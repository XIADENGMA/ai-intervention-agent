# config_manager

> 英文 signature-only 版本（仅函数 / 类签名速查）：[`docs/api/config_manager.md`](../api/config_manager.md)

配置管理模块：TOML 配置文件的跨平台加载、读写、热重载。

## 函数

### `_is_sensitive_config_key(key: str) -> bool`

### `_sanitize_config_value_for_log(key: str, value: Any) -> str`

### `parse_jsonc(content: str) -> dict[str, Any]`

解析 JSONC（带注释的 JSON）为字典，支持 // 单行注释和 /* */ 多行注释。

### `_path_contains_segment(candidate: Path | str, segment: str) -> bool`

检测路径中是否包含某个完整的目录段（不会被前缀/后缀误匹配）。

### `_looks_like_repo_checkout(module_dir: Path) -> bool`

模块目录是否是本仓库源码树（``src/ai_intervention_agent/`` 形态）。

### `_path_under(child: Path, parents: tuple[Path, ...]) -> bool`

``child`` 是否位于 ``parents`` 任一目录下（含 child == parent 等价）。

### `_is_isolated_install_runtime() -> bool`

启发式检测当前 Python 是否运行在 uv / uvx / uv tool / pipx / pip 隔离环境。

### `_is_uvx_mode() -> bool`

检测是否应使用"用户配置目录"（uvx / 已安装模式）而非"开发模式"。

### `_macos_legacy_xdg_config_dir() -> Path | None`

**R113** — 返回 macOS 上 ``~/.config/ai-intervention-agent/`` 残留目录。

### `_retire_legacy_config_file(legacy_file: Path) -> bool`

R686：把 legacy 配置文件重命名为 ``<name>.migrated-<时间戳>`` 备份。

### `_migrate_legacy_config_to_standard(legacy_file: Path, standard_dir: Path) -> Path | None`

R686（TODO#4）：把 macOS legacy ``~/.config/...`` 配置迁移到标准目录。

### `_files_have_same_content(a: Path, b: Path) -> bool`

比较两个小文件内容是否一致（配置文件 KB 级，直接读全量即可）。

### `_is_same_physical_file(a: Path, b: Path) -> bool`

R703：判断两个路径是否解析到同一物理文件（samefile 优先，降级 resolve）。

### `_resolve_standard_user_config_dir() -> Path`

解析"标准用户配置目录"（R703：macOS 上免疫 ``XDG_CONFIG_HOME`` 改写）。

### `find_default_config_template() -> Path | None`

定位带注释的默认配置模板：安装包里在包目录内，源码树里在仓库根。

### `_why_path_cannot_be_examined(path: Path) -> str | None`

``stat`` 一次路径：检查不了时返回原因，存在或只是"不存在"时返回 ``None``。

直接 ``os.stat`` 而不是 ``Path.exists()``：哪些错误算"检查不了"由上面两张表决定，写在
这里、能被测试钉住，不取决于 ``pathlib`` 在某个 Python 版本里怎么处理异常。

### `_config_file_from_env_override(override: str, config_filename: str) -> Path | None`

``AI_INTERVENTION_AGENT_CONFIG_FILE`` 指向的配置文件路径；路径检查不了时返回 ``None``（R793）。

环境变量里写的路径落在没有搜索权限的目录里、某一段超出文件系统上限、或者是
``~没有这个用户/...`` 时，``Path.is_dir()`` / ``Path.expanduser()`` 会抛出 ``PermissionError`` /
``OSError`` / ``RuntimeError``——而 ``config_manager`` 在 import 时就要实例化全局
``ConfigManager()``，于是 MCP 服务器、Web UI、``--print-config`` 全部带着原始 traceback 起不来。
其它环境变量（端口、日志级别……）写错都是"忽略 + 警告"，这里与它们一致：打一条警告，
返回 ``None``，调用方按没有设置这个环境变量继续找标准配置位置；用户指定的位置一个字节都不动。
路径"只是不存在"不算检查不了：照旧使用，文件由后面的流程创建。

### `find_config_file(config_filename: str = 'config.toml') -> Path`

查找配置文件路径，支持环境变量覆盖、uvx / 安装模式和开发模式。

### `_get_user_config_dir_fallback() -> Path`

platformdirs 不可用时的回退实现，返回跨平台标准配置目录。

### `_shutdown_global_config_manager()`

### `get_config() -> ConfigManager`

获取全局配置管理器实例（自动启动文件监听）

## 类

### `class ConfigManager`

配置管理器：TOML 配置文件的加载、读写、持久化、热重载。

#### 方法

##### `__init__(self, config_file: str = 'config.toml')`

初始化配置管理器：查找配置文件、初始化锁和缓存、加载配置、启动文件监听

##### `get(self, key: str, default: Any = None) -> Any`

获取配置值（支持点号分隔的嵌套键如 'notification.sound_volume'，线程安全）

##### `set(self, key: str, value: Any, save: bool = True) -> None`

设置配置值（支持嵌套键，自动创建中间路径，值变化检测，可选延迟保存）

##### `update(self, updates: dict[str, Any], save: bool = True) -> None`

批量更新配置（仅处理变化项，合并为一次延迟保存，原子操作）

##### `force_save(self) -> None`

强制立即保存配置文件（取消延迟保存，应用所有待保存变更）

##### `get_section(self, section: str, use_cache: bool = True) -> dict[str, Any]`

获取配置段的深拷贝（带 Pydantic 校验、缓存优化，network_security 特殊处理）

##### `update_section(self, section: str, updates: dict[str, Any], save: bool = True) -> None`

更新配置段（检测变化，触发回调，可选延迟保存）

##### `reload(self) -> None`

从磁盘重新加载配置文件（覆盖内存配置，失效缓存）

##### `invalidate_section_cache(self, section: str) -> None`

失效指定配置段的缓存

##### `cache_epoch(self) -> int`

缓存被整体失效的次数；缓存了配置派生值的调用方用它判断自己手里的是不是最新一份（R792）。

``reload()`` 和 ``restore_config()`` 在把内存里的配置整体换成磁盘上的内容之后都会
清空缓存，每清一次加一。调用方先取这个数、再读配置，把两者一起记下来；之后数字变了，
说明内存里的配置在它读过之后被换过。文件的 mtime 做不到这一点：磁盘上的文件改了，
监听线程最多 2 秒后才把新内容读进内存，这段时间里按新 mtime 读到的还是旧内容。

##### `invalidate_all_caches(self) -> None`

清空所有配置缓存（最后把 ``cache_epoch`` 加一：先清缓存、再加，读到新数字的人一定读到新内容）

##### `get_cache_stats(self) -> dict[str, Any]`

获取缓存统计（命中/未命中/失效次数、命中率等）

##### `reset_cache_stats(self) -> None`

重置缓存统计信息

##### `set_cache_ttl(self, section_ttl: float | None = None, network_security_ttl: float | None = None) -> None`

设置缓存有效期（TTL）

##### `get_all(self) -> dict[str, Any]`

获取所有配置的深拷贝（不含 network_security），防止外部修改内部状态

##### `get_typed(self, key: str, default: Any, value_type: type, min_val: Any | None = None, max_val: Any | None = None) -> Any`

获取配置值，带类型转换和边界验证

##### `get_int(self, key: str, default: int = 0, min_val: int | None = None, max_val: int | None = None) -> int`

获取整数配置值

##### `get_float(self, key: str, default: float = 0.0, min_val: float | None = None, max_val: float | None = None) -> float`

获取浮点数配置值

##### `get_bool(self, key: str, default: bool = False) -> bool`

获取布尔配置值

##### `get_str(self, key: str, default: str = '', max_length: int | None = None) -> str`

获取字符串配置值（可选截断）
