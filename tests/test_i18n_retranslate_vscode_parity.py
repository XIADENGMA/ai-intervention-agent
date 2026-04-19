"""P8 不变量：VSCode webview 的 ``retranslateAllI18nElements`` 委托给
``i18n.translateDOM()``，并仅保留 ``data-i18n-version`` 本地处理。

P8 之前 ``retranslateAllI18nElements`` 只认 3 种 selector（text/title/placeholder），
而 P7 的 ``translateDOM`` 已扩到 5 种 + ``data-i18n-html``。任何新属性（如
``data-i18n-alt``）在首屏被 ``translateDOM`` 翻译、但语言切换时被漏掉，
静默回归。P8 改为委托 ``translateDOM()`` 自动继承所有当前 + 未来 selector，
只把 ``data-i18n-version`` 的版本号插值留在本地（避免两份 i18n.js runtime
行为漂移）。

合约：
  1. 函数调用了 ``i18n.translateDOM(``（主路径）；
  2. 仍保留 ``data-i18n-version`` special case（``t(..., { version: ... })``）；
  3. i18n 模块还没挂到 window 的竞态 fallback 至少覆盖
     ``data-i18n`` / ``-title`` / ``-placeholder``。

走静态分析而非 JSDOM：runtime 行为由 translateDOM 自身 parity 测试覆盖
（``test_i18n_translate_dom_parity`` / ``test_i18n_attr_translation``）。
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
