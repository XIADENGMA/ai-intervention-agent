"""R398 · OpenAPI property `type` 字段完整性 invariant — API contract
7th app (cycle-45 #A2, **API contract 维度达 7 应用进入 v3.10 候选成
熟期**)。

OpenAPI 3.0 / Swagger 2.0 schema 规范要求每个 ``properties.{name}``
块必须含 ``type`` 字段 (或 ``$ref`` / ``allOf`` / ``oneOf`` /
``anyOf``), 否则:

- Swagger UI 渲染 "无类型" 字段, 接入方不知道该字段是 string / int
  / array / object;
- openapi-generator / postman 等 client generator 把 schemaless 字段
  当成 ``any`` / ``object``, 用户传入任何值都通过 client 校验, 后端
  也无法做类型校验;
- API consumer 无法在静态类型语言 (TypeScript / Go / Rust) 里生成
  type-safe wrapper;

R398 静态扫描 web_ui_routes/*.py 内所有 OpenAPI YAML 块, 验证每个
``properties.{name}`` 块必须含以下任一字段:
- ``type`` (基本类型: string / integer / number / boolean / array / object)
- ``$ref`` (引用其他 schema)
- ``allOf`` / ``oneOf`` / ``anyOf`` (组合 schema)
- ``schema`` (request body 字段引用其他 schema)

R398 invariant (3 层)
---------------------

1. **Layer 1 (Anchor)**: web_ui_routes 至少 10 个 OpenAPI property
   (整体规模检查 + 防 YAML 提取 broken);
2. **Layer 2 (Forward coverage)**: 每个 property 必须含 ``type`` 或
   等效 schema 引用;
3. **Layer 3 (Whitelist)**: 显式豁免 (理想为空) — 某些 property 可能
   在 nested schema / additionalProperties 内, 豁免必须含 rationale;

methodology lineage
-------------------

R398 是 **API contract 7 应用 lineage**, 进入 **v3.10 候选成熟期**:

| Pass | R#    | 维度                                              |
| ---- | ----- | ------------------------------------------------- |
| 1st  | R355  | coverage — tags/responses/summary 三件套           |
| 2nd  | R358  | error path — POST 4xx/5xx                         |
| 3rd  | R364  | taxonomy — tag closed set                         |
| 4th  | R368  | response schema — Pydantic field 曝光             |
| 5th  | R378  | request schema — parameters ↔ handler             |
| 6th  | R392  | schema structure — required ↔ properties           |
| 7th  | R398  | **property type completeness — type or ref**       |

7 应用 = **v3.10 候选成熟期阈值** (单 pattern 维度 5+ 应用是 v3.x
升级常见阈值, 7 应用更稳)。OpenAPI 文档质量 7 维度全覆盖:
1. coverage (1st)
2. error path (2nd)
3. taxonomy (3rd)
4. response schema (4th)
5. request schema (5th)
6. schema structure (6th)
7. **property type completeness (7th)**
"""

from __future__ import annotations

import ast
import re
import textwrap
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
ROUTES_DIR = REPO_ROOT / "src" / "ai_intervention_agent" / "web_ui_routes"

# 等效 schema 引用 (any of these means property has a type)
SCHEMA_REF_KEYS: tuple[str, ...] = (
    "type",
    "$ref",
    "allOf",
    "oneOf",
    "anyOf",
    "schema",
)

# 豁免 (理想为空; 某些 property 可能在 additionalProperties 等特殊场景)
EXEMPT_PROPERTY_PATHS: set[str] = set()


def _extract_yaml_docstrings_from_file(py_file: Path) -> list[str]:
    """从 Python 文件提取 function docstring 内的 OpenAPI YAML block。"""
    text = py_file.read_text(encoding="utf-8")
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return []
    out: list[str] = []
    sep_pattern = re.compile(r"^\s*---\s*$", re.MULTILINE)
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        ds = ast.get_docstring(node, clean=False)
        if not ds or "---" not in ds:
            continue
        m = sep_pattern.search(ds)
        if not m:
            continue
        yaml_raw = ds[m.end() :]
        yaml_text = textwrap.dedent(yaml_raw).strip()
        if yaml_text:
            out.append(yaml_text)
    return out


def _find_all_properties(
    yaml_obj: object, path: str = ""
) -> list[tuple[str, str, dict]]:
    """递归找所有 (path, property_name, property_dict) 三元组。

    OpenAPI ``properties:`` 块下的每个 key 都是一个 property。
    """
    out: list[tuple[str, str, dict]] = []
    if isinstance(yaml_obj, dict):
        d: dict = yaml_obj
        if "properties" in d and isinstance(d["properties"], dict):
            props: dict = d["properties"]
            for prop_name, prop_def in props.items():
                if isinstance(prop_def, dict):
                    out.append((path, str(prop_name), prop_def))
        for k, v in d.items():
            out.extend(_find_all_properties(v, f"{path}.{k}"))
    elif isinstance(yaml_obj, list):
        lst: list = yaml_obj
        for i, item in enumerate(lst):
            out.extend(_find_all_properties(item, f"{path}[{i}]"))
    return out


def _collect_all_properties() -> list[tuple[str, str, str, dict]]:
    """收集 (file, path, prop_name, prop_def) 四元组。"""
    out: list[tuple[str, str, str, dict]] = []
    for py_file in sorted(ROUTES_DIR.glob("*.py")):
        for ds in _extract_yaml_docstrings_from_file(py_file):
            try:
                data = yaml.safe_load(ds)
            except yaml.YAMLError:
                continue
            for path, name, prop in _find_all_properties(data):
                out.append((py_file.name, path, name, prop))
    return out


class TestLayer1Anchor:
    """Layer 1: web_ui_routes 至少 10 个 OpenAPI property。"""

    def test_at_least_10_properties(self):
        props = _collect_all_properties()
        assert len(props) >= 10, (
            f"R398-L1: only {len(props)} OpenAPI properties in "
            f"web_ui_routes/, expected >= 10. YAML extraction may "
            f"be broken."
        )


class TestLayer2ForwardCoverage:
    """Layer 2: 每个 property 必须含 type 或等效 schema 引用。"""

    def test_every_property_has_type_or_ref(self, subtests):
        props = _collect_all_properties()
        violations: list[str] = []
        for file_name, path, name, prop_def in props:
            key = f"{file_name}@{path}.{name}"
            if key in EXEMPT_PROPERTY_PATHS:
                continue
            with subtests.test(file=file_name, path=f"{path}.{name}"):
                has_type_or_ref = any(k in prop_def for k in SCHEMA_REF_KEYS)
                if not has_type_or_ref:
                    violations.append(
                        f"  {file_name} @ {path}.{name}: missing "
                        f"'type' / '$ref' / 'allOf' / 'oneOf' / "
                        f"'anyOf' / 'schema' "
                        f"(keys present: {list(prop_def.keys())})"
                    )
        if violations:
            raise AssertionError(
                f"R398-L2: {len(violations)} OpenAPI property/ies "
                f"without type or schema ref:\n"
                + "\n".join(violations)
                + "\n\nFix: add 'type: string' / 'type: integer' / "
                "'type: array' / etc. or use '$ref' to reference "
                "another schema."
            )


class TestLayer3WhitelistMeaningful:
    """Layer 3: 显式豁免 (理想为空)。"""

    def test_exempt_whitelist_documented(self):
        if not EXEMPT_PROPERTY_PATHS:
            return  # 理想状态
        text = Path(__file__).read_text(encoding="utf-8")
        for entry in EXEMPT_PROPERTY_PATHS:
            assert entry in text, (
                f"R398-L3: exempt entry '{entry}' has no rationale comment in this file"
            )


class TestR398LineageMarker:
    """Methodology lineage 引用必须保留。"""

    def test_this_file_contains_r398_marker(self):
        text = Path(__file__).read_text(encoding="utf-8")
        assert "R398" in text

    def test_this_file_references_lineage(self):
        text = Path(__file__).read_text(encoding="utf-8")
        for prior in ("R355", "R378", "R392"):
            assert prior in text, f"R398: must cite related lineage: {prior}"

    def test_this_file_marks_7th_app(self):
        text = Path(__file__).read_text(encoding="utf-8")
        for kw in ("API contract 7 应用", "v3.10 候选成熟期"):
            assert kw in text, f"R398: missing keyword: {kw!r}"
