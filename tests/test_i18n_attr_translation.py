"""P7·L4：属性 i18n binding 覆盖（``data-i18n-alt`` / ``-aria-label`` /
``-value`` / ``-title`` / ``-placeholder``）。

P7 之前 ``translateDOM`` 只覆盖 4 种属性（text/html/title/placeholder），
留下三类坑：
  * ``aria-label`` 是 icon-only 按钮唯一的 accessible name，非中文 locale
    下会被 ``templates/web_ui.html`` 里硬写的中文冻住；
  * ``alt`` 同款 a11y 回归；
  * ``value``——``<input type=button/submit>`` 等场景，先行覆盖避免未来又一轮
    「加第五个属性」重构。

P7 把 4 份重复循环合并成单一 ``ATTR_BINDINGS`` 表。本文件锁 3 条不变量：
  1. 5 种属性全部在 binding 表中；
  2. 每个 binding 的 setter 正确（``property`` 还是 ``attribute``）——
     ``aria-label`` 不是 DOM property，走 property 赋值会在部分浏览器
     静默 no-op；
  3. Web UI + VSCode 两侧 binding 完全相同（selector 级由
     ``test_i18n_translate_dom_parity.py`` 看管，这里扩到 setter 策略）。

走静态分析而非 jsdom：binding 表是纯字面量数据，模式匹配够了；
``test_runtime_behavior.py`` 已端到端覆盖字典层。
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
