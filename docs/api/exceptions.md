# exceptions — Unified Exception Definitions

Project-level exception hierarchy. All business exceptions inherit from `AIAgentError`, supporting structured error codes and extra details.

## Exception Hierarchy

```
Exception
└── AIAgentError                 # Project base exception
    ├── ConfigError              # Configuration
    │   ├── ConfigFileNotFoundError
    │   └── ConfigValidationError
    ├── ServiceConnectionError   # Service connectivity
    │   ├── ServiceUnavailableError
    │   └── ServiceTimeoutError
    ├── TaskError                # Task lifecycle
    │   ├── TaskNotFoundError
    │   └── TaskTimeoutError
    ├── NotificationError        # Notifications
    └── ValidationError          # Input validation
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

### Attributes

| Attribute | Type | Description |
|-----------|------|-------------|
| `code` | `str \| None` | Machine-readable error code (e.g. `"service_unavailable"`) |
| `details` | `dict[str, Any]` | Structured debugging info, defaults to `{}` |

### Usage

```python
from exceptions import ServiceTimeoutError

raise ServiceTimeoutError(
    "Web UI startup timed out",
    code="timeout",
    details={"elapsed_ms": 5000, "url": "http://localhost:8080"},
)
```

## Helper Functions

### make_error_response

```python
def make_error_response(
    message: str,
    status_code: int = 400,
    *,
    code: str | None = None,
) -> tuple[dict[str, Any], int]:
```

Builds a standardised Flask API error response body. Returns `(body_dict, status_code)`; the caller is responsible for `jsonify()`.

**Standard response format:**

```json
{
  "success": false,
  "error": "Error description",
  "code": "error_code"
}
```

### Usage

```python
from exceptions import make_error_response
from flask import jsonify

body, status = make_error_response("Task not found", 404, code="not_found")
return jsonify(body), status
```

## Flask Global Error Handler

`web_ui.py` registers `@app.errorhandler(AIAgentError)` which converts uncaught `AIAgentError` instances into JSON responses:

| `exc.code` | HTTP Status |
|-------------|-------------|
| `"not_found"` | 404 |
| `"validation"` | 400 |
| `"timeout"` | 504 |
| Other / `None` | 500 |
