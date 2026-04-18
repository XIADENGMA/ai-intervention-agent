"""Forbid direct-path consumption of shared @aiia/* modules (T1 · C10b).

BEST_PRACTICES_PLAN.tmp.md §T1 v3 mandates that consumers reach shared
modules via bare specifiers (``import { X } from '@aiia/tri-state-panel'``)
so Web UI and VSCode webview business code remains byte-identical.

If someone sneaks a direct path (``/static/js/tri-state-panel.js`` from Web
or ``./tri-state-panel.js`` from VSCode webview) into business code, the
symmetry breaks and the Import Maps investment is lost. This test grep-scans
all JS business files and forbids the direct paths **except** in the
three known bridging files:

* ``tri-state-panel-loader.js`` (declares the bare specifier via ``import('@aiia/tri-state-panel')``)
* ``tri-state-panel-bootstrap.js`` (classic script; consumes global, no path)
* ``tri-state-panel.js`` itself (the module source)

HTML / Flask templates are allowed to mention the path (they drive the
Import Map), so this test only looks at JS.
"""

from __future__ import annotations

import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
STATIC_JS_DIR = REPO_ROOT / "static" / "js"
VSCODE_DIR = REPO_ROOT / "packages" / "vscode"

FORBIDDEN_PATHS = (
    "/static/js/tri-state-panel.js",
    "./tri-state-panel.js",
    "../static/js/tri-state-panel.js",
)

ALLOWED_FILES = {
    STATIC_JS_DIR / "tri-state-panel.js",
    STATIC_JS_DIR / "tri-state-panel-loader.js",
    STATIC_JS_DIR / "tri-state-panel-bootstrap.js",
    VSCODE_DIR / "tri-state-panel.js",
    VSCODE_DIR / "tri-state-panel-loader.js",
    VSCODE_DIR / "tri-state-panel-bootstrap.js",
}


def _iter_business_js_files() -> list[Path]:
    results: list[Path] = []
    for root in (STATIC_JS_DIR, VSCODE_DIR):
        if not root.exists():
            continue
        for path in sorted(root.rglob("*.js")):
            if ".min." in path.name:
                continue
            if path in ALLOWED_FILES:
                continue
            results.append(path)
    return results


class TestNoDirectSharedPathImport(unittest.TestCase):
    """Business JS MUST use the bare specifier, not a physical path."""

    def test_no_business_file_references_tri_state_panel_by_path(self) -> None:
        offenders: list[tuple[Path, str]] = []
        for path in _iter_business_js_files():
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            for forbidden in FORBIDDEN_PATHS:
                if forbidden in text:
                    offenders.append((path, forbidden))

        if offenders:
            bullet_list = "\n  ".join(
                f"{p.relative_to(REPO_ROOT)}  uses forbidden path {fragment!r}"
                for p, fragment in offenders
            )
            self.fail(
                "The following business JS files hard-code a direct path to the "
                "shared tri-state panel module. Replace with the bare specifier "
                "import (``import ... from '@aiia/tri-state-panel'``) and declare "
                "the mapping in the Import Map (§T1 v3):\n  " + bullet_list
            )


if __name__ == "__main__":
    unittest.main()
