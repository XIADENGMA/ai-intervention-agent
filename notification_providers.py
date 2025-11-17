#!/usr/bin/env python3
"""
AI Intervention Agent - 通知提供者实现

包含各种通知方式的具体实现：
- Web 浏览器通知
- 声音通知
- Bark 推送通知
"""

import time
from typing import Any, Dict

import requests

from enhanced_logging import EnhancedLogger
from notification_manager import NotificationEvent, NotificationType

logger = EnhancedLogger(__name__)


class WebNotificationProvider:
    """Web 通知提供者

    通过 WebSocket 或 HTTP 推送通知到浏览器
    """

    def __init__(self, config):
        """初始化 Web 通知提供者

        Args:
            config: 通知配置对象
        """
        self.config = config
        self.web_clients: Dict[str, Any] = {}

    def register_client(self, client_id: str, client_info: Dict[str, Any]):
        """注册 Web 客户端

        Args:
            client_id: 客户端唯一标识
            client_info: 客户端信息字典
        """
        self.web_clients[client_id] = {"info": client_info, "last_seen": time.time()}
        logger.debug(f"Web客户端已注册: {client_id}")

    def unregister_client(self, client_id: str):
        """注销 Web 客户端

        Args:
            client_id: 客户端唯一标识
        """
        if client_id in self.web_clients:
            del self.web_clients[client_id]
            logger.debug(f"Web客户端已注销: {client_id}")

    def send(self, event: NotificationEvent) -> bool:
        """发送 Web 通知

        准备通知数据并存储到事件的 metadata 中，供前端获取

        Args:
            event: 通知事件对象

        Returns:
            bool: 是否成功准备通知数据
        """
        try:
            # 构建通知数据
            notification_data = {
                "id": event.id,
                "type": "notification",
                "title": event.title,
                "message": event.message,
                "timestamp": event.timestamp,
                "config": {
                    "icon": self.config.web_icon,
                    "timeout": self.config.web_timeout,
                    "auto_request_permission": self.config.web_permission_auto_request,
                    "mobile_optimized": self.config.mobile_optimized,
                    "mobile_vibrate": self.config.mobile_vibrate,
                },
                "metadata": event.metadata,
            }

            event.metadata["web_notification_data"] = notification_data

            logger.debug(f"Web通知数据已准备: {event.id}")
            return True

        except Exception as e:
            logger.error(f"准备Web通知失败: {e}")
            return False


class SoundNotificationProvider:
    """声音通知提供者

    通过 Web Audio API 播放声音
    """

    def __init__(self, config):
        """初始化声音通知提供者

        Args:
            config: 通知配置对象
        """
        self.config = config
        self.sound_files = {
            "default": "deng[噔].mp3",
            "deng": "deng[噔].mp3",
        }

    def send(self, event: NotificationEvent) -> bool:
        """发送声音通知

        准备声音通知数据并存储到事件的 metadata 中

        Args:
            event: 通知事件对象

        Returns:
            bool: 是否成功准备声音数据
        """
        try:
            if self.config.sound_mute:
                logger.debug("声音通知已静音，跳过播放")
                return True

            sound_file = self.sound_files.get(
                self.config.sound_file, self.sound_files["default"]
            )

            sound_data = {
                "id": event.id,
                "type": "sound",
                "file": sound_file,
                "volume": self.config.sound_volume,
                "timestamp": event.timestamp,
                "metadata": event.metadata,
            }

            event.metadata["sound_notification_data"] = sound_data

            logger.debug(f"声音通知数据已准备: {event.id} - {sound_file}")
            return True

        except Exception as e:
            logger.error(f"准备声音通知失败: {e}")
            return False


class BarkNotificationProvider:
    """Bark 通知提供者

    iOS 推送通知服务，支持自定义图标、动作和元数据
    """

    def __init__(self, config):
        """初始化 Bark 通知提供者

        Args:
            config: 通知配置对象
        """
        self.config = config
        self.session = requests.Session()
        adapter = requests.adapters.HTTPAdapter(max_retries=3)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)

    def send(self, event: NotificationEvent) -> bool:
        """发送 Bark 通知

        通过 HTTP POST 请求发送通知到 Bark 服务器

        Args:
            event: 通知事件对象

        Returns:
            bool: 是否成功发送通知
        """
        try:
            if not self.config.bark_enabled:
                logger.debug("Bark通知已禁用")
                return False

            if not self.config.bark_url or not self.config.bark_device_key:
                logger.warning("Bark配置不完整，跳过发送")
                return False

            bark_data = {
                "title": event.title,
                "body": event.message,
                "device_key": self.config.bark_device_key,
                "action": self.config.bark_action,
            }

            if self.config.bark_icon:
                bark_data["icon"] = self.config.bark_icon

            if event.metadata:
                for key, value in event.metadata.items():
                    if isinstance(value, (str, int, float, bool, type(None))):
                        bark_data[key] = value
                    elif isinstance(value, (list, dict)):
                        try:
                            import json

                            json.dumps(value)
                            bark_data[key] = value
                        except (TypeError, ValueError):
                            bark_data[key] = str(value)
                    else:
                        bark_data[key] = str(value)

            response = self.session.post(
                self.config.bark_url,
                json=bark_data,
                timeout=10,
                headers={
                    "Content-Type": "application/json",
                    "User-Agent": "AI-Intervention-Agent",
                },
            )

            if response.status_code == 200:
                logger.info(f"Bark通知发送成功: {event.id}")
                return True
            else:
                logger.error(
                    f"Bark通知发送失败: {response.status_code} - {response.text}"
                )
                return False

        except requests.exceptions.Timeout:
            logger.error(f"Bark通知发送超时: {event.id}")
            return False
        except requests.exceptions.RequestException as e:
            logger.error(f"Bark通知发送网络错误: {e}")
            return False
        except Exception as e:
            logger.error(f"Bark通知发送失败: {e}")
            return False


class SystemNotificationProvider:
    """系统通知提供者

    操作系统级别的通知（可选实现），需要 plyer 库支持
    """

    def __init__(self, config):
        """初始化系统通知提供者

        Args:
            config: 通知配置对象
        """
        self.config = config
        self._check_system_support()

    def _check_system_support(self):
        """检查系统通知支持

        尝试导入 plyer 库，设置支持状态
        """
        try:
            import plyer

            self.plyer = plyer
            self.supported = True
            logger.debug("系统通知支持已启用")
        except ImportError:
            self.plyer = None
            self.supported = False
            logger.debug("系统通知不支持（缺少plyer库）")

    def send(self, event: NotificationEvent) -> bool:
        """发送系统通知

        使用 plyer 库发送操作系统级别的通知

        Args:
            event: 通知事件对象

        Returns:
            bool: 是否成功发送通知
        """
        try:
            if not self.supported:
                logger.debug("系统通知不支持，跳过发送")
                return False

            self.plyer.notification.notify(
                title=event.title,
                message=event.message,
                app_name="AI Intervention Agent",
                timeout=self.config.web_timeout // 1000,
            )

            logger.debug(f"系统通知发送成功: {event.id}")
            return True

        except Exception as e:
            logger.error(f"系统通知发送失败: {e}")
            return False


def create_notification_providers(config) -> Dict[NotificationType, Any]:
    """创建所有通知提供者

    根据配置创建并返回所有启用的通知提供者

    Args:
        config: 通知配置对象

    Returns:
        Dict[NotificationType, Any]: 通知类型到提供者的映射字典
    """
    providers = {}

    if config.web_enabled:
        providers[NotificationType.WEB] = WebNotificationProvider(config)
        logger.debug("Web通知提供者已创建")

    if config.sound_enabled:
        providers[NotificationType.SOUND] = SoundNotificationProvider(config)
        logger.debug("声音通知提供者已创建")

    if config.bark_enabled:
        providers[NotificationType.BARK] = BarkNotificationProvider(config)
        logger.debug("Bark通知提供者已创建")

    try:
        system_provider = SystemNotificationProvider(config)
        if system_provider.supported:
            providers[NotificationType.SYSTEM] = system_provider
            logger.debug("系统通知提供者已创建")
    except Exception as e:
        logger.debug(f"系统通知提供者创建失败: {e}")

    logger.info(f"已创建 {len(providers)} 个通知提供者")
    return providers


def initialize_notification_system(config):
    """初始化通知系统

    创建所有通知提供者并注册到通知管理器

    Args:
        config: 通知配置对象

    Returns:
        notification_manager: 初始化后的通知管理器实例
    """
    from notification_manager import notification_manager

    providers = create_notification_providers(config)

    for notification_type, provider in providers.items():
        notification_manager.register_provider(notification_type, provider)

    logger.info("通知系统初始化完成")
    return notification_manager
