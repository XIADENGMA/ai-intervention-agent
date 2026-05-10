# 故障排查（Troubleshooting）

> English version: [`troubleshooting.md`](troubleshooting.md)

针对最常见的部署 / 运行时问题的精简 FAQ。如果你的问题不在这里，
请参考 [`SUPPORT.md`](../.github/SUPPORT.md) 选择合适渠道。

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
| **Bark** | device key 错 / 推送服务不可达 / `bark_url` 没指向你自建实例 | 用 `curl -v "$BARK_URL/$DEVICE_KEY/test"` 单测。设 `bark_action = "url"` + `bark_url_template = "{base_url}/?task_id={task_id}"` 做点击直达。**如果解析出来的 URL 是 loopback 地址**（`localhost` / `127.x.x.x` / `::1`），agent 现在会在服务端直接过滤——手机不会再收到一个无法点击打开的 URL；同时 Web UI 的 Bark 设置面板会推荐对应的 LAN IP（`http://<lan-ip>:<port>`）让你一键复制并写入 `web_ui.external_base_url`（或开 mDNS）后重试。 |

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

**为什么这么严**：这个端点强制三道 guard（见 `.github/SECURITY.md`）：

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
  + `KeyboardInterrupt` 优雅退出的 harness 里。
- R114（通知管理器）已经把 atexit / shutdown TOCTOU race 静默化，
  老版本会在 host restart 期间打 `ERROR: 处理通知事件失败` 噪声日志，
  容易被误判成 MCP 端故障；新版本不会再出。

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

—— 通常**只有** Open VSX job 报错；同一份 VSIX 上传到 Microsoft VS
Code Marketplace 一切正常。

### 为什么会这样

`ovsx publish` 服务端校验器严格比较 `package.json`（NLS 占位符**未**
解析）和 VSIX 内 `extension.vsixmanifest` 的字符串字段。NLS 占位符
（如 `"%displayName%"`）在 `ovsx` 看来就是字面量字符串，不会展开后再
比对——因此与 VSIX manifest 内被构建工具展开的字面值（如
`"AI Intervention Agent"`）必然不等。Microsoft Marketplace 容忍这种
差异；Open VSX（约 2026-05 起）不再容忍。

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
> release.yml` 里找），不要走浮动。

## 还是没解决？

1. 看 [`SUPPORT.md`](../.github/SUPPORT.md) 选合适渠道。
2. 安全相关症状**不要**开公开 issue，按
   [`SECURITY.md`](../.github/SECURITY.md) 走私有公告。
3. 不确定是 bug、配置、还是环境问题，就开
   [GitHub Discussion][disc]。

[disc]: https://github.com/xiadengma/ai-intervention-agent/discussions
