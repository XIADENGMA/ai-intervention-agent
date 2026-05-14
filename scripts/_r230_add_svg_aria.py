#!/usr/bin/env python3
"""R230 one-shot helper: 给 web_ui.html 中所有装饰性 <svg> 加 aria-hidden + focusable。

不是常驻 CI 脚本——一次性修复工具，提交后保留作为 R230 commit 的 audit
trail (对照 commit message / CHANGELOG 可还原出哪些 SVG 被修改)。运行后
人工 git diff 检查每一处变更。

每个 <svg> opening tag 末尾插入两个 attribute：

    aria-hidden="true"
    focusable="false"

实现策略
--------

仅对**多行格式**的 SVG opening tag (即 ``<svg\n  attr1=...\n  ...\n>``)
做插入：在最后一个属性所在行之后、闭合 ``>`` 之前插入两行新属性，缩进
对齐到既有 attribute 缩进。这种是 web_ui.html 全部 31 个 SVG 的现有
格式 (Prettier 默认输出风格)。

如果 opening tag 是单行格式 (``<svg foo="bar">``) 则在 ``>`` 前直接附加
``空格 + 两个 attribute``，但 web_ui.html 当前没有这种情况——若未来出现
也能正确处理。

属性预存检测：如果 opening tag 已有 ``aria-hidden`` 或 ``focusable``，
仅补缺的那个；都有则跳过 (idempotent)。
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
HTML_PATH = REPO_ROOT / "src" / "ai_intervention_agent" / "templates" / "web_ui.html"

SVG_OPENING_RE = re.compile(r"<svg\b([^>]*)>", re.DOTALL)


def _process(opening_attrs: str) -> str:
    has_aria = re.search(r"\baria-hidden\s*=", opening_attrs) is not None
    has_focusable = re.search(r"\bfocusable\s*=", opening_attrs) is not None
    if has_aria and has_focusable:
        return opening_attrs

    is_multiline = "\n" in opening_attrs
    if is_multiline:
        last_attr_line_match = re.search(r"(.*\n)(\s*)$", opening_attrs, re.DOTALL)
        if last_attr_line_match is None:
            return opening_attrs
        before_closing_indent = last_attr_line_match.group(1)
        trailing_indent_before_gt = last_attr_line_match.group(2)
        indent_match = re.search(r"\n(\s+)\S", before_closing_indent)
        attr_indent = indent_match.group(1) if indent_match else "  "
        additions: list[str] = []
        if not has_aria:
            additions.append(f'{attr_indent}aria-hidden="true"\n')
        if not has_focusable:
            additions.append(f'{attr_indent}focusable="false"\n')
        return before_closing_indent + "".join(additions) + trailing_indent_before_gt

    additions_inline: list[str] = []
    if not has_aria:
        additions_inline.append(' aria-hidden="true"')
    if not has_focusable:
        additions_inline.append(' focusable="false"')
    return opening_attrs + "".join(additions_inline)


def _replace_svg(match: re.Match[str]) -> str:
    return f"<svg{_process(match.group(1))}>"


def main() -> int:
    original = HTML_PATH.read_text(encoding="utf-8")
    new_content = SVG_OPENING_RE.sub(_replace_svg, original)
    if new_content == original:
        print("No changes needed.")
        return 0
    HTML_PATH.write_text(new_content, encoding="utf-8")
    delta = len(new_content) - len(original)
    print(f"Modified {HTML_PATH} (+{delta} chars).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
