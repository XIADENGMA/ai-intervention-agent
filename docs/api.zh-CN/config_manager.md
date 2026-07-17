# config_manager

> 英文 signature-only 版本（仅函数 / 类签名速查）：[`docs/api/config_manager.md`](../api/config_manager.md)

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

### `_path_contains_segment(candidate: Path | str, segment: str) -> bool`

检测路径中是否包含某个完整的目录段（不会被前缀/后缀误匹配）。

例如 ``/Users/foo/uv-bar`` 不应该被 ``segment="uv"`` 命中——只命中真正
出现 ``.../uv/...`` 这种完整目录节。同时兼容 Windows 反斜杠与 POSIX
斜杠。

### `_looks_like_repo_checkout(module_dir: Path) -> bool`

模块目录是否是本仓库源码树（``src/ai_intervention_agent/`` 形态）。

判定条件（必须同时成立）：
1. ``module_dir`` 内有 ``server.py`` —— 防止 site-packages 误命中；
2. ``module_dir.parent.parent`` 有 ``pyproject.toml`` —— 表征真正
   的 src layout 仓库根。

抽出来方便单测 + 增强可读性。

### `_path_under(child: Path, parents: tuple[Path, ...]) -> bool`

``child`` 是否位于 ``parents`` 任一目录下（含 child == parent 等价）。

### `_is_isolated_install_runtime() -> bool`

启发式检测当前 Python 是否运行在 uv / uvx / uv tool / pipx / pip 隔离环境。

覆盖 2026 年常见的 4 类隔离运行时：

* **uvx**（``uv tool run``）—— sys.executable 在 uv cache 临时 venv 里，
  路径常见形态 ``~/.cache/uv/builds-v0/<hash>/.venv/bin/python``。
* **uv tool install**—— sys.executable 在 ``~/.local/share/uv/tools/<name>/.venv/bin/python``
  （或 ``$XDG_DATA_HOME/uv/tools/...``、``%LOCALAPPDATA%\uv\tools\...``）。
* **pipx install**—— sys.executable 在 ``~/.local/share/pipx/venvs/<name>/bin/python``。
* **pip install + 全局 / 项目 venv**—— 模块文件本身在 ``site-packages`` 下，
  运行时不需要看 sys.executable。

任一命中就视为 "已安装到用户环境"，必须走用户配置目录。环境变量
``UV_TOOL_DIR`` / ``UV_CACHE_DIR`` / ``PIPX_HOME`` 也会作为路径前缀
参与匹配，覆盖用户自定义安装目录的情况。

### `_is_uvx_mode() -> bool`

检测是否应使用"用户配置目录"（uvx / 已安装模式）而非"开发模式"。

说明
----
* **用户模式（True）**：使用用户配置目录（跨平台标准路径）。
  - uvx 运行（推荐给普通用户）
  - 通过 pip / uv tool / pipx 等任意方式安装后运行
* **开发模式（False）**：优先使用当前目录配置（从仓库克隆运行时更方便调试）。

判定优先级（高 → 低，命中即返回）
----
1. ``AI_INTERVENTION_AGENT_DEV_MODE`` 显式启用 → 开发模式（``False``）。
2. ``AI_INTERVENTION_AGENT_USER_MODE`` 显式启用 → 用户模式（``True``）。
3. 兼容旧 ``UVX_PROJECT`` → 用户模式。
4. 启发式检测 :func:`_is_isolated_install_runtime`（uvx / uv tool / pipx
   / site-packages）→ 用户模式。
5. 仓库检出 + cwd 在仓库内（兼顾仓库内 ``.venv`` 的 isolated runtime
   case）→ 开发模式。
6. 默认（保守）→ 用户模式。

任何判定阶段抛异常都降级为用户模式，避免误把"任意 git 仓库 cwd"判为
开发模式而在那里写 ``config.toml``。

注：步骤 5 对仓库内 ``.venv``（``./venv`` / ``./.venv`` / ``./uv-venv``
等开发者本地 venv）做 carve-out——虽然 ``Path(sys.executable)`` 可能
在 ``./.venv/bin/python``，但只要模块自己仍在仓库源码树（不在
site-packages）且 cwd 在源码树，就视为 dev。

### `_macos_legacy_xdg_config_dir() -> Path | None`

**R113** — 返回 macOS 上 ``~/.config/ai-intervention-agent/`` 残留目录。

macOS 用户配置的标准位置是 ``~/Library/Application Support/ai-intervention-agent/``
（Apple File System Programming Guide / platformdirs ``user_config_dir`` 的
macOS 实现都返回此路径）。但实际现场会出现 **macOS 上 `~/.config/ai-intervention-agent/`
被创建** 的情况，可能来源：

* **历史早期版本**：早期 ai-intervention-agent 或 platformdirs 早期版本可能
  在 macOS 上误用 XDG 路径。
* **第三方安装脚本 / 跨平台 dotfiles**：用户从 Linux 迁移过来的 dotfiles
  或者批量配置脚本可能假设 ``.config/`` 是跨平台的。
* **手动 mkdir + cp**：用户测试 / 调试时手动复制了 config。
* **进程在错误的 cwd 下启动**：某个调用方把 ``find_config_file`` 在
  ``~/.config/ai-intervention-agent/`` 当 cwd 启动时，dev 模式分支会在该 cwd
  创建 ``config.toml``。

R113 在 macOS 上探测此目录是否存在；**R686（TODO#4）** 在此基础上把
"被动 warn + 临时采用 legacy" 升级为 "标准路径始终优先 + 自动迁移"：

1. 仅 legacy 有 config → **自动迁移**到标准路径后使用标准路径
   （旧文件重命名为 ``*.migrated-<时间戳>`` 备份，不删除数据）。
2. 标准 + legacy 同时存在且内容一致 → 自动把 legacy 重命名为备份，
   消除歧义（幂等，之后不再告警）。
3. 标准 + legacy 同时存在且内容**不一致** → 使用标准路径 + warn
   （数据取舍必须由用户决定，程序不擅自合并/覆盖）。

返回：
    macOS 上目录存在 → ``Path``；其他情况（非 macOS / 目录不存在）→ ``None``。

### `_retire_legacy_config_file(legacy_file: Path) -> bool`

R686：把 legacy 配置文件重命名为 ``<name>.migrated-<时间戳>`` 备份。

重命名（而非删除）保证零数据丢失；重命名后的文件不再匹配
``config.toml`` / ``config.jsonc`` / ``config.json`` 候选名，后续启动
不会再进入 legacy 分支——迁移天然幂等。

返回是否成功；失败（权限 / 只读卷等）由调用方决定降级策略。

### `_migrate_legacy_config_to_standard(legacy_file: Path, standard_dir: Path) -> Path | None`

R686（TODO#4）：把 macOS legacy ``~/.config/...`` 配置迁移到标准目录。

步骤：
1. ``mkdir -p`` 标准目录；
2. ``shutil.copy2`` 保留元数据地复制 legacy 文件到标准目录（同名）；
3. 复制成功后把 legacy 文件重命名为 ``*.migrated-<时间戳>`` 备份。

任何一步失败都返回 ``None``，调用方降级回 "临时采用 legacy" 的旧行为，
保证迁移永远不会让用户丢配置。

### `_files_have_same_content(a: Path, b: Path) -> bool`

比较两个小文件内容是否一致（配置文件 KB 级，直接读全量即可）。

### `find_config_file(config_filename: str = 'config.toml') -> Path`

查找配置文件路径，支持环境变量覆盖、uvx / 安装模式和开发模式。

检测路径以单个 ``logger.info`` 行可追溯地表达——每次冷启动都能从日志反查
出"为什么用了这个路径"。

优先级（高 → 低）
----
1. ``config_filename`` 自身是绝对路径或带子目录 → 原样返回，跳过所有探测。
2. ``AI_INTERVENTION_AGENT_CONFIG_FILE`` 环境变量 → 显式 override；目录形态
   会自动追加 ``config_filename``。
3. :func:`_is_uvx_mode` 命中 → 仅在用户配置目录搜索 + 创建。
4. 否则：当前目录 > 用户配置目录。

格式探测
----
每个候选目录都按 TOML > JSONC > JSON 的次序尝试，用于向后兼容历史
JSONC/JSON 用户。**同目录里同时存在多种格式时只采用排序首位**——
这一行为会显式 warn，避免静默忽略 user-edited JSONC。

跨平台配置目录
----
* Linux：``$XDG_CONFIG_HOME/ai-intervention-agent`` 或 ``~/.config/ai-intervention-agent``
* macOS：``~/Library/Application Support/ai-intervention-agent``
* Windows：``%APPDATA%\ai-intervention-agent``

macOS 兼容性（R113 + R686）
----
在 macOS 上**额外**检查 ``~/.config/ai-intervention-agent/`` 是否有残留 config
（历史版本 / 第三方脚本 / 手动 mkdir 都可能创建）。规则（R686 起标准路径
``~/Library/Application Support/...`` **始终优先**）：

* 标准路径 + ``.config/`` 都有、内容一致 → 用标准路径，legacy 自动重命名
  为 ``*.migrated-<时间戳>`` 备份（幂等，一次性消除歧义）
* 标准路径 + ``.config/`` 都有、内容不一致 → 用标准路径，warn 提示用户
  人工取舍（程序不擅自合并/覆盖）
* 仅 ``.config/`` 有 → **自动迁移**到标准路径（copy2 + 重命名备份，零数据
  丢失）后使用标准路径；迁移失败才降级为临时采用 legacy
* 仅标准路径或都没有 → 行为不变

Linux 上 ``.config/`` 是 XDG 标准，本逻辑不触发。

错误处理
----
用户配置目录探测失败（``platformdirs`` 都不可用 + 自家 fallback 也 raise）
最终降级为 ``Path(config_filename)``——但会把 ``warning`` 日志带上完整堆栈
便于排查权限 / 只读 home 等问题。

### `_get_user_config_dir_fallback() -> Path`

platformdirs 不可用时的回退实现，返回跨平台标准配置目录。

Windows: %APPDATA%、macOS: ~/Library/Application Support、Linux: $XDG_CONFIG_HOME 或 ~/.config。

### `_shutdown_global_config_manager()`

### `get_config() -> ConfigManager`

获取全局配置管理器实例（自动启动文件监听）

## 类

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
