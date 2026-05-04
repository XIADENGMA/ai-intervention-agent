# config_manager

配置管理模块：TOML 配置文件的跨平台加载、读写、热重载。

核心特性：使用可重入锁（RLock）保护共享状态、延迟保存优化、network_security 独立管理、文件变更监听。
旧 JSONC/JSON 文件在首次加载时自动迁移为 TOML。
通过 get_config() 获取全局 ConfigManager 实例。

## 函数

### `_is_sensitive_config_key(key: str) -> bool`

### `_sanitize_config_value_for_log(key: str, value: Any) -> str`

### `parse_jsonc(content: str) -> dict[str, Any]`

解析 JSONC（带注释的 JSON）为字典，支持 // 单行注释和 /* */ 多行注释。

异常:
    json.JSONDecodeError: JSON 语法错误时抛出

### `_is_uvx_mode() -> bool`

检测是否应使用“用户配置目录”（uvx/安装模式）而非“开发模式”。

说明
----
- **用户模式（True）**：使用用户配置目录（跨平台标准路径）。
  - uvx 运行（推荐给普通用户）
  - 通过 pip/uv 安装后运行（避免在任意项目目录意外生成 config.jsonc）
- **开发模式（False）**：优先使用当前目录配置（从仓库运行时更方便调试）。

判定规则
----
1) 若检测到 uvx 运行特征（sys.executable 含 uvx 或 UVX_PROJECT 环境变量），返回 True
2) 若当前代码看起来位于本仓库源码树内，且当前工作目录位于该源码树内，返回 False
3) 其他情况（默认）：返回 True

### `find_config_file(config_filename: str = 'config.toml') -> Path`

查找配置文件路径，支持环境变量覆盖、uvx 模式和开发模式。

查找优先级（开发模式）：当前目录 > 用户配置目录 > 创建新配置。
格式优先级：TOML > JSONC > JSON（向后兼容）。
uvx 模式仅使用用户配置目录。
跨平台配置目录：Linux ~/.config、macOS ~/Library/Application Support、Windows %APPDATA%。

### `_get_user_config_dir_fallback() -> Path`

platformdirs 不可用时的回退实现，返回跨平台标准配置目录。

Windows: %APPDATA%、macOS: ~/Library/Application Support、Linux: $XDG_CONFIG_HOME 或 ~/.config。

### `_shutdown_global_config_manager()`

### `get_config() -> ConfigManager`

获取全局配置管理器实例（自动启动文件监听）

## 类

### `class ReadWriteLock`

读写锁：多读者并发、写者独占，基于 Condition + RLock 实现。

注意：本类目前未被 ConfigManager 使用（ConfigManager 使用 threading.RLock），
作为独立工具类保留，供需要读写分离锁场景的调用方使用。

#### 方法

##### `__init__(self)`

初始化读写锁

##### `read_lock(self) -> Generator[None, None, None]`

获取读锁（多读者并发，仅在写者持有锁时阻塞）

##### `write_lock(self) -> Generator[None, None, None]`

获取写锁（独占访问，等待所有读者退出）

### `class ConfigManager`

配置管理器：TOML 配置文件的加载、读写、持久化、热重载。

核心特性：使用可重入锁（RLock）保护共享状态、延迟保存优化、network_security 独立管理（带缓存）、
文件变更监听、配置导入导出。通过模块级 config_manager 全局实例访问。

支持格式：TOML（主格式）。旧 JSONC/JSON 文件在首次加载时自动迁移为 TOML。

路由通过 Mixin 拆分（各 Mixin 定义在 config_modules/ 下）：
- TomlEngineMixin: TOML 格式解析/保存（保留注释）
- NetworkSecurityMixin: network_security 段校验/读写
- FileWatcherMixin: 文件监听/回调/shutdown
- IOOperationsMixin: 配置导出/导入/备份/恢复

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

##### `invalidate_all_caches(self) -> None`

清空所有配置缓存

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
