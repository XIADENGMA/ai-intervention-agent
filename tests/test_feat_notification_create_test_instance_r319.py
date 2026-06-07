"""R319 · ``NotificationManager._create_test_instance()`` 集中化 test
isolation helper invariant (test-isolation pattern 2nd app)。

背景
----

R316 (cycle-33 #A1, 5a15a6c) 修复了 R145 ``TestStreakInRealNotificationManager
SendPath`` 间歇性 flake — 通过在 setUp 显式补充缺失的 3 个 instance attr。
这是 **test-isolation pattern 1st app** (单点修复, "**修补**"模式)。

R319 (cycle-33 #A2, 本 commit) 是 **2nd app** (**收编**模式):

- 把 R316 的"R145 setUp 维护 13 行属性列表"逻辑收编到 NotificationManager
  自己暴露的 ``_create_test_instance()`` classmethod
- R145 setUp 现在只 1 行: ``self.mgr = NotificationManager._create_test_
  instance()``
- 未来 ``NotificationManager.__init__`` 加新 instance attr 时, 只要同步
  更新 ``_create_test_instance()``, 所有 caller 自动受益, 不再需要每个
  setUp 都维护一份属性列表

**Pattern lineage** (test-isolation):

- 1st app: R316 — R145 setUp 手动补充缺失 attr (单点修复)
- **2nd app: R319 (本 commit)** — NotificationManager 自己提供集中化
  ``_create_test_instance()`` API + R145 1st caller 迁移

**R319 invariant 锁定的契约**:

1. ``_create_test_instance()`` classmethod 存在且可调用
2. 返回值是 ``NotificationManager`` instance, **不**等于 singleton
   ``_instance`` (即每次返回 fresh instance)
3. 初始化全部 ``REQUIRED_R316_ATTRS`` + ``REQUIRED_INIT_ATTRS`` (与
   ``__init__`` 对齐, 但不读 config / 不启 worker)
4. ``config`` 是默认 ``NotificationConfig()`` (不读文件)
5. ``_executor`` is ``None`` (测试不启动后台 worker)
6. 多次调用返回**不同** instance (每个测试一个独立 instance)
7. 端到端: ``_send_single_notification`` 在 helper 实例上**不**抛
   ``AttributeError`` (R316 contract 的传递)
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC = REPO_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


REQUIRED_R319_LOCKS = (
    "_stats_lock",
    "_providers_lock",
    "_callbacks_lock",
    "_delayed_timers_lock",
    "_queue_lock",
    "_config_lock",
)
"""``_create_test_instance()`` 必须初始化的 6 个 lock 字段。"""

REQUIRED_R319_STATE_DICTS = (
    "_providers",
    "_stats",
    "_callbacks",
    "_delayed_timers",
    "_provider_latency_histograms",
    "_finalized_event_ids",
    "_event_queue",
)
"""``_create_test_instance()`` 必须初始化的 7 个 state dict/list 字段。"""

REQUIRED_R319_LIFECYCLE_ATTRS = (
    "_executor",
    "_worker_thread",
    "_stop_event",
    "_shutdown_called",
    "_inflight_persisted_ids",
    "_inflight_seen_at_startup",
    "_finalized_max_size",
    "_config_file_mtime",
    "_initialized",
    "config",
)
"""``_create_test_instance()`` 必须初始化的 lifecycle / scalar attrs。"""

R316_ATTRS_SUBSET = (
    "_provider_latency_histograms",
    "_finalized_event_ids",
    "_finalized_max_size",
)
"""R316 锁定的 3 个 attr — R319 必须**继承覆盖**, 是 contract 传递的最小集。"""


class TestR319HelperExists:
    """Layer 1: ``_create_test_instance`` classmethod 必须存在且签名正确。"""

    def test_method_exists(self):
        from ai_intervention_agent.notification_manager import NotificationManager

        assert hasattr(NotificationManager, "_create_test_instance"), (
            "R319: NotificationManager._create_test_instance() must exist "
            "(test-isolation pattern 2nd app)"
        )
        assert callable(NotificationManager._create_test_instance)

    def test_method_is_classmethod(self):
        from ai_intervention_agent.notification_manager import NotificationManager

        # classmethod 的 __self__ 是 class 本身
        bound = NotificationManager._create_test_instance
        # classmethod 在 class 上访问时是 bound method, __self__ 应该是 cls
        assert getattr(bound, "__self__", None) is NotificationManager, (
            "R319: _create_test_instance must be a @classmethod"
        )


class TestR319InstanceIsNotSingleton:
    """Layer 2: 返回值必须是 fresh instance, 不是 singleton ``_instance``。
    多次调用返回**不同** instance。"""

    def test_returns_instance_of_notification_manager(self):
        from ai_intervention_agent.notification_manager import NotificationManager

        inst = NotificationManager._create_test_instance()
        assert isinstance(inst, NotificationManager), (
            f"R319: must return NotificationManager instance, got {type(inst).__name__}"
        )

    def test_multiple_calls_return_different_instances(self):
        from ai_intervention_agent.notification_manager import NotificationManager

        inst_a = NotificationManager._create_test_instance()
        inst_b = NotificationManager._create_test_instance()
        assert inst_a is not inst_b, (
            "R319: _create_test_instance() must return DIFFERENT instances "
            "on each call (each test gets its own fresh isolated instance). "
            "Otherwise it would just be the singleton, defeating the purpose."
        )


class TestR319InstanceHasAllRequiredAttrs:
    """Layer 3: helper 返回的 instance 必须初始化全部 attr (locks / dicts /
    lifecycle)。"""

    def _fresh(self):
        from ai_intervention_agent.notification_manager import NotificationManager

        return NotificationManager._create_test_instance()

    def test_all_locks_present(self, subtests):
        inst = self._fresh()
        for attr in REQUIRED_R319_LOCKS:
            with subtests.test(attr=attr):
                assert hasattr(inst, attr), (
                    f"R319: _create_test_instance must init lock `{attr}`"
                )
                # 验证是真的 lock (有 acquire / release method)
                obj = getattr(inst, attr)
                assert hasattr(obj, "acquire") and hasattr(obj, "release"), (
                    f"R319: `{attr}` is not a Lock-like object: {type(obj).__name__}"
                )

    def test_all_state_dicts_present(self, subtests):
        inst = self._fresh()
        for attr in REQUIRED_R319_STATE_DICTS:
            with subtests.test(attr=attr):
                assert hasattr(inst, attr), (
                    f"R319: _create_test_instance must init state attr `{attr}`"
                )

    def test_all_lifecycle_attrs_present(self, subtests):
        inst = self._fresh()
        for attr in REQUIRED_R319_LIFECYCLE_ATTRS:
            with subtests.test(attr=attr):
                assert hasattr(inst, attr), (
                    f"R319: _create_test_instance must init lifecycle attr `{attr}`"
                )

    def test_r316_attrs_subset_covered(self, subtests):
        """R319 必须继承 R316 锁定的 3 个 attr (contract 传递)。"""
        inst = self._fresh()
        for attr in R316_ATTRS_SUBSET:
            with subtests.test(attr=attr):
                assert hasattr(inst, attr), (
                    f"R319 must inherit R316 contract: `{attr}` must be "
                    f"initialized. This is the **same** attr that R316 "
                    f"single-point fix required R145 setUp to init manually."
                )


class TestR319InstanceDefaultsAreSafe:
    """Layer 4: helper 返回的 instance 默认值是安全的 (test-friendly)。
    - executor is None (不启 worker)
    - config 是 fresh NotificationConfig (不读文件)
    - _initialized is True (避免触发 __init__)
    - state dicts/sets 都是空的 / empty"""

    def test_executor_is_none(self):
        from ai_intervention_agent.notification_manager import NotificationManager

        inst = NotificationManager._create_test_instance()
        assert inst._executor is None, (
            "R319: _executor must be None to skip background worker startup"
        )

    def test_config_is_fresh_notification_config(self):
        from ai_intervention_agent.notification_manager import (
            NotificationConfig,
            NotificationManager,
        )

        inst = NotificationManager._create_test_instance()
        assert isinstance(inst.config, NotificationConfig), (
            f"R319: inst.config must be NotificationConfig, got "
            f"{type(inst.config).__name__}"
        )

    def test_initialized_is_true(self):
        from ai_intervention_agent.notification_manager import NotificationManager

        inst = NotificationManager._create_test_instance()
        assert inst._initialized is True, (
            "R319: _initialized must be True to prevent __init__() from "
            "re-running and re-reading config"
        )

    def test_state_dicts_are_empty(self):
        from ai_intervention_agent.notification_manager import NotificationManager

        inst = NotificationManager._create_test_instance()
        assert inst._providers == {}
        assert inst._callbacks == {}
        assert inst._delayed_timers == {}
        assert inst._provider_latency_histograms == {}
        assert inst._finalized_event_ids == {}
        assert inst._inflight_persisted_ids == set()
        assert inst._inflight_seen_at_startup == []
        assert inst._event_queue == []


class TestR319EndToEndRuntimeContract:
    """Layer 5 (runtime contract, 最强): 调 helper 后, _send_single_notification
    完整流程**不**抛 AttributeError, success_streak 正确累加。

    这是 R316 Layer 4 runtime contract 的传递验证 — R316 验证 R145 setUp
    后 send 路径不 throw, R319 验证 helper 模式同样不 throw。"""

    def test_send_path_does_not_raise_after_helper(self):
        from unittest.mock import MagicMock

        from ai_intervention_agent.notification_manager import (
            NotificationEvent,
            NotificationManager,
            NotificationType,
        )
        from ai_intervention_agent.notification_models import NotificationTrigger

        inst = NotificationManager._create_test_instance()

        prov = MagicMock()
        prov.send.return_value = True
        inst._providers[NotificationType.BARK] = prov

        event = NotificationEvent(
            id="r319-t1",
            title="t",
            message="m",
            trigger=NotificationTrigger.IMMEDIATE,
            types=[NotificationType.BARK],
        )
        ok = inst._send_single_notification(NotificationType.BARK, event)

        assert ok is True
        bark = inst._stats["providers"]["bark"]
        assert bark["success_streak"] == 1, (
            f"R319 runtime contract: success_streak should be 1 after 1 "
            f"successful send, got {bark['success_streak']} — helper "
            f"missing an attr probably."
        )
        assert bark["failure_streak"] == 0


class TestR319LineageMarker:
    """Pattern lineage marker — R319 是 test-isolation pattern 2nd app。"""

    def test_this_file_contains_r319_marker(self):
        text = Path(__file__).read_text(encoding="utf-8")
        assert "R319" in text
        assert "test-isolation" in text.lower() or "test isolation" in text.lower()

    def test_this_file_references_prior_app_r316(self):
        text = Path(__file__).read_text(encoding="utf-8")
        assert "R316" in text, (
            "R319 docstring must cite R316 as test-isolation pattern 1st app"
        )

    def test_this_file_documents_pattern(self):
        text = Path(__file__).read_text(encoding="utf-8")
        for kw in (
            "2nd app",
            "_create_test_instance",
            "REQUIRED_R319_LOCKS",
            "REQUIRED_R319_STATE_DICTS",
            "R316_ATTRS_SUBSET",
        ):
            assert kw in text, f"R319 docstring missing keyword: {kw!r}"
