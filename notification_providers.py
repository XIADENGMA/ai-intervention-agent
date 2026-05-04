"""通知提供者实现 - Web/Sound/Bark/System 四种通知方式。

所有提供者实现 send(event) -> bool 接口，由 NotificationManager 调用。
"""

import re
import string
import sys
import time
from abc import ABC, abstractmethod
from collections.abc import Callable
from importlib.util import find_spec
from typing import Any

import httpx

from enhanced_logging import EnhancedLogger
from notification_models import NotificationEvent, NotificationType

logger = EnhancedLogger(__name__)


# ---------------------------------------------------------------------------
# Bark URL 模板渲染辅助
#
# 设计目标：
# - 用户在配置里写 "http://ai.local:8080/?task_id={task_id}" 这种模板时，
#   Bark 通知能正确渲染并嵌入 metadata。
# - 任何缺失的占位符（例如模板里有 {weird_key} 但 metadata 没给）原样保留，
#   绝不抛 KeyError，从而避免一条配置错误导致整个 Bark 通知发不出去。
# - 任何无法被序列化为字符串的值（None / dict / list 等）一律退化为空串，
#   防止 Pythonic 表达污染 URL（例如 "[1, 2]"）。
# ---------------------------------------------------------------------------


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
    """安全渲染 Bark 点击 URL 模板。

    - 模板为空 / 渲染异常时返回空串（调用方应判空跳过 url 字段）。
    - 不会抛出 KeyError；缺失的占位符保持 "{name}" 字面量（便于排查）。
    """
    tpl = (template or "").strip()
    if not tpl:
        return ""

    safe_params = _BarkSafeFormatDict(
        {key: _coerce_bark_format_value(val) for key, val in params.items()}
    )

    try:
        return _BARK_TEMPLATE_FORMATTER.vformat(tpl, (), safe_params).strip()
    except (ValueError, IndexError) as exc:
        # 例如未闭合的 "{"、位置参数引用，记 warn 但不抛
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
            logger.error(f"准备声音通知失败: {e}", exc_info=True)
            return False


class BarkNotificationProvider(BaseNotificationProvider):
    """Bark iOS 推送 - 通过 HTTP POST 发送通知到 Bark 服务器。"""

    _RESERVED_KEYS = frozenset(
        {"title", "body", "device_key", "icon", "action", "url", "copy"}
    )

    # 允许转发到 Bark 服务器的元数据键白名单（防止内部数据泄漏到第三方）
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
        except Exception:
            pass

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

                        # metadata 没有提供 URL 时，回退到 bark_url_template
                        # 设计：模板只在缺省时生效，避免覆盖调用方明确指定的 URL
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
                                if rendered.startswith(("http://", "https://")):
                                    url_value = rendered
                                elif rendered:
                                    logger.warning(
                                        f"bark_url_template 渲染结果不是合法 URL，已忽略: {rendered!r}"
                                    )

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
                    if bark_action.startswith(("http://", "https://")):
                        bark_data["url"] = bark_action
                    else:
                        # 未知值直接忽略，避免发送无效字段导致请求失败
                        logger.debug(
                            f"未知 bark_action='{bark_action}'，已忽略: {event.id}"
                        )

            # 白名单机制：仅转发允许的元数据键，防止内部数据泄漏到第三方 Bark 服务
            if event.metadata:
                for key, value in event.metadata.items():
                    if key in self._RESERVED_KEYS:
                        continue
                    if key not in self._ALLOWED_METADATA_KEYS:
                        continue
                    if isinstance(value, (str, int, float, bool, type(None))):
                        bark_data[key] = value

            # 【可配置】Bark 请求超时（秒）
            try:
                timeout_seconds = max(int(getattr(self.config, "bark_timeout", 10)), 1)
            except (TypeError, ValueError):
                timeout_seconds = 10

            # 默认 headers 已在 __init__ 中设置
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
            # macOS 下 plyer 依赖 pyobjus；若缺失，plyer 在导入阶段会向 stderr 打印 traceback，
            # 但系统通知本身也无法使用。这里提前探测并跳过导入，避免在 scripts/manual_test.py 等场景产生噪声。
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

    # plyer.notify(..., timeout=N) 的 N 是「通知显示时长（秒）」，**不是**
    # 发送超时——plyer 没有发送超时入口，调用过程是同步阻塞到底层平台 API
    # （macOS osascript / Windows balloon notification / Linux libnotify）
    # 返回。
    #
    # 这里复用 ``NotificationManager._process_event`` 里的
    # ``as_completed(timeout=bark_timeout + buffer)`` 作为兜底：
    # 如果底层平台 API 卡住超过 15s，``as_completed`` 会抛 ``TimeoutError``
    # 并把这条 future 视为失败（``cancel()`` 对运行中任务无效，但 future
    # 不会再被等下去）。
    #
    # 故意保持 ``timeout=10``（10 秒显示时长）而不是更长：超过 10s 仍未消失
    # 的桌面通知大概率被用户错过，且会和后续 task 的通知打架。
    _DISPLAY_DURATION_SECONDS = 10

    def send(self, event: NotificationEvent) -> bool:
        """调用 plyer 发送系统通知

        注意：``timeout`` 参数指通知 banner 在屏幕上显示的时长，不是发送超时。
        plyer 自身没有发送超时机制；如果底层平台 API 卡住，依赖
        ``NotificationManager._process_event`` 的 ``as_completed`` 兜底
        （见 ``notification_manager._AS_COMPLETED_TIMEOUT_BUFFER_SECONDS``）。
        """
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
    from notification_manager import notification_manager

    providers = create_notification_providers(config)

    for notification_type, provider in providers.items():
        notification_manager.register_provider(notification_type, provider)

    logger.info("通知系统初始化完成")
    return notification_manager
