"""R121-A：``GET /api/system/health`` 增强契约。

R53-F 在 ``test_system_health_r53f.py`` 已经覆盖：
  - 路由形状 / rate-limit / GET 方法
  - sse_bus / task_queue / recent_errors 三检查聚合
  - status enum (healthy/degraded/unhealthy) + HTTP 503/200 决策
  - 不做 loopback gate
  - payload 不漏 task.prompt / get_config()

R121-A 增量加固：
  1. 新增 ``notification`` check（{ok, enabled, providers_count, queue_size,
     delivery_success_rate, events_finalized, events_in_flight}）
  2. 新增顶层 ``version`` / ``uptime_seconds`` / ``config_file_path`` 字段
  3. status 决策考虑 notification 健康度（enabled+样本≥30+成功率<0.8 → degraded）
  4. 模块级 helpers (`_safe_*`) exception-safe，绝不让 health 端点 5xx
  5. **保留 R53-F 契约**：handler body 仍不能直接调 ``get_config()``，
     新字段必须通过模块级 helper 间接获取（这就是为什么有 ``_safe_config_file_path``）

设计意图：health endpoint 是监控仪表板 / K8s probe / Datadog
integration 的命脉，新字段 + 新决策维度都必须有自动化回归保护。
"""

from __future__ import annotations

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
    """提取 ``system_health()`` handler 的源码片段，用于做静态契约断言。"""
    m = re.search(
        r"def system_health\(\).*?(?=\n        @self\.app\.route|\nclass )",
        SOURCE,
        re.DOTALL,
    )
    if not m:
        raise AssertionError("无法在 system.py 里定位 system_health() handler 体")
    return m.group(0)


# ---------------------------------------------------------------------------
# 1. 新增子检查 + 顶层字段（静态源码契约）
# ---------------------------------------------------------------------------


class TestNotificationCheckPresent(unittest.TestCase):
    """handler 必须聚合 ``notification`` 检查。"""

    def setUp(self) -> None:
        self.body = _system_health_body()

    def test_aggregates_notification_check(self) -> None:
        self.assertIn(
            '"notification"',
            self.body,
            "/api/system/health 必须聚合 notification 子检查（R121-A）",
        )

    def test_uses_safe_notification_summary_helper(self) -> None:
        self.assertIn(
            "_safe_notification_summary()",
            self.body,
            "notification 检查必须走 _safe_notification_summary() helper（避免直接读敏感 config）",
        )


class TestTopLevelMetadataFieldsPresent(unittest.TestCase):
    """payload 必须含顶层 ``version`` / ``uptime_seconds`` / ``config_file_path``。"""

    def setUp(self) -> None:
        self.body = _system_health_body()

    def test_version_field_present(self) -> None:
        self.assertIn(
            '"version"',
            self.body,
            "payload 必须含 version 字段（R121-A：滚动升级时区分实例）",
        )

    def test_uptime_seconds_field_present(self) -> None:
        self.assertIn(
            '"uptime_seconds"',
            self.body,
            "payload 必须含 uptime_seconds 字段（R121-A：检测异常重启）",
        )

    def test_config_file_path_field_present(self) -> None:
        self.assertIn(
            '"config_file_path"',
            self.body,
            "payload 必须含 config_file_path 字段（R121-A：检测加载错配置）",
        )


# ---------------------------------------------------------------------------
# 2. R53-F 契约必须保留（回归保护）
# ---------------------------------------------------------------------------


class TestR53FContractsStillHold(unittest.TestCase):
    """R121-A 增强不能破坏 R53-F 已经编码的契约。"""

    def setUp(self) -> None:
        self.body = _system_health_body()

    def test_no_get_config_in_handler_body(self) -> None:
        """handler body 不能含 ``get_config()`` —— R53-F 的核心契约。"""
        self.assertNotIn(
            "get_config()",
            self.body,
            "R53-F 契约：handler 不应直接读 config（R121-A 也必须遵守，"
            "config 字段值改用 _safe_config_file_path() helper 间接读路径）",
        )

    def test_no_task_prompt_in_handler_body(self) -> None:
        self.assertNotIn(
            "task.prompt",
            self.body,
            "R53-F 契约：handler 不应触碰 task.prompt（R121-A 不引入新泄漏）",
        )

    def test_three_status_values_still_present(self) -> None:
        for value in ("healthy", "degraded", "unhealthy"):
            with self.subTest(value=value):
                self.assertIn(
                    f'"{value}"',
                    self.body,
                    f"R121-A 不应破坏 R53-F status enum：{value!r} 必须保留",
                )

    def test_503_still_associated_with_unhealthy(self) -> None:
        m = re.search(r'503\s+if\s+status\s*==\s*"unhealthy"', self.body)
        self.assertIsNotNone(
            m,
            "R121-A 不应破坏 R53-F 决策：503 仍必须只对应 unhealthy",
        )


# ---------------------------------------------------------------------------
# 3. helpers 行为契约（静态源码 + 运行时）
# ---------------------------------------------------------------------------


class TestHelpersDefinedAtModuleLevel(unittest.TestCase):
    """4 个 helper 必须在模块级别（而非 handler 内嵌），让 R53-F 测试通过。"""

    def test_safe_uptime_seconds_defined(self) -> None:
        self.assertTrue(
            hasattr(system_module, "_safe_uptime_seconds"),
            "_safe_uptime_seconds 必须在 module 级别可调用",
        )

    def test_safe_project_version_defined(self) -> None:
        self.assertTrue(
            hasattr(system_module, "_safe_project_version"),
            "_safe_project_version 必须在 module 级别可调用",
        )

    def test_safe_config_file_path_defined(self) -> None:
        self.assertTrue(
            hasattr(system_module, "_safe_config_file_path"),
            "_safe_config_file_path 必须在 module 级别可调用",
        )

    def test_safe_notification_summary_defined(self) -> None:
        self.assertTrue(
            hasattr(system_module, "_safe_notification_summary"),
            "_safe_notification_summary 必须在 module 级别可调用",
        )


class TestSafeUptimeSeconds(unittest.TestCase):
    """``_safe_uptime_seconds`` 行为契约。"""

    def test_returns_float_when_healthy(self) -> None:
        result = system_module._safe_uptime_seconds()
        self.assertIsNotNone(result, "正常情况下应返回 float（进程已启动）")
        # 让 ty narrow result 为 float（``assertIsNotNone`` 不更新 ty 的
        # 类型推断，下方 ``assertGreater`` 会因 ``Optional[float]`` 与
        # ``float`` 的 overload 不匹配报 no-matching-overload）。
        assert result is not None
        self.assertIsInstance(result, float)
        self.assertGreater(result, 0.0, "uptime 必须 > 0（导入时已开始计时）")

    def test_returns_none_on_missing_attribute(self) -> None:
        """server 模块的 ``_PROCESS_STARTED_AT_UNIX`` 缺失时 graceful 返回 None。"""
        from ai_intervention_agent import server as server_module

        original = server_module._PROCESS_STARTED_AT_UNIX
        try:
            del server_module._PROCESS_STARTED_AT_UNIX
            result = system_module._safe_uptime_seconds()
            self.assertIsNone(result, "属性缺失时必须返回 None，而不是抛")
        finally:
            server_module._PROCESS_STARTED_AT_UNIX = original

    def test_returns_none_on_invalid_type(self) -> None:
        from ai_intervention_agent import server as server_module

        original = server_module._PROCESS_STARTED_AT_UNIX
        try:
            # 故意赋 str 测 graceful 降级。原版用的 mypy ``type ignore``
            # 注释 ty 不认（ty 仍报 invalid-assignment），改 ty 原生
            # 语法。
            server_module._PROCESS_STARTED_AT_UNIX = "not a number"  # ty: ignore[invalid-assignment]
            result = system_module._safe_uptime_seconds()
            self.assertIsNone(result, "类型不对时必须返回 None")
        finally:
            server_module._PROCESS_STARTED_AT_UNIX = original


class TestSafeProjectVersion(unittest.TestCase):
    """``_safe_project_version`` 行为契约。"""

    def test_returns_string_when_healthy(self) -> None:
        result = system_module._safe_project_version()
        self.assertIsNotNone(result, "正常情况下应返回字符串版本号")
        self.assertIsInstance(result, str)

    def test_returns_none_on_exception(self) -> None:
        with patch(
            "ai_intervention_agent.web_ui.get_project_version",
            side_effect=RuntimeError("simulated"),
        ):
            result = system_module._safe_project_version()
            self.assertIsNone(result, "get_project_version 抛异常时必须返回 None")


class TestSafeConfigFilePath(unittest.TestCase):
    """``_safe_config_file_path`` 行为契约。"""

    def test_returns_string_or_none(self) -> None:
        result = system_module._safe_config_file_path()
        # 可能是 str（配置文件已加载）或 None（exception path），都不能抛
        self.assertTrue(
            result is None or isinstance(result, str),
            "返回值必须是 str 或 None",
        )

    def test_returns_none_on_get_config_exception(self) -> None:
        """``get_config()`` 抛异常时 helper 必须 graceful 返回 None。"""
        with patch(
            "ai_intervention_agent.web_ui_routes.system.get_config",
            side_effect=RuntimeError("simulated config load failure"),
        ):
            result = system_module._safe_config_file_path()
            self.assertIsNone(result, "get_config 异常时必须 graceful 返回 None")


class TestSafeNotificationSummary(unittest.TestCase):
    """``_safe_notification_summary`` 行为契约。"""

    def test_returns_dict_or_none(self) -> None:
        result = system_module._safe_notification_summary()
        self.assertTrue(
            result is None or isinstance(result, dict),
            "返回值必须是 dict 或 None",
        )

    def test_dict_shape_matches_contract(self) -> None:
        result = system_module._safe_notification_summary()
        if result is None:
            self.skipTest("notification_manager 不可用，跳过 shape 检查")
        expected_keys = {
            "enabled",
            "providers_count",
            "queue_size",
            "delivery_success_rate",
            "events_finalized",
            "events_in_flight",
        }
        actual_keys = set(result.keys())
        self.assertEqual(
            expected_keys,
            actual_keys,
            f"summary keys 不匹配契约：缺 {expected_keys - actual_keys}，"
            f"多 {actual_keys - expected_keys}",
        )

    def test_no_sensitive_fields_in_summary(self) -> None:
        """summary 不能含 ``config`` 子树（含 token / bark_secret 等）。"""
        result = system_module._safe_notification_summary()
        if result is None:
            self.skipTest("notification_manager 不可用，跳过敏感字段检查")
        forbidden = {"config", "providers", "stats"}
        for key in forbidden:
            self.assertNotIn(
                key,
                result,
                f"summary 不能透出 {key!r}（可能含敏感字段或过于详细）",
            )

    def test_returns_none_on_exception(self) -> None:
        """notification_manager.get_status 抛时必须 graceful 返回 None。"""
        from ai_intervention_agent.notification_manager import notification_manager

        with patch.object(
            notification_manager,
            "get_status",
            side_effect=RuntimeError("simulated notification manager failure"),
        ):
            result = system_module._safe_notification_summary()
            self.assertIsNone(
                result,
                "notification_manager.get_status 异常时必须返回 None",
            )

    def test_returns_none_when_status_returns_non_dict(self) -> None:
        """get_status 返回非 dict（破坏契约）时 helper 必须 graceful 返回 None。"""
        from ai_intervention_agent.notification_manager import notification_manager

        with patch.object(
            notification_manager,
            "get_status",
            return_value="not a dict",
        ):
            result = system_module._safe_notification_summary()
            self.assertIsNone(
                result,
                "get_status 返回非 dict 时必须 graceful 返回 None",
            )


# ---------------------------------------------------------------------------
# 4. status 决策：notification 健康度参与 degraded 判定
# ---------------------------------------------------------------------------


class TestStatusDecisionConsidersNotificationHealth(unittest.TestCase):
    """notification 子健康度必须参与 degraded 决策（在源码层面有体现）。"""

    def setUp(self) -> None:
        self.body = _system_health_body()

    def test_handler_references_notification_in_degraded_decision(self) -> None:
        """``notif_degraded`` 变量 / 注入必须出现在决策块。"""
        self.assertIn(
            "notif_degraded",
            self.body,
            "status 决策必须考虑 notification 健康度（R121-A）",
        )

    def test_finalized_threshold_documented(self) -> None:
        """门槛 ``30`` 个 finalized 必须在源码里有体现，避免被无意改成低门槛。"""
        # 既要有 ``finalized >= 30``，又要有 0.8 success_rate 比较
        self.assertRegex(
            self.body,
            r"finalized\s*>=\s*30",
            "门槛 30 finalized 是 R121-A 的反误判设计，必须保留",
        )
        self.assertIn(
            "0.8",
            self.body,
            "成功率门槛 0.8 是 R121-A 决策设计，必须保留",
        )


# ---------------------------------------------------------------------------
# 5. payload 结构契约（静态源码层面）—— end-to-end Flask 集成测试故意不做
#
# WebFeedbackUI 的实例化需要 (host, port, prompt, ...) 多参数 + Flask + CORS +
# limiter + mDNS 全套依赖，跑一个 test client 仅为了拿响应字段会让测试设
# 置非常脆弱（任何配置改动都可能挂掉测试）。**用源码契约 + helper 单测**
# 已经能覆盖 R121-A 的全部行为表面（payload 字段、helper 异常路径、status
# 决策门槛），代价是省掉了 end-to-end 网络栈这一层验证 —— 但同样的端到端
# 场景在 R53-F 已经用静态源码契约验证过 ``payload = {"status": ...}``，
# R121-A 沿用同一套机制即可。
# ---------------------------------------------------------------------------


class TestPayloadStructureContract(unittest.TestCase):
    """payload dict literal 必须含 R121-A 新字段（源码层面契约）。"""

    def setUp(self) -> None:
        self.body = _system_health_body()

    def test_payload_dict_contains_version_key(self) -> None:
        m = re.search(r'"version":\s*_safe_project_version\(\)', self.body)
        self.assertIsNotNone(
            m,
            'payload dict literal 必须有 ``"version": _safe_project_version()`` '
            "（R121-A 契约：value 必须走 helper，不能 inline）",
        )

    def test_payload_dict_contains_uptime_seconds_key(self) -> None:
        m = re.search(r'"uptime_seconds":\s*_safe_uptime_seconds\(\)', self.body)
        self.assertIsNotNone(
            m,
            'payload dict literal 必须有 ``"uptime_seconds": _safe_uptime_seconds()`` '
            "（R121-A 契约：value 必须走 helper）",
        )

    def test_payload_dict_contains_config_file_path_key(self) -> None:
        m = re.search(r'"config_file_path":\s*_safe_config_file_path\(\)', self.body)
        self.assertIsNotNone(
            m,
            'payload dict literal 必须有 ``"config_file_path": '
            "_safe_config_file_path()`` （R121-A 契约：value 必须走 helper，"
            "不能 inline get_config）",
        )


# ---------------------------------------------------------------------------
# 6. 文档更新检查（OpenAPI 里必须提到新字段）
# ---------------------------------------------------------------------------


class TestSwaggerDocsIncludeR121AFields(unittest.TestCase):
    """OpenAPI 描述必须提到 R121-A 新字段，否则前端 / 监控集成会困惑。"""

    def setUp(self) -> None:
        self.body = _system_health_body()

    def test_docstring_mentions_version_field(self) -> None:
        self.assertIn(
            "``version``",
            self.body,
            "OpenAPI 文档必须描述 version 字段（R121-A）",
        )

    def test_docstring_mentions_uptime_seconds_field(self) -> None:
        self.assertIn(
            "``uptime_seconds``",
            self.body,
            "OpenAPI 文档必须描述 uptime_seconds 字段（R121-A）",
        )

    def test_docstring_mentions_config_file_path_field(self) -> None:
        self.assertIn(
            "``config_file_path``",
            self.body,
            "OpenAPI 文档必须描述 config_file_path 字段（R121-A）",
        )


if __name__ == "__main__":
    unittest.main()
