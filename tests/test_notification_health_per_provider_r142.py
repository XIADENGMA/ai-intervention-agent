"""R142 · ``/api/system/health`` 暴露 per-provider stats 摘要契约测试。

背景
----

R121-A 已经在 ``checks.notification`` 里暴露 **全局** delivery 成功率，
但故障定位时回不出"是 Bark 挂还是 Web 挂"——这恰是 dashboard 最需要
的下钻维度。NotificationManager 内部其实已经按 provider 维度记录
``stats.providers.{type: {attempts/success/failure/last_success_at/...}}``
（line 1465-1471 的 ``providers_stats`` 拷贝），R121-A 的
``_safe_notification_summary`` 故意 strip 了它（避免 last_error 文本里
含 token / Bark URL 这种 PII）。

R142 在保留同一安全边界的前提下，把"够监控用"的聚合量重新放出：

- attempts / success / failure（计数）
- success_rate（全局已存在，per-provider 新增）
- avg_latency_ms（NotificationManager 已计算，转浮点暴露）
- last_success_age_seconds / last_failure_age_seconds（用 ``now -
  last_*_at`` 算 age 而非绝对时间戳——绝对时间戳跨副本/跨时区无意义）
- last_error_present: bool（刻意 **不** 暴露 last_error 原文本，防 PII；
  详情请看 logs）

设计契约（共 ~25 cases）：

1. **常量 / 形状** — ``_HEALTH_PER_PROVIDER_KEYS`` 是 4 个；
   ``_safe_per_provider_snapshot`` 为每个 key 都生成条目；
   ``_safe_notification_summary`` 返回值含 ``per_provider`` 键。

2. **未注册 provider** — 没在 stats.providers 出现的 provider →
   ``per_provider[ptype]`` 为 ``None``（监控 dashboard 用 stable key
   集合，不会有 KeyError）。

3. **dict 字段全集** — 注册过的 provider，``per_provider[ptype]``
   含 8 个 key 不多不少：``attempts/success/failure/success_rate/
   avg_latency_ms/last_success_age_seconds/last_failure_age_seconds/
   last_error_present``。

4. **success_rate 计算** — attempts=0 → ``None``；attempts>0 →
   读 NotificationManager 已经算好的 ``success_rate`` 浮点。

5. **avg_latency_ms 计算** — latency_ms_count=0 → ``None``；>0 →
   ``latency_ms_total / latency_ms_count``（NotificationManager 已计
   算）。

6. **age 字段单调性** — ``last_success_at`` 距 ``now`` 越久，
   ``last_success_age_seconds`` 越大；不会出现负值（即使时钟回拨
   也 clamp 到 0）。

7. **PII 安全边界** — ``last_error`` 包含 "device_key=xxx" /
   "https://api.day.app/push" / Bark token 等 PII 时，
   ``per_provider[ptype]['last_error_present']=True`` 但 endpoint 返回
   值的 **任何字段** 里都不包含原始字符串内容。

8. **整体 health endpoint 集成** — GET /api/system/health 实际响应
   含 ``checks.notification.per_provider``；4 家 key 都在；类型符合
   契约；HTTP 200 不为 5xx。

9. **空 / 异常 stats fallback** — ``stats.providers`` 不是 dict 时，
   ``per_provider`` 仍返回 4 个 ``None`` 而不是 raise。

10. **Swagger doc 字段** — health docstring 里出现 R142 字段说明
    （字符串"per_provider"、"last_error_present"、"R142"等）。
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
    _safe_notification_summary,
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
) -> dict[str, Any]:
    """造一个跟 NotificationManager.get_status()['stats']['providers'][type]
    同结构的 dict。``success_rate`` / ``avg_latency_ms`` 直接传，模拟
    NotificationManager line 1488-1502 已经在 status 里算好。"""
    return {
        "attempts": attempts,
        "success": success,
        "failure": failure,
        "success_rate": success_rate,
        "avg_latency_ms": avg_latency_ms,
        "last_success_at": last_success_at,
        "last_failure_at": last_failure_at,
        "last_error": last_error,
    }


class TestKeysAndShape(unittest.TestCase):
    """常量 + 形状契约。"""

    def test_health_per_provider_keys_are_four(self):
        self.assertEqual(len(_HEALTH_PER_PROVIDER_KEYS), 4)
        self.assertEqual(
            set(_HEALTH_PER_PROVIDER_KEYS), {"bark", "web", "sound", "system"}
        )

    def test_keys_order_is_stable(self):
        # 顺序固定：bark, web, sound, system —— 监控 dashboard 模板按
        # 这个顺序给四列，要是 reorder 会破 dashboard 兼容性
        self.assertEqual(_HEALTH_PER_PROVIDER_KEYS, ("bark", "web", "sound", "system"))

    def test_snapshot_contains_all_four_keys_when_empty(self):
        snap = _safe_per_provider_snapshot({}, time.time())
        self.assertEqual(set(snap.keys()), set(_HEALTH_PER_PROVIDER_KEYS))
        # 空 stats —— 每个 provider 都是 None
        for ptype in _HEALTH_PER_PROVIDER_KEYS:
            self.assertIsNone(snap[ptype])

    def test_summary_returns_per_provider_key(self):
        with patch(
            "ai_intervention_agent.web_ui_routes.system.notification_manager",
            create=True,
        ):
            from ai_intervention_agent.web_ui_routes import system as sys_mod

            mock_mgr = MagicMock()
            mock_mgr.get_status.return_value = {
                "enabled": True,
                "providers": ["bark"],
                "queue_size": 0,
                "stats": {
                    "delivery_success_rate": 1.0,
                    "events_finalized": 1,
                    "events_in_flight": 0,
                    "providers": {},
                },
            }
            with patch.object(sys_mod, "_safe_notification_summary") as _patched:
                # 直接调真实函数（绕开 patch），重要的是 import path
                _patched.side_effect = lambda: _safe_notification_summary()
                with patch(
                    "ai_intervention_agent.notification_manager.notification_manager",
                    mock_mgr,
                ):
                    summary = _safe_notification_summary()
        assert summary is not None
        self.assertIn("per_provider", summary)


class TestUnregisteredProviderIsNone(unittest.TestCase):
    """未注册 provider → None；防 KeyError 暴露给监控。"""

    def test_only_bark_in_stats(self):
        bark = _build_provider_stats(attempts=10, success=8, success_rate=0.8)
        snap = _safe_per_provider_snapshot({"bark": bark}, time.time())
        self.assertIsNotNone(snap["bark"])
        for ptype in ("web", "sound", "system"):
            self.assertIsNone(snap[ptype])

    def test_unknown_provider_in_stats_is_ignored(self):
        # 假如哪天有人手抖往 stats 里加了 "unknown" provider —— 不应
        # 出现在 health 返回里
        snap = _safe_per_provider_snapshot(
            {"unknown": _build_provider_stats(attempts=1)}, time.time()
        )
        self.assertNotIn("unknown", snap)
        # 4 家固定 key 仍然是 None
        for ptype in _HEALTH_PER_PROVIDER_KEYS:
            self.assertIsNone(snap[ptype])


class TestProviderDictShape(unittest.TestCase):
    """注册过的 provider，dict 形状 8 个 key 不多不少。"""

    # R143：在 R142 8 个 key 基础上新增 ``last_error_class``——把
    # ``last_error`` 字符串归一成 ``client_error`` / ``server_error``
    # / ``network_error`` / ``timeout`` / ``not_registered`` / ``unknown``
    # / ``None`` 之一；与 ``last_error_present`` 互补，PII 边界保持。
    expected_keys = {
        "attempts",
        "success",
        "failure",
        "success_rate",
        "avg_latency_ms",
        "last_success_age_seconds",
        "last_failure_age_seconds",
        "last_error_present",
        "last_error_class",
    }

    def test_eight_keys_exact(self):
        snap = _safe_per_provider_snapshot(
            {"bark": _build_provider_stats(attempts=1, success=1)}, time.time()
        )
        bark = snap["bark"]
        self.assertIsNotNone(bark)
        assert isinstance(bark, dict)
        self.assertEqual(set(bark.keys()), self.expected_keys)

    def test_no_extra_internal_fields_leak(self):
        # last_success_at / latency_ms_total / latency_ms_count 是内部字
        # 段 —— 不应出现在 health 返回里（age 字段已经是聚合形态）
        snap = _safe_per_provider_snapshot(
            {
                "bark": _build_provider_stats(
                    attempts=10,
                    success=8,
                    success_rate=0.8,
                    last_success_at=time.time() - 10,
                )
            },
            time.time(),
        )
        bark = snap["bark"]
        assert isinstance(bark, dict)
        self.assertNotIn("last_success_at", bark)
        self.assertNotIn("last_failure_at", bark)
        self.assertNotIn("latency_ms_total", bark)
        self.assertNotIn("latency_ms_count", bark)


class TestSuccessRateCalculation(unittest.TestCase):
    """success_rate 透传 / attempts=0 → None。"""

    def test_zero_attempts_yields_none(self):
        snap = _safe_per_provider_snapshot(
            {"bark": _build_provider_stats(attempts=0, success_rate=None)},
            time.time(),
        )
        bark = snap["bark"]
        assert isinstance(bark, dict)
        self.assertEqual(bark["attempts"], 0)
        self.assertIsNone(bark["success_rate"])

    def test_passthrough_when_present(self):
        snap = _safe_per_provider_snapshot(
            {
                "bark": _build_provider_stats(
                    attempts=20, success=15, failure=5, success_rate=0.75
                )
            },
            time.time(),
        )
        bark = snap["bark"]
        assert isinstance(bark, dict)
        self.assertEqual(bark["attempts"], 20)
        self.assertEqual(bark["success"], 15)
        self.assertEqual(bark["failure"], 5)
        rate = bark["success_rate"]
        assert isinstance(rate, float)
        self.assertAlmostEqual(rate, 0.75, places=4)


class TestAvgLatencyCalculation(unittest.TestCase):
    """avg_latency_ms 透传 / 缺失 → None。"""

    def test_zero_count_yields_none(self):
        snap = _safe_per_provider_snapshot(
            {"web": _build_provider_stats(attempts=0, avg_latency_ms=None)},
            time.time(),
        )
        web = snap["web"]
        assert isinstance(web, dict)
        self.assertIsNone(web["avg_latency_ms"])

    def test_passthrough_when_present(self):
        snap = _safe_per_provider_snapshot(
            {"web": _build_provider_stats(attempts=10, avg_latency_ms=234.56)},
            time.time(),
        )
        web = snap["web"]
        assert isinstance(web, dict)
        latency = web["avg_latency_ms"]
        assert isinstance(latency, float)
        self.assertAlmostEqual(latency, 234.56, places=2)


class TestAgeMonotonicity(unittest.TestCase):
    """age 字段：相对 now 越远的事件 age 越大；时钟回拨 clamp 0。"""

    def test_recent_success_age_smaller_than_old_success(self):
        now = 1000000.0
        recent = now - 5
        old = now - 3600
        snap_recent = _safe_per_provider_snapshot(
            {"bark": _build_provider_stats(attempts=1, last_success_at=recent)}, now
        )
        snap_old = _safe_per_provider_snapshot(
            {"bark": _build_provider_stats(attempts=1, last_success_at=old)}, now
        )
        bark_recent = snap_recent["bark"]
        bark_old = snap_old["bark"]
        assert isinstance(bark_recent, dict) and isinstance(bark_old, dict)
        recent_age = bark_recent["last_success_age_seconds"]
        old_age = bark_old["last_success_age_seconds"]
        assert isinstance(recent_age, float)
        assert isinstance(old_age, float)
        self.assertLess(recent_age, old_age)

    def test_negative_age_clamped_to_zero(self):
        # 时钟回拨：last_success_at > now —— age 应被 clamp 到 0
        now = 1000.0
        snap = _safe_per_provider_snapshot(
            {"bark": _build_provider_stats(attempts=1, last_success_at=now + 50)}, now
        )
        bark = snap["bark"]
        assert isinstance(bark, dict)
        self.assertEqual(bark["last_success_age_seconds"], 0.0)

    def test_no_last_success_yields_none(self):
        snap = _safe_per_provider_snapshot(
            {"bark": _build_provider_stats(attempts=0, last_success_at=None)},
            time.time(),
        )
        bark = snap["bark"]
        assert isinstance(bark, dict)
        self.assertIsNone(bark["last_success_age_seconds"])

    def test_failure_age_independent_of_success_age(self):
        now = 1000.0
        snap = _safe_per_provider_snapshot(
            {
                "bark": _build_provider_stats(
                    attempts=10,
                    success=5,
                    failure=5,
                    last_success_at=now - 10,
                    last_failure_at=now - 100,
                )
            },
            now,
        )
        bark = snap["bark"]
        assert isinstance(bark, dict)
        self.assertEqual(bark["last_success_age_seconds"], 10.0)
        self.assertEqual(bark["last_failure_age_seconds"], 100.0)


class TestPIIBoundary(unittest.TestCase):
    """last_error 原文本不暴露——防 device_key / 服务器 URL 等 PII。"""

    def test_last_error_string_not_in_output(self):
        evil_err = (
            "Bark API returned 401 for "
            "https://api.day.app/push?device_key=SECRET_KEY_123 "
            "with token=BARK_TOKEN_X"
        )
        snap = _safe_per_provider_snapshot(
            {"bark": _build_provider_stats(attempts=1, failure=1, last_error=evil_err)},
            time.time(),
        )
        bark = snap["bark"]
        assert isinstance(bark, dict)
        # last_error_present 是 True，但原文本任何片段都不应出现在
        # 整个返回 dict 的 stringified 版本里
        self.assertTrue(bark["last_error_present"])
        snap_str = str(snap)
        self.assertNotIn("device_key", snap_str)
        self.assertNotIn("SECRET_KEY_123", snap_str)
        self.assertNotIn("BARK_TOKEN_X", snap_str)
        self.assertNotIn("api.day.app", snap_str)

    def test_last_error_none_yields_present_false(self):
        snap = _safe_per_provider_snapshot(
            {"bark": _build_provider_stats(attempts=1, success=1, last_error=None)},
            time.time(),
        )
        bark = snap["bark"]
        assert isinstance(bark, dict)
        self.assertFalse(bark["last_error_present"])

    def test_last_error_empty_string_yields_present_false(self):
        # 空字符串 == falsy → present=False（与 None 同一语义）
        snap = _safe_per_provider_snapshot(
            {"bark": _build_provider_stats(attempts=1, success=1, last_error="")},
            time.time(),
        )
        bark = snap["bark"]
        assert isinstance(bark, dict)
        self.assertFalse(bark["last_error_present"])


class TestEdgeStatsTypes(unittest.TestCase):
    """异常类型的 providers_stats —— 不抛错。"""

    def test_non_dict_provider_stats_yields_none(self):
        # provider 字段是 str 而不是 dict（数据腐坏）—— 返回 None
        snap = _safe_per_provider_snapshot({"bark": "corrupted"}, time.time())  # type: ignore[dict-item]
        self.assertIsNone(snap["bark"])

    def test_provider_stats_missing_fields_uses_defaults(self):
        # provider 是 dict 但 attempt/success/failure 这种字段都没（空 dict）
        snap = _safe_per_provider_snapshot({"bark": {}}, time.time())
        bark = snap["bark"]
        assert isinstance(bark, dict)
        self.assertEqual(bark["attempts"], 0)
        self.assertEqual(bark["success"], 0)
        self.assertEqual(bark["failure"], 0)
        self.assertIsNone(bark["success_rate"])
        self.assertIsNone(bark["avg_latency_ms"])

    def test_summary_with_non_dict_providers_stats(self):
        # _safe_notification_summary 拿到 stats.providers 不是 dict 时
        mock_mgr = MagicMock()
        mock_mgr.get_status.return_value = {
            "enabled": True,
            "providers": [],
            "queue_size": 0,
            "stats": {
                "delivery_success_rate": None,
                "events_finalized": 0,
                "events_in_flight": 0,
                "providers": "this is not a dict",
            },
        }
        with patch(
            "ai_intervention_agent.notification_manager.notification_manager", mock_mgr
        ):
            result = _safe_notification_summary()

        self.assertIsNotNone(result)
        assert result is not None
        per_prov_raw: object = result["per_provider"]
        assert isinstance(per_prov_raw, dict)
        per_prov = cast("dict[str, Any]", per_prov_raw)
        for ptype in _HEALTH_PER_PROVIDER_KEYS:
            self.assertIn(ptype, per_prov)
            self.assertIsNone(per_prov[ptype])


class TestHealthEndpointIntegration(unittest.TestCase):
    """整体 health endpoint 集成测试——HTTP 客户端真打 GET /api/system/health。"""

    _port: int = 19112
    _ui: Any = None
    _client: Any = None

    @classmethod
    def setUpClass(cls) -> None:
        from ai_intervention_agent.web_ui import WebFeedbackUI

        cls._ui = WebFeedbackUI(prompt="r142 health", task_id="rt-r142", port=cls._port)
        cls._ui.app.config["TESTING"] = True
        cls._ui.limiter.enabled = False
        cls._client = cls._ui.app.test_client()

    def test_health_response_contains_per_provider(self):
        resp = self._client.get("/api/system/health")
        self.assertIn(resp.status_code, (200, 503))
        body = resp.get_json()
        self.assertIn("checks", body)
        self.assertIn("notification", body["checks"])
        notif_check = body["checks"]["notification"]
        # ok=True 说明 _safe_notification_summary() 返回了 dict —— 此时
        # per_provider 必须出现
        if notif_check.get("ok"):
            self.assertIn("per_provider", notif_check)
            per_prov = notif_check["per_provider"]
            self.assertIsInstance(per_prov, dict)
            for ptype in _HEALTH_PER_PROVIDER_KEYS:
                self.assertIn(ptype, per_prov)

    def test_health_response_does_not_leak_last_error_text(self):
        # 即使有 provider 失败、last_error 写入 stats，HTTP 响应 body
        # 里 last_error 原文本不应出现
        resp = self._client.get("/api/system/health")
        body_str = resp.get_data(as_text=True)
        # 这里只是 sanity check —— 真实 PII 内容不会泄漏到 health
        # （由于 _safe_per_provider_snapshot 的行为）
        self.assertNotIn('last_error":', body_str.lower())


class TestSwaggerDocAndSourceInvariants(unittest.TestCase):
    """source 内 Swagger doc 提及 R142 / per_provider / last_error_present。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.source = (
            REPO_ROOT / "src" / "ai_intervention_agent" / "web_ui_routes" / "system.py"
        ).read_text(encoding="utf-8")

    def test_swagger_mentions_r142(self):
        self.assertIn("R142", self.source)

    def test_swagger_mentions_per_provider(self):
        self.assertIn("per_provider", self.source)

    def test_swagger_mentions_last_error_present(self):
        self.assertIn("last_error_present", self.source)

    def test_swagger_mentions_pii_safety(self):
        # 说明文里至少有"PII"或"防...泄漏"字样，为后人维护提供 lock
        self.assertTrue(
            "PII" in self.source or "泄漏" in self.source,
            "Swagger doc must explicitly call out the PII safety boundary",
        )

    def test_health_per_provider_keys_constant_documented(self):
        self.assertIn("_HEALTH_PER_PROVIDER_KEYS", self.source)


if __name__ == "__main__":
    unittest.main()
