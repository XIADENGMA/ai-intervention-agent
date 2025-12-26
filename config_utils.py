#!/usr/bin/env python3
"""
配置工具模块

提供配置相关的公共辅助函数，减少代码重复。

【主要功能】
- 边界值验证和调整
- 向后兼容的配置读取
- 类型转换辅助

【使用场景】
- WebUIConfig、FeedbackConfig、NotificationConfig 等配置类
- 配置文件读取和验证
"""

import logging
from typing import Any, Optional, TypeVar, cast, overload

logger = logging.getLogger(__name__)

# 数值类型别名：用于边界校验（int/float 均支持比较运算）
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
    """
    将值限制在指定范围内

    参数
    ----
    value : T
        要限制的值
    min_val : T
        最小允许值
    max_val : T
        最大允许值
    field_name : str
        字段名称（用于日志）
    log_warning : bool
        是否记录警告日志，默认 True

    返回
    ----
    T
        限制后的值

    示例
    ----
    >>> clamp_value(150, 0, 100, "volume")
    100
    >>> clamp_value(-10, 0, 100, "volume")
    0
    """
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
    """
    在 dataclass 的 __post_init__ 中限制字段值

    参数
    ----
    obj : Any
        dataclass 实例
    field_name : str
        字段名称
    min_val : T
        最小允许值
    max_val : T
        最大允许值

    说明
    ----
    使用 object.__setattr__ 绑定新值，适用于 frozen=True 的 dataclass。

    示例
    ----
    >>> @dataclass
    ... class Config:
    ...     timeout: int = 30
    ...     def __post_init__(self):
    ...         clamp_dataclass_field(self, "timeout", 1, 300)
    """
    current_value = getattr(obj, field_name)
    clamped_value = clamp_value(
        cast(Number, current_value), min_val, max_val, field_name
    )
    if current_value != clamped_value:
        object.__setattr__(obj, field_name, clamped_value)


def get_compat_config(
    config: dict,
    new_key: str,
    old_key: Optional[str] = None,
    default: Any = None,
) -> Any:
    """
    获取配置值，支持向后兼容

    参数
    ----
    config : dict
        配置字典
    new_key : str
        新的配置键名
    old_key : Optional[str]
        旧的配置键名（用于向后兼容）
    default : Any
        默认值

    返回
    ----
    Any
        配置值，按优先级：new_key > old_key > default

    示例
    ----
    >>> config = {"old_timeout": 60}
    >>> get_compat_config(config, "http_request_timeout", "old_timeout", 30)
    60
    >>> config = {"http_request_timeout": 120}
    >>> get_compat_config(config, "http_request_timeout", "old_timeout", 30)
    120
    """
    if new_key in config:
        return config[new_key]
    if old_key and old_key in config:
        return config[old_key]
    return default


def get_typed_config(
    config: dict,
    key: str,
    default: T,
    value_type: type[T],
    min_val: Number | None = None,
    max_val: Number | None = None,
    old_key: Optional[str] = None,
) -> T:
    """
    获取配置值并进行类型转换和边界验证

    参数
    ----
    config : dict
        配置字典
    key : str
        配置键名
    default : T
        默认值
    value_type : type
        目标类型（int, float, str, bool）
    min_val : Optional[T]
        最小值（可选）
    max_val : Optional[T]
        最大值（可选）
    old_key : Optional[str]
        旧的配置键名（用于向后兼容）

    返回
    ----
    T
        类型转换并验证后的值

    示例
    ----
    >>> config = {"timeout": "30"}
    >>> get_typed_config(config, "timeout", 60, int, 1, 300)
    30
    >>> config = {"timeout": "invalid"}
    >>> get_typed_config(config, "timeout", 60, int, 1, 300)
    60
    """
    raw_value = get_compat_config(config, key, old_key, default)

    # 类型转换
    typed_value: T = default
    try:
        if value_type is bool and isinstance(raw_value, str):
            # 特殊处理字符串布尔值
            typed_value = cast(T, raw_value.lower() in ("true", "1", "yes", "on"))
        else:
            typed_value = value_type(raw_value)
    except (ValueError, TypeError):
        logger.warning(
            f"配置 {key} 值 '{raw_value}' 类型转换失败，使用默认值 {default}"
        )
        typed_value = default

    # 边界验证（仅对数值类型）
    if min_val is not None and max_val is not None:
        if isinstance(typed_value, (int, float)):
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
    """
    验证枚举值是否在有效范围内

    参数
    ----
    value : str
        要验证的值
    valid_values : tuple
        有效值元组
    field_name : str
        字段名称（用于日志）
    default : str
        无效时的默认值

    返回
    ----
    str
        有效值或默认值

    示例
    ----
    >>> validate_enum_value("url", ("none", "url", "copy"), "bark_action", "none")
    'url'
    >>> validate_enum_value("invalid", ("none", "url", "copy"), "bark_action", "none")
    'none'
    """
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
    default: Optional[str] = None,
    log_warning: bool = True,
) -> str:
    """
    截断字符串到指定长度

    参数
    ----
    value : str
        要截断的字符串
    max_length : int
        最大允许长度
    field_name : str
        字段名称（用于日志）
    default : Optional[str]
        当 value 为空或空白时使用的默认值，None 表示不替换
    log_warning : bool
        是否记录警告日志，默认 True

    返回
    ----
    str
        截断后的字符串

    示例
    ----
    >>> truncate_string("hello world", 5, "text")
    'hello'
    >>> truncate_string("", 10, "text", default="default")
    'default'
    """
    # 处理空值
    if not value or not value.strip():
        if default is not None:
            if log_warning:
                logger.warning(f"{field_name} 为空，使用默认值")
            return default
        return value if value is not None else ""

    # 截断过长的字符串
    if len(value) > max_length:
        if log_warning:
            logger.warning(f"{field_name} 过长 ({len(value)}>{max_length})，已截断")
        return value[:max_length]

    return value
