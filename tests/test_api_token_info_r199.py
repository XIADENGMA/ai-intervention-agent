"""R199 / Cycle 7 · ``GET /api/system/api-token-info`` 测试套件。

背景
----
R195 引入 ``POST /api/system/rotate-api-token`` 让 admin 通过 HTTP 端点
轮换 token，但**没有**任何方式查询「上次什么时候轮换的」——admin 工具
想做「90 天没轮换就 alert」需要自己维护 rotation 时间戳，重启就丢。

R199 把 rotation 时间戳**持久化**进 ``config.toml.network_security
.api_token_rotated_at``（R195 endpoint 改造同步写入），再提供新端点
``GET /api/system/api-token-info`` 让 admin 工具读取 token 元数据
（has_token / token_length / rotated_at / age_seconds）但**绝不**返回
token 本身——rotation endpoint 仍是唯一的明文 token 发放时机。

设计要点（与 implementation 对齐）
================================
- ``_is_loopback_request()``：loopback-only（token age 是元数据但仍敏感，
  泄露给 LAN 攻击者可让他们预测 admin rotation 窗口）；
- 响应字段：
  * ``has_token: bool`` —— config 里 ``api_token`` 是否已设置（非空 +
    长度 ≥ 16）
  * ``token_length: int | None`` —— ``has_token=false`` 时为 ``null``
  * ``rotated_at: str`` —— ISO-8601 UTC 或空串
  * ``age_seconds: int | None`` —— 时钟跳变 / 未设置 → ``null``
- rate-limit 30/min（poll-friendly + 防滥用）；
- 响应**不**含 ``api_token`` 明文。

测试覆盖（14 cases / 5 invariant classes）：

1. **Loopback gate**（2 cases）
2. **响应 schema**（5 cases）
3. **age_seconds 计算**（4 cases）
4. **rotation → info 端到端**（2 cases）
5. **source-level 约束**（1 case：rate-limit + 不泄漏 token）
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


class _TokenInfoRouteBase(unittest.TestCase):
    """复用 WebFeedbackUI test_client 走真实 HTTP 路径。"""

    _port: int = 19199
    _ui: Any = None
    _client: Any = None

    @classmethod
    def setUpClass(cls) -> None:
        from ai_intervention_agent.web_ui import WebFeedbackUI

        cls._ui = WebFeedbackUI(
            prompt="r199 token-info test", task_id="tk-r199", port=cls._port
        )
        cls._ui.app.config["TESTING"] = True
        cls._ui.limiter.enabled = False
        cls._client = cls._ui.app.test_client()


# ---------------------------------------------------------------------------
# 1. Loopback gate
# ---------------------------------------------------------------------------


class TestLoopbackGate(_TokenInfoRouteBase):
    """R199 严格 loopback-only——token age 是元数据但仍敏感
    （攻击者据此预测下一次 rotation 时机）。"""

    def test_non_loopback_returns_403(self) -> None:
        from ai_intervention_agent.web_ui_routes import system as system_module

        with patch.object(system_module, "_get_client_ip", return_value="10.0.0.5"):
            resp = self._client.get("/api/system/api-token-info")
        self.assertEqual(resp.status_code, 403)
        body = resp.get_json()
        self.assertFalse(body["success"])
        self.assertIn("loopback", body["error"].lower())

    def test_loopback_returns_200(self) -> None:
        from ai_intervention_agent.web_ui_routes import system as system_module

        with patch.object(system_module, "_get_client_ip", return_value="127.0.0.1"):
            resp = self._client.get("/api/system/api-token-info")
        self.assertEqual(resp.status_code, 200)


# ---------------------------------------------------------------------------
# 2. 响应 schema
# ---------------------------------------------------------------------------


class TestResponseSchema(_TokenInfoRouteBase):
    """response body 必须严格满足 R199 schema——dashboard / admin 工具
    会按字段直接 parse，缺字段 / 多字段都是 breaking change。"""

    def _get(self, *, token: str = "", rotated_at: str = "") -> Any:
        from ai_intervention_agent.web_ui_routes import system as system_module

        ns_stub = {
            "bind_interface": "127.0.0.1",
            "allowed_networks": ["127.0.0.0/8", "::1/128"],
            "blocked_ips": [],
            "access_control_enabled": True,
            "api_token": token,
            "api_token_rotated_at": rotated_at,
        }
        with (
            patch.object(system_module, "_get_client_ip", return_value="127.0.0.1"),
            patch.object(
                system_module.get_config().__class__,
                "get_network_security_config",
                return_value=ns_stub,
            ),
        ):
            return self._client.get("/api/system/api-token-info")

    def test_required_fields_present(self) -> None:
        resp = self._get()
        body = resp.get_json()
        for k in ("success", "has_token", "token_length", "rotated_at", "age_seconds"):
            self.assertIn(k, body, f"R199 response missing field: {k}")

    def test_no_token_response_shape(self) -> None:
        # 未配置 token / config 里是空串 → has_token=False, length=None
        resp = self._get(token="")
        body = resp.get_json()
        self.assertTrue(body["success"])
        self.assertFalse(body["has_token"])
        self.assertIsNone(body["token_length"])

    def test_response_never_leaks_api_token(self) -> None:
        # **最关键的安全不变量**：response 体里**绝不**应该出现明文
        # token——rotation endpoint 是唯一的发放时机
        secret = "supersecret-token-do-not-leak-32xx"
        resp = self._get(token=secret)
        body = resp.get_json()
        # 1. 没有 api_token 字段
        self.assertNotIn("api_token", body)
        # 2. 任何字符串字段都不应包含 secret 子串
        for k, v in body.items():
            if isinstance(v, str):
                self.assertNotIn(secret, v, f"R199 leaked token via field {k!r}: {v!r}")

    def test_has_token_true_when_long_enough(self) -> None:
        # token 长度 ≥ 16 → has_token=True + token_length 返回真实值
        resp = self._get(token="x" * 32)
        body = resp.get_json()
        self.assertTrue(body["has_token"])
        self.assertEqual(body["token_length"], 32)

    def test_has_token_false_when_too_short(self) -> None:
        # 实战中 validate_network_security_config 会把 < 16 的 token
        # 视作未配置——但 endpoint 仍然应该按当前看到的 config 状态
        # 给一致结论。如果 config 已经 sanitize 过，应该走 has_token=False
        # 路径。我们模拟一个未经 sanitize 的脏 config（len < 16）来
        # 验证 endpoint 自己的判断逻辑（不依赖上游 sanitize）。
        resp = self._get(token="too-short")
        body = resp.get_json()
        self.assertFalse(body["has_token"])
        self.assertIsNone(body["token_length"])


# ---------------------------------------------------------------------------
# 3. age_seconds 计算
# ---------------------------------------------------------------------------


class TestAgeSecondsCalculation(_TokenInfoRouteBase):
    """``age_seconds`` 是 R199 的核心 deliverable——这是 dashboard 做
    「90 天没轮换 → alert」的关键字段，必须正确处理边界。"""

    def _get_age(self, rotated_at: str) -> Any:
        from ai_intervention_agent.web_ui_routes import system as system_module

        ns_stub = {
            "bind_interface": "127.0.0.1",
            "allowed_networks": ["127.0.0.0/8", "::1/128"],
            "blocked_ips": [],
            "access_control_enabled": True,
            "api_token": "x" * 32,
            "api_token_rotated_at": rotated_at,
        }
        with (
            patch.object(system_module, "_get_client_ip", return_value="127.0.0.1"),
            patch.object(
                system_module.get_config().__class__,
                "get_network_security_config",
                return_value=ns_stub,
            ),
        ):
            resp = self._client.get("/api/system/api-token-info")
        return resp.get_json()

    def test_empty_rotated_at_yields_null_age(self) -> None:
        body = self._get_age("")
        self.assertEqual(body["rotated_at"], "")
        self.assertIsNone(body["age_seconds"])

    def test_recent_rotation_yields_small_age(self) -> None:
        # 10 秒前轮换 → age 应该接近 10
        ts = (
            (datetime.now(UTC) - timedelta(seconds=10))
            .isoformat()
            .replace("+00:00", "Z")
        )
        body = self._get_age(ts)
        self.assertIsInstance(body["age_seconds"], int)
        # 容忍 ±5 秒（test 执行 + clock granularity）
        self.assertGreaterEqual(body["age_seconds"], 5)
        self.assertLessEqual(body["age_seconds"], 30)

    def test_90_days_ago_rotation_yields_correct_age(self) -> None:
        # NIST SP 800-63B 推荐 30-90 天 rotation——这是核心 use-case
        ts = (datetime.now(UTC) - timedelta(days=90)).isoformat().replace("+00:00", "Z")
        body = self._get_age(ts)
        # 90 天 = 7,776,000 秒，容忍 ±60 秒
        expected = 90 * 86400
        self.assertGreaterEqual(body["age_seconds"], expected - 60)
        self.assertLessEqual(body["age_seconds"], expected + 60)

    def test_future_timestamp_yields_null_age(self) -> None:
        # 时钟跳变 / config 被恶意篡改成未来时间戳 → age 应该是 None
        # （而不是 0，0 会让 dashboard 误以为 token 刚刚轮换）
        ts = (datetime.now(UTC) + timedelta(days=1)).isoformat().replace("+00:00", "Z")
        body = self._get_age(ts)
        self.assertIsNone(
            body["age_seconds"],
            "future timestamp should yield None to avoid 'just rotated' false signal",
        )

    def test_malformed_rotated_at_yields_null_age(self) -> None:
        # config 里万一有脏数据（非 ISO-8601）→ age 应该是 None，
        # rotated_at 字段透出原值（debug 用）
        body = self._get_age("not-a-timestamp")
        self.assertIsNone(body["age_seconds"])


# ---------------------------------------------------------------------------
# 4. rotation → info 端到端
# ---------------------------------------------------------------------------


class TestRotationE2E(_TokenInfoRouteBase):
    """R195 rotate → R199 read 必须一致：rotation 写入的 ``rotated_at``
    应该在下一次 ``GET /api/system/api-token-info`` 立即可见，
    不能因 cache / async write 落后一拍。"""

    def test_rotation_then_info_returns_recent_rotated_at(self) -> None:
        from ai_intervention_agent.web_ui_routes import system as system_module

        with patch.object(system_module, "_get_client_ip", return_value="127.0.0.1"):
            r1 = self._client.post("/api/system/rotate-api-token")
            r2 = self._client.get("/api/system/api-token-info")

        self.assertEqual(r1.status_code, 200)
        self.assertEqual(r2.status_code, 200)
        info = r2.get_json()
        rotate_body = r1.get_json()
        # rotated_at **完全一致**——R199 endpoint 改造保证 rotate 写
        # config 的时间戳就是 response 里那个
        self.assertEqual(info["rotated_at"], rotate_body["rotated_at"])
        # age 应该接近 0（刚轮换）
        self.assertIsNotNone(info["age_seconds"])
        self.assertGreaterEqual(info["age_seconds"], 0)
        self.assertLess(info["age_seconds"], 10)

        # 清理 token + rotated_at（避免污染后续测试）
        system_module.get_config().update_network_security_config(
            {"api_token": "", "api_token_rotated_at": ""}
        )

    def test_rotation_persists_token_length_in_info(self) -> None:
        from ai_intervention_agent.web_ui_routes import system as system_module

        with patch.object(system_module, "_get_client_ip", return_value="127.0.0.1"):
            r1 = self._client.post("/api/system/rotate-api-token")
            r2 = self._client.get("/api/system/api-token-info")

        rotate_body = r1.get_json()
        info = r2.get_json()
        self.assertTrue(info["has_token"])
        self.assertEqual(info["token_length"], len(rotate_body["api_token"]))

        system_module.get_config().update_network_security_config(
            {"api_token": "", "api_token_rotated_at": ""}
        )


# ---------------------------------------------------------------------------
# 5. source-level 约束
# ---------------------------------------------------------------------------


class TestSourceLevelGuards(unittest.TestCase):
    """对 ``system.py`` 做静态扫描——防止后续 refactor 摘掉关键约束。"""

    def test_endpoint_has_rate_limit_and_returns_no_token(self) -> None:
        system_py = (
            Path(__file__).resolve().parent.parent
            / "src"
            / "ai_intervention_agent"
            / "web_ui_routes"
            / "system.py"
        )
        source = system_py.read_text(encoding="utf-8")

        idx = source.find("def api_token_info")
        self.assertGreater(idx, 0, "R199 endpoint api_token_info not found")
        # 装饰器在 def 上方 ~300 字符内
        nearby = source[max(0, idx - 300) : idx]
        self.assertIn(
            "30 per minute",
            nearby,
            "R199 api_token_info must have @self.limiter.limit('30 per minute')",
        )

        # 找到 endpoint 结束位置（下一个 @self.app.route）
        end_idx = source.find("@self.app.route", idx)
        if end_idx == -1:
            end_idx = len(source)
        body = source[idx:end_idx]

        # 关键安全不变量：endpoint 函数体里**不应**出现「写入 api_token
        # 到 response」的代码——任何 ``"api_token":`` 字面量（response
        # 字典 key）都不允许出现
        self.assertNotIn(
            '"api_token":',
            body,
            "R199 api_token_info MUST NOT include api_token field in response",
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
