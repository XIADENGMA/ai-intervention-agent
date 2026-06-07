"""R308: CI xdist worker tuning 决策文档 invariant (cycle-31 t31-3)。

cycle-30 cr60 §5 #C1 - CI 加速 v2 决策记录。

R305 引入了 ``-n 4 --dist=loadfile`` 作为 CI default, 但没有记录 *为什么*
是 4 而不是 auto/2/8。R308 通过本地 benchmark 收集数据 (16-core M-series)
+ GitHub Actions free tier 推算, 形成决策记录文档 ``docs/perf-ci-xdist-r308.md``,
并锁定:

1. 文档存在 + 引用 R305 + R308 lineage
2. 文档必须含 benchmark table (4 行: -n 2, 4, 8, auto)
3. 文档必须提及 "cross-environment" / "GitHub Actions" (防 future
   maintainers 不知道 2-core runner 上 auto 退化的教训)
4. 文档必须解释为什么不用 worksteal (R72-A pollution lineage)

================================================================
| Tests | 维度                                                    |
|-------|------------------------------------------------------|
| 4     | 文档存在 / R305 reference / R308 marker / size > 0     |
| 3     | benchmark 表格: -n 2 / -n 4 / -n 8 / -n auto 至少 3 行  |
| 2     | 决策原因: cross-environment + GitHub Actions 关键词      |
| 1     | worksteal 替代方案被显式拒绝 (R72-A lineage)             |
================================================================
| 10 总计                                                          |
================================================================

**pattern lineage**: v3.7 "运行时 + 决策文档 + 锁" 三层 pattern。
R306 锁的是 "Python 代码 + Jinja 模板 + ctx 注入" 三层一致性;
**R308 锁的是 "代码 (ci_gate.py R305) + 决策文档 (R308) + 锁文档不漂移
的 invariant" 三层**。每次未来开发者想改 `-n 4` 时都会被文档 + invariant
两层提醒 "请重新跑 benchmark"。
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DOC = PROJECT_ROOT / "docs" / "perf-ci-xdist-r308.md"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


# ============================================================
# 文档存在 + 基础引用
# ============================================================
class TestDocExistsAndReferences(unittest.TestCase):
    """决策文档必须存在并引用 R305 + R308"""

    def test_doc_file_exists(self) -> None:
        """``docs/perf-ci-xdist-r308.md`` 必须存在。"""
        self.assertTrue(
            DOC.exists(),
            f"R308: {DOC} 必须存在 (CI xdist worker tuning 决策记录)",
        )

    def test_doc_has_substantial_content(self) -> None:
        """决策文档不能是空文件 / 占位符 (> 2000 字符 = 实质内容)。"""
        content = _read(DOC)
        self.assertGreater(
            len(content),
            2000,
            f"R308: {DOC.name} 长度 ({len(content)}) 必须 > 2000 字符 — "
            "决策记录必须 substantive, 不能是 placeholder",
        )

    def test_doc_references_r305(self) -> None:
        """决策文档必须引用 R305 (CI gate xdist 引入起点)。"""
        content = _read(DOC)
        self.assertIn(
            "R305",
            content,
            "R308: 决策文档必须引用 R305 (前序工作), 让 future maintainers "
            "知道完整 lineage",
        )

    def test_doc_has_r308_marker(self) -> None:
        """决策文档必须有 R308 marker (本身就是 R308 产出)。"""
        content = _read(DOC)
        self.assertIn(
            "R308",
            content,
            "R308: 决策文档必须含 R308 marker (本身就是 R308 产出, "
            "防误删 R308 注释后 marker 丢失)",
        )


# ============================================================
# benchmark 表格存在
# ============================================================
class TestBenchmarkTablePresent(unittest.TestCase):
    """决策文档必须含 4 种 worker 数的 benchmark"""

    def setUp(self) -> None:
        self.content = _read(DOC)

    def test_n_4_benchmark_documented(self) -> None:
        """``-n 4`` benchmark 必须出现 (CI default)。"""
        self.assertRegex(
            self.content,
            r"-n\s*4",
            "R308: 决策文档必须含 `-n 4` benchmark (CI default 数据点)",
        )

    def test_n_auto_benchmark_documented(self) -> None:
        """``-n auto`` benchmark 必须出现 (反面教材)。"""
        self.assertRegex(
            self.content,
            r"-n\s*auto",
            "R308: 决策文档必须含 `-n auto` benchmark (说明为什么 CI 不选 auto)",
        )

    def test_n_2_or_8_benchmark_documented(self) -> None:
        """至少 ``-n 2`` 或 ``-n 8`` benchmark 必须出现 (边界数据点)。"""
        has_n2 = re.search(r"-n\s*2[^0-9]", self.content)
        has_n8 = re.search(r"-n\s*8[^0-9]", self.content)
        self.assertTrue(
            has_n2 or has_n8,
            "R308: 决策文档必须至少含 -n 2 或 -n 8 边界数据点",
        )


# ============================================================
# 决策原因关键词
# ============================================================
class TestDecisionRationale(unittest.TestCase):
    """决策原因必须含关键词解释 cross-env 考虑"""

    def setUp(self) -> None:
        self.content = _read(DOC)

    def test_cross_environment_or_github_actions_mentioned(self) -> None:
        """文档必须提及 "cross-environment" / "GitHub Actions" — 这是
        future maintainers 最常犯错的关键点 (本地快 ≠ CI 快)。"""
        self.assertTrue(
            "cross-environment" in self.content or "GitHub Actions" in self.content,
            "R308: 文档必须提及 'cross-environment' 或 'GitHub Actions' "
            "(防 future maintainers 凭本地 -n auto 快就改默认)",
        )

    def test_ci_runner_vcpu_count_mentioned(self) -> None:
        """文档必须提及 CI runner vCPU 规格 (具体数字才有说服力)。"""
        m = re.search(r"\b\d+\s*vCPU\b", self.content)
        self.assertIsNotNone(
            m,
            "R308: 文档必须提及具体 vCPU 数 (e.g. '2 vCPU' / '4 vCPU') "
            "— 抽象说 'CI 核少' 不够有说服力",
        )


# ============================================================
# worksteal 拒绝 lineage
# ============================================================
class TestWorkstealRejectionLineage(unittest.TestCase):
    """文档必须显式拒绝 worksteal 替代方案 (R72-A pollution lineage)"""

    def setUp(self) -> None:
        self.content = _read(DOC)

    def test_worksteal_alternative_explicitly_rejected(self) -> None:
        """文档必须提及 worksteal 并解释为什么不用 (R72-A pollution)。"""
        has_worksteal = "worksteal" in self.content
        # 拒绝理由必须包含 pollution / R72 / 副作用关键词之一
        has_rejection_reason = bool(
            re.search(
                r"worksteal[\s\S]{0,500}?(pollution|R72|副作用|non-deterministic)",
                self.content,
                re.IGNORECASE,
            )
        )
        self.assertTrue(
            has_worksteal and has_rejection_reason,
            "R308: 文档必须提及 worksteal 并解释拒绝理由 "
            "(R72-A pollution / non-deterministic, 防 future maintainers 凭"
            "'worksteal 是 xdist 官方推荐' 而改回)",
        )


if __name__ == "__main__":
    unittest.main()
