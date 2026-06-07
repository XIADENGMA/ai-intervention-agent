"""R314 invariant: ``_FETCH_RETRY_BACKOFF_S`` 决策三层 (代码 + 决策文档 +
锁文档) — v3.7 决策三层 pattern 2nd app。

背景
----
R308 (cr61) 引入 v3.7 第二个新 pattern "决策三层 invariant", 锁了 CI
xdist `-n 4 --dist=loadfile` 决策的三层一致性 (代码 + 决策文档 + 锁文档
invariant)。R314 是其第 2 次应用, 对象从 "CI 配置" 切换到 "fetch retry
backoff 数字"。

为什么 fetch backoff 需要决策三层
----------------------------
``_FETCH_RETRY_BACKOFF_S = (0.0, 0.1, 0.25, 0.5, 1.0)`` 这个 5 元组看起来
任意, 但实际每个元素都对应一类网络抖动 (DNS / TLS / 网格 / 蜂窝 handoff)。
没有决策文档时:
- 后人会用 "exponential backoff is best practice" 把它改成
  ``(0.1, 0.2, 0.4, 0.8, 1.6)`` — 看似优雅, 实际错过 TCP RST 即时重试场景
- 或者扩到 7-10 个元素 "为了更可靠" — 实际超 2s 后大部分是真故障, retry
  收益递减
- 或者改成 list 类型 "为了灵活" — 失去 immutability, 引入 monkey-patch
  跨测试污染风险

R314 锁定三层
-------------
- **Layer 1 (Code)**: ``server_feedback.py:206`` 的 ``_FETCH_RETRY_BACKOFF_S``
  必须是 ``tuple[float, ...]`` 字面量 ``(0.0, 0.1, 0.25, 0.5, 1.0)``,
  恰好 5 个元素
- **Layer 2 (Decision doc)**: ``docs/perf-fetch-retry-backoff-r314.md``
  必须存在, 含 R308 references / R314 marker / 5 个具体退避值 / 总等待时间 /
  retry 次数 / 关键失败类别说明 (TLS / DNS / cellular handoff)
- **Layer 3 (Lock invariant)**: 本测试文件锁住前两层的一致性 + future-guard

pattern lineage
---------------
v3.7 决策三层 pattern 应用历史:
- 1st: R308 (cr61) — CI xdist worker tuning
- **2nd: R314 (cycle-32 #B2, this)** — fetch retry backoff sequence

methodology: 决策三层 pattern 的核心是 "把魔法数字配上 *为什么是这个* 文档"
+ "锁住文档与代码不漂移"。R314 把这个 pattern 从 "infra 决策" 扩展到
"运行时常量决策", 是 pattern 域跨度的关键证明。
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_PY = REPO_ROOT / "src" / "ai_intervention_agent" / "server_feedback.py"
DOC = REPO_ROOT / "docs" / "perf-fetch-retry-backoff-r314.md"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


# Expected baseline (locked by R314)
EXPECTED_BACKOFF_VALUES = (0.0, 0.1, 0.25, 0.5, 1.0)
EXPECTED_RETRY_COUNT = 5
EXPECTED_TOTAL_WAIT_S = 1.85  # 0 + 0.1 + 0.25 + 0.5 + 1.0 = 1.85


# ============================================================================
# Layer 1: Code 锁定 _FETCH_RETRY_BACKOFF_S 字面量
# ============================================================================


class TestFetchRetryBackoffConstant(unittest.TestCase):
    """Layer 1: 代码中的 _FETCH_RETRY_BACKOFF_S 必须是固定 5 元组。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.src = _read(SRC_PY)

    def test_constant_name_is_module_level_underscore_prefix(self) -> None:
        """R314-L1: 常量命名必须是 ``_FETCH_RETRY_BACKOFF_S`` (模块级 + 下划线前缀私有)。"""
        # multiline flag 让 ^ 匹配每行行首, 而不仅是 string 起始 (同 R310 修复)
        m = re.search(
            r"^_FETCH_RETRY_BACKOFF_S\s*:",
            self.src,
            re.MULTILINE,
        )
        self.assertIsNotNone(
            m,
            "R314-L1: 必须有模块级 _FETCH_RETRY_BACKOFF_S 注解",
        )

    def test_constant_is_tuple_type_annotated(self) -> None:
        """R314-L1: 类型必须是 ``tuple[float, ...]`` (immutable, 防 monkey-patch 污染)。"""
        m = re.search(
            r"_FETCH_RETRY_BACKOFF_S\s*:\s*tuple\[float,\s*\.\.\.\]\s*=", self.src
        )
        self.assertIsNotNone(
            m,
            "R314-L1: _FETCH_RETRY_BACKOFF_S 必须标注为 tuple[float, ...] (不能用 list)",
        )

    def test_constant_value_matches_expected_5_tuple(self) -> None:
        """R314-L1: 字面量必须恰好是 (0.0, 0.1, 0.25, 0.5, 1.0)。"""
        # 匹配赋值右侧的 tuple 字面量
        m = re.search(
            r"_FETCH_RETRY_BACKOFF_S[^=]*=\s*\(([^)]+)\)",
            self.src,
        )
        self.assertIsNotNone(m, "R314-L1: 未找到 _FETCH_RETRY_BACKOFF_S = (...) 字面量")
        assert m is not None
        # 解析数字
        nums_str = m.group(1)
        nums = tuple(float(s.strip()) for s in nums_str.split(",") if s.strip())
        self.assertEqual(
            nums,
            EXPECTED_BACKOFF_VALUES,
            f"R314-L1: backoff 字面量必须是 {EXPECTED_BACKOFF_VALUES}, 实际 {nums}",
        )

    def test_exactly_5_elements(self) -> None:
        """R314-L1: 元素数量必须恰好 5。"""
        m = re.search(r"_FETCH_RETRY_BACKOFF_S[^=]*=\s*\(([^)]+)\)", self.src)
        assert m is not None
        nums = [s.strip() for s in m.group(1).split(",") if s.strip()]
        self.assertEqual(
            len(nums),
            EXPECTED_RETRY_COUNT,
            f"R314-L1: backoff 必须有 {EXPECTED_RETRY_COUNT} 个元素, 实际 {len(nums)}",
        )

    def test_constant_is_actually_used_by_consumer(self) -> None:
        """R314-L1: 常量必须被 ``_close_orphan_task_best_effort`` 实际消费 (防 dead code)。"""
        # 必须出现 for retry_idx, backoff_s in enumerate(_FETCH_RETRY_BACKOFF_S)
        self.assertRegex(
            self.src,
            r"enumerate\s*\(\s*_FETCH_RETRY_BACKOFF_S\s*\)",
            "R314-L1: _FETCH_RETRY_BACKOFF_S 必须被 enumerate 实际消费",
        )

    def test_total_wait_time_matches_decision(self) -> None:
        """R314-L1: 元素之和 = 1.85s (决策文档锁定)。"""
        m = re.search(r"_FETCH_RETRY_BACKOFF_S[^=]*=\s*\(([^)]+)\)", self.src)
        assert m is not None
        nums = tuple(float(s.strip()) for s in m.group(1).split(",") if s.strip())
        self.assertAlmostEqual(
            sum(nums),
            EXPECTED_TOTAL_WAIT_S,
            places=2,
            msg=f"R314-L1: 总等待 {sum(nums)} 与决策文档锁定的 {EXPECTED_TOTAL_WAIT_S}s 不一致",
        )


# ============================================================================
# Layer 2: Decision doc 存在 + 内容完整
# ============================================================================


class TestDecisionDocExistsAndIsSubstantial(unittest.TestCase):
    """Layer 2: ``docs/perf-fetch-retry-backoff-r314.md`` 必须存在且充实。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.doc = _read(DOC)

    def test_doc_file_exists(self) -> None:
        """R314-L2: 决策文档必须存在。"""
        self.assertTrue(DOC.exists(), f"R314-L2: {DOC} 必须存在")

    def test_doc_references_r314_marker(self) -> None:
        """R314-L2: 文档必须含 R314 marker。"""
        self.assertIn("R314", self.doc, "R314-L2: 决策文档必须含 R314 marker")

    def test_doc_references_r308_as_prior_art(self) -> None:
        """R314-L2: 文档必须引用 R308 (decision-three-layer pattern 1st app)。"""
        self.assertIn(
            "R308",
            self.doc,
            "R314-L2: 文档必须引用 R308 作为 decision-three-layer 1st app",
        )

    def test_doc_is_substantial(self) -> None:
        """R314-L2: 文档必须足够长 (3000+ 字符, 防止"占位文档")。"""
        self.assertGreater(
            len(self.doc),
            3000,
            f"R314-L2: 文档长度 {len(self.doc)} < 3000, 可能是占位文档",
        )

    def test_doc_contains_all_5_backoff_values(self) -> None:
        """R314-L2: 文档必须明确列出 5 个具体退避值。"""
        for v in EXPECTED_BACKOFF_VALUES:
            with self.subTest(value=v):
                # 值可能以 "0.0s" / "0.1s" / "100ms" / "1000ms" 等格式出现
                # 我们用宽松匹配: 数字本身或其 ms 形式
                v_str = str(v)
                ms_str = (
                    f"{int(v * 1000)}ms"
                    if v > 0 and (v * 1000) == int(v * 1000)
                    else None
                )
                found = v_str in self.doc or (ms_str and ms_str in self.doc)
                self.assertTrue(
                    found,
                    f"R314-L2: 文档必须含退避值 {v_str} 或 {ms_str}",
                )

    def test_doc_explains_total_wait_time(self) -> None:
        """R314-L2: 文档必须解释总等待时间 (~1.85s)。"""
        # 接受 "1.85s" / "1.85 s" / "~1.85" 等格式
        self.assertRegex(
            self.doc,
            r"1\.85\s*s?\b",
            "R314-L2: 文档必须解释总等待时间 ~1.85s",
        )

    def test_doc_explains_retry_count_choice(self) -> None:
        """R314-L2: 文档必须解释为什么是 5 次 retry (不是 3 / 7)。"""
        # 必须含 "5 retries" / "5 次" / "exactly 5" 等
        has_5_count = (
            "5 retries" in self.doc
            or "exactly 5" in self.doc.lower()
            or "5 次" in self.doc
        )
        self.assertTrue(
            has_5_count,
            "R314-L2: 文档必须解释为什么选 5 次 retry",
        )
        # 必须 reject 3 / 7
        has_3_reject = "3 retries" in self.doc or "not 3" in self.doc.lower()
        has_7_reject = "7+" in self.doc or "not 7" in self.doc.lower()
        self.assertTrue(
            has_3_reject and has_7_reject,
            "R314-L2: 文档必须显式拒绝 3 retry 和 7+ retry 方案",
        )

    def test_doc_mentions_network_failure_classes(self) -> None:
        """R314-L2: 文档必须提及至少 3 类网络失败 (DNS / TLS / cellular)。"""
        failure_classes = ["DNS", "TLS", "cellular"]
        for cls in failure_classes:
            with self.subTest(failure_class=cls):
                self.assertIn(
                    cls,
                    self.doc,
                    f"R314-L2: 文档必须解释 {cls} 失败类别",
                )

    def test_doc_explains_tuple_vs_list_choice(self) -> None:
        """R314-L2: 文档必须解释为什么用 tuple 而不是 list。"""
        self.assertIn(
            "tuple",
            self.doc.lower(),
            "R314-L2: 文档必须讨论 tuple/list 选择",
        )
        self.assertIn(
            "immutab",  # immutable / immutability
            self.doc.lower(),
            "R314-L2: 文档必须提到 immutability 作为 tuple 选择的理由",
        )


# ============================================================================
# Layer 3: Cross-layer 锁文档与代码不漂移
# ============================================================================


class TestCrossLayerDecisionLockConsistency(unittest.TestCase):
    """Layer 3: 文档中的具体值必须与代码 baseline 完全一致 (防 silent drift)。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.src = _read(SRC_PY)
        cls.doc = _read(DOC)

    def test_doc_value_tuple_matches_code(self) -> None:
        """R314-L3: 文档中以 ``(0.0, 0.1, 0.25, 0.5, 1.0)`` 字面量出现的部分必须与代码一致。"""
        # 文档应该在 cross-reference 部分或 TL;DR 部分直接展示 tuple
        code_literal = "(0.0, 0.1, 0.25, 0.5, 1.0)"
        self.assertIn(
            code_literal,
            self.doc,
            f"R314-L3: 文档必须含完整 tuple 字面量 {code_literal} (与代码字面一致)",
        )
        self.assertIn(
            code_literal,
            self.src,
            f"R314-L3: 代码必须含完整 tuple 字面量 {code_literal}",
        )

    def test_doc_cross_references_actual_code_path(self) -> None:
        """R314-L3: 文档必须指向真实的代码路径 (server_feedback.py:206 或函数名)。"""
        self.assertIn(
            "server_feedback.py",
            self.doc,
            "R314-L3: 文档必须引用代码路径 src/.../server_feedback.py",
        )
        # 还要 reference consumer 函数
        self.assertIn(
            "_close_orphan_task_best_effort",
            self.doc,
            "R314-L3: 文档必须 reference consumer 函数 _close_orphan_task_best_effort",
        )


# ============================================================================
# R314 lineage marker
# ============================================================================


class TestR314MarkerPresent(unittest.TestCase):
    """R314 lineage marker。"""

    def test_test_file_contains_lineage_explanation(self) -> None:
        """本测试文件 docstring 必须含 R314 + v3.7 决策三层 + R308 reference。"""
        src = _read(Path(__file__))
        self.assertIn("R314", src, "R314 marker 应在测试 docstring")
        self.assertIn("v3.7", src, "R314 应说明 v3.7 决策三层 lineage")
        self.assertIn("2nd", src, "R314 应说明这是 v3.7 决策三层 pattern 2nd app")
        self.assertIn(
            "R308",
            src,
            "R314 应引用 R308 作为 v3.7 决策三层 1st app",
        )


if __name__ == "__main__":
    unittest.main()
