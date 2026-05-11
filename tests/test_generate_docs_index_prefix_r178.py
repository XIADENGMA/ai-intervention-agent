"""R178 follow-up — ``generate_docs.generate_index`` 必须保留 index.md 前置手工块。

背景
====

R169 把 README 的 5 个技术 section （"How it works" / "Architecture" /
"Production-grade middleware" / "Server self-info resource" / "MCP-spec
compliance"）手工插入到 ``docs/api/index.md`` 与 ``docs/api.zh-CN/index.md``
的 ``## Modules`` / ``## 模块列表`` 标题**之前**。这是 R169 提交时的设计
决策：README 面向使用者（保持简洁），技术细节下沉到 docs 顶部。

R178 之前的 ``generate_docs.py`` 会按 signatures-only 模板**完全重写**
index.md，跑 ``--check`` 会把 R169 手工块判为 drift，从而把
``scripts/ci_gate.py:222`` 的 ``generate_docs.py --check`` gate 红掉。这
是个 latent CI footgun ——本测试集合是 R178 落地这条 invariant 的回归
保险：

1. ``generate_index`` 支持 ``existing_path``，传 ``None`` 时行为与历史
   完全一致（首次生成）；
2. 传一个**包含 modules-heading** 的现有文件时，函数保留 heading 之前
   的所有内容（手工块）；
3. 不传 / 传不存在的路径 / 传不含 heading 的文件时，回退到"全文重写"
   行为（保留原版策略）；
4. 真实仓库的 ``docs/api(.zh-CN)/index.md`` 当前必须包含 R169 手工块且
   ``--check`` 通过——锁住 R178 落地后没有回归。
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts import generate_docs as gd

DOCS_API_EN_INDEX = REPO_ROOT / "docs" / "api" / "index.md"
DOCS_API_ZH_INDEX = REPO_ROOT / "docs" / "api.zh-CN" / "index.md"


def _minimal_modules() -> list[str]:
    """复用真实仓库的模块清单，避免 quick-nav invariant 因为缺模块而 SystemExit。"""
    return list(gd.MODULES_TO_DOCUMENT)


class TestGenerateIndexPrefixPreservation(unittest.TestCase):
    """``existing_path`` 行为契约。"""

    def test_no_existing_path_returns_fresh_content(self) -> None:
        """``existing_path=None`` 时函数返回完整新生成内容（首次落盘场景）。"""
        out = gd.generate_index(
            _minimal_modules(),
            lang="en",
            output_dir_display="docs/api/",
            existing_path=None,
        )
        self.assertIn("# AI Intervention Agent API Docs", out)
        self.assertIn("## Modules", out)
        # 首次生成不应带任何 R169 手工 section
        self.assertNotIn("## How it works", out)
        self.assertNotIn("## Architecture", out)

    def test_existing_file_does_not_exist_returns_fresh_content(self) -> None:
        """``existing_path`` 指向不存在的文件时 fallback 到 fresh 行为。"""
        with tempfile.TemporaryDirectory() as tmp:
            non_existent = Path(tmp) / "missing.md"
            out = gd.generate_index(
                _minimal_modules(),
                lang="en",
                output_dir_display="docs/api/",
                existing_path=non_existent,
            )
        self.assertIn("# AI Intervention Agent API Docs", out)
        self.assertNotIn("## How it works", out)

    def test_existing_file_without_modules_heading_returns_fresh_content(self) -> None:
        """如果现有文件不含 modules-heading（极不可能但要 fail-safe），不保留任何内容。"""
        with tempfile.TemporaryDirectory() as tmp:
            existing = Path(tmp) / "index.md"
            existing.write_text(
                "# Old title\n\nSome stale content without any modules heading.\n",
                encoding="utf-8",
            )
            out = gd.generate_index(
                _minimal_modules(),
                lang="en",
                output_dir_display="docs/api/",
                existing_path=existing,
            )
        # Stale content 不应混入
        self.assertNotIn("stale content", out)
        # 仍应返回正常 fresh content
        self.assertIn("## Modules", out)

    def test_existing_file_with_modules_heading_preserves_custom_prefix(self) -> None:
        """关键契约：手工块**必须**被保留到 generated content 之前。"""
        with tempfile.TemporaryDirectory() as tmp:
            existing = Path(tmp) / "index.md"
            existing.write_text(
                "# AI Intervention Agent API Docs\n"
                "\n"
                "English API reference (signatures-focused).\n"
                "\n"
                "- Chinese version: [`docs/api.zh-CN/index.md`](../api.zh-CN/index.md)\n"
                "\n"
                "## How it works\n"
                "\n"
                "Hand-authored prose explaining the high-level flow.\n"
                "\n"
                "## Architecture\n"
                "\n"
                "Hand-authored mermaid diagram placeholder.\n"
                "\n"
                "## Modules\n"
                "\n"
                "- [config_manager](config_manager.md)\n",
                encoding="utf-8",
            )
            out = gd.generate_index(
                _minimal_modules(),
                lang="en",
                output_dir_display="docs/api/",
                existing_path=existing,
            )
        self.assertIn("## How it works", out, "前置手工块应被保留")
        self.assertIn(
            "Hand-authored prose explaining the high-level flow.",
            out,
            "手工 prose 内容应被字节级保留",
        )
        self.assertIn(
            "Hand-authored mermaid diagram placeholder.", out, "手工占位符应保留"
        )
        # generated 段（## Modules 之后）应回到当前 spec
        self.assertIn("## Modules", out)
        self.assertIn("## Quick navigation", out)
        self.assertIn("_Auto-generated under `docs/api/`_", out)

    def test_zh_cn_uses_chinese_modules_heading_for_split(self) -> None:
        """中文版用 ``## 模块列表`` 做 split anchor，不应吃英文 ``## Modules``。"""
        with tempfile.TemporaryDirectory() as tmp:
            existing = Path(tmp) / "index.md"
            existing.write_text(
                "# 标题\n\n## 工作原理\n\n中文手写内容。\n\n## 模块列表\n\n- 旧条目\n",
                encoding="utf-8",
            )
            out = gd.generate_index(
                _minimal_modules(),
                lang="zh-CN",
                output_dir_display="docs/api.zh-CN/",
                existing_path=existing,
            )
        self.assertIn("## 工作原理", out)
        self.assertIn("中文手写内容。", out)
        self.assertIn("## 模块列表", out)
        # generated suffix（## 模块列表 之后）应该来自 generator，不是 "- 旧条目"
        self.assertNotIn("- 旧条目", out)

    def test_real_repo_en_index_has_r169_prefix_block(self) -> None:
        """真实仓库 ``docs/api/index.md`` 必须包含 R169 5 个 section（落地 invariant）。"""
        text = DOCS_API_EN_INDEX.read_text(encoding="utf-8")
        for heading in (
            "## How it works",
            "## Architecture",
            "## Production-grade middleware",
            "## Server self-info resource",
            "## MCP-spec compliance",
        ):
            self.assertIn(heading, text, f"R169 prefix block lost: {heading}")

    def test_real_repo_zh_cn_index_has_r169_prefix_block(self) -> None:
        """真实仓库 ``docs/api.zh-CN/index.md`` 必须包含 R169 5 个 section（中文版）。"""
        text = DOCS_API_ZH_INDEX.read_text(encoding="utf-8")
        for heading in (
            "## 工作原理",
            "## 架构",
            "## 生产级中间件",
            "## Server 自检 resource",
            "## MCP 协议规范",
        ):
            self.assertIn(heading, text, f"R169 prefix block lost (zh-CN): {heading}")


class TestGenerateIndexSignature(unittest.TestCase):
    """``generate_index`` 函数签名锁定。"""

    def test_existing_path_param_exists(self) -> None:
        """``existing_path: Path | None = None`` 必须是 kwarg —— R178 设计契约。"""
        import inspect

        sig = inspect.signature(gd.generate_index)
        self.assertIn("existing_path", sig.parameters)
        param = sig.parameters["existing_path"]
        self.assertEqual(
            param.kind,
            inspect.Parameter.KEYWORD_ONLY,
            "existing_path 必须是 keyword-only 参数（防止位置参数误传）",
        )
        self.assertIs(param.default, None, "existing_path 必须默认 None（向后兼容）")


if __name__ == "__main__":
    unittest.main()
