"""R355 · API endpoint OpenAPI docstring 覆盖 audit invariant (cycle-40
#B1, **API contract 新维度**)。

R355 audit 目标
---------------

项目所有 ``@self.app.route("/api/...", methods=[...])`` 装饰的 endpoint
函数的 docstring 必须包含 OpenAPI/Swagger schema 注解:

- ``---`` 分隔符 (YAML front-matter 起点)
- ``tags:`` (endpoint 归属分类, 用于 Swagger UI 分组)
- ``responses:`` (返回值 schema, 用于 client 代码生成 / API 文档)

为什么这个 invariant 重要
-------------------------

1. **API 文档完整性**: 项目用 Flasgger 自动从 docstring 生成 Swagger UI;
   缺失 OpenAPI 注解的 endpoint 在 Swagger 上是 "黑洞", 用户看不到
   schema, 也无法用 codegen 工具 (e.g., OpenAPI Generator) 派生
   client SDK
2. **前端契约**: VSCode extension + browser JS 调用这些 endpoint, 没有
   schema 注解, 跨语言 / 跨版本调试时只能靠源码翻阅
3. **预防性 future-guard**: 新增 endpoint 时, 测试会强制开发者写文档,
   防止 "先 ship API, 文档 later" 的退化

R355 audit 范围
---------------

扫描 ``src/ai_intervention_agent/web_ui_routes/`` 下所有 ``@self.app.
route("/api/...", methods=[...])`` 装饰 + 紧跟的 ``def func():`` +
docstring, 检查 3 个 OpenAPI 关键字。

R355 invariant (3 层)
---------------------

1. **Layer 1 (Anchor)**: ``web_ui_routes/`` 目录存在 + 至少含 4 个 route
   文件 (feedback / task / system / notification)
2. **Layer 2 (OpenAPI coverage)**: 每个 ``/api/...`` endpoint docstring
   都含 ``---`` / ``tags:`` / ``responses:`` 三件套
3. **Layer 3 (Whitelist)**: 显式列出**豁免** endpoint (如有, 含理由),
   且 whitelist 应该为空 (R355 fix 让 100% 覆盖)

methodology lineage
-------------------

R355 是 API contract 新维度首次 invariant, 与:
- v3.6 perf-baseline (R348 HTTP endpoint)
- v3.7 决策三层 (R317/R321/R323)
- v3.8 idempotent contract (R322 GET docstring)
- v3.9 async race contract (R326-R342)

并列为可复用方法论。R355 强调 **API contract documentation completeness**,
不同于 idempotent contract (强调单一字段, R322/R313/R318); R355 强制
**整个 API documentation 套件** 完整。
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ROUTES_DIR = REPO_ROOT / "src" / "ai_intervention_agent" / "web_ui_routes"

# Whitelist: endpoints 豁免 OpenAPI 注解的合理原因 (理想情况是空集合)
DOCSTRING_WHITELIST: dict[str, str] = {
    # (endpoint, reason)
    # 当前为空 — R355 让 100% endpoint 都有完整 OpenAPI 注解
}


def _extract_route_path(decorator: ast.expr) -> str | None:
    """从 ``@self.app.route("/api/...", methods=[...])`` 装饰器 AST 节点
    抽取 endpoint 字符串。返回 ``None`` 如果不是 route 装饰器。"""
    if not isinstance(decorator, ast.Call):
        return None
    func = decorator.func
    if not isinstance(func, ast.Attribute):
        return None
    if func.attr != "route":
        return None
    if not decorator.args:
        return None
    first_arg = decorator.args[0]
    if not isinstance(first_arg, ast.Constant):
        return None
    if not isinstance(first_arg.value, str):
        return None
    if not first_arg.value.startswith("/api/"):
        return None
    return first_arg.value


def _collect_endpoints() -> list[tuple[str, str, str, str]]:
    """返回 ``[(file, endpoint, fn_name, docstring), ...]`` via AST walk."""
    results: list[tuple[str, str, str, str]] = []
    for py_file in sorted(ROUTES_DIR.glob("*.py")):
        if py_file.name == "__init__.py":
            continue
        tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for dec in node.decorator_list:
                path = _extract_route_path(dec)
                if path is None:
                    continue
                doc = ast.get_docstring(node) or ""
                results.append((py_file.name, path, node.name, doc))
                break
    return results


class TestLayer1AnchorRoutesDirAndFiles:
    """Layer 1: routes 目录 + 4 个 route 文件存在。"""

    def test_routes_dir_exists(self):
        assert ROUTES_DIR.is_dir()

    def test_four_route_files_present(self):
        names = {p.name for p in ROUTES_DIR.glob("*.py")}
        for required in ("feedback.py", "task.py", "system.py", "notification.py"):
            assert required in names, f"R355-L1: missing {required}"


class TestLayer2OpenAPICoverage:
    """Layer 2: 每个 endpoint docstring 含 OpenAPI 三件套。"""

    def test_every_endpoint_has_openapi_docs(self, subtests):
        endpoints = _collect_endpoints()
        assert len(endpoints) >= 20, (
            f"R355-L2: route regex only matched {len(endpoints)} endpoints "
            f"— expected >= 20. Regex likely broken."
        )
        missing: list[str] = []
        for file, endpoint, fn_name, docstring in endpoints:
            with subtests.test(file=file, endpoint=endpoint):
                if endpoint in DOCSTRING_WHITELIST:
                    continue
                violations: list[str] = []
                if "---" not in docstring:
                    violations.append("missing ``---`` YAML separator")
                if "tags:" not in docstring:
                    violations.append("missing ``tags:`` field")
                if "responses:" not in docstring:
                    violations.append("missing ``responses:`` field")
                if violations:
                    missing.append(
                        f"  {file}:{fn_name} ({endpoint}): " + ", ".join(violations)
                    )
        if missing:
            raise AssertionError(
                f"R355-L2: {len(missing)} endpoint(s) lack OpenAPI "
                f"docstring annotations:\n"
                + "\n".join(missing)
                + "\nFix: add ``---\\ntags:\\n  - Group\\nresponses:\\n  "
                "200:\\n    description: ...\\n    schema: ...`` block "
                "to docstring (Flasgger picks this up to generate "
                "Swagger UI)."
            )


class TestLayer3WhitelistMustBeEmpty:
    """Layer 3: 理想情况是 whitelist 为空, 强制 100% endpoint 都有完整
    OpenAPI 文档。"""

    def test_whitelist_is_empty(self):
        if DOCSTRING_WHITELIST:
            raise AssertionError(
                f"R355-L3: DOCSTRING_WHITELIST has {len(DOCSTRING_WHITELIST)} "
                f"entries; ideal is 0. Either fix the endpoints to add "
                f"OpenAPI docstring annotations or document why a "
                f"persistent exemption is justified.\n"
                f"Current whitelist: {DOCSTRING_WHITELIST}"
            )


class TestR355LineageMarker:
    def test_this_file_contains_r355_marker(self):
        text = Path(__file__).read_text(encoding="utf-8")
        assert "R355" in text

    def test_this_file_marks_api_contract_dimension(self):
        text = Path(__file__).read_text(encoding="utf-8")
        for kw in ("API contract", "OpenAPI", "Swagger", "Flasgger"):
            assert kw in text, f"R355: missing keyword: {kw!r}"

    def test_this_file_references_idempotent_lineage(self):
        text = Path(__file__).read_text(encoding="utf-8")
        for prior in ("R322", "R313", "R318"):
            assert prior in text, (
                f"R355: must cite idempotent contract lineage: {prior}"
            )
