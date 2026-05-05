"""
AI Intervention Agent - 通知提供者单元测试

测试覆盖：
1. WebNotificationProvider - Web 浏览器通知
2. SoundNotificationProvider - 声音通知
3. BarkNotificationProvider - Bark 推送通知
4. SystemNotificationProvider - 系统通知
"""

import unittest
from typing import Any, cast
from unittest.mock import MagicMock, patch

from notification_manager import (
    NotificationConfig,
    NotificationEvent,
    NotificationTrigger,
)


def create_event(title="测试", message="消息", metadata=None):
    """创建测试用通知事件"""
    return NotificationEvent(
        id=f"test-{id(title)}",
        title=title,
        message=message,
        trigger=NotificationTrigger.IMMEDIATE,
        metadata=metadata or {},
    )


class TestWebNotificationProvider(unittest.TestCase):
    """测试 Web 通知提供者"""

    def setUp(self):
        """每个测试前的准备"""
        from notification_providers import WebNotificationProvider

        self.config = NotificationConfig()
        self.config.web_enabled = True
        self.config.web_icon = "/icons/icon.svg"
        self.config.web_timeout = 5000
        self.config.web_permission_auto_request = True
        self.config.mobile_optimized = True
        self.config.mobile_vibrate = True

        self.provider = WebNotificationProvider(self.config)

    def test_send_success(self):
        """测试成功发送通知"""
        event = create_event(title="测试标题", message="测试消息")

        result = self.provider.send(event)

        self.assertTrue(result)
        self.assertIn("web_notification_data", event.metadata)

        data = event.metadata["web_notification_data"]
        self.assertEqual(data["title"], "测试标题")
        self.assertEqual(data["message"], "测试消息")
        self.assertEqual(data["type"], "notification")

    def test_send_empty_title(self):
        """测试空标题"""
        event = create_event(title="", message="测试消息")

        result = self.provider.send(event)

        self.assertFalse(result)

    def test_send_empty_message(self):
        """测试空消息"""
        event = create_event(title="测试标题", message="")

        result = self.provider.send(event)

        self.assertFalse(result)

    def test_register_client(self):
        """测试客户端注册"""
        self.provider.register_client("client-1", {"user_agent": "test"})

        self.assertIn("client-1", self.provider.web_clients)

    def test_unregister_client(self):
        """测试客户端注销"""
        self.provider.register_client("client-1", {"user_agent": "test"})
        self.provider.unregister_client("client-1")

        self.assertNotIn("client-1", self.provider.web_clients)


class TestSoundNotificationProvider(unittest.TestCase):
    """测试声音通知提供者"""

    def setUp(self):
        """每个测试前的准备"""
        from notification_providers import SoundNotificationProvider

        self.config = NotificationConfig()
        self.config.sound_enabled = True
        self.config.sound_mute = False
        self.config.sound_volume = 0.8
        self.config.sound_file = "default"

        self.provider = SoundNotificationProvider(self.config)

    def test_send_success(self):
        """测试成功发送声音通知"""
        event = create_event()

        result = self.provider.send(event)

        self.assertTrue(result)
        self.assertIn("sound_notification_data", event.metadata)

        data = event.metadata["sound_notification_data"]
        self.assertEqual(data["type"], "sound")
        self.assertEqual(data["file"], "deng[噔].mp3")
        self.assertEqual(data["volume"], 0.8)

    def test_send_muted(self):
        """测试静音模式"""
        self.config.sound_mute = True

        event = create_event()

        result = self.provider.send(event)

        # 静音模式返回 True，但不准备数据
        self.assertTrue(result)
        self.assertNotIn("sound_notification_data", event.metadata)

    def test_volume_boundary(self):
        """测试音量边界值"""
        # 测试超出边界的音量值
        self.config.sound_volume = 1.5

        event = create_event()

        result = self.provider.send(event)

        self.assertTrue(result)
        data = event.metadata["sound_notification_data"]
        self.assertLessEqual(data["volume"], 1.0)


class TestBarkNotificationProvider(unittest.TestCase):
    """测试 Bark 通知提供者"""

    def setUp(self):
        """每个测试前的准备"""
        from notification_providers import BarkNotificationProvider

        self.config = NotificationConfig()
        self.config.bark_enabled = True
        self.config.bark_url = "https://api.day.app/push"
        self.config.bark_device_key = "test_device_key"
        self.config.bark_icon = ""
        self.config.bark_action = "none"

        self.provider = BarkNotificationProvider(self.config)

    def test_send_disabled(self):
        """测试禁用状态"""
        self.config.bark_enabled = False

        event = create_event()

        result = self.provider.send(event)

        self.assertFalse(result)

    def test_send_incomplete_config(self):
        """测试配置不完整"""
        self.config.bark_device_key = ""

        event = create_event()

        result = self.provider.send(event)

        self.assertFalse(result)

    def test_invalid_url_format(self):
        """测试无效 URL 格式"""
        self.config.bark_url = "invalid-url"

        event = create_event()

        result = self.provider.send(event)

        self.assertFalse(result)

    def test_empty_title(self):
        """测试空标题"""
        event = create_event(title="", message="消息")

        result = self.provider.send(event)

        self.assertFalse(result)

    def test_empty_message(self):
        """测试空消息"""
        event = create_event(title="标题", message="")

        result = self.provider.send(event)

        self.assertFalse(result)

    @patch("notification_providers.httpx.Client.post")
    def test_send_success(self, mock_post):
        """测试成功发送（模拟 HTTP）"""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_post.return_value = mock_response

        event = create_event(title="测试标题", message="测试消息")

        result = self.provider.send(event)

        self.assertTrue(result)
        mock_post.assert_called_once()

    @patch("notification_providers.httpx.Client.post")
    def test_send_uses_configured_timeout(self, mock_post):
        """应使用配置中的 bark_timeout 作为 httpx 超时参数"""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_post.return_value = mock_response

        self.config.bark_timeout = 3
        event = create_event(title="测试标题", message="测试消息")

        result = self.provider.send(event)

        self.assertTrue(result)
        _, kwargs = mock_post.call_args
        self.assertEqual(kwargs.get("timeout"), 3)

    @patch("notification_providers.httpx.Client.post")
    def test_payload_no_action_field_when_none(self, mock_post):
        """bark_action=none 时不应发送 action/url/copy 字段（避免服务端 4xx）"""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_post.return_value = mock_response

        self.config.bark_action = "none"
        event = create_event(title="测试标题", message="测试消息")

        result = self.provider.send(event)

        self.assertTrue(result)
        _, kwargs = mock_post.call_args
        payload = kwargs.get("json", {})
        self.assertNotIn("action", payload)
        self.assertNotIn("url", payload)
        self.assertNotIn("copy", payload)

    @patch("notification_providers.httpx.Client.post")
    def test_payload_url_field_when_action_url(self, mock_post):
        """bark_action=url 时应使用 Bark 的 url 字段"""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_post.return_value = mock_response

        self.config.bark_action = "url"
        event = create_event(
            title="测试标题",
            message="测试消息",
            metadata={"url": "https://example.com"},
        )

        result = self.provider.send(event)

        self.assertTrue(result)
        _, kwargs = mock_post.call_args
        payload = kwargs.get("json", {})
        self.assertEqual(payload.get("url"), "https://example.com")
        self.assertNotIn("action", payload)

    @patch("notification_providers.httpx.Client.post")
    def test_payload_url_template_when_action_url_without_explicit_url(self, mock_post):
        """bark_action=url 且 metadata 无显式 URL 时，使用 bark_url_template 渲染"""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_post.return_value = mock_response

        self.config.bark_action = "url"
        self.config.bark_url_template = (
            "{base_url}/?task_id={task_id}&event_id={event_id}"
        )
        event = create_event(
            title="测试标题",
            message="测试消息",
            metadata={"task_id": "task-123", "base_url": "http://ai.local:8080/"},
        )

        result = self.provider.send(event)

        self.assertTrue(result)
        _, kwargs = mock_post.call_args
        payload = kwargs.get("json", {})
        self.assertEqual(
            payload.get("url"),
            f"http://ai.local:8080/?task_id=task-123&event_id={event.id}",
        )
        self.assertNotIn("action", payload)

    @patch("notification_providers.httpx.Client.post")
    def test_payload_url_template_does_not_override_explicit_url(self, mock_post):
        """metadata 显式 URL 优先于 bark_url_template"""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_post.return_value = mock_response

        self.config.bark_action = "url"
        self.config.bark_url_template = "{base_url}/?task_id={task_id}"
        event = create_event(
            title="测试标题",
            message="测试消息",
            metadata={
                "task_id": "task-123",
                "base_url": "http://ai.local:8080",
                "url": "https://example.com/explicit",
            },
        )

        result = self.provider.send(event)

        self.assertTrue(result)
        _, kwargs = mock_post.call_args
        payload = kwargs.get("json", {})
        self.assertEqual(payload.get("url"), "https://example.com/explicit")

    @patch("notification_providers.logger.warning")
    @patch("notification_providers.httpx.Client.post")
    def test_payload_url_template_rejects_non_http_result(
        self, mock_post, _mock_warning
    ):
        """模板渲染结果不是 http(s) URL 时不发送 url 字段"""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_post.return_value = mock_response

        self.config.bark_action = "url"
        self.config.bark_url_template = "ai.local/?task_id={task_id}"
        event = create_event(
            title="测试标题",
            message="测试消息",
            metadata={"task_id": "task-123"},
        )

        result = self.provider.send(event)

        self.assertTrue(result)
        _, kwargs = mock_post.call_args
        payload = kwargs.get("json", {})
        self.assertNotIn("url", payload)

    @patch("notification_providers.httpx.Client.post")
    def test_payload_copy_field_when_action_copy(self, mock_post):
        """bark_action=copy 时应使用 Bark 的 copy 字段"""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_post.return_value = mock_response

        self.config.bark_action = "copy"
        event = create_event(title="测试标题", message="测试消息")

        result = self.provider.send(event)

        self.assertTrue(result)
        _, kwargs = mock_post.call_args
        payload = kwargs.get("json", {})
        self.assertEqual(payload.get("copy"), "测试消息")
        self.assertNotIn("action", payload)

    @patch("notification_providers.httpx.Client.post")
    def test_send_http_error(self, mock_post):
        """测试 HTTP 错误"""
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = "Internal Server Error"
        mock_post.return_value = mock_response

        event = create_event(title="测试标题", message="测试消息")

        result = self.provider.send(event)

        self.assertFalse(result)

    @patch("notification_providers.httpx.Client.post")
    def test_send_timeout(self, mock_post):
        """测试超时"""
        import httpx

        mock_post.side_effect = httpx.TimeoutException("connection timed out")

        event = create_event(title="测试标题", message="测试消息")

        result = self.provider.send(event)

        self.assertFalse(result)


class TestSystemNotificationProvider(unittest.TestCase):
    """测试系统通知提供者"""

    def setUp(self):
        """每个测试前的准备"""
        from notification_providers import SystemNotificationProvider

        self.config = NotificationConfig()
        self.config.web_timeout = 5000

        self.provider = SystemNotificationProvider(self.config)

    def test_check_support(self):
        """测试支持检查"""
        # 验证 supported 属性存在
        self.assertIsInstance(self.provider.supported, bool)

    def test_send_unsupported(self):
        """测试不支持时的行为"""
        # 如果不支持，应该返回 False
        if not self.provider.supported:
            event = create_event()

            result = self.provider.send(event)

            self.assertFalse(result)


class TestCreateNotificationProviders(unittest.TestCase):
    """通知提供者工厂函数测试"""

    def test_create_all_providers(self):
        """测试创建所有提供者"""
        from notification_manager import NotificationConfig, NotificationType
        from notification_providers import create_notification_providers

        config = NotificationConfig()
        config.web_enabled = True
        config.sound_enabled = True
        config.bark_enabled = True

        providers = create_notification_providers(config)

        self.assertIn(NotificationType.WEB, providers)
        self.assertIn(NotificationType.SOUND, providers)
        self.assertIn(NotificationType.BARK, providers)

    def test_create_disabled_providers(self):
        """测试创建禁用的提供者"""
        from notification_manager import NotificationConfig, NotificationType
        from notification_providers import create_notification_providers

        config = NotificationConfig()
        config.web_enabled = False
        config.sound_enabled = False
        config.bark_enabled = False

        providers = create_notification_providers(config)

        # 禁用的提供者不应该被创建
        self.assertNotIn(NotificationType.WEB, providers)
        self.assertNotIn(NotificationType.SOUND, providers)
        self.assertNotIn(NotificationType.BARK, providers)


class TestBarkProviderAdvanced(unittest.TestCase):
    """Bark 提供者高级测试"""

    def setUp(self):
        """每个测试前的准备"""
        from notification_manager import NotificationConfig
        from notification_providers import BarkNotificationProvider

        self.config = NotificationConfig()
        self.config.bark_enabled = True
        self.config.bark_url = "https://api.day.app/push"
        self.config.bark_device_key = "test_device_key"
        self.config.bark_icon = "https://icon.url/icon.png"
        self.config.bark_action = "https://action.url"

        self.provider = BarkNotificationProvider(self.config)

    def test_metadata_serialization(self):
        """测试元数据序列化"""
        from notification_manager import NotificationEvent, NotificationTrigger

        with patch.object(self.provider.session, "post") as mock_post:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_post.return_value = mock_response

            event = NotificationEvent(
                id="test-meta",
                title="标题",
                message="消息",
                trigger=NotificationTrigger.IMMEDIATE,
                metadata={
                    "string": "value",
                    "number": 42,
                    "list": [1, 2, 3],
                    "dict": {"nested": "value"},
                    "bool": True,
                    "none": None,
                },
            )

            result = self.provider.send(event)

            self.assertTrue(result)
            mock_post.assert_called_once()

    def test_reserved_keys_skipped(self):
        """测试保留键被跳过"""
        from notification_manager import NotificationEvent, NotificationTrigger

        with patch.object(self.provider.session, "post") as mock_post:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_post.return_value = mock_response

            # 尝试在元数据中覆盖保留键
            event = NotificationEvent(
                id="test-reserved",
                title="标题",
                message="消息",
                trigger=NotificationTrigger.IMMEDIATE,
                metadata={
                    "title": "覆盖的标题",  # 保留键，应被跳过
                    "body": "覆盖的内容",  # 保留键，应被跳过
                    "custom": "允许的值",
                },
            )

            result = self.provider.send(event)

            self.assertTrue(result)

            # 检查调用参数
            call_args = mock_post.call_args
            json_data = call_args.kwargs.get("json", {})

            # 原始标题应该保留
            self.assertEqual(json_data.get("title"), "标题")

    @patch("notification_providers.httpx.Client.post")
    def test_all_2xx_success(self, mock_post):
        """测试所有 2xx 状态码都成功"""
        from notification_manager import NotificationEvent, NotificationTrigger

        for status_code in [200, 201, 202, 204]:
            mock_response = MagicMock()
            mock_response.status_code = status_code
            mock_post.return_value = mock_response

            event = NotificationEvent(
                id=f"test-{status_code}",
                title="标题",
                message="消息",
                trigger=NotificationTrigger.IMMEDIATE,
                metadata={},
            )

            result = self.provider.send(event)

            self.assertTrue(result, f"状态码 {status_code} 应该成功")


class TestWebProviderAdvanced(unittest.TestCase):
    """Web 提供者高级测试"""

    def setUp(self):
        """每个测试前的准备"""
        from notification_manager import NotificationConfig
        from notification_providers import WebNotificationProvider

        self.config = NotificationConfig()
        self.config.web_enabled = True
        self.config.web_icon = "/icons/custom.svg"
        self.config.web_timeout = 10000
        self.config.web_permission_auto_request = True
        self.config.mobile_optimized = True
        self.config.mobile_vibrate = True

        self.provider = WebNotificationProvider(self.config)

    def test_notification_data_structure(self):
        """测试通知数据结构"""
        from notification_manager import NotificationEvent, NotificationTrigger

        event = NotificationEvent(
            id="test-structure",
            title="测试标题",
            message="测试消息",
            trigger=NotificationTrigger.IMMEDIATE,
            metadata={"extra": "data"},
        )

        result = self.provider.send(event)

        self.assertTrue(result)

        data = event.metadata.get("web_notification_data")
        self.assertIsNotNone(data)
        data = cast(dict[str, Any], data)
        self.assertEqual(data["type"], "notification")
        self.assertIn("config", data)
        config = cast(dict[str, Any], data["config"])
        self.assertEqual(config["icon"], "/icons/custom.svg")
        self.assertEqual(config["timeout"], 10000)

    def test_whitespace_trimming(self):
        """测试空白字符修剪"""
        from notification_manager import NotificationEvent, NotificationTrigger

        event = NotificationEvent(
            id="test-trim",
            title="  带空格的标题  ",
            message="  带空格的消息  ",
            trigger=NotificationTrigger.IMMEDIATE,
            metadata={},
        )

        result = self.provider.send(event)

        self.assertTrue(result)

        data = event.metadata.get("web_notification_data")
        self.assertIsNotNone(data)
        data = cast(dict[str, Any], data)
        self.assertEqual(data["title"], "带空格的标题")
        self.assertEqual(data["message"], "带空格的消息")


class TestSoundProviderAdvanced(unittest.TestCase):
    """声音提供者高级测试"""

    def setUp(self):
        """每个测试前的准备"""
        from notification_manager import NotificationConfig
        from notification_providers import SoundNotificationProvider

        self.config = NotificationConfig()
        self.config.sound_enabled = True
        self.config.sound_mute = False
        self.config.sound_volume = 0.5
        self.config.sound_file = "deng"

        self.provider = SoundNotificationProvider(self.config)

    def test_sound_file_mapping(self):
        """测试声音文件映射"""
        from notification_manager import NotificationEvent, NotificationTrigger

        event = NotificationEvent(
            id="test-sound",
            title="测试",
            message="消息",
            trigger=NotificationTrigger.IMMEDIATE,
            metadata={},
        )

        result = self.provider.send(event)

        self.assertTrue(result)

        data = event.metadata.get("sound_notification_data")
        self.assertIsNotNone(data)
        data = cast(dict[str, Any], data)
        self.assertEqual(data["file"], "deng[噔].mp3")

    def test_unknown_sound_file_fallback(self):
        """测试未知声音文件回退到默认"""
        from notification_manager import NotificationEvent, NotificationTrigger
        from notification_providers import SoundNotificationProvider

        self.config.sound_file = "unknown_sound"
        provider = SoundNotificationProvider(self.config)

        event = NotificationEvent(
            id="test-fallback",
            title="测试",
            message="消息",
            trigger=NotificationTrigger.IMMEDIATE,
            metadata={},
        )

        result = provider.send(event)

        self.assertTrue(result)

        data = event.metadata.get("sound_notification_data")
        # 应该回退到默认声音文件
        self.assertIsNotNone(data)
        data = cast(dict[str, Any], data)
        self.assertEqual(data["file"], "deng[噔].mp3")


class TestBarkProviderEdgeCases(unittest.TestCase):
    """Bark 提供者边界测试"""

    def setUp(self):
        """每个测试前的准备"""
        from notification_manager import NotificationConfig
        from notification_providers import BarkNotificationProvider

        self.config = NotificationConfig()
        self.config.bark_enabled = True
        self.config.bark_url = "https://api.day.app/push"
        self.config.bark_device_key = "test_key"

        self.provider = BarkNotificationProvider(self.config)

    def test_send_with_special_characters(self):
        """测试发送带特殊字符的通知"""
        from notification_manager import NotificationEvent, NotificationTrigger

        with patch.object(self.provider.session, "post") as mock_post:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_post.return_value = mock_response

            event = NotificationEvent(
                id="test-special",
                title="标题 <script>alert('xss')</script>",
                message="消息 & 特殊字符 \"引号\" '单引号'",
                trigger=NotificationTrigger.IMMEDIATE,
                metadata={},
            )

            result = self.provider.send(event)

            self.assertTrue(result)

    def test_send_with_unicode(self):
        """测试发送 Unicode 内容"""
        from notification_manager import NotificationEvent, NotificationTrigger

        with patch.object(self.provider.session, "post") as mock_post:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_post.return_value = mock_response

            event = NotificationEvent(
                id="test-unicode",
                title="🎉 庆祝 🎊",
                message="日本語 한국어 العربية",
                trigger=NotificationTrigger.IMMEDIATE,
                metadata={},
            )

            result = self.provider.send(event)

            self.assertTrue(result)

    def test_send_with_empty_metadata(self):
        """测试发送空元数据"""
        from notification_manager import NotificationEvent, NotificationTrigger

        with patch.object(self.provider.session, "post") as mock_post:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_post.return_value = mock_response

            event = NotificationEvent(
                id="test-empty-meta",
                title="标题",
                message="消息",
                trigger=NotificationTrigger.IMMEDIATE,
                metadata={},
            )

            result = self.provider.send(event)

            self.assertTrue(result)


class TestWebProviderEdgeCases(unittest.TestCase):
    """Web 提供者边界测试"""

    def setUp(self):
        """每个测试前的准备"""
        from notification_manager import NotificationConfig
        from notification_providers import WebNotificationProvider

        self.config = NotificationConfig()
        self.config.web_enabled = True

        self.provider = WebNotificationProvider(self.config)

    def test_send_with_long_title(self):
        """测试发送超长标题"""
        from notification_manager import NotificationEvent, NotificationTrigger

        event = NotificationEvent(
            id="test-long-title",
            title="长" * 1000,
            message="消息",
            trigger=NotificationTrigger.IMMEDIATE,
            metadata={},
        )

        result = self.provider.send(event)

        self.assertTrue(result)

    def test_send_with_long_message(self):
        """测试发送超长消息"""
        from notification_manager import NotificationEvent, NotificationTrigger

        event = NotificationEvent(
            id="test-long-message",
            title="标题",
            message="消" * 10000,
            trigger=NotificationTrigger.IMMEDIATE,
            metadata={},
        )

        result = self.provider.send(event)

        self.assertTrue(result)


class TestSoundProviderEdgeCases(unittest.TestCase):
    """声音提供者边界测试"""

    def setUp(self):
        """每个测试前的准备"""
        from notification_manager import NotificationConfig
        from notification_providers import SoundNotificationProvider

        self.config = NotificationConfig()
        self.config.sound_enabled = True
        self.config.sound_mute = False
        self.config.sound_volume = 0.5

        self.provider = SoundNotificationProvider(self.config)

    def test_volume_zero(self):
        """测试音量为 0"""
        from notification_providers import SoundNotificationProvider

        self.config.sound_volume = 0.0
        provider = SoundNotificationProvider(self.config)

        # 音量为 0 时不应该抛异常
        self.assertIsNotNone(provider)

    def test_volume_max(self):
        """测试音量为最大"""
        from notification_providers import SoundNotificationProvider

        self.config.sound_volume = 1.0
        provider = SoundNotificationProvider(self.config)

        # 音量为最大时不应该抛异常
        self.assertIsNotNone(provider)


class TestNotificationProvidersExceptions(unittest.TestCase):
    """通知提供者异常处理测试"""

    def setUp(self):
        """每个测试前的准备"""
        from notification_manager import NotificationConfig

        self.config = NotificationConfig()

    def test_bark_network_unavailable(self):
        """测试 Bark 网络不可用"""
        import httpx

        from notification_manager import NotificationEvent, NotificationTrigger
        from notification_providers import BarkNotificationProvider

        self.config.bark_enabled = True
        self.config.bark_url = "https://example.invalid/push"
        self.config.bark_device_key = "test"

        provider = BarkNotificationProvider(self.config)

        event = NotificationEvent(
            id="test-1",
            title="测试",
            message="消息",
            trigger=NotificationTrigger.IMMEDIATE,
            metadata={},
        )

        with patch(
            "notification_providers.httpx.Client.post",
            side_effect=httpx.HTTPError("network down"),
        ):
            result = provider.send(event)
        self.assertFalse(result)

    def test_web_provider_with_none_metadata(self):
        """测试 Web 提供者处理 None metadata"""
        from notification_manager import NotificationEvent, NotificationTrigger
        from notification_providers import WebNotificationProvider

        provider = WebNotificationProvider(self.config)

        event = NotificationEvent(
            id="test-1",
            title="测试",
            message="消息",
            trigger=NotificationTrigger.IMMEDIATE,
            metadata=cast(Any, None),  # 测试 None（绕过类型检查器）
        )
        # 手动设置 metadata 为 None 来测试
        event.metadata = cast(Any, None)

        # 应该不崩溃
        try:
            result = provider.send(event)
            # 可能返回 True 或 False
        except Exception as e:
            self.fail(f"不应该抛出异常: {e}")


# ============================================================================
# 覆盖率补充测试
# ============================================================================


class TestBaseProviderClose(unittest.TestCase):
    """BaseNotificationProvider.close 默认实现"""

    def test_close_noop(self):
        from notification_providers import WebNotificationProvider

        config = NotificationConfig()
        config.web_enabled = True
        provider = WebNotificationProvider(config)
        provider.close()


class TestBarkProviderClose(unittest.TestCase):
    """BarkNotificationProvider.close 和异常处理"""

    def test_close(self):
        from notification_providers import BarkNotificationProvider

        config = NotificationConfig()
        config.bark_enabled = True
        config.bark_url = "https://example.com/push"
        config.bark_device_key = "key"
        provider = BarkNotificationProvider(config)
        provider.close()

    def test_close_after_session_error(self):
        from notification_providers import BarkNotificationProvider

        config = NotificationConfig()
        config.bark_enabled = True
        config.bark_url = "https://example.com/push"
        config.bark_device_key = "key"
        provider = BarkNotificationProvider(config)
        provider.session.close()
        provider.close()


class TestBarkSanitizeErrorText(unittest.TestCase):
    """_sanitize_error_text 方法"""

    def test_empty_text(self):
        from notification_providers import BarkNotificationProvider

        self.assertEqual(BarkNotificationProvider._sanitize_error_text(""), "")

    def test_apns_url_redacted(self):
        from notification_providers import BarkNotificationProvider

        text = "Failed: https://api.push.apple.com/3/device/abcdef1234567890abcdef"
        result = BarkNotificationProvider._sanitize_error_text(text)
        self.assertNotIn("abcdef1234567890abcdef", result)
        self.assertIn("<redacted>", result)

    def test_long_hex_redacted(self):
        from notification_providers import BarkNotificationProvider

        text = "Token: " + "a1" * 20
        result = BarkNotificationProvider._sanitize_error_text(text)
        self.assertIn("<redacted_hex>", result)


class TestBarkSendEdgeCases(unittest.TestCase):
    """Bark send 边缘分支"""

    def _make_provider(self, **overrides):
        from notification_providers import BarkNotificationProvider

        config = NotificationConfig()
        config.bark_enabled = True
        config.bark_url = "https://api.day.app/push"
        config.bark_device_key = "test_key"
        config.bark_icon = ""
        config.bark_action = "none"
        for k, v in overrides.items():
            setattr(config, k, v)
        return BarkNotificationProvider(config)

    def test_empty_device_key_whitespace(self):
        """device_key 全空白 → False"""
        provider = self._make_provider(bark_device_key="   ")
        event = create_event(title="T", message="M")
        self.assertFalse(provider.send(event))

    @patch("notification_providers.httpx.Client.post")
    def test_action_url_no_url_in_metadata(self, mock_post):
        """bark_action=url 但 metadata 无 URL → 正常发送不带 url 字段"""
        mock_post.return_value = MagicMock(status_code=200)
        provider = self._make_provider(bark_action="url")
        event = create_event(title="T", message="M", metadata={})
        self.assertTrue(provider.send(event))
        payload = mock_post.call_args.kwargs["json"]
        self.assertNotIn("url", payload)

    @patch("notification_providers.httpx.Client.post")
    def test_action_copy_with_metadata(self, mock_post):
        """bark_action=copy + metadata 有 copy_text → 使用 metadata 值"""
        mock_post.return_value = MagicMock(status_code=200)
        provider = self._make_provider(bark_action="copy")
        event = create_event(
            title="T", message="M", metadata={"copy_text": "custom copy"}
        )
        self.assertTrue(provider.send(event))
        payload = mock_post.call_args.kwargs["json"]
        self.assertEqual(payload["copy"], "custom copy")

    @patch("notification_providers.httpx.Client.post")
    def test_action_unknown_as_url(self, mock_post):
        """bark_action 是一个 URL → 当作 url 字段"""
        mock_post.return_value = MagicMock(status_code=200)
        provider = self._make_provider(bark_action="https://custom.action/")
        event = create_event(title="T", message="M")
        self.assertTrue(provider.send(event))
        payload = mock_post.call_args.kwargs["json"]
        self.assertEqual(payload.get("url"), "https://custom.action/")

    @patch("notification_providers.httpx.Client.post")
    def test_action_unknown_non_url(self, mock_post):
        """bark_action 是未知非 URL 值 → 忽略"""
        mock_post.return_value = MagicMock(status_code=200)
        provider = self._make_provider(bark_action="some_random_value")
        event = create_event(title="T", message="M")
        self.assertTrue(provider.send(event))
        payload = mock_post.call_args.kwargs["json"]
        self.assertNotIn("url", payload)
        self.assertNotIn("action", payload)

    @patch("notification_providers.httpx.Client.post")
    def test_metadata_complex_type_skipped(self, mock_post):
        """白名单内键的非基本类型值应被静默跳过，非白名单键也应被跳过"""
        mock_post.return_value = MagicMock(status_code=200)
        provider = self._make_provider()

        class Custom:
            def __str__(self):
                return "custom_str"

        event = create_event(
            title="T",
            message="M",
            metadata={"group": Custom(), "obj": "should_be_filtered"},
        )
        self.assertTrue(provider.send(event))
        payload = mock_post.call_args.kwargs["json"]
        self.assertNotIn("group", payload)
        self.assertNotIn("obj", payload)

    @patch("notification_providers.httpx.Client.post")
    def test_bark_timeout_invalid_fallback(self, mock_post):
        """bark_timeout 无效时回退到默认 10s"""
        mock_post.return_value = MagicMock(status_code=200)
        provider = self._make_provider()
        provider.config.bark_timeout = "not_a_number"
        event = create_event(title="T", message="M")
        self.assertTrue(provider.send(event))
        self.assertEqual(mock_post.call_args.kwargs["timeout"], 10)

    @patch("notification_providers.httpx.Client.post")
    def test_http_error_json_parse_fails(self, mock_post):
        """HTTP 错误 + response.json() 抛异常 → 使用 response.text"""
        resp = MagicMock(status_code=500, text="raw error")
        resp.json.side_effect = ValueError("no json")
        mock_post.return_value = resp
        provider = self._make_provider()
        event = create_event(title="T", message="M")
        self.assertFalse(provider.send(event))

    @patch("notification_providers.httpx.Client.post")
    def test_http_error_debug_mode(self, mock_post):
        """debug=True 时 bark_error 写入 metadata"""
        resp = MagicMock(status_code=400, text="bad request")
        resp.json.return_value = {"code": 400, "message": "bad"}
        mock_post.return_value = resp
        provider = self._make_provider()
        provider.config.debug = True
        event = create_event(title="T", message="M")
        self.assertFalse(provider.send(event))
        self.assertIn("bark_error", event.metadata)

    @patch("notification_providers.httpx.Client.post")
    def test_http_error_test_event(self, mock_post):
        """test=True 的事件也写 bark_error"""
        resp = MagicMock(status_code=400, text="bad")
        resp.json.return_value = {"code": 400, "message": "bad"}
        mock_post.return_value = resp
        provider = self._make_provider()
        event = create_event(title="T", message="M", metadata={"test": True})
        self.assertFalse(provider.send(event))
        self.assertIn("bark_error", event.metadata)

    @patch("notification_providers.httpx.Client.post")
    def test_generic_exception(self, mock_post):
        """send 内部 generic Exception → False"""
        mock_post.side_effect = RuntimeError("unexpected")
        provider = self._make_provider()
        event = create_event(title="T", message="M")
        self.assertFalse(provider.send(event))


class TestSoundProviderException(unittest.TestCase):
    """SoundNotificationProvider.send 异常处理"""

    def test_send_exception_in_sound_files(self):
        from notification_providers import SoundNotificationProvider

        config = NotificationConfig()
        config.sound_enabled = True
        config.sound_mute = False
        config.sound_volume = 0.5
        config.sound_file = "default"
        provider = SoundNotificationProvider(config)
        provider.sound_files = None  # ty: ignore[invalid-assignment]
        event = create_event()
        self.assertFalse(provider.send(event))


class TestSystemProviderSend(unittest.TestCase):
    """SystemNotificationProvider.send 各路径"""

    def test_send_supported_success(self):
        from notification_providers import SystemNotificationProvider

        config = NotificationConfig()
        config.web_timeout = 5000
        provider = SystemNotificationProvider(config)
        provider.supported = True
        provider._notify = MagicMock()
        event = create_event()
        self.assertTrue(provider.send(event))
        provider._notify.assert_called_once()

    def test_send_supported_exception(self):
        from notification_providers import SystemNotificationProvider

        config = NotificationConfig()
        config.web_timeout = 5000
        provider = SystemNotificationProvider(config)
        provider.supported = True
        provider._notify = MagicMock(side_effect=RuntimeError("fail"))
        event = create_event()
        self.assertFalse(provider.send(event))

    def test_send_notify_none(self):
        from notification_providers import SystemNotificationProvider

        config = NotificationConfig()
        config.web_timeout = 5000
        provider = SystemNotificationProvider(config)
        provider.supported = True
        provider._notify = None
        event = create_event()
        self.assertFalse(provider.send(event))

    def test_send_uses_display_duration_constant(self):
        """plyer ``timeout`` 必须等于 ``_DISPLAY_DURATION_SECONDS``。

        历史这里硬编码了 ``timeout_seconds = 10.0`` + 误导性变量名（看起来像
        send timeout，实际是 plyer 的 banner 显示时长）。提取成类常量
        ``_DISPLAY_DURATION_SECONDS`` 后必须保证 plyer 收到的就是这个值。
        """
        from notification_providers import SystemNotificationProvider

        config = NotificationConfig()
        config.web_timeout = 5000
        provider = SystemNotificationProvider(config)
        provider.supported = True
        provider._notify = MagicMock()

        event = create_event()
        provider.send(event)

        provider._notify.assert_called_once()
        call_kwargs = provider._notify.call_args.kwargs
        self.assertEqual(
            call_kwargs.get("timeout"),
            SystemNotificationProvider._DISPLAY_DURATION_SECONDS,
            "plyer 的 timeout 参数必须来自类常量；硬编码 magic number "
            "会让未来想调显示时长的人找不到入口",
        )

    def test_display_duration_constant_value_locked(self):
        """反向锁：``_DISPLAY_DURATION_SECONDS`` 不能被悄悄改成无意义值。

        - ``< 3``：banner 闪一下就消失，用户大概率错过通知。
        - ``> 30``：和后续 task 通知互相打架。
        - ``== 0``：plyer 行为依平台而异（macOS = 永久；Linux = 立即）；
          会引入跨平台分歧。
        """
        from notification_providers import SystemNotificationProvider

        self.assertEqual(
            SystemNotificationProvider._DISPLAY_DURATION_SECONDS,
            10,
            "如果你确实想调通知 banner 的显示时长，请：\n"
            "  1. 想清楚跨平台行为差异（macOS 用 osascript display notification "
            "尊重 timeout；Linux libnotify 行为依发行版而异）\n"
            "  2. 在 [3, 30] 范围内选值，否则会触发上面的边缘案例\n"
            "  3. 同时更新这条断言 + 类常量 + 模块级 docstring",
        )


class TestInitializeNotificationSystem(unittest.TestCase):
    """initialize_notification_system 函数"""

    def test_initializes(self):
        from notification_providers import initialize_notification_system

        config = NotificationConfig()
        config.web_enabled = True
        config.sound_enabled = False
        config.bark_enabled = False
        result = initialize_notification_system(config)
        self.assertIsNotNone(result)


class TestWebProviderUnregisterNonexistent(unittest.TestCase):
    """unregister_client 对不存在的客户端"""

    def test_unregister_nonexistent(self):
        from notification_providers import WebNotificationProvider

        config = NotificationConfig()
        config.web_enabled = True
        provider = WebNotificationProvider(config)
        provider.unregister_client("does-not-exist")


# ---------------------------------------------------------------------------
# 边界路径补充（原 test_notification_providers_extended.py）
# ---------------------------------------------------------------------------
from notification_models import NotificationType
from notification_providers import (
    BarkNotificationProvider,
    create_notification_providers,
)


def _make_ext_config(**overrides) -> MagicMock:
    defaults = {
        "web_enabled": False,
        "sound_enabled": False,
        "bark_enabled": True,
        "bark_url": "https://api.day.app/push",
        "bark_device_key": "test_key",
        "bark_icon": "",
        "bark_action": "none",
        "bark_url_template": "{base_url}/?task_id={task_id}",
        "bark_timeout": 10,
        "web_timeout": 5000,
        "web_icon": "",
        "web_permission_auto_request": True,
        "mobile_optimized": False,
        "mobile_vibrate": True,
        "sound_volume": 0.8,
        "sound_file": "default",
        "sound_mute": False,
        "debug": False,
    }
    defaults.update(overrides)
    cfg = MagicMock()
    for k, v in defaults.items():
        setattr(cfg, k, v)
    return cfg  # type: ignore[return-value]


def _make_ext_event(**overrides) -> NotificationEvent:
    defaults = {
        "id": "test-event-001",
        "title": "测试标题",
        "message": "测试消息",
        "trigger": NotificationTrigger.IMMEDIATE,
        "types": [NotificationType.BARK],
        "metadata": {},
    }
    defaults.update(overrides)
    return NotificationEvent(**defaults)  # ty: ignore[invalid-argument-type]


class TestBarkCloseException(unittest.TestCase):
    def test_close_session_error_swallowed(self):
        cfg = _make_ext_config()
        provider = BarkNotificationProvider(cfg)
        provider.session.close = MagicMock(side_effect=RuntimeError("close error"))  # ty: ignore[invalid-assignment]
        provider.close()

    def test_close_success(self):
        cfg = _make_ext_config()
        provider = BarkNotificationProvider(cfg)
        provider.close()


class TestBarkUrlActionNoLink(unittest.TestCase):
    def test_url_action_no_link_in_metadata(self):
        cfg = _make_ext_config(bark_action="url")
        provider = BarkNotificationProvider(cfg)
        event = _make_ext_event(metadata={"custom_key": "no_url_here"})
        with patch.object(provider.session, "post") as mock_post:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_post.return_value = mock_resp
            result = provider.send(event)
        self.assertTrue(result)


class TestBarkCopyAction(unittest.TestCase):
    def test_copy_action_from_metadata(self):
        cfg = _make_ext_config(bark_action="copy")
        provider = BarkNotificationProvider(cfg)
        event = _make_ext_event(metadata={"copy_text": "要复制的内容"})
        with patch.object(provider.session, "post") as mock_post:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_post.return_value = mock_resp
            result = provider.send(event)
        self.assertTrue(result)
        bark_data = mock_post.call_args.kwargs.get("json") or mock_post.call_args[
            1
        ].get("json")
        self.assertEqual(bark_data["copy"], "要复制的内容")

    def test_copy_action_fallback_to_message(self):
        cfg = _make_ext_config(bark_action="copy")
        provider = BarkNotificationProvider(cfg)
        event = _make_ext_event(metadata={})
        with patch.object(provider.session, "post") as mock_post:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_post.return_value = mock_resp
            result = provider.send(event)
        self.assertTrue(result)
        bark_data = mock_post.call_args.kwargs.get("json") or mock_post.call_args[
            1
        ].get("json")
        self.assertEqual(bark_data["copy"], "测试消息")


class TestBarkDebugMetadataWriteException(unittest.TestCase):
    def test_metadata_write_error_swallowed(self):
        cfg = _make_ext_config(debug=True)
        provider = BarkNotificationProvider(cfg)
        event = _make_ext_event()

        class FrozenDict(dict):
            def __setitem__(self, key, value):
                if key == "bark_error":
                    raise TypeError("immutable")
                super().__setitem__(key, value)

        event.metadata = FrozenDict()  # type: ignore[assignment]
        with patch.object(provider.session, "post") as mock_post:
            mock_resp = MagicMock()
            mock_resp.status_code = 400
            mock_resp.json.return_value = {"code": 400, "message": "bad"}
            mock_resp.text = "bad request"
            mock_post.return_value = mock_resp
            result = provider.send(event)
        self.assertFalse(result)


class TestSystemProviderCreationException(unittest.TestCase):
    def test_system_provider_exception_swallowed(self):
        cfg = _make_ext_config(
            web_enabled=True, sound_enabled=False, bark_enabled=False
        )
        with patch(
            "notification_providers.SystemNotificationProvider",
            side_effect=RuntimeError("init failed"),
        ):
            providers = create_notification_providers(cfg)
        self.assertIn(NotificationType.WEB, providers)
        self.assertNotIn(NotificationType.SYSTEM, providers)


class TestSystemProviderPlyerImportSuccess(unittest.TestCase):
    def test_plyer_available(self):
        from notification_providers import SystemNotificationProvider

        cfg = _make_ext_config()
        mock_module = MagicMock()
        mock_module.notify = MagicMock()
        with patch("notification_providers.find_spec", return_value=MagicMock()):
            with patch.dict(
                "sys.modules", {"plyer": MagicMock(), "plyer.notification": mock_module}
            ):
                provider = SystemNotificationProvider(cfg)
                self.assertTrue(provider.supported)
                self.assertIsNotNone(provider._notify)


class TestSystemProviderPlyerImportError(unittest.TestCase):
    def test_plyer_import_error_caught(self):
        from notification_providers import SystemNotificationProvider

        cfg = _make_ext_config()
        with patch("notification_providers.find_spec", return_value=MagicMock()):
            import builtins

            original_import = builtins.__import__

            def mock_import(name, *args, **kwargs):
                if name == "plyer" or name.startswith("plyer."):
                    raise ImportError("no plyer")
                return original_import(name, *args, **kwargs)

            with patch("builtins.__import__", side_effect=mock_import):
                provider = SystemNotificationProvider(cfg)
                self.assertFalse(provider.supported)
                self.assertIsNone(provider._notify)


class TestCreateProvidersSystemSupported(unittest.TestCase):
    def test_system_provider_added_when_supported(self):
        cfg = _make_ext_config(
            web_enabled=False, sound_enabled=False, bark_enabled=False
        )
        mock_provider = MagicMock()
        mock_provider.supported = True
        with patch(
            "notification_providers.SystemNotificationProvider",
            return_value=mock_provider,
        ):
            providers = create_notification_providers(cfg)
        self.assertIn(NotificationType.SYSTEM, providers)


class TestBarkCopyActionWithMetadata(unittest.TestCase):
    def test_copy_action_with_copy_metadata(self):
        cfg = _make_ext_config(bark_action="copy")
        provider = BarkNotificationProvider(cfg)
        event = NotificationEvent(
            id="test-copy",
            title="标题",
            message="内容",
            trigger=NotificationTrigger.IMMEDIATE,
            metadata={"copy": "  自定义复制内容  "},
        )
        with patch.object(provider.session, "post") as mock_post:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {"code": 200}
            mock_post.return_value = mock_resp
            result = provider.send(event)
        self.assertTrue(result)
        call_json = mock_post.call_args[1].get("json") or mock_post.call_args[0][0]
        if isinstance(call_json, dict):
            self.assertEqual(call_json.get("copy"), "自定义复制内容")


class TestBarkCopyActionNoMetadata(unittest.TestCase):
    def test_copy_action_empty_metadata_uses_message(self):
        cfg = _make_ext_config(bark_action="copy")
        provider = BarkNotificationProvider(cfg)
        event = _make_ext_event(
            id="bark-copy-no-meta", message="fallback body", metadata={}
        )
        with patch.object(provider.session, "post") as mock_post:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {"code": 200}
            mock_post.return_value = mock_resp
            result = provider.send(event)
        self.assertTrue(result)
        call_json = mock_post.call_args[1].get("json") or mock_post.call_args[0][0]
        if isinstance(call_json, dict):
            self.assertEqual(call_json.get("copy"), "fallback body")


if __name__ == "__main__":
    unittest.main()
