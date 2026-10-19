# local_images

> For the Chinese version with full docstrings, see: [`docs/api.zh-CN/local_images.md`](../api.zh-CN/local_images.md)

## Functions

### `normalize_image_dirs(value: Any) -> list[str]`

### `image_url(task_id: str, index: int) -> str`

### `has_image_candidates(prompt: str) -> bool`

### `sniff_image_mime(head: bytes) -> str | None`

### `file_uri_to_path(uri: str) -> Path | None`

### `_realpath(path: Path) -> Path | None`

### `_is_inside(path: Path, root: Path) -> bool`

### `_temp_dirs() -> list[Path]`

### `resolve_allowed_dirs(setting: Any, client_roots: Sequence[Path] = ()) -> list[Path]`

### `_code_ranges(text: str) -> list[tuple[int, int]]`

### `_inline_code_spans(paragraph: str, offset: int) -> list[tuple[int, int]]`

### `_in_code(position: int, spans: list[tuple[int, int]], starts: list[int]) -> bool`

### `_skip_whitespace(text: str, index: int) -> int`

### `_unescape_markdown(text: str) -> str`

### `_match_markdown_image(text: str, bang: int) -> _Ref | None`

### `_find_refs(text: str) -> list[_Ref]`

### `_spellings(text: str) -> list[str]`

### `_local_spellings(dest: str) -> list[str] | None`

### `_candidate_paths(spelling: str, roots: Sequence[Path]) -> list[Path]`

### `_locate(spellings: Sequence[str], roots: Sequence[Path]) -> Path`

### `_read_image(real: Path, remaining_total: int) -> PromptImage`

### `_placeholder(ref: _Ref, reason: Reason) -> str`

### `prepare_prompt_images(prompt: str, task_id: str, roots: Sequence[Path]) -> PreparedPrompt`

### `encode_prompt_images(images: Sequence[PromptImage]) -> list[dict[str, str]]`

### `_decode_prompt_image(item: Any, remaining_total: int) -> PromptImage | None`

### `parse_prompt_images(raw: Any) -> tuple[PromptImage | None, ...]`

## Classes

### `class Reason`

### `class PromptImage`

### `class SkippedImage`

### `class PreparedPrompt`

### `class _Ref`

### `class _Skip`

#### Methods

##### `__init__(self, reason: Reason) -> None`
