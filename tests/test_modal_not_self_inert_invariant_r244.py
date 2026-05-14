"""R244 / Cycle 16 · fix R240 modal-inside-container self-inert bug.

The bug
-------

R240 set ``.container.inert = true`` when a modal opened. Both modals
(``#code-paste-panel``, ``#settings-panel``) live **inside** the
``.container`` (per ``templates/web_ui.html`` L160 / L713 / L976), so
the HTML5 ``inert`` cascade made the modals themselves uninteractive
— clicks, focus, and AT all blocked. R237 ARIA + R238 focus-trap were
fine in isolation but the R240 cascade silently undid focus-trap
because focus could never *enter* the modal at all.

The bug went undetected for 4 cycles (R240 → R243) because:

1. R240's invariant test (``test_modal_inert_background_invariant_r240.py``)
   was Pattern B — static grep for ``container.inert = …`` patterns,
   never exercised real DOM cascade behavior.
2. R242/R243's audit happened to surface stale `.min.js`, not the
   semantic bug in the original sources.
3. Manual smoke testing of "modal opens" stopped at "I see the modal"
   without trying to interact with it.

The fix (R244)
--------------

Replace ``container.inert = true`` with iteration over
``.container.children``: set ``inert`` on every direct child
**except** the open dialog. The dialog stays interactive while
every sibling (header, main content, footer, image-modal, the
*other* dialog) becomes inert. The `.container` itself is **not**
inert, so the cascade doesn't reach the open dialog's subtree.

This matches the recommended HTML5 "modal but not <dialog>" pattern.

What this test guards
---------------------

* Both ``openCodePasteModal`` and ``showSettings`` use the new helper
  ``_setContainerSiblingsInert(modalEl, true)`` — **not** the old
  direct ``container.inert = true``.
* The helper ``_setContainerSiblingsInert`` exists in both files
  (top-level function in app.js, instance method in settings-manager.js).
* The helper takes the modal element as parameter (proves the
  contract: caller specifies which child to exclude).
* The helper iterates ``container.children`` (NOT just sets
  container.inert), evidenced by the presence of ``container.children``
  / ``for ... of`` patterns near the helper definition.
* No regression: ``.container.inert = …`` direct writes are GONE
  from both modal open/close paths (Pattern B static grep).
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


def _extract_function_body(src: str, header_pattern: str) -> str:
    """Scan from header forward, counting braces until depth returns to 0.

    ``header_pattern`` may NOT include the opening brace — this helper
    appends a search for ``\\([^)]*\\)\\s*\\{`` to skip over the
    parameter list, then brace-counts to find the matching close.
    Avoids the regex pitfall of stopping at the first ``}`` inside
    the function body (e.g. ``if (...) { ... }`` blocks).
    """
    header_match = re.search(header_pattern + r"\s*\([^)]*\)\s*\{", src)
    if not header_match:
        return ""
    start = header_match.end()
    depth = 1
    i = start
    while i < len(src) and depth > 0:
        ch = src[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
        i += 1
    return src[start : i - 1]


class TestHelperExists(unittest.TestCase):
    def test_app_js_has_set_container_siblings_inert(self) -> None:
        src = _read(APP_JS)
        self.assertRegex(
            src,
            r"function\s+_setContainerSiblingsInert\s*\(",
            "R244: app.js 必须有 _setContainerSiblingsInert(modalEl, value) helper, "
            "替代 R240 的 container.inert= 直接写。这个 helper 是修复 R240 cascade "
            "bug 的核心 —— modal 在 .container 内, container.inert=true 会让 modal "
            "自己也变成 inert, 完全无法交互。",
        )

    def test_settings_js_has_set_container_siblings_inert(self) -> None:
        src = _read(SETTINGS_JS)
        self.assertRegex(
            src,
            r"_setContainerSiblingsInert\s*\(",
            "R244: settings-manager.js 必须有 _setContainerSiblingsInert method "
            "(同 app.js, 但作为 SettingsManager class method)。两个文件必须用"
            "一致的 helper 名称, 不能一边修一边漏。",
        )


class TestHelperIteratesChildrenExcludingModal(unittest.TestCase):
    def test_app_js_helper_iterates_children_and_skips_open_modal(self) -> None:
        src = _read(APP_JS)
        body = _extract_function_body(src, r"function\s+_setContainerSiblingsInert")
        self.assertIn(
            "container.children",
            body,
            "R244: _setContainerSiblingsInert 必须遍历 container.children, "
            "不能只调一次 container.inert=。这就是 R240 → R244 修复的关键差异。",
        )
        self.assertRegex(
            body,
            r"if\s*\(\s*child\s*===?\s*openModalEl\s*\)\s*continue",
            "R244: helper 必须明确 skip openModalEl —— 不 skip 就会把 modal "
            "自己也 inert 掉, 把 R240 bug 重新引入。assertRegex 找的是 "
            "`if (child === openModalEl) continue` 这类 idiomatic 写法。",
        )

    def test_settings_js_helper_iterates_children_and_skips_open_modal(self) -> None:
        src = _read(SETTINGS_JS)
        body = _extract_function_body(src, r"\n\s*_setContainerSiblingsInert")
        self.assertIn(
            "container.children",
            body,
            "R244: settings-manager helper 同 app.js 必须遍历 container.children。",
        )
        self.assertRegex(
            body,
            r"if\s*\(\s*child\s*===?\s*openModalEl\s*\)\s*continue",
            "R244: settings-manager helper 必须 skip openModalEl。",
        )


class TestOpenClosePathsUseNewHelper(unittest.TestCase):
    def test_open_code_paste_uses_new_helper(self) -> None:
        src = _read(APP_JS)
        body = _extract_function_body(src, r"function\s+openCodePasteModal")
        self.assertIn(
            "_setContainerSiblingsInert(panel, true)",
            body,
            "R244: openCodePasteModal 必须用新 helper 而非旧 _safelySetInert(container). "
            "找不到 `_setContainerSiblingsInert(panel, true)` 调用 = R240 bug 还没修。",
        )

    def test_close_code_paste_uses_new_helper(self) -> None:
        src = _read(APP_JS)
        body = _extract_function_body(src, r"function\s+closeCodePasteModal")
        self.assertIn(
            "_setContainerSiblingsInert(panel, false)",
            body,
            "R244: closeCodePasteModal 必须用新 helper 把 inert 清掉。"
            "open 用了新 helper 但 close 没用, 会让 inert 永远不被清。",
        )

    def test_show_settings_uses_new_helper(self) -> None:
        src = _read(SETTINGS_JS)
        self.assertRegex(
            src,
            r"showSettings[\s\S]{0,2000}?_setContainerSiblingsInert\s*\(\s*panel\s*,\s*true\s*\)",
            "R244: showSettings 必须用新 helper 而非旧 container.inert=。",
        )

    def test_hide_settings_uses_new_helper(self) -> None:
        src = _read(SETTINGS_JS)
        self.assertRegex(
            src,
            r"hideSettings[\s\S]{0,2000}?_setContainerSiblingsInert\s*\(\s*panel\s*,\s*false\s*\)",
            "R244: hideSettings 必须用新 helper 清 inert。",
        )


class TestNoRegressionToContainerDirectInert(unittest.TestCase):
    """Pattern B regression guard: don't let anyone re-introduce
    `container.inert = …` or call the old direct helper from a
    modal open/close path."""

    def test_app_js_no_container_inert_in_modal_paths(self) -> None:
        src = _read(APP_JS)
        for func in ("openCodePasteModal", "closeCodePasteModal"):
            body = _extract_function_body(src, rf"function\s+{func}")
            self.assertNotIn(
                "container.inert =",
                body,
                f"R244 regression guard: {func} 不能再含 `container.inert = …`. "
                "如果你看到这条 fail, 说明 R240 cascade bug 被重新引入了, "
                "请改用 _setContainerSiblingsInert(panel, true/false) helper。",
            )
            self.assertNotIn(
                '_safelySetInert(document.querySelector(".container")',
                body,
                f"R244 regression guard: {func} 不能再调 "
                "_safelySetInert(document.querySelector('.container'), …) — "
                "那是 R240 的旧 buggy 写法, 必须用新 _setContainerSiblingsInert。",
            )

    def test_settings_js_no_container_inert_in_modal_paths(self) -> None:
        src = _read(SETTINGS_JS)
        for func in (r"showSettings", r"hideSettings"):
            match = re.search(rf"{func}\s*\([^)]*\)\s*\{{(.+?)\n\s*\}}", src, re.DOTALL)
            if not match:
                continue
            body = match.group(1)
            self.assertNotRegex(
                body,
                r"this\._safelySetInert\s*\(\s*container\s*,",
                f"R244 regression guard: {func} 不能再直接 "
                "this._safelySetInert(container, …) — 会让 modal "
                "(.container 的 child) 也变 inert。改用 "
                "this._setContainerSiblingsInert(panel, true/false)。",
            )


if __name__ == "__main__":
    unittest.main()
