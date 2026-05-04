# exceptions

> 英文 signature-only 版本（仅函数 / 类签名速查）：[`docs/api/exceptions.md`](../api/exceptions.md)

项目统一异常定义。

所有业务异常均继承 AIAgentError 基类，支持结构化错误码与附加详情，
便于日志分析、错误追踪和前端展示。

## 函数

### `make_error_response(message: str, status_code: int = 400) -> tuple[dict[str, Any], int]`

构建标准化的 Flask API 错误响应。

返回值可直接作为 Flask 路由的 return 值（jsonify 由调用方负责）。

用法::

    from exceptions import make_error_response
    from flask import jsonify
    return jsonify(make_error_response("任务不存在", 404, code="not_found")[0]), 404
    # 或更简洁：
    body, status = make_error_response("任务不存在", 404, code="not_found")
    return jsonify(body), status

## 类

### `class AIAgentError`

项目基础异常。

属性:
    code: 机器可读的错误码（如 "service_unavailable"），可选
    details: 附加结构化信息，便于调试或前端展示

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
