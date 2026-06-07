"""R364 · API tag taxonomy closed-set invariant (cycle-41 #D1, **API
contract 3rd 应用 — 工业化深化期**)。

R355 (cycle-40) 强制 OpenAPI 三件套覆盖, R358 (cycle-41) 强制 POST
error response 文档, **R364 强制 endpoint tag 必须来自封闭集合** +
**每个 endpoint exactly 1 tag**。

为什么这个 invariant 重要
-------------------------

Swagger UI 用 ``tags:`` 字段把 endpoint 分组展示。如果某个开发者:

- 写 ``- system`` (小写) 而非 ``- System`` → Swagger 出现 2 个 "System"
  group, endpoint 散落看不全;
- 写 ``- Misc`` 新 tag → 之后人人随便加新 tag, 一年后 30 个 tag,
  几乎无分组;
- 漏写 tag → endpoint 进入 "default" group, 文档 UX 差;
- 写多个 tag → endpoint 重复出现在 UI 多个 group, 用户找不到主分类。

R364 把 tag 锁在 ``{Feedback, Notification, System, Tasks}`` 封闭集合,
强制 endpoint exactly 1 tag, 让 Swagger UI 永远保持 4 个清晰分组。

API contract 应用 lineage
-------------------------

- R355 (cycle-40 #B1): 1st app — OpenAPI 三件套覆盖
- R358 (cycle-41 #A1): 2nd app — POST error response 覆盖
- **R364 (本 commit, cycle-41)**: **3rd app 工业化深化期** — tag
  taxonomy 封闭集合 + exactly 1 tag

R364 invariant (3 层)
---------------------

1. **Layer 1 (Anchor)**: 至少 20 个 endpoint 含 tags 块
2. **Layer 2 (Closed set)**: 每个 endpoint tag 必须 ∈
   ``{Feedback, Notification, System, Tasks}``
3. **Layer 3 (Exactly 1)**: 每个 endpoint 必须 exactly 1 tag (不能 0,
   不能 2+)
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ROUTES_DIR = REPO_ROOT / "src" / "ai_intervention_agent" / "web_ui_routes"

ALLOWED_TAGS = frozenset({"Feedback", "Notification", "System", "Tasks"})

# regex 提取 docstring 内 tags: 后跟随的 - 列表
TAG_BLOCK_PATTERN = re.compile(r"tags:\s*\n((?:\s+-\s+\S+\s*\n)+)", re.MULTILINE)


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


def _collect_endpoints_with_tags() -> list[tuple[str, str, str, list[str]]]:
    """返回 [(file, endpoint, fn_name, tags), ...]."""
    results: list[tuple[str, str, str, list[str]]] = []
    for py_file in sorted(ROUTES_DIR.glob("*.py")):
        if py_file.name == "__init__.py":
            continue
        tree = ast.parse(py_file.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            endpoint = None
            for dec in node.decorator_list:
                path = _extract_route_path(dec)
                if path:
                    endpoint = path
                    break
            if not endpoint:
                continue
            doc = ast.get_docstring(node) or ""
            tags = _extract_tags(doc)
            results.append((py_file.name, endpoint, node.name, tags))
    return results


def _extract_tags(docstring: str) -> list[str]:
    """从 docstring 内提取 ``tags:`` 块下的 - 列表项。"""
    match = TAG_BLOCK_PATTERN.search(docstring)
    if not match:
        return []
    block = match.group(1)
    tags = []
    for line in block.splitlines():
        s = line.strip()
        if s.startswith("- "):
            tags.append(s[2:].strip())
    return tags


class TestLayer1Anchor:
    """Layer 1: 至少 20 个 endpoint 含 tags 块。"""

    def test_at_least_20_endpoints_have_tags(self):
        eps = _collect_endpoints_with_tags()
        with_tags = [e for e in eps if e[3]]
        assert len(with_tags) >= 20, (
            f"R364-L1: only {len(with_tags)} endpoints with tags found "
            f"(total {len(eps)} endpoints). Expected >= 20. Either AST "
            f"parser broken or tag coverage collapsed."
        )


class TestLayer2ClosedSet:
    """Layer 2: 每个 tag 必须 ∈ {Feedback, Notification, System, Tasks}。"""

    def test_every_tag_in_allowed_set(self, subtests):
        eps = _collect_endpoints_with_tags()
        violations: list[str] = []
        for file, endpoint, fn_name, tags in eps:
            for tag in tags:
                with subtests.test(file=file, endpoint=endpoint, tag=tag):
                    if tag not in ALLOWED_TAGS:
                        violations.append(
                            f"  {file}:{fn_name} ({endpoint}): tag "
                            f"{tag!r} not in {sorted(ALLOWED_TAGS)}"
                        )
        if violations:
            raise AssertionError(
                f"R364-L2: {len(violations)} tag violation(s) in API "
                f"docstring:\n"
                + "\n".join(violations)
                + f"\nFix: change to one of {sorted(ALLOWED_TAGS)}. "
                f"If you genuinely need a new taxonomy group, update "
                f"ALLOWED_TAGS in this test with rationale."
            )


class TestLayer3ExactlyOneTag:
    """Layer 3: 每个 endpoint 必须 exactly 1 tag。"""

    def test_every_endpoint_has_exactly_one_tag(self, subtests):
        eps = _collect_endpoints_with_tags()
        violations: list[str] = []
        for file, endpoint, fn_name, tags in eps:
            with subtests.test(file=file, endpoint=endpoint):
                if len(tags) != 1:
                    violations.append(
                        f"  {file}:{fn_name} ({endpoint}): "
                        f"{len(tags)} tags (expected exactly 1) — {tags}"
                    )
        if violations:
            raise AssertionError(
                f"R364-L3: {len(violations)} endpoint(s) have wrong tag "
                f"count:\n"
                + "\n".join(violations)
                + "\nFix: each endpoint must have exactly 1 ``- TagName`` "
                "under ``tags:``. Multiple tags → endpoint appears in "
                "multiple Swagger groups (confusing UX)."
            )


class TestR364LineageMarker:
    def test_this_file_contains_r364_marker(self):
        text = Path(__file__).read_text(encoding="utf-8")
        assert "R364" in text

    def test_this_file_references_api_contract_lineage(self):
        text = Path(__file__).read_text(encoding="utf-8")
        for prior in ("R355", "R358"):
            assert prior in text, f"R364: must cite API contract lineage: {prior}"

    def test_this_file_marks_third_application(self):
        text = Path(__file__).read_text(encoding="utf-8")
        for kw in ("3rd 应用", "工业化深化期"):
            assert kw in text, f"R364: missing keyword: {kw!r}"
