"""R287 invariant: ``docs/mcp_tools.md`` 与 ``docs/mcp_tools.zh-CN.md`` 必须
完整文档化 4 个 Agent-mode 参数 (`header_label` / `question_type` /
`feedback_placeholder` / `auto_resubmit_timeout`) + 1 个 Agent-mode 综合
调用示例。

背景
----
LLM 调用 MCP 工具时通过 ``tools/list`` JSON-Schema description 拿到
完整参数描述（server_feedback.py 已写齐）。但 ``docs/mcp_tools.{md,
zh-CN.md}`` 只文档化了 ``message`` + ``predefined_options``，
另外 4 个 Agent-mode optional 参数完全没提：

- ``header_label`` (上下文 chip，≤16 chars，借鉴 gemini-cli ask_user)
- ``question_type='yesno'`` (二元按钮 UI，借鉴 gemini-cli)
- ``feedback_placeholder`` (textarea per-task 提示，≤200 chars)
- ``auto_resubmit_timeout`` (per-task 倒计时覆盖)

人类读者读 docs 时找不到 → 维护者 review code 时漏掉 / 开发者吸收同
类竞品功能时不知道哪些已有 → 文档 ↔ 功能漂移。

R287 在两份 docs 都加上：

1. 新 ``#### Agent-mode parameters`` / ``#### Agent 模式专用参数`` 小节
   逐字段文档化 4 个参数（max 长度、推荐值、典型用例）。
2. 新 ``#### Agent-mode example`` / ``#### Agent 模式示例`` 小节
   提供一个完整调用，组合所有 4 个参数（``header_label`` + ``feedback_placeholder``
   + ``question_type='yesno'`` + ``auto_resubmit_timeout``）。

本测试静态扫描两份 docs 锁住：4 个参数名 + 1 个完整示例 + 双语
section anchor 必须存在。
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DOCS_EN = REPO_ROOT / "docs" / "mcp_tools.md"
DOCS_ZH = REPO_ROOT / "docs" / "mcp_tools.zh-CN.md"

# 4 个 Agent-mode 参数（必须在 docs 中文档化）
AGENT_MODE_PARAMS = [
    "header_label",
    "question_type",
    "feedback_placeholder",
    "auto_resubmit_timeout",
]


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


class TestEnDocAgentModeParams(unittest.TestCase):
    """``docs/mcp_tools.md`` 必须有 Agent-mode section + 4 个参数 + 示例。"""

    def setUp(self) -> None:
        self.source = _read(DOCS_EN)

    def test_agent_mode_section_heading_present(self) -> None:
        """必须有 ``#### Agent-mode parameters`` heading (h4)。"""
        self.assertRegex(
            self.source,
            r"####\s+Agent-mode parameters",
            "docs/mcp_tools.md must contain a `#### Agent-mode parameters` "
            "h4 section to document the 4 Agent-mode optional parameters "
            "(header_label, question_type, feedback_placeholder, "
            "auto_resubmit_timeout)",
        )

    def test_all_4_agent_mode_params_documented(self) -> None:
        """4 个 Agent-mode 参数必须都出现在 docs 中（不只是 description，
        要求每个参数有自己的 markdown bullet 文档块）。"""
        # 提取 Agent-mode parameters section body
        match = re.search(
            r"####\s+Agent-mode parameters[^#]+?(?=^#### )",
            self.source,
            re.MULTILINE | re.DOTALL,
        )
        self.assertIsNotNone(
            match,
            "Failed to locate Agent-mode parameters section body in docs/mcp_tools.md",
        )
        assert match is not None
        body = match.group(0)
        for param in AGENT_MODE_PARAMS:
            self.assertIn(
                param,
                body,
                f"docs/mcp_tools.md Agent-mode parameters section must document "
                f"`{param}` (one of the 4 Agent-mode optional parameters)",
            )

    def test_agent_mode_example_section_present(self) -> None:
        """必须有 ``#### Agent-mode example`` heading 展示综合调用。"""
        self.assertRegex(
            self.source,
            r"####\s+Agent-mode example",
            "docs/mcp_tools.md must contain a `#### Agent-mode example` h4 "
            "section showing a real-world composition of all 4 Agent-mode "
            "parameters in a single call",
        )

    def test_agent_mode_example_uses_all_4_params(self) -> None:
        """Example section 必须实际组合 4 个参数（避免 docs 写了 section
        但 example 漏调 1-2 个参数的退化）。"""
        match = re.search(
            r"####\s+Agent-mode example.*",
            self.source,
            re.MULTILINE | re.DOTALL,
        )
        self.assertIsNotNone(match)
        assert match is not None
        body = match.group(0)
        for param in AGENT_MODE_PARAMS:
            self.assertIn(
                param,
                body,
                f"docs/mcp_tools.md Agent-mode example section must invoke "
                f"`{param}=...` (showing how the agent combines all 4 Agent-mode "
                f"parameters in one call)",
            )

    def test_borrowed_from_gemini_cli_credit_present(self) -> None:
        """必须保留 gemini-cli 借鉴致谢（mining-3 原始来源）。"""
        self.assertIn(
            "gemini-cli",
            self.source,
            "docs/mcp_tools.md should credit `gemini-cli ask_user` schema "
            "as the borrow source for 3 of the 4 Agent-mode params "
            "(header_label, question_type, feedback_placeholder); preserves "
            "the mining-cycle-3 §2.1 attribution chain",
        )


class TestZhDocAgentModeParams(unittest.TestCase):
    """``docs/mcp_tools.zh-CN.md`` 必须有等价的中文 Agent-mode section。"""

    def setUp(self) -> None:
        self.source = _read(DOCS_ZH)

    def test_agent_mode_section_heading_present(self) -> None:
        """必须有 ``#### Agent 模式专用参数`` heading。"""
        self.assertRegex(
            self.source,
            r"####\s+Agent 模式专用参数",
            "docs/mcp_tools.zh-CN.md must contain a `#### Agent 模式专用参数` "
            "h4 section to document the 4 Agent-mode optional parameters",
        )

    def test_all_4_agent_mode_params_documented(self) -> None:
        """4 个 Agent-mode 参数必须都出现在中文 docs section 中。"""
        match = re.search(
            r"####\s+Agent 模式专用参数[^#]+?(?=^#### )",
            self.source,
            re.MULTILINE | re.DOTALL,
        )
        self.assertIsNotNone(
            match,
            "Failed to locate Agent 模式专用参数 section body in docs/mcp_tools.zh-CN.md",
        )
        assert match is not None
        body = match.group(0)
        for param in AGENT_MODE_PARAMS:
            self.assertIn(
                param,
                body,
                f"docs/mcp_tools.zh-CN.md Agent 模式 section must document `{param}`",
            )

    def test_agent_mode_example_section_present(self) -> None:
        """必须有 ``#### Agent 模式示例`` heading。"""
        self.assertRegex(
            self.source,
            r"####\s+Agent 模式示例",
            "docs/mcp_tools.zh-CN.md must contain a `#### Agent 模式示例` h4 "
            "section showing a real-world composition of all 4 Agent-mode "
            "parameters",
        )

    def test_agent_mode_example_uses_all_4_params(self) -> None:
        """中文 example section 必须实际组合 4 个参数。"""
        match = re.search(
            r"####\s+Agent 模式示例.*",
            self.source,
            re.MULTILINE | re.DOTALL,
        )
        self.assertIsNotNone(match)
        assert match is not None
        body = match.group(0)
        for param in AGENT_MODE_PARAMS:
            self.assertIn(
                param,
                body,
                f"docs/mcp_tools.zh-CN.md Agent 模式示例 section must invoke "
                f"`{param}=...`",
            )


class TestBilingualDocsParity(unittest.TestCase):
    """双语 docs 的 Agent-mode section 必须 1:1 对应（防 i18n 漂移）。"""

    def setUp(self) -> None:
        self.en = _read(DOCS_EN)
        self.zh = _read(DOCS_ZH)

    def test_max_length_constants_consistent(self) -> None:
        """文档中提到的 max-length 上限两端必须一致（16 / 200）。"""
        # header_label max 16
        en_h = re.findall(
            r"header_label[^.]*max\s+(?:\*\*)?(\d+)(?:\*\*)?\s+chars?", self.en
        )
        zh_h = re.findall(r"header_label[^。]*\*\*最长\s+(\d+)\s+字符\*\*", self.zh)
        self.assertGreater(
            len(en_h),
            0,
            "docs/mcp_tools.md must specify header_label max length explicitly "
            "(e.g. 'max **16** chars')",
        )
        self.assertGreater(
            len(zh_h),
            0,
            "docs/mcp_tools.zh-CN.md must specify header_label max length explicitly "
            "(e.g. '**最长 16 字符**')",
        )
        self.assertEqual(
            en_h[0],
            zh_h[0],
            f"header_label max length disagrees between en ({en_h[0]}) "
            f"and zh-CN ({zh_h[0]}) docs",
        )
        self.assertEqual(int(en_h[0]), 16, "header_label max length must be 16")

        # feedback_placeholder max 200
        en_p = re.findall(
            r"feedback_placeholder[^.]*max\s+(?:\*\*)?(\d+)(?:\*\*)?\s+chars?",
            self.en,
        )
        zh_p = re.findall(
            r"feedback_placeholder[^。]*\*\*最长\s+(\d+)\s+字符\*\*", self.zh
        )
        self.assertGreater(len(en_p), 0)
        self.assertGreater(len(zh_p), 0)
        self.assertEqual(en_p[0], zh_p[0])
        self.assertEqual(
            int(en_p[0]), 200, "feedback_placeholder max length must be 200"
        )

    def test_both_docs_show_yesno_value(self) -> None:
        """``question_type='yesno'`` 的字面量必须在两份 docs 都出现。"""
        self.assertIn('"yesno"', self.en, 'docs/mcp_tools.md must mention `"yesno"`')
        self.assertIn(
            '"yesno"', self.zh, 'docs/mcp_tools.zh-CN.md must mention `"yesno"`'
        )


class TestSourceTruthConsistency(unittest.TestCase):
    """Docs 中提到的 4 个参数必须真的是 ``server_feedback.interactive_feedback``
    的实参（防 docs 列出已被砍掉的参数）。"""

    def test_all_documented_params_exist_in_source(self) -> None:
        from ai_intervention_agent import server_feedback

        signature = (
            server_feedback.interactive_feedback.__wrapped__.__code__.co_varnames
            if hasattr(server_feedback.interactive_feedback, "__wrapped__")
            else server_feedback.interactive_feedback.__code__.co_varnames
        )
        # __code__.co_varnames 含 local 变量，所以转 set 后包含 args
        for param in AGENT_MODE_PARAMS:
            self.assertIn(
                param,
                signature,
                f"docs claim `{param}` is an interactive_feedback parameter "
                f"but it's missing from the actual function signature "
                f"({signature[:20]}...). Either the parameter was renamed "
                f"or the docs are stale.",
            )


if __name__ == "__main__":
    unittest.main()
