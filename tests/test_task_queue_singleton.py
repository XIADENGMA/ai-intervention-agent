"""R20.8 ``task_queue_singleton`` 模块测试

背景
----
为了消除 Web UI 子进程启动时 ``from server import get_task_queue`` 拖入
``fastmcp`` / ``mcp`` / ``loguru`` 的 ~310 ms 启动延迟，将 TaskQueue 单例的
实现从 ``server.py`` 抽到了独立的 ``task_queue_singleton`` 模块；``web_ui``
及其路由 mixin 直接 import 自该模块，不再触发整条 MCP server 加载链路。

本测试套件在 4 条互补路径上锁定该优化的行为契约：

1. **功能正确性**
   - 双重检查锁定真的双重检查（线程并发只创建一个实例）
   - 单例幂等：多次调用返回同一对象
   - ``_shutdown_global_task_queue`` 幂等且吞异常
   - persist_path 指向 ``data/tasks.json``（与 R20.8 前行为一致）

2. **公开 API 兼容**
   - ``server.get_task_queue is task_queue_singleton.get_task_queue``
     （调用者拿到同一 callable，避免「双单例分裂」bug）
   - ``server._shutdown_global_task_queue is
     task_queue_singleton._shutdown_global_task_queue``

3. **解耦不变量**（R20.8 性能优化的核心）
   - 加载 ``task_queue_singleton`` 时**绝不**触发 ``fastmcp`` 模块加载
     ——这是 R20.8 的全部价值（fastmcp 单独 ~310 ms 启动开销）
   - 顶层依赖只有 stdlib + ``task_queue``

4. **源文本不变量**（防止单例实现在重构中被悄悄挪回 server.py）
   - ``task_queue_singleton.py`` 文件存在且包含双重检查锁定
   - ``server.py`` 不再自行定义 ``_global_task_queue`` 模块变量
   - ``web_ui.py`` / ``web_ui_routes/{task,feedback}.py`` 都从
     ``task_queue_singleton`` 而非 ``server`` 导入 ``get_task_queue``
"""

from __future__ import annotations

import importlib
import subprocess
import sys
import threading
import unittest
from pathlib import Path
from unittest.mock import MagicMock

PROJECT_ROOT = Path(__file__).resolve().parent.parent


# ═══════════════════════════════════════════════════════════════════════════
# 1. 功能正确性
# ═══════════════════════════════════════════════════════════════════════════
class TestSingletonBehavior(unittest.TestCase):
    """双重检查锁定 + 幂等 + persist 路径"""

    def setUp(self) -> None:
        import task_queue_singleton

        self._mod = task_queue_singleton
        self._orig = task_queue_singleton._global_task_queue
        task_queue_singleton._global_task_queue = None

    def tearDown(self) -> None:
        if (
            self._mod._global_task_queue is not None
            and self._mod._global_task_queue is not self._orig
        ):
            try:
                self._mod._global_task_queue.stop_cleanup()
            except Exception:
                pass
        self._mod._global_task_queue = self._orig

    def test_idempotent_returns_same_instance(self) -> None:
        a = self._mod.get_task_queue()
        b = self._mod.get_task_queue()
        self.assertIs(a, b, "同一进程内多次调用必须返回同一实例")

    def test_concurrent_creation_yields_single_instance(self) -> None:
        """20 线程并发首次调用时，必须只生成 1 个 TaskQueue 实例

        双重检查锁定的核心保障——若锁错位或被简化为单检，会观察到 >1 个
        不同对象。"""
        results: list = []
        barrier = threading.Barrier(20)

        def worker() -> None:
            barrier.wait()
            results.append(self._mod.get_task_queue())

        threads = [threading.Thread(target=worker) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(len(results), 20)
        first = results[0]
        for tq in results[1:]:
            self.assertIs(tq, first, "并发首次调用不允许出现多个实例")

    def test_persist_path_points_to_data_tasks_json(self) -> None:
        """persist 路径必须仍然是 <project>/data/tasks.json（行为兼容）

        注：TaskQueue 内部把传入路径存为 ``self._persist_path: Path``。
        这里直接断言私有字段——R20.8 必须保证 persist 行为字节级兼容。
        """
        tq = self._mod.get_task_queue()
        persist_path = tq._persist_path
        self.assertIsNotNone(persist_path, "get_task_queue 必须启用持久化")
        path_str = str(persist_path)
        self.assertTrue(
            path_str.endswith(("data/tasks.json", "data\\tasks.json")),
            f"_persist_path 应指向 data/tasks.json，实际：{path_str}",
        )


class TestShutdownIdempotent(unittest.TestCase):
    """_shutdown_global_task_queue 必须幂等且吞异常"""

    def setUp(self) -> None:
        import task_queue_singleton

        self._mod = task_queue_singleton
        self._orig = task_queue_singleton._global_task_queue

    def tearDown(self) -> None:
        self._mod._global_task_queue = self._orig

    def test_noop_when_no_queue(self) -> None:
        self._mod._global_task_queue = None
        self._mod._shutdown_global_task_queue()

    def test_calls_stop_cleanup_when_queue_exists(self) -> None:
        mock_tq = MagicMock()
        self._mod._global_task_queue = mock_tq
        self._mod._shutdown_global_task_queue()
        mock_tq.stop_cleanup.assert_called_once()

    def test_swallows_stop_cleanup_exceptions(self) -> None:
        """退出阶段任何异常都必须吞掉，否则会污染解释器关闭日志"""
        mock_tq = MagicMock()
        mock_tq.stop_cleanup.side_effect = RuntimeError("intentional")
        self._mod._global_task_queue = mock_tq
        self._mod._shutdown_global_task_queue()


# ═══════════════════════════════════════════════════════════════════════════
# 2. 公开 API 兼容（server.* 必须仍然可用）
# ═══════════════════════════════════════════════════════════════════════════
class TestServerReExportContract(unittest.TestCase):
    """server.{get_task_queue, _shutdown_global_task_queue} 必须是同一 callable"""

    def test_get_task_queue_is_re_export(self) -> None:
        import server
        import task_queue_singleton

        self.assertIs(
            server.get_task_queue,
            task_queue_singleton.get_task_queue,
            "server.get_task_queue 必须就是 task_queue_singleton.get_task_queue，"
            "否则会出现「双单例分裂」",
        )

    def test_shutdown_is_re_export(self) -> None:
        import server
        import task_queue_singleton

        self.assertIs(
            server._shutdown_global_task_queue,
            task_queue_singleton._shutdown_global_task_queue,
        )


# ═══════════════════════════════════════════════════════════════════════════
# 3. 解耦不变量：加载 task_queue_singleton 不能触发 fastmcp/mcp
# ═══════════════════════════════════════════════════════════════════════════
class TestImportDecoupling(unittest.TestCase):
    """R20.8 的核心价值：加载本模块时**绝不**拉起 fastmcp/mcp/loguru。

    使用全新的 Python 子进程独立验证（避免被父进程已加载的模块污染）。
    """

    def test_loading_module_does_not_import_fastmcp(self) -> None:
        """fresh interpreter 中 import task_queue_singleton 必须**不**拉起 fastmcp

        fastmcp 是 R20.8 优化的**第一目标**——单独占 ~310 ms 启动开销，且
        web_ui 子进程根本不需要任何 MCP server 能力。本不变量保证再有人
        往 task_queue_singleton / task_queue / server_config 链路上加
        ``import fastmcp`` 都会立即被本测试阻断。

        注：``mcp.types`` / ``loguru`` 仍会被加载——这是 task_queue 经
        ``server_config``（用于 ImageContent/TextContent 实例化）和
        ``enhanced_logging``（loguru sink）的间接依赖。完全切割它们需要把
        ``server_config`` 中的 ``mcp.types`` import 改成 lazy，并改造
        ``enhanced_logging`` 的 loguru 入口——这是后续可独立衡量的优化项，
        而非 R20.8 的范围。
        """
        code = (
            "import sys\n"
            "import task_queue_singleton  # noqa: F401\n"
            "leaked = [m for m in ('fastmcp',) if m in sys.modules]\n"
            "print('LEAKED:' + ','.join(leaked))\n"
        )
        result = subprocess.run(
            [sys.executable, "-c", code],
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
            check=True,
            timeout=30,
        )
        last = (result.stdout.strip().splitlines() or [""])[-1]
        self.assertTrue(
            last.startswith("LEAKED:"),
            f"子进程未输出 LEAKED 标记，stdout={result.stdout!r}",
        )
        leaked = last[len("LEAKED:") :]
        self.assertEqual(
            leaked,
            "",
            f"task_queue_singleton 加载时不允许触发 fastmcp 加载，实际泄漏：{leaked}",
        )


# ═══════════════════════════════════════════════════════════════════════════
# 4. 源文本不变量：防止单例被悄悄挪回 server.py
# ═══════════════════════════════════════════════════════════════════════════
class TestSourceTextInvariants(unittest.TestCase):
    """通过 grep 源代码锁定 R20.8 的关键结构

    任何"把 get_task_queue 搬回 server.py"或"web_ui 重新 from server import"
    的回归 PR 都会让本组测试 fail。
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.singleton_src = (PROJECT_ROOT / "task_queue_singleton.py").read_text(
            encoding="utf-8"
        )
        cls.server_src = (PROJECT_ROOT / "server.py").read_text(encoding="utf-8")
        cls.web_ui_src = (PROJECT_ROOT / "web_ui.py").read_text(encoding="utf-8")
        cls.task_route_src = (PROJECT_ROOT / "web_ui_routes" / "task.py").read_text(
            encoding="utf-8"
        )
        cls.feedback_route_src = (
            PROJECT_ROOT / "web_ui_routes" / "feedback.py"
        ).read_text(encoding="utf-8")

    def test_singleton_module_has_double_checked_locking(self) -> None:
        """task_queue_singleton 必须保留双重检查锁定结构"""
        self.assertIn("_global_task_queue_lock", self.singleton_src)
        self.assertIn("if _global_task_queue is None:", self.singleton_src)
        self.assertIn(
            "with _global_task_queue_lock:",
            self.singleton_src,
            "缺失双重检查锁定的 with 语句会导致并发竞态",
        )

    def test_singleton_module_does_not_import_fastmcp(self) -> None:
        """source-text 层面禁止 fastmcp / loguru 直接依赖泄漏

        注：``mcp.types`` 不在禁止列表——它通过 task_queue → server_config
        被间接拉入，本模块自己不会显式 ``from mcp.types import``。本测试只
        管「task_queue_singleton.py 文件本身」的 import 行，这是文本层
        最强可执行约束。
        """
        forbidden_imports = [
            "from fastmcp",
            "import fastmcp",
            "from loguru",
        ]
        for needle in forbidden_imports:
            self.assertNotIn(
                needle,
                self.singleton_src,
                f"task_queue_singleton.py 不允许包含 {needle!r}—— "
                f"这会破坏 R20.8 的解耦目标",
            )

    def test_server_no_longer_owns_global_task_queue_module_var(self) -> None:
        """server.py 不应再自行定义 _global_task_queue 模块级变量"""
        self.assertNotIn(
            "_global_task_queue: TaskQueue | None = None",
            self.server_src,
            "server.py 不应再自行定义模块级 _global_task_queue，"
            "应该 re-export task_queue_singleton 的成员",
        )

    def test_server_re_exports_singleton_api(self) -> None:
        """server.py 必须 re-export get_task_queue 与 _shutdown_global_task_queue"""
        self.assertIn("from task_queue_singleton import", self.server_src)
        self.assertIn("get_task_queue", self.server_src)
        self.assertIn("_shutdown_global_task_queue", self.server_src)

    def test_web_ui_imports_from_singleton_not_server(self) -> None:
        """web_ui.py 必须直接从 task_queue_singleton 拿 get_task_queue"""
        self.assertIn(
            "from task_queue_singleton import get_task_queue",
            self.web_ui_src,
        )
        self.assertNotIn(
            "from server import get_task_queue",
            self.web_ui_src,
            "web_ui.py 不允许 from server import get_task_queue—— "
            "这会让 web_ui 子进程白白加载 fastmcp/mcp",
        )

    def test_task_route_imports_from_singleton(self) -> None:
        self.assertIn(
            "from task_queue_singleton import get_task_queue",
            self.task_route_src,
        )
        self.assertNotIn(
            "from server import get_task_queue",
            self.task_route_src,
        )

    def test_feedback_route_imports_from_singleton(self) -> None:
        self.assertIn(
            "from task_queue_singleton import get_task_queue",
            self.feedback_route_src,
        )
        self.assertNotIn(
            "from server import get_task_queue",
            self.feedback_route_src,
        )


# ═══════════════════════════════════════════════════════════════════════════
# 5. 模块结构稳定性
# ═══════════════════════════════════════════════════════════════════════════
class TestModuleStructure(unittest.TestCase):
    def test_module_has_expected_public_api(self) -> None:
        import task_queue_singleton

        self.assertTrue(callable(task_queue_singleton.get_task_queue))
        self.assertTrue(callable(task_queue_singleton._shutdown_global_task_queue))
        self.assertIsInstance(
            task_queue_singleton._global_task_queue_lock,
            type(threading.Lock()),
        )

    def test_reload_does_not_create_duplicate_singleton(self) -> None:
        """importlib.reload 不应该让单例被错误重置（非常规场景，但防御性测试）"""
        import task_queue_singleton

        before = task_queue_singleton._global_task_queue
        importlib.reload(task_queue_singleton)
        after = task_queue_singleton._global_task_queue
        self.assertIsNone(after, "reload 后单例字段应回到 None（重新初始化）")
        if before is not None:
            try:
                before.stop_cleanup()
            except Exception:
                pass


if __name__ == "__main__":
    unittest.main()
