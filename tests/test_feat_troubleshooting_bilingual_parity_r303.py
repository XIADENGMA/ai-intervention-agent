"""R303: docs/troubleshooting 双语 parity invariant (cycle-30 t30-3)。

cr59 §5 #B 推荐 "docs/troubleshooting 双语 parity invariant" 应对
docs drift 风险 (en 535 行 vs zh-CN 479 行 ~10% 差异隐患)。

cycle-22 cr46 教训: 单语改动滑漏 6 个月。R288 / R300 已经锁定了 README
双语 parity, **troubleshooting docs 仍未锁定**。R303 补齐这层。

================================================================
| 维度                                                | tests |
|---------------------------------------------------|-------|
| 1. H2 数量必须相同 (en vs zh-CN)                     | 1     |
| 2. H2 编号必须 1-13 + 结尾 1 个 (en + zh 各)         | 2     |
| 3. H3 数量必须相同 (en vs zh-CN)                     | 1     |
| 4. 关键章节存在性 (双语 parity, 13 个编号 H2)        | 13    |
| 5. 结尾"Still stuck"章节存在 (双语 parity)           | 2     |
| 6. 文档行数差距不能超过 30% (容许翻译伸缩)           | 1     |
================================================================
| 合计                                                | 20    |
================================================================

**pattern lineage**: R288 (sequence diagram parity), R300 (component
diagram parity) 都是 *可视化层* 的双语 parity, R303 是 *纯文本层* 的
双语 parity。三者共同形成 **docs bilingual parity invariant family**
(v3.6 methodology pattern #4 visual-architecture invariant 的纯文本
扩展)。
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
EN_PATH = PROJECT_ROOT / "docs" / "troubleshooting.md"
ZH_PATH = PROJECT_ROOT / "docs" / "troubleshooting.zh-CN.md"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def _extract_h2_titles(content: str) -> list[str]:
    """提取所有 H2 标题文本 (去掉前缀 `## `)。"""
    return [
        m.group(1).strip() for m in re.finditer(r"^##\s+(.+)$", content, re.MULTILINE)
    ]


def _extract_h3_titles(content: str) -> list[str]:
    return [
        m.group(1).strip() for m in re.finditer(r"^###\s+(.+)$", content, re.MULTILINE)
    ]


def _extract_numbered_h2(content: str) -> list[int]:
    """提取所有 H2 中以数字开头的章节编号。"""
    nums: list[int] = []
    for m in re.finditer(r"^##\s+(\d+)\.\s", content, re.MULTILINE):
        nums.append(int(m.group(1)))
    return nums


# ============================================================
# #1 + #3: H2 / H3 数量必须相同
# ============================================================
class TestHeadingCountParity(unittest.TestCase):
    def test_h2_count_same(self) -> None:
        en_h2 = _extract_h2_titles(_read(EN_PATH))
        zh_h2 = _extract_h2_titles(_read(ZH_PATH))
        self.assertEqual(
            len(en_h2),
            len(zh_h2),
            f"R303: troubleshooting H2 count 不一致 (en {len(en_h2)} vs "
            f"zh-CN {len(zh_h2)}) — 检查单语漏译/漏更新\n"
            f"en: {en_h2}\nzh: {zh_h2}",
        )

    def test_h3_count_same(self) -> None:
        en_h3 = _extract_h3_titles(_read(EN_PATH))
        zh_h3 = _extract_h3_titles(_read(ZH_PATH))
        self.assertEqual(
            len(en_h3),
            len(zh_h3),
            f"R303: troubleshooting H3 count 不一致 (en {len(en_h3)} vs "
            f"zh-CN {len(zh_h3)})\nen: {en_h3}\nzh: {zh_h3}",
        )


# ============================================================
# #2: H2 编号必须 1-13
# ============================================================
class TestH2NumberingParity(unittest.TestCase):
    EXPECTED_NUMBERS = list(range(1, 14))  # 1..13

    def test_en_h2_numbered_1_to_13(self) -> None:
        nums = _extract_numbered_h2(_read(EN_PATH))
        self.assertEqual(
            nums,
            self.EXPECTED_NUMBERS,
            f"R303: en docs H2 编号 drift, 期望 {self.EXPECTED_NUMBERS}, "
            f"实际 {nums} — 新增章节请按顺序编号, 不要跳号",
        )

    def test_zh_h2_numbered_1_to_13(self) -> None:
        nums = _extract_numbered_h2(_read(ZH_PATH))
        self.assertEqual(
            nums,
            self.EXPECTED_NUMBERS,
            f"R303: zh-CN docs H2 编号 drift, 期望 {self.EXPECTED_NUMBERS}, "
            f"实际 {nums}",
        )


# ============================================================
# #4: 关键章节存在性 (13 个编号 H2)
#    每个章节作单独 test 便于失败定位
# ============================================================
class TestNumberedSectionsExist(unittest.TestCase):
    """13 个编号章节, 双语必须都存在 (各按主题关键字检测)"""

    # (英文关键字, 中文关键字, 章节号) — 主题词必须在对应章节标题中出现
    SECTION_KEYWORDS = [
        (1, "Web UI does not start", "Web UI 启动失败"),
        (2, "VS Code panel is blank", "VS Code 面板空白"),
        (3, "Task list is empty", "AI 调用了"),
        (4, "No notifications", "通知没响"),
        (5, "mDNS", "mDNS"),
        (6, "Open in IDE", "Open in IDE"),
        (7, "PWA", "PWA"),
        (8, "Bark notification", "Bark 通知"),
        (9, "CI Gate", "CI Gate"),
        (10, "Dependency Review", "Dependency Review"),
        (11, "Extension host terminated", "Extension host terminated"),
        (12, "Open VSX publish", "Open VSX 发布"),
        (13, "Backend `/api/system/", "后端 `/api/system/"),
    ]

    def test_all_13_sections_exist(self) -> None:
        en = _read(EN_PATH)
        zh = _read(ZH_PATH)
        for num, en_key, zh_key in self.SECTION_KEYWORDS:
            with self.subTest(section=num, language="en"):
                m = re.search(
                    rf"^##\s+{num}\.\s+.*{re.escape(en_key)}",
                    en,
                    re.MULTILINE,
                )
                self.assertIsNotNone(m, f"R303: en docs 缺少 章节 {num} 含 {en_key!r}")
            with self.subTest(section=num, language="zh-CN"):
                m = re.search(
                    rf"^##\s+{num}\.\s+.*{re.escape(zh_key)}",
                    zh,
                    re.MULTILINE,
                )
                self.assertIsNotNone(
                    m, f"R303: zh-CN docs 缺少 章节 {num} 含 {zh_key!r}"
                )


# ============================================================
# #5: 结尾"Still stuck"章节存在
# ============================================================
class TestStillStuckSectionPresent(unittest.TestCase):
    def test_en_has_still_stuck(self) -> None:
        en = _read(EN_PATH)
        m = re.search(r"^##\s+Still stuck", en, re.MULTILINE)
        self.assertIsNotNone(m, "R303: en docs 必须有结尾 ## Still stuck? 章节")

    def test_zh_has_still_stuck(self) -> None:
        zh = _read(ZH_PATH)
        m = re.search(r"^##\s+还是没解决", zh, re.MULTILINE)
        self.assertIsNotNone(m, "R303: zh-CN docs 必须有结尾 ## 还是没解决？ 章节")


# ============================================================
# #6: 文档行数差距不能超过 30%
#    中英行数会有自然差异（中文紧凑 / 标点不同 / 翻译伸缩）
#    但 30% 是经验阈值，>= 30% 通常意味着单语漏更新
# ============================================================
class TestLineCountSanity(unittest.TestCase):
    MAX_LINE_DIFF_RATIO = 0.30

    def test_line_counts_within_30_percent(self) -> None:
        en_lines = len(_read(EN_PATH).splitlines())
        zh_lines = len(_read(ZH_PATH).splitlines())
        max_lines = max(en_lines, zh_lines)
        min_lines = min(en_lines, zh_lines)
        ratio = (max_lines - min_lines) / max_lines
        self.assertLessEqual(
            ratio,
            self.MAX_LINE_DIFF_RATIO,
            f"R303: docs/troubleshooting 双语行数差距 {ratio:.1%} > "
            f"{self.MAX_LINE_DIFF_RATIO:.0%} 阈值 (en {en_lines} 行 vs "
            f"zh {zh_lines} 行) — 单语可能漏更新, 检查最近 5 个 commit",
        )


if __name__ == "__main__":
    unittest.main()
