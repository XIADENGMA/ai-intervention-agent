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
- [server](server.md)
- [server_feedback](server_feedback.md)
- [server_config](server_config.md)
- [service_manager](service_manager.md)
- [shared_types](shared_types.md)
- [notification_manager](notification_manager.md)
- [notification_models](notification_models.md)
- [notification_providers](notification_providers.md)
- [task_queue](task_queue.md)
- [task_queue_singleton](task_queue_singleton.md)
- [web_ui](web_ui.md)
- [web_ui_config_sync](web_ui_config_sync.md)
- [web_ui_mdns](web_ui_mdns.md)
- [web_ui_mdns_utils](web_ui_mdns_utils.md)
- [web_ui_security](web_ui_security.md)
- [web_ui_validators](web_ui_validators.md)
- [file_validator](file_validator.md)
- [enhanced_logging](enhanced_logging.md)

## 快速导航

### 核心模块

- **config_manager**: 配置管理
- **exceptions**: 统一异常定义与错误响应
- **notification_manager**: 通知管理
- **protocol**: 协议版本、Capabilities、服务器时钟 —— 前后端契约的单一事实来源
- **state_machine**: 连接 / 内容 / 交互状态机（与前端 `state.js` 常量一一对应）
- **server**: MCP 服务器入口 —— `interactive_feedback` 工具注册、多任务队列生命周期、通知集成与 `main()` 事件循环
- **server_feedback**: 从 `server.py` 抽出的 `interactive_feedback` 工具实现 —— 任务轮询、上下文管理、未装饰的工具函数本体（注册仍在 `server.mcp`）
- **server_config**: MCP 服务器配置与工具函数（数据类、常量、输入验证、响应解析）
- **service_manager**: Web 服务编排层 —— 进程生命周期管理、HTTP 客户端、Web UI 启动与健康检查
- **task_queue**: 任务队列
- **task_queue_singleton**: 轻量级 `TaskQueue` 单例访问器（与 `server.py` 解耦）—— 让 Web UI 子进程不再为了拿一个 task queue 而触发 `fastmcp` / `mcp` 整条依赖链加载（R20.8 启动延迟优化）
- **web_ui**: Flask Web UI 主类 —— 多任务面板、文件上传、通知、mDNS 发布、安全中间件与浏览器引导
- **web_ui_security**: 安全策略 Mixin —— IP 访问控制、CSP 安全头注入、网络安全配置加载（通过 MRO 注入 `WebFeedbackUI`）
- **web_ui_validators**: 网络安全配置 / 超时校验的纯函数（从 `web_ui.py` 抽出；测试 / CLI / 配置热更新均可安全复用）

### 工具模块

- **config_utils**: 配置工具函数
- **i18n**: 后端轻量 i18n（请求语言检测 + 本地化消息查表）
- **shared_types**: 共享 TypedDict 类型定义
- **notification_models**: 通知数据模型
- **notification_providers**: 具体通知后端实现（Web Push / 系统声音 / Bark / 移动振动 / macOS 原生）
- **file_validator**: 文件验证
- **enhanced_logging**: 日志增强
- **web_ui_config_sync**: 配置热更新回调 —— 把 `feedback.auto_resubmit_timeout` 与网络安全配置变更同步到运行中的任务 / Web UI 实例
- **web_ui_mdns**: mDNS / DNS-SD 生命周期 Mixin —— 服务发现、注册、注销
- **web_ui_mdns_utils**: mDNS 纯函数辅助 —— 主机名规范化、虚拟网卡过滤、IPv4 探测

---

_文档自动生成于 `docs/api.zh-CN/`_
