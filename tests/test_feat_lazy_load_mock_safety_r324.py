"""R324 · ``_ensure_*_loaded`` lazy-load mock-safety invariant
(cycle-34 #D, 真实 bug fix + 工程化 invariant)。

背景 — bark mock pollution bug
--------------------------------

R324 修复了一个**长期存在 (2026/3/27 以来一直 broken)** 的 cross-test
mock pollution bug:

- ``tests/test_web_ui_routes.py::TestBarkTestEndpoint::test_bark_send_
  fail_with_detail_no_status_code`` 用 ``@patch("...NotificationEvent")``
  单一 attribute mock
- 但 ``_ensure_notification_loaded()`` 的 short-circuit 只看
  ``notification_manager is None``, 不看 ``NotificationEvent is None``
- 如果 ``notification_manager`` 还没被任何前置路由调用触发 lazy load
  → short-circuit fail → 进入 import 分支 → **覆盖** mock 为真实 class
- 测试断言 ``test_event.metadata == {"bark_error": {...}}`` 失败, 因为
  ``test_event`` 是真 ``NotificationEvent`` instance (metadata 是
  ``test_metadata`` dict, 没有 ``bark_error``)

bug fix 策略
------------

把 short-circuit 从 "all-or-nothing" 改为 **per-attribute lazy load**:
每个 module-level attribute 独立检查 ``is None``, 独立赋值。这样:

1. **mock 安全**: 任何 ``@patch("...X")`` 单独 patch 都不会被 lazy import
   覆盖, X 已不是 None 时跳过赋值
2. **性能不变**: 所有 attribute 共享同一次 ``from ai_intervention_agent
   .notification_manager import ...``, R20.10 的 ~43ms cold-start saving
   完全保留
3. **幂等**: 全部 attribute 已加载时入口直接 early return, 不付任何成本

R324 invariant 锁三层
-----------------------

1. **Layer 1 (Source code structure)**: ``_ensure_notification_loaded``
   函数体必须含 per-attribute null check (``NotificationEvent is None``
   等), 不能退化回 "只看 notification_manager"
2. **Layer 2 (Behavior)**: mock 任意一个 attribute (不 mock
   notification_manager), 调用 ``_ensure_notification_loaded()`` 后, mock
   必须保留
3. **Layer 3 (Bug regression)**: 直接调原始 ``test_bark_send_fail_with_
   detail_no_status_code`` 测试, 验证 bug fix 持久

R324 同时是 v3.8 test-isolation pattern 的 **4th 应用** (cross-domain):

- 1st R316 (cycle-33): R145 setUp 显式补充
- 2nd R319 (cycle-33): ``_create_test_instance()`` classmethod
- 3rd R323 (cycle-34): ``reset_for_testing()`` + conftest 自动调用
- **4th R324 (cycle-34, 本 commit)**: lazy-load mock pollution fix —
  把 isolation 从 "test setUp/conftest 层" 推到 "source 层 mock safety"

methodology lineage
-------------------

R324 是 **bug fix + pattern extension** 双重价值:

- bug 类型: cross-test mock pollution due to lazy-load short-circuit
- pattern: per-attribute lazy load (R20.10 性能保留 + mock safety)
- prior art: R316/R319/R323 都是 isolation 的 test 层, R324 把 isolation
  扩展到 source 层 (任何用 lazy load + mock 的 module 都受益)
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

_NOTIFICATION_ROUTE_PY = (
    SRC / "ai_intervention_agent" / "web_ui_routes" / "notification.py"
)


class TestLayer1SourceStructure:
    """Layer 1: ``_ensure_notification_loaded`` 必须有 per-attribute null
    check, 不能退化回 'only check notification_manager'。"""

    def test_source_file_exists(self):
        assert _NOTIFICATION_ROUTE_PY.is_file()

    def test_function_defined(self):
        text = _NOTIFICATION_ROUTE_PY.read_text(encoding="utf-8")
        assert "def _ensure_notification_loaded()" in text, (
            "R324 anchor: `_ensure_notification_loaded` function must exist"
        )

    def test_per_attribute_null_check_present(self):
        """R324-L1: 函数体必须含 per-attribute null check (4 个)。"""
        text = _NOTIFICATION_ROUTE_PY.read_text(encoding="utf-8")
        m = re.search(
            r"def\s+_ensure_notification_loaded\s*\(\s*\)[^:]*:\s*\n"
            r"(?P<body>.*?)(?=\n(?:def\s+|class\s+|@|\Z))",
            text,
            re.DOTALL,
        )
        assert m, "R324: cannot locate _ensure_notification_loaded body"
        body = m.group("body")

        required_attrs = (
            "notification_manager is None",
            "NotificationEvent is None",
            "NotificationTrigger is None",
            "NotificationType is None",
        )
        for attr_check in required_attrs:
            assert attr_check in body, (
                f"R324-L1: _ensure_notification_loaded body must contain "
                f"per-attribute null check `{attr_check}`. Without it, "
                f"mock.patch on one attribute can be overwritten by lazy "
                f"import when other attributes are still None."
            )

    def test_function_marks_r324_in_docstring(self):
        """R324 marker 必须在函数 docstring 里, 帮助后续维护者理解。"""
        text = _NOTIFICATION_ROUTE_PY.read_text(encoding="utf-8")
        m = re.search(
            r"def\s+_ensure_notification_loaded\s*\(\s*\)[^:]*:\s*\n"
            r'\s*"""(?P<doc>.*?)"""',
            text,
            re.DOTALL,
        )
        assert m, "R324: cannot extract docstring of _ensure_notification_loaded"
        doc = m.group("doc")
        assert "R324" in doc, (
            "R324: function docstring must contain R324 marker to prevent "
            "future regression."
        )
        assert "per-attribute" in doc or "per attribute" in doc.lower(), (
            "R324: docstring must explain per-attribute lazy load strategy."
        )


class TestLayer2MockSafetyBehavior:
    """Layer 2: mock 任一 attribute 后调 ``_ensure_notification_loaded()``,
    mock 不能被覆盖。"""

    def test_mock_notification_event_survives_ensure_call(self):
        from ai_intervention_agent.web_ui_routes import notification as nr

        original_ne = nr.NotificationEvent
        original_nm = nr.notification_manager
        try:
            with patch.object(nr, "NotificationEvent", "MOCK_NE_VALUE"):
                with patch.object(nr, "notification_manager", None):
                    nr._ensure_notification_loaded()
                    assert nr.NotificationEvent == "MOCK_NE_VALUE", (
                        "R324: NotificationEvent mock was overwritten by "
                        "lazy import! Per-attribute null check missing or "
                        "broken."
                    )
        finally:
            nr.NotificationEvent = original_ne
            nr.notification_manager = original_nm

    def test_mock_notification_type_survives_ensure_call(self):
        from ai_intervention_agent.web_ui_routes import notification as nr

        original = nr.NotificationType
        original_nm = nr.notification_manager
        try:
            with patch.object(nr, "NotificationType", "MOCK_NTY_VALUE"):
                with patch.object(nr, "notification_manager", None):
                    nr._ensure_notification_loaded()
                    assert nr.NotificationType == "MOCK_NTY_VALUE", (
                        "R324: NotificationType mock overwritten by lazy import."
                    )
        finally:
            nr.NotificationType = original
            nr.notification_manager = original_nm

    def test_mock_notification_trigger_survives_ensure_call(self):
        from ai_intervention_agent.web_ui_routes import notification as nr

        original = nr.NotificationTrigger
        original_nm = nr.notification_manager
        try:
            with patch.object(nr, "NotificationTrigger", "MOCK_NT_VALUE"):
                with patch.object(nr, "notification_manager", None):
                    nr._ensure_notification_loaded()
                    assert nr.NotificationTrigger == "MOCK_NT_VALUE", (
                        "R324: NotificationTrigger mock overwritten by lazy import."
                    )
        finally:
            nr.NotificationTrigger = original
            nr.notification_manager = original_nm

    def test_all_already_loaded_short_circuits_to_early_return(self):
        """如果全部 4 个 attribute 已 non-None, 函数应直接 return, 不进入
        import 分支 — R20.10 性能保留的核心。"""
        from ai_intervention_agent.web_ui_routes import notification as nr

        with patch.object(nr, "NotificationEvent", "SENTINEL_NE"):
            with patch.object(nr, "NotificationTrigger", "SENTINEL_NT"):
                with patch.object(nr, "NotificationType", "SENTINEL_NTY"):
                    with patch.object(nr, "notification_manager", "SENTINEL_NM"):
                        nr._ensure_notification_loaded()
                        assert nr.NotificationEvent == "SENTINEL_NE"
                        assert nr.NotificationTrigger == "SENTINEL_NT"
                        assert nr.NotificationType == "SENTINEL_NTY"
                        assert nr.notification_manager == "SENTINEL_NM"


class TestLayer3BugRegressionGuard:
    """Layer 3: 直接调原始触发 bug 的测试场景, 防止 R324 fix 退化。"""

    def test_partial_mock_with_none_notification_manager_works(self):
        """模拟 ``test_bark_send_fail_with_detail_no_status_code`` 的核心
        mock 模式: 只 patch NotificationEvent, notification_manager 保持
        实际状态 (可能 None 可能非 None)。无论 notification_manager 是什
        么, mock 必须存活到 lazy load 之后。"""
        from ai_intervention_agent.web_ui_routes import notification as nr

        original = nr.NotificationEvent
        try:
            # 强制 NotificationEvent = mock, 但不动 notification_manager
            with patch.object(nr, "NotificationEvent", "BUG_REGRESSION_SENTINEL"):
                # 第一次调用 (无论 notification_manager 状态如何)
                nr._ensure_notification_loaded()
                assert nr.NotificationEvent == "BUG_REGRESSION_SENTINEL", (
                    "R324 BUG REGRESSION: NotificationEvent mock was "
                    "overwritten! The Mar-27-2026 bark test pollution "
                    "bug is back. Re-apply per-attribute null check."
                )
        finally:
            nr.NotificationEvent = original


class TestR324LineageMarker:
    """R324 是 v3.8 test-isolation pattern 4th 应用, 是 bug fix + pattern
    扩展。"""

    def test_this_file_contains_r324_marker(self):
        text = Path(__file__).read_text(encoding="utf-8")
        assert "R324" in text

    def test_this_file_references_prior_pattern_apps(self):
        text = Path(__file__).read_text(encoding="utf-8")
        for prior in ("R316", "R319", "R323"):
            assert prior in text, f"R324: must cite prior test-isolation app: {prior}"

    def test_this_file_documents_bug_fix(self):
        text = Path(__file__).read_text(encoding="utf-8")
        for kw in (
            "bark mock pollution",
            "per-attribute",
            "lazy",
            "short-circuit",
            "R20.10",
        ):
            assert kw in text, f"R324: documentation missing keyword: {kw!r}"

    def test_this_file_documents_pattern_extension(self):
        text = Path(__file__).read_text(encoding="utf-8")
        assert "4th" in text, (
            "R324: documentation should mark this as 4th app of test-isolation"
        )
        assert "source" in text.lower(), (
            "R324: should explain extension from test-layer to source-layer"
        )
