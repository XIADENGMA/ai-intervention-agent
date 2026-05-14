"""R209 / Cycle 10 · F-release-2 · pre-push hook automation tests。

设计目标
========

R206 (cycle 9) 把 v1.7.2 docs-sync miss 经验固化成 13 步本地预飞行清
单, 但所有 13 步都靠**人**记得跑——一旦忘了步骤 6 (``scripts/
check_tag_push_safety.py``), 4+ 个未推送 ``v*.*.*`` tag 累积时
``git push --follow-tags`` 会静默触发 GitHub webhook 屏蔽 (R19.1),
release.yml 一个 job 都不跑。

R209 把 ``check_tag_push_safety.py`` 装到 pre-commit framework 的
**pre-push** stage, 让 ``git push`` 触发时自动跑——用代码强制 R206
§1 step 6, 不再靠人。本测试守护几个**结构性契约**, 防止未来重构悄
悄解除 hook 接入。

测试覆盖 (8 cases / 3 invariant class)
=======================================

1. **TestPreCommitConfigHasPrePushHook** (3): .pre-commit-config.yaml
   含 check-tag-push-safety hook + stages 含 pre-push + entry 指向
   check_tag_push_safety.py
2. **TestMakefileInstallHooksTarget** (3): Makefile install-hooks
   target 存在于 .PHONY + body 含 --hook-type pre-push + help 列出
3. **TestDocsMentionAutomation** (2): docs/release-recovery.{md,
   zh-CN.md} 提到 R209 / install-hooks (沿用 R185 双语 lockstep
   契约)

设计沿用 R185 ``TestMakefileReleaseCheckCveTarget`` + ``TestRelease
RecoveryBilingualSync`` 静态字符串匹配模式 — 不深入语义校验文档,
留出 wording polish 空间, 只锁结构。
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


class TestPreCommitConfigHasPrePushHook(unittest.TestCase):
    """.pre-commit-config.yaml 必须含 R209 pre-push hook 配置。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.config_text = (REPO_ROOT / ".pre-commit-config.yaml").read_text(
            encoding="utf-8"
        )

    def test_check_tag_push_safety_hook_declared(self) -> None:
        """hook id ``check-tag-push-safety`` 必须存在 (let `pre-commit
        install --hook-type pre-push` 识别)。"""
        self.assertIn(
            "id: check-tag-push-safety",
            self.config_text,
            ".pre-commit-config.yaml 必须含 id: check-tag-push-safety hook",
        )

    def test_stages_contains_pre_push(self) -> None:
        """hook 必须 declared in pre-push stage, 否则只会在 commit 时跑
        而不是 push 时跑。"""
        # 简单字符串匹配 'pre-push' (pre-commit framework v3+ 的 stage 名)
        self.assertIn(
            "pre-push",
            self.config_text,
            ".pre-commit-config.yaml 必须配置 pre-push stage",
        )

    def test_entry_invokes_check_tag_push_safety_script(self) -> None:
        """hook entry 必须指向 scripts/check_tag_push_safety.py, 不是
        其他脚本 (防 future hook 改成无关 entry 解除保护)。"""
        # 在 hook block 附近找 entry, 简化为 全文 + check_tag_push_safety.py 出现
        self.assertIn(
            "check_tag_push_safety.py",
            self.config_text,
            ".pre-commit-config.yaml 必须含 check_tag_push_safety.py entry",
        )


class TestMakefileInstallHooksTarget(unittest.TestCase):
    """Makefile install-hooks target 必须存在且指向正确命令。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.makefile_text = (REPO_ROOT / "Makefile").read_text(encoding="utf-8")

    def test_install_hooks_in_phony(self) -> None:
        """.PHONY 必须列 install-hooks (避免被同名文件遮蔽)。"""
        phony_lines = [
            line
            for line in self.makefile_text.splitlines()
            if line.startswith(".PHONY:")
        ]
        joined = " ".join(phony_lines)
        self.assertIn(
            "install-hooks",
            joined,
            ".PHONY 必须列 install-hooks target",
        )

    def test_target_body_invokes_pre_push_hook_type(self) -> None:
        """target body 必须含 --hook-type pre-push, 否则只装 pre-commit
        (用户体感 install-hooks 已跑但 R209 没生效)。"""
        idx = self.makefile_text.find("install-hooks:")
        self.assertGreater(idx, 0, "找不到 install-hooks target 定义")
        following = self.makefile_text[idx : idx + 400]
        self.assertIn(
            "--hook-type pre-push",
            following,
            "install-hooks target 必须传 --hook-type pre-push",
        )
        self.assertIn(
            "pre-commit install",
            following,
            "install-hooks target 必须调 pre-commit install",
        )

    def test_help_lists_install_hooks(self) -> None:
        """``make help`` 输出必须含 install-hooks——否则用户发现不了。"""
        self.assertIn(
            'echo "  make install-hooks',
            self.makefile_text,
            "Makefile help 必须列 install-hooks 让用户能发现",
        )


class TestDocsMentionAutomation(unittest.TestCase):
    """双语 release-recovery 必须提到 R209 / install-hooks。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.en = (REPO_ROOT / "docs" / "release-recovery.md").read_text(
            encoding="utf-8"
        )
        cls.zh = (REPO_ROOT / "docs" / "release-recovery.zh-CN.md").read_text(
            encoding="utf-8"
        )

    def test_english_mentions_r209_and_install_hooks(self) -> None:
        for needle in ("R209", "install-hooks", "pre-push"):
            self.assertIn(
                needle,
                self.en,
                f"docs/release-recovery.md 必须提到 {needle}",
            )

    def test_chinese_mentions_r209_and_install_hooks(self) -> None:
        for needle in ("R209", "install-hooks", "pre-push"):
            self.assertIn(
                needle,
                self.zh,
                f"docs/release-recovery.zh-CN.md 必须提到 {needle}",
            )


if __name__ == "__main__":
    unittest.main()
