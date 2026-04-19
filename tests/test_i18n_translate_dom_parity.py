"""T1·C10c 跨端 parity 守卫：``AIIA_I18N.translateDOM``。

``static/js/tri-state-panel-bootstrap.js``（由 ``package_vscode_vsix.mjs``
byte-mirror 到 VSCode 侧）在 panel 挂载后调用 ``translateDOM(rootEl)``
把 13 个 ``data-i18n="aiia.state.*"`` 串 i18n 化（bootstrap §Behavior §3）。
合约首源于 BEST_PRACTICES_PLAN.tmp.md §T1 v3 §4：

  > SSR + data-i18n 双写不是冗余：SSR 防 JS 失败时首屏空白；
  > data-i18n 喂客户端 translateDOM(rootEl) 让语言切换无需重渲染。

Web UI 侧一直有 ``translateDOM``；VSCode 侧早期缺，导致 bootstrap 调用
在 VSCode 沦为静默 no-op。本文件锁不变量：两份 ``i18n.js`` 必须都导出
``translateDOM`` 且扫同样四种 ``data-i18n[-variant]`` 属性集合。

捕获的失败模式：
  1. 任一侧移掉 ``translateDOM`` → bootstrap 本地化步骤变 dead code；
  2. 只在单侧加 ``data-i18n-foo`` → 语言切换 retranslation 不对称；
  3. 函数体在但未挂到 ``AIIA_I18N`` 公共 API → settings-manager.js 等
     消费者静默失效。

走静态分析而非 JSDOM：这些 IIFE 跑在 ``window.AIIA_I18N`` 副作用里；
runtime 行为由 ``test_runtime_behavior.py`` 覆盖，结构断言足够挡 §T1 v3
记录的那种漂移。
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
STATIC_I18N = REPO_ROOT / "static" / "js" / "i18n.js"
VSCODE_I18N = REPO_ROOT / "packages" / "vscode" / "i18n.js"

EXPECTED_TRANSLATE_SELECTORS = frozenset(
    {
        "[data-i18n]",
        "[data-i18n-title]",
        "[data-i18n-html]",
        "[data-i18n-placeholder]",
        "[data-i18n-alt]",
        "[data-i18n-aria-label]",
        "[data-i18n-value]",
    }
)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _extract_translate_selectors(src: str) -> set[str]:
    """Pull every ``[data-i18n...]`` selector out of the ``translateDOM``
    function body. Supports two source styles:

    1. **Literal**: ``querySelectorAll('[data-i18n-foo]')`` — the selector
       appears verbatim in a string literal. Used for the base
       ``data-i18n`` and ``data-i18n-html`` (text content / innerHTML)
       branches which can't share a binding table because they invoke
       different setters.

    2. **Binding-table driven**: ``{ dataAttr: 'data-i18n-foo', target: ...,
       setter: ... }`` — the selector is derived at runtime via
       ``'[' + binding.dataAttr + ']'``. Used for attribute-style bindings
       (title / placeholder / alt / aria-label / value) so adding a new
       attribute is a single table row, not three duplicated loops.

    Both sources are merged into one selector set because the contract is
    "what translateDOM scans", not "what syntax the source uses". If a
    future change decides to expand the binding table back into literal
    branches (or vice versa), this parser still sees the same set.
    """
    literal = set(
        re.findall(
            r"querySelectorAll\(\s*['\"](\[data-i18n[-\w]*\])['\"]\s*\)",
            src,
        )
    )
    table_keys = set(
        re.findall(
            r"dataAttr\s*:\s*['\"](data-i18n[-\w]*)['\"]",
            src,
        )
    )
    table_selectors = {"[" + k + "]" for k in table_keys}
    return literal | table_selectors


class TestTranslateDomSymbolParity(unittest.TestCase):
    """Both i18n.js files MUST expose AIIA_I18N.translateDOM publicly."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.web_src = _read(STATIC_I18N)
        cls.vsc_src = _read(VSCODE_I18N)

    def _assert_api_exposes_translate_dom(self, src: str, label: str) -> None:
        self.assertRegex(
            src,
            r"translateDOM\s*:\s*translateDOM",
            msg=(
                f"{label}::AIIA_I18N must expose ``translateDOM`` in its "
                f"public api object. Without this, "
                f"``tri-state-panel-bootstrap.js::translatePanel()`` silently "
                f"no-ops on this half and the 13 aiia.state.* strings never "
                f"get re-translated on language switch (user-visible regression "
                f"if SSR is bypassed or a future commit adds a client-only "
                f"aiia.* data-i18n node).\n"
                f"Fix: add ``translateDOM: translateDOM,`` to the api object."
            ),
        )

    def test_static_side_exposes_translate_dom(self) -> None:
        self._assert_api_exposes_translate_dom(self.web_src, "static/js/i18n.js")

    def test_vscode_side_exposes_translate_dom(self) -> None:
        self._assert_api_exposes_translate_dom(self.vsc_src, "packages/vscode/i18n.js")

    def test_function_definition_exists_on_both_sides(self) -> None:
        """The symbol in the api object must point at a real function —
        detect accidental removal of the function body while leaving
        the api entry stale."""
        for src, label in (
            (self.web_src, "static/js/i18n.js"),
            (self.vsc_src, "packages/vscode/i18n.js"),
        ):
            self.assertRegex(
                src,
                r"function\s+translateDOM\s*\(",
                msg=(
                    f"{label} exposes ``translateDOM`` in its api object but "
                    f"has no ``function translateDOM(...)`` definition. "
                    f"The api entry resolves to ``undefined`` at call time."
                ),
            )


class TestTranslateDomAttributeCoverageParity(unittest.TestCase):
    """Both ``translateDOM`` implementations MUST scan the same set of
    ``data-i18n[-variant]`` attributes. Asymmetry here means a language
    switch leaves stale text on one half (e.g. ``data-i18n-placeholder``
    updated on Web UI but not on VSCode)."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.web_src = _read(STATIC_I18N)
        cls.vsc_src = _read(VSCODE_I18N)

    def _expected_contract(self) -> str:
        return (
            "{data-i18n, data-i18n-title, data-i18n-html, data-i18n-placeholder, "
            "data-i18n-alt, data-i18n-aria-label, data-i18n-value}"
        )

    def test_web_covers_all_expected_selectors(self) -> None:
        selectors = _extract_translate_selectors(self.web_src)
        missing = sorted(EXPECTED_TRANSLATE_SELECTORS - selectors)
        extra = sorted(selectors - EXPECTED_TRANSLATE_SELECTORS)
        if missing or extra:
            self.fail(
                "static/js/i18n.js::translateDOM scans an unexpected "
                f"selector set.\n  missing = {missing}\n  extra   = {extra}\n"
                "Fix: align with the documented contract "
                f"{self._expected_contract()} "
                "or update EXPECTED_TRANSLATE_SELECTORS + the VSCode mirror "
                "in lockstep."
            )

    def test_vscode_covers_all_expected_selectors(self) -> None:
        selectors = _extract_translate_selectors(self.vsc_src)
        missing = sorted(EXPECTED_TRANSLATE_SELECTORS - selectors)
        extra = sorted(selectors - EXPECTED_TRANSLATE_SELECTORS)
        if missing or extra:
            self.fail(
                "packages/vscode/i18n.js::translateDOM scans an unexpected "
                f"selector set.\n  missing = {missing}\n  extra   = {extra}\n"
                "Fix: align with the documented contract "
                f"{self._expected_contract()} "
                "or update EXPECTED_TRANSLATE_SELECTORS + the Web UI source "
                "in lockstep."
            )

    def test_selector_sets_match_between_halves(self) -> None:
        """Belt-and-suspenders symmetry check: even if both sides drift
        together (e.g. both add ``data-i18n-foo``), the two sets must
        stay identical so there is no half-migrated state where only
        one UI responds to language switches."""
        web_sel = _extract_translate_selectors(self.web_src)
        vsc_sel = _extract_translate_selectors(self.vsc_src)
        self.assertEqual(
            web_sel,
            vsc_sel,
            msg=(
                f"translateDOM selector sets diverged between Web UI "
                f"({sorted(web_sel)}) and VSCode ({sorted(vsc_sel)}). "
                f"Both halves must scan the same ``data-i18n[-variant]`` "
                f"attribute set so language switching is symmetric."
            ),
        )


if __name__ == "__main__":
    unittest.main()
