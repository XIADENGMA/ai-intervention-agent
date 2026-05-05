# web_ui_mdns

> 英文 signature-only 版本（仅函数 / 类签名速查）：[`docs/api/web_ui_mdns.md`](../api/web_ui_mdns.md)

mDNS 生命周期 Mixin — 从 WebFeedbackUI 提取。

封装 mDNS/DNS-SD 服务的发现、注册、注销逻辑，
由 WebFeedbackUI 通过 MRO 继承。

异步注册（R20.11）
~~~~~~~~~~~~~~~~~~
``_start_mdns_if_needed`` 内部的 ``zeroconf.register_service`` 因 RFC 6762 §8
要求的 conflict-probe announcement 而**同步阻塞 ~1.7 s**（多次 250 ms multicast
probe + 最终 announcement）。在 ``WebFeedbackUI.run()`` 中直接同步调用会让
Flask ``app.run()`` 进入 listen 状态延迟 ~1.7 s——浏览器/插件第一次访问 Web UI
会被推迟相同时间。

R20.11 把对 ``_start_mdns_if_needed`` 的调用搬到后台 daemon 线程：``run()`` 启动
线程后立刻进入 ``app.run()``，``app.run`` 在 ~30 ms 内开始 listen，浏览器可立即
访问；mDNS announcement 在后台并行完成，对 ``http://127.0.0.1:port`` /
``http://<lan-ip>:port`` 路径完全透明（这两条访问路径不依赖 mDNS 名字解析），仅
LAN 上其他设备用 ``ai.local`` 路径访问时才会等 announcement 完成（典型在 1-2 秒
内自然达成）。

``_stop_mdns`` 在 ``run()`` finally 块中 ``join`` 线程，防止 daemon 线程在主进程
结束时 race 写入 ``_mdns_zeroconf``。``_start_mdns_if_needed`` 自身保持同步语义
不变——既兼容现有 26+ 个直接调用该方法的单元测试，也允许 daemon thread 中按
原契约执行。

## 类

### `class MdnsMixin`

mDNS/Zeroconf 服务发布与注销。

#### 方法
