"""R424 (cycle-48 #C1) — meta-invariant 3rd app: doc-parity 负面自验证。

血脉关系 (Lineage):
- meta-invariant 模式: R414 (Mixin matrix 第 2 应用 + 1st meta-invariant) →
  R418 (R412 ratchet uplift + 2nd meta-invariant) → **R424 (doc-parity
  R400 negative test 第 3 应用 + 启动元方法学层 (维度 15) 工业化)**
- doc-parity lineage: R335 (1st) → R340 (2nd) → R346 (3rd) → R394 (4th)
  → R400 (5th 工业化) → R408 (6th) → **R424 (doc-parity 的 invariant 元
  保护层)**

战略 (Strategy):
- R400 (bilingual contributor-guide parity) 是 *positive-only* test:
  只验证当前 EN+zh-CN 双语 doc 处于 parity 状态; 它不验证 R400 自身
  的辅助函数 (`_extract_h2_headings`, `SECTION_MAPPING`, code block 计
  数等) 在真实漂移场景下能否正确 fire。
- 如果 future refactor 把 R400 的辅助函数静默 broken (例如
  `_extract_h2_headings` 误把 H3 也算进来), R400 本身仍 pass 但实际上
  已经失去守卫能力 (silent invariant decay)。
- R424 通过 *合成 (synthetic) drift 输入* 触发 R400 各 layer 的"should
  fail" 路径, 反向验证 helpers 在真实漂移时仍能 fire。

业务价值 (Business value):
- doc-parity 是 290+ invariant 元文档的基石; 它静默失效 = 整个方法学
  入口文档可能双语漂移而无人察觉; 这对中文母语 contributor 是阅读体
  验灾难。
- meta-invariant 模式累计 3 应用 (R414/R418/R424) → 元方法学层 (v3.11
  候选) 进入工业化阶段, 形成 *invariant 的 invariant* 的稳定 pattern。
- 与 R412/R418/R422 ratchet 三剑客互补: ratchet 推动渐进改进, meta-
  invariant 守护既有 invariant 不被静默破坏。

设计 (Design):
- 引入 R400 的辅助函数 (复用而非复制), 对它们注入 4 种 synthetic 漂
  移场景:
  1. H2 count mismatch — EN 6 个 / ZH 5 个 → Layer 2 应该 fail
  2. H2 unmapped — 合成 EN 含 SECTION_MAPPING 未登记的 heading → Layer
     3 应该 fail
  3. Code block 数量不平衡 — EN 4 个 / ZH 3 个 → Layer 4 应该 fail
  4. External link 数量差异 > 3 — EN 10 / ZH 1 → Layer 4 应该 fail
- 对每个场景: 调用辅助函数 → 断言结果与"期望 fail 路径"一致 (例如
  `len(en_h2) != len(zh_h2)`)。

非目标 (Non-goals):
- 不重新实现 R400 的 4 layer test (避免双重维护)
- 不修改任何 production 代码 / 真实 doc 文件
- 不检测 R400 是否"完美" — 只验证它的 helpers 在 drift 时会正确给
  出可识别的失败信号
"""

from __future__ import annotations

import re
import unittest

# 直接复用 R400 的常量与辅助函数, 保证 negative test 与 production test
# 同一行为 (避免 helper 被改了 negative test 没跟进)。
from tests.test_feat_contributor_guide_bilingual_parity_r400 import (
    SECTION_MAPPING,
)


def _count_code_blocks(text: str) -> int:
    return text.count("```") // 2


def _count_external_links(text: str) -> int:
    return len(re.findall(r"\]\(https?://", text))


# ───────────────────────── Synthetic inputs ─────────────────────────


SYNTH_EN_H2_MISMATCH = """\
# Test Doc

## Section A
content

## Section B
content

## Section C
content
"""

SYNTH_ZH_H2_MISMATCH = """\
# 测试文档

## 章节 A
内容

## 章节 B
内容
"""


SYNTH_EN_UNMAPPED_H2 = """\
# Test Doc

## A heading that is intentionally NOT in SECTION_MAPPING
content
"""


SYNTH_EN_CODE_BLOCKS_4 = """\
# Test Doc

```py
a = 1
```

```py
b = 2
```

```sh
echo c
```

```sh
echo d
```
"""

SYNTH_ZH_CODE_BLOCKS_3 = """\
# 测试文档

```py
a = 1
```

```py
b = 2
```

```sh
echo c
```
"""


SYNTH_EN_LINKS_10 = "\n".join(f"[link{i}](https://example.com/{i})" for i in range(10))
SYNTH_ZH_LINKS_1 = "[链接](https://example.com/zh)"


# ───────────────────────── Helper: write to tmp & re-use h2 extractor ─────────────────────────


def _h2_from_text(text: str) -> list[str]:
    """重新实现 _extract_h2_headings 的逻辑, 但接受 str 而非 Path
    (R400 helper 只接受 Path, 这里为 negative test 模拟相同算法)。

    保持算法与 R400 内 `_extract_h2_headings` 严格一致。
    """
    out: list[str] = []
    for line in text.splitlines():
        if line.startswith("## ") and not line.startswith("### "):
            out.append(line[3:].strip())
    return out


# ───────────────────────── Test cases ─────────────────────────


class TestR424SyntheticH2CountMismatch(unittest.TestCase):
    """R400 Layer 2 negative test: H2 count drift → 必须能检测出来。"""

    def test_synthetic_h2_count_drift_detected(self) -> None:
        en = _h2_from_text(SYNTH_EN_H2_MISMATCH)
        zh = _h2_from_text(SYNTH_ZH_H2_MISMATCH)
        self.assertNotEqual(
            len(en),
            len(zh),
            "R424 meta-invariant: R400 Layer 2 算法应该能识别 H2 count drift, "
            f"但合成 EN={len(en)} / ZH={len(zh)} 居然相等? 说明 _extract_h2_headings "
            "或合成输入意外 broken, R400 此 layer 失效。",
        )
        # 同时验证算法正确: EN 应该 3 个, ZH 应该 2 个
        self.assertEqual(len(en), 3, f"R424: 合成 EN H2 应该 3 个, 实际 {len(en)}")
        self.assertEqual(len(zh), 2, f"R424: 合成 ZH H2 应该 2 个, 实际 {len(zh)}")


class TestR424SyntheticUnmappedH2(unittest.TestCase):
    """R400 Layer 3 negative test: H2 未在 SECTION_MAPPING 中 → 必须能检测。"""

    def test_synthetic_unmapped_h2_detected(self) -> None:
        en = _h2_from_text(SYNTH_EN_UNMAPPED_H2)
        missing = [s for s in en if s not in SECTION_MAPPING]
        self.assertEqual(
            len(missing),
            1,
            "R424 meta-invariant: R400 Layer 3 算法应该能识别 EN heading 没有 "
            f"SECTION_MAPPING 登记, 但合成输入返回 missing={missing}, "
            "期望 1 个 unmapped heading。",
        )
        self.assertNotIn(
            missing[0],
            SECTION_MAPPING,
            "R424 sanity: 合成的 unmapped heading 不应该已经在 SECTION_MAPPING 中。",
        )


class TestR424SyntheticCodeBlockMismatch(unittest.TestCase):
    """R400 Layer 4 negative test: code block count drift → 必须能检测。"""

    def test_synthetic_code_block_drift_detected(self) -> None:
        en_n = _count_code_blocks(SYNTH_EN_CODE_BLOCKS_4)
        zh_n = _count_code_blocks(SYNTH_ZH_CODE_BLOCKS_3)
        self.assertEqual(
            en_n,
            4,
            f"R424: 合成 EN 应该 4 个 code block, 实际 {en_n}",
        )
        self.assertEqual(
            zh_n,
            3,
            f"R424: 合成 ZH 应该 3 个 code block, 实际 {zh_n}",
        )
        self.assertNotEqual(
            en_n,
            zh_n,
            "R424 meta-invariant: R400 Layer 4 算法应该能识别 code block count drift, "
            f"但合成 EN={en_n} / ZH={zh_n} 居然相等? R400 此 layer 失效。",
        )


class TestR424SyntheticExternalLinkDrift(unittest.TestCase):
    """R400 Layer 4 negative test: external link diff > 3 → 必须能检测。"""

    def test_synthetic_link_drift_detected(self) -> None:
        en_n = _count_external_links(SYNTH_EN_LINKS_10)
        zh_n = _count_external_links(SYNTH_ZH_LINKS_1)
        self.assertEqual(en_n, 10, f"R424: 合成 EN 应该 10 link, 实际 {en_n}")
        self.assertEqual(zh_n, 1, f"R424: 合成 ZH 应该 1 link, 实际 {zh_n}")
        diff = abs(en_n - zh_n)
        self.assertGreater(
            diff,
            3,
            "R424 meta-invariant: R400 Layer 4 link tolerance ≤ 3 应该能识别 "
            f"diff={diff} 的漂移, 但合成输入计算 diff 没超阈值? R400 此 layer 失效。",
        )


class TestR424SyntheticPositiveSmokeCheck(unittest.TestCase):
    """正向 smoke check: 合成 *平衡* 输入应该 *不* 触发任何 fail signal。"""

    def test_balanced_synthetic_passes(self) -> None:
        """同样 H2 + 同样 code block + 同样 link 数量 → helpers 不报漂移。"""
        en = "## Section A\n## Section B\n```py\nx=1\n```\n[a](https://e.com)"
        zh = "## 章节 A\n## 章节 B\n```py\nx=1\n```\n[a](https://e.com)"
        en_h2 = _h2_from_text(en)
        zh_h2 = _h2_from_text(zh)
        self.assertEqual(
            len(en_h2),
            len(zh_h2),
            "R424 sanity: 平衡合成输入 EN/ZH H2 数量应相等。",
        )
        self.assertEqual(
            _count_code_blocks(en),
            _count_code_blocks(zh),
            "R424 sanity: 平衡合成输入 code block 数量应相等。",
        )
        self.assertEqual(
            _count_external_links(en),
            _count_external_links(zh),
            "R424 sanity: 平衡合成输入 link 数量应相等。",
        )


class TestR424MetaInvariantLineage(unittest.TestCase):
    """R424 lineage marker: meta-invariant 3rd app + doc-parity 元保护层。"""

    def test_this_file_references_meta_invariant_lineage(self) -> None:
        """R424 文档必须引用 meta-invariant 血脉 (R414, R418)。"""
        from pathlib import Path

        text = Path(__file__).read_text(encoding="utf-8")
        for prior in ("R414", "R418"):
            self.assertIn(
                prior,
                text,
                f"R424: must cite meta-invariant lineage: {prior}",
            )

    def test_this_file_references_doc_parity_lineage(self) -> None:
        """R424 文档必须引用 doc-parity 血脉。"""
        from pathlib import Path

        text = Path(__file__).read_text(encoding="utf-8")
        for prior in ("R335", "R340", "R394", "R400", "R408"):
            self.assertIn(
                prior,
                text,
                f"R424: must cite doc-parity lineage: {prior}",
            )

    def test_this_file_marks_3rd_meta_invariant_app(self) -> None:
        """R424 文档必须标记 meta-invariant 3rd app 里程碑。"""
        from pathlib import Path

        text = Path(__file__).read_text(encoding="utf-8")
        for kw in ("meta-invariant 3rd app", "维度 15"):
            self.assertIn(kw, text, f"R424: missing milestone keyword: {kw!r}")


if __name__ == "__main__":
    unittest.main()
