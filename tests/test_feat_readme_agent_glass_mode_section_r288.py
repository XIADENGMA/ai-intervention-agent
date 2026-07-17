"""R288 invariant: README.md + README.zh-CN.md 必须有 "Agent / Glass mode
workflow" 专项 H2 section，统一展示对 Agent 模式有帮助的全部 features。

背景
----
cr56 §5 #1 推荐 "README 同类产品功能调研 + Agent 模式专项审计"。
当前 README 把 Agent 模式 features（`header_label` / `question_type` /
`feedback_placeholder` / multi-task / countdown freeze）都散落在 "Key
features" 列表里，没有给 Agent 用户一个统一的工作流视图。Glass / Composer
模式新用户读 README 时无法立刻 "看到这是个 Agent 工具"。

R288 在双语 README 添加 ``## Agent / Glass mode workflow`` H2 section，
内含：

1. 一句话定位 (long-running autonomous agent loops, < 5s per task)
2. mermaid sequence diagram (Agent → MCP → AIIA → User → Agent)
3. Agent-side parameters 表格 (5 行 — 4 Agent-mode + predefined_options)
4. User-side workflow features 列表 (7 项 — multi-task tabs, drafts, freeze,
   quick replies, sound, images, SSE badge)
5. Recommended LLM system prompt link

本测试锁住：
- 双语 H2 section heading 必须存在
- mermaid diagram 必须存在 + 包含 5 个 participant
- 5 个 Agent 端参数都必须在表格中
- 7 个 user-side features 都必须 mention
- mermaid 跨语言一致 (复用同一份 diagram block)
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
README_EN = REPO_ROOT / "README.md"
README_ZH = REPO_ROOT / "README.zh-CN.md"

# 5 个 Agent-mode 关键参数（必须在表格中）
AGENT_MODE_PARAMS_FOR_TABLE = [
    "header_label",
    "question_type",
    "feedback_placeholder",
    "auto_resubmit_timeout",
    "predefined_options",
]

# 7 个 user-side feature 关键词
USER_SIDE_FEATURES_EN = [
    "Multi-task tabs",
    "Per-task draft autosave",
    # R700：+60s/freeze 按钮下线，特性改述为 typing-hold 自动延长
    "Typing-hold auto-extension",
    "Quick reply phrases",
    "Custom notification sound",
    "Per-task images",
    "SSE liveness badge",
]

USER_SIDE_FEATURES_ZH = [
    "多任务标签页",
    "每任务草稿自动保存",
    "输入即延长",  # R700：freeze/+60s 下线后的 typing-hold 述法
    "常用回复短语",
    "自定义通知音效",
    "每任务图片",
    "SSE 实时连接徽章",
]

# mermaid sequence diagram 必须包含的 5 个 participant
MERMAID_PARTICIPANTS = ["Agent", "MCP", "AIIA", "UI", "Human"]


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


class TestEnReadmeAgentGlassSection(unittest.TestCase):
    """README.md 必须有 ``## Agent / Glass mode workflow`` section。"""

    def setUp(self) -> None:
        self.source = _read(README_EN)

    def test_h2_heading_present(self) -> None:
        """``## Agent / Glass mode workflow`` heading 必须存在。"""
        match = re.search(
            r"^##\s+Agent / Glass mode workflow",
            self.source,
            re.MULTILINE,
        )
        self.assertIsNotNone(
            match,
            "README.md must contain `## Agent / Glass mode workflow` H2 "
            "section (cr56 §5 #1 — README 同类产品功能调研 + Agent 模式专项)",
        )

    def _extract_section_body(self) -> str:
        """提取 ``## Agent / Glass mode workflow`` section 的内容（到下一个 H2 为止）。"""
        match = re.search(
            r"##\s+Agent / Glass mode workflow.*?(?=^##\s+\S)",
            self.source,
            re.MULTILINE | re.DOTALL,
        )
        self.assertIsNotNone(match, "Failed to extract Agent / Glass section body")
        assert match is not None
        return match.group(0)

    def test_mermaid_sequence_diagram_present(self) -> None:
        """section 必须包含 mermaid sequence diagram。"""
        body = self._extract_section_body()
        self.assertIn(
            "```mermaid",
            body,
            "Agent / Glass section must include a mermaid diagram block",
        )
        self.assertIn(
            "sequenceDiagram",
            body,
            "mermaid block must be a `sequenceDiagram` (not flowchart) — "
            "shows Agent → MCP → AIIA → User → Agent message flow",
        )

    def test_mermaid_has_5_participants(self) -> None:
        body = self._extract_section_body()
        # 提取 mermaid block 内容
        mermaid_match = re.search(
            r"```mermaid\s*\n(?P<m>.*?)```",
            body,
            re.DOTALL,
        )
        self.assertIsNotNone(mermaid_match)
        assert mermaid_match is not None
        mermaid_body = mermaid_match.group("m")
        for p in MERMAID_PARTICIPANTS:
            # mermaid participant syntax: "participant X as ..."
            self.assertRegex(
                mermaid_body,
                rf"participant\s+{re.escape(p)}\b",
                f"mermaid sequenceDiagram must declare `participant {p}` — "
                f"shows the full hop chain that Agent-mode interactions follow",
            )

    def test_all_5_agent_params_in_table(self) -> None:
        body = self._extract_section_body()
        # 表格里 ``question_type`` 以 ``question_type='yesno'`` 形式出现
        # (backtick 包了整个表达式)，所以 substring 匹配即可。
        for param in AGENT_MODE_PARAMS_FOR_TABLE:
            self.assertIn(
                param,
                body,
                f"Agent / Glass section must list `{param}` in the Agent-side "
                f"parameters table (5 params total: 4 Agent-mode + predefined_options)",
            )

    def test_all_7_user_side_features_listed(self) -> None:
        body = self._extract_section_body()
        for feat in USER_SIDE_FEATURES_EN:
            self.assertIn(
                feat,
                body,
                f"Agent / Glass section must mention `{feat}` in the "
                f"user-side workflow features list (7 features total)",
            )

    def test_links_to_mcp_tools_docs(self) -> None:
        body = self._extract_section_body()
        self.assertIn(
            "docs/mcp_tools.md",
            body,
            "Agent / Glass section must link to docs/mcp_tools.md for the "
            "complete Agent-mode parameter reference (R287 lives there)",
        )


class TestZhReadmeAgentGlassSection(unittest.TestCase):
    """README.zh-CN.md 必须有等价的 ``## Agent / Glass 模式工作流`` section。"""

    def setUp(self) -> None:
        self.source = _read(README_ZH)

    def test_h2_heading_present(self) -> None:
        match = re.search(
            r"^##\s+Agent / Glass 模式工作流",
            self.source,
            re.MULTILINE,
        )
        self.assertIsNotNone(
            match,
            "README.zh-CN.md must contain `## Agent / Glass 模式工作流` H2 section",
        )

    def _extract_section_body(self) -> str:
        match = re.search(
            r"##\s+Agent / Glass 模式工作流.*?(?=^##\s+\S)",
            self.source,
            re.MULTILINE | re.DOTALL,
        )
        self.assertIsNotNone(match)
        assert match is not None
        return match.group(0)

    def test_mermaid_sequence_diagram_present(self) -> None:
        body = self._extract_section_body()
        self.assertIn("```mermaid", body)
        self.assertIn("sequenceDiagram", body)

    def test_mermaid_has_5_participants(self) -> None:
        body = self._extract_section_body()
        mermaid_match = re.search(
            r"```mermaid\s*\n(?P<m>.*?)```",
            body,
            re.DOTALL,
        )
        self.assertIsNotNone(mermaid_match)
        assert mermaid_match is not None
        mermaid_body = mermaid_match.group("m")
        for p in MERMAID_PARTICIPANTS:
            self.assertRegex(
                mermaid_body,
                rf"participant\s+{re.escape(p)}\b",
                f"中文 README mermaid must declare `participant {p}`",
            )

    def test_all_5_agent_params_in_table(self) -> None:
        body = self._extract_section_body()
        for param in AGENT_MODE_PARAMS_FOR_TABLE:
            self.assertIn(param, body, f"中文 README must list `{param}`")

    def test_all_7_user_side_features_listed_in_chinese(self) -> None:
        body = self._extract_section_body()
        for feat in USER_SIDE_FEATURES_ZH:
            self.assertIn(
                feat,
                body,
                f"中文 README user-side features must mention `{feat}`",
            )

    def test_links_to_mcp_tools_docs_zh(self) -> None:
        body = self._extract_section_body()
        self.assertIn(
            "docs/mcp_tools.zh-CN.md",
            body,
            "中文 README Agent / Glass section must link to "
            "docs/mcp_tools.zh-CN.md (not English version)",
        )


class TestBilingualParityForAgentGlass(unittest.TestCase):
    """双语 README 的 Agent / Glass section 必须 1:1 等价（防 i18n 漂移）。"""

    def setUp(self) -> None:
        self.en = _read(README_EN)
        self.zh = _read(README_ZH)

    def _extract_mermaid(self, source: str, lang: str) -> str:
        heading = (
            r"##\s+Agent / Glass mode workflow"
            if lang == "en"
            else r"##\s+Agent / Glass 模式工作流"
        )
        section_match = re.search(
            heading + r".*?(?=^##\s+\S)",
            source,
            re.MULTILINE | re.DOTALL,
        )
        self.assertIsNotNone(section_match)
        assert section_match is not None
        mermaid_match = re.search(
            r"```mermaid\s*\n(?P<m>.*?)```",
            section_match.group(0),
            re.DOTALL,
        )
        self.assertIsNotNone(mermaid_match)
        assert mermaid_match is not None
        return mermaid_match.group("m")

    def test_mermaid_participants_match(self) -> None:
        """双语 mermaid 必须包含同样的 participant set（避免 zh 拆了一个 hop）。"""
        en_mermaid = self._extract_mermaid(self.en, "en")
        zh_mermaid = self._extract_mermaid(self.zh, "zh")
        en_participants = set(re.findall(r"participant\s+(\w+)\b", en_mermaid))
        zh_participants = set(re.findall(r"participant\s+(\w+)\b", zh_mermaid))
        self.assertEqual(
            en_participants,
            zh_participants,
            f"双语 mermaid participant 集合不一致: en={en_participants} "
            f"zh={zh_participants}。双语 README 的 sequence diagram 应该完全"
            f"对称，只有 alias 文本翻译不同",
        )

    def test_both_sections_link_to_mcp_tools_docs(self) -> None:
        """双语都必须 link 到对应语言的 docs/mcp_tools.{md,zh-CN.md}。"""
        en_section = re.search(
            r"##\s+Agent / Glass mode workflow.*?(?=^##\s+\S)",
            self.en,
            re.MULTILINE | re.DOTALL,
        )
        zh_section = re.search(
            r"##\s+Agent / Glass 模式工作流.*?(?=^##\s+\S)",
            self.zh,
            re.MULTILINE | re.DOTALL,
        )
        self.assertIsNotNone(en_section)
        self.assertIsNotNone(zh_section)
        assert en_section is not None
        assert zh_section is not None
        self.assertIn("docs/mcp_tools.md", en_section.group(0))
        self.assertIn("docs/mcp_tools.zh-CN.md", zh_section.group(0))


if __name__ == "__main__":
    unittest.main()
