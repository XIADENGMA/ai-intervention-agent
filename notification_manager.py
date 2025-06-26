#!/usr/bin/env python3
"""
AI Intervention Agent - 通知管理器
负责管理各种通知方式的统一接口和配置
"""

import logging
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

try:
    from config_manager import get_config

    CONFIG_FILE_AVAILABLE = True
except ImportError:
    CONFIG_FILE_AVAILABLE = False

logger = logging.getLogger(__name__)


class NotificationType(Enum):
    """通知类型枚举"""

    WEB = "web"
    SOUND = "sound"
    BARK = "bark"
    SYSTEM = "system"


class NotificationTrigger(Enum):
    """通知触发时机枚举"""

    IMMEDIATE = "immediate"  # 立即通知
    DELAYED = "delayed"  # 延迟通知
    REPEAT = "repeat"  # 重复提醒
    FEEDBACK_RECEIVED = "feedback_received"  # 反馈收到时
    ERROR = "error"  # 错误时


@dataclass
class NotificationConfig:
    """通知配置类"""

    # 总开关
    enabled: bool = True
    debug: bool = False

    # Web通知配置
    web_enabled: bool = True
    web_permission_auto_request: bool = True
    web_icon: str = "default"
    web_timeout: int = 5000  # 毫秒

    # 声音通知配置
    sound_enabled: bool = True
    sound_volume: float = 0.8
    sound_file: str = "default"
    sound_mute: bool = False

    # 触发时机配置
    trigger_immediate: bool = True
    trigger_delay: int = 30  # 秒
    trigger_repeat: bool = False
    trigger_repeat_interval: int = 60  # 秒

    # 错误处理配置
    retry_count: int = 3
    retry_delay: int = 2  # 秒
    fallback_enabled: bool = True

    # 移动设备优化
    mobile_optimized: bool = True
    mobile_vibrate: bool = True

    # Bark通知配置（可选）
    bark_enabled: bool = False
    bark_url: str = ""
    bark_device_key: str = ""
    bark_icon: str = ""
    bark_action: str = "none"

    @classmethod
    def from_config_file(cls) -> "NotificationConfig":
        """从配置文件创建配置实例"""
        if not CONFIG_FILE_AVAILABLE:
            logger.error("配置文件管理器不可用，无法初始化通知配置")
            raise Exception("配置文件管理器不可用")

        config_mgr = get_config()
        notification_config = config_mgr.get_section("notification")

        return cls(
            enabled=notification_config.get("enabled", True),
            debug=notification_config.get("debug", False),
            web_enabled=notification_config.get("web_enabled", True),
            web_permission_auto_request=notification_config.get(
                "auto_request_permission", True
            ),
            sound_enabled=notification_config.get("sound_enabled", True),
            sound_volume=notification_config.get("sound_volume", 80)
            / 100.0,  # 转换为0-1范围
            sound_mute=notification_config.get("sound_mute", False),
            mobile_optimized=notification_config.get("mobile_optimized", True),
            mobile_vibrate=notification_config.get("mobile_vibrate", True),
            bark_enabled=notification_config.get("bark_enabled", False),
            bark_url=notification_config.get("bark_url", ""),
            bark_device_key=notification_config.get("bark_device_key", ""),
            bark_icon=notification_config.get("bark_icon", ""),
            bark_action=notification_config.get("bark_action", "none"),
        )


@dataclass
class NotificationEvent:
    """通知事件数据结构"""

    id: str
    title: str
    message: str
    trigger: NotificationTrigger
    types: List[NotificationType] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)
    retry_count: int = 0
    max_retries: int = 3


class NotificationManager:
    """通知管理器 - 单例模式"""

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if not getattr(self, "_initialized", False):
            # 使用配置文件初始化
            try:
                self.config = NotificationConfig.from_config_file()
                logger.info("使用配置文件初始化通知管理器")
            except Exception as e:
                logger.error(f"配置文件加载失败: {e}")
                raise Exception(f"通知管理器初始化失败，无法加载配置文件: {e}")

            self._providers: Dict[NotificationType, Any] = {}
            self._event_queue: List[NotificationEvent] = []
            self._queue_lock = threading.Lock()
            self._worker_thread = None
            self._stop_event = threading.Event()
            self._callbacks: Dict[str, List[Callable]] = {}
            self._initialized = True

            if self.config.debug:
                logger.setLevel(logging.DEBUG)
                logger.debug("通知管理器初始化完成（调试模式）")
            else:
                logger.info("通知管理器初始化完成")

    def register_provider(self, notification_type: NotificationType, provider: Any):
        """注册通知提供者"""
        self._providers[notification_type] = provider
        logger.debug(f"已注册通知提供者: {notification_type.value}")

    def add_callback(self, event_name: str, callback: Callable):
        """添加事件回调"""
        if event_name not in self._callbacks:
            self._callbacks[event_name] = []
        self._callbacks[event_name].append(callback)
        logger.debug(f"已添加回调: {event_name}")

    def trigger_callbacks(self, event_name: str, *args, **kwargs):
        """触发事件回调"""
        if event_name in self._callbacks:
            for callback in self._callbacks[event_name]:
                try:
                    callback(*args, **kwargs)
                except Exception as e:
                    logger.error(f"回调执行失败 {event_name}: {e}")

    def send_notification(
        self,
        title: str,
        message: str,
        trigger: NotificationTrigger = NotificationTrigger.IMMEDIATE,
        types: Optional[List[NotificationType]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """发送通知"""
        if not self.config.enabled:
            logger.debug("通知功能已禁用，跳过发送")
            return ""

        # 生成事件ID
        event_id = f"notification_{int(time.time() * 1000)}_{id(self)}"

        # 默认通知类型
        if types is None:
            types = []
            if self.config.web_enabled:
                types.append(NotificationType.WEB)
            if self.config.sound_enabled and not self.config.sound_mute:
                types.append(NotificationType.SOUND)
            if self.config.bark_enabled:
                types.append(NotificationType.BARK)

        # 创建通知事件
        event = NotificationEvent(
            id=event_id,
            title=title,
            message=message,
            trigger=trigger,
            types=types,
            metadata=metadata or {},
            max_retries=self.config.retry_count,
        )

        # 添加到队列
        with self._queue_lock:
            self._event_queue.append(event)

        logger.debug(f"通知事件已创建: {event_id} - {title}")

        # 立即处理或延迟处理
        if trigger == NotificationTrigger.IMMEDIATE:
            self._process_event(event)
        elif trigger == NotificationTrigger.DELAYED:
            threading.Timer(
                self.config.trigger_delay, self._process_event, args=[event]
            ).start()

        return event_id

    def _process_event(self, event: NotificationEvent):
        """处理通知事件"""
        try:
            logger.debug(f"处理通知事件: {event.id}")

            success_count = 0
            for notification_type in event.types:
                if self._send_single_notification(notification_type, event):
                    success_count += 1

            # 触发回调
            self.trigger_callbacks("notification_sent", event, success_count)

            if success_count == 0 and self.config.fallback_enabled:
                logger.warning(f"所有通知方式失败，启用降级处理: {event.id}")
                self._handle_fallback(event)

        except Exception as e:
            logger.error(f"处理通知事件失败: {event.id} - {e}")
            if self.config.fallback_enabled:
                self._handle_fallback(event)

    def _send_single_notification(
        self, notification_type: NotificationType, event: NotificationEvent
    ) -> bool:
        """发送单个类型的通知"""
        provider = self._providers.get(notification_type)
        if not provider:
            logger.debug(f"未找到通知提供者: {notification_type.value}")
            return False

        try:
            # 调用提供者的发送方法
            if hasattr(provider, "send"):
                return provider.send(event)
            else:
                logger.error(f"通知提供者缺少send方法: {notification_type.value}")
                return False
        except Exception as e:
            logger.error(f"发送通知失败 {notification_type.value}: {e}")
            return False

    def _handle_fallback(self, event: NotificationEvent):
        """处理降级方案"""
        logger.info(f"执行降级处理: {event.id}")
        # 这里可以实现降级逻辑，比如记录到日志、发送邮件等
        self.trigger_callbacks("notification_fallback", event)

    def get_config(self) -> NotificationConfig:
        """获取当前配置"""
        return self.config

    def update_config(self, **kwargs):
        """更新配置"""
        bark_was_enabled = self.config.bark_enabled

        for key, value in kwargs.items():
            if hasattr(self.config, key):
                setattr(self.config, key, value)
                logger.debug(f"配置已更新: {key} = {value}")

        # 如果Bark配置发生变化，动态更新提供者
        bark_now_enabled = self.config.bark_enabled
        if bark_was_enabled != bark_now_enabled:
            self._update_bark_provider()

        # 保存配置到文件
        self._save_config_to_file()

    def _update_bark_provider(self):
        """动态更新Bark通知提供者"""
        try:
            if self.config.bark_enabled:
                # 启用Bark通知，添加提供者
                if NotificationType.BARK not in self._providers:
                    from notification_providers import BarkNotificationProvider

                    bark_provider = BarkNotificationProvider(self.config)
                    self.register_provider(NotificationType.BARK, bark_provider)
                    logger.info("Bark通知提供者已动态添加")
            else:
                # 禁用Bark通知，移除提供者
                if NotificationType.BARK in self._providers:
                    del self._providers[NotificationType.BARK]
                    logger.info("Bark通知提供者已移除")
        except Exception as e:
            logger.error(f"更新Bark提供者失败: {e}")

    def _save_config_to_file(self):
        """保存当前配置到配置文件"""
        if not CONFIG_FILE_AVAILABLE:
            return

        try:
            config_mgr = get_config()
            notification_config = {
                "enabled": self.config.enabled,
                "web_enabled": self.config.web_enabled,
                "auto_request_permission": self.config.web_permission_auto_request,
                "sound_enabled": self.config.sound_enabled,
                "sound_mute": self.config.sound_mute,
                "sound_volume": int(self.config.sound_volume * 100),  # 转换回0-100范围
                "mobile_optimized": self.config.mobile_optimized,
                "mobile_vibrate": self.config.mobile_vibrate,
                "bark_enabled": self.config.bark_enabled,
                "bark_url": self.config.bark_url,
                "bark_device_key": self.config.bark_device_key,
                "bark_icon": self.config.bark_icon,
                "bark_action": self.config.bark_action,
            }
            config_mgr.update_section("notification", notification_config)
            logger.debug("配置已保存到文件")
        except Exception as e:
            logger.error(f"保存配置到文件失败: {e}")

    def get_status(self) -> Dict[str, Any]:
        """获取通知管理器状态"""
        with self._queue_lock:
            queue_size = len(self._event_queue)

        return {
            "enabled": self.config.enabled,
            "providers": list(self._providers.keys()),
            "queue_size": queue_size,
            "config": {
                "web_enabled": self.config.web_enabled,
                "sound_enabled": self.config.sound_enabled,
                "bark_enabled": self.config.bark_enabled,
            },
        }


# 全局通知管理器实例
notification_manager = NotificationManager()
