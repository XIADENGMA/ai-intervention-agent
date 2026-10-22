# config_utils

> 英文 signature-only 版本（仅函数 / 类签名速查）：[`docs/api/config_utils.md`](../api/config_utils.md)

配置工具模块：边界值验证、向后兼容配置读取、类型转换辅助、仅属主可读的文件写入。

## 函数

### `clamp_value(value: int, min_val: int, max_val: int, field_name: str, log_warning: bool = True) -> int`

### `clamp_value(value: float, min_val: float, max_val: float, field_name: str, log_warning: bool = True) -> float`

### `clamp_value(value: Number, min_val: Number, max_val: Number, field_name: str, log_warning: bool = True) -> Number`

将值限制在 [min_val, max_val] 范围内，超出时记录警告

### `clamp_dataclass_field(obj: Any, field_name: str, min_val: Number, max_val: Number) -> None`

在 dataclass __post_init__ 中限制字段值（支持 frozen=True）

### `get_compat_config(config: Mapping[str, Any], new_key: str, old_key: str | None = None, default: Any = None) -> Any`

获取配置值，优先级：new_key > old_key > default

### `apply_legacy_key_aliases(config: dict[str, Any]) -> list[tuple[str, str, str]]`

文件里只写了旧名字的配置项，把它的值放到新名字上（原地修改）。

config 是从配置文件里读出来、还没有合并默认值的各段；每采用一个旧名字打一条 INFO 日志
（写明新旧两个键名），并把被采用的 (段, 旧名, 新名) 作为列表返回。

必须在合并默认值之前调用：合并之后每个新键都带着默认值在场，"新键没写"这个判断就再也
做不出来。get_compat_config 先看新键，永远看得到，旧名字因此一次都没被读到过（R795）。
新键只要在文件里（哪怕写的是默认值）就不动；旧键本身也留在原处，文件不会被改写。
不是 dict 的段、表里没有的键一律跳过。

### `get_typed_config(config: dict, key: str, default: T, value_type: type[T], min_val: Number | None = None, max_val: Number | None = None, old_key: str | None = None) -> T`

获取配置值并进行类型转换和边界验证

### `validate_enum_value(value: str, valid_values: tuple, field_name: str, default: str) -> str`

验证枚举值是否在有效范围内，无效时返回默认值

### `truncate_string(value: str | None, max_length: int, field_name: str, default: str | None = None, log_warning: bool = True) -> str`

截断字符串到指定长度，空值时使用默认值

### `restrict_to_owner(path: str | os.PathLike[str]) -> None`

把 ``path`` 收紧到 0600；尽力而为，做不到只留一条 DEBUG。

FAT / 部分网络盘不支持 chmod（Windows 上它只管只读位），文件不存在也一样：
这些情况下文件照用，只是没法收紧，不该让第一次运行或一次保存失败。

### `_restrict_descriptor_to_owner(fd: int) -> bool`

``fchmod(fd, 0600)``，尽力而为；成功返回 ``True``。

### `write_text_owner_only(path: str | os.PathLike[str], text: str) -> None`

写文本文件；文件还不存在时直接以 0600 创建，不会先以 0644 / 0666 出现再收紧。

``open(path, "w")`` 建出来的模式是 ``0666 & ~umask``：umask 022 时同机所有账号可读，
umask 0（容器、``UMask=0000``）时还可写。这里把模式交给 ``os.open``，umask 只会再
拿掉几位，不会放宽。

文件已经存在时默认保持它的模式——那可能是用户有意放宽的（组共享），不该悄悄收回。
代理自己生成的文件（备份、``.tmp``）每次都会写进当前的密钥，传 ``tighten_existing=True``
让旧版本留下的 0644 文件在被覆盖时一并收紧：在已打开的描述符上 ``fchmod``，第一个字节
写进去之前就是 0600；没有 ``fchmod`` 的平台（Windows）或它失败时，写完再按路径 chmod。
