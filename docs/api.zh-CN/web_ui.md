# web_ui

> 英文 signature-only 版本（仅函数 / 类签名速查）：[`docs/api/web_ui.md`](../api/web_ui.md)

Web 反馈界面 - Flask Web UI，支持多任务、文件上传、通知、安全机制。

## 函数

### `get_project_version() -> str`

从 pyproject.toml 读取版本号，缓存结果

### `web_feedback_ui(prompt: str, predefined_options: list[str] | None = None, task_id: str | None = None, auto_resubmit_timeout: int = AUTO_RESUBMIT_TIMEOUT_DEFAULT, output_file: str | None = None, host: str = '0.0.0.0', port: int = 8080) -> FeedbackResult | None`

启动 Web UI（交互反馈界面）的便捷函数

功能说明：
    创建 WebFeedbackUI 实例并启动服务，收集用户反馈。可选地将结果保存到文件。

参数说明：
    prompt: 提示文本（Markdown 格式）
    predefined_options: 预定义选项列表（可选）
    task_id: 任务 ID（可选）
    auto_resubmit_timeout: 自动重调倒计时（秒，默认 240；范围 [10, 3600]；0=禁用）
    output_file: 输出文件路径（可选；若指定则将结果保存为 JSON 文件）
    host: 绑定主机地址（默认"0.0.0.0"）
    port: 绑定端口（默认8080）

返回值：
    FeedbackResult | None: 用户反馈结果字典，包含：
        - user_input: 用户输入文本
        - selected_options: 选中的选项数组
        - images: 图片数组（Base64编码）
    若指定output_file，则返回None（结果已保存到文件）

处理逻辑：
    1. 创建WebFeedbackUI实例
    2. 调用ui.run()启动服务器并等待反馈
    3. 若指定output_file：
       - 确保输出目录存在
       - 将反馈结果保存为JSON文件（UTF-8编码，格式化缩进）
       - 返回None
    4. 否则直接返回反馈结果

使用场景：
    - 命令行工具快速启动反馈界面
    - 自动化脚本收集用户输入
    - 测试和开发环境

注意事项：
    - 服务器会阻塞当前线程，直到用户提交反馈或关闭服务器
    - output_file路径的父目录会被自动创建
    - JSON文件使用ensure_ascii=False保留中文字符

## 类

### `class WebFeedbackUI`

Web 反馈界面核心类 - Flask 应用、安全策略、API 路由、任务管理。

功能通过 Mixin 组织：
- SecurityMixin          — IP 访问控制、CSP、安全头（web_ui_security.py）
- MdnsMixin              — mDNS/Zeroconf 服务发布（web_ui_mdns.py）
- TaskRoutesMixin        — 任务 CRUD（5 个路由）
- FeedbackRoutesMixin    — 反馈提交/查询（3 个路由）
- NotificationRoutesMixin — 通知配置/触发（5 个路由）
- StaticRoutesMixin      — 静态资源（8 个路由）
- SystemRoutesMixin      — 系统集成（用 IDE 打开配置文件等）
核心路由（index / config / health / close）保留在本类。

#### 方法

##### `__init__(self, prompt: str, predefined_options: list[str] | None = None, task_id: str | None = None, auto_resubmit_timeout: int = AUTO_RESUBMIT_TIMEOUT_DEFAULT, host: str = '0.0.0.0', port: int = 8080)`

初始化 Flask 应用、安全策略、路由

##### `setup_markdown(self) -> None`

设置Markdown渲染器和扩展

功能说明：
    初始化Python-Markdown实例，配置渲染扩展和代码高亮样式。

启用的扩展：
    - fenced_code：围栏代码块（```语法）
    - codehilite：代码语法高亮（基于Pygments）
    - tables：表格支持（GFM风格）
    - toc：自动生成目录
    - nl2br：换行符转<br>标签
    - attr_list：元素属性语法
    - def_list：定义列表
    - abbr：缩写词
    - footnotes：脚注支持
    - md_in_html：HTML中嵌入Markdown

代码高亮配置：
    - css_class: highlight（用于CSS样式）
    - use_pygments: True（使用Pygments进行语法高亮）
    - noclasses: True（内联样式，无需外部CSS）
    - pygments_style: monokai（Monokai配色方案）
    - guess_lang: True（自动检测代码语言）
    - linenums: False（禁用行号）

副作用：
    - 创建self.md实例（Markdown渲染器）

注意事项：
    - Pygments需要额外安装（pip install pygments）
    - 内联样式会增加HTML体积，但避免CSP问题
    - 扩展顺序可能影响渲染结果

##### `render_markdown(self, text: str) -> str`

渲染Markdown文本为HTML

功能说明：
    将Markdown格式的文本转换为HTML，应用代码高亮、表格、LaTeX等扩展。
    **R20.7：附带 LRU 缓存**——同一 ``text`` 重复调用直接命中 cache。

参数说明：
    text: Markdown格式的文本字符串（支持GFM风格）

返回值：
    str: 渲染后的HTML字符串（已应用语法高亮和格式化）

处理流程：
    1. 检查文本是否为空
    2. **缓存查表**：命中则 LRU touch（pop + 重新插入末尾）后直接返回
    3. **缓存未命中**：重置 Markdown 实例 → convert → 写入 cache
       （超过容量时 evict 最旧条目）

缓存语义
--------
- **key**：完整 prompt 字符串（避免 hash 冲突；prompt 长度受
  ``PROMPT_MAX_LENGTH`` 上限保护，单条最多 ~50KB）。
- **value**：渲染后的 HTML 字符串。
- **容量**：16 条（远大于 ``max_tasks=10``，合理场景命中率 ~100%）。
- **LRU 实现**：``dict`` 插入顺序保证（Python 3.7+），命中时
  ``pop`` + 重新插入把热条目移到末尾，逐出时
  ``next(iter(...))`` 是最旧的 key。

线程安全
--------
- 共享 ``self._md_lock``：``markdown.Markdown`` 实例非线程安全，
  ``reset() + convert()`` 必须串行执行；缓存读写也在同一锁内，
  避免 cache write 与 markdown convert race。
- 没用 ``RLock`` 因为方法内部不会递归 acquire 自己。

注意事项：
    - 空文本返回空字符串（避免None错误）
    - HTML未进行额外的XSS过滤，依赖Markdown库的安全性
    - cache 不在 ``/api/update`` 时显式失效——新 prompt 会作为新 key
      进入 cache，旧 key 自然 LRU evict，简化逻辑且无正确性问题。

##### `setup_routes(self) -> None`

注册所有API路由和静态资源路由

功能说明：
    注册Flask路由处理器，包括主页面、API端点、静态资源服务。

路由分类：
    **页面路由**：
        - GET / - 主页面HTML

    **任务管理API**：
        - GET  /api/config              - 获取当前任务配置
        - GET  /api/tasks               - 获取所有任务列表
        - POST /api/tasks               - 创建新任务
        - GET  /api/tasks/<id>          - 获取单个任务详情
        - POST /api/tasks/<id>/activate - 激活指定任务
        - POST /api/tasks/<id>/submit   - 提交任务反馈

    **反馈API**：
        - POST /api/submit              - 提交反馈（通用端点）
        - POST /api/update              - 更新页面内容
        - GET  /api/feedback            - 获取反馈结果

    **系统API**：
        - GET  /api/health              - 健康检查
        - POST /api/close               - 关闭服务器

    **通知API**：
        - POST /api/test-bark                - 测试Bark通知
        - POST /api/notify-new-tasks         - 新任务 Bark 触发（兼容第三方外部调用；内部 UI 不再调用，由 MCP 主进程统一推送）
        - POST /api/update-notification-config - 更新通知配置
        - GET  /api/get-notification-config  - 获取通知配置

    **静态资源**：
        - /static/css/<filename>        - CSS文件
        - /static/js/<filename>         - JavaScript文件
        - /fonts/<filename>             - 字体文件
        - /icons/<filename>             - 图标文件
        - /sounds/<filename>            - 音频文件
        - /favicon.ico                  - 网站图标

频率限制：
    - 默认：60次/分钟，10次/秒（全局）
    - /api/config：300次/分钟（轮询高频场景）
    - /api/tasks（GET）：300次/分钟（轮询高频场景）
    - /api/submit：60次/分钟（防止恶意提交）
    - /api/tasks（POST）：60次/分钟（防止任务创建滥用）

注意事项：
    - 所有路由处理器定义为内部函数，通过闭包访问self
    - limiter装饰器需要放在路由装饰器之后
    - 静态资源路由使用send_from_directory安全地提供文件

##### `shutdown_server(self) -> None`

优雅关闭Flask服务器

功能说明：
    向当前进程发送SIGINT信号，触发Flask服务器的优雅关闭流程。

处理逻辑：
    1. 获取当前进程PID（os.getpid()）
    2. 发送SIGINT信号（os.kill()）
    3. Flask接收信号后执行关闭流程

副作用：
    - 当前进程收到SIGINT信号
    - Flask服务器停止接受新请求
    - 等待现有请求处理完毕后退出

注意事项：
    - SIGINT相当于Ctrl+C信号
    - 关闭是全局的，影响所有客户端连接
    - 适用于单次任务完成后的自动关闭场景
    - 多任务模式下应避免调用此方法

##### `update_content(self, new_prompt: str, new_options: list[str] | None = None, new_task_id: str | None = None) -> None`

更新页面内容（单任务模式，实例方法）

功能说明：
    更新当前任务的prompt、选项、任务ID，用于单任务模式下的内容动态更新。

参数说明：
    new_prompt: 新的提示文本（Markdown格式）
    new_options: 新的预定义选项列表（可选，默认为空列表）
    new_task_id: 新的任务ID（可选）

处理逻辑：
    1. 更新self.current_prompt
    2. 更新self.current_options（None转为空列表）
    3. 更新self.current_task_id
    4. 更新self.has_content标志
    5. 记录日志（INFO级别）

副作用：
    - 修改self.current_prompt、current_options、current_task_id
    - 更新self.has_content标志
    - 记录日志到enhanced_logging

注意事项：
    - 仅更新实例属性，不修改self.feedback_result
    - 适用于单任务模式，多任务模式请使用TaskQueue API
    - 前端需通过/api/config轮询获取更新后的内容

##### `run(self) -> FeedbackResult`

启动Flask Web服务器并等待用户反馈

功能说明：
    启动Flask开发服务器，监听指定的host和port，等待用户提交反馈。

返回值：
    FeedbackResult: 用户反馈结果，包含以下字段：
        - user_input: 用户输入文本
        - selected_options: 选中的选项数组
        - images: 图片数组（Base64编码）

处理逻辑：
    1. 打印启动信息（访问URL、SSH端口转发命令等）
    2. 调用Flask的app.run()启动服务器
    3. 服务器运行直到收到SIGINT信号或调用shutdown_server()
    4. 返回self.feedback_result（若无反馈则返回空字典）

启动参数：
    - host: self.host（默认"0.0.0.0"）
    - port: self.port（默认8080）
    - debug: False（禁用调试模式）
    - use_reloader: False（禁用自动重载）

异常处理：
    - KeyboardInterrupt: 捕获Ctrl+C信号，正常退出

副作用：
    - 阻塞当前线程，直到服务器关闭
    - 打印启动信息到标准输出

注意事项：
    - 使用Flask开发服务器，不适合生产环境
    - 生产环境建议使用Gunicorn或uWSGI
    - 若self.feedback_result为None，返回空反馈字典
    - 服务器关闭后才返回，适用于单次任务模式
