r"""锁定 debounceSaveFeedback 的「累积」语义：800ms 窗口内多个字段不能互相覆盖。

历史 bug
---------
``static/js/settings-manager.js`` 与 ``packages/vscode/webview-settings-ui.js``
原始实现：

    let timer = null
    const debounceSaveFeedback = updates => {
      if (timer) clearTimeout(timer)
      timer = setTimeout(() => saveFeedbackConfig(updates), 800)
    }

闭包对 ``updates`` 的捕获让每次新调用直接**丢弃**前一次的 ``updates``：

  T=0    用户改 frontend_countdown=60   → setTimeout(1, updates={c:60}, at 800)
  T=300  用户改 resubmit_prompt="新"    → clearTimeout(1)，
                                            setTimeout(2, updates={p:"新"}, at 1100)
  T=1100 saveFeedbackConfig({p:"新"})   → frontend_countdown=60 永久丢失

修复
----
每次调用 merge 进 ``pendingUpdates``，timer 真正触发时一次性 POST：

    let timer = null
    let pendingUpdates = null
    const debounceSaveFeedback = updates => {
      if (timer) clearTimeout(timer)
      pendingUpdates = Object.assign(pendingUpdates || {}, updates || {})
      timer = setTimeout(() => {
        const merged = pendingUpdates
        pendingUpdates = null
        timer = null
        saveFeedbackConfig(merged)
      }, 800)
    }

合约（被本测试锁定）
--------------------
- ``static/js/settings-manager.js`` 与 ``packages/vscode/webview-settings-ui.js``
  各自有一个 ``Pending(?:Updates)?`` 变量名，且 ``debounceSaveFeedback`` 体里
  必须出现 ``Object.assign(`` 模式（保证累积写入）。
- 两份代码必须**同步**修改；任何一份退化成 ``setTimeout(...saveFeedbackConfig(updates))``
  形式（即在 ``debounceSaveFeedback`` 体内直接把 ``updates`` 喂给 ``saveFeedbackConfig``）
  都会被本测试 catch。
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
WEB_FILE = REPO_ROOT / "static" / "js" / "settings-manager.js"
VSCODE_FILE = REPO_ROOT / "packages" / "vscode" / "webview-settings-ui.js"


def _extract_debounce_block(text: str) -> str:
    """切出 ``const debounceSaveFeedback = updates => { ... }`` 函数体。

    取**最后**一个匹配，避免误匹配注释里复制的旧实现（修复版往往会
    在注释里保留 ``const debounceSaveFeedback = updates =>`` 历史片段
    作为反例对照）。两份修复后的函数体都 < 600 字符，slice 足以覆盖。
    """
    matches = list(
        re.finditer(r"const\s+debounceSaveFeedback\s*=\s*updates\s*=>", text)
    )
    if not matches:
        return ""
    start = matches[-1].end()
    return text[start : start + 600]


class TestDebounceSaveFeedbackAccumulates(unittest.TestCase):
    """两份 JS 必须用累积模式而不是丢弃模式。"""

    def _assert_accumulating_pattern(self, file_path: Path, label: str) -> None:
        text = file_path.read_text(encoding="utf-8")
        body = _extract_debounce_block(text)
        self.assertNotEqual(
            body,
            "",
            f"{label}: 找不到 `const debounceSaveFeedback = updates =>` "
            "声明——可能函数被重构，本测试正则需要更新",
        )

        self.assertRegex(
            body,
            r"Object\.assign\s*\(",
            f"{label}: debounceSaveFeedback 体内必须用 `Object.assign(...)` "
            f"累积 updates；旧的 `setTimeout(() => save(updates))` 形式会让 "
            f"800ms 窗口内的连续字段修改互相覆盖（详见模块 docstring 重现步骤）。"
            f"\n实际函数体（前 600 字符）:\n{body}",
        )

        self.assertRegex(
            body,
            r"[Pp]ending(?:Updates)?",
            f"{label}: 必须有一个名字带 `Pending` 的累积变量；旧实现没有任何"
            f"持久化 buffer，新实现的合约就是这个 buffer。"
            f"\n实际函数体（前 600 字符）:\n{body}",
        )

        self.assertNotRegex(
            body,
            r"setTimeout\s*\([^)]*saveFeedbackConfig\s*\(\s*updates\s*\)",
            f"{label}: 检测到 `setTimeout(... saveFeedbackConfig(updates))` 形式，"
            f"这会让闭包捕获最后一次调用的 `updates`，前面的字段修改全部丢弃。"
            f"必须改成 `saveFeedbackConfig(merged)` 或 "
            f"`saveFeedbackConfig(pendingUpdates)`。"
            f"\n实际函数体（前 600 字符）:\n{body}",
        )

    def test_web_settings_manager_accumulates(self) -> None:
        self._assert_accumulating_pattern(WEB_FILE, "static/js/settings-manager.js")

    def test_vscode_settings_ui_accumulates(self) -> None:
        self._assert_accumulating_pattern(
            VSCODE_FILE, "packages/vscode/webview-settings-ui.js"
        )

    def test_web_and_vscode_pattern_parity(self) -> None:
        """两份代码必须**同步**修复；只改一边等于又埋一颗 parity drift 雷。"""
        web_body = _extract_debounce_block(WEB_FILE.read_text(encoding="utf-8"))
        vsc_body = _extract_debounce_block(VSCODE_FILE.read_text(encoding="utf-8"))

        web_has_assign = bool(re.search(r"Object\.assign\s*\(", web_body))
        vsc_has_assign = bool(re.search(r"Object\.assign\s*\(", vsc_body))
        self.assertEqual(
            web_has_assign,
            vsc_has_assign,
            "Web 与 VSCode 任一份的 debounceSaveFeedback 用了 Object.assign "
            "累积、另一份没有——这是 parity drift；必须同步修复，"
            "否则 web/vscode 行为分歧。",
        )


if __name__ == "__main__":
    unittest.main()
