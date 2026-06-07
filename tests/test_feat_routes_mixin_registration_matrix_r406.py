"""R406 · Flask Mixin route registration matrix invariant — 第 14 个方法学
维度首次落地 (cycle-46 #B1)。

ai-intervention-agent 采用 Mixin-based route 组织 (而非 Flask blueprint),
所有 web routes 由 5 个 Mixin 类 (TaskRoutesMixin / FeedbackRoutesMixin /
NotificationRoutesMixin / StaticRoutesMixin / SystemRoutesMixin) 通过多重
继承组合到 ``WebFeedbackUI``, 每个 Mixin 提供一个 ``_setup_<name>_routes(self)``
方法, ``WebFeedbackUI.setup_routes`` 显式调用所有 5 个 setup 方法。

这种架构有 3 个 silent failure 风险:

1. **Orphan setup method** — 新增 Mixin 但忘记在 ``__all__`` 注册;
2. **Orphan __all__ entry** — ``__all__`` 列出 Mixin 但 ``WebFeedbackUI``
   父类列表里漏继承, 或 setup 方法漏调用;
3. **Drift between __all__ / parent classes / setup calls 三方** — 三个清单
   逐渐 drift, 导致某些 route 注册 / 某些不注册, 出现 404 静默失败 (route
   handler 写了但 Flask 不知道, 用户访问会得到 404);

R406 锁这 3 个清单的**完全一致性**:

- ``web_ui_routes/__init__.py:__all__`` (declared Mixin export 列表)
- ``WebFeedbackUI`` 的 ``...RoutesMixin`` 父类 (实际 inherit 链)
- ``WebFeedbackUI.setup_routes`` 的 ``self._setup_X_routes()`` 调用清单
- 每个 Mixin 文件实际定义的 ``def _setup_X_routes`` 方法

四方一致性 (4-way consistency lock):

```
__all__ ⊆ parent_classes
parent_classes ⊆ __all__
setup_calls ⊆ {_setup_X for X in __all__ 去掉 "RoutesMixin"}
each Mixin file defines exactly its declared setup method
```

R406 invariant (4 层)
---------------------

1. **Layer 1 (Anchor)**: ``web_ui_routes/__init__.py`` 至少 5 个 Mixin 在
   ``__all__`` (防 __init__.py broken);
2. **Layer 2 (__all__ ↔ parent class consistency)**: ``__all__`` 中每个
   ``...RoutesMixin`` 都必须出现在 ``WebFeedbackUI`` 的父类列表;
3. **Layer 3 (setup_calls ↔ method existence)**: ``setup_routes`` 调用的
   每个 ``self._setup_X_routes()`` 都必须有对应 Mixin 文件定义该方法;
4. **Layer 4 (no orphan setup methods)**: 每个 Mixin 文件定义的
   ``_setup_<name>_routes`` 方法都必须被 ``setup_routes`` 调用 (防 dead code)。

methodology lineage
-------------------

R406 是 **第 14 个方法学维度**首次落地, 与之前 13 个维度并行运转:

| 维度                                  | 首次 R# | 应用数 |
| ------------------------------------- | ------- | ------ |
| v3.6 perf-baseline                    | R232    | 9      |
| v3.7 three-layer consistency          | R311    | 3      |
| v3.7 decision-three-layer             | R314    | 4      |
| v3.8 idempotent contract              | R313    | 3      |
| v3.8 test-isolation                   | R316    | 6      |
| v3.9 async race contract              | R326    | 6      |
| doc-parity                            | R335    | 5      |
| JS event listener audit               | -       | 3      |
| cross-language schema                 | -       | 4      |
| visual-architecture                   | R311    | 3      |
| config 默认值漂移防护                  | -       | 2      |
| i18n consistency                      | R350    | 4      |
| v3.10 API contract (OpenAPI quality)  | R355    | 8      |
| Pydantic field validator coverage     | R380    | 5      |
| **route registration matrix** (本)     | **R406** | **1**  |

R406 价值
--------

R406 防御的真实失败场景:

1. **重构 web_ui.py 拆 Mixin** 时漏调用 setup 方法 → 部分 route 不注册;
2. **新增 Mixin** 时忘记在 ``__all__`` 注册 → IDE autocomplete 不发现, 但
   ``setup_routes`` 仍可能 import 到 (因为 web_ui.py 显式 import);
3. **删除 deprecated Mixin** 时漏改父类列表 → MRO 引用未定义类, ImportError
   阻塞启动;

invariant 比 unit test 更强: unit test 只能验证 "已注册 route 工作正常",
invariant 验证 "应该注册的 route 全部都注册了" (覆盖率层级)。

R406 与 R398/R404 关系
---------------------

R398/R404 聚焦 **route 内部 OpenAPI 文档质量**, R406 聚焦 **route 注册元
信息**, 形成 OpenAPI invariant 矩阵的 **架构层** 补充 (route 必须存在 → R406;
存在的 route 必须有正确 schema → R398; 必须有 quality summary → R404)。
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ROUTES_INIT = (
    REPO_ROOT / "src" / "ai_intervention_agent" / "web_ui_routes" / "__init__.py"
)
WEB_UI_PY = REPO_ROOT / "src" / "ai_intervention_agent" / "web_ui.py"
ROUTES_DIR = REPO_ROOT / "src" / "ai_intervention_agent" / "web_ui_routes"

# Mixin 名称约定: <Name>RoutesMixin 对应 _setup_<name>_routes 方法。
# 转换规则: TaskRoutesMixin → _setup_task_routes
_MIXIN_SUFFIX = "RoutesMixin"
_SETUP_PREFIX = "_setup_"
_SETUP_SUFFIX = "_routes"


def _mixin_to_setup_name(mixin_name: str) -> str:
    """``TaskRoutesMixin`` → ``_setup_task_routes``."""
    base = mixin_name
    if base.endswith(_MIXIN_SUFFIX):
        base = base[: -len(_MIXIN_SUFFIX)]
    return f"{_SETUP_PREFIX}{base.lower()}{_SETUP_SUFFIX}"


def _setup_to_mixin_name(setup_name: str) -> str:
    """``_setup_task_routes`` → ``TaskRoutesMixin``."""
    base = setup_name
    if base.startswith(_SETUP_PREFIX):
        base = base[len(_SETUP_PREFIX) :]
    if base.endswith(_SETUP_SUFFIX):
        base = base[: -len(_SETUP_SUFFIX)]
    return f"{base.capitalize()}{_MIXIN_SUFFIX}"


def _parse_all_from_init() -> list[str]:
    """从 web_ui_routes/__init__.py 提取 __all__ 列表 (只含 ...RoutesMixin)。"""
    text = ROUTES_INIT.read_text(encoding="utf-8")
    tree = ast.parse(text)
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Assign)
            and any(isinstance(t, ast.Name) and t.id == "__all__" for t in node.targets)
            and isinstance(node.value, (ast.List, ast.Tuple))
        ):
            return [
                elt.value
                for elt in node.value.elts
                if isinstance(elt, ast.Constant)
                and isinstance(elt.value, str)
                and elt.value.endswith(_MIXIN_SUFFIX)
            ]
    return []


def _parse_webfeedbackui_parents() -> list[str]:
    """从 web_ui.py 的 ``class WebFeedbackUI(...)`` 提取所有 ...RoutesMixin 父类。"""
    text = WEB_UI_PY.read_text(encoding="utf-8")
    tree = ast.parse(text)
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "WebFeedbackUI":
            return [
                base.id
                for base in node.bases
                if isinstance(base, ast.Name) and base.id.endswith(_MIXIN_SUFFIX)
            ]
    return []


def _parse_setup_calls_in_setup_routes() -> list[str]:
    """从 web_ui.py 的 ``setup_routes`` 方法提取所有 self._setup_X_routes() 调用。"""
    text = WEB_UI_PY.read_text(encoding="utf-8")
    pattern = re.compile(r"self\.(_setup_\w+_routes)\s*\(")
    return list(dict.fromkeys(pattern.findall(text)))


def _find_setup_methods_in_mixin_files() -> dict[str, str]:
    """扫描 web_ui_routes/*.py, 返回 {method_name: file_name}。"""
    out: dict[str, str] = {}
    for py_file in sorted(ROUTES_DIR.glob("*.py")):
        if py_file.name in {"__init__.py", "_upload_helpers.py"}:
            continue
        try:
            text = py_file.read_text(encoding="utf-8")
            tree = ast.parse(text)
        except (OSError, SyntaxError):
            continue
        for node in ast.walk(tree):
            if (
                isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name.startswith(_SETUP_PREFIX)
                and node.name.endswith(_SETUP_SUFFIX)
            ):
                out[node.name] = py_file.name
    return out


class TestLayer1Anchor:
    """Layer 1: __init__.py __all__ 至少 5 个 Mixin。"""

    def test_at_least_5_mixins_in_all(self):
        mixins = _parse_all_from_init()
        assert len(mixins) >= 5, (
            f"R406-L1: __init__.py __all__ has only {len(mixins)} Mixin(s) "
            f"({mixins}), expected >= 5. AST parsing may be broken or "
            f"Mixin 命名约定改变。"
        )

    def test_webfeedbackui_class_found(self):
        parents = _parse_webfeedbackui_parents()
        assert len(parents) >= 5, (
            f"R406-L1: WebFeedbackUI has only {len(parents)} ...RoutesMixin "
            f"parent(s) ({parents}), expected >= 5. AST extraction may be "
            f"broken or class structure changed."
        )

    def test_setup_calls_found(self):
        calls = _parse_setup_calls_in_setup_routes()
        assert len(calls) >= 5, (
            f"R406-L1: web_ui.py setup_routes() has only {len(calls)} "
            f"_setup_X_routes() call(s) ({calls}), expected >= 5."
        )


class TestLayer2AllVsParentConsistency:
    """Layer 2: __all__ ↔ WebFeedbackUI parent classes 一致性。"""

    def test_all_mixins_in_parent_classes(self):
        all_mixins = set(_parse_all_from_init())
        parent_mixins = set(_parse_webfeedbackui_parents())
        missing_in_parents = all_mixins - parent_mixins
        assert not missing_in_parents, (
            f"R406-L2: Mixin(s) in __all__ but not in WebFeedbackUI parents: "
            f"{sorted(missing_in_parents)}\n"
            f"This causes the Mixin to be exported but never integrated → "
            f"its routes are never registered."
        )

    def test_parent_mixins_in_all(self):
        all_mixins = set(_parse_all_from_init())
        parent_mixins = set(_parse_webfeedbackui_parents())
        missing_in_all = parent_mixins - all_mixins
        assert not missing_in_all, (
            f"R406-L2: Mixin(s) in WebFeedbackUI parents but not in "
            f"__all__: {sorted(missing_in_all)}\n"
            f"This causes IDE autocomplete to miss the Mixin and external "
            f"importers (e.g., tests) to face ImportError on `from "
            f"web_ui_routes import XRoutesMixin`."
        )


class TestLayer3SetupCallsVsMethodExistence:
    """Layer 3: setup_routes calls ↔ Mixin method existence 一致性。"""

    def test_every_setup_call_has_method_definition(self, subtests):
        setup_calls = _parse_setup_calls_in_setup_routes()
        defined_methods = _find_setup_methods_in_mixin_files()
        violations: list[str] = []
        for call in setup_calls:
            with subtests.test(call=call):
                if call not in defined_methods:
                    violations.append(
                        f"  {call}: called in WebFeedbackUI.setup_routes "
                        f"but no Mixin file defines this method"
                    )
        if violations:
            raise AssertionError(
                f"R406-L3-forward: {len(violations)} setup call(s) without "
                f"backing method:\n" + "\n".join(violations) + "\n"
                "\nThis causes AttributeError at startup when "
                "setup_routes() is invoked."
            )

    def test_every_setup_call_corresponds_to_a_parent_mixin(self, subtests):
        setup_calls = _parse_setup_calls_in_setup_routes()
        parent_mixins = set(_parse_webfeedbackui_parents())
        violations: list[str] = []
        for call in setup_calls:
            with subtests.test(call=call):
                expected_mixin = _setup_to_mixin_name(call)
                if expected_mixin not in parent_mixins:
                    violations.append(
                        f"  {call} → expected Mixin {expected_mixin} not in "
                        f"WebFeedbackUI parents (parents: {sorted(parent_mixins)})"
                    )
        if violations:
            raise AssertionError(
                f"R406-L3-mapping: {len(violations)} setup call(s) without "
                f"corresponding Mixin in parent classes:\n" + "\n".join(violations)
            )


class TestLayer4NoOrphanSetupMethods:
    """Layer 4: 每个 Mixin 文件定义的 _setup_X_routes 方法都必须被调用 (no dead code)。"""

    def test_every_defined_setup_method_is_called(self, subtests):
        setup_calls = set(_parse_setup_calls_in_setup_routes())
        defined_methods = _find_setup_methods_in_mixin_files()
        violations: list[str] = []
        for method, file_name in defined_methods.items():
            with subtests.test(method=method, file=file_name):
                if method not in setup_calls:
                    violations.append(
                        f"  {file_name}::{method}: defined but never called "
                        f"in WebFeedbackUI.setup_routes (dead code, routes "
                        f"are silently not registered)"
                    )
        if violations:
            raise AssertionError(
                f"R406-L4: {len(violations)} orphan setup method(s):\n"
                + "\n".join(violations)
                + "\n"
                "\nFix: add `self.{method}()` to WebFeedbackUI."
                "setup_routes(), or remove the orphan method if it's dead "
                "code."
            )

    def test_each_mixin_has_exactly_one_setup_method(self, subtests):
        all_mixins = _parse_all_from_init()
        defined_methods = _find_setup_methods_in_mixin_files()
        defined_method_names = set(defined_methods.keys())
        violations: list[str] = []
        for mixin in all_mixins:
            expected_setup = _mixin_to_setup_name(mixin)
            with subtests.test(mixin=mixin, expected=expected_setup):
                if expected_setup not in defined_method_names:
                    violations.append(
                        f"  {mixin}: expected setup method "
                        f"{expected_setup} not defined in any Mixin file"
                    )
        if violations:
            raise AssertionError(
                f"R406-L4-naming: {len(violations)} Mixin(s) violating "
                f"naming convention (<Name>RoutesMixin should have "
                f"_setup_<name>_routes method):\n" + "\n".join(violations)
            )


class TestR406LineageMarker:
    """Layer 5: methodology lineage 引用必须保留 + 维度 14 首次落地标记。"""

    def test_this_file_contains_r406_marker(self):
        text = Path(__file__).read_text(encoding="utf-8")
        assert "R406" in text

    def test_this_file_references_lineage(self):
        text = Path(__file__).read_text(encoding="utf-8")
        for prior in ("R398", "R404"):
            assert prior in text, f"R406: must cite related lineage: {prior}"

    def test_this_file_marks_dimension_14(self):
        text = Path(__file__).read_text(encoding="utf-8")
        for kw in ("第 14 个方法学维度", "route registration matrix"):
            assert kw in text, f"R406: missing keyword: {kw!r}"
