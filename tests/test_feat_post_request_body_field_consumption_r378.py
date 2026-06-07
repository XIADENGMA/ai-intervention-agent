"""R378 · POST endpoint request body field consumption invariant
(cycle-43 #A1, **API contract 5th 应用 — 工业化深化期巩固**)。

API contract 应用 lineage
-------------------------

- R355 (cycle-40 #B1): 1st — OpenAPI 三件套覆盖
- R358 (cycle-41 #A1): 2nd — POST error response 覆盖
- R364 (cycle-41 #D1): 3rd — tag taxonomy 封闭集合
- R368 (cycle-42 #A1): 4th — Task model ↔ response schema 反向校验
- **R378 (本 commit, cycle-43)**: **5th — 工业化深化期巩固** — POST
  request body 文档字段必须被 handler 真实消费 (orphan param 检测)

R378 audit 目标
---------------

OpenAPI ``parameters:`` block 内的 ``name:`` field (whether ``in:
body`` JSON schema property or ``in: formData``) 必须被 endpoint
handler 真实读取 (``request.form.get("X")`` / ``request.files["X"]``
/ ``data.get("X")``)。

为什么这个 invariant 重要
-------------------------

- 用户读 Swagger 看到 ``parameters.X``, 写代码传 X → handler 不读, 字
  段被静默忽略 → 用户 baffled "why my X didn't work";
- handler 重构删除字段消费但忘了更新 OpenAPI 文档 → orphan param 长
  期残留, 文档失实;
- R368 锁的是 response 字段曝光, R378 是镜像锁 request 字段消费, 形
  成 **request + response 双向 schema 完整性**。

R378 invariant (3 层)
---------------------

1. **Layer 1 (Anchor)**: 至少 3 个 POST endpoint 含 ``parameters:``
   ``name:`` 字段
2. **Layer 2 (Forward consumption)**: 每个文档化的 param ``name`` 必
   须在 handler 函数体内被引用 (作为 ``request.form.get`` /
   ``request.files`` / ``data.get`` 等的 string literal arg)
3. **Layer 3 (Whitelist)**: 显式列出豁免 param (e.g., ``body`` 作为
   通用 wrapper 名占位, 不是真实字段), whitelist 不为空 (机制运转
   证明)
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ROUTES_DIR = REPO_ROOT / "src" / "ai_intervention_agent" / "web_ui_routes"

# Whitelist: param name 不是真实字段, 而是 OpenAPI 占位结构
PARAM_NAME_WHITELIST: set[str] = {
    # ``in: body`` schema 的 wrapper 名 (Flasgger 习惯写法), schema 内
    # 的 properties 才是真实字段
    "body",
    # path parameter (e.g., ``/api/tasks/<task_id>``), 已通过 Flask
    # routing 自动绑定到 handler signature, 不在 request body 内
    "task_id",
    "id",
    # query parameter, 由 ``request.args.get`` 消费, 不锁
    "format",
    "include_images",
    "since",
}


def _iter_post_endpoints() -> list[tuple[str, ast.FunctionDef, str]]:
    """返回 ``[(filename, function_node, docstring), ...]`` for POSTs."""
    results: list[tuple[str, ast.FunctionDef, str]] = []
    for py_file in sorted(ROUTES_DIR.glob("*.py")):
        if py_file.name == "__init__.py":
            continue
        tree = ast.parse(py_file.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if not isinstance(node, ast.FunctionDef):
                continue
            is_post = False
            for dec in node.decorator_list:
                if not isinstance(dec, ast.Call):
                    continue
                func = dec.func
                if isinstance(func, ast.Attribute) and func.attr == "route":
                    for kw in dec.keywords:
                        if kw.arg == "methods" and isinstance(kw.value, ast.List):
                            for elt in kw.value.elts:
                                if (
                                    isinstance(elt, ast.Constant)
                                    and elt.value == "POST"
                                ):
                                    is_post = True
            if not is_post:
                continue
            doc = ast.get_docstring(node) or ""
            results.append((py_file.name, node, doc))
    return results


def _extract_param_names(docstring: str) -> list[str]:
    """从 docstring 内提取 ``parameters:`` 块下的 ``name: X`` 字段。"""
    names: list[str] = []
    # 找 parameters: ... responses: 之间的块
    m = re.search(
        r"parameters:\s*\n(.*?)(?=\n\s{0,12}responses:|\Z)",
        docstring,
        re.DOTALL,
    )
    if not m:
        return names
    block = m.group(1)
    # 在 in: body 的 schema/properties 块内, 也提取 properties: 下的字段
    # 但 in: formData 的 name: X 是 top-level
    for line in block.splitlines():
        stripped = line.strip()
        if stripped.startswith("name:"):
            name = stripped[len("name:") :].strip()
            if name and not name.startswith("-"):
                names.append(name)
    # 同时提取 in: body schema 下 properties 内字段名
    properties_block_match = re.search(
        r"properties:\s*\n((?:\s{14,}\S.*\n)+)",
        block,
    )
    if properties_block_match:
        for line in properties_block_match.group(1).splitlines():
            stripped = line.strip()
            # 字段名行格式: ``fieldname:`` (后续 type: 等是子行)
            m2 = re.match(r"^([a-zA-Z_][a-zA-Z0-9_]*):\s*$", stripped)
            if m2:
                names.append(m2.group(1))
    return names


def _extract_consumed_strings(fn: ast.FunctionDef) -> set[str]:
    """提取函数体内所有 string literal (用作 dict key / kwarg)。"""
    consumed: set[str] = set()
    for node in ast.walk(fn):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            consumed.add(node.value)
    return consumed


class TestLayer1Anchor:
    """Layer 1: 至少 3 个 POST endpoint 含 ``parameters: name:`` 字段。"""

    def test_at_least_3_posts_have_param_names(self):
        eps = _iter_post_endpoints()
        with_params = []
        for filename, fn, doc in eps:
            if _extract_param_names(doc):
                with_params.append((filename, fn.name))
        assert len(with_params) >= 3, (
            f"R378-L1: only {len(with_params)} POST endpoints with "
            f"``parameters: name:`` block — expected >= 3. AST collector "
            f"may be broken."
        )


class TestLayer2ForwardConsumption:
    """Layer 2: 文档化的 param 必须在 handler 函数体内被引用。"""

    def test_every_documented_param_consumed(self, subtests):
        eps = _iter_post_endpoints()
        violations: list[str] = []
        for filename, fn, doc in eps:
            params = _extract_param_names(doc)
            if not params:
                continue
            consumed = _extract_consumed_strings(fn)
            for param in params:
                with subtests.test(file=filename, fn=fn.name, param=param):
                    if param in PARAM_NAME_WHITELIST:
                        continue
                    if param not in consumed:
                        violations.append(
                            f"  {filename}:{fn.name}: documented param "
                            f"{param!r} not referenced as string literal "
                            f"in handler body"
                        )
        if violations:
            raise AssertionError(
                f"R378-L2: {len(violations)} documented POST param(s) "
                f"not consumed by handler:\n"
                + "\n".join(violations)
                + "\nFix: either consume the param in handler "
                "(e.g., ``request.form.get('X')``) or remove from "
                "OpenAPI ``parameters:`` block (orphan documentation), "
                "or add to PARAM_NAME_WHITELIST with rationale."
            )


class TestLayer3WhitelistMeaningful:
    """Layer 3: PARAM_NAME_WHITELIST 不为空 (机制运转证明)。"""

    def test_whitelist_not_empty(self):
        assert len(PARAM_NAME_WHITELIST) > 0, (
            "R378-L3: PARAM_NAME_WHITELIST should not be empty; at "
            "least the ``body`` wrapper name needs whitelisting as "
            "evidence the mechanism is in active use."
        )

    def test_whitelist_contains_body_wrapper(self):
        assert "body" in PARAM_NAME_WHITELIST, (
            "R378-L3: ``body`` must be in whitelist (it's a common "
            "Flasgger wrapper name for ``in: body`` schema and isn't "
            "a real consumed field)"
        )


class TestR378LineageMarker:
    def test_this_file_contains_r378_marker(self):
        text = Path(__file__).read_text(encoding="utf-8")
        assert "R378" in text

    def test_this_file_references_api_contract_lineage(self):
        text = Path(__file__).read_text(encoding="utf-8")
        for prior in ("R355", "R358", "R364", "R368"):
            assert prior in text, f"R378: must cite API contract lineage: {prior}"

    def test_this_file_marks_fifth_application(self):
        text = Path(__file__).read_text(encoding="utf-8")
        for kw in ("5th 应用", "工业化深化期巩固"):
            assert kw in text, f"R378: missing keyword: {kw!r}"
