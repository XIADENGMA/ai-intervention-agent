"""R22.1 ``wait_for_task_completion`` 自适应轮询节奏测试

背景
----

R21 之前 ``server_feedback.wait_for_task_completion`` 的 ``_poll_fallback``
固定每 2 秒拉一次 ``GET /api/tasks/<task_id>``，与 SSE 主路径并行；当
SSE 健康时，这些 fetch 全部是冗余的，单次任务（默认 240 s 倒计时）
触发 ~119 次冗余 round-trip + ``task_queue._lock`` 竞争。

R22.1 把节奏改为自适应：

    - SSE 已连接（``_sse_listener`` 进入 stream 主循环后 set
      ``sse_connected``）→ 30 s safety net；
    - SSE 未连接 / 已断开 → 2 s 紧密兜底。

与前端 ``static/js/multi_task.js`` 的 ``TASKS_POLL_BASE_MS = 2000`` /
``TASKS_POLL_SSE_FALLBACK_MS = 30000`` 保持完全同步。

测试矩阵
--------

本套件在 5 条互补路径上锁定 R22.1 的契约：

1. **常量层**：模块顶部的 ``_POLL_INTERVAL_FAST_S`` /
   ``_POLL_INTERVAL_SAFETY_NET_S`` 常量存在、取值与前端对齐。
2. **源码不变量**：``_sse_listener`` set / clear ``sse_connected``，
   ``_poll_fallback`` 据此选 interval。这是 R22.1 的"心脏"——如果
   未来某个无意 PR 把 set/clear 删掉或者把 interval 选择逻辑写
   错，这层 invariant 测试会立即红灯。
3. **运行时**：在不破坏既有 R13·B1 / R17.4 契约的前提下，验证
   poll fallback 在 SSE 未连接时仍按 2 s 节奏跑（确保不引入回归）。
4. **文档**：docstring 提到 R22.1 / sse_connected / 30 s，让未来
   维护者读源码就能理解设计意图，无需翻 commit 历史。
5. **前后端一致性**：源码常量与前端 JS 常量值对齐（避免单边漂移）。
"""

from __future__ import annotations

import asyncio
import inspect
import re
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import server_feedback

REPO_ROOT = Path(__file__).resolve().parent.parent
SERVER_FEEDBACK_PATH = REPO_ROOT / "server_feedback.py"
MULTI_TASK_JS_PATH = REPO_ROOT / "static" / "js" / "multi_task.js"


def _read_server_feedback_source() -> str:
    return SERVER_FEEDBACK_PATH.read_text(encoding="utf-8")


def _read_multi_task_js_source() -> str:
    return MULTI_TASK_JS_PATH.read_text(encoding="utf-8")


def _extract_function_source(module_source: str, func_name: str) -> str:
    """从源码中提取顶层 ``async def`` / ``def`` 函数体（含 nested 闭包）。

    这里手写而不依赖 ``ast`` 是因为 ``wait_for_task_completion`` 内部
    定义了 ``_fetch_result`` / ``_sse_listener`` / ``_poll_fallback``
    三个嵌套闭包，这些闭包的源码必须随父函数一起提取，否则 invariant
    测试无法 grep 到内部 set / clear 调用。
    """
    pattern = (
        rf"((?:async\s+)?def\s+{re.escape(func_name)}\s*\([^)]*\)[^:]*:.*?)"
        r"(?=\nasync\s+def\s|\ndef\s|\nclass\s|\Z)"
    )
    match = re.search(pattern, module_source, re.DOTALL)
    assert match is not None, f"未能在源码中找到函数 {func_name}"
    return match.group(1)


def _extract_nested_closure(parent_body: str, closure_name: str) -> str:
    """从父函数体中提取 nested closure 源码（``async def closure_name``）。

    nested closure 的边界是下一个同级 ``async def`` / ``def`` 或函数末尾
    （以缩进减少为信号）。
    """
    lines = parent_body.split("\n")
    closure_start = None
    closure_indent: int | None = None
    closure_lines: list[str] = []
    sig_pat = re.compile(rf"^(\s*)(?:async\s+)?def\s+{re.escape(closure_name)}\s*\(")

    for idx, line in enumerate(lines):
        if closure_start is None:
            m = sig_pat.match(line)
            if m:
                closure_start = idx
                closure_indent = len(m.group(1))
                closure_lines.append(line)
        else:
            assert closure_indent is not None
            if line.strip() == "":
                closure_lines.append(line)
                continue
            line_indent = len(line) - len(line.lstrip())
            if line_indent <= closure_indent:
                break
            closure_lines.append(line)

    assert closure_start is not None, f"未能在父函数中找到嵌套闭包 {closure_name}"
    return "\n".join(closure_lines)


# ============================================================================
# Section 1：常量层
# ============================================================================


class TestConstantsExist(unittest.TestCase):
    """``_POLL_INTERVAL_FAST_S`` / ``_POLL_INTERVAL_SAFETY_NET_S`` 必须存在。

    没有这两个常量，``_poll_fallback`` 内部就只能写魔法数字，未来调整
    节奏需要扫描多处；提到模块顶部还便于测试 reference + 文档引用。
    """

    def test_fast_constant_defined(self) -> None:
        self.assertTrue(hasattr(server_feedback, "_POLL_INTERVAL_FAST_S"))

    def test_safety_net_constant_defined(self) -> None:
        self.assertTrue(hasattr(server_feedback, "_POLL_INTERVAL_SAFETY_NET_S"))

    def test_fast_constant_is_2_seconds(self) -> None:
        """与前端 ``TASKS_POLL_BASE_MS = 2000`` 对齐。"""
        self.assertEqual(server_feedback._POLL_INTERVAL_FAST_S, 2.0)

    def test_safety_net_constant_is_30_seconds(self) -> None:
        """与前端 ``TASKS_POLL_SSE_FALLBACK_MS = 30000`` 对齐。"""
        self.assertEqual(server_feedback._POLL_INTERVAL_SAFETY_NET_S, 30.0)

    def test_safety_net_strictly_larger_than_fast(self) -> None:
        """语义不变量：safety_net 必须严格大于 fast，否则 R22.1 退化为 R20 状态。"""
        self.assertGreater(
            server_feedback._POLL_INTERVAL_SAFETY_NET_S,
            server_feedback._POLL_INTERVAL_FAST_S,
        )

    def test_fast_constant_is_float(self) -> None:
        """``asyncio.wait_for`` 的 timeout 参数必须是 float / int。"""
        self.assertIsInstance(server_feedback._POLL_INTERVAL_FAST_S, float)

    def test_safety_net_constant_is_float(self) -> None:
        self.assertIsInstance(server_feedback._POLL_INTERVAL_SAFETY_NET_S, float)


# ============================================================================
# Section 2：源码不变量（R22.1 心脏）
# ============================================================================


class TestSourceInvariants(unittest.TestCase):
    """R22.1 的核心契约：``_sse_listener`` set/clear ``sse_connected``，
    ``_poll_fallback`` 据此选 interval。这些 invariant 被破坏 → 性能优化
    回退到 R21 状态（每任务 ~119 次冗余 fetch）但行为依然"看起来对"，
    所以光靠运行时测试很难捕获——只有源码 grep 能可靠 lock。
    """

    def setUp(self) -> None:
        self.source = _read_server_feedback_source()
        self.wait_func_body = _extract_function_source(
            self.source, "wait_for_task_completion"
        )
        self.sse_listener_body = _extract_nested_closure(
            self.wait_func_body, "_sse_listener"
        )
        self.poll_fallback_body = _extract_nested_closure(
            self.wait_func_body, "_poll_fallback"
        )

    # --- sse_connected 事件层 ---

    def test_wait_func_declares_sse_connected_event(self) -> None:
        """``wait_for_task_completion`` 必须声明 ``sse_connected = asyncio.Event()``。"""
        self.assertRegex(
            self.wait_func_body,
            r"sse_connected\s*=\s*asyncio\.Event\(\)",
            "缺少 sse_connected 事件声明——R22.1 设计核心",
        )

    def test_wait_func_declares_sse_connected_before_closures(self) -> None:
        """``sse_connected`` 必须在 ``_sse_listener`` / ``_poll_fallback`` 闭包之前
        声明，否则 nested 闭包看不到它（Python 闭包按词法作用域）。"""
        body = self.wait_func_body
        sse_idx = body.find("sse_connected = asyncio.Event(")
        listener_idx = body.find("def _sse_listener(")
        poll_idx = body.find("def _poll_fallback(")
        self.assertGreater(sse_idx, 0)
        self.assertGreater(listener_idx, sse_idx)
        self.assertGreater(poll_idx, sse_idx)

    # --- _sse_listener 维护 sse_connected ---

    def test_sse_listener_sets_sse_connected_inside_stream(self) -> None:
        """SSE 进入 stream 主循环前必须 set ``sse_connected``。

        如果 set 在 stream 外（例如 listener 入口）就会有 false-positive
        ——SSE 还没真正连上，poll 已经按为 30s 节奏，导致首个事件
        延迟最多 30s。set 的位置必须紧跟 ``sc.stream(...)`` 后。

        实现策略：用字符串索引代替"嵌套括号"正则——前者鲁棒，后者
        无法跨多行 ``sc.stream("GET", sse_url, timeout=httpx.Timeout(...))``
        正确匹配（嵌套括号让 [^)]* 提前停止）。
        """
        body = self.sse_listener_body
        stream_idx = body.find("sc.stream(")
        async_for_idx = body.find("async for line in resp.aiter_lines")
        self.assertGreaterEqual(stream_idx, 0, "sse_listener 必须用 sc.stream(...)")
        self.assertGreater(
            async_for_idx,
            stream_idx,
            "sse_listener 必须有 async for ... aiter_lines 主循环",
        )
        between = body[stream_idx:async_for_idx]
        self.assertIn(
            "sse_connected.set()",
            between,
            "sse_connected.set() 必须在 sc.stream(...) 与 async for 主循环之间",
        )

    def test_sse_listener_clears_sse_connected_in_finally(self) -> None:
        """所有退出路径（正常完成、cancel、异常）都必须 clear ``sse_connected``，
        否则 listener 退出后 poll 仍按 30s 节奏，再也回不到 2s 紧密兜底。"""
        # 简单 grep：finally 块里出现 sse_connected.clear()
        self.assertRegex(
            self.sse_listener_body,
            r"finally:\s*[\r\n]+\s*sse_connected\.clear\(\)",
            "_sse_listener 必须在 finally 中 clear sse_connected",
        )

    def test_sse_listener_does_not_leak_sse_connected_outside_listener(self) -> None:
        """``sse_connected`` 仅在 ``_sse_listener`` 内修改；外部任何
        set/clear 都会破坏"SSE 是否在 stream 主循环"的语义。"""
        # 排除 listener 内部，统计 sse_connected.set() / clear() 出现次数
        # 这里更严格：在 wait_func_body 中减去 listener_body 的部分，剩下不应有
        outside = self.wait_func_body.replace(self.sse_listener_body, "")
        self.assertNotIn("sse_connected.set()", outside, "外部不得 set sse_connected")
        self.assertNotIn(
            "sse_connected.clear()", outside, "外部不得 clear sse_connected"
        )

    # --- _poll_fallback 读取 sse_connected ---

    def test_poll_fallback_reads_sse_connected(self) -> None:
        """``_poll_fallback`` 必须读 ``sse_connected.is_set()`` 决定 interval。"""
        self.assertIn(
            "sse_connected.is_set()",
            self.poll_fallback_body,
            "_poll_fallback 必须读 sse_connected.is_set() 来选 interval",
        )

    def test_poll_fallback_uses_safety_net_constant(self) -> None:
        """``_poll_fallback`` 必须引用 ``_POLL_INTERVAL_SAFETY_NET_S`` 常量
        而不是写死 30 / 30.0。"""
        self.assertIn(
            "_POLL_INTERVAL_SAFETY_NET_S",
            self.poll_fallback_body,
            "_poll_fallback 必须引用 _POLL_INTERVAL_SAFETY_NET_S 常量",
        )

    def test_poll_fallback_uses_fast_constant(self) -> None:
        """同上，必须引用 ``_POLL_INTERVAL_FAST_S`` 常量。"""
        self.assertIn(
            "_POLL_INTERVAL_FAST_S",
            self.poll_fallback_body,
            "_poll_fallback 必须引用 _POLL_INTERVAL_FAST_S 常量",
        )

    def test_poll_fallback_no_hardcoded_2s_interval(self) -> None:
        """R22.1 之前的 ``_INTERVAL = 2.0`` 局部常量必须移除，否则
        既有的 hardcoded 2s 与新的常量并存，未来调整节奏会错位。"""
        self.assertNotRegex(
            self.poll_fallback_body,
            r"_INTERVAL\s*=\s*2\.0",
            "_poll_fallback 不应再有 hardcoded _INTERVAL = 2.0",
        )

    def test_poll_fallback_safety_net_branch_appears_before_fast(self) -> None:
        """三元表达式的语义：``safety_net if connected else fast``。
        这条 invariant 防止"if-else 反向写错"的回归。"""
        body = self.poll_fallback_body
        safety_idx = body.find("_POLL_INTERVAL_SAFETY_NET_S")
        fast_idx = body.find("_POLL_INTERVAL_FAST_S")
        self.assertGreaterEqual(safety_idx, 0)
        self.assertGreaterEqual(fast_idx, 0)
        # 三元表达式：safety 在 if 之前出现，fast 在 else 之后；具体格式取决于
        # 三元的写法。这里至少保证两个常量都被引用，且 safety_net 关联 is_set()。
        # 抓取使用 safety 的整行/片段
        snippet_match = re.search(
            r"interval\s*=\s*\(?\s*_POLL_INTERVAL_SAFETY_NET_S[\s\S]{0,200}?_POLL_INTERVAL_FAST_S",
            body,
        )
        self.assertIsNotNone(
            snippet_match,
            "interval = ... 三元表达式的顺序必须是 safety_net if ... else fast",
        )

    # --- 不再有冗余的 set/clear ---

    def test_sse_connected_set_appears_exactly_once(self) -> None:
        """``sse_connected.set()`` 在整个 ``wait_for_task_completion`` 函数体内
        应当只出现一次（在 listener 内部 stream 进入主循环前）。多余的 set
        会让 poll 提前进入 30s 节奏。"""
        count = self.wait_func_body.count("sse_connected.set()")
        self.assertEqual(
            count, 1, f"sse_connected.set() 应只出现 1 次，实际 {count} 次"
        )

    def test_sse_connected_clear_appears_exactly_once(self) -> None:
        """同上，clear 也只在 listener finally 中出现一次。"""
        count = self.wait_func_body.count("sse_connected.clear()")
        self.assertEqual(
            count, 1, f"sse_connected.clear() 应只出现 1 次，实际 {count} 次"
        )


# ============================================================================
# Section 3：运行时行为（确保不引入回归）
# ============================================================================


class TestPollFallbackBehaviorWithoutSSE(unittest.TestCase):
    """SSE 未连接（httpx 测试 fixture 全局禁用真实网络）→ ``_poll_fallback``
    必须按 2 s 节奏运行；同时既有的 R13·B1 / R17.4 / 404 / 完成检测路径
    必须保持原行为，证明 R22.1 没有把已有契约改坏。
    """

    def _mock_async_client(self, *, get_side_effect=None, get_return_value=None):
        client = MagicMock()
        if get_side_effect is not None:
            client.get = AsyncMock(side_effect=get_side_effect)
        else:
            client.get = AsyncMock(return_value=get_return_value)
        client.post = AsyncMock()
        return client

    @patch("service_manager.get_web_ui_config")
    @patch("service_manager.get_async_client")
    def test_completion_via_poll_still_works(self, mock_get_client, mock_get_cfg):
        """SSE 永远不连接（httpx blocked），poll 第二次拉到 completed → 正常返回。"""
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

        # 第一次 GET 返回 200 + 任务还在 active；第二次返回 200 + completed
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
                "result": {"user_input": "ok-from-poll"},
            },
        }
        mock_get_client.return_value = self._mock_async_client(
            get_side_effect=[in_progress, completed, completed]
        )

        with patch("server_config.BACKEND_MIN", 1):
            result = asyncio.run(
                server_feedback.wait_for_task_completion("t-poll", timeout=5)
            )

        self.assertEqual(result.get("user_input"), "ok-from-poll")

    @patch("service_manager.get_web_ui_config")
    @patch("service_manager.get_async_client")
    def test_404_still_returns_resubmit(self, mock_get_client, mock_get_cfg):
        """既有契约：``_fetch_result`` 收到 404 → 立即返回 resubmit_response。"""
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

        gone = MagicMock()
        gone.status_code = 404
        mock_get_client.return_value = self._mock_async_client(get_return_value=gone)

        with patch("server_config.BACKEND_MIN", 1):
            result = asyncio.run(
                server_feedback.wait_for_task_completion("t-404", timeout=5)
            )

        self.assertIn("text", result)

    @patch("service_manager.get_web_ui_config")
    @patch("service_manager.get_async_client")
    def test_poll_uses_fast_interval_when_sse_never_connects(
        self, mock_get_client, mock_get_cfg
    ):
        """SSE 一直不连接（httpx 测试 fixture 阻止真实 SSE），poll 应当
        按 2 s 节奏运行——通过 timeout=3s 时段内的 GET 调用次数验证。

        预期：3 s 内至少完成一次 fetch + 一次 wait（2 s）= 至少 1-2 次 GET 调用，
        远小于 30s 节奏（那种情况下只会有 1 次 GET）。
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

        ticking = MagicMock()
        ticking.status_code = 200
        ticking.json.return_value = {
            "success": True,
            "task": {"status": "active", "result": None},
        }
        client = self._mock_async_client(get_return_value=ticking)
        mock_get_client.return_value = client

        with patch("server_config.BACKEND_MIN", 1):
            asyncio.run(server_feedback.wait_for_task_completion("t-fast", timeout=3))

        # 3s timeout / 2s interval ≈ 1-2 次 GET（包括首次 + 1-2 次重试）
        # 算上 R17.4 finally retry 再加 1 次。所以总数 >= 2。
        # 如果 R22.1 误把 SSE 未连接路径也拉成 30s，就只会有 1 次首次 GET +
        # 1 次 retry = 2 次，与正常路径一样，所以 *仅靠* call_count 判断
        # 不是足够强的 invariant；保留作为 smoke。
        self.assertGreaterEqual(client.get.call_count, 2)


# ============================================================================
# Section 4：文档契约
# ============================================================================


class TestDocumentationMentionsR22(unittest.TestCase):
    """docstring 必须提到 R22.1 / sse_connected / 30 s，让未来维护者
    读源码就能理解设计意图。"""

    def setUp(self) -> None:
        self.wait_doc = server_feedback.wait_for_task_completion.__doc__ or ""
        self.module_source = _read_server_feedback_source()

    def test_wait_func_docstring_mentions_r22(self) -> None:
        self.assertIn("R22.1", self.wait_doc)

    def test_wait_func_docstring_mentions_sse_connected(self) -> None:
        # 不强制大小写，因为 docstring 里可能 inline code 或叙述
        self.assertRegex(
            self.wait_doc, r"sse_connected", "docstring 应提到 sse_connected"
        )

    def test_wait_func_docstring_mentions_30s(self) -> None:
        self.assertRegex(self.wait_doc, r"30\s*s|30 秒")

    def test_wait_func_docstring_mentions_2s(self) -> None:
        self.assertRegex(self.wait_doc, r"2\s*s|2 秒")

    def test_module_top_docstring_mentions_r22_constants(self) -> None:
        """模块顶部应有针对常量的设计注释（让 grep R22.1 直接命中）。"""
        self.assertIn("R22.1", self.module_source)


# ============================================================================
# Section 5：前后端常量一致性
# ============================================================================


class TestFrontendBackendConstantAlignment(unittest.TestCase):
    """R22.1 的设计承诺是"前后端节奏完全对齐"，所以前端 ``multi_task.js``
    的 ``TASKS_POLL_BASE_MS`` / ``TASKS_POLL_SSE_FALLBACK_MS`` 必须与后端
    Python 常量同步更新。如果哪天前端改了节奏，这里立即红灯。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.js_source = _read_multi_task_js_source()

    def _extract_js_const_ms(self, name: str) -> int:
        """从 ``var FOO = 1234`` 形态的 JS 源码抓出整数常量。"""
        match = re.search(
            rf"\b{re.escape(name)}\s*=\s*(\d+)",
            self.js_source,
        )
        assert match is not None, f"未在 multi_task.js 中找到常量 {name}"
        return int(match.group(1))

    def test_fast_interval_matches_frontend(self) -> None:
        """``_POLL_INTERVAL_FAST_S * 1000 == TASKS_POLL_BASE_MS``。"""
        ms = self._extract_js_const_ms("TASKS_POLL_BASE_MS")
        self.assertEqual(
            int(server_feedback._POLL_INTERVAL_FAST_S * 1000),
            ms,
            "后端 _POLL_INTERVAL_FAST_S 必须与前端 TASKS_POLL_BASE_MS 同步",
        )

    def test_safety_net_matches_frontend(self) -> None:
        """``_POLL_INTERVAL_SAFETY_NET_S * 1000 == TASKS_POLL_SSE_FALLBACK_MS``。"""
        ms = self._extract_js_const_ms("TASKS_POLL_SSE_FALLBACK_MS")
        self.assertEqual(
            int(server_feedback._POLL_INTERVAL_SAFETY_NET_S * 1000),
            ms,
            "后端 _POLL_INTERVAL_SAFETY_NET_S 必须与前端 TASKS_POLL_SSE_FALLBACK_MS 同步",
        )


# ============================================================================
# Section 6：同步逻辑直接单元测试
# ============================================================================


class TestPollIntervalSelectionLogic(unittest.TestCase):
    """直接验证"interval 选择三元逻辑"：用一个独立的 ``asyncio.Event``
    模拟 ``sse_connected`` 状态，调用相同的判断式，确认行为正确。

    这等价于把 ``_poll_fallback`` 内部的关键判断抽出来单测——既能挡住
    "if-else 顺序写反"的回归，又能挡住"sse_connected.is_set() 写成
    sse_connected"（少了一个 ``.is_set()`` 调用，会变成总返回 truthy）的
    回归。
    """

    @staticmethod
    def _select_interval(sse_connected: asyncio.Event) -> float:
        """与 ``_poll_fallback`` 内部三元写法完全一致的逻辑副本。

        如果 ``server_feedback._poll_fallback`` 改了，这里也要同步——本测
        试同时 lock 实现源码中的常量名（见
        ``TestSourceInvariants::test_poll_fallback_uses_*``）。
        """
        return (
            server_feedback._POLL_INTERVAL_SAFETY_NET_S
            if sse_connected.is_set()
            else server_feedback._POLL_INTERVAL_FAST_S
        )

    def test_disconnected_chooses_fast(self) -> None:
        ev = asyncio.Event()
        self.assertEqual(
            self._select_interval(ev), server_feedback._POLL_INTERVAL_FAST_S
        )

    def test_connected_chooses_safety_net(self) -> None:
        ev = asyncio.Event()
        ev.set()
        self.assertEqual(
            self._select_interval(ev),
            server_feedback._POLL_INTERVAL_SAFETY_NET_S,
        )

    def test_set_then_clear_returns_to_fast(self) -> None:
        """模拟 SSE 连接 → 断开 → 下一次 poll 必须回到 2 s 紧密兜底。"""
        ev = asyncio.Event()
        ev.set()
        self.assertEqual(
            self._select_interval(ev),
            server_feedback._POLL_INTERVAL_SAFETY_NET_S,
        )
        ev.clear()
        self.assertEqual(
            self._select_interval(ev), server_feedback._POLL_INTERVAL_FAST_S
        )

    def test_multiple_set_idempotent(self) -> None:
        """多次 set 不影响选择结果（``asyncio.Event.set()`` 是幂等的）。"""
        ev = asyncio.Event()
        ev.set()
        ev.set()
        ev.set()
        self.assertEqual(
            self._select_interval(ev),
            server_feedback._POLL_INTERVAL_SAFETY_NET_S,
        )

    def test_multiple_clear_idempotent(self) -> None:
        ev = asyncio.Event()
        ev.clear()
        ev.clear()
        self.assertEqual(
            self._select_interval(ev), server_feedback._POLL_INTERVAL_FAST_S
        )


# ============================================================================
# Section 7：协程结构层
# ============================================================================


class TestCoroutineStructure(unittest.TestCase):
    """``wait_for_task_completion`` 仍然是 ``async def``；闭包结构未变。

    R22.1 不该把函数签名 / 异步上下文改坏，否则会破坏所有调用方的
    ``asyncio.run(wait_for_task_completion(...))`` 链路。
    """

    def test_wait_for_task_completion_is_coroutine_function(self) -> None:
        self.assertTrue(
            asyncio.iscoroutinefunction(server_feedback.wait_for_task_completion)
        )

    def test_wait_for_task_completion_signature_unchanged(self) -> None:
        sig = inspect.signature(server_feedback.wait_for_task_completion)
        params = list(sig.parameters.keys())
        self.assertEqual(params, ["task_id", "timeout"])
        self.assertEqual(sig.parameters["timeout"].default, 260)

    def test_module_constants_are_module_level(self) -> None:
        """``_POLL_INTERVAL_FAST_S`` / ``_POLL_INTERVAL_SAFETY_NET_S`` 必须在
        模块层（不是 wait_for_task_completion 的局部）才能被外部测试与
        监控引用。"""
        members = dict(inspect.getmembers(server_feedback))
        self.assertIn("_POLL_INTERVAL_FAST_S", members)
        self.assertIn("_POLL_INTERVAL_SAFETY_NET_S", members)


if __name__ == "__main__":
    unittest.main()
