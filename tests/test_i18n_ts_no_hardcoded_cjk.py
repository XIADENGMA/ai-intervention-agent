"""L2·G6: VSCode extension host TypeScript sources must not contain
hardcoded CJK string literals.

Scope
-----
Mirrors ``scripts/check_i18n_ts_no_cjk.py`` as a pytest assertion so
regressions surface before a contributor even stages a commit. Extension
host code (``packages/vscode/*.ts``) runs on the Node side and its
user-facing strings go through ``vscode.l10n.t(...)`` backed by
``packages/vscode/l10n/bundle.l10n.*.json``. Any inline CJK literal here
either bypasses translation (zh-CN text in en IDE, or vice versa) or
leaks through to status bar / error toasts / diagnostic logs.

The webview JS side is covered by
``tests/test_i18n_js_no_hardcoded_cjk.py``; together they form the
i18n string-literal gate for every runtime that ships to the end user.

Exemption contract
------------------
Append ``// aiia:i18n-allow-cjk`` on the same line to mark a literal as
intentionally hardcoded. Use sparingly — every exemption is a potential
translation regression that will never be reported in the bug tracker
because the affected users cannot read the English test output.
"""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = REPO_ROOT / "scripts" / "check_i18n_ts_no_cjk.py"


def _load_gate_module():
    """Import ``scripts/check_i18n_ts_no_cjk.py`` as a module (the scripts
    folder is not on ``sys.path`` by default)."""
    spec = importlib.util.spec_from_file_location(
        "_aiia_check_i18n_ts_no_cjk", SCRIPT_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class TestVscodeExtensionHostTsHasNoHardcodedCjk(unittest.TestCase):
    """No file under ``packages/vscode/*.ts`` may contain a CJK string
    literal outside ``// aiia:i18n-allow-cjk``-tagged lines."""

    def test_extension_host_ts_is_cjk_free(self) -> None:
        gate = _load_gate_module()
        violations = gate.collect_violations()
        if violations:
            formatted = "\n".join(
                f"  {path.relative_to(REPO_ROOT).as_posix()}:{line}: {literal!r}"
                for path, line, literal in violations
            )
            self.fail(
                f"Found {len(violations)} hardcoded CJK string literal(s) "
                f"in packages/vscode/*.ts sources:\n{formatted}\n"
                f"Wrap user-visible text in vscode.l10n.t(...) and add "
                f"the English source string to packages/vscode/l10n/"
                f"bundle.l10n.json (plus matching locale bundles), or tag "
                f"the line with '// aiia:i18n-allow-cjk' if the literal "
                f"is deliberately hardcoded."
            )


if __name__ == "__main__":
    unittest.main()
