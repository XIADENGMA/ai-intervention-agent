"""R206 / Cycle 9 · F-release-1 · Pre-tag-push checklist docs sync 测试。

R206 在 ``docs/release-recovery.{md,zh-CN.md}`` 加 "Pre-tag-push
checklist" section，把 v1.7.2 docs-sync miss 的经验固化成 13 步本
地预飞行清单 + retag 安全窗口 + tag-was-moved 历史表。本 test 守护
两份文档的关键 section 同步存在，防止未来 docs polish 漏掉一边。

设计原则（沿用 R185 ``TestReleaseRecoveryBilingualSync`` 思路）
================================================================

* 仅做静态字符串匹配，不深入语义校验—— 文档总会小调整，过严的
  字符串匹配会自伤；
* 测试断言 "关键 keyword 出现过"，不卡死具体 wording；
* 中英文必须同步——避免漂移（与项目 R178 / R185 双语 lockstep 契
  约风格一致）；
* Tag-was-moved 历史表（v1.6.3 + v1.7.2 两行）必须两份对齐——这是
  最容易漂移的 quantitative 数据。

测试覆盖（5 cases）：

1. 两份都含 "Pre-tag-push checklist" / "Tag 推送前清单" 段标题；
2. 两份都含 v1.7.2 retag 案例引用；
3. 两份都含 v1.6.3 retag 案例引用（历史完整性）；
4. 两份都含 "F-release-1" 标识（CR#21 follow-up 追溯性）；
5. 两份都含 "30 minutes" / "30 分钟" 的 retag 窗口数字一致性。
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


class TestReleaseRecoveryPreTagChecklistBilingual(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.en = (REPO_ROOT / "docs" / "release-recovery.md").read_text(
            encoding="utf-8"
        )
        cls.zh = (REPO_ROOT / "docs" / "release-recovery.zh-CN.md").read_text(
            encoding="utf-8"
        )

    def test_both_have_pre_tag_push_checklist_section(self) -> None:
        self.assertIn(
            "Pre-tag-push checklist",
            self.en,
            "docs/release-recovery.md 必须含 R206 'Pre-tag-push checklist' 段标题",
        )
        self.assertIn(
            "Tag 推送前清单",
            self.zh,
            "docs/release-recovery.zh-CN.md 必须含 R206 'Tag 推送前清单' 段标题",
        )

    def test_both_reference_v1_7_2_retag_case(self) -> None:
        """v1.7.2 force-retag 是本 section 的主要触发案例，必须两份都提
        到，否则未来 maintainer 看不到「为什么需要这份 checklist」的
        具体动机。"""
        for doc_name, doc in (
            ("release-recovery.md", self.en),
            ("release-recovery.zh-CN.md", self.zh),
        ):
            self.assertIn("v1.7.2", doc, f"{doc_name} 必须引用 v1.7.2 retag 案例")
            self.assertIn("36222a3", doc, f"{doc_name} 必须含 v1.7.2 旧 SHA 36222a3")
            self.assertIn("35f9671", doc, f"{doc_name} 必须含 v1.7.2 新 SHA 35f9671")

    def test_both_reference_v1_6_3_retag_case(self) -> None:
        """v1.6.3 是更早的 retag 案例（R180 + R181 之前），保留它在表
        里强化「retag 不是单次事件」的历史完整性。"""
        for doc_name, doc in (
            ("release-recovery.md", self.en),
            ("release-recovery.zh-CN.md", self.zh),
        ):
            self.assertIn("v1.6.3", doc, f"{doc_name} 必须含 v1.6.3 retag 历史")

    def test_both_mention_f_release_1_label(self) -> None:
        """F-release-1 是 CR#21 §4.4 列的 follow-up ID, 必须两份都标——
        future cycle 想 grep `F-release-` 找所有 release-process polish
        candidates 能 hit。"""
        for doc_name, doc in (
            ("release-recovery.md", self.en),
            ("release-recovery.zh-CN.md", self.zh),
        ):
            self.assertIn(
                "F-release-1", doc, f"{doc_name} 必须含 R206 / F-release-1 标识"
            )

    def test_retag_safety_window_30_minutes_consistent(self) -> None:
        """retag 安全窗口的数值（30 分钟）必须中英文一致——这是
        operational 数据，drift 会直接导致两份文档给的运维建议不同。"""
        self.assertIn(
            "30 minutes",
            self.en,
            "docs/release-recovery.md 必须明确 retag 窗口为 30 minutes",
        )
        self.assertIn(
            "30 分钟",
            self.zh,
            "docs/release-recovery.zh-CN.md 必须明确 retag 窗口为 30 分钟",
        )


if __name__ == "__main__":
    unittest.main()
