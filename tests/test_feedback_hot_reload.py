#!/usr/bin/env python3
"""
配置热更新（feedback）相关测试

目标：
1) 不依赖浏览器，直接验证 Web UI 侧的“配置变更回调”逻辑
2) 验证单任务模式在未显式指定 auto_resubmit_timeout 时，会随配置更新
3) 验证 /api/get-feedback-prompts 的默认值与空值回退逻辑（与 server.py 一致）
"""

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch


class TestFeedbackHotReloadCallback(unittest.TestCase):
    """测试 Web UI 的 feedback 热更新回调（不依赖浏览器）"""

    def setUp(self):
        import web_ui

        # 复位全局状态，避免用例间串扰
        web_ui._LAST_APPLIED_AUTO_RESUBMIT_TIMEOUT = None
        web_ui._CURRENT_WEB_UI_INSTANCE = None

    @patch("web_ui.get_task_queue")
    @patch("web_ui.get_config")
    def test_sync_updates_task_queue_and_single_task_default(
        self, mock_get_config, mock_get_task_queue
    ):
        """配置变更：更新 TaskQueue + 单任务模式（未显式指定）也跟随更新"""
        import web_ui

        # mock config -> frontend_countdown=120
        cfg = MagicMock()
        cfg.get_section.return_value = {"frontend_countdown": 120}
        mock_get_config.return_value = cfg

        # mock task queue
        q = MagicMock()
        q.update_auto_resubmit_timeout_for_all.return_value = 2
        mock_get_task_queue.return_value = q

        # mock single-task instance
        dummy_ui = SimpleNamespace(
            current_auto_resubmit_timeout=240,
            _single_task_timeout_explicit=False,
        )
        web_ui._CURRENT_WEB_UI_INSTANCE = dummy_ui

        web_ui._sync_existing_tasks_timeout_from_config()

        q.update_auto_resubmit_timeout_for_all.assert_called_once_with(120)
        self.assertEqual(dummy_ui.current_auto_resubmit_timeout, 120)

        # 再次调用（值相同）应短路，不重复更新
        web_ui._sync_existing_tasks_timeout_from_config()
        q.update_auto_resubmit_timeout_for_all.assert_called_once()

    @patch("web_ui.get_task_queue")
    @patch("web_ui.get_config")
    def test_sync_does_not_override_single_task_explicit_timeout(
        self, mock_get_config, mock_get_task_queue
    ):
        """配置变更：单任务模式若显式指定 timeout，则不被全局配置覆盖"""
        import web_ui

        cfg = MagicMock()
        cfg.get_section.return_value = {"frontend_countdown": 100}
        mock_get_config.return_value = cfg

        q = MagicMock()
        q.update_auto_resubmit_timeout_for_all.return_value = 1
        mock_get_task_queue.return_value = q

        dummy_ui = SimpleNamespace(
            current_auto_resubmit_timeout=999,
            _single_task_timeout_explicit=True,
        )
        web_ui._CURRENT_WEB_UI_INSTANCE = dummy_ui

        web_ui._sync_existing_tasks_timeout_from_config()

        q.update_auto_resubmit_timeout_for_all.assert_called_once_with(100)
        # 显式指定不应被覆盖
        self.assertEqual(dummy_ui.current_auto_resubmit_timeout, 999)


class TestGetFeedbackPromptsAPIValidation(unittest.TestCase):
    """测试 /api/get-feedback-prompts 的默认值/空值回退"""

    def setUp(self):
        from web_ui import WebFeedbackUI

        self.web_ui = WebFeedbackUI(prompt="prompts", task_id="prompts-test", port=8964)
        self.app = self.web_ui.app
        self.app.config["TESTING"] = True
        self.client = self.app.test_client()

    @patch("web_ui.get_config")
    def test_empty_strings_fallback_to_defaults(self, mock_get_config):
        """resubmit_prompt/prompt_suffix 为空字符串时回退默认值（与 server.py 一致）"""
        from pathlib import Path

        mock_cfg = MagicMock()
        mock_cfg.get_section.return_value = {
            "resubmit_prompt": "   ",
            "prompt_suffix": "",
        }
        mock_cfg.config_file = Path("/tmp/config.jsonc")
        mock_get_config.return_value = mock_cfg

        resp = self.client.get("/api/get-feedback-prompts")
        self.assertEqual(resp.status_code, 200)

        data = resp.get_json()
        self.assertEqual(data["status"], "success")
        self.assertEqual(
            data["config"]["resubmit_prompt"], "请立即调用 interactive_feedback 工具"
        )
        self.assertEqual(
            data["config"]["prompt_suffix"], "\n请积极调用 interactive_feedback 工具"
        )
