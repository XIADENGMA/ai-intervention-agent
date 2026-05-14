"""R188 / T3 · ``GET/POST /api/system/log-level`` 运行时日志级别动态调整。

背景
----
R93 把 ``AI_INTERVENTION_AGENT_LOG_LEVEL`` env var 接到 server 启动路径，
让 standalone 部署能在启动前选定日志级别。但**运行时**没有调旋钮——一
旦 server 跑起来，要改 level 必须杀进程、改 env var、重启，对生产环境
非常笨重。

R188 / T3 把 ``configure_logging_from_config()`` 的核心动作（``root_logger.
setLevel(level) + 所有 handler.setLevel(level)``）封装到一个运行时 helper
``apply_runtime_log_level(level)``，并暴露 ``GET/POST /api/system/log-level``
端点让运维 / 调试场景下零停机切换。

设计约束
========
1. **零持久化**：本 API 只改运行时；下次启动仍走 env var / config 路径。
   运维忘记关回去不会污染 config。
2. **攻击面最小化**：只接受 5 个 enum 值（``DEBUG`` / ``INFO`` / ``WARNING``
   / ``ERROR`` / ``CRITICAL``），不接受任意 ``logger_name`` 参数（防止远程
   把 ``zeroconf`` / ``httpx`` 调成 DEBUG 让日志爆量）。
3. **POST 仅 loopback**：与 ``open-config-file`` 同档安全级别——远程主
   机不能通过 Web UI 修改 server 日志策略。
4. **GET 任意来源**：返回的只是 enum + level 名，没有 PII / 敏感信息。
5. **失败原子化**：``apply_runtime_log_level`` 先验证 level 合法再
   setLevel；validation 失败时不留半改半未改的状态。

测试覆盖（17 cases / 4 invariant classes）：

1. **``get_current_log_level()`` helper**（3 cases）
   - 返回字段是 ``{root_level, aiia_level, valid_levels}`` 三件套
   - level 字段是 string（不是 int），便于直接 JSON 序列化
   - ``valid_levels`` 含 5 个 enum 值

2. **``apply_runtime_log_level()`` helper**（6 cases）
   - 接受大写 enum
   - 大小写不敏感（``"debug"`` 也能用）
   - 非法 level 抛 ``ValueError`` 不修改 state
   - 非字符串抛 ``ValueError``
   - 返回值含 ``old_level`` / ``new_level`` / ``logger``
   - 修改后 ``logging.getLogger().getEffectiveLevel()`` 立即反映

3. **HTTP GET 端点**（3 cases）
   - 任意来源都 200
   - 返回字段含 ``success`` + level 三件套
   - 不需要 payload

4. **HTTP POST 端点**（5 cases）
   - loopback + 合法 level → 200 + 改 root logger
   - 非 loopback → 403
   - payload 缺 level → 400
   - level 非 string → 400
   - level 非法 → 400 + 错误消息含 valid enum 提示
"""

from __future__ import annotations

import logging
import sys
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ai_intervention_agent.enhanced_logging import (
    VALID_LOG_LEVELS,
    apply_runtime_log_level,
    get_current_log_level,
)


def _save_and_restore_root_level() -> int:
    """工具：保存当前 root logger level，用于测试 tearDown 还原。"""
    return logging.getLogger().getEffectiveLevel()


# ---------------------------------------------------------------------------
# 1. get_current_log_level helper
# ---------------------------------------------------------------------------


class TestGetCurrentLogLevel(unittest.TestCase):
    def setUp(self) -> None:
        self._original_level = _save_and_restore_root_level()

    def tearDown(self) -> None:
        logging.getLogger().setLevel(self._original_level)

    def test_returns_three_required_fields(self) -> None:
        snapshot = get_current_log_level()
        self.assertIn("root_level", snapshot)
        self.assertIn("aiia_level", snapshot)
        self.assertIn("valid_levels", snapshot)

    def test_level_fields_are_string_not_int(self) -> None:
        snapshot = get_current_log_level()
        self.assertIsInstance(snapshot["root_level"], str)
        self.assertIsInstance(snapshot["aiia_level"], str)
        # JSON-friendly: client UI 不该再做 reverse-lookup
        self.assertNotEqual(snapshot["root_level"], "")
        self.assertNotEqual(snapshot["aiia_level"], "")

    def test_valid_levels_contains_all_five_enums(self) -> None:
        snapshot = get_current_log_level()
        self.assertEqual(
            list(snapshot["valid_levels"]),
            list(VALID_LOG_LEVELS),
            f"valid_levels 必须正好等于 {VALID_LOG_LEVELS}",
        )


# ---------------------------------------------------------------------------
# 2. apply_runtime_log_level helper
# ---------------------------------------------------------------------------


class TestApplyRuntimeLogLevel(unittest.TestCase):
    def setUp(self) -> None:
        self._original_level = _save_and_restore_root_level()

    def tearDown(self) -> None:
        logging.getLogger().setLevel(self._original_level)

    def test_accepts_uppercase_enum(self) -> None:
        result = apply_runtime_log_level("INFO")
        self.assertEqual(result["new_level"], "INFO")
        self.assertEqual(result["logger"], "root")
        self.assertEqual(logging.getLogger().getEffectiveLevel(), logging.INFO)

    def test_case_insensitive(self) -> None:
        apply_runtime_log_level("debug")
        self.assertEqual(logging.getLogger().getEffectiveLevel(), logging.DEBUG)
        apply_runtime_log_level("WaRnInG")
        self.assertEqual(logging.getLogger().getEffectiveLevel(), logging.WARNING)

    def test_invalid_level_raises_value_error(self) -> None:
        before = logging.getLogger().getEffectiveLevel()
        with self.assertRaises(ValueError) as ctx:
            apply_runtime_log_level("LOUD")
        # 错误消息含 valid enum 提示，让 caller 能直接拼回给 client
        self.assertIn("'LOUD'", str(ctx.exception))
        self.assertIn("DEBUG", str(ctx.exception))
        # validation 失败不能让 state 半改半未改
        self.assertEqual(
            logging.getLogger().getEffectiveLevel(),
            before,
            "validation 失败时不应留半改半未改的状态",
        )

    def test_non_string_raises_value_error(self) -> None:
        with self.assertRaises(ValueError):
            apply_runtime_log_level(123)  # type: ignore[arg-type]  # ty: ignore[invalid-argument-type]
        with self.assertRaises(ValueError):
            apply_runtime_log_level(None)  # type: ignore[arg-type]  # ty: ignore[invalid-argument-type]

    def test_returns_old_and_new_level_names(self) -> None:
        apply_runtime_log_level("WARNING")
        result = apply_runtime_log_level("ERROR")
        self.assertEqual(result["old_level"], "WARNING")
        self.assertEqual(result["new_level"], "ERROR")
        self.assertEqual(result["logger"], "root")

    def test_root_logger_level_updates_immediately(self) -> None:
        apply_runtime_log_level("CRITICAL")
        self.assertEqual(logging.getLogger().getEffectiveLevel(), logging.CRITICAL)
        apply_runtime_log_level("DEBUG")
        self.assertEqual(logging.getLogger().getEffectiveLevel(), logging.DEBUG)


# ---------------------------------------------------------------------------
# 3. HTTP endpoint contract — GET + POST
# ---------------------------------------------------------------------------


class _LogLevelRouteBase(unittest.TestCase):
    """复用其他 system 端点测试的 fixture 模式。"""

    _port: int = 19188
    _ui: Any = None
    _client: Any = None
    _saved_level: int = logging.WARNING

    @classmethod
    def setUpClass(cls) -> None:
        from ai_intervention_agent.web_ui import WebFeedbackUI

        cls._ui = WebFeedbackUI(
            prompt="log-level route test", task_id="ll-rt", port=cls._port
        )
        cls._ui.app.config["TESTING"] = True
        cls._ui.limiter.enabled = False
        cls._client = cls._ui.app.test_client()
        cls._saved_level = logging.getLogger().getEffectiveLevel()

    @classmethod
    def tearDownClass(cls) -> None:
        # 测试结束后恢复 root logger level，避免污染其他 test module
        logging.getLogger().setLevel(cls._saved_level)


class TestGetLogLevelEndpoint(_LogLevelRouteBase):
    def test_get_returns_200_for_any_source(self) -> None:
        # GET 不限制来源——payload 不含 PII
        with patch(
            "ai_intervention_agent.web_ui_routes.system._get_client_ip",
            return_value="192.168.1.5",
        ):
            resp = self._client.get("/api/system/log-level")
        self.assertEqual(resp.status_code, 200)

    def test_get_returns_expected_payload_shape(self) -> None:
        resp = self._client.get("/api/system/log-level")
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertTrue(body["success"])
        self.assertIn("root_level", body)
        self.assertIn("aiia_level", body)
        self.assertIn("valid_levels", body)
        self.assertEqual(list(body["valid_levels"]), list(VALID_LOG_LEVELS))

    def test_get_does_not_require_payload(self) -> None:
        # body 留空也应 200（GET 语义）
        resp = self._client.get("/api/system/log-level")
        self.assertEqual(resp.status_code, 200)


class TestPostLogLevelEndpoint(_LogLevelRouteBase):
    def setUp(self) -> None:
        # 每个 test 之前还原 level，避免 cross-test 串扰
        logging.getLogger().setLevel(self._saved_level)

    def test_post_with_valid_level_from_loopback_returns_200(self) -> None:
        resp = self._client.post("/api/system/log-level", json={"level": "ERROR"})
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertTrue(body["success"])
        self.assertEqual(body["new_level"], "ERROR")
        self.assertEqual(body["logger"], "root")
        # 立即生效
        self.assertEqual(logging.getLogger().getEffectiveLevel(), logging.ERROR)

    def test_post_from_non_loopback_returns_403(self) -> None:
        before = logging.getLogger().getEffectiveLevel()
        with patch(
            "ai_intervention_agent.web_ui_routes.system._get_client_ip",
            return_value="192.168.1.5",
        ):
            resp = self._client.post("/api/system/log-level", json={"level": "DEBUG"})
        self.assertEqual(resp.status_code, 403)
        body = resp.get_json()
        self.assertFalse(body["success"])
        self.assertIn("loopback", body["error"].lower())
        # 非 loopback 来源不能修改 state
        self.assertEqual(logging.getLogger().getEffectiveLevel(), before)

    def test_post_missing_level_returns_400(self) -> None:
        resp = self._client.post("/api/system/log-level", json={})
        self.assertEqual(resp.status_code, 400)
        body = resp.get_json()
        self.assertFalse(body["success"])
        self.assertIn("level", body["error"].lower())

    def test_post_non_string_level_returns_400(self) -> None:
        resp = self._client.post("/api/system/log-level", json={"level": 123})
        self.assertEqual(resp.status_code, 400)

    def test_post_invalid_level_enum_returns_400_with_valid_hint(self) -> None:
        resp = self._client.post("/api/system/log-level", json={"level": "VERBOSE"})
        self.assertEqual(resp.status_code, 400)
        body = resp.get_json()
        self.assertFalse(body["success"])
        # 错误消息应该提示 valid enum，让 client 不需要 grep code
        self.assertIn("DEBUG", body["error"])


# ---------------------------------------------------------------------------
# 4. Source-level regression guards
# ---------------------------------------------------------------------------


class TestSourceLevelRegressions(unittest.TestCase):
    """守住 R188 关键设计点不被未来重构弄丢。"""

    def setUp(self) -> None:
        from ai_intervention_agent.web_ui_routes import system as system_module

        self._source = Path(system_module.__file__).read_text(encoding="utf-8")

    def test_post_endpoint_has_loopback_check(self) -> None:
        # POST handler 内必须显式调安全网关 helper（``_is_loopback_request()``
        # 或 R189 之后的 ``_is_authorized()`` 复合 helper），否则任何远程主
        # 机都能修改日志策略。本测试同时接受两种 helper 命名，让 T4 / R189
        # 的「loopback OR API token」升级不需要再回头改本断言。
        import re

        match = re.search(
            r"def system_log_level_post\(\)[\s\S]*?return jsonify",
            self._source,
        )
        self.assertIsNotNone(match)
        assert match is not None
        body = match.group(0)
        # 接受 ``_is_loopback_request()``（R188 起步实现）或 ``_is_authorized()``
        # （R189 复合实现）任一形式
        has_gate = "_is_loopback_request()" in body or "_is_authorized()" in body
        self.assertTrue(
            has_gate,
            "POST /api/system/log-level 必须有安全门控（_is_loopback_request() 或 _is_authorized()）",
        )

    def test_post_endpoint_has_rate_limit_decorator(self) -> None:
        import re

        match = re.search(
            r'@self\.limiter\.limit\("30 per minute"\)\s*\n\s*def system_log_level_post',
            self._source,
        )
        self.assertIsNotNone(
            match,
            "POST /api/system/log-level 必须用 @self.limiter.limit('30 per minute') 装饰",
        )

    def test_get_endpoint_has_rate_limit_decorator(self) -> None:
        import re

        match = re.search(
            r'@self\.limiter\.limit\("60 per minute"\)\s*\n\s*def system_log_level_get',
            self._source,
        )
        self.assertIsNotNone(
            match,
            "GET /api/system/log-level 必须用 @self.limiter.limit('60 per minute') 装饰",
        )

    def test_handler_docstring_mentions_t3_or_r188(self) -> None:
        # 让 future grep 能秒定位本块功能
        self.assertRegex(
            self._source,
            r"def system_log_level_(get|post)\(\)[\s\S]{0,500}(R188|T3)",
            "system_log_level handler docstring 必须显式提到 R188 或 T3 标记",
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
