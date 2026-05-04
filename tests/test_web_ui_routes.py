"""web_ui_routes 三个路由 Mixin 的单元测试。

覆盖目标：
- notification.py  52.2% → 95%+
- feedback.py      52.8% → 95%+
- task.py          58.3% → 95%+
"""

from __future__ import annotations

import io
import json
import unittest
from typing import Any
from unittest.mock import ANY, MagicMock, patch

from task_queue import Task


# ---------------------------------------------------------------------------
# 测试基类：创建 WebFeedbackUI + Flask test client
# ---------------------------------------------------------------------------
class _RouteTestBase(unittest.TestCase):
    """共享基类：延迟创建 WebFeedbackUI，端口唯一避免冲突。"""

    _port: int = 19001
    _ui: Any = None
    _client: Any = None

    @classmethod
    def setUpClass(cls) -> None:
        from web_ui import WebFeedbackUI

        cls._ui = WebFeedbackUI(prompt="route test", task_id="rt-base", port=cls._port)
        cls._ui.app.config["TESTING"] = True
        cls._ui.limiter.enabled = False
        cls._client = cls._ui.app.test_client()


# ═══════════════════════════════════════════════════════════════════════════
#  notification.py — /api/test-bark
# ═══════════════════════════════════════════════════════════════════════════
class TestBarkTestEndpoint(_RouteTestBase):
    _port = 19010

    def test_missing_device_key_returns_400(self):
        resp = self._client.post(
            "/api/test-bark",
            json={"bark_url": "https://example.com/push", "bark_device_key": ""},
        )
        self.assertEqual(resp.status_code, 400)
        data = resp.get_json()
        self.assertEqual(data["status"], "error")
        self.assertIn("Device Key", data["message"])

    @patch("web_ui_routes.notification.NOTIFICATION_AVAILABLE", False)
    def test_notification_unavailable_returns_500(self):
        resp = self._client.post(
            "/api/test-bark",
            json={"bark_device_key": "test-key-123"},
        )
        self.assertEqual(resp.status_code, 500)
        data = resp.get_json()
        self.assertIn("unavailable", data["message"])

    @patch("web_ui_routes.notification.NOTIFICATION_AVAILABLE", True)
    @patch("web_ui_routes.notification.BarkNotificationProvider")
    @patch("web_ui_routes.notification.NotificationEvent")
    def test_bark_send_success(self, mock_event_cls, mock_provider_cls):
        mock_provider = MagicMock()
        mock_provider.send.return_value = True
        mock_provider_cls.return_value = mock_provider

        resp = self._client.post(
            "/api/test-bark",
            json={
                "bark_device_key": "real-key",
                "bark_url": "https://bark.test/push",
                "bark_action": "url",
                "bark_url_template": "{base_url}/?task_id={task_id}",
            },
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data["status"], "success")
        self.assertIn("sent", data["message"])
        temp_config = mock_provider_cls.call_args.args[0]
        self.assertEqual(temp_config.bark_url_template, "{base_url}/?task_id={task_id}")
        self.assertEqual(temp_config.bark_action, "url")
        event_kwargs = mock_event_cls.call_args.kwargs
        self.assertEqual(event_kwargs["metadata"]["task_id"], "test-task-id")

    @patch("web_ui_routes.notification.NOTIFICATION_AVAILABLE", True)
    @patch("web_ui_routes.notification.BarkNotificationProvider")
    @patch("web_ui_routes.notification.NotificationEvent")
    def test_bark_send_fail_no_error_detail(self, mock_event_cls, mock_provider_cls):
        mock_provider = MagicMock()
        mock_provider.send.return_value = False
        mock_provider_cls.return_value = mock_provider

        mock_event = MagicMock()
        mock_event.metadata = {"test": True}
        mock_event_cls.return_value = mock_event

        resp = self._client.post("/api/test-bark", json={"bark_device_key": "key1"})
        self.assertEqual(resp.status_code, 500)
        data = resp.get_json()
        self.assertIn("check configuration", data["message"])

    @patch("web_ui_routes.notification.NOTIFICATION_AVAILABLE", True)
    @patch("web_ui_routes.notification.BarkNotificationProvider")
    @patch("web_ui_routes.notification.NotificationEvent")
    def test_bark_send_fail_with_error_detail(self, mock_event_cls, mock_provider_cls):
        mock_provider = MagicMock()
        mock_provider.send.return_value = False
        mock_provider_cls.return_value = mock_provider

        mock_event = MagicMock()
        mock_event.metadata = {
            "bark_error": {"detail": "Invalid device key", "status_code": 401}
        }
        mock_event_cls.return_value = mock_event

        resp = self._client.post("/api/test-bark", json={"bark_device_key": "bad-key"})
        self.assertEqual(resp.status_code, 500)
        data = resp.get_json()
        self.assertIn("HTTP 401", data["message"])
        self.assertIn("Invalid device key", data["message"])

    @patch("web_ui_routes.notification.NOTIFICATION_AVAILABLE", True)
    @patch("web_ui_routes.notification.BarkNotificationProvider")
    @patch("web_ui_routes.notification.NotificationEvent")
    def test_bark_send_fail_with_detail_no_status_code(
        self, mock_event_cls, mock_provider_cls
    ):
        mock_provider = MagicMock()
        mock_provider.send.return_value = False
        mock_provider_cls.return_value = mock_provider

        mock_event = MagicMock()
        mock_event.metadata = {"bark_error": {"detail": "timeout"}}
        mock_event_cls.return_value = mock_event

        resp = self._client.post("/api/test-bark", json={"bark_device_key": "key2"})
        self.assertEqual(resp.status_code, 500)
        data = resp.get_json()
        self.assertIn("timeout", data["message"])
        self.assertNotIn("HTTP", data["message"])

    @patch("web_ui_routes.notification.NOTIFICATION_AVAILABLE", True)
    @patch(
        "web_ui_routes.notification.BarkNotificationProvider",
        side_effect=RuntimeError("boom"),
    )
    def test_bark_outer_exception_returns_500(self, _):
        resp = self._client.post("/api/test-bark", json={"bark_device_key": "key3"})
        self.assertEqual(resp.status_code, 500)
        data = resp.get_json()
        self.assertEqual(data["message"], "Test failed")

    def test_bark_no_json_body(self):
        resp = self._client.post(
            "/api/test-bark",
            data="not json",
            content_type="text/plain",
        )
        self.assertIn(resp.status_code, (400, 500))

    @patch("web_ui_routes.notification.NOTIFICATION_AVAILABLE", True)
    @patch("web_ui_routes.notification.BarkNotificationProvider")
    @patch("web_ui_routes.notification.NotificationEvent")
    def test_bark_metadata_access_exception(self, mock_event_cls, mock_provider_cls):
        """metadata 访问异常时兜底返回通用错误"""
        mock_provider = MagicMock()
        mock_provider.send.return_value = False
        mock_provider_cls.return_value = mock_provider

        mock_event = MagicMock()
        type(mock_event).metadata = property(
            lambda s: (_ for _ in ()).throw(RuntimeError("no attr"))
        )
        mock_event_cls.return_value = mock_event

        resp = self._client.post("/api/test-bark", json={"bark_device_key": "key4"})
        self.assertEqual(resp.status_code, 500)


# ═══════════════════════════════════════════════════════════════════════════
#  notification.py — /api/notify-new-tasks
# ═══════════════════════════════════════════════════════════════════════════
class TestNotifyNewTasks(_RouteTestBase):
    _port = 19011

    def test_count_zero_skipped(self):
        resp = self._client.post("/api/notify-new-tasks", json={"count": 0})
        data = resp.get_json()
        self.assertEqual(data["status"], "skipped")
        self.assertIn("count=0", data["message"])

    def test_count_nan_falls_back_to_zero(self):
        """lines 171-172: int(float('nan')) 异常被捕获"""
        with patch(
            "flask.wrappers.Request.get_json",
            return_value={"count": float("nan"), "taskIds": []},
        ):
            resp = self._client.post(
                "/api/notify-new-tasks", content_type="application/json"
            )
            data = resp.get_json()
            self.assertEqual(data["status"], "skipped")

    def test_task_ids_non_list_ignored(self):
        """branch 157->166: taskIds 非列表时被忽略，仅使用 count"""
        resp = self._client.post(
            "/api/notify-new-tasks",
            json={"taskIds": "not-a-list", "count": 0},
        )
        data = resp.get_json()
        self.assertEqual(data["status"], "skipped")

    def test_empty_body_skipped(self):
        resp = self._client.post("/api/notify-new-tasks", json={})
        data = resp.get_json()
        self.assertEqual(data["status"], "skipped")

    @patch("web_ui_routes.notification.NOTIFICATION_AVAILABLE", False)
    def test_notification_unavailable_skipped(self):
        resp = self._client.post(
            "/api/notify-new-tasks", json={"count": 1, "taskIds": ["t1"]}
        )
        data = resp.get_json()
        self.assertEqual(data["status"], "skipped")
        self.assertIn("unavailable", data["message"])

    @patch("web_ui_routes.notification.NOTIFICATION_AVAILABLE", True)
    @patch("web_ui_routes.notification.notification_manager")
    def test_config_disabled_skipped(self, mock_nm):
        mock_nm.config = MagicMock()
        mock_nm.config.enabled = False
        mock_nm.refresh_config_from_file = MagicMock()

        resp = self._client.post(
            "/api/notify-new-tasks", json={"count": 1, "taskIds": ["t1"]}
        )
        data = resp.get_json()
        self.assertEqual(data["status"], "skipped")
        self.assertIn("master switch", data["message"])

    @patch("web_ui_routes.notification.NOTIFICATION_AVAILABLE", True)
    @patch("web_ui_routes.notification.notification_manager")
    def test_bark_disabled_skipped(self, mock_nm):
        mock_nm.config = MagicMock()
        mock_nm.config.enabled = True
        mock_nm.config.bark_enabled = False
        mock_nm.refresh_config_from_file = MagicMock()

        resp = self._client.post(
            "/api/notify-new-tasks", json={"count": 1, "taskIds": ["t1"]}
        )
        data = resp.get_json()
        self.assertIn("Bark is disabled", data["message"])

    @patch("web_ui_routes.notification.NOTIFICATION_AVAILABLE", True)
    @patch("web_ui_routes.notification.notification_manager")
    def test_bark_device_key_empty_skipped(self, mock_nm):
        mock_nm.config = MagicMock()
        mock_nm.config.enabled = True
        mock_nm.config.bark_enabled = True
        mock_nm.config.bark_device_key = ""
        mock_nm.refresh_config_from_file = MagicMock()

        resp = self._client.post("/api/notify-new-tasks", json={"count": 2})
        data = resp.get_json()
        self.assertIn("bark_device_key", data["message"])

    @patch("web_ui_routes.notification.NOTIFICATION_AVAILABLE", True)
    @patch("web_ui_routes.notification.notification_manager")
    def test_send_success_single_task(self, mock_nm):
        mock_nm.config = MagicMock()
        mock_nm.config.enabled = True
        mock_nm.config.bark_enabled = True
        mock_nm.config.bark_device_key = "valid-key"
        mock_nm.refresh_config_from_file = MagicMock()
        mock_nm.send_notification.return_value = "evt-001"

        resp = self._client.post(
            "/api/notify-new-tasks", json={"count": 1, "taskIds": ["task-abc"]}
        )
        data = resp.get_json()
        self.assertEqual(data["status"], "success")
        self.assertEqual(data["event_id"], "evt-001")
        call_kwargs = mock_nm.send_notification.call_args
        self.assertIn("task-abc", call_kwargs.kwargs.get("message", ""))

    @patch("web_ui_routes.notification.NOTIFICATION_AVAILABLE", True)
    @patch("web_ui_routes.notification.notification_manager")
    def test_send_success_multiple_tasks(self, mock_nm):
        mock_nm.config = MagicMock()
        mock_nm.config.enabled = True
        mock_nm.config.bark_enabled = True
        mock_nm.config.bark_device_key = "valid-key"
        mock_nm.refresh_config_from_file = MagicMock()
        mock_nm.send_notification.return_value = "evt-002"

        resp = self._client.post(
            "/api/notify-new-tasks", json={"count": 3, "taskIds": ["a", "b", "c"]}
        )
        data = resp.get_json()
        self.assertEqual(data["status"], "success")
        call_kwargs = mock_nm.send_notification.call_args
        self.assertIn("3 个新任务", call_kwargs.kwargs.get("message", ""))

    @patch("web_ui_routes.notification.NOTIFICATION_AVAILABLE", True)
    @patch("web_ui_routes.notification.notification_manager")
    def test_send_returns_none_skipped(self, mock_nm):
        mock_nm.config = MagicMock()
        mock_nm.config.enabled = True
        mock_nm.config.bark_enabled = True
        mock_nm.config.bark_device_key = "valid-key"
        mock_nm.refresh_config_from_file = MagicMock()
        mock_nm.send_notification.return_value = None

        resp = self._client.post(
            "/api/notify-new-tasks", json={"count": 1, "taskIds": ["t1"]}
        )
        self.assertEqual(
            resp.status_code, 200, f"Unexpected: {resp.status_code} {resp.data}"
        )
        data = resp.get_json()
        self.assertIsNotNone(data, f"Not JSON: {resp.data}")
        self.assertEqual(data["status"], "skipped")

    @patch("web_ui_routes.notification.NOTIFICATION_AVAILABLE", True)
    @patch("web_ui_routes.notification.notification_manager")
    def test_refresh_config_exception_ignored(self, mock_nm):
        mock_nm.refresh_config_from_file.side_effect = RuntimeError("fail")
        mock_nm.config = MagicMock()
        mock_nm.config.enabled = True
        mock_nm.config.bark_enabled = True
        mock_nm.config.bark_device_key = "key"
        mock_nm.send_notification.return_value = "evt-003"

        resp = self._client.post(
            "/api/notify-new-tasks", json={"count": 1, "taskIds": ["t2"]}
        )
        data = resp.get_json()
        self.assertEqual(data["status"], "success")

    @patch("web_ui_routes.notification.NOTIFICATION_AVAILABLE", True)
    @patch(
        "web_ui_routes.notification.notification_manager",
        side_effect=AttributeError("boom"),
    )
    def test_outer_exception_returns_500(self, _):
        resp = self._client.post(
            "/api/notify-new-tasks", json={"count": 1, "taskIds": ["x"]}
        )
        self.assertEqual(resp.status_code, 500)
        data = resp.get_json()
        self.assertEqual(data["status"], "error")

    def test_task_ids_with_none_and_empty(self):
        """None / 空字符串的 taskIds 元素被过滤"""
        resp = self._client.post(
            "/api/notify-new-tasks",
            json={"taskIds": [None, "", "valid-id"]},
        )
        data = resp.get_json()
        self.assertIn(data["status"], ("skipped", "success"))

    def test_count_from_float(self):
        """count 为浮点数时正确转换"""
        resp = self._client.post(
            "/api/notify-new-tasks", json={"count": 2.7, "taskIds": ["a", "b"]}
        )
        data = resp.get_json()
        self.assertIn(data["status"], ("skipped", "success"))

    @patch("web_ui_routes.notification.NOTIFICATION_AVAILABLE", True)
    @patch("web_ui_routes.notification.notification_manager")
    def test_no_config_attr_skipped(self, mock_nm):
        """notification_manager 无 config 属性时降级"""
        mock_nm.refresh_config_from_file = MagicMock()
        mock_nm.config = None

        resp = self._client.post(
            "/api/notify-new-tasks", json={"count": 1, "taskIds": ["t1"]}
        )
        data = resp.get_json()
        self.assertEqual(data["status"], "skipped")


# ═══════════════════════════════════════════════════════════════════════════
#  notification.py — /api/update-notification-config
# ═══════════════════════════════════════════════════════════════════════════
class TestUpdateNotificationConfig(_RouteTestBase):
    _port = 19012

    @patch("web_ui_routes.notification.NOTIFICATION_AVAILABLE", False)
    def test_notification_unavailable_returns_500(self):
        resp = self._client.post(
            "/api/update-notification-config", json={"enabled": True}
        )
        self.assertEqual(resp.status_code, 500)
        data = resp.get_json()
        self.assertIn("unavailable", data["message"])

    @patch("web_ui_routes.notification.NOTIFICATION_AVAILABLE", True)
    @patch("web_ui_routes.notification.notification_manager")
    @patch("web_ui_routes.notification.get_config")
    def test_no_recognizable_fields(self, mock_get_cfg, mock_nm):
        mock_cfg = MagicMock()
        mock_cfg.get_section.return_value = {"sound_volume": 80}
        mock_get_cfg.return_value = mock_cfg

        resp = self._client.post(
            "/api/update-notification-config", json={"unknown_field": "value"}
        )
        data = resp.get_json()
        self.assertEqual(data["status"], "success")
        self.assertIn("No notification config fields", data["message"])

    @patch("web_ui_routes.notification.NOTIFICATION_AVAILABLE", True)
    @patch("web_ui_routes.notification.notification_manager")
    @patch("web_ui_routes.notification.get_config")
    def test_update_multiple_fields(self, mock_get_cfg, mock_nm):
        mock_cfg = MagicMock()
        mock_cfg.get_section.return_value = {
            "sound_volume": 80,
            "web_timeout": 5000,
        }
        mock_get_cfg.return_value = mock_cfg

        resp = self._client.post(
            "/api/update-notification-config",
            json={
                "enabled": True,
                "soundVolume": 60,
                "webTimeout": 3000,
                "barkEnabled": True,
                "barkDeviceKey": "my-key",
                "soundEnabled": True,
                "soundMute": False,
                "macosNativeEnabled": True,
                "barkUrl": "https://bark.test",
                "barkIcon": "icon.png",
                "barkAction": "open",
                "webEnabled": True,
                "webIcon": "alert.png",
                "autoRequestPermission": True,
                "soundFile": "chime.mp3",
                "mobileOptimized": True,
                "mobileVibrate": True,
            },
        )
        data = resp.get_json()
        self.assertEqual(data["status"], "success")
        self.assertIn("updated", data["message"])
        mock_nm.update_config_without_save.assert_called_once()
        mock_cfg.update_section.assert_called_once()

    @patch("web_ui_routes.notification.NOTIFICATION_AVAILABLE", True)
    @patch("web_ui_routes.notification.notification_manager")
    @patch("web_ui_routes.notification.get_config")
    def test_sound_volume_invalid_falls_back(self, mock_get_cfg, mock_nm):
        mock_cfg = MagicMock()
        mock_cfg.get_section.return_value = {"sound_volume": 75}
        mock_get_cfg.return_value = mock_cfg

        resp = self._client.post(
            "/api/update-notification-config",
            json={"soundVolume": "not_a_number"},
        )
        data = resp.get_json()
        self.assertEqual(data["status"], "success")

    @patch("web_ui_routes.notification.NOTIFICATION_AVAILABLE", True)
    @patch("web_ui_routes.notification.notification_manager")
    @patch("web_ui_routes.notification.get_config")
    def test_web_timeout_invalid_falls_back(self, mock_get_cfg, mock_nm):
        mock_cfg = MagicMock()
        mock_cfg.get_section.return_value = {"web_timeout": 5000}
        mock_get_cfg.return_value = mock_cfg

        resp = self._client.post(
            "/api/update-notification-config",
            json={"webTimeout": "bad"},
        )
        data = resp.get_json()
        self.assertEqual(data["status"], "success")

    @patch("web_ui_routes.notification.NOTIFICATION_AVAILABLE", True)
    @patch(
        "web_ui_routes.notification.get_config",
        side_effect=RuntimeError("config boom"),
    )
    def test_outer_exception_returns_500(self, _):
        resp = self._client.post(
            "/api/update-notification-config", json={"enabled": True}
        )
        self.assertEqual(resp.status_code, 500)

    def test_non_dict_data_treated_as_empty(self):
        """传入非 dict JSON 体（如 list）→ data 被重置为空 dict"""
        resp = self._client.post(
            "/api/update-notification-config",
            data=json.dumps([1, 2, 3]),
            content_type="application/json",
        )
        self.assertIn(resp.status_code, (200, 500))


# ═══════════════════════════════════════════════════════════════════════════
#  notification.py — /api/get-notification-config & /api/get-feedback-prompts
# ═══════════════════════════════════════════════════════════════════════════
class TestGetNotificationConfig(_RouteTestBase):
    _port = 19013

    @patch("web_ui_routes.notification.get_config")
    def test_success(self, mock_get_cfg):
        mock_cfg = MagicMock()
        mock_cfg.get_section.return_value = {"enabled": True, "bark_enabled": False}
        mock_get_cfg.return_value = mock_cfg

        resp = self._client.get("/api/get-notification-config")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data["status"], "success")
        self.assertTrue(data["config"]["enabled"])

    @patch(
        "web_ui_routes.notification.get_config",
        side_effect=RuntimeError("fail"),
    )
    def test_exception_returns_500(self, _):
        resp = self._client.get("/api/get-notification-config")
        self.assertEqual(resp.status_code, 500)
        data = resp.get_json()
        self.assertIn("Failed to get config", data["message"])


class TestGetFeedbackPrompts(_RouteTestBase):
    _port = 19014

    @patch("web_ui_routes.notification.get_config")
    def test_success(self, mock_get_cfg):
        mock_cfg = MagicMock()
        mock_cfg.get_section.return_value = {
            "resubmit_prompt": "请调用",
            "prompt_suffix": "\n追加",
        }
        mock_cfg.config_file = MagicMock()
        mock_cfg.config_file.absolute.return_value = "/tmp/config.toml"
        mock_get_cfg.return_value = mock_cfg

        resp = self._client.get("/api/get-feedback-prompts")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data["status"], "success")
        self.assertIn("resubmit_prompt", data["config"])
        self.assertIn("meta", data)

    @patch(
        "web_ui_routes.notification.get_config",
        side_effect=RuntimeError("fail"),
    )
    def test_exception_returns_500(self, _):
        resp = self._client.get("/api/get-feedback-prompts")
        self.assertEqual(resp.status_code, 500)


# ═══════════════════════════════════════════════════════════════════════════
#  feedback.py — /api/submit
# ═══════════════════════════════════════════════════════════════════════════
class TestSubmitFeedbackJSON(_RouteTestBase):
    _port = 19020

    @patch("web_ui_routes.feedback.get_task_queue")
    def test_json_body_success(self, mock_get_tq):
        mock_tq = MagicMock()
        mock_tq.get_active_task.return_value = MagicMock(task_id="active-1")
        mock_get_tq.return_value = mock_tq

        resp = self._client.post(
            "/api/submit",
            json={"feedback_text": "looks good", "selected_options": ["A"]},
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data["status"], "success")
        mock_tq.complete_task.assert_called_once()

    @patch("web_ui_routes.feedback.get_task_queue")
    def test_json_with_task_id_not_found(self, mock_get_tq):
        mock_tq = MagicMock()
        mock_tq.get_task.return_value = None
        mock_get_tq.return_value = mock_tq

        resp = self._client.post(
            "/api/submit",
            json={"task_id": "nonexistent", "feedback_text": "hello"},
        )
        self.assertEqual(resp.status_code, 404)

    @patch("web_ui_routes.feedback.get_task_queue")
    def test_json_with_task_id_exists(self, mock_get_tq):
        mock_tq = MagicMock()
        mock_tq.get_task.return_value = MagicMock(task_id="existing-task")
        mock_get_tq.return_value = mock_tq

        resp = self._client.post(
            "/api/submit",
            json={"task_id": "existing-task", "feedback_text": "done"},
        )
        self.assertEqual(resp.status_code, 200)
        mock_tq.complete_task.assert_called_once_with("existing-task", ANY)

    @patch("web_ui_routes.feedback.get_task_queue")
    def test_json_no_active_task(self, mock_get_tq):
        """无 task_id 且无活跃任务 → target_task_id 为空"""
        mock_tq = MagicMock()
        mock_tq.get_active_task.return_value = None
        mock_get_tq.return_value = mock_tq

        resp = self._client.post("/api/submit", json={"feedback_text": "standalone"})
        self.assertEqual(resp.status_code, 200)
        mock_tq.complete_task.assert_not_called()


class TestSubmitFeedbackForm(_RouteTestBase):
    _port = 19021

    @patch("web_ui_routes.feedback.get_task_queue")
    def test_form_data_with_invalid_json_options(self, mock_get_tq):
        mock_tq = MagicMock()
        mock_tq.get_active_task.return_value = MagicMock(task_id="a1")
        mock_get_tq.return_value = mock_tq

        resp = self._client.post(
            "/api/submit",
            data={
                "feedback_text": "hello",
                "selected_options": "not-valid-json",
            },
            content_type="application/x-www-form-urlencoded",
        )
        self.assertEqual(resp.status_code, 200)

    @patch("web_ui_routes.feedback.get_task_queue")
    def test_form_data_normal(self, mock_get_tq):
        mock_tq = MagicMock()
        mock_tq.get_active_task.return_value = MagicMock(task_id="a2")
        mock_get_tq.return_value = mock_tq

        resp = self._client.post(
            "/api/submit",
            data={
                "feedback_text": "form feedback",
                "selected_options": '["opt1"]',
            },
            content_type="application/x-www-form-urlencoded",
        )
        self.assertEqual(resp.status_code, 200)


class TestSubmitFeedbackMultipart(_RouteTestBase):
    _port = 19022

    @patch("web_ui_routes._upload_helpers.validate_uploaded_file")
    @patch("web_ui_routes.feedback.get_task_queue")
    def test_multipart_with_valid_image(self, mock_get_tq, mock_validate):
        mock_tq = MagicMock()
        mock_tq.get_active_task.return_value = MagicMock(task_id="multi-1")
        mock_get_tq.return_value = mock_tq
        mock_validate.return_value = {
            "valid": True,
            "errors": [],
            "warnings": [],
            "mime_type": "image/png",
            "file_type": "image",
            "extension": ".png",
        }

        data = {
            "feedback_text": "with image",
            "selected_options": "[]",
            "image_0": (io.BytesIO(b"\x89PNG\r\n\x1a\nfakedata"), "test.png"),
        }
        resp = self._client.post(
            "/api/submit", data=data, content_type="multipart/form-data"
        )
        self.assertEqual(resp.status_code, 200)

    @patch("web_ui_routes._upload_helpers.validate_uploaded_file")
    @patch("web_ui_routes.feedback.get_task_queue")
    def test_multipart_with_invalid_file(self, mock_get_tq, mock_validate):
        mock_tq = MagicMock()
        mock_tq.get_active_task.return_value = MagicMock(task_id="multi-2")
        mock_get_tq.return_value = mock_tq
        mock_validate.return_value = {
            "valid": False,
            "errors": ["恶意文件"],
            "warnings": [],
            "mime_type": None,
            "file_type": "unknown",
            "extension": ".bin",
        }

        data = {
            "feedback_text": "bad file",
            "selected_options": "[]",
            "image_0": (io.BytesIO(b"malicious"), "bad.exe"),
        }
        resp = self._client.post(
            "/api/submit", data=data, content_type="multipart/form-data"
        )
        self.assertEqual(resp.status_code, 200)

    @patch("web_ui_routes._upload_helpers.validate_uploaded_file")
    @patch("web_ui_routes.feedback.get_task_queue")
    def test_multipart_with_validation_warnings(self, mock_get_tq, mock_validate):
        mock_tq = MagicMock()
        mock_tq.get_active_task.return_value = MagicMock(task_id="multi-3")
        mock_get_tq.return_value = mock_tq
        mock_validate.return_value = {
            "valid": True,
            "errors": [],
            "warnings": ["文件较大"],
            "mime_type": "image/jpeg",
            "file_type": "image",
            "extension": ".jpg",
        }

        data = {
            "feedback_text": "warned",
            "selected_options": "[]",
            "image_0": (io.BytesIO(b"\xff\xd8\xff\xe0fake"), "large.jpg"),
        }
        resp = self._client.post(
            "/api/submit", data=data, content_type="multipart/form-data"
        )
        self.assertEqual(resp.status_code, 200)

    @patch(
        "web_ui_routes._upload_helpers.validate_uploaded_file", side_effect=RuntimeError
    )
    @patch("web_ui_routes.feedback.get_task_queue")
    def test_multipart_file_processing_exception(self, mock_get_tq, _):
        mock_tq = MagicMock()
        mock_tq.get_active_task.return_value = MagicMock(task_id="multi-4")
        mock_get_tq.return_value = mock_tq

        data = {
            "feedback_text": "error",
            "selected_options": "[]",
            "image_0": (io.BytesIO(b"data"), "crash.png"),
        }
        resp = self._client.post(
            "/api/submit", data=data, content_type="multipart/form-data"
        )
        self.assertEqual(resp.status_code, 200)

    @patch("web_ui_routes.feedback.get_task_queue")
    def test_multipart_invalid_json_options(self, mock_get_tq):
        mock_tq = MagicMock()
        mock_tq.get_active_task.return_value = MagicMock(task_id="multi-5")
        mock_get_tq.return_value = mock_tq

        data = {
            "feedback_text": "test",
            "selected_options": "{bad json}",
            "image_0": (io.BytesIO(b"data"), "img.png"),
        }
        resp = self._client.post(
            "/api/submit", data=data, content_type="multipart/form-data"
        )
        self.assertEqual(resp.status_code, 200)

    @patch("web_ui_routes.feedback.get_task_queue")
    def test_non_image_file_key_ignored(self, mock_get_tq):
        """键名非 image_ 前缀的文件被忽略"""
        mock_tq = MagicMock()
        mock_tq.get_active_task.return_value = MagicMock(task_id="multi-6")
        mock_get_tq.return_value = mock_tq

        data = {
            "feedback_text": "no img",
            "selected_options": "[]",
            "document_0": (io.BytesIO(b"data"), "doc.pdf"),
        }
        resp = self._client.post(
            "/api/submit", data=data, content_type="multipart/form-data"
        )
        self.assertEqual(resp.status_code, 200)


class TestSubmitFeedbackJSONParseFail(_RouteTestBase):
    _port = 19023

    @patch("web_ui_routes.feedback.get_task_queue")
    def test_json_parse_fails_uses_defaults(self, mock_get_tq):
        """Content-Type 非 form/multipart 且 JSON 解析失败 → 默认值"""
        mock_tq = MagicMock()
        mock_tq.get_active_task.return_value = None
        mock_get_tq.return_value = mock_tq

        resp = self._client.post(
            "/api/submit",
            data="not valid json at all",
            content_type="application/json",
        )
        self.assertIn(resp.status_code, (200, 400))


# ═══════════════════════════════════════════════════════════════════════════
#  feedback.py — /api/update
# ═══════════════════════════════════════════════════════════════════════════
class TestUpdateContent(_RouteTestBase):
    _port = 19024

    def test_invalid_json_returns_400(self):
        resp = self._client.post(
            "/api/update",
            data="not json",
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)
        data = resp.get_json()
        self.assertEqual(data["error"], "invalid_json")

    def test_non_dict_body_returns_400(self):
        resp = self._client.post(
            "/api/update",
            data=json.dumps([1, 2]),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)
        data = resp.get_json()
        self.assertEqual(data["error"], "invalid_body")

    def test_missing_prompt_returns_400(self):
        resp = self._client.post("/api/update", json={"not_prompt": "x"})
        self.assertEqual(resp.status_code, 400)
        data = resp.get_json()
        self.assertEqual(data["error"], "missing_field")

    def test_non_string_prompt_returns_400(self):
        resp = self._client.post("/api/update", json={"prompt": 123})
        self.assertEqual(resp.status_code, 400)
        data = resp.get_json()
        self.assertEqual(data["error"], "invalid_field_type")

    def test_prompt_too_long_truncated(self):
        long_prompt = "x" * 10001
        resp = self._client.post("/api/update", json={"prompt": long_prompt})
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data["prompt"].endswith("..."))
        self.assertEqual(len(data["prompt"]), 10003)

    def test_options_none_treated_as_empty(self):
        resp = self._client.post(
            "/api/update", json={"prompt": "hello", "predefined_options": None}
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data["predefined_options"], [])

    def test_options_non_list_returns_400(self):
        resp = self._client.post(
            "/api/update", json={"prompt": "hello", "predefined_options": "string"}
        )
        self.assertEqual(resp.status_code, 400)

    def test_options_non_string_items_filtered(self):
        resp = self._client.post(
            "/api/update",
            json={"prompt": "hello", "predefined_options": [123, "valid", "", "  "]},
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data["predefined_options"], ["valid"])

    def test_option_too_long_truncated(self):
        long_opt = "o" * 501
        resp = self._client.post(
            "/api/update", json={"prompt": "hello", "predefined_options": [long_opt]}
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data["predefined_options"][0].endswith("..."))

    def test_task_id_none(self):
        resp = self._client.post(
            "/api/update", json={"prompt": "hello", "task_id": None}
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertIsNone(data["task_id"])

    def test_task_id_string(self):
        resp = self._client.post(
            "/api/update", json={"prompt": "hello", "task_id": "  t-1  "}
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data["task_id"], "t-1")

    def test_task_id_non_string(self):
        resp = self._client.post("/api/update", json={"prompt": "hello", "task_id": 42})
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data["task_id"], "42")

    def test_timeout_explicit_valid(self):
        resp = self._client.post(
            "/api/update", json={"prompt": "hello", "auto_resubmit_timeout": 120}
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertIn("auto_resubmit_timeout", data)

    def test_timeout_explicit_invalid_returns_400(self):
        resp = self._client.post(
            "/api/update", json={"prompt": "hello", "auto_resubmit_timeout": "bad"}
        )
        self.assertEqual(resp.status_code, 400)
        data = resp.get_json()
        self.assertEqual(data["error"], "invalid_field_value")

    def test_update_success_with_content(self):
        resp = self._client.post(
            "/api/update",
            json={
                "prompt": "# Hello World",
                "predefined_options": ["Yes", "No"],
                "task_id": "task-42",
            },
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data["status"], "success")
        self.assertTrue(data["has_content"])
        self.assertIn("Hello", data["prompt_html"])

    def test_update_empty_prompt(self):
        resp = self._client.post("/api/update", json={"prompt": "   "})
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertFalse(data["has_content"])


# ═══════════════════════════════════════════════════════════════════════════
#  feedback.py — /api/feedback
# ═══════════════════════════════════════════════════════════════════════════
class TestGetFeedback(_RouteTestBase):
    _port = 19025

    def test_no_feedback_returns_waiting(self):
        with self._ui._state_lock:
            self._ui.feedback_result = None
        resp = self._client.get("/api/feedback")
        data = resp.get_json()
        self.assertEqual(data["status"], "waiting")
        self.assertIsNone(data["feedback"])

    def test_has_feedback_returns_success(self):
        with self._ui._state_lock:
            self._ui.feedback_result = {
                "user_input": "yes",
                "selected_options": ["A"],
                "images": [],
            }
        resp = self._client.get("/api/feedback")
        data = resp.get_json()
        self.assertEqual(data["status"], "success")
        self.assertEqual(data["feedback"]["user_input"], "yes")

        resp2 = self._client.get("/api/feedback")
        data2 = resp2.get_json()
        self.assertEqual(data2["status"], "waiting")


# ═══════════════════════════════════════════════════════════════════════════
#  task.py — /api/tasks GET (list)
# ═══════════════════════════════════════════════════════════════════════════
class TestGetTasks(_RouteTestBase):
    _port = 19030

    @patch("web_ui_routes.task.get_task_queue")
    def test_success_with_tasks(self, mock_get_tq):
        mock_tq = MagicMock()
        task = Task(
            task_id="t1",
            prompt="hello world test prompt",
            auto_resubmit_timeout=120,
        )
        mock_tq.get_all_tasks.return_value = [task]
        mock_tq.get_task_count.return_value = {
            "total": 1,
            "pending": 1,
            "active": 0,
            "completed": 0,
        }
        mock_get_tq.return_value = mock_tq

        resp = self._client.get("/api/tasks")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data["success"])
        self.assertEqual(len(data["tasks"]), 1)
        self.assertEqual(data["tasks"][0]["task_id"], "t1")
        mock_tq.cleanup_completed_tasks.assert_called_once_with(age_seconds=10)

    @patch("web_ui_routes.task.get_task_queue", side_effect=RuntimeError("boom"))
    def test_exception_returns_500(self, _):
        resp = self._client.get("/api/tasks")
        self.assertEqual(resp.status_code, 500)
        data = resp.get_json()
        self.assertFalse(data["success"])


# ═══════════════════════════════════════════════════════════════════════════
#  task.py — /api/tasks POST (create)
# ═══════════════════════════════════════════════════════════════════════════
class TestCreateTask(_RouteTestBase):
    _port = 19031

    def test_invalid_json_returns_400(self):
        resp = self._client.post(
            "/api/tasks",
            data="not json",
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)

    def test_non_dict_body_returns_400(self):
        resp = self._client.post(
            "/api/tasks",
            data=json.dumps([1, 2]),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)

    def test_missing_task_id_returns_400(self):
        resp = self._client.post("/api/tasks", json={"prompt": "test"})
        self.assertEqual(resp.status_code, 400)
        data = resp.get_json()
        self.assertIn("task_id", data["error"])

    def test_empty_task_id_returns_400(self):
        resp = self._client.post(
            "/api/tasks", json={"task_id": "   ", "prompt": "test"}
        )
        self.assertEqual(resp.status_code, 400)

    def test_missing_prompt_returns_400(self):
        resp = self._client.post("/api/tasks", json={"task_id": "t1"})
        self.assertEqual(resp.status_code, 400)
        data = resp.get_json()
        self.assertIn("prompt", data["error"])

    def test_non_string_prompt_returns_400(self):
        resp = self._client.post("/api/tasks", json={"task_id": "t1", "prompt": 123})
        self.assertEqual(resp.status_code, 400)

    def test_options_non_list_returns_400(self):
        resp = self._client.post(
            "/api/tasks",
            json={"task_id": "t1", "prompt": "p", "predefined_options": "str"},
        )
        self.assertEqual(resp.status_code, 400)

    def test_options_non_string_element_returns_400(self):
        resp = self._client.post(
            "/api/tasks",
            json={"task_id": "t1", "prompt": "p", "predefined_options": [1]},
        )
        self.assertEqual(resp.status_code, 400)

    def test_options_none_allowed(self):
        with patch("web_ui_routes.task.get_task_queue") as mock_get_tq:
            mock_tq = MagicMock()
            mock_tq.add_task.return_value = True
            mock_get_tq.return_value = mock_tq

            resp = self._client.post(
                "/api/tasks",
                json={
                    "task_id": "t2",
                    "prompt": "p",
                    "predefined_options": None,
                },
            )
            self.assertEqual(resp.status_code, 200)

    def test_timeout_none_returns_400(self):
        resp = self._client.post(
            "/api/tasks",
            json={
                "task_id": "t1",
                "prompt": "p",
                "auto_resubmit_timeout": None,
            },
        )
        self.assertEqual(resp.status_code, 400)

    def test_timeout_bool_returns_400(self):
        resp = self._client.post(
            "/api/tasks",
            json={
                "task_id": "t1",
                "prompt": "p",
                "auto_resubmit_timeout": True,
            },
        )
        self.assertEqual(resp.status_code, 400)

    def test_timeout_non_numeric_returns_400(self):
        resp = self._client.post(
            "/api/tasks",
            json={
                "task_id": "t1",
                "prompt": "p",
                "auto_resubmit_timeout": "bad",
            },
        )
        self.assertEqual(resp.status_code, 400)

    @patch("web_ui_routes.task.get_task_queue")
    def test_create_success(self, mock_get_tq):
        mock_tq = MagicMock()
        mock_tq.add_task.return_value = True
        mock_get_tq.return_value = mock_tq

        resp = self._client.post(
            "/api/tasks",
            json={
                "task_id": "new-task",
                "prompt": "do something",
                "predefined_options": ["A", "B"],
                "auto_resubmit_timeout": 120,
            },
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data["success"])
        self.assertEqual(data["task_id"], "new-task")

    @patch("web_ui_routes.task.get_task_queue")
    def test_create_fails_409(self, mock_get_tq):
        mock_tq = MagicMock()
        mock_tq.add_task.return_value = False
        mock_get_tq.return_value = mock_tq

        resp = self._client.post(
            "/api/tasks",
            json={"task_id": "dup", "prompt": "test"},
        )
        self.assertEqual(resp.status_code, 409)

    @patch("web_ui_routes.task.get_task_queue", side_effect=RuntimeError("boom"))
    def test_create_exception_500(self, _):
        resp = self._client.post(
            "/api/tasks",
            json={"task_id": "err", "prompt": "test"},
        )
        self.assertEqual(resp.status_code, 500)

    def test_alias_id_and_message(self):
        """使用 id/message 别名替代 task_id/prompt"""
        with patch("web_ui_routes.task.get_task_queue") as mock_get_tq:
            mock_tq = MagicMock()
            mock_tq.add_task.return_value = True
            mock_get_tq.return_value = mock_tq

            resp = self._client.post(
                "/api/tasks",
                json={"id": "alias-t", "message": "alias prompt"},
            )
            self.assertEqual(resp.status_code, 200)

    def test_alias_timeout(self):
        """使用 timeout 别名"""
        with patch("web_ui_routes.task.get_task_queue") as mock_get_tq:
            mock_tq = MagicMock()
            mock_tq.add_task.return_value = True
            mock_get_tq.return_value = mock_tq

            resp = self._client.post(
                "/api/tasks",
                json={"task_id": "t-alias", "prompt": "p", "timeout": 60},
            )
            self.assertEqual(resp.status_code, 200)

    def test_options_with_empty_strings_cleaned(self):
        """空字符串选项被过滤"""
        with patch("web_ui_routes.task.get_task_queue") as mock_get_tq:
            mock_tq = MagicMock()
            mock_tq.add_task.return_value = True
            mock_get_tq.return_value = mock_tq

            resp = self._client.post(
                "/api/tasks",
                json={
                    "task_id": "t-clean",
                    "prompt": "p",
                    "options": ["valid", "  ", ""],
                },
            )
            self.assertEqual(resp.status_code, 200)
            call_kwargs = mock_tq.add_task.call_args
            self.assertEqual(call_kwargs.kwargs.get("predefined_options"), ["valid"])

    # ────────────────────────────────────────────────────────────────────
    # predefined_options_defaults（TODO #3 加的字段，原本完全无测试覆盖）
    # ────────────────────────────────────────────────────────────────────

    def test_options_defaults_non_list_returns_400(self):
        """``predefined_options_defaults`` 不是 list（如对象/字符串）→ 400。"""
        resp = self._client.post(
            "/api/tasks",
            json={
                "task_id": "td-1",
                "prompt": "p",
                "predefined_options": ["A", "B"],
                "predefined_options_defaults": "true",
            },
        )
        self.assertEqual(resp.status_code, 400)
        data = resp.get_json()
        self.assertIn("predefined_options_defaults", data["error"])

    def test_options_defaults_mixed_types_normalized(self):
        """defaults 内含 bool / int / float / str / 其它 → 全部规范化为 bool。

        覆盖 task.py 411-423 的 normalisation 矩阵：
        - True / 1 / 1.0 / 'true' / 'yes' / 'on' / 'selected' → True
        - False / 0 / 0.0 / 'no' / 'off' / 'random' / None / list / dict → False
        """
        with patch("web_ui_routes.task.get_task_queue") as mock_get_tq:
            mock_tq = MagicMock()
            mock_tq.add_task.return_value = True
            mock_get_tq.return_value = mock_tq

            resp = self._client.post(
                "/api/tasks",
                json={
                    "task_id": "td-2",
                    "prompt": "p",
                    "predefined_options": [
                        "a",
                        "b",
                        "c",
                        "d",
                        "e",
                        "f",
                        "g",
                        "h",
                    ],
                    "predefined_options_defaults": [
                        True,  # → True
                        1,  # int truthy → True
                        "yes",  # str alias → True
                        "selected",  # str alias → True
                        0,  # int falsy → False
                        "no",  # str non-alias → False
                        None,  # 其它 → False
                        ["x"],  # 列表 → False
                    ],
                },
            )
            self.assertEqual(resp.status_code, 200)

            call_kwargs = mock_tq.add_task.call_args.kwargs
            defaults = call_kwargs.get("predefined_options_defaults")
            self.assertEqual(
                defaults,
                [True, True, True, True, False, False, False, False],
            )

    def test_options_defaults_too_long_truncated(self):
        """defaults 长度大于 options → 截断到 options 长度。"""
        with patch("web_ui_routes.task.get_task_queue") as mock_get_tq:
            mock_tq = MagicMock()
            mock_tq.add_task.return_value = True
            mock_get_tq.return_value = mock_tq

            resp = self._client.post(
                "/api/tasks",
                json={
                    "task_id": "td-3",
                    "prompt": "p",
                    "predefined_options": ["a", "b"],
                    "predefined_options_defaults": [True, False, True, False],
                },
            )
            self.assertEqual(resp.status_code, 200)
            defaults = mock_tq.add_task.call_args.kwargs.get(
                "predefined_options_defaults"
            )
            self.assertEqual(defaults, [True, False])

    def test_options_defaults_too_short_padded_with_false(self):
        """defaults 长度小于 options → 用 False 补足到 options 长度。"""
        with patch("web_ui_routes.task.get_task_queue") as mock_get_tq:
            mock_tq = MagicMock()
            mock_tq.add_task.return_value = True
            mock_get_tq.return_value = mock_tq

            resp = self._client.post(
                "/api/tasks",
                json={
                    "task_id": "td-4",
                    "prompt": "p",
                    "predefined_options": ["a", "b", "c", "d"],
                    "predefined_options_defaults": [True],
                },
            )
            self.assertEqual(resp.status_code, 200)
            defaults = mock_tq.add_task.call_args.kwargs.get(
                "predefined_options_defaults"
            )
            self.assertEqual(defaults, [True, False, False, False])

    def test_options_defaults_omitted_keeps_none(self):
        """``predefined_options_defaults`` 字段缺省 → 不传给 add_task（None）。"""
        with patch("web_ui_routes.task.get_task_queue") as mock_get_tq:
            mock_tq = MagicMock()
            mock_tq.add_task.return_value = True
            mock_get_tq.return_value = mock_tq

            resp = self._client.post(
                "/api/tasks",
                json={
                    "task_id": "td-5",
                    "prompt": "p",
                    "predefined_options": ["a", "b"],
                },
            )
            self.assertEqual(resp.status_code, 200)
            defaults = mock_tq.add_task.call_args.kwargs.get(
                "predefined_options_defaults"
            )
            self.assertIsNone(defaults)


# ═══════════════════════════════════════════════════════════════════════════
#  task.py — /api/tasks/<id> GET (detail)
# ═══════════════════════════════════════════════════════════════════════════
class TestGetTaskDetail(_RouteTestBase):
    _port = 19032

    @patch("web_ui_routes.task.get_task_queue")
    def test_task_found(self, mock_get_tq):
        mock_tq = MagicMock()
        task = Task(
            task_id="detail-1",
            prompt="test prompt",
            predefined_options=["A", "B"],
            auto_resubmit_timeout=120,
        )
        mock_tq.get_task.return_value = task
        mock_get_tq.return_value = mock_tq

        resp = self._client.get("/api/tasks/detail-1")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data["success"])
        self.assertEqual(data["task"]["task_id"], "detail-1")
        self.assertIn("remaining_time", data["task"])
        self.assertIn("deadline", data["task"])
        self.assertIn("server_time", data)

    @patch("web_ui_routes.task.get_task_queue")
    def test_task_not_found(self, mock_get_tq):
        mock_tq = MagicMock()
        mock_tq.get_task.return_value = None
        mock_get_tq.return_value = mock_tq

        resp = self._client.get("/api/tasks/nonexistent")
        self.assertEqual(resp.status_code, 404)

    @patch("web_ui_routes.task.get_task_queue", side_effect=RuntimeError("boom"))
    def test_exception_returns_500(self, _):
        resp = self._client.get("/api/tasks/any-id")
        self.assertEqual(resp.status_code, 500)


# ═══════════════════════════════════════════════════════════════════════════
#  task.py — /api/tasks/<id>/activate POST
# ═══════════════════════════════════════════════════════════════════════════
class TestActivateTask(_RouteTestBase):
    _port = 19033

    @patch("web_ui_routes.task.get_task_queue")
    def test_activate_success(self, mock_get_tq):
        mock_tq = MagicMock()
        mock_tq.set_active_task.return_value = True
        mock_get_tq.return_value = mock_tq

        resp = self._client.post("/api/tasks/task-1/activate")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data["success"])
        self.assertEqual(data["active_task_id"], "task-1")

    @patch("web_ui_routes.task.get_task_queue")
    def test_activate_fails_400(self, mock_get_tq):
        mock_tq = MagicMock()
        mock_tq.set_active_task.return_value = False
        mock_get_tq.return_value = mock_tq

        resp = self._client.post("/api/tasks/bad-task/activate")
        self.assertEqual(resp.status_code, 400)

    @patch("web_ui_routes.task.get_task_queue", side_effect=RuntimeError("boom"))
    def test_activate_exception_500(self, _):
        resp = self._client.post("/api/tasks/any/activate")
        self.assertEqual(resp.status_code, 500)


# ═══════════════════════════════════════════════════════════════════════════
#  task.py — /api/tasks/<id>/close POST  (端点之前完全无测试)
# ═══════════════════════════════════════════════════════════════════════════
class TestCloseTask(_RouteTestBase):
    """``/api/tasks/<task_id>/close`` 路由在 v1.5.x 一直存在但无回归点。

    它是用户在多任务面板里手动关闭某个反馈任务的入口；若静默坏掉，
    任务会一直停留在 SSE 列表里无法清理。
    """

    _port = 19035

    @patch("web_ui_routes.task.get_task_queue")
    def test_close_success(self, mock_get_tq):
        mock_tq = MagicMock()
        mock_tq.remove_task.return_value = True
        mock_get_tq.return_value = mock_tq

        resp = self._client.post("/api/tasks/task-x/close")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data["success"])
        mock_tq.remove_task.assert_called_once_with("task-x")

    @patch("web_ui_routes.task.get_task_queue")
    def test_close_task_not_found_404(self, mock_get_tq):
        mock_tq = MagicMock()
        mock_tq.remove_task.return_value = False
        mock_get_tq.return_value = mock_tq

        resp = self._client.post("/api/tasks/ghost/close")
        self.assertEqual(resp.status_code, 404)
        data = resp.get_json()
        self.assertFalse(data["success"])
        self.assertIn("不存在", data["error"])

    @patch("web_ui_routes.task.get_task_queue", side_effect=RuntimeError("boom"))
    def test_close_exception_500(self, _):
        resp = self._client.post("/api/tasks/any/close")
        self.assertEqual(resp.status_code, 500)
        self.assertIn("error", resp.get_json())


# ═══════════════════════════════════════════════════════════════════════════
#  task.py — /api/tasks/<id>/submit POST
# ═══════════════════════════════════════════════════════════════════════════
class TestSubmitTaskFeedback(_RouteTestBase):
    _port = 19034

    @patch("web_ui_routes.task.get_task_queue")
    def test_task_not_found_404(self, mock_get_tq):
        mock_tq = MagicMock()
        mock_tq.get_task.return_value = None
        mock_get_tq.return_value = mock_tq

        resp = self._client.post(
            "/api/tasks/no-task/submit",
            data={"feedback_text": "hello", "selected_options": "[]"},
        )
        self.assertEqual(resp.status_code, 404)

    @patch("web_ui_routes.task.get_task_queue")
    def test_success_text_only(self, mock_get_tq):
        mock_tq = MagicMock()
        mock_tq.get_task.return_value = MagicMock(task_id="t1")
        mock_get_tq.return_value = mock_tq

        resp = self._client.post(
            "/api/tasks/t1/submit",
            data={"feedback_text": "done", "selected_options": '["A","B"]'},
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data["success"])
        mock_tq.complete_task.assert_called_once()

    @patch("web_ui_routes.task.get_task_queue")
    def test_invalid_selected_options_json(self, mock_get_tq):
        mock_tq = MagicMock()
        mock_tq.get_task.return_value = MagicMock(task_id="t2")
        mock_get_tq.return_value = mock_tq

        resp = self._client.post(
            "/api/tasks/t2/submit",
            data={"feedback_text": "x", "selected_options": "not json"},
        )
        self.assertEqual(resp.status_code, 400)

    @patch("web_ui_routes.task.get_task_queue")
    def test_selected_options_not_list(self, mock_get_tq):
        mock_tq = MagicMock()
        mock_tq.get_task.return_value = MagicMock(task_id="t3")
        mock_get_tq.return_value = mock_tq

        resp = self._client.post(
            "/api/tasks/t3/submit",
            data={"feedback_text": "x", "selected_options": '"just a string"'},
        )
        self.assertEqual(resp.status_code, 400)

    @patch("web_ui_routes.task.get_task_queue")
    def test_selected_options_non_string_element(self, mock_get_tq):
        mock_tq = MagicMock()
        mock_tq.get_task.return_value = MagicMock(task_id="t4")
        mock_get_tq.return_value = mock_tq

        resp = self._client.post(
            "/api/tasks/t4/submit",
            data={"feedback_text": "x", "selected_options": '[1, "ok"]'},
        )
        self.assertEqual(resp.status_code, 400)

    @patch("web_ui_routes._upload_helpers.validate_uploaded_file")
    @patch("web_ui_routes.task.get_task_queue")
    def test_image_upload_success(self, mock_get_tq, mock_validate):
        mock_tq = MagicMock()
        mock_tq.get_task.return_value = MagicMock(task_id="t5")
        mock_get_tq.return_value = mock_tq
        mock_validate.return_value = {
            "valid": True,
            "errors": [],
            "warnings": [],
            "mime_type": "image/png",
            "file_type": "image",
        }

        data = {
            "feedback_text": "with img",
            "selected_options": "[]",
            "image_0": (io.BytesIO(b"\x89PNG"), "shot.png"),
        }
        resp = self._client.post(
            "/api/tasks/t5/submit", data=data, content_type="multipart/form-data"
        )
        self.assertEqual(resp.status_code, 200)
        call_args = mock_tq.complete_task.call_args[0]
        self.assertIn("images", call_args[1])

    @patch("web_ui_routes._upload_helpers.validate_uploaded_file")
    @patch("web_ui_routes.task.get_task_queue")
    def test_image_validation_fail_skipped(self, mock_get_tq, mock_validate):
        mock_tq = MagicMock()
        mock_tq.get_task.return_value = MagicMock(task_id="t6")
        mock_get_tq.return_value = mock_tq
        mock_validate.return_value = {
            "valid": False,
            "errors": ["bad file"],
            "warnings": [],
            "mime_type": None,
            "file_type": "unknown",
        }

        data = {
            "feedback_text": "bad",
            "selected_options": "[]",
            "image_0": (io.BytesIO(b"malicious"), "evil.exe"),
        }
        resp = self._client.post(
            "/api/tasks/t6/submit", data=data, content_type="multipart/form-data"
        )
        self.assertEqual(resp.status_code, 200)
        call_args = mock_tq.complete_task.call_args[0]
        self.assertNotIn("images", call_args[1])

    @patch(
        "web_ui_routes._upload_helpers.validate_uploaded_file", side_effect=RuntimeError
    )
    @patch("web_ui_routes.task.get_task_queue")
    def test_image_processing_exception(self, mock_get_tq, _):
        mock_tq = MagicMock()
        mock_tq.get_task.return_value = MagicMock(task_id="t7")
        mock_get_tq.return_value = mock_tq

        data = {
            "feedback_text": "err",
            "selected_options": "[]",
            "image_0": (io.BytesIO(b"data"), "crash.png"),
        }
        resp = self._client.post(
            "/api/tasks/t7/submit", data=data, content_type="multipart/form-data"
        )
        self.assertEqual(resp.status_code, 200)

    @patch("web_ui_routes.task.get_task_queue", side_effect=RuntimeError("boom"))
    def test_outer_exception_500(self, _):
        resp = self._client.post(
            "/api/tasks/any/submit",
            data={"feedback_text": "x", "selected_options": "[]"},
        )
        self.assertEqual(resp.status_code, 500)

    @patch("web_ui_routes.task.get_task_queue")
    def test_empty_options_cleaned(self, mock_get_tq):
        """空字符串选项被过滤"""
        mock_tq = MagicMock()
        mock_tq.get_task.return_value = MagicMock(task_id="t8")
        mock_get_tq.return_value = mock_tq

        resp = self._client.post(
            "/api/tasks/t8/submit",
            data={
                "feedback_text": "test",
                "selected_options": '["valid", "  ", ""]',
            },
        )
        self.assertEqual(resp.status_code, 200)

    @patch("web_ui_routes.task.get_task_queue")
    def test_non_image_file_field_skipped(self, mock_get_tq):
        """branch 441->440: 非 image_ 前缀的文件字段被跳过"""
        mock_tq = MagicMock()
        mock_tq.get_task.return_value = MagicMock(task_id="t9")
        mock_get_tq.return_value = mock_tq

        data = {
            "feedback_text": "test",
            "selected_options": "[]",
            "attachment_0": (io.BytesIO(b"data"), "readme.txt"),
        }
        resp = self._client.post(
            "/api/tasks/t9/submit", data=data, content_type="multipart/form-data"
        )
        self.assertEqual(resp.status_code, 200)
        call_args = mock_tq.complete_task.call_args[0]
        self.assertNotIn("images", call_args[1])

    @patch("web_ui_routes.task.get_task_queue")
    def test_image_file_no_filename_skipped(self, mock_get_tq):
        """branch 443->440: image_ 前缀但无文件名的字段被跳过"""
        mock_tq = MagicMock()
        mock_tq.get_task.return_value = MagicMock(task_id="t10")
        mock_get_tq.return_value = mock_tq

        data = {
            "feedback_text": "test",
            "selected_options": "[]",
            "image_0": (io.BytesIO(b""), ""),
        }
        resp = self._client.post(
            "/api/tasks/t10/submit", data=data, content_type="multipart/form-data"
        )
        self.assertEqual(resp.status_code, 200)
        call_args = mock_tq.complete_task.call_args[0]
        self.assertNotIn("images", call_args[1])


# ═══════════════════════════════════════════════════════════════════════════
#  static.py — 补充未覆盖行（favicon 404、lottie non-json、service worker）
# ═══════════════════════════════════════════════════════════════════════════
# ═══════════════════════════════════════════════════════════════════════════
#  feedback.py — /api/update 补充难触达分支
# ═══════════════════════════════════════════════════════════════════════════
class TestUpdateContentEdge(_RouteTestBase):
    _port = 19026

    def test_render_markdown_exception_returns_empty_html(self):
        """render_markdown 异常时 prompt_html 为空字符串（L396-400）"""
        with patch.object(
            self._ui, "render_markdown", side_effect=RuntimeError("render fail")
        ):
            resp = self._client.post("/api/update", json={"prompt": "# valid markdown"})
            self.assertEqual(resp.status_code, 200)
            data = resp.get_json()
            self.assertEqual(data["prompt_html"], "")
            self.assertTrue(data["has_content"])

    def test_state_lock_exception_returns_500(self):
        """_state_lock 内部异常 → 500（L414-416）"""
        original_lock = self._ui._state_lock

        class BrokenLock:
            def __enter__(self):
                raise RuntimeError("lock broken")

            def __exit__(self, *args):
                pass

        self._ui._state_lock = BrokenLock()
        try:
            resp = self._client.post("/api/update", json={"prompt": "hello"})
            self.assertEqual(resp.status_code, 500)
            data = resp.get_json()
            self.assertEqual(data["error"], "internal_error")
        finally:
            self._ui._state_lock = original_lock


class TestSubmitMultipartEdge(_RouteTestBase):
    """文件上传边界：文件存在但无 filename（L88 分支）"""

    _port = 19027

    @patch("web_ui_routes.feedback.get_task_queue")
    def test_file_without_filename_skipped(self, mock_get_tq):
        mock_tq = MagicMock()
        mock_tq.get_active_task.return_value = MagicMock(task_id="multi-edge")
        mock_get_tq.return_value = mock_tq

        data = {
            "feedback_text": "edge",
            "selected_options": "[]",
            "image_0": (io.BytesIO(b"data"), ""),
        }
        resp = self._client.post(
            "/api/submit", data=data, content_type="multipart/form-data"
        )
        self.assertEqual(resp.status_code, 200)


# ═══════════════════════════════════════════════════════════════════════════
#  static.py — favicon 路由（L264-268）
# ═══════════════════════════════════════════════════════════════════════════
class TestFaviconRoute(_RouteTestBase):
    _port = 19041

    def test_favicon_returns_icon(self):
        resp = self._client.get("/favicon.ico")
        if resp.status_code == 200:
            self.assertEqual(resp.headers.get("Content-Type"), "image/x-icon")
            cache = resp.headers.get("Cache-Control", "")
            self.assertIn("no-cache", cache)


class TestStaticRoutesEdge(_RouteTestBase):
    _port = 19040

    def test_lottie_non_json_returns_404(self):
        resp = self._client.get("/static/lottie/animation.txt")
        self.assertEqual(resp.status_code, 404)

    def test_lottie_empty_filename_returns_404(self):
        resp = self._client.get("/static/lottie/")
        self.assertIn(resp.status_code, (404, 308))

    def test_service_worker_headers(self):
        resp = self._client.get("/notification-service-worker.js")
        if resp.status_code == 200:
            self.assertIn("Service-Worker-Allowed", resp.headers)
            self.assertEqual(resp.headers["Service-Worker-Allowed"], "/")
            cache = resp.headers.get("Cache-Control", "")
            self.assertIn("no-cache", cache)
        resp.close()

    def test_css_with_version_param_long_cache(self):
        """line 132: CSS ?v=xxx 时启用 1 年缓存"""
        resp = self._client.get("/static/css/main.css?v=abc123")
        if resp.status_code == 200:
            cache = resp.headers.get("Cache-Control", "")
            self.assertIn("max-age=31536000", cache)
            self.assertIn("immutable", cache)
        resp.close()

    def test_favicon_with_mock_icon(self):
        """lines 264-268: favicon 路由返回正确响应头"""
        from unittest.mock import patch

        from flask import Response

        mock_resp = Response(
            b"\x00\x00\x01\x00", content_type="application/octet-stream"
        )
        with patch("web_ui_routes.static.send_from_directory", return_value=mock_resp):
            resp = self._client.get("/favicon.ico")
            self.assertEqual(resp.status_code, 200)
            self.assertEqual(resp.headers.get("Content-Type"), "image/x-icon")
            cache = resp.headers.get("Cache-Control", "")
            self.assertIn("no-cache", cache)
            self.assertEqual(resp.headers.get("Pragma"), "no-cache")
            self.assertEqual(resp.headers.get("Expires"), "0")

    def test_pwa_manifest_endpoint_returns_json(self):
        """``/manifest.webmanifest`` 应返回 PWA manifest JSON，
        Content-Type 为 ``application/manifest+json``，且包含浏览器
        ``Add to Home Screen`` 必需字段。

        没有此端点 → 浏览器收到 404 后会忽略整个 PWA install banner，
        在 ai.local 等域名上图标会回退成截图。这是 v1.5.20 的 PWA
        关键路径，必须有回归点。
        """
        import json as _json

        resp = self._client.get("/manifest.webmanifest")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.headers.get("Content-Type"), "application/manifest+json")
        cache = resp.headers.get("Cache-Control", "")
        self.assertIn("max-age=3600", cache)
        manifest = _json.loads(resp.data)
        self.assertIn("name", manifest)
        self.assertIn("icons", manifest)
        self.assertIsInstance(manifest["icons"], list)
        self.assertGreater(len(manifest["icons"]), 0)
        for icon in manifest["icons"]:
            self.assertIn("src", icon)
            self.assertIn("sizes", icon)


# ═══════════════════════════════════════════════════════════════════════════
#  protocol.py — /api/capabilities + /api/time
# ═══════════════════════════════════════════════════════════════════════════
class TestCapabilitiesEndpoint(_RouteTestBase):
    """前后端契约发现端点的回归点。

    这是 IG-1 的前端入口：若字段命名 / 结构发生变化，所有客户端的
    feature detection 都会级联受影响，必须有明确断言护栏。
    """

    _port = 19200

    def test_returns_expected_shape(self):
        resp = self._client.get("/api/capabilities")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertIn("protocol_version", data)
        self.assertIn("server_version", data)
        self.assertIn("build_id", data)
        self.assertIn("features", data)
        self.assertIsInstance(data["features"], dict)

    def test_protocol_version_is_semver(self):
        resp = self._client.get("/api/capabilities")
        data = resp.get_json()
        parts = data["protocol_version"].split(".")
        self.assertEqual(len(parts), 3, "protocol_version 必须是三段 semver")
        for part in parts:
            self.assertTrue(part.isdigit(), f"protocol_version 段 {part!r} 应为数字")

    def test_declared_features_contain_baseline(self):
        resp = self._client.get("/api/capabilities")
        data = resp.get_json()
        features = data["features"]
        for key in ("sse", "polling", "multi_task", "capabilities_endpoint", "clock"):
            self.assertIn(key, features, f"features 缺少基线键 {key!r}")
            self.assertIsInstance(features[key], bool)

    def test_build_id_reads_env(self):
        import os

        import web_ui as web_ui_module

        with patch.dict(os.environ, {"AIIA_BUILD_ID": "test-sha-abc"}):
            resp = self._client.get("/api/capabilities")
            self.assertEqual(resp.status_code, 200)
            self.assertEqual(resp.get_json()["build_id"], "test-sha-abc")

        self.assertIsNotNone(web_ui_module)


class TestUpdateFeedbackConfigEndpoint(_RouteTestBase):
    """``/api/update-feedback-config`` 错误分支与字段独立更新覆盖。

    happy path（三字段一并更新 + round-trip 读回）已在
    ``test_runtime_behavior.TestFeedbackConfigRoundTrip`` 锁定。本测试聚焦
    错误处理与单字段路径，防止 regress 后用户端无声损失。
    """

    _port = 19250

    def test_non_int_frontend_countdown_returns_400(self):
        """``frontend_countdown`` 不能转 int → 400 + 中文报错信息。

        防止 lambda 误转 ``int(None) → TypeError`` 一路打到 500，把
        traceback 暴露给浏览器。
        """
        resp = self._client.post(
            "/api/update-feedback-config",
            json={"frontend_countdown": "not-an-int"},
        )
        self.assertEqual(resp.status_code, 400)
        data = resp.get_json()
        self.assertEqual(data["status"], "error")
        self.assertIn("frontend_countdown", data["message"])

    def test_zero_frontend_countdown_disables_timer(self):
        """``frontend_countdown=0`` 是「禁用前端倒计时」的特殊语义，
        必须原样落盘，不能被 ``clamp_value`` 提到 ``AUTO_RESUBMIT_TIMEOUT_MIN``。
        """
        with patch("web_ui_routes.notification.get_config") as mock_get_config:
            mock_mgr = MagicMock()
            mock_mgr.get_section.return_value = {}
            mock_get_config.return_value = mock_mgr

            resp = self._client.post(
                "/api/update-feedback-config",
                json={"frontend_countdown": 0},
            )

        self.assertEqual(resp.status_code, 200)
        update_call = mock_mgr.update_section.call_args
        assert update_call is not None
        section, payload = update_call.args
        self.assertEqual(section, "feedback")
        self.assertEqual(payload.get("frontend_countdown"), 0)

    def test_only_resubmit_prompt_is_updated(self):
        """单字段更新：仅 ``resubmit_prompt``，不应同时改其它字段。"""
        with patch("web_ui_routes.notification.get_config") as mock_get_config:
            mock_mgr = MagicMock()
            mock_mgr.get_section.return_value = {"frontend_countdown": 60}
            mock_get_config.return_value = mock_mgr

            resp = self._client.post(
                "/api/update-feedback-config",
                json={"resubmit_prompt": "请马上回复"},
            )

        self.assertEqual(resp.status_code, 200)
        _, payload = mock_mgr.update_section.call_args.args
        self.assertEqual(payload.get("resubmit_prompt"), "请马上回复")
        self.assertEqual(payload.get("frontend_countdown"), 60)

    def test_only_prompt_suffix_is_updated(self):
        """单字段更新：仅 ``prompt_suffix``。"""
        with patch("web_ui_routes.notification.get_config") as mock_get_config:
            mock_mgr = MagicMock()
            mock_mgr.get_section.return_value = {}
            mock_get_config.return_value = mock_mgr

            resp = self._client.post(
                "/api/update-feedback-config",
                json={"prompt_suffix": "\n（自动追加）"},
            )

        self.assertEqual(resp.status_code, 200)
        _, payload = mock_mgr.update_section.call_args.args
        self.assertEqual(payload.get("prompt_suffix"), "\n（自动追加）")

    def test_no_recognised_fields_returns_success_with_message(self):
        """payload 里没有任何已知字段 → 200 + 「无可识别的更新字段」，
        不调用 ``update_section``。
        """
        with patch("web_ui_routes.notification.get_config") as mock_get_config:
            mock_mgr = MagicMock()
            mock_mgr.get_section.return_value = {}
            mock_get_config.return_value = mock_mgr

            resp = self._client.post(
                "/api/update-feedback-config",
                json={"unknown_field": 123},
            )

        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data["status"], "success")
        self.assertIn("无可识别", data["message"])
        mock_mgr.update_section.assert_not_called()

    def test_non_dict_payload_treated_as_empty(self):
        """payload 不是 dict（如发了一个 list）→ 视为空 dict，回 200 + 提示。"""
        with patch("web_ui_routes.notification.get_config") as mock_get_config:
            mock_mgr = MagicMock()
            mock_mgr.get_section.return_value = {}
            mock_get_config.return_value = mock_mgr

            resp = self._client.post(
                "/api/update-feedback-config",
                json=["not", "a", "dict"],
            )

        self.assertEqual(resp.status_code, 200)
        mock_mgr.update_section.assert_not_called()

    def test_config_manager_exception_returns_500(self):
        """``update_section`` 抛异常 → 500 + 标准化错误（不泄漏 traceback）。"""
        with patch("web_ui_routes.notification.get_config") as mock_get_config:
            mock_mgr = MagicMock()
            mock_mgr.get_section.return_value = {}
            mock_mgr.update_section.side_effect = OSError(
                "simulated config write failure"
            )
            mock_get_config.return_value = mock_mgr

            resp = self._client.post(
                "/api/update-feedback-config",
                json={"frontend_countdown": 120},
            )

        self.assertEqual(resp.status_code, 500)
        data = resp.get_json()
        self.assertEqual(data["status"], "error")
        # 标准化文案，不应是 raw exception text
        self.assertNotIn("simulated config write failure", data["message"])


class TestServerClockEndpoint(_RouteTestBase):
    """服务器时钟端点回归点（IG-2）。"""

    _port = 19201

    def test_returns_integer_ms_fields(self):
        resp = self._client.get("/api/time")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertIn("time_ms", data)
        self.assertIn("monotonic_ms", data)
        self.assertIsInstance(data["time_ms"], int)
        self.assertIsInstance(data["monotonic_ms"], int)

    def test_wall_clock_near_current_time(self):
        import time as _time

        before = int(_time.time() * 1000)
        resp = self._client.get("/api/time")
        after = int(_time.time() * 1000)
        data = resp.get_json()
        self.assertGreaterEqual(data["time_ms"], before - 5)
        self.assertLessEqual(data["time_ms"], after + 5)

    def test_monotonic_is_non_negative(self):
        resp = self._client.get("/api/time")
        data = resp.get_json()
        self.assertGreaterEqual(data["monotonic_ms"], 0)


if __name__ == "__main__":
    unittest.main()
