"""R311 invariant: README.md + README.zh-CN.md 必须新增 "Failure & recovery
flows" / "异常路径 & 恢复流程" H3 section，含 sequence diagram 展示 3 个
关键边界场景 (auto-resubmit / SSE 重连 / ❄️ freeze)。

背景
----
R288 (cr57) 加了 README "Agent / Glass mode workflow" H2 + 1 个 happy-path
sequence diagram (单任务正常流转)。R300 (cr59) 加了 architecture overview
component diagram。但是 happy path 只覆盖了 "用户立刻看到 → 立刻点 →
立刻提交" 的理想情况, 不反映 Agent 模式下真正的高频场景:

1. **Auto-resubmit** — 用户离开座位 / 走神, 倒计时归零自动重交
2. **SSE drop → reconnect** — 笔记本休眠 / 网络抖动, 降级 polling + 重连
3. **❄️ Freeze** — 跨页面刷新的长时间深度审阅

R311 在双语 README 的 "Agent / Glass mode workflow" H2 下, 紧接 "How a
single interaction flows" / "单次交互流转" H3 之后, 新增第 2 个 H3:

- 英文: ``### Failure & recovery flows``
- 中文: ``### 异常路径 & 恢复流程``

每个 H3 内含 1 个 mermaid ``sequenceDiagram`` 用 ``autonumber`` 排序,
分 3 段 ``Note over`` 展示上述 3 个边界场景。

本测试锁住:
- 双语 H3 section heading 必须存在
- 双语 README 总共必须含 **2 个** ``sequenceDiagram`` block (R288 happy +
  R311 failure)
- R311 新 sequence 必须含 4 个 participant (Agent, AIIA, UI, Human; **不**
  含 MCP 是有意为之 — failure flows 聚焦 backend↔UI↔Human 三层)
- R311 新 sequence 必须出现 3 个边界场景关键词
- 双语 parity: 双语都加, 段落数 / mermaid block 数一致
- R311 marker 在测试 docstring 中, 保留 lineage

pattern lineage
---------------
v3.6 visual-architecture: R300 (component diagram, 静态架构) →
R303 (双语 troubleshooting parity, 文本扩展) → **R311 (sequence diagram
2nd type, 异常路径)** — visual-architecture pattern 3rd app, 至此 v3.6
全 4 pattern 都达到 3+ 应用, **v3.6 完全工业化**。
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
README_EN = REPO_ROOT / "README.md"
README_ZH = REPO_ROOT / "README.zh-CN.md"

# R311 新 sequence 必须含的 4 个 participant (无 MCP, 因为 failure 聚焦后端↔UI↔人)
R311_FAILURE_PARTICIPANTS = ["Agent", "AIIA", "UI", "Human"]

# 3 个边界场景关键词 — 英文版用文本关键词
R311_BOUNDARY_KEYWORDS_EN = [
    "auto-resubmit",
    "SSE",
    # R700：手动 freeze 按钮下线，第三个边界场景改为 typing-hold
    # （输入中自动延长、归零不打断）
    "typing-hold",
]

# 3 个边界场景关键词 — 中文版用语言对应词 + 协议缩写
R311_BOUNDARY_KEYWORDS_ZH = [
    "auto-resubmit",  # 跨语言 endpoint 名称, 中英文 mermaid 都保留
    "SSE",  # 同上, 协议缩写
    "typing-hold",  # R700：freeze 按钮下线后的第三边界场景（中英同词）
]


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


class TestEnReadmeFailureRecoverySection(unittest.TestCase):
    """README.md 必须有 ``### Failure & recovery flows`` H3 section。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.src = _read(README_EN)

    def test_failure_recovery_h3_exists(self) -> None:
        """R311: README.md 必须有 ``### Failure & recovery flows`` H3。"""
        self.assertIn(
            "### Failure & recovery flows",
            self.src,
            "R311: README.md 需要 H3 ``### Failure & recovery flows``",
        )

    def test_failure_recovery_under_agent_glass_h2(self) -> None:
        """R311: failure 章节必须在 ``## Agent / Glass mode workflow`` H2 下面。"""
        agent_h2_idx = self.src.find("## Agent / Glass mode workflow")
        failure_h3_idx = self.src.find("### Failure & recovery flows")
        self.assertGreater(
            agent_h2_idx, -1, "R288 H2 ``## Agent / Glass mode workflow`` 应存在"
        )
        self.assertGreater(
            failure_h3_idx,
            agent_h2_idx,
            "R311: failure H3 必须在 Agent / Glass H2 之后 (同 H2 之内)",
        )

    def test_two_sequence_diagrams_total(self) -> None:
        """R311: README.md 总共必须含 2 个 ``sequenceDiagram`` (R288 + R311)。"""
        count = len(re.findall(r"sequenceDiagram", self.src))
        self.assertEqual(
            count,
            2,
            f"R311: README.md 应有 2 个 sequenceDiagram (R288 happy + R311 failure), 实际 {count}",
        )

    def test_r311_sequence_has_4_participants(self) -> None:
        """R311: 新 sequence 必须含 4 个 participant (Agent/AIIA/UI/Human)。"""
        # 提取 R311 sequence block (在 "Failure & recovery" 之后第一个 mermaid block)
        failure_h3_idx = self.src.find("### Failure & recovery flows")
        block_match = re.search(
            r"```mermaid\s*\nsequenceDiagram[\s\S]*?\n```",
            self.src[failure_h3_idx:],
        )
        self.assertIsNotNone(block_match, "R311: 未找到 failure mermaid block")
        assert block_match is not None
        block = block_match.group(0)
        for p in R311_FAILURE_PARTICIPANTS:
            with self.subTest(participant=p):
                self.assertIn(
                    f"participant {p}",
                    block,
                    f"R311: failure sequence 必须含 participant {p}",
                )

    def test_r311_sequence_no_mcp_participant(self) -> None:
        """R311: 新 sequence **不含** MCP (failure 聚焦 backend↔UI↔Human)。"""
        failure_h3_idx = self.src.find("### Failure & recovery flows")
        block_match = re.search(
            r"```mermaid\s*\nsequenceDiagram[\s\S]*?\n```",
            self.src[failure_h3_idx:],
        )
        self.assertIsNotNone(block_match)
        assert block_match is not None
        block = block_match.group(0)
        self.assertNotIn(
            "participant MCP",
            block,
            "R311: failure sequence 不应含 MCP participant (聚焦 backend↔UI↔Human)",
        )

    def test_r311_sequence_has_3_boundary_keywords(self) -> None:
        """R311: 新 sequence 必须出现 3 个边界场景关键词。"""
        failure_h3_idx = self.src.find("### Failure & recovery flows")
        block_match = re.search(
            r"```mermaid\s*\nsequenceDiagram[\s\S]*?\n```",
            self.src[failure_h3_idx:],
        )
        self.assertIsNotNone(block_match)
        assert block_match is not None
        block = block_match.group(0).lower()
        for kw in R311_BOUNDARY_KEYWORDS_EN:
            with self.subTest(keyword=kw):
                self.assertIn(
                    kw.lower(),
                    block,
                    f"R311: failure sequence 必须含关键词 ``{kw}``",
                )

    def test_r311_sequence_has_autonumber(self) -> None:
        """R311: 新 sequence 必须用 ``autonumber`` 排序 (区别于 R288 happy)。"""
        failure_h3_idx = self.src.find("### Failure & recovery flows")
        block_match = re.search(
            r"```mermaid\s*\nsequenceDiagram[\s\S]*?\n```",
            self.src[failure_h3_idx:],
        )
        self.assertIsNotNone(block_match)
        assert block_match is not None
        block = block_match.group(0)
        self.assertIn(
            "autonumber",
            block,
            "R311: failure sequence 应用 ``autonumber`` (R288 happy 没用, 区别明确)",
        )

    def test_r311_sequence_has_3_note_over_sections(self) -> None:
        """R311: 新 sequence 必须含 3 个 ``Note over`` (① ② ③ 三段)。"""
        failure_h3_idx = self.src.find("### Failure & recovery flows")
        block_match = re.search(
            r"```mermaid\s*\nsequenceDiagram[\s\S]*?\n```",
            self.src[failure_h3_idx:],
        )
        self.assertIsNotNone(block_match)
        assert block_match is not None
        block = block_match.group(0)
        count = len(re.findall(r"Note over.*[①②③]", block))
        self.assertEqual(
            count,
            3,
            f"R311: failure sequence 应有 3 个 Note over (①②③), 实际 {count}",
        )


class TestZhReadmeFailureRecoverySection(unittest.TestCase):
    """README.zh-CN.md 必须有 ``### 异常路径 & 恢复流程`` H3 section。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.src = _read(README_ZH)

    def test_failure_recovery_h3_exists_zh(self) -> None:
        """R311: README.zh-CN.md 必须有 ``### 异常路径 & 恢复流程`` H3。"""
        self.assertIn(
            "### 异常路径 & 恢复流程",
            self.src,
            "R311: README.zh-CN.md 需要 H3 ``### 异常路径 & 恢复流程``",
        )

    def test_failure_recovery_under_agent_glass_h2_zh(self) -> None:
        """R311: failure 章节必须在 ``## Agent / Glass 模式工作流`` H2 下面。"""
        agent_h2_idx = self.src.find("## Agent / Glass 模式工作流")
        failure_h3_idx = self.src.find("### 异常路径 & 恢复流程")
        self.assertGreater(
            agent_h2_idx, -1, "R288 H2 ``## Agent / Glass 模式工作流`` 应存在"
        )
        self.assertGreater(
            failure_h3_idx,
            agent_h2_idx,
            "R311: failure H3 必须在 Agent / Glass H2 之后",
        )

    def test_two_sequence_diagrams_total_zh(self) -> None:
        """R311: README.zh-CN.md 总共必须含 2 个 ``sequenceDiagram``。"""
        count = len(re.findall(r"sequenceDiagram", self.src))
        self.assertEqual(
            count,
            2,
            f"R311: README.zh-CN.md 应有 2 个 sequenceDiagram, 实际 {count}",
        )

    def test_r311_sequence_has_4_participants_zh(self) -> None:
        """R311 (zh): 新 sequence 必须含 4 个 participant。"""
        failure_h3_idx = self.src.find("### 异常路径 & 恢复流程")
        block_match = re.search(
            r"```mermaid\s*\nsequenceDiagram[\s\S]*?\n```",
            self.src[failure_h3_idx:],
        )
        self.assertIsNotNone(block_match, "R311(zh): 未找到 failure mermaid block")
        assert block_match is not None
        block = block_match.group(0)
        for p in R311_FAILURE_PARTICIPANTS:
            with self.subTest(participant=p):
                self.assertIn(
                    f"participant {p}",
                    block,
                    f"R311(zh): failure sequence 必须含 participant {p}",
                )

    def test_r311_sequence_has_3_boundary_keywords_zh(self) -> None:
        """R311 (zh): 新 sequence 必须出现 3 个边界场景关键词 (中文用 emoji + 协议缩写)。"""
        failure_h3_idx = self.src.find("### 异常路径 & 恢复流程")
        block_match = re.search(
            r"```mermaid\s*\nsequenceDiagram[\s\S]*?\n```",
            self.src[failure_h3_idx:],
        )
        self.assertIsNotNone(block_match)
        assert block_match is not None
        block_lower = block_match.group(0).lower()
        block_raw = block_match.group(0)
        # 注意: emoji ❄️ 是大小写无关的 (没有 case 概念), 用 raw block
        for kw in R311_BOUNDARY_KEYWORDS_ZH:
            with self.subTest(keyword=kw):
                # emoji / 全角符号在 lower() 后保持原样, 但为了对称我们对 ASCII 用 lower
                target = block_lower if kw.isascii() else block_raw
                needle = kw.lower() if kw.isascii() else kw
                self.assertIn(
                    needle,
                    target,
                    f"R311(zh): failure sequence 必须含关键词 ``{kw}``",
                )

    def test_r311_sequence_has_autonumber_zh(self) -> None:
        """R311 (zh): 新 sequence 必须用 ``autonumber``。"""
        failure_h3_idx = self.src.find("### 异常路径 & 恢复流程")
        block_match = re.search(
            r"```mermaid\s*\nsequenceDiagram[\s\S]*?\n```",
            self.src[failure_h3_idx:],
        )
        self.assertIsNotNone(block_match)
        assert block_match is not None
        block = block_match.group(0)
        self.assertIn(
            "autonumber", block, "R311(zh): failure sequence 应用 ``autonumber``"
        )


class TestBilingualParityR311(unittest.TestCase):
    """R311: 双语 README 必须 parity (mermaid 块数 / Note 段数一致)。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.en = _read(README_EN)
        cls.zh = _read(README_ZH)

    def test_same_number_of_mermaid_blocks(self) -> None:
        """R311: 双语 README mermaid sequenceDiagram 块数必须一致。"""
        en_count = len(re.findall(r"sequenceDiagram", self.en))
        zh_count = len(re.findall(r"sequenceDiagram", self.zh))
        self.assertEqual(
            en_count,
            zh_count,
            f"R311: 双语 sequenceDiagram 块数应一致, EN={en_count} ZH={zh_count}",
        )

    def test_same_number_of_note_circled_sections_in_failure_block(self) -> None:
        """R311: 双语 failure block 内 ①②③ 段数必须一致。"""
        en_failure_idx = self.en.find("### Failure & recovery flows")
        zh_failure_idx = self.zh.find("### 异常路径 & 恢复流程")
        en_block_match = re.search(
            r"```mermaid\s*\nsequenceDiagram[\s\S]*?\n```",
            self.en[en_failure_idx:],
        )
        zh_block_match = re.search(
            r"```mermaid\s*\nsequenceDiagram[\s\S]*?\n```",
            self.zh[zh_failure_idx:],
        )
        self.assertIsNotNone(en_block_match)
        self.assertIsNotNone(zh_block_match)
        assert en_block_match is not None
        assert zh_block_match is not None
        en_circled_count = len(re.findall(r"[①②③]", en_block_match.group(0)))
        zh_circled_count = len(re.findall(r"[①②③]", zh_block_match.group(0)))
        self.assertEqual(
            en_circled_count,
            3,
            f"R311(en): failure block 应有 3 个 ①②③ 段, 实际 {en_circled_count}",
        )
        self.assertEqual(
            zh_circled_count,
            3,
            f"R311(zh): failure block 应有 3 个 ①②③ 段, 实际 {zh_circled_count}",
        )


class TestR311MarkerPresent(unittest.TestCase):
    """R311 lineage marker 在测试 docstring 中。"""

    def test_test_file_contains_lineage_explanation(self) -> None:
        """本测试文件 docstring 必须含 R311 + v3.6 visual-architecture pattern lineage。"""
        test_src = _read(Path(__file__))
        self.assertIn("R311", test_src, "R311 marker 应出现在测试 docstring")
        self.assertIn(
            "v3.6",
            test_src,
            "R311 应说明 v3.6 visual-architecture pattern lineage",
        )
        self.assertIn(
            "3rd",
            test_src,
            "R311 应说明这是 visual-architecture pattern 3rd app",
        )


if __name__ == "__main__":
    unittest.main()
