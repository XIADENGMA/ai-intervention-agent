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

### `_judge_ip_entry(item: Any) -> str | None`

名单里一项算什么：``normalize_ip_entries`` 和 ``unusable_ip_entries`` 共用这一份判断。

返回规范写法（能用）；``""``（只有空白，静默跳过）；``None``（不是字符串，或不是 IP / 网段）。

### `unusable_ip_entries(items: list[Any]) -> list[int]`

名单里 ``normalize_ip_entries`` 会丢掉（并各记一条 WARNING）的条目的位置，从 0 数起。

只有位置，没有内容：读不懂的那一项可能是贴错了地方的令牌，不该被写进日志。

### `validate_allowed_networks(networks: Any) -> list[str]`

验证并规范化 allowed_networks；空列表 / 全部无效时只放行本机回环。

``networks`` 不是列表时改用 ``non_list_fallback``（缺省为 ``DEFAULT_ALLOWED_NETWORKS``）。
``ConfigManager`` 读写配置文件时传 ``LOOPBACK_ALLOWED_NETWORKS``：文件里写成了字符串之类的
错误，不该因此放开整个内网。

### `validate_blocked_ips(ips: Any) -> list[str]`

验证并规范化 blocked_ips（单个 IP 或 CIDR）；不是列表时按空名单处理。

### `blocked_ips_problem(ips: Any) -> str | None`

``blocked_ips`` 里有 ``validate_blocked_ips`` 会丢掉的东西时，返回一句说明；没有就是 ``None``。

拦截名单丢掉一项，那个地址就没有被拦住；放行名单丢掉一项只是少放行一个。所以读配置文件的
一侧（``ConfigManager.get_network_security_config``）遇到这样的名单，不把这一段当成一份能用的
配置（R920）。没写（``None``）、空列表、只有空白的条目都不是问题。说明里只有类型和位置，
没有内容：读不懂的那一项可能是贴错了地方的令牌。

### `validate_trusted_hosts(hosts: Any) -> list[str]`

Validate explicit Host allowlist entries while preserving hostname form.

### `validate_trusted_proxy_hops(value: Any) -> int`

``trusted_proxy_hops``：0 到 ``MAX_TRUSTED_PROXY_HOPS`` 的整数。

没写（``None``）是 1，不作声；写坏了（布尔、字符串、小数、越界）也按 1 处理并记一条
WARNING，与没配置时的行为一致（R849）。

### `validate_network_security_config(config: Any) -> dict[str, Any]`

验证并清理 network_security 配置
