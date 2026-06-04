"""BUG5 回归契约：后台仍运行但 web 页面无法显示的鲁棒性修复。

背景：用户报告"有时候会后台还在运行，但是 web 页面已经无法显示了"。
深入分析 ``static/js/multi_task.js`` 后定位到两个相邻 root cause：

1. **init 链路脆弱**：``initMultiTaskSupport`` 中 ``await Promise.all([
   fetchFeedbackPromptsFresh(), refreshTasksList()])`` 任一 reject 会让
   整个 init 函数抛出 → **后续 ``startTasksPolling`` + ``startTasksHealthCheck``
   永远不会被调用** → 页面卡在初始 loading 状态，即便后端恢复也不会
   自动重连（无 polling / 无健康检查 / 无 SSE）。
2. **缺少 ``online`` 事件监听**：浏览器从离线变在线（笔记本休眠唤醒、
   WiFi 切换、后端外部断电恢复）时，web UI 必须等下一个 30s 健康检查
   tick 才能重连，体验差。VSCode webview-ui.js 已有此监听，web 端
   长期缺失，双端 UX 不一致。

修复策略：
1. 把 ``Promise.all`` 改成 ``Promise.allSettled`` + try/catch 双层兜底，
   确保 init 主流程始终能跑到 ``startTasksPolling`` + ``startTasksHealthCheck``。
2. 在 visibilitychange handler 安装路径同时注册 ``window.addEventListener
   ('online', ...)``，网络恢复时立即触发 startTasksPolling + startTasksHealthCheck。

本测试通过静态扫描锁住上述契约。
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
MULTI_TASK_JS = (
    REPO_ROOT / "src" / "ai_intervention_agent" / "static" / "js" / "multi_task.js"
)


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def _strip_js_comments(source: str) -> str:
    """剥除 JS 单行 ``// ...`` 与块 ``/* ... */`` 注释，保留代码主体。

    复用自 ``test_bug4_icon_cache_and_badge.py`` 的同名 helper（避免跨测试
    文件引入，本测试也用得到）。状态机字符级处理，足够本场景使用。
    """
    out: list[str] = []
    i = 0
    n = len(source)
    in_string: str | None = None
    in_line_comment = False
    in_block_comment = False
    while i < n:
        ch = source[i]
        nxt = source[i + 1] if i + 1 < n else ""
        if in_line_comment:
            if ch == "\n":
                in_line_comment = False
                out.append(ch)
        elif in_block_comment:
            if ch == "*" and nxt == "/":
                in_block_comment = False
                i += 1
        elif in_string is not None:
            out.append(ch)
            if ch == "\\":
                if i + 1 < n:
                    out.append(source[i + 1])
                    i += 1
            elif ch == in_string:
                in_string = None
        else:
            if ch == "/" and nxt == "/":
                in_line_comment = True
                i += 1
            elif ch == "/" and nxt == "*":
                in_block_comment = True
                i += 1
            elif ch in ('"', "'", "`"):
                in_string = ch
                out.append(ch)
            else:
                out.append(ch)
        i += 1
    return "".join(out)


class TestInitUsesAllSettledNotAll(unittest.TestCase):
    """``initMultiTaskSupport`` 必须用 ``Promise.allSettled`` 而非 ``Promise.all``。

    Promise.all 在任一 reject 时整个抛出；而 Promise.allSettled 始终 resolve
    一个数组，能保证后续 polling + 健康检查启动路径一定被执行。
    """

    def setUp(self) -> None:
        self.source = _read(MULTI_TASK_JS)

    def _extract_init_body(self) -> str:
        # 提取 initMultiTaskSupport 函数体（用大括号配对）
        start_marker = "async function initMultiTaskSupport()"
        idx = self.source.find(start_marker)
        self.assertGreaterEqual(idx, 0, "找不到 initMultiTaskSupport 函数")
        open_brace = self.source.find("{", idx)
        self.assertGreaterEqual(open_brace, 0)
        depth = 1
        i = open_brace + 1
        in_string = None
        in_line_comment = False
        in_block_comment = False
        while i < len(self.source) and depth > 0:
            ch = self.source[i]
            nxt = self.source[i + 1] if i + 1 < len(self.source) else ""
            if in_line_comment:
                if ch == "\n":
                    in_line_comment = False
            elif in_block_comment:
                if ch == "*" and nxt == "/":
                    in_block_comment = False
                    i += 1
            elif in_string is not None:
                if ch == "\\":
                    i += 1
                elif ch == in_string:
                    in_string = None
            else:
                if ch == "/" and nxt == "/":
                    in_line_comment = True
                    i += 1
                elif ch == "/" and nxt == "*":
                    in_block_comment = True
                    i += 1
                elif ch in ('"', "'", "`"):
                    in_string = ch
                elif ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0:
                        return self.source[open_brace + 1 : i]
            i += 1
        self.fail("initMultiTaskSupport 大括号未平衡")
        return ""

    def test_init_uses_promise_all_settled(self) -> None:
        body = self._extract_init_body()
        self.assertIn(
            "Promise.allSettled",
            body,
            "initMultiTaskSupport 必须用 Promise.allSettled（任一 reject 不阻塞）；"
            "Promise.all 会让初始 fetch 失败时整个 init 抛出，后续 polling + "
            "健康检查永远不会启动，页面卡在 loading 状态",
        )

    def test_init_does_not_use_promise_all(self) -> None:
        """禁止裸 ``Promise.all`` 出现在 init 函数体（除非作为 ``Promise.allSettled`` 的子串）。"""
        body = _strip_js_comments(self._extract_init_body())
        bad_uses = re.findall(r"Promise\.all\b(?!Settled)", body)
        self.assertEqual(
            len(bad_uses),
            0,
            f"initMultiTaskSupport 函数体内不应出现裸 Promise.all（不带 Settled）调用，"
            f"找到 {len(bad_uses)} 处：必须改用 Promise.allSettled 保证 init 鲁棒",
        )

    def test_init_wraps_settled_in_try_catch(self) -> None:
        """Promise.allSettled 调用必须被 try/catch 包裹（双层兜底）。"""
        body = self._extract_init_body()
        settled_match = re.search(r"Promise\.allSettled\(", body)
        assert settled_match is not None, (
            "BUG5 修复后 init body 必须包含 Promise.allSettled"
        )
        preceding = body[: settled_match.start()]
        last_200 = preceding[-200:] if len(preceding) > 200 else preceding
        self.assertIn(
            "try {",
            last_200,
            "Promise.allSettled 必须包裹在 try { ... } 内做双层兜底，"
            "防御极端情况下 allSettled 自身因环境问题失败",
        )

    def test_init_starts_polling_after_fetch_block(self) -> None:
        """init 函数必须在 fetch 块之后调用 startTasksPolling 和 startTasksHealthCheck。"""
        body = self._extract_init_body()
        self.assertIn(
            "startTasksPolling()",
            body,
            "initMultiTaskSupport 必须调用 startTasksPolling()",
        )
        self.assertIn(
            "startTasksHealthCheck()",
            body,
            "initMultiTaskSupport 必须调用 startTasksHealthCheck()",
        )
        # 顺序断言：fetch 块 → polling → healthCheck
        settled_idx = body.find("Promise.allSettled")
        poll_idx = body.find("startTasksPolling()")
        health_idx = body.find("startTasksHealthCheck()")
        self.assertGreater(poll_idx, settled_idx)
        self.assertGreater(health_idx, settled_idx)


class TestOnlineEventRecovery(unittest.TestCase):
    """``window`` 必须监听 ``online`` 事件，网络恢复时立即重启 polling + 健康检查。"""

    def setUp(self) -> None:
        self.source = _read(MULTI_TASK_JS)

    def test_online_listener_present(self) -> None:
        # 同时接受单/双引号字面量
        self.assertRegex(
            self.source,
            r"window\.addEventListener\(\s*['\"]online['\"]",
            "multi_task.js 必须监听 window 'online' 事件，网络恢复时立即重连；"
            "否则需要等下一个 30s 健康检查 tick 才能恢复，体验差",
        )

    def test_online_handler_restarts_polling(self) -> None:
        """``online`` 事件 handler body 必须调用 startTasksPolling 与 startTasksHealthCheck。"""
        match = re.search(
            r"window\.addEventListener\(\s*['\"]online['\"]\s*,\s*function\s*\([^)]*\)\s*\{(?P<body>.*?)\n\s*\}",
            self.source,
            re.DOTALL,
        )
        assert match is not None, "无法定位 online handler 函数体"
        body = match.group("body")
        self.assertIn(
            "startTasksPolling()",
            body,
            "'online' handler 必须调用 startTasksPolling()",
        )
        self.assertIn(
            "startTasksHealthCheck()",
            body,
            "'online' handler 必须调用 startTasksHealthCheck()",
        )

    def test_online_handler_respects_document_hidden(self) -> None:
        """``online`` handler 必须先检查 ``document.hidden``，避免后台标签页无谓重连。"""
        match = re.search(
            r"window\.addEventListener\(\s*['\"]online['\"]\s*,\s*function\s*\([^)]*\)\s*\{(?P<body>.*?)\n\s*\}",
            self.source,
            re.DOTALL,
        )
        assert match is not None, "无法定位 online handler 函数体"
        body = match.group("body")
        self.assertIn(
            "document.hidden",
            body,
            "'online' handler 应检查 document.hidden，避免后台标签页被网络恢复"
            "事件唤醒成 active polling（visibilitychange handler 会负责真正可见时的重连）",
        )

    def test_online_listener_wrapped_in_try_catch(self) -> None:
        """``online`` 监听器注册必须被 try/catch 包裹（防御极简测试环境下 addEventListener 抛错）。"""
        # 找到 online 监听器附近 300 字符内必须有 try {
        idx = self.source.find('"online"')
        if idx < 0:
            idx = self.source.find("'online'")
        self.assertGreaterEqual(idx, 0)
        window_start = max(0, idx - 300)
        preceding = self.source[window_start:idx]
        self.assertIn(
            "try {",
            preceding,
            "online 监听器注册应被 try { ... } 包裹，避免极简浏览器/测试 stub 下"
            "addEventListener 抛错而破坏 init 主流程",
        )


class TestBug5DocumentationAnchor(unittest.TestCase):
    """注释中必须有 BUG5 锚点，便于后续维护者追溯。"""

    def test_bug5_documented(self) -> None:
        source = _read(MULTI_TASK_JS)
        self.assertIn(
            "BUG5",
            source,
            "multi_task.js 应在 initMultiTaskSupport / online listener 附近注释中"
            "标注 'BUG5' 锚点，方便追溯设计动机",
        )


if __name__ == "__main__":
    unittest.main()
