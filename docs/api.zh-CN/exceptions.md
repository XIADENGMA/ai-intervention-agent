# exceptions — 统一异常定义

项目级别的异常层次结构。所有业务异常均继承 `AIAgentError` 基类，支持结构化错误码与附加详情。

## 异常层次

```
Exception
└── AIAgentError                 # 项目基础异常
    ├── ConfigError              # 配置相关
    │   ├── ConfigFileNotFoundError
    │   └── ConfigValidationError
    ├── ServiceConnectionError   # 服务连接
    │   ├── ServiceUnavailableError
    │   └── ServiceTimeoutError
    ├── TaskError                # 任务相关
    │   ├── TaskNotFoundError
    │   └── TaskTimeoutError
    ├── NotificationError        # 通知相关
    └── ValidationError          # 输入验证
```

## AIAgentError

```python
class AIAgentError(Exception):
    def __init__(
        self,
        message: str,
        *,
        code: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None: ...
```

### 属性

| 属性 | 类型 | 说明 |
|------|------|------|
| `code` | `str \| None` | 机器可读的错误码（如 `"service_unavailable"`） |
| `details` | `dict[str, Any]` | 附加结构化信息，默认为空字典 |

### 用法示例

```python
from exceptions import ServiceTimeoutError

raise ServiceTimeoutError(
    "Web UI 启动超时",
    code="timeout",
    details={"elapsed_ms": 5000, "url": "http://localhost:8080"},
)
```

## 工具函数

### make_error_response

```python
def make_error_response(
    message: str,
    status_code: int = 400,
    *,
    code: str | None = None,
) -> tuple[dict[str, Any], int]:
```

构建标准化的 Flask API 错误响应体。返回 `(body_dict, status_code)` 元组，调用方需自行 `jsonify`。

**标准响应格式：**

```json
{
  "success": false,
  "error": "错误描述",
  "code": "error_code"
}
```

### 用法

```python
from exceptions import make_error_response
from flask import jsonify

body, status = make_error_response("任务不存在", 404, code="not_found")
return jsonify(body), status
```

## Flask 全局错误处理器

`web_ui.py` 中注册了 `@app.errorhandler(AIAgentError)`，自动将未捕获的 `AIAgentError` 转为 JSON 响应：

| `exc.code` | HTTP 状态码 |
|-------------|-------------|
| `"not_found"` | 404 |
| `"validation"` | 400 |
| `"timeout"` | 504 |
| 其他 / `None` | 500 |
