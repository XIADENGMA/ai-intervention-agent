#!/usr/bin/env python3
"""R286 / cycle-26 t26-3: TODO 状态审计工具 — 扫描 TODO.md (user
gitignored personal scratchpad) 与 CHANGELOG.md，输出 TODO 项 →
addressing commit 映射表。

Why this tool exists
====================

cr54 §5 + cr55 §3.4 持续指出 process gap: TODO.md 是用户的本地
gitignored scratchpad，cycle 完成对应功能时 commit 中往往没有显式标记
"Closes TODO #X"，user 重新打开 TODO.md 时看不到状态变化，以为没修。

本工具不改变任何文件，只读 TODO.md + CHANGELOG.md → stdout 一个表，让
user 一眼看到：

  | TODO item snippet | Status | Addressing commits / cycles |
  |-------------------|--------|------------------------------|
  | BUG1 web 通知重复 | ✓ FIXED| cycle-21 R256/R257 (notification dedupe + i18n) |
  | BUG3 vunknown    | ✓ FIXED| cycle-21+ (PWA manifest version) |
  | 循环任务 持续优化 | ⏳ ONGOING | cycle-25/26 (持续) |

Usage
=====

    python scripts/audit_todo_status.py        # plain stdout table
    python scripts/audit_todo_status.py --md   # GitHub markdown table
    python scripts/audit_todo_status.py --strict  # exit 1 if any TODO is 未修复

Algorithm
=========

1. Parse TODO.md line by line, extract each `- [ ]` / `- [x]` checkbox line
2. For each TODO item, extract distinguishing keywords (BUG\\d+, 功能, etc.)
3. Search CHANGELOG.md for anchors mentioning those keywords
4. Output mapping table with status (FIXED / STALE / NEW)

Pattern from R284 (cross-source const audit)
============================================

R278/R283/R284 lock 5 个 cross-source const 防 silent drift。R286 同
philosophy 但作用于 process-level drift (TODO 状态与 implementation
脱节)。本工具是 "process invariant" 而非 code invariant。

Future enhancements (cycle-27+ candidates)
==========================================

- Tags 模式: TODO 项加 ``[anchor:cycle-X-RY]`` 显式 anchor,
  让本工具不需要 fuzzy matching
- 自动写回: ``--apply`` flag 把找到的 anchor 写入 TODO.md (sed-style)
- CI hook: ``--strict`` 整合到 pre-commit 可选 hook
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TODO_MD = REPO_ROOT / "TODO.md"
CHANGELOG_MD = REPO_ROOT / "CHANGELOG.md"


def parse_todos(todo_src: str) -> list[tuple[str, str, str]]:
    """从 TODO.md 提取所有 ``- [ ]`` / ``- [x]`` 项。

    Returns: list of (status, raw_line, summary) tuples.
        - status: "open" | "done"
        - raw_line: original TODO.md line (for output)
        - summary: 提取出来用于关键词匹配的简短描述
    """
    out: list[tuple[str, str, str]] = []
    for line in todo_src.splitlines():
        m = re.match(r"^\s*-\s*\[([x ])\]\s*(.+)$", line)
        if not m:
            continue
        status = "done" if m.group(1).strip() == "x" else "open"
        text = m.group(2).strip()
        # 提取简短 summary (去掉 trailing ``(已...修复)`` 等元数据)
        summary = re.sub(r"_?\(.*?已.*?\)_?$", "", text).strip()
        summary = re.sub(r"\s+", " ", summary)[:80]
        out.append((status, text, summary))
    return out


def extract_changelog_anchors(changelog_src: str) -> list[tuple[str, str]]:
    """从 CHANGELOG.md 提取所有 ``- \\`\\`xxx\\`\\``` commit anchor。

    Returns: list of (anchor_name, description_snippet) tuples.
    """
    out: list[tuple[str, str]] = []
    # 匹配 ``- **`anchor-name`**`` 风格 或 ``- **`anchor`**`` 后跟描述
    pattern = re.compile(r"^-\s+\*\*`([^`]+)`\*\*(.*?)$", re.MULTILINE)
    for m in pattern.finditer(changelog_src):
        anchor = m.group(1)
        # 取 anchor 后 500 字符作为 description sample
        end = min(m.start() + 800, len(changelog_src))
        desc = changelog_src[m.start() : end]
        out.append((anchor, desc))
    return out


def find_addressing_anchors(
    todo_summary: str, anchors: list[tuple[str, str]]
) -> list[str]:
    """对一个 TODO summary，找出可能 address 它的 CHANGELOG anchors。

    简化的关键词匹配: 提取 TODO 中的关键词 (BUG\\d+ / 功能 / R\\d+ / etc.),
    在 CHANGELOG anchor 描述里搜索。
    """
    # 关键词候选
    keywords = []
    # BUG1, BUG2, etc.
    for m in re.finditer(r"\bBUG\d+\b", todo_summary):
        keywords.append(m.group(0))
    # 功能关键词
    func_keywords = [
        ("下载按钮", "export-tasks"),
        ("发送系统自检通知", "remove-test"),
        ("活动面板", "remove-test"),
        ("重置设置", "reset-feedback-confirm"),
        ("二次确认", "reset-feedback-confirm"),
        ("footer", "footer-link"),
        ("AI Intervention Agent x.x.x", "footer-link"),
        ("插件", "footer-link-plugin"),
        ("vunknown", "version"),
        ("notification", "config-changed-notification"),
        ("通知", "config-changed-notification"),
        ("icon", "pwa-icon"),
        ("Resubmit prompt", "resubmit-prompt-maxlength"),
        ("Feedback suffix", "prompt-max-length"),
        ("字数限制", "prompt-max-length"),
    ]
    for k, anchor_hint in func_keywords:
        if k in todo_summary:
            keywords.append(anchor_hint)

    matches: list[str] = []
    for anchor, desc in anchors:
        for kw in keywords:
            if kw.lower() in (anchor + desc).lower() and anchor not in matches:
                matches.append(anchor)
    return matches


def render_table_plain(rows: list[dict[str, str]]) -> str:
    """Plain text 风格输出 (对齐列宽)。"""
    if not rows:
        return "(no TODO items)"
    cols = ["#", "STATUS", "TODO", "ADDRESSED BY"]
    widths = [3, 8, 60, 50]
    out = ["  ".join(f"{c:<{w}}" for c, w in zip(cols, widths, strict=True))]
    out.append("  ".join("-" * w for w in widths))
    for i, r in enumerate(rows, 1):
        row_vals = (str(i), r["status"], r["todo"][:60], r["addressed_by"][:50])
        out.append(
            "  ".join(f"{val:<{w}}" for val, w in zip(row_vals, widths, strict=True))
        )
    return "\n".join(out)


def render_table_md(rows: list[dict[str, str]]) -> str:
    """GitHub markdown 表格风格输出。"""
    if not rows:
        return "(no TODO items)"
    out = ["| # | Status | TODO snippet | Addressing commits |"]
    out.append("|---|--------|--------------|--------------------|")
    for i, r in enumerate(rows, 1):
        # escape pipes in content
        td = r["todo"].replace("|", r"\|")[:80]
        addr = r["addressed_by"].replace("|", r"\|")
        out.append(f"| {i} | {r['status']} | {td} | {addr} |")
    return "\n".join(out)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="TODO 状态审计：扫 TODO.md + CHANGELOG.md → 映射表",
    )
    parser.add_argument(
        "--md",
        action="store_true",
        help="GitHub markdown 格式输出 (默认 plain text)",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="如果有 TODO 项未找到 addressing commits，exit 1",
    )
    args = parser.parse_args()

    if not TODO_MD.exists():
        print(
            "warn: TODO.md 不存在 (它是 .gitignored 的 user scratchpad)。"
            "本工具需要 user 本地有 TODO.md。",
            file=sys.stderr,
        )
        return 0

    todo_src = TODO_MD.read_text(encoding="utf-8")
    changelog_src = CHANGELOG_MD.read_text(encoding="utf-8")

    todos = parse_todos(todo_src)
    anchors = extract_changelog_anchors(changelog_src)

    rows: list[dict[str, str]] = []
    untracked_count = 0
    for status, _raw, summary in todos:
        status_emoji = "[x] DONE" if status == "done" else "[ ] OPEN"
        addressing = find_addressing_anchors(summary, anchors)
        if addressing:
            addressed_by = ", ".join(addressing[:3])
            if len(addressing) > 3:
                addressed_by += f" (+{len(addressing) - 3} more)"
        else:
            addressed_by = "(none found)" if status == "open" else "(未追踪到 anchor)"
            if status == "open":
                untracked_count += 1
        rows.append(
            {
                "status": status_emoji,
                "todo": summary,
                "addressed_by": addressed_by,
            }
        )

    if args.md:
        print(render_table_md(rows))
    else:
        print(render_table_plain(rows))

    print(
        f"\n# Summary: {len(todos)} TODO items, "
        f"{sum(1 for r in rows if 'DONE' in r['status'])} done, "
        f"{sum(1 for r in rows if 'OPEN' in r['status'])} open, "
        f"{untracked_count} open without addressing commit"
    )

    if args.strict and untracked_count > 0:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
