# web_ui_validators

> 英文 signature-only 版本（仅函数 / 类签名速查）：[`docs/api/web_ui_validators.md`](../api/web_ui_validators.md)

网络安全配置验证 & 超时校验 — 从 web_ui.py 提取的纯函数。

``network_security`` 里"一条 IP / 网段算不算有效、写成什么样"只在这里判断一次：
Web UI 的访问控制用这些函数，``ConfigManager`` 保存和读取配置时也用它们
（``config_modules.network_security``），两边不会各养一份慢慢走样的拷贝（R843）。

## 函数

### `validate_auto_resubmit_timeout(value: int) -> int`

验证并限制 auto_resubmit_timeout 范围。

### `parse_bind_interface(value: object) -> str | None`

监听地址（去掉首尾空白）；不是特殊值 / IP 字面量时返回 ``None``。不记日志。

### `validate_bind_interface(value: object) -> str`

验证绑定接口，无效时返回 127.0.0.1

### `validate_network_cidr(network_str: Any) -> bool`

验证 CIDR 或 IP 格式是否有效

### `_normalize_ip_str(addr_str: str) -> str`

将 IP 地址字符串规范化（处理 IPv4-mapped IPv6 → IPv4、非标准缩写 → 标准形式）。

### `_canonical_ip_entry(entry: str) -> str`

名单里一项（单个 IP 或 CIDR）的规范写法；不是 IP / 网段时抛 ``ValueError``。

单个 IP 里的 IPv4-mapped IPv6（``::ffff:10.0.0.1``）写成 IPv4：访问控制比较之前对客户端
地址也是这么处理的，名单里的写法不一致就匹配不上。CIDR 取 ``ip_network(strict=False)``
的结果（``10.0.0.5/8`` 记成 ``10.0.0.0/8``）。

### `normalize_ip_entries(items: list[Any], field: str) -> list[str]`

把 allowed_networks / blocked_ips 这类名单整理成规范、去重、保序的字符串列表。

- 首尾空白去掉；空串和纯空白静默跳过
- 不是字符串、不是 IP / 网段的条目跳过，各记一条带字段名 ``field`` 的 WARNING
- 规范化之后重复的只留第一个（``10.0.0.5/8`` 和 ``10.0.0.0/8`` 是同一项）

### `validate_allowed_networks(networks: Any) -> list[str]`

验证并规范化 allowed_networks；空列表 / 全部无效时只放行本机回环。

``networks`` 不是列表时改用 ``non_list_fallback``（缺省为 ``DEFAULT_ALLOWED_NETWORKS``）。
``ConfigManager`` 读写配置文件时传 ``LOOPBACK_ALLOWED_NETWORKS``：文件里写成了字符串之类的
错误，不该因此放开整个内网。

### `validate_blocked_ips(ips: Any) -> list[str]`

验证并规范化 blocked_ips（单个 IP 或 CIDR）；不是列表时按空名单处理。

### `validate_trusted_hosts(hosts: Any) -> list[str]`

Validate explicit Host allowlist entries while preserving hostname form.

### `validate_trusted_proxy_hops(value: Any) -> int`

``trusted_proxy_hops``：0 到 ``MAX_TRUSTED_PROXY_HOPS`` 的整数。

没写（``None``）是 1，不作声；写坏了（布尔、字符串、小数、越界）也按 1 处理并记一条
WARNING，与没配置时的行为一致（R849）。

### `validate_network_security_config(config: Any) -> dict[str, Any]`

验证并清理 network_security 配置
