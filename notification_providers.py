#!/usr/bin/env python3
"""通知提供者实现 - Web/Sound/Bark/System 四种通知方式。

所有提供者实现 send(event) -> bool 接口，由 NotificationManager 调用。
"""

import re
import time
from collections.abc import Callable
from typing import Any, Dict

import requests
from requests.adapters import HTTPAdapter

from enhanced_logging import EnhancedLogger
from notification_manager import NotificationEvent, NotificationType

logger = EnhancedLogger(__name__)


class WebNotificationProvider:
    """Web 浏览器通知 - 准备通知数据到 event.metadata 供前端轮询展示。"""

    def __init__(self, config):
        self.config = config
        self.web_clients: Dict[str, Any] = {}

    def register_client(self, client_id: str, client_info: Dict[str, Any]):
        """注册 Web 客户端"""
        self.web_clients[client_id] = {"info": client_info, "last_seen": time.time()}
        logger.debug(f"Web客户端已注册: {client_id}")

    def unregister_client(self, client_id: str):
        """注销 Web 客户端"""
        if client_id in self.web_clients:
            del self.web_clients[client_id]
            logger.debug(f"Web客户端已注销: {client_id}")

    def send(self, event: NotificationEvent) -> bool:
        """准备通知数据到 event.metadata['web_notification_data']"""
        try:
            # 验证标题和消息非空
            if not event.title or not event.title.strip():
                logger.warning(f"Web通知标题为空，跳过发送: {event.id}")
                return False

            if not event.message or not event.message.strip():
                logger.warning(f"Web通知消息为空，跳过发送: {event.id}")
                return False

            # 验证web_timeout为正数
            timeout = max(self.config.web_timeout, 1)

            # 深拷贝metadata避免循环引用
            metadata_copy = dict(event.metadata) if event.metadata else {}

            # 构建通知数据
            notification_data = {
                "id": event.id,
                "type": "notification",
                "title": event.title.strip(),
                "message": event.message.strip(),
                "timestamp": event.timestamp,
                "config": {
                    "icon": self.config.web_icon,
                    "timeout": timeout,
                    "auto_request_permission": self.config.web_permission_auto_request,
                    "mobile_optimized": self.config.mobile_optimized,
                    "mobile_vibrate": self.config.mobile_vibrate,
                },
                "metadata": metadata_copy,
            }

            event.metadata["web_notification_data"] = notification_data

            logger.debug(f"Web通知数据已准备: {event.id}")
            return True

        except Exception as e:
            logger.error(f"准备Web通知失败: {e}")
            return False


class SoundNotificationProvider:
    """声音通知 - 准备音频数据到 event.metadata 供前端播放。"""

    def __init__(self, config):
        self.config = config
        self.sound_files = {"default": "deng[噔].mp3", "deng": "deng[噔].mp3"}

    def send(self, event: NotificationEvent) -> bool:
        """准备声音数据到 event.metadata['sound_notification_data']，静音时返回True但不播放"""
        try:
            if self.config.sound_mute:
                logger.debug("声音通知已静音，跳过播放")
                return True

            sound_file = self.sound_files.get(
                self.config.sound_file, self.sound_files["default"]
            )

            # 验证音量范围0.0-1.0
            volume = max(0.0, min(self.config.sound_volume, 1.0))

            # 深拷贝metadata避免循环引用
            metadata_copy = dict(event.metadata) if event.metadata else {}

            sound_data = {
                "id": event.id,
                "type": "sound",
                "file": sound_file,
                "volume": volume,
                "timestamp": event.timestamp,
                "metadata": metadata_copy,
            }

            event.metadata["sound_notification_data"] = sound_data

            logger.debug(
                f"声音通知数据已准备: {event.id} - {sound_file} (音量: {volume})"
            )
            return True

        except Exception as e:
            logger.error(f"准备声音通知失败: {e}")
            return False


class BarkNotificationProvider:
    """Bark iOS 推送 - 通过 HTTP POST 发送通知到 Bark 服务器。"""

    # 【优化】类级别常量：元数据保留键（所有实例共享，不可变）
    # 说明：
    # - 这些键由本提供者负责构建/控制，避免 event.metadata 覆盖导致请求体不一致
    # - Bark 常见参数是 url/copy（而不是 action），这里也纳入保留键集合
    _RESERVED_KEYS = frozenset(
        {"title", "body", "device_key", "icon", "action", "url", "copy"}
    )

    # 【安全】脱敏规则：避免在日志/调试信息中泄露 APNs device token 等敏感标识
    _APNS_DEVICE_URL_RE = re.compile(
        r"(https://api\.push\.apple\.com/3/device/)[0-9a-fA-F]{16,}"
    )
    _LONG_HEX_RE = re.compile(r"\b[0-9a-fA-F]{32,}\b")
    _BRACKET_TOKEN_RE = re.compile(r"\[([A-Za-z0-9]{16,})\]")

    @classmethod
    def _sanitize_error_text(cls, text: str) -> str:
        """脱敏错误文本中的敏感 token"""
        if not text:
            return text
        sanitized = cls._APNS_DEVICE_URL_RE.sub(r"\1<redacted>", text)
        sanitized = cls._LONG_HEX_RE.sub("<redacted_hex>", sanitized)
        sanitized = cls._BRACKET_TOKEN_RE.sub("[<redacted_key>]", sanitized)
        return sanitized

    def __init__(self, config):
        """初始化 Session 连接池（3次重试）"""
        self.config = config
        self.session = requests.Session()
        adapter = HTTPAdapter(max_retries=3)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)

        # 【优化】设置默认 headers（避免每次请求重复创建）
        self.session.headers.update(
            {
                "Content-Type": "application/json",
                "User-Agent": "AI-Intervention-Agent",
            }
        )

    def send(self, event: NotificationEvent) -> bool:
        """HTTP POST 发送通知到 Bark，返回成功与否"""
        try:
            if not self.config.bark_enabled:
                logger.debug("Bark通知已禁用")
                return False

            # 验证配置格式和完整性
            if not self.config.bark_url or not self.config.bark_device_key:
                logger.warning("Bark配置不完整，跳过发送")
                return False

            # 验证 URL 格式（基本检查）
            if not (
                self.config.bark_url.startswith("http://")
                or self.config.bark_url.startswith("https://")
            ):
                logger.error(f"Bark URL 格式无效: {self.config.bark_url}")
                return False

            # 【优化】提前 strip 并缓存，避免重复调用
            device_key_stripped = self.config.bark_device_key.strip()
            title_stripped = event.title.strip() if event.title else ""
            message_stripped = event.message.strip() if event.message else ""

            # 验证 device_key 不为空字符串
            if not device_key_stripped:
                logger.error("Bark device_key 为空字符串")
                return False

            # 验证标题和消息非空
            if not title_stripped:
                logger.warning(f"Bark通知标题为空，跳过发送: {event.id}")
                return False

            if not message_stripped:
                logger.warning(f"Bark通知消息为空，跳过发送: {event.id}")
                return False

            # 使用缓存的 strip 结果
            bark_data = {
                "title": title_stripped,
                "body": message_stripped,
                "device_key": device_key_stripped,
            }

            # 只在有值时添加可选字段
            if self.config.bark_icon:
                bark_data["icon"] = self.config.bark_icon

            # 点击行为：
            # - 配置里的 bark_action 是枚举（none/url/copy），不是“动作 URL”
            # - Bark 常见实现使用 url/copy 字段；发送 action="none/url/copy" 可能触发服务端 4xx
            bark_action = (self.config.bark_action or "").strip()
            if bark_action and bark_action != "none":
                if bark_action in ("url", "copy"):
                    if bark_action == "url":
                        # 优先从事件元数据中取 URL（例如 web_ui_url/url/action_url）
                        url_value = None
                        if event.metadata:
                            for key in ("url", "web_ui_url", "action_url", "link"):
                                value = event.metadata.get(key)
                                if isinstance(value, str) and value.strip():
                                    url_value = value.strip()
                                    break

                        if url_value:
                            bark_data["url"] = url_value
                        else:
                            # 不视为错误：没有 URL 也可以正常推送
                            logger.debug(
                                f"Bark 点击行为为 url，但未提供可用链接，已忽略: {event.id}"
                            )
                    else:
                        # copy：默认复制通知正文；如元数据提供 copy/copy_text，则优先使用
                        copy_value = None
                        if event.metadata:
                            for key in ("copy", "copy_text", "copyContent"):
                                value = event.metadata.get(key)
                                if isinstance(value, str) and value.strip():
                                    copy_value = value.strip()
                                    break
                        bark_data["copy"] = copy_value or message_stripped
                else:
                    # 兼容旧用法：直接将 bark_action 当作 URL（仅当其像 URL）
                    if bark_action.startswith("http://") or bark_action.startswith(
                        "https://"
                    ):
                        bark_data["url"] = bark_action
                    else:
                        # 未知值直接忽略，避免发送无效字段导致请求失败
                        logger.debug(
                            f"未知 bark_action='{bark_action}'，已忽略: {event.id}"
                        )

            # 添加元数据时跳过保留键（防止覆盖核心字段）
            if event.metadata:
                for key, value in event.metadata.items():
                    # 跳过保留键，防止元数据覆盖核心配置
                    if key in self._RESERVED_KEYS:
                        logger.warning(f"跳过元数据中的保留键: {key}")
                        continue

                    # 【优化】简化序列化逻辑，依赖 requests 的 json 参数
                    if isinstance(
                        value, (str, int, float, bool, type(None), list, dict)
                    ):
                        # 基本类型和容器类型直接添加，由 requests 处理序列化
                        # 如果 requests 序列化失败会抛出异常，被外层 catch
                        bark_data[key] = value
                    else:
                        # 其他复杂类型转为字符串
                        bark_data[key] = str(value)

            # 【可配置】Bark 请求超时（秒）
            try:
                timeout_seconds = max(int(getattr(self.config, "bark_timeout", 10)), 1)
            except (TypeError, ValueError):
                timeout_seconds = 10

            # 【优化】使用 Session 默认 headers（在 __init__ 中设置）
            response = self.session.post(
                self.config.bark_url,
                json=bark_data,
                timeout=timeout_seconds,
            )

            # 接受所有2xx状态码为成功
            if 200 <= response.status_code < 300:
                logger.info(
                    f"Bark通知发送成功: {event.id} (状态码: {response.status_code})"
                )
                return True
            else:
                # Bark 往往返回 JSON（code/message）；尽量解析以便排查
                try:
                    error_detail = response.json()
                except Exception:
                    error_detail = response.text
                sanitized_detail = self._sanitize_error_text(str(error_detail))

                # 仅在 debug / 测试事件时将错误细节写入 event.metadata，便于上层展示
                try:
                    is_debug = bool(getattr(self.config, "debug", False))
                    is_test_event = bool(
                        isinstance(event.metadata, dict) and event.metadata.get("test")
                    )
                    if is_debug or is_test_event:
                        event.metadata["bark_error"] = {
                            "status_code": response.status_code,
                            "detail": sanitized_detail[:800],
                        }
                except Exception:
                    # 不让调试信息写入影响主流程
                    pass

                logger.error(
                    f"Bark通知发送失败: {response.status_code} - {sanitized_detail[:800]}"
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
    """系统通知 - 通过 plyer 库发送跨平台桌面通知（可选依赖）。"""

    def __init__(self, config):
        """检查 plyer 库是否可用"""
        self.config = config
        self._notify: Callable[..., Any] | None = None
        self._check_system_support()

    def _check_system_support(self):
        """尝试导入 plyer 设置 supported 状态"""
        try:
            from plyer import notification as plyer_notification

            self._notify = plyer_notification.notify
            self.supported = True
            logger.debug("系统通知支持已启用")
        except ImportError:
            self._notify = None
            self.supported = False
            logger.debug("系统通知不支持（缺少plyer库）")

    def send(self, event: NotificationEvent) -> bool:
        """调用 plyer 发送系统通知"""
        try:
            if not self.supported:
                logger.debug("系统通知不支持，跳过发送")
                return False
            if self._notify is None:
                logger.debug("系统通知未初始化 notify 句柄，跳过发送")
                return False

            # 使用浮点除法保留小数精度，限制最小值为1.0秒
            timeout_seconds = max(self.config.web_timeout / 1000, 1.0)

            self._notify(
                title=event.title,
                message=event.message,
                app_name="AI Intervention Agent",
                timeout=timeout_seconds,
            )

            logger.debug(f"系统通知发送成功: {event.id}")
            return True

        except Exception as e:
            logger.error(f"系统通知发送失败: {e}")
            return False


def create_notification_providers(config) -> Dict[NotificationType, Any]:
    """工厂函数 - 根据配置启用状态创建提供者实例"""
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
    """创建提供者并注册到全局 notification_manager"""
    from notification_manager import notification_manager

    providers = create_notification_providers(config)

    for notification_type, provider in providers.items():
        notification_manager.register_provider(notification_type, provider)

    logger.info("通知系统初始化完成")
    return notification_manager
