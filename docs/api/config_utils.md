# config_utils

配置工具模块

提供配置相关的公共辅助函数，减少代码重复。

【主要功能】
- 边界值验证和调整
- 向后兼容的配置读取
- 类型转换辅助

【使用场景】
- WebUIConfig、FeedbackConfig、NotificationConfig 等配置类
- 配置文件读取和验证

## 函数

### `clamp_value(value: T, min_val: T, max_val: T, field_name: str, log_warning: bool = True) -> T`

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

### `clamp_dataclass_field(obj: Any, field_name: str, min_val: T, max_val: T) -> None`

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

### `get_compat_config(config: dict, new_key: str, old_key: Optional[str] = None, default: Any = None) -> Any`

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

### `get_typed_config(config: dict, key: str, default: T, value_type: type, min_val: Optional[T] = None, max_val: Optional[T] = None, old_key: Optional[str] = None) -> T`

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

### `validate_enum_value(value: str, valid_values: tuple, field_name: str, default: str) -> str`

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

### `truncate_string(value: str, max_length: int, field_name: str, default: Optional[str] = None, log_warning: bool = True) -> str`

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
