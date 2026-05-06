r"""端到端诊断日志链回归 (R40 P0-S3)

R40 引入 ``EnhancedLogger.event(name, **ctx)`` API，并在 ``server.py`` 的
启动入口、``server_feedback._interactive_feedback_impl`` 的关键节点打
event-style 单行日志。这套日志专为 ``grep '^.*event=task\.created'`` 等
"按 event 名拉时间线"的运维场景设计。

借鉴 ``cursor-count`` v0.4.5 的诊断日志链做法：用户贴一段 stderr，运维
能一眼看出"卡在哪一环"。

测试组织：

1. ``EnhancedLogger.event()`` 行为：
   - 输出格式 ``event=<name> k1=v1 k2=v2 ...``；
   - bare vs repr 的边界（int / float / bool / None / 简单字符串 /
     含空格字符串 / 含转义字符）；
   - 空 ctx 时只输出 ``event=<name>``；
   - 走的是 ``self.info()``，因此被 root logger 级别约束 + 受去重保护
     （连续相同 event 1 秒内只打一次）。

2. server.py 启动 banner：
   - ``server.boot`` event 在 ``main()`` 里被打印；
   - 包含 version / mcp_name / transport / python / middleware 字段。

3. server_feedback.py 关键节点：
   - ``task.created`` 在 task_id 生成后立刻打；
   - ``task.notified`` 在 HTTP /api/tasks 200 后立刻打；
   - ``task.failed`` 在三条错误路径上各自打（http_status / httpx_error /
     wait_error）；
   - ``task.completed`` 在反馈完成后打，含 ``duration_ms``。
"""

from __future__ import annotations

import logging
import unittest
from typing import Any
from unittest.mock import MagicMock, patch

import server
import server_feedback
from enhanced_logging import EnhancedLogger


class TestEnhancedLoggerFormatEventValue(unittest.TestCase):
    """``_format_event_value`` 静态方法的边界行为。

    用静态方法而不是 instance method 测：避免 SingletonLogManager 副作用，
    100% 纯函数行为。
    """

    def test_none_returns_bare_none(self) -> None:
        self.assertEqual(EnhancedLogger._format_event_value(None), "None")

    def test_bool_returns_bare(self) -> None:
        self.assertEqual(EnhancedLogger._format_event_value(True), "True")
        self.assertEqual(EnhancedLogger._format_event_value(False), "False")

    def test_int_returns_bare(self) -> None:
        self.assertEqual(EnhancedLogger._format_event_value(42), "42")
        self.assertEqual(EnhancedLogger._format_event_value(-7), "-7")

    def test_float_returns_bare(self) -> None:
        self.assertEqual(EnhancedLogger._format_event_value(3.14), "3.14")

    def test_simple_string_returns_bare(self) -> None:
        """无空格 / 无引号 / 无 = / 无反斜杠的纯字符串保持原样（grep 友好）。"""
        self.assertEqual(
            EnhancedLogger._format_event_value("task_abcd1234"), "task_abcd1234"
        )
        self.assertEqual(
            EnhancedLogger._format_event_value("hello-world"), "hello-world"
        )

    def test_string_with_whitespace_uses_repr(self) -> None:
        """含空格的字符串走 repr，避免 grep 时被空格切错列。"""
        rendered = EnhancedLogger._format_event_value("hello world")
        self.assertEqual(rendered, "'hello world'")

    def test_string_with_equals_uses_repr(self) -> None:
        """含 ``=`` 的字符串走 repr，避免破坏 ``key=value`` 结构。"""
        rendered = EnhancedLogger._format_event_value("a=b")
        self.assertEqual(rendered, "'a=b'")

    def test_string_with_quote_uses_repr(self) -> None:
        rendered = EnhancedLogger._format_event_value("it's")
        self.assertIn("it", rendered)
        # repr 行为：含 ' 时 Python 会切到 "..."
        self.assertTrue(rendered.startswith(('"', "'")))

    def test_empty_string_uses_repr(self) -> None:
        """空字符串走 repr 形式 ``''``，避免渲染成 ``key=`` 引发歧义。"""
        rendered = EnhancedLogger._format_event_value("")
        self.assertEqual(rendered, "''")

    def test_complex_object_uses_repr(self) -> None:
        rendered = EnhancedLogger._format_event_value({"a": 1})
        self.assertIn("'a'", rendered)
        self.assertIn("1", rendered)


class TestEnhancedLoggerEventMethod(unittest.TestCase):
    """``EnhancedLogger.event()`` 行为。"""

    def setUp(self) -> None:
        self.logger = EnhancedLogger("test.diagnostic_events_r40")

    def test_event_no_ctx_emits_event_name_only(self) -> None:
        with patch.object(self.logger, "info") as mock_info:
            self.logger.event("task.created")
        mock_info.assert_called_once_with("event=task.created")

    def test_event_with_ctx_emits_key_value_pairs(self) -> None:
        with patch.object(self.logger, "info") as mock_info:
            self.logger.event("task.created", task_id="t_abc", message_len=120)
        mock_info.assert_called_once()
        emitted = mock_info.call_args[0][0]
        self.assertEqual(
            emitted,
            "event=task.created task_id=t_abc message_len=120",
        )

    def test_event_with_string_containing_space_uses_repr(self) -> None:
        with patch.object(self.logger, "info") as mock_info:
            self.logger.event("task.failed", reason="connection refused")
        emitted = mock_info.call_args[0][0]
        self.assertEqual(emitted, "event=task.failed reason='connection refused'")

    def test_event_routes_through_info_and_dedup_pipeline(self) -> None:
        """``event`` 真的走的是 ``info`` 路径——可以被去重 / 脱敏 /
        level mapping 影响（与项目其它 logger 一致）。"""
        # SingletonLogManager 默认把新 logger 级别设为 WARNING；此处显式提到
        # INFO，让 ``self.logger.isEnabledFor(INFO)`` 为真，dedup 路径才被
        # 命中（否则 EnhancedLogger.log() 在 isEnabledFor 这一关就短路返回，
        # 测试无法观察到 deduplicator）。
        self.logger.setLevel(logging.INFO)

        with patch.object(self.logger.deduplicator, "should_log") as mock_should:
            mock_should.return_value = (True, None)
            self.logger.event("test.evt", a=1)
        mock_should.assert_called()


class TestServerBootBanner(unittest.TestCase):
    """``server.main()`` 启动 banner 必须包含 ``event=server.boot`` + 关键字段。

    不真的让 ``mcp.run()`` 起来——把它 patch 成 raise KeyboardInterrupt
    让 main() 立刻退出，只验证 banner 已经被打了。
    """

    def test_main_emits_server_boot_event_with_required_fields(self) -> None:
        with (
            patch.object(server.mcp, "run", side_effect=KeyboardInterrupt),
            patch.object(server, "logger") as mock_logger,
            patch.object(server, "cleanup_services"),
        ):
            server.main()

        warning_calls = [call.args[0] for call in mock_logger.warning.call_args_list]
        boot_lines = [msg for msg in warning_calls if "event=server.boot" in msg]
        self.assertEqual(
            len(boot_lines),
            1,
            f"main() 必须打印恰好 1 条 server.boot banner；实际 warning 调用：{warning_calls}",
        )

        line = boot_lines[0]
        for field in (
            "version=",
            "transport=stdio",
            "python=",
            "middleware=",
            "mcp_name=",
        ):
            self.assertIn(field, line, f"server.boot banner 缺字段 {field!r}：{line}")


class TestInteractiveFeedbackEventLog(unittest.TestCase):
    """``server_feedback._interactive_feedback_impl`` 关键节点的 event 日志。

    用 patch.object(server_feedback, 'logger', ...) 监视所有 event 调用，
    通过 mock 切断真正的 web_ui HTTP 路径（ensure_web_ui_running / client.post /
    wait_for_task_completion 各自用 AsyncMock 返回成功值），让函数能跑完
    happy path 并打齐 task.created → task.notified → task.completed。
    """

    def _make_async_mock(self, return_value: Any) -> Any:
        """生成一个 awaitable 的 mock：``await m(...)`` 返回 return_value。"""

        async def _impl(*args: Any, **kwargs: Any) -> Any:
            return return_value

        return _impl

    def test_happy_path_emits_created_notified_completed(self) -> None:
        import asyncio

        from server_config import WebUIConfig

        cfg = WebUIConfig(host="127.0.0.1", port=12345)
        # client.post 返回 200 模拟 web_ui /api/tasks 接受任务
        post_response = MagicMock()
        post_response.status_code = 200
        post_response.json.return_value = {"ok": True}

        client = MagicMock()
        client.post = self._make_async_mock(post_response)

        events: list[tuple[str, dict]] = []

        def _fake_event(name: str, **ctx: Any) -> None:
            events.append((name, dict(ctx)))

        with (
            patch.object(server_feedback.logger, "event", side_effect=_fake_event),
            patch.object(server_feedback.logger, "info"),
            patch.object(server_feedback.logger, "warning"),
            patch.object(server_feedback.logger, "error"),
            patch.object(
                server_feedback.service_manager,
                "get_web_ui_config",
                return_value=(cfg, 30),
            ),
            patch.object(
                server_feedback.service_manager,
                "get_async_client",
                return_value=client,
            ),
            patch.object(
                server_feedback.service_manager,
                "ensure_web_ui_running",
                self._make_async_mock(None),
            ),
            patch.object(
                server_feedback,
                "wait_for_task_completion",
                self._make_async_mock({"interactive_feedback": "ok"}),
            ),
            # 通知系统在测试中不真发，但参数合法路径不应抛
            patch.object(
                server_feedback,
                "NOTIFICATION_AVAILABLE",
                False,
            ),
        ):
            asyncio.run(
                server_feedback.interactive_feedback(
                    message="hello world test prompt", predefined_options=["A", "B"]
                )
            )

        names = [name for name, _ in events]
        self.assertIn("task.created", names)
        self.assertIn("task.notified", names)
        self.assertIn("task.completed", names)
        # 顺序契约：created 必须先于 notified 先于 completed
        self.assertLess(names.index("task.created"), names.index("task.notified"))
        self.assertLess(names.index("task.notified"), names.index("task.completed"))

        created_ctx = next(c for n, c in events if n == "task.created")
        self.assertIn("task_id", created_ctx)
        self.assertEqual(created_ctx["message_len"], len("hello world test prompt"))
        self.assertEqual(created_ctx["options_count"], 2)

        notified_ctx = next(c for n, c in events if n == "task.notified")
        self.assertEqual(notified_ctx["host"], "127.0.0.1")
        self.assertEqual(notified_ctx["port"], 12345)

        completed_ctx = next(c for n, c in events if n == "task.completed")
        self.assertIn("duration_ms", completed_ctx)
        self.assertIsInstance(completed_ctx["duration_ms"], int)
        self.assertGreaterEqual(completed_ctx["duration_ms"], 0)

    def test_http_error_emits_task_failed_with_stage_notify(self) -> None:
        import asyncio

        from server_config import WebUIConfig

        cfg = WebUIConfig(host="127.0.0.1", port=12345)
        post_response = MagicMock()
        post_response.status_code = 503
        post_response.json.return_value = {"error": "service down"}
        post_response.text = '{"error":"service down"}'

        client = MagicMock()
        client.post = self._make_async_mock(post_response)

        events: list[tuple[str, dict]] = []

        def _fake_event(name: str, **ctx: Any) -> None:
            events.append((name, dict(ctx)))

        with (
            patch.object(server_feedback.logger, "event", side_effect=_fake_event),
            patch.object(server_feedback.logger, "info"),
            patch.object(server_feedback.logger, "warning"),
            patch.object(server_feedback.logger, "error"),
            patch.object(
                server_feedback.service_manager,
                "get_web_ui_config",
                return_value=(cfg, 30),
            ),
            patch.object(
                server_feedback.service_manager,
                "get_async_client",
                return_value=client,
            ),
            patch.object(
                server_feedback.service_manager,
                "ensure_web_ui_running",
                self._make_async_mock(None),
            ),
            patch.object(
                server_feedback,
                "NOTIFICATION_AVAILABLE",
                False,
            ),
        ):
            asyncio.run(
                server_feedback.interactive_feedback(
                    message="quick test", predefined_options=None
                )
            )

        failed_events = [c for n, c in events if n == "task.failed"]
        self.assertEqual(len(failed_events), 1)
        self.assertEqual(failed_events[0]["stage"], "notify")
        self.assertEqual(failed_events[0]["reason"], "http_503")


if __name__ == "__main__":
    unittest.main()
