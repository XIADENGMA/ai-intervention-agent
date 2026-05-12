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
        payload = self._run()
        for key in ("config_file_path", "web_ui", "env_overrides"):
            self.assertIn(
                key,
                payload,
                f"payload 必须含 {key} top-level key（自省/监控/CI 都依赖）",
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
        """直接重置 service_manager 的 web_ui 配置 TTL 缓存。"""
        from ai_intervention_agent import service_manager as _sm

        with _sm._config_cache_lock:
            _sm._config_cache["config"] = None
            _sm._config_cache["timestamp"] = 0.0

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
