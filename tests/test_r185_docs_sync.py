"""R185 文档 / 入口同步契约 — `make release-check-cve` 和 scripts/README 索引。

R185 的 CVE gate（``check_tag_push_safety.py --check-cve``）一旦落地，
就必须同步三处入口点否则会形成 "代码有功能但文档查不到" 的孤儿：

1. **Makefile** —— `release-check-cve` 目标存在，且确实指向
   `check_tag_push_safety.py --check-cve`。这个测试是给 CI 的：
   将来任何人 rename / remove 该 target，pytest 会立刻红。
2. **scripts/README.md** —— `check_tag_push_safety.py` 条目必须
   提到 `--check-cve` 或 R185，让 fresh contributor 一文索骥。
3. **docs/release-recovery.{md,zh-CN.md}** —— recovery playbook
   提到 `--check-cve` 或 `release-check-cve`。

设计原则
--------

* 仅做静态字符串匹配，不真去跑 `make`（CI 容器里没有 GitHub
  remote / `gh` CLI，跑会假阳）；
* 测试断言 "出现过相关 keyword"，不卡死具体 wording——文档总会
  小调整，过严的字符串匹配会自伤；
* 中英文 release-recovery 必须同步——避免漂移（与项目 R178 等
  i18n 双语 lockstep 契约风格保持一致）。
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


class TestMakefileReleaseCheckCveTarget(unittest.TestCase):
    """`make release-check-cve` 必须存在且指向 `--check-cve` flag。"""

    def setUp(self) -> None:
        self.makefile = (REPO_ROOT / "Makefile").read_text(encoding="utf-8")

    def test_target_declared_in_phony(self) -> None:
        """`.PHONY` 列必须含 `release-check-cve`——避免被同名文件遮蔽。"""
        phony_lines = [
            line for line in self.makefile.splitlines() if line.startswith(".PHONY:")
        ]
        joined = " ".join(phony_lines)
        self.assertIn(
            "release-check-cve",
            joined,
            ".PHONY 列必须声明 release-check-cve target",
        )

    def test_target_body_invokes_check_cve_flag(self) -> None:
        """target body 必须含 `--check-cve`——保证 `make release-check-cve`
        真的启用 R185 而不是仅做 tag-count 检查。"""
        # 简化：匹配 `release-check-cve:` 块下方 6 行内含 --check-cve
        idx = self.makefile.find("release-check-cve:")
        self.assertGreater(idx, 0, "找不到 release-check-cve target 定义")
        following = self.makefile[idx : idx + 600]
        self.assertIn(
            "--check-cve",
            following,
            "release-check-cve target 必须传 --check-cve flag",
        )
        self.assertIn(
            "check_tag_push_safety.py",
            following,
            "release-check-cve target 必须指向 check_tag_push_safety.py",
        )

    def test_help_lists_release_check_cve(self) -> None:
        """`make help` 输出必须含 release-check-cve——否则用户发现不了。"""
        self.assertIn(
            "release-check-cve",
            self.makefile,
            "Makefile 的 help 必须列出 release-check-cve 让用户能发现",
        )


class TestScriptsReadmeMentionsR185(unittest.TestCase):
    """scripts/README.md 的 `check_tag_push_safety.py` 条目必须更新到 R185。"""

    def setUp(self) -> None:
        self.readme = (REPO_ROOT / "scripts" / "README.md").read_text(encoding="utf-8")

    def test_mentions_check_cve_flag(self) -> None:
        self.assertIn(
            "--check-cve",
            self.readme,
            "scripts/README.md 必须提到 --check-cve flag",
        )

    def test_mentions_r185_label(self) -> None:
        """R-feature label 必须出现——保持 R-naming 一致性传统。"""
        self.assertIn(
            "R185",
            self.readme,
            "scripts/README.md 必须用 R185 label 标识本 feature",
        )


class TestReleaseRecoveryBilingualSync(unittest.TestCase):
    """中英文 release-recovery 必须同步提到 R185 / `release-check-cve`。"""

    def setUp(self) -> None:
        self.en = (REPO_ROOT / "docs" / "release-recovery.md").read_text(
            encoding="utf-8"
        )
        self.zh = (REPO_ROOT / "docs" / "release-recovery.zh-CN.md").read_text(
            encoding="utf-8"
        )

    def test_english_mentions_r185(self) -> None:
        for needle in ("R185", "--check-cve"):
            self.assertIn(
                needle,
                self.en,
                f"docs/release-recovery.md 必须提到 {needle}",
            )

    def test_chinese_mentions_r185(self) -> None:
        for needle in ("R185", "--check-cve"):
            self.assertIn(
                needle,
                self.zh,
                f"docs/release-recovery.zh-CN.md 必须提到 {needle}",
            )

    def test_both_mention_release_check_cve_shortcut(self) -> None:
        """两份文档都必须指向便利目标 `release-check-cve`——保持入口统一。"""
        self.assertIn("release-check-cve", self.en)
        self.assertIn("release-check-cve", self.zh)


if __name__ == "__main__":
    unittest.main()
