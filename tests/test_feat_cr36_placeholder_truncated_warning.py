"""cr36 §8 #2 [low] — placeholder truncation warning regression.

【背景】cycle-3 §2.1 borrow #3 在 server-side 把超长 placeholder
silent clamp 到 200 chars。cr36 §8 #2 指出这会让 agent 不知道自己
的提示被截断了（可能有重要的第二句话丢失）。

本测试确保：
1. 短 placeholder → 响应不含 truncated 字段（避免响应膨胀）。
2. 200-char 整 placeholder → 不算 truncate（不含字段）。
3. > 200 char placeholder → 响应含 placeholder_truncated=True +
   placeholder_original_length + placeholder_max_length。
"""

from __future__ import annotations

import json
import unittest
from typing import Any
from unittest.mock import MagicMock, patch


class _RouteFixtureBase(unittest.TestCase):
    _port: int = 19099
    _ui: Any = None
    _client: Any = None

    @classmethod
    def setUpClass(cls) -> None:
        from ai_intervention_agent.web_ui import WebFeedbackUI

        cls._ui = WebFeedbackUI(
            prompt="placeholder test", task_id="ph-base", port=cls._port
        )
        cls._ui.app.config["TESTING"] = True
        cls._ui.limiter.enabled = False
        cls._client = cls._ui.app.test_client()

    @staticmethod
    def _mock_queue(success: bool = True) -> MagicMock:
        q = MagicMock()
        q.add_task.return_value = success
        return q


class TestNoTruncation(_RouteFixtureBase):
    @patch("ai_intervention_agent.web_ui_routes.task.get_task_queue")
    def test_short_placeholder_no_truncation_field(self, mock_q) -> None:
        mock_q.return_value = self._mock_queue()
        body = {
            "task_id": "t-short",
            "prompt": "hi",
            "feedback_placeholder": "short hint",
        }
        resp = self._client.post(
            "/api/tasks", data=json.dumps(body), content_type="application/json"
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data["success"])
        self.assertNotIn(
            "placeholder_truncated",
            data,
            "短 placeholder 不应有 truncated 字段，避免响应膨胀",
        )

    @patch("ai_intervention_agent.web_ui_routes.task.get_task_queue")
    def test_exactly_200_char_no_truncation(self, mock_q) -> None:
        """200-char (= clamp boundary) 严格不算 truncate。"""
        mock_q.return_value = self._mock_queue()
        body = {
            "task_id": "t-boundary",
            "prompt": "hi",
            "feedback_placeholder": "x" * 200,
        }
        resp = self._client.post(
            "/api/tasks", data=json.dumps(body), content_type="application/json"
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertNotIn("placeholder_truncated", data)

    @patch("ai_intervention_agent.web_ui_routes.task.get_task_queue")
    def test_missing_placeholder_no_truncation(self, mock_q) -> None:
        mock_q.return_value = self._mock_queue()
        body = {"task_id": "t-none", "prompt": "hi"}
        resp = self._client.post(
            "/api/tasks", data=json.dumps(body), content_type="application/json"
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertNotIn("placeholder_truncated", data)


class TestTruncationWarning(_RouteFixtureBase):
    @patch("ai_intervention_agent.web_ui_routes.task.get_task_queue")
    def test_300_char_returns_warning(self, mock_q) -> None:
        mock_q.return_value = self._mock_queue()
        body = {
            "task_id": "t-long",
            "prompt": "hi",
            "feedback_placeholder": "y" * 300,
        }
        resp = self._client.post(
            "/api/tasks", data=json.dumps(body), content_type="application/json"
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data["success"])
        self.assertTrue(data.get("placeholder_truncated"))
        self.assertEqual(data.get("placeholder_original_length"), 300)
        self.assertEqual(data.get("placeholder_max_length"), 200)

    @patch("ai_intervention_agent.web_ui_routes.task.get_task_queue")
    def test_201_char_minimum_overflow_triggers_warning(self, mock_q) -> None:
        """201-char (= clamp + 1) 必须触发警告 — 这是 boundary 测试。"""
        mock_q.return_value = self._mock_queue()
        body = {
            "task_id": "t-201",
            "prompt": "hi",
            "feedback_placeholder": "z" * 201,
        }
        resp = self._client.post(
            "/api/tasks", data=json.dumps(body), content_type="application/json"
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data.get("placeholder_truncated"))

    @patch("ai_intervention_agent.web_ui_routes.task.get_task_queue")
    def test_whitespace_padded_long_placeholder_strip_before_check(
        self, mock_q
    ) -> None:
        """如 placeholder 实际正文短，但前后 padding 大量空格，``.strip()``
        后短于 200 → 不应误报 truncation。
        """
        mock_q.return_value = self._mock_queue()
        body = {
            "task_id": "t-pad",
            "prompt": "hi",
            "feedback_placeholder": "   short   " + "\n" * 500,
        }
        resp = self._client.post(
            "/api/tasks", data=json.dumps(body), content_type="application/json"
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        # ".strip()" 后剩 "short"，不 truncate
        self.assertNotIn("placeholder_truncated", data)


if __name__ == "__main__":
    unittest.main()
