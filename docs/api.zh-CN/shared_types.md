# shared_types

共享类型定义（Pydantic 配置段模型 + TypedDict 反馈结构）

目的：
- 配置段模型：提供 TOML 配置段的运行时校验与类型安全
- TypedDict：让 `ty` 在跨模块分析时拥有一致的结构化类型

命名规则：
- 配置段模型以 `SectionConfig` 后缀命名，与 notification_manager.NotificationConfig 等运行时模型区分

## 函数

### `_coerce_bool(v: Any) -> Any`

TOML/JSON 安全布尔值转换（兼容字符串 "true"/"false"/数字 0/1）

### `_coerce_int(v: Any) -> Any`

TOML/JSON 安全整数转换（兼容浮点数和数字字符串）

### `_clamp_int(min_val: int, max_val: int, default: int)`

生成一个 BeforeValidator：将整数值钳位到 [min_val, max_val]，失败返回 default

### `_clamp_int_allow_zero(min_val: int, max_val: int, default: int)`

生成一个 BeforeValidator：0 或负值 → 0（禁用），其余钳位到 [min_val, max_val]

### `_clamp_float(min_val: float, max_val: float, default: float)`

生成一个 BeforeValidator：将浮点值钳位到 [min_val, max_val]，失败返回 default

### `_coerce_float(v: Any) -> Any`

TOML/JSON 安全浮点转换

### `_coerce_str(v: Any) -> Any`

TOML/JSON 安全字符串转换（None → 默认由 Pydantic 处理）

## 类

### `class FeedbackImage`

单张图片的结构（Web UI / MCP 交互中使用）

### `class FeedbackResult`

Web UI 反馈结果结构（与 /api/feedback 返回一致）

### `class NotificationSectionConfig`

notification TOML 配置段（与 notification_manager.NotificationConfig 区分）

### `class WebUISectionConfig`

web_ui TOML 配置段

### `class MdnsSectionConfig`

mdns TOML 配置段

### `class NetworkSecuritySectionConfig`

network_security TOML 配置段

### `class FeedbackSectionConfig`

feedback TOML 配置段
