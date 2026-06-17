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
    proxy_buffering off;
    proxy_cache off;
    proxy_read_timeout 1h;
}
```

如果把 Web UI 暴露到 loopback 之外，请尽量收窄
`network_security.allowed_networks`，可行时优先使用 SSH 隧道。运行中的设置 API
必须能 round-trip 已有通知配置，所以它不是经过 secret-redaction 的公开 API。

## 验证清单

把部署变更视为健康之前，先跑：

```bash
curl -i http://127.0.0.1:8080/api/system/health
curl -N http://127.0.0.1:8080/api/events
uv run pytest -q tests/test_web_ui_wsgi_profile_r452.py tests/test_sse_last_event_id_r41.py
```

对于多浏览器标签的 heavy user，Web UI 在 `BroadcastChannel` 可用时会让同源标签页
共享一条 EventSource。这样能避开 MDN 记录的 HTTP/1.x 每浏览器 / 每域名 SSE 连接
上限，同时在 `BroadcastChannel` 不可用时仍回退到直连 SSE。

本 profile 的依据文档包括 Flask production deployment guide、Flask
Gunicorn/gevent 部署页、Waitress runner 参数页，以及 MDN 的 Server-Sent
Events 连接上限说明。
