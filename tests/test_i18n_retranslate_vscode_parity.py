"""Invariant: VSCode webview's retranslateAllI18nElements delegates to
i18n.translateDOM() + handles data-i18n-version interpolation locally.

Background:
    ``packages/vscode/webview-ui.js`` has a local ``retranslateAllI18nElements``
    function that runs on language switch to refresh ``data-i18n*`` attributes
    in the DOM. Prior to P8 it only handled three selectors:

        data-i18n           (textContent)
        data-i18n-title     (title + aria-label)
        data-i18n-placeholder

    Meanwhile ``packages/vscode/i18n.js::translateDOM`` was refactored in P7 to
    use the unified ATTR_BINDINGS table, covering five attributes:

        data-i18n-title / -placeholder / -alt / -aria-label / -value

    plus ``data-i18n-html``. That asymmetry means if someone ever adds a
    ``data-i18n-alt`` attribute to the VSCode webview HTML (templates/*.ts
    served by webview.ts), it would be translated by translateDOM() on first
    load but NOT by retranslateAllI18nElements() on language switch — silent
    regression.

    P8 fixes this by having ``retranslateAllI18nElements`` delegate to
    ``i18n.translateDOM()`` when available (auto-inherits all current + future
    selectors), and retains only a special case for ``data-i18n-version``
    (version-interpolation kept out of the shared translateDOM to maintain
    byte-identical parity between static/js/i18n.js and packages/vscode/i18n.js).

What this test pins:

1. The function calls ``i18n.translateDOM(`` (primary path).
2. It still has a ``data-i18n-version`` special case with ``t(..., { version: ... })``.
3. The minimal fallback (for the race condition where i18n module isn't yet
   registered on window) handles at least data-i18n / data-i18n-title /
   data-i18n-placeholder.

Rationale for static analysis (not JSDOM):
    The function reads from ``window.AIIA_I18N`` which is populated by a
    sibling IIFE. Setting up a full harness would require loading the 200+ lines
    of i18n.js plus mocking the webview globals — overkill for a structural
    invariant. The runtime behavior is already covered by translateDOM's own
    parity tests (test_i18n_translate_dom_parity, test_i18n_attr_translation).
"""

from __future__ import annotations

import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
WEBVIEW_UI_JS = REPO_ROOT / "packages" / "vscode" / "webview-ui.js"


def _extract_retranslate_body(source: str) -> str:
    """Return the body of ``function retranslateAllI18nElements()`` or raise."""
    # Anchor on the function declaration; use a simple brace counter rather
    # than regex to survive nested braces in the body.
    marker = "function retranslateAllI18nElements()"
    idx = source.find(marker)
    if idx < 0:
        raise AssertionError(
            "packages/vscode/webview-ui.js no longer declares "
            "`function retranslateAllI18nElements()` — the language-switch "
            "retranslation hook was renamed or removed. Update this test "
            "(or restore the function)."
        )
    # Find the opening brace right after the signature.
    brace_open = source.find("{", idx)
    if brace_open < 0:
        raise AssertionError("retranslateAllI18nElements has no opening brace?")
    depth = 1
    cursor = brace_open + 1
    while cursor < len(source) and depth > 0:
        ch = source[cursor]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
        cursor += 1
    if depth != 0:
        raise AssertionError(
            "Could not find matching close brace for retranslateAllI18nElements"
        )
    return source[brace_open:cursor]


class RetranslateVscodeParityTest(unittest.TestCase):
    """Pin the P8 contract on ``retranslateAllI18nElements``."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.source = WEBVIEW_UI_JS.read_text(encoding="utf-8")
        cls.body = _extract_retranslate_body(cls.source)

    def test_delegates_to_i18n_translate_dom(self) -> None:
        """Primary path: delegate to the shared translateDOM() implementation.

        If this fails, ``retranslateAllI18nElements`` went back to a copy-paste
        local implementation and will silently drift from
        ``packages/vscode/i18n.js::translateDOM``'s selector set.
        """
        self.assertRegex(
            self.body,
            r"i18n\s*\.\s*translateDOM\s*\(",
            msg=(
                "retranslateAllI18nElements() must delegate to i18n.translateDOM() "
                "(the shared ATTR_BINDINGS-driven implementation). Found no call "
                "site in the function body."
            ),
        )

    def test_handles_data_i18n_version_special_case(self) -> None:
        """Retains the ``data-i18n-version`` interpolation special case.

        translateDOM() intentionally does NOT handle this (keeps static/js
        and packages/vscode i18n.js byte-identical); the special case lives
        here so the footer version label updates on language change.
        """
        self.assertIn(
            "data-i18n-version",
            self.body,
            msg=(
                "retranslateAllI18nElements() no longer scans for "
                "data-i18n-version — the footer version string will stop "
                "updating on language change (see i18n.js docstring "
                "explaining why this is NOT in translateDOM)."
            ),
        )
        self.assertRegex(
            self.body,
            r"t\s*\([^)]*,\s*\{\s*version\s*:",
            msg=(
                "data-i18n-version special case must pass { version } as the "
                "t() params object so the placeholder interpolates."
            ),
        )

    def test_fallback_path_covers_three_basic_selectors(self) -> None:
        """Fallback (i18n module not yet loaded) covers the 3 basic selectors.

        This only matters in the theoretical race where ``retranslateAllI18nElements``
        fires before ``globalThis.AIIA_I18N`` is populated. The minimal set
        ensures first-render doesn't leave raw keys on-screen even in that case.
        """
        for selector in ("[data-i18n]", "[data-i18n-title]", "[data-i18n-placeholder]"):
            self.assertIn(
                selector,
                self.body,
                msg=(
                    f"retranslateAllI18nElements() fallback path must still "
                    f"query `{selector}` so first paint works even if the "
                    "i18n module hasn't registered on window yet."
                ),
            )

    def test_function_stays_defensive(self) -> None:
        """Everything inside a try/catch — a single DOM error must not brick the UI."""
        # Count top-level try's — expect >= 1 wrapping the whole function body.
        self.assertGreaterEqual(
            self.body.count("try"),
            1,
            msg=(
                "retranslateAllI18nElements() lost its try/catch wrap — a "
                "DOM exception on language switch would now escape and "
                "brick subsequent rendering."
            ),
        )


class RetranslateCallSiteInvariantTest(unittest.TestCase):
    """Sanity: the function is still called at least from applyServerLanguage()
    (the sole lang-change entry point from the server TOML config)."""

    def test_applyServerLanguage_calls_retranslate(self) -> None:
        source = WEBVIEW_UI_JS.read_text(encoding="utf-8")
        # grab applyServerLanguage body
        marker = "function applyServerLanguage("
        idx = source.find(marker)
        self.assertGreaterEqual(
            idx,
            0,
            msg="applyServerLanguage() vanished — how does server TOML language switching work now?",
        )
        brace_open = source.find("{", idx)
        depth = 1
        cursor = brace_open + 1
        while cursor < len(source) and depth > 0:
            ch = source[cursor]
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
            cursor += 1
        body = source[brace_open:cursor]
        self.assertIn(
            "retranslateAllI18nElements()",
            body,
            msg=(
                "applyServerLanguage() no longer calls retranslateAllI18nElements() "
                "after setLang() — language switches from the server TOML config "
                "will not refresh the DOM."
            ),
        )


# Allow both `pytest tests/...` and `python -m unittest ...` invocations.
if __name__ == "__main__":
    unittest.main()
