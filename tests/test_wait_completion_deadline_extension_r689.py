"""R689 — 用户延长倒计时后 backend 等待必须跟随延长（TODO#13 后端部分）。

问题链（修复前）
----------------

``wait_for_task_completion`` 的 backend 超时在任务创建时一次性算好
（``frontend_countdown + BACKEND_BUFFER``）。用户点 +60s（extend endpoint）
或输入触发 typing auto-extend 后，前端倒计时被推后，但 backend 仍按旧
deadline 超时：

1. backend 超时 → ghost-close 把**仍在倒计时**的任务 remove；
2. 用户随后提交 → 404，输入内容永久丢失；
3. MCP 调用方收到 resubmit，而 UI 上任务凭空消失 —— 状态矛盾。

修复
----

backend 超时前先探测任务：仍存活且 ``remaining_time > 0`` → 继续等待
``remaining_time + BACKEND_BUFFER``；探测次数受
``_DEADLINE_EXTENSION_PROBE_MAX`` 防御性上限约束。

本测试锁定：

1. 任务被延长时 backend 不超时、最终取回用户反馈。
2. 任务无剩余倒计时时，超时语义与修复前一致（返回 resubmit）。
3. 探测上限存在且为正数（防僵尸协程）。
"""

from __future__ import annotations

import asyncio
import time
import unittest
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import ai_intervention_agent.server_feedback as server_feedback


def _make_config() -> Any:
    from ai_intervention_agent.service_manager import WebUIConfig

    return WebUIConfig(
        host="127.0.0.1",
        port=8091,
        language="auto",
        timeout=5,
        max_retries=0,
        retry_delay=0.1,
        external_base_url="",
    )


def _response(payload: dict[str, Any], status_code: int = 200) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = payload
    return resp


def _make_client(get_side_effect: Any) -> MagicMock:
    client = MagicMock()
    client.get = AsyncMock(side_effect=get_side_effect)
    client.post = AsyncMock()
    client.stream = MagicMock(side_effect=RuntimeError("SSE blocked in test"))
    client.is_closed = False
    return client


class TestDeadlineExtensionAwareWait(unittest.TestCase):
    """backend 等待必须感知用户对倒计时的延长。"""

    @patch("ai_intervention_agent.service_manager.get_web_ui_config")
    @patch("ai_intervention_agent.service_manager.get_async_client")
    def test_wait_extends_when_task_still_counting_down(
        self, mock_get_client, mock_get_cfg
    ) -> None:
        mock_get_cfg.return_value = (_make_config(), 60)

        start = time.monotonic()

        def _get(url: str, timeout: Any = None) -> MagicMock:
            elapsed = time.monotonic() - start
            if elapsed < 1.5:
                # 任务仍在倒计时（模拟用户 extend / typing auto-extend 后）
                return _response(
                    {
                        "success": True,
                        "task": {"status": "active", "remaining_time": 0.2},
                    }
                )
            return _response(
                {
                    "success": True,
                    "task": {
                        "status": "completed",
                        "result": {"user_input": "extended-and-answered-r689"},
                    },
                }
            )

        mock_get_client.return_value = _make_client(_get)

        with (
            patch("ai_intervention_agent.server_config.BACKEND_MIN", 1),
            patch("ai_intervention_agent.runtime_constants.BACKEND_BUFFER", 0),
            patch.object(server_feedback, "_POLL_INTERVAL_FAST_S", 0.05),
        ):
            result = asyncio.run(
                server_feedback.wait_for_task_completion("t-r689", timeout=1)
            )

        self.assertEqual(
            result.get("user_input"),
            "extended-and-answered-r689",
            "任务倒计时被延长时 backend 必须继续等待并取回用户反馈",
        )

    @patch("ai_intervention_agent.service_manager.get_web_ui_config")
    @patch("ai_intervention_agent.service_manager.get_async_client")
    def test_wait_times_out_when_no_remaining_countdown(
        self, mock_get_client, mock_get_cfg
    ) -> None:
        """无剩余倒计时时按原语义超时并返回 resubmit 文本。"""
        mock_get_cfg.return_value = (_make_config(), 60)

        def _get(url: str, timeout: Any = None) -> MagicMock:
            return _response(
                {
                    "success": True,
                    "task": {"status": "active", "remaining_time": 0},
                }
            )

        mock_get_client.return_value = _make_client(_get)

        with (
            patch("ai_intervention_agent.server_config.BACKEND_MIN", 1),
            patch.object(server_feedback, "_POLL_INTERVAL_FAST_S", 0.05),
            patch.object(server_feedback, "_FETCH_RETRY_BACKOFF_S", (0.0,)),
        ):
            result = asyncio.run(
                server_feedback.wait_for_task_completion("t-r689-timeout", timeout=1)
            )

        self.assertIn("text", result, "超时兜底必须返回 resubmit 文本响应")

    def test_probe_cap_is_positive(self) -> None:
        self.assertGreater(
            server_feedback._DEADLINE_EXTENSION_PROBE_MAX,
            0,
            "探测上限必须为正数（防止 R689 循环退化为僵尸协程）",
        )


if __name__ == "__main__":
    unittest.main()
