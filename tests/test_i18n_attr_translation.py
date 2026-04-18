"""P7·L4: attribute-style i18n binding coverage (``data-i18n-alt``,
``data-i18n-aria-label``, ``data-i18n-value``, ``data-i18n-title``,
``data-i18n-placeholder``).

Background:
    Historically ``AIIA_I18N.translateDOM`` only handled four attribute
    variants: ``data-i18n`` (textContent), ``data-i18n-html`` (innerHTML),
    ``data-i18n-title`` and ``data-i18n-placeholder``. That left a gap
    for two very common cases:

    * ``aria-label`` — the only way to provide an accessible name for
      icon-only buttons (settings gear, theme toggle, close button). On a
      non-Chinese locale these were silently frozen to the Chinese strings
      hard-coded in ``templates/web_ui.html`` (e.g. ``aria-label="切换主题"``).
    * ``alt`` — image alt text for preview thumbnails and inline icons,
      same accessibility regression as above.
    * ``value`` — the text label on ``<input type="button">`` / ``<input
      type="submit">`` and (rare) ``<option>`` / ``<button value="...">``
      cases. Not used heavily yet but covered pre-emptively so future
      authors don't hit another "add a fifth attribute" round of
      refactoring.

    The P7 rewrite collapsed the four duplicated loops into a single
    ``ATTR_BINDINGS`` table in both ``static/js/i18n.js`` and
    ``packages/vscode/i18n.js``. This test pins three invariants against
    that table:

    1. All five expected attributes are declared in the binding table.
    2. Each binding correctly identifies itself as ``property`` (el[x]=v)
       or ``attribute`` (el.setAttribute(x, v)) — critical because
       ``aria-label`` is NOT a DOM property on ``HTMLElement`` (it is only
       exposed as an attribute, so property-assignment silently no-ops
       on some browsers).
    3. Both halves (Web UI + VSCode) declare identical bindings — this
       is the cross-platform parity guard already enforced at the
       selector level by ``test_i18n_translate_dom_parity.py``, extended
       here to cover the setter strategy as well.

Why static analysis instead of jsdom:
    Running the real ``translateDOM`` against a jsdom harness would be
    more end-to-end, but it would also introduce a Node / jsdom runtime
    dependency that the rest of ``tests/`` deliberately avoids. The
    binding table is a single shape of literal data so pattern-matching
    is sufficient. ``test_runtime_behavior.py`` already covers the dict
    layer end-to-end; the missing layer was "does translateDOM cover the
    attribute we added data-i18n-aria-label for?" which is exactly what
    this test asserts.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
STATIC_I18N = REPO_ROOT / "static" / "js" / "i18n.js"
VSCODE_I18N = REPO_ROOT / "packages" / "vscode" / "i18n.js"

BINDING_RE = re.compile(
    r"""
    \{\s*
    dataAttr\s*:\s*['"](?P<attr>data-i18n[-\w]*)['"]\s*,\s*
    target\s*:\s*['"](?P<target>[\w-]+)['"]\s*,\s*
    setter\s*:\s*['"](?P<setter>property|attribute)['"]\s*
    \}
    """,
    re.VERBOSE,
)

# Expected bindings per the P7 contract. (data-i18n, data-i18n-html) are
# NOT in this list because they are handled by the textContent / innerHTML
# branches that must stay outside the binding table (different semantics).
EXPECTED_BINDINGS: dict[str, tuple[str, str]] = {
    "data-i18n-title": ("title", "property"),
    "data-i18n-placeholder": ("placeholder", "property"),
    "data-i18n-alt": ("alt", "property"),
    "data-i18n-aria-label": ("aria-label", "attribute"),
    "data-i18n-value": ("value", "property"),
}


def _parse_bindings(src: str) -> dict[str, tuple[str, str]]:
    """Parse the ``ATTR_BINDINGS`` table from an i18n.js source file.

    Returns a dict keyed by ``dataAttr`` mapping to ``(target, setter)``.
    If the table is absent or the individual row shape drifts, the
    returned dict will be empty (or missing entries) which the tests
    below translate into actionable failure messages.
    """
    result: dict[str, tuple[str, str]] = {}
    for match in BINDING_RE.finditer(src):
        result[match.group("attr")] = (match.group("target"), match.group("setter"))
    return result


class TestAttributeBindingCoverage(unittest.TestCase):
    """Both halves MUST declare all five attribute bindings with the
    right setter strategy."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.web_bindings = _parse_bindings(STATIC_I18N.read_text(encoding="utf-8"))
        cls.vsc_bindings = _parse_bindings(VSCODE_I18N.read_text(encoding="utf-8"))

    def _assert_covers_expected(
        self, bindings: dict[str, tuple[str, str]], label: str
    ) -> None:
        missing = sorted(set(EXPECTED_BINDINGS) - set(bindings))
        self.assertFalse(
            missing,
            msg=(
                f"{label}::ATTR_BINDINGS is missing expected entries: "
                f"{missing}. These attributes are required for i18n on "
                f"icon-only buttons (aria-label), image previews (alt), "
                f"and input labels (value). Without them, HTML templates "
                f"using data-i18n-<attr> will silently fail to translate."
            ),
        )

    def _assert_setter_strategy(
        self, bindings: dict[str, tuple[str, str]], label: str
    ) -> None:
        for attr, (expected_target, expected_setter) in EXPECTED_BINDINGS.items():
            if attr not in bindings:
                continue
            got_target, got_setter = bindings[attr]
            self.assertEqual(
                got_target,
                expected_target,
                msg=(
                    f"{label}::ATTR_BINDINGS[{attr!r}] has wrong target "
                    f"(got {got_target!r}, expected {expected_target!r}). "
                    f"The target is the DOM property / attribute name "
                    f"that will receive the translated value."
                ),
            )
            self.assertEqual(
                got_setter,
                expected_setter,
                msg=(
                    f"{label}::ATTR_BINDINGS[{attr!r}] uses setter "
                    f"{got_setter!r} but should use {expected_setter!r}. "
                    f"NOTE: 'aria-label' is NOT a DOM property on "
                    f"HTMLElement (WAI-ARIA 1.x), so setting "
                    f"el['aria-label'] = value creates an expando instead "
                    f"of updating the attribute accessible to screen "
                    f"readers. It MUST use setAttribute(), i.e. "
                    f"setter='attribute'. Other attributes (title, "
                    f"placeholder, alt, value) are reflected as properties "
                    f"per HTML spec, so property-setter is both legal and "
                    f"faster than setAttribute."
                ),
            )

    def test_web_covers_all_expected_bindings(self) -> None:
        self._assert_covers_expected(self.web_bindings, "static/js/i18n.js")

    def test_vscode_covers_all_expected_bindings(self) -> None:
        self._assert_covers_expected(self.vsc_bindings, "packages/vscode/i18n.js")

    def test_web_uses_correct_setter_strategy(self) -> None:
        self._assert_setter_strategy(self.web_bindings, "static/js/i18n.js")

    def test_vscode_uses_correct_setter_strategy(self) -> None:
        self._assert_setter_strategy(self.vsc_bindings, "packages/vscode/i18n.js")

    def test_binding_tables_match_across_halves(self) -> None:
        """Defense-in-depth: even if both halves drift in lockstep from
        the EXPECTED_BINDINGS dict above, they must not drift apart from
        each other. This catches the case where only one side was updated
        (e.g. added data-i18n-foo on Web UI but forgot VSCode mirror)."""
        self.assertEqual(
            self.web_bindings,
            self.vsc_bindings,
            msg=(
                f"ATTR_BINDINGS drift detected between halves.\n"
                f"  web = {self.web_bindings}\n"
                f"  vsc = {self.vsc_bindings}\n"
                f"Both must stay identical (see BEST_PRACTICES_PLAN.tmp.md "
                f"§T1 v3 §4 cross-platform contract)."
            ),
        )


class TestBindingTableSelfConsistency(unittest.TestCase):
    """Defensive tests that document invariants the binding mechanism
    relies on, so a future refactor doesn't silently violate them."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.web_src = STATIC_I18N.read_text(encoding="utf-8")
        cls.vsc_src = VSCODE_I18N.read_text(encoding="utf-8")

    def _assert_table_then_loop(self, src: str, label: str) -> None:
        """ATTR_BINDINGS must be declared BEFORE translateDOM's binding
        loop. Otherwise the loop captures an undefined reference at
        function-definition time in strict mode, or iterates over an
        empty array in sloppy mode — both silent regressions."""
        idx_table = src.find("ATTR_BINDINGS")
        idx_loop = src.find("ATTR_BINDINGS.length")
        self.assertGreaterEqual(
            idx_table,
            0,
            msg=f"{label} has no ATTR_BINDINGS declaration",
        )
        self.assertGreaterEqual(
            idx_loop,
            0,
            msg=f"{label} has no ATTR_BINDINGS iteration loop",
        )
        self.assertLess(
            idx_table,
            idx_loop,
            msg=(
                f"{label}: ATTR_BINDINGS must be declared before it is "
                f"iterated. Declaration starts at index {idx_table}, "
                f"loop starts at index {idx_loop}."
            ),
        )

    def test_web_table_precedes_loop(self) -> None:
        self._assert_table_then_loop(self.web_src, "static/js/i18n.js")

    def test_vscode_table_precedes_loop(self) -> None:
        self._assert_table_then_loop(self.vsc_src, "packages/vscode/i18n.js")


if __name__ == "__main__":
    unittest.main()
