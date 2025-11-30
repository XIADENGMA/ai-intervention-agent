# enhanced_logging

增强的日志系统模块

本模块提供企业级日志功能，解决 MCP 服务器环境中的日志问题，包括重复输出、级别错误、
安全风险和性能问题。

核心功能
--------
1. **单例日志管理器**: 防止 logger 重复初始化导致的日志重复输出
2. **多流输出策略**: 基于日志级别智能路由到不同输出流（全部输出到 stderr）
3. **日志脱敏处理**: 自动检测和脱敏密码、API 密钥等敏感信息
4. **注入攻击防护**: 转义危险字符，防止日志分割和注入攻击
5. **日志去重机制**: 在时间窗口内去除重复日志，减少噪声
6. **智能级别映射**: 根据消息内容自动调整日志级别

主要组件
--------
- SingletonLogManager: 单例日志管理器，确保每个 logger 只初始化一次
- LevelBasedStreamHandler: 基于级别的多流输出处理器（所有输出到 stderr）
- LogSanitizer: 日志脱敏处理器，保护敏感信息
- SecureLogFormatter: 安全日志格式化器，集成脱敏功能
- AntiInjectionFilter: 防注入过滤器，转义危险字符
- LogDeduplicator: 日志去重器，在时间窗口内去除重复日志
- EnhancedLogger: 增强日志记录器，集成所有功能的高级接口

设计原则
--------
1. **MCP 友好**: 所有日志输出到 stderr，避免污染 MCP stdio 通信通道
2. **线程安全**: 使用锁保护共享状态，支持多线程环境
3. **性能优化**: 去重缓存自动清理，限制最大缓存大小
4. **安全第一**: 默认启用脱敏和注入防护
5. **易用性**: 提供与标准 logging 兼容的 API

使用场景
--------
- MCP 服务器日志记录（避免污染 stdio）
- 多线程环境的安全日志
- 需要脱敏的敏感信息日志
- 高频日志场景（需要去重）
- 防止日志注入攻击的安全日志

典型用法
--------
创建增强日志记录器并使用标准 API。

脱敏规则
--------
自动脱敏以下类型的敏感信息：
- 密码字段（password、passwd）
- 密钥字段（secret_key、private_key）
- OpenAI API key（sk-xxx）
- Slack Bot Token（xoxb-xxx）
- GitHub Personal Access Token（ghp_xxx）

去重规则
--------
- 时间窗口: 5 秒（可配置）
- 缓存大小: 1000 条（可配置）
- 重复计数: 自动附加 "(重复 N 次)" 信息

线程安全
--------
- SingletonLogManager 使用双重检查锁实现线程安全的单例
- LogDeduplicator 使用线程锁保护缓存操作
- 所有共享状态都使用 threading.Lock 保护

注意事项
--------
- 日志级别映射基于消息内容关键词匹配（可扩展）
- 脱敏处理使用正则表达式，可能影响性能（已优化）
- 去重缓存会占用内存，自动清理旧条目
- 所有日志输出到 stderr，确保 stdout 用于 MCP 通信

依赖
----
- logging: Python 标准库日志模块
- threading: 线程安全保护
- re: 正则表达式（用于脱敏和注入防护）
- 【性能优化】使用内置 hash() 代替 hashlib.md5，无需额外依赖

## 函数

### `get_log_level_from_config() -> int`

从配置文件读取日志级别

返回
----
int
    logging 模块的日志级别常量

处理逻辑
--------
1. 尝试从 config_manager 读取 web_ui.log_level 配置
2. 如果配置无效或读取失败，使用默认级别 WARNING
3. 忽略大小写（如 "warning" 等同于 "WARNING"）

示例
----
>>> # config.jsonc: {"web_ui": {"log_level": "DEBUG"}}
>>> get_log_level_from_config()
10  # logging.DEBUG

### `configure_logging_from_config() -> None`

根据配置文件设置全局日志级别

功能
----
1. 从配置读取日志级别
2. 设置 root logger 级别
3. 更新所有已存在的 handler 级别

使用场景
--------
在应用启动时调用，确保日志级别与配置一致

示例
----
>>> configure_logging_from_config()
>>> # 现在所有日志都使用配置中的级别

## 类

### `class SingletonLogManager`

单例日志管理器

功能概述
--------
确保每个 logger 只被初始化一次，防止重复注册 handler 导致的日志重复输出问题。
使用双重检查锁实现线程安全的单例模式。

核心特性
--------
1. **单例模式**: 全局唯一实例，防止多次初始化
2. **Logger 去重**: 跟踪已初始化的 logger 名称
3. **自动配置**: 为每个 logger 自动配置多流输出和安全过滤器
4. **线程安全**: 使用锁保护初始化过程

内部状态
--------
- _instance: 单例实例（类变量）
- _lock: 线程锁（类变量）
- _initialized_loggers: 已初始化的 logger 名称集合（类变量）

单例实现
----------
使用双重检查锁（Double-Checked Locking）：
- 第一次检查: 快速路径，避免不必要的锁竞争
- 加锁: 确保只有一个线程创建实例
- 第二次检查: 防止多个线程同时通过第一次检查

使用场景
--------
- 创建应用级日志记录器
- 确保日志不重复输出
- 多模块共享日志配置

注意事项
--------
- 一旦 logger 初始化，无法更改其配置
- 所有 logger 共享相同的 handler 配置
- 默认日志级别为 WARNING

#### 方法

##### `setup_logger(self, name: str, level = logging.WARNING)`

设置并返回已配置的 logger 实例

参数
----
name : str
    logger 名称（通常使用 __name__）
level : int, optional
    日志级别，默认 logging.WARNING

返回
----
logging.Logger
    配置好的 logger 实例

功能
----
1. 检查 logger 是否已初始化（快速路径）
2. 如果未初始化，加锁并配置：
   - 清除现有 handler（避免重复）
   - 创建并附加 LevelBasedStreamHandler
   - 设置日志级别
   - 禁用传播到父 logger（防止重复）
   - 标记为已初始化
3. 返回 logger 实例

线程安全
--------
使用 _lock 保护初始化过程，确保每个 logger 只被配置一次。
始终在锁内检查并返回，避免快速路径的竞态条件。

注意事项
--------
- 重复调用返回相同的 logger 实例（已配置）
- handler 配置无法更改（一次性初始化）
- propagate=False 防止日志向上传播到 root logger
- 移除快速路径，所有访问都在锁内进行，确保线程安全

### `class LevelBasedStreamHandler`

基于日志级别的多流输出处理器

功能概述
--------
创建两个 StreamHandler，根据日志级别将日志路由到不同的 handler：
- DEBUG/INFO: 通过第一个 handler
- WARNING/ERROR/CRITICAL: 通过第二个 handler

所有 handler 都输出到 stderr，避免污染 MCP 的 stdio 通信通道。

设计原因
--------
在 MCP 环境中，stdout 用于协议通信，必须保持纯净。所有日志输出
（包括 INFO 级别）都应该输出到 stderr。

内部结构
----------
- stdout_handler: 处理 DEBUG 和 INFO 级别（实际输出到 stderr）
- stderr_handler: 处理 WARNING、ERROR、CRITICAL 级别（输出到 stderr）
- formatter: SecureLogFormatter（集成脱敏功能）
- anti_injection_filter: AntiInjectionFilter（防注入防护）

日志格式
--------
"%(asctime)s - %(name)s - %(levelname)s - %(message)s"

安全特性
--------
- 所有 handler 都添加了 AntiInjectionFilter（防注入攻击）
- 使用 SecureLogFormatter（自动脱敏）

使用场景
--------
- 被 SingletonLogManager 自动创建和配置
- 不应该手动创建或配置

注意事项
--------
- 虽然名为 stdout_handler，但实际输出到 stderr
- 两个 handler 的日志会按时间顺序交织输出
- 所有输出流都是 sys.stderr

#### 方法

##### `__init__(self)`

初始化多流输出处理器

初始化流程
----------
1. 创建两个 StreamHandler（都输出到 stderr）
2. 设置日志级别和过滤器
3. 配置 SecureLogFormatter（脱敏功能）
4. 添加 AntiInjectionFilter（防注入功能）

##### `attach_to_logger(self, logger)`

将两个处理器附加到指定 logger

参数
----
logger : logging.Logger
    要配置的 logger 实例

功能
----
将 stdout_handler 和 stderr_handler 同时添加到 logger，
实现基于级别的多流输出。

注意事项
--------
- 两个 handler 会同时处理所有日志
- 过滤器确保每条日志只被一个 handler 输出

### `class LogSanitizer`

日志脱敏处理器

功能概述
--------
自动检测并脱敏日志中的敏感信息，只处理真正的密码、密钥和 API Token，
避免过度脱敏导致日志可读性下降。

支持的敏感信息类型
------------------
1. **密码字段**: password, passwd（至少 6 字符）
2. **密钥字段**: secret_key, private_key（至少 16 字符）
3. **知名 API Token**:
   - OpenAI API key (sk-xxx，至少 32 字符)
   - Slack Bot Token (xoxb-xxx，至少 50 字符)
   - GitHub Personal Access Token (ghp_xxx，36 字符)

脱敏规则
--------
- 匹配的敏感信息替换为 "***REDACTED***"
- 使用长度限制减少误判（如 password 至少 6 字符）
- 使用边界匹配（）确保精确匹配 Token 格式

实现方式
--------
使用预编译的正则表达式列表，在初始化时编译所有模式，提高性能。

设计原则
--------
- **精确匹配**: 避免过度脱敏（如 "timeout" 不会被误判为 "password"）
- **性能优化**: 编译正则表达式，避免重复编译
- **可扩展**: 可通过添加新模式支持更多敏感信息类型

使用场景
--------
- 被 SecureLogFormatter 自动调用
- 也可独立使用：sanitizer = LogSanitizer(); sanitizer.sanitize(message)

注意事项
--------
- 脱敏是不可逆的
- 可能无法检测复杂编码或混淆的敏感信息
- 正则匹配可能影响高频日志性能

#### 方法

##### `__init__(self)`

初始化脱敏处理器

初始化流程
----------
预编译所有正则表达式模式，提高后续匹配性能。

编译的模式
----------
- 密码字段（至少 6 字符）
- 密钥字段（至少 16 字符）
- OpenAI、Slack、GitHub 等知名服务的 API Token

性能优化
--------
使用 re.compile() 预编译正则表达式，避免每次匹配都重新编译。

##### `sanitize(self, message: str) -> str`

脱敏处理日志消息

参数
----
message : str
    原始日志消息

返回
----
str
    脱敏后的日志消息

处理流程
--------
1. 遍历所有预编译的正则模式
2. 对每个模式执行替换
3. 返回脱敏后的消息

替换策略
--------
所有匹配的敏感信息替换为 "***REDACTED***"

性能
----
- 时间复杂度: O(n * m)，n 为消息长度，m 为模式数量
- 使用预编译正则表达式，减少编译开销

注意事项
--------
- 不会修改原始消息（返回新字符串）
- 脱敏是不可逆的
- 可能存在误判或漏判

### `class SecureLogFormatter`

安全的日志格式化器

功能概述
--------
继承自标准 logging.Formatter，在格式化后自动脱敏敏感信息。

工作流程
--------
1. 使用父类的 format() 方法进行标准格式化
2. 调用 LogSanitizer 脱敏敏感信息
3. 返回脱敏后的日志字符串

使用场景
--------
- 被 LevelBasedStreamHandler 自动使用
- 可用于任何需要脱敏的 logging.Handler

优势
----
- 无缝集成到标准 logging 系统
- 对用户代码透明（自动脱敏）
- 不影响日志的其他功能（级别、时间戳、模块名等）

注意事项
--------
- 脱敏发生在格式化之后，不影响日志记录的原始数据
- 脱敏会略微影响性能（正则匹配）

#### 方法

##### `__init__(self)`

初始化安全日志格式化器

参数
----
*args, **kwargs
    传递给父类 logging.Formatter 的参数

初始化流程
----------
1. 调用父类构造函数
2. 创建 LogSanitizer 实例

##### `format(self, record)`

格式化并脱敏日志记录

参数
----
record : logging.LogRecord
    日志记录对象

返回
----
str
    格式化并脱敏后的日志字符串

处理流程
--------
1. 调用父类的 format() 进行标准格式化
2. 调用 sanitizer.sanitize() 脱敏
3. 返回脱敏后的字符串

性能
----
- 增加的开销主要来自脱敏正则匹配
- 对于不含敏感信息的日志，影响较小

### `class AntiInjectionFilter`

防止日志注入攻击的过滤器

功能概述
--------
转义日志消息中的危险字符，防止日志分割攻击和日志伪造攻击。

攻击场景
--------
攻击者可能通过在输入中插入换行符或控制字符，伪造日志条目或分割日志：
- 插入 "\n" 可以伪造多行日志
- 插入 "\x00"（空字节）可能导致日志处理器异常
- 插入 "\r" 可能覆盖同一行的日志

防护策略
--------
- 转义空字节（\x00）为 "\\x00"
- 转义换行符（\n）为 "\\n"
- 转义回车符（\r）为 "\\r"
- 不转义 HTML 字符（保持可读性）

处理范围
--------
- record.msg: 日志消息模板
- record.args: 日志消息参数（仅字符串类型）

设计原则
--------
- **安全优先**: 转义所有潜在危险字符
- **最小影响**: 只转义必要的字符，保持可读性
- **不阻止日志**: 始终返回 True，允许日志记录

使用场景
--------
- 被 LevelBasedStreamHandler 自动添加
- 适用于所有 logging.Handler

注意事项
--------
- 转义后日志可读性略有下降（"\n" 显示为 "\\n"）
- 不处理非字符串类型的参数
- 不修改日志记录的其他属性

#### 方法

##### `filter(self, record)`

过滤并转义日志记录中的危险字符

参数
----
record : logging.LogRecord
    日志记录对象

返回
----
bool
    始终返回 True（允许日志通过）

处理流程
--------
1. 转义 record.msg 中的危险字符（如果是字符串）
2. 转义 record.args 中所有字符串参数的危险字符
3. 返回 True

转义规则
--------
- \x00 → \\x00（空字节）
- \n → \\n（换行符）
- \r → \\r（回车符）

副作用
------
直接修改 record.msg 和 record.args，不会创建新对象。

性能
----
- 只处理字符串类型
- 只转义 3 种字符，性能影响很小

线程安全
--------
每个 LogRecord 只被一个线程处理，无需加锁。

注意事项（修复）
--------------
record.msg和record.args都需要转义危险字符，确保一致性

### `class LogDeduplicator`

日志去重器

功能概述
--------
在指定时间窗口内去除重复日志，减少日志噪声，提高日志可读性。

去重策略
--------
- **时间窗口**: 默认 5 秒，在此期间的重复日志被抑制
- **哈希匹配**: 【性能优化】使用 Python 内置 hash() 函数判断消息是否重复（比 MD5 快 5-10 倍）
- **计数累加**: 重复日志的计数会累加，可附加到最终日志

缓存管理
----------
- **过期清理**: 超出时间窗口的缓存条目自动删除
- **大小限制**: 缓存超过 max_cache_size 时，删除最旧的 25% 条目
- **线程安全**: 使用 threading.Lock 保护缓存操作

内部结构
----------
- cache: {log_hash: (timestamp, count)}
  - log_hash: 消息的 MD5 哈希
  - timestamp: 最后一次出现的时间戳
  - count: 累计重复次数

使用场景
--------
- 高频日志场景（如轮询、心跳）
- 错误重试场景（避免相同错误刷屏）
- EnhancedLogger 自动集成

性能考虑
--------
- MD5 哈希计算成本较低
- 缓存查找为 O(1)
- 定期清理防止内存泄漏

注意事项
--------
- 不同的日志内容（如时间戳）会导致哈希不同
- 去重可能隐藏重要信息（需谨慎配置时间窗口）
- 缓存会占用内存（由 max_cache_size 限制）

#### 方法

##### `__init__(self, time_window = 5.0, max_cache_size = 1000)`

初始化日志去重器

参数
----
time_window : float, optional
    时间窗口（秒），默认 5.0
    在此时间内的重复日志将被抑制
max_cache_size : int, optional
    最大缓存大小，默认 1000
    超过此大小时自动清理最旧的 25% 条目

初始化流程
----------
1. 设置时间窗口和缓存大小
2. 初始化空缓存字典
3. 创建线程锁

内部状态
--------
- time_window: 时间窗口（秒）
- max_cache_size: 最大缓存大小
- cache: 日志哈希 -> (时间戳, 计数) 的映射
- lock: 线程锁

##### `should_log(self, message: str) -> Tuple[bool, Optional[str]]`

检查是否应该记录日志

参数
----
message : str
    日志消息

返回
----
Tuple[bool, Optional[str]]
    - bool: 是否应该记录日志
    - Optional[str]: 重复信息（如 "重复 3 次"），无重复则为 None

处理流程
--------
1. 生成消息的 MD5 哈希
2. 检查哈希是否在缓存中：
   - 存在且在时间窗口内: 增加计数，不记录，返回 (False, "重复 N 次")
   - 存在但超出时间窗口: 重置计数，记录，返回 (True, None)
   - 不存在: 添加到缓存，记录，返回 (True, None)
3. 定期清理过期缓存

线程安全
--------
使用 self.lock 保护整个操作，确保缓存一致性。

性能
----
- 时间复杂度: O(1)（哈希查找）
- 【性能优化】使用 Python 内置 hash()，比 MD5 快 5-10 倍
- 清理操作: O(m)（m 为缓存大小）

注意事项
--------
- 相同内容的消息会被去重
- 不同时间戳的消息会被视为不同（需在格式化前去重）
- 使用内置 hash() 而非加密哈希，因为日志去重不需要加密安全性

### `class EnhancedLogger`

增强的日志记录器

功能概述
--------
提供企业级日志功能的高级接口，集成所有底层优化：
- 单例管理（防止日志重复）
- 日志去重（减少噪声）
- 自动脱敏（保护敏感信息）
- 注入防护（防止日志攻击）
- 智能级别映射（动态调整日志级别）

核心特性
--------
1. **单例 Logger**: 通过 SingletonLogManager 确保 logger 不重复初始化
2. **自动去重**: 5 秒时间窗口内的重复日志自动抑制
3. **透明脱敏**: 自动检测并脱敏密码、API key 等敏感信息
4. **防注入攻击**: 自动转义换行符和控制字符
5. **智能级别**: 根据消息内容关键词自动调整日志级别

使用场景
--------
- 替代标准 logging.Logger 使用
- 需要高级日志功能的场景
- MCP 服务器日志记录

API 兼容性
----------
提供与标准 logging.Logger 兼容的方法：
- debug(message, *args, **kwargs)
- info(message, *args, **kwargs)
- warning(message, *args, **kwargs)
- error(message, *args, **kwargs)

级别映射规则
------------
根据消息中的关键词自动调整日志级别（可扩展）：
- "收到反馈请求", "Web UI 配置加载成功" → DEBUG
- "等待用户反馈", "收到用户反馈" → INFO
- "服务启动失败", "配置加载失败" → ERROR

性能
----
- 去重增加少量开销（MD5 哈希 + 缓存查找）
- 级别映射使用简单字符串匹配（O(m)，m 为映射数量）
- 脱敏和注入防护在底层 Handler 处理

注意事项
--------
- 去重可能隐藏重要信息（时间窗口 5 秒）
- 级别映射基于字符串匹配，可能误判
- 不支持动态修改 level_mapping（需重新创建实例）

#### 方法

##### `__init__(self, name: str)`

初始化增强日志记录器

参数
----
name : str
    logger 名称（通常使用 __name__）

初始化流程
----------
1. 创建 SingletonLogManager 并获取 logger
2. 创建 LogDeduplicator（5 秒窗口，1000 条缓存）
3. 配置级别映射规则

内部组件
--------
- log_manager: SingletonLogManager 实例
- logger: 配置好的 logging.Logger
- deduplicator: LogDeduplicator 实例
- level_mapping: 消息关键词 -> 日志级别的映射

##### `log(self, level: int, message: str)`

记录日志（带去重和级别优化）

参数
----
level : int
    日志级别（DEBUG, INFO, WARNING, ERROR, CRITICAL）
message : str
    日志消息
*args
    传递给 logger.log() 的额外参数
**kwargs
    传递给 logger.log() 的关键字参数

处理流程
--------
1. 根据消息内容获取有效日志级别（可能与 level 不同）
2. 检查是否应该记录（去重）
3. 如果应该记录：
   - 如果有重复信息，附加到消息末尾
   - 调用底层 logger.log()

去重机制
--------
在 5 秒时间窗口内，相同消息只记录一次，重复计数附加到消息。

级别映射
--------
即使调用 debug()，如果消息匹配到 ERROR 映射，也会以 ERROR 级别记录。

注意事项
--------
- 去重基于消息内容（不包括参数）
- 级别映射可能覆盖传入的 level
- 底层 handler 会自动脱敏和防注入

##### `debug(self, message: str)`

记录 DEBUG 级别日志

参数
----
message : str
    日志消息
*args
    额外参数
**kwargs
    关键字参数

功能
----
调用 self.log(logging.DEBUG, message, *args, **kwargs)

注意
----
实际日志级别可能被 level_mapping 覆盖

##### `info(self, message: str)`

记录 INFO 级别日志

参数
----
message : str
    日志消息
*args
    额外参数
**kwargs
    关键字参数

功能
----
调用 self.log(logging.INFO, message, *args, **kwargs)

注意
----
实际日志级别可能被 level_mapping 覆盖

##### `warning(self, message: str)`

记录 WARNING 级别日志

参数
----
message : str
    日志消息
*args
    额外参数
**kwargs
    关键字参数

功能
----
调用 self.log(logging.WARNING, message, *args, **kwargs)

注意
----
实际日志级别可能被 level_mapping 覆盖

##### `error(self, message: str)`

记录 ERROR 级别日志

参数
----
message : str
    日志消息
*args
    额外参数
**kwargs
    关键字参数

功能
----
调用 self.log(logging.ERROR, message, *args, **kwargs)

注意
----
实际日志级别可能被 level_mapping 覆盖
