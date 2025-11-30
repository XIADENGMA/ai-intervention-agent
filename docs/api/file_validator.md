# file_validator

文件验证模块

功能概述
--------
提供企业级文件上传安全验证，防止恶意文件上传和文件类型伪装攻击。

核心功能
--------
1. **魔数验证**: 基于文件头部字节序列验证真实文件类型
2. **文件类型检查**: 支持 PNG、JPEG、GIF、WebP、BMP、TIFF、ICO、SVG 等图片格式
3. **恶意内容扫描**: 检测 JavaScript、PHP、Shell、SQL 注入等恶意代码模式
4. **文件大小限制**: 可配置的文件大小上限（默认 10MB）
5. **文件名安全**: 检测路径遍历、特殊字符、隐藏文件等安全风险
6. **MIME 类型一致性**: 验证声明的 MIME 类型与实际检测结果是否一致

主要组件
--------
- IMAGE_MAGIC_NUMBERS: 图片格式魔数字典（支持 10+ 种格式）
- DANGEROUS_EXTENSIONS: 危险文件扩展名黑名单（可执行文件、脚本等）
- MALICIOUS_PATTERNS: 恶意内容正则模式列表（JavaScript、PHP、Shell 等）
- FileValidationError: 文件验证异常类
- FileValidator: 核心验证器类
- validate_uploaded_file: 便捷验证函数
- is_safe_image_file: 快速安全检查函数

验证流程
--------
1. 基础属性检查（文件大小、文件名长度、危险扩展名）
2. 魔数验证（识别真实文件类型）
3. 文件名安全检查（路径遍历、特殊字符）
4. MIME 类型一致性验证（可选）
5. 恶意内容扫描（前 64KB）
6. 汇总验证结果

安全特性
--------
- **魔数优先**: 不依赖文件扩展名或 MIME 声明，基于文件实际内容判断
- **深度扫描**: 检测嵌入在图片中的恶意代码
- **性能平衡**: 只扫描文件前 64KB，避免大文件性能问题
- **多层防护**: 文件名、类型、内容、大小多维度验证

使用场景
--------
- Web 应用文件上传
- 用户头像、图片上传
- 文件存储服务
- MCP 服务器文件接收

注意事项
--------
- 恶意内容扫描基于正则匹配，可能存在误判或漏判
- 魔数验证依赖文件头部，对损坏文件可能识别失败
- SVG 文件可能包含 JavaScript，建议额外处理
- 性能优化：只扫描前 64KB，超大文件末尾的恶意代码可能漏检

依赖
----
- logging: 日志记录
- re: 正则表达式（恶意内容扫描）
- pathlib: 文件路径处理
- typing: 类型注解

## 函数

### `validate_uploaded_file(file_data: bytes, filename: str, mime_type: str = None) -> Dict`

便捷函数：验证上传的文件

参数
----
file_data : bytes
    文件二进制数据
filename : str
    文件名
mime_type : str, optional
    客户端声明的 MIME 类型

返回
----
Dict
    验证结果字典，包含以下字段：
    - valid: 是否通过验证（bool）
    - file_type: 检测到的文件类型描述（str）
    - mime_type: MIME 类型（str）
    - extension: 推荐扩展名（str）
    - size: 文件大小（int）
    - warnings: 警告列表（List[str]）
    - errors: 错误列表（List[str]）

功能
----
使用模块级单例 _default_validator 实例（10MB 限制）并执行验证。

使用场景
--------
- 快速验证单个文件
- 不需要自定义配置时使用
- API 端点中的简单验证

性能
----
- 【优化】使用模块级单例实例，避免重复创建和正则编译
- 【优化】所有调用共享预编译的正则模式，大幅提升性能

注意事项
--------
- 【修改】使用模块级单例 _default_validator（线程安全）
- 使用默认的 10MB 文件大小限制
- 如需自定义配置，请直接使用 FileValidator 类

### `is_safe_image_file(file_data: bytes, filename: str) -> bool`

便捷函数：检查是否为安全的图片文件

参数
----
file_data : bytes
    文件二进制数据
filename : str
    文件名

返回
----
bool
    True: 文件通过所有验证且无错误
    False: 文件验证失败或存在错误

功能
----
调用 validate_uploaded_file() 并简化返回结果为布尔值。

判断逻辑
--------
同时满足以下条件返回 True：
- valid 为 True
- errors 列表为空

使用场景
--------
- 快速布尔判断（不需要详细错误信息）
- 条件分支判断
- 简单的上传前检查

注意事项
--------
- 只返回布尔值，不提供具体错误信息
- 警告不影响返回结果（只检查 errors）
- 如需详细信息，请使用 validate_uploaded_file()

## 类

### `class FileValidationError`

文件验证异常

异常类型
--------
当文件验证失败时抛出此异常，表示文件不符合安全要求。

使用场景
--------
- 文件格式无法识别
- 文件大小超过限制
- 检测到恶意内容
- 文件名包含非法字符

继承
----
继承自 Exception，可被 try-except 捕获。

注意
----
- 异常消息应包含具体的失败原因
- 调用方应记录异常信息用于审计

### `class FileValidator`

文件验证器

功能概述
--------
提供全面的文件上传安全验证，包括魔数验证、恶意内容扫描、文件名检查等。

核心职责
--------
1. 基础属性验证（大小、文件名长度、危险扩展名）
2. 魔数验证（识别真实文件类型）
3. 文件名安全检查（路径遍历、特殊字符）
4. MIME 类型一致性检查（可选）
5. 恶意内容扫描（正则模式匹配）

配置参数
--------
- max_file_size: 最大文件大小（字节），默认 10MB
- compiled_patterns: 预编译的恶意内容正则模式列表

验证结果
--------
返回字典包含：
- valid: 是否通过验证
- file_type: 检测到的文件类型描述
- mime_type: MIME 类型
- extension: 推荐扩展名
- size: 文件大小
- warnings: 警告列表
- errors: 错误列表

设计原则
--------
- **安全优先**: 多层验证，宁可误杀不可放过
- **性能平衡**: 只扫描前 64KB，避免大文件性能问题
- **可扩展**: 易于添加新的验证规则和文件格式

使用场景
--------
- Web 应用文件上传
- API 文件接收端点
- 文件存储服务

线程安全
--------
每个验证操作是独立的，不共享状态，可在多线程环境使用。

注意事项
--------
- 验证失败不会抛出异常，而是返回包含错误信息的字典
- 警告不影响验证结果，但应引起注意
- 预编译的正则模式在初始化时生成，提高性能

#### 方法

##### `__init__(self, max_file_size: int = 10 * 1024 * 1024)`

初始化文件验证器

参数
----
max_file_size : int, optional
    最大文件大小（字节），默认 10MB（10 * 1024 * 1024）

初始化流程
----------
1. 验证max_file_size参数（必须为正数）
2. 设置最大文件大小限制
3. 预编译所有恶意内容正则模式（提高后续扫描性能）
4. 【优化】预先 decode 正则 pattern 字符串（避免重复 decode）

预编译优化
----------
在初始化时预编译正则表达式，避免每次验证都重新编译，提高性能。
使用 re.IGNORECASE 标志，实现不区分大小写的匹配。
同时预先 decode pattern 字符串，避免在错误报告时重复 decode。

异常
----
ValueError
    如果 max_file_size <= 0

##### `validate_file(self, file_data: bytes, filename: str, declared_mime_type: str = None) -> Dict`

验证文件安全性（核心方法）

参数
----
file_data : bytes
    文件二进制数据
filename : str
    文件名（用于扩展名检查和日志）
declared_mime_type : str, optional
    客户端声明的 MIME 类型（用于一致性检查）

返回
----
Dict
    验证结果字典，包含以下字段：
    - valid: 是否通过验证（bool）
    - file_type: 检测到的文件类型描述（str）
    - mime_type: MIME 类型（str）
    - extension: 推荐扩展名（str）
    - size: 文件大小（int）
    - warnings: 警告列表（List[str]）
    - errors: 错误列表（List[str]）

验证流程
--------
1. 基础属性检查（文件大小、文件名长度、危险扩展名）
2. 魔数验证（识别真实文件类型）
3. 文件名安全检查（路径遍历、特殊字符）
4. MIME 类型一致性检查（如果提供了 declared_mime_type）
5. 恶意内容扫描（前 64KB）
6. 汇总验证结果

验证结果判定
------------
- valid = True: errors 列表为空
- valid = False: errors 列表包含至少一个错误
- warnings 不影响 valid 的值，但应引起注意

异常处理
--------
捕获所有验证过程中的异常，记录到 errors 列表，不会向外抛出异常。

日志记录
--------
- 验证通过: logger.info()
- 验证失败: logger.warning()
- 验证异常: logger.error()

性能
----
- 时间复杂度: O(n)，n 为文件大小（恶意内容扫描）
- 空间复杂度: O(1)，不复制文件数据
- 优化: 恶意内容扫描限制为前 64KB

线程安全
--------
每次调用创建独立的 result 字典，无共享状态，线程安全。

注意事项
--------
- 不会抛出 FileValidationError 异常（保留向后兼容）
- 所有错误都记录在返回字典的 errors 字段
- 验证失败不会中断流程，会执行所有检查
- 添加输入参数验证（filename、file_data非空）
