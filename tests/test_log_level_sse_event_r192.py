"""R192 / Cycle 5 · POST /api/system/log-level 触发 ``log_level_changed`` SSE 事件。

背景
----
CR#18 §4.3 指出 R188 的运行时日志级别 dial 是「**silent system-wide
mutation**」——POST 成功后，唯一发现方式是：

1. 主动 poll ``GET /api/system/log-level``，或
2. 读 stderr（自己的 logger 级别变了会有一行 ``Level changed to ...``）。

多操作员部署场景（``access_control_enabled = false`` LAN setups）下这
是个**协调失效**：

- Op-A 切到 DEBUG 排查 bug，**忘了切回**；
- Op-B 看到 stderr 爆量，但不知道是「正常排查」还是「真有 bug」。

R192 让 POST handler 在 ``apply_runtime_log_level()`` 成功后通过现有
SSE bus 推送 ``log_level_changed`` 事件，payload 包含旧/新 level + 触发
方 client IP + logger 名。Activity dashboard / PWA 状态栏可订阅展示
横幅：「Log level changed to DEBUG by 127.0.0.1 at 14:35:22」。

设计取舍
========

- **SSE bus 失败 fail-open**：即使 ``_sse_bus.emit`` raise，POST handler
  **仍然**返回 200——日志级别已经改成功，配套通知失败只是降级到「没有
  横幅展示」，没有数据丢失也没有安全暴露。
- **不引入新 SSE event 类型注册**：``_sse_bus.emit("log_level_changed",
  payload)`` 复用现有 free-form event_type 接口（与 ``task_changed``
  / ``config_changed`` 同款），SSE bus 自身不需要改。
- **payload PII 控制**：``changed_by`` 字段是请求 client IP，与现有
  R47 SSE stats 端点暴露的 IP 同 PII 级别；token 字符串 / 请求体绝不
  进 payload。

测试覆盖（10 cases / 3 invariant classes）：

1. **Happy path emit**（4 cases）：POST 成功 → emit 一次；event_type
   正确；payload 字段齐全；新 level 与 result 一致。
2. **Fail-open**（3 cases）：emit raise → 200 仍返回；emit raise →
   apply_runtime_log_level 不回滚；emit 异常被 swallow + debug log。
3. **PII / 安全契约**（3 cases）：payload 不含 token；client IP
   填入 changed_by；level 校验失败时**不**触发 emit。
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


class _LogLevelRouteBase(unittest.TestCase):
    """复用 WebFeedbackUI 测试 client 走 HTTP 路径。"""

    _port: int = 19192
    _ui: Any = None
    _client: Any = None
    _original_root_level: int = logging.WARNING

    @classmethod
    def setUpClass(cls) -> None:
        from ai_intervention_agent.web_ui import WebFeedbackUI

        cls._original_root_level = logging.getLogger().level
        cls._ui = WebFeedbackUI(
            prompt="r192 sse test", task_id="tk-r192", port=cls._port
        )
        cls._ui.app.config["TESTING"] = True
        cls._ui.limiter.enabled = False
        cls._client = cls._ui.app.test_client()

    @classmethod
    def tearDownClass(cls) -> None:
        # 恢复 root logger level，避免污染后续测试
        logging.getLogger().setLevel(cls._original_root_level)

    def setUp(self) -> None:
        # 每个测试前重置 root level，避免上一个测试残留
        logging.getLogger().setLevel(self._original_root_level)

    def _post_log_level(self, level: str, *, client_ip: str = "127.0.0.1") -> Any:
        from ai_intervention_agent.web_ui_routes import system as system_module

        with patch.object(system_module, "_get_client_ip", return_value=client_ip):
            return self._client.post("/api/system/log-level", json={"level": level})


# ---------------------------------------------------------------------------
# 1. Happy path emit
# ---------------------------------------------------------------------------


class TestHappyPathEmit(_LogLevelRouteBase):
    def test_emit_called_once_on_success(self) -> None:
        from ai_intervention_agent.web_ui_routes import task as task_module

        with patch.object(task_module._sse_bus, "emit") as mock_emit:
            resp = self._post_log_level("DEBUG")

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(mock_emit.call_count, 1)

    def test_emit_uses_log_level_changed_event_type(self) -> None:
        from ai_intervention_agent.web_ui_routes import task as task_module

        with patch.object(task_module._sse_bus, "emit") as mock_emit:
            self._post_log_level("INFO")

        event_type, _payload = mock_emit.call_args.args
        self.assertEqual(event_type, "log_level_changed")

    def test_emit_payload_has_all_fields(self) -> None:
        from ai_intervention_agent.web_ui_routes import task as task_module

        with patch.object(task_module._sse_bus, "emit") as mock_emit:
            self._post_log_level("WARNING")

        _, payload = mock_emit.call_args.args
        self.assertIn("old_level", payload)
        self.assertIn("new_level", payload)
        self.assertIn("logger", payload)
        self.assertIn("changed_by", payload)

    def test_emit_new_level_matches_apply_result(self) -> None:
        from ai_intervention_agent.web_ui_routes import task as task_module

        with patch.object(task_module._sse_bus, "emit") as mock_emit:
            resp = self._post_log_level("ERROR")

        result = resp.get_json()
        _, payload = mock_emit.call_args.args
        self.assertEqual(payload["new_level"], result["new_level"])


# ---------------------------------------------------------------------------
# 2. Fail-open behavior
# ---------------------------------------------------------------------------


class TestFailOpenBehavior(_LogLevelRouteBase):
    def test_post_returns_200_when_emit_raises(self) -> None:
        from ai_intervention_agent.web_ui_routes import task as task_module

        with patch.object(
            task_module._sse_bus,
            "emit",
            side_effect=RuntimeError("SSE blown up"),
        ):
            resp = self._post_log_level("DEBUG")

        # 关键：emit 故障不应让 200 退化成 500
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertTrue(body["success"])

    def test_log_level_actually_changed_despite_emit_failure(self) -> None:
        from ai_intervention_agent.web_ui_routes import task as task_module

        before = logging.getLogger().level
        with patch.object(
            task_module._sse_bus,
            "emit",
            side_effect=RuntimeError("SSE blown up"),
        ):
            self._post_log_level("DEBUG")

        # SSE emit 失败 ≠ log level 没改——后者已经在 emit 之前完成
        after = logging.getLogger().level
        self.assertEqual(after, logging.DEBUG)
        self.assertNotEqual(after, before)

    def test_emit_exception_logged_at_debug(self) -> None:
        from ai_intervention_agent.web_ui_routes import system as system_module
        from ai_intervention_agent.web_ui_routes import task as task_module

        with (
            patch.object(
                task_module._sse_bus,
                "emit",
                side_effect=RuntimeError("SSE blown up"),
            ),
            patch.object(system_module.logger, "debug") as mock_debug,
        ):
            self._post_log_level("INFO")

        # debug log 应被调用过至少一次（emit 异常路径）
        # 注意：可能有其他 debug log，找含 "log_level_changed SSE emit failed" 的
        emit_failed_logs = [
            call
            for call in mock_debug.call_args_list
            if "log_level_changed SSE emit failed" in str(call.args[0])
        ]
        self.assertEqual(
            len(emit_failed_logs),
            1,
            f"expected 1 emit-failed debug log, got {len(emit_failed_logs)}",
        )


# ---------------------------------------------------------------------------
# 3. PII / security contract
# ---------------------------------------------------------------------------


class TestPiiSecurityContract(_LogLevelRouteBase):
    def test_changed_by_is_client_ip(self) -> None:
        # 注意：non-loopback IP 默认会被 _is_authorized() 拦下（除非配置
        # 了有效 token）。本测试目的是验证「emit payload 里 changed_by
        # 字段填的是真实 client IP」，因此 mock _is_authorized 强制放
        # 行——避免与 R189 的鉴权策略耦合。
        from ai_intervention_agent.web_ui_routes import system as system_module
        from ai_intervention_agent.web_ui_routes import task as task_module

        with (
            patch.object(system_module, "_get_client_ip", return_value="192.168.1.42"),
            patch.object(system_module, "_is_authorized", return_value=True),
            patch.object(task_module._sse_bus, "emit") as mock_emit,
        ):
            self._client.post("/api/system/log-level", json={"level": "DEBUG"})

        self.assertEqual(mock_emit.call_count, 1)
        _, payload = mock_emit.call_args.args
        self.assertEqual(payload["changed_by"], "192.168.1.42")

    def test_payload_does_not_contain_token_string(self) -> None:
        # 即使请求附带 token 头（理论上 R189 才会接受），SSE payload
        # 也不应回传 token 字符串
        from ai_intervention_agent.web_ui_routes import system as system_module
        from ai_intervention_agent.web_ui_routes import task as task_module

        bad_token = "super-secret-token-do-not-leak-32xx"
        with (
            patch.object(system_module, "_get_client_ip", return_value="127.0.0.1"),
            patch.object(task_module._sse_bus, "emit") as mock_emit,
        ):
            self._client.post(
                "/api/system/log-level",
                json={"level": "DEBUG"},
                headers={"X-API-Token": bad_token},
            )

        if mock_emit.called:
            _, payload = mock_emit.call_args.args
            # 序列化 payload 全部 str，断言不包含 token
            payload_str = repr(payload)
            self.assertNotIn(bad_token, payload_str)

    def test_emit_not_called_on_400_validation_failure(self) -> None:
        from ai_intervention_agent.web_ui_routes import task as task_module

        with patch.object(task_module._sse_bus, "emit") as mock_emit:
            resp = self._post_log_level("INVALID_LEVEL")

        self.assertEqual(resp.status_code, 400)
        # level 校验失败 → log level 没改 → 不应 emit
        self.assertEqual(mock_emit.call_count, 0)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
