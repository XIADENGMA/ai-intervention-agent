"""P7·L1·step-6: ``templates/web_ui.html`` must not contain hardcoded
CJK text nodes or attribute values. Every user-visible label, tooltip,
placeholder, alt text, and aria-label must route through a ``data-i18n*``
attribute so the client ``translateDOM()`` pass can swap it by locale.

This is the pytest mirror of ``scripts/check_i18n_html_coverage.py``.
See that module's docstring for the full rationale; having both is
cheap and makes the invariant show up in local dev loops (pytest) *and*
CI gates.

Exemption contract:
    Append an HTML comment ``<!-- aiia:i18n-allow-cjk -->`` on the same
    line to whitelist a genuinely-untranslatable string (e.g. the
    ``简体中文`` language endonym in the language picker). Every
    exemption is a potential regression surface — audit carefully.
"""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = REPO_ROOT / "scripts" / "check_i18n_html_coverage.py"


def _load_gate_module():
    spec = importlib.util.spec_from_file_location(
        "_aiia_check_i18n_html_coverage", SCRIPT_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class TestHtmlTemplateI18nCoverage(unittest.TestCase):
    def test_web_ui_template_has_no_hardcoded_cjk(self) -> None:
        gate = _load_gate_module()
        template = gate.TEMPLATE_PATH
        self.assertTrue(
            template.is_file(),
            msg=f"Expected template at {template} to exist",
        )
        violations = gate.scan_template(template)
        if violations:
            formatted = "\n".join(
                f"  line {line}: hardcoded CJK in {kind}: {snippet!r}"
                for line, kind, snippet in violations
            )
            self.fail(
                f"Found {len(violations)} hardcoded CJK occurrence(s) in "
                f"{template.relative_to(REPO_ROOT).as_posix()}:\n{formatted}\n"
                f"Replace the text with a data-i18n* attribute (data-i18n, "
                f"data-i18n-html, data-i18n-title, data-i18n-placeholder, "
                f"data-i18n-alt, data-i18n-aria-label, or data-i18n-value) "
                f"and move the copy into static/locales/*.json."
            )


if __name__ == "__main__":
    unittest.main()
