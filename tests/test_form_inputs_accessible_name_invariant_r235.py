"""R235 / Cycle 14 · F-cycle13 a11y wave: every form input has an accessible name.

Why this invariant
------------------

R230 hid 29 decorative SVGs from screen readers. R232 then locked
that all icon-only ``<button>`` / ``<a role="button">`` elements
have ``aria-label``. Both protect graphical controls.

R235 closes the symmetric gap on the **text/data input** side: every
``<input>`` (except hidden / submit / button / reset variants) and
every ``<textarea>`` in ``web_ui.html`` must have an accessible name
exposed to assistive technology — or be explicitly removed from the
a11y tree via ``aria-hidden="true"`` (the
programmatically-driven-hidden-file-input pattern, e.g.
``#file-upload-input`` + ``#quick-phrases-import-file``).

Accepted accessible-name sources (WCAG 4.1.2 + WAI-ARIA 1.2):

1. **Wrapping label** — ``<label class="..."><input ...></label>``.
   This is the dominant pattern in the settings panel (every
   ``setting-item`` is a wrapping label).
2. **Explicit label** — ``<label for="foo">Bar</label>`` paired with
   ``<input id="foo">``.
3. **``aria-label="…"``** — direct annotation.
4. **``aria-labelledby="other-id"``** — references another element's
   text.
5. **``aria-hidden="true"``** — input is *intentionally* removed from
   the a11y tree (the file-input pattern, where a separate visible
   button with its own ``aria-label`` drives ``.click()``). The
   invariant additionally requires ``tabindex="-1"`` so keyboard
   users cannot land on it via Tab.

Discovery context
-----------------

The audit script that produced R235 found 2 inputs in ``web_ui.html``
with no accessible name: ``#file-upload-input`` (L799) had only
``class="hidden"`` while ``#quick-phrases-import-file`` (L852) had
``aria-hidden="true"`` + ``tabindex="-1"``. R235 brings them to a
single pattern and locks it.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
HTML_PATH = REPO_ROOT / "src" / "ai_intervention_agent" / "templates" / "web_ui.html"

SKIP_INPUT_TYPES = frozenset({"hidden", "submit", "button", "reset", "image"})

ATTR_PATTERN = re.compile(r"<input\b([^>]*?)>", re.DOTALL)
TEXTAREA_PATTERN = re.compile(r"<textarea\b([^>]*?)>", re.DOTALL)


def _read_html() -> str:
    return HTML_PATH.read_text(encoding="utf-8")


def _attr(attrs: str, name: str) -> str | None:
    match = re.search(rf"\b{re.escape(name)}=\"([^\"]*)\"", attrs)
    return match.group(1) if match else None


def _has_attr(attrs: str, name: str) -> bool:
    return re.search(rf"\b{re.escape(name)}=", attrs) is not None


def _is_wrapped_in_label(open_pos: int, html: str) -> bool:
    """True iff the most recent unbalanced `<label>` open is still open at `open_pos`."""
    before = html[:open_pos]
    last_open = before.rfind("<label")
    last_close = before.rfind("</label>")
    return last_open > last_close


def _has_explicit_label(input_id: str, html: str) -> bool:
    return bool(re.search(rf"<label[^>]*\bfor=\"{re.escape(input_id)}\"", html))


def _enumerate_inputs(html: str) -> list[tuple[int, str, str]]:
    """Returns [(line_no, attrs_str, kind)] for non-skipped inputs + textareas."""
    items: list[tuple[int, str, str]] = []

    for m in ATTR_PATTERN.finditer(html):
        attrs = m.group(1)
        elem_type = _attr(attrs, "type") or "text"
        if elem_type in SKIP_INPUT_TYPES:
            continue
        line_no = html[: m.start()].count("\n") + 1
        items.append((line_no, attrs, "input"))

    for m in TEXTAREA_PATTERN.finditer(html):
        attrs = m.group(1)
        line_no = html[: m.start()].count("\n") + 1
        items.append((line_no, attrs, "textarea"))

    return items


def _input_has_accessible_name(
    attrs: str, open_pos: int, html: str
) -> tuple[bool, str]:
    """Returns (ok, reason). ok=True if the input is properly labeled or
    intentionally aria-hidden."""
    if _has_attr(attrs, "aria-label"):
        return True, "aria-label"
    if _has_attr(attrs, "aria-labelledby"):
        return True, "aria-labelledby"

    aria_hidden = _attr(attrs, "aria-hidden")
    if aria_hidden == "true":
        tabindex = _attr(attrs, "tabindex")
        if tabindex == "-1":
            return True, "aria-hidden=true + tabindex=-1"
        return False, "aria-hidden=true but tabindex!=-1 (keyboard Tab can still focus)"

    input_id = _attr(attrs, "id")
    if input_id and _has_explicit_label(input_id, html):
        return True, f"<label for='{input_id}'>"

    if _is_wrapped_in_label(open_pos, html):
        return True, "wrapping <label>"

    return False, "no accessible name (no label, no aria-label, no aria-hidden)"


class TestEveryFormInputHasAccessibleName(unittest.TestCase):
    """所有 form input 必须有 accessible name (WCAG 4.1.2)。"""

    def test_inputs_and_textareas_all_have_accessible_name(self) -> None:
        html = _read_html()

        failures: list[str] = []
        for m in ATTR_PATTERN.finditer(html):
            attrs = m.group(1)
            elem_type = _attr(attrs, "type") or "text"
            if elem_type in SKIP_INPUT_TYPES:
                continue
            line_no = html[: m.start()].count("\n") + 1
            ok, reason = _input_has_accessible_name(attrs, m.start(), html)
            if not ok:
                input_id = _attr(attrs, "id") or "(no id)"
                failures.append(
                    f"  L{line_no} <input type={elem_type} id={input_id}>: {reason}"
                )

        for m in TEXTAREA_PATTERN.finditer(html):
            attrs = m.group(1)
            line_no = html[: m.start()].count("\n") + 1
            ok, reason = _input_has_accessible_name(attrs, m.start(), html)
            if not ok:
                input_id = _attr(attrs, "id") or "(no id)"
                failures.append(f"  L{line_no} <textarea id={input_id}>: {reason}")

        self.assertEqual(
            failures,
            [],
            msg=(
                "R235 invariant: 所有 <input> 与 <textarea> 必须有 accessible name "
                "之一: (1) 包裹 <label>, (2) <label for=id>, (3) aria-label, "
                "(4) aria-labelledby, 或 (5) aria-hidden=true + tabindex=-1。"
                "WCAG 4.1.2 (Name, Role, Value) 违反:\n" + "\n".join(failures)
            ),
        )


class TestHiddenFileInputPatternIsConsistent(unittest.TestCase):
    """programmatically-clicked <input type='file' class='hidden'> 必须用 R235 pattern.

    web_ui.html 现有 2 个 #file-upload-input + #quick-phrases-import-file,
    两个都用 class='hidden' 隐藏后由可见按钮 .click() 路由焦点。R235 之前
    这两个 input 配置不一致, R235 后必须统一为
    `aria-hidden='true' + tabindex='-1'`。
    """

    def test_all_hidden_file_inputs_use_the_pattern(self) -> None:
        html = _read_html()

        hidden_file_inputs: list[tuple[int, str]] = []
        for m in ATTR_PATTERN.finditer(html):
            attrs = m.group(1)
            if _attr(attrs, "type") != "file":
                continue
            cls = _attr(attrs, "class") or ""
            if "hidden" not in cls.split():
                continue
            line_no = html[: m.start()].count("\n") + 1
            hidden_file_inputs.append((line_no, attrs))

        self.assertGreaterEqual(
            len(hidden_file_inputs),
            2,
            msg=(
                "R235 sanity: 至少存在 2 个 hidden file input "
                "(file-upload-input + quick-phrases-import-file); "
                "若少于 2, pattern 可能被重构, 请更新此测试。"
            ),
        )

        failures: list[str] = []
        for line_no, attrs in hidden_file_inputs:
            if _attr(attrs, "aria-hidden") != "true":
                failures.append(
                    f"  L{line_no}: 缺 aria-hidden='true' (隐藏 input 应"
                    f"对屏幕阅读器透明)"
                )
            if _attr(attrs, "tabindex") != "-1":
                failures.append(
                    f"  L{line_no}: 缺 tabindex='-1' (隐藏 input 不应被 "
                    f"Tab 键聚焦, 否则键盘用户会卡在不可见控件上)"
                )

        self.assertEqual(
            failures,
            [],
            msg=(
                "R235 invariant: 所有 hidden file input 必须用统一 pattern "
                "(aria-hidden=true + tabindex=-1)。新增此类 input 时复制 "
                "现有写法即可:\n" + "\n".join(failures)
            ),
        )


class TestInputCoverageSanity(unittest.TestCase):
    """sanity 用: 总数大致稳定, 别让 input 被无声删除/复制。"""

    def test_total_input_count_is_in_expected_range(self) -> None:
        html = _read_html()
        inputs = list(ATTR_PATTERN.finditer(html))
        textareas = list(TEXTAREA_PATTERN.finditer(html))
        total = len(inputs) + len(textareas)
        self.assertGreaterEqual(
            total,
            18,
            msg=(
                f"R235 sanity: form input 总数 (input + textarea) 异常低 "
                f"({total} < 18), 可能存在大批删除。基线为 ~21 (R235 实施时为 "
                f"17 input + 4 textarea = 21)。如果是合法删除, 请下调下限"
                "并加上理由。"
            ),
        )
        self.assertLessEqual(
            total,
            40,
            msg=(
                f"R235 sanity: form input 总数异常高 ({total} > 40), 可能存在"
                "复制粘贴扩散, 请审查是否引入 a11y 债务。如果是合法增长, 请上调"
                "上限并加上理由。"
            ),
        )


if __name__ == "__main__":
    unittest.main()
