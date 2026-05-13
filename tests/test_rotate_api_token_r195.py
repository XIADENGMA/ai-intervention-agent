"""R195 / Cycle 5 · POST /api/system/rotate-api-token 测试套件。

背景
----
CR#18 §4.4(b) 把 ``POST /api/system/rotate-api-token`` 列为「low priority
follow-up」——R189 的 ``api_token`` 字段是「配置后用到挂掉」的静态凭据，
但 NIST SP 800-63B 推荐共享密钥 30-90 天 rotation。如果只能通过「编辑
config.toml + 重启进程」rotation，对 24/7 运行的 server 来说成本高且会
打断 in-flight feedback tasks。

R195 让本机 admin 通过 HTTP 端点请求生成新 token + 写入 config + 立即
生效，无需进程重启。**强制 loopback-only**——不接受 token 鉴权——避免
被盗 token 自动续期的攻击路径。

设计要点（与 implementation 对齐）
================================
- ``_is_loopback_request()`` 而**不**是 ``_is_authorized()``：强制本机；
- ``secrets.token_urlsafe(32)`` 生成 ~43 char URL-safe random token；
- ``cfg.update_network_security_config({"api_token": new_token})`` 写入
  （走现有 R189 + R193 的 hot-reload + cache invalidation 链路）；
- 响应体**含明文 token**——这是 rotation 端点的**唯一**返回时机；
- rate-limit 5/hour（admin 工具偶尔调，攻击者高频立即限流）；
- 写入失败 → 500，旧 token 保持有效（fail-safe，不锁本机管理员出去）。

测试覆盖（13 cases / 4 invariant classes）：

1. **Loopback gate**（3 cases）
2. **Token generation contract**（4 cases）
3. **Config persistence + cache invalidation**（3 cases）
4. **失败兜底 / 边界**（3 cases）
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


class _RotateRouteBase(unittest.TestCase):
    """复用 WebFeedbackUI test_client 走真实 HTTP 路径。"""

    _port: int = 19195
    _ui: Any = None
    _client: Any = None

    @classmethod
    def setUpClass(cls) -> None:
        from ai_intervention_agent.web_ui import WebFeedbackUI

        cls._ui = WebFeedbackUI(
            prompt="r195 rotate test", task_id="tk-r195", port=cls._port
        )
        cls._ui.app.config["TESTING"] = True
        cls._ui.limiter.enabled = False
        cls._client = cls._ui.app.test_client()


# ---------------------------------------------------------------------------
# 1. Loopback gate
# ---------------------------------------------------------------------------


class TestLoopbackGate(_RotateRouteBase):
    """R195 强制 loopback-only，**不**接受 token 鉴权——这是 R195 区别
    于其他 R189 升级过的端点的关键差异。"""

    def test_non_loopback_returns_403(self) -> None:
        from ai_intervention_agent.web_ui_routes import system as system_module

        with patch.object(system_module, "_get_client_ip", return_value="192.168.1.5"):
            resp = self._client.post("/api/system/rotate-api-token")
        self.assertEqual(resp.status_code, 403)
        body = resp.get_json()
        self.assertFalse(body["success"])
        # 错误消息应明确指出原因（admin 文档化 token rotation hijacking 防御）
        self.assertIn("loopback", body["error"].lower())

    def test_non_loopback_with_valid_token_still_403(self) -> None:
        # 关键差异：即使附上正确 token，仍然 403——R195 不接受 token
        # 鉴权，避免被盗 token 自动续期攻击路径。
        from ai_intervention_agent.web_ui_routes import system as system_module

        fake_token = "valid-r195-test-token-32xx-xxxxxxxxx"
        with (
            patch.object(system_module, "_get_client_ip", return_value="192.168.1.5"),
            patch.object(
                system_module,
                "_get_configured_api_token",
                return_value=fake_token,
            ),
        ):
            resp = self._client.post(
                "/api/system/rotate-api-token",
                headers={"Authorization": f"Bearer {fake_token}"},
            )
        self.assertEqual(resp.status_code, 403)

    def test_loopback_returns_200(self) -> None:
        from ai_intervention_agent.web_ui_routes import system as system_module

        with (
            patch.object(system_module, "_get_client_ip", return_value="127.0.0.1"),
            patch.object(
                system_module.get_config().__class__,
                "update_network_security_config",
                return_value=None,
            ),
        ):
            resp = self._client.post("/api/system/rotate-api-token")
        self.assertEqual(resp.status_code, 200)


# ---------------------------------------------------------------------------
# 2. Token generation contract
# ---------------------------------------------------------------------------


class TestTokenGenerationContract(_RotateRouteBase):
    def _rotate(self) -> Any:
        from ai_intervention_agent.web_ui_routes import system as system_module

        with (
            patch.object(system_module, "_get_client_ip", return_value="127.0.0.1"),
            patch.object(
                system_module.get_config().__class__,
                "update_network_security_config",
                return_value=None,
            ),
        ):
            return self._client.post("/api/system/rotate-api-token")

    def test_response_contains_api_token_field(self) -> None:
        resp = self._rotate()
        body = resp.get_json()
        self.assertIn("api_token", body)
        self.assertIsInstance(body["api_token"], str)

    def test_token_length_meets_minimum(self) -> None:
        # token_urlsafe(32) → ~43 char base64url。R189 要求 ≥ 16 chars，
        # R195 应该远超此下限。
        resp = self._rotate()
        body = resp.get_json()
        self.assertGreaterEqual(
            len(body["api_token"]),
            32,
            f"R195 generated token too short: {len(body['api_token'])} < 32",
        )

    def test_two_rotations_produce_different_tokens(self) -> None:
        # 关键不变量：连续两次 rotation 必须产生不同 token——否则 entropy
        # 来源有问题（secrets.token_urlsafe 错误使用 / random seed 固化）
        resp1 = self._rotate()
        resp2 = self._rotate()
        self.assertNotEqual(
            resp1.get_json()["api_token"],
            resp2.get_json()["api_token"],
        )

    def test_response_contains_rotated_at_timestamp(self) -> None:
        # ISO-8601 UTC，方便 audit log 直接 grep
        resp = self._rotate()
        body = resp.get_json()
        self.assertIn("rotated_at", body)
        # ISO-8601 末尾 Z 或 +00:00
        ts = body["rotated_at"]
        self.assertTrue(
            ts.endswith(("Z", "+00:00")),
            f"rotated_at not ISO-8601 UTC: {ts!r}",
        )


# ---------------------------------------------------------------------------
# 3. Config persistence + cache invalidation
# ---------------------------------------------------------------------------


class TestConfigPersistence(_RotateRouteBase):
    def test_update_network_security_config_called_with_new_token(self) -> None:
        from ai_intervention_agent.web_ui_routes import system as system_module

        cfg = system_module.get_config()
        with (
            patch.object(system_module, "_get_client_ip", return_value="127.0.0.1"),
            patch.object(
                cfg.__class__, "update_network_security_config"
            ) as mock_update,
        ):
            resp = self._client.post("/api/system/rotate-api-token")

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(mock_update.call_count, 1)
        # 第一个参数（位置或 kw）必须含 api_token
        args, kwargs = mock_update.call_args
        # update_network_security_config(updates_dict)
        updates = args[0] if args else kwargs.get("updates", {})
        self.assertIn("api_token", updates)
        # 响应里的 token 必须与写入 config 的 token 一致
        body = resp.get_json()
        self.assertEqual(updates["api_token"], body["api_token"])

    def test_new_token_persists_to_real_config(self) -> None:
        # 端到端：rotation → 直接读 ConfigManager 应该看到新值
        from ai_intervention_agent.web_ui_routes import system as system_module

        with patch.object(system_module, "_get_client_ip", return_value="127.0.0.1"):
            resp = self._client.post("/api/system/rotate-api-token")
        body = resp.get_json()

        cfg = system_module.get_config()
        ns_config = cfg.get_network_security_config()
        # 真实写入路径生效
        self.assertEqual(ns_config["api_token"], body["api_token"])

        # 清理：恢复空 token，避免污染后续测试
        cfg.update_network_security_config({"api_token": ""})

    def test_cache_invalidated_so_is_authorized_uses_new_token(self) -> None:
        # 与 R193 hot-reload 测试一致：rotation 后下一次 _is_authorized()
        # 应该立即使用新 token，没有缓存延迟
        from ai_intervention_agent.web_ui_routes import system as system_module

        with patch.object(system_module, "_get_client_ip", return_value="127.0.0.1"):
            resp = self._client.post("/api/system/rotate-api-token")
        body = resp.get_json()
        new_token = body["api_token"]

        # 直接调 helper 验证缓存确实更新到新值
        configured = system_module._get_configured_api_token()
        self.assertEqual(configured, new_token)

        # 清理
        system_module.get_config().update_network_security_config({"api_token": ""})


# ---------------------------------------------------------------------------
# 4. 失败兜底 / 边界
# ---------------------------------------------------------------------------


class TestFailureBoundary(_RotateRouteBase):
    def test_persist_failure_returns_500(self) -> None:
        # 写入失败 → 500 + 错误消息描述
        from ai_intervention_agent.web_ui_routes import system as system_module

        with (
            patch.object(system_module, "_get_client_ip", return_value="127.0.0.1"),
            patch.object(
                system_module.get_config().__class__,
                "update_network_security_config",
                side_effect=OSError("disk full"),
            ),
        ):
            resp = self._client.post("/api/system/rotate-api-token")

        self.assertEqual(resp.status_code, 500)
        body = resp.get_json()
        self.assertFalse(body["success"])
        # 错误消息提示 admin 老 token 仍有效（避免误以为被锁出）
        self.assertIn("old token", body["error"].lower())

    def test_persist_failure_response_does_not_contain_token(self) -> None:
        # 失败路径**不**应回传新生成的 token——避免「写入失败但 token
        # 被泄漏」+ admin 误以为是新 token 但实际旧 token 仍生效的混乱
        from ai_intervention_agent.web_ui_routes import system as system_module

        with (
            patch.object(system_module, "_get_client_ip", return_value="127.0.0.1"),
            patch.object(
                system_module.get_config().__class__,
                "update_network_security_config",
                side_effect=OSError("disk full"),
            ),
        ):
            resp = self._client.post("/api/system/rotate-api-token")
        body = resp.get_json()
        self.assertNotIn("api_token", body)

    def test_rate_limit_decorator_present(self) -> None:
        # Source-level 检查：``5 per hour`` 装饰器必须在 rotate_api_token
        # 上出现，防止后续 refactor 把 rate limit 摘掉
        from pathlib import Path

        system_py = (
            Path(__file__).resolve().parent.parent
            / "src"
            / "ai_intervention_agent"
            / "web_ui_routes"
            / "system.py"
        )
        source = system_py.read_text(encoding="utf-8")
        # 提取 rotate_api_token 定义前 200 字符（rate limit 装饰器在 def 上方）
        idx = source.find("def rotate_api_token")
        self.assertGreater(idx, 0, "rotate_api_token endpoint not found")
        nearby = source[max(0, idx - 200) : idx]
        self.assertIn(
            "5 per hour",
            nearby,
            "rotate_api_token endpoint must have @self.limiter.limit('5 per hour')",
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
