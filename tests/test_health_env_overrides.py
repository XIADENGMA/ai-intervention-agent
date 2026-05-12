"""CR#15 续 · ``GET /api/system/health`` 暴露 ``web_ui_env_overrides`` 字段。

设计目标
========

本周期新增了三条 ``AI_INTERVENTION_AGENT_WEB_UI_*`` env override（host /
port / language），但 K8s probe / 监控仪表板**没法**仅靠 ``host`` /
``port`` 字段判断 "这个进程是不是被 env 覆盖了"——所有值都已经经过
``service_manager.get_web_ui_config()`` merge，下游看到的是终态。

CR#15 续给 ``/api/system/health`` 加 ``web_ui_env_overrides`` 字段，让
运维一眼看出：

* ``{}``：无 env override 生效，配置全来自 ``config.toml`` / 默认值；
* ``{env_name: value, ...}``：env override 名单（明文值，host/port/language
  都不敏感）；
* ``null``：探测失败。

invariant 守护
========

1. ``_safe_web_ui_env_overrides()`` 行为正确：``{}`` / 命中 / 异常路径；
2. ``/api/system/health`` payload 含 ``web_ui_env_overrides`` 字段；
3. 仅暴露 web_ui 三个明确 env var（白名单），不会因为未来添加新 env
   override（如 LOG_LEVEL）就悄悄扩面到敏感字段；
4. handler body 通过 ``_safe_*`` helper 间接访问 env，保留 R53-F 的
   "handler 不直接读配置" 契约。
"""

from __future__ import annotations

import os
import re
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ai_intervention_agent.web_ui_routes import system as system_module

SOURCE = Path(system_module.__file__).read_text(encoding="utf-8")


def _system_health_body() -> str:
    m = re.search(
        r"def system_health\(\).*?(?=\n        @self\.app\.route|\nclass )",
        SOURCE,
        re.DOTALL,
    )
    if not m:
        raise AssertionError("无法在 system.py 里定位 system_health() handler 体")
    return m.group(0)


# ---------------------------------------------------------------------------
# 1. ``_safe_web_ui_env_overrides()`` 直接函数测试
# ---------------------------------------------------------------------------


class TestSafeWebUiEnvOverridesEmpty(unittest.TestCase):
    """env 全部未设时返回 ``{}``——表示"无 override 生效"的明确语义。"""

    def setUp(self) -> None:
        # 清干净三个 env，避免被前一个测试 / 外部环境污染
        from ai_intervention_agent import service_manager as _sm

        for env_name in (
            _sm._ENV_WEB_UI_HOST,
            _sm._ENV_WEB_UI_PORT,
            _sm._ENV_WEB_UI_LANGUAGE,
        ):
            os.environ.pop(env_name, None)

    def test_returns_empty_dict_when_no_env_set(self) -> None:
        result = system_module._safe_web_ui_env_overrides()
        self.assertEqual(
            result,
            {},
            f"无 env 覆盖时应返回 {{}}（非 None），实际：{result!r}",
        )

    def test_returns_empty_dict_when_env_is_whitespace(self) -> None:
        """全空白 env 等价于未设——避免 shell 误粘空格被当成 override。"""
        from ai_intervention_agent import service_manager as _sm

        with patch.dict(
            os.environ,
            {
                _sm._ENV_WEB_UI_HOST: "   ",
                _sm._ENV_WEB_UI_PORT: "\t\n",
                _sm._ENV_WEB_UI_LANGUAGE: "",
            },
            clear=False,
        ):
            result = system_module._safe_web_ui_env_overrides()
        self.assertEqual(result, {})


class TestSafeWebUiEnvOverridesHit(unittest.TestCase):
    """有 env 命中时返回完整 dict，明文 host/port/language 值。"""

    def setUp(self) -> None:
        from ai_intervention_agent import service_manager as _sm

        for env_name in (
            _sm._ENV_WEB_UI_HOST,
            _sm._ENV_WEB_UI_PORT,
            _sm._ENV_WEB_UI_LANGUAGE,
        ):
            os.environ.pop(env_name, None)

    def test_single_env_override_reflected(self) -> None:
        from ai_intervention_agent import service_manager as _sm

        with patch.dict(os.environ, {_sm._ENV_WEB_UI_PORT: "8181"}, clear=False):
            result = system_module._safe_web_ui_env_overrides()
        self.assertEqual(result, {_sm._ENV_WEB_UI_PORT: "8181"})

    def test_all_three_env_overrides_reflected(self) -> None:
        from ai_intervention_agent import service_manager as _sm

        with patch.dict(
            os.environ,
            {
                _sm._ENV_WEB_UI_HOST: "0.0.0.0",
                _sm._ENV_WEB_UI_PORT: "9000",
                _sm._ENV_WEB_UI_LANGUAGE: "zh-CN",
            },
            clear=False,
        ):
            result = system_module._safe_web_ui_env_overrides()
        self.assertEqual(
            result,
            {
                _sm._ENV_WEB_UI_HOST: "0.0.0.0",
                _sm._ENV_WEB_UI_PORT: "9000",
                _sm._ENV_WEB_UI_LANGUAGE: "zh-CN",
            },
        )

    def test_strips_surrounding_whitespace(self) -> None:
        """env 值前后空白应被 trim——配合 ``_coerce_env_str`` 一致行为。"""
        from ai_intervention_agent import service_manager as _sm

        with patch.dict(os.environ, {_sm._ENV_WEB_UI_PORT: "  8181  "}, clear=False):
            result = system_module._safe_web_ui_env_overrides()
        self.assertEqual(result, {_sm._ENV_WEB_UI_PORT: "8181"})


class TestSafeWebUiEnvOverridesWhitelisted(unittest.TestCase):
    """白名单：仅暴露 host/port/language 三个 env，未来加新 env override
    不会自动扩面到敏感字段——避免悄悄泄漏。"""

    def setUp(self) -> None:
        from ai_intervention_agent import service_manager as _sm

        for env_name in (
            _sm._ENV_WEB_UI_HOST,
            _sm._ENV_WEB_UI_PORT,
            _sm._ENV_WEB_UI_LANGUAGE,
        ):
            os.environ.pop(env_name, None)

    def test_does_not_expose_unrelated_env_vars(self) -> None:
        """无关 env vars（即使匹配 ``AI_INTERVENTION_AGENT_*`` 前缀）也不
        应出现在 web_ui_env_overrides。"""
        with patch.dict(
            os.environ,
            {
                "AI_INTERVENTION_AGENT_LOG_LEVEL": "DEBUG",
                "AI_INTERVENTION_AGENT_SECRET_KEY": "should-never-leak",
                "AI_INTERVENTION_AGENT_CONFIG_FILE": "/some/path",
                "AI_INTERVENTION_AGENT_FAKE_FUTURE_VAR": "value",
            },
            clear=False,
        ):
            result = system_module._safe_web_ui_env_overrides()
        self.assertEqual(
            result,
            {},
            f"白名单外的 env vars 不应出现，实际：{result!r}",
        )

    def test_dict_keys_match_service_manager_constants(self) -> None:
        """字段 key 必须是 service_manager 暴露的常量值——避免硬编码漂移。"""
        from ai_intervention_agent import service_manager as _sm

        with patch.dict(
            os.environ,
            {
                _sm._ENV_WEB_UI_HOST: "127.0.0.1",
                _sm._ENV_WEB_UI_PORT: "8080",
                _sm._ENV_WEB_UI_LANGUAGE: "en",
            },
            clear=False,
        ):
            result = system_module._safe_web_ui_env_overrides()
        self.assertEqual(
            set(result.keys()),
            {
                _sm._ENV_WEB_UI_HOST,
                _sm._ENV_WEB_UI_PORT,
                _sm._ENV_WEB_UI_LANGUAGE,
            },
        )


class TestSafeWebUiEnvOverridesFailureMode(unittest.TestCase):
    """探测失败时返回 ``None``——绝不让 health 端点因为本字段挂掉。

    我们通过两个角度交叉证明 fail-safe：
    1. 源码层：函数体被 try / except 包围（静态契约）；
    2. 运行时层：``os.environ.get`` 抛异常时函数返回 ``None``（动态契约）。

    单 ``service_manager`` import 失败的场景**不**测，因为 system_module
    被 import 时已经把 service_manager 拉进 ``sys.modules`` 缓存，二次
    import 不再走 ``__import__``——任何模拟方式都会 leak 进其它测试。
    """

    def test_function_source_has_try_except_guard(self) -> None:
        """源码契约：函数体必须包 ``try/except``，否则任何运行时异常都会
        让 ``/api/system/health`` 5xx——违反 R53-F "health 端点绝不挂"。"""
        import inspect

        source = inspect.getsource(system_module._safe_web_ui_env_overrides)
        self.assertIn("try:", source)
        self.assertIn("except", source)
        self.assertIn("return None", source)

    def test_returns_none_when_os_environ_raises(self) -> None:
        """``os.environ.get`` 异常（极端：chroot/sandbox bug）时返回 None。"""

        def raising_get(*args, **kwargs):
            raise RuntimeError("simulated environ failure")

        with patch.object(os.environ, "get", side_effect=raising_get):
            result = system_module._safe_web_ui_env_overrides()
        self.assertIsNone(
            result,
            "os.environ.get 抛异常时应返回 None，让 health endpoint 用 null"
            "表达'探测失败'，而不是把 dict 当无 override（误报）",
        )


# ---------------------------------------------------------------------------
# 2. ``/api/system/health`` payload 静态契约
# ---------------------------------------------------------------------------


class TestHealthPayloadContainsField(unittest.TestCase):
    """system_health() handler 必须在 payload 里加 web_ui_env_overrides。"""

    def setUp(self) -> None:
        self.body = _system_health_body()

    def test_payload_includes_field(self) -> None:
        self.assertIn(
            '"web_ui_env_overrides"',
            self.body,
            "/api/system/health payload 必须含 web_ui_env_overrides 字段——"
            "K8s probe / 监控仪表板需要它判断 'env 是不是覆盖了 config.toml'",
        )

    def test_payload_uses_safe_helper(self) -> None:
        """必须通过 ``_safe_web_ui_env_overrides()`` 间接读 env，保留
        R53-F "handler 不直接访问配置 API" 契约。"""
        self.assertIn(
            "_safe_web_ui_env_overrides()",
            self.body,
            "新字段必须走 _safe_* helper，避免 handler body 直接读 env",
        )


if __name__ == "__main__":
    unittest.main()
