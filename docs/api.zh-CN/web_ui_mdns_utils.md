# web_ui_mdns_utils

> 英文 signature-only 版本（仅函数 / 类签名速查）：[`docs/api/web_ui_mdns_utils.md`](../api/web_ui_mdns_utils.md)

mDNS / DNS-SD 辅助工具 — 从 web_ui.py 提取。

R23.2：``psutil`` 为 lazy 导入——唯一使用点 ``_list_non_loopback_ipv4``
只在 mDNS 启用且枚举网卡时触发（daemon thread），cold-start 主线程
100% 不需要；延迟 import 可省 ~3 ms 启动成本，失败仍走空列表降级。

## 函数

### `normalize_mdns_hostname(value: Any) -> str`

规范化 mDNS 主机名。

### `_is_probably_virtual_interface(ifname: str) -> bool`

启发式过滤虚拟网卡（避免优先选到 docker0 / veth 等）

### `_get_default_route_ipv4() -> str | None`

通过路由选择的方式获取"默认出口"IPv4（不实际发包）

### `_list_non_loopback_ipv4(prefer_physical: bool = True) -> list[str]`

枚举本机非回环 IPv4 地址（优先物理网卡）。

### `detect_best_publish_ipv4(bind_interface: str) -> str | None`

自动探测适合对外发布的 IPv4 地址。
