# web_ui_rate_limiter

> 英文 signature-only 版本（仅函数 / 类签名速查）：[`docs/api/web_ui_rate_limiter.md`](../api/web_ui_rate_limiter.md)

Lightweight in-memory rate limiter for the local Web UI.

## 函数

### `_is_more_limiting(candidate: _LimitDecision, current: _LimitDecision) -> bool`

Whether ``candidate`` is the decision to report instead of ``current``.

A request goes through only when every limit that applies to it lets it
through, so a refusal outranks a pass whatever the numbers say (R914). Of
two refusals the one that lifts later is reported, because that is when the
request can go through again; of two passes the one with fewer calls left,
and on a tie the one that resets first.

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
