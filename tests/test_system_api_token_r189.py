"""R189 / T4 · 可选 API token 认证（配合 non-loopback hardening）契约测试。

背景
----
R188 之前所有「敏感写入端点」（``open-config-file`` /
``log-level POST`` / ``open-config-file/info``）都是 ``loopback-only``。这
个策略在本机 / Docker / SSH-tunnel 部署下足够，但**反向代理 / LAN PWA /
mobile**等 non-loopback 场景下用户被迫放宽到 ``access_control_enabled = false``
+ ``allowed_networks`` 加私网段，本质相当于「凭 IP 信任远端」，没有真
正的认证机制。

R189 / T4 把这个 gap 补齐：在 ``[network_security]`` 段引入可选 ``api_token``
字段，并把所有原本走 ``_is_loopback_request()`` 的端点升级成
``_is_authorized()`` —— **loopback OR 有效 API token** 双轨。

设计取舍
========
1. **默认行为不变**：``api_token = ""`` 视作未配置，端点回退成
   ``loopback-only``，与既有用户的 zero-config 行为完全一致；
2. **不强制 token-only**：本机 loopback 始终通过，避免本机管理员被
   错配的 token 锁在门外（fail-closed footgun）；
3. **配置侧硬约束**：
   - ``api_token`` 必须是字符串；
   - 长度 < 16 字符（< 96 bit entropy，低于 NIST SP 800-63B 推荐）→ 警告
     + 视作未配置；
   - 长度 > 256 字符 → 截断到前 256（HTTP header 长度上限近似）；
   - 含 whitespace / control char → 清洗（防 ``compare_digest`` 永远 False）；
4. **endpoint 侧 constant-time compare**：用 ``secrets.compare_digest``
   防 timing-attack 字节级前缀推断；
5. **不污染 logs**：token 字符串不出现在 stderr / response error message；
6. **R53-F 契约自动覆盖**：``network_security`` 整段在 ``ConfigManager.
   get_all()`` 边界被过滤，``api_token`` 字段不会泄漏到
   ``/api/system/health`` / ``--print-config`` 输出。

支持的认证 header（first-match-wins）：

1. ``Authorization: Bearer <token>``——IETF RFC 6750 标准；
2. ``X-API-Token: <token>``——curl / Postman / PWA fetch 更直观。

测试覆盖（25 cases / 5 invariant classes）：

1. **``_get_configured_api_token()`` helper**（3 cases）
2. **``_extract_request_api_token()`` helper**（5 cases）
3. **``_is_api_token_authorized()`` helper**（5 cases）
4. **``_is_authorized()`` 复合 helper**（5 cases）
5. **配置校验**（5 cases）
6. **R53-F 安全契约**（2 cases）
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

from ai_intervention_agent.web_ui_routes import system as system_module

# ---------------------------------------------------------------------------
# 1. _get_configured_api_token helper
# ---------------------------------------------------------------------------


class TestGetConfiguredApiToken(unittest.TestCase):
    def test_returns_empty_when_unset(self) -> None:
        with patch.object(
            system_module,
            "get_config",
            return_value=type(
                "FakeCfg", (), {"get_network_security_config": lambda self: {}}
            )(),
        ):
            self.assertEqual(system_module._get_configured_api_token(), "")

    def test_returns_token_when_configured(self) -> None:
        configured = "x" * 32
        with patch.object(
            system_module,
            "get_config",
            return_value=type(
                "FakeCfg",
                (),
                {"get_network_security_config": lambda self: {"api_token": configured}},
            )(),
        ):
            self.assertEqual(system_module._get_configured_api_token(), configured)

    def test_returns_empty_when_config_raises(self) -> None:
        with patch.object(
            system_module,
            "get_config",
            side_effect=RuntimeError("config blown up"),
        ):
            # 不应让配置故障扩大成端点 500——helper 静默返回 ""
            self.assertEqual(system_module._get_configured_api_token(), "")


# ---------------------------------------------------------------------------
# 2. _extract_request_api_token helper
# ---------------------------------------------------------------------------


class _ApiTokenRouteBase(unittest.TestCase):
    """复用 system 路由测试 fixture——FlaskTest client 自带请求上下文。"""

    _port: int = 19189
    _ui: Any = None
    _client: Any = None

    @classmethod
    def setUpClass(cls) -> None:
        from ai_intervention_agent.web_ui import WebFeedbackUI

        cls._ui = WebFeedbackUI(
            prompt="api-token route test", task_id="tk-rt", port=cls._port
        )
        cls._ui.app.config["TESTING"] = True
        cls._ui.limiter.enabled = False
        cls._client = cls._ui.app.test_client()


class TestExtractRequestApiToken(_ApiTokenRouteBase):
    """在 Flask request context 内验证 header 提取。"""

    def _extract_with_headers(self, headers: dict[str, str]) -> str:
        with self._ui.app.test_request_context(headers=headers):
            return system_module._extract_request_api_token()

    def test_extracts_authorization_bearer(self) -> None:
        self.assertEqual(
            self._extract_with_headers({"Authorization": "Bearer abc123"}),
            "abc123",
        )

    def test_extracts_authorization_bearer_case_insensitive(self) -> None:
        # ``bearer`` 全小写、混合大小写都该 OK——RFC 6750 § 2.1 不区分大小写
        self.assertEqual(
            self._extract_with_headers({"Authorization": "bearer abc123"}),
            "abc123",
        )

    def test_extracts_x_api_token_header(self) -> None:
        self.assertEqual(
            self._extract_with_headers({"X-API-Token": "xyz456"}),
            "xyz456",
        )

    def test_returns_empty_when_no_token_header(self) -> None:
        self.assertEqual(self._extract_with_headers({}), "")

    def test_authorization_takes_priority_over_x_api_token(self) -> None:
        # 同时给两个 header 时 Authorization 优先（IETF 标准 trump 项目 header）
        self.assertEqual(
            self._extract_with_headers(
                {"Authorization": "Bearer first", "X-API-Token": "second"}
            ),
            "first",
        )


# ---------------------------------------------------------------------------
# 3. _is_api_token_authorized helper
# ---------------------------------------------------------------------------


class TestIsApiTokenAuthorized(_ApiTokenRouteBase):
    _configured = "y" * 32

    def _verify(self, headers: dict[str, str], configured: str) -> bool:
        fake_cfg = type(
            "FakeCfg",
            (),
            {"get_network_security_config": lambda self: {"api_token": configured}},
        )()
        with self._ui.app.test_request_context(headers=headers):
            with patch.object(system_module, "get_config", return_value=fake_cfg):
                return system_module._is_api_token_authorized()

    def test_false_when_no_token_configured(self) -> None:
        # api_token == "" → 函数应直接 False（不能授权任何请求）
        self.assertFalse(
            self._verify({"Authorization": "Bearer anything"}, configured="")
        )

    def test_false_when_configured_token_too_short(self) -> None:
        # < 16 字符的 token 即使匹配也不接受（防 brute-force）
        self.assertFalse(
            self._verify(
                {"Authorization": "Bearer shorttoken"}, configured="shorttoken"
            )
        )

    def test_false_when_client_omits_token(self) -> None:
        self.assertFalse(self._verify({}, configured=self._configured))

    def test_false_when_client_token_mismatches(self) -> None:
        self.assertFalse(
            self._verify({"X-API-Token": "wrong" * 8}, configured=self._configured)
        )

    def test_true_when_client_token_matches(self) -> None:
        self.assertTrue(
            self._verify(
                {"Authorization": f"Bearer {self._configured}"},
                configured=self._configured,
            )
        )


# ---------------------------------------------------------------------------
# 4. _is_authorized 复合 helper
# ---------------------------------------------------------------------------


class TestIsAuthorized(_ApiTokenRouteBase):
    _configured = "z" * 32

    def _check(
        self,
        *,
        client_ip: str,
        headers: dict[str, str] | None,
        configured: str,
    ) -> bool:
        fake_cfg = type(
            "FakeCfg",
            (),
            {"get_network_security_config": lambda self: {"api_token": configured}},
        )()
        with self._ui.app.test_request_context(headers=headers or {}):
            with (
                patch.object(system_module, "_get_client_ip", return_value=client_ip),
                patch.object(system_module, "get_config", return_value=fake_cfg),
            ):
                return system_module._is_authorized()

    def test_loopback_without_token_passes(self) -> None:
        # 默认行为不变：loopback + 未配置 token → 通过
        self.assertTrue(self._check(client_ip="127.0.0.1", headers=None, configured=""))

    def test_non_loopback_without_token_blocks(self) -> None:
        self.assertFalse(
            self._check(client_ip="192.168.1.5", headers=None, configured="")
        )

    def test_non_loopback_with_valid_token_passes(self) -> None:
        self.assertTrue(
            self._check(
                client_ip="192.168.1.5",
                headers={"Authorization": f"Bearer {self._configured}"},
                configured=self._configured,
            )
        )

    def test_non_loopback_with_invalid_token_blocks(self) -> None:
        self.assertFalse(
            self._check(
                client_ip="192.168.1.5",
                headers={"X-API-Token": "wrong" * 8},
                configured=self._configured,
            )
        )

    def test_loopback_with_invalid_token_still_passes(self) -> None:
        # loopback 是「主轨道」——即使带了错 token，loopback 来源依然通过。
        # 这是刻意的「不锁本机管理员」设计；如果未来需要严格 token-only
        # 模式，加 api_token_strict = true 显式 opt-in。
        self.assertTrue(
            self._check(
                client_ip="127.0.0.1",
                headers={"X-API-Token": "definitely-wrong"},
                configured=self._configured,
            )
        )


# ---------------------------------------------------------------------------
# 5. config validation: api_token 字段
# ---------------------------------------------------------------------------


class TestConfigValidation(unittest.TestCase):
    """直接调 ``ConfigManager._validate_network_security_config`` 验证 api_token
    字段的归一化行为——避免完整 config_manager.get() 路径的依赖耦合。"""

    def setUp(self) -> None:
        # 创建一个最小化的实例，只暴露 validator 需要的接口
        from ai_intervention_agent.config_modules.network_security import (
            NetworkSecurityMixin,
        )

        class Stub(NetworkSecurityMixin):
            def _get_default_config(self) -> dict[str, Any]:
                return {
                    "network_security": {
                        "bind_interface": "127.0.0.1",
                        "allowed_networks": ["127.0.0.0/8"],
                        "blocked_ips": [],
                        "access_control_enabled": True,
                        "api_token": "",
                    }
                }

            @staticmethod
            def _coerce_bool(value: Any, default: bool = True) -> bool:
                if isinstance(value, bool):
                    return value
                return default

        self.validator = Stub()

    def test_empty_token_stays_empty(self) -> None:
        result = self.validator._validate_network_security_config({"api_token": ""})
        self.assertEqual(result["api_token"], "")

    def test_short_token_dropped_as_unconfigured(self) -> None:
        # < 16 字符 → 视作未配置，结果为空串
        result = self.validator._validate_network_security_config(
            {"api_token": "tooshort"}
        )
        self.assertEqual(result["api_token"], "")

    def test_long_token_truncated_to_256(self) -> None:
        long_token = "a" * 500
        result = self.validator._validate_network_security_config(
            {"api_token": long_token}
        )
        self.assertEqual(len(result["api_token"]), 256)
        self.assertEqual(result["api_token"], "a" * 256)

    def test_whitespace_in_token_cleaned(self) -> None:
        # 含空格 / \n / \t → 清洗
        result = self.validator._validate_network_security_config(
            {"api_token": "  abc\tdef\nghi" + "x" * 16 + "  "}
        )
        self.assertNotIn(" ", result["api_token"])
        self.assertNotIn("\t", result["api_token"])
        self.assertNotIn("\n", result["api_token"])
        # 清洗后 + > 16 字符，应该保留
        self.assertGreaterEqual(len(result["api_token"]), 16)

    def test_non_string_token_dropped(self) -> None:
        result = self.validator._validate_network_security_config({"api_token": 12345})
        self.assertEqual(result["api_token"], "")


# ---------------------------------------------------------------------------
# 6. R53-F 安全契约：api_token 不能泄漏到 health / print-config
# ---------------------------------------------------------------------------


class TestApiTokenRedactionBoundary(unittest.TestCase):
    """``api_token`` 是 secret，不能出现在 ``/api/system/health`` /
    ``--print-config`` 输出中——R53-F 已经过滤了整个 ``network_security``
    段，本测试守护这条契约不被未来重构弄丢。"""

    def test_config_manager_get_all_filters_network_security(self) -> None:
        # ConfigManager.get_all() 边界过滤掉 network_security
        from ai_intervention_agent.config_manager import get_config

        cfg = get_config()
        all_config = cfg.get_all()
        # network_security 不应出现在 get_all() 顶层
        self.assertNotIn(
            "network_security",
            all_config,
            "R53-F: ConfigManager.get_all() 必须过滤 network_security 段（含 api_token）",
        )

    def test_token_substring_in_sensitive_key_list(self) -> None:
        # 即便 R53-F 过滤失效，token 也会被 _SENSITIVE_KEY_SUBSTRINGS 的
        # "token" substring 兜底 redact
        from ai_intervention_agent import server

        self.assertTrue(
            any("token" in s for s in server._SENSITIVE_KEY_SUBSTRINGS),
            "_SENSITIVE_KEY_SUBSTRINGS 必须含 'token' substring（兜底 api_token redact）",
        )


# ---------------------------------------------------------------------------
# 7. End-to-end: POST /api/system/log-level via API token
# ---------------------------------------------------------------------------


class TestEndpointTokenIntegration(_ApiTokenRouteBase):
    """实际打 HTTP 路径，验证非 loopback + token → 200。"""

    _configured = "test-r189-token-abcdefghijklmnopqrst-32chars"  # > 16 chars

    def _fake_cfg(self) -> Any:
        token = self._configured
        return type(
            "FakeCfg",
            (),
            {"get_network_security_config": lambda self: {"api_token": token}},
        )()

    def test_post_log_level_non_loopback_with_valid_token_returns_200(self) -> None:
        with (
            patch.object(system_module, "_get_client_ip", return_value="192.168.1.5"),
            patch.object(system_module, "get_config", return_value=self._fake_cfg()),
        ):
            resp = self._client.post(
                "/api/system/log-level",
                json={"level": "INFO"},
                headers={"Authorization": f"Bearer {self._configured}"},
            )
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertTrue(body["success"])

    def test_post_log_level_non_loopback_without_token_returns_403(self) -> None:
        with (
            patch.object(system_module, "_get_client_ip", return_value="192.168.1.5"),
            patch.object(system_module, "get_config", return_value=self._fake_cfg()),
        ):
            resp = self._client.post("/api/system/log-level", json={"level": "INFO"})
        self.assertEqual(resp.status_code, 403)

    def test_post_log_level_non_loopback_with_wrong_token_returns_403(self) -> None:
        with (
            patch.object(system_module, "_get_client_ip", return_value="192.168.1.5"),
            patch.object(system_module, "get_config", return_value=self._fake_cfg()),
        ):
            resp = self._client.post(
                "/api/system/log-level",
                json={"level": "INFO"},
                headers={
                    "Authorization": "Bearer wrong-token-with-enough-length-but-fake"
                },
            )
        self.assertEqual(resp.status_code, 403)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
