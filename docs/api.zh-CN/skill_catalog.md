# skill_catalog

> 英文 signature-only 版本（仅函数 / 类签名速查）：[`docs/api/skill_catalog.md`](../api/skill_catalog.md)

Skill and slash-command catalogue behind the ``/`` picker of the feedback box.

Typing ``/`` in the feedback box opens a picker that lists the agent skills and
custom commands installed on the machine running the Web UI. This module finds
them:

- a *skill* is a folder holding a ``SKILL.md`` whose YAML front matter carries
  ``name`` and ``description`` (the Agent Skills layout shared by Cursor,
  Claude Code and Codex). Nested skill folders are supported,
  ``user-invocable: false`` hides a skill from the picker, and a ``SKILL.md``
  without any front matter is not a valid skill and is skipped;
- a *command* is a Markdown file placed directly inside a directory named
  ``commands`` or ``prompts`` (``.cursor/commands``, ``.claude/commands``,
  ``~/.codex/prompts``).

Which directories are scanned is controlled by ``[feedback] skill_dirs``. The
token ``"auto"`` expands to the well-known locations (project directories first,
then the user's home); every other entry is a directory, where ``~`` is expanded
and a relative path is resolved against the working directory. Entries that do
not exist are ignored.

A skill is inserted into the feedback box as ``/<token>``. The token is the
skill's ``name`` when that is a single word; otherwise the name written after
``触发名:`` / ``trigger name:`` in the description, then the folder name, then a
dash-joined form of the name.

Only display metadata (name, token, description, kind and a short origin label)
leaves this module. File bodies and absolute paths never do, and scanning is
bounded by a depth limit, an entry limit, a per-file read limit and a time
budget so that a huge or hostile directory cannot stall the Web UI.

## 函数

### `parse_frontmatter(text: str) -> tuple[dict[str, str], str]`

Split a Markdown document into ``(front matter scalars, body)``.

Only top-level scalar keys survive: plain, single/double quoted and
``|`` / ``>`` block scalars (whitespace collapsed to single spaces).
Nested mappings, lists and flow collections are skipped. A document
without a leading ``---`` fence yields ``({}, text)``; an unterminated
fence (for example a file cut at the read limit) is parsed up to the end.

### `_parse_mapping(lines: Sequence[str]) -> dict[str, str]`

### `_parse_scalar(first: str, continuation: Sequence[str]) -> str | None`

### `_strip_comment(text: str) -> str`

### `_parse_quoted(text: str) -> str`

### `_parse_escape(text: str, index: int) -> tuple[str, int]`

### `_clip(text: str, limit: int) -> str`

### `_clean_token(text: str) -> str`

### `slash_token(name: str, description: str, fallback: str) -> str`

Return the word inserted after ``/`` for a skill or command.

``name`` is the front-matter name, ``fallback`` the folder (or file) name.

### `_is_false(value: str | None) -> bool`

### `_first_body_line(body: str) -> str`

### `build_entry(text: str, fallback_name: str, kind: Literal['skill', 'command'], source: str) -> SkillEntry | None`

Build a picker row from a ``SKILL.md`` / command file, or ``None`` to hide it.

### `normalize_skill_dirs(value: Any) -> list[str]`

Coerce a ``skill_dirs`` setting into a bounded list of non-empty strings.

``None``, an unsupported type, or a non-empty list without a single usable
entry falls back to ``["auto"]``; an explicit empty list stays empty and
turns the picker off.

### `_describe(path: Path, home: Path | None, cwd: Path | None) -> str`

### `_role_of(path: Path) -> Literal['skill', 'command']`

### `_identity(path: Path) -> str`

### `resolve_skill_roots(configured: Any) -> list[SkillRoot]`

Turn a ``skill_dirs`` setting into existing directories, in priority order.

### `_read_head(path: Path) -> str | None`

### `_list_dir(directory: Path) -> list[os.DirEntry[str]]`

### `_is_dir(entry: os.DirEntry[str]) -> bool`

### `_is_file(entry: os.DirEntry[str]) -> bool`

### `_walk_skill_files(root: Path, deadline: float, clock: Callable[[], float]) -> Iterator[Path]`

### `_scan_skill_root(root: SkillRoot, deadline: float, clock: Callable[[], float]) -> Iterator[SkillEntry]`

### `_scan_command_root(root: SkillRoot, deadline: float, clock: Callable[[], float]) -> Iterator[SkillEntry]`

### `scan_roots(roots: Sequence[SkillRoot]) -> Catalog`

Scan ``roots`` in order; the first root defining a token wins.

### `invalidate_cache() -> None`

Forget the cached catalogue (tests and config reloads).

### `get_catalog(configured: Any = None) -> Catalog`

Return the catalogue for a ``skill_dirs`` setting, cached for ``ttl`` seconds.

## 类

### `class SkillEntry`

One row of the ``/`` picker.

### `class Catalog`

Result of :func:`get_catalog`.

### `class SkillRoot`

A directory to scan, with the role implied by its name.
