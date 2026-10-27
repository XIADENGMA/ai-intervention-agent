"""后端轻量 i18n 模块：根据请求语言返回本地化字符串。"""

from __future__ import annotations

import logging
import os
import plistlib
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

_UNRESOLVED: Any = object()
_flask_request: Any | None = _UNRESOLVED
"""Flask 的 ``request`` 代理：第一次用到时才导入（``None`` 表示没装 Flask）。

R830：MCP 服务进程不加载 Flask（``import ai_intervention_agent.server`` 不会带进 Flask、
Werkzeug 和 Jinja2），而它现在要从这里取推送标题。顶部的 ``from flask import request``
会让这个进程为了一个标题多背一整个 Web 框架。
"""


def _request_proxy() -> Any | None:
    """Flask 的 ``request`` 代理，没装 Flask 时是 ``None``；只导入一次。"""
    global _flask_request
    if _flask_request is _UNRESOLVED:
        try:
            from flask import request as proxy
        except ImportError:  # pragma: no cover - Flask is a runtime dependency.
            _flask_request = None
        else:
            _flask_request = proxy
    return _flask_request


logger = logging.getLogger(__name__)

SUPPORTED_LANGS = ("en", "zh-CN", "zh-TW")
DEFAULT_LANG = "en"

_MESSAGES: dict[str, dict[str, str]] = {
    "en": {
        "feedback.submitted": "Feedback submitted",
        "feedback.bodyMustBeJson": "Request body must be JSON (object)",
        "feedback.bodyMustBeObject": "Request body must be JSON object",
        "feedback.bodyMustBeForm": "No answer in the request: send a form (multipart/form-data or application/x-www-form-urlencoded) with feedback_text and/or selected_options, or image files",
        "feedback.payloadTooLarge": "Request is larger than the server accepts (limit: {limit})",
        "feedback.requestLimitsExceeded": "Request exceeds a server limit (total {limit}, {field_limit} per text field, {parts} form parts)",
        "feedback.alreadyAnswered": "This task was already answered; this answer was not sent",
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
        "notify.invalidFieldValue": "Invalid value for: {fields}",
        "notify.getFailed": "Failed to get config",
        "notify.newRequestTitle": "New feedback request",
        "notify.barkTestTitle": "AI Intervention Agent test",
        "notify.barkTestBody": "This is a Bark test notification. If you received it, the configuration is correct.",
    },
    "zh-CN": {
        "feedback.submitted": "反馈已提交",
        "feedback.bodyMustBeJson": "请求体必须是 JSON（object）",
        "feedback.bodyMustBeObject": "请求体必须是 JSON object",
        "feedback.bodyMustBeForm": "请求里没有答案：请发送表单（multipart/form-data 或 application/x-www-form-urlencoded），带 feedback_text 和/或 selected_options，或图片文件",
        "feedback.payloadTooLarge": "请求体超过服务器允许的上限（{limit}）",
        "feedback.requestLimitsExceeded": "请求超出服务器限制（总计 {limit}，每个文本字段 {field_limit}，最多 {parts} 个表单字段）",
        "feedback.alreadyAnswered": "这个任务已经被回答过了，这次的答案没有发送",
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
        "notify.invalidFieldValue": "以下字段的值无效：{fields}",
        "notify.getFailed": "获取配置失败",
        "notify.newRequestTitle": "新的反馈请求",
        "notify.barkTestTitle": "AI Intervention Agent 测试",
        "notify.barkTestBody": "这是一个 Bark 通知测试，如果收到此消息，说明配置正确。",
    },
    "zh-TW": {
        "feedback.submitted": "回饋已提交",
        "feedback.bodyMustBeJson": "要求主體必須是 JSON（object）",
        "feedback.bodyMustBeObject": "要求主體必須是 JSON object",
        "feedback.bodyMustBeForm": "請求中沒有答案：請傳送表單（multipart/form-data 或 application/x-www-form-urlencoded），並帶有 feedback_text 和／或 selected_options，或圖片檔案",
        "feedback.payloadTooLarge": "請求主體超過伺服器允許的上限（{limit}）",
        "feedback.requestLimitsExceeded": "請求超出伺服器限制（總計 {limit}，每個文字欄位 {field_limit}，最多 {parts} 個表單欄位）",
        "feedback.alreadyAnswered": "這個任務已經被回答過了，這次的答案沒有送出",
        "feedback.missingPrompt": "缺少欄位：prompt",
        "feedback.promptMustBeString": "欄位 prompt 必須是字串",
        "feedback.optionsMustBeArray": "欄位 predefined_options 必須是陣列",
        "feedback.timeoutMustBeInt": "欄位 auto_resubmit_timeout 必須是整數（秒）",
        "feedback.contentUpdated": "內容已更新",
        "feedback.serverError": "伺服器內部錯誤",
        "server.shuttingDown": "服務即將關閉",
        "notify.testSuccess": "Bark 測試通知傳送成功！請檢查裝置",
        "notify.deviceKeyEmpty": "Device Key 不能為空",
        "notify.sendFailedDetail": "Bark 通知傳送失敗：{detail}",
        "notify.sendFailedConfig": "Bark 通知傳送失敗，請檢查設定",
        "notify.systemUnavailable": "通知系統無法使用",
        "notify.testFailed": "測試失敗",
        "notify.countZero": "count=0，已忽略",
        "notify.systemDegraded": "通知系統無法使用，已降級",
        "notify.globalOff": "通知總開關未開啟，已忽略",
        "notify.barkDisabled": "Bark 未啟用，已忽略",
        "notify.barkKeyEmpty": "bark_device_key 為空，已忽略",
        "notify.notTriggered": "通知未觸發（可能已停用）",
        "notify.triggerFailed": "觸發失敗",
        "notify.configUpdated": "通知設定已更新",
        "notify.noUpdateFields": "未偵測到需要更新的通知設定欄位",
        "notify.configUnavailable": "設定系統無法使用",
        "notify.updateFailed": "更新失敗",
        "notify.invalidFieldValue": "以下欄位的值無效：{fields}",
        "notify.getFailed": "取得設定失敗",
        "notify.newRequestTitle": "新的回饋請求",
        "notify.barkTestTitle": "AI Intervention Agent 測試",
        "notify.barkTestBody": "這是一則 Bark 通知測試，如果收到這則訊息，代表設定正確。",
    },
}


def normalize_lang(raw: str) -> str:
    """将语言标识归一化为支持的语言代码。"""
    s = (raw or "").strip().lower()
    if s.startswith("zh"):
        if s in {"zh-tw", "zh-hk", "zh-mo", "zh-hant"} or s.startswith("zh-hant-"):
            return "zh-TW"
        return "zh-CN"
    if s.startswith("en"):
        return "en"
    return DEFAULT_LANG


def detect_request_lang() -> str:
    """从 Flask request 的 Accept-Language 头检测语言，回退到 config.toml 配置。"""
    request_proxy = _request_proxy()
    if request_proxy is not None:
        try:
            accept = request_proxy.headers.get("Accept-Language", "")
            if accept:
                primary = accept.partition(",")[0].partition(";")[0].strip()
                lang = normalize_lang(primary)
                if lang in SUPPORTED_LANGS:
                    return lang
        except RuntimeError:
            pass

    try:
        from ai_intervention_agent.config_manager import get_config

        ui_lang = get_config().get_section("web_ui").get("language", "auto")
        if ui_lang != "auto":
            return normalize_lang(ui_lang)
    except Exception:
        pass

    return DEFAULT_LANG


_POSIX_LANG_VARS = ("LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG")


def _supported_lang(tag: str) -> str | None:
    """``zh_CN.UTF-8``、``zh-Hant-TW``、``en`` 这类标识 → 页面能说的语言。

    别的语言和"没说"（空、``C``、``POSIX``、``C.UTF-8``）都是 ``None``，
    不会像 ``normalize_lang`` 那样顺手变成英文：调用方要靠它跳到下一个候选。
    """
    name = tag.strip().partition(".")[0].partition("@")[0].replace("_", "-")
    if name[:2].lower() not in ("zh", "en"):
        return None
    return normalize_lang(name)


def _macos_languages(home: Path) -> list[str]:
    """macOS 用户的显示语言，按优先顺序（全局偏好里的 ``AppleLanguages``）。

    读不到（没有这个文件、没权限、不是 plist、不是预期的形状）就是空列表。
    """
    try:
        path = home / "Library" / "Preferences" / ".GlobalPreferences.plist"
        with path.open("rb") as handle:
            prefs = plistlib.load(handle)
    except Exception:
        return []
    languages = prefs.get("AppleLanguages") if isinstance(prefs, dict) else None
    if not isinstance(languages, list):
        return []
    return [item for item in languages if isinstance(item, str)]


def _windows_ui_langid() -> int | None:
    """Windows 的显示语言（LANGID）；不是 Windows 或调用失败时是 ``None``。"""
    try:
        import ctypes

        windll = getattr(ctypes, "windll", None)
        if windll is None:
            return None
        return int(windll.kernel32.GetUserDefaultUILanguage())
    except Exception:
        return None


def _lang_from_windows_langid(langid: int) -> str | None:
    """Windows 的 LANGID → 页面能说的语言；别的语言是 ``None``。"""
    primary = langid & 0x3FF
    if primary == 0x09:
        return "en"
    if primary == 0x04:
        # 繁体：台湾 0x0404、香港 0x0C04、澳门 0x1404、中性 zh-Hant 0x7C04
        # （子语言 1、3、5、0x1F）；其余中文（大陆 0x0804、新加坡 0x1004、中性 0x0004）是简体。
        return "zh-TW" if (langid >> 10) in (0x01, 0x03, 0x05, 0x1F) else "zh-CN"
    return None


def detect_system_lang(
    *,
    platform: str | None = None,
    environ: Mapping[str, str] | None = None,
    home: Path | None = None,
) -> str | None:
    """操作系统的显示语言，归一成 ``SUPPORTED_LANGS`` 之一；说不出来就是 ``None``。

    R830：服务端在没有请求可问的时候（给手机和桌面的推送标题）没有 ``Accept-Language``，
    也拿不到浏览器的 ``navigator.language``——页面上 ``auto`` 靠的就是它。最接近的是
    操作系统自己的语言：

    * macOS：用户全局偏好里的 ``AppleLanguages``。编辑器启动的 MCP 服务进程只有
      ``LANG=C.UTF-8``，终端里的 ``LANG`` 又只带"地区"（中文系统、美国地区是
      ``en_US.UTF-8``），都不是显示语言。
    * Windows：``GetUserDefaultUILanguage``。
    * 最后一道：``LANGUAGE``（冒号分隔的列表）、``LC_ALL``、``LC_MESSAGES``、``LANG``，
      ``C``/``POSIX`` 等于没说。

    按列表顺序取第一个页面能说的语言（应用选语言就是这么选的），不抛异常。
    ``platform`` / ``environ`` / ``home`` 只给测试注入。
    """
    system = sys.platform if platform is None else platform
    env = os.environ if environ is None else environ
    tags: list[str] = []
    if system == "darwin":
        try:
            tags += _macos_languages(home if home is not None else Path.home())
        except RuntimeError:  # ``Path.home()``: no home directory to be found
            pass
    elif system == "win32":
        langid = _windows_ui_langid()
        lang = None if langid is None else _lang_from_windows_langid(langid)
        if lang is not None:
            return lang
    for name in _POSIX_LANG_VARS:
        tags += str(env.get(name, "")).split(":")
    for tag in tags:
        lang = _supported_lang(tag)
        if lang is not None:
            return lang
    return None


def resolve_lang(configured: str | None) -> str:
    """没有请求可问时用的语言：设置里明确选的，否则系统的，否则英文。

    ``configured`` 是 ``web_ui.language``（``auto`` / ``en`` / ``zh-CN`` / ``zh-TW``）。
    """
    raw = (configured or "").strip()
    if raw and raw.lower() != "auto":
        return normalize_lang(raw)
    return detect_system_lang() or DEFAULT_LANG


def get_locale_message(
    key: str,
    lang: str | None = None,
    **kwargs: str,
) -> str:
    """获取本地化消息字符串。"""
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


msg = get_locale_message
