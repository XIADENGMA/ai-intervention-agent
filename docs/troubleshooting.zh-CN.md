# 故障排查（Troubleshooting）

> English version: [`troubleshooting.md`](troubleshooting.md)

针对最常见的部署 / 运行时问题的精简 FAQ。如果你的问题不在这里，
请参考 [`SUPPORT.md`](../SUPPORT.md) 选择合适渠道。

> 提示：拿到日志后绝大多数问题都能秒级定位。在 `config.toml` 里
> 设 `web_ui.log_level = "DEBUG"`（或独立 server 用环境变量
> `AI_INTERVENTION_AGENT_LOG_LEVEL=DEBUG`，VS Code 里把
> `ai-intervention-agent.logLevel` 改成 `debug`）。然后复现问题，
> 抓 stderr / Output 的**最后 20-30 行**。

## 1. Web UI 启动失败（端口被占用）

**症状**：MCP 工具调用一直挂起；VS Code Output 里出现
`Address already in use` 或 `Errno 48`；浏览器打不开
`http://127.0.0.1:8080`。

**原因**：默认端口 `8080`（`web_ui.port`）被其他进程占用。常见有：
之前残留的 `ai-intervention-agent` 进程、其他本地开发服务器、
开机时被某个系统服务抢占。

**修复**：

```bash
# 1. 杀掉残留 agent（macOS / Linux）：
pkill -f ai-intervention-agent || true
lsof -nP -iTCP:8080 -sTCP:LISTEN  # 确认端口已空闲

# 2. 或者改端口（编辑 config.toml）：
# [web_ui]
# port = 8181

# 3. 重启 AI 客户端（Cursor / VS Code），让 MCP 进程重新解析端口。
```

如果改了端口，VS Code 的 `ai-intervention-agent.serverUrl` 也要跟着
改（如 `http://localhost:8181`）。

## 2. VS Code 面板空白 / 一直 "Loading..."

**症状**：点活动栏的 AI Intervention Agent 图标，看到的是空 / 转圈。

**常见原因 + 修复**：

- **VS Code 访问不到 Web UI** —— 确认
  `ai-intervention-agent.serverUrl` 与实际 Web UI 地址一致。
  在浏览器里打开试试；浏览器都打不开就先解决问题 1。
- **MCP server 还没启动** —— 让 AI 调用一次任意 MCP 工具
  （比如 `interactive_feedback`），server 才会拉起 Web UI 子进程。
  面板每秒轮询，一旦 URL 通了大约 2 秒内就渲染。
- **Webview 静默崩溃** —— Output → "AI Intervention Agent" 应该
  打 5 行 boot 日志（`webview.resolve`、`webview.boot`、
  `webview.ready`、`webview.config_loaded`、
  `webview.first_task_rendered`）。如果断在哪一行，就说明哪个阶段
  挂了。
- **企业网络拦截** —— 公司 Zscaler / 终端安全软件偶尔会拦
  VS Code 发起的 `localhost` 请求。要么找 IT 加白，要么把
  `web_ui.host` 改成 `0.0.0.0` 走局域网 IP。

## 3. AI 调用了 `interactive_feedback` 后 Web UI 没看到任务

**症状**：AI 说"等你输入"，但 Web UI 任务列表空。

**排查顺序**：

1. **先刷一下页面** —— 任务出现，说明断网瞬间漏掉了 SSE 事件。
   升级到最新版；v1.5.x 已经支持基于 [`Last-Event-ID` 的 SSE 重放][sse]。
2. **确认 server 端任务队列状态** —— 跑
   `curl http://127.0.0.1:8080/api/tasks`，看任务是否在 server 端。
   有 → bug 在浏览器，清缓存硬刷新。
3. **MCP server 日志看 `Web service already running on a different port`**
   —— 父进程发现旧端口上还有遗留 Web UI，没启动新的。
   按问题 1 杀掉残留再试。

[sse]: https://html.spec.whatwg.org/multipage/server-sent-events.html#concept-event-stream-last-event-id

## 4. 通知没响（Web / 声音 / 系统 / Bark）

| 渠道 | 最常见原因 | 修复 |
| --- | --- | --- |
| **Web** | 浏览器 tab 在后台 + 系统拒绝授权 | 页面右上角铃铛 → "允许通知"。Safari 还要去 系统设置 → 通知 → Safari 单独允许。 |
| **声音** | `notifications.sound_mute = true` 或音量 0 | 设置页 → 声音 → 关闭"静音"，调高音量。iOS / iPadOS 需要每次会话至少把页面置前一次。 |
| **系统（plyer）** | macOS 缺 `pyobjus`（**有意跳过**） | macOS 通过 plyer 走的系统通知有意跳过；项目改用 `macos_native_enabled = true`（基于 `osascript`）。Linux 需要 `libnotify`；Windows 走 Toast。 |
| **Bark** | device key 错 / 推送服务不可达 / `bark_url` 没指向你自建实例 | 用 `curl -v "$BARK_URL/$DEVICE_KEY/test"` 单测。设 `bark_action = "url"` + `bark_url_template = "{base_url}/?task_id={task_id}"` 做点击直达。 |

## 5. mDNS（`ai.local`）局域网解析不出来

**症状**：手机 / 平板和电脑在同一 Wi-Fi，但打不开
`http://ai.local:8080`；走 `http://<电脑 IP>:8080` 是好的。

**原因**：

- **mDNS 只在绑定到非 loopback 接口时发布**。
  把 `web_ui.bind_interface` 改成局域网 IP（比如 `192.168.x.y`）
  或者 `0.0.0.0`，不能是 `127.0.0.1`。
- **macOS 休眠 / Wi-Fi 省电** 大约 5 分钟后会清掉 Bonjour 记录。
  要么 caffeinate 保持唤醒，要么手机刷一下页面 —— 通常重新解析
  是秒级的。
- **企业 / 酒店 Wi-Fi 屏蔽 multicast**。换个人热点，或者在设置页
  让它生成 IP 形式的 URL 二维码（`web_ui.host = "0.0.0.0"`
  之后会显示）。

## 6. "Open in IDE" 按钮没反应 / 开错了编辑器

**症状**：设置页点 "Open in IDE" 后无任何动静。

**为什么这么严**：这个端点强制三道 guard（见 `SECURITY.md`）：

1. **仅 loopback** —— 非 loopback 源直接 403。
2. **路径白名单** —— 只允许打开"当前生效配置文件" + `config.toml.default`，
   绝对不接受任意路径。
3. **编辑器优先级**：`AI_INTERVENTION_AGENT_OPEN_WITH` 环境变量 →
   请求体里的 `editor` 字段 → 自动探测链
   （cursor / code / windsurf / subl / webstorm / pycharm）→
   系统默认 opener（`open` / `xdg-open` / `start`）。

**修复**：

```bash
# 1. 确认 PATH 上至少有一个编辑器：
which cursor code  # 至少一条要解析得出

# 2. 强制指定编辑器：
export AI_INTERVENTION_AGENT_OPEN_WITH=cursor

# 3. 重启 MCP server，让环境变量被继承。
```

## 7. PWA "安装" / "添加到主屏幕" 不出现

**症状**：在 Chrome / Edge / Safari 打开 Web UI，但没看到"安装"提示。

**Checklist**：

- PWA install prompt 要求 **HTTPS 或 `localhost`**。
  局域网走纯 HTTP `http://192.168.x.y:8080` 在现代浏览器永远不会
  触发；iOS Safari 最宽松但仍然要用户主动 "添加到主屏幕"。
- 确认 manifest 可访问：
  `curl http://127.0.0.1:8080/manifest.webmanifest` 应该返回
  JSON，包含 `start_url`、`icons`、`display: standalone`。
- iOS 用户：`分享` → `添加到主屏幕` 是稳定可用的兜底，不依赖
  浏览器的安装横幅启发。

## 8. 本地 CI Gate 挂了，但 GitHub Actions 是绿的（或反过来）

**症状**：`uv run python scripts/ci_gate.py` 在本地挂，CI 没复现；或反过来。

**最常见原因**：

- **uv 锁文件漂移** —— 本地 `uv.lock` 旧了。`uv sync --all-groups`
  对齐。CI 用 `--frozen`；锁不一致会显示
  `Locked dependency not found` 或传递依赖版本错位。
- **fnm 与系统 Node 冲突** —— i18n red-team smoke 检查跑 Node。
  CI 锁 `v24`；本地 `node --version` 可能不一样。可以用
  `fnm exec --using v24.14.0 -- npm run vscode:check` 强制
  使用对齐版本。
- **时区敏感测试** ——
  `tests/test_i18n_relative_time_thresholds.py` 用本地时区算
  "x 分钟前"。用
  `TZ=UTC uv run pytest tests/test_i18n_relative_time_thresholds.py`
  二分。

以上都不解释，把完整输出贴上来开 [bug report][bug]，标题前缀
`[ci]`。

[bug]: https://github.com/xiadengma/ai-intervention-agent/issues/new?template=bug_report.yml

## 还是没解决？

1. 看 [`SUPPORT.md`](../SUPPORT.md) 选合适渠道。
2. 安全相关症状**不要**开公开 issue，按
   [`SECURITY.md`](../SECURITY.md) 走私有公告。
3. 不确定是 bug、配置、还是环境问题，就开
   [GitHub Discussion][disc]。

[disc]: https://github.com/xiadengma/ai-intervention-agent/discussions
