# notification_models

通知领域模型：枚举与事件结构（避免 manager/provider 循环依赖）。

## 类

### `class NotificationType`

通知类型枚举：WEB(浏览器)、SOUND(声音)、BARK(iOS推送)、SYSTEM(系统)

### `class NotificationTrigger`

通知触发时机：立即/延迟/重复/反馈收到/错误

### `class NotificationPriority`

通知优先级：用于路由/降级/节流（阶段 A 先完成数据结构与可观测性）。

### `class NotificationEvent`

通知事件 - 封装一次通知的标题/消息/类型/触发时机/重试信息。

#### 方法

##### `coerce_none_metadata(cls, v: Any) -> dict[str, Any]`
