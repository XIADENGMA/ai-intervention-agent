# web_ui_security

> For the Chinese version with full docstrings, see: [`docs/api.zh-CN/web_ui_security.md`](../api.zh-CN/web_ui_security.md)

## Functions

### `_normalize_trusted_host_candidate(value: object) -> str | None`

### `build_trusted_hosts() -> list[str]`

### `_may_change_state(method: str, path: str) -> bool`

### `_origin_parts(value: str) -> tuple[str, str] | None`

### `_origin_is_allowed(origin: str, host: str, allowed_origins: Collection[str | re.Pattern[str]]) -> bool`

### `is_cross_origin_write() -> bool`

### `_bracketed_address(value: str) -> IPv4Address | IPv6Address | None`

### `_host_is_trusted_with_ipv6(original: Callable[..., bool]) -> Callable[..., bool]`

### `ensure_ipv6_trusted_hosts_support() -> bool`

### `get_config() -> Any`

## Classes

### `class SecurityMixin`

#### Methods

##### `setup_security_headers(self) -> None`
