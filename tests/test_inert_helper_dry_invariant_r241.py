"""R241 / Cycle 16 · F-cycle15-2: `_safelySetInert` DRY helper exists in
both `app.js` and `settings-manager.js`, replacing the 4× duplicated
try/catch from R240.

Why this invariant
------------------

R240 introduced `inert` background attribute toggling on modal
open/close. The defensive try/catch pattern appeared **4 times** in
2 files (open+close × code-paste + settings):

```javascript
try {
  container.inert = true;
} catch (_e) {
  container.setAttribute("inert", "");
}
```

CR#28's F-cycle15-2 flagged this as DRY violation candidate. R241
extracts the pattern to a single helper function in each file:

* `app.js`: top-level `function _safelySetInert(el, value)`
* `settings-manager.js`: `SettingsManager.prototype._safelySetInert`
  method (so it can be called via `this._safelySetInert(…)`)

Both helpers behave identically (signature, branch, attribute write).
R241 locks the existence + signature + branch behavior so a future
refactor can't silently regress to inline duplication.

Why not a shared module?

Considered + rejected. Adding `static/js/a11y-helpers.js` would
require:
1. Flask static-serve config touch (works automatically but new file
   would lack docstring on the route)
2. Script-tag wiring in `web_ui.html` before consumers
3. New precompress entry (auto-handled by R226 hook)
4. New cross-file dependency test surface

For 5-line helper duplicated across 2 files (10 lines saved by
shared module vs. ~50 lines of surface added), inlined helpers win
on net code volume + cognitive overhead. If a 3rd file ever needs
`_safelySetInert`, that's the moment to extract — locked as
F-cycle16-1.
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
    assert match is not None, f"Cannot find function: {header_regex}"
    return match.group(1)


def _extract_method_body(src: str, header_regex: str) -> str:
    match = re.search(rf"{header_regex}\s*\{{(.+?)\n  \}}", src, re.DOTALL)
    assert match is not None, f"Cannot find method: {header_regex}"
    return match.group(1)


class TestHelperExistsInBothFiles(unittest.TestCase):
    def test_app_js_has_safely_set_inert_function(self) -> None:
        src = _read(APP_JS)
        self.assertRegex(
            src,
            r"function\s+_safelySetInert\s*\([^)]*\)\s*\{",
            msg=(
                "R241 invariant: app.js 必须定义 `function _safelySetInert(el, "
                "value)` (top-level), 由 openCodePasteModal + closeCodePasteModal "
                "调用。若被内联回 4× try/catch, R240+R241 的 DRY 收益丢失。"
            ),
        )

    def test_settings_js_has_safely_set_inert_method(self) -> None:
        src = _read(SETTINGS_JS)
        self.assertRegex(
            src,
            r"\b_safelySetInert\s*\([^)]*\)\s*\{",
            msg=(
                "R241 invariant: settings-manager.js 必须定义 _safelySetInert "
                "method (on SettingsManager class), 由 showSettings + hideSettings "
                "调用 (用 ``this._safelySetInert(...)``)。"
            ),
        )


class TestHelperHasCorrectBehavior(unittest.TestCase):
    def test_app_js_helper_branches_on_value(self) -> None:
        src = _read(APP_JS)
        body = _extract_function_body(src, r"function\s+_safelySetInert\s*\([^)]*\)")
        self.assertIn(
            "el.inert = value",
            body,
            msg=(
                "R241 invariant: app.js _safelySetInert 必须用 IDL setter "
                "(``el.inert = value``) 作为主路径, setAttribute 作为 fallback。"
            ),
        )
        self.assertIn(
            'setAttribute("inert"',
            body,
            msg="R241 invariant: helper 必须有 setAttribute fallback",
        )
        self.assertIn(
            'removeAttribute("inert"',
            body,
            msg="R241 invariant: helper 必须有 removeAttribute fallback",
        )
        self.assertIn(
            "try {",
            body,
            msg="R241 invariant: helper 必须 try/catch IDL set",
        )

    def test_settings_js_helper_branches_on_value(self) -> None:
        src = _read(SETTINGS_JS)
        body = _extract_method_body(src, r"_safelySetInert\s*\([^)]*\)")
        for token in (
            "el.inert = value",
            'setAttribute("inert"',
            'removeAttribute("inert"',
            "try {",
        ):
            self.assertIn(
                token,
                body,
                msg=(
                    f"R241 invariant: settings-manager.js _safelySetInert 必须包含 "
                    f"{token!r}。否则与 app.js 行为分歧, DRY 假象 (函数名相同但"
                    "实现漂移)。"
                ),
            )


class TestCallSitesUseHelper(unittest.TestCase):
    """收紧锁: open+close 调用点必须调 helper, 不能 inline 写 .inert (DRY 反向"
    "防护, 否则有人改完忘记)。
    """

    def test_app_js_callers_use_helper(self) -> None:
        src = _read(APP_JS)
        # 排除掉 helper 定义本身和 ResizeObserver-like 不相关 .inert 出现 (理论上没有)。
        helper_def = re.search(r"function\s+_safelySetInert.+?\n\}", src, re.DOTALL)
        assert helper_def is not None
        outside_helper = src.replace(helper_def.group(0), "")
        # 调用点之外不应再出现 container.inert =  inline 赋值。
        inline_set = re.search(r"container\.inert\s*=", outside_helper)
        self.assertIsNone(
            inline_set,
            msg=(
                "R241 invariant: app.js 中除 _safelySetInert helper 外, 不应再有 "
                "``container.inert = ...`` inline 赋值。请统一通过 helper 调用。"
            ),
        )

    def test_settings_js_callers_use_helper(self) -> None:
        src = _read(SETTINGS_JS)
        helper_def = re.search(
            r"_safelySetInert\s*\([^)]*\)\s*\{.+?\n  \}", src, re.DOTALL
        )
        assert helper_def is not None
        outside_helper = src.replace(helper_def.group(0), "")
        inline_set = re.search(r"container\.inert\s*=", outside_helper)
        self.assertIsNone(
            inline_set,
            msg=(
                "R241 invariant: settings-manager.js 中除 _safelySetInert helper "
                "外, 不应再有 ``container.inert = ...`` inline 赋值。"
            ),
        )


if __name__ == "__main__":
    unittest.main()
