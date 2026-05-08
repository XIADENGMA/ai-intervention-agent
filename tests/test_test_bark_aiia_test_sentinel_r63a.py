"""R63a — Bark 测试通知 ``aiia_test=1`` sentinel 端到端契约。

为什么需要这层锁
================

历史 ``/api/test-bark`` 路径里硬编码 ``"task_id": "test-task-id"`` 作为
metadata 占位符。配合默认 ``bark_url_template = "{base_url}/?task_id={task_id}"``
渲染出的点击 URL 是 ``https://your.host/?task_id=test-task-id``。

用户在 PWA 端打开后：

1. ``static/js/multi_task.js::getDeepLinkedTaskIdFromUrl()`` 读出
   ``task_id=test-task-id`` → 写入 ``pendingDeepLinkedTaskId``；
2. ``tryApplyDeepLinkedTask()`` 在 ``currentTasks`` 里 ``find`` 这个虚
   假 ID 永远找不到；
3. 源码注释明说「任务可能还没从后端快照恢复出来，保留 pending，下一轮
   轮询继续尝试」—— 对真实 task 是合理的，但对 sentinel 来说就是
   ``pendingDeepLinkedTaskId`` 永久挂着、每轮 ``.find()`` 白调。

R63a 的设计：

* 后端 ``/api/test-bark`` 在传给 ``BarkNotificationProvider`` 之前给
  ``bark_url_template`` 末尾自动追加 ``aiia_test=1`` query
  （已有 ``aiia_test=`` 的不重复加，幂等）；
* 前端 ``getDeepLinkedTaskIdFromUrl`` 识别 ``aiia_test=1`` /
  ``aiia_test=true`` / ``aiia_test=yes``（大小写不敏感、自动 trim）后
  跳过 deep-link 路径并 toast 提示「Bark test notification opened —
  UI is working.」。

这一层只是「不再让测试通知制造死链路」的回归契约，运行时 bark provider
不依赖这个 query；用户的真实 ``bark_url_template`` 配置完全不受影响
（只在 ``/api/test-bark`` 路径里插入）。
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


class _RouteTestBase(unittest.TestCase):
    """共享基类：启动一个最小 WebFeedbackUI + Flask test client。

    对齐 ``tests/test_web_ui_routes.py::_RouteTestBase`` 的实现，避免
    多端起 server 引入额外副作用。
    """

    _port: int = 19090
    _ui: Any = None
    _client: Any = None

    @classmethod
    def setUpClass(cls) -> None:
        from web_ui import WebFeedbackUI

        cls._ui = WebFeedbackUI(
            prompt="bark sentinel test", task_id="rt-r63a", port=cls._port
        )
        cls._ui.app.config["TESTING"] = True
        cls._ui.limiter.enabled = False
        cls._client = cls._ui.app.test_client()


class TestTestBarkUrlTemplateAppendsSentinel(_RouteTestBase):
    """``/api/test-bark`` 给 ``bark_url_template`` 末尾自动追加 ``aiia_test=1``。"""

    @patch("web_ui_routes.notification.NOTIFICATION_AVAILABLE", True)
    @patch("web_ui_routes.notification.BarkNotificationProvider")
    @patch("web_ui_routes.notification.NotificationEvent")
    def test_default_template_gets_sentinel_query_appended(
        self, _mock_event_cls, mock_provider_cls
    ):
        mock_provider = MagicMock()
        mock_provider.send.return_value = True
        mock_provider_cls.return_value = mock_provider

        resp = self._client.post(
            "/api/test-bark",
            json={
                "bark_device_key": "k",
                "bark_url": "https://bark.test/push",
                "bark_action": "url",
                "bark_url_template": "{base_url}/?task_id={task_id}",
            },
        )
        self.assertEqual(resp.status_code, 200)

        temp_config = mock_provider_cls.call_args.args[0]
        self.assertTrue(
            temp_config.bark_url_template.endswith("aiia_test=1"),
            f"bark_url_template 末尾必须有 aiia_test=1 sentinel，"
            f"实际：{temp_config.bark_url_template!r}",
        )
        self.assertIn("?", temp_config.bark_url_template)

    @patch("web_ui_routes.notification.NOTIFICATION_AVAILABLE", True)
    @patch("web_ui_routes.notification.BarkNotificationProvider")
    @patch("web_ui_routes.notification.NotificationEvent")
    def test_template_without_query_string_uses_question_mark(
        self, _mock_event_cls, mock_provider_cls
    ):
        mock_provider = MagicMock()
        mock_provider.send.return_value = True
        mock_provider_cls.return_value = mock_provider

        # 模板里完全没有 ``?`` —— sentinel 必须用 ``?`` 起头，不要写成 ``&``
        resp = self._client.post(
            "/api/test-bark",
            json={
                "bark_device_key": "k",
                "bark_url": "https://bark.test/push",
                "bark_action": "url",
                "bark_url_template": "{base_url}/tasks",
            },
        )
        self.assertEqual(resp.status_code, 200)

        temp_config = mock_provider_cls.call_args.args[0]
        self.assertTrue(
            temp_config.bark_url_template.endswith("?aiia_test=1"),
            f"无 query 的模板必须用 ``?`` 起头加 sentinel，"
            f"实际：{temp_config.bark_url_template!r}",
        )

    @patch("web_ui_routes.notification.NOTIFICATION_AVAILABLE", True)
    @patch("web_ui_routes.notification.BarkNotificationProvider")
    @patch("web_ui_routes.notification.NotificationEvent")
    def test_idempotent_when_template_already_has_sentinel(
        self, _mock_event_cls, mock_provider_cls
    ):
        mock_provider = MagicMock()
        mock_provider.send.return_value = True
        mock_provider_cls.return_value = mock_provider

        # 用户已经手动写了 aiia_test —— 不要重复加
        resp = self._client.post(
            "/api/test-bark",
            json={
                "bark_device_key": "k",
                "bark_url": "https://bark.test/push",
                "bark_action": "url",
                "bark_url_template": "{base_url}/?aiia_test=1&task_id={task_id}",
            },
        )
        self.assertEqual(resp.status_code, 200)

        temp_config = mock_provider_cls.call_args.args[0]
        self.assertEqual(
            temp_config.bark_url_template.count("aiia_test="),
            1,
            f"sentinel 必须幂等，实际：{temp_config.bark_url_template!r}",
        )

    @patch("web_ui_routes.notification.NOTIFICATION_AVAILABLE", True)
    @patch("web_ui_routes.notification.BarkNotificationProvider")
    @patch("web_ui_routes.notification.NotificationEvent")
    def test_empty_template_does_not_get_sentinel(
        self, _mock_event_cls, mock_provider_cls
    ):
        mock_provider = MagicMock()
        mock_provider.send.return_value = True
        mock_provider_cls.return_value = mock_provider

        # 空模板 —— sentinel 不应在空字符串上凭空冒出来
        resp = self._client.post(
            "/api/test-bark",
            json={
                "bark_device_key": "k",
                "bark_url": "https://bark.test/push",
                "bark_action": "url",
                "bark_url_template": "",
            },
        )
        self.assertEqual(resp.status_code, 200)

        temp_config = mock_provider_cls.call_args.args[0]
        self.assertEqual(
            temp_config.bark_url_template,
            "",
            "空模板不应被注入 sentinel——空 URL 走 default URL 路径，不需要 aiia_test",
        )


class TestFrontendDeepLinkSkipsAiiaTestSentinel(unittest.TestCase):
    """``static/js/multi_task.js::getDeepLinkedTaskIdFromUrl`` 必须识别 sentinel。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.multi_task = (REPO_ROOT / "static" / "js" / "multi_task.js").read_text(
            encoding="utf-8"
        )

    def test_function_checks_aiia_test_query(self) -> None:
        """getDeepLinkedTaskIdFromUrl 必须读取 aiia_test query。"""
        self.assertIn(
            'params.get("aiia_test")',
            self.multi_task,
            "getDeepLinkedTaskIdFromUrl 必须显式读取 aiia_test query 才能识别 sentinel",
        )

    def test_function_returns_empty_when_aiia_test_truthy(self) -> None:
        """识别到 truthy aiia_test 时函数应早返回（避免后续 task_id 被采纳）。"""
        # 提取 getDeepLinkedTaskIdFromUrl 函数体；取首个 ``"1"`` 比较行
        # 锁住「sentinel 先于 task_id 检查」这个不变量
        idx = self.multi_task.index("function getDeepLinkedTaskIdFromUrl")
        body = self.multi_task[idx : idx + 1500]
        # 既检查值匹配 1 / "1"，也确认 task_id 读取在 sentinel 之后
        sentinel_pos = body.find("aiia_test")
        task_id_pos = body.find('params.get("task_id")')
        self.assertGreater(
            sentinel_pos,
            -1,
            "函数体必须有 aiia_test sentinel 检查",
        )
        self.assertGreater(
            task_id_pos,
            sentinel_pos,
            "sentinel 检查必须在 task_id 读取之前，否则 sentinel 命中也会先填入 pendingDeepLinkedTaskId",
        )

    def test_function_emits_toast_for_sentinel(self) -> None:
        """识别 sentinel 后必须 toast 通知用户「测试通知已工作」，避免静默无反馈。"""
        idx = self.multi_task.index("function getDeepLinkedTaskIdFromUrl")
        body = self.multi_task[idx : idx + 1500]
        self.assertIn(
            "_showToast",
            body,
            "sentinel 命中分支必须 toast 提示，不应静默；用户期望「点了通知有反馈」",
        )

    def test_documentation_mentions_aiia_test(self) -> None:
        """函数 JSDoc 必须说明 aiia_test 来源 + 用途，便于后续改动者理解契约。"""
        idx = self.multi_task.index("function getDeepLinkedTaskIdFromUrl")
        # JSDoc 在函数定义之前——往前抓 800 字符
        head = self.multi_task[max(0, idx - 800) : idx]
        self.assertIn(
            "aiia_test",
            head,
            "JSDoc 必须解释 aiia_test sentinel 的设计意图，否则后续重构容易丢",
        )


if __name__ == "__main__":
    unittest.main()
