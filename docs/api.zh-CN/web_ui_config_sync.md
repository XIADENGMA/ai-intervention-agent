# web_ui_config_sync

> 英文 signature-only 版本（仅函数 / 类签名速查）：[`docs/api/web_ui_config_sync.md`](../api/web_ui_config_sync.md)

配置热更新回调 — 从 web_ui.py 提取的纯逻辑。

管理 feedback.auto_resubmit_timeout 和 network_security 配置变更后
对运行中任务/Web UI 实例的同步逻辑。

设计约束：
- 模块级状态变量保留在 web_ui.py（测试通过 web_ui.XXX 读写）
- get_config / get_task_queue 通过 lazy import web_ui 获取
  → 测试 @patch("web_ui.get_config") 即可生效，无需修改

## 函数

### `_get_default_auto_resubmit_timeout_from_config() -> int`

从配置文件读取默认 auto_resubmit_timeout（保持向后兼容）

### `_sync_existing_tasks_timeout_from_config() -> None`

配置变更回调：将新的默认倒计时同步到所有未完成任务

### `_sync_network_security_from_config() -> None`

配置变更回调：同步运行中 Web UI 的 network_security 配置。

### `_ensure_network_security_hot_reload_callback_registered() -> None`

确保仅注册一次 network_security 配置热更新回调。

### `_ensure_feedback_timeout_hot_reload_callback_registered() -> None`

确保仅注册一次 feedback.auto_resubmit_timeout 热更新回调。
