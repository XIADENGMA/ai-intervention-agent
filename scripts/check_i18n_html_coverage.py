#!/usr/bin/env python3
"""CI 门禁：HTML 模板里不允许残留硬编码中文/日文/韩文文本节点或属性值。

背景
----
``templates/web_ui.html`` 是 Web UI 的唯一模板入口，所有用户可见文本都应通过
``data-i18n`` / ``data-i18n-html`` / ``data-i18n-title`` / ``data-i18n-placeholder``
/ ``data-i18n-alt`` / ``data-i18n-aria-label`` / ``data-i18n-value`` 等属性提供
i18n key；元素内的英文默认文本只是「fallback」，运行时会被 ``translateDOM()``
覆盖。因此：

- 若 HTML 元素内文本含有 CJK 字符，说明漏打了 ``data-i18n*`` 属性。
- 若 ``placeholder``/``title``/``aria-label``/``alt``/``value`` 等属性值含 CJK，
  同样说明缺少配对的 ``data-i18n-*`` 变体。

实现
----
- 逐行扫描 ``templates/web_ui.html``。
- 使用 ``html.parser.HTMLParser`` 逐 token 解析，命中：
    * 文本节点含 CJK 字符；
    * 标签属性值含 CJK 字符。
- ``<script>`` / ``<style>`` 的 raw 内容不参与 CJK 检查（它们是脚本/样式，
  不是用户文本）。
- 同样支持 ``<!-- aiia:i18n-allow-cjk -->`` 注释在同一行豁免，但默认不鼓励。

退出码
------
- 0：模板中无硬编码 CJK 用户文本。
- 1：至少有一个违反项；逐行输出位置与上下文。
- 2：配置错误（``TEMPLATE_PATH`` 解析后指向不存在的文件）。R100 之前
  这条路径返回 0（silent skip），与 R88 修复 brand-color guard 时的
  ``DEFAULT_ROOT`` 漂移问题完全同源——R76 重布局把 ``static/`` 挪进
  ``src/ai_intervention_agent/`` 包内时也可能动 ``templates/``，这里
  改成 fail-loud 阻止类似 silent breakage 复发。
"""

from __future__ import annotations

import re
import sys
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE_PATH = ROOT / "src" / "ai_intervention_agent" / "templates" / "web_ui.html"

CJK_RE = re.compile(
    r"["
    r"\u4e00-\u9fff"  # CJK Unified Ideographs
    r"\u3040-\u309f"  # Hiragana
    r"\u30a0-\u30ff"  # Katakana
    r"\uac00-\ud7af"  # Hangul Syllables
    r"]"
)
ALLOW_MARKER = "aiia:i18n-allow-cjk"


class CjkTemplateScanner(HTMLParser):
    """Walk the HTML template, recording CJK occurrences outside raw blocks."""

    _RAW_TAGS = {"script", "style"}

    def __init__(self, source_lines: list[str]) -> None:
        super().__init__(convert_charrefs=True)
        self._source_lines = source_lines
        self._raw_depth = 0
        self.violations: list[tuple[int, str, str]] = []

    def _line_exempt(self, line_number: int) -> bool:
        if 1 <= line_number <= len(self._source_lines):
            return ALLOW_MARKER in self._source_lines[line_number - 1]
        return False

    def _report(self, kind: str, text: str) -> None:
        line_number = self.getpos()[0]
        if self._line_exempt(line_number):
            return
        collapsed = " ".join(text.split())
        if not collapsed:
            return
        snippet = collapsed if len(collapsed) < 80 else collapsed[:77] + "..."
        self.violations.append((line_number, kind, snippet))

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag_lower = tag.lower()
        if tag_lower in self._RAW_TAGS:
            self._raw_depth += 1
        for name, value in attrs:
            if value is None:
                continue
            if CJK_RE.search(value):
                self._report(f"attribute {tag_lower}[{name}]", value)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in self._RAW_TAGS and self._raw_depth > 0:
            self._raw_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._raw_depth > 0:
            return
        if CJK_RE.search(data):
            self._report("text node", data)


def scan_template(path: Path) -> list[tuple[int, str, str]]:
    html = path.read_text(encoding="utf-8")
    source_lines = html.splitlines()
    parser = CjkTemplateScanner(source_lines)
    parser.feed(html)
    parser.close()
    return parser.violations


def main() -> int:
    # R100：TEMPLATE_PATH 不存在 → fail-loud（exit 2），不再 silent skip
    # 返回 0。R76 重布局把 ``static/`` 挪进 ``src/ai_intervention_agent/``
    # 包内时让 R66 的 brand-color guard silently broken（R88 修），同款风
    # 险这里也存在：如果以后有人重命名 / 移动 ``web_ui.html`` 但忘了同
    # 步 ``TEMPLATE_PATH``，旧的 silent-skip 实现会让 CI gate 一直 pass，
    # 模板里悄悄回流的硬编码 CJK 没人察觉到。loud failure 模式下 reviewer
    # 会立刻看到 stderr 的报错，被迫显式决定（重命名常量或恢复路径）。
    if not TEMPLATE_PATH.exists():
        rel = TEMPLATE_PATH.relative_to(ROOT).as_posix()
        print(
            f"ERROR: HTML template not found: {rel}\n"
            f"  Resolved absolute path: {TEMPLATE_PATH}\n"
            f"  This is a configuration drift, not 'OK' — the template either\n"
            f"  moved (update TEMPLATE_PATH in scripts/check_i18n_html_coverage.py)\n"
            f"  or got accidentally deleted. Failing loud (exit 2) instead of\n"
            f"  silently skipping (R100; matches R88's fix on brand-color guard).",
            file=sys.stderr,
        )
        return 2
    violations = scan_template(TEMPLATE_PATH)
    for line, kind, snippet in violations:
        rel = TEMPLATE_PATH.relative_to(ROOT).as_posix()
        print(f"{rel}:{line}: hardcoded CJK in {kind}: {snippet!r}")
    if violations:
        print(
            f"\nFound {len(violations)} hardcoded CJK occurrence(s) in HTML template. "
            f"Replace user-visible text with a data-i18n* attribute and move the "
            f"Chinese copy into static/locales/zh-CN.json.",
            file=sys.stderr,
        )
        return 1
    print(f"OK: no hardcoded CJK in {TEMPLATE_PATH.relative_to(ROOT).as_posix()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
