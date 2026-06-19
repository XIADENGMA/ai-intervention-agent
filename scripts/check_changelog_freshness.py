#!/usr/bin/env python3
"""cr36 §8 #1 — CHANGELOG.md vs git activity drift check.

【背景】mining-cycle-3 Track A 发现竞品 ``mcp-feedback-enhanced``
的 ``CHANGELOG.en.md`` HEAD 只到 v2.5.6，但 GitHub Releases 已经
v2.6.0，PR 标题甚至提到 v2.6.1 — three-way doc drift。

本 script 是我们自身的 anti-drift gate：
  1. ``CHANGELOG.md`` 必须含 ``## [<latest-git-tag>]`` section
     —— 否则发了 tag 但 CHANGELOG 落后。
  2. 如果 ``HEAD`` 上有 commits 在最新 git tag 之后，``CHANGELOG.md``
     必须含 ``## [Unreleased]`` section 且**不为空**（至少一个
     ``### Added / Changed / Fixed`` 子节有内容）—— 否则积压了
     无文档的工作。

通过 ``pre-commit`` / CI 调用：

    uv run python scripts/check_changelog_freshness.py [--strict]

``--strict`` 模式下任何告警变 exit 1；默认是 exit 0 + 警告，方便
在不阻塞 CI 的前提下渐进引入。
"""

from __future__ import annotations

import argparse
import re
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CHANGELOG_PATH = REPO_ROOT / "CHANGELOG.md"


def _run(cmd: list[str]) -> str:
    return subprocess.run(
        cmd, cwd=str(REPO_ROOT), capture_output=True, text=True, check=True
    ).stdout.strip()


def latest_git_tag() -> str | None:
    try:
        return _run(["git", "tag", "-l", "--sort=-v:refname"]).splitlines()[0]
    except (subprocess.CalledProcessError, IndexError):
        return None


def commits_since_tag(tag: str) -> int:
    try:
        out = _run(["git", "log", f"{tag}..HEAD", "--oneline"])
        return len([line for line in out.splitlines() if line.strip()])
    except subprocess.CalledProcessError:
        return 0


def changelog_text() -> str:
    return CHANGELOG_PATH.read_text(encoding="utf-8")


def find_section(text: str, header: str) -> str | None:
    """提取 ``## [<header>]`` 到下一个 ``## [`` 之间的正文。"""
    pat = rf"^## \[{re.escape(header)}\][^\n]*\n(.*?)(?=^## \[|\Z)"
    m = re.search(pat, text, flags=re.MULTILINE | re.DOTALL)
    if m is None:
        return None
    return m.group(1).strip()


def unreleased_is_empty(body: str) -> bool:
    """Unreleased section 没有任何 ``### Added/Changed/Fixed`` 子节有正文。"""
    if not body:
        return True
    sub_sections = re.findall(
        r"^### (\w[\w\s/]*)\n(.*?)(?=^### |\Z)",
        body,
        flags=re.MULTILINE | re.DOTALL,
    )
    return all(not sub_body.strip() for _, sub_body in sub_sections)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit non-zero on any drift (default: warn-only).",
    )
    args = parser.parse_args()

    issues: list[str] = []
    text = changelog_text()

    tag = latest_git_tag()
    if tag is None:
        # repo 没 tag — 跳过；新 repo 的合理状态
        print("[changelog-freshness] OK — no git tag found; skipping")
        return 0

    version = tag.lstrip("v")

    # check #1: 最新 tag 必须在 CHANGELOG 出现为 ``## [<version>]``
    if find_section(text, version) is None:
        issues.append(
            f"CHANGELOG.md 缺少 ``## [{version}]`` 段 — "
            f"latest git tag={tag} 已发布但 CHANGELOG 没记。"
        )

    # check #2: 如果 HEAD 在 tag 之后还有 commits，[Unreleased] 不能空
    new_commits = commits_since_tag(tag)
    if new_commits > 0:
        unreleased = find_section(text, "Unreleased")
        if unreleased is None:
            issues.append(
                f"HEAD 已有 {new_commits} 个 commit 在 {tag} 之后，"
                "但 CHANGELOG.md 没有 ``## [Unreleased]`` 段。"
            )
        elif unreleased_is_empty(unreleased):
            issues.append(
                f"HEAD 已有 {new_commits} 个 commit 在 {tag} 之后，"
                "但 CHANGELOG.md ``## [Unreleased]`` 段为空 "
                "（无 Added/Changed/Fixed 内容）。"
            )

    if not issues:
        print(
            f"[changelog-freshness] OK — latest tag {tag} 在 CHANGELOG，"
            f"Unreleased 段 ({new_commits} commits) 已记录"
        )
        return 0

    print("[changelog-freshness] DRIFT DETECTED:")
    for i, issue in enumerate(issues, 1):
        print(f"  {i}. {issue}")

    if args.strict:
        return 1
    print("  → (warn-only mode; pass --strict to fail CI)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
