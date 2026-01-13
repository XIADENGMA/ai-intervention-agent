#!/usr/bin/env python3
"""
配置工具模块：边界值验证、向后兼容配置读取、类型转换辅助。
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
    config: dict,
    new_key: str,
    old_key: Optional[str] = None,
    default: Any = None,
) -> Any:
    """获取配置值，优先级：new_key > old_key > default"""
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
    """获取配置值并进行类型转换和边界验证"""
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
    default: Optional[str] = None,
    log_warning: bool = True,
) -> str:
    """截断字符串到指定长度，空值时使用默认值"""
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
