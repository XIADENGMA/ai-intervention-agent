"""R245 / Cycle 16 · HTML cascade-aware modal-not-inert structural invariant.

Why this invariant (Pattern A++, not just Pattern B)
----------------------------------------------------

R244 fixed a specific bug (R240 made modals inside ``.container``
inert because of HTML5 inert cascade). The R244 invariant test
verifies the *exact fix code* (helper exists, all 4 paths use it),
but it's still Pattern B (static-grep) at heart — it cannot detect
the **next** modal being added that lives inside an inerted ancestor.

R245 closes that gap by combining **HTML structural parse** with
**JS source analysis** to model the cascade:

1. Parse ``templates/web_ui.html`` to enumerate every
   ``role="dialog"`` element and its **ancestor chain** up to
   ``<body>``.
2. Parse ``app.js`` + ``settings-manager.js`` to enumerate which
   selectors (e.g., ``.container``) JS will programmatically mark
   ``inert`` on modal open.
3. For each dialog, verify that **none** of the JS inert targets
   appear in its ancestor chain — UNLESS the JS uses the R244
   sibling-iteration helper that explicitly skips the open dialog.

This means: **adding a new ``role="dialog"`` inside ``.container``
without using ``_setContainerSiblingsInert`` will FAIL this test
at commit time**, regardless of whether anyone updated R244's test.

Limitations
-----------

* This is a static cascade model, not a real browser test (which
  would be Playwright). It cannot catch dynamic DOM mutations
  (e.g., JS injecting a modal at runtime via createElement). For
  those cases, F-cycle16-playwright remains the canonical guard.
* Selector resolution is **simple ancestor-CSS-match**: this test
  recognises ``.container`` matching ``<div class="container">``
  but does not handle ``:not()``, ``:has()``, attribute selectors
  etc. (currently the codebase only uses class-name selectors for
  inert targets, so this is sufficient).
"""

from __future__ import annotations

import re
import unittest
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
WEB_UI_HTML = REPO_ROOT / "src" / "ai_intervention_agent" / "templates" / "web_ui.html"
APP_JS = REPO_ROOT / "src" / "ai_intervention_agent" / "static" / "js" / "app.js"
SETTINGS_JS = (
    REPO_ROOT
    / "src"
    / "ai_intervention_agent"
    / "static"
    / "js"
    / "settings-manager.js"
)

# Helpers that explicitly *exclude* the open dialog from the inert set.
# Detection ignores call-site-specific selectors and trusts the helper's
# implementation contract (which is itself guarded by R244).
SAFE_INERT_HELPERS = {"_setContainerSiblingsInert"}

# Direct-inert selectors that DO propagate to descendants. If any of
# these match an ancestor of a dialog, the test fails.
DANGEROUS_INERT_PATTERNS = (
    re.compile(
        r"(?:document\.querySelector|document\.getElementById)"
        r"\(\s*[\"']([^\"']+)[\"']\s*\)\.inert\s*=",
    ),
    re.compile(
        r"_safelySetInert\(\s*document\.querySelector\(\s*[\"']([^\"']+)[\"']\s*\)",
    ),
    re.compile(
        r"this\._safelySetInert\(\s*document\.querySelector\(\s*[\"']([^\"']+)[\"']\s*\)",
    ),
)


class _DialogAncestorCollector(HTMLParser):
    """Walks the DOM keeping a stack; records ancestor chain on every dialog."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._stack: list[tuple[str, dict[str, str | None]]] = []
        self.dialogs: list[dict[str, Any]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_d = dict(attrs)
        self._stack.append((tag, attrs_d))
        if tag == "div" and attrs_d.get("role") == "dialog":
            self.dialogs.append(
                {
                    "id": attrs_d.get("id") or "?",
                    "ancestors": list(self._stack[:-1]),
                }
            )

    def handle_endtag(self, tag: str) -> None:
        while self._stack and self._stack[-1][0] != tag:
            self._stack.pop()
        if self._stack:
            self._stack.pop()


def _selector_matches(selector: str, tag: str, attrs: dict[str, str | None]) -> bool:
    """Minimal CSS selector matcher (.class, #id, plain tag)."""
    selector = selector.strip()
    if selector.startswith("."):
        cls = (attrs.get("class") or "").split()
        return selector[1:] in cls
    if selector.startswith("#"):
        return attrs.get("id") == selector[1:]
    return tag == selector


def _collect_dialog_ancestors() -> list[dict[str, Any]]:
    html = WEB_UI_HTML.read_text(encoding="utf-8")
    html = re.sub(r"\{\{.*?\}\}", "PH", html, flags=re.DOTALL)
    html = re.sub(r"\{%.*?%\}", "", html, flags=re.DOTALL)
    parser = _DialogAncestorCollector()
    parser.feed(html)
    return parser.dialogs


def _collect_dangerous_inert_selectors(js_src: str) -> set[str]:
    """Return the set of CSS selectors that JS marks inert directly.

    Matches dangerous (direct-inert) patterns from ``DANGEROUS_INERT_PATTERNS``.
    Calls to SAFE_INERT_HELPERS are intentionally NOT collected because
    they explicitly skip the open dialog and are validated by R244.
    """
    selectors: set[str] = set()
    for pat in DANGEROUS_INERT_PATTERNS:
        for match in pat.finditer(js_src):
            selectors.add(match.group(1))
    return selectors


class TestNoDialogCascadeFromDirectInert(unittest.TestCase):
    """For every role=dialog, no ancestor matches any DANGEROUS direct-inert selector."""

    def test_no_dialog_has_direct_inert_ancestor(self) -> None:
        dialogs = _collect_dialog_ancestors()
        self.assertGreater(
            len(dialogs),
            0,
            "R245 sanity: 至少应该找到一个 role=dialog 元素 (#code-paste-panel "
            "or #settings-panel). 没找到说明 HTML 解析有问题, 或者 dialogs "
            "全被删了 (后者也不应该, 因为我们有 R237 守 dialog ARIA 合规)。",
        )

        app_src = APP_JS.read_text(encoding="utf-8")
        settings_src = SETTINGS_JS.read_text(encoding="utf-8")
        dangerous = _collect_dangerous_inert_selectors(app_src + "\n" + settings_src)

        failures: list[str] = []
        for dialog in dialogs:
            dialog_id = dialog["id"]
            for selector in dangerous:
                for ancestor_tag, ancestor_attrs in dialog["ancestors"]:
                    if _selector_matches(selector, ancestor_tag, ancestor_attrs):
                        failures.append(
                            f"  - dialog #{dialog_id} 的 ancestor "
                            f"<{ancestor_tag} class={ancestor_attrs.get('class')!r}> "
                            f"会被 JS 选中 selector {selector!r} 直接 .inert=, "
                            "这是 R240/R244 fix 之前的 buggy 模式. dialog 会"
                            "因 HTML5 cascade 也变 inert。"
                        )
                        break

        self.assertEqual(
            failures,
            [],
            "\nR245 invariant 失败: 检测到 dialog 处于 DANGEROUS direct-inert "
            "祖先链中。修复:\n"
            "  1. 改用 R244 的 _setContainerSiblingsInert(openModalEl, true/false) "
            "helper, 它会遍历 children 并跳过 openModalEl;\n"
            "  2. 或者把 dialog 移到该 inert 祖先**外面** (推荐做法: 直接挂在 "
            "<body> 下面, modern modal pattern)。\n"
            "失败明细:\n" + "\n".join(failures),
        )


class TestSafeHelperIsKnownToTest(unittest.TestCase):
    """Sanity guard: the helper allowlist must reference a real helper.

    If someone renames _setContainerSiblingsInert, this test fails so
    they remember to update R245 as well as R244.
    """

    def test_safe_inert_helper_exists_in_app_js(self) -> None:
        src = APP_JS.read_text(encoding="utf-8")
        for helper in SAFE_INERT_HELPERS:
            self.assertIn(
                helper,
                src,
                f"R245 sanity: SAFE_INERT_HELPERS allowlist 包含 "
                f"{helper!r}, 但 app.js 找不到该 helper。是不是 R244 helper "
                "被 rename 了？请同步更新 SAFE_INERT_HELPERS 和 R244 测试。",
            )

    def test_safe_inert_helper_exists_in_settings_js(self) -> None:
        src = SETTINGS_JS.read_text(encoding="utf-8")
        for helper in SAFE_INERT_HELPERS:
            self.assertIn(
                helper,
                src,
                f"R245 sanity: SAFE_INERT_HELPERS allowlist 包含 "
                f"{helper!r}, 但 settings-manager.js 找不到该 helper。"
                "R244 doctrine 要求两个文件保持一致。",
            )


if __name__ == "__main__":
    unittest.main()
