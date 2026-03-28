"""
共享类型定义（Pydantic 配置段模型 + TypedDict 反馈结构）

目的：
- 配置段模型：提供 TOML 配置段的运行时校验与类型安全
- TypedDict：让 `ty` 在跨模块分析时拥有一致的结构化类型

命名规则：
- 配置段模型以 `SectionConfig` 后缀命名，与 notification_manager.NotificationConfig 等运行时模型区分
"""

from typing import Any, List, TypedDict, Union

from pydantic import BaseModel, BeforeValidator, ConfigDict
from typing_extensions import Annotated

# ---------------------------------------------------------------------------
# 可复用的 Pydantic 前置校验器（替代 safe_bool / safe_int / safe_str）
# ---------------------------------------------------------------------------


def _coerce_bool(v: Any) -> Any:
    """TOML/JSON 安全布尔值转换（兼容字符串 "true"/"false"/数字 0/1）"""
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return bool(v)
    if isinstance(v, str):
        s = v.strip().lower()
        if s in ("true", "1", "yes", "y", "on"):
            return True
        if s in ("false", "0", "no", "n", "off"):
            return False
    return v


def _coerce_int(v: Any) -> Any:
    """TOML/JSON 安全整数转换（兼容浮点数和数字字符串）"""
    if isinstance(v, bool):
        return int(v)
    if isinstance(v, int):
        return v
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return v


def _clamp_int(min_val: int, max_val: int, default: int):
    """生成一个 BeforeValidator：将整数值钳位到 [min_val, max_val]，失败返回 default"""

    def _validator(v: Any) -> int:
        try:
            iv = int(float(v)) if not isinstance(v, bool) else int(v)
        except (TypeError, ValueError):
            return default
        return max(min_val, min(max_val, iv))

    return _validator


def _clamp_int_allow_zero(min_val: int, max_val: int, default: int):
    """生成一个 BeforeValidator：0 或负值 → 0（禁用），其余钳位到 [min_val, max_val]"""

    def _validator(v: Any) -> int:
        try:
            iv = int(float(v)) if not isinstance(v, bool) else int(v)
        except (TypeError, ValueError):
            return default
        if iv <= 0:
            return 0
        return max(min_val, min(max_val, iv))

    return _validator


def _clamp_float(min_val: float, max_val: float, default: float):
    """生成一个 BeforeValidator：将浮点值钳位到 [min_val, max_val]，失败返回 default"""

    def _validator(v: Any) -> float:
        try:
            fv = float(v)
        except (TypeError, ValueError):
            return default
        return max(min_val, min(max_val, fv))

    return _validator


def _coerce_float(v: Any) -> Any:
    """TOML/JSON 安全浮点转换"""
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return float(v)
    try:
        return float(v)
    except (TypeError, ValueError):
        return v


def _coerce_str(v: Any) -> Any:
    """TOML/JSON 安全字符串转换（None → 默认由 Pydantic 处理）"""
    if v is None:
        return v
    return str(v)


SafeBool = Annotated[bool, BeforeValidator(_coerce_bool)]
SafeInt = Annotated[int, BeforeValidator(_coerce_int)]
SafeFloat = Annotated[float, BeforeValidator(_coerce_float)]
SafeStr = Annotated[str, BeforeValidator(_coerce_str)]


# ---------------------------------------------------------------------------
# 反馈数据结构（TypedDict，用于运行时字典构造）
# ---------------------------------------------------------------------------


class FeedbackImage(TypedDict, total=False):
    """单张图片的结构（Web UI / MCP 交互中使用）"""

    data: str
    filename: str
    size: int
    content_type: str
    mimeType: str
    mime_type: str


class FeedbackResult(TypedDict):
    """Web UI 反馈结果结构（与 /api/feedback 返回一致）"""

    user_input: str
    selected_options: list[str]
    images: list[FeedbackImage]


# ---------------------------------------------------------------------------
# Pydantic 配置段模型（与 config_manager._get_default_config 对齐）
#
# 每个模型的默认值即为 TOML 配置的默认值（单一真相源）。
# extra="allow" 确保未知键不会被丢弃（用户可自定义扩展键）。
# ---------------------------------------------------------------------------


class NotificationSectionConfig(BaseModel):
    """notification TOML 配置段（与 notification_manager.NotificationConfig 区分）"""

    model_config = ConfigDict(extra="allow")

    enabled: SafeBool = True
    debug: SafeBool = False
    web_enabled: SafeBool = True
    auto_request_permission: SafeBool = True
    web_icon: SafeStr = "default"
    web_timeout: Annotated[int, BeforeValidator(_clamp_int(1, 600000, 5000))] = 5000
    system_enabled: SafeBool = False
    macos_native_enabled: SafeBool = True
    sound_enabled: SafeBool = True
    sound_mute: SafeBool = False
    sound_file: SafeStr = "default"
    sound_volume: Annotated[int, BeforeValidator(_clamp_int(0, 100, 80))] = 80
    mobile_optimized: SafeBool = True
    mobile_vibrate: SafeBool = True
    retry_count: Annotated[int, BeforeValidator(_clamp_int(0, 10, 3))] = 3
    retry_delay: Annotated[int, BeforeValidator(_clamp_int(0, 60, 2))] = 2
    bark_enabled: SafeBool = False
    bark_url: SafeStr = ""
    bark_device_key: SafeStr = ""
    bark_icon: SafeStr = ""
    bark_action: SafeStr = "none"
    bark_timeout: Annotated[int, BeforeValidator(_clamp_int(1, 300, 10))] = 10


class WebUISectionConfig(BaseModel):
    """web_ui TOML 配置段"""

    model_config = ConfigDict(extra="allow")

    host: SafeStr = "127.0.0.1"
    port: Annotated[int, BeforeValidator(_clamp_int(1, 65535, 8080))] = 8080
    language: SafeStr = "auto"
    debug: SafeBool = False
    http_request_timeout: Annotated[int, BeforeValidator(_clamp_int(1, 600, 30))] = 30
    http_max_retries: Annotated[int, BeforeValidator(_clamp_int(0, 20, 3))] = 3
    http_retry_delay: Annotated[float, BeforeValidator(_clamp_float(0, 60, 1.0))] = 1.0


class MdnsSectionConfig(BaseModel):
    """mdns TOML 配置段"""

    model_config = ConfigDict(extra="allow")

    enabled: Union[SafeBool, str] = "auto"
    hostname: SafeStr = "ai.local"
    service_name: SafeStr = "AI Intervention Agent"


class NetworkSecuritySectionConfig(BaseModel):
    """network_security TOML 配置段"""

    model_config = ConfigDict(extra="allow")

    bind_interface: SafeStr = "0.0.0.0"
    allowed_networks: List[str] = [
        "127.0.0.0/8",
        "::1/128",
        "192.168.0.0/16",
        "10.0.0.0/8",
        "172.16.0.0/12",
    ]
    blocked_ips: List[str] = []
    access_control_enabled: SafeBool = True


class FeedbackSectionConfig(BaseModel):
    """feedback TOML 配置段"""

    model_config = ConfigDict(extra="allow")

    backend_max_wait: Annotated[int, BeforeValidator(_clamp_int(10, 7200, 600))] = 600
    frontend_countdown: Annotated[
        int, BeforeValidator(_clamp_int_allow_zero(10, 3600, 240))
    ] = 240
    resubmit_prompt: SafeStr = "请立即调用 interactive_feedback 工具"
    prompt_suffix: SafeStr = "\n请积极调用 interactive_feedback 工具"


# ---------------------------------------------------------------------------
# 段名 → 模型类 注册表（供 config_manager 使用）
# ---------------------------------------------------------------------------

SECTION_MODELS: dict[str, type[BaseModel]] = {
    "notification": NotificationSectionConfig,
    "web_ui": WebUISectionConfig,
    "mdns": MdnsSectionConfig,
    "network_security": NetworkSecuritySectionConfig,
    "feedback": FeedbackSectionConfig,
}

# ---------------------------------------------------------------------------
# 向后兼容别名（旧名 → 新名，逐步淘汰）
# ---------------------------------------------------------------------------
NotificationConfig = NotificationSectionConfig
MdnsConfig = MdnsSectionConfig
NetworkSecurityConfig = NetworkSecuritySectionConfig
FeedbackConfig = FeedbackSectionConfig
