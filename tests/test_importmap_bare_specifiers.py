"""Import-map bare-specifier contract guard (T1 · C10b).

Pins down the CSS-first / JS-symmetric architecture from
BEST_PRACTICES_PLAN.tmp.md §T1 v3:

* Every time a shared module is published under a bare specifier
  (``@aiia/<name>``), the specifier MUST appear in both the Web UI and
  VSCode webview Import Maps (HTML / TS sources).
* The Import Map ``<script type="importmap">`` MUST carry the CSP nonce,
  otherwise ``script-src 'self' 'nonce-...'`` refuses to apply it.
* The Import Map ``<script>`` MUST appear **before** any ``<script type="module">``
  tag in the same document — this is a browser hard requirement
  (once any module script fetches, the importmap is frozen).

Scope for C10b: only the Web UI half is wired now. The VSCode half is
implemented in C10c and this file will grow a second test class then.
"""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
WEB_UI_HTML = REPO_ROOT / "templates" / "web_ui.html"

EXPECTED_BARE_SPECIFIERS = {
    "@aiia/tri-state-panel": "/static/js/tri-state-panel.js",
}


class TestWebUiImportMap(unittest.TestCase):
    """Web UI importmap shape guarantees."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.html = WEB_UI_HTML.read_text(encoding="utf-8")

    @staticmethod
    def _strip_html_comments(html: str) -> str:
        """Remove HTML comments so sample `<script>` snippets in docs
        don't accidentally count toward the test's positional checks."""
        return re.sub(r"<!--.*?-->", "", html, flags=re.DOTALL)

    def _extract_importmap(self) -> dict[str, str]:
        html = self._strip_html_comments(self.html)
        match = re.search(
            r'<script\s+type="importmap"(?P<attrs>[^>]*)>\s*(?P<body>\{.*?\})\s*</script>',
            html,
            flags=re.DOTALL,
        )
        if not match:
            self.fail(
                "No <script type='importmap'>...</script> block found in "
                "templates/web_ui.html — required by §T1 v3 §3."
            )
        attrs = match.group("attrs")
        self.assertIn(
            'nonce="{{ csp_nonce }}"',
            attrs,
            msg=(
                'Import map script must carry nonce="{{ csp_nonce }}"; without it '
                "the CSP `script-src 'nonce-...'` directive refuses to apply it."
            ),
        )
        try:
            parsed = json.loads(match.group("body"))
        except json.JSONDecodeError as exc:
            self.fail(
                f"Importmap body is not valid JSON: {exc}\nBody:\n{match.group('body')}"
            )
        imports = parsed.get("imports")
        self.assertIsInstance(
            imports,
            dict,
            msg="Importmap JSON must have a top-level 'imports' object per W3C spec.",
        )
        return imports

    def test_importmap_contains_all_expected_bare_specifiers(self) -> None:
        imports = self._extract_importmap()
        for specifier, expected_url in EXPECTED_BARE_SPECIFIERS.items():
            self.assertIn(
                specifier,
                imports,
                msg=(
                    f"Importmap missing bare specifier '{specifier}'. Either the "
                    f"module was dropped or the specifier was renamed — in both "
                    f"cases the consumer imports will fail at runtime."
                ),
            )
            self.assertEqual(
                imports[specifier],
                expected_url,
                msg=(
                    f"Bare specifier '{specifier}' maps to '{imports[specifier]}', "
                    f"expected '{expected_url}'. Updating the physical path without "
                    f"updating this test risks silently breaking the VSCode half "
                    f"(C10c) which expects the same specifier."
                ),
            )

    def test_importmap_precedes_module_scripts(self) -> None:
        html = self._strip_html_comments(self.html)
        importmap_match = re.search(
            r'<script\s+type="importmap"',
            html,
        )
        module_match = re.search(
            r'<script\b[^>]*\btype="module"',
            html,
            flags=re.DOTALL,
        )
        self.assertIsNotNone(
            importmap_match,
            msg="Importmap script element not found",
        )
        self.assertIsNotNone(
            module_match,
            msg="No <script type='module'> found — bootstrap loader is missing",
        )
        self.assertLess(
            importmap_match.start(),
            module_match.start(),
            msg=(
                "The <script type='importmap'> element must appear BEFORE any "
                "<script type='module'>. Browsers freeze the importmap as soon "
                "as the first module script starts fetching; declaring them in "
                "the wrong order breaks bare-specifier resolution silently."
            ),
        )

    def test_importmap_maps_only_documented_specifiers(self) -> None:
        imports = self._extract_importmap()
        unexpected = sorted(set(imports.keys()) - set(EXPECTED_BARE_SPECIFIERS.keys()))
        if unexpected:
            self.fail(
                "Import map contains unexpected bare specifiers: "
                f"{unexpected}. Every new specifier must be registered in "
                "EXPECTED_BARE_SPECIFIERS and documented in "
                "BEST_PRACTICES_PLAN.tmp.md §T1 v3 §3 to preserve the "
                "symmetric consumption contract with the VSCode webview."
            )


if __name__ == "__main__":
    unittest.main()
