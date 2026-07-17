# web_ui_rate_limiter

> 英文 signature-only 版本（仅函数 / 类签名速查）：[`docs/api/web_ui_rate_limiter.md`](../api/web_ui_rate_limiter.md)

Lightweight in-memory rate limiter for the local Web UI.

This module intentionally covers the small Flask-Limiter surface used by the
Web UI (``limit`` / ``exempt`` / ``enabled``) without importing
``flask_limiter`` during ``WebFeedbackUI`` construction.

## 函数

### `_parse_limit(raw: str) -> _LimitSpec`

### `_limit_period_seconds(raw: str) -> int`

## 类

### `class WebUiLimiterProtocol`

Small limiter surface used by Web UI route mixins.

#### 方法

##### `limit(self, limit_value: str) -> Callable[[_DecoratedCallable], _DecoratedCallable]`

##### `exempt(self, func: _DecoratedCallable) -> _DecoratedCallable`

### `class _LimitSpec`

#### 方法

##### `__init__(self, amount: int, period_seconds: int, raw: str) -> None`

### `class _LimitDecision`

#### 方法

##### `__init__(self) -> None`

### `class WebUiRateLimiter`

Small fixed-window limiter compatible with the Web UI's decorator use.

#### 方法

##### `__init__(self, app: Any) -> None`

##### `limit(self, limit_value: str) -> Callable[[_DecoratedCallable], _DecoratedCallable]`

##### `exempt(self, func: _DecoratedCallable) -> _DecoratedCallable`
