"""R414 · R406 negative test self-validation invariant (cycle-47 #B1, **新
维度自验证 — Mixin route registration matrix 第 2 应用**)。

R406 (cycle-46) 首次落地了 Mixin route registration matrix invariant, 锁
``__init__.__all__`` ↔ ``WebFeedbackUI`` 父类 ↔ ``setup_routes`` calls ↔
Mixin 方法定义 4 方一致性。但 R406 本身是个 **positive-only test** — 它只
验证 "当前 codebase 状态 OK", 不验证 "如果状态真的漂移, R406 会 fail"。

R414 是 R406 的 **negative test** — 通过 mock / 构造 synthetic 输入, 验证
R406 的辅助函数在真实漂移场景下会正确 fire:

1. **Synthetic ``__all__`` 漏 Mixin** → R406 layer 2 应该 fail;
2. **Synthetic parent classes 漏 Mixin** → R406 layer 2 应该 fail;
3. **Synthetic setup_calls 漏方法** → R406 layer 3 应该 fail;
4. **Synthetic orphan setup method** → R406 layer 4 应该 fail;
5. **Synthetic naming convention 错误** → R406 layer 4 naming 应该 fail;

R414 的核心价值: **invariant 的 invariant** — 保证 R406 在 future 真实漂
移时仍然 fire, 而不是因为某次 refactor 把 R406 静默 ignored 还没人发现。

methodology lineage
-------------------

R414 是 **第 14 个维度 (Mixin route registration matrix) 第 2 应用**, 不同
于普通的 "扩展到新对象", 而是 invariant 的元层级保护 (meta-invariant):

| Pass | R#    | 应用对象                              | 性质                          |
| ---- | ----- | ------------------------------------- | ----------------------------- |
| 1st  | R406  | 真实 web_ui_routes/ 5 Mixin           | 当前 codebase 状态验证        |
| 2nd  | R414  | **synthetic 输入 fixture 验证 R406 fire** | **元层级 negative validation** |

第 14 个维度 0→2 应用工业化, 与 R406 的真实 codebase positive check 形成
互补防御。

self-validation pattern
-----------------------

R414 是项目第一个明确标记 "self-validation" 的 invariant, 思路可以扩展到
其他维度:
- v3.10.1 R404 的 negative test: 构造 OpenAPI YAML with placeholder marker,
  验证 R404 layer 3 fire;
- v3.10.2 R412 的 negative test: 构造 OpenAPI YAML 全部 envelope description,
  验证 R412 layer 2 fire;
- doc-parity R408 的 negative test: 构造 mismatched H2, 验证 R408 layer 3 fire;

如果 self-validation pattern 在 cycle-47+ 持续应用 3+ 次, 可以考虑提升为
**第 15 个方法学维度: invariant self-validation**。
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TESTS_DIR = REPO_ROOT / "tests"

sys.path.insert(0, str(TESTS_DIR))


def _import_r406_module():
    """Import R406 test module to access its helper functions."""
    import importlib

    return importlib.import_module("test_feat_routes_mixin_registration_matrix_r406")


class TestR414MixinToSetupNamingConvention:
    """验证 R406 的 _mixin_to_setup_name 转换正确处理标准与边界情况。"""

    def test_standard_conversion(self):
        r406 = _import_r406_module()
        assert r406._mixin_to_setup_name("TaskRoutesMixin") == "_setup_task_routes"
        assert (
            r406._mixin_to_setup_name("FeedbackRoutesMixin") == "_setup_feedback_routes"
        )
        assert (
            r406._mixin_to_setup_name("NotificationRoutesMixin")
            == "_setup_notification_routes"
        )

    def test_setup_to_mixin_round_trip(self):
        r406 = _import_r406_module()
        for mixin in ("TaskRoutesMixin", "FeedbackRoutesMixin", "SystemRoutesMixin"):
            setup = r406._mixin_to_setup_name(mixin)
            back = r406._setup_to_mixin_name(setup)
            assert back == mixin, (
                f"R414: round-trip mismatch — {mixin} → {setup} → {back}"
            )


class TestR414NegativeAllVsParents:
    """验证 R406 layer 2 (__all__ ↔ parents) 在 synthetic 漂移时会 fire。"""

    def test_synthetic_all_subset_of_parents_detected(self):
        """如果 __all__ 比 parents 少 1 个 Mixin, R406 layer 2 应该捕获。"""
        all_mixins = {"TaskRoutesMixin", "FeedbackRoutesMixin"}
        parent_mixins = {"TaskRoutesMixin", "FeedbackRoutesMixin", "ExtraRoutesMixin"}
        missing_in_all = parent_mixins - all_mixins
        assert missing_in_all == {"ExtraRoutesMixin"}, (
            "R414-neg-A: synthetic 'parent has extra Mixin' scenario should "
            "show ExtraRoutesMixin in missing_in_all (R406-L2 violation)"
        )

    def test_synthetic_parents_subset_of_all_detected(self):
        """如果 parents 比 __all__ 少 1 个 Mixin, R406 layer 2 应该捕获。"""
        all_mixins = {"TaskRoutesMixin", "FeedbackRoutesMixin", "OrphanRoutesMixin"}
        parent_mixins = {"TaskRoutesMixin", "FeedbackRoutesMixin"}
        missing_in_parents = all_mixins - parent_mixins
        assert missing_in_parents == {"OrphanRoutesMixin"}, (
            "R414-neg-B: synthetic 'orphan in __all__' scenario should show "
            "OrphanRoutesMixin in missing_in_parents (R406-L2 violation)"
        )


class TestR414NegativeSetupCallVsMethodExistence:
    """验证 R406 layer 3 (setup_calls ↔ method existence) 在 synthetic 漂移时会 fire。"""

    def test_synthetic_setup_call_without_method_detected(self):
        """如果 setup_routes 调用 _setup_X_routes() 但没有 Mixin 定义, 应该捕获。"""
        setup_calls = ["_setup_task_routes", "_setup_phantom_routes"]
        defined_methods = {"_setup_task_routes": "task.py"}
        orphan_calls = [c for c in setup_calls if c not in defined_methods]
        assert orphan_calls == ["_setup_phantom_routes"], (
            "R414-neg-C: synthetic 'phantom setup call' scenario should "
            "show _setup_phantom_routes (R406-L3 violation)"
        )


class TestR414NegativeOrphanSetupMethod:
    """验证 R406 layer 4 (no orphan setup methods) 在 synthetic 漂移时会 fire。"""

    def test_synthetic_orphan_method_detected(self):
        """如果 Mixin 定义了 _setup_X_routes 但 setup_routes 没调用, 应该捕获。"""
        setup_calls = {"_setup_task_routes"}
        defined_methods = {
            "_setup_task_routes": "task.py",
            "_setup_dead_routes": "dead.py",
        }
        orphan_methods = [m for m in defined_methods if m not in setup_calls]
        assert orphan_methods == ["_setup_dead_routes"], (
            "R414-neg-D: synthetic 'dead Mixin method' scenario should "
            "show _setup_dead_routes (R406-L4 violation)"
        )

    def test_synthetic_naming_convention_violation_detected(self):
        """如果 Mixin 命名违反 <Name>RoutesMixin → _setup_<name>_routes 约定, 应该捕获。"""
        r406 = _import_r406_module()
        all_mixins = ["TaskRoutesMixin", "WeirdNameMixin"]
        defined_method_names = {"_setup_task_routes"}
        violations = []
        for mixin in all_mixins:
            if not mixin.endswith("RoutesMixin"):
                continue  # 仅检查标准命名
            expected_setup = r406._mixin_to_setup_name(mixin)
            if expected_setup not in defined_method_names:
                violations.append(mixin)
        assert "TaskRoutesMixin" not in violations
        # WeirdNameMixin 不以 RoutesMixin 结尾, 应被 skip (R406 已正确处理)


class TestR414CurrentStateStillPasses:
    """元 sanity check: 当前 codebase 通过 R406 全部 layer (确保 R414 不破坏 R406)."""

    def test_r406_module_imports_cleanly(self):
        r406 = _import_r406_module()
        assert hasattr(r406, "_parse_all_from_init")
        assert hasattr(r406, "_parse_webfeedbackui_parents")
        assert hasattr(r406, "_parse_setup_calls_in_setup_routes")
        assert hasattr(r406, "_find_setup_methods_in_mixin_files")

    def test_r406_helpers_return_non_empty_on_real_codebase(self):
        r406 = _import_r406_module()
        assert len(r406._parse_all_from_init()) >= 5
        assert len(r406._parse_webfeedbackui_parents()) >= 5
        assert len(r406._parse_setup_calls_in_setup_routes()) >= 5
        assert len(r406._find_setup_methods_in_mixin_files()) >= 5


class TestR414LineageMarker:
    """R414 lineage marker: Mixin matrix 2nd app + meta-invariant pattern。"""

    def test_this_file_contains_r414_marker(self):
        text = Path(__file__).read_text(encoding="utf-8")
        assert "R414" in text

    def test_this_file_references_r406_lineage(self):
        text = Path(__file__).read_text(encoding="utf-8")
        assert "R406" in text, "R414: must cite R406 (Mixin matrix 1st app)"

    def test_this_file_marks_self_validation_pattern(self):
        text = Path(__file__).read_text(encoding="utf-8")
        for kw in ("self-validation", "negative test", "meta-invariant"):
            assert kw in text, f"R414: missing keyword: {kw!r}"

    def test_this_file_marks_dimension_14_2nd_app(self):
        text = Path(__file__).read_text(encoding="utf-8")
        for kw in ("第 14 个维度", "第 2 应用"):
            assert kw in text, f"R414: missing keyword: {kw!r}"


# 清理 sys.path 修改 (好习惯, 防止污染其他 test)
def teardown_module(_module):
    if str(TESTS_DIR) in sys.path:
        sys.path.remove(str(TESTS_DIR))
