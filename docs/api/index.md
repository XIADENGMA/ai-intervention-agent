# AI Intervention Agent API Docs

English API reference (signatures-focused).

- Chinese version: [`docs/api.zh-CN/index.md`](../api.zh-CN/index.md)

## Modules

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

## Quick navigation

### Core modules

- **config_manager**: Configuration management
- **exceptions**: Unified exception definitions and error responses
- **notification_manager**: Notification orchestration
- **protocol**: Protocol version, capabilities, and server clock — single source of truth for the front/back contract
- **state_machine**: Connection / content / interaction state machines (mirrors front-end constants in `state.js`)
- **server**: MCP server entry point — `interactive_feedback` tool registration, multi-task queue lifecycle, notification integration, and the `main()` event loop
- **server_feedback**: `interactive_feedback` MCP tool implementation extracted from `server.py` — task polling, context management, undecorated tool function (registration stays on `server.mcp`)
- **server_config**: MCP server configuration and utility helpers (dataclasses, constants, input validation, response parsing)
- **service_manager**: Web service orchestration — process lifecycle, HTTP client, Web UI bring-up + health checks
- **task_queue**: Task queue
- **task_queue_singleton**: Lightweight `TaskQueue` singleton accessor decoupled from `server.py` — keeps the Web UI subprocess from pulling in `fastmcp` / `mcp` purely to access the queue (R20.8 startup-latency optimisation)
- **web_ui**: Flask Web UI main class — multi-task panel, file uploads, notifications, mDNS publishing, security middleware, and browser bootstrapping
- **web_ui_security**: Security policy mixin — IP allow/deny lists, CSP headers, network-security config loading (mixed into `WebFeedbackUI` via MRO)
- **web_ui_validators**: Pure validation/normalisation helpers for network-security configs and timeouts (extracted from `web_ui.py`; safe to call from tests / CLI / hot-reload paths)

### Utility modules

- **config_utils**: Configuration utility helpers
- **i18n**: Lightweight back-end i18n (request-language detection + locale-keyed message lookup)
- **shared_types**: Shared TypedDict definitions
- **notification_models**: Notification data models
- **notification_providers**: Concrete notification backends (Web Push / system sound / Bark / mobile vibration / macOS native)
- **file_validator**: File validation
- **enhanced_logging**: Logging enhancements
- **web_ui_config_sync**: Hot-reload callbacks — propagate `feedback.auto_resubmit_timeout` and network-security config changes into running tasks / Web UI instances
- **web_ui_mdns**: mDNS / DNS-SD lifecycle mixin — service discovery, registration, deregistration
- **web_ui_mdns_utils**: mDNS pure helpers — hostname normalisation, virtual-NIC filtering, IPv4 detection

---

_Auto-generated under `docs/api/`_
