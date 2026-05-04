# config_utils

> 英文 signature-only 版本（仅函数 / 类签名速查）：[`docs/api/config_utils.md`](../api/config_utils.md)

配置工具模块：边界值验证、向后兼容配置读取、类型转换辅助。

## 函数

### `clamp_value(value: int, min_val: int, max_val: int, field_name: str, log_warning: bool = True) -> int`

### `clamp_value(value: float, min_val: float, max_val: float, field_name: str, log_warning: bool = True) -> float`

### `clamp_value(value: Number, min_val: Number, max_val: Number, field_name: str, log_warning: bool = True) -> Number`

将值限制在 [min_val, max_val] 范围内，超出时记录警告

### `clamp_dataclass_field(obj: Any, field_name: str, min_val: Number, max_val: Number) -> None`

在 dataclass __post_init__ 中限制字段值（支持 frozen=True）

### `get_compat_config(config: Mapping[str, Any], new_key: str, old_key: str | None = None, default: Any = None) -> Any`

获取配置值，优先级：new_key > old_key > default

### `get_typed_config(config: dict, key: str, default: T, value_type: type[T], min_val: Number | None = None, max_val: Number | None = None, old_key: str | None = None) -> T`

获取配置值并进行类型转换和边界验证

### `validate_enum_value(value: str, valid_values: tuple, field_name: str, default: str) -> str`

验证枚举值是否在有效范围内，无效时返回默认值

### `truncate_string(value: str | None, max_length: int, field_name: str, default: str | None = None, log_warning: bool = True) -> str`

截断字符串到指定长度，空值时使用默认值
