"""R240 / Cycle 15: open modals mark `.container` as ``inert``.

Why this invariant
------------------

Completes the **a11y wave 4 trilogy**:

* R237 — declarative ARIA contract on `role="dialog"` (aria-modal,
  aria-labelledby, aria-label).
* R238 — imperative focus management (Tab trap + focus restore).
* **R240** — HTML5 ``inert`` on the background, so the page under
  an open modal is *completely* non-interactive: cannot receive
  focus (even programmatically), cannot be clicked, hidden from
  assistive technology.

Why ``inert`` over alternatives:

* ``aria-hidden`` alone would hide from AT but still allow mouse
  clicks + Tab focus on background buttons. R238's focus trap
  blocks Tab, but mouse click is still possible. ``inert`` blocks
  both.
* ``tabindex="-1"`` on every focusable would scale poorly and
  miss new elements.
* CSS ``pointer-events: none`` blocks mouse but not keyboard or AT.

``inert`` is the canonical HTML5 attribute for "this subtree is
not part of the current interaction" (Whatwg / W3C, stable since
2022, supported in all modern browsers — Chrome 102+, Firefox 112+,
Safari 15.5+).

Note on the try/catch around ``el.inert = …``:

Older browser engines lacked the ``inert`` IDL property; the
fallback ``setAttribute("inert", "")`` works on any HTML element
in any browser that recognizes the attribute. The pattern is
**defense-in-depth**, not paranoia — even modern browsers might
have ``HTMLElement.prototype.inert`` shadowed by polyfills or
Sentry instrumentation.

What this test guards
---------------------

For both modal open functions (``showSettings`` /
``openCodePasteModal``) + their corresponding close functions
(``hideSettings`` / ``closeCodePasteModal``), the JS source must:

1. Touch ``.container`` (the ``role="main"`` wrapper).
2. Set ``container.inert = true`` (or ``setAttribute("inert", "")``)
   on open.
3. Set ``container.inert = false`` (or ``removeAttribute("inert")``)
   on close.

Pattern B (cross-file content) like R238.
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


def _extract_function_body(src: str, header_regex: str) -> str:
    match = re.search(rf"{header_regex}\s*\{{(.+?)\n\}}", src, re.DOTALL)
    assert match is not None, f"Cannot find function matching: {header_regex}"
    return match.group(1)


def _extract_method_body(src: str, header_regex: str) -> str:
    match = re.search(rf"{header_regex}\s*\{{(.+?)\n  \}}", src, re.DOTALL)
    assert match is not None, f"Cannot find method matching: {header_regex}"
    return match.group(1)


class TestSettingsOpenSetsInert(unittest.TestCase):
    def test_show_settings_sets_container_inert_true(self) -> None:
        src = _read(SETTINGS_JS)
        match = re.search(r"showSettings\s*\([^)]*\)\s*\{(.+?)\n  \}", src, re.DOTALL)
        assert match is not None
        body = match.group(1)
        self.assertIn(
            ".container",
            body,
            msg=(
                "R240 invariant: showSettings 必须触碰 .container 元素 (role=main "
                "wrapper)。如果 selector 变了, 请同步本测试。"
            ),
        )
        self.assertRegex(
            body,
            r"container\.inert\s*=\s*true|setAttribute\([\"']inert[\"']",
            msg=(
                "R240 invariant: showSettings 必须把 .container 标记为 inert "
                "(``container.inert = true`` 或 setAttribute('inert', ''))。"
                "没有 inert 时背景仍可被鼠标点击, 失去 modal 隔离 (R238 焦点陷阱"
                "只挡键盘, 不挡鼠标)。"
            ),
        )


class TestSettingsCloseClearsInert(unittest.TestCase):
    def test_hide_settings_clears_container_inert(self) -> None:
        src = _read(SETTINGS_JS)
        body = _extract_method_body(src, r"hideSettings\(\)")
        self.assertRegex(
            body,
            r"container\.inert\s*=\s*false|removeAttribute\([\"']inert[\"']",
            msg=(
                "R240 invariant: hideSettings 必须清除 .container 的 inert "
                "(``container.inert = false`` 或 removeAttribute('inert'))。"
                "残留 inert 会让用户关闭 modal 后主界面无法操作, 看起来像 hang 死。"
            ),
        )


class TestCodePasteOpenSetsInert(unittest.TestCase):
    def test_open_code_paste_sets_inert(self) -> None:
        src = _read(APP_JS)
        body = _extract_function_body(src, r"function\s+openCodePasteModal\s*\([^)]*\)")
        self.assertIn(
            ".container",
            body,
            msg="R240 invariant: openCodePasteModal 必须触碰 .container",
        )
        self.assertRegex(
            body,
            r"container\.inert\s*=\s*true|setAttribute\([\"']inert[\"']",
        )


class TestCodePasteCloseClearsInert(unittest.TestCase):
    def test_close_code_paste_clears_inert(self) -> None:
        src = _read(APP_JS)
        body = _extract_function_body(src, r"function\s+closeCodePasteModal\s*\(\)")
        self.assertRegex(
            body,
            r"container\.inert\s*=\s*false|removeAttribute\([\"']inert[\"']",
            msg=("R240 invariant: closeCodePasteModal 必须清除 .container 的 inert"),
        )


class TestInertUsesDefensivePattern(unittest.TestCase):
    """try/catch 包裹 .inert IDL set: 老浏览器/被 polyfill 覆盖时 fallback 到
    setAttribute。如果未来移除 try/catch 必须有理由 (e.g., 升 ES2023+ baseline)。"""

    def test_settings_js_uses_try_catch_on_inert(self) -> None:
        src = _read(SETTINGS_JS)
        self.assertRegex(
            src,
            r"try\s*\{[^}]*container\.inert\s*=\s*true[^}]*\}\s*catch",
            msg=(
                "R240 invariant: settings-manager.js 设置 container.inert 时必须用 "
                "try/catch 包裹 (老浏览器或 polyfill 覆盖时 fallback 到 "
                "setAttribute('inert', ''))。"
            ),
        )

    def test_app_js_uses_try_catch_on_inert(self) -> None:
        src = _read(APP_JS)
        self.assertRegex(
            src,
            r"try\s*\{[^}]*container\.inert\s*=\s*true[^}]*\}\s*catch",
            msg=(
                "R240 invariant: app.js 设置 container.inert 时必须用 try/catch 包裹。"
            ),
        )


if __name__ == "__main__":
    unittest.main()
