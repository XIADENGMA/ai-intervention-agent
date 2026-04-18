"""CSP-compatibility guard for Import Maps (T1 · C10b).

Rationale (BEST_PRACTICES_PLAN.tmp.md §T1 v3 §4):
    Import Maps are subject to CSP `script-src` (WICG/import-maps#105).
    Our Web UI ships `script-src 'self' 'nonce-<...>'`, which is ALREADY
    compatible with Import Maps as long as two conditions hold:

    1. The CSP policy MUST declare a nonce-based `script-src`.
       (If it ever changes to hash-only or an allowlist, Import Maps
       would need `script-src-elem 'unsafe-inline'` or equivalent, which
       would be a regression.)

    2. Every `<script type="importmap">` tag MUST carry that nonce.
       (Otherwise the browser refuses to apply it and bare specifiers
       would fail to resolve at runtime — silent fallback, no error.)

    3. The CSP MUST NOT set `require-trusted-types-for 'script'` (we
       never did, but the guard is kept forward-looking).

If any of these drift, the `@aiia/*` shared-module contract breaks.
This test catches the drift at CI time.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
WEB_UI_HTML = REPO_ROOT / "templates" / "web_ui.html"
SECURITY_MODULE = REPO_ROOT / "web_ui_security.py"


def _strip_html_comments(html: str) -> str:
    return re.sub(r"<!--.*?-->", "", html, flags=re.DOTALL)


class TestCspAllowsImportMapNonce(unittest.TestCase):
    """Regression pins for Web UI CSP + Import Map nonce."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.html = _strip_html_comments(WEB_UI_HTML.read_text(encoding="utf-8"))
        cls.security_src = SECURITY_MODULE.read_text(encoding="utf-8")

    def test_csp_script_src_uses_nonce(self) -> None:
        self.assertIn(
            "'nonce-",
            self.security_src,
            msg=(
                "Web UI CSP must use nonce-based script-src. Hash-only or "
                "allowlist-only policies would break Import Maps (the "
                "<script type='importmap'> must match the same nonce or hash "
                "rule as inline scripts)."
            ),
        )
        self.assertIn(
            "script-src 'self' 'nonce-",
            self.security_src,
            msg=(
                "Expected CSP fragment \"script-src 'self' 'nonce-<...>'\" in "
                "web_ui_security.py. If this is changed, every importmap and "
                "module script in templates/web_ui.html must follow the new "
                "contract or bare-specifier resolution will silently fail."
            ),
        )

    def test_csp_does_not_require_trusted_types(self) -> None:
        self.assertNotIn(
            "require-trusted-types-for",
            self.security_src,
            msg=(
                "If `require-trusted-types-for 'script'` is enabled, Import "
                "Maps and module scripts must be wrapped through a trusted "
                "types policy. We are not ready for that rollout; this test "
                "fails loudly when the CSP is hardened without first "
                "retrofitting the importmap path."
            ),
        )

    def test_importmap_script_carries_nonce(self) -> None:
        match = re.search(
            r'<script\s+type="importmap"\s+nonce="\{\{\s*csp_nonce\s*\}\}"',
            self.html,
        )
        self.assertIsNotNone(
            match,
            msg=(
                '`<script type="importmap" nonce="{{ csp_nonce }}">` missing '
                "in templates/web_ui.html. Without the nonce attribute the "
                "browser drops the importmap under our CSP (nonce-only "
                "script-src), breaking every bare-specifier import silently."
            ),
        )

    def test_module_loader_script_carries_nonce(self) -> None:
        pattern = re.compile(
            r'<script\b[^>]*\btype="module"[^>]*\bnonce="\{\{\s*csp_nonce\s*\}\}"'
            r'[^>]*\bsrc="/static/js/tri-state-panel-loader\.js"',
            flags=re.DOTALL,
        )
        alt_pattern = re.compile(
            r'<script\b[^>]*\bsrc="/static/js/tri-state-panel-loader\.js"'
            r'[^>]*\bnonce="\{\{\s*csp_nonce\s*\}\}"[^>]*\btype="module"',
            flags=re.DOTALL,
        )
        if not pattern.search(self.html) and not alt_pattern.search(self.html):
            self.fail(
                "Loader module script (type='module' src='/static/js/tri-state-panel-loader.js') "
                "missing its nonce attribute. CSP nonce-only script-src would "
                "reject it and bare-specifier resolution never runs."
            )


if __name__ == "__main__":
    unittest.main()
