# web_ui_mdns_utils

> 英文 signature-only 版本（仅函数 / 类签名速查）：[`docs/api/web_ui_mdns_utils.md`](../api/web_ui_mdns_utils.md)

mDNS / DNS-SD 辅助工具 — 从 web_ui.py 提取。

包含主机名规范化、虚拟网卡过滤、IPv4 地址探测等纯函数，
由 WebFeedbackUI 的 mDNS 功能调用。

## 函数

### `normalize_mdns_hostname(value: Any) -> str`

规范化 mDNS 主机名。

- 非字符串 / 空 → 默认 ai.local
- 末尾 '.' 移除（zeroconf 内部会追加 FQDN 点号）
- 不含 '.' 的短名 → 追加 '.local'

### `_is_probably_virtual_interface(ifname: str) -> bool`

启发式过滤虚拟网卡（避免优先选到 docker0 / veth 等）

### `_get_default_route_ipv4() -> str | None`

通过路由选择的方式获取"默认出口"IPv4（不实际发包）

### `_list_non_loopback_ipv4(prefer_physical: bool = True) -> list[str]`

枚举本机非回环 IPv4 地址（优先物理网卡）

### `detect_best_publish_ipv4(bind_interface: str) -> str | None`

自动探测适合对外发布的 IPv4 地址。

优先级：
1) bind_interface 为具体 IPv4（非 0.0.0.0/回环）→ 直接使用
2) 默认路由推断
3) 物理网卡枚举
4) 所有非回环地址兜底
