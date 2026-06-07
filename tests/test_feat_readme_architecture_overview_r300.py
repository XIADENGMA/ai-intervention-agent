"""R300: README 双语 Architecture overview 章节 + Mermaid component diagram 测试。

cycle-29 #E (cr58 §5)：cr58 推荐"README troubleshooting + architecture
overview Mermaid component diagram"。troubleshooting docs 已经存在
(docs/troubleshooting.md 535 行 + zh-CN 479 行)，本 R 聚焦 component-level
architecture diagram (区别于 R288 加的 workflow sequence diagram)。

R300 在 README + README.zh-CN 的 "Key features" / "主要特性" 之后 +
"Agent / Glass mode workflow" 之前 加 "## Architecture overview" /
"## 架构总览" 章节，包含:
- Mermaid `graph LR` (component diagram, 3 subgraph: Clients/Backend/External)
- 4 个 Client 节点 (LLM Agent / Web browser / VS Code extension / CLI)
- 5 个 Backend 节点 (MCP server / Flask / Task queue / Notification / Config)
- 3 个 External 节点 (FS / Browser-OS / Bark API)
- 关键 invariants 描述 (link to R296/R297 tests)

R300 invariant 锁定:

================================================================
| 维度                                                | tests |
|---------------------------------------------------|-------|
| 1. 双语 H2 标题存在 (en: Architecture overview / zh: 架构总览) | 2 |
| 2. 章节位置在 Key features 之后 + Agent/Glass 之前 | 2     |
| 3. Mermaid graph LR (component diagram) 存在        | 2     |
| 4. 3 个 subgraph (Clients / Backend / External)     | 2     |
| 5. 4 个 Client 节点全部命名 (双语 parity)            | 2     |
| 6. 5 个 Backend 节点全部命名 (双语 parity)           | 2     |
| 7. 3 个 External 节点全部命名 (双语 parity)          | 2     |
| 8. 关键 invariants 引用 R296/R297 测试文件名         | 2     |
================================================================
| 合计                                                | 16    |
================================================================

**pattern lineage**: R288 加 sequence diagram (workflow 视角),
R300 加 component diagram (architecture 视角) — 形成 "整体架构 → 具体
workflow" 的递进 narrative, 双语 parity 锁定避免 docs drift。
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
README_EN = PROJECT_ROOT / "README.md"
README_ZH = PROJECT_ROOT / "README.zh-CN.md"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


# ============================================================
# #1: 双语 H2 标题存在
# ============================================================
class TestH2HeadingsPresent(unittest.TestCase):
    def test_en_has_architecture_overview_h2(self) -> None:
        content = _read(README_EN)
        m = re.search(r"^##\s+Architecture overview\s*$", content, re.MULTILINE)
        self.assertIsNotNone(
            m,
            "README.md 必须有 H2 '## Architecture overview'",
        )

    def test_zh_has_architecture_overview_h2(self) -> None:
        content = _read(README_ZH)
        m = re.search(r"^##\s+架构总览\s*$", content, re.MULTILINE)
        self.assertIsNotNone(
            m,
            "README.zh-CN.md 必须有 H2 '## 架构总览'",
        )


# ============================================================
# #2: 章节位置 (Key features 之后 + Agent / Glass 之前)
# ============================================================
class TestSectionPosition(unittest.TestCase):
    def test_en_position_between_key_features_and_agent_glass(self) -> None:
        content = _read(README_EN)
        m_key = re.search(r"^##\s+Key features\s*$", content, re.MULTILINE)
        m_arch = re.search(r"^##\s+Architecture overview\s*$", content, re.MULTILINE)
        m_agent = re.search(
            r"^##\s+Agent / Glass mode workflow\s*$", content, re.MULTILINE
        )
        self.assertIsNotNone(m_key, "README.md 必须有 Key features 章节作位置锚点")
        self.assertIsNotNone(m_arch, "README.md 必须有 Architecture overview 章节")
        self.assertIsNotNone(
            m_agent, "README.md 必须有 Agent / Glass mode workflow 章节作位置锚点"
        )
        assert m_key and m_arch and m_agent
        self.assertLess(
            m_key.start(),
            m_arch.start(),
            "README.md Architecture overview 必须在 Key features 之后",
        )
        self.assertLess(
            m_arch.start(),
            m_agent.start(),
            "README.md Architecture overview 必须在 Agent / Glass mode workflow 之前",
        )

    def test_zh_position_between_key_features_and_agent_glass(self) -> None:
        content = _read(README_ZH)
        m_key = re.search(r"^##\s+主要特性\s*$", content, re.MULTILINE)
        m_arch = re.search(r"^##\s+架构总览\s*$", content, re.MULTILINE)
        m_agent = re.search(
            r"^##\s+Agent / Glass 模式工作流\s*$", content, re.MULTILINE
        )
        self.assertIsNotNone(m_key, "README.zh-CN.md 必须有 主要特性 章节作位置锚点")
        self.assertIsNotNone(m_arch, "README.zh-CN.md 必须有 架构总览 章节")
        self.assertIsNotNone(
            m_agent, "README.zh-CN.md 必须有 Agent / Glass 模式工作流 章节作位置锚点"
        )
        assert m_key and m_arch and m_agent
        self.assertLess(
            m_key.start(),
            m_arch.start(),
            "README.zh-CN.md 架构总览必须在 主要特性 之后",
        )
        self.assertLess(
            m_arch.start(),
            m_agent.start(),
            "README.zh-CN.md 架构总览必须在 Agent / Glass 模式工作流 之前",
        )


# ============================================================
# #3: Mermaid graph LR 存在
# ============================================================
class TestMermaidGraphPresent(unittest.TestCase):
    def test_en_has_mermaid_graph_lr(self) -> None:
        content = _read(README_EN)
        m_arch_start = re.search(
            r"^##\s+Architecture overview\s*$", content, re.MULTILINE
        )
        m_agent = re.search(
            r"^##\s+Agent / Glass mode workflow\s*$", content, re.MULTILINE
        )
        assert m_arch_start and m_agent
        section = content[m_arch_start.end() : m_agent.start()]
        self.assertRegex(
            section,
            r"```mermaid[\s\S]+?graph LR",
            "README.md Architecture overview 必须包含 mermaid graph LR (component diagram)",
        )

    def test_zh_has_mermaid_graph_lr(self) -> None:
        content = _read(README_ZH)
        m_arch_start = re.search(r"^##\s+架构总览\s*$", content, re.MULTILINE)
        m_agent = re.search(
            r"^##\s+Agent / Glass 模式工作流\s*$", content, re.MULTILINE
        )
        assert m_arch_start and m_agent
        section = content[m_arch_start.end() : m_agent.start()]
        self.assertRegex(
            section,
            r"```mermaid[\s\S]+?graph LR",
            "README.zh-CN.md 架构总览必须包含 mermaid graph LR (component diagram)",
        )


# ============================================================
# #4: 3 个 subgraph (Clients / Backend / External)
# ============================================================
class TestThreeSubgraphsPresent(unittest.TestCase):
    def test_en_subgraphs(self) -> None:
        content = _read(README_EN)
        for keyword in (
            'Clients["Clients',
            'Backend["AIIA backend',
            'External["External',
        ):
            self.assertIn(
                keyword,
                content,
                f"README.md Architecture overview 必须有 subgraph {keyword!r}",
            )

    def test_zh_subgraphs(self) -> None:
        content = _read(README_ZH)
        for keyword in ('Clients["客户端', 'Backend["AIIA 后端', 'External["外部'):
            self.assertIn(
                keyword,
                content,
                f"README.zh-CN.md 架构总览必须有 subgraph {keyword!r}",
            )


# ============================================================
# #5-7: 节点命名 parity
# ============================================================
class TestNodeNamingParity(unittest.TestCase):
    CLIENT_LABELS_COMMON = ["LLM Agent", "VS Code", "CLI"]
    BACKEND_LABELS_COMMON = [
        "MCP server",
        "Flask web server",
        "Task queue",
        "Notification manager",
        "Config manager",
    ]
    EXTERNAL_LABELS_COMMON = ["Bark API"]

    def test_en_client_nodes(self) -> None:
        content = _read(README_EN)
        for label in [*self.CLIENT_LABELS_COMMON, "Web browser"]:
            self.assertIn(
                label,
                content,
                f"README.md Architecture overview 必须列出 Client 节点 {label!r}",
            )

    def test_zh_client_nodes(self) -> None:
        content = _read(README_ZH)
        for label in [*self.CLIENT_LABELS_COMMON, "Web 浏览器"]:
            self.assertIn(
                label,
                content,
                f"README.zh-CN.md 架构总览必须列出 Client 节点 {label!r}",
            )

    def test_en_backend_nodes(self) -> None:
        content = _read(README_EN)
        for label in self.BACKEND_LABELS_COMMON:
            self.assertIn(
                label,
                content,
                f"README.md Architecture overview 必须列出 Backend 节点 {label!r}",
            )

    def test_zh_backend_nodes(self) -> None:
        content = _read(README_ZH)
        for label in self.BACKEND_LABELS_COMMON:
            self.assertIn(
                label,
                content,
                f"README.zh-CN.md 架构总览必须列出 Backend 节点 {label!r}",
            )

    def test_en_external_nodes(self) -> None:
        content = _read(README_EN)
        for label in [*self.EXTERNAL_LABELS_COMMON, "File system", "Browser / OS"]:
            self.assertIn(
                label,
                content,
                f"README.md Architecture overview 必须列出 External 节点 {label!r}",
            )

    def test_zh_external_nodes(self) -> None:
        content = _read(README_ZH)
        for label in [*self.EXTERNAL_LABELS_COMMON, "文件系统", "浏览器 / OS"]:
            self.assertIn(
                label,
                content,
                f"README.zh-CN.md 架构总览必须列出 External 节点 {label!r}",
            )


# ============================================================
# #8: 关键 invariants 引用 R296/R297 测试文件名
# ============================================================
class TestKeyInvariantsReferencesTests(unittest.TestCase):
    def test_en_mentions_r296_and_r297_tests(self) -> None:
        content = _read(README_EN)
        for test_fname in [
            "test_feat_sse_cross_language_schema_r297",
            "test_feat_perf_baseline_const_r296",
        ]:
            self.assertIn(
                test_fname,
                content,
                f"README.md Architecture overview 必须 reference test {test_fname!r} "
                f"以让 reader 知道有 invariant 保护",
            )

    def test_zh_mentions_r296_and_r297_tests(self) -> None:
        content = _read(README_ZH)
        for test_fname in [
            "test_feat_sse_cross_language_schema_r297",
            "test_feat_perf_baseline_const_r296",
        ]:
            self.assertIn(
                test_fname,
                content,
                f"README.zh-CN.md 架构总览必须 reference test {test_fname!r} "
                f"以让 reader 知道有 invariant 保护",
            )


if __name__ == "__main__":
    unittest.main()
