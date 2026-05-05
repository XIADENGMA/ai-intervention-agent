"""R25.2 性能不变量：``httpx`` 顶级 import 必须延迟到使用点。

背景
====

R25.2 把 ``service_manager`` 与 ``server_feedback`` 顶层的 ``import httpx`` 推迟到
函数体内执行（搭配 ``TYPE_CHECKING`` block 保留类型注解给静态检查器）。配套的
``service_manager`` 通知系统加载（``notification_manager`` 单例 + ``notification_providers``）
也改成 ``_ensure_notification_system_loaded()`` 触发的懒加载。

收益
====

- ``service_manager`` 模块单独 cold-start：~148 ms → ~71 ms（**省 ~77 ms**）。
- 主要节省来源：``httpx`` (~55 ms) + ``httpcore`` + ``h11`` + ``anyio`` transport 栈，
  以及 ``notification_manager.NotificationManager()`` 单例构造（线程池初始化 + 磁盘
  config I/O，约 10-20 ms）。
- ``server.py`` 仍然吃 ~55 ms httpx 加载，但那是 ``mcp.shared.session`` 上游 import
  带进来的，不在我们控制范围内——本次改动等于「在 fastmcp 之外把这条路径断掉」。

不变量
======

本测试组验证以下静态/动态契约，防止以后误把顶层 ``import httpx`` 加回去（哪怕只是
看起来「无所谓」的 cleanup PR 也会被拦下来，因为这意味着 +55 ms 的 cold-start
regression）。

1. **静态源码检查**（``inspect.getsource``）：
   - ``service_manager.py`` 顶层不能裸 ``import httpx``，必须放在 ``if TYPE_CHECKING:`` 块。
   - ``server_feedback.py`` 同上。
   - 顶层不能 ``from notification_manager import notification_manager``（会触发
     单例构造 + 通知系统懒加载链路）。
   - 顶层不能 ``from notification_providers import initialize_notification_system``。

2. **运行时不变量**（fresh subprocess）：
   - ``import service_manager`` 不应让 ``httpx`` 进入 ``sys.modules``。
   - ``import service_manager`` 不应让 ``notification_manager`` 进入 ``sys.modules``。
   - ``import service_manager`` 不应让 ``notification_providers`` 进入 ``sys.modules``。

3. **行为契约**：``_ensure_notification_system_loaded()`` 的幂等性——首次调用加载，
   后续调用直接返回缓存引用，第二次调用必须 < 1 ms。

边界
====

- ``server_feedback`` 在 fastmcp 这条路径下，``import httpx`` 仍然会被
  ``mcp.shared.session`` 触发——所以我们**不**断言 ``import server_feedback`` 之后
  ``httpx`` 不在 ``sys.modules``，因为这个断言会被无关的上游变更打破。
- 但 ``import service_manager`` 是干净路径（不依赖 fastmcp），所以这条断言可以
  长期作为性能 watchdog。
"""

from __future__ import annotations

import inspect
import re
import subprocess
import sys
import time
import unittest

import server_feedback
import service_manager


class TestServiceManagerLazyHttpxStatic(unittest.TestCase):
    """``service_manager`` 顶层不能再 ``import httpx``——必须走 TYPE_CHECKING。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.source = inspect.getsource(service_manager)

    def test_no_bare_top_level_import_httpx(self) -> None:
        """模块顶层不能有缩进 0 的 ``import httpx``——否则等于 R25.2 被回退。"""
        # `^import httpx\b` 在 MULTILINE 下匹配行首裸 import
        bare_match = re.search(r"^import httpx\b", self.source, re.MULTILINE)
        self.assertIsNone(
            bare_match,
            "R25.2 性能保护：service_manager 顶层禁止 ``import httpx``，"
            "必须放进 ``if TYPE_CHECKING:`` 块或函数体内（cold-start +55 ms regression）",
        )

    def test_type_checking_block_imports_httpx(self) -> None:
        """``TYPE_CHECKING`` 守护块里仍要 ``import httpx``，让 ty / mypy 能解析类型注解。"""
        type_checking_pattern = re.compile(
            r"if TYPE_CHECKING:\s*\n(?:\s+.*\n)*?\s+import httpx\b",
            re.MULTILINE,
        )
        self.assertIsNotNone(
            type_checking_pattern.search(self.source),
            "service_manager 必须在 ``if TYPE_CHECKING:`` 块里 ``import httpx``，"
            "否则 ty 无法解析 ``httpx.AsyncClient`` 等类型注解",
        )

    def test_get_async_client_has_local_import(self) -> None:
        """``get_async_client`` 函数体首行必须本地 ``import httpx``。"""
        match = re.search(
            r"def get_async_client\(.*?\) -> .*?\n(?:\s+\".*?\"\"\".*?\"\"\"\s*\n)?(\s+import httpx\b)",
            self.source,
            re.DOTALL,
        )
        self.assertIsNotNone(
            match,
            "get_async_client 函数体必须本地 ``import httpx``——"
            "运行时 ``httpx.AsyncClient`` 解析依赖此 import",
        )

    def test_get_sync_client_has_local_import(self) -> None:
        """``get_sync_client`` 函数体首行必须本地 ``import httpx``。"""
        match = re.search(
            r"def get_sync_client\(.*?\) -> .*?\n(?:\s+\".*?\"\"\".*?\"\"\"\s*\n)?(\s+import httpx\b)",
            self.source,
            re.DOTALL,
        )
        self.assertIsNotNone(
            match,
            "get_sync_client 函数体必须本地 ``import httpx``——"
            "运行时 ``httpx.Client`` 解析依赖此 import",
        )

    def test_no_top_level_notification_import(self) -> None:
        """模块顶层不能 ``from notification_manager import notification_manager``。

        如果允许，``NotificationManager()`` 单例会在 import 期就被构造（线程池 +
        config I/O），并通过 ``_update_bark_provider`` 透过 ``notification_providers``
        把 httpx 拖回来。
        """
        bad_patterns = [
            r"^from notification_manager import notification_manager\b",
            r"^from notification_providers import initialize_notification_system\b",
        ]
        for pat in bad_patterns:
            with self.subTest(pattern=pat):
                self.assertIsNone(
                    re.search(pat, self.source, re.MULTILINE),
                    f"R25.2 保护：service_manager 顶层禁止 ``{pat}``，"
                    "应改为 ``_ensure_notification_system_loaded()`` 懒加载",
                )

    def test_ensure_notification_system_loaded_exists(self) -> None:
        """必须有 ``_ensure_notification_system_loaded()`` 懒加载入口。"""
        self.assertTrue(
            hasattr(service_manager, "_ensure_notification_system_loaded"),
            "service_manager 必须暴露 ``_ensure_notification_system_loaded()`` 用作懒加载入口",
        )
        self.assertTrue(
            callable(service_manager._ensure_notification_system_loaded),
            "_ensure_notification_system_loaded 必须可调用",
        )


class TestServerFeedbackLazyHttpxStatic(unittest.TestCase):
    """``server_feedback`` 顶层不能裸 ``import httpx``。

    与 ``service_manager`` 不同，``server_feedback`` **没有**模块级 ``httpx.X``
    类型注解（``except httpx.HTTPError`` 与 ``httpx.Timeout(...)`` 都在函数体内），
    因此不需要 ``TYPE_CHECKING`` 守护块——三个使用函数（``_sse_listener`` /
    ``launch_feedback_ui`` / ``interactive_feedback``）直接函数体首行 ``import httpx``
    即可满足 ty 与运行时双方的需求。
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.source = inspect.getsource(server_feedback)

    def test_no_bare_top_level_import_httpx(self) -> None:
        bare_match = re.search(r"^import httpx\b", self.source, re.MULTILINE)
        self.assertIsNone(
            bare_match,
            "R25.2 性能保护：server_feedback 顶层禁止 ``import httpx``",
        )

    def test_use_sites_have_local_import(self) -> None:
        """``launch_feedback_ui`` / ``interactive_feedback`` 函数体内必须本地 ``import httpx``。

        ``_sse_listener`` 的 import 由 ``test_top_module_imports_httpx``
        （``test_sse_listener_pooled_client_r23_1.py``）单独验证。
        """
        for func_name in ("launch_feedback_ui", "interactive_feedback"):
            with self.subTest(func=func_name):
                # 匹配函数体（直到下一条 module-level def 或文件结束）
                func_match = re.search(
                    rf"^(?:async )?def {func_name}\(.*?(?=\n(?:async )?def |\Z)",
                    self.source,
                    re.MULTILINE | re.DOTALL,
                )
                self.assertIsNotNone(
                    func_match,
                    f"未找到 {func_name} 函数体——测试需要更新",
                )
                if func_match is not None:
                    self.assertIn(
                        "import httpx",
                        func_match.group(0),
                        f"R25.2: {func_name} 函数体必须本地 ``import httpx`` 才能引用 "
                        "``httpx.HTTPError`` / ``httpx.Timeout``",
                    )


class TestServiceManagerLazyHttpxRuntime(unittest.TestCase):
    """``import service_manager`` 在干净 subprocess 里不应触发 httpx 加载。"""

    def _run_in_subprocess(self, code: str) -> str:
        """在干净 Python subprocess 里跑 ``code``，返回 stdout。"""
        result = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
            cwd=str(__import__("pathlib").Path(service_manager.__file__).parent),
            check=True,
        )
        return result.stdout

    def test_import_does_not_load_httpx(self) -> None:
        """干净 ``import service_manager`` 后 ``httpx`` 不应在 ``sys.modules``。"""
        stdout = self._run_in_subprocess(
            'import sys; import service_manager; print("httpx" in sys.modules)'
        )
        self.assertEqual(
            stdout.strip(),
            "False",
            "R25.2 性能保护：``import service_manager`` 不应触发 httpx 加载（"
            "若失败请检查是否有人重新加了顶层 ``import httpx`` 或顶层加了拉 httpx 的 import）",
        )

    def test_import_does_not_load_httpcore_h11(self) -> None:
        """同时 ``httpcore`` / ``h11`` 也不应被拉进来——它们都是 httpx 的依赖。"""
        stdout = self._run_in_subprocess(
            "import sys; import service_manager; "
            'print("httpcore" in sys.modules, "h11" in sys.modules)'
        )
        self.assertEqual(
            stdout.strip(),
            "False False",
            "R25.2 性能保护：``import service_manager`` 不应触发 httpcore/h11 加载",
        )

    def test_import_does_not_load_notification_manager(self) -> None:
        """``import service_manager`` 不应触发 ``notification_manager`` 单例构造。"""
        stdout = self._run_in_subprocess(
            "import sys; import service_manager; "
            'print("notification_manager" in sys.modules)'
        )
        self.assertEqual(
            stdout.strip(),
            "False",
            "R25.2 性能保护：``import service_manager`` 不应触发 notification_manager 加载",
        )

    def test_import_does_not_load_notification_providers(self) -> None:
        """``import service_manager`` 不应让 ``notification_providers`` 进入 sys.modules。"""
        stdout = self._run_in_subprocess(
            "import sys; import service_manager; "
            'print("notification_providers" in sys.modules)'
        )
        self.assertEqual(
            stdout.strip(),
            "False",
            "R25.2 性能保护：``import service_manager`` 不应触发 notification_providers 加载",
        )


class TestEnsureNotificationSystemLoadedBehavior(unittest.TestCase):
    """``_ensure_notification_system_loaded`` 行为契约：幂等 + 缓存命中。"""

    def test_idempotent_returns_same_references(self) -> None:
        """连续调用必须返回同一对引用，状态在模块级保持。"""
        nm1, init1 = service_manager._ensure_notification_system_loaded()
        nm2, init2 = service_manager._ensure_notification_system_loaded()
        self.assertIs(nm1, nm2, "notification_manager 单例引用必须稳定")
        self.assertIs(init1, init2, "initialize_notification_system 引用必须稳定")

    def test_second_call_is_fast_cache_hit(self) -> None:
        """第二次调用必须 < 1 ms（cache hit），证明确实有 ``_notification_initialized`` 短路。"""
        # 触发首次加载（可能很慢，~50-100 ms 取决于通知系统加载耗时）
        service_manager._ensure_notification_system_loaded()

        t0 = time.perf_counter()
        for _ in range(1000):
            service_manager._ensure_notification_system_loaded()
        elapsed = time.perf_counter() - t0
        per_call_us = (elapsed / 1000) * 1_000_000

        self.assertLess(
            per_call_us,
            10.0,
            f"R25.2 缓存命中应 < 10 µs/call，实测 {per_call_us:.2f} µs；"
            "如果回退到非缓存路径，cold-start 收益会被吞掉",
        )

    def test_notification_available_flag_reflects_state(self) -> None:
        """加载成功后 ``NOTIFICATION_AVAILABLE`` 必须反映真实状态。"""
        nm, init_fn = service_manager._ensure_notification_system_loaded()
        if nm is not None and init_fn is not None:
            self.assertTrue(
                service_manager.NOTIFICATION_AVAILABLE,
                "懒加载成功后 NOTIFICATION_AVAILABLE 必须翻成 True",
            )
        else:
            self.assertFalse(
                service_manager.NOTIFICATION_AVAILABLE,
                "懒加载失败后 NOTIFICATION_AVAILABLE 必须是 False",
            )


if __name__ == "__main__":
    unittest.main()
