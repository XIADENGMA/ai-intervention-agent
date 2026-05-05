# web_ui_mdns_utils

> 英文 signature-only 版本（仅函数 / 类签名速查）：[`docs/api/web_ui_mdns_utils.md`](../api/web_ui_mdns_utils.md)

mDNS / DNS-SD 辅助工具 — 从 web_ui.py 提取。

包含主机名规范化、虚拟网卡过滤、IPv4 地址探测等纯函数，
由 WebFeedbackUI 的 mDNS 功能调用。

R23.2: ``psutil`` 改成 lazy 导入。
why：``import psutil`` 在 ``web_ui`` cold-start trace 上是 ~3 ms 的纯静态成本
（``psutil._psosx`` ~1.5 ms + ``psutil._common`` ~1 ms + 子模块 ~0.5 ms），
但 psutil 在本模块**唯一的使用点**是 ``_list_non_loopback_ipv4`` —— 只有
在 mDNS 启用（``bind_interface != 127.0.0.1``）且需要枚举本机网卡时才会触发，
而 mDNS 注册又在 ``WebFeedbackUI.run()`` 启动的 daemon thread 异步执行（R20.11
确立的契约）。所以 main thread 的 cold-start 路径上 100% 不需要 psutil。
本地回环开发场景（``host=127.0.0.1``）甚至**永远**用不到。
延迟到 ``_list_non_loopback_ipv4`` 内部首次调用时才 import：
- ``sys.modules`` 已缓存，第二次调用零成本（mDNS 一般只查一次网卡）
- 第一次 import 在 daemon thread 中发生（mDNS 路径），不阻塞 main thread
  的 ``app.run()`` socket listen
- 失败仍走原有 ``except Exception`` 兜底（返回空列表 → mDNS 降级为不发布）

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

枚举本机非回环 IPv4 地址（优先物理网卡）。

R23.2: ``psutil`` 改成函数内 lazy import（详见模块顶部注释）。``sys.modules``
会自动缓存，第二次及以后调用零额外 import 成本；第一次 import 失败（极罕见，
psutil 是 hard dep）走 ``except Exception`` 路径，返回空列表让 mDNS 降级。

### `detect_best_publish_ipv4(bind_interface: str) -> str | None`

自动探测适合对外发布的 IPv4 地址。

优先级：
1) bind_interface 为具体 IPv4（非 0.0.0.0/回环）→ 直接使用
2) 默认路由推断
3) 物理网卡枚举
4) 所有非回环地址兜底
