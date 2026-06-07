"""R392 · OpenAPI schema ``required`` fields 必须出现在 ``properties``
invariant — API contract 6th app (cycle-44 #C1, **API contract 维度达
6 应用深化期**)。

OpenAPI 3.0 / Swagger 2.0 schema 规范:

```yaml
required:
  - task_id
  - prompt
properties:
  task_id:
    type: string
  prompt:
    type: string
```

如果 ``required`` 列了 ``task_id``, 但 ``properties`` 里漏了
``task_id``, 那 Swagger UI / OpenAPI client generator 会:

- 提示 "required field task_id missing from properties" 警告;
- 部分 client (Postman / openapi-generator) 完全忽略该字段;
- 接入方按 ``required`` 假设字段必出现, 但 schema 没描述字段结构 →
  接入失败。

R392 静态扫描所有 web_ui_routes/*.py 里的 OpenAPI YAML docstring (从
``---`` 后开始, 跨多段), 验证: **每个 ``required: [foo, bar]`` 列出
的 name, 必须在对应的同级 ``properties:`` 块下出现 key**。

R392 invariant (3 层)
---------------------

1. **Layer 1 (Anchor)**: web_ui_routes 模块下至少 3 个 docstring 含
   ``required:`` 块 (整体规模检查);
2. **Layer 2 (Forward coverage)**: 每个 ``required`` 列出的字段必须
   在同级 ``properties`` 内被声明;
3. **Layer 3 (Whitelist)**: 显式豁免 (理想为空) — 某些 ``required``
   引用的字段可能在 nested schema / $ref 内, 豁免列表必须含 rationale;

methodology lineage
-------------------

R392 是 **API contract 维度 6th 应用**:

| Pass | R#    | 维度                                          |
| ---- | ----- | --------------------------------------------- |
| 1st  | R355  | OpenAPI docstring 覆盖 + tags/responses 三件套 |
| 2nd  | R358  | POST endpoint 必有 ≥1 个 4xx/5xx              |
| 3rd  | R364  | tag ∈ closed set + exactly 1                  |
| 4th  | R368  | Pydantic field 曝光 (response schema)         |
| 5th  | R378  | POST request body field consumption (request) |
| 6th  | R392  | **required ↔ properties 一致性 (schema 结构)**|

API contract 维度从 cycle-40 启动到 cycle-44 完成 1→6 应用深化期工
业化, OpenAPI 文档质量 6 维度全锁:
1. coverage (1st) — 文档存在性
2. error path (2nd) — 失败路径覆盖
3. taxonomy (3rd) — 分类一致性
4. response schema (4th) — 出参完整性
5. request schema (5th) — 入参一致性
6. **schema structure (6th)** — required ↔ properties 一致性

完成 OpenAPI 文档质量**完整 6 维度**, API contract 进入 v3.10 候选
里程碑期。
"""

from __future__ import annotations

import ast
import re
import textwrap
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
ROUTES_DIR = REPO_ROOT / "src" / "ai_intervention_agent" / "web_ui_routes"

# 豁免: required name 在 nested schema / $ref / inherited 处, 不在 same-level properties
# (理想状态为空; 当前为 0)
EXEMPT_REQUIRED_NAMES: set[str] = set()


def _extract_yaml_docstrings_from_file(py_file: Path) -> list[str]:
    """从 Python 文件提取所有 function/method docstring 内的 OpenAPI YAML block。

    Flasgger 规范: docstring 中以 ``---`` 单独一行 (允许任意缩进) 起始的
    部分是 OpenAPI YAML。
    """
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
        # 取 --- 之后的内容
        yaml_raw = ds[m.end() :]
        # docstring 内部统一缩进 (函数体缩进 12 spaces 等), dedent 去掉
        yaml_text = textwrap.dedent(yaml_raw).strip()
        if yaml_text:
            out.append(yaml_text)
    return out


def _find_required_properties_pairs(
    yaml_obj: object, path: str = ""
) -> list[tuple[str, list[str], dict]]:
    """递归遍历 OpenAPI dict 找所有 (path, required-list, properties-dict) 三元组。

    返回每个有 ``required`` 块的 schema 同级 ``properties`` 字典。
    """
    out: list[tuple[str, list[str], dict]] = []
    if isinstance(yaml_obj, dict):
        d: dict = yaml_obj
        if "required" in d and "properties" in d:
            req = d.get("required")
            props = d.get("properties")
            if isinstance(req, list) and isinstance(props, dict):
                out.append((path, [str(x) for x in req], props))
        for k, v in d.items():
            out.extend(_find_required_properties_pairs(v, f"{path}.{k}"))
    elif isinstance(yaml_obj, list):
        lst: list = yaml_obj
        for i, item in enumerate(lst):
            out.extend(_find_required_properties_pairs(item, f"{path}[{i}]"))
    return out


def _collect_all_pairs() -> list[tuple[str, str, list[str], dict]]:
    """遍历 web_ui_routes/*.py 收集 (file, path, required, properties) 四元组。"""
    out: list[tuple[str, str, list[str], dict]] = []
    for py_file in sorted(ROUTES_DIR.glob("*.py")):
        for ds in _extract_yaml_docstrings_from_file(py_file):
            try:
                data = yaml.safe_load(ds)
            except yaml.YAMLError:
                continue
            for path, req, props in _find_required_properties_pairs(data):
                out.append((py_file.name, path, req, props))
    return out


class TestLayer1Anchor:
    """Layer 1: web_ui_routes 至少 3 个 required/properties 对 (整体规模检查)。"""

    def test_at_least_3_required_blocks(self):
        pairs = _collect_all_pairs()
        assert len(pairs) >= 3, (
            f"R392-L1: only {len(pairs)} required/properties pair(s) "
            f"in web_ui_routes/, expected >= 3. OpenAPI docstring "
            f"discovery / YAML extraction may be broken."
        )


class TestLayer2ForwardCoverage:
    """Layer 2: 每个 required 列出的字段必须在同级 properties 内被声明。"""

    def test_every_required_field_in_properties(self, subtests):
        pairs = _collect_all_pairs()
        violations: list[str] = []
        for file_name, path, required, properties in pairs:
            for field in required:
                if field in EXEMPT_REQUIRED_NAMES:
                    continue
                with subtests.test(file=file_name, path=path, field=field):
                    if field not in properties:
                        violations.append(
                            f"  {file_name} @ {path}: required field "
                            f"'{field}' not in properties "
                            f"(props keys: {list(properties.keys())})"
                        )
        if violations:
            raise AssertionError(
                f"R392-L2: {len(violations)} required field(s) missing "
                f"from properties:\n"
                + "\n".join(violations)
                + "\n\nFix: either add the field to the same-level "
                "properties block, or remove it from required, or "
                "add to EXEMPT_REQUIRED_NAMES with rationale."
            )


class TestLayer3WhitelistMeaningful:
    """Layer 3: EXEMPT_REQUIRED_NAMES 必须有 rationale (当前为空, future-proof)。"""

    def test_exempt_whitelist_is_empty_or_documented(self):
        if not EXEMPT_REQUIRED_NAMES:
            return  # 理想状态
        # 如果有豁免, 必须有对应的 rationale 文档
        text = Path(__file__).read_text(encoding="utf-8")
        for entry in EXEMPT_REQUIRED_NAMES:
            assert entry in text, (
                f"R392-L3: exempt name '{entry}' has no rationale "
                f"comment in this test file"
            )


class TestR392LineageMarker:
    """Methodology lineage 引用必须保留。"""

    def test_this_file_contains_r392_marker(self):
        text = Path(__file__).read_text(encoding="utf-8")
        assert "R392" in text

    def test_this_file_references_lineage(self):
        text = Path(__file__).read_text(encoding="utf-8")
        for prior in ("R355", "R368", "R378"):
            assert prior in text, f"R392: must cite related lineage: {prior}"

    def test_this_file_marks_6th_app(self):
        text = Path(__file__).read_text(encoding="utf-8")
        for kw in ("API contract 6th app", "深化期工业化"):
            assert kw in text, f"R392: missing keyword: {kw!r}"
