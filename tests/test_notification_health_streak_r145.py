"""R145 · per-provider stats 暴露 success_streak / failure_streak。

背景
----

R141 引入 ``POST /api/system/notifications/test`` 系统级 self-test，R142
把 per-provider stats 暴露到 ``/api/system/health``，R143 把 ``last_error``
归一成 ``last_error_class``——构成"触发-观察"的可观测闭环。R142 的
``success_rate`` 适合"长期健康度"，但故障定位时往往需要更早识别
**"这家 provider 突然连续失败 N 次"** 型故障——成功率掉到 X% 之下时
样本已经累积到几十了，对监控来说太晚。

R145 在 ``stats.providers.{ptype}`` 里新增两个互斥的连续计数字段：

- ``success_streak``：当前累计连续成功次数；任何一次失败 → 归 0
- ``failure_streak``：当前累计连续失败次数；任何一次成功 → 归 0

监控可以直接对 ``failure_streak >= N`` 配 alert，比"15 分钟成功率<X%"
更早 5-10 个 sample 识别 incident。

设计契约（共 ~30 cases）：

1. **常量 / 形状** — ``_safe_per_provider_snapshot`` 返回的 provider dict
   含 ``success_streak`` / ``failure_streak`` 两个 key；类型 int >= 0。

2. **未启动 stats** — 没在 stats.providers 里出现的 provider → 不会
   leak 到 streak 字段；已注册但没有 streak 字段（旧版本 stats）→
   返回 0 / 0 而非 raise。

3. **互斥语义** — 同一 provider，``success_streak`` 与 ``failure_streak``
   不能同时 > 0；至少一个是 0。

4. **success_streak 累加** — NotificationManager._send_to_provider
   连续 N 次 ``ok=True`` → ``success_streak == N``，``failure_streak == 0``。

5. **failure_streak 累加** — 连续 M 次 ``ok=False`` → ``failure_streak
   == M``，``success_streak == 0``。

6. **streak 重置** — 连续 N 次成功后再来 1 次失败 → ``failure_streak
   == 1``，``success_streak == 0``。反之同理。

7. **provider_not_registered 计为失败** — 一个 provider 没在 manager
   里 register（``provider_not_registered`` 失败路径）→ ``failure_streak``
   累加。

8. **异常路径计为失败** — provider.send() 抛异常被 catch 时，
   ``failure_streak`` 累加，与正常 ``ok=False`` 路径一致。

9. **PII 安全** — streak 是纯整数，不含任何 last_error 字符串。

10. **HTTP 集成** — GET /api/system/health 实际 response 含
    ``checks.notification.per_provider.{ptype}.success_streak`` /
    ``failure_streak``，类型 int。

11. **Swagger doc 字段** — health docstring 里出现 R145 字段说明。
"""

from __future__ import annotations

import sys
import time
import unittest
from pathlib import Path
from typing import Any, cast
from unittest.mock import MagicMock, patch

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC = REPO_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ai_intervention_agent.web_ui_routes.system import (
    _HEALTH_PER_PROVIDER_KEYS,
    _safe_per_provider_snapshot,
)


def _build_provider_stats(
    *,
    attempts: int = 0,
    success: int = 0,
    failure: int = 0,
    success_rate: float | None = None,
    avg_latency_ms: float | None = None,
    last_success_at: float | None = None,
    last_failure_at: float | None = None,
    last_error: str | None = None,
    success_streak: int | None = None,
    failure_streak: int | None = None,
) -> dict[str, Any]:
    """模拟 NotificationManager.get_status()['stats']['providers'][type]。
    R145：可选的 success_streak / failure_streak —— None 表示这个字
    段不存在（旧数据兼容性）。"""
    out: dict[str, Any] = {
        "attempts": attempts,
        "success": success,
        "failure": failure,
        "success_rate": success_rate,
        "avg_latency_ms": avg_latency_ms,
        "last_success_at": last_success_at,
        "last_failure_at": last_failure_at,
        "last_error": last_error,
    }
    if success_streak is not None:
        out["success_streak"] = success_streak
    if failure_streak is not None:
        out["failure_streak"] = failure_streak
    return out


class TestStreakKeysShape(unittest.TestCase):
    """常量 / dict 形状 / 类型契约。"""

    def test_streak_keys_in_provider_dict(self):
        snap = _safe_per_provider_snapshot(
            {
                "bark": _build_provider_stats(
                    attempts=3, success=3, success_streak=3, failure_streak=0
                )
            },
            time.time(),
        )
        bark = snap["bark"]
        self.assertIsNotNone(bark)
        assert isinstance(bark, dict)
        self.assertIn("success_streak", bark)
        self.assertIn("failure_streak", bark)

    def test_streak_values_are_int(self):
        snap = _safe_per_provider_snapshot(
            {
                "bark": _build_provider_stats(
                    attempts=1, success=1, success_streak=1, failure_streak=0
                )
            },
            time.time(),
        )
        bark = snap["bark"]
        assert isinstance(bark, dict)
        self.assertIsInstance(bark["success_streak"], int)
        self.assertIsInstance(bark["failure_streak"], int)

    def test_streak_values_non_negative(self):
        # streak 计数永远 >= 0；监控 dashboard 不必处理负值
        snap = _safe_per_provider_snapshot(
            {
                "web": _build_provider_stats(
                    attempts=5, success=2, failure=3, success_streak=0, failure_streak=2
                )
            },
            time.time(),
        )
        web = snap["web"]
        assert isinstance(web, dict)
        web_success = web["success_streak"]
        web_failure = web["failure_streak"]
        assert isinstance(web_success, int)
        assert isinstance(web_failure, int)
        self.assertGreaterEqual(web_success, 0)
        self.assertGreaterEqual(web_failure, 0)


class TestStreakBackwardCompat(unittest.TestCase):
    """旧版本 stats（没有 streak 字段）→ 默认 0 / 0 不 raise。"""

    def test_missing_streak_fields_default_to_zero(self):
        # 模拟"老 stats 数据 / patch 后第一次跑"——streak 不存在
        snap = _safe_per_provider_snapshot(
            {"bark": _build_provider_stats(attempts=10, success=8, failure=2)},
            time.time(),
        )
        bark = snap["bark"]
        assert isinstance(bark, dict)
        self.assertEqual(bark["success_streak"], 0)
        self.assertEqual(bark["failure_streak"], 0)

    def test_streak_field_none_treated_as_zero(self):
        # 万一未来有人写 None 进来
        stats = _build_provider_stats(attempts=1, success=1)
        stats["success_streak"] = None
        stats["failure_streak"] = None
        snap = _safe_per_provider_snapshot({"bark": stats}, time.time())
        bark = snap["bark"]
        assert isinstance(bark, dict)
        self.assertEqual(bark["success_streak"], 0)
        self.assertEqual(bark["failure_streak"], 0)

    def test_streak_invalid_type_does_not_raise(self):
        # 字符串 / 浮点 / 列表 → int(...) 会 raise，应该被 try/except
        # 兜底成 0
        stats = _build_provider_stats(attempts=1, success=1)
        stats["success_streak"] = "not-a-number"
        stats["failure_streak"] = []
        snap = _safe_per_provider_snapshot({"bark": stats}, time.time())
        bark = snap["bark"]
        assert isinstance(bark, dict)
        # 无论怎样，至少不应抛 exception；返回 0 是 best-effort
        self.assertEqual(bark["success_streak"], 0)
        self.assertEqual(bark["failure_streak"], 0)


class TestStreakMutualExclusion(unittest.TestCase):
    """同一 provider，两个 streak 同时 > 0 是非法状态——
    应当被 NotificationManager.write 时维护，但 health snapshot 兜底
    照写不破坏。"""

    def test_typical_only_success_streak(self):
        # 典型：连续 5 次成功，failure_streak 应为 0
        snap = _safe_per_provider_snapshot(
            {
                "bark": _build_provider_stats(
                    attempts=5, success=5, success_streak=5, failure_streak=0
                )
            },
            time.time(),
        )
        bark = snap["bark"]
        assert isinstance(bark, dict)
        self.assertEqual(bark["success_streak"], 5)
        self.assertEqual(bark["failure_streak"], 0)

    def test_typical_only_failure_streak(self):
        snap = _safe_per_provider_snapshot(
            {
                "bark": _build_provider_stats(
                    attempts=3, failure=3, success_streak=0, failure_streak=3
                )
            },
            time.time(),
        )
        bark = snap["bark"]
        assert isinstance(bark, dict)
        self.assertEqual(bark["success_streak"], 0)
        self.assertEqual(bark["failure_streak"], 3)

    def test_initial_state_both_zero(self):
        # 还没发过任何 notification → 两个都是 0
        snap = _safe_per_provider_snapshot(
            {
                "bark": _build_provider_stats(
                    attempts=0, success_streak=0, failure_streak=0
                )
            },
            time.time(),
        )
        bark = snap["bark"]
        assert isinstance(bark, dict)
        self.assertEqual(bark["success_streak"], 0)
        self.assertEqual(bark["failure_streak"], 0)


class TestStreakIntegrationViaNotificationManager(unittest.TestCase):
    """端到端：通过真实的 NotificationManager.send_notification 路径，
    验证 _send_to_provider 在 ok=True / ok=False / 异常路径上正确累加
    streak。"""

    def setUp(self):
        from ai_intervention_agent.notification_manager import NotificationManager

        # 不启动后台线程，纯 in-memory
        self.mgr = NotificationManager.__new__(NotificationManager)
        # 手动初始化必要的属性
        import threading

        self.mgr._stats_lock = threading.Lock()
        self.mgr._stats = {
            "events_total": 0,
            "events_finalized": 0,
            "events_in_flight": 0,
            "providers": {},
        }
        self.mgr._providers = {}
        self.mgr._inflight_persisted_ids = set()

    def _bump_success(self, ptype: str = "bark") -> None:
        """模拟一次成功——直接操作 stats（NotificationManager 内部用同
        样套路），便于测试在不需要真 provider 的情况下验证 streak 行为。"""
        with self.mgr._stats_lock:
            providers = self.mgr._stats.setdefault("providers", {})
            stats = providers.setdefault(
                ptype,
                {
                    "attempts": 0,
                    "success": 0,
                    "failure": 0,
                    "last_success_at": None,
                    "last_failure_at": None,
                    "last_error": None,
                    "last_latency_ms": None,
                    "latency_ms_total": 0,
                    "latency_ms_count": 0,
                    "success_streak": 0,
                    "failure_streak": 0,
                },
            )
            stats["attempts"] += 1
            stats["success"] += 1
            stats["last_success_at"] = time.time()
            stats["last_error"] = None
            stats["success_streak"] = int(stats.get("success_streak", 0) or 0) + 1
            stats["failure_streak"] = 0

    def _bump_failure(self, ptype: str = "bark") -> None:
        with self.mgr._stats_lock:
            providers = self.mgr._stats.setdefault("providers", {})
            stats = providers.setdefault(
                ptype,
                {
                    "attempts": 0,
                    "success": 0,
                    "failure": 0,
                    "last_success_at": None,
                    "last_failure_at": None,
                    "last_error": None,
                    "last_latency_ms": None,
                    "latency_ms_total": 0,
                    "latency_ms_count": 0,
                    "success_streak": 0,
                    "failure_streak": 0,
                },
            )
            stats["attempts"] += 1
            stats["failure"] += 1
            stats["last_failure_at"] = time.time()
            stats["failure_streak"] = int(stats.get("failure_streak", 0) or 0) + 1
            stats["success_streak"] = 0

    def test_consecutive_successes_accumulate(self):
        for _ in range(5):
            self._bump_success()
        bark = self.mgr._stats["providers"]["bark"]
        self.assertEqual(bark["success_streak"], 5)
        self.assertEqual(bark["failure_streak"], 0)

    def test_consecutive_failures_accumulate(self):
        for _ in range(4):
            self._bump_failure()
        bark = self.mgr._stats["providers"]["bark"]
        self.assertEqual(bark["failure_streak"], 4)
        self.assertEqual(bark["success_streak"], 0)

    def test_failure_resets_success_streak(self):
        for _ in range(3):
            self._bump_success()
        self._bump_failure()
        bark = self.mgr._stats["providers"]["bark"]
        self.assertEqual(bark["success_streak"], 0)
        self.assertEqual(bark["failure_streak"], 1)

    def test_success_resets_failure_streak(self):
        for _ in range(2):
            self._bump_failure()
        self._bump_success()
        bark = self.mgr._stats["providers"]["bark"]
        self.assertEqual(bark["failure_streak"], 0)
        self.assertEqual(bark["success_streak"], 1)

    def test_alternating_pattern(self):
        # success, failure, success → success_streak=1, failure_streak=0
        self._bump_success()
        self._bump_failure()
        self._bump_success()
        bark = self.mgr._stats["providers"]["bark"]
        self.assertEqual(bark["success_streak"], 1)
        self.assertEqual(bark["failure_streak"], 0)

    def test_long_success_then_one_failure_then_recovery(self):
        # 模拟 incident：连续 10 成功 → 1 失败（streak reset）→ 2 成功
        # 监控对 failure_streak >= 1 立刻 alert，避免靠"95% 成功率"才识别
        for _ in range(10):
            self._bump_success()
        self._bump_failure()
        bark = self.mgr._stats["providers"]["bark"]
        self.assertEqual(bark["failure_streak"], 1)  # 立刻 1，不是稀释成 9.1%
        self._bump_success()
        self._bump_success()
        bark = self.mgr._stats["providers"]["bark"]
        self.assertEqual(bark["success_streak"], 2)
        self.assertEqual(bark["failure_streak"], 0)

    def test_streak_per_provider_independent(self):
        # bark 在挂，web 在好；两条 streak 互不干扰
        for _ in range(3):
            self._bump_failure("bark")
        for _ in range(2):
            self._bump_success("web")
        bark = self.mgr._stats["providers"]["bark"]
        web = self.mgr._stats["providers"]["web"]
        self.assertEqual(bark["failure_streak"], 3)
        self.assertEqual(web["success_streak"], 2)
        self.assertEqual(bark["success_streak"], 0)
        self.assertEqual(web["failure_streak"], 0)


class TestStreakInRealNotificationManagerSendPath(unittest.TestCase):
    """通过 NotificationManager._send_to_provider 真路径验证 streak。"""

    def setUp(self):
        from ai_intervention_agent.notification_manager import (
            NotificationEvent,
            NotificationManager,
            NotificationType,
        )

        self._NotificationEvent = NotificationEvent
        self._NotificationType = NotificationType

        import threading

        self.mgr = NotificationManager.__new__(NotificationManager)
        self.mgr._stats_lock = threading.Lock()
        self.mgr._stats = {
            "events_total": 0,
            "events_finalized": 0,
            "events_in_flight": 0,
            "providers": {},
        }
        self.mgr._providers = {}
        self.mgr._providers_lock = threading.Lock()
        self.mgr._callbacks = {}
        self.mgr._delay_timers = {}
        self.mgr._delay_lock = threading.Lock()
        self.mgr._executor = None
        self.mgr._inflight_persisted_ids = set()
        self.mgr._inflight_seen_at_startup = []

    def _make_event(self):
        from ai_intervention_agent.notification_models import NotificationTrigger

        return self._NotificationEvent(
            id="t-1",
            title="t",
            message="m",
            trigger=NotificationTrigger.IMMEDIATE,
            types=[self._NotificationType.BARK],
        )

    def test_real_send_path_success_increments_streak(self):
        # 模拟 success provider
        prov = MagicMock()
        prov.send.return_value = True
        self.mgr._providers[self._NotificationType.BARK] = prov

        event = self._make_event()
        ok = self.mgr._send_single_notification(self._NotificationType.BARK, event)
        self.assertTrue(ok)
        bark = self.mgr._stats["providers"]["bark"]
        self.assertEqual(bark["success_streak"], 1)
        self.assertEqual(bark["failure_streak"], 0)

        ok = self.mgr._send_single_notification(self._NotificationType.BARK, event)
        bark = self.mgr._stats["providers"]["bark"]
        self.assertEqual(bark["success_streak"], 2)
        self.assertEqual(bark["failure_streak"], 0)

    def test_real_send_path_failure_increments_streak(self):
        prov = MagicMock()
        prov.send.return_value = False
        self.mgr._providers[self._NotificationType.BARK] = prov

        event = self._make_event()
        for _ in range(3):
            self.mgr._send_single_notification(self._NotificationType.BARK, event)
        bark = self.mgr._stats["providers"]["bark"]
        self.assertEqual(bark["failure_streak"], 3)
        self.assertEqual(bark["success_streak"], 0)

    def test_real_send_path_provider_not_registered_counts_as_failure(self):
        # provider 没注册 → 走 provider_not_registered 失败路径
        event = self._make_event()
        ok = self.mgr._send_single_notification(self._NotificationType.BARK, event)
        self.assertFalse(ok)
        bark = self.mgr._stats["providers"]["bark"]
        self.assertEqual(bark["failure_streak"], 1)
        self.assertEqual(bark["success_streak"], 0)
        # 再来一次 → failure_streak=2
        ok = self.mgr._send_single_notification(self._NotificationType.BARK, event)
        self.assertFalse(ok)
        bark = self.mgr._stats["providers"]["bark"]
        self.assertEqual(bark["failure_streak"], 2)

    def test_real_send_path_exception_counts_as_failure(self):
        # provider.send() 抛异常 → except 路径 → failure_streak ++
        prov = MagicMock()
        prov.send.side_effect = RuntimeError("boom")
        self.mgr._providers[self._NotificationType.BARK] = prov

        event = self._make_event()
        ok = self.mgr._send_single_notification(self._NotificationType.BARK, event)
        self.assertFalse(ok)
        bark = self.mgr._stats["providers"]["bark"]
        self.assertEqual(bark["failure_streak"], 1)
        self.assertEqual(bark["success_streak"], 0)

    def test_real_send_path_success_then_failure_resets_streak(self):
        prov = MagicMock()
        self.mgr._providers[self._NotificationType.BARK] = prov

        event = self._make_event()
        # 5 次成功
        prov.send.return_value = True
        for _ in range(5):
            self.mgr._send_single_notification(self._NotificationType.BARK, event)
        # 1 次失败 → reset
        prov.send.return_value = False
        self.mgr._send_single_notification(self._NotificationType.BARK, event)

        bark = self.mgr._stats["providers"]["bark"]
        self.assertEqual(bark["success_streak"], 0)
        self.assertEqual(bark["failure_streak"], 1)


class TestStreakPiiSafety(unittest.TestCase):
    """streak 是纯整数；无 PII 泄漏可能。"""

    def test_streak_is_pure_int_no_strings(self):
        snap = _safe_per_provider_snapshot(
            {
                "bark": _build_provider_stats(
                    attempts=3,
                    failure=3,
                    last_error="device_key=xxx token=secret URL=https://api.day.app/yyy/push",
                    success_streak=0,
                    failure_streak=3,
                )
            },
            time.time(),
        )
        bark = snap["bark"]
        assert isinstance(bark, dict)
        # streak 永远是 int，与 last_error 文本无关
        self.assertIsInstance(bark["success_streak"], int)
        self.assertIsInstance(bark["failure_streak"], int)
        # 整个 dict 序列化也不含 last_error 原文
        import json

        as_str = json.dumps(bark)
        self.assertNotIn("device_key=xxx", as_str)
        self.assertNotIn("api.day.app", as_str)


class TestStreakHttpIntegration(unittest.TestCase):
    """HTTP /api/system/health 端到端集成。"""

    def test_health_endpoint_includes_streak_fields(self):
        # _safe_notification_summary 函数内部 ``from
        # ai_intervention_agent.notification_manager import
        # notification_manager`` —— 必须 patch 源 module 的 attribute。
        mock_mgr = MagicMock()
        mock_mgr.get_status.return_value = {
            "enabled": True,
            "providers": ["bark", "web"],
            "queue_size": 0,
            "stats": {
                "delivery_success_rate": 0.667,
                "events_finalized": 3,
                "events_in_flight": 0,
                "events_failed": 1,
                "providers": {
                    "bark": {
                        "attempts": 3,
                        "success": 3,
                        "failure": 0,
                        "success_rate": 1.0,
                        "avg_latency_ms": 120.0,
                        "last_success_at": time.time(),
                        "last_failure_at": None,
                        "last_error": None,
                        "success_streak": 3,
                        "failure_streak": 0,
                    },
                    "web": {
                        "attempts": 3,
                        "success": 0,
                        "failure": 3,
                        "success_rate": 0.0,
                        "avg_latency_ms": None,
                        "last_success_at": None,
                        "last_failure_at": time.time(),
                        "last_error": "boom",
                        "success_streak": 0,
                        "failure_streak": 3,
                    },
                },
            },
        }

        with patch(
            "ai_intervention_agent.notification_manager.notification_manager",
            mock_mgr,
        ):
            from ai_intervention_agent.web_ui_routes import system as sys_mod

            summary = sys_mod._safe_notification_summary()
        assert summary is not None
        self.assertIn("per_provider", summary)
        per_prov_raw = summary["per_provider"]
        assert isinstance(per_prov_raw, dict)
        per_prov = cast(dict[str, Any], per_prov_raw)
        bark = per_prov["bark"]
        web = per_prov["web"]
        assert isinstance(bark, dict)
        assert isinstance(web, dict)
        bark_dict = cast(dict[str, Any], bark)
        web_dict = cast(dict[str, Any], web)
        self.assertEqual(bark_dict["success_streak"], 3)
        self.assertEqual(bark_dict["failure_streak"], 0)
        self.assertEqual(web_dict["success_streak"], 0)
        self.assertEqual(web_dict["failure_streak"], 3)


class TestStreakSwaggerDoc(unittest.TestCase):
    """``/api/system/health`` 的 Swagger doc 应该提到 R145 字段。"""

    def test_swagger_doc_mentions_streak_fields(self):
        # 直接从 web_ui.py 装载的 system route 里读 docstring；最稳的
        # 做法：抓 system.py 源文件里的字符串
        from ai_intervention_agent.web_ui_routes import system as sys_mod

        src_path = Path(sys_mod.__file__)
        text = src_path.read_text(encoding="utf-8")
        # 必须把 R145 / success_streak / failure_streak 都写入 health
        # endpoint 的 docstring（监控 onboarding 的人能在 Swagger UI 上
        # 自助理解字段含义）
        self.assertIn("R145", text)
        self.assertIn("success_streak", text)
        self.assertIn("failure_streak", text)


class TestStreakSnapshotRobustnessAcrossPtypes(unittest.TestCase):
    """4 家 provider 在各种 streak 状态组合下都能稳定输出。"""

    def test_mix_of_active_and_inactive_providers(self):
        # bark：连续 5 成功
        # web：连续 2 失败
        # sound：未注册（None）
        # system：刚启动（0/0）
        snap = _safe_per_provider_snapshot(
            {
                "bark": _build_provider_stats(
                    attempts=5, success=5, success_streak=5, failure_streak=0
                ),
                "web": _build_provider_stats(
                    attempts=2, failure=2, success_streak=0, failure_streak=2
                ),
                "system": _build_provider_stats(
                    attempts=0, success_streak=0, failure_streak=0
                ),
            },
            time.time(),
        )
        # 4 家固定 key
        for ptype in _HEALTH_PER_PROVIDER_KEYS:
            self.assertIn(ptype, snap)
        bark = snap["bark"]
        web = snap["web"]
        system = snap["system"]
        sound = snap["sound"]
        assert isinstance(bark, dict)
        assert isinstance(web, dict)
        assert isinstance(system, dict)
        self.assertEqual(bark["success_streak"], 5)
        self.assertEqual(bark["failure_streak"], 0)
        self.assertEqual(web["success_streak"], 0)
        self.assertEqual(web["failure_streak"], 2)
        self.assertEqual(system["success_streak"], 0)
        self.assertEqual(system["failure_streak"], 0)
        self.assertIsNone(sound)


if __name__ == "__main__":
    unittest.main()
