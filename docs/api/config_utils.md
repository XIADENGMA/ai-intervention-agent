# config_utils

> For the Chinese version with full docstrings, see: [`docs/api.zh-CN/config_utils.md`](../api.zh-CN/config_utils.md)

## Functions

### `clamp_value(value: int, min_val: int, max_val: int, field_name: str, log_warning: bool = True) -> int`

### `clamp_value(value: float, min_val: float, max_val: float, field_name: str, log_warning: bool = True) -> float`

### `clamp_value(value: Number, min_val: Number, max_val: Number, field_name: str, log_warning: bool = True) -> Number`

### `clamp_dataclass_field(obj: Any, field_name: str, min_val: Number, max_val: Number) -> None`

### `get_compat_config(config: dict, new_key: str, old_key: Optional[str] = None, default: Any = None) -> Any`

### `get_typed_config(config: dict, key: str, default: T, value_type: type[T], min_val: Number | None = None, max_val: Number | None = None, old_key: Optional[str] = None) -> T`

### `validate_enum_value(value: str, valid_values: tuple, field_name: str, default: str) -> str`

### `truncate_string(value: str | None, max_length: int, field_name: str, default: Optional[str] = None, log_warning: bool = True) -> str`
