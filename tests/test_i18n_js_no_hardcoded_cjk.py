"""P7·L1·step-12: Web UI JS sources must not contain hardcoded CJK string
literals. User-visible text belongs in ``static/locales/*.json`` and must
be rendered through ``t('...')``; anything else couples the UI copy to a
single language and blocks future locales.

Why this lives in pytest *and* in ``scripts/check_i18n_js_no_cjk.py``
(redundancy is intentional):
    * The CLI gate runs in CI (``ci_gate.py``) and on pre-commit hooks,
      catching regressions before they land on a branch.
    * The pytest assertion runs on every local ``pytest`` invocation a
      contributor types, catching regressions *before* they even stage
      a commit. When a test fails the developer sees the offending
      file/line inline, which is faster than waiting for a CI red X.

Scope note:
    Only the **Web UI** (``static/js/*``) is covered today. The VSCode
    webview (``packages/vscode/*``) has ~66 legacy CJK literals that
    pre-date the i18n refactor; those will be migrated in a follow-up
    pass (tracked as P8). When that happens, flip the scan scope to
    ``"all"`` and drop this note.

Exemption contract (shared with the CLI gate):
    Append ``// aiia:i18n-allow-cjk`` on the same line to mark a literal
    as intentionally hardcoded (e.g. an AI-prompt default that must
    remain in Chinese regardless of UI locale). Use sparingly — every
    exemption is a potential translation regression.
"""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = REPO_ROOT / "scripts" / "check_i18n_js_no_cjk.py"


def _load_gate_module():
    """Import ``scripts/check_i18n_js_no_cjk.py`` as a module (the scripts
    folder is not on ``sys.path`` by default)."""
    spec = importlib.util.spec_from_file_location(
        "_aiia_check_i18n_js_no_cjk", SCRIPT_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class TestWebUiJsHasNoHardcodedCjk(unittest.TestCase):
    """No file under ``static/js/`` may contain a CJK string literal."""

    def test_webui_js_is_cjk_free(self) -> None:
        gate = _load_gate_module()
        violations = gate.collect_violations("webui")
        if violations:
            formatted = "\n".join(
                f"  {path.relative_to(REPO_ROOT).as_posix()}:{line}: {literal!r}"
                for path, line, literal in violations
            )
            self.fail(
                f"Found {len(violations)} hardcoded CJK string literal(s) "
                f"in Web UI JS sources:\n{formatted}\n"
                f"Move user-visible text to static/locales/*.json and "
                f"render via t('...'), or tag the line with "
                f"'// aiia:i18n-allow-cjk' if the literal is deliberately "
                f"hardcoded (e.g. AI prompt defaults)."
            )


if __name__ == "__main__":
    unittest.main()
