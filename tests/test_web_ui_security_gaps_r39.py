"""``web_ui_security`` 安全关键路径补全测试 (R39)

R39 之前 ``web_ui_security.py`` 的整体覆盖率 93.79%，但漏掉的恰好是 *最
不能漏* 的几条安全分支：

1. ``_get_csp_nonce`` 在非请求上下文（``has_request_context() is False``
   或访问 ``flask.g`` 抛 ``RuntimeError``）的兜底分支 (lines 151-153)。
   这条路径在 SSE 心跳协程、后台清理线程、以及单元测试用 mock app 时被
   命中；如果 fallback 失效会让 nonce 为空字符串，CSP 直接放过任何脚本。
2. ``_is_ip_allowed`` 黑名单 *CIDR 网段* 命中分支 (lines 198-202)。
   现有 ``test_blocked_ip`` 只覆盖单 IP 字符串黑名单（``"192.168.1.100"``），
   *没有* 覆盖网段（``"192.168.1.0/24"``）—— 而这正是生产环境上"封整段
   IP 范围"最常用的写法。
3. ``_is_ip_allowed`` 黑名单条目格式异常时的静默跳过分支 (lines 207-208)。
   如果 ``config.toml`` 里有人手抖写出 ``"abc.def"`` 这种非法 CIDR/IP，
   helper 必须 ``continue`` 跳过，否则 1 个错条目会让整个 IP 校验环节
   抛 ``AddressValueError`` 把所有正常请求拒绝（fail-closed 但实际是
   误伤所有人，非预期）。

为什么这些"特别小"的 gap 值得单独写测试：

- 安全代码的边界 *是* 安全代码本身。``_is_ip_allowed`` 漏一个分支不会
  让 lint / format / type-check 报错，coverage 报告里也只是 ``93.79%``
  这样温和的数字；而漏掉的恰是 fail-open 风险路径。
- 这套 helper 没有"业务侧测试"——它的失败现场在生产 server 拒掉合法
  请求或放过黑名单 IP 的瞬间，事后回放成本极高。
- R32.1 的反思（"为什么 PWA 漏检"）告诉我们：声明 / 单测 / 集成 必须
  分层都覆盖到，单纯靠模型层面集成测试漏掉运行时分支是常态。
"""

from __future__ import annotations

import inspect
import unittest
from typing import Any
from unittest.mock import patch

from ai_intervention_agent.web_ui import WebFeedbackUI


class TestTrustedHostsBoundary(unittest.TestCase):
    """Flask ``TRUSTED_HOSTS`` must reject spoofed Host headers."""

    def _status_for_host(self, ui: WebFeedbackUI, host: str) -> int:
        ui.app.config["TESTING"] = True
        response = ui.app.test_client().get(
            "/",
            headers={"Host": host},
            environ_base={"REMOTE_ADDR": "127.0.0.1"},
        )
        return response.status_code

    def test_default_trusted_hosts_allow_loopback_and_mdns(self) -> None:
        ui = WebFeedbackUI(
            prompt="test",
            predefined_options=[],
            task_id="test-host-default-r39",
            host="0.0.0.0",
            port=8080,
        )

        for host in (
            "localhost:8080",
            "127.0.0.1:8080",
            "[::1]:8080",
            "ai.local:8080",
        ):
            with self.subTest(host=host):
                self.assertEqual(self._status_for_host(ui, host), 200)

    def test_concrete_lan_bind_host_is_allowed(self) -> None:
        ui = WebFeedbackUI(
            prompt="test",
            predefined_options=[],
            task_id="test-host-lan-r39",
            host="192.168.1.10",
            port=8080,
        )

        self.assertEqual(self._status_for_host(ui, "192.168.1.10:8080"), 200)

    def test_external_base_url_and_explicit_trusted_hosts_are_allowed(self) -> None:
        ui = WebFeedbackUI(
            prompt="test",
            predefined_options=[],
            task_id="test-host-custom-r39",
            host="0.0.0.0",
            port=8080,
            external_base_url="https://ai.example.com/ui",
            mdns_hostname="lab-ai.local",
            trusted_hosts=["proxy.internal:9443", "https://tunnel.example.net/x"],
        )

        for host in (
            "ai.example.com:443",
            "lab-ai.local:8080",
            "proxy.internal:9443",
            "tunnel.example.net",
        ):
            with self.subTest(host=host):
                self.assertEqual(self._status_for_host(ui, host), 200)

    def test_spoofed_hosts_are_rejected(self) -> None:
        ui = WebFeedbackUI(
            prompt="test",
            predefined_options=[],
            task_id="test-host-reject-r39",
            host="0.0.0.0",
            port=8080,
        )

        for host in (
            "evil.example:8080",
            "localhost.evil.example:8080",
            "0.0.0.0:8080",
        ):
            with self.subTest(host=host):
                self.assertEqual(self._status_for_host(ui, host), 400)

    def test_build_trusted_hosts_excludes_wildcards_and_normalizes_ipv6(self) -> None:
        from ai_intervention_agent.web_ui import build_trusted_hosts

        trusted = build_trusted_hosts(
            host="::",
            mdns_hostname="AI.local.",
            external_base_url="https://[2001:db8::1]:8443/path",
            configured_trusted_hosts=["*.example.com", "[::1]:8080"],
        )

        self.assertIn("localhost", trusted)
        self.assertIn("127.0.0.1", trusted)
        self.assertIn("[::1]", trusted)
        self.assertIn("ai.local", trusted)
        self.assertIn("[2001:db8::1]", trusted)
        self.assertNotIn("::", trusted)
        self.assertNotIn("*.example.com", trusted)


class TestCspNonceOutsideRequestContext(unittest.TestCase):
    """``_get_csp_nonce`` 在非请求上下文 / RuntimeError 时的 fallback 行为。"""

    def setUp(self) -> None:
        self.ui = WebFeedbackUI(
            prompt="test",
            predefined_options=[],
            task_id="test-csp-r39",
        )

    def test_outside_request_context_returns_fresh_nonce(self) -> None:
        """``has_request_context() is False`` 时必须返回新随机 nonce。"""
        nonce = self.ui._get_csp_nonce()
        self.assertIsInstance(nonce, str)
        self.assertGreater(
            len(nonce),
            10,
            "CSP nonce 必须有足够熵（``token_urlsafe(16)`` 约 22 chars）",
        )

    def test_two_calls_outside_context_yield_distinct_nonces(self) -> None:
        """两次调用应当返回不同的 nonce —— 否则 fallback 退化成静态值，
        攻击者可预测注入脚本的 nonce 旁路 CSP。"""
        n1 = self.ui._get_csp_nonce()
        n2 = self.ui._get_csp_nonce()
        self.assertNotEqual(
            n1,
            n2,
            "非请求上下文下的两次 fallback 应当生成独立 nonce",
        )

    def test_runtime_error_in_has_request_context_falls_through(self) -> None:
        """``has_request_context()`` 自身抛 ``RuntimeError`` 时（极端边界，
        例如 app context teardown 期 / 多线程 race）必须落到
        ``return secrets.token_urlsafe(16)`` 而不是冒泡。

        R656 后 ``has_request_context`` 是 ``web_ui_security`` 的模块级绑定，
        所以必须 patch ``web_ui_security.has_request_context``；否则 patch
        不会被命中，测试看起来"通过"实际上根本没走到 except 分支。
        """

        def _fake_has_request_context() -> bool:
            raise RuntimeError("torn down")

        with patch(
            "ai_intervention_agent.web_ui_security.has_request_context",
            _fake_has_request_context,
        ):
            nonce = self.ui._get_csp_nonce()
            self.assertIsInstance(nonce, str)
            self.assertGreater(len(nonce), 10)

    def test_existing_request_nonce_does_not_generate_unused_fallback(self) -> None:
        """R464: request context already has ``g.csp_nonce`` → no extra CSPRNG call.

        Regression target: ``getattr(g, "csp_nonce", secrets.token_urlsafe(16))``
        looks lazy but Python evaluates call arguments before invoking
        ``getattr``. That burned one unused secure random token every time
        ``_get_template_context`` read the request nonce.
        """
        from flask import g

        with self.ui.app.test_request_context("/"):
            g.csp_nonce = "request-nonce"
            with patch(
                "ai_intervention_agent.web_ui_security.secrets.token_urlsafe",
                side_effect=AssertionError("unused fallback should not run"),
            ):
                nonce = self.ui._get_csp_nonce()

        self.assertEqual(nonce, "request-nonce")

    def test_missing_request_nonce_still_generates_secure_fallback(self) -> None:
        """R464 fallback behavior is preserved when ``g.csp_nonce`` is absent."""
        with self.ui.app.test_request_context("/"):
            with patch(
                "ai_intervention_agent.web_ui_security.secrets.token_urlsafe",
                return_value="generated-nonce",
            ) as token_spy:
                nonce = self.ui._get_csp_nonce()

        self.assertEqual(nonce, "generated-nonce")
        token_spy.assert_called_once_with(16)


class TestBlockedCidrNetwork(unittest.TestCase):
    """``_is_ip_allowed`` 在 blocked_ips 含 CIDR 网段时的命中分支。"""

    def setUp(self) -> None:
        self.ui = WebFeedbackUI(
            prompt="test",
            predefined_options=[],
            task_id="test-blocked-cidr-r39",
        )
        self.ui.network_security_config["access_control_enabled"] = True

    def test_ip_inside_blocked_cidr_v4_is_rejected(self) -> None:
        """``"192.168.1.0/24"`` 应当封掉整个 ``192.168.1.0-255`` 段。"""
        self.ui.network_security_config["blocked_ips"] = ["192.168.1.0/24"]
        self.ui.network_security_config["allowed_networks"] = ["0.0.0.0/0"]
        for ip in ("192.168.1.1", "192.168.1.50", "192.168.1.254"):
            with self.subTest(ip=ip):
                self.assertFalse(
                    self.ui._is_ip_allowed(ip),
                    f"{ip} 在黑名单网段 192.168.1.0/24 内，必须被拒绝",
                )

    def test_ip_outside_blocked_cidr_passes_to_allowlist(self) -> None:
        """段外 IP 不应被黑名单 CIDR 误拦——继续走白名单判断。"""
        self.ui.network_security_config["blocked_ips"] = ["192.168.1.0/24"]
        self.ui.network_security_config["allowed_networks"] = ["10.0.0.0/8"]
        # 段外 + 白名单内
        self.assertTrue(self.ui._is_ip_allowed("10.0.0.1"))
        # 段外 + 白名单外
        self.assertFalse(self.ui._is_ip_allowed("8.8.8.8"))

    def test_ip_inside_blocked_cidr_v6_is_rejected(self) -> None:
        """IPv6 段同样要支持。"""
        self.ui.network_security_config["blocked_ips"] = ["2001:db8::/32"]
        self.ui.network_security_config["allowed_networks"] = ["::/0"]
        self.assertFalse(self.ui._is_ip_allowed("2001:db8::1"))

    def test_blocked_single_ip_still_works_after_cidr_branch(self) -> None:
        """混合写法（CIDR + 单 IP）—— 防止"加了 CIDR 分支后单 IP 失效"。"""
        self.ui.network_security_config["blocked_ips"] = [
            "10.0.0.0/8",
            "8.8.8.8",
        ]
        self.ui.network_security_config["allowed_networks"] = ["0.0.0.0/0"]
        self.assertFalse(self.ui._is_ip_allowed("10.0.0.5"))
        self.assertFalse(self.ui._is_ip_allowed("8.8.8.8"))
        self.assertTrue(self.ui._is_ip_allowed("1.1.1.1"))


class TestBlockedIpsMalformedEntry(unittest.TestCase):
    """``_is_ip_allowed`` 对非法黑名单条目必须 *静默跳过* 而不是整体 fail。

    这是 fail-fast 与 fail-safe 的取舍：黑名单条目错配时，正确做法是
    跳过那一条让其它条目继续生效（最大程度保留预期防护），而不是 raise
    把整套访问控制打崩——后者是"配置错一个字段全员 403"的 DoS 漏洞。
    """

    def setUp(self) -> None:
        self.ui = WebFeedbackUI(
            prompt="test",
            predefined_options=[],
            task_id="test-malformed-r39",
        )
        self.ui.network_security_config["access_control_enabled"] = True

    def test_garbage_string_entry_is_skipped(self) -> None:
        """``"abc.def"`` 既不是合法 IP 也不是合法 CIDR —— continue。"""
        self.ui.network_security_config["blocked_ips"] = [
            "abc.def",
            "8.8.8.8",
        ]
        self.ui.network_security_config["allowed_networks"] = ["0.0.0.0/0"]
        # 后续合法条目不能被前一条非法条目搅黄
        self.assertFalse(
            self.ui._is_ip_allowed("8.8.8.8"),
            "非法 entry 应被静默跳过，让 8.8.8.8 仍被合法 entry 命中",
        )
        # 与黑名单无关的合法 IP 正常放行
        self.assertTrue(self.ui._is_ip_allowed("127.0.0.1"))

    def test_non_string_entry_is_skipped(self) -> None:
        """配置层意外塞进 ``None`` / int 等非字符串 entry 必须 ``TypeError`` →
        continue，不能让整个访问控制环节崩。"""
        self.ui.network_security_config["blocked_ips"] = [
            None,
            12345,
            "8.8.8.8",
        ]
        self.ui.network_security_config["allowed_networks"] = ["0.0.0.0/0"]
        self.assertFalse(self.ui._is_ip_allowed("8.8.8.8"))
        self.assertTrue(self.ui._is_ip_allowed("127.0.0.1"))

    def test_invalid_cidr_entry_is_skipped(self) -> None:
        """``"999.999.999.0/24"`` 是 ``ValueError`` 路径，同样要跳过。"""
        self.ui.network_security_config["blocked_ips"] = [
            "999.999.999.0/24",
            "8.8.8.8",
        ]
        self.ui.network_security_config["allowed_networks"] = ["0.0.0.0/0"]
        self.assertFalse(self.ui._is_ip_allowed("8.8.8.8"))


class TestNetworkSecurityConfigFallback(unittest.TestCase):
    """``self.network_security_config`` 不是 dict 时的兜底（line 185-186）。

    历史上有人 patch 测试用替换成 ``MagicMock``，``.get()`` 路径就会报
    ``AttributeError``。代码里加了 ``isinstance(..., dict)`` guard 防御
    这种情况，让 ``cfg`` 退化成空 dict 仍然走完逻辑。这条测试锁住该分支。
    """

    def test_non_dict_security_config_falls_back_to_empty(self) -> None:
        ui = WebFeedbackUI(
            prompt="test",
            predefined_options=[],
            task_id="test-non-dict-r39",
        )
        # 注入一个非 dict 的 sentinel；用 ``setattr`` 绕过静态类型检查，
        # 因为 ``network_security_config`` 在类型层声明的是 ``dict[str, Any]``，
        # 但运行时 helper 显式 guard ``isinstance(..., dict)`` 来兜住其它形状。
        setattr(ui, "network_security_config", "this-is-not-a-dict")  # noqa: B010
        # 默认 allowed_networks 退化成 ``["127.0.0.0/8", "::1/128"]`` 这条
        # ``cfg.get("allowed_networks", ...)`` 在空 cfg 上会拿到默认 list
        result = ui._is_ip_allowed("127.0.0.1")
        self.assertTrue(result, "兜底空 dict 仍要让 127.0.0.1 走默认白名单")

    def test_invalid_client_ip_returns_false(self) -> None:
        """``client_ip`` 本身解析失败时直接 fail-close 拒绝（line 226-228）。"""
        ui = WebFeedbackUI(
            prompt="test",
            predefined_options=[],
            task_id="test-bad-client-r39",
        )
        ui.network_security_config["access_control_enabled"] = True
        # 完全不是 IP 的字符串
        self.assertFalse(ui._is_ip_allowed("definitely-not-an-ip"))

    def test_access_control_disabled_short_circuits(self) -> None:
        """已经被 ``test_network_security_config`` 覆盖；这里只做 sanity，
        防止 R39 重构时把 short-circuit 误删。"""
        ui = WebFeedbackUI(
            prompt="test",
            predefined_options=[],
            task_id="test-disabled-r39",
        )
        ui.network_security_config["access_control_enabled"] = False
        ui.network_security_config["blocked_ips"] = ["1.1.1.1"]
        # 显式禁用后即使在黑名单也放行
        self.assertTrue(ui._is_ip_allowed("1.1.1.1"))

    def test_malformed_blocked_ips_is_treated_as_empty_collection(self) -> None:
        from ai_intervention_agent.web_ui_security import SecurityMixin

        ui = WebFeedbackUI(
            prompt="test",
            predefined_options=[],
            task_id="test-bad-blocked-ips-r39",
        )
        ui.network_security_config["access_control_enabled"] = True
        ui.network_security_config["blocked_ips"] = "127.0.0.1"
        ui.network_security_config["allowed_networks"] = ["127.0.0.0/8"]

        self.assertTrue(ui._is_ip_allowed("127.0.0.1"))

        source = inspect.getsource(SecurityMixin._is_ip_allowed)
        self.assertNotIn('cfg.get("blocked_ips", [])', source)

    def test_missing_allowed_networks_uses_lazy_default_path(self) -> None:
        from ai_intervention_agent.web_ui_security import SecurityMixin

        ui = WebFeedbackUI(
            prompt="test",
            predefined_options=[],
            task_id="test-missing-allowed-networks-r497",
        )
        ui.network_security_config = {
            "access_control_enabled": True,
            "blocked_ips": [],
        }

        self.assertTrue(ui._is_ip_allowed("127.0.0.1"))

        source = inspect.getsource(SecurityMixin._is_ip_allowed)
        self.assertIn("_DEFAULT_ALLOWED_NETWORKS", source)
        self.assertNotIn('cfg.get("allowed_networks", [', source)


class TestNetworkSecurityConfigLoadFailure(unittest.TestCase):
    """``_load_network_security_config`` 异常路径（line 165-167）。"""

    def test_get_config_raises_falls_back_to_defaults(self) -> None:
        """``get_config()`` / ``get_section()`` 抛异常时必须落到默认安全配置
        而不是冒泡——这是 server 启动期 ConfigManager 还没就绪时的常见情况。"""
        with patch(
            "ai_intervention_agent.web_ui_security.get_config",
            side_effect=RuntimeError("config not initialized"),
        ):
            from ai_intervention_agent.web_ui_security import SecurityMixin

            class _Stub(SecurityMixin):
                pass

            stub = _Stub()
            cfg = stub._load_network_security_config()  # type: ignore[attr-defined]

        self.assertIsInstance(cfg, dict)
        self.assertIn(
            "allowed_networks",
            cfg,
            "兜底配置必须含默认 allowed_networks 字段",
        )
        self.assertIn("access_control_enabled", cfg)


class TestNetworkSecurityLazyTestingGuard(unittest.TestCase):
    """R474: TESTING guard must not allocate an unused dict fallback."""

    def test_testing_short_circuit_does_not_load_config(self) -> None:
        ui = WebFeedbackUI(
            prompt="test",
            predefined_options=[],
            task_id="test-ns-testing-guard-r474",
        )
        ui.app.config["TESTING"] = True
        ui._network_security_config_loaded_from_config = False

        with patch.object(
            ui,
            "_load_network_security_config",
            side_effect=AssertionError("TESTING guard should short-circuit"),
        ):
            ui._ensure_network_security_config_loaded()

        self.assertTrue(ui._network_security_config_loaded_from_config)

    def test_lazy_loader_no_eager_app_config_dict_fallback(self) -> None:
        from ai_intervention_agent.web_ui_security import SecurityMixin

        source = inspect.getsource(SecurityMixin._ensure_network_security_config_loaded)

        self.assertNotIn(
            'getattr(getattr(self, "app", None), "config", {})',
            source,
        )
        self.assertIn("_MISSING_APP_CONFIG", source)


def _build_app_context_helper(ui: WebFeedbackUI) -> Any:
    """生成一个真实 Flask 请求上下文 helper，便于走 ``has_request_context``
    is True 的分支（line 149-150 通过 ``test_csp_*`` 已经覆盖；这里仅
    占位以便未来扩展不漏 import 时被保留）。"""
    return ui.app.test_request_context()


if __name__ == "__main__":
    unittest.main()
