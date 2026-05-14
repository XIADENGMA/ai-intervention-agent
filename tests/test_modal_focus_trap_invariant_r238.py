"""R238 / Cycle 15: modal dialogs trap Tab focus + restore focus on close.

Why this invariant
------------------

R237 locked the **declarative** ARIA contract on `role="dialog"`
elements (aria-modal, aria-labelledby, hidden default). R238 locks
the **imperative** focus-management contract: when a modal is open,
Tab/Shift-Tab must cycle within it (focus trap), and on close, focus
must return to a sensible element (opener or feedback area).

Why this matters (WCAG / ARIA Authoring Practices 1.2):

* Without a focus trap, keyboard users tabbing through an open modal
  can land on hidden/background controls — confusing and bypasses
  the modal's intended interaction barrier.
* Without focus restore, the focus pointer can be left "nowhere"
  after close (typically falls back to `<body>`), forcing the user
  to start Tab cycle from scratch.

What this test guards
---------------------

For the 2 existing modals (`#code-paste-panel` + `#settings-panel`):

1. Their keydown handlers include a Tab handler (not just Escape).
   Specifically, `app.js` `handleCodePasteModalKeydown` calls
   `_modalFocusTrap`, and `settings-manager.js`
   `_settingsEscHandler` invokes `_settingsFocusTrap` for Tab.
2. The focus-trap helper queries focusable elements with the
   standard selector and pivots between first/last.
3. The close handlers restore focus to the opener (or sensible
   fallback): `closeCodePasteModal` focuses `#feedback-text`;
   `hideSettings` focuses `#settings-btn`.

Patterns
--------

This is Pattern B (cross-file content check) — the test reads JS
files as text and uses regex to assert the presence of the
focus-trap and focus-restore patterns. It does NOT exercise the
JS at runtime (that requires a browser harness); it instead
guarantees the *code* exists, so a future refactor that breaks
the trap will fail the invariant.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
APP_JS = REPO_ROOT / "src" / "ai_intervention_agent" / "static" / "js" / "app.js"
SETTINGS_JS = (
    REPO_ROOT
    / "src"
    / "ai_intervention_agent"
    / "static"
    / "js"
    / "settings-manager.js"
)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


class TestCodePasteModalHasFocusTrap(unittest.TestCase):
    def test_keydown_handler_handles_tab_not_just_escape(self) -> None:
        src = _read(APP_JS)
        match = re.search(
            r"function\s+handleCodePasteModalKeydown\s*\([^)]*\)\s*\{(.+?)\n\}",
            src,
            re.DOTALL,
        )
        assert match is not None, "Cannot find handleCodePasteModalKeydown"
        body = match.group(1)
        self.assertIn(
            "_modalFocusTrap",
            body,
            msg=(
                "R238 invariant: handleCodePasteModalKeydown 必须调用 "
                "_modalFocusTrap (R238 加的 Tab 焦点陷阱)。如果只处理 Escape, "
                "键盘用户 Tab 时会跑到背景元素, 失去模态隔离。"
            ),
        )

    def test_focus_trap_helper_uses_standard_focusable_selector(self) -> None:
        src = _read(APP_JS)
        match = re.search(
            r"function\s+_modalFocusTrap\s*\([^)]*\)\s*\{(.+?)\n\}",
            src,
            re.DOTALL,
        )
        assert match is not None, "_modalFocusTrap helper missing in app.js"
        body = match.group(1)
        for selector in ("button", "input", "textarea", "tabindex"):
            self.assertIn(
                selector,
                body,
                msg=(
                    f"R238 invariant: _modalFocusTrap 焦点选择器必须覆盖 "
                    f"{selector!r} (W3C ARIA Authoring Practices 1.2 标准)。"
                    "缺失会让某类可聚焦元素被遗漏, 导致 Tab 跳过或卡住。"
                ),
            )
        self.assertIn("event.preventDefault()", body)
        self.assertIn("shiftKey", body)

    def test_close_modal_restores_focus(self) -> None:
        src = _read(APP_JS)
        match = re.search(
            r"function\s+closeCodePasteModal\s*\(\)\s*\{(.+?)\n\}",
            src,
            re.DOTALL,
        )
        assert match is not None
        body = match.group(1)
        self.assertIn(
            "feedbackTextarea.focus()",
            body,
            msg=(
                "R238 invariant: closeCodePasteModal 必须把焦点还给 "
                "#feedback-text (modal 触发点的主战场)。不还焦点会让"
                "用户的键盘 cursor 落在 body 上, 必须重新 Tab 才能继续。"
            ),
        )


class TestSettingsPanelHasFocusTrap(unittest.TestCase):
    def test_settings_esc_handler_handles_tab(self) -> None:
        src = _read(SETTINGS_JS)
        self.assertRegex(
            src,
            r'if\s*\(e\.key\s*===\s*"Tab"\)\s*this\._settingsFocusTrap',
            msg=(
                "R238 invariant: settings-manager.js _settingsEscHandler 必须"
                "在 Tab 键时调用 _settingsFocusTrap。当前匹配的 pattern: "
                "if (e.key === 'Tab') this._settingsFocusTrap。"
            ),
        )

    def test_settings_focus_trap_method_exists(self) -> None:
        src = _read(SETTINGS_JS)
        match = re.search(
            r"_settingsFocusTrap\s*\([^)]*\)\s*\{(.+?)\n  \}",
            src,
            re.DOTALL,
        )
        assert match is not None, "_settingsFocusTrap method missing"
        body = match.group(1)
        for selector in ("button", "input", "textarea", "tabindex"):
            self.assertIn(selector, body)
        self.assertIn("preventDefault()", body)

    def test_hide_settings_restores_focus_to_settings_btn(self) -> None:
        src = _read(SETTINGS_JS)
        match = re.search(r"hideSettings\s*\(\)\s*\{(.+?)\n  \}", src, re.DOTALL)
        assert match is not None
        body = match.group(1)
        self.assertRegex(
            body,
            r'getElementById\("settings-btn"\)',
            msg=(
                "R238 invariant: hideSettings() 必须把焦点还给 "
                "#settings-btn (modal 的打开按钮)。"
            ),
        )
        self.assertIn(
            "settingsBtn.focus()",
            body,
            msg="R238 invariant: hideSettings() 必须调用 settingsBtn.focus()",
        )


class TestFocusTrapDoesNotMatchHiddenElements(unittest.TestCase):
    """trap 必须用 offsetParent !== null 之类的可见性判定, 避免把 hidden 元素当焦点。"""

    def test_app_js_trap_filters_visible(self) -> None:
        src = _read(APP_JS)
        match = re.search(
            r"function\s+_modalFocusTrap\s*\([^)]*\)\s*\{(.+?)\n\}",
            src,
            re.DOTALL,
        )
        assert match is not None
        body = match.group(1)
        self.assertIn(
            "offsetParent",
            body,
            msg=(
                "R238 invariant: app.js _modalFocusTrap 必须用 offsetParent !== "
                "null 过滤掉 display:none / 父级 hidden 的元素, 否则 Tab 会跳到"
                "不可见的元素上, 用户看不到焦点指示。"
            ),
        )

    def test_settings_trap_filters_visible(self) -> None:
        src = _read(SETTINGS_JS)
        match = re.search(
            r"_settingsFocusTrap\s*\([^)]*\)\s*\{(.+?)\n  \}",
            src,
            re.DOTALL,
        )
        assert match is not None
        body = match.group(1)
        self.assertIn("offsetParent", body)


if __name__ == "__main__":
    unittest.main()
