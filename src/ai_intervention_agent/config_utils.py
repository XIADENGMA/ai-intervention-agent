"""配置工具模块：边界值验证、向后兼容配置读取、类型转换辅助、仅属主可读的文件写入、原子写入。"""

import contextlib
import logging
import os
import tempfile
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


# 只有属主能读写。可能装着密钥的文件（config.toml 里的 Bark device key / API token、
# 带 api_token 的备份、还没送达的通知正文）新建时用它；已经存在的文件不动（R827）。
OWNER_ONLY_FILE_MODE = 0o600


def restrict_to_owner(path: str | os.PathLike[str]) -> None:
    """把 ``path`` 收紧到 0600；尽力而为，做不到只留一条 DEBUG。

    FAT / 部分网络盘不支持 chmod（Windows 上它只管只读位），文件不存在也一样：
    这些情况下文件照用，只是没法收紧，不该让第一次运行或一次保存失败。"""
    try:
        os.chmod(path, OWNER_ONLY_FILE_MODE)
    except OSError as exc:
        logger.debug(f"[R827] 无法把 {path} 收紧为仅属主可读写: {exc!r}")


def _restrict_descriptor_to_owner(fd: int) -> bool:
    """``fchmod(fd, 0600)``，尽力而为；成功返回 ``True``。"""
    if not hasattr(os, "fchmod"):
        return False
    try:
        os.fchmod(fd, OWNER_ONLY_FILE_MODE)
    except OSError as exc:
        logger.debug(f"[R827] 无法在描述符上收紧为仅属主可读写: {exc!r}")
        return False
    return True


def write_text_owner_only(
    path: str | os.PathLike[str],
    text: str,
    *,
    encoding: str = "utf-8",
    tighten_existing: bool = False,
) -> None:
    """写文本文件；文件还不存在时直接以 0600 创建，不会先以 0644 / 0666 出现再收紧。

    ``open(path, "w")`` 建出来的模式是 ``0666 & ~umask``：umask 022 时同机所有账号可读，
    umask 0（容器、``UMask=0000``）时还可写。这里把模式交给 ``os.open``，umask 只会再
    拿掉几位，不会放宽。

    文件已经存在时默认保持它的模式——那可能是用户有意放宽的（组共享），不该悄悄收回。
    代理自己生成的文件（备份、``.tmp``）每次都会写进当前的密钥，传 ``tighten_existing=True``
    让旧版本留下的 0644 文件在被覆盖时一并收紧：在已打开的描述符上 ``fchmod``，第一个字节
    写进去之前就是 0600；没有 ``fchmod`` 的平台（Windows）或它失败时，写完再按路径 chmod。"""
    # O_BINARY：Windows 上 os.open 默认是文本模式，再叠上 TextIOWrapper 的换行翻译会写出 \r\r\n
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_BINARY", 0)
    fd = os.open(path, flags, OWNER_ONLY_FILE_MODE)
    try:
        tightened = _restrict_descriptor_to_owner(fd) if tighten_existing else True
        stream = os.fdopen(fd, "w", encoding=encoding)
    except BaseException:
        os.close(fd)
        raise
    with stream:
        stream.write(text)
    if not tightened:
        restrict_to_owner(path)


def atomic_write_text(
    path: str | os.PathLike[str],
    text: str,
    *,
    keep_existing_mode: bool = False,
    temp_prefix: str = "",
) -> None:
    """整个文件换成 ``text``：同目录的临时文件写满 → ``flush`` → ``fsync`` → ``os.replace``。

    读的一侧要么看到旧内容、要么看到新内容，崩溃或断电后也不会留下写了一半的文件；``fsync``
    必须在 ``replace`` 之前，否则文件名已经指向新 inode、数据却还在页缓存里（R17.2）。任何异常
    （包括 ``KeyboardInterrupt`` 和任务取消）都会先删掉临时文件再原样抛出，旧文件原封不动。

    新文件的模式是 ``mkstemp`` 给的 0600：里面可能有密钥（R827）。``keep_existing_mode=True``
    时，被替换的文件原来是什么模式就保持什么模式——可能是用户有意放宽的（组共享），保存一次
    不该悄悄收回；没有 ``os.fchmod`` 的平台（Windows）上这一步跳过。目录要由调用方先建好。
    """
    target = os.fspath(path)
    original_mode: int | None = None
    if keep_existing_mode and hasattr(os, "fchmod"):
        try:
            original_mode = os.stat(target).st_mode
        except OSError:
            pass

    fd, tmp_path = tempfile.mkstemp(
        dir=os.path.dirname(target) or ".", prefix=temp_prefix, suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            if original_mode is not None:
                os.fchmod(stream.fileno(), original_mode)
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp_path, target)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp_path)
        raise
