"""R204 / Cycle 9 · F-203-1 · ``aiia_token_age_seconds`` Prometheus gauge tests。

设计目标
========

R199 把 token rotation 时间戳暴露到 ``GET /api/system/api-token-info``
endpoint 的 ``age_seconds`` 字段，但 alertmanager 想做「90 天没轮换 →
alert」必须**自己 scrape JSON**——绕开 Prometheus scrape 的标准方式，
增加运维复杂度。R204 把同一份数据 mirror 到 Prometheus exposition
``aiia_token_age_seconds`` gauge，让 alertmanager 用标准 PromQL 直接
写规则（如 ``aiia_token_age_seconds > 90 * 86400``）。

设计决策（与 ``_safe_uptime_seconds`` 等其他 ``_safe_*`` helper 同款契约）
================================================================================

- **No token / no rotated_at / 解析失败 / future timestamp**：metric
  **不出现**（不输出 NaN，不输出 0）。Grafana 会显示 "no data"
  触发 ``absent(aiia_token_age_seconds)`` 类型的告警规则，与 normal
  age threshold 告警分开（two-tier alerting）。
- **Helper 函数与 R199 endpoint inline 逻辑刻意 verbatim duplicated**：
  endpoint inline 已被 R199 测试覆盖 5+ case，重构有 backward-compat
  风险；endpoint 返回 dict (多字段) vs helper 返回 int | None (单值)，
  抽象层不对齐。R205+ 可以考虑统一。两份实现的 bug fix 必须同步——
  本套件的 ``TestEndpointMetricParity`` invariant 守护一致性。

测试覆盖 (10 cases / 4 invariant class)
=========================================

1. **TestSafeTokenAgeHelper** (5): no token / token < 16 char / no
   rotated_at / malformed rotated_at / future timestamp 全部 → None
2. **TestPrometheusMetricRendering** (3): 正常 token + recent rotation
   → exposition 含 metric line / no token → metric absent / age 计算
   正确 (45-day-old token)
3. **TestEndpointMetricParity** (1): 同一份 config 下 endpoint
   ``age_seconds`` ≈ metric value，差异 ≤ 2 秒（运算 + clock 容忍）
4. **TestPrometheusOutputFormat** (1): HELP/TYPE/value 行格式合规
   （metric_type=gauge，help_text 含 R204 / F-203-1 标识）

总计 10 cases。
"""

from __future__ import annotations

import sys
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ai_intervention_agent.web_ui_routes import system as system_module


def _ns_stub_with(api_token: str = "x" * 32, rotated_at: str = "") -> dict[str, Any]:
    return {
        "bind_interface": "127.0.0.1",
        "allowed_networks": ["127.0.0.0/8", "::1/128"],
        "blocked_ips": [],
        "access_control_enabled": True,
        "api_token": api_token,
        "api_token_rotated_at": rotated_at,
    }


def _iso_ago(seconds: float = 0, days: float = 0) -> str:
    ts = datetime.now(UTC) - timedelta(seconds=seconds, days=days)
    return ts.isoformat().replace("+00:00", "Z")


def _iso_future(days: float = 1) -> str:
    ts = datetime.now(UTC) + timedelta(days=days)
    return ts.isoformat().replace("+00:00", "Z")


# ---------------------------------------------------------------------------
# 1. _safe_token_age_seconds helper
# ---------------------------------------------------------------------------


class TestSafeTokenAgeHelper(unittest.TestCase):
    def _call_helper_with(self, ns_stub: dict[str, Any]) -> int | None:
        with patch.object(
            system_module.get_config().__class__,
            "get_network_security_config",
            return_value=ns_stub,
        ):
            return system_module._safe_token_age_seconds()

    def test_no_token_returns_none(self) -> None:
        self.assertIsNone(
            self._call_helper_with(_ns_stub_with(api_token="", rotated_at=_iso_ago(10)))
        )

    def test_short_token_below_min_length_returns_none(self) -> None:
        self.assertIsNone(
            self._call_helper_with(
                _ns_stub_with(api_token="x" * 15, rotated_at=_iso_ago(10))
            )
        )

    def test_no_rotated_at_returns_none(self) -> None:
        self.assertIsNone(self._call_helper_with(_ns_stub_with(rotated_at="")))

    def test_malformed_rotated_at_returns_none(self) -> None:
        self.assertIsNone(
            self._call_helper_with(_ns_stub_with(rotated_at="not-a-timestamp"))
        )

    def test_future_rotated_at_returns_none(self) -> None:
        """clock skew / 恶意 config → age < 0 → None（与 endpoint 同档契
        约：不输出 0 否则 dashboard 误以为刚 rotate）。"""
        self.assertIsNone(
            self._call_helper_with(_ns_stub_with(rotated_at=_iso_future(days=1)))
        )

    def test_valid_recent_rotation_returns_positive_int(self) -> None:
        age = self._call_helper_with(_ns_stub_with(rotated_at=_iso_ago(seconds=10)))
        self.assertIsInstance(age, int)
        assert age is not None
        self.assertGreaterEqual(age, 5)
        self.assertLessEqual(age, 30)


# ---------------------------------------------------------------------------
# 2. Prometheus metric rendering
# ---------------------------------------------------------------------------


class TestPrometheusMetricRendering(unittest.TestCase):
    def _render_with(self, ns_stub: dict[str, Any]) -> str:
        with patch.object(
            system_module.get_config().__class__,
            "get_network_security_config",
            return_value=ns_stub,
        ):
            return system_module._render_prometheus_metrics()

    def test_metric_renders_when_token_set_with_recent_rotation(self) -> None:
        output = self._render_with(_ns_stub_with(rotated_at=_iso_ago(seconds=5)))
        self.assertIn("# HELP aiia_token_age_seconds ", output)
        self.assertIn("# TYPE aiia_token_age_seconds gauge\n", output)

        metric_lines = [
            line
            for line in output.splitlines()
            if line.startswith("aiia_token_age_seconds ")
        ]
        self.assertEqual(len(metric_lines), 1, f"got {metric_lines!r}")
        value_str = metric_lines[0].split(" ", 1)[1].strip()
        value = int(value_str)
        self.assertGreaterEqual(value, 0)
        self.assertLessEqual(value, 30)

    def test_metric_absent_when_no_token(self) -> None:
        output = self._render_with(_ns_stub_with(api_token="", rotated_at=_iso_ago(10)))
        self.assertNotIn("aiia_token_age_seconds", output)

    def test_45_day_old_token_renders_correct_age(self) -> None:
        """NIST SP 800-63B 30-90 天 rotation 中点（45 天）—— 这是核心
        use-case 的代表性数据点，确保 ``aiia_token_age_seconds > 90 *
        86400`` 这类 alertmanager rule 真的会在该 boundary 触发。"""
        output = self._render_with(_ns_stub_with(rotated_at=_iso_ago(days=45)))
        metric_lines = [
            line
            for line in output.splitlines()
            if line.startswith("aiia_token_age_seconds ")
        ]
        self.assertEqual(len(metric_lines), 1)
        value = int(metric_lines[0].split(" ", 1)[1].strip())
        expected = 45 * 86400
        self.assertGreaterEqual(value, expected - 60)
        self.assertLessEqual(value, expected + 60)


# ---------------------------------------------------------------------------
# 3. Endpoint ↔ metric parity invariant
# ---------------------------------------------------------------------------


class TestEndpointMetricParity(unittest.TestCase):
    """**R204 核心契约**: helper + endpoint inline 逻辑刻意 duplicated
    （见 ``_safe_token_age_seconds`` docstring），任何 bug fix 必须同步。
    本测试在同一份 config + 同一时间点下抽样验证两路 age 计算一致，
    防止 future drift。"""

    _port: int = 19204
    _ui: Any = None
    _client: Any = None

    @classmethod
    def setUpClass(cls) -> None:
        from ai_intervention_agent.web_ui import WebFeedbackUI

        cls._ui = WebFeedbackUI(
            prompt="r204 token-age parity test", task_id="tk-r204", port=cls._port
        )
        cls._ui.app.config["TESTING"] = True
        cls._ui.limiter.enabled = False
        cls._client = cls._ui.app.test_client()

    def test_endpoint_age_seconds_matches_metric_value(self) -> None:
        ns_stub = _ns_stub_with(rotated_at=_iso_ago(days=30))

        with (
            patch.object(system_module, "_get_client_ip", return_value="127.0.0.1"),
            patch.object(
                system_module.get_config().__class__,
                "get_network_security_config",
                return_value=ns_stub,
            ),
        ):
            endpoint_resp = self._client.get("/api/system/api-token-info")
            endpoint_age = endpoint_resp.get_json()["age_seconds"]

            metrics_resp = self._client.get("/api/system/metrics")
            metrics_text = metrics_resp.get_data(as_text=True)

        self.assertEqual(endpoint_resp.status_code, 200)
        self.assertEqual(metrics_resp.status_code, 200)
        self.assertIsInstance(endpoint_age, int)

        metric_lines = [
            line
            for line in metrics_text.splitlines()
            if line.startswith("aiia_token_age_seconds ")
        ]
        self.assertEqual(len(metric_lines), 1, f"got {metric_lines!r}")
        metric_age = int(metric_lines[0].split(" ", 1)[1].strip())

        self.assertLessEqual(
            abs(endpoint_age - metric_age),
            2,
            f"endpoint age_seconds={endpoint_age} drifts from metric "
            f"value={metric_age} by > 2 seconds — R199 endpoint inline "
            f"logic and R204 _safe_token_age_seconds helper diverged. "
            "Both implementations should compute identical age modulo "
            "clock-granularity skew; if you changed one without the "
            "other, sync now.",
        )


# ---------------------------------------------------------------------------
# 4. Output format compliance
# ---------------------------------------------------------------------------


class TestPrometheusOutputFormat(unittest.TestCase):
    def test_help_and_type_lines_well_formed(self) -> None:
        with patch.object(
            system_module.get_config().__class__,
            "get_network_security_config",
            return_value=_ns_stub_with(rotated_at=_iso_ago(seconds=5)),
        ):
            output = system_module._render_prometheus_metrics()

        self.assertEqual(output.count("# HELP aiia_token_age_seconds "), 1)
        self.assertEqual(output.count("# TYPE aiia_token_age_seconds gauge"), 1)

        help_line = next(
            line
            for line in output.splitlines()
            if line.startswith("# HELP aiia_token_age_seconds")
        )
        self.assertIn("R204", help_line)
        self.assertIn("F-203-1", help_line)
        self.assertIn("rotated", help_line.lower())


if __name__ == "__main__":
    unittest.main()
