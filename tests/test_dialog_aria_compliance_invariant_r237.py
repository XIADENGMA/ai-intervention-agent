"""R237 / Cycle 15: every `role="dialog"` modal carries full ARIA compliance.

Why this invariant
------------------

The Cycle 14 a11y wave (R230 SVGs → R232 icon-only buttons → R235
form inputs) closed gaps on graphical and form-input controls. R237
locks the **dialog/modal layer**: any element with ``role="dialog"``
must also expose:

1. ``aria-modal="true"`` — tells AT this is a *modal* (focus should
   not escape back to the page underneath). Required by WAI-ARIA 1.2
   for true modals.
2. Either ``aria-labelledby="…"`` or ``aria-label="…"`` — the dialog
   needs an *accessible name* (WCAG 4.1.2). Without it screen reader
   says only "dialog".

Why an invariant rather than a refactor:

A scan of ``web_ui.html`` shows the existing 2 dialogs
(``#code-paste-panel`` + ``#settings-panel``) **already** have all 3
attributes. R237 is a "lock current good state" invariant in the same
spirit as R232 (icon-only buttons): the discipline existed silently in
code reviews, R237 makes it a hard contract so a future contributor
adding a 3rd dialog without ``aria-modal`` will get a clear failure.

Out of scope (deliberate, follow-up R238): actual focus-trap behavior
(Tab/Shift-Tab cycling within modal + focus restore on close +
`inert` on background). R237 locks the **declarative ARIA contract**;
R238 will tackle the imperative focus-management contract.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
HTML_PATH = REPO_ROOT / "src" / "ai_intervention_agent" / "templates" / "web_ui.html"

DIALOG_OPEN_PATTERN = re.compile(
    r'<(?P<tag>\w+)\b([^>]*?\brole="dialog"[^>]*)>',
    re.DOTALL,
)


def _read_html() -> str:
    return HTML_PATH.read_text(encoding="utf-8")


def _attr(attrs_blob: str, name: str) -> str | None:
    m = re.search(rf"\b{re.escape(name)}=\"([^\"]*)\"", attrs_blob)
    return m.group(1) if m else None


def _enumerate_dialogs(html: str) -> list[tuple[int, str, str]]:
    """Returns [(line_no, tag, attrs_blob)] for every element with role=dialog."""
    out: list[tuple[int, str, str]] = []
    for m in DIALOG_OPEN_PATTERN.finditer(html):
        line_no = html[: m.start()].count("\n") + 1
        out.append((line_no, m.group("tag"), m.group(2)))
    return out


class TestDialogHasAriaModalTrue(unittest.TestCase):
    def test_every_role_dialog_has_aria_modal_true(self) -> None:
        html = _read_html()
        dialogs = _enumerate_dialogs(html)
        self.assertGreaterEqual(
            len(dialogs),
            2,
            msg=(
                "R237 sanity: web_ui.html 至少包含 2 个 role='dialog' 元素 "
                "(#code-paste-panel + #settings-panel)。若小于 2, 可能存在"
                "结构重构, 请更新此测试或检查是否漏标 role。"
            ),
        )

        failures: list[str] = []
        for line_no, tag, attrs in dialogs:
            elem_id = _attr(attrs, "id") or "(no id)"
            aria_modal = _attr(attrs, "aria-modal")
            if aria_modal != "true":
                failures.append(
                    f"  L{line_no} <{tag} id={elem_id}>: aria-modal={aria_modal!r}, "
                    f"必须是 'true'"
                )
        self.assertEqual(
            failures,
            [],
            msg=(
                "R237 invariant: 每个 role='dialog' 必须有 aria-modal='true' "
                "(WAI-ARIA 1.2). 没有 aria-modal 屏幕阅读器会把 dialog 当作"
                "普通区块, 用户 swipe 时可能漂到背景内容上, 失去 modal 隔离感:\n"
                + "\n".join(failures)
            ),
        )


class TestDialogHasAccessibleName(unittest.TestCase):
    def test_every_role_dialog_has_label(self) -> None:
        html = _read_html()
        dialogs = _enumerate_dialogs(html)
        failures: list[str] = []
        for line_no, tag, attrs in dialogs:
            elem_id = _attr(attrs, "id") or "(no id)"
            labelledby = _attr(attrs, "aria-labelledby")
            label = _attr(attrs, "aria-label")
            if not (labelledby or label):
                failures.append(
                    f"  L{line_no} <{tag} id={elem_id}>: 同时缺 aria-labelledby "
                    f"与 aria-label"
                )
        self.assertEqual(
            failures,
            [],
            msg=(
                "R237 invariant: 每个 role='dialog' 必须有 aria-labelledby "
                "(指向标题元素 id) 或 aria-label (字面 string)。WCAG 4.1.2 "
                "(Name, Role, Value): 没 accessible name 的 dialog, 屏幕阅读器"
                "只能说 'dialog', 用户不知道这是什么对话框:\n" + "\n".join(failures)
            ),
        )

    def test_labelledby_targets_exist(self) -> None:
        """aria-labelledby 指的 id 必须真实存在于同文档, 否则等于没标签。"""
        html = _read_html()
        dialogs = _enumerate_dialogs(html)
        failures: list[str] = []
        for line_no, tag, attrs in dialogs:
            labelledby = _attr(attrs, "aria-labelledby")
            if not labelledby:
                continue
            for target_id in labelledby.split():
                pattern = rf"\bid=\"{re.escape(target_id)}\""
                if not re.search(pattern, html):
                    elem_id = _attr(attrs, "id") or "(no id)"
                    failures.append(
                        f"  L{line_no} <{tag} id={elem_id}>: "
                        f"aria-labelledby='{labelledby}' 指向 id='{target_id}' "
                        f"但该 id 不存在 (dangling reference, 等于无 label)"
                    )
        self.assertEqual(failures, [])


class TestDialogStartsHiddenViaClass(unittest.TestCase):
    """所有 role=dialog 默认 hidden, 由 JS 显示。防止页面加载即拦截焦点。"""

    def test_every_role_dialog_starts_hidden_or_has_hidden_attr(self) -> None:
        html = _read_html()
        dialogs = _enumerate_dialogs(html)
        failures: list[str] = []
        for line_no, tag, attrs in dialogs:
            elem_id = _attr(attrs, "id") or "(no id)"
            classes = _attr(attrs, "class") or ""
            has_hidden_attr = re.search(r"\bhidden\b(?!\w)", attrs) is not None
            has_hidden_class = "hidden" in classes.split()
            if not (has_hidden_attr or has_hidden_class):
                failures.append(
                    f"  L{line_no} <{tag} id={elem_id}>: class='{classes}' 不含 "
                    f"'hidden' 且无 hidden attribute (会在 page-load 就显示)"
                )
        self.assertEqual(
            failures,
            [],
            msg=(
                "R237 invariant: role='dialog' 元素必须以 class='hidden' 或 "
                "[hidden] attribute 默认隐藏, 由 JS 在用户触发时显示。如果 "
                "page-load 即显示, modal 会立刻 trap 焦点, 用户主页面不可"
                "操作:\n" + "\n".join(failures)
            ),
        )


if __name__ == "__main__":
    unittest.main()
