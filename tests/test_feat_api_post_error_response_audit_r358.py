"""R358 · POST endpoint error response 覆盖 audit invariant (cycle-41
#A1, **API contract 2nd 应用 — 巩固阶段**)。

R355 (cycle-40) 引入 OpenAPI docstring 三件套 (---/tags:/responses:)
强制覆盖; R358 进一步**深化** API contract — 锁定 POST endpoint 必须
显式文档化 error response (4xx 或 5xx), 因为 POST 路径的 input
validation / auth / state mutation 都是常见失败点。

API contract 应用 lineage
-------------------------

- R355 (cycle-40 #B1): 1st app — OpenAPI 三件套覆盖
- **R358 (本 commit, cycle-41)**: **2nd app 巩固期** — POST 必须有
  error response 文档

R358 invariant (3 层)
---------------------

1. **Layer 1 (Anchor)**: routes/ 内能找到至少 10 个 POST endpoint
2. **Layer 2 (Error response coverage)**: 每个 POST endpoint docstring
   含至少 1 个 4xx 或 5xx response (代表 error path 被显式文档化)
3. **Layer 3 (Whitelist)**: 显式列出**豁免** POST endpoint (e.g.,
   纯触发型 POST 没有任何 error path), whitelist 应该为空 (R358 修复
   让 100% POST 都有 error documentation)

R358 fix
--------

cycle-41 修复 `submit_feedback` (`/api/submit` POST) 缺失 400 / 413 / 429
error response 文档, 添加完整 4 个 status code 文档块 (200 / 400 / 413
/ 429)。

methodology
-----------

R358 与 R322 (v3.8 idempotent contract GET docstring) 同源 — 都是给
endpoint docstring 添加**特定字段**的强制契约, 但 R358 锁的是 **error
path 覆盖**, R322 锁的是 **幂等性声明**。
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ROUTES_DIR = REPO_ROOT / "src" / "ai_intervention_agent" / "web_ui_routes"

# Whitelist: POST endpoints 豁免 error response 强制 (理想空集合)
POST_ERROR_RESPONSE_WHITELIST: dict[str, str] = {
    # (endpoint, reason)
    # 当前空 — R358 让 100% POST 都有 error path 文档
}

# 4xx / 5xx HTTP status code 匹配字符串 (docstring YAML 内会出现的格式)
ERROR_STATUS_PATTERNS = [
    "400:",
    "401:",
    "403:",
    "404:",
    "405:",
    "409:",
    "413:",
    "415:",
    "422:",
    "423:",
    "429:",
    "500:",
    "501:",
    "502:",
    "503:",
    "504:",
    '"400"',
    '"403"',
    '"404"',
    '"500"',
]


def _is_post_endpoint(decorator: ast.expr) -> bool:
    """检查装饰器是否标记 POST methods。"""
    if not isinstance(decorator, ast.Call):
        return False
    func = decorator.func
    if not isinstance(func, ast.Attribute) or func.attr != "route":
        return False
    for kw in decorator.keywords:
        if kw.arg != "methods":
            continue
        if isinstance(kw.value, ast.List):
            for elt in kw.value.elts:
                if isinstance(elt, ast.Constant) and elt.value == "POST":
                    return True
    return False


def _extract_route_path(decorator: ast.expr) -> str | None:
    if not isinstance(decorator, ast.Call):
        return None
    func = decorator.func
    if not isinstance(func, ast.Attribute) or func.attr != "route":
        return None
    if not decorator.args:
        return None
    first = decorator.args[0]
    if (
        isinstance(first, ast.Constant)
        and isinstance(first.value, str)
        and first.value.startswith("/api/")
    ):
        return first.value
    return None


def _collect_post_endpoints() -> list[tuple[str, str, str, str]]:
    """返回 ``[(file, endpoint, fn_name, docstring), ...]`` for POSTs."""
    results: list[tuple[str, str, str, str]] = []
    for py_file in sorted(ROUTES_DIR.glob("*.py")):
        if py_file.name == "__init__.py":
            continue
        tree = ast.parse(py_file.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            endpoint = None
            is_post = False
            for dec in node.decorator_list:
                path = _extract_route_path(dec)
                if path:
                    endpoint = path
                if _is_post_endpoint(dec):
                    is_post = True
            if not is_post or not endpoint:
                continue
            doc = ast.get_docstring(node) or ""
            results.append((py_file.name, endpoint, node.name, doc))
    return results


class TestLayer1Anchor:
    """Layer 1: routes 下至少能找到 10 个 POST endpoint。"""

    def test_at_least_10_post_endpoints(self):
        posts = _collect_post_endpoints()
        assert len(posts) >= 10, (
            f"R358-L1: only {len(posts)} POST endpoints found — "
            f"expected >= 10. AST collector likely broken or codebase "
            f"shrank dramatically."
        )


class TestLayer2PostErrorResponseCoverage:
    """Layer 2: 每个 POST endpoint docstring 含至少 1 个 4xx 或 5xx
    response。"""

    def test_every_post_has_error_response_doc(self, subtests):
        posts = _collect_post_endpoints()
        missing: list[str] = []
        for file, endpoint, fn_name, docstring in posts:
            with subtests.test(file=file, endpoint=endpoint):
                if endpoint in POST_ERROR_RESPONSE_WHITELIST:
                    continue
                has_error = any(pat in docstring for pat in ERROR_STATUS_PATTERNS)
                if not has_error:
                    missing.append(
                        f"  {file}:{fn_name} ({endpoint}): "
                        f"docstring lacks 4xx or 5xx status code"
                    )
        if missing:
            raise AssertionError(
                f"R358-L2: {len(missing)} POST endpoint(s) lack error "
                f"response documentation:\n"
                + "\n".join(missing)
                + "\nFix: add at least one ``4xx:`` or ``5xx:`` block in "
                "docstring ``responses:`` section. POST endpoints have "
                "input validation, auth, state mutation — all common "
                "failure paths must be discoverable via OpenAPI docs."
            )


class TestLayer3WhitelistMustBeEmpty:
    """Layer 3: whitelist 理想为空, 强制 100% POST 都有 error 文档。"""

    def test_whitelist_is_empty(self):
        if POST_ERROR_RESPONSE_WHITELIST:
            raise AssertionError(
                f"R358-L3: POST_ERROR_RESPONSE_WHITELIST has "
                f"{len(POST_ERROR_RESPONSE_WHITELIST)} entries; ideal is "
                f"0. Either fix the endpoint or document persistent "
                f"exemption rationale."
            )


class TestR358LineageMarker:
    def test_this_file_contains_r358_marker(self):
        text = Path(__file__).read_text(encoding="utf-8")
        assert "R358" in text

    def test_this_file_references_r355_lineage(self):
        text = Path(__file__).read_text(encoding="utf-8")
        assert "R355" in text, "R358 must cite R355 (1st app)"

    def test_this_file_marks_second_application(self):
        text = Path(__file__).read_text(encoding="utf-8")
        for kw in ("2nd 应用", "巩固期"):
            assert kw in text, f"R358: missing keyword: {kw!r}"
