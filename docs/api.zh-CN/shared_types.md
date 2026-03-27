# shared_types

共享类型定义（TypedDict）

目的：
- 让 `ty` 在跨模块（server/web_ui/task_queue/tests）分析时拥有一致的结构化类型
- 避免在多个文件中重复声明相同的字典结构

说明：
- 这些类型仅用于类型检查/IDE 提示，不影响运行时行为

## 类

### `class FeedbackImage`

单张图片的结构（Web UI / MCP 交互中使用）

### `class FeedbackResult`

Web UI 反馈结果结构（与 /api/feedback 返回一致）

### `class NotificationConfig`

notification 配置段。

### `class WebUISectionConfig`

web_ui 配置段（config.toml 中的 web_ui 字段）。

### `class MdnsConfig`

mdns 配置段。

### `class NetworkSecurityConfig`

network_security 配置段。

### `class FeedbackConfig`

feedback 配置段。
