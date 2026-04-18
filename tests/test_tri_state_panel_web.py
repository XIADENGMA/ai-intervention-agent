"""Regression tests for @aiia/tri-state-panel — Web UI half (T1 · C10b).

These are **doc-anchor** tests: they grep HTML / JS source for specific
markers (DOM ids, class names, data-attributes, exported symbols) declared in
BEST_PRACTICES_PLAN.tmp.md §T1 v3. Any refactor that silently drops a marker
will turn the test red before an E2E regression surfaces in the browser.

Test scope (5 assertions per `README`-style checklist in §T1 v3 §5):

1. ``#aiia-tri-state-panel`` root element lives in ``templates/web_ui.html``
   with the full data-* attribute trio (``state``/``error-mode``/``empty-mode``).
2. All four branches (``skeleton``/``loading``/``empty``/``error``) are
   represented as ``data-tsp-branch`` sections.
3. All four error-mode detail paragraphs exist (``network``/``server_500``/
   ``timeout``/``unknown``).
4. All three error action buttons carry ``data-tsp-action`` (``retry``/
   ``open_log``/``copy_diagnostics``).
5. ``static/js/tri-state-panel.js`` is a valid ES module and exports
   ``TriStatePanelController`` plus frozen state/mode lists expected by
   the bootstrap (``VALID_STATES_FROZEN``/``ERROR_MODES_FROZEN``/
   ``EMPTY_MODES_FROZEN``).

These assertions complement — they do NOT replace — the runtime Playwright /
Mocha harness that will be wired in C10b step 9 before commit.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
WEB_UI_HTML = REPO_ROOT / "templates" / "web_ui.html"
STATIC_JS_DIR = REPO_ROOT / "static" / "js"
TRI_STATE_PANEL_JS = STATIC_JS_DIR / "tri-state-panel.js"
TRI_STATE_PANEL_LOADER_JS = STATIC_JS_DIR / "tri-state-panel-loader.js"
TRI_STATE_PANEL_BOOTSTRAP_JS = STATIC_JS_DIR / "tri-state-panel-bootstrap.js"
TRI_STATE_PANEL_CSS = REPO_ROOT / "static" / "css" / "tri-state-panel.css"
MAIN_CSS = REPO_ROOT / "static" / "css" / "main.css"

EXPECTED_BRANCHES = ("skeleton", "loading", "empty", "error")
EXPECTED_ERROR_DETAILS = ("network", "server_500", "timeout", "unknown")
EXPECTED_ERROR_ACTIONS = ("retry", "open_log", "copy_diagnostics")
EXPECTED_EMPTY_DETAILS = ("default", "filtered")


class TestTriStatePanelWebDom(unittest.TestCase):
    """HTML shape guarantees for the tri-state panel in the Web UI template."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.html = WEB_UI_HTML.read_text(encoding="utf-8")

    def test_root_element_exists_with_full_data_attrs(self) -> None:
        root_pattern = re.compile(
            r'<div[^>]*\bid="aiia-tri-state-panel"[^>]*\bdata-state="ready"[^>]*'
            r'\bdata-error-mode="unknown"[^>]*\bdata-empty-mode="default"[^>]*>',
            re.DOTALL,
        )
        self.assertRegex(
            self.html,
            root_pattern,
            msg=(
                "Expected <div id='aiia-tri-state-panel' data-state='ready' "
                "data-error-mode='unknown' data-empty-mode='default' ...> in "
                "templates/web_ui.html — the three data-* attributes form the "
                "CSS/JS contract declared in tri-state-panel.css/.js"
            ),
        )

    def test_all_four_branches_declared(self) -> None:
        for branch in EXPECTED_BRANCHES:
            self.assertIn(
                f'data-tsp-branch="{branch}"',
                self.html,
                msg=(
                    f"Missing <div data-tsp-branch='{branch}'> in web_ui.html. "
                    f"All four branches ({EXPECTED_BRANCHES}) must be present "
                    f"so the CSS [data-state=...] selectors have a target."
                ),
            )

    def test_error_mode_details_and_empty_mode_details(self) -> None:
        for mode in EXPECTED_ERROR_DETAILS:
            self.assertIn(
                f'data-tsp-error-detail="{mode}"',
                self.html,
                msg=(
                    f"Missing <p data-tsp-error-detail='{mode}'> in error "
                    f"branch; CSS [data-error-mode] selector would render nothing."
                ),
            )
        for mode in EXPECTED_EMPTY_DETAILS:
            self.assertIn(
                f'data-tsp-empty-detail="{mode}"',
                self.html,
                msg=(
                    f"Missing <p data-tsp-empty-detail='{mode}'> in empty "
                    f"branch; CSS [data-empty-mode] selector would render nothing."
                ),
            )

    def test_error_action_buttons_declared(self) -> None:
        for action in EXPECTED_ERROR_ACTIONS:
            self.assertIn(
                f'data-tsp-action="{action}"',
                self.html,
                msg=(
                    f"Missing <button data-tsp-action='{action}'>; action "
                    f"dispatcher window.AIIA_TRI_STATE_PANEL_ACTIONS would "
                    f"never receive '{action}' clicks."
                ),
            )

    def test_panel_loader_and_bootstrap_are_wired(self) -> None:
        self.assertIn(
            '<script type="importmap"',
            self.html,
            msg="templates/web_ui.html must declare an importmap for @aiia/tri-state-panel",
        )
        self.assertIn(
            'src="/static/js/tri-state-panel-loader.js"',
            self.html,
            msg="Loader script (<script type='module' src='/static/js/tri-state-panel-loader.js'>) missing",
        )
        self.assertIn(
            'src="/static/js/tri-state-panel-bootstrap.js"',
            self.html,
            msg="Bootstrap script (<script defer src='/static/js/tri-state-panel-bootstrap.js'>) missing",
        )


class TestTriStatePanelEsModule(unittest.TestCase):
    """Verify the source module shape for @aiia/tri-state-panel."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.panel_src = TRI_STATE_PANEL_JS.read_text(encoding="utf-8")
        cls.loader_src = TRI_STATE_PANEL_LOADER_JS.read_text(encoding="utf-8")
        cls.bootstrap_src = TRI_STATE_PANEL_BOOTSTRAP_JS.read_text(encoding="utf-8")
        cls.css_src = TRI_STATE_PANEL_CSS.read_text(encoding="utf-8")
        cls.main_css_src = MAIN_CSS.read_text(encoding="utf-8")

    def test_tri_state_panel_js_is_es_module(self) -> None:
        self.assertTrue(
            TRI_STATE_PANEL_JS.exists(),
            msg=f"Missing ES module source file: {TRI_STATE_PANEL_JS}",
        )
        self.assertIn(
            "export class TriStatePanelController",
            self.panel_src,
            msg="tri-state-panel.js must export class TriStatePanelController",
        )
        for named_export in (
            "export const VERSION",
            "export const VALID_STATES_FROZEN",
            "export const ERROR_MODES_FROZEN",
            "export const EMPTY_MODES_FROZEN",
        ):
            self.assertIn(
                named_export,
                self.panel_src,
                msg=(
                    f"tri-state-panel.js must expose `{named_export}` so the "
                    f"classic bootstrap can validate state/mode names before "
                    f"calling setState/setErrorMode/setEmptyMode."
                ),
            )

    def test_loader_resolves_bare_specifier_and_publishes_global(self) -> None:
        self.assertIn(
            "import('@aiia/tri-state-panel')",
            self.loader_src,
            msg=(
                "tri-state-panel-loader.js must consume the bare specifier "
                "'@aiia/tri-state-panel' (Import Maps contract, §T1 v3 §4). "
                "Using a direct path like '/static/js/tri-state-panel.js' "
                "would break the symmetric consumption model expected by "
                "the VSCode webview half (C10c)."
            ),
        )
        self.assertIn(
            "AIIA_TRI_STATE_PANEL",
            self.loader_src,
            msg=(
                "Loader must publish the resolved module on window.AIIA_TRI_STATE_PANEL "
                "so the classic-script bootstrap can consume it."
            ),
        )
        self.assertIn(
            "aiia:tri-state-panel-ready",
            self.loader_src,
            msg=(
                "Loader must dispatch the 'aiia:tri-state-panel-ready' CustomEvent "
                "so tri-state-panel-bootstrap.js can mount without polling."
            ),
        )

    def test_bootstrap_creates_content_state_machine(self) -> None:
        self.assertIn(
            "AIIAState.createMachine('content'",
            self.bootstrap_src,
            msg=(
                "Bootstrap must create the canonical content state machine "
                "via window.AIIAState.createMachine('content', 'ready') so "
                "future consumers (C10d / S2 / BM-2) share one source of "
                "truth for loading/empty/error/ready transitions."
            ),
        )
        self.assertIn(
            "AIIA_CONTENT_SM",
            self.bootstrap_src,
            msg=(
                "Bootstrap must publish the content state machine on "
                "window.AIIA_CONTENT_SM so callers can .transition(...) it "
                "without re-creating a parallel instance."
            ),
        )

    def test_css_uses_shared_state_tokens(self) -> None:
        for token in (
            "var(--aiia-state-padding-y)",
            "var(--aiia-state-padding-x)",
            "var(--aiia-state-gap)",
            "var(--aiia-state-icon-size)",
            "var(--aiia-state-radius)",
            "var(--aiia-state-transition)",
        ):
            self.assertIn(
                token,
                self.css_src,
                msg=(
                    f"tri-state-panel.css must consume the shared token {token} "
                    f"introduced by C10a; otherwise Web UI and VSCode webview "
                    f"will diverge visually."
                ),
            )

    def test_main_css_imports_tri_state_panel(self) -> None:
        self.assertIn(
            '@import url("./tri-state-panel.css")',
            self.main_css_src,
            msg=(
                "static/css/main.css must @import ./tri-state-panel.css so the "
                "component layer is actually loaded by the browser."
            ),
        )


if __name__ == "__main__":
    unittest.main()
