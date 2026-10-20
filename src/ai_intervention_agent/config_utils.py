"""配置工具模块：边界值验证、向后兼容配置读取、类型转换辅助。"""

import logging
from collections.abc import Mapping
from typing import Any, TypeVar, cast, overload

logger = logging.getLogger(__name__)


Number = int | float

T = TypeVar("T")


@overload
def clamp_value(
    value: int,
    min_val: int,
    max_val: int,
    field_name: str,
    log_warning: bool = True,
) -> int: ...


@overload
def clamp_value(
    value: float,
    min_val: float,
    max_val: float,
    field_name: str,
    log_warning: bool = True,
) -> float: ...


def clamp_value(
    value: Number,
    min_val: Number,
    max_val: Number,
    field_name: str,
    log_warning: bool = True,
) -> Number:
    """将值限制在 [min_val, max_val] 范围内，超出时记录警告"""
    if value < min_val:
        if log_warning:
            logger.warning(f"{field_name} ({value}) 小于最小值 {min_val}，已调整")
        return min_val
    if value > max_val:
        if log_warning:
            logger.warning(f"{field_name} ({value}) 大于最大值 {max_val}，已调整")
        return max_val
    return value


def clamp_dataclass_field(
    obj: Any,
    field_name: str,
    min_val: Number,
    max_val: Number,
) -> None:
    """在 dataclass __post_init__ 中限制字段值（支持 frozen=True）"""
    current_value = getattr(obj, field_name)
    clamped_value = clamp_value(
        cast(Number, current_value), min_val, max_val, field_name
    )
    if current_value != clamped_value:
        object.__setattr__(obj, field_name, clamped_value)


def get_compat_config(
    config: Mapping[str, Any],
    new_key: str,
    old_key: str | None = None,
    default: Any = None,
) -> Any:
    """获取配置值，优先级：new_key > old_key > default"""
    if new_key in config:
        return config[new_key]
    if old_key and old_key in config:
        return config[old_key]
    return default


# 旧配置键 -> 现行配置键：(段, 旧名, 新名)。docs/configuration.md 的 Backward compatibility
# 一节列的就是这张表。network_security.enable_access_control 不在其中：它由
# NetworkSecurityMixin 直接读文件里的原始值，从来不经过默认值合并。
LEGACY_KEY_ALIASES: tuple[tuple[str, str, str], ...] = (
    ("feedback", "timeout", "backend_max_wait"),
    ("feedback", "auto_resubmit_timeout", "frontend_countdown"),
    ("web_ui", "max_retries", "http_max_retries"),
    ("web_ui", "retry_delay", "http_retry_delay"),
    ("web_ui", "timeout", "http_request_timeout"),
)


def apply_legacy_key_aliases(config: dict[str, Any]) -> list[tuple[str, str, str]]:
    """文件里只写了旧名字的配置项，把它的值放到新名字上（原地修改）。

    config 是从配置文件里读出来、还没有合并默认值的各段；每采用一个旧名字打一条 INFO 日志
    （写明新旧两个键名），并把被采用的 (段, 旧名, 新名) 作为列表返回。

    必须在合并默认值之前调用：合并之后每个新键都带着默认值在场，"新键没写"这个判断就再也
    做不出来。get_compat_config 先看新键，永远看得到，旧名字因此一次都没被读到过（R795）。
    新键只要在文件里（哪怕写的是默认值）就不动；旧键本身也留在原处，文件不会被改写。
    不是 dict 的段、表里没有的键一律跳过。
    """
    applied: list[tuple[str, str, str]] = []
    for section_name, old_key, new_key in LEGACY_KEY_ALIASES:
        section = config.get(section_name)
        if not isinstance(section, dict):
            continue
        if old_key in section and new_key not in section:
            section[new_key] = section[old_key]
            applied.append((section_name, old_key, new_key))
            logger.info(
                f"配置项 {section_name}.{old_key} 是旧名称，已按 {section_name}.{new_key} "
                f"读取（文件里没有写 {new_key}）；建议改用新名称"
            )
    return applied


def get_typed_config(
    config: dict,
    key: str,
    default: T,
    value_type: type[T],
    min_val: Number | None = None,
    max_val: Number | None = None,
    old_key: str | None = None,
) -> T:
    """获取配置值并进行类型转换和边界验证"""
    raw_value = get_compat_config(config, key, old_key, default)

    typed_value: T = default
    try:
        if value_type is bool and isinstance(raw_value, str):
            typed_value = cast(T, raw_value.lower() in ("true", "1", "yes", "on"))
        else:
            typed_value = cast(T, cast(Any, value_type)(raw_value))
    except (ValueError, TypeError):
        logger.warning(
            f"配置 {key} 值 '{raw_value}' 类型转换失败，使用默认值 {default}"
        )
        typed_value = default

    if (
        min_val is not None
        and max_val is not None
        and isinstance(typed_value, (int, float))
    ):
        typed_value = cast(
            T,
            clamp_value(
                cast(Number, typed_value),
                min_val,
                max_val,
                key,
            ),
        )

    return typed_value


def validate_enum_value(
    value: str,
    valid_values: tuple,
    field_name: str,
    default: str,
) -> str:
    """验证枚举值是否在有效范围内，无效时返回默认值"""
    if value in valid_values:
        return value
    logger.warning(
        f"{field_name} '{value}' 无效，有效值: {valid_values}，使用默认值 '{default}'"
    )
    return default


def truncate_string(
    value: str | None,
    max_length: int,
    field_name: str,
    default: str | None = None,
    log_warning: bool = True,
) -> str:
    """截断字符串到指定长度，空值时使用默认值"""

    if not value or not value.strip():
        if default is not None:
            if log_warning:
                logger.warning(f"{field_name} 为空，使用默认值")
            return default
        return value if value is not None else ""

    if len(value) > max_length:
        if log_warning:
            logger.warning(f"{field_name} 过长 ({len(value)}>{max_length})，已截断")
        return value[:max_length]

    return value
