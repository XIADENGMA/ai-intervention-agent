"""Import-map bare-specifier contract guard (T1 · C10b + C10c).

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

C10b wired the Web UI half; C10c (this file's ``TestVscodeWebviewImportMap``)
wires the VSCode webview half. The two halves intentionally use different
mapped URLs (Web → ``/static/...``, VSCode → ``${triStatePanelJsUri}``)
because the physical file layout differs, but the bare-specifier KEY
(``@aiia/tri-state-panel``) is byte-identical so business code is portable.
"""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
WEB_UI_HTML = REPO_ROOT / "templates" / "web_ui.html"
VSCODE_WEBVIEW_TS = REPO_ROOT / "packages" / "vscode" / "webview.ts"

EXPECTED_BARE_SPECIFIERS = {
    "@aiia/tri-state-panel": "/static/js/tri-state-panel.js",
}

# VSCode webview maps the same specifier KEYS but to template-literal
# placeholders that resolve to ``vscode-webview://<authority>/...`` URIs
# at runtime via ``webview.asWebviewUri()``. We only assert the placeholder
# name here — the real URI is generated per-extension at activation time.
EXPECTED_BARE_SPECIFIERS_VSCODE = {
    "@aiia/tri-state-panel": "${triStatePanelJsUri}",
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
        assert match is not None
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
        assert importmap_match is not None
        assert module_match is not None
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


class TestVscodeWebviewImportMap(unittest.TestCase):
    """VSCode webview importmap shape guarantees (mirror of TestWebUiImportMap).

    The webview HTML is generated dynamically inside
    ``packages/vscode/webview.ts::_getHtmlContent``; the importmap is
    a template literal whose imports object resolves URIs through
    ``webview.asWebviewUri()`` template placeholders. We assert structural
    invariants on that template literal so the bare-specifier contract
    stays in lockstep with the Web UI half.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.ts = VSCODE_WEBVIEW_TS.read_text(encoding="utf-8")

    @staticmethod
    def _strip_ts_comments(ts: str) -> str:
        """Remove TS line comments AND HTML comments inside the template
        literal so doc-comments mentioning ``<script type='module'>`` (or
        sample importmap snippets) don't accidentally count toward
        positional checks.

        We deliberately do NOT strip ``/* */`` TS block comments because
        they don't typically contain HTML script tags.
        """
        ts = re.sub(r"^\s*//.*$", "", ts, flags=re.MULTILINE)
        ts = re.sub(r"<!--[\s\S]*?-->", "", ts)
        return ts

    def _extract_importmap_body(self) -> dict[str, str]:
        """Parse the template-literal importmap body.

        Why not run the TS through ts-node? Static analysis is enough:
        the importmap is a literal JSON-with-template-placeholders block;
        we accept template placeholders as opaque strings so JSON.parse
        succeeds (templates like ``${triStatePanelJsUri}`` are kept verbatim
        as the values).
        """
        ts = self._strip_ts_comments(self.ts)
        match = re.search(
            r'<script\s+type="importmap"(?P<attrs>[^>]*)>\s*(?P<body>\{[\s\S]*?\})\s*</script>',
            ts,
        )
        if not match:
            self.fail(
                "No <script type='importmap'>...</script> block found in "
                "webview.ts::_getHtmlContent — required by §T1 v3 §C10c."
            )
        assert match is not None
        attrs = match.group("attrs")
        self.assertIn(
            'nonce="${nonce}"',
            attrs,
            msg=(
                'Import map script must carry nonce="${nonce}" in webview.ts; '
                "without it the CSP `script-src 'nonce-...'` directive "
                "refuses to apply it."
            ),
        )
        # Replace template placeholders with quoted strings so json.loads
        # can parse the body. The placeholder names matter — preserve them
        # in the parsed value for the assertion below.
        body = match.group("body")
        body_for_json = re.sub(
            r"\$\{([a-zA-Z_][a-zA-Z0-9_]*)\}", r"PLACEHOLDER:\1", body
        )
        try:
            parsed = json.loads(body_for_json)
        except json.JSONDecodeError as exc:
            self.fail(
                f"Importmap body in webview.ts is not valid JSON-like: {exc}\n"
                f"Body (after placeholder substitution):\n{body_for_json}"
            )
        imports = parsed.get("imports")
        self.assertIsInstance(
            imports,
            dict,
            msg="Importmap JSON must have a top-level 'imports' object per W3C spec.",
        )
        # Restore the placeholder shape so callers can compare against the
        # expected ``${triStatePanelJsUri}`` value.
        return {
            k: re.sub(r"PLACEHOLDER:([a-zA-Z_][a-zA-Z0-9_]*)", r"${\1}", v)
            for k, v in imports.items()
        }

    def test_importmap_contains_all_expected_bare_specifiers(self) -> None:
        imports = self._extract_importmap_body()
        for specifier, expected_placeholder in EXPECTED_BARE_SPECIFIERS_VSCODE.items():
            self.assertIn(
                specifier,
                imports,
                msg=(
                    f"VSCode webview importmap missing bare specifier "
                    f"'{specifier}'. The Web UI half (templates/web_ui.html) "
                    f"already declares it; without symmetry, business code "
                    f"that imports '{specifier}' will only work in one half."
                ),
            )
            self.assertEqual(
                imports[specifier],
                expected_placeholder,
                msg=(
                    f"VSCode webview importmap maps '{specifier}' to "
                    f"'{imports[specifier]}', expected '{expected_placeholder}'. "
                    f"The placeholder name MUST match the URI constant declared "
                    f"in webview.ts (asWebviewUri) so the resolved URL respects "
                    f"VSCode's localResourceRoots and CSP."
                ),
            )

    def test_importmap_precedes_module_scripts(self) -> None:
        ts = self._strip_ts_comments(self.ts)
        importmap_match = re.search(
            r'<script\s+type="importmap"',
            ts,
        )
        module_match = re.search(
            r'<script\s+type="module"',
            ts,
        )
        self.assertIsNotNone(
            importmap_match,
            msg="Importmap script element not found in webview.ts",
        )
        self.assertIsNotNone(
            module_match,
            msg="No <script type='module'> found in webview.ts — bootstrap loader is missing",
        )
        assert importmap_match is not None
        assert module_match is not None
        self.assertLess(
            importmap_match.start(),
            module_match.start(),
            msg=(
                "The <script type='importmap'> element must appear BEFORE "
                "any <script type='module'> in webview.ts. Browsers freeze "
                "the importmap as soon as the first module script starts "
                "fetching; declaring them in the wrong order breaks "
                "bare-specifier resolution silently."
            ),
        )

    def test_importmap_maps_only_documented_specifiers(self) -> None:
        imports = self._extract_importmap_body()
        unexpected = sorted(
            set(imports.keys()) - set(EXPECTED_BARE_SPECIFIERS_VSCODE.keys())
        )
        if unexpected:
            self.fail(
                "VSCode webview importmap contains unexpected bare specifiers: "
                f"{unexpected}. Every new specifier must be registered in "
                "EXPECTED_BARE_SPECIFIERS_VSCODE and EXPECTED_BARE_SPECIFIERS "
                "(Web UI side) so the symmetric consumption contract holds."
            )

    def test_specifier_keyset_matches_web_ui(self) -> None:
        """The two halves MUST publish the same specifier keys."""
        web_keys = set(EXPECTED_BARE_SPECIFIERS.keys())
        vscode_keys = set(EXPECTED_BARE_SPECIFIERS_VSCODE.keys())
        self.assertEqual(
            web_keys,
            vscode_keys,
            msg=(
                f"Bare-specifier key sets diverged between Web UI "
                f"({sorted(web_keys)}) and VSCode webview ({sorted(vscode_keys)}). "
                f"Update EXPECTED_BARE_SPECIFIERS and EXPECTED_BARE_SPECIFIERS_VSCODE "
                f"in sync — the symmetric consumption model REQUIRES identical keys."
            ),
        )


if __name__ == "__main__":
    unittest.main()
