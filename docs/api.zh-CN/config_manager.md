# config_manager

配置管理模块：JSONC/JSON 配置文件的跨平台加载、读写、热重载。

核心特性：使用可重入锁（RLock）保护共享状态、延迟保存优化、network_security 独立管理、文件变更监听。
通过 get_config() 获取全局 ConfigManager 实例。

## 函数

### `_is_sensitive_config_key(key: str) -> bool`

### `_sanitize_config_value_for_log(key: str, value: Any) -> str`

### `parse_jsonc(content: str) -> Dict[str, Any]`

解析 JSONC（带注释的 JSON）为字典，支持 // 单行注释和 /\* \*/ 多行注释。

异常:
json.JSONDecodeError: JSON 语法错误时抛出

### `_is_uvx_mode() -> bool`

检测是否应使用“用户配置目录”（用户模式：uvx/安装后运行）而非“开发模式”（从仓库运行）。

判定规则（简化）：

- 用户模式（True）：
  - `sys.executable` 路径包含 `uvx`
  - 或存在 `UVX_PROJECT` 环境变量
  - 或无法确认“当前工作目录属于同一份源码仓库”时默认走用户模式（避免在任意仓库/项目目录意外生成 `config.jsonc`）
- 开发模式（False）：
  - 代码文件位于仓库源码树内
  - 且当前工作目录也位于同一源码树内（便于在仓库根目录调试）

### `find_config_file(config_filename: str = 'config.jsonc') -> Path`

查找配置文件路径，支持环境变量覆盖、uvx 模式和开发模式。

查找顺序（高 → 低）：

1. 环境变量强制指定：`AI_INTERVENTION_AGENT_CONFIG_FILE`
   - 指向文件：直接使用该路径
   - 指向目录（或以 `/`、`\` 结尾）：自动拼接 `config_filename`
2. 用户模式（uvx/安装模式）：只使用用户配置目录
   - `config.jsonc` → `config.json`
   - 都不存在则复制模板创建 `config.jsonc`
3. 开发模式（从仓库运行）：优先使用当前目录，再回落用户配置目录
   - 当前目录 `./config.jsonc` → `./config.json`
   - 用户配置目录 `config.jsonc` → `config.json`
   - 都不存在则在用户配置目录创建 `config.jsonc`

支持 `.jsonc`/`.json` 两种格式。
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

#### 方法

##### `__init__(self)`

初始化读写锁

##### `read_lock(self)`

获取读锁（多读者并发，仅在写者持有锁时阻塞）

##### `write_lock(self)`

获取写锁（独占访问，等待所有读者退出）

### `class ConfigManager`

配置管理器：JSONC/JSON 配置文件的加载、读写、持久化、热重载。

核心特性：使用可重入锁（RLock）保护共享状态、延迟保存优化、network_security 独立管理（带缓存）、
文件变更监听、配置导入导出。通过模块级 config_manager 全局实例访问。

#### 方法

##### `__init__(self, config_file: str = 'config.jsonc')`

初始化配置管理器：查找配置文件、初始化锁和缓存、加载配置、启动文件监听

##### `get(self, key: str, default: Any = None) -> Any`

获取配置值（支持点号分隔的嵌套键如 'notification.sound_volume'，线程安全）

##### `set(self, key: str, value: Any, save: bool = True)`

设置配置值（支持嵌套键，自动创建中间路径，值变化检测，可选延迟保存）

##### `update(self, updates: Dict[str, Any], save: bool = True)`

批量更新配置（仅处理变化项，合并为一次延迟保存，原子操作）

##### `force_save(self)`

强制立即保存配置文件（取消延迟保存，应用所有待保存变更）

##### `get_section(self, section: str, use_cache: bool = True) -> Dict[str, Any]`

获取配置段的深拷贝（带缓存优化，network_security 特殊处理）

##### `update_section(self, section: str, updates: Dict[str, Any], save: bool = True)`

更新配置段（检测变化，触发回调，可选延迟保存）

##### `reload(self)`

从磁盘重新加载配置文件（覆盖内存配置，失效缓存）

##### `invalidate_section_cache(self, section: str)`

失效指定配置段的缓存

##### `invalidate_all_caches(self)`

清空所有配置缓存

##### `get_cache_stats(self) -> Dict[str, Any]`

获取缓存统计（命中/未命中/失效次数、命中率等）

##### `reset_cache_stats(self)`

重置缓存统计信息

##### `set_cache_ttl(self, section_ttl: float | None = None, network_security_ttl: float | None = None)`

设置缓存有效期（TTL）

##### `get_all(self) -> Dict[str, Any]`

获取所有配置的副本（不含 network_security）

##### `get_network_security_config(self) -> Dict[str, Any]`

从文件读取 network_security 配置（带 30 秒缓存，失败返回默认配置）

##### `get_typed(self, key: str, default: Any, value_type: type, min_val: Optional[Any] = None, max_val: Optional[Any] = None) -> Any`

获取配置值，带类型转换和边界验证

##### `get_int(self, key: str, default: int = 0, min_val: Optional[int] = None, max_val: Optional[int] = None) -> int`

获取整数配置值

##### `get_float(self, key: str, default: float = 0.0, min_val: Optional[float] = None, max_val: Optional[float] = None) -> float`

获取浮点数配置值

##### `get_bool(self, key: str, default: bool = False) -> bool`

获取布尔配置值

##### `get_str(self, key: str, default: str = '', max_length: Optional[int] = None) -> str`

获取字符串配置值（可选截断）

##### `start_file_watcher(self, interval: float = 2.0)`

启动配置文件监听（后台守护线程，检测文件变化自动重载）

##### `stop_file_watcher(self)`

停止配置文件监听

##### `shutdown(self)`

关闭配置管理器：停止文件监听、取消延迟保存定时器（幂等）

##### `register_config_change_callback(self, callback: Callable[[], None])`

注册配置变更回调函数

##### `unregister_config_change_callback(self, callback: Callable[[], None])`

取消注册配置变更回调函数

##### `is_file_watcher_running(self) -> bool`

检查文件监听器是否在运行

##### `export_config(self, include_network_security: bool = False) -> Dict[str, Any]`

导出当前配置（可选包含 network_security）

##### `import_config(self, config_data: Dict[str, Any], merge: bool = True, save: bool = True) -> bool`

导入配置（支持合并或覆盖模式）

##### `backup_config(self, backup_path: Optional[str] = None) -> str`

备份当前配置到文件

##### `restore_config(self, backup_path: str) -> bool`

从备份文件恢复配置
