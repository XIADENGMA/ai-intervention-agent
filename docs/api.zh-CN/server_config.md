# server_config

> 英文 signature-only 版本（仅函数 / 类签名速查）：[`docs/api/server_config.md`](../api/server_config.md)

MCP 服务器配置与工具函数 — 配置数据类、常量、输入验证、响应解析。

## 函数

### `_lazy_mcp_types() -> Any`

懒加载并缓存 ``mcp.types`` 模块对象（线程安全：GIL + 幂等赋值）。

### `get_feedback_config() -> FeedbackConfig`

从配置文件加载反馈配置

### `calculate_backend_timeout(auto_resubmit_timeout: int, max_timeout: int = 0, infinite_wait: bool = False) -> int`

计算后端等待超时：前端倒计时 + 缓冲，0 表示无限等待

### `get_feedback_prompts() -> tuple[str, str]`

获取 (resubmit_prompt, prompt_suffix)

### `_append_prompt_suffix(text: str) -> str`

为用户反馈类文本追加 prompt_suffix（若已存在则不重复追加）

### `_make_resubmit_response(as_mcp: Literal[True] = ...) -> list`

### `_make_resubmit_response(as_mcp: Literal[False]) -> dict`

### `_make_resubmit_response(as_mcp: bool = True) -> list | dict`

创建错误/超时的重新提交响应

### `_normalize_option_default(value: Any) -> bool`

把任意输入归一化为 bool（接受 true/false/1/0/"true"/"false"/"yes"/"no"）。

### `validate_input_with_defaults(prompt: str, predefined_options: list | None = None) -> tuple[str, list[str], list[bool]]`

验证清理输入：截断过长内容，过滤非法选项，并解析每项的"默认选中"状态。

### `validate_input(prompt: str, predefined_options: list | None = None) -> tuple[str, list[str]]`

验证清理输入：截断过长内容，过滤非法选项（向后兼容签名）。

### `_task_id_prefix() -> str`

任务 ID 里可读的项目前缀，保证能安全地放进任何位置。

任务 ID 会进 URL 路径、查询串、CSS 属性选择器、HTML 属性和日志，所以前缀只保留
任何语言的字母和数字、依附在它们后面的组合符号，以及 ``._-``；其余字符
（``#``、``?``、``%``、引号、空白、emoji……）一律换成 ``-``，连续的 ``-`` 合并、
首尾的去掉。工作目录已被删除或读不了、或者名字里没有可读字符时回落到 ``task``。

### `_generate_task_id() -> str`

生成全局唯一任务 ID（避免极端并发下碰撞）

形如 ``<项目前缀>-<uuid4>``，前缀的清洗规则见 ``_task_id_prefix``。

### `get_target_host(host: str) -> str`

将不可直连的监听地址转换为客户端可访问地址（如 localhost）

返回的是**主机地址**，不是 URL 里的写法：IPv6 字面量不带方括号。它要原样交给
``getaddrinfo`` 之类的套接字接口（``is_web_service_running``），拼 URL 请用
:func:`get_target_base_url` / :func:`format_url_host`。

### `format_url_host(host: str) -> str`

主机放进 URL 时的写法：IPv6 字面量必须加方括号（``::1`` → ``[::1]``）。

``http://::1:8080`` 不是合法 URL（httpx 报 ``Invalid port: ':1:8080'``），
``http://[::1]:8080`` 才是。IPv4、主机名和已经带方括号的输入原样返回。

### `get_target_base_url(host: str, port: int) -> str`

MCP 服务访问 Web UI 的基地址 ``http://<可直连主机>:<port>``。

``0.0.0.0`` / ``::`` 这类通配监听地址换成 ``localhost``，IPv6 字面量加方括号。

### `is_loopback_url(url: str) -> bool`

判断 URL 的 host 是否解析到本机回环地址。

### `resolve_external_base_url(web_ui_config: WebUIConfig | None = None) -> str`

解析"对外可访问"的 Web UI 基地址，用于通知点击跳转等场景。

### `suggest_lan_base_url(port: int) -> str | None`

探测一个适合对外推送的 LAN base_url（``http://<lan-ipv4>:<port>``）。

### `_format_file_size(size: int) -> str`

格式化文件大小为人类可读格式

### `_guess_mime_type_from_data(base64_data: str) -> str | None`

通过文件魔数猜测 MIME 类型

### `_process_image(image: dict, index: int) -> tuple[ImageContent | None, str | None]`

处理单张图片，返回 (ImageContent, 文本描述)

### `parse_structured_response(response_data: dict[str, Any] | None) -> list[ContentBlock]`

解析反馈数据为 MCP Content 列表

## 类

### `class WebUIConfig`

Web UI 服务配置：host, port, timeout, max_retries, retry_delay

#### 方法

##### `validate_language(cls, v: str) -> str`

##### `validate_port(cls, v: int) -> int`

##### `clamp_timeout(cls, v: int) -> int`

##### `clamp_max_retries(cls, v: int) -> int`

##### `clamp_retry_delay(cls, v: float) -> float`

### `class FeedbackConfig`

反馈配置：timeout、auto_resubmit_timeout、提示语等

#### 方法

##### `clamp_timeout(cls, v: int) -> int`

##### `clamp_auto_resubmit(cls, v: int) -> int`

##### `truncate_resubmit(cls, v: str) -> str`

##### `truncate_suffix(cls, v: str) -> str`
