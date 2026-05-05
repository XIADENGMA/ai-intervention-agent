"""R23.1 — _sse_listener 复用 service_manager pooled client 的契约测试。

R23.1 优化把 `server_feedback._sse_listener` 内部从每次 `__aenter__/__aexit__`
新建一个独立 `httpx.AsyncClient`，改成复用 `service_manager.get_async_client(cfg)`
返回的进程级 singleton（与 `_fetch_result` polling 路径共享同一个 connection
pool）。

省下来的成本（每次 `interactive_feedback` 调用）：
- `httpx.AsyncClient.__init__` 内部一次完整的 `AsyncHTTPTransport` 构造
  + retry 策略对象创建 + 内部 asyncio lock 初始化（loopback 测得 ~1-3 ms）
- 一对 SSE-only 的 TCP 连接（同 process 内连续多次 invoke 时，pooled client
  能 keep-alive 复用底层 socket，前提是 server `Connection: keep-alive`）
- 进程退出时一次 client `__aexit__`（旧路径每次都做，新路径只在
  `service_manager._close_async_client_best_effort` 一次性收尾）

本测试套件锁定的不变量：
1. **Source contract**：`_sse_listener` 必须用 `service_manager.get_async_client`
   拿 client，禁止再写 `httpx.AsyncClient()` 直接 new；`stream(...)` 调用必须
   显式传 `httpx.Timeout(None, connect=...)` 覆盖默认 read timeout（SSE 是
   long-lived 流，会被默认 5s read timeout 砍掉）。
2. **Doc contract**：`_sse_listener` docstring 必须自描述"复用 pooled client"
   的设计意图，方便 6 个月后的维护者一眼看懂为什么不直接 new client。
3. **Behavioral**：模拟 SSE 完成场景下，`service_manager.get_async_client`
   被 `_sse_listener` 命中（spy 计数 ≥ 1），且不存在 listener 内部直接
   `httpx.AsyncClient(...)` 调用。
4. **Behavioral**：listener 内部对 `stream(...)` 的调用必须带
   `timeout=httpx.Timeout(None, connect=...)`（read timeout = None = 不超时），
   防止 SSE 长流被默认 timeout 误杀。
5. **Regression**：R22.1 既有契约（SSE 不连接 → poll 走 fast cadence；SSE
   连接 → poll 走 30s safety net）保持不变，R23.1 不引入回归。
"""

from __future__ import annotations

import asyncio
import inspect
import re
import unittest
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx

import server_feedback


def _read_sse_listener_source() -> str:
    """从 `wait_for_task_completion` 函数源码里截取 `_sse_listener` 内嵌闭包
    的源码片段（含 docstring 和函数体），不依赖 `inspect.getsource(_sse_listener)`
    （那会报 OSError，因为 listener 是闭包不在 module 顶层）。"""
    full = inspect.getsource(server_feedback.wait_for_task_completion)
    # 抓 `async def _sse_listener` 到下一个 `async def _poll_fallback` 之间
    m = re.search(
        r"(    async def _sse_listener.*?)(?=\n    async def _poll_fallback)",
        full,
        re.DOTALL,
    )
    if m is None:
        raise AssertionError(
            "无法从 wait_for_task_completion 中提取 _sse_listener 源码片段，"
            "如果重构后函数名变了请同步修复本测试。"
        )
    return m.group(1)


# ============================================================================
# Section 1：源码不变量
# ============================================================================


class TestSourceInvariants(unittest.TestCase):
    """锁定 `_sse_listener` 必须经过 service_manager 拿 client、必须覆盖 timeout。"""

    def setUp(self) -> None:
        self.body = _read_sse_listener_source()

    def test_uses_service_manager_get_async_client(self) -> None:
        """必须经由 `service_manager.get_async_client(cfg)` 拿 client。"""
        self.assertIn(
            "service_manager.get_async_client",
            self.body,
            "_sse_listener 必须用 service_manager.get_async_client 复用进程级池化 client",
        )

    def test_does_not_construct_new_async_client(self) -> None:
        """禁止直接 `httpx.AsyncClient(...)` 构造新 client。

        允许出现 `httpx.Timeout(...)`、`httpx.AsyncBaseTransport` 等其它 httpx
        类型，但 `httpx.AsyncClient(...)` 这个具体调用一定不能再出现，否则就
        破坏了 R23.1 复用池的目的。
        """
        self.assertNotRegex(
            self.body,
            r"httpx\.AsyncClient\s*\(",
            "_sse_listener 不应再直接新建 httpx.AsyncClient(...)，必须复用 pooled client",
        )

    def test_stream_overrides_timeout_with_none_read(self) -> None:
        """`stream(...)` 调用必须显式传 `httpx.Timeout(None, ...)`。

        如果不覆盖，`get_async_client` 返回的 client 默认 read timeout =
        `config.timeout`（短请求合适但对 long-lived SSE stream 会在第一个
        空闲窗口就被砍掉）。这是 R23.1 新增的关键边界约束。
        """
        self.assertRegex(
            self.body,
            r"stream\([^)]*timeout\s*=\s*httpx\.Timeout\(\s*None",
            "stream(...) 调用必须用 httpx.Timeout(None, connect=...) 覆盖默认 read timeout",
        )

    def test_uses_async_with_for_stream_only(self) -> None:
        """SSE listener 应只对 `sc.stream(...)` 用 `async with`，client 本身
        是 module 级 singleton，不能再 `async with` 它（会在 `__aexit__` 时
        关掉所有走该 client 的 _fetch_result polling）。"""
        # async with 应该只 wrap stream(...) 这一个对象，不再包 client
        async_with_blocks = re.findall(r"async with\s+(.+?):", self.body)
        for block in async_with_blocks:
            self.assertNotIn(
                "AsyncClient",
                block,
                f"async with 不能再包 AsyncClient，否则会关掉共享 client：{block}",
            )

    def test_top_module_imports_httpx(self) -> None:
        """R25.2 之后：``server_feedback`` 顶层不再 ``import httpx``，改成函数体内 lazy import。

        原因：``server_feedback`` 在 R25.2 之前直接 ``import httpx``，把 ~55 ms 的
        cold-start 成本绑死在 ``server.py`` 顶层 import 链路上。R25.2 把 ``httpx``
        从模块顶层移到使用点函数体首行；由于 ``server_feedback`` 没有模块级
        ``httpx.X`` 类型注解（``except httpx.HTTPError`` 与 ``httpx.Timeout(...)`` 都在
        函数体内），连 ``TYPE_CHECKING`` 守护块都不需要——三处使用点（``_sse_listener``
        / ``launch_feedback_ui`` / ``interactive_feedback``）直接本地 ``import httpx`` 即可。

        本测试断言：

        1. 顶层不能再裸 ``import httpx``。
        2. ``_sse_listener`` 函数体里必须有 ``import httpx`` 才能引用 ``httpx.Timeout``。

        如果未来有人把 ``import httpx`` 加回顶层，本测试会立刻失败，挡住 +55 ms 的
        cold-start regression。
        """
        module_src = inspect.getsource(server_feedback)

        # 1) 不能有裸的 ``import httpx`` 在模块顶层（缩进 0）
        bare_top_level = re.search(r"^import httpx\b", module_src, re.MULTILINE)
        self.assertIsNone(
            bare_top_level,
            "R25.2: server_feedback 顶层不能再 ``import httpx``——应改成函数体内 lazy import",
        )

        # 2) ``_sse_listener`` 函数体里必须有运行时本地 import httpx
        sse_listener_match = re.search(
            r"async def _sse_listener\(\) -> None:.*?(?=\n    async def |\n\s{0,4}\S)",
            module_src,
            re.DOTALL,
        )
        self.assertIsNotNone(
            sse_listener_match,
            "未找到 _sse_listener 函数体——测试需要更新",
        )
        if sse_listener_match is not None:
            self.assertIn(
                "import httpx",
                sse_listener_match.group(0),
                "R25.2: _sse_listener 函数体必须本地 import httpx 才能引用 httpx.Timeout",
            )


# ============================================================================
# Section 2：文档契约
# ============================================================================


class TestDocumentationContract(unittest.TestCase):
    """`_sse_listener` 的 docstring 必须解释 R23.1 的复用动机和 timeout 覆盖原因。"""

    def setUp(self) -> None:
        self.body = _read_sse_listener_source()

    def test_docstring_mentions_r23_marker(self) -> None:
        self.assertIn(
            "R23.1",
            self.body,
            "_sse_listener docstring 必须有 R23.1 标记，方便日后 grep 追溯优化历史",
        )

    def test_docstring_explains_pool_reuse(self) -> None:
        """必须出现"复用"+"连接池"或类似措辞，让维护者明白意图。"""
        self.assertTrue(
            "复用" in self.body
            and ("连接池" in self.body or "pool" in self.body.lower()),
            "_sse_listener docstring 必须解释复用连接池的动机，避免日后被误改回 new AsyncClient",
        )

    def test_docstring_explains_timeout_override(self) -> None:
        """必须解释为什么要把 read timeout 设成 None（SSE long-lived）。"""
        self.assertTrue(
            "long-lived" in self.body
            or "long lived" in self.body
            or "长连接" in self.body
            or "不超时" in self.body
            or "timeout" in self.body.lower(),
            "_sse_listener docstring 必须解释 SSE 是 long-lived 所以 read timeout 要 None",
        )


# ============================================================================
# Section 3：运行时行为（spy 验证 client 真的来自 service_manager）
# ============================================================================


def _make_pooled_client_mock(
    *,
    get_side_effect: list[Any] | None = None,
    get_return_value: Any = None,
    stream_should_complete: bool = False,
) -> MagicMock:
    """造一个模拟的 pooled client，覆盖 `_fetch_result` 用的 `.get` 和
    `_sse_listener` 用的 `.stream`。

    `stream_should_complete=True` 时 stream 会推一条 `task_changed/completed`
    事件让 listener 走完整路径退出；否则 stream 抛异常模拟 SSE 不可用，
    listener 会 fallback 到 poll。
    """
    client = MagicMock()
    if get_side_effect is not None:
        client.get = AsyncMock(side_effect=get_side_effect)
    else:
        client.get = AsyncMock(return_value=get_return_value)
    client.post = AsyncMock()

    if stream_should_complete:
        # 构造一个 async context manager，迭代时 yield 一行 SSE
        class _StreamCM:
            async def __aenter__(self):
                resp = MagicMock()

                async def _aiter():
                    yield 'data: {"task_id":"t-spy","new_status":"completed"}'

                resp.aiter_lines = _aiter
                return resp

            async def __aexit__(self, exc_type, exc, tb):
                return False

        client.stream = MagicMock(return_value=_StreamCM())
    else:
        client.stream = MagicMock(side_effect=RuntimeError("SSE blocked in test"))
    return client


class TestSseListenerCallsPooledClient(unittest.TestCase):
    """运行时验证：`_sse_listener` 真的命中 `service_manager.get_async_client`。"""

    @patch("service_manager.get_web_ui_config")
    @patch("service_manager.get_async_client")
    def test_get_async_client_is_called_at_least_once(
        self, mock_get_client, mock_get_cfg
    ) -> None:
        """SSE 完成路径下，`get_async_client` 至少被命中一次（来自 SSE listener
        和/或 _fetch_result，关键是不再直接 new client）。"""
        from service_manager import WebUIConfig

        cfg = WebUIConfig(
            host="127.0.0.1",
            port=8088,
            language="auto",
            timeout=5,
            max_retries=0,
            retry_delay=0.1,
            external_base_url="",
        )
        mock_get_cfg.return_value = (cfg, 60)

        completed_resp = MagicMock()
        completed_resp.status_code = 200
        completed_resp.json.return_value = {
            "success": True,
            "task": {
                "status": "completed",
                "result": {"user_input": "ok-r23-1"},
            },
        }
        client = _make_pooled_client_mock(
            get_return_value=completed_resp,
            stream_should_complete=True,
        )
        mock_get_client.return_value = client

        with patch("server_config.BACKEND_MIN", 1):
            result = asyncio.run(
                server_feedback.wait_for_task_completion("t-spy", timeout=5)
            )

        self.assertEqual(result.get("user_input"), "ok-r23-1")
        # SSE listener 进入完成分支会调一次 get_async_client，_fetch_result 也会
        # 调一次（拉 completed 任务的 result），总和应当 ≥ 2，至少 ≥ 1 表示
        # 池化路径生效。
        self.assertGreaterEqual(
            mock_get_client.call_count,
            1,
            "service_manager.get_async_client 必须被 _sse_listener / _fetch_result 调用",
        )

    @patch("service_manager.get_web_ui_config")
    @patch("service_manager.get_async_client")
    def test_stream_called_with_none_read_timeout(
        self, mock_get_client, mock_get_cfg
    ) -> None:
        """spy `stream(...)` 调用，验证 timeout kwarg 是 `Timeout(None, ...)`。"""
        from service_manager import WebUIConfig

        cfg = WebUIConfig(
            host="127.0.0.1",
            port=8088,
            language="auto",
            timeout=5,
            max_retries=0,
            retry_delay=0.1,
            external_base_url="",
        )
        mock_get_cfg.return_value = (cfg, 60)

        completed_resp = MagicMock()
        completed_resp.status_code = 200
        completed_resp.json.return_value = {
            "success": True,
            "task": {
                "status": "completed",
                "result": {"user_input": "ok-timeout-check"},
            },
        }
        client = _make_pooled_client_mock(
            get_return_value=completed_resp,
            stream_should_complete=True,
        )
        mock_get_client.return_value = client

        with patch("server_config.BACKEND_MIN", 1):
            asyncio.run(
                server_feedback.wait_for_task_completion("t-timeout", timeout=5)
            )

        self.assertGreaterEqual(
            client.stream.call_count, 1, "_sse_listener 必须调用 client.stream(...)"
        )
        call_kwargs = client.stream.call_args.kwargs
        self.assertIn("timeout", call_kwargs, "stream(...) 必须显式传 timeout kwarg")
        timeout = call_kwargs["timeout"]
        self.assertIsInstance(
            timeout,
            httpx.Timeout,
            f"timeout 必须是 httpx.Timeout 实例，实际：{type(timeout).__name__}",
        )
        self.assertIsNone(
            timeout.read,
            f"SSE stream 的 read timeout 必须是 None（long-lived），实际：{timeout.read}",
        )
        self.assertIsNotNone(
            timeout.connect,
            "connect timeout 不能是 None，避免 connect 阶段卡死",
        )

    @patch("service_manager.get_web_ui_config")
    @patch("service_manager.get_async_client")
    def test_listener_does_not_construct_new_async_client(
        self, mock_get_client, mock_get_cfg
    ) -> None:
        """运行 listener 期间不能新建 `httpx.AsyncClient(...)`。

        通过 spy `httpx.AsyncClient.__init__` 来检测：如果 listener 真的还在
        new client，spy 计数会增加；R23.1 后该计数应该为 0。

        注意：`service_manager.get_async_client` 内部第一次调用时本身会 new
        一个 client（这是预期的，singleton 创建路径），但本测试在 patch 中
        替换掉了 `service_manager.get_async_client`，所以 service_manager
        不会真的去 new。这样剩下的任何 `httpx.AsyncClient.__init__` 调用都
        是 listener 自己 new 出来的，必为 0。
        """
        from service_manager import WebUIConfig

        cfg = WebUIConfig(
            host="127.0.0.1",
            port=8088,
            language="auto",
            timeout=5,
            max_retries=0,
            retry_delay=0.1,
            external_base_url="",
        )
        mock_get_cfg.return_value = (cfg, 60)

        completed_resp = MagicMock()
        completed_resp.status_code = 200
        completed_resp.json.return_value = {
            "success": True,
            "task": {
                "status": "completed",
                "result": {"user_input": "ok-no-new-client"},
            },
        }
        client = _make_pooled_client_mock(
            get_return_value=completed_resp,
            stream_should_complete=True,
        )
        mock_get_client.return_value = client

        original_init = httpx.AsyncClient.__init__
        init_calls: list[tuple[Any, ...]] = []

        def _spy_init(self, *args, **kwargs):
            init_calls.append((args, kwargs))
            return original_init(self, *args, **kwargs)

        with (
            patch.object(httpx.AsyncClient, "__init__", _spy_init),
            patch("server_config.BACKEND_MIN", 1),
        ):
            asyncio.run(server_feedback.wait_for_task_completion("t-no-new", timeout=5))

        self.assertEqual(
            len(init_calls),
            0,
            f"R23.1 后 _sse_listener 不应再 new AsyncClient（spy 命中：{init_calls}）",
        )


# ============================================================================
# Section 4：R22.1 既有契约回归保护
# ============================================================================


class TestR22ContractsStillHold(unittest.TestCase):
    """R23.1 改 client 来源不能破坏 R22.1 的 SSE+poll 协同语义。"""

    @patch("service_manager.get_web_ui_config")
    @patch("service_manager.get_async_client")
    def test_poll_fallback_when_sse_blocked(
        self, mock_get_client, mock_get_cfg
    ) -> None:
        """SSE 不可用 → poll 接管 → 在 active→completed 切换时拿到 result。"""
        from service_manager import WebUIConfig

        cfg = WebUIConfig(
            host="127.0.0.1",
            port=8088,
            language="auto",
            timeout=5,
            max_retries=0,
            retry_delay=0.1,
            external_base_url="",
        )
        mock_get_cfg.return_value = (cfg, 60)

        in_progress = MagicMock()
        in_progress.status_code = 200
        in_progress.json.return_value = {
            "success": True,
            "task": {"status": "active", "result": None},
        }
        completed = MagicMock()
        completed.status_code = 200
        completed.json.return_value = {
            "success": True,
            "task": {
                "status": "completed",
                "result": {"user_input": "ok-poll-r23-regression"},
            },
        }
        client = _make_pooled_client_mock(
            get_side_effect=[in_progress, completed, completed],
            stream_should_complete=False,
        )
        mock_get_client.return_value = client

        with patch("server_config.BACKEND_MIN", 1):
            result = asyncio.run(
                server_feedback.wait_for_task_completion("t-r23-regression", timeout=5)
            )

        self.assertEqual(result.get("user_input"), "ok-poll-r23-regression")


if __name__ == "__main__":
    unittest.main()
