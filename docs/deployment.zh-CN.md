# 部署 Profile

AI Intervention Agent 的 Web UI 支持两种部署 profile。

## 本地桌面 Profile

这是默认路径。`WebFeedbackUI.run()` 继续使用 Flask 内置 server，并固定
`debug=False`、`use_reloader=False`。它针对普通 MCP 工作流优化：快速启动、
绑定到配置里的本机 / 局域网地址、服务单个用户，然后干净退出。

本地 CLI、`uvx`、VS Code、Cursor、Claude Desktop、SSH 隧道等场景都应使用
这个 profile。

## WSGI / 反向代理 Profile

只有当 Web UI 需要长期运行、远程访问、由 systemd 托管，或放到 nginx /
Apache / 企业代理后面时才使用这一 profile。Flask 官方部署文档已经明确：
内置开发 server 只适合本地开发，不适合 production 的稳定性、安全性或效率要求。

在同一个环境里安装 WSGI server，然后指向 lazy factory。Waitress 适合
Windows / 简单部署，官方参数里也提供 threads / connection 相关调优项。不要
把普通短请求成功等同于 SSE 健康；目标 profile 必须用 `curl -N /api/events`
实际验证事件流。

```bash
python -m pip install ai-intervention-agent waitress
waitress-serve --listen=127.0.0.1:8080 --threads=8 --call 'ai_intervention_agent.web_ui_wsgi:create_app'
```

POSIX 主机若有长连接或多 SSE client，优先用 Gunicorn gevent 或等价 async
worker。但仍必须保持单 worker 进程，因为当前任务队列和 SSE bus 都是进程内内存：

```bash
python -m pip install ai-intervention-agent gunicorn gevent
gunicorn 'ai_intervention_agent.web_ui_wsgi:create_app()' \
  --bind 127.0.0.1:8080 \
  --workers 1 \
  --worker-class gevent \
  --worker-connections 100 \
  --timeout 0
```

除非未来版本引入外部任务队列后端，否则不要启用多 worker 进程。多个 worker 会各自
拥有独立的 task queue 和 SSE bus，于是某个 worker 创建的任务可能对连到另一个
worker 的浏览器不可见。

这样构建的 Web UI，地址类设置和 MCP 服务器给它自己启动的 Web UI 的完全一样：
`network_security.bind_interface`、`web_ui.port`、`web_ui.external_base_url`、
`mdns.hostname` 和 `network_security.trusted_hosts`（以及
`AI_INTERVENTION_AGENT_WEB_UI_HOST` / `AI_INTERVENTION_AGENT_WEB_UI_PORT` 两个环境变量的
覆盖）。它们决定接受哪些 `Host` 名称，所以把原始 `Host` 原样传下去的反向代理，要把它的
名字写进 `trusted_hosts` 或 `external_base_url`。它们只在应用构建时读一次：改了其中任何
一项都要重启 WSGI server。读不了配置时，应用按默认值启动（只接受回环地址和 `ai.local`），
日志里会说明。监听在哪里由 server 自己的 `--listen` / `--bind` 决定，不是
`bind_interface`。

## SSE 代理要求

`/api/events` 是 Server-Sent Events 流。反向代理不能缓冲它。路由本身已经输出：

- `Content-Type: text/event-stream`
- `Cache-Control: no-cache`
- `X-Accel-Buffering: no`

nginx 仍然需要显式代理配置：

```nginx
location /api/events {
    proxy_pass http://127.0.0.1:8080;
    proxy_http_version 1.1;
    proxy_set_header Connection "";
    proxy_set_header X-Forwarded-For $remote_addr;
    proxy_buffering off;
    proxy_cache off;
    proxy_read_timeout 1h;
}
```

这个块里也要保留 `X-Forwarded-For` 这一行。nginx 不会把外层块里的 `proxy_set_header` 带进自己也写了
`proxy_set_header` 的 `location`，不写的话事件流到 Web UI 时没有客户端地址，访问控制会把它的
每个访问者都当成 `127.0.0.1`（见[反向代理后面的客户端地址](#反向代理后面的客户端地址)）。

放在反向代理后面时，还要决定谁能发写请求。浏览器发来的会改状态的请求（`POST` / `PUT` /
`PATCH` / `DELETE`，加上 `GET /api/feedback`），除非浏览器声明它来自 Web UI 自己的页面，
否则返回 `403 cross_origin_write_blocked`。走 HTTPS 不用配置。走纯 HTTP 且代理改写了
`Host`（nginx 默认的 `proxy_pass` 就会）时，把 `web_ui.external_base_url` 设成你在浏览器里
打开的地址，或者让代理把原始 `Host` 传下去（`proxy_set_header Host $http_host;`）并把这个名字
写进 `network_security.trusted_hosts`；详见
[故障排查 §19](troubleshooting.zh-CN.md#19-web-ui-里的按钮没反应浏览器里看到-403-cross_origin_write_blocked)。

如果把 Web UI 暴露到 loopback 之外，请尽量收窄
`network_security.allowed_networks`，可行时优先使用 SSH 隧道。运行中的设置 API
必须能 round-trip 已有通知配置，所以它不是经过 secret-redaction 的公开 API。

## 反向代理后面的客户端地址

访问控制（`network_security.allowed_networks` 和 `blocked_ips`）和限流都靠一个客户端
地址区分访问者。来自其他机器的连接按它自己的地址判断，不读它的 `X-Forwarded-For` 头
（另一台机器上的代理会被当作它自己）。来自 Web UI 所在机器的连接就是紧挨着它的反向
代理（上面这种部署），这时客户端是这层代理写在 `X-Forwarded-For` 里的地址。

每层代理把它看到的地址追加在这个头的右边，而它左边的全是访问者自己写的，访问者可以在
那里写任何地址。所以客户端是 `network_security.trusted_proxy_hops` 指定的、从右数的那
一项：

- `1`（默认）：Web UI 旁边有一层代理，例如 nginx。客户端是最后一项。
- `2`：它前面还有一层代理，例如 CDN → nginx → Web UI。nginx 要把 CDN 的地址追加到 CDN
  发来的内容后面（`$proxy_add_x_forwarded_for`），客户端就是从右数第二项。
- `0`：不信任 `X-Forwarded-For`。经本机代理来的请求都按代理自己（`127.0.0.1`）判断。

头里的项数比设置的数还少时，取第一项。这个设置接受 0 到 8 的整数，其他值按 `1` 处理，
并在日志里打 warning。修改后约 2 秒内生效，和其他访问控制设置一样。

填 Web UI 前面真正有的代理层数。填得比实际多时，访问者自己写的一项会被当成客户端：
只有一层代理却填 `2`，访问者就能自己决定访问控制看到哪个地址。

紧挨着 Web UI 的代理必须自己写这个头。下面两种都安全；把访问者发来的头原样传下去
（`$http_x_forwarded_for`）则不安全：

```nginx
location / {
    proxy_pass http://127.0.0.1:8080;
    # 只有一项：nginx 看到的地址（trusted_proxy_hops = 1）
    proxy_set_header X-Forwarded-For $remote_addr;
    # 或者保留上一层代理发来的内容，再追加 nginx 看到的地址：
    # proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
}
```

不写这个头的代理会让每个访问者都像是 `127.0.0.1`，默认的 `allowed_networks` 会放行它。
CDN 在 nginx 前面、设置却还是 `1` 时，Web UI 判断的是 CDN 的地址，不是访问者的。

Waitress 必须被告知该信任哪个代理。从 3.0 起，没有给它代理的地址时，它会在请求到达 Web UI 之前删掉
`X-Forwarded-For`（以及 `X-Forwarded-Host`、`X-Forwarded-Proto`、`X-Forwarded-Port` 和
`Forwarded`），不管代理写了什么。按本页开头的命令运行、前面放 nginx 时，每个访问者都会像是
`127.0.0.1`：只许本机调用的路由（见下）对 nginx 放进来的所有人都有应答，`blocked_ips` 和
`allowed_networks` 谁也不拦，限流把所有访问者算成一个。写明代理和这个头，再给出 Web UI 前面
的代理层数（和 `trusted_proxy_hops` 是同一个数）；这样 Waitress 会自己把访问者的地址放进
`REMOTE_ADDR`：

```bash
waitress-serve --listen=127.0.0.1:8080 --threads=8 \
  --trusted-proxy=127.0.0.1 --trusted-proxy-headers=x-forwarded-for --trusted-proxy-count=1 \
  --call 'ai_intervention_agent.web_ui_wsgi:create_app'
```

Gunicorn 和 Flask 自带的 server 不会动这个头，不需要额外设置。

只许本机调用的路由按同一个地址判断：`POST /api/system/rotate-api-token`、
`GET /api/system/api-token-info`，以及没带有效 API token 时的
`POST /api/system/log-level`、`POST /api/system/open-config-file`、
`GET /api/system/open-config-file/info`。代理后面的访问者只有在代理写下的客户端地址是
回环地址时才算本机（例如你在服务器上自己打开页面）；其他人得到 `403`，设置页上的
“用 IDE 打开配置文件”按钮会置灰，并提示仅本机访问可用。要用它们请在服务器上执行，
例如 `curl http://127.0.0.1:8080/api/system/api-token-info`，或者对能用 token 的那三个
路由带上 API token。`trusted_proxy_hops = 0` 时经代理来的请求都算代理自己，也就是本机。

## 验证清单

把部署变更视为健康之前，先跑：

```bash
curl -i http://127.0.0.1:8080/api/system/health
curl -N http://127.0.0.1:8080/api/events
uv run pytest -q tests/test_web_ui_wsgi_profile_r452.py tests/test_sse_last_event_id_r41.py
```

放在代理后面时，还要从另一台机器（不是服务器本机）问一次：Web UI 必须能把你和它所在的机器分开。

```bash
curl -i http://<代理地址>/api/system/api-token-info
```

它必须答 `403`。答 `200` 说明 Web UI 把每个访问者都看成 `127.0.0.1`：头没写，或者被 server
删掉了（见上）。然后把这台机器的地址写进 `network_security.blocked_ips`（约 2 秒内生效）；
事件流也必须像其他路由一样拒绝它：

```bash
curl -i -m 3 http://<代理地址>/api/events
```

健康的流会立刻打印 `: connected`，之后空闲时每 25 秒一条 `event: heartbeat`。如果几秒内
连这条注释都没有出现，说明应用前面有东西在缓冲响应。

对于多浏览器标签的 heavy user，Web UI 在 `BroadcastChannel` 可用时会让同源标签页
共享一条 EventSource。这样能避开 MDN 记录的 HTTP/1.x 每浏览器 / 每域名 SSE 连接
上限，同时在 `BroadcastChannel` 不可用时仍回退到直连 SSE。

本 profile 的依据文档包括 Flask production deployment guide、Flask
Gunicorn/gevent 部署页、Waitress runner 参数页，以及 MDN 的 Server-Sent
Events 连接上限说明。
