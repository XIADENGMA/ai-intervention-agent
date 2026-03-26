"""
共享类型定义（TypedDict）

目的：
- 让 `ty` 在跨模块（server/web_ui/task_queue/tests）分析时拥有一致的结构化类型
- 避免在多个文件中重复声明相同的字典结构

说明：
- 这些类型仅用于类型检查/IDE 提示，不影响运行时行为
"""

from typing import Optional, TypedDict


class FeedbackImage(TypedDict, total=False):
    """单张图片的结构（Web UI / MCP 交互中使用）"""

    # 纯 base64 数据（可能是 data URI，也可能是纯 base64）
    data: str

    # 可选元信息（字段名在不同链路里可能不同，这里都兼容）
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
# 配置段 TypedDict（与 config_manager._get_default_config 对齐）
# ---------------------------------------------------------------------------


class NotificationConfig(TypedDict, total=False):
    """notification 配置段。"""

    enabled: bool
    debug: bool
    web_enabled: bool
    auto_request_permission: bool
    web_icon: str
    web_timeout: int
    system_enabled: bool
    macos_native_enabled: bool
    sound_enabled: bool
    sound_mute: bool
    sound_file: str
    sound_volume: int
    mobile_optimized: bool
    mobile_vibrate: bool
    retry_count: int
    retry_delay: int
    bark_enabled: bool
    bark_url: str
    bark_device_key: str
    bark_icon: str
    bark_action: str
    bark_timeout: int


class WebUISectionConfig(TypedDict, total=False):
    """web_ui 配置段（config.jsonc 中的 web_ui 字段）。"""

    host: str
    port: int
    debug: bool
    http_request_timeout: int
    http_max_retries: int
    http_retry_delay: float


class MdnsConfig(TypedDict, total=False):
    """mdns 配置段。"""

    enabled: Optional[bool]
    hostname: str
    service_name: str


class NetworkSecurityConfig(TypedDict, total=False):
    """network_security 配置段。"""

    bind_interface: str
    allowed_networks: list[str]
    blocked_ips: list[str]
    access_control_enabled: bool


class FeedbackConfig(TypedDict, total=False):
    """feedback 配置段。"""

    backend_max_wait: int
    frontend_countdown: int
    resubmit_prompt: str
    prompt_suffix: str
