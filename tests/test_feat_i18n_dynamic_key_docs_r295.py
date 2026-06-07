"""R295 invariant: ``docs/i18n.md`` 必须文档化 dynamic key reservation
rule (cycle-28 R291 spillover lock)。

背景
----
cycle-27 R289 引入 ``_classifyFetchError`` dynamic-key 模式 → cycle-27 R291
紧急修了 2 处豁免清单 + 立 sync 守护。但根本问题没解决：**未来开发者
不知道 dynamic-key 模式的存在**，下次再加 helper-returned 字符串就再踩
同一个坑。

R295 在 ``docs/i18n.md`` ``## Adding a new user-facing string`` 章节后
新增 ``### Dynamic key reservation rule (R295)`` 小节：

1. 说明 ``JS_T_CALL_RE`` 只识别字面值 ``t('...')`` 而非 dynamic 表达式
2. 用代码示例展示 wrong pattern
3. 强制要求同时更新 ``_PRE_RESERVED_KEYS`` + ``_WEB_RESERVED_DYNAMIC``
4. 引用 R291 sync 守护测试 (``test_feat_dynamic_i18n_reserved_sync_r291.py``)
5. 列出当前 3 个真实 case (cr40 customSound / R289 fetch error / R294 http response)

R295 是 process invariant：未来增加 dynamic-key 模式的 helper 时，docs
要同步更新表格 (case-N 一栏)。
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DOCS_I18N = REPO_ROOT / "docs" / "i18n.md"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


class TestDocsI18nHasDynamicKeyRuleSection(unittest.TestCase):
    """``docs/i18n.md`` 必须包含 dynamic key 章节。"""

    def test_dynamic_key_subheading_present(self) -> None:
        src = _read(DOCS_I18N)
        match = re.search(
            r"^###\s+Dynamic key reservation rule",
            src,
            re.MULTILINE,
        )
        self.assertIsNotNone(
            match,
            "docs/i18n.md 必须有 '### Dynamic key reservation rule' H3 小节",
        )

    def test_section_mentions_js_t_call_re(self) -> None:
        """章节必须 mention 检测器名 (``JS_T_CALL_RE``) 让开发者能溯源。"""
        src = _read(DOCS_I18N)
        self.assertIn(
            "JS_T_CALL_RE",
            src,
            "Dynamic key section 必须 mention JS_T_CALL_RE 让开发者搜得到检测器",
        )

    def test_section_mentions_2_exemption_lists(self) -> None:
        """章节必须明确列出 2 处必须同步的豁免清单 (test + script)。"""
        src = _read(DOCS_I18N)
        for name in ["_PRE_RESERVED_KEYS", "_WEB_RESERVED_DYNAMIC"]:
            self.assertIn(
                name,
                src,
                f"Dynamic key section 必须 mention `{name}` (强制开发者去改这两处)",
            )

    def test_section_mentions_sync_test_r291(self) -> None:
        """章节必须 reference R291 sync 守护测试，让开发者知道有 CI 闸门。"""
        src = _read(DOCS_I18N)
        self.assertIn(
            "test_feat_dynamic_i18n_reserved_sync_r291",
            src,
            "Dynamic key section 必须 reference R291 sync 守护测试",
        )


class TestSectionListsAllKnownDynamicCases(unittest.TestCase):
    """章节末尾必须列表展示**当前**所有 dynamic-key helper case (worked examples)，
    便于未来开发者 grep 找出"同模式怎么写的"。"""

    EXPECTED_CASES = (
        ("customSound", "settings.customSound"),  # cr40
        ("_classifyFetchError", "status.requestTimeout"),  # R289
        ("_classifyHttpResponse", "status.unauthorized"),  # R294
    )

    def test_all_3_cases_documented(self) -> None:
        src = _read(DOCS_I18N)
        for helper, sample_key in self.EXPECTED_CASES:
            self.assertIn(
                helper,
                src,
                f"docs/i18n.md Dynamic key section 必须 mention helper `{helper}`",
            )
            self.assertIn(
                sample_key,
                src,
                f"docs/i18n.md Dynamic key section 必须 mention sample key `{sample_key}`",
            )

    def test_cycle_lineage_documented(self) -> None:
        """3 case 必须分别注明 cycle/R-id (便于追溯历史)。"""
        src = _read(DOCS_I18N)
        for anchor in ["cr40", "R289", "R294"]:
            self.assertIn(
                anchor,
                src,
                f"docs/i18n.md Dynamic key section 必须 mention `{anchor}` lineage",
            )


class TestSectionPlacementBetweenNamingAndIcu(unittest.TestCase):
    """章节位置必须在 ``### Key naming convention`` 后 + ``## ICU plural / select``
    前 (逻辑相邻：先讲 namespace 规则，再讲 dynamic 规则，再讲 ICU 语法)。"""

    def test_dynamic_section_after_naming_convention(self) -> None:
        src = _read(DOCS_I18N)
        naming_idx = src.find("### Key naming convention")
        dynamic_idx = src.find("### Dynamic key reservation rule")
        icu_idx = src.find("## ICU plural / select")
        self.assertGreater(naming_idx, -1, "Key naming convention 必须存在")
        self.assertGreater(dynamic_idx, -1, "Dynamic key reservation 必须存在")
        self.assertGreater(icu_idx, -1, "ICU plural / select 必须存在")
        self.assertGreater(
            dynamic_idx,
            naming_idx,
            "Dynamic key section 必须出现在 Key naming convention 后",
        )
        self.assertLess(
            dynamic_idx,
            icu_idx,
            "Dynamic key section 必须出现在 ICU plural / select 前 (逻辑分组)",
        )


class TestProcessInvariantR291LinkagePreserved(unittest.TestCase):
    """meta-doc: R295 是 R291 sync 守护的"文档/教学层" — docstring 必须
    显式提到这是配套 process invariant。"""

    def test_docstring_mentions_r291_lineage(self) -> None:
        src = _read(Path(__file__))
        self.assertIn(
            "R291",
            src,
            "R295 test docstring 必须 reference R291 (sync 守护) 作为前置 anchor",
        )

    def test_docstring_mentions_3_cases(self) -> None:
        """R295 docstring 必须列出 3 个 case 名 (与 docs 表格一致)。"""
        src = _read(Path(__file__))
        for case in ["customSound", "_classifyFetchError", "_classifyHttpResponse"]:
            self.assertIn(case, src, f"R295 docstring 必须 mention case `{case}`")


if __name__ == "__main__":
    unittest.main()
