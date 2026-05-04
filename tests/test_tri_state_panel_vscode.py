"""Regression tests for @aiia/tri-state-panel — VSCode webview half (T1 · C10c).

Mirror of ``tests/test_tri_state_panel_web.py`` but for the VSCode side.
The webview HTML is generated dynamically inside
``packages/vscode/webview.ts::_getHtmlContent``; these tests grep the
TypeScript source for the same DOM/attribute markers (declared in
BEST_PRACTICES_PLAN.tmp.md §T1 v3 §C10c) so any silent refactor that
drops a marker fails CI before reaching a real webview.

Test scope (one assertion per checklist item in §T1 v3 §C10c):

1. ``#aiia-tri-state-panel`` root element with ``data-state``/
   ``data-error-mode``/``data-empty-mode`` attribute trio.
2. All four ``data-tsp-branch`` sections.
3. All four error-mode detail paragraphs.
4. Both empty-mode detail paragraphs.
5. All three error action buttons.
6. All 13 ``data-i18n="aiia.state.*"`` attributes (drives client-side
   i18n re-translation and feeds ``_collect_all_used_vscode_keys`` so
   the reverse gate ``_PRE_RESERVED_KEYS`` can drain).
7. All 13 ``${tl('aiia.state.*')}`` SSR template literals (drives the
   first-paint text so the panel reads correctly even if the bootstrap
   never runs).
8. Importmap + ES module loader + classic bootstrap wiring with CSP
   nonce on every ``<script>`` tag.
9. CSS @import for the shared ``tri-state-panel.css`` module declared in
   ``packages/vscode/webview.css`` (asserted in
   ``tests/test_tri_state_panel_parity.py`` for byte-parity, here only
   the @import statement).

These tests complement — they do NOT replace — the VSCode Mocha smoke
runs invoked by ``scripts/ci_gate.py --with-vscode``.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
VSCODE_DIR = REPO_ROOT / "packages" / "vscode"
WEBVIEW_TS = VSCODE_DIR / "webview.ts"
WEBVIEW_CSS = VSCODE_DIR / "webview.css"

EXPECTED_BRANCHES = ("skeleton", "loading", "empty", "error")
EXPECTED_ERROR_DETAILS = ("network", "server_500", "timeout", "unknown")
EXPECTED_EMPTY_DETAILS = ("default", "filtered")
EXPECTED_ERROR_ACTIONS = ("retry", "open_log", "copy_diagnostics")

EXPECTED_I18N_KEYS = (
    "aiia.state.loading.title",
    "aiia.state.loading.message",
    "aiia.state.empty.title",
    "aiia.state.empty.message.default",
    "aiia.state.empty.message.filtered",
    "aiia.state.error.title",
    "aiia.state.error.message.network",
    "aiia.state.error.message.server_500",
    "aiia.state.error.message.timeout",
    "aiia.state.error.message.unknown",
    "aiia.state.error.action.retry",
    "aiia.state.error.action.open_log",
    "aiia.state.error.action.copy_diagnostics",
)


class TestTriStatePanelVscodeDom(unittest.TestCase):
    """webview.ts must render the tri-state panel DOM symmetrically with web_ui.html."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.ts = WEBVIEW_TS.read_text(encoding="utf-8")

    def test_root_element_with_full_data_attrs(self) -> None:
        # Use a multi-line tolerant regex because the TS template literal
        # spreads attrs across many lines.
        root_pattern = re.compile(
            r'id="aiia-tri-state-panel"[\s\S]*?'
            r'data-state="ready"[\s\S]*?'
            r'data-error-mode="unknown"[\s\S]*?'
            r'data-empty-mode="default"',
        )
        self.assertRegex(
            self.ts,
            root_pattern,
            msg=(
                "Expected <div id='aiia-tri-state-panel' data-state='ready' "
                "data-error-mode='unknown' data-empty-mode='default' ...> in "
                "webview.ts::_getHtmlContent — three data-* form the CSS/JS "
                "contract; without them the panel CSS [data-state] selectors "
                "render nothing."
            ),
        )

    def test_all_four_branches_declared(self) -> None:
        for branch in EXPECTED_BRANCHES:
            self.assertIn(
                f'data-tsp-branch="{branch}"',
                self.ts,
                msg=(
                    f"Missing data-tsp-branch='{branch}' in webview.ts. "
                    f"All four branches ({EXPECTED_BRANCHES}) must be present "
                    f"so the CSS [data-state=...] selectors have a target."
                ),
            )

    def test_error_mode_details_and_empty_mode_details(self) -> None:
        for mode in EXPECTED_ERROR_DETAILS:
            self.assertIn(
                f'data-tsp-error-detail="{mode}"',
                self.ts,
                msg=(
                    f"Missing data-tsp-error-detail='{mode}' in webview.ts; "
                    f"CSS [data-error-mode] selector would render nothing for "
                    f"this error mode."
                ),
            )
        for mode in EXPECTED_EMPTY_DETAILS:
            self.assertIn(
                f'data-tsp-empty-detail="{mode}"',
                self.ts,
                msg=(
                    f"Missing data-tsp-empty-detail='{mode}' in webview.ts; "
                    f"CSS [data-empty-mode] selector would render nothing."
                ),
            )

    def test_error_action_buttons_declared(self) -> None:
        for action in EXPECTED_ERROR_ACTIONS:
            self.assertIn(
                f'data-tsp-action="{action}"',
                self.ts,
                msg=(
                    f"Missing data-tsp-action='{action}' in webview.ts; "
                    f"action dispatcher window.AIIA_TRI_STATE_PANEL_ACTIONS "
                    f"would never receive '{action}' clicks."
                ),
            )

    def test_all_thirteen_i18n_keys_declared(self) -> None:
        """Each aiia.state.* key MUST appear as data-i18n=... so the
        bootstrap's ``window.AIIA_I18N.translateDOM`` call can resolve
        live language switches without re-rendering the whole webview."""
        for key in EXPECTED_I18N_KEYS:
            self.assertIn(
                f'data-i18n="{key}"',
                self.ts,
                msg=(
                    f"Missing data-i18n='{key}' in webview.ts. The 13 "
                    f"aiia.state.* keys MUST all appear as data-i18n attrs "
                    f"so the i18n re-translation pass can localize them; "
                    f"without it, switching language leaves stale text."
                ),
            )

    def test_all_thirteen_i18n_keys_have_ssr_text(self) -> None:
        """Each aiia.state.* key MUST also be embedded as SSR text via
        ``${tl('aiia.state.<key>')}`` so the first paint shows the right
        copy even if the loader/bootstrap chain fails (defense in depth)
        AND so ``_collect_all_used_vscode_keys()`` (test_runtime_behavior)
        sees the consumption and the reverse gate can drain."""
        for key in EXPECTED_I18N_KEYS:
            pattern = re.compile(r"tl\(\s*['\"]" + re.escape(key) + r"['\"]\s*\)")
            self.assertRegex(
                self.ts,
                pattern,
                msg=(
                    f"Missing ${{tl('{key}')}} SSR call in webview.ts. "
                    f"The 13 aiia.state.* keys MUST be SSR'd via tl() so "
                    f"(a) first paint is correct without JS and (b) the "
                    f"i18n dead-key scanner registers them as consumed on "
                    f"the VSCode side (drains _PRE_RESERVED_KEYS)."
                ),
            )

    def test_importmap_loader_and_bootstrap_wiring(self) -> None:
        """The webview HTML must declare the importmap with the bare
        specifier ``@aiia/tri-state-panel`` and load the loader (module)
        + bootstrap (classic) scripts, all carrying a CSP nonce."""
        self.assertRegex(
            self.ts,
            re.compile(
                r'<script\s+type="importmap"\s+nonce="\$\{nonce\}"',
            ),
            msg=(
                "<script type='importmap' nonce='${nonce}'> not found in "
                "webview.ts. CSP nonce-only script-src would refuse the "
                "importmap and bare-specifier resolution silently fails."
            ),
        )
        self.assertIn(
            '"@aiia/tri-state-panel"',
            self.ts,
            msg=(
                "Bare specifier '@aiia/tri-state-panel' missing from the "
                "webview importmap; the loader's import('@aiia/tri-state-panel') "
                "would 404 with no graceful fallback."
            ),
        )
        self.assertRegex(
            self.ts,
            re.compile(
                r'<script\s+type="module"\s+nonce="\$\{nonce\}"\s+src="\$\{triStatePanelLoaderUri\}"',
            ),
            msg=(
                "Loader module script (<script type='module' src='${triStatePanelLoaderUri}'>) "
                "missing or missing nonce. Without it the bare specifier "
                "is never resolved."
            ),
        )
        self.assertRegex(
            self.ts,
            re.compile(
                r'<script\s+nonce="\$\{nonce\}"\s+src="\$\{triStatePanelBootstrapUri\}"',
            ),
            msg=(
                "Bootstrap classic script (<script src='${triStatePanelBootstrapUri}'>) "
                "missing or missing nonce. Without it the controller is "
                "never instantiated and the panel stays in 'ready' (hidden)."
            ),
        )

    def test_importmap_precedes_module_scripts(self) -> None:
        """Browser hard requirement: <script type='importmap'> MUST
        appear before any <script type='module'> in the same document.

        We strip HTML comments first so doc-comments inside the template
        literal that mention "<script type='module'>" don't count toward
        the positional check."""
        ts_no_comments = re.sub(r"<!--[\s\S]*?-->", "", self.ts)
        importmap_match = re.search(
            r'<script\s+type="importmap"',
            ts_no_comments,
        )
        module_match = re.search(
            r'<script\s+type="module"',
            ts_no_comments,
        )
        self.assertIsNotNone(importmap_match, msg="Importmap script missing")
        self.assertIsNotNone(module_match, msg="No <script type='module'> found")
        assert importmap_match is not None
        assert module_match is not None
        self.assertLess(
            importmap_match.start(),
            module_match.start(),
            msg=(
                "<script type='importmap'> must appear BEFORE the first "
                "<script type='module'> in webview.ts. Browsers freeze the "
                "importmap as soon as the first module script starts "
                "fetching; declaring them in the wrong order breaks "
                "bare-specifier resolution silently."
            ),
        )

    def test_uri_constants_declared(self) -> None:
        """The four shared assets MUST go through ``webview.asWebviewUri()``
        so VSCode's CSP/local-resource-roots policy lets them load.
        Hard-coding ``./tri-state-panel.js`` would fail with ERR_BLOCKED_BY_CSP."""
        for uri_var in (
            "triStatePanelJsUri",
            "triStatePanelLoaderUri",
            "triStatePanelBootstrapUri",
        ):
            self.assertIn(
                f"const {uri_var} = webview.asWebviewUri",
                self.ts,
                msg=(
                    f"Expected `const {uri_var} = webview.asWebviewUri(...)` "
                    f"in webview.ts. Direct file:// or relative paths are "
                    f"blocked by the webview CSP; the asWebviewUri bridge "
                    f"is the only sanctioned channel."
                ),
            )


class TestTriStatePanelVscodeCss(unittest.TestCase):
    """webview.css must @import the shared tri-state panel CSS module."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.css = WEBVIEW_CSS.read_text(encoding="utf-8")

    def test_webview_css_imports_tri_state_panel(self) -> None:
        import_re = re.compile(
            r'@import\s+url\(\s*(["\'])\./tri-state-panel\.css\1\s*\)\s*;'
        )
        self.assertRegex(
            self.css,
            import_re,
            msg=(
                "packages/vscode/webview.css must @import ./tri-state-panel.css "
                "so the component layer is loaded by the webview. Single or "
                "double quotes are both acceptable (formatter-agnostic)."
            ),
        )


if __name__ == "__main__":
    unittest.main()
