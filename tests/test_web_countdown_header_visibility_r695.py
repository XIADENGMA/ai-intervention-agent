"""R695 回归护栏：Web 端倒计时控件可见性 + 冻结语义。

背景（运行时验证发现的两个缺陷）：

1. **控件永久不可见**：``#task-header-chip``、``+60s`` 延长按钮、冻结按钮
   的 DOM 锚点全部位于 ``.header-info-container`` 内，而 ``main.css`` 曾对
   该容器无条件 ``display: none``——三个功能在 Web 端永远不可见（仅
   VS Code 端可用），与 README 宣称的两端一致不符。
2. **冻结即自动提交**：冻结成功路径只把 countdown 条目的
   ``remaining/timeout`` 置 0 但保留条目；同时 ``loadTaskDetails`` 与新任务
   路径会为 ``auto_resubmit_timeout <= 0`` 的任务以 remaining=0 重建倒计时。
   两者叠加导致下一个 1Hz tick 触发 ``autoSubmitTask``——点击冻结的任务在
   约 1-2 秒内被自动提交，与冻结语义完全相反。

本文件锁定修复后的源码形态，防止未来重构倒退。
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
STATIC_DIR = REPO_ROOT / "src" / "ai_intervention_agent" / "static"
JS_PATH = STATIC_DIR / "js" / "multi_task.js"
CSS_PATH = STATIC_DIR / "css" / "main.css"
HTML_PATH = REPO_ROOT / "src" / "ai_intervention_agent" / "templates" / "web_ui.html"


class TestHeaderContainerVisible(unittest.TestCase):
    """``.header-info-container`` 不得再被无条件隐藏。"""

    def setUp(self) -> None:
        self.css = CSS_PATH.read_text(encoding="utf-8")

    def _rule_body(self, selector: str) -> str:
        idx = self.css.find(selector + " {")
        self.assertGreater(idx, 0, f"selector missing: {selector}")
        end = self.css.find("}", idx)
        return self.css[idx:end]

    def test_header_info_container_not_display_none(self) -> None:
        body = self._rule_body(".header-info-container")
        self.assertNotIn("display: none", body)

    def test_header_info_container_is_flex_row(self) -> None:
        body = self._rule_body(".header-info-container")
        self.assertIn("display: flex", body)

    def test_task_id_container_stays_hidden(self) -> None:
        """任务 ID 在标签页展示，容器本体保持隐藏避免重复。"""
        body = self._rule_body(".task-id-container")
        self.assertIn("display: none", body)


class TestHeaderChipOutsideTaskIdContainer(unittest.TestCase):
    """chip 锚点必须位于被隐藏的 ``.task-id-container`` 之外。"""

    def setUp(self) -> None:
        self.html = HTML_PATH.read_text(encoding="utf-8")

    def test_chip_anchor_present(self) -> None:
        self.assertIn('id="task-header-chip"', self.html)

    def test_chip_precedes_task_id_container(self) -> None:
        chip_idx = self.html.find('id="task-header-chip"')
        tid_idx = self.html.find('id="task-id-container"')
        self.assertGreater(chip_idx, 0)
        self.assertGreater(tid_idx, 0)
        self.assertLess(
            chip_idx,
            tid_idx,
            "chip 必须排在 .task-id-container 之前（并列，不得嵌套其中）",
        )


class TestFreezeClearsCountdownEntry(unittest.TestCase):
    """冻结成功路径必须整体注销 countdown 条目。"""

    def setUp(self) -> None:
        self.js = JS_PATH.read_text(encoding="utf-8")

    def test_freeze_success_calls_clear_task_countdown(self) -> None:
        idx = self.js.find("function handleFreezeCountdownClick()")
        self.assertGreater(idx, 0)
        body = self.js[idx : idx + 4000]
        self.assertIn("_clearTaskCountdown(taskId)", body)

    def test_freeze_success_no_zeroed_entry_left(self) -> None:
        """不允许回退到「只置 0 保留条目」的旧写法。"""
        idx = self.js.find("function handleFreezeCountdownClick()")
        body = self.js[idx : idx + 4000]
        self.assertNotIn("cd.remaining = 0", body)


class TestStartCountdownGuardsDisabledTimeout(unittest.TestCase):
    """所有 startTaskCountdown 调用点必须先排除 timeout <= 0 的任务。"""

    def setUp(self) -> None:
        self.js = JS_PATH.read_text(encoding="utf-8")

    def test_load_task_details_guard(self) -> None:
        """新任务与 loadTaskDetails 路径：显式禁用的任务不得重建倒计时。"""
        pattern = re.compile(
            r"TimeoutDisabled =\s*\n?\s*"
            r"typeof task\.auto_resubmit_timeout === \"number\" &&\s*\n?\s*"
            r"task\.auto_resubmit_timeout <= 0"
        )
        self.assertGreaterEqual(
            len(pattern.findall(self.js)),
            2,
            "新任务路径与 loadTaskDetails 路径都必须带显式禁用守卫",
        )
        self.assertIn("!addedTimeoutDisabled", self.js)
        self.assertIn("!detailsTimeoutDisabled", self.js)

    def test_hot_reload_fallback_still_clears_disabled(self) -> None:
        """热更新兜底路径保留「禁用则清理倒计时」分支。"""
        idx = self.js.find("// 禁用：确保不启动倒计时")
        self.assertGreater(idx, 0)
        snippet = self.js[idx : idx + 200]
        self.assertIn("_clearTaskCountdown(task.task_id)", snippet)


if __name__ == "__main__":
    unittest.main()
