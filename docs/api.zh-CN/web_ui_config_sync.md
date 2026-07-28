# web_ui_config_sync

> 英文 signature-only 版本（仅函数 / 类签名速查）：[`docs/api/web_ui_config_sync.md`](../api/web_ui_config_sync.md)

配置热更新回调 — 从 web_ui.py 提取的纯逻辑。

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

R702：注册时只记录当前配置基线（_LAST_APPLIED_AUTO_RESUBMIT_TIMEOUT），
不立即同步已存在任务——同步只在配置真正变更的回调里发生。

### `_emit_config_changed_to_sse_bus() -> None`

配置变更回调：通过 SSE 总线推一个 ``config_changed`` 事件（带 debounce）。

### `_ensure_config_changed_sse_callback_registered() -> None`

确保仅注册一次 config_changed SSE 推送回调（R48）。
