"""CLI · ``ai-intervention-agent --print-config`` 回归测试。

设计目标
========

R185 续：``--version`` / ``--help`` 之后，下一个最有价值的 CLI 自省 flag
是 ``--print-config``——dump 进程实际生效的 merged config（含 env
override）到 stdout，让用户排查 "为什么我的 port 是 8181 不是
config.toml 里的 8080" 这类配置问题不需要打开 Python REPL。

输出契约
========

JSON object，三个 top-level key：

* ``config_file_path``: ConfigManager 实际加载的文件绝对路径，与
  ``/api/system/health`` 的同名字段对齐；
* ``web_ui``: 已 merge env override 的 web_ui 配置——host/port/language
  反映进程真实绑定值，而**不是** ``config.toml`` 写的原值；
* ``env_overrides``: 当前生效的 ``AI_INTERVENTION_AGENT_WEB_UI_*``
  env vars 名单（与 health endpoint 的 ``web_ui_env_overrides`` 字段
  语义完全一致）。

安全契约
========

``ConfigManager.get_all()`` 已经显式过滤 ``network_security`` 段（含
allowed_networks / token），所以 ``--print-config`` 不会泄漏敏感字段
——与 ``/api/system/health`` 同一信任等级。

invariant 守护
========

1. ``--print-config`` flag 注册在 argparse 上；
2. ``main(["--print-config"])`` ``sys.exit(0)``——不进入 stdio loop；
3. stdout 是合法 JSON；
4. payload 含 ``config_file_path`` / ``web_ui`` / ``env_overrides``
   三个 top-level key；
5. ``env_overrides`` 反映当前 env state（设了显示，没设为 {}）；
6. 探测失败时输出仍是 JSON（带 ``error`` 字段），方便 jq 解析。
"""

from __future__ import annotations

import io
import json
import os
import unittest
from contextlib import redirect_stderr, redirect_stdout
from typing import Any, cast
from unittest.mock import patch

from ai_intervention_agent import server


class TestPrintConfigFlagRegistered(unittest.TestCase):
    """argparse 必须知道这个 flag——否则用户敲了会得 'unrecognized argument'。"""

    def test_flag_in_help_text(self) -> None:
        parser = server._build_arg_parser()
        help_text = parser.format_help()
        self.assertIn(
            "--print-config",
            help_text,
            "--print-config 必须出现在 help 文本里供用户发现",
        )

    def test_parser_accepts_flag(self) -> None:
        parser = server._build_arg_parser()
        ns = parser.parse_args(["--print-config"])
        self.assertTrue(getattr(ns, "print_config", False))


class TestMainExitsCleanlyOnPrintConfig(unittest.TestCase):
    """``main(["--print-config"])`` 必须 ``sys.exit(0)`` 且不进入 stdio loop。"""

    def test_main_exits_zero_and_skips_stdio_loop(self) -> None:
        from ai_intervention_agent import server as _srv

        with (
            patch.object(_srv.mcp, "run") as fake_run,
            redirect_stdout(io.StringIO()) as captured_stdout,
            redirect_stderr(io.StringIO()),
        ):
            with self.assertRaises(SystemExit) as ctx:
                _srv.main(["--print-config"])
        self.assertEqual(ctx.exception.code, 0)
        fake_run.assert_not_called()
        self.assertGreater(
            len(captured_stdout.getvalue()),
            0,
            "stdout 必须有内容——dump JSON",
        )


class TestPrintConfigOutputShape(unittest.TestCase):
    """直接调用 ``_print_effective_config()`` 检查 stdout JSON shape。"""

    def _run(self) -> dict:
        """运行函数，返回解析后的 JSON。"""
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = server._print_effective_config()
        self.assertEqual(rc, 0, "成功路径必须返回 0")
        raw = buf.getvalue()
        self.assertGreater(len(raw), 0, "stdout 必须有 JSON 输出")
        return json.loads(raw)

    def test_top_level_keys(self) -> None:
        """CR#16 F-1 + F-3：payload 至少含 5 个 top-level key。"""
        payload = self._run()
        for key in (
            "config_file_path",
            "using_defaults",  # F-3
            "web_ui",  # 向后兼容
            "sections",  # F-1
            "env_overrides",
        ):
            self.assertIn(
                key,
                payload,
                f"payload 必须含 {key} top-level key（自省/监控/CI 都依赖）",
            )

    def test_sections_includes_all_non_sensitive(self) -> None:
        """CR#16 F-1：sections 必须含 web_ui / mdns / feedback / notification。"""
        payload = self._run()
        sections = payload.get("sections", {})
        self.assertIsInstance(sections, dict)
        for required_section in ("web_ui", "mdns", "feedback", "notification"):
            self.assertIn(
                required_section,
                sections,
                f"sections 必须含 {required_section}——F-1 要求覆盖所有非敏感",
            )

    def test_sections_does_not_include_network_security(self) -> None:
        """sections 顶层不能含 network_security——R53-F 同信任级。"""
        payload = self._run()
        sections = payload.get("sections", {})
        self.assertNotIn(
            "network_security",
            sections,
            "sections.network_security 必须被 ConfigManager.get_all() 过滤",
        )

    def test_using_defaults_is_bool(self) -> None:
        """CR#16 F-3：``using_defaults`` 必须是 bool 类型。"""
        payload = self._run()
        self.assertIsInstance(
            payload.get("using_defaults"),
            bool,
            "using_defaults 必须是 bool（None/字符串/数字都不合契约）",
        )

    def test_web_ui_section_has_resolved_fields(self) -> None:
        """``web_ui`` 必须含 host/port/language——这是 effective merged 值，
        不是 config.toml 原值。"""
        payload = self._run()
        web_ui = payload.get("web_ui", {})
        self.assertIsInstance(web_ui, dict)
        for key in ("host", "port", "language"):
            self.assertIn(
                key,
                web_ui,
                f"web_ui 必须含 {key} 字段（用户排查端口/语言时直接看这里）",
            )

    def test_env_overrides_is_dict(self) -> None:
        payload = self._run()
        self.assertIsInstance(
            payload.get("env_overrides"),
            dict,
            "env_overrides 必须是 dict（None 仅用于 health endpoint 的探测失败语义）",
        )


class TestPrintConfigReflectsEnvOverrides(unittest.TestCase):
    """env 设了就显示，没设就 {}——与 health endpoint 行为镜像。

    ``service_manager.get_web_ui_config()`` 有 10s TTL 缓存——所以本
    类每个测试都必须 invalidate 缓存，否则相邻测试看到的是上一个
    case 的 stale value。invalidation 走 module-level ``_config_cache``
    重置，与 service_manager 自己的 ``_invalidate_runtime_caches_on_
    config_change`` 同路径。
    """

    def setUp(self) -> None:
        from ai_intervention_agent import service_manager as _sm

        for env_name in (
            _sm._ENV_WEB_UI_HOST,
            _sm._ENV_WEB_UI_PORT,
            _sm._ENV_WEB_UI_LANGUAGE,
        ):
            os.environ.pop(env_name, None)
        self._invalidate_sm_cache()

    @staticmethod
    def _invalidate_sm_cache() -> None:
        """CR#16 F-5：调 public helper 而不是 reach 到 ``_config_cache``
        private dict——保护测试不被未来 cache shape 变更打挂。"""
        from ai_intervention_agent import service_manager as _sm

        _sm.invalidate_web_ui_config_cache()

    def _run_and_parse(self) -> dict:
        # env patch 后必须再次 invalidate，否则 _print_effective_config
        # 里调用 get_web_ui_config 时会拿到 setUp 时 cache 的值
        self._invalidate_sm_cache()
        buf = io.StringIO()
        with redirect_stdout(buf):
            server._print_effective_config()
        return json.loads(buf.getvalue())

    def test_no_env_returns_empty_dict(self) -> None:
        payload = self._run_and_parse()
        self.assertEqual(payload.get("env_overrides"), {})

    def test_port_env_reflected_in_env_overrides_and_web_ui(self) -> None:
        from ai_intervention_agent import service_manager as _sm

        with patch.dict(os.environ, {_sm._ENV_WEB_UI_PORT: "8181"}, clear=False):
            payload = self._run_and_parse()
        self.assertEqual(
            payload["env_overrides"].get(_sm._ENV_WEB_UI_PORT),
            "8181",
            "env_overrides 必须反映当前 env state",
        )
        self.assertEqual(
            payload["web_ui"].get("port"),
            8181,
            "web_ui.port 必须是 merged 后的 effective 值（int），"
            "而不是 config.toml 里的原始值——用户最关心的就是这个",
        )

    def test_language_env_reflected(self) -> None:
        from ai_intervention_agent import service_manager as _sm

        with patch.dict(os.environ, {_sm._ENV_WEB_UI_LANGUAGE: "en"}, clear=False):
            payload = self._run_and_parse()
        self.assertEqual(payload["web_ui"].get("language"), "en")
        self.assertEqual(
            payload["env_overrides"].get(_sm._ENV_WEB_UI_LANGUAGE),
            "en",
        )


class TestPrintConfigDoesNotLeakNetworkSecurity(unittest.TestCase):
    """``--print-config`` 输出必须不含 ``network_security``——R53-F 同信任级。"""

    def test_no_network_security_key(self) -> None:
        buf = io.StringIO()
        with redirect_stdout(buf):
            server._print_effective_config()
        payload = json.loads(buf.getvalue())
        web_ui = payload.get("web_ui", {})
        self.assertNotIn(
            "network_security",
            payload,
            "顶层不应含 network_security——ConfigManager.get_all() 已过滤",
        )
        self.assertNotIn(
            "network_security",
            web_ui,
            "web_ui 子树也不应含 network_security",
        )


class TestRedactSensitiveHelpers(unittest.TestCase):
    """``_redact_sensitive`` / ``_is_sensitive_key`` 单元测试。

    设计目标：CR#16 F-1 让 ``--print-config`` 暴露所有非敏感 sections——
    这是个双刃剑，notification 段里有 ``bark_device_key`` 这样的 user-
    specific token。本类守护：

    1. ``_is_sensitive_key`` 对常见敏感字段名都返回 True；
    2. ``_redact_sensitive`` 递归 dict / list，匹配的字段值替换为 ``***REDACTED***``；
    3. 非敏感字段保留原值；
    4. 大小写不敏感（``Bark_Device_Key`` 与 ``bark_device_key`` 等价）。
    """

    def test_is_sensitive_key_detects_common_patterns(self) -> None:
        for sensitive in (
            "bark_device_key",
            "device_key",
            "api_key",
            "apikey",
            "auth_token",
            "token",
            "password",
            "secret",
            "private_key",
            "client_secret",
            "webhook_url",
            "bot_token",
            "session_key",
            "credential",
        ):
            self.assertTrue(
                server._is_sensitive_key(sensitive),
                f"{sensitive!r} 必须被识别为敏感字段名",
            )

    def test_is_sensitive_key_case_insensitive(self) -> None:
        for variant in (
            "Bark_Device_Key",
            "BARK_DEVICE_KEY",
            "BarkDeviceKey",
        ):
            self.assertTrue(
                server._is_sensitive_key(variant),
                f"{variant!r} 大小写变体也必须被识别",
            )

    def test_is_sensitive_key_non_sensitive_passes(self) -> None:
        """常见非敏感字段不应被误伤。"""
        for not_sensitive in (
            "host",
            "port",
            "language",
            "log_level",
            "enabled",
            "retry_count",
            "timeout",
            "hostname",  # 不含 'host_name'，仅是 hostname——不敏感
        ):
            self.assertFalse(
                server._is_sensitive_key(not_sensitive),
                f"{not_sensitive!r} 不应被识别为敏感",
            )

    def test_redact_sensitive_replaces_value_in_dict(self) -> None:
        out = cast(
            "dict[str, Any]",
            server._redact_sensitive(
                {"bark_device_key": "real_token_xyz", "host": "127.0.0.1"}
            ),
        )
        self.assertEqual(out["bark_device_key"], "***REDACTED***")
        self.assertEqual(out["host"], "127.0.0.1")

    def test_redact_sensitive_recursive_into_nested_dict(self) -> None:
        out = cast(
            "dict[str, Any]",
            server._redact_sensitive(
                {
                    "notification": {
                        "enabled": True,
                        "bark_device_key": "real_token",
                        "bark_url": "https://example.com/",
                    },
                    "web_ui": {"host": "0.0.0.0", "port": 8080},
                }
            ),
        )
        notification = cast("dict[str, Any]", out["notification"])
        self.assertEqual(notification["bark_device_key"], "***REDACTED***")
        self.assertEqual(notification["enabled"], True)
        web_ui = cast("dict[str, Any]", out["web_ui"])
        self.assertEqual(web_ui["host"], "0.0.0.0")

    def test_redact_sensitive_recursive_into_list(self) -> None:
        out = cast(
            "list[dict[str, Any]]",
            server._redact_sensitive(
                [
                    {"api_key": "k1"},
                    {"name": "alice", "token": "t1"},
                ]
            ),
        )
        self.assertEqual(out[0]["api_key"], "***REDACTED***")
        self.assertEqual(out[1]["token"], "***REDACTED***")
        self.assertEqual(out[1]["name"], "alice")

    def test_redact_sensitive_does_not_mutate_input(self) -> None:
        """输入不应被原地修改——返回的是新的 dict。"""
        original = {"bark_device_key": "real"}
        out = cast("dict[str, Any]", server._redact_sensitive(original))
        self.assertEqual(original["bark_device_key"], "real")
        self.assertEqual(out["bark_device_key"], "***REDACTED***")

    def test_redact_sensitive_preserves_atomic_types(self) -> None:
        for atomic in (None, True, False, 42, 3.14, "hello"):
            self.assertEqual(
                server._redact_sensitive(atomic),
                atomic,
                f"原子类型 {atomic!r} 应原样返回",
            )


class TestPrintConfigRedactsBarkDeviceKey(unittest.TestCase):
    """E2E：``--print-config`` stdout 必须不含真实 bark_device_key。

    这是 CR#16 F-1 实施过程中发现的实际 bug：扩展 sections dump 后，
    notification.bark_device_key 直接进了 stdout。本类是回归 guard。
    """

    def test_real_bark_device_key_redacted_in_stdout(self) -> None:
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = server._print_effective_config()
        self.assertEqual(rc, 0)
        raw = buf.getvalue()
        # 解析 JSON，找 notification.bark_device_key 字段
        payload = json.loads(raw)
        notif = payload.get("sections", {}).get("notification", {})
        device_key = notif.get("bark_device_key")
        # 用户的 config.toml 里 bark_device_key 是 "uvMegCBMH9PQ8M2gDMpC4A"
        # （真实 device token）。本测试断言它**绝不**进 stdout。
        if device_key is not None:
            self.assertEqual(
                device_key,
                "***REDACTED***",
                f"bark_device_key 必须被 redact，实际：{device_key!r}",
            )


class TestPrintConfigFailureMode(unittest.TestCase):
    """探测失败时输出仍是 JSON——shell pipeline 能可靠处理。"""

    def test_output_is_valid_json_on_get_config_failure(self) -> None:
        with patch(
            "ai_intervention_agent.config_manager.get_config",
            side_effect=RuntimeError("simulated failure"),
        ):
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = server._print_effective_config()
        self.assertEqual(rc, 1, "失败路径必须返回 1")
        payload = json.loads(buf.getvalue())
        self.assertIn(
            "error",
            payload,
            "失败路径仍输出合法 JSON 含 error 字段——脚本可用 jq 区分",
        )


if __name__ == "__main__":
    unittest.main()
