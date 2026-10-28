# web_ui_validators

> For the Chinese version with full docstrings, see: [`docs/api.zh-CN/web_ui_validators.md`](../api.zh-CN/web_ui_validators.md)

## Functions

### `validate_auto_resubmit_timeout(value: int) -> int`

### `parse_bind_interface(value: object) -> str | None`

### `validate_bind_interface(value: object) -> str`

### `validate_network_cidr(network_str: Any) -> bool`

### `_normalize_ip_str(addr_str: str) -> str`

### `_canonical_ip_entry(entry: str) -> str`

### `normalize_ip_entries(items: list[Any], field: str) -> list[str]`

### `_judge_ip_entry(item: Any) -> str | None`

### `unusable_ip_entries(items: list[Any]) -> list[int]`

### `validate_allowed_networks(networks: Any) -> list[str]`

### `validate_blocked_ips(ips: Any) -> list[str]`

### `blocked_ips_problem(ips: Any) -> str | None`

### `validate_trusted_hosts(hosts: Any) -> list[str]`

### `validate_trusted_proxy_hops(value: Any) -> int`

### `validate_network_security_config(config: Any) -> dict[str, Any]`
