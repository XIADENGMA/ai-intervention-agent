## 配置文件说明

AI Intervention Agent 使用 **TOML** 配置文件，用于配置通知、Web UI、安全策略与超时行为。

默认模板：`config.toml.default`。

### 配置文件名

- 推荐：`config.toml`
- 向后兼容：`config.jsonc`、`config.json`（首次加载时自动迁移为 TOML）

### 配置文件位置与查找顺序

查找策略会根据运行方式变化。检测顺序如下，**先匹配的赢**：

| #   | 来源                                         | 模式             | 触发条件                                                                                                                                                |
| --- | -------------------------------------------- | ---------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | `AI_INTERVENTION_AGENT_CONFIG_FILE` 环境变量 | （任意）         | 设置了任意值；支持绝对文件路径或目录                                                                                                                    |
| 2   | `AI_INTERVENTION_AGENT_DEV_MODE=1`           | 强制 **dev**     | 在仓库内开发，希望即便从仓库外启动也使用 `./config.toml`                                                                                                |
| 3   | `AI_INTERVENTION_AGENT_USER_MODE=1`          | 强制 **user**    | 虽然进程启动目录在仓库内，但希望以「用户安装」语义运行（例如 systemd 服务）                                                                             |
| 4   | `UVX_PROJECT` 环境变量（旧）                 | 强制 **user**    | 部分老 uvx runner 会注入；保留向后兼容                                                                                                                  |
| 5   | 自动检测的隔离运行时                         | **user**         | `sys.executable` 位于 `~/.local/share/uv/tools/…` / `~/.local/share/pipx/venvs/…` / `~/.cache/uv/builds-…` 或模块位于 `site-packages` / `dist-packages` |
| 6   | 仓库 checkout 启发式                         | **dev**          | `pyproject.toml` + `server.py` 与 `config_manager.py` 同目录，**且**当前 shell `cwd` 在该目录树内                                                       |
| 7   | 默认                                         | **user**（安全） | 其他情况—永远不会在陌生人的 `cwd` 写入 `config.toml`                                                                                                    |

#### 强制指定（所有模式）

```bash
# 锁定到具体文件
AI_INTERVENTION_AGENT_CONFIG_FILE=/path/to/config.toml

# 或目录；会自动追加 `config.toml`
AI_INTERVENTION_AGENT_CONFIG_FILE=/path/to/dir/

# 在仓库外强制 dev 模式（例如 CI shell 里）
AI_INTERVENTION_AGENT_DEV_MODE=1

# 在仓库内强制 user 模式（例如 systemd 服务从 /opt/aiia 运行仓库代码）
AI_INTERVENTION_AGENT_USER_MODE=1
```

`UV_TOOL_DIR`、`UV_CACHE_DIR`、`PIPX_HOME`、`PIPX_LOCAL_VENVS` 也会被识别：
即使你修改过这些工具的默认安装目录，只要 `sys.executable` 在它们下面，agent
就会按「已安装」处理，不需要你设置任何额外环境变量。

#### uvx / `uv tool install` / pipx 模式（推荐给普通用户）

- **只使用**「用户配置目录」中的全局配置。
- 若文件不存在，会自动复制包内的 `config.toml.default` 创建默认配置。
- `~/.local/share/uv/tools/<name>/`、`~/.local/share/pipx/venvs/<name>/`、
  `~/.cache/uv/builds-…` 都会自动识别，不需要设置任何环境变量。

#### 开发模式（从仓库运行）

dev 模式内部优先级顺序：

1. 当前目录 `./config.toml`
2. 当前目录 `./config.jsonc`（向后兼容，自动迁移）
3. 当前目录 `./config.json`（向后兼容，自动迁移）
4. 用户配置目录（同上优先级）
5. 都不存在时，会在用户配置目录创建 `config.toml`

> 提示（避免“改了配置但不生效”的误解）
> Web UI 的「设置 → 配置」会显示**当前进程实际读取的配置文件路径**。
> 如果你希望在开发模式下也强制使用某一份全局配置，请用环境变量指定具体文件路径，例如：
>
> - Linux：`AI_INTERVENTION_AGENT_CONFIG_FILE=~/.config/ai-intervention-agent/config.toml`
> - macOS：`AI_INTERVENTION_AGENT_CONFIG_FILE=~/Library/Application Support/ai-intervention-agent/config.toml`
> - Windows：`AI_INTERVENTION_AGENT_CONFIG_FILE=%APPDATA%/ai-intervention-agent/config.toml`

> 提示（避免“我改了 config.jsonc 但没生效”）
> 同一目录如果同时存在 `config.toml` 和 `config.jsonc`（或 `config.json`），TOML 优先；
> agent 启动时会打印 `WARNING` 列出被忽略的旧格式文件。迁移完成后请删除或重命名旧文件。

### 环境变量覆盖

为方便 `uvx`、Docker、systemd 等「难以直接修改 `config.toml`」的运行场景，
以下 env vars 会在进程启动时一次性覆盖对应的 `config.toml` 值（在
`get_web_ui_config()` 内应用，并随 10 秒 TTL 缓存一同保留）。

| 环境变量                                | 覆盖项            | 类型 / 范围             | 说明                                                                |
| --------------------------------------- | ----------------- | ----------------------- | ------------------------------------------------------------------- |
| `AI_INTERVENTION_AGENT_WEB_UI_HOST`     | `web_ui.host`     | string                  | 典型值：`127.0.0.1`（loopback）/ `0.0.0.0`（局域网 / SSH 远程访问） |
| `AI_INTERVENTION_AGENT_WEB_UI_PORT`     | `web_ui.port`     | int，`[1, 65535]`       | 越界或非数字会记 WARNING 并忽略，server 继续用 `config.toml` 中的值 |
| `AI_INTERVENTION_AGENT_WEB_UI_LANGUAGE` | `web_ui.language` | `auto` / `en` / `zh-CN` | 强制设置 Web UI 语言，忽略系统 locale 与已保存的偏好                |

非法值**仅 WARNING，不抛异常**：env override 是「便利路径」，shell profile 里
打错一个字符不应该让 MCP server 起不来。原 `config.toml` 值会保留，且 WARNING
行会写到 stderr，让你能在日志反查 typo。

#### 示例：SSH 远程绑定到非默认端口

```bash
export AI_INTERVENTION_AGENT_WEB_UI_HOST=0.0.0.0
export AI_INTERVENTION_AGENT_WEB_UI_PORT=18080
uvx ai-intervention-agent
```

> **安全提示 —— 绑定非 loopback 地址时。** 设置
> `AI_INTERVENTION_AGENT_WEB_UI_HOST=0.0.0.0`（或任何非 `127.0.0.1`
> 地址）会把 `/api/get-notification-config` 之类的端点暴露给同网段所有
> 机器。这些响应包含 `notification.bark_device_key` 等 user-specific
> 凭证。绑定到 loopback 之外时建议的加固：
>
> 1. 在 `config.toml` 把 `network_security.allowed_networks` 设置为你
>    实际信任的最小 CIDR（例如 `["192.168.1.0/24"]`）。默认值
>    （`["127.0.0.0/8"]`，仅 loopback）**不会**被 `*_WEB_UI_HOST` env
>    var 覆盖——它们是相互独立的两层。
> 2. 优先考虑 `ssh -L 18080:127.0.0.1:18080` 隧道，而不是直接 bind
>    `0.0.0.0`——从远端机器上访问的体验一样，端口却完全不暴露。
> 3. `ai-intervention-agent --print-config` 会自动 redact 敏感 key，
>    但运行中的 HTTP API **不会**——边界 redaction 故意没启用，否
>    则 settings 面板就没法 round-trip 已有配置值。

#### 验证当前生效的配置

两条互补的可观测路径会告诉你同一件事：

```bash
# 本地 CLI：把 merged 配置 + 活跃 env 覆盖 dump 成 JSON
ai-intervention-agent --print-config | jq

# 运行中进程：通过 health 端点暴露的同一组字段
curl -s http://127.0.0.1:8080/api/system/health | jq '{config_file_path, web_ui_env_overrides}'
```

两条路径都刻意省略 `network_security` 段（敏感字段），返回的是 **merge 后**
的值——即进程实际绑定的，而不是 `config.toml` 里写的原值。如果两者
不一致，那 CLI 回答的是"下一次重启的行为"，health 端点回答的是
"当前进程的行为"；正常情况下两者一致。

要把同一组数据接入 **Prometheus / Grafana / Datadog OpenMetrics** 监控栈，
另有 `/api/system/metrics` 端点以 Prometheus 0.0.4 exposition format 输出
（R186）：

```yaml
# prometheus.yml
scrape_configs:
  - job_name: ai-intervention-agent
    metrics_path: /api/system/metrics
    static_configs:
      - targets: ["localhost:8080"]
    scrape_interval: 15s
```

所有 metric 都以 `aiia_*` 前缀命名（process / SSE / TaskQueue / 错误 /
notification per-provider）。任何子系统探测失败仅会让对应 metric 行缺失，
端点本身永远 200——监控会通过 metric staleness 自动 alert，而不会因为
某次内部 transient 错误把整个 target 标 red。

#### 其他 env vars（已在别处文档化）

- `AI_INTERVENTION_AGENT_LOG_LEVEL` —— 覆盖 `web_ui.log_level`（仅独立服务端）。
  VS Code 插件用户改 VS Code 设置里的 `ai-intervention-agent.logLevel`。
- `AI_INTERVENTION_AGENT_OPEN_WITH` —— 决定「用 IDE 打开配置文件」按钮调用的
  IDE，详见 [`docs/troubleshooting.zh-CN.md`](troubleshooting.zh-CN.md)。
- 路径探测类 env vars（`AI_INTERVENTION_AGENT_CONFIG_FILE`、`*_DEV_MODE`、
  `*_USER_MODE`、`UVX_PROJECT`）—— 详见上面的查找顺序表格。

### 跨平台用户配置目录

- Linux：`~/.config/ai-intervention-agent/`
- macOS：`~/Library/Application Support/ai-intervention-agent/`
- Windows：`%APPDATA%/ai-intervention-agent/`

> **macOS 上 `.config/` 残留兼容（R113）**
>
> 如果你的 macOS 上同时存在 `~/.config/ai-intervention-agent/config.toml`（可能是早期
> 版本残留、跨平台 dotfiles 抄过来、或第三方安装脚本硬编码了 XDG 风格路径），agent 会：
>
> 1. **标准路径 + legacy 同时存在** → 使用标准 `~/Library/Application Support/...`，
>    并打印 `WARNING` 日志说明 legacy 文件位置 + 给出 `rm -rf` 清理建议。
> 2. **仅 legacy 存在** → 优先使用 legacy 路径以**避免静默丢失**你已有的配置，并打印
>    强 `WARNING` 给出可一键复制的 `mkdir -p / mv / rmdir` 迁移脚本。
>
> Linux 用户不受影响——`~/.config/` 在 Linux 上是 XDG 标准，本检测仅 macOS 触发。

## 向后兼容

项目会兼容旧版配置项（便于升级）：

- **feedback**
  - `timeout` → `backend_max_wait`
  - `auto_resubmit_timeout` → `frontend_countdown`
- **web_ui**
  - `max_retries` → `http_max_retries`
  - `retry_delay` → `http_retry_delay`
- **network_security**
  - `enable_access_control` → `access_control_enabled`

配置在加载时会进行校验与范围裁剪（超出范围会自动调整到边界值）。

## 配置段说明

### `notification`（通知）

控制 Web/声音/系统通知/Bark 推送。

| 配置项                    | 类型    | 默认值                            | 说明                                                                                        |
| ------------------------- | ------- | --------------------------------- | ------------------------------------------------------------------------------------------- |
| `enabled`                 | boolean | `true`                            | 通知总开关                                                                                  |
| `debug`                   | boolean | `false`                           | 调试模式（仅影响通知模块的日志详细程度）                                                    |
| `web_enabled`             | boolean | `true`                            | 浏览器通知                                                                                  |
| `auto_request_permission` | boolean | `true`                            | 页面加载时自动请求通知权限                                                                  |
| `web_icon`                | string  | `"default"`                       | `"default"` 或自定义图标 URL                                                                |
| `web_timeout`             | number  | `5000`                            | Web 通知显示时长（毫秒），范围 `[1, 600000]`                                                |
| `system_enabled`          | boolean | `false`                           | 桌面系统通知（`plyer` 可选依赖）                                                            |
| `macos_native_enabled`    | boolean | `true`                            | macOS 原生通知（主要由 VS Code/Cursor 插件侧使用）                                          |
| `sound_enabled`           | boolean | `true`                            | 声音通知                                                                                    |
| `sound_mute`              | boolean | `false`                           | 静音                                                                                        |
| `sound_file`              | string  | `"default"`                       | 声音文件 key/name（例如 `"default"`、`"deng"`）                                             |
| `sound_volume`            | number  | `80`                              | 范围 `[0, 100]`                                                                             |
| `mobile_optimized`        | boolean | `true`                            | 移动端优化                                                                                  |
| `mobile_vibrate`          | boolean | `true`                            | 移动端震动（浏览器通常要求用户交互后才允许）                                                |
| `bark_enabled`            | boolean | `false`                           | 启用 Bark 推送                                                                              |
| `bark_url`                | string  | `""`                              | 必须以 `http://` 或 `https://` 开头                                                         |
| `bark_device_key`         | string  | `""`                              | `bark_enabled=true` 时必填                                                                  |
| `bark_icon`               | string  | `""`                              | 可选                                                                                        |
| `bark_action`             | string  | `"none"`                          | `none` / `url` / `copy`                                                                     |
| `bark_url_template`       | string  | `"{base_url}/?task_id={task_id}"` | `bark_action="url"` 且事件没有显式 URL 时使用；支持 `{task_id}`、`{event_id}`、`{base_url}` |
| `retry_count`             | number  | `3`                               | 失败重试次数（不含首次），范围 `[0, 10]`                                                    |
| `retry_delay`             | number  | `2`                               | 重试间隔秒数，范围 `[0, 60]`                                                                |
| `bark_timeout`            | number  | `10`                              | 请求超时秒数，范围 `[1, 300]`                                                               |

### `web_ui`（Web UI）

控制 Web UI 的监听与 HTTP 客户端行为。

| 配置项                 | 类型    | 默认值      | 说明                                                                                                                                                                                                                                                                                   |
| ---------------------- | ------- | ----------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `language`             | string  | `"auto"`    | 界面语言；`"auto"` 自动检测（浏览器 `navigator.language` / VS Code `vscode.env.language`），可显式设为 `"en"` / `"zh-CN"`                                                                                                                                                              |
| `host`                 | string  | `127.0.0.1` | 可能会被 `network_security.bind_interface` 覆盖                                                                                                                                                                                                                                        |
| `port`                 | number  | `8080`      | 范围 `[1, 65535]`                                                                                                                                                                                                                                                                      |
| `debug`                | boolean | `false`     | 调试模式                                                                                                                                                                                                                                                                               |
| `http_request_timeout` | number  | `30`        | HTTP 请求超时（秒），范围 `[1, 600]`                                                                                                                                                                                                                                                   |
| `http_max_retries`     | number  | `3`         | HTTP 最大重试次数，范围 `[0, 20]`                                                                                                                                                                                                                                                      |
| `http_retry_delay`     | number  | `1.0`       | HTTP 重试间隔（秒），范围 `[0, 60]`                                                                                                                                                                                                                                                    |
| `log_level`            | string  | `"WARNING"` | 独立服务端 enhanced_logging 模块日志级别，大小写不敏感，有效值：`"DEBUG"` / `"INFO"` / `"WARNING"` / `"ERROR"` / `"CRITICAL"`。可被环境变量 `AI_INTERVENTION_AGENT_LOG_LEVEL` 覆盖（env 优先）。VS Code 扩展使用方应改 VS Code 设置里的 `ai-intervention-agent.logLevel`（独立维度）。 |
| `external_base_url`    | string  | `""`        | 通知点击跳转使用的外部 Web UI 基地址，例如 `http://ai.local:8080`；留空时优先回退到 mDNS（`http://ai.local:{port}`），再回退到 `http://{host}:{port}`                                                                                                                                  |

### `network_security`（网络安全）

控制 Web UI 绑定网卡与访问控制。

| 配置项                   | 类型     | 默认值     | 说明                                   |
| ------------------------ | -------- | ---------- | -------------------------------------- |
| `bind_interface`         | string   | `0.0.0.0`  | `127.0.0.1` 仅本机；`0.0.0.0` 所有接口 |
| `allowed_networks`       | string[] | （见模板） | CIDR 白名单                            |
| `blocked_ips`            | string[] | `[]`       | IP 黑名单                              |
| `access_control_enabled` | boolean  | `true`     | 是否启用访问控制                       |

**Host 选择规则**：

- Web UI 实际 host 优先使用 `network_security.bind_interface`（若存在），否则使用 `web_ui.host`。

### `mdns`（mDNS / 局域网服务发现）

用于通过 `ai.local` 访问，并让局域网工具发现服务（DNS-SD / `_http._tcp.local`）。

| 配置项         | 类型             | 默认值                  | 说明                                                          |
| -------------- | ---------------- | ----------------------- | ------------------------------------------------------------- |
| `enabled`      | boolean / string | `"auto"`                | `true` 强制启用；`false` 强制禁用；`"auto"`（默认）= 自动检测 |
| `hostname`     | string           | `ai.local`              | mDNS 主机名（浏览器可直接访问 `http://ai.local:8080`）        |
| `service_name` | string           | `AI Intervention Agent` | DNS-SD 服务实例名（用于服务发现列表展示）                     |

**默认启用策略**：

- 当实际监听地址（`bind_interface`）不是 `127.0.0.1` / `localhost` / `::1` 时，自动启用。

**IP 自动探测策略**：

- 会优先选择“看起来是物理网卡”的 IPv4 地址，并尽量避开常见容器网卡与 VPN/隧道接口（如 `docker0`、`br-*`、`*tun*`、`tailscale*` 等）。
- 若你希望固定发布某个 IP，可将 `network_security.bind_interface` 设为该具体 IP（而不是 `0.0.0.0`）。

**冲突策略**：

- 若 `hostname` 发生冲突，会在启动时**报错并提示修改配置**，但不会阻断 Web UI 启动（仍可用 IP/localhost 访问）。

**安全说明**：

- mDNS 仅用于“发现/解析”，不会绕过 `allowed_networks` / `access_control_enabled` 等访问控制。

### `feedback`（反馈/超时）

控制等待时间与自动重调提示语。

| 配置项               | 类型   | 默认值                                     | 说明                                                                                                                                    |
| -------------------- | ------ | ------------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------- |
| `backend_max_wait`   | number | `600`                                      | 后端最大等待（秒），范围 `[10, 7200]`                                                                                                   |
| `frontend_countdown` | number | `240`                                      | 前端自动重调倒计时（秒），范围 `[10, 3600]`；`0`（或任意非正整数）禁用                                                                  |
| `resubmit_prompt`    | string | `"请立即调用 interactive_feedback 工具"`   | 错误/超时返回的引导语                                                                                                                   |
| `prompt_suffix`      | string | `"\n请积极调用 interactive_feedback 工具"` | 追加到用户反馈末尾的提示语。开头的 `\n` 是 TOML 转义的换行符；原样复制到 `config.toml` 即可（加载时 TOML 解析器会把它还原成真实换行）。 |

**超时规则**：

当 `frontend_countdown <= 0`：

`后端等待 = max(backend_max_wait, 260)`

否则：

`后端等待 = min(max(前端倒计时 + 40, 260), backend_max_wait)`

## 最小示例

```toml
[web_ui]
port = 8080

[feedback]
frontend_countdown = 240
```
