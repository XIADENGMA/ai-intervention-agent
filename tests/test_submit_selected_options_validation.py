#!/usr/bin/env python3
"""P6Y-3 回归：/api/submit 必须对 selected_options 做类型校验。

背景：
    历史实现里 selected_options 直接从请求体中读取，然后透传到
    Task.result['selected_options']。当调用方传入：
      - selected_options: null / "opt" / 42 / {"a": 1}
      - 列表中含 None / dict / 空串 / 过长串
    都会进入 Task.result 并由前端渲染，触发：
      - `.forEach is not a function` 等前端崩溃
      - 历史任务面板异常
      - 通知标题/正文出现奇怪 repr。

修复后 _sanitize_selected_options 会：
  1. 非 list 直接返回 []
  2. list 内元素转 str / strip / 去空 / 去过长 / 去重 / 截断 50 项
"""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from web_ui_routes.feedback import _sanitize_selected_options


class TestSanitizeSelectedOptions(unittest.TestCase):
    """直接单元测试 helper 函数，覆盖各种异常输入。"""

    def test_none_returns_empty(self) -> None:
        self.assertEqual(_sanitize_selected_options(None), [])

    def test_string_returns_empty(self) -> None:
        self.assertEqual(_sanitize_selected_options("opt1,opt2"), [])

    def test_dict_returns_empty(self) -> None:
        self.assertEqual(_sanitize_selected_options({"a": "b"}), [])

    def test_integer_returns_empty(self) -> None:
        self.assertEqual(_sanitize_selected_options(42), [])

    def test_normal_list_kept(self) -> None:
        self.assertEqual(
            _sanitize_selected_options(["alpha", "beta"]),
            ["alpha", "beta"],
        )

    def test_non_string_items_coerced(self) -> None:
        out = _sanitize_selected_options([1, 2, True])
        self.assertEqual(out, ["1", "2", "True"])

    def test_none_items_skipped(self) -> None:
        self.assertEqual(
            _sanitize_selected_options(["a", None, "b", None]),
            ["a", "b"],
        )

    def test_empty_and_whitespace_items_skipped(self) -> None:
        self.assertEqual(
            _sanitize_selected_options(["a", "", "  ", "\t\n", "b"]),
            ["a", "b"],
        )

    def test_items_are_stripped(self) -> None:
        self.assertEqual(
            _sanitize_selected_options(["  a  ", "\tb\n"]),
            ["a", "b"],
        )

    def test_duplicate_items_removed(self) -> None:
        self.assertEqual(
            _sanitize_selected_options(["a", "b", "a", "b", "c"]),
            ["a", "b", "c"],
        )

    def test_overlong_items_dropped(self) -> None:
        too_long = "x" * 501
        self.assertEqual(
            _sanitize_selected_options(["ok", too_long, "also-ok"]),
            ["ok", "also-ok"],
        )

    def test_max_50_items(self) -> None:
        huge = [f"opt-{i}" for i in range(200)]
        out = _sanitize_selected_options(huge)
        self.assertEqual(len(out), 50)
        self.assertEqual(out[0], "opt-0")
        self.assertEqual(out[-1], "opt-49")

    def test_empty_list_returns_empty(self) -> None:
        self.assertEqual(_sanitize_selected_options([]), [])


class _RouteTestBase(unittest.TestCase):
    """启动真实 Flask test_client，针对 /api/submit 做端到端回归。"""

    _port = 19520
    _ui = None
    _client = None

    @classmethod
    def setUpClass(cls) -> None:
        from web_ui import WebFeedbackUI

        cls._ui = WebFeedbackUI(
            prompt="p6y3 regression",
            task_id="rt-base",
            port=cls._port,
        )
        cls._ui.app.config["TESTING"] = True
        cls._ui.limiter.enabled = False
        cls._client = cls._ui.app.test_client()


class TestSubmitRejectsNonListSelectedOptions(_RouteTestBase):
    @patch("web_ui_routes.feedback.get_task_queue")
    def test_json_selected_options_is_string_is_sanitized_to_empty(
        self, mock_get_tq
    ) -> None:
        mock_tq = MagicMock()
        mock_tq.get_active_task.return_value = MagicMock(task_id="active-1")
        mock_get_tq.return_value = mock_tq

        resp = self._client.post(
            "/api/submit",
            json={"feedback_text": "hi", "selected_options": "not-a-list"},
        )

        self.assertEqual(resp.status_code, 200)
        mock_tq.complete_task.assert_called_once()
        _, result = mock_tq.complete_task.call_args.args
        self.assertEqual(result["selected_options"], [])

    @patch("web_ui_routes.feedback.get_task_queue")
    def test_json_selected_options_is_dict_is_sanitized_to_empty(
        self, mock_get_tq
    ) -> None:
        mock_tq = MagicMock()
        mock_tq.get_active_task.return_value = MagicMock(task_id="active-2")
        mock_get_tq.return_value = mock_tq

        resp = self._client.post(
            "/api/submit",
            json={"feedback_text": "hi", "selected_options": {"foo": "bar"}},
        )
        self.assertEqual(resp.status_code, 200)
        _, result = mock_tq.complete_task.call_args.args
        self.assertEqual(result["selected_options"], [])

    @patch("web_ui_routes.feedback.get_task_queue")
    def test_json_list_with_none_and_empty_is_cleaned(self, mock_get_tq) -> None:
        mock_tq = MagicMock()
        mock_tq.get_active_task.return_value = MagicMock(task_id="active-3")
        mock_get_tq.return_value = mock_tq

        resp = self._client.post(
            "/api/submit",
            json={
                "feedback_text": "hi",
                "selected_options": [None, "  alpha  ", "", "\t", "beta", None],
            },
        )
        self.assertEqual(resp.status_code, 200)
        _, result = mock_tq.complete_task.call_args.args
        self.assertEqual(result["selected_options"], ["alpha", "beta"])

    @patch("web_ui_routes.feedback.get_task_queue")
    def test_form_selected_options_non_json_falls_back_to_empty(
        self, mock_get_tq
    ) -> None:
        mock_tq = MagicMock()
        mock_tq.get_active_task.return_value = MagicMock(task_id="active-4")
        mock_get_tq.return_value = mock_tq

        resp = self._client.post(
            "/api/submit",
            data={
                "feedback_text": "hi",
                "selected_options": "this-is-not-json",
            },
            content_type="application/x-www-form-urlencoded",
        )
        self.assertEqual(resp.status_code, 200)
        _, result = mock_tq.complete_task.call_args.args
        self.assertEqual(result["selected_options"], [])

    @patch("web_ui_routes.feedback.get_task_queue")
    def test_form_selected_options_valid_json_dict_sanitized(self, mock_get_tq) -> None:
        """表单字段传来的是合法 JSON，但反序列化结果不是 list（例如 {}）。"""
        mock_tq = MagicMock()
        mock_tq.get_active_task.return_value = MagicMock(task_id="active-5")
        mock_get_tq.return_value = mock_tq

        resp = self._client.post(
            "/api/submit",
            data={
                "feedback_text": "hi",
                "selected_options": '{"not":"a list"}',
            },
            content_type="application/x-www-form-urlencoded",
        )
        self.assertEqual(resp.status_code, 200)
        _, result = mock_tq.complete_task.call_args.args
        self.assertEqual(result["selected_options"], [])

    @patch("web_ui_routes.feedback.get_task_queue")
    def test_json_list_dedup_and_strip(self, mock_get_tq) -> None:
        mock_tq = MagicMock()
        mock_tq.get_active_task.return_value = MagicMock(task_id="active-6")
        mock_get_tq.return_value = mock_tq

        resp = self._client.post(
            "/api/submit",
            json={
                "feedback_text": "hi",
                "selected_options": ["alpha", "alpha", "  alpha  ", "beta"],
            },
        )
        self.assertEqual(resp.status_code, 200)
        _, result = mock_tq.complete_task.call_args.args
        self.assertEqual(result["selected_options"], ["alpha", "beta"])


if __name__ == "__main__":
    unittest.main()
