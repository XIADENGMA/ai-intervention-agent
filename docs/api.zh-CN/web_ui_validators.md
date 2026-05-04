# web_ui_validators

> 英文 signature-only 版本（仅函数 / 类签名速查）：[`docs/api/web_ui_validators.md`](../api/web_ui_validators.md)

网络安全配置验证 & 超时校验 — 从 web_ui.py 提取的纯函数。

所有函数均为无状态、无副作用（仅日志）的验证/规范化工具，
可安全地在测试、CLI、配置热更新等场景复用。

## 函数

### `validate_auto_resubmit_timeout(value: int) -> int`

验证并限制 auto_resubmit_timeout 范围。

- 0 / 负值 → 禁用（返回 0）
- 低于 AUTO_RESUBMIT_TIMEOUT_MIN → 提升至下限
- 高于 AUTO_RESUBMIT_TIMEOUT_MAX → 截断至上限

### `validate_bind_interface(value: object) -> str`

验证绑定接口，无效时返回 127.0.0.1

### `validate_network_cidr(network_str: Any) -> bool`

验证 CIDR 或 IP 格式是否有效

### `_normalize_ip_str(addr_str: str) -> str`

将 IP 地址字符串规范化（处理 IPv4-mapped IPv6 → IPv4、非标准缩写 → 标准形式）。

### `validate_allowed_networks(networks: Any) -> list[str]`

验证并过滤 allowed_networks（存储规范化形式），空列表时添加回环地址。

### `validate_blocked_ips(ips: Any) -> list[str]`

验证并清理 blocked_ips 列表（支持单个 IP 和 CIDR，存储规范化后的形式）。

### `validate_network_security_config(config: Any) -> dict[str, Any]`

验证并清理 network_security 配置
