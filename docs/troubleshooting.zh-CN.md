# 故障排查（Troubleshooting）

> English version: [`troubleshooting.md`](troubleshooting.md)

针对最常见的部署 / 运行时问题的精简 FAQ。如果你的问题不在这里，
请参考 [`SUPPORT.zh-CN.md`](../.github/SUPPORT.zh-CN.md) 选择合适渠道。

> 提示：拿到日志后绝大多数问题都能秒级定位。在 `config.toml` 里
> 设 `web_ui.log_level = "DEBUG"`（或用环境变量
> `AI_INTERVENTION_AGENT_LOG_LEVEL=DEBUG`，它优先于配置文件）并重启
> MCP 服务端；VS Code 里则把 `ai-intervention-agent.logLevel` 改成
> `debug`。然后复现问题，抓 stderr / Output 的**最后 20-30 行**。

## 1. Web UI 启动失败（端口被占用）

**症状**：agent 一直拿到重调提示、始终没有问题弹出来（工具几秒内就返回，
不会等你）；MCP 日志里出现
`端口 127.0.0.1:8080 已被占用（health-check 未识别为本服务）`（错误码
`port_in_use`），或者 Web UI 日志里出现 `Address already in use` /
`Errno 48`；浏览器打不开 `http://127.0.0.1:8080`。

**原因**：默认端口 `8080`（`web_ui.port`）被其他进程占用。常见有：
之前残留的 `ai-intervention-agent` 进程、其他本地开发服务器、
开机时被某个系统服务抢占。

**修复**（按速度从快到慢）：

```bash
# 方案 A —— 临时换端口（不动 config.toml，重启 IDE 即可生效）
#
# 下次 MCP server 启动时立刻命中新端口。当前 shell session 内一直有效，
# 登出后失效，适合"先用着、回头再改 config.toml"的场景。
export AI_INTERVENTION_AGENT_WEB_UI_PORT=8181
# 重启 AI 客户端（Cursor / VS Code），让 MCP 进程重新读 env var。
# 详见 docs/configuration.zh-CN.md#环境变量覆盖。

# 方案 B —— 永久换端口（编辑 config.toml）
#
# 找配置文件位置：
#   ai-intervention-agent --help  # 看版本 / 二进制路径
#   uvx ai-intervention-agent     # 启动 banner 含 "config_file_path=..."
#
# 然后编辑：
#   [web_ui]
#   port = 8181

# 方案 C —— 不换端口，把占用进程腾出来
pkill -f ai-intervention-agent || true
lsof -nP -iTCP:8080 -sTCP:LISTEN  # 确认端口已空闲
```

如果改了端口（方案 A 或 B），VS Code 的 `ai-intervention-agent.serverUrl`
也要跟着改（如 `http://localhost:8181`）。

## 2. VS Code 面板空白 / 一直 "Loading..."

**症状**：点活动栏的 AI Intervention Agent 图标，看到的是空 / 转圈。

**常见原因 + 修复**：

- **VS Code 访问不到 Web UI** —— 确认
  `ai-intervention-agent.serverUrl` 与实际 Web UI 地址一致。
  在浏览器里打开试试；浏览器都打不开就先解决问题 1。
- **MCP server 还没启动** —— 让 AI 调用一次任意 MCP 工具
  （比如 `interactive_feedback`），server 才会拉起 Web UI 子进程。
  面板每秒轮询，一旦 URL 通了大约 2 秒内就渲染。
- **面板里的脚本没有启动** —— 打开 Output → "AI Intervention Agent"。面板
  正常时，脚本跑起来后会记录一行 `event=webview.ready`。如果面板可见、脚本却在
  2.5 秒内没有报告就绪，扩展会以 `WARN` 级别记录 `event=webview.ready_timeout`；
  它的 `reason` 字段说明计时从何而来（面板被隐藏后再次显示是 `shown`，服务器地址
  变化后是 `serverUrl_changed`，首次加载没有 `reason`）。面板处于隐藏状态时不会
  告警，再次显示时重新计时。常见原因是脚本被页面拦截（CSP）或 HTML 没有加载出来；
  **Developer: Open Webview Developer Tools** 可以查看面板的控制台。
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

| 渠道              | 最常见原因                                                   | 修复                                                                                                                                                                                                                                                                                                                                                                                                                                         |
| ----------------- | ------------------------------------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Web**           | 浏览器 tab 在后台 + 系统拒绝授权                             | 页面右上角铃铛 → "允许通知"。Safari 还要去 系统设置 → 通知 → Safari 单独允许。                                                                                                                                                                                                                                                                                                                                                               |
| **声音**          | `notification.sound_mute = true` 或音量 0                   | 设置页 → 声音 → 关闭"静音"，调高音量。iOS / iPadOS 需要每次会话至少把页面置前一次。                                                                                                                                                                                                                                                                                                                                                          |
| **系统（plyer）** | `system_enabled = false`（默认）或 macOS 缺 `pyobjus`        | 在 `[notification]` 里设置 `system_enabled = true`。macOS 通过 plyer 走的系统通知有意跳过；项目改用 `macos_native_enabled = true`（基于 `osascript`）。Linux 需要 `libnotify`；Windows 走 Toast。                                                                                                                                                                                                                                            |
| **Bark**          | device key 错 / 推送服务不可达 / `bark_url` 没指向你自建实例 | 用 `curl -v "$BARK_URL/$DEVICE_KEY/test"` 单测。设 `bark_action = "url"` + `bark_url_template = "{base_url}/?task_id={task_id}"` 做点击直达。**如果解析出来的 URL 是 loopback 地址**（`localhost` / `127.x.x.x` / `::1`），agent 现在会在服务端直接过滤——手机不会再收到一个无法点击打开的 URL；同时 Web UI 的 Bark 设置面板会推荐对应的 LAN IP（`http://<lan-ip>:<port>`）让你一键复制并写入 `web_ui.external_base_url`（或开 mDNS）后重试。 |

**代理环境下的 Bark。** Bark 推送直接发往 `bark_url`：不读 `HTTP_PROXY`、`HTTPS_PROXY`、`ALL_PROXY`（大小写都不读）和操作系统里的代理设置，也没有代理选项。所以，如果在设了代理变量的终端里 `curl -v "$BARK_URL/$DEVICE_KEY/test"` 能通、推送却始终没到，原因就是推送没有走代理。网络只能通过代理访问外网时，在应用之下接管流量（VPN 或 TUN 模式的代理、透明代理），或者把 `bark_url` 指向你的网络能直连的 Bark 服务器。

## 5. mDNS（`ai.local`）局域网解析不出来

**症状**：手机 / 平板和电脑在同一 Wi-Fi，但打不开
`http://ai.local:8080`；走 `http://<电脑 IP>:8080` 是好的。

**原因**：

- **mDNS 只在绑定到非 loopback 接口时发布**。
  把 `network_security.bind_interface` 改成局域网 IP（比如 `192.168.x.y`）
  或者 `0.0.0.0`，不能是 `127.0.0.1`。（`bind_interface` 配置项在
  `[network_security]` section 下，不是 `[web_ui]` —— 它在运行时会
  覆盖 `web_ui.host`。）
- **macOS 休眠 / Wi-Fi 省电** 大约 5 分钟后会清掉 Bonjour 记录。
  要么 caffeinate 保持唤醒，要么手机刷一下页面 —— 通常重新解析
  是秒级的。
- **企业 / 酒店 Wi-Fi 屏蔽 multicast**。换个人热点，或者在设置页
  让它生成 IP 形式的 URL 二维码（`web_ui.host = "0.0.0.0"`
  之后会显示）。

## 6. "Open in IDE" 按钮没反应 / 开错了编辑器

**症状**：设置页点 "Open in IDE" 后无任何动静。

**为什么这么严**：这个端点强制三道 guard（见 `.github/SECURITY.zh-CN.md`）：

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
- 主屏幕图标带黑边，或更新后仍是旧图：iOS 在创建快捷方式的那一刻
  就把图标存下来了，修复之前创建的快捷方式会一直保留旧图。删除后
  重新添加即可。想确认服务端给出的是什么，运行
  `curl -s http://127.0.0.1:8080/ | grep -A2 apple-touch-icon`，再
  打开它打印出的 `/icons/apple-touch-icon.png?...`：应该是一块没有
  黑色边框的浅色方块。

## 8. 在手机上点 Bark 通知，打开的是 Bark App 而不是 PWA

**症状**：手机收到了 Bark 推送，但是点开后停在 Bark 主页 / 提示"未配置 URL"，没有跳进 AI Intervention Agent 的反馈页。

**原因**（基本就这两种）：

1. **推送负载里没有 `url` 字段** —— agent 检测到生成的 URL 是 loopback 地址后主动剥离了（`bark-r42` 引入）。loopback URL 从手机视角根本走不回你电脑的 `localhost`，发了也是死链。
2. **`bark_action` 没设成 `"url"`** —— `bark_action = "default"` 是"点开后即关闭通知"；只有 `"url"`（或者直接写一个 http/https 完整 URL）才会让 Bark App 真正去 deep-link。

**修复**：

1. 打开 Web UI（或 VS Code 插件）→ **设置 → 通知 → Bark**。URL 模板下方新增的诊断面板会展示其中之一：
   - `OK：点击目标 = http://<你的 LAN IP>:<端口>` → 一切正常，AI client 那边重试。
   - `检测到 loopback —— 手机无法访问 <url>` + 一个 "复制 LAN URL" 按钮。点一下复制，粘贴到 `web_ui.external_base_url`，保存后重试。
   - `未检测到 LAN IP` → 你机器离线 / 只在 VPN 里。换到 LAN-bound 的 Wi-Fi 或者用 mDNS `<host>.local`。
2. （可选）用 `curl http://127.0.0.1:<端口>/api/system/network-base-url-status` 验证 —— 返回里的 `recommendation` 字段告诉你具体要调哪一个：`ok` / `configure_external_base_url` / `bind_lan_interface`。

> 注意：`0.0.0.0` **不是**合法的 `external_base_url` —— 它是服务端的"绑定到所有接口"通配符，从手机视角是无意义地址。诊断面板会用同一条 loopback 警告把它驳回。

## 9. 本地 CI Gate 挂了，但 GitHub Actions 是绿的（或反过来）

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

## 10. 每个 PR 上的 `Dependency Review` 检查都报 "not supported on this repository"

**症状**：每一个 PR（包括 dependabot 自动 PR）的 `Dependency Review`
工作流都失败，日志里能看到这一行：

```
##[error]Dependency review is not supported on this repository.
Please ensure that Dependency graph is enabled, see
https://github.com/<owner>/<repo>/settings/security_analysis
```

其他 CI（`Tests`、`VSCode`、`CodeQL`、`actionlint`）可能全绿，
**只有 `Dependency Review`** 是红的。

**根因**：GitHub `actions/dependency-review-action` 依赖仓库的
**Dependency graph** 功能。Dependency graph 在 **public** 仓库默认开启，
但 **private** 仓库和 fork 默认关闭。如果仓库刚从 private 切到 public、
或者你在 fork 上跑 workflow，这个开关可能没启用。

**修复**（一次性，仓库 owner 操作）：

1. 进入 `Settings` → `Code security`（或 `Security & analysis`，
   取决于 GitHub 版本）。
2. 在 **Dependency graph** 下点 **Enable**。同时可以一起启用
   `Dependabot alerts` 和 `Dependabot security updates`。
3. 回到 PR 的 `Checks` 选项卡，重跑失败的 `Dependency Review` job —
   1 分钟内应该变绿。

**用 API 验证**（不点 UI）：

```bash
gh api repos/<owner>/<repo>/vulnerability-alerts -i
# 204 No Content → vulnerability alerts（含 dependency graph）已开
# 404 Not Found  → 未开 — `Dependency Review` 会一直失败
```

启用之前，`Dependency Review` 的红灯纯属基础设施问题，**不代表**
PR 依赖里真的有漏洞或 license 问题。

## 11. Cursor 报 "Extension host terminated unexpectedly 3 times within the last 5 minutes"

**症状**：Cursor 弹出横幅
`Extension host terminated unexpectedly 3 times within the last 5
minutes.`。有时还伴随原本配的中文界面被重置成英文；有时只在
`interactive_feedback` 等待人类回复期间出现。

**重要的上游背景**：这是 **Cursor IDE 自身的已知问题**，不一定由
ai-intervention-agent 触发。[Cursor 社区论坛同主题][cursor-ext-host]
有大量用户报告 Cursor 2.4.14 及更早版本即使**禁用所有插件也会出现
同样的横幅**。"语言被重置"也是 Cursor extension host 重启的副作用
（host 重启后 language picker 会重读默认值）。

[cursor-ext-host]: https://forum.cursor.com/t/how-to-recover-from-extension-host-terminated-unexpectedly-3-times/148772

**本项目侧已有的防御措施（所以横幅大概率不是我们的锅）**：

- MCP `interactive_feedback` 工具**忽略**调用方传入的
  `timeout` / `timeout_seconds` 参数，所以不会出现"timeout 太小直接
  超时"的回归（`timeout=1` 是 mcp-feedback-enhanced 那条 issue 里的
  典型坑，本项目从设计上不会踩中）。
- `wait_for_task_completion` 用 `max(timeout, server_config.BACKEND_MIN=260)`
  和 `calculate_backend_timeout` 钳位 backend 等待时长。
- `server.py::main()` 把 MCP 主循环包在 3 次重试 + `cleanup_services()`
  - `KeyboardInterrupt` 优雅退出的 harness 里。
- R114（通知管理器）已经把 atexit / shutdown TOCTOU race 静默化，
  老版本会在 host restart 期间打 `ERROR: 处理通知事件失败` 噪声日志，
  容易被误判成 MCP 端故障；新版本不会再出。

如果横幅出现前，Cursor / VS Code 主日志里有
`extensionHost crashed with code 9 and reason 'killed'`，说明扩展宿主是
被外部用 `SIGKILL` 结束的，请看下面第 14 节，按它的步骤判定这次 kill 的来源。

**排查顺序**：

1. **先确认是不是 MCP server 的事**。在 Cursor 里打开 MCP server 面板
   （列出 `ai-intervention-agent` 等所有 MCP server 那个面板），
   连接灯应该是**绿的**。横幅出现期间灯一直绿，那 crash 在 Cursor 的
   其他扩展上，下面的工作流照样适用。
2. **先用 Cursor 自带的恢复机制**。`Cmd/Ctrl+Shift+P` →
   `Developer: Restart Extension Host`。如果横幅停了，说明是瞬态状态。
3. **升级 Cursor**。论坛主题里跟踪了 2.4.14 之后的一系列修复，
   升级是单步杠杆最大的动作。
4. **看 MCP server 日志确认我们这边干净**。把 `web_ui.log_level`
   设成 `"DEBUG"`，在 stderr 里找：
   - `处理通知事件失败` ERROR 行 → 在最新版本（R114 之后）还出现的话，
     麻烦带上日志开个 [issue][bug]。
   - `[R114] _executor.submit 与 shutdown 竞态` DEBUG 行 → 这条是
     **预期**的 shutdown / restart 路径，可以忽略；它就是老版本
     ERROR 在 R114 之后的静默版。
5. **如果横幅只在** `interactive_feedback` **正在阻塞等你回复时弹出**，
   就是长轮询（默认 `frontend_countdown=240s` + `BACKEND_BUFFER=40s`
   ≈ 280s 等待）撞 Cursor extension host 的 watchdog。截止 Cursor
   2.4.14 没有公开文档化的 MCP server 端 watchdog 延长开关，实际
   绕开方法是把 Web UI / VS Code 面板放在前台、在倒计时之内回复。

如果以上都试过、横幅仍稳定复现、MCP 日志干净，请把
`ai-intervention-agent` 版本和
`Help → Toggle Developer Tools → Console` 里的 trace 一起开
[Cursor bug 跟踪 issue][cursor-bugs]，并在我们这边的
[GitHub Discussion][disc] 里反向引用一下，让我们能镜像跟踪上游进展。

[cursor-bugs]: https://forum.cursor.com/c/bug-report/6
[disc]: https://github.com/xiadengma/ai-intervention-agent/discussions

## 12. Open VSX 发布步骤失败（`displayName` 不一致 / 锁定的 `ovsx` 升级）

**症状**

Release workflow 的 `open-vsx` job 退出，错误信息形如：

```
ERROR: Display name in extension.vsixmanifest and package.json does not match.
ERROR: Description in extension.vsixmanifest and package.json does not match.
ERROR: Categories in extension.vsixmanifest and package.json do not match.
```

—— 通常**只有** Open VSX job 报错；打包同一份 VSIX 的 `build` job
是通过的。

### 为什么会这样

`ovsx publish` 服务端校验器严格比较 `package.json`（NLS 占位符**未**
解析）和 VSIX 内 `extension.vsixmanifest` 的字符串字段。NLS 占位符
（如 `"%displayName%"`）在 `ovsx` 看来就是字面量字符串，不会展开后再
比对——因此与 VSIX manifest 内被构建工具展开的字面值（如
`"AI Intervention Agent"`）必然不等。Open VSX 从约 2026-05 起严格
执行这个比对。

历史上这个问题坑过 v1.6.1 —— 详情见
[`CHANGELOG.md`](../CHANGELOG.md#162--2026-05-10) —— 当时 `npx --yes
ovsx publish` 用的是浮动版本，v1.6.0（2026-05-08）发布时还能跑
通，v1.6.1（2026-05-10）同一份代码因为上游 ovsx 在两天间收紧了校验
规则就 fail 了。我们这边没改一行代码。

### 修复 1 级 —— 字面量对齐

把 `packages/vscode/package.json` 里出问题的字段从 `"%占位符键%"` 改
成字面字符串：

```diff
- "displayName": "%displayName%",
+ "displayName": "AI Intervention Agent",
```

`displayName` 是 ASCII / 拉丁字符，本来就没用国际化的必要；其它真
的需要按 locale 切换的字段（`activitybar.title`、`views.title`、
`commands.title` 等）继续保留 NLS 占位符不动。

防回归测试见
[`tests/test_vscode_displayname_literal_for_ovsx.py`](../tests/test_vscode_displayname_literal_for_ovsx.py)
—— 把 `displayName` 锁成字面量，并要求 NLS bundle 的 zh-CN / en
两套同步对齐，下次再有人无意间换回占位符 CI 直接红，不等到 release
tag。

### 修复 2 级 —— 锁工具链版本（R149）

光把内容字面量化还不够：万一未来某次 `ovsx` 又收紧校验，浮动 tag
仍然能在我们没改一行代码的情况下让 release 红。R149 在
`.github/workflows/release.yml` 里把两处 `ovsx` 调用都钉死到具体版
本：

```yaml
- name: 发布到 Open VSX（从 VSIX 发布）
  run: |
    npx --yes ovsx@0.10.9 verify-pat xiadengma -p "$OVSX_TOKEN"
    npx --yes ovsx@0.10.9 publish -p "$OVSX_TOKEN" vsix/*.vsix
```

[`tests/test_release_workflow_ovsx_pinned_r149.py`](../tests/test_release_workflow_ovsx_pinned_r149.py)
强制：禁止 `npx --yes ovsx publish` / `verify-pat` 浮动调用、必须用
严格 semver、`verify-pat` 与 `publish` 两行的版本必须一致、附近必
须有解释 R149 历史的注释。

### 升级钉死的 `ovsx` 版本（手动流程）

工具链升级走 PR，不让浮动 tag 偷偷漂移：

1. **先用 dry VSIX 在临时仓库验证新版本。**

   ```sh
   git clone --depth 1 https://github.com/xiadengma/ai-intervention-agent
   cd ai-intervention-agent/packages/vscode
   npm ci
   npm run build:vscode      # 产出 dist/vsix/*.vsix
   npx --yes ovsx@<新版>.<x>.<y> verify-pat xiadengma -p "$YOUR_OVSX_PAT"
   ```

   `verify-pat` 通过 → 新版接受现有 PAT 格式，可继续。

2. **`release.yml` 两行同步 bump。** 两行 `ovsx@<X.Y.Z>` 必须完全
   一致；matching-pins 测试（`test_publish_and_verify_use_same_pin`）
   会兜底。

3. **拿一个牺牲 tag 跑 release 验证**（例如打一个 `vX.Y.Z-rc1`，推
   上去看 workflow 结果）。新版接受现有 VSIX → 下一个 PATCH / MINOR
   release 正式上；新版还是拒绝 → 回滚到上一个能 work 的 pin，并去
   [`eclipse-openvsx/cli`](https://github.com/eclipse/openvsx/issues)
   开 upstream issue。

4. **`release.yml` 注释更新**，让未来的维护者能看到每次 pin 是什么
   时候验证过的：

   ```yaml
   # R149 —— pin ovsx version. <YYYY-MM-DD> 验证升到 <新版>.<x>.<y>
   #     after <upstream changelog link>。
   ```

5. **本节文档同步更新**至当前 pin 的版本号。

> **注意** —— `npx --yes ovsx@latest` 在 CI 里**永远不对**，哪怕只
> 是临时也不行；那就是 v1.6.1 失败的根因。如果当前 pin 的 ovsx 有
> 已知 bug 阻塞 release，回滚到**上一个**能 work 的 pin（在 `git log
release.yml` 里找），不要走浮动。

## 13. 后端 `/api/system/*` payload 字段稳定性（R154 教训，feat-remove-test 后）

> **状态说明（feat-remove-test）** —— 这些 endpoint 原本的 UI 消费者
> （设置页"发送系统自检通知"按钮 + "活动面板"）已经**移除**；R154
> 客户端契约（`activity_dashboard.js`）以及 in-suite 的
> `test_system_endpoint_payload_contract_r154.py` 也在同周期 prune。
> **教训本身仍然适用** —— 只是消费者重新定位到剩余的"非 UI"消费者
> （CI 烟测、Prometheus exporter、k8s liveness probe、ad-hoc curl 调试），
> 而不再针对 in-app UI 指示器。

**症状** —— 监控面板某一行、CI 断言、或 `curl | jq` 管道一直显示
"stale" / "—" / 缺字段，但 endpoint 实际返回 200 + 合法 JSON。

- `curl /api/system/recent-logs | jq '.entries | length'` 返回 `null`
  （实际读成了 `.logs`）。
- `curl /api/system/health | jq '.checks.notification.status'` 返回
  `undefined`（字段被悄悄重命名）。
- Prometheus exporter 抓不到 per-provider streak 指标，尽管 JSON
  里明明有。

**根因** —— 服务端 endpoint 改了顶层 JSON 字段名（例如
`entries → logs`、`stats → counters`），或者消费者读取的字段名跟
服务端发出的不一致。fetch 成功、JSON 解析正常，但消费者读到 `undefined`，
就当成"无数据"处理。

R152 的 `_formatLogs` 写的是 `var entries = logs.logs`，而服务端
一直在 `entries` 字段下发数组。在 R153 抓到并修复之前，Dashboard
的"近期日志"行在生产环境一直处于 stale 状态。即使 UI 消费者被
移除，**同一类 bug 也不会消失** —— 每个 off-process 消费者都有
同样的脆性。

**怀疑漂移时怎么处理**

1. **抓 live payload**：
   `curl -s http://localhost:8080/api/system/<endpoint> | jq`，然后
   把顶层 keys 跟你的消费者（CI 测试、监控 scrape config、Grafana
   dashboard JSON）实际读取的字段名逐个对照。
2. **沿 view function 历史 diff**：受影响的 route view function
   （在 `web_ui_routes/system.py` / `web_ui_routes/notification.py`）
   的 commit message 通常会标注字段重命名 —— `git log --follow -p`
   能把变更面摊开。
3. **在你的消费者侧测试套件**里**结构化 pin 该字段**（CI 烟测 /
   监控 config schema 测试），让下次服务端重命名先在你这里红，
   再传播到生产。

**未来如何避免** —— 把每个 endpoint 的顶层字段名当成**公开** API
合约的一部分 —— 即便没有 in-app UI 消费者，off-process 消费者也
依赖它。重命名必须：

- 同步更新 route 的 inline docstring（这样 `docs/api*/` 重生成时
  能抓到）；
- 如果是破坏性重命名，bump 一个 documented API version note；
- 理想情况下伴随一段 deprecation alias 期。

**不要**因为"已经没有 UI 消费者了，可以随便改名"就 ship —— in-app
消费者缺席会让静默回归**更难**、而非更容易被发现。UI 面板掉成 "—"
是显式的；CI scrape job 静默掉成 0 metric 才是真坑。

## 14. 日志里出现 `extensionHost crashed with code 9 and reason 'killed'`

**症状**：Cursor / VS Code 主日志里出现成对的两行

```log
[error] [UtilityProcess id: 20, type: extensionHost, pid: 65757]: crashed with code 9 and reason 'killed'
[info] Extension host with pid 65756 exited with code: 9, signal: unknown.
```

随后所有扩展（包括本扩展）一起重启，且之前没有任何扩展自己的报错。

**这意味着什么**：退出码 9 就是 `SIGKILL`。扩展宿主不是自己出错退出的，而是被外部结束的。macOS 上常见的发送方有：内存压力清理（jetsam）、内核因某进程耗尽 Mach 端口而杀掉它（[macOS 26 + VS Code / Electron 上已知的一类故障][vscode-326338]：先是子进程风暴，随后出现 `spawn EBADF` / `EMFILE`，最后渲染进程或扩展宿主被杀）、或者别的工具执行了 `kill -9`。本扩展不可能产生这个信号：代码里没有任何对宿主发信号的路径，宿主侧的资源行为也在真实 VS Code 扩展宿主里测试过（R718：有界的 SSE 缓冲、重连退避、释放 HTTP 响应体，并且在抖动 / 事件风暴 / 错误响应体的故障注入下没有泄漏 socket 或堆）。

[vscode-326338]: https://github.com/microsoft/vscode/issues/326338

**排查顺序（macOS，崩溃后尽快做）**：

1. 先判断是哪一类 kill。请使用完整路径，因为裸的 `log` 在 zsh 里是内建命令：

   ```bash
   /usr/bin/log show --last 30m \
     --predicate 'eventMessage CONTAINS "FATAL exception" OR eventMessage CONTAINS "exiting with signal 9"' \
     | grep -iE "code helper|cursor helper"
   ls -lt /Library/Logs/DiagnosticReports/JetsamEvent-*.ips | head
   ```

   - 崩溃时间附近出现 `JetsamEvent`，且其中最大的进程**不是**编辑器：这是整机内存压力，关闭它列出的大户应用或虚拟机。
   - 出现 `FATAL exception ... EXC_RESOURCE` 行，或崩溃前不久 Extension Host 输出里有 `spawn EBADF` / `EMFILE`：这是资源耗尽。上游报告里的触发条件是自定义的 `files.watcherExclude` **替换**了 VS Code 的默认值（于是 `node_modules` 被监听，内置 Git 扩展为每个嵌套仓库派生子进程）。请改成在默认值之上追加，并考虑 `git.autofetch = false` 与 `git.autoRepositoryDetection = "openEditors"`。
   - 所有 Cursor / VS Code 进程（渲染进程、文件监听、pty host）在同一瞬间都以 code 9 退出，同样指向整机内存压力，而不是某一个扩展。
2. 升级 Cursor / VS Code，然后用 `cursor --disable-extensions` 重试。禁用所有扩展后仍被 kill，就不是本扩展的问题。
3. 用本扩展自己的日志排除它：打开 **输出 → AI Intervention Agent**。出现 `sse.buffer_overflow` 警告说明服务端发来了超过 1 MiB 的单行或单个 SSE 事件；这是有意丢弃连接并按退避重连。

如果仍能复现，请开一个 [issue][bug]，附上崩溃时间、第 1 步里的 `JetsamEvent` / `FATAL exception` 行，以及 **AI Intervention Agent** 的输出。

## 15. 侧边栏面板打开或重新加载很慢

**症状**：Cursor / VS Code 启动后，或切回 AI Intervention Agent 侧边栏时，面板空白或停在加载骨架屏上很久；或者带长代码块的提示词要过一会儿才显示。

**各阶段分别耗时多少**（在真实的 VS Code 1.110.0 扩展宿主里测得，并只读地观察了一个运行中的 Cursor；取热启动多次测量的中位数，Apple 芯片 Mac）：

- **编辑器创建 webview（仅冷启动）：在测量的那次 Cursor 会话里约 1 秒。** 编辑器先构建 webview 框架并注册它的 service worker，之后才会请求扩展的页面，此时扩展自己的代码还没有运行，扩展无法缩短这一段。
- **扩展自身的工作，从写入 HTML 到内容上屏：VS Code 1.110 约 60 毫秒，Cursor 约 90 毫秒。** 页面 59 KB，脚本从本地文件同步加载。
- **隐藏后再次显示侧边栏：恢复内容约 55 毫秒。** 默认会用页面通过 `setState` 保存的状态重建 webview。`ai-intervention-agent.webview.retainContextWhenHidden` 可让它一直保留（约 25 毫秒），代价是更多内存；默认关闭是有意为之（R452）。
- **带长代码块的提示词：一个 52 KB、含 12 000 个高亮 token 的提示词首次渲染约 110 毫秒（R719 之前是 259 毫秒）。** 代码由服务端高亮（同样大小的提示词首次请求约 70 毫秒，之后走缓存）。

**排查顺序**：

1. 打开 **输出 → AI Intervention Agent**，对比 `event=webview.ready` 的时间戳与你打开面板的时刻。这里出现间隔，是编辑器在创建 webview，而不是扩展慢。
2. 运行 **Developer: Open Webview Developer Tools** 并查看控制台。普通提示词不应该打印 `Refused to apply inline style because it violates the following Content Security Policy directive`：每一条都是浏览器要生成的一个违规事件，R719 保证扩展自己的标记里没有这类内联样式。如果看到很多，请开 issue 并描述提示词的形态。
3. 想用数据代替感觉：打开探针启动编辑器，把侧边栏隐藏再显示几次，然后在本仓库的检出目录里汇总结果文件：

   ```bash
   AIIA_WEBVIEW_BENCH_OUTPUT=/tmp/aiia-webview.ndjson cursor .
   npm run vscode:webview-bench -- --input /tmp/aiia-webview.ndjson
   ```

4. 只有长提示词慢：给面板为当前任务发出的请求计时（服务端负责渲染并缓存 Markdown）：`curl -s -o /dev/null -w '%{time_total}\n' http://localhost:8081/api/config`。

如果仍然觉得慢，请开一个 [issue][bug]，附上探针汇总、编辑器及其版本，并说明是启动后的第一次打开慢，还是每次重新显示都慢。

## 16. Cursor 把服务器标成 "Needs Authentication"，或工具列表里多出一个 `mcp_auth`

**症状**：Cursor 的 MCP 列表里这个服务器显示 **Needs Authentication**，或者 agent 拿到的该服务器工具列表里多了一个 `mcp_auth` 工具（"Authenticate this MCP server so its tools can be used"）。

**含义**：本服务器从不要求认证。它是本地 stdio 进程（`uvx ai-intervention-agent`），Cursor 与它之间没有任何登录，`~/.cursor/mcp.json` 里它的条目也不需要 `headers`、`auth` 或 token；Web UI 同样没有登录页。这两个现象都来自 Cursor 对所有 MCP 服务器一视同仁的处理（依据 Cursor 3.26 读到的行为）：

- Cursor 会在给 agent 构造的工具列表里加一个虚拟的 `mcp_auth` 工具。服务器没有定义它，也无法关掉它。只有当某个服务器被标记为需要认证时，agent 才应该调用它。
- 当对服务器的某次请求失败、且错误文本里含 `unauthorized` 或数字 `401` 时，Cursor 会把该服务器标为需要认证。这只是文本匹配，stdio 服务器同样适用，所以转述自其他程序的消息（例如别的程序占用了 Web UI 端口并返回 `401`）也可能触发。

**排查顺序**：

1. 打开 **输出 → MCP Logs**，或 macOS 上的 `~/Library/Application Support/Cursor/logs/<session>/mcp-server-user-<name>.log`（`<name>` 是 `mcp.json` 里的键名，例如 `ai-intervention-agent`），在标签出现的时间点附近搜索 `401` 或 `unauthorized`。那一行会指出是哪次调用失败。
2. 如果是别的程序占着 Web UI 端口并在响应，腾出端口或修改 `web_ui.port`（第 1 节）。
3. 执行 **Developer: Reload Window**，或在 Cursor 的 MCP 设置里把该服务器关掉再打开以重新连接。之后某次工具调用拿到应答时，标签也会自行消失；如果它反复出现，原因就是第 1 步日志里的那一行。

Web UI 里的“访问被拒绝”提示是另一回事：它表示页面请求被服务器（或前面的代理）以 401 或 403 拒绝。请检查 `config.toml` 里的 `network_security.allowed_networks` 与 `blocked_ips`。

## 17. 提示词里的本地图片被替换成“图片未显示”说明，或显示为破图

**症状**：agent 在消息里写了 `![shot](path/to/shot.png)`，但反馈页面显示的是一行说明（例如 🖼️ *(image not shown: outside the allowed folders)*）而不是图片，或者是一个破图图标。

**原理**：MCP 服务端与文件在同一台机器上，所以由它读取图片并把字节随任务一起发送；Web UI 自己从不按路径打开文件。无法显示的引用会被替换成一行说明，并写明原因：

- `outside the allowed folders`：文件不在 MCP 客户端上报的工作区目录、系统临时目录或 `[feedback] local_image_dirs` 列出的目录之内。把文件移动或复制进工作区，或把它所在目录加进该列表。`..` 以及指向允许目录之外的符号链接都算作目录之外。
- `file not found`：路径不存在。相对路径按工作区目录解析；`~` 是你的主目录。
- `not a png, jpg, gif, webp, bmp or avif image`：SVG、ICO、HEIC 等格式一律拒绝，文件头与扩展名不符的文件也会被拒绝。
- `too large (max 8 MB each, 16 MB per prompt)`、`more than 8 images in one prompt`、`cannot be read`：限制与权限见 [`configuration.zh-CN.md`](configuration.zh-CN.md)。

**只有破图图标、没有说明**，说明这个引用根本没有经过 MCP 服务端：

- `local_image_dirs = []` 会关闭该功能，引用保持原样。
- 目标是远程（`https:`）或 `data:` 地址：这类地址不会被处理，由浏览器自己加载。Web UI 的内容安全策略只允许来自自身服务器以及 `data:` / `blob:` 的图片，所以远程图片在那里会被拦截。
- Web UI 重启过：图片只保存在内存里，重启后恢复出来的任务会显示图片缺失。请让 agent 重新调用该工具。
- 引用位于代码块或行内代码里：那里永远不会被当作图片。

**排查顺序**：

1. 打开 MCP 服务端日志搜索 `本地图片`：`任务 <task_id> 的本地图片: 已附带 N 张，跳过 M 张` 会说明附带了几张、跳过了几张；debug 级别还会逐条列出被跳过的引用及原因。
2. 直接问 Web UI 是否持有这张图片（任务 ID 可在 `/api/tasks` 里查到）：`curl -s -o /dev/null -w '%{http_code}\n' http://localhost:8080/api/tasks/<task_id>/images/0`，存有第 0 张时输出 `200`，没有则输出 `404`。
3. 如果 MCP 客户端不上报工作区目录，服务端会退回到自己的工作目录；当工作目录是 `/` 或你的主目录时（由编辑器启动的服务端经常如此）不会使用它。请显式列出工作区，例如 `local_image_dirs = ["auto", "~/work"]`。

## 18. MCP 服务端每次启动都会记录一行 `WARNING`：`event=server.boot`

**症状**：MCP 日志里每次启动都有一行这样的内容，级别是 `WARNING`：

```text
2026-10-20 20:11:15,910 - ai_intervention_agent.server - WARNING - event=server.boot version=1.8.12 transport=stdio mcp_name='AI Intervention Agent MCP' python=3.11.15 middleware=ErrorHandlingMiddleware,...
```

**含义**：没有任何问题。这是启动横幅：版本、传输方式、Python 版本和正在响应的中间件栈。它故意用 `WARNING` 级别写出：MCP 服务端的日志级别是 `WARNING`，除非你修改 `web_ui.log_level`（或 `AI_INTERVENTION_AGENT_LOG_LEVEL`）并重启它，所以用 `INFO` 级别写的横幅会被丢弃，而它正是说明当前运行哪个版本的那一行。

- 每次进程启动只出现一次。短时间内连续出现多条，说明 MCP 客户端多次启动了服务端；每一条之前的日志会说明原因。
- 报告问题时请附上这一行：里面有版本号。
- `web_ui.log_level = "ERROR"` 会把它和其他所有警告一起隐藏。

## 19. Web UI 里的按钮没反应，浏览器里看到 `403 cross_origin_write_blocked`

**症状**：Web UI 能打开，但提交回答、关闭任务、保存设置都失败。浏览器网络面板里这个 `POST` 返回 `403`，响应是 `{"success": false, "error": "cross_origin_write_blocked", ...}`，Web UI 日志里有一条以 `拒绝跨源写请求` 开头的警告，写着这个请求的 `Origin`、`Host` 和 `Sec-Fetch-Site`。只在通过反向代理、隧道或自定义主机名打开 Web UI 时出现；`http://127.0.0.1:<端口>`、`http://localhost:<端口>` 和本机自己的局域网地址不受影响。

**含义**：会改状态的请求（所有 `POST` / `PUT` / `PATCH` / `DELETE`，加上读后即清的 `GET /api/feedback`）在浏览器声明是另一个页面发起的时候会被拒绝。没有这道检查，你浏览器里打开的任何网页都能以你的名义回答 agent 的问题、关闭任务、把 Web UI 关掉。放行的情形有三种：浏览器带了 `Sec-Fetch-Site: same-origin`；请求既没有 `Origin` 也没有 `Sec-Fetch-Site`（MCP 服务、`curl`、脚本和 VS Code 扩展都不是浏览器）；或者 `Origin` 是 Web UI 自己的——和 `Host` 头同一个主机和端口、带 Web UI 端口的 `localhost` / `127.0.0.1`、VS Code webview，或 `web_ui.external_base_url`。改写 `Host` 的纯 HTTP 代理（nginx 默认）会让第一种和最后一种都落空：浏览器不会向纯 HTTP 地址发 `Sec-Fetch-Site`，而 `Origin`（`http://agent.example.com`）也不再等于被改写的 `Host`（`127.0.0.1:8080`）。

**修复**（任选一种）：

1. 把 `web_ui.external_base_url` 设成你在浏览器里输入的地址，例如 `http://agent.example.com`，然后重启 MCP 服务。Web UI 就把这个来源当作自己的。
2. 让代理把原始 `Host` 传下去（nginx：`proxy_set_header Host $http_host;`），并把这个名字加进 `network_security.trusted_hosts`。这样 `Origin` 就等于 `Host`。

走 HTTPS 时，会发 `Sec-Fetch-Site` 的浏览器（Chrome 76、Firefox 90、Safari 16.4 及以后）报的是 `same-origin`，所以 HTTPS 代理两样都不用配。如果日志里出现一个不是你发出的请求、`Origin` 是你不认识的网站，那就是这道保护在起作用：关掉那个页面。

## 20. 调用在大约两分钟后以 `MCP error -32001: Request timed out` 结束

**症状**：agent 调用 `interactive_feedback`，大约 120 秒后工具结果（或 Cursor 的 MCP 日志）显示 `MCP error -32001: Request timed out`。问题当时还在页面上，或者已经从页面上消失，你之后输入的回答也没有到达 agent。

**含义**：客户端放弃了一个沉默太久的调用。等人回答很慢，而客户端会给每个工具调用设一个空闲超时（Cursor 3.27：120 秒）。等待期间，服务器每 20 秒发送一次进度通知（`progress` 是已等待的秒数，消息内容为 `Waiting for human feedback (N s)`）。收到进度就重置空闲计时的客户端（Cursor 就是这样）会一直等到调用结束：你回答的时候、打开着的面板倒计时到点自动提交的时候（`frontend_countdown`），或者服务器自己的上限到了、返回重新提交提示的时候（`frontend_countdown` + 40 秒，至少 260，至多 `backend_max_wait`）。

- 1.8.12 及更早的版本在等待期间什么都不发。请升级到更新的版本并重启 MCP 服务端。
- 不要求进度的客户端（不发送进度令牌）收不到通知，仍按它自己的空闲超时计时。如果客户端有这个设置，请调大；或者调小 `frontend_countdown`，让打开着的面板抢在它之前提交。
- 没有任何面板或浏览器标签页显示这个问题时，没有东西在倒计时，所以调用会在服务器的上限处结束；agent 随后会再次调用该工具。

**排查顺序**：

1. 在 MCP 日志里找到这次失败（位置见第 16 节）并记下时间。设置 `web_ui.log_level = "INFO"` 并重启服务端，然后在它的日志里找 `等待任务完成:`：这一行写明了任务和上限（`超时: 260秒`）。调用后约 120 秒失败、而这一行里的上限更大，就是客户端的空闲超时。
2. 在 `DEBUG` 级别下，`progress keepalive failed (ignored)` 表示有一条通知没能发出，说明客户端没有在读它这一端的连接。

## 21. 有问题在等回答时 Web UI 页面不响应了，MCP 日志里写着 `Web UI 没有响应`

**症状**：显示问题的页面断开连接或打不开（`ERR_CONNECTION_REFUSED`），默认设置下大约十秒之后（重启本身很慢时会更久一点）又能打开了，问题还在上面。某个 MCP 服务端的日志里有一行 `WARNING`，形如：

```text
Web UI 没有响应（连续 3 次连接被拒绝），任务 <task_id> 仍在等待，正在重新启动（第 1/3 次）
```

**含义**：有调用在等 Web UI 的时候，Web UI 进程被停掉了。常见原因是两个编辑器窗口共用一个 Web UI（同一个 `web_ui.port`）：起这个 Web UI 的 MCP 服务端属于刚被关掉的那个窗口，而服务端退出时会停掉它自己起的 Web UI。对 Web UI 做 `kill` 或者它崩溃，效果相同。还在等待的那个窗口连续三次轮询都被拒绝连接，就重新启动 Web UI（每次中断最多三次尝试，相隔三次轮询），然后继续等。新进程会从自己的快照 `data/tasks-<端口>.json`（在包目录里，每个 `web_ui.port` 一个文件，所以端口不同的 Web UI 互相看不到对方的问题）恢复任务列表，所以问题带着原来的倒计时回来，包括你延长过的时间或设成“不限时”的状态；被关掉的窗口留下的问题也会回来，直到被回答、被关闭或倒计时结束。

- 重启失败时，日志里随后会出现 `重新启动 Web UI 失败` 加上原因。常见的是端口被别的程序占着：见第 1 节。调用会一直等到它的上限，然后返回重新提交提示；agent 再次调用工具时，那次调用会再试着启动一次 Web UI。
- 只有被拒绝的连接才算数。Web UI 还活着但很慢、或者回了一个错误，都不会被动。
- 正常情况下什么都不用做：等页面又能打开的时候刷新一下即可。

**排查顺序**：

1. 在还在等待的那个窗口的日志里找 `Web UI 没有响应`，后面应该跟着 `Web服务已启动`。第一行写明了任务和第几次尝试。别的窗口抢先启动了的话，这份日志里没有第二行，页面直接又能打开。
2. 页面一直打不开、第二行也一直没出现的话，看 `重新启动 Web UI 失败` 里的原因，再看是哪个进程占着端口：`lsof -nP -iTCP:8080 -sTCP:LISTEN`（换成你的 `web_ui.port`）。

## 还是没解决？

1. 看 [`SUPPORT.zh-CN.md`](../.github/SUPPORT.zh-CN.md) 选合适渠道。
2. 安全相关症状**不要**开公开 issue，按
   [`SECURITY.zh-CN.md`](../.github/SECURITY.zh-CN.md) 走私有公告。
3. 不确定是 bug、配置、还是环境问题，就开
   [GitHub Discussion][disc]。

[disc]: https://github.com/xiadengma/ai-intervention-agent/discussions
