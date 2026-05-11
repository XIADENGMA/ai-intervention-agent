"""interactive_feedback MCP 工具错误返回契约测试（BM-1）。

目标：锁定"参数错误用 ToolError，服务/任务错误走 _make_resubmit_response"
的双轨语义，防止后续重构又把参数错误裹进 resubmit 文本导致 agent 死循环。
"""

from __future__ import annotations

import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from fastmcp.exceptions import ToolError

import ai_intervention_agent.server as server
import ai_intervention_agent.server_config as server_config
from ai_intervention_agent.server_config import WebUIConfig

_interactive_feedback_fn = server.interactive_feedback


def _run(message, predefined_options=None):
    """显式传 predefined_options 以避开底层未装饰函数的 FieldInfo 默认值陷阱。"""
    return asyncio.run(_interactive_feedback_fn(message, predefined_options))


def _make_config(
    host: str = "127.0.0.1",
    port: int = 8080,
    timeout: int = 30,
    max_retries: int = 3,
    retry_delay: float = 1.0,
) -> WebUIConfig:
    return WebUIConfig(
        host=host,
        port=port,
        timeout=timeout,
        max_retries=max_retries,
        retry_delay=retry_delay,
    )


def _patch_async_post(*, return_value=None, side_effect=None):
    mock_client = MagicMock()
    if side_effect is not None:
        mock_client.post = AsyncMock(side_effect=side_effect)
    else:
        mock_client.post = AsyncMock(return_value=return_value)
    return patch(
        "ai_intervention_agent.service_manager.get_async_client",
        return_value=mock_client,
    )


class TestInteractiveFeedbackRaisesToolError(unittest.TestCase):
    """参数错误 —— MCP 必须以 ToolError 形式上报，agent 才能感知到"别再拿同参数重试"。"""

    def test_non_string_message_raises_tool_error(self):
        with self.assertRaises(ToolError) as ctx:
            _run(123)  # type: ignore[arg-type]
        self.assertIn("Invalid argument", str(ctx.exception))
        self.assertIn("retry", str(ctx.exception).lower())

    def test_none_message_raises_tool_error(self):
        with self.assertRaises(ToolError):
            _run(None)  # type: ignore[arg-type]

    def test_tool_error_includes_actionable_hint(self):
        """错误消息必须告诉 agent「下一步怎么做」—— 对照 MCP 可操作错误消息最佳实践"""
        with self.assertRaises(ToolError) as ctx:
            _run(object())  # type: ignore[arg-type]
        msg = str(ctx.exception)
        self.assertIn("message", msg)
        self.assertIn("predefined_options", msg)


class TestInteractiveFeedbackResubmitPathPreserved(unittest.TestCase):
    """服务/任务错误继续走 _make_resubmit_response —— 保留"等待用户反馈"的重试语义。

    反向回归保护：如果未来有人把所有 error 都粗暴换成 ToolError，
    这里的断言会立刻红灯，提醒重新评估。
    """

    @patch("ai_intervention_agent.server_feedback.wait_for_task_completion")
    @patch("ai_intervention_agent.service_manager.ensure_web_ui_running")
    @patch("ai_intervention_agent.service_manager.get_web_ui_config")
    @patch(
        "ai_intervention_agent.server_config._generate_task_id",
        return_value="bm1-task-1",
    )
    @patch("ai_intervention_agent.server_feedback.NOTIFICATION_AVAILABLE", False)
    def test_http_error_returns_resubmit_text_not_tool_error(
        self, mock_tid, mock_cfg, mock_ensure, mock_wait
    ):
        import httpx

        mock_cfg.return_value = (_make_config(), 120)
        mock_ensure.return_value = None

        with _patch_async_post(side_effect=httpx.ConnectError("no route")):
            result = _run("hello")

        expected = server_config._make_resubmit_response()
        self.assertEqual(result, expected)
        mock_wait.assert_not_called()

    @patch("ai_intervention_agent.server_feedback.wait_for_task_completion")
    @patch("ai_intervention_agent.service_manager.ensure_web_ui_running")
    @patch("ai_intervention_agent.service_manager.get_web_ui_config")
    @patch(
        "ai_intervention_agent.server_config._generate_task_id",
        return_value="bm1-task-2",
    )
    @patch("ai_intervention_agent.server_feedback.NOTIFICATION_AVAILABLE", False)
    def test_task_error_returns_resubmit_text_not_tool_error(
        self, mock_tid, mock_cfg, mock_ensure, mock_wait
    ):
        mock_cfg.return_value = (_make_config(), 120)
        mock_ensure.return_value = None
        mock_wait.return_value = {"error": "task failed"}

        mock_resp = MagicMock()
        mock_resp.status_code = 200

        with _patch_async_post(return_value=mock_resp):
            result = _run("hello")

        expected = server_config._make_resubmit_response()
        self.assertEqual(result, expected)

    @patch("ai_intervention_agent.server_feedback.wait_for_task_completion")
    @patch("ai_intervention_agent.service_manager.ensure_web_ui_running")
    @patch("ai_intervention_agent.service_manager.get_web_ui_config")
    @patch(
        "ai_intervention_agent.server_config._generate_task_id",
        return_value="bm1-task-3",
    )
    @patch("ai_intervention_agent.server_feedback.NOTIFICATION_AVAILABLE", False)
    def test_unexpected_internal_error_returns_resubmit_text(
        self, mock_tid, mock_cfg, mock_ensure, mock_wait
    ):
        """内部非预期异常也走 resubmit，而不是暴露给 agent

        这里保留现有设计：interactive_feedback 是"等用户反馈"的工具，一次失败
        不意味着永久失败，让 agent 重新调用比 raise ToolError 更符合产品意图。
        """
        mock_cfg.return_value = (_make_config(), 120)
        mock_ensure.side_effect = RuntimeError("simulated ensure crash")

        result = _run("hello")

        expected = server_config._make_resubmit_response()
        self.assertEqual(result, expected)
        mock_wait.assert_not_called()


class TestInteractiveFeedbackCompatAliases(unittest.TestCase):
    """跨工具兼容：当其它 feedback MCP 的参数（summary / project_directory 等）
    误传过来时，本工具应当正常解析而不是首次调用就失败（TODO #1）。"""

    @patch("ai_intervention_agent.server_feedback.wait_for_task_completion")
    @patch("ai_intervention_agent.service_manager.ensure_web_ui_running")
    @patch("ai_intervention_agent.service_manager.get_web_ui_config")
    @patch(
        "ai_intervention_agent.server_config._generate_task_id",
        return_value="compat-task-1",
    )
    @patch("ai_intervention_agent.server_feedback.NOTIFICATION_AVAILABLE", False)
    def test_summary_alias_is_accepted_when_message_missing(
        self, mock_tid, mock_cfg, mock_ensure, mock_wait
    ):
        mock_cfg.return_value = (_make_config(), 120)
        mock_ensure.return_value = None
        mock_wait.return_value = {
            "user_input": "ok",
            "selected_options": [],
            "images": [],
        }

        mock_resp = MagicMock()
        mock_resp.status_code = 200

        with _patch_async_post(return_value=mock_resp):
            result = asyncio.run(
                _interactive_feedback_fn(
                    None,
                    None,
                    summary="please review",
                    project_directory="/tmp/proj",
                    submit_button_text="提交选择",
                )
            )

        self.assertIsInstance(result, list)
        mock_wait.assert_called_once()

    def test_unknown_compat_args_do_not_raise(self):
        """常见漂移字段不应触发 ToolError（与 TODO #1 报错对照）。"""
        with (
            patch(
                "ai_intervention_agent.server_feedback.wait_for_task_completion"
            ) as mock_wait,
            patch(
                "ai_intervention_agent.service_manager.ensure_web_ui_running",
                return_value=None,
            ),
            patch(
                "ai_intervention_agent.service_manager.get_web_ui_config",
                return_value=(_make_config(), 120),
            ),
            patch(
                "ai_intervention_agent.server_config._generate_task_id",
                return_value="compat-task-2",
            ),
            patch(
                "ai_intervention_agent.server_feedback.NOTIFICATION_AVAILABLE", False
            ),
        ):
            mock_wait.return_value = {
                "user_input": "ok",
                "selected_options": [],
                "images": [],
            }
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            with _patch_async_post(return_value=mock_resp):
                result = asyncio.run(
                    _interactive_feedback_fn(
                        "hi",
                        None,
                        project_directory="/tmp/proj",
                        submit_button_text="提交选择",
                        timeout=999,
                        feedback_type="question",
                        priority="high",
                        language="zh",
                        tags=["a", "b"],
                        user_id="u1",
                    )
                )
            self.assertIsInstance(result, list)

    def test_v1_5_36_drift_args_do_not_raise(self):
        """R77：v1.5.36 测试反馈里实际报错的 drift 字段必须被吸收。

        错误样本（TODO.md 引用）：
          - ``predefined_options_defaults=[...]`` —— R63b 一度作为正式参数；
            R167 已移除，请改用 ``list[dict]`` 形态（本用例已迁移）。
          - ``timeout_seconds=600`` —— R77 加 alias（与 ``timeout`` 同义）
          - ``task_id='src-layout-resources-decision-r76'`` —— R77 加并显式忽略

        本用例同时传两个仍合法的 drift 字段以及 R167 后表达"推荐项预选"
        的正确形态（``list[dict]``），验证不再触发 Pydantic
        ``unexpected_keyword_argument``，调用能跑通到 ``wait_for_task_completion``。
        """
        with (
            patch(
                "ai_intervention_agent.server_feedback.wait_for_task_completion"
            ) as mock_wait,
            patch(
                "ai_intervention_agent.service_manager.ensure_web_ui_running",
                return_value=None,
            ),
            patch(
                "ai_intervention_agent.service_manager.get_web_ui_config",
                return_value=(_make_config(), 120),
            ),
            patch(
                "ai_intervention_agent.server_config._generate_task_id",
                return_value="compat-task-r77",
            ),
            patch(
                "ai_intervention_agent.server_feedback.NOTIFICATION_AVAILABLE", False
            ),
        ):
            mock_wait.return_value = {
                "user_input": "ok",
                "selected_options": [],
                "images": [],
            }
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            with _patch_async_post(return_value=mock_resp):
                # R167：用 list[dict] 形态表达"第二项推荐预选"的语义，
                # 等价于旧 predefined_options_defaults=[False, True] 写法。
                result = asyncio.run(
                    _interactive_feedback_fn(
                        "Continue?",
                        [
                            {"label": "[范围] 只修最小必要", "default": False},
                            {"label": "[范围] 询问 — 推荐", "default": True},
                        ],
                        timeout_seconds=600,
                        task_id="src-layout-resources-decision-r76",
                    )
                )
            self.assertIsInstance(result, list)
            mock_wait.assert_called_once()

    def test_predefined_options_defaults_now_raises_r167(self):
        """R167：原 ``predefined_options_defaults`` 顶层参数已移除——再传会触发 TypeError。

        这是 R167 "形态收敛到 list[dict]" 的回归锁：在 Python 函数级别，
        旧调用方传 ``predefined_options_defaults=[...]`` 会被 Pydantic /
        函数签名拒掉（``unexpected_keyword_argument`` → TypeError）。
        在 FastMCP schema 级别，``additionalProperties: false`` 也会让 LLM
        客户端收到清晰的 schema ToolError。两者都引导 LLM 用 dict 形态。
        """
        with self.assertRaises(TypeError) as ctx:
            asyncio.run(
                _interactive_feedback_fn(
                    "Continue?",
                    ["A", "B"],
                    predefined_options_defaults=[False, True],  # ty: ignore[unknown-argument]
                )
            )
        self.assertIn("predefined_options_defaults", str(ctx.exception))

    def test_timeout_seconds_alias_does_not_override_server_config(self):
        """``timeout_seconds`` 是兼容别名 — 不应改变实际后端等待时间（由 server_config 计算）。"""
        with (
            patch(
                "ai_intervention_agent.server_feedback.wait_for_task_completion"
            ) as mock_wait,
            patch(
                "ai_intervention_agent.service_manager.ensure_web_ui_running",
                return_value=None,
            ),
            patch(
                "ai_intervention_agent.service_manager.get_web_ui_config",
                return_value=(_make_config(), 120),
            ),
            patch(
                "ai_intervention_agent.server_config._generate_task_id",
                return_value="compat-task-timeout-seconds",
            ),
            patch(
                "ai_intervention_agent.server_feedback.NOTIFICATION_AVAILABLE", False
            ),
        ):
            mock_wait.return_value = {
                "user_input": "ok",
                "selected_options": [],
                "images": [],
            }
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            with _patch_async_post(return_value=mock_resp):
                asyncio.run(
                    _interactive_feedback_fn(
                        "hi",
                        None,
                        timeout_seconds=999_999,
                    )
                )
            mock_wait.assert_called_once()
            actual_timeout = (
                mock_wait.call_args.kwargs.get("timeout") or mock_wait.call_args.args[1]
            )
            self.assertNotEqual(
                actual_timeout,
                999_999,
                "timeout_seconds 不能直接代替 server_config 计算出的后端 timeout",
            )

    def test_external_task_id_is_ignored_in_favour_of_generated_id(self):
        """外部传入的 ``task_id`` 不应替换 server 自动生成的 task_id（防止 trace ID 串扰）。"""
        with (
            patch(
                "ai_intervention_agent.server_feedback.wait_for_task_completion"
            ) as mock_wait,
            patch(
                "ai_intervention_agent.service_manager.ensure_web_ui_running",
                return_value=None,
            ),
            patch(
                "ai_intervention_agent.service_manager.get_web_ui_config",
                return_value=(_make_config(), 120),
            ),
            patch(
                "ai_intervention_agent.server_config._generate_task_id",
                return_value="server-side-id",
            ),
            patch(
                "ai_intervention_agent.server_feedback.NOTIFICATION_AVAILABLE", False
            ),
        ):
            mock_wait.return_value = {
                "user_input": "ok",
                "selected_options": [],
                "images": [],
            }
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            external_id = "client-supplied-id-do-not-honour"
            with _patch_async_post(return_value=mock_resp):
                asyncio.run(
                    _interactive_feedback_fn(
                        "hi",
                        None,
                        task_id=external_id,
                    )
                )
            args, kwargs = mock_wait.call_args
            actual_task_id = kwargs.get("task_id") or (args[0] if args else None)
            self.assertEqual(
                actual_task_id,
                "server-side-id",
                "外部 task_id 必须被忽略；server 用自己生成的 ID",
            )
            self.assertNotEqual(actual_task_id, external_id)


if __name__ == "__main__":
    unittest.main()
