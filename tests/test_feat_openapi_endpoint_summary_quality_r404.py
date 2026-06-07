"""R404 · OpenAPI endpoint summary 质量 invariant — API contract 8th app
(cycle-46 #A1, **v3.10.1 OpenAPI 文档质量矩阵首个明确标记应用**)。

OpenAPI 3.0 / Swagger 2.0 在 endpoint 文档质量层面有 4 个核心维度
(coverage / error-path / schema / human-readable). 前 7 应用 (R355 ~ R398)
已覆盖前 3 维度的 7 个子维度, R404 推进到第 4 维度 **human-readable summary
quality**:

- ``summary`` (第一行, flasgger 自动从 docstring 第一行抽取): OpenAPI spec
  规定 "A short summary of what the operation does", **必须单行 ≤ 120 字符**
  (Swagger UI 在 endpoint 列表里只显示这一行, 多行 / 过长会被截断或破版);
- Swagger UI / Redoc / openapi-generator 等工具都依赖 summary 作为 endpoint
  的人类可读标识 (e.g., postman collection imports use summary as request
  name), summary 质量直接影响 API consumer 找接口的效率。

R404 静态扫描 ``web_ui_routes/*.py`` 所有 OpenAPI YAML docstring (flasgger
约定为 docstring 中 ``---`` 之前的内容), 验证每个 endpoint 的 **first line**
(``\n`` 之前的内容):

1. **非空** (strip 后 length ≥ 5);
2. **单行** (first line 是 docstring summary block 的 ``\n`` 之前部分);
3. **长度 [5, 200]** chars (双语友好 200 上限, OpenAPI 标准 120 但中文密
   度更高, 给一些余量);
4. **不包含 TODO / FIXME / XXX 等占位标记** (防 contributor 半成品 summary
   留在 production)。

R404 invariant (4 层)
---------------------

1. **Layer 1 (Anchor)**: web_ui_routes 至少 25 个 endpoint with OpenAPI
   docstring (整体规模 + 防 docstring 抽取 broken);
2. **Layer 2 (Forward coverage)**: 每个 endpoint first-line 非空 + 长度
   [5, 200];
3. **Layer 3 (Quality)**: first-line 不含 TODO/FIXME/XXX 占位标记 (产品质
   量门禁);
4. **Layer 4 (Lineage marker)**: 显式 v3.10.1 标记 + API contract 8th 引用
   前置 lineage。

methodology lineage
-------------------

R404 是 **API contract 8 应用 lineage**, 进入 **v3.10.1 命名启动**:

| Pass | R#    | 维度                                                     |
| ---- | ----- | -------------------------------------------------------- |
| 1st  | R355  | coverage — tags/responses/summary 三件套                  |
| 2nd  | R358  | error path — POST 4xx/5xx                                |
| 3rd  | R364  | taxonomy — tag closed set                                |
| 4th  | R368  | response schema — Pydantic field 曝光                    |
| 5th  | R378  | request schema — parameters ↔ handler                     |
| 6th  | R392  | schema structure — required ↔ properties                  |
| 7th  | R398  | property type completeness — type or ref                  |
| 8th  | R404  | **endpoint summary quality — first-line length & quality** |

8 应用 = **v3.10.1 OpenAPI 文档质量矩阵 representative pattern**, 形成
field-level (R398 type completeness) + endpoint-level (R404 summary quality)
双层保护, 完成 OpenAPI 用户面向文档可读性双层全覆盖。

v3.10 系列定位
-------------

v3.10 系列 = **OpenAPI 文档质量矩阵**:
- v3.10.1: endpoint summary quality (R404, 本)
- v3.10.2 (待定): property description completeness — properties.{name}.description
  覆盖率提升 (当前 36% → 目标 80%+, 需 ~91 propeety 补 description)
- v3.10.3 (待定): error response schema parity — 4xx/5xx 必须有 ``schema``
  字段, 不能只有 ``description``

v3.10 与之前 v3.x 系列的区别:
- v3.6 (perf-baseline): 运行时性能基线
- v3.7 (three-layer consistency / decision): 源/常量/文档一致性
- v3.8 (idempotent / test-isolation): REST 语义 + 测试卫生
- v3.9 (async race contract): 并发原语正确性
- **v3.10 (OpenAPI documentation quality): 用户面向 API 文档质量**

v3.10 第一次把 invariant 焦点放在 **API consumer 用户体验** 上, 之前 v3.x
都聚焦内部代码质量 / 测试质量 / 运行时正确性。
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ROUTES_DIR = REPO_ROOT / "src" / "ai_intervention_agent" / "web_ui_routes"

# first-line 长度边界 (chars):
# - MIN_LEN=5: "创建新任务" 是当前 codebase 最短 (5 chars), 设为下界;
# - MAX_LEN=200: OpenAPI standard 推荐 ~120, 但中文字符密度更高 (一个汉字 ≈
#   3 个英文字符的信息量), 给到 200 chars 保留余量, 避免 future endpoint
#   summary 含双语注解被卡死。
FIRST_LINE_MIN_LEN: int = 5
FIRST_LINE_MAX_LEN: int = 200

# 占位标记 — 半成品 summary 不允许进 production
PLACEHOLDER_MARKERS: tuple[str, ...] = (
    "TODO",
    "FIXME",
    "XXX",
    "TBD",
    "WIP",
    "PLACEHOLDER",
    "待定",
    "待补",
    "待完成",
)

# 豁免 (理想为空; 若有特殊场景 endpoint 需豁免, 在此列表 + rationale)
EXEMPT_ENDPOINTS: set[tuple[str, str]] = set()


def _extract_endpoint_summaries() -> list[tuple[str, str, str]]:
    """收集 (file_name, endpoint_func_name, first_line) 三元组。

    flasgger 约定: function docstring 中 ``---`` 之前的内容是 summary block,
    之后的内容是 OpenAPI YAML body。本函数提取 summary block 的第一行 (``\n``
    之前部分), strip 后返回。
    """
    out: list[tuple[str, str, str]] = []
    sep_pattern = re.compile(r"^\s*---\s*$", re.MULTILINE)
    for py_file in sorted(ROUTES_DIR.glob("*.py")):
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
            if not ds:
                continue
            m = sep_pattern.search(ds)
            if not m:
                continue
            summary_block = ds[: m.start()].strip()
            if not summary_block:
                first_line = ""
            else:
                first_line = summary_block.split("\n")[0].strip()
            out.append((py_file.name, node.name, first_line))
    return out


class TestLayer1Anchor:
    """Layer 1: web_ui_routes 至少 25 个 endpoint with OpenAPI docstring。

    防 docstring 抽取 broken (如 ``---`` 规范变更) 导致 invariant 静默 pass。
    """

    def test_at_least_25_endpoints(self):
        endpoints = _extract_endpoint_summaries()
        assert len(endpoints) >= 25, (
            f"R404-L1: only {len(endpoints)} OpenAPI endpoints found in "
            f"web_ui_routes/, expected >= 25. Docstring extraction may "
            f"be broken (check '---' separator)."
        )


class TestLayer2ForwardCoverage:
    """Layer 2: 每个 endpoint first-line 非空 + 长度 [5, 200]。"""

    def test_every_endpoint_has_non_empty_first_line(self, subtests):
        endpoints = _extract_endpoint_summaries()
        violations: list[str] = []
        for file_name, func_name, first_line in endpoints:
            key = (file_name, func_name)
            if key in EXEMPT_ENDPOINTS:
                continue
            with subtests.test(file=file_name, func=func_name):
                if not first_line:
                    violations.append(f"  {file_name}::{func_name}: empty first line")
        if violations:
            raise AssertionError(
                f"R404-L2-empty: {len(violations)} endpoint(s) with "
                f"empty first-line summary:\n" + "\n".join(violations)
            )

    def test_every_endpoint_first_line_length_in_range(self, subtests):
        endpoints = _extract_endpoint_summaries()
        violations: list[str] = []
        for file_name, func_name, first_line in endpoints:
            key = (file_name, func_name)
            if key in EXEMPT_ENDPOINTS:
                continue
            with subtests.test(file=file_name, func=func_name):
                n = len(first_line)
                if n < FIRST_LINE_MIN_LEN or n > FIRST_LINE_MAX_LEN:
                    violations.append(
                        f"  {file_name}::{func_name} ({n} chars): "
                        f"out of [{FIRST_LINE_MIN_LEN}, {FIRST_LINE_MAX_LEN}]; "
                        f"first_line={first_line!r}"
                    )
        if violations:
            raise AssertionError(
                f"R404-L2-len: {len(violations)} endpoint(s) with first-line "
                f"out of length bounds:\n" + "\n".join(violations)
            )


class TestLayer3Quality:
    """Layer 3: first-line 不含 TODO/FIXME/XXX 占位标记。

    防半成品 summary 留在 production 影响 API consumer 体验。
    """

    def test_no_placeholder_markers_in_first_line(self, subtests):
        endpoints = _extract_endpoint_summaries()
        violations: list[str] = []
        for file_name, func_name, first_line in endpoints:
            key = (file_name, func_name)
            if key in EXEMPT_ENDPOINTS:
                continue
            with subtests.test(file=file_name, func=func_name):
                upper = first_line.upper()
                for marker in PLACEHOLDER_MARKERS:
                    if marker.upper() in upper:
                        violations.append(
                            f"  {file_name}::{func_name}: contains placeholder "
                            f"marker {marker!r}; first_line={first_line!r}"
                        )
                        break
        if violations:
            raise AssertionError(
                f"R404-L3: {len(violations)} endpoint(s) with placeholder "
                f"markers in first-line summary:\n" + "\n".join(violations)
            )


class TestLayer4LineageMarker:
    """Layer 4: methodology lineage 引用必须保留 + v3.10.1 标记。"""

    def test_this_file_contains_r404_marker(self):
        text = Path(__file__).read_text(encoding="utf-8")
        assert "R404" in text

    def test_this_file_references_lineage(self):
        text = Path(__file__).read_text(encoding="utf-8")
        for prior in ("R355", "R378", "R392", "R398"):
            assert prior in text, f"R404: must cite related lineage: {prior}"

    def test_this_file_marks_v3_10_launch(self):
        text = Path(__file__).read_text(encoding="utf-8")
        for kw in ("v3.10.1", "API contract 8", "OpenAPI 文档质量矩阵"):
            assert kw in text, f"R404: missing keyword: {kw!r}"

    def test_exempt_whitelist_documented(self):
        if not EXEMPT_ENDPOINTS:
            return
        text = Path(__file__).read_text(encoding="utf-8")
        for entry in EXEMPT_ENDPOINTS:
            entry_str = f"{entry[0]}::{entry[1]}"
            assert entry_str in text, (
                f"R404-L4: exempt entry {entry_str!r} has no rationale "
                f"comment in this file"
            )
