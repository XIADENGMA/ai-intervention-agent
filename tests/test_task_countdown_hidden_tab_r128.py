"""R128 · 任务倒计时在 ``document.hidden`` 时跳过 DOM 写入 + visibility 切回时立即同步。

背景
----
R460 之前，``static/js/multi_task.js::startTaskCountdown`` 给每个并发任务装一个
``setInterval(..., 1000)``，每秒做：

- ``getElementById('countdown-${taskId}')``
- ``.querySelector('circle')``
- ``.querySelector('.countdown-number')``
- ``circle.setAttribute('stroke-dashoffset', offset)``
- ``numberSpan.textContent = remaining``
- ``countdownRing.title = _t(...)``
- 如果是活跃任务，再 ``updateCountdownDisplay(remaining)``

这套 DOM 写入在用户切走标签页时**完全是浪费**——浏览器把 1Hz interval
节流到 ~1Hz 但**不会停 callback**，每个 tick 仍走 Layout/Paint phase
（哪怕没有像素被绘制，DOM mutation 仍触发 reflow recompute）。N 个并
发任务 + 用户切走 5 分钟 = ``N × 300`` 次冗余 DOM 操作，对长时间挂在
后台等待 AI 反馈的"侧边栏式" workflow 影响显著。

R128/R460 的修复策略：

1. R460 把 N 个 per-task interval 收敛为一个 ``tickAllTaskCountdowns``
   共享 1Hz ticker；``tickTaskCountdown`` 内把所有 DOM 写入框在
   ``if (!document.hidden) { ... }`` 内；``calculateTaskCountdownRemaining``
   仍正常执行（deadline 是绝对时间，autoSubmit 的判定不能因为页面 hidden
   而推迟）。
2. 安装一个 process-scope 的 ``visibilitychange`` handler，在 visible
   边沿事件上调用 ``forceUpdateAllTaskCountdowns``，让所有 alive timer
   立即同步一次 SVG 圆环 / 数字 / 主倒计时——避免用户切回标签页瞬间
   看到"切走那一刻的旧数字停留 0-1s"。

本测试覆盖五个层面：

1.  **源码不变量**：``tickTaskCountdown`` body 包含
    ``document.hidden`` 检查，且 DOM 写入分支被框在
    ``if (!documentHidden) { ... }`` 内；``calculateTaskCountdownRemaining``
    必须在该 if 之外（保持每秒更新）。
2.  **autoSubmit 仍然触发**：``remaining <= 0`` 的 if-block 必须
    位于 ``if (!documentHidden)`` 之外——"页面隐藏期间到期的任务
    不能延迟提交"。
3.  **forceUpdate helper 存在 + 行为正确**：
    ``forceUpdateAllTaskCountdowns`` 函数体存在；``hidden``
    时早返回；遍历 ``taskCountdowns``。
4.  **install once 幂等**：``installCountdownVisibilitySyncHandlerOnce``
    用 ``window.tasksCountdownVisibilityHandlerInstalled`` flag 守护，
    重复调用不会装第二个 listener。
5.  **module export 暴露**：``window.multiTaskModule`` 同时导出
    ``forceUpdateAllTaskCountdowns`` 与
    ``installCountdownVisibilitySyncHandlerOnce``。
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
MULTI_TASK_JS = (
    REPO_ROOT / "src" / "ai_intervention_agent" / "static" / "js" / "multi_task.js"
)


def _read_source() -> str:
    assert MULTI_TASK_JS.is_file(), f"multi_task.js 缺失: {MULTI_TASK_JS}"
    return MULTI_TASK_JS.read_text(encoding="utf-8")


def _extract_named_function_body(source: str, name: str) -> str:
    """提取 ``function name() { ... }`` 的函数体（含大括号）。

    采用括号配对扫描，跳过字符串/注释，避免 docstring/字符串里出现
    ``{`` ``}`` 干扰。
    """
    candidates = [
        f"function {name}(",
        f"async function {name}(",
    ]
    start = -1
    for marker in candidates:
        pos = source.find(marker)
        if pos >= 0:
            start = pos
            break
    assert start >= 0, f"找不到函数定义: {name}"
    brace_open = source.find("{", start)
    assert brace_open >= 0, f"{name} 缺少 '{{'"

    depth = 0
    in_str: str | None = None
    in_template = False
    in_line_comment = False
    in_block_comment = False
    i = brace_open
    while i < len(source):
        ch = source[i]
        nxt = source[i + 1] if i + 1 < len(source) else ""

        if in_line_comment:
            if ch == "\n":
                in_line_comment = False
            i += 1
            continue
        if in_block_comment:
            if ch == "*" and nxt == "/":
                in_block_comment = False
                i += 2
                continue
            i += 1
            continue
        if in_str is not None:
            if ch == "\\":
                i += 2
                continue
            if ch == in_str:
                in_str = None
            i += 1
            continue
        if in_template:
            if ch == "\\":
                i += 2
                continue
            if ch == "`":
                in_template = False
            i += 1
            continue

        if ch == "/" and nxt == "/":
            in_line_comment = True
            i += 2
            continue
        if ch == "/" and nxt == "*":
            in_block_comment = True
            i += 2
            continue
        if ch in ('"', "'"):
            in_str = ch
            i += 1
            continue
        if ch == "`":
            in_template = True
            i += 1
            continue

        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return source[brace_open : i + 1]
        i += 1

    raise AssertionError(f"{name} 函数体没有正确闭合")


# ---------------------------------------------------------------------------
# 1. tickTaskCountdown 源码不变量
# ---------------------------------------------------------------------------


class TestTaskCountdownTickHiddenSkipsDOM(unittest.TestCase):
    """共享 ticker 的 ``tickTaskCountdown`` 必须在 hidden 时跳过 DOM 操作。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.source = _read_source()
        cls.body = _extract_named_function_body(cls.source, "tickTaskCountdown")

    def test_body_checks_document_hidden(self) -> None:
        """函数体里必须显式检查 ``document.hidden``——这是 hidden-tab CPU 优化的核心信号。"""
        self.assertRegex(
            self.body,
            r"document\.hidden",
            "tickTaskCountdown 必须检查 document.hidden 才能跳过隐藏时的 DOM 写入",
        )

    def test_dom_writes_gated_by_documenthidden_flag(self) -> None:
        """所有 DOM 写入分支必须被 ``if (!documentHidden)`` 守护。"""
        # 应当至少有一处 ``if (!documentHidden)`` 形态（或等价），围住 DOM 写入
        self.assertRegex(
            self.body,
            r"if\s*\(\s*!documentHidden\s*\)",
            "DOM 写入必须在 if (!documentHidden) 守护下，否则 hidden tab 仍走 reflow",
        )

    def test_calculate_remaining_runs_outside_hidden_guard(self) -> None:
        """``calculateTaskCountdownRemaining`` 必须在 ``if (!documentHidden)`` 之**前**调用。

        why：deadline 是绝对时间，autoSubmit 的判定不能因为页面 hidden
        而推迟一秒（会让到期任务被推迟 0-N 秒提交）。
        """
        calc_idx = self.body.find("calculateTaskCountdownRemaining(taskId, entry)")
        guard_idx = self.body.find("if (!documentHidden)")
        self.assertGreater(calc_idx, -1, "找不到 calculateTaskCountdownRemaining 调用")
        self.assertGreater(guard_idx, -1, "找不到 if (!documentHidden) 守护")
        self.assertLess(
            calc_idx,
            guard_idx,
            "calculateTaskCountdownRemaining 必须在 hidden 守护之前调用（deadline 是绝对时间，"
            "autoSubmit 判定不能因隐藏而推迟）",
        )


class TestAutoSubmitRunsEvenWhenHidden(unittest.TestCase):
    """倒计时归零的 autoSubmit 路径必须**不**被 hidden 守护框住。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.body = _extract_named_function_body(_read_source(), "tickTaskCountdown")

    def test_auto_submit_branch_not_inside_hidden_guard(self) -> None:
        """``if (taskCountdowns[taskId].remaining <= 0)`` 必须在 ``if (!documentHidden)`` 之外。"""
        guard_idx = self.body.find("if (!documentHidden)")
        # 找 autoSubmit 的 if-block 起点。这里用 ``remaining <= 0`` 字面量定位
        timeout_idx = self.body.find("remaining <= 0")
        self.assertGreater(guard_idx, -1, "找不到 if (!documentHidden) 守护")
        self.assertGreater(timeout_idx, -1, "找不到 remaining <= 0 timeout 判定")

        # 在 guard 之后的右大括号位置，应该早于 timeout_idx
        # 用括号配对找 guard block 的结束 ``}``
        depth = 0
        i = self.body.find("{", guard_idx)
        guard_end = -1
        while i < len(self.body):
            ch = self.body[i]
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    guard_end = i
                    break
            i += 1
        self.assertGreater(guard_end, -1, "if (!documentHidden) 块没有正确闭合")
        self.assertGreater(
            timeout_idx,
            guard_end,
            "timeout 判定必须在 hidden 守护块之后，否则隐藏期间到期的任务"
            "会被延迟提交（违反 autoSubmit 即时性）",
        )


# ---------------------------------------------------------------------------
# 2. forceUpdateAllTaskCountdowns helper
# ---------------------------------------------------------------------------


class TestForceUpdateHelperContract(unittest.TestCase):
    """``forceUpdateAllTaskCountdowns`` 必须存在并具有正确语义。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.source = _read_source()

    def test_helper_function_defined(self) -> None:
        self.assertIn(
            "function forceUpdateAllTaskCountdowns()",
            self.source,
            "R128 后必须存在 forceUpdateAllTaskCountdowns 函数",
        )

    def test_helper_early_returns_when_hidden(self) -> None:
        body = _extract_named_function_body(self.source, "forceUpdateAllTaskCountdowns")
        self.assertRegex(
            body,
            r"document\.hidden\s*\)\s*return",
            "forceUpdateAllTaskCountdowns 必须在 hidden 时早返回（避免被错误"
            "调用时仍写 DOM）",
        )

    def test_helper_iterates_taskcountdowns(self) -> None:
        body = _extract_named_function_body(self.source, "forceUpdateAllTaskCountdowns")
        self.assertIn(
            "for (const tid in taskCountdowns)",
            body,
            "forceUpdateAllTaskCountdowns 必须遍历 taskCountdowns 才能强刷所有任务",
        )
        self.assertIn(
            "Object.prototype.hasOwnProperty.call(taskCountdowns, tid)",
            body,
            "forceUpdateAllTaskCountdowns 使用 for...in 时必须过滤 inherited keys",
        )
        self.assertNotIn(
            "Object.keys(taskCountdowns)",
            body,
            "forceUpdateAllTaskCountdowns 不应在可见 resync 时创建 Object.keys 数组",
        )


# ---------------------------------------------------------------------------
# 3. installCountdownVisibilitySyncHandlerOnce 幂等
# ---------------------------------------------------------------------------


class TestInstallOnceIdempotent(unittest.TestCase):
    """``installCountdownVisibilitySyncHandlerOnce`` 必须用 flag 守护避免重复安装。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.source = _read_source()

    def test_install_function_defined(self) -> None:
        self.assertIn(
            "function installCountdownVisibilitySyncHandlerOnce()",
            self.source,
        )

    def test_install_uses_flag_guard(self) -> None:
        body = _extract_named_function_body(
            self.source, "installCountdownVisibilitySyncHandlerOnce"
        )
        self.assertRegex(
            body,
            r"window\.tasksCountdownVisibilityHandlerInstalled",
            "installCountdownVisibilitySyncHandlerOnce 必须用 "
            "window.tasksCountdownVisibilityHandlerInstalled flag 守护，"
            "否则 startTaskCountdown 反复调用会装多个 listener",
        )

    def test_install_attaches_visibilitychange(self) -> None:
        body = _extract_named_function_body(
            self.source, "installCountdownVisibilitySyncHandlerOnce"
        )
        self.assertIn(
            'addEventListener("visibilitychange"',
            body,
            "installCountdownVisibilitySyncHandlerOnce 必须注册 visibilitychange",
        )

    def test_install_handler_calls_force_update_on_visible(self) -> None:
        body = _extract_named_function_body(
            self.source, "installCountdownVisibilitySyncHandlerOnce"
        )
        self.assertIn(
            "forceUpdateAllTaskCountdowns()",
            body,
            "visibilitychange handler 必须在 visible 边沿调用 "
            "forceUpdateAllTaskCountdowns 才能消除 0-1s 切回 UI 延迟",
        )

    def test_global_flag_default_false(self) -> None:
        """``window.tasksCountdownVisibilityHandlerInstalled`` 必须有 ``= false`` 的默认初始化。"""
        self.assertRegex(
            self.source,
            r"window\.tasksCountdownVisibilityHandlerInstalled\s*=\s*false",
            "必须给 window.tasksCountdownVisibilityHandlerInstalled 提供默认 "
            "false 初始化（与文件顶部其他 flag 保持对称）",
        )


# ---------------------------------------------------------------------------
# 4. startTaskCountdown 安装路径
# ---------------------------------------------------------------------------


class TestStartTaskCountdownInstallsHandler(unittest.TestCase):
    """``startTaskCountdown`` 必须在每次启动时调用 installCountdownVisibilitySyncHandlerOnce。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.body = _extract_named_function_body(_read_source(), "startTaskCountdown")

    def test_install_called_in_start(self) -> None:
        self.assertIn(
            "installCountdownVisibilitySyncHandlerOnce()",
            self.body,
            "startTaskCountdown 必须调用 installCountdownVisibilitySyncHandlerOnce()，"
            "否则 visibility 切回不会触发 forceUpdate",
        )


# ---------------------------------------------------------------------------
# 5. R460 shared countdown ticker
# ---------------------------------------------------------------------------


class TestSharedCountdownTicker(unittest.TestCase):
    """R460：所有任务倒计时必须复用一个页面级 1Hz ticker。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.source = _read_source()
        cls.start_body = _extract_named_function_body(cls.source, "startTaskCountdown")
        cls.ensure_body = _extract_named_function_body(
            cls.source, "ensureSharedTaskCountdownTicker"
        )
        cls.tick_all_body = _extract_named_function_body(
            cls.source, "tickAllTaskCountdowns"
        )

    def test_start_marks_entry_with_shared_timer_sentinel(self) -> None:
        self.assertIn(
            "timer: TASK_COUNTDOWN_SHARED_TIMER_SENTINEL",
            self.start_body,
            "startTaskCountdown 应写入共享 ticker sentinel，而不是 per-task interval id",
        )

    def test_start_ensures_shared_ticker(self) -> None:
        self.assertIn(
            "ensureSharedTaskCountdownTicker()",
            self.start_body,
            "startTaskCountdown 必须启动页面级共享 ticker",
        )

    def test_shared_ticker_is_the_only_countdown_interval(self) -> None:
        self.assertIn(
            "setInterval(tickAllTaskCountdowns, 1000)",
            self.ensure_body,
            "R460 期望唯一 1Hz countdown interval 位于 ensureSharedTaskCountdownTicker",
        )
        self.assertNotIn(
            "setInterval(",
            self.start_body,
            "startTaskCountdown 不能再为每个任务创建独立 setInterval",
        )

    def test_tick_all_iterates_taskcountdowns(self) -> None:
        self.assertIn(
            "for (const taskId in taskCountdowns)",
            self.tick_all_body,
            "tickAllTaskCountdowns 必须遍历 taskCountdowns 来驱动所有任务倒计时",
        )
        self.assertIn(
            "Object.prototype.hasOwnProperty.call(taskCountdowns, taskId)",
            self.tick_all_body,
            "tickAllTaskCountdowns 使用 for...in 时必须过滤 inherited keys",
        )
        self.assertNotIn(
            "Object.keys(taskCountdowns)",
            self.tick_all_body,
            "tickAllTaskCountdowns 不应每秒创建 Object.keys 数组",
        )


# ---------------------------------------------------------------------------
# 6. module export 暴露
# ---------------------------------------------------------------------------


class TestModuleExportSurface(unittest.TestCase):
    """``window.multiTaskModule`` 必须导出 forceUpdate 与 install once。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.source = _read_source()

    def test_exports_force_update(self) -> None:
        """export object 字面量里必须出现 ``forceUpdateAllTaskCountdowns,``。"""
        # 用宽松正则避免空白格式干扰
        match = re.search(
            r"window\.multiTaskModule\s*=\s*\{[\s\S]*?forceUpdateAllTaskCountdowns"
            r"[\s\S]*?\}",
            self.source,
        )
        self.assertIsNotNone(
            match,
            "window.multiTaskModule 必须导出 forceUpdateAllTaskCountdowns，"
            "否则单元测试无法直接驱动 UI sync 路径",
        )

    def test_exports_install_once(self) -> None:
        match = re.search(
            r"window\.multiTaskModule\s*=\s*\{[\s\S]*?installCountdownVisibilitySyncHandlerOnce"
            r"[\s\S]*?\}",
            self.source,
        )
        self.assertIsNotNone(
            match,
            "window.multiTaskModule 必须导出 "
            "installCountdownVisibilitySyncHandlerOnce，便于"
            "嵌入场景显式控制 listener 安装时机",
        )


if __name__ == "__main__":
    unittest.main()
