# exceptions

> 英文 signature-only 版本（仅函数 / 类签名速查）：[`docs/api/exceptions.md`](../api/exceptions.md)

项目统一异常定义。

## 函数

### `make_error_response(message: str, status_code: int = 400) -> tuple[dict[str, Any], int]`

构建标准化的 Flask API 错误响应。

## 类

### `class AIAgentError`

项目基础异常。

#### 方法

##### `__init__(self, message: str) -> None`

### `class ConfigError`

配置加载、解析或校验失败。

### `class ConfigFileNotFoundError`

配置文件不存在。

### `class ConfigValidationError`

配置值不满足约束条件。

### `class ServiceConnectionError`

与 Web UI / 外部服务通信失败（连接、超时、HTTP 非 2xx 等）。

### `class ServiceUnavailableError`

服务未启动或无法到达。

### `class ServiceTimeoutError`

请求超时。

### `class TaskError`

任务创建、执行或等待失败。

### `class TaskNotFoundError`

指定任务不存在。

### `class TaskTimeoutError`

等待任务完成超时。

### `class NotificationError`

通知发送或配置错误。

### `class ValidationError`

输入参数不合法。
