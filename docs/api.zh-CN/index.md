# AI Intervention Agent API 文档

中文 API 参考（含完整 docstring 叙述）。

- English version: [`docs/api/index.md`](../api/index.md)

## 模块列表

- [config_manager](config_manager.md)
- [config_utils](config_utils.md)
- [exceptions](exceptions.md)
- [i18n](i18n.md)
- [protocol](protocol.md)
- [state_machine](state_machine.md)
- [server_config](server_config.md)
- [shared_types](shared_types.md)
- [notification_manager](notification_manager.md)
- [notification_models](notification_models.md)
- [notification_providers](notification_providers.md)
- [task_queue](task_queue.md)
- [file_validator](file_validator.md)
- [enhanced_logging](enhanced_logging.md)

## 快速导航

### 核心模块

- **config_manager**: 配置管理
- **exceptions**: 统一异常定义与错误响应
- **notification_manager**: 通知管理
- **protocol**: 协议版本、Capabilities、服务器时钟 —— 前后端契约的单一事实来源
- **state_machine**: 连接 / 内容 / 交互状态机（与前端 `state.js` 常量一一对应）
- **server_config**: MCP 服务器配置与工具函数（数据类、常量、输入验证、响应解析）
- **task_queue**: 任务队列

### 工具模块

- **config_utils**: 配置工具函数
- **i18n**: 后端轻量 i18n（请求语言检测 + 本地化消息查表）
- **shared_types**: 共享 TypedDict 类型定义
- **notification_models**: 通知数据模型
- **notification_providers**: 具体通知后端实现（Web Push / 系统声音 / Bark / 移动振动 / macOS 原生）
- **file_validator**: 文件验证
- **enhanced_logging**: 日志增强

---

_文档自动生成于 `docs/api.zh-CN/`_
