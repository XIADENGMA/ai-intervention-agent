# server_config

> For the Chinese version with full docstrings, see: [`docs/api.zh-CN/server_config.md`](../api.zh-CN/server_config.md)

## Functions

### `_lazy_mcp_types() -> Any`

### `get_feedback_config() -> FeedbackConfig`

### `calculate_backend_timeout(auto_resubmit_timeout: int, max_timeout: int = 0, infinite_wait: bool = False) -> int`

### `get_feedback_prompts() -> tuple[str, str]`

### `_append_prompt_suffix(text: str) -> str`

### `_make_resubmit_response(as_mcp: Literal[True] = ...) -> list`

### `_make_resubmit_response(as_mcp: Literal[False]) -> dict`

### `_make_resubmit_response(as_mcp: bool = True) -> list | dict`

### `_normalize_option_default(value: Any) -> bool`

### `validate_input_with_defaults(prompt: str, predefined_options: list | None = None) -> tuple[str, list[str], list[bool]]`

### `validate_input(prompt: str, predefined_options: list | None = None) -> tuple[str, list[str]]`

### `_generate_task_id() -> str`

### `get_target_host(host: str) -> str`

### `resolve_external_base_url(web_ui_config: WebUIConfig | None = None) -> str`

### `_format_file_size(size: int) -> str`

### `_guess_mime_type_from_data(base64_data: str) -> str | None`

### `_process_image(image: dict, index: int) -> tuple[ImageContent | None, str | None]`

### `parse_structured_response(response_data: dict[str, Any] | None) -> list[ContentBlock]`

## Classes

### `class WebUIConfig`

#### Methods

##### `validate_language(cls, v: str) -> str`

##### `validate_port(cls, v: int) -> int`

##### `clamp_timeout(cls, v: int) -> int`

##### `clamp_max_retries(cls, v: int) -> int`

##### `clamp_retry_delay(cls, v: float) -> float`

### `class FeedbackConfig`

#### Methods

##### `clamp_timeout(cls, v: int) -> int`

##### `clamp_auto_resubmit(cls, v: int) -> int`

##### `truncate_resubmit(cls, v: str) -> str`

##### `truncate_suffix(cls, v: str) -> str`
