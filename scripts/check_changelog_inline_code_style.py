#!/usr/bin/env python3
r"""R219 / Cycle 11 · F-cycle10-3 · CHANGELOG.md inline-code 风格 lint 护栏。

设计目标
========

R211 (Cycle 10) 一次性把 ``CHANGELOG.md`` 中 363 个 reStructuredText
风格的 ``X`` (双反引号) 全部 normalize 成 Markdown 标准 `X` (单反引
号), 保留 18 个 legitimate 双反引号场景 (X 内含字面单反引号、
``\`\`\`lang`` fenced code block 围栏)。

但 **R211 是一次性 cleanup, 没有 lint 守护**——未来任何 contributor
(或 prettier-like formatter / IDE auto-fix) 把双反引号又加回来, 一切
都从零开始。silent decay 剧本:

1. 某次 PR 在 ``[Unreleased]`` 段加 entry 时手快或 copy-paste 带回了
   ``X`` 风格;
2. ``check-changelog-diff-scope`` (CR#16 F-4) 不管 inline-code 风格,
   只管 diff 范围, 所以放行;
3. ``markdownlint`` / Prettier 也不强制 single-vs-double backtick;
4. 渐进式累积下次 R211 又要清一次, R211 lessons-learned 失效。

R219 加一个**轻量 pre-commit hook**:

- 扫 ``CHANGELOG.md`` 中**所有非 fenced 区** (即不在 ``\`\`\``` 围栏
  内的 prose 区);
- 任何 ``X`` 模式 (X 是 1+ 个非反引号字符) 即报错, 因为 Markdown
  inline-code 单反引号已经够用, 双反引号只在 X 本身含字面单反引号
  时才必要;
- 例外: X 字面含反引号的双反引号是合法的 (Markdown 规范); 本脚本
  通过正则 ``[^`]+`` 确保 X 不含反引号, 不会误报。

用法
----

::

    python scripts/check_changelog_inline_code_style.py        # 检查
    python scripts/check_changelog_inline_code_style.py --fix  # 自动修复 (in-place)

退出码:
- ``0``: 通过 / fix 完成无差异;
- ``1``: 检测到违规 (打印位置+行号 + 建议修复)。

设计契约
========

A. **零误报**: 只标记 ``X`` 中 X 不含反引号的, 即 X 真的可以安全
   normalize 成单反引号。
B. **fence-aware**: 识别 ``\`\`\``` 围栏 (任意 trailing language 标
   签), 围栏内一律跳过 (代码内的双反引号是数据, 不是 inline-code 标
   记)。
C. **零依赖**: 纯 stdlib (re + pathlib + argparse), 不引入 markdown
   parser, 让 pre-commit cold-start 时间最小。
D. **指引性 error message**: 报错时打印行号 + 完整匹配 + 建议替换
   形式, 让贡献者 30 秒内自己改完。
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# 匹配 ``X`` 形式: 起始 / 结束都是恰好 2 个反引号, X 内不含反引号
# 用 lookahead/lookbehind 防止匹配 ``` 围栏 (开头/结尾)
INLINE_DOUBLE_BACKTICK_RE = re.compile(r"(?<!`)``([^`]+)``(?!`)")

# 围栏标记: 以 3+ 反引号开头的行
FENCE_RE = re.compile(r"^\s*```")


def find_violations(text: str) -> list[tuple[int, str, str]]:
    """扫 CHANGELOG 文本, 返回违规列表。

    Returns:
        list of (line_number, matched_text, suggested_replacement)
    """
    violations: list[tuple[int, str, str]] = []
    in_fence = False

    for idx, line in enumerate(text.splitlines(), start=1):
        # toggle fence state
        if FENCE_RE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue

        for match in INLINE_DOUBLE_BACKTICK_RE.finditer(line):
            full = match.group(0)
            inner = match.group(1)
            suggested = f"`{inner}`"
            violations.append((idx, full, suggested))

    return violations


def fix_text(text: str) -> str:
    """fence-aware 替换 ``X`` → `X`。"""
    lines = text.splitlines(keepends=True)
    in_fence = False
    out_lines: list[str] = []
    for line in lines:
        if FENCE_RE.match(line):
            in_fence = not in_fence
            out_lines.append(line)
            continue
        if in_fence:
            out_lines.append(line)
            continue
        out_lines.append(INLINE_DOUBLE_BACKTICK_RE.sub(r"`\1`", line))
    return "".join(out_lines)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Lint CHANGELOG.md for double-backtick inline code style "
            "(R219 / Cycle 11 · F-cycle10-3). Reports any ``X`` outside "
            "fenced code blocks and suggests single-backtick `X` form."
        )
    )
    parser.add_argument(
        "path",
        nargs="?",
        default="CHANGELOG.md",
        help="path to CHANGELOG.md (default: CHANGELOG.md in CWD)",
    )
    parser.add_argument(
        "--fix",
        action="store_true",
        help="auto-fix in place (fence-aware, idempotent)",
    )
    args = parser.parse_args()

    path = Path(args.path)
    if not path.exists():
        print(f"❌ file not found: {path}", file=sys.stderr)
        return 1

    text = path.read_text(encoding="utf-8")

    if args.fix:
        fixed = fix_text(text)
        if fixed == text:
            print("✅ no changes — CHANGELOG inline-code already conforms.")
            return 0
        path.write_text(fixed, encoding="utf-8")
        print(f"✅ fixed in place: {path}")
        return 0

    violations = find_violations(text)
    if not violations:
        print("✅ CHANGELOG inline-code style OK (no ``X`` outside fenced blocks).")
        return 0

    print(
        f"❌ {len(violations)} double-backtick inline-code violation(s) in {path}:",
        file=sys.stderr,
    )
    print(
        "    R219 / Cycle 11 · F-cycle10-3 forbids reStructuredText-style ``X`` "
        "inline code outside fenced blocks. Use single-backtick `X` instead "
        "(R211 normalized 363 instances; R219 is the lint guard).",
        file=sys.stderr,
    )
    print(file=sys.stderr)
    for line_num, full, suggested in violations[:20]:
        print(
            f"  CHANGELOG.md:{line_num}: {full!r} → suggest {suggested!r}",
            file=sys.stderr,
        )
    if len(violations) > 20:
        print(
            f"  ... and {len(violations) - 20} more.",
            file=sys.stderr,
        )
    print(file=sys.stderr)
    print(
        "Auto-fix: run `python scripts/check_changelog_inline_code_style.py --fix`",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
