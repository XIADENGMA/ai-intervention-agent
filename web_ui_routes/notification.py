"""通知路由 Mixin — Bark 测试、新任务通知、通知配置读写、反馈提示语。

启动期解耦（R20.10）
~~~~~~~~~~~~~~~~~~~~
本模块顶层只通过 ``importlib.util.find_spec`` 探测 ``notification_manager`` /
``notification_providers`` 是否可发现，而不真正 ``import`` 它们；后者会强制
拉入 ``httpx`` (~22ms) 和 ``notification_manager`` 自己的全部依赖（~43ms），
共计 ~65ms 的纯启动开销。

实测：Web UI 子进程 5 条核心 API 路径（``/api/tasks``、``/api/config``、
``/api/events``、``/api/submit``、``/api/health``）从不接触通知系统；
通知模块仅在 4 条用户主动触发的路由中使用：

* ``/api/test-bark``           - 用户在设置页点击「测试 Bark 推送」时
* ``/api/notify-new-tasks``    - 兼容旧前端调用（注释明确说明前端已不再调用）
* ``/api/update-notification-config`` - 用户保存通知配置时
* ``/api/get-notification-config`` 等只读端点 - 仅读 config_manager，不依赖通知模块

实施模式：**first-touch hoist**
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
1. 模块顶层声明 5 个 ``None`` 占位 (``notification_manager`` / ``NotificationEvent``
   / ``NotificationTrigger`` / ``NotificationType`` / ``BarkNotificationProvider``)，
   这样 ``mock.patch("web_ui_routes.notification.X", mock)`` 能找到 attribute，
   不会因 ``AttributeError`` 失败。
2. ``_ensure_notification_loaded()`` / ``_ensure_bark_provider_loaded()`` 在路由
   函数体内第一次被调用时把真模块从 source 拉进来并写回 module global；后续
   调用通过 ``if X is None`` 短路、零开销。
3. 路由代码使用 module-global 名字（闭包查找模块全局），所以 mock.patch 替换
   的占位生效——``_ensure_*_loaded`` 在 mock 已就位时不会"覆盖" mock（因为 mock
   不是 None，short-circuit 跳过 lazy import）。

``NOTIFICATION_AVAILABLE`` 的语义保持不变：``True`` 表示模块可发现，graceful
degradation 仍按原契约工作。``find_spec`` 比 ``try: import`` 节省 100% 模块
执行成本（仅检查 ``sys.path`` 和 finder 链，不执行模块顶层语句）。

实测：``import web_ui`` 中位数 192 ms → 156 ms（**-36 ms / -19%**）；
累计相对 R19 baseline 425 ms 累计 156 ms（**-269 ms / -63% cold-start**）。
"""

from __future__ import annotations

import time
from importlib.util import find_spec
from typing import TYPE_CHECKING, Any

from flask import jsonify, request
from flask.typing import ResponseReturnValue

from config_manager import get_config
from config_utils import clamp_value
from enhanced_logging import EnhancedLogger
from i18n import msg

NOTIFICATION_AVAILABLE = (
    find_spec("notification_manager") is not None
    and find_spec("notification_providers") is not None
)

# ---------------------------------------------------------------------------
# R20.10 first-touch hoist 占位
#
# 这 5 个 module-level 名字在 cold-start 时是 ``None``——直到第一次 ``_ensure_*``
# 被路由函数体内调用，才会从 source 模块拉过来并写回这里。这样：
# * cold-start 不付 ~65 ms 启动税；
# * mock.patch("web_ui_routes.notification.X", mock) 能找到 attribute；
# * mock 在 short-circuit 中保留——``_ensure_*`` 看到 ``X is not None`` 就不再覆盖。
# ---------------------------------------------------------------------------
notification_manager: Any = None
NotificationEvent: Any = None
NotificationTrigger: Any = None
NotificationType: Any = None
BarkNotificationProvider: Any = None


def _ensure_notification_loaded() -> None:
    """First-touch hoist：把 notification_manager 模块拉进本模块 global namespace。

    幂等：``if notification_manager is None`` 短路；mock.patch 注入的 mock
    会让短路成立，从而保留 mock 不被覆盖。
    """
    global \
        notification_manager, \
        NotificationEvent, \
        NotificationTrigger, \
        NotificationType
    if notification_manager is None:
        # 函数体内 lazy import，禁用 ruff isort（I001）；这是 R20.10 的核心
        # 设计——一旦顶层化就会在 cold-start 时拖入 notification_manager 全部
        # 依赖（~43 ms）。
        from notification_manager import (  # noqa: I001
            NotificationEvent as _NE,
            NotificationTrigger as _NT,
            NotificationType as _NTy,
            notification_manager as _nm,
        )

        notification_manager = _nm
        NotificationEvent = _NE
        NotificationTrigger = _NT
        NotificationType = _NTy


def _ensure_bark_provider_loaded() -> None:
    """First-touch hoist：把 BarkNotificationProvider 拉进本模块 global namespace。"""
    global BarkNotificationProvider
    if BarkNotificationProvider is None:
        from notification_providers import (
            BarkNotificationProvider as _BNP,
        )

        BarkNotificationProvider = _BNP


if TYPE_CHECKING:
    from flask import Flask

logger = EnhancedLogger(__name__)


class NotificationRoutesMixin:
    """提供 5 个通知相关 API 路由，由 WebFeedbackUI 通过 MRO 继承。"""

    if TYPE_CHECKING:
        app: Flask
        limiter: Any

    def _setup_notification_routes(self) -> None:
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
                bark_url_template = str(
                    data.get("bark_url_template", "{base_url}/?task_id={task_id}") or ""
                ).strip()

                if not bark_device_key:
                    return jsonify(
                        {"status": "error", "message": msg("notify.deviceKeyEmpty")}
                    ), 400

                try:
                    if not NOTIFICATION_AVAILABLE:
                        raise ImportError(msg("notify.systemUnavailable"))

                    _ensure_notification_loaded()
                    _ensure_bark_provider_loaded()

                    class TempConfig:
                        def __init__(self) -> None:
                            self.bark_enabled = True
                            self.bark_url = bark_url
                            self.bark_device_key = bark_device_key
                            self.bark_icon = bark_icon
                            self.bark_action = bark_action
                            self.bark_url_template = bark_url_template

                    temp_config = TempConfig()
                    bark_provider = BarkNotificationProvider(temp_config)

                    test_metadata: dict[str, Any] = {
                        "test": True,
                        "task_id": "test-task-id",
                    }
                    base_url_for_test = ""
                    try:
                        import server_config as _sc

                        base_url_for_test = _sc.resolve_external_base_url()
                    except Exception:
                        base_url_for_test = ""
                    if base_url_for_test:
                        test_metadata["base_url"] = base_url_for_test

                    test_event = NotificationEvent(
                        id=f"test_bark_{int(time.time())}",
                        title="AI Intervention Agent 测试",
                        message="这是一个 Bark 通知测试，如果收到此消息，说明配置正确。",
                        trigger=NotificationTrigger.IMMEDIATE,
                        types=[NotificationType.BARK],
                        metadata=test_metadata,
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
            """触发新任务 Bark 推送通知（兼容保留，内部不再主动调用）

            注意：从"后端统一推送"方案起，Bark 新任务通知由 MCP 主进程在
            `server_feedback._interactive_feedback_impl` / `launch_feedback_ui`
            中直接通过 `notification_manager.send_notification(types=[...BARK])` 发送，
            Web UI 前端已不再调用该端点。此端点仅为外部第三方客户端兼容保留，
            重复调用会触发重复 Bark 推送，请调用方自行做去重。
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

                _ensure_notification_loaded()

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

                    _ensure_notification_loaded()

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
                        (
                            ("barkUrlTemplate", "bark_url_template"),
                            "bark_url_template",
                            "bark_url_template",
                            normalize_string,
                            normalize_string,
                        ),
                    ]

                    manager_updates: dict[str, Any] = {}
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
                        frontend_countdown:
                          type: integer
                          description: 前端倒计时时间（秒）
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
                from server_config import (
                    AUTO_RESUBMIT_TIMEOUT_DEFAULT,
                    PROMPT_MAX_LENGTH,
                )

                raw_countdown = feedback_config.get(
                    "frontend_countdown",
                    feedback_config.get(
                        "auto_resubmit_timeout",
                        AUTO_RESUBMIT_TIMEOUT_DEFAULT,
                    ),
                )
                try:
                    frontend_countdown = int(raw_countdown)
                except (TypeError, ValueError):
                    frontend_countdown = AUTO_RESUBMIT_TIMEOUT_DEFAULT

                return jsonify(
                    {
                        "status": "success",
                        "config": {
                            "frontend_countdown": frontend_countdown,
                            "resubmit_prompt": truncate_string(
                                feedback_config.get("resubmit_prompt"),
                                PROMPT_MAX_LENGTH,
                                "feedback.resubmit_prompt",
                                default="请立即调用 interactive_feedback 工具",
                            ),
                            "prompt_suffix": truncate_string(
                                feedback_config.get("prompt_suffix"),
                                PROMPT_MAX_LENGTH,
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

        @self.app.route("/api/update-feedback-config", methods=["POST"])
        @self.limiter.limit("30 per minute")
        def update_feedback_config() -> ResponseReturnValue:
            """更新反馈配置（倒计时、提示语）
            ---
            tags:
              - Feedback
            consumes:
              - application/json
            parameters:
              - in: body
                name: body
                schema:
                  type: object
                  properties:
                    frontend_countdown:
                      type: integer
                      minimum: 0
                      maximum: 3600
                      description: 倒计时秒数；0=禁用；非零值范围 [10, 3600]，与 server_config.AUTO_RESUBMIT_TIMEOUT_MAX 对齐
                    resubmit_prompt:
                      type: string
                      maxLength: 10000
                    prompt_suffix:
                      type: string
                      maxLength: 10000
            responses:
              200:
                description: 配置已更新
              400:
                description: 参数无效
              500:
                description: 更新失败
            """
            try:
                data = request.json or {}
                if not isinstance(data, dict):
                    data = {}

                config_mgr = get_config()
                feedback_config = dict(config_mgr.get_section("feedback"))

                from config_utils import truncate_string
                from server_config import (
                    AUTO_RESUBMIT_TIMEOUT_MAX,
                    AUTO_RESUBMIT_TIMEOUT_MIN,
                    PROMPT_MAX_LENGTH,
                    PROMPT_SUFFIX_DEFAULT,
                    RESUBMIT_PROMPT_DEFAULT,
                )

                changed_keys: list[str] = []

                if "frontend_countdown" in data:
                    raw = data["frontend_countdown"]
                    try:
                        val = int(raw)
                    except (TypeError, ValueError):
                        return jsonify(
                            {
                                "status": "error",
                                "message": "frontend_countdown 必须为整数",
                            }
                        ), 400
                    if val == 0:
                        feedback_config["frontend_countdown"] = 0
                    else:
                        feedback_config["frontend_countdown"] = int(
                            clamp_value(
                                val,
                                AUTO_RESUBMIT_TIMEOUT_MIN,
                                AUTO_RESUBMIT_TIMEOUT_MAX,
                                "frontend_countdown",
                            )
                        )
                    changed_keys.append("frontend_countdown")

                if "resubmit_prompt" in data:
                    feedback_config["resubmit_prompt"] = truncate_string(
                        data["resubmit_prompt"],
                        PROMPT_MAX_LENGTH,
                        "feedback.resubmit_prompt",
                        default=RESUBMIT_PROMPT_DEFAULT,
                    )
                    changed_keys.append("resubmit_prompt")

                if "prompt_suffix" in data:
                    feedback_config["prompt_suffix"] = truncate_string(
                        data["prompt_suffix"],
                        PROMPT_MAX_LENGTH,
                        "feedback.prompt_suffix",
                        default=PROMPT_SUFFIX_DEFAULT,
                    )
                    changed_keys.append("prompt_suffix")

                if not changed_keys:
                    return jsonify(
                        {"status": "success", "message": "无可识别的更新字段"}
                    )

                config_mgr.update_section("feedback", feedback_config)
                logger.info(f"反馈配置已更新: {changed_keys}")

                return jsonify({"status": "success", "message": "反馈配置已更新"})

            except Exception as e:
                logger.error(f"更新反馈配置失败: {e}", exc_info=True)
                return jsonify(
                    {"status": "error", "message": msg("notify.updateFailed")}
                ), 500

        @self.app.route("/api/reset-feedback-config", methods=["POST"])
        @self.limiter.limit("10 per minute")
        def reset_feedback_config() -> ResponseReturnValue:
            """重置反馈配置为服务器默认值（单一真源）
            ---
            tags:
              - Feedback
            description: >-
              把 feedback.frontend_countdown / resubmit_prompt / prompt_suffix 写回
              server_config.py 中定义的默认值。前端不再硬编码中文默认值，
              避免 i18n 破坏和默认值漂移。
            responses:
              200:
                description: 配置已重置
              500:
                description: 重置失败
            """
            try:
                from server_config import (
                    AUTO_RESUBMIT_TIMEOUT_DEFAULT,
                    FEEDBACK_TIMEOUT_DEFAULT,
                    PROMPT_SUFFIX_DEFAULT,
                    RESUBMIT_PROMPT_DEFAULT,
                )

                # 不变量：本 dict 的 key 集合必须 == SECTION_MODELS::feedback 的字段集合，
                # 否则 partial reset 会让某个字段静默保留上次的用户值（contract 是
                # "重置整个 feedback section"，不是 "只重置 UI 可见字段"）。
                # 用 tests/test_reset_feedback_config_parity.py 的 introspection
                # 测试锁住这个覆盖契约。
                defaults = {
                    "backend_max_wait": int(FEEDBACK_TIMEOUT_DEFAULT),
                    "frontend_countdown": int(AUTO_RESUBMIT_TIMEOUT_DEFAULT),
                    "resubmit_prompt": RESUBMIT_PROMPT_DEFAULT,
                    "prompt_suffix": PROMPT_SUFFIX_DEFAULT,
                }

                config_mgr = get_config()
                current = dict(config_mgr.get_section("feedback"))
                current.update(defaults)
                config_mgr.update_section("feedback", current)
                logger.info("反馈配置已重置为默认值")

                return jsonify(
                    {
                        "status": "success",
                        "message": "反馈配置已重置为默认值",
                        "defaults": defaults,
                    }
                )

            except Exception as e:
                logger.error(f"重置反馈配置失败: {e}", exc_info=True)
                return jsonify(
                    {"status": "error", "message": msg("notify.updateFailed")}
                ), 500
