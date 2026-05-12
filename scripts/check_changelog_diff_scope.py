#!/usr/bin/env python3
"""CR#16 F-4 护栏：检测 CHANGELOG.md 在 ``[Unreleased]`` 区段**外**的大幅 diff。

背景
====

在 CR#16 中，``a37e17d`` commit 把 markdownlint 自动格式化（``* `` → ``- ``、
``*emph*`` → ``_emph_`` 等）一起卷进了 R185 feature commit。结果一个 645 行
的 diff 大部分是 R184/v1.6.4 历史段落的格式化，code review 时很难一眼区分
"哪些是真改动 vs 哪些是格式化"。

CR#16 F-4 提议加一道护栏：**单次 commit 改 CHANGELOG.md 时，``[Unreleased]``
区段以外的修改若超过 N 行，hook 必须 fail-fast，强迫拆 commit**。

工作原理
========

1. 调 ``git diff --cached`` 拿到当前要 commit 的 CHANGELOG.md diff（含
   +/-，但不算上下文行）；
2. 用 ``[Unreleased]`` / ``## [`` 标题切分原文，定位每行属于哪个 release；
3. 计算"非 Unreleased"区段的总变更行数；
4. 超过阈值（默认 100 行）→ 提示并 exit 1。

设计取舍
========

* **只检查 staged diff，不检查 working tree**：这样 ``git stash`` /
  manual cherry-pick 等中间态不被误伤；
* **默认阈值 100 行**：足够覆盖一次正常 release 区段的小修，但能 catch
  整段 lint 改写；
* **可以用 ``--allow-massive-changelog-rewrite`` 紧急绕过**：用于真有理由
  整体重写历史 release 区段的场景，会记进 stderr 让 reviewer 看到；
* **失败提示给具体修复路径**：建议把格式化拆成单独 commit。

依赖
====

只调 ``git`` CLI；不依赖任何 Python 第三方包，方便 pre-commit hook 直接跑。
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

_DEFAULT_THRESHOLD = 100
"""默认阈值：100 行非-Unreleased 改动。

正常 release 历史区段的微调（typo / link 修复）一般 < 50 行；> 100 行
通常意味着批量格式化或大段重写——这两种都应拆成独立 commit 让 reviewer
看清楚。"""

_UNRELEASED_HEADER_RE = re.compile(r"^## \[Unreleased\]\s*$", re.MULTILINE)
"""``## [Unreleased]`` 区段标题正则。"""

_RELEASE_HEADER_RE = re.compile(r"^## \[v?\d+\.\d+\.\d+\]", re.MULTILINE)
"""任意 ``## [vX.Y.Z]`` / ``## [X.Y.Z]`` release 区段标题正则。"""


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _run_git(args: list[str]) -> str:
    """跑 ``git`` 命令，返回 stdout（utf-8，剥 trailing newline）。"""
    result = subprocess.run(
        ["git", *args],
        check=True,
        capture_output=True,
        text=True,
        cwd=_repo_root(),
    )
    return result.stdout


def _is_changelog_staged() -> bool:
    """``git diff --cached --name-only`` 包含 CHANGELOG.md？"""
    try:
        names = _run_git(["diff", "--cached", "--name-only"])
    except subprocess.CalledProcessError:
        return False
    return "CHANGELOG.md" in names.splitlines()


def _staged_changelog_diff_lines() -> list[tuple[int, str, str]]:
    """返回 ``CHANGELOG.md`` 在 ``git diff --cached`` 里的所有 ``+``/``-`` 行。

    每个 tuple 是 ``(old_lineno, new_lineno, kind, payload)``——简化版只关心
    *new file* 视角下"这行属于哪个 release 区段"。所以这里直接走"按 new
    file 的最终内容 + diff 行号"思路：拿 staged 版本的完整文件，扫一遍
    定位 release 区段范围；然后扫 diff 提取 +/- 行号映射回区段。
    """
    try:
        diff = _run_git(["diff", "--cached", "--unified=0", "--", "CHANGELOG.md"])
    except subprocess.CalledProcessError:
        return []

    result: list[tuple[int, str, str]] = []
    new_lineno = 0
    in_hunk_header = False
    for line in diff.splitlines():
        if line.startswith("@@"):
            # @@ -OLD_START,OLD_COUNT +NEW_START,NEW_COUNT @@
            m = re.match(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@", line)
            if m:
                new_lineno = int(m.group(1))
            in_hunk_header = True
            continue
        if line.startswith(("+++", "---")):
            continue
        if line.startswith("+") and not line.startswith("++"):
            result.append((new_lineno, "+", line[1:]))
            new_lineno += 1
        elif line.startswith("-") and not line.startswith("--"):
            result.append((new_lineno, "-", line[1:]))
            # 删除行不推进 new_lineno
        else:
            new_lineno += 1
        in_hunk_header = False  # silence "unused" lint
    _ = in_hunk_header
    return result


def _release_sections_in_staged_file() -> list[tuple[int, int, str]]:
    """读取 staged 版本 CHANGELOG.md，返回 release 区段范围列表。

    每个 tuple = ``(start_lineno, end_lineno, label)``。``label`` 为
    ``"unreleased"`` / ``"v1.6.4"`` 等；``end_lineno`` 是下一个 section
    的前一行（最后一个区段用文件总行数兜底）。
    """
    try:
        text = _run_git(["show", ":CHANGELOG.md"])
    except subprocess.CalledProcessError:
        return []

    lines = text.splitlines()
    sections: list[tuple[int, str]] = []
    for idx, line in enumerate(lines, start=1):
        if _UNRELEASED_HEADER_RE.match(line):
            sections.append((idx, "unreleased"))
        elif _RELEASE_HEADER_RE.match(line):
            m = re.match(r"^## \[(v?\d+\.\d+\.\d+)\]", line)
            label = m.group(1) if m else "unknown"
            sections.append((idx, label))

    ranges: list[tuple[int, int, str]] = []
    total = len(lines)
    for i, (start, label) in enumerate(sections):
        end = sections[i + 1][0] - 1 if i + 1 < len(sections) else total
        ranges.append((start, end, label))
    return ranges


def _classify_line_section(
    lineno: int, ranges: list[tuple[int, int, str]]
) -> str | None:
    """把 diff 中 new-file 视角的行号定位到对应 release 区段标签。"""
    for start, end, label in ranges:
        if start <= lineno <= end:
            return label
    return None


def _count_non_unreleased_lines(
    diff_lines: list[tuple[int, str, str]],
    ranges: list[tuple[int, int, str]],
) -> int:
    """统计落在"非 Unreleased"区段的 ``+``/``-`` 行总数。"""
    count = 0
    for lineno, _kind, _payload in diff_lines:
        section = _classify_line_section(lineno, ranges)
        if section is None:
            continue
        if section != "unreleased":
            count += 1
    return count


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="check_changelog_diff_scope.py",
        description=(
            "CR#16 F-4：CHANGELOG.md 单次 commit 非-Unreleased 区段改动若超过"
            f"{_DEFAULT_THRESHOLD} 行（默认），hook 失败。建议把格式化 / 历史"
            "段落整理拆成独立 commit，避免淹没 feature commit 的有效 diff。"
        ),
    )
    parser.add_argument(
        "--threshold",
        type=int,
        default=_DEFAULT_THRESHOLD,
        help=f"非 Unreleased 区段改动行数阈值（默认 {_DEFAULT_THRESHOLD}）",
    )
    parser.add_argument(
        "--allow-massive-changelog-rewrite",
        action="store_true",
        default=False,
        help=(
            "紧急绕过：真有需要整体重写历史 release 区段时显式启用。"
            "会在 stderr 记一条 WARNING，让 reviewer 看到该 commit 主动绕过了护栏。"
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(argv)
    if args.threshold < 0:
        print("--threshold 不能为负数", file=sys.stderr)
        return 2

    if not _is_changelog_staged():
        # 没改 CHANGELOG.md，直接通过——快速 short-circuit 让 hook 几乎零开销
        return 0

    diff_lines = _staged_changelog_diff_lines()
    if not diff_lines:
        return 0

    ranges = _release_sections_in_staged_file()
    if not ranges:
        # 解析失败（极端情况），保守通过 + 警告，不阻断 commit
        print(
            "WARNING (check_changelog_diff_scope): 无法解析 CHANGELOG.md 区段结构，"
            "本次不做检测。",
            file=sys.stderr,
        )
        return 0

    non_unreleased = _count_non_unreleased_lines(diff_lines, ranges)
    if non_unreleased <= args.threshold:
        return 0

    if args.allow_massive_changelog_rewrite:
        print(
            "WARNING (check_changelog_diff_scope): 非-Unreleased 区段改动 "
            f"{non_unreleased} 行 > 阈值 {args.threshold}，但 "
            "--allow-massive-changelog-rewrite 已显式启用——放行。",
            file=sys.stderr,
        )
        return 0

    print(
        "FAIL (check_changelog_diff_scope): 本次 commit 在 CHANGELOG.md "
        f"的非-Unreleased 区段改动 {non_unreleased} 行，超过阈值 "
        f"{args.threshold}。\n\n"
        "可能原因 + 修复路径：\n"
        "  1. 你顺带把 markdownlint 自动格式化卷进了 feature commit。\n"
        "     → 撤回这些变更，单独提一个 `:art: chore(changelog): "
        "normalize markdownlint formatting in <region>` commit；\n"
        "  2. 你有意整理某个旧 release 段落。\n"
        "     → 也请拆独立 commit，让 reviewer 一眼看出"
        "「这是历史整理 vs 这是 feature」的边界；\n"
        "  3. 真的需要本 commit 同时改大段历史：\n"
        "     → 加 `--allow-massive-changelog-rewrite`（会在 stderr 记 WARNING）。\n",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
