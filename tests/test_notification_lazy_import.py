"""R20.10 ``web_ui_routes/notification.py`` 通知模块惰性化锁定测试

背景
----
R20.4–R20.9 累积优化后，Web UI 子进程 cold-start 仍有 ~65 ms 净浪费来自
``web_ui_routes/notification.py`` 顶层强制 import 的两条路径：

* ``from notification_manager import ...`` 拖入 ``pydantic`` 校验器、
  ``concurrent.futures`` thread-pool、``config_manager`` 等共 ~43 ms
* ``from notification_providers import BarkNotificationProvider`` 拖入
  ``httpx`` (含 ``httpcore`` / ``httpcore._sync.connection_pool`` /
  ``rich.console``) 共 ~22 ms

而事实是：Web UI 子进程的高频路径（``/api/tasks`` 轮询、``/api/config``
轮询、``/api/events`` SSE、``/api/submit`` 反馈、``/api/health``）**永远
不接触通知模块**；通知模块仅在 4 条用户主动触发的低频路由中使用：
``test_bark_notification`` / ``notify_new_tasks`` / ``update_notification_config``
（``get_notification_config`` 等只读端点完全不依赖通知模块）。

R20.10 修复：

1. 模块顶层把 ``try: from notification_manager import ...; except ImportError``
   改成 ``find_spec`` 探测——后者只走 ``sys.path`` 扫描而不执行模块顶层语句，
   实测开销 0.04 ms（vs eager import 65 ms），收益比 ~1600×。
2. 4 条使用点函数体内做 lazy import；首次实际触发该路由时一次性付 ~65 ms
   并被 ``sys.modules`` 缓存，之后所有调用 0 开销。
3. ``NOTIFICATION_AVAILABLE`` 语义保持不变：``True`` 表示模块可发现；
   graceful degradation 契约不动。

实测：``import web_ui`` 中位数 192 ms → 156 ms（-36 ms / -19%）；
累计相对 R19 baseline 425 ms → 156 ms（**-269 ms / -63%**）。

本测试套件锁定 5 条不变量：

1. **解耦不变量**（fresh interpreter 子进程独立验证）
   - 加载 ``web_ui`` 时**不**触发 ``notification_manager`` 加载
   - 加载 ``web_ui`` 时**不**触发 ``notification_providers`` 加载
   - 加载 ``web_ui`` 时**不**触发 ``httpx`` 加载（最大单点开销 ~22 ms）

2. **NOTIFICATION_AVAILABLE 探测正确性**
   - 标准开发环境下应为 ``True``（两个模块都能 ``find_spec``）
   - ``find_spec`` 不应触发模块加载

3. **行为零回归**
   - ``test_bark_notification`` 在 NOTIFICATION_AVAILABLE=False 时仍正确返回 500
     （而非 NameError——因为 lazy import 在 if NOTIFICATION_AVAILABLE 后执行）
   - ``notify_new_tasks`` / ``update_notification_config`` 同样 graceful degradation

4. **源文本不变量**
   - ``web_ui_routes/notification.py`` 顶层**不**含 ``from notification_manager import``
   - ``web_ui_routes/notification.py`` 顶层**不**含 ``from notification_providers import``
   - 顶层必须包含 ``find_spec`` 探测（防止有人误把 lazy 化复原）
   - 4 个使用点函数体内必须有 ``from notification_manager`` / ``from notification_providers``

5. **lazy import 路径正确性**
   - ``test_bark_notification`` 函数体首次执行时拉入 notification_manager + notification_providers
   - 后续调用 ``sys.modules`` 复用、不重复加载（Python import 缓存语义）

设计决策：
* 所有 fresh-interpreter 检查必须放进 ``subprocess.run([sys.executable, '-c', ...])``，
  因为本测试 runner 自己的进程早已 import 过 notification_manager（任何时候 server.py
  / server_feedback.py 被加载都会走完整链），单进程内 ``'notification_manager'
  in sys.modules`` 总是 True，无法验证 cold-start 收益。
"""

from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


# ═══════════════════════════════════════════════════════════════════════════
# 1. 解耦不变量：fresh interpreter 子进程独立验证
# ═══════════════════════════════════════════════════════════════════════════
class TestImportDecoupling(unittest.TestCase):
    """fresh interpreter 中 import web_ui_routes.notification 不应触发 notification_manager / notification_providers / httpx 加载"""

    def _run_in_subprocess(self, code: str) -> str:
        result = subprocess.run(
            [sys.executable, "-c", code],
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
            check=True,
            timeout=30,
        )
        return result.stdout.strip()

    def test_loading_notification_route_does_not_load_notification_manager(
        self,
    ) -> None:
        out = self._run_in_subprocess(
            "import sys\n"
            "from web_ui_routes import notification  # noqa: F401\n"
            "print('LOADED' if 'notification_manager' in sys.modules else 'NOT_LOADED')\n"
        )
        last = out.splitlines()[-1] if out else ""
        self.assertEqual(
            last,
            "NOT_LOADED",
            "import web_ui_routes.notification 不应触发 notification_manager 加载"
            "（这是 R20.10 节省 ~43ms 启动延迟的核心）",
        )

    def test_loading_notification_route_does_not_load_notification_providers(
        self,
    ) -> None:
        out = self._run_in_subprocess(
            "import sys\n"
            "from web_ui_routes import notification  # noqa: F401\n"
            "print('LOADED' if 'notification_providers' in sys.modules else 'NOT_LOADED')\n"
        )
        last = out.splitlines()[-1] if out else ""
        self.assertEqual(
            last,
            "NOT_LOADED",
            "import web_ui_routes.notification 不应触发 notification_providers 加载",
        )

    def test_loading_notification_route_does_not_load_httpx(self) -> None:
        """httpx 是 R20.10 节省的最大单点（~22ms）——通过 notification_providers 拖入"""
        out = self._run_in_subprocess(
            "import sys\n"
            "from web_ui_routes import notification  # noqa: F401\n"
            "print('LOADED' if 'httpx' in sys.modules else 'NOT_LOADED')\n"
        )
        last = out.splitlines()[-1] if out else ""
        self.assertEqual(
            last,
            "NOT_LOADED",
            "import web_ui_routes.notification 不应触发 httpx 加载——后者是"
            "通知模块依赖链中最重的单点（含 httpcore / connection_pool / rich.console）",
        )

    def test_loading_notification_providers_does_not_load_httpx(self) -> None:
        """导入 provider 模块本身不应加载 httpx；只有 Bark provider 首次使用才需要。"""
        out = self._run_in_subprocess(
            "import sys\n"
            "import notification_providers  # noqa: F401\n"
            "print('LOADED' if 'httpx' in sys.modules else 'NOT_LOADED')\n"
        )
        last = out.splitlines()[-1] if out else ""
        self.assertEqual(
            last,
            "NOT_LOADED",
            "import notification_providers 不应立刻加载 httpx；Web/Sound/System "
            "provider 不需要 HTTP transport，Bark 首次使用时再加载即可",
        )

    def test_bark_provider_first_use_loads_httpx(self) -> None:
        """访问 Bark provider 的 HTTP transport 时才真正加载 httpx。"""
        out = self._run_in_subprocess(
            "import sys\n"
            "from notification_manager import NotificationConfig\n"
            "from notification_providers import BarkNotificationProvider\n"
            "before = 'httpx' in sys.modules\n"
            "provider = BarkNotificationProvider(NotificationConfig())\n"
            "after = 'httpx' in sys.modules\n"
            "provider.close()\n"
            "print(f'BEFORE={before} AFTER={after}')\n"
        )
        last = out.splitlines()[-1] if out else ""
        self.assertEqual(last, "BEFORE=False AFTER=True")

    def test_loading_full_web_ui_does_not_load_notification_manager(self) -> None:
        """端到端验证：完整 import web_ui 也不应触发通知模块加载"""
        out = self._run_in_subprocess(
            "import sys\n"
            "import web_ui  # noqa: F401\n"
            "print('LOADED' if 'notification_manager' in sys.modules else 'NOT_LOADED')\n"
        )
        last = out.splitlines()[-1] if out else ""
        self.assertEqual(
            last,
            "NOT_LOADED",
            "import web_ui 不应触发 notification_manager 加载——这是 Web UI 子进程"
            "cold-start 节省 ~36ms（实测中位数）的端到端验证",
        )


# ═══════════════════════════════════════════════════════════════════════════
# 2. NOTIFICATION_AVAILABLE 探测正确性
# ═══════════════════════════════════════════════════════════════════════════
class TestNotificationAvailableDetection(unittest.TestCase):
    """find_spec 探测必须在不加载模块的前提下正确返回 True/False"""

    def test_notification_available_is_true_in_dev_environment(self) -> None:
        from web_ui_routes.notification import NOTIFICATION_AVAILABLE

        self.assertTrue(
            NOTIFICATION_AVAILABLE,
            "标准开发环境下 notification_manager + notification_providers"
            "都可发现，NOTIFICATION_AVAILABLE 必须为 True",
        )

    def test_find_spec_does_not_load_module(self) -> None:
        """find_spec 仅扫 sys.path，不执行模块顶层——在 fresh interpreter 中验证"""
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                "import sys\n"
                "from importlib.util import find_spec\n"
                "spec = find_spec('notification_manager')\n"
                "loaded = 'notification_manager' in sys.modules\n"
                "print(f'spec={spec is not None} loaded={loaded}')\n",
            ],
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
            check=True,
            timeout=30,
        )
        last = result.stdout.strip().splitlines()[-1]
        self.assertEqual(
            last,
            "spec=True loaded=False",
            "find_spec 必须能找到模块但不触发加载——这是 R20.10 节省的全部技术核心",
        )


# ═══════════════════════════════════════════════════════════════════════════
# 3. 行为零回归：NOTIFICATION_AVAILABLE=False 路径仍 graceful
# ═══════════════════════════════════════════════════════════════════════════
class TestGracefulDegradationParity(unittest.TestCase):
    """通知模块不可用时各路由必须仍能正确响应（不抛 NameError）

    实现细节：路由处理函数中 ``if not NOTIFICATION_AVAILABLE:`` 是闭包查找
    ``web_ui_routes.notification`` 模块的全局变量，所以测试要在 ``client.post``
    调用**期间**保持 patch 生效；不能在 setup 时 patch 完就退出 with 块。
    """

    @classmethod
    def setUpClass(cls) -> None:
        from web_ui import WebFeedbackUI

        cls._ui = WebFeedbackUI(
            prompt="lazy-import-test",
            predefined_options=["A", "B"],
            task_id="r20-10-test",
            port=18999,
        )
        cls._client = cls._ui.app.test_client()
        # 持有模块对象以便测试中临时翻转 NOTIFICATION_AVAILABLE
        cls._notif_module = __import__(
            "web_ui_routes.notification", fromlist=["NOTIFICATION_AVAILABLE"]
        )

    def _set_notification_available(self, value: bool) -> bool:
        """临时翻转 NOTIFICATION_AVAILABLE，返回原值供 finally 恢复用。

        ty 类型检查器对 ``ModuleType.NOTIFICATION_AVAILABLE`` 的赋值发出
        ``invalid-assignment`` 警告（因为 ModuleType 没有静态 attribute schema）；
        通过 ``# type: ignore[invalid-assignment]`` 显式标注我们知道这是动态
        模块属性翻转——这是 Python 测试隔离的合法手段。
        """
        original = bool(self._notif_module.NOTIFICATION_AVAILABLE)
        self._notif_module.NOTIFICATION_AVAILABLE = value  # ty: ignore[unresolved-attribute]
        return original

    def _restore_notification_available(self, value: bool) -> None:
        self._notif_module.NOTIFICATION_AVAILABLE = value  # ty: ignore[unresolved-attribute]

    def test_test_bark_returns_500_when_notification_unavailable(self) -> None:
        original = self._set_notification_available(False)
        try:
            rv = self._client.post("/api/test-bark", json={"bark_device_key": "abc"})
            self.assertEqual(
                rv.status_code,
                500,
                "NOTIFICATION_AVAILABLE=False 时 /api/test-bark 必须返回 500"
                "（contract 是 ImportError → 500），不能因 lazy import 顺序错位"
                "而冒出 NameError 等内部异常",
            )
            body = rv.get_json()
            self.assertEqual(body["status"], "error")
        finally:
            self._restore_notification_available(original)

    def test_notify_new_tasks_returns_skipped_when_notification_unavailable(
        self,
    ) -> None:
        original = self._set_notification_available(False)
        try:
            rv = self._client.post(
                "/api/notify-new-tasks", json={"taskIds": ["t1"], "count": 1}
            )
            self.assertEqual(rv.status_code, 200)
            body = rv.get_json()
            self.assertEqual(
                body["status"],
                "skipped",
                "NOTIFICATION_AVAILABLE=False 时该端点必须 graceful skip"
                "（注释里明确说外部第三方客户端兼容保留）",
            )
        finally:
            self._restore_notification_available(original)

    def test_update_notification_config_returns_500_when_notification_unavailable(
        self,
    ) -> None:
        original = self._set_notification_available(False)
        try:
            rv = self._client.post(
                "/api/update-notification-config", json={"enabled": True}
            )
            self.assertEqual(
                rv.status_code,
                500,
                "NOTIFICATION_AVAILABLE=False 时配置写入必须 graceful 失败",
            )
        finally:
            self._restore_notification_available(original)


# ═══════════════════════════════════════════════════════════════════════════
# 4. 源文本不变量：禁止把 lazy 化"复原"成顶层 eager import
# ═══════════════════════════════════════════════════════════════════════════
class TestSourceTextInvariants(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.src = (PROJECT_ROOT / "web_ui_routes" / "notification.py").read_text(
            encoding="utf-8"
        )

    def test_no_module_level_notification_manager_import(self) -> None:
        """source-text 层禁止把 notification_manager 拖回模块顶部 eager import"""
        # 顶层 import 形式：行首 from / 行首 import（防止 docstring 里的字串误判）
        for forbidden in (
            "\nfrom notification_manager import",
            "\nimport notification_manager",
        ):
            # 容忍 docstring 里出现的提示文本（比如开头的"注意"段落），仅检查
            # 是否存在带前导换行 + 行首关键字的真实 Python 顶层 import 语句。
            # 这里通过简单子串检查就能过滤——docstring 内的叙述都带缩进或不在行首。
            self.assertNotIn(
                forbidden,
                self.src,
                f"web_ui_routes/notification.py 不允许 {forbidden!r}——"
                "这会破坏 R20.10 lazy 化，重新拖入 ~43ms 启动延迟",
            )

    def test_no_module_level_notification_providers_import(self) -> None:
        for forbidden in (
            "\nfrom notification_providers import",
            "\nimport notification_providers",
        ):
            self.assertNotIn(
                forbidden,
                self.src,
                f"web_ui_routes/notification.py 不允许 {forbidden!r}——"
                "这会重新拖入 httpx ~22ms 启动延迟",
            )

    def test_has_find_spec_detection(self) -> None:
        """顶层必须用 find_spec 探测，而非 try-import"""
        self.assertIn(
            "from importlib.util import find_spec",
            self.src,
            "web_ui_routes/notification.py 必须使用 find_spec 探测可用性",
        )
        self.assertIn(
            'find_spec("notification_manager")',
            self.src,
            "find_spec 必须探测 notification_manager",
        )
        self.assertIn(
            'find_spec("notification_providers")',
            self.src,
            "find_spec 必须探测 notification_providers",
        )

    def test_notification_available_constant_exists(self) -> None:
        """探测结果必须暴露给 4 个使用路由（NOTIFICATION_AVAILABLE 是 contract）"""
        self.assertIn(
            "NOTIFICATION_AVAILABLE = (",
            self.src,
            "NOTIFICATION_AVAILABLE 必须保留作为 graceful degradation 契约",
        )

    def test_first_touch_hoist_helpers_exist(self) -> None:
        """first-touch hoist 模式：必须有 _ensure_notification_loaded /
        _ensure_bark_provider_loaded 两个 helper 函数"""
        self.assertIn(
            "def _ensure_notification_loaded(",
            self.src,
            "_ensure_notification_loaded helper 必须存在——R20.10 first-touch "
            "hoist 模式的核心，提供 mock-friendly 的延迟加载接口",
        )
        self.assertIn(
            "def _ensure_bark_provider_loaded(",
            self.src,
            "_ensure_bark_provider_loaded helper 必须存在",
        )

    def test_module_level_placeholders_exist(self) -> None:
        """模块顶层必须有 5 个 None 占位（mock.patch 兼容性 + first-touch hoist 起点）"""
        for placeholder in (
            "notification_manager: Any = None",
            "NotificationEvent: Any = None",
            "NotificationTrigger: Any = None",
            "NotificationType: Any = None",
            "BarkNotificationProvider: Any = None",
        ):
            self.assertIn(
                placeholder,
                self.src,
                f"模块顶层必须有占位 {placeholder!r}——这是 mock.patch 能找到 "
                "attribute 的前提（否则 @patch 抛 AttributeError）",
            )

    def test_lazy_load_in_test_bark_route(self) -> None:
        """test_bark_notification 函数体内必须调用 _ensure_*_loaded()"""
        marker = "def test_bark_notification("
        idx = self.src.find(marker)
        self.assertGreater(idx, 0, "未找到 test_bark_notification 函数定义")
        window = self.src[idx : idx + 3500]
        self.assertIn(
            "_ensure_notification_loaded()",
            window,
            "test_bark_notification 函数体内必须调用 _ensure_notification_loaded()"
            " 触发 first-touch hoist",
        )
        self.assertIn(
            "_ensure_bark_provider_loaded()",
            window,
            "test_bark_notification 函数体内必须调用 _ensure_bark_provider_loaded()"
            " 触发 BarkNotificationProvider first-touch hoist",
        )

    def test_lazy_load_in_notify_new_tasks_route(self) -> None:
        marker = "def notify_new_tasks("
        idx = self.src.find(marker)
        self.assertGreater(idx, 0, "未找到 notify_new_tasks 函数定义")
        window = self.src[idx : idx + 3500]
        self.assertIn(
            "_ensure_notification_loaded()",
            window,
            "notify_new_tasks 函数体内必须调用 _ensure_notification_loaded()",
        )

    def test_lazy_load_in_update_notification_config_route(self) -> None:
        marker = "def update_notification_config("
        idx = self.src.find(marker)
        self.assertGreater(idx, 0, "未找到 update_notification_config 函数定义")
        # update_notification_config 函数体超长（18 个 field_specs）；放宽窗口
        window = self.src[idx : idx + 8000]
        self.assertIn(
            "_ensure_notification_loaded()",
            window,
            "update_notification_config 函数体内必须调用 _ensure_notification_loaded()",
        )


# ═══════════════════════════════════════════════════════════════════════════
# 5. lazy import 缓存语义：首次触发后 sys.modules 复用
# ═══════════════════════════════════════════════════════════════════════════
class TestLazyImportCachingSemantics(unittest.TestCase):
    """Python 自带 sys.modules 缓存即可——本测试只验证 contract 不被破坏"""

    def test_first_test_bark_call_loads_notification_manager(self) -> None:
        """通过 fresh interpreter 验证：调用 /api/test-bark 后 notification_manager 进入 sys.modules"""
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                "import sys\n"
                "import web_ui\n"
                "before = 'notification_manager' in sys.modules\n"
                "ui = web_ui.WebFeedbackUI(prompt='lazy-test', task_id='lazy-test', port=18998)\n"
                "client = ui.app.test_client()\n"
                "rv = client.post('/api/test-bark', json={'bark_device_key': 'fake-key-for-test'})\n"
                "after = 'notification_manager' in sys.modules\n"
                "print(f'BEFORE={before} AFTER={after}')\n",
            ],
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
            timeout=60,
        )
        self.assertEqual(
            result.returncode,
            0,
            f"subprocess 执行失败: stdout={result.stdout!r} stderr={result.stderr!r}",
        )
        last = result.stdout.strip().splitlines()[-1]
        self.assertEqual(
            last,
            "BEFORE=False AFTER=True",
            "调用 /api/test-bark 之前 notification_manager 不在 sys.modules"
            "（lazy 还没触发），调用之后必须在 sys.modules（lazy import 真的执行了）",
        )


if __name__ == "__main__":
    unittest.main()
