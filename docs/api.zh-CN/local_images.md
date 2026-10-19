# local_images

> 英文 signature-only 版本（仅函数 / 类签名速查）：[`docs/api/local_images.md`](../api/local_images.md)

Local images inside a prompt: find them, check them, read them.

An agent that wants to show a screenshot or a chart writes an ordinary Markdown
image whose destination is a path on its own machine, for example
``![chart](/work/proj/out/chart.png)``. A browser cannot load such a path, and
the Web UI must never read a file because a path arrived over HTTP
(``POST /api/tasks`` is open to every allowed network). So the MCP process, which
runs next to the files, reads the bytes and ships them with the task, rewrites
each reference to ``/api/tasks/<task_id>/images/<n>``, and the Web UI only serves
what it was handed.

What may be read is deliberately narrow:

- only inside the *allowed folders*: the workspace folders the MCP client
  declares (``roots/list``), the system temporary directory, and whatever
  ``[feedback] local_image_dirs`` adds (``"auto"`` stands for the first two,
  ``[]`` switches the feature off). A filesystem root is never allowed;
- the path is resolved with ``realpath`` first, so ``..`` segments and symlinks
  that lead out of an allowed folder are refused, and the file is opened without
  following a final symlink and verified to be a regular file;
- the extension must be png, jpg, jpeg, gif, webp, bmp or avif **and** the first
  bytes must say the same (SVG is refused: it is a script carrier);
- at most :data:`MAX_IMAGES` images, :data:`MAX_IMAGE_BYTES` each and
  :data:`MAX_TOTAL_BYTES` together per prompt.

A reference that cannot be honoured is replaced by a one-line text placeholder
that names the reason, so the person reading the prompt knows what is missing;
references that are not local (``http(s):``, ``data:``, ``#fragment``) are left
alone. Only the inline syntaxes ``![alt](dest "title")`` and ``<img src="...">``
are recognised, and nothing inside fenced code or inline code is touched.

## 函数

### `normalize_image_dirs(value: Any) -> list[str]`

Coerce a ``local_image_dirs`` setting into a bounded list of strings.

``None``, an unsupported type, or a non-empty list without a single usable
entry falls back to ``["auto"]``; an explicit empty list stays empty and
turns local images off.

### `image_url(task_id: str, index: int) -> str`

The URL under which the Web UI serves image ``index`` of ``task_id``.

### `has_image_candidates(prompt: str) -> bool`

Cheap pre-check: does the prompt contain anything that looks like an image?

### `sniff_image_mime(head: bytes) -> str | None`

The MIME type the leading bytes of a file declare, or ``None``.

### `file_uri_to_path(uri: str) -> Path | None`

Convert a ``file://`` URI (as sent in MCP roots) to a path, else ``None``.

### `_realpath(path: Path) -> Path | None`

### `_is_inside(path: Path, root: Path) -> bool`

### `_temp_dirs() -> list[Path]`

### `resolve_allowed_dirs(setting: Any, client_roots: Sequence[Path] = ()) -> list[Path]`

Turn a ``local_image_dirs`` setting into existing, real directories.

``"auto"`` expands to the client's workspace folders (the working directory
stands in when the client declares none and it is neither a filesystem root
nor the home directory) plus the system temporary directory; any other entry
is a directory where ``~`` is expanded and a relative path is resolved
against the working directory. Entries that do not exist and filesystem
roots are dropped.

### `_code_ranges(text: str) -> list[tuple[int, int]]`

Half-open spans of fenced code blocks and inline code spans, sorted.

### `_inline_code_spans(paragraph: str, offset: int) -> list[tuple[int, int]]`

### `_in_code(position: int, spans: list[tuple[int, int]], starts: list[int]) -> bool`

### `_skip_whitespace(text: str, index: int) -> int`

### `_unescape_markdown(text: str) -> str`

### `_match_markdown_image(text: str, bang: int) -> _Ref | None`

### `_find_refs(text: str) -> list[_Ref]`

### `_spellings(text: str) -> list[str]`

### `_local_spellings(dest: str) -> list[str] | None`

Path spellings for a local destination; ``None`` when it is not local.

### `_candidate_paths(spelling: str, roots: Sequence[Path]) -> list[Path]`

### `_locate(spellings: Sequence[str], roots: Sequence[Path]) -> Path`

### `_read_image(real: Path, remaining_total: int) -> PromptImage`

### `_placeholder(ref: _Ref, reason: Reason) -> str`

### `prepare_prompt_images(prompt: str, task_id: str, roots: Sequence[Path]) -> PreparedPrompt`

Resolve the local images referenced by ``prompt``.

Every readable image becomes an entry of ``images`` and its reference is
rewritten to :func:`image_url`; every other local reference becomes a text
placeholder. ``roots`` are the already resolved allowed folders (see
:func:`resolve_allowed_dirs`).

### `encode_prompt_images(images: Sequence[PromptImage]) -> list[dict[str, str]]`

The JSON shape ``POST /api/tasks`` accepts for ``prompt_images``.

### `_decode_prompt_image(item: Any, remaining_total: int) -> PromptImage | None`

### `parse_prompt_images(raw: Any) -> tuple[PromptImage | None, ...]`

Validate the ``prompt_images`` field of a task payload.

The result keeps the positions of the request: an entry that is malformed,
not an image, or over a limit becomes ``None`` (so ``/images/<n>`` answers
404) instead of shifting the later images onto the wrong index. The MIME
type a client claims is ignored; only the bytes decide.

## 类

### `class Reason`

Why a reference was not turned into an image.

### `class PromptImage`

An image attached to a task: the sniffed MIME type and the raw bytes.

### `class SkippedImage`

A local reference that was replaced by a placeholder.

### `class PreparedPrompt`

A prompt after local images were resolved.

### `class _Ref`

### `class _Skip`

#### 方法

##### `__init__(self, reason: Reason) -> None`
