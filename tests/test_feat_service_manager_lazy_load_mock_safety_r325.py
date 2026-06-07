"""R325 · ``service_manager._ensure_notification_system_loaded`` per-attribute
mock safety (cycle-34 #E, v3.8 test-isolation 5th 跨域应用 — R324 follow-up)。

背景
----

R324 (cycle-34 #D) 修复了 ``web_ui_routes/notification.py`` 的 lazy load
mock pollution bug, 引入 **per-attribute null check** 模式。

但在 codebase 里, ``service_manager.py`` 还有一个**同源**的 lazy load 函
数 ``_ensure_notification_system_loaded``, 也用 "flag-based all-or-nothing"
short-circuit (检查 ``_notification_initialized``)。如果未来的测试只 patch
``_notification_manager_singleton`` 但忘记 patch
``_notification_initialized=True``, 同样会被 lazy import 覆盖。

R325 把 R324 的 per-attribute mock safety 模式扩展到 ``service_manager``,
让两个 lazy load 函数采用**同一种模式**, 防患于未然。

R325 invariant 锁
------------------

1. **Layer 1 (Source structure)**: ``_ensure_notification_system_loaded``
   函数体 short-circuit 必须**同时**检查 flag + 2 个 attribute 的 non-None
2. **Layer 2 (Mock safety behavior)**: mock 任一 attribute (不 mock flag)
   → 调用 ``_ensure_*()`` → mock 不被覆盖
3. **Layer 3 (R324 一致性)**: 两个 lazy load 函数 (web_ui_routes 的
   ``_ensure_notification_loaded`` + service_manager 的
   ``_ensure_notification_system_loaded``) 都使用 per-attribute null check
   模式, 形成 codebase 一致策略

methodology lineage (v3.8 test-isolation)
-------------------------------------------

- 1st: R316 (cycle-33) — R145 setUp 显式补充 (test 层)
- 2nd: R319 (cycle-33) — ``_create_test_instance()`` (test 层 helper)
- 3rd: R323 (cycle-34) — ``reset_for_testing()`` + conftest (test + conftest 层)
- 4th: R324 (cycle-34 #D) — web_ui_routes lazy-load mock safety (source 层)
- **5th: R325 (cycle-34 #E, 本 commit)** — service_manager lazy-load mock
  safety (source 层 cross-module consistency)

意义
-----

R325 让 v3.8 test-isolation pattern **横跨 2 个 source-layer module** 应用
(R324 + R325), 证明 pattern 在 codebase 内可重复扩展。同时主动 harden
service_manager, 避免未来类似的 cross-test mock pollution bug。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC = REPO_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

_SERVICE_MANAGER_PY = SRC / "ai_intervention_agent" / "service_manager.py"
_NOTIFICATION_ROUTE_PY = (
    SRC / "ai_intervention_agent" / "web_ui_routes" / "notification.py"
)


class TestLayer1SourceStructure:
    """Layer 1: ``_ensure_notification_system_loaded`` 必须有 per-attribute
    null check 同时配合 flag, 不能退化回 'only check flag'。"""

    def test_source_file_exists(self):
        assert _SERVICE_MANAGER_PY.is_file()

    def test_function_defined(self):
        text = _SERVICE_MANAGER_PY.read_text(encoding="utf-8")
        assert "def _ensure_notification_system_loaded()" in text, (
            "R325 anchor: `_ensure_notification_system_loaded` function must exist"
        )

    def test_short_circuit_checks_both_flag_and_attributes(self):
        """R325-L1: short-circuit 必须**同时**检查 flag + 2 个 attribute
        non-None, 避免 mock pollution。"""
        text = _SERVICE_MANAGER_PY.read_text(encoding="utf-8")
        m = re.search(
            r"def\s+_ensure_notification_system_loaded\s*\(\s*\)[^:]*:\s*\n"
            r"(?P<body>.*?)(?=\n(?:def\s+|class\s+|@|\Z))",
            text,
            re.DOTALL,
        )
        assert m, "R325: cannot locate _ensure_notification_system_loaded body"
        body = m.group("body")

        required_checks = (
            "_notification_initialized",
            "_notification_manager_singleton is not None",
            "_initialize_notification_system_fn is not None",
        )
        for chk in required_checks:
            assert chk in body, (
                f"R325-L1: _ensure_notification_system_loaded body must "
                f"contain `{chk}` in short-circuit condition. Without it, "
                f"mock.patch on attribute alone (without patching the "
                f"flag) can be overwritten by lazy import."
            )

    def test_per_attribute_null_check_in_assignment(self):
        """R325-L1: import 后的赋值也必须 per-attribute null check, 防止
        覆盖已 mock 的值。"""
        text = _SERVICE_MANAGER_PY.read_text(encoding="utf-8")
        m = re.search(
            r"def\s+_ensure_notification_system_loaded\s*\(\s*\)[^:]*:\s*\n"
            r"(?P<body>.*?)(?=\n(?:def\s+|class\s+|@|\Z))",
            text,
            re.DOTALL,
        )
        assert m
        body = m.group("body")

        assert "if _notification_manager_singleton is None:" in body, (
            "R325-L1: assignment of `_notification_manager_singleton` must "
            "be guarded by `if ... is None:` to prevent overwriting mock."
        )
        assert "if _initialize_notification_system_fn is None:" in body, (
            "R325-L1: assignment of `_initialize_notification_system_fn` "
            "must be guarded similarly."
        )

    def test_function_marks_r325_in_docstring(self):
        text = _SERVICE_MANAGER_PY.read_text(encoding="utf-8")
        m = re.search(
            r"def\s+_ensure_notification_system_loaded\s*\(\s*\)[^:]*:\s*\n"
            r'\s*"""(?P<doc>.*?)"""',
            text,
            re.DOTALL,
        )
        assert m
        doc = m.group("doc")
        assert "R325" in doc, "R325: function docstring must contain R325 marker."
        assert "R324" in doc, (
            "R325: docstring must reference R324 (same pattern, prior art)."
        )


class TestLayer2MockSafetyBehavior:
    """Layer 2: mock 任一 attribute (不 mock flag) → 调用 ``_ensure_*()`` →
    mock 不被覆盖。"""

    def test_mock_singleton_survives_ensure_call_when_flag_false(self):
        from ai_intervention_agent import service_manager as sm

        original = sm._notification_manager_singleton
        original_flag = sm._notification_initialized
        try:
            with patch.object(sm, "_notification_manager_singleton", "MOCK_NM_VALUE"):
                with patch.object(sm, "_notification_initialized", False):
                    sm._ensure_notification_system_loaded()
                    assert sm._notification_manager_singleton == "MOCK_NM_VALUE", (
                        "R325: _notification_manager_singleton mock was "
                        "overwritten by lazy import! Per-attribute null "
                        "check missing or broken."
                    )
        finally:
            sm._notification_manager_singleton = original
            sm._notification_initialized = original_flag

    def test_mock_init_fn_survives_ensure_call_when_flag_false(self):
        from ai_intervention_agent import service_manager as sm

        original = sm._initialize_notification_system_fn
        original_flag = sm._notification_initialized
        try:
            with patch.object(
                sm, "_initialize_notification_system_fn", "MOCK_FN_VALUE"
            ):
                with patch.object(sm, "_notification_initialized", False):
                    sm._ensure_notification_system_loaded()
                    assert sm._initialize_notification_system_fn == "MOCK_FN_VALUE", (
                        "R325: _initialize_notification_system_fn mock was overwritten."
                    )
        finally:
            sm._initialize_notification_system_fn = original
            sm._notification_initialized = original_flag


class TestLayer3R324CrossModuleConsistency:
    """Layer 3: R324 + R325 形成 codebase 一致策略 — 所有 lazy-load with
    multi-attribute 的函数都必须用 per-attribute null check。"""

    def test_r324_and_r325_both_use_per_attribute_pattern(self):
        """两个 lazy load 函数都包含 per-attribute null check。"""
        # R324 path
        nr_text = _NOTIFICATION_ROUTE_PY.read_text(encoding="utf-8")
        nr_m = re.search(
            r"def\s+_ensure_notification_loaded\s*\(\s*\)[^:]*:\s*\n"
            r"(?P<body>.*?)(?=\n(?:def\s+|class\s+|@|\Z))",
            nr_text,
            re.DOTALL,
        )
        assert nr_m, "R324 anchor: _ensure_notification_loaded missing"
        nr_body = nr_m.group("body")
        assert "is None" in nr_body
        # 至少 3 个 per-attribute null check (R324 锁了 4 个, 这里宽松判 3)
        is_none_count_nr = nr_body.count("is None")
        assert is_none_count_nr >= 4, (
            f"R325 cross-module: R324 _ensure_notification_loaded has "
            f"{is_none_count_nr} `is None` checks, expected >=4"
        )

        # R325 path
        sm_text = _SERVICE_MANAGER_PY.read_text(encoding="utf-8")
        sm_m = re.search(
            r"def\s+_ensure_notification_system_loaded\s*\(\s*\)[^:]*:\s*\n"
            r"(?P<body>.*?)(?=\n(?:def\s+|class\s+|@|\Z))",
            sm_text,
            re.DOTALL,
        )
        assert sm_m, "R325 anchor: _ensure_notification_system_loaded missing"
        sm_body = sm_m.group("body")
        is_none_count_sm = sm_body.count("is None")
        assert is_none_count_sm >= 4, (
            f"R325: _ensure_notification_system_loaded has {is_none_count_sm} "
            f"`is None` checks, expected >=4 (short-circuit 2 + assignment 2)"
        )

    def test_codebase_has_no_unguarded_lazy_load(self):
        """**future-guard**: 所有定义 ``def _ensure_*_loaded(...)`` 的函数
        必须在已知 R324/R325 名单内, 或者本身只单 attribute (无 mock 风
        险)。"""
        known_safe = {
            "_ensure_notification_loaded",
            "_ensure_notification_system_loaded",
            "_ensure_bark_provider_loaded",  # 单 attribute, 无风险
        }

        # 扫整个 src 目录
        src_dir = SRC / "ai_intervention_agent"
        all_funcs = set()
        for py in src_dir.rglob("*.py"):
            text = py.read_text(encoding="utf-8")
            for m in re.finditer(r"def\s+(_ensure_\w+_loaded)\s*\(", text):
                all_funcs.add(m.group(1))

        unknown = all_funcs - known_safe
        assert not unknown, (
            f"R325 future-guard: NEW lazy-load function(s) detected NOT in "
            f"known_safe list: {unknown}. **Action**: (1) audit the new "
            f"function for multi-attribute mock pollution risk (R324 "
            f"pattern); (2) add to known_safe list with rationale; "
            f"(3) if multi-attribute, apply per-attribute null check."
        )


class TestR325LineageMarker:
    """R325 是 v3.8 test-isolation pattern 5th app, source 层 cross-module。"""

    def test_this_file_contains_r325_marker(self):
        text = Path(__file__).read_text(encoding="utf-8")
        assert "R325" in text

    def test_this_file_references_prior_pattern_apps(self):
        text = Path(__file__).read_text(encoding="utf-8")
        for prior in ("R316", "R319", "R323", "R324"):
            assert prior in text, f"R325: must cite prior test-isolation app: {prior}"

    def test_this_file_documents_extension(self):
        text = Path(__file__).read_text(encoding="utf-8")
        assert "5th" in text, (
            "R325: documentation should mark this as 5th app of test-isolation"
        )
        for kw in (
            "cross-module",
            "per-attribute",
            "service_manager",
            "R324",
        ):
            assert kw in text, f"R325: documentation missing keyword: {kw!r}"
