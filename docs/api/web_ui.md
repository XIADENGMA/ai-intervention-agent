# web_ui

> For the Chinese version with full docstrings, see: [`docs/api.zh-CN/web_ui.md`](../api.zh-CN/web_ui.md)

## Functions

### `get_project_version() -> str`

### `_read_inline_locale_json(locale_path_str: str) -> str | None`

### `_is_swagger_enabled_via_env() -> bool`

### `_compute_file_version(file_path_str: str) -> str`

### `_get_module_static_dir() -> Path`

### `web_feedback_ui(prompt: str, predefined_options: list[str] | None = None, task_id: str | None = None, auto_resubmit_timeout: int = AUTO_RESUBMIT_TIMEOUT_DEFAULT, output_file: str | None = None, host: str = '0.0.0.0', port: int = 8080) -> FeedbackResult | None`

## Classes

### `class WebFeedbackUI`

#### Methods

##### `__init__(self, prompt: str, predefined_options: list[str] | None = None, task_id: str | None = None, auto_resubmit_timeout: int = AUTO_RESUBMIT_TIMEOUT_DEFAULT, host: str = '0.0.0.0', port: int = 8080)`

##### `setup_markdown(self) -> None`

##### `render_markdown(self, text: str) -> str`

##### `setup_routes(self) -> None`

##### `shutdown_server(self) -> None`

##### `update_content(self, new_prompt: str, new_options: list[str] | None = None, new_task_id: str | None = None) -> None`

##### `run(self) -> FeedbackResult`
