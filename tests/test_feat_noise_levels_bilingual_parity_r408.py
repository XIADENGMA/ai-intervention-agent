"""R408 · ``docs/noise-levels.{md,zh-CN.md}`` 双语 parity invariant
(cycle-46 #C1, doc-parity **6th 应用 — 完全工业化期巩固**)。

doc-parity 系列累计应用
-----------------------

- R335 (cycle-36): ``docs/troubleshooting.{md,zh-CN.md}`` — 1st app
- R340 (cycle-37): ``README.{md,zh-CN.md}`` 主仓 README — 2nd app
- R346 (cycle-38): ``packages/vscode/README.{md,zh-CN.md}`` — 3rd app
- R394 (cycle-44): ``docs/configuration.{md,zh-CN.md}`` — 4th app
- R400 (cycle-45): ``docs/contributor-guide-invariant-tests.{md,zh-CN.md}``
  — 5th app 深化期工业化里程碑 (reflexive 应用)
- **R408 (cycle-46)** — ``docs/noise-levels.{md,zh-CN.md}`` → **6th app
  完全工业化期巩固**, doc-parity 与 v3.7 decision-three-layer (4 应用) /
  v3.8 全 pattern (3/6 应用) / v3.9 (6 应用) 等完全工业化 pattern 进入
  同一梯队

特殊价值
--------

``noise-levels`` 是项目的 **通知 / 日志 / toast 三层噪音控制规范文档**, 是
所有 cycle 提交 notification / logging / UI feedback 变更时的 review
checklist 之一。这份文档双语漂移会导致:

- 中文母语 contributor 提 PR 时按 ZH 版默认级别配置, 但 EN 版已升级为更严
  格的阈值, 触发 reviewer 来回沟通;
- ``test_noise_levels.py`` 等 invariant 引用文档中定义的级别, 双语描述漂移
  会让人怀疑该 invariant 已过期;
- 6 应用 = doc-parity 完全工业化标准 (与 v3.8 idempotent/test-isolation /
  v3.9 async race contract 一致), 锁住此文档完成 doc-parity 从深化期 → 完
  全工业化期的最后一步。

R408 invariant (4 层 + lineage marker)
--------------------------------------

1. **Layer 1 (Anchor)**: 两个文件存在 + 行数差异 ≤ 30%
2. **Layer 2 (章节结构 1:1)**: ``## section`` 数量 + 顺序完全 1:1 映射
3. **Layer 3 (语义映射表)**: 12 个英文 H2 + 12 个中文 H2 显式 mapping
4. **Layer 4 (代码块计数 parity + 外链 ±3 parity)**

methodology lineage
-------------------

doc-parity 从 cycle-36 启动到 cycle-46 完成 1→6 应用, 6 应用 = 完全工业化
期 (v3.x 系列 6 应用阈值, 等同 v3.9 async race contract / v3.8 test-isolation
等成熟 pattern). 与 i18n consistency (R350/R353/R366/R374, 4 应用) / API
contract (R355/R358/R364/R368/R378/R392/R398/R404, 8 应用) / Pydantic
validator coverage (R380/R384/R388/R396/R402, 5 应用) / route registration
matrix (R406, 1 应用 新维度) 形成 "用户/开发者面向产物完整性 + 架构层防御"
多维度协同。
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DOC_EN = REPO_ROOT / "docs" / "noise-levels.md"
DOC_ZH = REPO_ROOT / "docs" / "noise-levels.zh-CN.md"

# 显式 1:1 mapping (EN 标题 → ZH-CN 标题)。
# 任一侧标题改名后需要同步更新此 mapping, layer 3 测试会拦截 unmapped。
SECTION_MAPPING: dict[str, str] = {
    "1. The 3-level × 4-channel matrix": "一、三级 × 四通道矩阵",
    "2. Level semantics": "二、级别语义",
    "3. Default rule and escalation circuit-breaker": "三、默认规则与升级熔断",
    "4. Channel semantics": "四、通道语义",
    "5. Current-state snapshot (when this doc was committed, 2026-04-18)": (
        "五、现状快照（本文 commit 时，2026-04-18）"
    ),
    "6. Anti-patterns (using the current code as the textbook)": "六、反例清单（以现状为教材）",
    "7. Consumption path — how each phase-1/2 change-set honours this doc": (
        "七、消费路径——阶段 1/2 各改动点怎么守本文"
    ),
    "8. Review checklist (whenever you add a new notification / log / toast)": (
        "八、review checklist（引入任何新通知 / 日志 / toast 时）"
    ),
    "9. Automated guard (`tests/test_noise_levels.py`)": (
        "九、自动守护（`tests/test_noise_levels.py`）"
    ),
    "10. Relationship to other specifications": "十、与其他规范的关系",
    "11. Change history": "十一、变更历史",
    "12. Exit clause (delete when mission complete)": "十二、退场条款（mission complete 即删）",
}


def _extract_h2_headings(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    out: list[str] = []
    for line in text.splitlines():
        if line.startswith("## ") and not line.startswith("### "):
            out.append(line[3:].strip())
    return out


class TestLayer1AnchorAndLineBalance:
    """Layer 1: 文件存在 + 行数差异 ≤ 30%。"""

    def test_en_file_exists(self):
        assert DOC_EN.is_file(), f"R408-L1: {DOC_EN} missing"

    def test_zh_file_exists(self):
        assert DOC_ZH.is_file(), f"R408-L1: {DOC_ZH} missing"

    def test_line_count_within_30_percent(self):
        en_lines = DOC_EN.read_text(encoding="utf-8").splitlines()
        zh_lines = DOC_ZH.read_text(encoding="utf-8").splitlines()
        ratio = abs(len(en_lines) - len(zh_lines)) / max(len(en_lines), len(zh_lines))
        assert ratio <= 0.30, (
            f"R408-L1: line count differs by {ratio:.1%} "
            f"(EN={len(en_lines)}, ZH={len(zh_lines)}); ≤ 30% expected"
        )


class TestLayer2StructuralParity:
    """Layer 2: ## 章节数量 + 顺序 1:1 映射。"""

    def test_h2_count_equal(self):
        en = _extract_h2_headings(DOC_EN)
        zh = _extract_h2_headings(DOC_ZH)
        assert len(en) == len(zh), (
            f"R408-L2: H2 count mismatch — EN has {len(en)} sections, "
            f"ZH has {len(zh)}. EN={en}, ZH={zh}"
        )

    def test_at_least_12_h2_sections(self):
        en = _extract_h2_headings(DOC_EN)
        assert len(en) >= 12, (
            f"R408-L2: noise-levels.md should have ≥ 12 H2 sections "
            f"(current: {len(en)}). If the doc was refactored to fewer "
            f"sections, update SECTION_MAPPING and this assertion."
        )


class TestLayer3SemanticMapping:
    """Layer 3: 每个 H2 必须在 SECTION_MAPPING 内有 1:1 mapping。"""

    def test_every_en_section_in_mapping(self):
        en = _extract_h2_headings(DOC_EN)
        missing = [s for s in en if s not in SECTION_MAPPING]
        assert not missing, (
            f"R408-L3: EN H2 missing from SECTION_MAPPING: "
            f"{missing}. Update SECTION_MAPPING or rename headings."
        )

    def test_every_zh_section_in_mapping(self):
        zh = _extract_h2_headings(DOC_ZH)
        zh_values = set(SECTION_MAPPING.values())
        missing = [s for s in zh if s not in zh_values]
        assert not missing, (
            f"R408-L3: ZH H2 missing from SECTION_MAPPING values: {missing}"
        )

    def test_order_matches_via_mapping(self):
        en = _extract_h2_headings(DOC_EN)
        zh = _extract_h2_headings(DOC_ZH)
        expected_zh = [SECTION_MAPPING.get(e, "<UNMAPPED>") for e in en]
        assert zh == expected_zh, (
            f"R408-L3: H2 order mismatch.\nEN -> mapped: {expected_zh}\nZH actual: {zh}"
        )


class TestLayer4ContentArtifactsParity:
    """Layer 4: 代码块计数 + 外链计数 parity。"""

    @staticmethod
    def _count_code_blocks(text: str) -> int:
        return text.count("```") // 2

    @staticmethod
    def _count_external_links(text: str) -> int:
        return len(re.findall(r"\]\(https?://", text))

    def test_code_block_count_within_2(self):
        en_text = DOC_EN.read_text(encoding="utf-8")
        zh_text = DOC_ZH.read_text(encoding="utf-8")
        en_blocks = self._count_code_blocks(en_text)
        zh_blocks = self._count_code_blocks(zh_text)
        assert abs(en_blocks - zh_blocks) <= 2, (
            f"R408-L4: code block count mismatch — EN={en_blocks}, "
            f"ZH={zh_blocks}, diff > 2. Code examples should be 1:1 bilingual."
        )

    def test_external_link_count_within_3(self):
        en_text = DOC_EN.read_text(encoding="utf-8")
        zh_text = DOC_ZH.read_text(encoding="utf-8")
        en_links = self._count_external_links(en_text)
        zh_links = self._count_external_links(zh_text)
        assert abs(en_links - zh_links) <= 3, (
            f"R408-L4: external link count differs by "
            f"{abs(en_links - zh_links)} (EN={en_links}, "
            f"ZH={zh_links}); ≤ 3 expected"
        )


class TestR408LineageMarker:
    """R408 lineage marker: doc-parity 6 应用完全工业化期巩固。"""

    def test_this_file_contains_r408_marker(self):
        text = Path(__file__).read_text(encoding="utf-8")
        assert "R408" in text

    def test_this_file_references_doc_parity_lineage(self):
        text = Path(__file__).read_text(encoding="utf-8")
        for prior in ("R335", "R340", "R346", "R394", "R400"):
            assert prior in text, f"R408: must cite doc-parity lineage: {prior}"

    def test_this_file_marks_6th_app_milestone(self):
        text = Path(__file__).read_text(encoding="utf-8")
        for kw in ("doc-parity", "6th app", "完全工业化期巩固"):
            assert kw in text, f"R408: missing keyword: {kw!r}"
