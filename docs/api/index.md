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
- [server_config](server_config.md)
- [shared_types](shared_types.md)
- [notification_manager](notification_manager.md)
- [notification_models](notification_models.md)
- [notification_providers](notification_providers.md)
- [task_queue](task_queue.md)
- [file_validator](file_validator.md)
- [enhanced_logging](enhanced_logging.md)

## Quick navigation

### Core modules

- **config_manager**: Configuration management
- **exceptions**: Unified exception definitions and error responses
- **notification_manager**: Notification orchestration
- **protocol**: Protocol version, capabilities, and server clock — single source of truth for the front/back contract
- **state_machine**: Connection / content / interaction state machines (mirrors front-end constants in `state.js`)
- **server_config**: MCP server configuration and utility helpers (dataclasses, constants, input validation, response parsing)
- **task_queue**: Task queue

### Utility modules

- **config_utils**: Configuration utility helpers
- **i18n**: Lightweight back-end i18n (request-language detection + locale-keyed message lookup)
- **shared_types**: Shared TypedDict definitions
- **notification_models**: Notification data models
- **file_validator**: File validation
- **enhanced_logging**: Logging enhancements

---

_Auto-generated under `docs/api/`_
