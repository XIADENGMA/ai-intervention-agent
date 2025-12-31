## 配置文件说明

AI Intervention Agent 使用 **JSONC**（带注释的 JSON）作为配置文件格式，用于配置通知、Web UI、安全策略与超时行为。

默认模板：`config.jsonc.default`。

### 配置文件名

- 推荐：`config.jsonc`
- 向后兼容：`config.json`

### 配置文件位置与查找顺序

查找策略会根据运行方式变化。

#### 强制指定（所有模式）

可通过环境变量强制指定配置路径：

- `AI_INTERVENTION_AGENT_CONFIG_FILE=/path/to/config.jsonc`
- `AI_INTERVENTION_AGENT_CONFIG_FILE=/path/to/dir/`（会自动拼接 `config.jsonc`）

#### uvx 模式（推荐给普通用户）

- **只使用**「用户配置目录」中的全局配置。
- 若文件不存在，会自动复制包内的 `config.jsonc.default` 创建默认配置。

#### 开发模式（从仓库运行）

优先级顺序：

1. 当前目录 `./config.jsonc`
2. 当前目录 `./config.json`（向后兼容）
3. 用户配置目录 `config.jsonc`
4. 用户配置目录 `config.json`（向后兼容）
5. 都不存在时，会在用户配置目录创建 `config.jsonc`

### 跨平台用户配置目录

- Linux：`~/.config/ai-intervention-agent/`
- macOS：`~/Library/Application Support/ai-intervention-agent/`
- Windows：`%APPDATA%/ai-intervention-agent/`

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

| 配置项 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `enabled` | boolean | `true` | 通知总开关 |
| `web_enabled` | boolean | `true` | 浏览器通知 |
| `auto_request_permission` | boolean | `true` | 页面加载时自动请求通知权限 |
| `sound_enabled` | boolean | `true` | 声音通知 |
| `sound_mute` | boolean | `false` | 静音 |
| `sound_volume` | number | `80` | 范围 `[0, 100]` |
| `mobile_optimized` | boolean | `true` | 移动端优化 |
| `mobile_vibrate` | boolean | `true` | 移动端震动（浏览器通常要求用户交互后才允许） |
| `bark_enabled` | boolean | `false` | 启用 Bark 推送 |
| `bark_url` | string | `""` | 必须以 `http://` 或 `https://` 开头 |
| `bark_device_key` | string | `""` | `bark_enabled=true` 时必填 |
| `bark_icon` | string | `""` | 可选 |
| `bark_action` | string | `"none"` | `none` / `url` / `copy` |
| `retry_count` | number | `3` | 失败重试次数（不含首次），范围 `[0, 10]` |
| `retry_delay` | number | `2` | 重试间隔秒数，范围 `[0, 60]` |
| `bark_timeout` | number | `10` | 请求超时秒数，范围 `[1, 300]` |

### `web_ui`（Web 界面）

控制 Web UI 的监听与 HTTP 客户端行为。

| 配置项 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `host` | string | `127.0.0.1` | 可能会被 `network_security.bind_interface` 覆盖 |
| `port` | number | `8080` | 范围 `[1, 65535]` |
| `debug` | boolean | `false` | 调试模式 |
| `http_request_timeout` | number | `30` | HTTP 请求超时（秒），范围 `[1, 300]` |
| `http_max_retries` | number | `3` | HTTP 最大重试次数，范围 `[0, 10]` |
| `http_retry_delay` | number | `1.0` | HTTP 重试间隔（秒），范围 `[0.1, 60.0]` |

### `network_security`（网络安全）

控制 Web UI 绑定网卡与访问控制。

| 配置项 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `bind_interface` | string | `0.0.0.0` | `127.0.0.1` 仅本机；`0.0.0.0` 所有接口 |
| `allowed_networks` | string[] |（见模板）| CIDR 白名单 |
| `blocked_ips` | string[] | `[]` | IP 黑名单 |
| `access_control_enabled` | boolean | `true` | 是否启用访问控制 |

**Host 选择规则**：

- Web UI 实际 host 优先使用 `network_security.bind_interface`（若存在），否则使用 `web_ui.host`。

### `feedback`（反馈/超时）

控制等待时间与自动重调提示语。

| 配置项 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `backend_max_wait` | number | `600` | 后端最大等待（秒），范围 `[60, 3600]` |
| `frontend_countdown` | number | `240` | 前端自动提交倒计时（秒），范围 `[30, 290]`；`0` 禁用 |
| `resubmit_prompt` | string | `"请立即调用 interactive_feedback 工具"` | 错误/超时返回的引导语 |
| `prompt_suffix` | string | `"\\n请积极调用 interactive_feedback 工具"` | 追加到用户反馈末尾的提示语 |

**超时规则**：

`后端等待 = min(max(前端倒计时 + 60, 300), backend_max_wait)`

## 最小示例

```jsonc
{
  "web_ui": {
    "port": 8080
  },
  "feedback": {
    "frontend_countdown": 240
  }
}
```

