# web_ui_rate_limiter

> For the Chinese version with full docstrings, see: [`docs/api.zh-CN/web_ui_rate_limiter.md`](../api.zh-CN/web_ui_rate_limiter.md)

## Functions

### `_parse_limit(raw: str) -> _LimitSpec`

## Classes

### `class WebUiLimiterProtocol`

#### Methods

##### `limit(self, limit_value: str) -> Callable[[_DecoratedCallable], _DecoratedCallable]`

##### `exempt(self, func: _DecoratedCallable) -> _DecoratedCallable`

### `class _LimitSpec`

#### Methods

##### `__init__(self, amount: int, period_seconds: int, raw: str) -> None`

### `class _LimitDecision`

#### Methods

##### `__init__(self) -> None`

### `class WebUiRateLimiter`

#### Methods

##### `__init__(self, app: Any) -> None`

##### `limit(self, limit_value: str) -> Callable[[_DecoratedCallable], _DecoratedCallable]`

##### `exempt(self, func: _DecoratedCallable) -> _DecoratedCallable`
