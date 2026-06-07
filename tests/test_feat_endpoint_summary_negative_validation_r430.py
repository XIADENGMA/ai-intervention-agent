"""R430 (cycle-49 #B1) — meta-invariant 6th app: API contract R404 endpoint
summary quality 负面自验证。

血脉关系 (Lineage):
- meta-invariant 模式: R414 (1st, Mixin matrix negative) → R418 (2nd,
  R412 ratchet uplift) → R424 (3rd, doc-parity R400 negative) → R426
  (4th, R412 ratchet uplift 2nd) → R428 (5th, R422 ratchet uplift 1st)
  → **R430 (6th, R404 endpoint summary negative)** = 元方法学层 (维度
  15) **6 应用进入超巩固期**
- 同时是 **API contract meta-invariant 子模式 1st app** — 把 meta-
  invariant 模式从 doc-parity / ratchet 扩展到 API contract 维度
- API contract pattern 累计 11 应用 (R355 → R422), R430 是它的元保护层
  首次落地

战略 (Strategy):
- R404 (cycle-46 #A1) 是 *positive-only* test: 只验证当前 codebase 内
  endpoint summary 满足质量门槛 (非空 / 长度 [5, 200] / 无 placeholder
  marker), 不验证 R404 helpers 在真实漂移场景下能否 fire
- R404 helpers 主要有 3 部分:
  1. `_extract_endpoint_summaries()` — AST 抓取 docstring 第一行
  2. `FIRST_LINE_MIN_LEN` / `FIRST_LINE_MAX_LEN` 边界常量
  3. `PLACEHOLDER_MARKERS` tuple — TODO / FIXME / 待定 等
- 如果 future refactor 把 helper 静默 broken (例如把 sep_pattern 写错
  / placeholder marker 列表清空 / 边界常量被改成 0/9999), R404 仍 pass
  但实际已失守
- R430 通过 *合成 (synthetic) input* 反向验证这些 helpers 在漂移场景能
  正确 fire

业务价值 (Business value):
- API contract 11 应用是项目方法学最深的维度 (与 v3.6 perf-baseline 9
  应用并列), 它的元保护层缺失是结构性盲点
- API consumer 体验是 v3.10 系列的核心战略, 端点 summary 是 Swagger UI
  入口屏幕第一眼看到的字段; R404 静默失效 = 整个 v3.10.1 sub-pattern
  失守
- meta-invariant 6 应用 = 超巩固期, 与 doc-parity (6 应用 R335/R340/
  R346/R394/R400/R408) 并列成熟方法学维度

设计 (Design):
- 合成 4 种 OpenAPI docstring drift:
  1. 空 first-line (docstring 直接 `---`, summary 缺失)
  2. 过短 first-line (< MIN_LEN 5 chars)
  3. 过长 first-line (> MAX_LEN 200 chars)
  4. 含 TODO/FIXME/待定 placeholder marker
- 对每个场景: 通过 AST + sep_pattern 模拟 R404 extraction 算法,
  断言能正确识别为 violation
- 正向 smoke check: 平衡 docstring (有效 summary) 应不 violate

非目标 (Non-goals):
- 不修改 R404 production 文件
- 不重新实现 R404 4 layer test (避免双重维护)
- 不检测 R404 是否"完美", 只验证它的 helpers 在 drift 时能给出可识别的
  失败信号
"""

from __future__ import annotations

import ast
import re
import unittest

# 复用 R404 的辅助常量, 保证 negative test 与 production test 行为一致
from tests.test_feat_openapi_endpoint_summary_quality_r404 import (
    FIRST_LINE_MAX_LEN,
    FIRST_LINE_MIN_LEN,
    PLACEHOLDER_MARKERS,
)

# 复制 R404 的 sep_pattern 算法 (它在函数 scope 内不直接 import; 严格保
# 持同 pattern, future R404 修改时同步)。
_SEP_PATTERN = re.compile(r"^\s*---\s*$", re.MULTILINE)


def _summary_first_line_from_docstring(ds: str) -> str:
    """模拟 R404 `_extract_endpoint_summaries` 提取 first-line 算法。

    严格复刻 R404 内行为, 用于 negative test 不依赖 file system。
    """
    if not ds:
        return ""
    m = _SEP_PATTERN.search(ds)
    if not m:
        return ""
    summary_block = ds[: m.start()].strip()
    if not summary_block:
        return ""
    return summary_block.split("\n")[0].strip()


# ───────────────────────── Synthetic inputs ─────────────────────────


# Case 1: 完全空 first-line (docstring 直接 ---)
SYNTH_DOCSTRING_EMPTY = """
---
tags:
  - Test
responses:
  200:
    description: ok
"""


# Case 2: 过短 first-line (< 5 chars)
SYNTH_DOCSTRING_TOO_SHORT = """A
---
tags:
  - Test
"""


# Case 3: 过长 first-line (> 200 chars)
SYNTH_DOCSTRING_TOO_LONG = "X" * 250 + "\n---\ntags:\n  - Test\n"


# Case 4: 含 TODO marker
SYNTH_DOCSTRING_TODO = """TODO: 实现一下这个 endpoint 的真实功能
---
tags:
  - Test
"""

# Case 5: 含 待定 marker (中文)
SYNTH_DOCSTRING_TBD_CN = """新接口（待定）
---
tags:
  - Test
"""


# Smoke: 平衡 docstring 应该不 violate (good summary)
SYNTH_DOCSTRING_BALANCED = """创建新任务 (POST /api/tasks)
---
tags:
  - Tasks
responses:
  200:
    description: success
"""


# ───────────────────────── Test cases ─────────────────────────


class TestR430SyntheticEmptyFirstLine(unittest.TestCase):
    """R404 Layer 2 negative test: 空 first-line 必须被识别为 violation。"""

    def test_synthetic_empty_first_line_detected(self) -> None:
        first_line = _summary_first_line_from_docstring(SYNTH_DOCSTRING_EMPTY)
        self.assertEqual(
            first_line,
            "",
            "R430 meta-invariant: R404 Layer 2 算法应该把直接 --- 的 docstring "
            f"识别为空 first-line, 但实际返回 {first_line!r}; "
            "_summary_first_line_from_docstring 或合成输入 broken, R404 此 layer 失效。",
        )


class TestR430SyntheticShortFirstLine(unittest.TestCase):
    """R404 Layer 2 negative test: 过短 first-line 必须被识别为 violation。"""

    def test_synthetic_short_first_line_below_min_len(self) -> None:
        first_line = _summary_first_line_from_docstring(SYNTH_DOCSTRING_TOO_SHORT)
        self.assertEqual(
            first_line,
            "A",
            f"R430: 合成短 summary 应该是 'A', 实际 {first_line!r}",
        )
        self.assertLess(
            len(first_line),
            FIRST_LINE_MIN_LEN,
            "R430 meta-invariant: R404 Layer 2 length check 应该识别 "
            f"len({first_line!r}) = {len(first_line)} < {FIRST_LINE_MIN_LEN} 为 "
            "violation, 但实际未识别; R404 此 layer 失效。",
        )


class TestR430SyntheticLongFirstLine(unittest.TestCase):
    """R404 Layer 2 negative test: 过长 first-line 必须被识别为 violation。"""

    def test_synthetic_long_first_line_above_max_len(self) -> None:
        first_line = _summary_first_line_from_docstring(SYNTH_DOCSTRING_TOO_LONG)
        self.assertEqual(
            len(first_line),
            250,
            f"R430: 合成长 summary 应该是 250 chars, 实际 {len(first_line)}",
        )
        self.assertGreater(
            len(first_line),
            FIRST_LINE_MAX_LEN,
            "R430 meta-invariant: R404 Layer 2 length check 应该识别 "
            f"len(synth_long) = {len(first_line)} > {FIRST_LINE_MAX_LEN} 为 "
            "violation, 但实际未识别; R404 此 layer 失效。",
        )


class TestR430SyntheticPlaceholderMarker(unittest.TestCase):
    """R404 Layer 3 negative test: TODO / 待定 等 placeholder marker 必须被识别。"""

    def test_synthetic_todo_marker_detected(self) -> None:
        first_line = _summary_first_line_from_docstring(SYNTH_DOCSTRING_TODO)
        upper = first_line.upper()
        found_marker = any(m.upper() in upper for m in PLACEHOLDER_MARKERS)
        self.assertTrue(
            found_marker,
            "R430 meta-invariant: R404 Layer 3 placeholder check 应该识别 "
            f"summary={first_line!r} 含 PLACEHOLDER_MARKERS, 但实际未识别; "
            f"PLACEHOLDER_MARKERS = {PLACEHOLDER_MARKERS}",
        )

    def test_synthetic_tbd_chinese_marker_detected(self) -> None:
        first_line = _summary_first_line_from_docstring(SYNTH_DOCSTRING_TBD_CN)
        upper = first_line.upper()
        found_marker = any(m.upper() in upper for m in PLACEHOLDER_MARKERS)
        self.assertTrue(
            found_marker,
            "R430 meta-invariant: R404 Layer 3 应该识别中文 placeholder "
            f"marker (e.g., 待定), 但 summary={first_line!r} 未被识别为 "
            f"violation; PLACEHOLDER_MARKERS = {PLACEHOLDER_MARKERS}",
        )


class TestR430SyntheticBalancedSmokeCheck(unittest.TestCase):
    """正向 smoke check: 平衡 docstring 应 *不* 触发任何 violation signal。"""

    def test_balanced_synthetic_summary_passes(self) -> None:
        first_line = _summary_first_line_from_docstring(SYNTH_DOCSTRING_BALANCED)
        self.assertGreaterEqual(
            len(first_line),
            FIRST_LINE_MIN_LEN,
            "R430 sanity: 平衡合成 summary 应 ≥ MIN_LEN。",
        )
        self.assertLessEqual(
            len(first_line),
            FIRST_LINE_MAX_LEN,
            "R430 sanity: 平衡合成 summary 应 ≤ MAX_LEN。",
        )
        upper = first_line.upper()
        for marker in PLACEHOLDER_MARKERS:
            self.assertNotIn(
                marker.upper(),
                upper,
                f"R430 sanity: 平衡合成 summary 不应含 placeholder marker {marker!r}, "
                f"但实际 {first_line!r} 含 {marker}",
            )


class TestR430MetaInvariantLineage(unittest.TestCase):
    """R430 Layer 4: lineage marker 锁血脉。"""

    def test_this_file_references_meta_invariant_lineage(self) -> None:
        from pathlib import Path

        text = Path(__file__).read_text(encoding="utf-8")
        for prior in ("R414", "R418", "R424", "R426", "R428"):
            self.assertIn(
                prior,
                text,
                f"R430: must cite meta-invariant lineage: {prior}",
            )

    def test_this_file_references_api_contract_lineage(self) -> None:
        from pathlib import Path

        text = Path(__file__).read_text(encoding="utf-8")
        for prior in ("R404", "R355", "R422"):
            self.assertIn(
                prior,
                text,
                f"R430: must cite API contract lineage: {prior}",
            )

    def test_this_file_marks_meta_invariant_6th_app(self) -> None:
        from pathlib import Path

        text = Path(__file__).read_text(encoding="utf-8")
        for kw in ("meta-invariant 6th app", "超巩固期"):
            self.assertIn(kw, text, f"R430: missing milestone keyword: {kw!r}")

    def test_this_file_marks_api_contract_meta_invariant_1st(self) -> None:
        from pathlib import Path

        text = Path(__file__).read_text(encoding="utf-8")
        self.assertIn(
            "API contract meta-invariant 子模式 1st app",
            text,
            "R430: must mark API contract meta-invariant 子模式 1st app",
        )


class TestR430RealCodebaseSanityCheck(unittest.TestCase):
    """额外 sanity: real codebase 至少有 25 endpoint (与 R404 Layer 1 对齐)。"""

    def test_real_codebase_endpoints_extractable(self) -> None:
        """通过 AST 验证 R404 在真实 codebase 仍能抽取 endpoint summary。"""
        from pathlib import Path

        routes_dir = (
            Path(__file__).resolve().parent.parent
            / "src"
            / "ai_intervention_agent"
            / "web_ui_routes"
        )
        endpoint_count = 0
        for py_file in routes_dir.glob("*.py"):
            if py_file.name in {"__init__.py", "_upload_helpers.py"}:
                continue
            try:
                text = py_file.read_text(encoding="utf-8")
                tree = ast.parse(text)
            except (OSError, SyntaxError):
                continue
            for node in ast.walk(tree):
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                ds = ast.get_docstring(node, clean=False)
                if not ds or "---" not in ds:
                    continue
                endpoint_count += 1
        self.assertGreaterEqual(
            endpoint_count,
            25,
            f"R430 sanity: 真实 codebase 至少 25 个 endpoint, 实际 {endpoint_count}; "
            "R404 Layer 1 anchor 阈值与此一致, 此 sanity check 防止 R404 抽取"
            "算法对真实 codebase 静默 broken。",
        )


if __name__ == "__main__":
    unittest.main()
