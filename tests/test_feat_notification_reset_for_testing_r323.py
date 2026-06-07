"""R323 · ``NotificationManager.reset_for_testing()`` + conftest 自动调用
(v3.8 test-isolation pattern 3rd app, 完成 v3.8 test-isolation 全工业化)。

背景
----

v3.8 test-isolation pattern 至今已有 2 个 app:

- 1st R316 (cycle-33 #A1): R145 setUp 显式补充缺失 attr (单点止血)
- 2nd R319 (cycle-33 #A2): ``_create_test_instance()`` classmethod (集中化
  helper for fresh instance, 适合 setUp 内手动调用)

R323 (cycle-34 #B2, 本 commit) 是 **3rd app**, 引入 ``reset_for_testing()``
instance method + conftest.py fixture 自动调用, 让 singleton 跨测试隔离
**全自动化**, 测试方不再需要在 setUp 维护任何 reset 代码。

**两者互补**:

- **R319 ``_create_test_instance()``** (classmethod): 创建 fresh instance,
  **不操作** singleton。适合需要完全独立 instance 的测试 (e.g. R145)
- **R323 ``reset_for_testing()``** (instance method): 重置 singleton state,
  让所有依赖 ``notification_manager`` singleton 的 route handler / 旧测试
  在每个测试开始时都看到 fresh state, 不被前一个测试污染

**R323 锁定层级**:

1. **Layer 1 (Method anchor)**: ``NotificationManager.reset_for_testing()``
   是 callable instance method, 不是 classmethod
2. **Layer 2 (Reset behavior)**: 调用后, 关键 state dict 必须被清空
   (stats counters reset to 0, queue/callbacks/delayed_timers empty,
   inflight sets empty)
3. **Layer 3 (Preservation)**: 调用后, lock instances / config /
   ``_initialized`` / lifecycle 资源 (executor / worker) **不**被替换
   (避免破坏 singleton lifecycle)
4. **Layer 4 (Conftest 集成)**: ``tests/conftest.py`` 的
   ``_isolate_config_and_notification_singletons`` fixture 必须调用
   ``notification_manager.reset_for_testing()``, 让每个测试前自动隔离

**Pattern lineage (v3.8 test-isolation)**:

- 1st app: R316 (cycle-33 #A1) — R145 setUp 显式补充缺失 attr
- 2nd app: R319 (cycle-33 #A2) — ``_create_test_instance()`` classmethod
- **3rd app: R323 (本 commit)** — ``reset_for_testing()`` instance method
  + conftest fixture 自动调用

**里程碑**: v3.8 test-isolation pattern 达 3 应用进入**完全工业化** (v3.8
**第 2 个全工业化 pattern**, 与 R322 idempotent 同 cycle 达到, **整个
v3.8 全部 pattern 完全工业化**)。
"""

from __future__ import annotations

import inspect
import re
import sys
import threading
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC = REPO_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from ai_intervention_agent.notification_manager import (
    NotificationManager,
    notification_manager,
)

_CONFTEST_PY = REPO_ROOT / "tests" / "conftest.py"
_NOTIFICATION_PY = SRC / "ai_intervention_agent" / "notification_manager.py"


class TestLayer1MethodAnchor:
    """Layer 1: ``reset_for_testing`` 必须是 ``NotificationManager`` 的
    callable instance method (不是 classmethod / staticmethod)。"""

    def test_method_exists(self):
        assert hasattr(NotificationManager, "reset_for_testing"), (
            "R323: NotificationManager.reset_for_testing() not found. "
            "v3.8 test-isolation pattern 3rd app requires this method."
        )

    def test_method_is_callable(self):
        method = NotificationManager.reset_for_testing
        assert callable(method)

    def test_method_is_instance_method_not_classmethod(self):
        """与 R319 _create_test_instance (classmethod) 区分: R323 是
        instance method, 操作 singleton self。"""
        attr = inspect.getattr_static(NotificationManager, "reset_for_testing")
        assert not isinstance(attr, classmethod), (
            "R323: reset_for_testing() must be instance method, not classmethod. "
            "(_create_test_instance is classmethod; reset_for_testing is "
            "instance method — they're complementary by design.)"
        )
        assert not isinstance(attr, staticmethod), (
            "R323: reset_for_testing() must be instance method, not staticmethod."
        )

    def test_method_signature_takes_self_only(self):
        sig = inspect.signature(NotificationManager.reset_for_testing)
        params = list(sig.parameters.values())
        assert len(params) == 1, (
            f"R323: reset_for_testing(self) should take only self, "
            f"got {len(params)} params: {[p.name for p in params]}"
        )
        assert params[0].name == "self"

    def test_method_returns_none(self):
        sig = inspect.signature(NotificationManager.reset_for_testing)
        annotation = sig.return_annotation
        assert annotation is None or annotation is type(None) or annotation == "None", (
            f"R323: reset_for_testing() should return None, got annotation: "
            f"{annotation!r}"
        )


class TestLayer2ResetBehavior:
    """Layer 2: 调用 ``reset_for_testing()`` 后, 关键 state 被清空。"""

    def test_stats_counters_reset_to_zero(self):
        notification_manager._stats["events_total"] = 42
        notification_manager._stats["events_succeeded"] = 30
        notification_manager._stats["events_failed"] = 12

        notification_manager.reset_for_testing()

        assert notification_manager._stats["events_total"] == 0
        assert notification_manager._stats["events_succeeded"] == 0
        assert notification_manager._stats["events_failed"] == 0

    def test_stats_schema_complete_after_reset(self):
        """reset 后 _stats 必须保留完整 schema (不能只清部分 key)。"""
        notification_manager._stats.clear()
        notification_manager._stats["random_key"] = "random_value"

        notification_manager.reset_for_testing()

        required = (
            "events_total",
            "events_succeeded",
            "events_failed",
            "attempts_total",
            "retries_scheduled",
            "last_event_id",
            "last_event_at",
            "providers",
        )
        for k in required:
            assert k in notification_manager._stats, (
                f"R323: reset_for_testing() must restore _stats key {k!r} "
                f"(complete schema). Got keys: {list(notification_manager._stats)}"
            )

    def test_histograms_reset_to_empty(self):
        notification_manager._provider_latency_histograms["dummy"] = {
            "count": 99,
            "sum_seconds": 0.5,
        }
        notification_manager.reset_for_testing()
        assert notification_manager._provider_latency_histograms == {}

    def test_finalized_event_ids_reset_to_empty(self):
        notification_manager._finalized_event_ids["dummy-id"] = None
        notification_manager.reset_for_testing()
        assert notification_manager._finalized_event_ids == {}

    def test_event_queue_reset_to_empty(self):
        from typing import cast

        from ai_intervention_agent.notification_manager import NotificationEvent

        notification_manager._event_queue.append(cast(NotificationEvent, object()))
        notification_manager.reset_for_testing()
        assert notification_manager._event_queue == []

    def test_callbacks_reset_to_empty(self):
        notification_manager._callbacks["dummy_event"] = [lambda *a, **k: None]
        notification_manager.reset_for_testing()
        assert notification_manager._callbacks == {}

    def test_delayed_timers_reset_and_cancelled(self):
        timer = threading.Timer(60.0, lambda: None)
        timer.start()
        notification_manager._delayed_timers["dummy-id"] = timer

        notification_manager.reset_for_testing()

        assert notification_manager._delayed_timers == {}
        # threading.Timer.cancel() 设置 finished flag, thread 自身可能短暂
        # 还 alive (等 wait() 退出), 但 callback 已保证不再执行。检查
        # finished 是更可靠的语义 (R322 锁的是 "不再执行" 不是 "thread 完
        # 全终止")。
        assert timer.finished.is_set(), (
            "R323: reset_for_testing() must cancel pending timers, otherwise "
            "they'd fire during later tests."
        )

    def test_inflight_sets_reset_to_empty(self):
        notification_manager._inflight_persisted_ids.add("dummy-id")
        notification_manager._inflight_seen_at_startup.append({"id": "dummy"})

        notification_manager.reset_for_testing()

        assert notification_manager._inflight_persisted_ids == set()
        assert notification_manager._inflight_seen_at_startup == []


class TestLayer3PreservesLifecycle:
    """Layer 3: ``reset_for_testing()`` **不**替换 lock / config /
    _initialized / lifecycle 资源, 避免破坏 singleton。"""

    def test_lock_instances_not_replaced(self):
        """同一个 lock 对象在 reset 前后必须是同一个 (id 一致)。
        否则正在持锁的并发代码会跟新 lock 失同步。"""
        lock_ids_before = {
            "_stats_lock": id(notification_manager._stats_lock),
            "_providers_lock": id(notification_manager._providers_lock),
            "_queue_lock": id(notification_manager._queue_lock),
            "_callbacks_lock": id(notification_manager._callbacks_lock),
            "_delayed_timers_lock": id(notification_manager._delayed_timers_lock),
            "_config_lock": id(notification_manager._config_lock),
        }

        notification_manager.reset_for_testing()

        lock_ids_after = {
            "_stats_lock": id(notification_manager._stats_lock),
            "_providers_lock": id(notification_manager._providers_lock),
            "_queue_lock": id(notification_manager._queue_lock),
            "_callbacks_lock": id(notification_manager._callbacks_lock),
            "_delayed_timers_lock": id(notification_manager._delayed_timers_lock),
            "_config_lock": id(notification_manager._config_lock),
        }
        assert lock_ids_before == lock_ids_after, (
            "R323: reset_for_testing() must NOT replace lock instances. "
            "Locks held by concurrent code would lose sync."
        )

    def test_initialized_flag_preserved(self):
        assert notification_manager._initialized is True
        notification_manager.reset_for_testing()
        assert notification_manager._initialized is True, (
            "R323: reset_for_testing() must NOT touch _initialized "
            "(would cause __init__ to re-run config load)."
        )

    def test_config_object_preserved(self):
        """config 由 ConfigManager 控制, R323 不应替换 config 对象本身。"""
        cfg_id_before = id(notification_manager.config)
        notification_manager.reset_for_testing()
        cfg_id_after = id(notification_manager.config)
        assert cfg_id_before == cfg_id_after, (
            "R323: reset_for_testing() must NOT replace config object "
            "(ConfigManager is the source of truth for config; conftest "
            "fixture handles config reload separately)."
        )

    def test_executor_preserved(self):
        """ThreadPoolExecutor 是 singleton lifecycle 一部分, R323 不应换。"""
        exec_id_before = id(notification_manager._executor)
        notification_manager.reset_for_testing()
        exec_id_after = id(notification_manager._executor)
        assert exec_id_before == exec_id_after, (
            "R323: reset_for_testing() must NOT replace _executor "
            "(lifecycle is owned by __init__ / shutdown / restart)."
        )


class TestLayer4ConftestIntegration:
    """Layer 4: ``tests/conftest.py`` 必须调用 ``reset_for_testing()`` 在
    isolate fixture 里, 让 singleton 跨测试隔离全自动化。"""

    def test_conftest_imports_notification_manager_singleton(self):
        text = _CONFTEST_PY.read_text(encoding="utf-8")
        assert "notification_manager" in text, (
            "R323: conftest.py must import notification_manager singleton."
        )

    def test_conftest_calls_reset_for_testing(self):
        text = _CONFTEST_PY.read_text(encoding="utf-8")
        assert "notification_manager.reset_for_testing()" in text, (
            "R323: conftest.py must call notification_manager.reset_for_testing() "
            "in _isolate_config_and_notification_singletons fixture. Without "
            "this, the v3.8 test-isolation pattern 3rd app is incomplete."
        )

    def test_conftest_reset_call_is_inside_isolate_fixture(self):
        """``reset_for_testing()`` 必须出现在
        ``_isolate_config_and_notification_singletons`` fixture 范围内。"""
        text = _CONFTEST_PY.read_text(encoding="utf-8")
        match = re.search(
            r"def\s+_isolate_config_and_notification_singletons\s*\(\s*\)"
            r"\s*:\s*\n.*?(?=\n@pytest\.fixture|\Z)",
            text,
            re.DOTALL,
        )
        assert match, (
            "R323: cannot locate _isolate_config_and_notification_singletons "
            "fixture in conftest.py"
        )
        fixture_body = match.group(0)
        assert "reset_for_testing()" in fixture_body, (
            "R323: reset_for_testing() call must be inside "
            "_isolate_config_and_notification_singletons fixture body, "
            "not in some other fixture."
        )

    def test_conftest_documents_r323_lineage(self):
        """conftest.py 里 reset_for_testing() 调用附近必须有 R323 marker
        + 提到 R319 互补关系, 帮助后续维护者理解 pattern lineage。"""
        text = _CONFTEST_PY.read_text(encoding="utf-8")
        assert "R323" in text, "R323: conftest.py missing R323 marker comment."
        assert "R319" in text or "_create_test_instance" in text, (
            "R323: conftest.py should reference R319 / _create_test_instance "
            "to clarify complementary relationship."
        )


class TestR323MethodDocstring:
    """``reset_for_testing()`` docstring 必须完整解释 pattern lineage +
    与 R319 的互补关系, 防止后续维护者错用。"""

    def test_method_has_docstring(self):
        doc = inspect.getdoc(NotificationManager.reset_for_testing)
        assert doc, "R323: reset_for_testing() must have docstring"
        assert len(doc) >= 500, (
            f"R323: reset_for_testing() docstring too short ({len(doc)} chars). "
            f"Should fully explain pattern + R319 complement."
        )

    def test_docstring_marks_test_only(self):
        doc = inspect.getdoc(NotificationManager.reset_for_testing)
        assert doc
        doc_lower = doc.lower()
        assert "test-only" in doc_lower or "test only" in doc_lower or "测试" in doc, (
            "R323: docstring must mark method as Test-only to prevent "
            "production misuse."
        )

    def test_docstring_references_r319_complement(self):
        doc = inspect.getdoc(NotificationManager.reset_for_testing)
        assert doc
        for kw in ("R319", "_create_test_instance"):
            assert kw in doc, (
                f"R323: docstring must reference R319 / _create_test_instance "
                f"to explain complement: {kw!r} missing"
            )

    def test_docstring_documents_pattern_lineage(self):
        doc = inspect.getdoc(NotificationManager.reset_for_testing)
        assert doc
        for marker in ("R316", "R319", "R323", "test-isolation"):
            assert marker in doc, (
                f"R323: docstring should document pattern lineage marker {marker!r}"
            )

    def test_docstring_explains_preservation(self):
        """docstring 必须解释哪些东西**不**被 reset (lock / config /
        executor), 防止后续维护者误改成 'reset all'。"""
        doc = inspect.getdoc(NotificationManager.reset_for_testing)
        assert doc
        doc_lower = doc.lower()
        preservation_hints = (
            "不重置",
            "保留",
            "preserve",
            "lifecycle",
            "lock",
        )
        hits = sum(1 for kw in preservation_hints if kw.lower() in doc_lower)
        assert hits >= 2, (
            f"R323: docstring must explain what's preserved (not reset), "
            f"hits {hits}/{len(preservation_hints)} for {preservation_hints}"
        )


class TestR323LineageMarker:
    """R323 是 v3.8 test-isolation pattern 3rd app, lineage marker 校验。"""

    def test_this_file_contains_r323_marker(self):
        text = Path(__file__).read_text(encoding="utf-8")
        assert "R323" in text
        assert "test-isolation" in text.lower() or "test_isolation" in text.lower()

    def test_this_file_references_prior_apps(self):
        text = Path(__file__).read_text(encoding="utf-8")
        for prior in ("R316", "R319"):
            assert prior in text, f"R323: must cite prior test-isolation app: {prior}"

    def test_this_file_documents_pattern_completion(self):
        text = Path(__file__).read_text(encoding="utf-8")
        for kw in (
            "3rd app",
            "v3.8",
            "reset_for_testing",
            "_create_test_instance",
            "conftest",
        ):
            assert kw in text, f"R323: missing keyword: {kw!r}"


class TestR323NotificationPyHasMethod:
    """Source-level grep: notification_manager.py 必须定义
    ``reset_for_testing`` 方法 (anchor 测试)。"""

    def test_source_file_has_method_definition(self):
        text = _NOTIFICATION_PY.read_text(encoding="utf-8")
        assert "def reset_for_testing(self)" in text, (
            "R323: notification_manager.py must define `def reset_for_testing(self)`"
        )

    def test_source_file_documents_r323(self):
        text = _NOTIFICATION_PY.read_text(encoding="utf-8")
        assert "R323" in text, (
            "R323: notification_manager.py source must contain R323 marker "
            "(in reset_for_testing docstring or comment)"
        )
