"""后端轻量 i18n 模块：根据请求语言返回本地化字符串。

使用方式：
    from i18n import get_locale_message, detect_request_lang

    lang = detect_request_lang()  # 从 Flask request 自动检测
    msg = get_locale_message("feedback.submitted", lang)
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

SUPPORTED_LANGS = ("en", "zh-CN")
DEFAULT_LANG = "en"

_MESSAGES: dict[str, dict[str, str]] = {
    "en": {
        "feedback.submitted": "Feedback submitted",
        "feedback.bodyMustBeJson": "Request body must be JSON (object)",
        "feedback.bodyMustBeObject": "Request body must be JSON object",
        "feedback.missingPrompt": "Missing field: prompt",
        "feedback.promptMustBeString": "Field prompt must be a string",
        "feedback.optionsMustBeArray": "Field predefined_options must be an array",
        "feedback.timeoutMustBeInt": "Field auto_resubmit_timeout must be an integer (seconds)",
        "feedback.contentUpdated": "Content updated",
        "feedback.serverError": "Internal server error",
        "server.shuttingDown": "Server is shutting down",
        "notify.testSuccess": "Bark test notification sent! Please check your device",
        "notify.deviceKeyEmpty": "Device Key cannot be empty",
        "notify.sendFailedDetail": "Bark notification send failed: {detail}",
        "notify.sendFailedConfig": "Bark notification send failed, please check configuration",
        "notify.systemUnavailable": "Notification system unavailable",
        "notify.testFailed": "Test failed",
        "notify.countZero": "count=0, ignored",
        "notify.systemDegraded": "Notification system unavailable, degraded",
        "notify.globalOff": "Notification master switch is off, ignored",
        "notify.barkDisabled": "Bark is disabled, ignored",
        "notify.barkKeyEmpty": "bark_device_key is empty, ignored",
        "notify.notTriggered": "Notification not triggered (may be disabled)",
        "notify.triggerFailed": "Trigger failed",
        "notify.configUpdated": "Notification config updated",
        "notify.noUpdateFields": "No notification config fields to update detected",
        "notify.configUnavailable": "Config system unavailable",
        "notify.updateFailed": "Update failed",
        "notify.getFailed": "Failed to get config",
    },
    "zh-CN": {
        "feedback.submitted": "反馈已提交",
        "feedback.bodyMustBeJson": "请求体必须是 JSON（object）",
        "feedback.bodyMustBeObject": "请求体必须是 JSON object",
        "feedback.missingPrompt": "缺少字段：prompt",
        "feedback.promptMustBeString": "字段 prompt 必须是字符串",
        "feedback.optionsMustBeArray": "字段 predefined_options 必须是数组",
        "feedback.timeoutMustBeInt": "字段 auto_resubmit_timeout 必须是整数（秒）",
        "feedback.contentUpdated": "内容已更新",
        "feedback.serverError": "服务器内部错误",
        "server.shuttingDown": "服务即将关闭",
        "notify.testSuccess": "Bark 测试通知发送成功！请检查设备",
        "notify.deviceKeyEmpty": "Device Key 不能为空",
        "notify.sendFailedDetail": "Bark 通知发送失败：{detail}",
        "notify.sendFailedConfig": "Bark 通知发送失败，请检查配置",
        "notify.systemUnavailable": "通知系统不可用",
        "notify.testFailed": "测试失败",
        "notify.countZero": "count=0，已忽略",
        "notify.systemDegraded": "通知系统不可用，已降级",
        "notify.globalOff": "通知总开关未开启，已忽略",
        "notify.barkDisabled": "Bark 未启用，已忽略",
        "notify.barkKeyEmpty": "bark_device_key 为空，已忽略",
        "notify.notTriggered": "通知未触发（可能已禁用）",
        "notify.triggerFailed": "触发失败",
        "notify.configUpdated": "通知配置已更新",
        "notify.noUpdateFields": "未检测到需要更新的通知配置字段",
        "notify.configUnavailable": "配置系统不可用",
        "notify.updateFailed": "更新失败",
        "notify.getFailed": "获取配置失败",
    },
}


def normalize_lang(raw: str) -> str:
    """将语言标识归一化为支持的语言代码。"""
    s = (raw or "").strip().lower()
    if s.startswith("zh"):
        return "zh-CN"
    if s.startswith("en"):
        return "en"
    return DEFAULT_LANG


def detect_request_lang() -> str:
    """从 Flask request 的 Accept-Language 头检测语言，回退到 config.toml 配置。"""
    try:
        from flask import request

        accept = request.headers.get("Accept-Language", "")
        if accept:
            primary = accept.split(",")[0].split(";")[0].strip()
            lang = normalize_lang(primary)
            if lang in SUPPORTED_LANGS:
                return lang
    except (RuntimeError, ImportError):
        pass

    try:
        from config_manager import get_config

        ui_lang = get_config().get_section("web_ui").get("language", "auto")
        if ui_lang != "auto":
            return normalize_lang(ui_lang)
    except Exception:
        pass

    return DEFAULT_LANG


def get_locale_message(
    key: str,
    lang: str | None = None,
    **kwargs: str,
) -> str:
    """获取本地化消息字符串。

    Args:
        key: 消息键（如 "feedback.submitted"）
        lang: 语言代码（None 则自动检测）
        **kwargs: 模板参数（如 detail="xxx"）
    """
    if lang is None:
        lang = detect_request_lang()

    messages = _MESSAGES.get(lang, _MESSAGES[DEFAULT_LANG])
    val = messages.get(key)

    if val is None:
        val = _MESSAGES[DEFAULT_LANG].get(key, key)

    if kwargs:
        try:
            val = val.format(**kwargs)
        except (KeyError, IndexError):
            pass

    return val


# 便捷别名
msg = get_locale_message
