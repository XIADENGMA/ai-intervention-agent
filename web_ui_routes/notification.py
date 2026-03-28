"""通知路由 Mixin — Bark 测试、新任务通知、通知配置读写、反馈提示语。"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any, Dict

from flask import jsonify, request
from flask.typing import ResponseReturnValue

from config_manager import get_config
from config_utils import clamp_value
from enhanced_logging import EnhancedLogger
from i18n import msg

try:
    from notification_manager import (
        NotificationEvent,
        NotificationTrigger,
        NotificationType,
        notification_manager,
    )
    from notification_providers import BarkNotificationProvider

    NOTIFICATION_AVAILABLE = True
except ImportError:
    NOTIFICATION_AVAILABLE = False

if TYPE_CHECKING:
    from flask import Flask

logger = EnhancedLogger(__name__)


class NotificationRoutesMixin:
    """提供 5 个通知相关 API 路由，由 WebFeedbackUI 通过 MRO 继承。"""

    if TYPE_CHECKING:
        app: Flask

    def _setup_notification_routes(self) -> None:  # noqa: C901
        @self.app.route("/api/test-bark", methods=["POST"])
        def test_bark_notification() -> ResponseReturnValue:
            """测试 Bark 推送通知
            ---
            tags:
              - Notification
            consumes:
              - application/json
            parameters:
              - in: body
                name: body
                required: true
                schema:
                  type: object
                  required:
                    - bark_device_key
                  properties:
                    bark_url:
                      type: string
                      default: "https://api.day.app/push"
                    bark_device_key:
                      type: string
                      description: Bark 设备密钥
                    bark_icon:
                      type: string
                    bark_action:
                      type: string
                      default: "none"
            responses:
              200:
                description: 测试通知发送成功
                schema:
                  type: object
                  properties:
                    status:
                      type: string
                      example: success
                    message:
                      type: string
              400:
                description: 设备密钥为空
              500:
                description: 发送失败或通知系统不可用
            """
            try:
                data = request.json or {}
                bark_url = data.get("bark_url", "https://api.day.app/push")
                bark_device_key = data.get("bark_device_key", "")
                bark_icon = data.get("bark_icon", "")
                bark_action = data.get("bark_action", "none")

                if not bark_device_key:
                    return jsonify(
                        {"status": "error", "message": msg("notify.deviceKeyEmpty")}
                    ), 400

                try:
                    if not NOTIFICATION_AVAILABLE:
                        raise ImportError(msg("notify.systemUnavailable"))

                    class TempConfig:
                        def __init__(self) -> None:
                            self.bark_enabled = True
                            self.bark_url = bark_url
                            self.bark_device_key = bark_device_key
                            self.bark_icon = bark_icon
                            self.bark_action = bark_action

                    temp_config = TempConfig()
                    bark_provider = BarkNotificationProvider(temp_config)

                    test_event = NotificationEvent(
                        id=f"test_bark_{int(time.time())}",
                        title="AI Intervention Agent 测试",
                        message="这是一个 Bark 通知测试，如果收到此消息，说明配置正确。",
                        trigger=NotificationTrigger.IMMEDIATE,
                        types=[NotificationType.BARK],
                        metadata={"test": True},
                    )

                    success = bark_provider.send(test_event)

                    if success:
                        return jsonify(
                            {
                                "status": "success",
                                "message": msg("notify.testSuccess"),
                            }
                        )
                    else:
                        bark_error = None
                        try:
                            if isinstance(test_event.metadata, dict):
                                bark_error = test_event.metadata.get("bark_error")
                        except Exception:
                            bark_error = None

                        if isinstance(bark_error, dict) and bark_error.get("detail"):
                            detail = str(bark_error.get("detail"))[:300]
                            status_code = bark_error.get("status_code")
                            status_hint = (
                                f"(HTTP {status_code}) " if status_code else ""
                            )
                            return jsonify(
                                {
                                    "status": "error",
                                    "message": msg(
                                        "notify.sendFailedDetail",
                                        detail=f"{status_hint}{detail}",
                                    ),
                                }
                            ), 500
                        return jsonify(
                            {
                                "status": "error",
                                "message": msg("notify.sendFailedConfig"),
                            }
                        ), 500

                except ImportError as e:
                    logger.error(f"导入通知系统失败: {e}", exc_info=True)
                    return jsonify(
                        {"status": "error", "message": msg("notify.systemUnavailable")}
                    ), 500

            except Exception as e:
                logger.error(f"Bark 测试通知失败: {e}", exc_info=True)
                return jsonify(
                    {"status": "error", "message": msg("notify.testFailed")}
                ), 500

        @self.app.route("/api/notify-new-tasks", methods=["POST"])
        def notify_new_tasks() -> ResponseReturnValue:
            """触发新任务 Bark 推送通知
            ---
            tags:
              - Notification
            consumes:
              - application/json
            parameters:
              - in: body
                name: body
                schema:
                  type: object
                  properties:
                    count:
                      type: integer
                      description: 新任务数量
                    taskIds:
                      type: array
                      items:
                        type: string
                      description: 新任务 ID 列表
            responses:
              200:
                description: 通知已触发或已跳过（优雅降级）
                schema:
                  type: object
                  properties:
                    status:
                      type: string
                      enum: [success, skipped]
                    event_id:
                      type: string
                    message:
                      type: string
              500:
                description: 触发失败
            """
            try:
                data = request.json or {}

                raw_task_ids = data.get("taskIds", data.get("task_ids", []))
                task_ids: list[str] = []
                if isinstance(raw_task_ids, list):
                    for item in raw_task_ids[:50]:
                        if item is None:
                            continue
                        s = str(item)
                        if not s:
                            continue
                        task_ids.append(s[:200])

                raw_count = data.get("count")
                count = 0
                if isinstance(raw_count, (int, float)):
                    try:
                        count = int(raw_count)
                    except Exception:
                        count = 0
                if count <= 0:
                    count = len(task_ids)

                if count <= 0:
                    return jsonify(
                        {"status": "skipped", "message": msg("notify.countZero")}
                    )

                if not NOTIFICATION_AVAILABLE:
                    return jsonify(
                        {"status": "skipped", "message": msg("notify.systemDegraded")}
                    )

                try:
                    notification_manager.refresh_config_from_file()
                except Exception:
                    pass

                cfg = getattr(notification_manager, "config", None)
                if not cfg or not getattr(cfg, "enabled", True):
                    return jsonify(
                        {"status": "skipped", "message": msg("notify.globalOff")}
                    )

                if not getattr(cfg, "bark_enabled", False):
                    return jsonify(
                        {"status": "skipped", "message": msg("notify.barkDisabled")}
                    )

                if not getattr(cfg, "bark_device_key", ""):
                    return jsonify(
                        {"status": "skipped", "message": msg("notify.barkKeyEmpty")}
                    )

                title = "AI Intervention Agent"
                message = (
                    f"新任务已添加: {task_ids[0]}"
                    if count == 1 and task_ids
                    else f"收到 {count} 个新任务"
                )

                event_id = notification_manager.send_notification(
                    title=title,
                    message=message,
                    trigger=NotificationTrigger.IMMEDIATE,
                    types=[NotificationType.BARK],
                    metadata={
                        "source": "web_ui",
                        "event": "new_tasks",
                        "count": count,
                        "task_ids": task_ids,
                    },
                    priority="normal",
                )

                if not event_id:
                    return jsonify(
                        {"status": "skipped", "message": msg("notify.notTriggered")}
                    )

                return jsonify({"status": "success", "event_id": event_id})
            except Exception as e:
                logger.error(f"触发新任务通知失败: {e}", exc_info=True)
                return jsonify(
                    {"status": "error", "message": msg("notify.triggerFailed")}
                ), 500

        @self.app.route("/api/update-notification-config", methods=["POST"])
        def update_notification_config() -> ResponseReturnValue:
            """更新通知配置
            ---
            tags:
              - Notification
            consumes:
              - application/json
            parameters:
              - in: body
                name: body
                schema:
                  type: object
                  properties:
                    enabled:
                      type: boolean
                    webEnabled:
                      type: boolean
                    soundEnabled:
                      type: boolean
                    soundVolume:
                      type: integer
                      minimum: 0
                      maximum: 100
                    barkEnabled:
                      type: boolean
                    barkUrl:
                      type: string
                    barkDeviceKey:
                      type: string
                    barkIcon:
                      type: string
                    barkAction:
                      type: string
                    macosNativeEnabled:
                      type: boolean
            responses:
              200:
                description: 配置已更新
                schema:
                  type: object
                  properties:
                    status:
                      type: string
                      example: success
                    message:
                      type: string
              500:
                description: 更新失败
            """
            try:
                data = request.json or {}
                if not isinstance(data, dict):
                    data = {}

                try:
                    if not NOTIFICATION_AVAILABLE:
                        raise ImportError(msg("notify.systemUnavailable"))

                    config_mgr = get_config()
                    notification_config = dict(config_mgr.get_section("notification"))

                    def normalize_sound_volume(raw_value: Any) -> int:
                        try:
                            return int(
                                clamp_value(float(raw_value), 0, 100, "sound_volume")
                            )
                        except (TypeError, ValueError):
                            return int(notification_config.get("sound_volume", 80))

                    def normalize_web_timeout(raw_value: Any) -> int:
                        try:
                            return int(
                                clamp_value(float(raw_value), 1, 600000, "web_timeout")
                            )
                        except (TypeError, ValueError):
                            return int(notification_config.get("web_timeout", 5000))

                    def normalize_string(raw_value: Any) -> str:
                        return "" if raw_value is None else str(raw_value)

                    def first_present(*keys: str) -> tuple[bool, Any]:
                        for key in keys:
                            if key in data:
                                return True, data.get(key)
                        return False, None

                    field_specs = [
                        (("enabled",), "enabled", "enabled", lambda v: v, lambda v: v),
                        (
                            ("webEnabled", "web_enabled"),
                            "web_enabled",
                            "web_enabled",
                            lambda v: v,
                            lambda v: v,
                        ),
                        (
                            ("webIcon", "web_icon"),
                            "web_icon",
                            "web_icon",
                            normalize_string,
                            normalize_string,
                        ),
                        (
                            ("webTimeout", "web_timeout"),
                            "web_timeout",
                            "web_timeout",
                            normalize_web_timeout,
                            normalize_web_timeout,
                        ),
                        (
                            ("autoRequestPermission", "auto_request_permission"),
                            "web_permission_auto_request",
                            "auto_request_permission",
                            lambda v: v,
                            lambda v: v,
                        ),
                        (
                            ("macosNativeEnabled", "macos_native_enabled"),
                            "macos_native_enabled",
                            "macos_native_enabled",
                            lambda v: v,
                            lambda v: v,
                        ),
                        (
                            ("soundEnabled", "sound_enabled"),
                            "sound_enabled",
                            "sound_enabled",
                            lambda v: v,
                            lambda v: v,
                        ),
                        (
                            ("soundFile", "sound_file"),
                            "sound_file",
                            "sound_file",
                            normalize_string,
                            normalize_string,
                        ),
                        (
                            ("soundMute", "sound_mute"),
                            "sound_mute",
                            "sound_mute",
                            lambda v: v,
                            lambda v: v,
                        ),
                        (
                            ("soundVolume", "sound_volume"),
                            "sound_volume",
                            "sound_volume",
                            lambda v: normalize_sound_volume(v) / 100.0,
                            normalize_sound_volume,
                        ),
                        (
                            ("mobileOptimized", "mobile_optimized"),
                            "mobile_optimized",
                            "mobile_optimized",
                            lambda v: v,
                            lambda v: v,
                        ),
                        (
                            ("mobileVibrate", "mobile_vibrate"),
                            "mobile_vibrate",
                            "mobile_vibrate",
                            lambda v: v,
                            lambda v: v,
                        ),
                        (
                            ("barkEnabled", "bark_enabled"),
                            "bark_enabled",
                            "bark_enabled",
                            lambda v: v,
                            lambda v: v,
                        ),
                        (
                            ("barkUrl", "bark_url"),
                            "bark_url",
                            "bark_url",
                            normalize_string,
                            normalize_string,
                        ),
                        (
                            ("barkDeviceKey", "bark_device_key"),
                            "bark_device_key",
                            "bark_device_key",
                            normalize_string,
                            normalize_string,
                        ),
                        (
                            ("barkIcon", "bark_icon"),
                            "bark_icon",
                            "bark_icon",
                            normalize_string,
                            normalize_string,
                        ),
                        (
                            ("barkAction", "bark_action"),
                            "bark_action",
                            "bark_action",
                            normalize_string,
                            normalize_string,
                        ),
                    ]

                    manager_updates: Dict[str, Any] = {}
                    changed_keys: list[str] = []
                    for (
                        request_keys,
                        manager_key,
                        config_key,
                        manager_cast,
                        config_cast,
                    ) in field_specs:
                        found, raw_value = first_present(*request_keys)
                        if not found:
                            continue
                        manager_updates[manager_key] = manager_cast(raw_value)
                        notification_config[config_key] = config_cast(raw_value)
                        changed_keys.append(config_key)

                    if not changed_keys:
                        logger.info("通知配置更新请求未包含可识别字段，已忽略")
                        return jsonify(
                            {
                                "status": "success",
                                "message": msg("notify.noUpdateFields"),
                            }
                        )

                    notification_manager.update_config_without_save(**manager_updates)
                    config_mgr.update_section("notification", notification_config)

                    logger.info("通知配置已更新到配置文件和内存")
                    return jsonify(
                        {"status": "success", "message": msg("notify.configUpdated")}
                    )

                except ImportError as e:
                    logger.error(f"导入配置系统失败: {e}", exc_info=True)
                    return jsonify(
                        {"status": "error", "message": msg("notify.configUnavailable")}
                    ), 500

            except Exception as e:
                logger.error(f"更新通知配置失败: {e}", exc_info=True)
                return jsonify(
                    {"status": "error", "message": msg("notify.updateFailed")}
                ), 500

        @self.app.route("/api/get-notification-config", methods=["GET"])
        def get_notification_config() -> ResponseReturnValue:
            """获取当前通知配置
            ---
            tags:
              - Notification
            responses:
              200:
                description: 通知配置
                schema:
                  type: object
                  properties:
                    status:
                      type: string
                      example: success
                    config:
                      type: object
                      description: 完整通知配置项
              500:
                description: 读取配置失败
            """
            try:
                config_mgr = get_config()
                notification_config = config_mgr.get_section("notification")

                return jsonify({"status": "success", "config": notification_config})

            except Exception as e:
                logger.error(f"获取通知配置失败: {e}", exc_info=True)
                return jsonify(
                    {"status": "error", "message": msg("notify.getFailed")}
                ), 500

        @self.app.route("/api/get-feedback-prompts", methods=["GET"])
        def get_feedback_prompts_api() -> ResponseReturnValue:
            """获取反馈提示语配置
            ---
            tags:
              - Feedback
            responses:
              200:
                description: 反馈提示语配置
                schema:
                  type: object
                  properties:
                    status:
                      type: string
                      example: success
                    config:
                      type: object
                      properties:
                        resubmit_prompt:
                          type: string
                          description: 错误/超时时的提示语
                        prompt_suffix:
                          type: string
                          description: 追加到反馈末尾的提示语
                    meta:
                      type: object
                      properties:
                        config_file:
                          type: string
                        override_env:
                          type: string
              500:
                description: 读取配置失败
            """
            try:
                config_mgr = get_config()
                feedback_config = config_mgr.get_section("feedback")

                from config_utils import truncate_string

                return jsonify(
                    {
                        "status": "success",
                        "config": {
                            "resubmit_prompt": truncate_string(
                                feedback_config.get("resubmit_prompt"),
                                500,
                                "feedback.resubmit_prompt",
                                default="请立即调用 interactive_feedback 工具",
                            ),
                            "prompt_suffix": truncate_string(
                                feedback_config.get("prompt_suffix"),
                                500,
                                "feedback.prompt_suffix",
                                default="\n请积极调用 interactive_feedback 工具",
                            ),
                        },
                        "meta": {
                            "config_file": str(config_mgr.config_file.absolute()),
                            "override_env": "AI_INTERVENTION_AGENT_CONFIG_FILE",
                        },
                    }
                )

            except Exception as e:
                logger.error(f"获取反馈提示语配置失败: {e}", exc_info=True)
                return jsonify(
                    {"status": "error", "message": msg("notify.getFailed")}
                ), 500
