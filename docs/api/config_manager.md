# config_manager

配置管理模块

【核心功能】
统一管理应用程序的所有配置，提供跨平台的配置文件管理能力。

【主要特性】
- JSONC 格式支持：支持带注释的 JSON 配置文件，保留用户注释
- 跨平台配置目录：自动识别不同操作系统的标准配置目录位置
- 运行模式检测：区分 uvx 运行模式和开发模式，智能选择配置文件位置
- 配置热重载：支持运行时重新加载配置文件
- 网络安全配置独立管理：network_security 配置段特殊处理，不加载到内存
- 线程安全：使用读写锁实现高性能的并发访问控制
- 延迟保存优化：批量配置更新时减少磁盘 I/O 次数
- 配置验证：保存后自动验证配置文件格式和结构

【配置文件位置】
- 开发模式：优先使用当前目录的 config.jsonc，其次用户配置目录
- uvx 模式：仅使用用户配置目录的全局配置
- Linux: ~/.config/ai-intervention-agent/config.jsonc
- macOS: ~/Library/Application Support/ai-intervention-agent/config.jsonc
- Windows: %APPDATA%/ai-intervention-agent/config.jsonc

【使用方式】
通过模块级全局实例 config_manager 访问配置，或使用 get_config() 函数获取实例。

【配置段说明】
- notification: 通知系统配置（Web、声音、Bark 推送）
- web_ui: Web UI 服务器配置（地址、端口、重试策略）
- network_security: 网络安全配置（访问控制、IP 白名单/黑名单）
- feedback: 反馈系统配置（超时设置）

【线程安全保证】
- 使用读写锁（ReadWriteLock）实现读多写少的高效并发
- 所有公共方法均为线程安全
- 支持多线程并发读取配置，写入时独占访问

## 函数

### `parse_jsonc(content: str) -> Dict[str, Any]`

解析 JSONC (JSON with Comments) 格式的内容

【功能说明】
将带注释的 JSON 字符串解析为 Python 字典对象。

【支持的注释格式】
- 单行注释：// 注释内容（到行尾）
- 多行注释：/* 注释内容 */（可跨行）

【处理流程】
1. 逐行扫描输入内容
2. 识别并移除多行注释块
3. 识别并移除单行注释（排除字符串内的 //）
4. 拼接清理后的内容
5. 使用标准 json.loads 解析

【注意事项】
- 字符串内的 // 和 /* */ 不会被视为注释
- 处理转义字符以避免误判字符串边界
- 保留原始 JSON 的换行和缩进（清理后）

【错误处理】
- 注释清理过程中的错误会导致解析失败
- JSON 语法错误会抛出 json.JSONDecodeError

【性能考虑】
- 逐字符扫描，适用于中小型配置文件
- 对于大型文件可能性能不佳

Args:
    content: JSONC 格式的字符串内容

Returns:
    Dict[str, Any]: 解析后的字典对象

Raises:
    json.JSONDecodeError: JSON 解析失败时抛出

### `_is_uvx_mode() -> bool`

检测是否为 uvx 方式运行

【功能说明】
判断应用是通过 uvx 工具运行还是开发模式运行，影响配置文件位置选择。

【检测特征】
1. 执行路径检查：sys.executable 是否包含 "uvx" 或 ".local/share/uvx"
2. 环境变量检查：是否存在 UVX_PROJECT 环境变量
3. 项目文件检查：当前目录及父目录是否包含开发文件
   - pyproject.toml：Python 项目配置
   - setup.py / setup.cfg：传统 Python 打包文件
   - .git：Git 版本控制目录

【判断逻辑】
- 如果检测到 uvx 特征 → 返回 True（uvx 模式）
- 如果检测到开发文件 → 返回 False（开发模式）
- 都未检测到 → 返回 True（默认为 uvx 模式）

【模式影响】
- uvx 模式：仅使用用户配置目录的全局配置
- 开发模式：优先使用当前目录的配置文件

【设计考虑】
- uvx 模式通常用于生产环境或用户安装的应用
- 开发模式允许开发者在项目目录调试配置
- 避免 uvx 模式下意外使用临时目录的配置

Returns:
    bool: True 表示 uvx 模式，False 表示开发模式

### `find_config_file(config_filename: str = 'config.jsonc') -> Path`

查找配置文件路径

【功能说明】
根据运行模式智能查找配置文件位置，支持开发模式和 uvx 生产模式。

【查找策略】
**uvx 模式**（生产环境）：
- 仅使用用户配置目录的全局配置
- 避免使用临时目录中的配置文件
- 确保配置持久化且全局一致

**开发模式**（本地开发）：
1. 优先级1：当前工作目录的 config.jsonc
2. 优先级2：当前工作目录的 config.json（向后兼容）
3. 优先级3：用户配置目录的 config.jsonc
4. 优先级4：用户配置目录的 config.json（向后兼容）
5. 默认：返回用户配置目录路径（用于创建新配置）

【跨平台配置目录】
自动适配不同操作系统的标准配置目录：
- **Linux**: ~/.config/ai-intervention-agent/
- **macOS**: ~/Library/Application Support/ai-intervention-agent/
- **Windows**: %APPDATA%/ai-intervention-agent/

【配置目录获取】
- 优先使用 platformdirs 库（如果可用）
- 回退到 _get_user_config_dir_fallback 手动判断

【向后兼容】
- 支持 .jsonc 和 .json 两种扩展名
- 优先使用 .jsonc 格式（支持注释）
- 自动查找并使用旧的 .json 配置文件

【文件不存在处理】
- 返回用户配置目录的目标路径
- 由 ConfigManager 负责创建默认配置文件
- 记录日志说明将创建新配置

【异常处理】
- 配置目录获取失败时回退到当前目录
- 记录警告日志但不抛出异常
- 确保应用能在各种环境下启动

Args:
    config_filename: 配置文件名，默认为 "config.jsonc"

Returns:
    Path: 配置文件的路径对象（可能尚不存在）

### `_get_user_config_dir_fallback() -> Path`

获取用户配置目录的回退实现

【功能说明】
在 platformdirs 库不可用时，手动判断操作系统并返回标准配置目录路径。

【支持的平台】
- **Windows**: %APPDATA%/ai-intervention-agent 或 ~/AppData/Roaming/ai-intervention-agent
- **macOS (darwin)**: ~/Library/Application Support/ai-intervention-agent
- **Linux 和其他 Unix**: $XDG_CONFIG_HOME/ai-intervention-agent 或 ~/.config/ai-intervention-agent

【平台检测】
使用 platform.system() 识别操作系统：
- "windows" → Windows 路径
- "darwin" → macOS 路径
- 其他 → Linux/Unix 路径

【环境变量支持】
- Windows: 优先使用 APPDATA 环境变量
- Linux: 优先使用 XDG_CONFIG_HOME 环境变量（符合 XDG 规范）

【回退路径】
环境变量不存在时使用硬编码的标准路径：
- Windows: ~/AppData/Roaming/ai-intervention-agent
- macOS: ~/Library/Application Support/ai-intervention-agent
- Linux: ~/.config/ai-intervention-agent

【设计考虑】
- 遵循各平台的标准配置目录规范
- 确保在没有第三方库时也能正常工作
- 使用 Path.home() 获取用户主目录，跨平台兼容

Returns:
    Path: 用户配置目录路径（不包含配置文件名）

### `get_config() -> ConfigManager`

获取配置管理器实例

【功能说明】
返回全局唯一的配置管理器实例。

【单例模式】
- config_manager 在模块加载时创建
- 整个应用生命周期内只有一个实例
- 所有模块共享同一个配置状态

【使用方式】
推荐使用此函数获取配置管理器，而非直接访问 config_manager 变量。

【线程安全】
- config_manager 实例本身线程安全
- 可从多线程安全调用此函数

Returns:
    ConfigManager: 全局配置管理器实例

## 类

### `class ReadWriteLock`

读写锁实现

【设计目的】
实现读写锁模式，允许多个读者并发访问，但写者需要独占访问。
适用于读多写少的场景，提升并发性能。

【锁模式】
- 读模式：多个线程可同时持有读锁，互不阻塞
- 写模式：只有一个线程可持有写锁，且必须等待所有读锁释放

【实现原理】
- 使用 Condition 变量协调读写线程
- 使用计数器 _readers 追踪当前读者数量
- 写者在进入前等待所有读者退出
- 最后一个读者退出时通知等待的写者

【使用场景】
- ConfigManager 的配置读取和更新
- 其他读多写少的共享资源访问

【线程安全】
- 基于 threading.Condition 和 threading.RLock 实现
- 保证读写操作的正确同步

#### 方法

##### `__init__(self)`

初始化读写锁

【内部状态】
- _read_ready: Condition 变量，用于协调读写线程
- _readers: 当前持有读锁的线程数量

##### `read_lock(self)`

获取读锁的上下文管理器

【功能说明】
获取读锁以访问共享资源。多个线程可同时持有读锁。

【使用流程】
1. 获取 Condition 锁
2. 增加读者计数
3. 释放 Condition 锁
4. 执行用户代码（持有读锁期间）
5. 重新获取 Condition 锁
6. 减少读者计数
7. 如果是最后一个读者，通知等待的写者
8. 释放 Condition 锁

【阻塞条件】
- 仅在写者持有锁时阻塞
- 读者之间不会相互阻塞

【典型用法】
在 ConfigManager.get() 方法中使用

Yields:
    None: 在持有读锁期间执行

##### `write_lock(self)`

获取写锁的上下文管理器

【功能说明】
获取写锁以独占访问共享资源。写者必须等待所有读者退出。

【使用流程】
1. 获取 Condition 锁
2. 等待所有读者退出（_readers == 0）
3. 执行用户代码（持有写锁期间，独占访问）
4. 释放 Condition 锁

【阻塞条件】
- 有读者持有读锁时阻塞
- 其他写者持有写锁时阻塞

【独占性】
- 持有写锁期间，任何读者和写者都无法获取锁
- 保证数据修改的原子性和一致性

【典型用法】
在 ConfigManager.set() 和 ConfigManager.update() 方法中使用

Yields:
    None: 在持有写锁期间执行（独占访问）

### `class ConfigManager`

配置管理器

【设计模式】
单例模式（通过模块级全局实例 config_manager 实现）

【核心职责】
1. 配置文件加载和解析（JSONC 和 JSON 格式）
2. 配置值的读取和更新（支持嵌套键）
3. 配置文件的持久化（保留注释和格式）
4. 线程安全的并发访问控制
5. 性能优化（延迟保存、读写锁、缓存）

【主要特性】
- **JSONC 支持**：保留用户在配置文件中的注释和格式
- **跨平台**：自动适配不同操作系统的配置目录
- **热重载**：支持运行时重新加载配置文件
- **网络安全配置独立管理**：network_security 段不加载到内存，特殊方法读取（带缓存）
- **线程安全**：使用读写锁实现高性能并发访问
- **延迟保存**：批量配置更新时减少磁盘 I/O
- **配置验证**：保存后自动验证文件格式和结构

【配置段管理】
- notification: 加载到内存，正常访问
- web_ui: 加载到内存，正常访问
- feedback: 加载到内存，正常访问
- network_security: **不加载到内存**，使用 get_network_security_config() 特殊读取（带 30 秒缓存）

【线程安全】
- 读操作使用读锁，允许多线程并发读取
- 写操作使用写锁，独占访问
- 延迟保存使用额外的 RLock 保护定时器

【性能优化】
- 延迟保存机制：批量更新后统一保存，减少磁盘 I/O
- 读写锁：读多写少场景下提升并发性能
- 值变化检测：跳过未变化的配置更新
- **network_security 缓存**：30 秒 TTL，减少文件读取

【使用方式】
通过模块级全局实例 config_manager 访问，避免手动创建实例。

#### 方法

##### `__init__(self, config_file: str = 'config.jsonc')`

初始化配置管理器

【初始化流程】
1. 查找配置文件路径（根据运行模式）
2. 初始化内部状态（配置字典、锁、定时器）
3. 加载配置文件内容
4. 合并默认配置（确保新增配置项存在）

【内部状态】
- config_file: 配置文件路径（Path 对象）
- _config: 内存中的配置字典（不含 network_security）
- _rw_lock: 读写锁，用于配置读写
- _lock: 可重入锁，用于延迟保存定时器
- _original_content: 原始文件内容（用于保留注释）
- _last_access_time: 最后访问时间（用于统计）
- _pending_changes: 待写入的配置变更字典
- _save_timer: 延迟保存定时器
- _save_delay: 延迟保存时间（默认3秒）
- _last_save_time: 上次保存时间

【配置文件查找】
使用 find_config_file() 根据运行模式查找配置文件位置

【默认配置】
如果配置文件不存在，自动创建带注释的默认配置文件

Args:
    config_file: 配置文件名，默认为 "config.jsonc"

##### `get(self, key: str, default: Any = None) -> Any`

获取配置值，支持点号分隔的嵌套键 - 使用读锁提高并发性能

【功能说明】
从配置字典中读取指定键的值，支持点号分隔的嵌套路径。

【键路径格式】
- 简单键：直接访问顶层配置，如 "notification"
- 嵌套键：使用点号分隔，如 "notification.sound_volume"
- 深度嵌套：支持任意深度，如 "web_ui.retry.max_attempts"

【查找过程】
1. 将键按 "." 分割成路径列表
2. 从 _config 字典开始逐层导航
3. 遇到 KeyError 或 TypeError 时返回默认值

【线程安全】
- 使用读锁（ReadWriteLock.read_lock）
- 允许多个线程并发读取
- 读操作不阻塞其他读操作

【性能优化】
- 更新最后访问时间（用于统计）
- 读锁机制提升并发性能

【特殊配置访问】
- **network_security 配置**：不在 _config 中，返回 None 或默认值
- 应使用 get_network_security_config() 特殊方法访问

【错误处理】
- 键不存在：返回 default 参数值
- 中间路径不是字典：返回 default 参数值
- 不抛出异常，确保调用安全

Args:
    key: 配置键，支持点号分隔的嵌套路径
    default: 键不存在时的默认返回值，默认为 None

Returns:
    Any: 配置值，如果键不存在则返回 default

##### `set(self, key: str, value: Any, save: bool = True)`

设置配置值，支持点号分隔的嵌套键 - 使用写锁确保原子操作

【功能说明】
更新配置字典中指定键的值，支持点号分隔的嵌套路径。

【键路径格式】
- 简单键：更新顶层配置，如 "enabled"
- 嵌套键：使用点号分隔，如 "notification.sound_volume"
- 自动创建中间路径：如果中间字典不存在，自动创建

【更新流程】
1. 获取写锁（独占访问）
2. 更新最后访问时间
3. 检查当前值是否与新值相同（性能优化）
4. 如果值未变化，记录日志并跳过
5. 如果值变化：
   - 立即更新内存中的 _config
   - 如果 save=True，将变更加入待保存队列并调度延迟保存
   - 如果 save=False，仅更新内存
6. 记录调试日志

【性能优化】
- 值变化检测：跳过未变化的更新，减少不必要的保存
- 延迟保存机制：批量更新时统一保存，减少磁盘 I/O
- 读写锁：写操作独占，但不影响其他读操作

【保存机制】
- save=True（默认）：更新后调度延迟保存（3秒后）
- save=False：仅更新内存，不保存到文件
- 延迟保存：多次更新会合并到一次保存操作

【线程安全】
- 使用写锁（ReadWriteLock.write_lock）
- 独占访问，阻塞其他读写操作
- 确保配置更新的原子性

【自动路径创建】
- 如果中间字典不存在，自动创建空字典
- 使用 _set_config_value 内部方法处理路径导航

【特殊配置更新】
- **network_security 配置**：不在 _config 中，更新会被忽略
- 应通过修改配置文件并调用 reload() 更新

Args:
    key: 配置键，支持点号分隔的嵌套路径
    value: 要设置的新值，可以是任意类型
    save: 是否保存到文件，默认为 True

##### `update(self, updates: Dict[str, Any], save: bool = True)`

批量更新配置 - 使用写锁确保原子操作

【功能说明】
一次性更新多个配置项，比多次调用 set() 更高效。

【更新流程】
1. 获取写锁（独占访问）
2. 更新最后访问时间
3. 过滤出真正有变化的配置项（性能优化）
4. 如果没有变化，记录日志并跳过
5. 如果有变化：
   - 立即更新内存中的 _config
   - 如果 save=True，将所有变更加入待保存队列并调度延迟保存
   - 如果 save=False，仅更新内存
6. 记录每个配置项的更新日志
7. 记录批量更新完成日志

【性能优化】
- 值变化检测：仅处理真正有变化的配置项
- 批量缓冲：所有变更合并到一次保存操作
- 单次调度：无论更新多少配置项，只调度一次延迟保存
- 减少磁盘 I/O：相比多次 set() 大幅减少磁盘操作

【保存机制】
- save=True（默认）：批量更新后调度延迟保存（3秒后）
- save=False：仅更新内存，不保存到文件
- 延迟保存：多次批量更新也会合并到一次保存操作

【线程安全】
- 使用写锁（ReadWriteLock.write_lock）
- 独占访问，阻塞其他读写操作
- 确保批量更新的原子性

【使用场景】
- 初始化时批量设置多个配置项
- 应用设置页面保存多个配置更改
- 配置迁移或导入

【与 set() 的对比】
- set()：单个配置项更新
- update()：多个配置项批量更新，性能更优

Args:
    updates: 配置更新字典，键为配置路径，值为新值
    save: 是否保存到文件，默认为 True

##### `force_save(self)`

强制立即保存配置文件（用于关键操作）

【功能说明】
立即保存配置文件，绕过延迟保存机制。

【使用场景】
- 应用退出前保存配置
- 关键配置更改需要立即持久化
- 测试环境中验证配置保存
- 避免延迟保存导致的配置丢失

【执行流程】
1. 取消延迟保存定时器（如果存在）
2. 应用所有待写入的配置变更
3. 调用 _save_config_immediate 立即保存
4. 更新最后保存时间
5. 记录调试日志

【与延迟保存的对比】
- 延迟保存：批量更新后3秒保存，减少磁盘 I/O
- 强制保存：立即保存，确保配置持久化

【线程安全】
- 使用 _lock 保护整个保存过程
- 确保保存操作的原子性

【性能考虑】
- 频繁调用会导致磁盘 I/O 增加
- 应仅在必要时使用
- 一般情况下依赖延迟保存机制即可

##### `get_section(self, section: str, use_cache: bool = True) -> Dict[str, Any]`

获取配置段（返回副本，防止外部修改影响内部状态）

【功能说明】
获取指定名称的整个配置段字典的深拷贝。

【配置段】
- notification: 通知系统配置
- web_ui: Web UI 服务器配置
- feedback: 反馈系统配置
- network_security: 网络安全配置（特殊处理）

【特殊处理】
- **network_security 配置段**：不在内存中，通过 get_network_security_config() 从文件读取
- 其他配置段：通过 get() 方法从内存读取

【性能优化】
- 使用 section 缓存层减少深拷贝开销
- 缓存有效期默认 10 秒，可通过 use_cache=False 强制刷新

【返回值】
- 配置段存在：返回该配置段字典的**深拷贝**
- 配置段不存在：返回空字典 {}

【安全性】
- 【修复】返回深拷贝，外部修改不会影响内部配置状态
- 需要修改配置请使用 update_section() 或 set() 方法

【使用场景】
- 获取某个功能模块的所有配置
- 配置页面展示某个配置段
- 批量读取配置项

Args:
    section: 配置段名称（顶层配置键）
    use_cache: 是否使用缓存（默认 True）

Returns:
    Dict[str, Any]: 配置段字典的深拷贝，如果不存在则返回空字典

##### `update_section(self, section: str, updates: Dict[str, Any], save: bool = True)`

更新配置段

【功能说明】
批量更新指定配置段内的多个配置项。

【更新流程】
1. 获取当前配置段的所有配置
2. 检查是否有配置项真的发生变化
3. 如果没有变化，记录日志并跳过
4. 如果有变化：
   - 应用更新到配置段
   - 更新内存中的 _config
   - 如果 save=True，调度延迟保存
5. 记录更新日志

【值变化检测】
- 逐项比较新旧值
- 仅当至少有一项变化时才执行更新
- 记录每项变化的调试日志

【保存机制】
- save=True（默认）：更新后调度延迟保存
- save=False：仅更新内存，不保存到文件

【线程安全】
- 使用 _lock 保护整个更新过程
- 确保配置段更新的原子性

【使用场景】
- 更新某个功能模块的多个配置
- 从 API 接收配置段更新
- 配置导入或迁移

【与 update() 的对比】
- update()：支持跨配置段的更新，键需要完整路径
- update_section()：限定在单个配置段内，键无需前缀

Args:
    section: 配置段名称（顶层配置键）
    updates: 配置更新字典，键为配置段内的键名，值为新值
    save: 是否保存到文件，默认为 True

##### `reload(self)`

重新加载配置文件

【功能说明】
从磁盘重新加载配置文件，覆盖内存中的配置。

【使用场景】
- 配置文件被外部修改后需要重新加载
- 开发调试时频繁修改配置
- 配置热更新，无需重启应用
- 恢复到文件中的配置（放弃内存中的未保存更改）

【注意事项】
- 内存中未保存的配置更改会丢失
- 调用前应考虑是否需要 force_save()
- 重新加载会触发完整的配置文件解析流程

【执行流程】
1. 记录信息日志
2. 调用 _load_config() 重新加载
3. 重新解析配置文件
4. 合并默认配置
5. 更新 _original_content

【线程安全】
- _load_config() 内部使用锁保护
- 重新加载期间其他操作会被阻塞

##### `invalidate_section_cache(self, section: str)`

失效指定 section 的缓存

【功能说明】
使指定配置段的缓存失效，下次访问时会重新从内存中读取。

Args:
    section: 配置段名称

##### `invalidate_all_caches(self)`

失效所有缓存

【功能说明】
清空所有配置缓存，包括 section 缓存和 network_security 缓存。

##### `get_cache_stats(self) -> Dict[str, Any]`

获取缓存统计信息

【功能说明】
返回缓存的命中率、未命中率等统计信息。

Returns:
    Dict: {
        "hits": 缓存命中次数,
        "misses": 缓存未命中次数,
        "invalidations": 缓存失效次数,
        "hit_rate": 命中率 (0.0-1.0),
        "section_cache_size": 当前 section 缓存数量,
        "network_security_cached": network_security 是否已缓存
    }

##### `reset_cache_stats(self)`

重置缓存统计

【功能说明】
将缓存统计信息归零，用于新一轮统计。

##### `set_cache_ttl(self, section_ttl: float = None, network_security_ttl: float = None)`

设置缓存有效期

【功能说明】
动态调整缓存有效期（TTL）。

Args:
    section_ttl: section 缓存有效期（秒），None 表示不修改
    network_security_ttl: network_security 缓存有效期（秒），None 表示不修改

##### `get_all(self) -> Dict[str, Any]`

获取所有配置

【功能说明】
返回内存中所有配置的副本。

【返回值】
- 配置字典的浅拷贝
- **不包含** network_security 配置段
- 修改返回的字典不影响内存中的配置

【使用场景】
- 配置导出或备份
- 配置页面展示所有配置
- 配置比较或差异分析
- API 返回完整配置

【性能考虑】
- 返回副本，避免外部直接修改内部状态
- 浅拷贝，嵌套字典仍是引用
- 对于大型配置可能有性能开销

【线程安全】
- 使用 _lock 保护拷贝操作
- 确保返回一致的配置快照

【network_security 配置】
- 使用 get_network_security_config() 单独获取
- 不会包含在返回值中

Returns:
    Dict[str, Any]: 所有配置的副本（不含 network_security）

##### `get_network_security_config(self) -> Dict[str, Any]`

特殊方法：从文件读取 network_security 配置（带缓存优化）

【设计原因】
network_security 配置包含敏感的网络访问控制信息，独立管理更安全：
- 防止意外修改或泄露
- 减少内存占用
- 降低安全风险
- 明确区分安全配置和业务配置

【功能说明】
从配置文件读取 network_security 配置段，带有 30 秒缓存优化。

【性能优化 - 缓存机制】
- 缓存有效期：30 秒（TTL）
- 缓存命中：直接返回缓存数据，避免文件 I/O
- 缓存过期：重新读取文件并更新缓存
- 线程安全：使用锁保护缓存访问

【读取流程】
1. 检查缓存是否有效（30 秒内）
2. 缓存有效：直接返回缓存数据
3. 缓存过期/不存在：
   - 检查配置文件是否存在
   - 读取文件内容
   - 根据扩展名选择解析器（JSONC 或 JSON）
   - 提取 network_security 配置段
   - 更新缓存
4. 发生异常时返回默认配置

【默认配置】
- bind_interface: "0.0.0.0"（允许所有接口）
- allowed_networks: 包含本地和私有网络段
- blocked_ips: 空列表
- enable_access_control: True（启用访问控制）

【使用场景】
- Web UI 启动时读取网络安全配置
- 检查客户端 IP 是否允许访问
- 配置页面展示网络安全设置
- API 返回网络安全配置

【性能考虑】
- 【优化】30 秒缓存减少文件 I/O
- 缓存过期后自动刷新
- 支持热重载：修改配置文件后 30 秒内生效

【错误处理】
- 文件不存在：返回默认配置
- 解析失败：记录错误日志，返回默认配置
- 配置段缺失：返回默认配置
- 不抛出异常，确保应用能正常启动

Returns:
    Dict[str, Any]: network_security 配置字典，如果读取失败则返回默认配置

##### `get_typed(self, key: str, default: Any, value_type: type, min_val: Optional[Any] = None, max_val: Optional[Any] = None) -> Any`

获取配置值，带类型转换和边界验证

【功能说明】
获取配置值并自动进行类型转换和边界验证。
如果转换失败或值超出边界，返回默认值或调整后的值。

【支持的类型】
- int: 整数类型
- float: 浮点数类型
- bool: 布尔类型（支持字符串 "true"/"false"）
- str: 字符串类型

【边界验证】
- min_val: 最小值（包含），仅对 int/float 有效
- max_val: 最大值（包含），仅对 int/float 有效
- 超出边界的值会被自动调整

【使用场景】
- 获取需要类型安全的配置值
- 避免在使用配置值前手动转换和验证

Args:
    key: 配置键，支持点号分隔的嵌套路径
    default: 默认值
    value_type: 目标类型（int, float, bool, str）
    min_val: 最小值（可选）
    max_val: 最大值（可选）

Returns:
    Any: 类型转换和边界验证后的配置值

Example:
    >>> config.get_typed("web_ui.port", 8080, int, 1, 65535)
    8081
    >>> config.get_typed("notification.enabled", True, bool)
    True

##### `get_int(self, key: str, default: int = 0, min_val: Optional[int] = None, max_val: Optional[int] = None) -> int`

获取整数配置值

Args:
    key: 配置键
    default: 默认值
    min_val: 最小值（可选）
    max_val: 最大值（可选）

Returns:
    int: 整数配置值

##### `get_float(self, key: str, default: float = 0.0, min_val: Optional[float] = None, max_val: Optional[float] = None) -> float`

获取浮点数配置值

Args:
    key: 配置键
    default: 默认值
    min_val: 最小值（可选）
    max_val: 最大值（可选）

Returns:
    float: 浮点数配置值

##### `get_bool(self, key: str, default: bool = False) -> bool`

获取布尔配置值

Args:
    key: 配置键
    default: 默认值

Returns:
    bool: 布尔配置值

##### `get_str(self, key: str, default: str = '', max_length: Optional[int] = None) -> str`

获取字符串配置值

Args:
    key: 配置键
    default: 默认值
    max_length: 最大长度（可选，超出会截断）

Returns:
    str: 字符串配置值

##### `start_file_watcher(self, interval: float = 2.0)`

启动配置文件监听

【功能说明】
启动一个后台线程，定期检查配置文件是否被修改。
当检测到文件变化时，自动重新加载配置并触发回调。

【参数】
interval : float
    检查间隔时间（秒），默认 2.0 秒

【使用场景】
- 开发调试时希望配置实时生效
- 需要支持外部工具修改配置文件
- 多进程共享配置文件时

【注意事项】
- 已启动的监听器不会重复启动
- 使用守护线程，主程序退出时自动终止
- 文件变化检测基于修改时间（mtime）

##### `stop_file_watcher(self)`

停止配置文件监听

【功能说明】
停止后台文件监听线程。

【注意事项】
- 会等待当前监听周期完成后再停止
- 可以安全地多次调用

##### `register_config_change_callback(self, callback: callable)`

注册配置变更回调函数

【功能说明】
当配置文件被修改并重新加载后，会调用所有注册的回调函数。

【参数】
callback : callable
    回调函数，无参数，无返回值
    函数签名: def callback() -> None

【使用场景】
- 通知其他模块配置已更新
- 触发配置相关的重新初始化
- 更新缓存或状态

【示例】
>>> def on_config_change():
...     print("配置已更新")
>>> config.register_config_change_callback(on_config_change)

##### `unregister_config_change_callback(self, callback: callable)`

取消注册配置变更回调函数

【参数】
callback : callable
    要取消的回调函数

##### `is_file_watcher_running(self) -> bool`

检查文件监听器是否在运行

##### `export_config(self, include_network_security: bool = False) -> Dict[str, Any]`

导出当前配置

【功能说明】
导出内存中的所有配置为字典格式，可用于备份或迁移。

【参数】
include_network_security : bool
    是否包含网络安全配置，默认 False（安全考虑）

【返回】
Dict[str, Any]
    包含所有配置的字典

【使用场景】
- 配置备份
- 配置迁移到其他环境
- 配置对比

【示例】
>>> config = get_config()
>>> backup = config.export_config()
>>> with open('config_backup.json', 'w') as f:
...     json.dump(backup, f, indent=2, ensure_ascii=False)

##### `import_config(self, config_data: Dict[str, Any], merge: bool = True, save: bool = True) -> bool`

导入配置

【功能说明】
从字典导入配置，支持合并或覆盖模式。

【参数】
config_data : Dict[str, Any]
    要导入的配置数据
merge : bool
    True: 合并模式（保留未指定的配置项）
    False: 覆盖模式（完全替换现有配置）
save : bool
    是否保存到文件，默认 True

【返回】
bool
    导入是否成功

【注意事项】
- 导入前会验证配置格式
- network_security 配置需要单独处理
- 合并模式下，只更新存在的键

【示例】
>>> config = get_config()
>>> with open('config_backup.json', 'r') as f:
...     backup = json.load(f)
>>> config.import_config(backup['config'], merge=True)

##### `backup_config(self, backup_path: Optional[str] = None) -> str`

备份当前配置到文件

【功能说明】
将当前配置导出并保存到备份文件。

【参数】
backup_path : Optional[str]
    备份文件路径，默认为 config.jsonc.backup

【返回】
str
    备份文件的完整路径

【示例】
>>> config = get_config()
>>> backup_file = config.backup_config()
>>> print(f"配置已备份到: {backup_file}")

##### `restore_config(self, backup_path: str) -> bool`

从备份文件恢复配置

【功能说明】
从备份文件导入配置并覆盖当前配置。

【参数】
backup_path : str
    备份文件路径

【返回】
bool
    恢复是否成功

【示例】
>>> config = get_config()
>>> config.restore_config('config.jsonc.backup')
