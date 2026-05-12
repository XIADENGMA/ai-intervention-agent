"""env-override · `service_manager` 环境变量覆盖 web_ui.host/port/language 的回归测试。

设计目标
========

为方便 uvx / Docker / systemd 等"无法直接编辑 config.toml"的运行场景，
新增三条 env vars 在进程启动时一次性覆盖 web_ui 配置：

* ``AI_INTERVENTION_AGENT_WEB_UI_HOST`` → ``web_ui.host``
* ``AI_INTERVENTION_AGENT_WEB_UI_PORT`` → ``web_ui.port``（[1, 65535]）
* ``AI_INTERVENTION_AGENT_WEB_UI_LANGUAGE`` → ``web_ui.language``

对标 ``mcp-feedback-enhanced`` 的 ``MCP_WEB_HOST`` / ``MCP_WEB_PORT`` /
``MCP_LANGUAGE`` 风格，但用项目现有的 ``AI_INTERVENTION_AGENT_*`` 命名
前缀（与 ``AI_INTERVENTION_AGENT_CONFIG_FILE`` /
``AI_INTERVENTION_AGENT_LOG_LEVEL`` 等保持一致）。

本测试守护三条 invariant：

1. env 未设置时 ``get_web_ui_config()`` 行为不变（与未引入 env override
   前的契约完全相同）；
2. env 合法值能命中覆盖路径（host / port / language 各一例）；
3. env 非法值（int 解析失败 / 越界 / 空白）记 warning 并 fallback 到
   config.toml 默认值，**不抛异常**——env override 是便利路径，错值
   不应让 server 启动失败。
"""

from __future__ import annotations

import logging
import unittest
from unittest.mock import patch

from ai_intervention_agent import service_manager


def _clear_web_ui_cache() -> None:
    """直接清空 ``_config_cache``，避免下次 ``get_web_ui_config`` 命中缓存。

    用 ``_invalidate_runtime_caches_on_config_change()`` 也可以，但它额外
    会关闭 httpx 客户端，这里不需要那种副作用。
    """
    with service_manager._config_cache_lock:
        service_manager._config_cache["config"] = None
        service_manager._config_cache["timestamp"] = 0


_BASELINE_WEB_UI_SECTION = {
    "host": "127.0.0.1",
    "port": 8080,
    "language": "auto",
    "http_request_timeout": 30,
    "http_max_retries": 3,
    "http_retry_delay": 1.0,
    "external_base_url": "",
}
_BASELINE_FEEDBACK_SECTION = {
    "frontend_countdown": 240,
}
_BASELINE_NETWORK_SECURITY_SECTION: dict = {}


class _StubConfigManager:
    """轻量 stub，仅实现 ``get_section`` 接口。"""

    def __init__(
        self,
        web_ui: dict | None = None,
        feedback: dict | None = None,
        network_security: dict | None = None,
    ) -> None:
        self._sections = {
            "web_ui": dict(web_ui or _BASELINE_WEB_UI_SECTION),
            "feedback": dict(feedback or _BASELINE_FEEDBACK_SECTION),
            "network_security": dict(
                network_security
                if network_security is not None
                else _BASELINE_NETWORK_SECURITY_SECTION
            ),
        }

    def get_section(self, section: str) -> dict:
        return self._sections.get(section, {})


class TestCoerceEnvStr(unittest.TestCase):
    """``_coerce_env_str`` 直接函数测试：empty / whitespace / set 三态。"""

    def test_unset_returns_none(self) -> None:
        with patch.dict("os.environ", {}, clear=False):
            import os as _os

            _os.environ.pop("AIIA_TEST_UNSET_VAR", None)
            self.assertIsNone(service_manager._coerce_env_str("AIIA_TEST_UNSET_VAR"))

    def test_empty_string_returns_none(self) -> None:
        with patch.dict("os.environ", {"AIIA_TEST_EMPTY": ""}, clear=False):
            self.assertIsNone(service_manager._coerce_env_str("AIIA_TEST_EMPTY"))

    def test_whitespace_only_returns_none(self) -> None:
        with patch.dict("os.environ", {"AIIA_TEST_WS": "   \t  \n"}, clear=False):
            self.assertIsNone(service_manager._coerce_env_str("AIIA_TEST_WS"))

    def test_trims_surrounding_whitespace(self) -> None:
        with patch.dict("os.environ", {"AIIA_TEST_TRIM": "  hello  "}, clear=False):
            self.assertEqual(service_manager._coerce_env_str("AIIA_TEST_TRIM"), "hello")

    def test_returns_non_empty_value(self) -> None:
        with patch.dict("os.environ", {"AIIA_TEST_VAL": "0.0.0.0"}, clear=False):
            self.assertEqual(
                service_manager._coerce_env_str("AIIA_TEST_VAL"), "0.0.0.0"
            )


class TestCoerceEnvInt(unittest.TestCase):
    """``_coerce_env_int`` 直接函数测试：边界 / 非法值 / 范围验证。"""

    def test_unset_returns_none(self) -> None:
        with patch.dict("os.environ", {}, clear=False):
            import os as _os

            _os.environ.pop("AIIA_TEST_INT_UNSET", None)
            self.assertIsNone(
                service_manager._coerce_env_int("AIIA_TEST_INT_UNSET", 1, 100)
            )

    def test_valid_value_returns_int(self) -> None:
        with patch.dict("os.environ", {"AIIA_TEST_INT_OK": "9000"}, clear=False):
            self.assertEqual(
                service_manager._coerce_env_int("AIIA_TEST_INT_OK", 1, 65535), 9000
            )

    def test_invalid_value_logs_warning_and_returns_none(self) -> None:
        with (
            patch.dict(
                "os.environ", {"AIIA_TEST_INT_BAD": "not-a-number"}, clear=False
            ),
            self.assertLogs(service_manager.logger.logger, level=logging.WARNING) as cm,
        ):
            result = service_manager._coerce_env_int("AIIA_TEST_INT_BAD", 1, 65535)
        self.assertIsNone(result)
        self.assertTrue(
            any("AIIA_TEST_INT_BAD" in line for line in cm.output),
            f"warning 日志未包含 env 名，实际: {cm.output!r}",
        )

    def test_below_lower_bound_logs_warning_and_returns_none(self) -> None:
        with (
            patch.dict("os.environ", {"AIIA_TEST_INT_LOW": "0"}, clear=False),
            self.assertLogs(service_manager.logger.logger, level=logging.WARNING) as cm,
        ):
            result = service_manager._coerce_env_int("AIIA_TEST_INT_LOW", 1, 65535)
        self.assertIsNone(result)
        self.assertTrue(
            any("超出合法范围" in line for line in cm.output),
            f"warning 日志未提示越界，实际: {cm.output!r}",
        )

    def test_above_upper_bound_logs_warning_and_returns_none(self) -> None:
        with (
            patch.dict("os.environ", {"AIIA_TEST_INT_HIGH": "99999"}, clear=False),
            self.assertLogs(service_manager.logger.logger, level=logging.WARNING) as cm,
        ):
            result = service_manager._coerce_env_int("AIIA_TEST_INT_HIGH", 1, 65535)
        self.assertIsNone(result)
        self.assertTrue(
            any("超出合法范围" in line for line in cm.output),
            f"warning 日志未提示越界，实际: {cm.output!r}",
        )

    def test_boundary_values_pass(self) -> None:
        """``lo`` 和 ``hi`` 自身应被接受（闭区间）。"""
        with patch.dict("os.environ", {"AIIA_TEST_LO": "1"}, clear=False):
            self.assertEqual(
                service_manager._coerce_env_int("AIIA_TEST_LO", 1, 65535), 1
            )
        with patch.dict("os.environ", {"AIIA_TEST_HI": "65535"}, clear=False):
            self.assertEqual(
                service_manager._coerce_env_int("AIIA_TEST_HI", 1, 65535), 65535
            )


class TestGetWebUIConfigEnvOverride(unittest.TestCase):
    """``get_web_ui_config()`` 端到端 env override 路径。"""

    def setUp(self) -> None:
        _clear_web_ui_cache()
        # 清掉本测试关心的 env vars，避免被前一个测试 / 用户环境污染
        import os as _os

        for env_name in (
            service_manager._ENV_WEB_UI_HOST,
            service_manager._ENV_WEB_UI_PORT,
            service_manager._ENV_WEB_UI_LANGUAGE,
        ):
            _os.environ.pop(env_name, None)

    def tearDown(self) -> None:
        _clear_web_ui_cache()

    def _call_with_stub_config(
        self,
        env_overrides: dict[str, str] | None = None,
        web_ui_section: dict | None = None,
    ) -> tuple:
        """便利封装：以 stub config + 指定 env 调用 get_web_ui_config。"""
        stub = _StubConfigManager(web_ui=web_ui_section)
        env = env_overrides or {}
        with (
            patch(
                "ai_intervention_agent.service_manager.get_config", return_value=stub
            ),
            patch.dict("os.environ", env, clear=False),
        ):
            _clear_web_ui_cache()
            return service_manager.get_web_ui_config()

    def test_no_env_uses_config_toml_defaults(self) -> None:
        """env 全部未设时，host/port/language 来自 stub config。"""
        config, _ = self._call_with_stub_config()
        self.assertEqual(config.host, "127.0.0.1")
        self.assertEqual(config.port, 8080)
        self.assertEqual(config.language, "auto")

    def test_host_env_override(self) -> None:
        config, _ = self._call_with_stub_config(
            env_overrides={service_manager._ENV_WEB_UI_HOST: "0.0.0.0"}
        )
        self.assertEqual(config.host, "0.0.0.0")

    def test_port_env_override_valid(self) -> None:
        config, _ = self._call_with_stub_config(
            env_overrides={service_manager._ENV_WEB_UI_PORT: "9000"}
        )
        self.assertEqual(config.port, 9000)

    def test_port_env_override_invalid_falls_back(self) -> None:
        """非数字 env value 应记 warning 并 fallback 到 config 默认值。"""
        with self.assertLogs(
            service_manager.logger.logger, level=logging.WARNING
        ) as cm:
            config, _ = self._call_with_stub_config(
                env_overrides={service_manager._ENV_WEB_UI_PORT: "not-an-int"}
            )
        self.assertEqual(config.port, 8080, "非法 env 应不影响 port，仍用 stub 默认")
        self.assertTrue(
            any("AI_INTERVENTION_AGENT_WEB_UI_PORT" in line for line in cm.output),
            f"warning 应提到 env 名，实际: {cm.output!r}",
        )

    def test_port_env_override_out_of_range_falls_back(self) -> None:
        config, _ = self._call_with_stub_config(
            env_overrides={service_manager._ENV_WEB_UI_PORT: "99999"}
        )
        self.assertEqual(config.port, 8080)

    def test_language_env_override(self) -> None:
        config, _ = self._call_with_stub_config(
            env_overrides={service_manager._ENV_WEB_UI_LANGUAGE: "en"}
        )
        self.assertEqual(config.language, "en")

    def test_all_three_env_overrides_together(self) -> None:
        config, _ = self._call_with_stub_config(
            env_overrides={
                service_manager._ENV_WEB_UI_HOST: "192.168.1.100",
                service_manager._ENV_WEB_UI_PORT: "18080",
                service_manager._ENV_WEB_UI_LANGUAGE: "zh-CN",
            }
        )
        self.assertEqual(config.host, "192.168.1.100")
        self.assertEqual(config.port, 18080)
        self.assertEqual(config.language, "zh-CN")

    def test_empty_env_treated_as_unset(self) -> None:
        """env 设为空字符串应等价于未设置（不覆盖）。"""
        config, _ = self._call_with_stub_config(
            env_overrides={
                service_manager._ENV_WEB_UI_HOST: "",
                service_manager._ENV_WEB_UI_PORT: "",
                service_manager._ENV_WEB_UI_LANGUAGE: "",
            }
        )
        self.assertEqual(config.host, "127.0.0.1")
        self.assertEqual(config.port, 8080)
        self.assertEqual(config.language, "auto")

    def test_host_env_override_logs_info(self) -> None:
        """命中 host override 时应记 info 让运维能反查。"""
        with self.assertLogs(service_manager.logger.logger, level=logging.INFO) as cm:
            self._call_with_stub_config(
                env_overrides={service_manager._ENV_WEB_UI_HOST: "10.0.0.1"}
            )
        self.assertTrue(
            any(
                "AI_INTERVENTION_AGENT_WEB_UI_HOST" in line and "10.0.0.1" in line
                for line in cm.output
            ),
            f"info 日志应包含 env 名和新值，实际: {cm.output!r}",
        )


if __name__ == "__main__":
    unittest.main()
