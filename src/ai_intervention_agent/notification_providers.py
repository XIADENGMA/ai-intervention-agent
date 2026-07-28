"""通知提供者实现 - Web/Sound/Bark/System 四种通知方式。"""

import re
import string
import sys
import time
from abc import ABC, abstractmethod
from collections.abc import Callable
from importlib.util import find_spec
from typing import Any

from ai_intervention_agent.enhanced_logging import EnhancedLogger
from ai_intervention_agent.notification_models import (
    NotificationEvent,
    NotificationType,
)

logger = EnhancedLogger(__name__)


_BARK_CLICK_URL_SCHEME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9+.\-]*://\S+$")


def _is_acceptable_bark_click_url(url: str) -> bool:
    """判断字符串是否可作为 Bark 点击跳转 URL（任意 ``scheme://`` 形式）。"""
    if not isinstance(url, str):
        return False
    return bool(_BARK_CLICK_URL_SCHEME_RE.match(url))


def _bark_url_is_loopback(url: str) -> bool:
    """Bark provider 内部 helper：判断渲染出的点击 URL 是否回环地址。"""
    if not isinstance(url, str) or not url:
        return False
    if not url.lower().startswith(("http://", "https://")):
        return False
    try:
        from ai_intervention_agent.server_config import is_loopback_url
    except Exception:
        return False
    try:
        return bool(is_loopback_url(url))
    except Exception:
        return False


class _LazyHttpx:
    """延迟加载 httpx，同时保留 ``notification_providers.httpx.X`` 访问形态。"""

    def __getattr__(self, name: str) -> Any:
        import httpx as real_httpx

        globals()["httpx"] = real_httpx
        return getattr(real_httpx, name)


httpx: Any = _LazyHttpx()


class _BarkSafeFormatDict(dict):
    """str.format_map() 的兜底字典：未命中的 key 原样返回 "{key}"。"""

    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


_BARK_TEMPLATE_FORMATTER = string.Formatter()


def _coerce_bark_format_value(value: Any) -> str:
    """把任意 value 转成对 URL 友好的字符串；非标量一律视为空。"""
    if value is None:
        return ""
    if isinstance(value, (str, int, float, bool)):
        return str(value)
    return ""


def render_bark_url_template(template: str, params: dict[str, Any]) -> str:
    """安全渲染 Bark 点击 URL 模板。"""
    tpl = (template or "").strip()
    if not tpl:
        return ""

    safe_params = _BarkSafeFormatDict(
        {key: _coerce_bark_format_value(val) for key, val in params.items()}
    )

    try:
        return _BARK_TEMPLATE_FORMATTER.vformat(tpl, (), safe_params).strip()
    except (ValueError, IndexError) as exc:
        logger.warning(
            f"渲染 Bark URL 模板失败: template={tpl!r} error={exc}; 已退化为空 URL"
        )
        return ""


class BaseNotificationProvider(ABC):
    """通知 Provider 抽象基类（阶段 A：统一接口与可观测性基线）。"""

    notification_type: NotificationType

    def __init__(self, config):
        self.config = config

    @abstractmethod
    def send(self, event: NotificationEvent) -> bool:
        """发送/准备通知。失败返回 False，异常应在内部捕获并降级为 False。"""

    def close(self) -> None:
        """释放资源（可选）。默认无操作。"""
        return


class WebNotificationProvider(BaseNotificationProvider):
    """Web 浏览器通知 - 准备通知数据到 event.metadata 供前端轮询展示。"""

    def __init__(self, config):
        super().__init__(config)
        self.notification_type = NotificationType.WEB
        self.web_clients: dict[str, Any] = {}

    def register_client(self, client_id: str, client_info: dict[str, Any]):
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
            if not event.title or not event.title.strip():
                logger.warning(f"Web通知标题为空，跳过发送: {event.id}")
                return False

            if not event.message or not event.message.strip():
                logger.warning(f"Web通知消息为空，跳过发送: {event.id}")
                return False

            timeout = max(self.config.web_timeout, 1)

            metadata_copy = event.metadata.copy() if event.metadata else {}

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
            logger.error(f"准备Web通知失败: {e}", exc_info=True)
            return False


class SoundNotificationProvider(BaseNotificationProvider):
    """声音通知 - 准备音频数据到 event.metadata 供前端播放。"""

    def __init__(self, config):
        super().__init__(config)
        self.notification_type = NotificationType.SOUND
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

            volume = max(0.0, min(self.config.sound_volume, 1.0))

            metadata_copy = event.metadata.copy() if event.metadata else {}

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
            logger.error(f"准备声音通知失败: {e}", exc_info=True)
            return False


class BarkNotificationProvider(BaseNotificationProvider):
    """Bark iOS 推送 - 通过 HTTP POST 发送通知到 Bark 服务器。"""

    _RESERVED_KEYS = frozenset(
        {"title", "body", "device_key", "icon", "action", "url", "copy"}
    )

    _ALLOWED_METADATA_KEYS = frozenset(
        {
            "group",
            "level",
            "badge",
            "autoCopy",
            "isArchive",
            "sound",
            "event",
            "count",
            "source",
        }
    )

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
        super().__init__(config)
        self.notification_type = NotificationType.BARK
        transport = httpx.HTTPTransport(retries=3)
        self.session = httpx.Client(
            transport=transport,
            headers={
                "Content-Type": "application/json",
                "User-Agent": "AI-Intervention-Agent",
            },
        )

    def close(self) -> None:
        """关闭 HTTP Session，释放连接池资源（幂等）。"""
        try:
            self.session.close()
        except Exception as e:
            logger.debug(
                "[R117] BarkNotificationProvider.close() httpx.Client.close() "
                f"raised (suppressed to keep shutdown chain intact): "
                f"{type(e).__name__}: {self._sanitize_error_text(str(e))}",
            )

    def send(self, event: NotificationEvent) -> bool:
        """HTTP POST 发送通知到 Bark，返回成功与否"""
        try:
            if not self.config.bark_enabled:
                logger.debug("Bark通知已禁用")
                return False

            if not self.config.bark_url or not self.config.bark_device_key:
                logger.warning("Bark配置不完整，跳过发送")
                return False

            if not (
                self.config.bark_url.startswith("http://")
                or self.config.bark_url.startswith("https://")
            ):
                logger.error(f"Bark URL 格式无效: {self.config.bark_url}")
                return False

            device_key_stripped = self.config.bark_device_key.strip()
            title_stripped = event.title.strip() if event.title else ""
            message_stripped = event.message.strip() if event.message else ""

            if not device_key_stripped:
                logger.error("Bark device_key 为空字符串")
                return False

            if not title_stripped:
                logger.warning(f"Bark通知标题为空，跳过发送: {event.id}")
                return False

            if not message_stripped:
                logger.warning(f"Bark通知消息为空，跳过发送: {event.id}")
                return False

            bark_data = {
                "title": title_stripped,
                "body": message_stripped,
                "device_key": device_key_stripped,
            }

            if self.config.bark_icon:
                bark_data["icon"] = self.config.bark_icon

            bark_action = (self.config.bark_action or "").strip()
            if bark_action and bark_action != "none":
                if bark_action in ("url", "copy"):
                    if bark_action == "url":
                        url_value = None
                        if event.metadata:
                            for key in ("url", "web_ui_url", "action_url", "link"):
                                value = event.metadata.get(key)
                                if isinstance(value, str) and value.strip():
                                    candidate = value.strip()
                                    if not _is_acceptable_bark_click_url(candidate):
                                        logger.warning(
                                            f"event.metadata['{key}']={candidate!r} "
                                            "不是合法跳转 URL，已忽略此候选"
                                        )
                                        continue
                                    if _bark_url_is_loopback(candidate):
                                        logger.warning(
                                            f"event.metadata['{key}']={candidate!r} 是回环地址，"
                                            "手机端 Bark 无法跳转，已忽略此候选"
                                        )
                                        continue
                                    url_value = candidate
                                    break

                        if not url_value:
                            template = (
                                getattr(self.config, "bark_url_template", "") or ""
                            )
                            if template:
                                base_url = ""
                                if event.metadata and isinstance(
                                    event.metadata.get("base_url"), str
                                ):
                                    base_url = event.metadata.get("base_url", "")
                                params: dict[str, Any] = {
                                    "task_id": (event.metadata or {}).get(
                                        "task_id", ""
                                    ),
                                    "event_id": event.id or "",
                                    "base_url": (base_url or "").rstrip("/"),
                                }
                                rendered = render_bark_url_template(template, params)

                                if _is_acceptable_bark_click_url(rendered):
                                    if _bark_url_is_loopback(rendered):
                                        logger.warning(
                                            f"bark_url_template 渲染结果命中回环地址 {rendered!r}，"
                                            "已抑制 url 字段；建议将 web_ui.host 改为 0.0.0.0 "
                                            "或在设置面板配置 external_base_url 为 LAN/公网 URL"
                                        )
                                    else:
                                        url_value = rendered
                                elif rendered:
                                    logger.warning(
                                        f"bark_url_template 渲染结果不是合法 URL，已忽略: {rendered!r}"
                                    )

                        if url_value:
                            bark_data["url"] = url_value
                        else:
                            logger.debug(
                                f"Bark 点击行为为 url，但未提供可用链接，已忽略: {event.id}"
                            )
                    else:
                        copy_value = None
                        if event.metadata:
                            for key in ("copy", "copy_text", "copyContent"):
                                value = event.metadata.get(key)
                                if isinstance(value, str) and value.strip():
                                    copy_value = value.strip()
                                    break
                        bark_data["copy"] = copy_value or message_stripped
                else:
                    if bark_action.startswith(("http://", "https://")):
                        if _bark_url_is_loopback(bark_action):
                            logger.warning(
                                f"bark_action 是回环地址 {bark_action!r}，已抑制 url 字段；"
                                "请改用具体的 LAN/公网 URL 或 url/copy 枚举"
                            )
                        else:
                            bark_data["url"] = bark_action
                    else:
                        logger.debug(
                            f"未知 bark_action='{bark_action}'，已忽略: {event.id}"
                        )

            if event.metadata:
                for key, value in event.metadata.items():
                    if key in self._RESERVED_KEYS:
                        continue
                    if key not in self._ALLOWED_METADATA_KEYS:
                        continue
                    if isinstance(value, (str, int, float, bool, type(None))):
                        bark_data[key] = value

            try:
                timeout_seconds = max(int(getattr(self.config, "bark_timeout", 10)), 1)
            except (TypeError, ValueError):
                timeout_seconds = 10

            response = self.session.post(
                self.config.bark_url,
                json=bark_data,
                timeout=timeout_seconds,
            )

            if 200 <= response.status_code < 300:
                logger.info(
                    f"Bark通知发送成功: {event.id} (状态码: {response.status_code})"
                )
                return True
            else:
                try:
                    error_detail = response.json()
                except Exception:
                    error_detail = response.text
                sanitized_detail = self._sanitize_error_text(str(error_detail))

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
                    pass

                logger.error(
                    f"Bark通知发送失败: {response.status_code} - {sanitized_detail[:800]}"
                )
                return False

        except httpx.TimeoutException:
            logger.error(f"Bark通知发送超时: {event.id}", exc_info=True)
            return False
        except httpx.HTTPError as e:
            logger.error(f"Bark通知发送网络错误: {e}", exc_info=True)
            return False
        except Exception as e:
            logger.error(f"Bark通知发送失败: {e}", exc_info=True)
            return False


class SystemNotificationProvider(BaseNotificationProvider):
    """系统通知 - 通过 plyer 库发送跨平台桌面通知（可选依赖）。"""

    def __init__(self, config):
        """检查 plyer 库是否可用"""
        super().__init__(config)
        self.notification_type = NotificationType.SYSTEM
        self._notify: Callable[..., Any] | None = None
        self._check_system_support()

    def _check_system_support(self):
        """尝试导入 plyer 设置 supported 状态"""
        try:
            if sys.platform == "darwin" and find_spec("pyobjus") is None:
                self._notify = None
                self.supported = False
                logger.debug("系统通知不支持（macOS 缺少可选依赖 pyobjus）")
                return

            from plyer import notification as plyer_notification

            self._notify = plyer_notification.notify
            self.supported = True
            logger.debug("系统通知支持已启用")
        except ImportError:
            self._notify = None
            self.supported = False
            logger.debug("系统通知不支持（缺少plyer库）")

    _DISPLAY_DURATION_SECONDS = 10

    def send(self, event: NotificationEvent) -> bool:
        """调用 plyer 发送系统通知"""
        try:
            if not self.supported:
                logger.debug("系统通知不支持，跳过发送")
                return False
            if self._notify is None:
                logger.debug("系统通知未初始化 notify 句柄，跳过发送")
                return False

            self._notify(
                title=event.title,
                message=event.message,
                app_name="AI Intervention Agent",
                timeout=self._DISPLAY_DURATION_SECONDS,
            )

            logger.debug(f"系统通知发送成功: {event.id}")
            return True

        except Exception as e:
            logger.error(f"系统通知发送失败: {e}", exc_info=True)
            return False


def create_notification_providers(
    config,
) -> dict[NotificationType, BaseNotificationProvider]:
    """工厂函数 - 根据配置启用状态创建提供者实例"""
    providers: dict[NotificationType, BaseNotificationProvider] = {}

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
        logger.debug(f"系统通知提供者创建失败: {e}", exc_info=True)

    logger.info(f"已创建 {len(providers)} 个通知提供者")
    return providers


def initialize_notification_system(config):
    """创建提供者并注册到全局 notification_manager"""
    from ai_intervention_agent.notification_manager import notification_manager

    providers = create_notification_providers(config)

    for notification_type, provider in providers.items():
        notification_manager.register_provider(notification_type, provider)

    logger.info("通知系统初始化完成")
    return notification_manager
