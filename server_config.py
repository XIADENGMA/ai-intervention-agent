"""MCP 服务器配置与工具函数 — 配置数据类、常量、输入验证、响应解析。

从 server.py 提取的无状态模块：
- WebUIConfig / FeedbackConfig 数据类及其 getter
- 超时计算、输入验证、图片处理、MCP 响应构建
- 所有函数不依赖 server.py 的全局状态（缓存、进程管理等）
"""

import base64
import uuid
from pathlib import Path
from typing import Any, ClassVar, Literal, overload

from mcp.types import ContentBlock, ImageContent, TextContent
from pydantic import BaseModel, field_validator

from config_manager import get_config
from config_utils import clamp_value, get_compat_config, truncate_string
from enhanced_logging import EnhancedLogger

logger = EnhancedLogger(__name__)

# ============================================================================
# 超时与边界常量
# ============================================================================

FEEDBACK_TIMEOUT_DEFAULT = 600  # 默认后端最大等待时间（秒）
FEEDBACK_TIMEOUT_MIN = 60  # 后端最小等待时间（秒）
FEEDBACK_TIMEOUT_MAX = 3600  # 后端最大等待时间上限（秒，1小时）

AUTO_RESUBMIT_TIMEOUT_DEFAULT = 240  # 默认前端倒计时（秒）
AUTO_RESUBMIT_TIMEOUT_MIN = 30  # 前端最小倒计时（秒）
AUTO_RESUBMIT_TIMEOUT_MAX = 250  # 前端最大倒计时（秒）

BACKEND_BUFFER = 40  # 后端缓冲时间（秒，前端+缓冲=后端最小）
BACKEND_MIN = 260  # 后端最低等待时间（秒，预留安全余量避免 MCPHub 300秒硬超时）

PROMPT_MAX_LENGTH = 500  # 提示语最大长度
RESUBMIT_PROMPT_DEFAULT = "请立即调用 interactive_feedback 工具"
PROMPT_SUFFIX_DEFAULT = "\n请积极调用 interactive_feedback 工具"

MAX_MESSAGE_LENGTH = 10000  # 用户输入/提示文本最大长度
MAX_OPTION_LENGTH = 500  # 单个预定义选项最大长度


# ============================================================================
# 配置数据类
# ============================================================================


class WebUIConfig(BaseModel):
    """Web UI 服务配置：host, port, timeout, max_retries, retry_delay"""

    PORT_MIN: ClassVar[int] = 1
    PORT_MAX: ClassVar[int] = 65535
    PORT_PRIVILEGED: ClassVar[int] = 1024
    TIMEOUT_MIN: ClassVar[int] = 1
    TIMEOUT_MAX: ClassVar[int] = 300
    MAX_RETRIES_MIN: ClassVar[int] = 0
    MAX_RETRIES_MAX: ClassVar[int] = 10
    RETRY_DELAY_MIN: ClassVar[float] = 0.1
    RETRY_DELAY_MAX: ClassVar[float] = 60.0

    SUPPORTED_LANGS: ClassVar[tuple] = ("auto", "en", "zh-CN")

    host: str
    port: int
    language: str = "auto"
    timeout: int = 30
    max_retries: int = 3
    retry_delay: float = 1.0

    @field_validator("language")
    @classmethod
    def validate_language(cls, v: str) -> str:
        if v not in cls.SUPPORTED_LANGS:
            logger.warning(
                "不支持的语言 '%s'，回退到 'auto'。支持的值: %s",
                v,
                ", ".join(cls.SUPPORTED_LANGS),
            )
            return "auto"
        return v

    @field_validator("port")
    @classmethod
    def validate_port(cls, v: int) -> int:
        if not (cls.PORT_MIN <= v <= cls.PORT_MAX):
            raise ValueError(
                f"端口号必须在 {cls.PORT_MIN}-{cls.PORT_MAX} 范围内，当前值: {v}"
            )
        if v < cls.PORT_PRIVILEGED:
            logger.warning(
                f"端口 {v} 是特权端口（<{cls.PORT_PRIVILEGED}），"
                f"可能需要 root/管理员权限才能绑定"
            )
        return v

    @field_validator("timeout")
    @classmethod
    def clamp_timeout(cls, v: int) -> int:
        return clamp_value(v, cls.TIMEOUT_MIN, cls.TIMEOUT_MAX, "timeout")

    @field_validator("max_retries")
    @classmethod
    def clamp_max_retries(cls, v: int) -> int:
        return clamp_value(v, cls.MAX_RETRIES_MIN, cls.MAX_RETRIES_MAX, "max_retries")

    @field_validator("retry_delay")
    @classmethod
    def clamp_retry_delay(cls, v: float) -> float:
        return clamp_value(v, cls.RETRY_DELAY_MIN, cls.RETRY_DELAY_MAX, "retry_delay")


class FeedbackConfig(BaseModel):
    """反馈配置：timeout、auto_resubmit_timeout、提示语等"""

    timeout: int
    auto_resubmit_timeout: int
    resubmit_prompt: str
    prompt_suffix: str

    @field_validator("timeout")
    @classmethod
    def clamp_timeout(cls, v: int) -> int:
        return clamp_value(
            v, FEEDBACK_TIMEOUT_MIN, FEEDBACK_TIMEOUT_MAX, "feedback.timeout"
        )

    @field_validator("auto_resubmit_timeout")
    @classmethod
    def clamp_auto_resubmit(cls, v: int) -> int:
        if v == 0:
            return v
        return clamp_value(
            v,
            AUTO_RESUBMIT_TIMEOUT_MIN,
            AUTO_RESUBMIT_TIMEOUT_MAX,
            "feedback.auto_resubmit_timeout",
        )

    @field_validator("resubmit_prompt")
    @classmethod
    def truncate_resubmit(cls, v: str) -> str:
        return truncate_string(
            v,
            PROMPT_MAX_LENGTH,
            "feedback.resubmit_prompt",
            default=RESUBMIT_PROMPT_DEFAULT,
        )

    @field_validator("prompt_suffix")
    @classmethod
    def truncate_suffix(cls, v: str) -> str:
        return truncate_string(
            v,
            PROMPT_MAX_LENGTH,
            "feedback.prompt_suffix",
        )


# ============================================================================
# 配置读取函数
# ============================================================================


def get_feedback_config() -> FeedbackConfig:
    """从配置文件加载反馈配置"""
    try:
        config_mgr = get_config()
        feedback_config = config_mgr.get_section("feedback")

        timeout = int(
            get_compat_config(
                feedback_config, "backend_max_wait", "timeout", FEEDBACK_TIMEOUT_DEFAULT
            )
        )
        auto_resubmit_timeout = int(
            get_compat_config(
                feedback_config,
                "frontend_countdown",
                "auto_resubmit_timeout",
                AUTO_RESUBMIT_TIMEOUT_DEFAULT,
            )
        )
        resubmit_prompt = str(
            feedback_config.get("resubmit_prompt", RESUBMIT_PROMPT_DEFAULT)
        )
        prompt_suffix = str(feedback_config.get("prompt_suffix", PROMPT_SUFFIX_DEFAULT))

        return FeedbackConfig(
            timeout=timeout,
            auto_resubmit_timeout=auto_resubmit_timeout,
            resubmit_prompt=resubmit_prompt,
            prompt_suffix=prompt_suffix,
        )
    except (ValueError, TypeError) as e:
        logger.warning(f"获取反馈配置失败（类型错误），使用默认值: {e}", exc_info=True)
        return FeedbackConfig(
            timeout=FEEDBACK_TIMEOUT_DEFAULT,
            auto_resubmit_timeout=AUTO_RESUBMIT_TIMEOUT_DEFAULT,
            resubmit_prompt=RESUBMIT_PROMPT_DEFAULT,
            prompt_suffix=PROMPT_SUFFIX_DEFAULT,
        )
    except Exception as e:
        logger.warning(f"获取反馈配置失败，使用默认值: {e}", exc_info=True)
        return FeedbackConfig(
            timeout=FEEDBACK_TIMEOUT_DEFAULT,
            auto_resubmit_timeout=AUTO_RESUBMIT_TIMEOUT_DEFAULT,
            resubmit_prompt=RESUBMIT_PROMPT_DEFAULT,
            prompt_suffix=PROMPT_SUFFIX_DEFAULT,
        )


def calculate_backend_timeout(
    auto_resubmit_timeout: int, max_timeout: int = 0, infinite_wait: bool = False
) -> int:
    """计算后端等待超时：前端倒计时 + 缓冲，0 表示无限等待"""
    if infinite_wait:
        return 0

    if max_timeout <= 0:
        feedback_config = get_feedback_config()
        max_timeout = feedback_config.timeout

    if auto_resubmit_timeout <= 0:
        return max(max_timeout, BACKEND_MIN)

    calculated = max(auto_resubmit_timeout + BACKEND_BUFFER, BACKEND_MIN)
    return min(calculated, max_timeout)


def get_feedback_prompts() -> tuple[str, str]:
    """获取 (resubmit_prompt, prompt_suffix)"""
    config = get_feedback_config()
    return config.resubmit_prompt, config.prompt_suffix


def _append_prompt_suffix(text: str) -> str:
    """为用户反馈类文本追加 prompt_suffix（若已存在则不重复追加）"""
    _, prompt_suffix = get_feedback_prompts()
    if not prompt_suffix:
        return text
    return text if text.endswith(prompt_suffix) else (text + prompt_suffix)


@overload
def _make_resubmit_response(as_mcp: Literal[True] = ...) -> list: ...


@overload
def _make_resubmit_response(as_mcp: Literal[False]) -> dict: ...


def _make_resubmit_response(as_mcp: bool = True) -> list | dict:
    """创建错误/超时的重新提交响应"""
    resubmit_prompt, _ = get_feedback_prompts()
    if as_mcp:
        return [TextContent(type="text", text=resubmit_prompt)]
    return {"text": resubmit_prompt}


# ============================================================================
# 输入验证
# ============================================================================


def validate_input(
    prompt: str, predefined_options: list | None = None
) -> tuple[str, list]:
    """验证清理输入：截断过长内容，过滤非法选项"""
    try:
        cleaned_prompt = prompt.strip()
    except AttributeError:
        raise ValueError("prompt 必须是字符串类型") from None
    if len(cleaned_prompt) > MAX_MESSAGE_LENGTH:
        logger.warning(
            f"prompt 长度过长 ({len(cleaned_prompt)} 字符)，将被截断到 {MAX_MESSAGE_LENGTH}"
        )
        cleaned_prompt = cleaned_prompt[:MAX_MESSAGE_LENGTH] + "..."

    cleaned_options: list[str] = []
    if predefined_options:
        for option in predefined_options:
            if not isinstance(option, str):
                logger.warning(f"跳过非字符串选项: {option}")
                continue
            cleaned_option = option.strip()
            if cleaned_option and len(cleaned_option) <= MAX_OPTION_LENGTH:
                cleaned_options.append(cleaned_option)
            elif len(cleaned_option) > MAX_OPTION_LENGTH:
                logger.warning(f"选项过长被截断: {cleaned_option[:50]}...")
                cleaned_options.append(cleaned_option[:MAX_OPTION_LENGTH] + "...")

    return cleaned_prompt, cleaned_options


# ============================================================================
# 工具函数
# ============================================================================


def _generate_task_id() -> str:
    """生成全局唯一任务 ID（避免极端并发下碰撞）"""
    project_name = Path.cwd().name or "task"
    return f"{project_name}-{uuid.uuid4()}"


def get_target_host(host: str) -> str:
    """将不可直连的监听地址转换为客户端可访问地址（如 localhost）"""
    return "localhost" if host in {"0.0.0.0", "::"} else host


# ============================================================================
# 图片处理与 MCP 响应构建
# ============================================================================


def _format_file_size(size: int) -> str:
    """格式化文件大小为人类可读格式"""
    if size < 1024:
        return f"{size} B"
    if size < 1024 * 1024:
        return f"{size / 1024:.1f} KB"
    return f"{size / (1024 * 1024):.1f} MB"


def _guess_mime_type_from_data(base64_data: str) -> str | None:
    """通过文件魔数猜测 MIME 类型"""
    try:
        snippet = base64_data[:256]
        snippet += "=" * ((4 - len(snippet) % 4) % 4)
        raw = base64.b64decode(snippet, validate=False)

        mime_signatures = [
            (b"\x89PNG\r\n\x1a\n", "image/png"),
            (b"\xff\xd8\xff", "image/jpeg"),
            (b"GIF87a", "image/gif"),
            (b"GIF89a", "image/gif"),
            (b"BM", "image/bmp"),
            (b"II*\x00", "image/tiff"),
            (b"MM\x00*", "image/tiff"),
            (b"\x00\x00\x01\x00", "image/x-icon"),
        ]

        for signature, mime_type in mime_signatures:
            if raw.startswith(signature):
                return mime_type

        if raw.startswith(b"RIFF") and len(raw) >= 12 and raw[8:12] == b"WEBP":
            return "image/webp"

        # SVG 检测已移除：与 file_validator.py 安全策略对齐，SVG 可嵌入脚本

    except Exception:
        pass
    return None


def _process_image(image: dict, index: int) -> tuple[ImageContent | None, str | None]:
    """处理单张图片，返回 (ImageContent, 文本描述)"""
    base64_data = image.get("data")
    if not isinstance(base64_data, str) or not base64_data.strip():
        logger.warning(f"图片 {index + 1} 的 data 字段无效: {type(base64_data)}")
        return None, f"=== 图片 {index + 1} ===\n处理失败: 图片数据无效"

    base64_data = base64_data.strip()

    inferred_mime_type: str | None = None
    if base64_data.startswith("data:") and ";base64," in base64_data:
        header, b64 = base64_data.split(",", 1)
        base64_data = b64.strip()
        if header.startswith("data:"):
            inferred_mime_type = header[5:].split(";", 1)[0].strip() or None

    content_type = (
        image.get("content_type")
        or image.get("mimeType")
        or image.get("mime_type")
        or inferred_mime_type
        or "image/jpeg"
    )

    content_type = str(content_type).strip()
    if ";" in content_type:
        content_type = content_type.split(";", 1)[0].strip()
    content_type = content_type.lower()
    if content_type == "image/jpg":
        content_type = "image/jpeg"

    if not content_type.startswith("image/"):
        guessed = _guess_mime_type_from_data(base64_data)
        content_type = guessed or "image/jpeg"

    filename = image.get("filename", f"image_{index + 1}")
    size = image.get("size", len(base64_data) * 3 // 4)
    text_desc = f"=== 图片 {index + 1} ===\n文件名: {filename}\n类型: {content_type}\n大小: {_format_file_size(size)}"

    return (
        ImageContent(type="image", data=base64_data, mimeType=str(content_type)),
        text_desc,
    )


def parse_structured_response(
    response_data: dict[str, Any] | None,
) -> list[ContentBlock]:
    """解析反馈数据为 MCP Content 列表"""
    result: list[ContentBlock] = []
    text_parts: list[str] = []

    if not isinstance(response_data, dict):
        response_data = {}

    logger.debug(f"parse_structured_response 接收数据: {type(response_data)}")

    legacy_text = response_data.get("interactive_feedback")
    user_input = response_data.get("user_input", "") or ""
    if not user_input and isinstance(legacy_text, str) and legacy_text.strip():
        user_input = legacy_text

    selected_options_raw = response_data.get("selected_options", [])
    selected_options = (
        [str(x) for x in selected_options_raw if x is not None]
        if isinstance(selected_options_raw, list)
        else []
    )

    logger.debug(
        f"解析结果: user_input={len(user_input)}字符, options={len(selected_options)}个"
    )

    if selected_options:
        text_parts.append(f"选择的选项: {', '.join(selected_options)}")
    if user_input:
        text_parts.append(f"用户输入: {user_input}")

    images = response_data.get("images", []) or []
    for index, image in enumerate(images):
        if not isinstance(image, dict):
            continue
        try:
            img_content, text_desc = _process_image(image, index)
            if img_content:
                result.append(img_content)
            if text_desc:
                text_parts.append(text_desc)
        except Exception as e:
            logger.error(f"处理图片 {index + 1} 时出错: {e}", exc_info=True)
            text_parts.append(f"=== 图片 {index + 1} ===\n处理失败: {e!s}")

    combined_text = "\n\n".join(text_parts) if text_parts else "用户未提供任何内容"

    combined_text = _append_prompt_suffix(combined_text)

    result.append(TextContent(type="text", text=combined_text))

    logger.debug("最终返回结果:")
    for i, item in enumerate(result):
        if isinstance(item, TextContent):
            preview = item.text[:100] + ("..." if len(item.text) > 100 else "")
            logger.debug(f"  - [{i}] TextContent: '{preview}'")
        elif isinstance(item, ImageContent):
            logger.debug(
                f"  - [{i}] ImageContent: mimeType={item.mimeType}, data_length={len(item.data)}"
            )
        else:
            logger.debug(f"  - [{i}] 未知类型: {type(item)}")

    return result
