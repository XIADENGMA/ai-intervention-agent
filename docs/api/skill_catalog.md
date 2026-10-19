# skill_catalog

> For the Chinese version with full docstrings, see: [`docs/api.zh-CN/skill_catalog.md`](../api.zh-CN/skill_catalog.md)

## Functions

### `parse_frontmatter(text: str) -> tuple[dict[str, str], str]`

### `_parse_mapping(lines: Sequence[str]) -> dict[str, str]`

### `_parse_scalar(first: str, continuation: Sequence[str]) -> str | None`

### `_strip_comment(text: str) -> str`

### `_parse_quoted(text: str) -> str`

### `_parse_escape(text: str, index: int) -> tuple[str, int]`

### `_clip(text: str, limit: int) -> str`

### `_clean_token(text: str) -> str`

### `slash_token(name: str, description: str, fallback: str) -> str`

### `_is_false(value: str | None) -> bool`

### `_first_body_line(body: str) -> str`

### `build_entry(text: str, fallback_name: str, kind: Literal['skill', 'command'], source: str) -> SkillEntry | None`

### `normalize_skill_dirs(value: Any) -> list[str]`

### `_describe(path: Path, home: Path | None, cwd: Path | None) -> str`

### `_role_of(path: Path) -> Literal['skill', 'command']`

### `_identity(path: Path) -> str`

### `resolve_skill_roots(configured: Any) -> list[SkillRoot]`

### `_read_head(path: Path) -> str | None`

### `_list_dir(directory: Path) -> list[os.DirEntry[str]]`

### `_is_dir(entry: os.DirEntry[str]) -> bool`

### `_is_file(entry: os.DirEntry[str]) -> bool`

### `_walk_skill_files(root: Path, deadline: float, clock: Callable[[], float]) -> Iterator[Path]`

### `_scan_skill_root(root: SkillRoot, deadline: float, clock: Callable[[], float]) -> Iterator[SkillEntry]`

### `_scan_command_root(root: SkillRoot, deadline: float, clock: Callable[[], float]) -> Iterator[SkillEntry]`

### `scan_roots(roots: Sequence[SkillRoot]) -> Catalog`

### `invalidate_cache() -> None`

### `get_catalog(configured: Any = None) -> Catalog`

## Classes

### `class SkillEntry`

### `class Catalog`

### `class SkillRoot`
