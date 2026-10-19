"""Local images inside a prompt: find them, check them, read them.

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
"""

from __future__ import annotations

import base64
import binascii
import html
import os
import re
import stat
from bisect import bisect_right
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any, Final
from urllib.parse import quote, unquote, urlsplit

from ai_intervention_agent.dir_settings import (
    AUTO_TOKEN,
    expand_user,
    normalize_dir_list,
    safe_cwd,
    safe_home,
)

DEFAULT_IMAGE_DIRS: Final[tuple[str, ...]] = (AUTO_TOKEN,)

MAX_IMAGES: Final = 8
MAX_IMAGE_BYTES: Final = 8 * 1024 * 1024
MAX_TOTAL_BYTES: Final = 16 * 1024 * 1024

_MAX_REFS_SCANNED: Final = 256
_MAX_ALT_CHARS: Final = 300
_MAX_DEST_CHARS: Final = 2048
_MAX_TITLE_CHARS: Final = 300
_MAX_IMG_TAG_CHARS: Final = 4096
_MAX_PLACEHOLDER_REF_CHARS: Final = 120

_EXTENSIONS: Final[frozenset[str]] = frozenset(
    {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".avif"}
)
_BMP_DIB_SIZES: Final[frozenset[int]] = frozenset({12, 40, 52, 56, 64, 108, 124})
_SNIFF_BYTES: Final = 32

_ASCII_PUNCTUATION: Final = frozenset("!\"#$%&'()*+,-./:;<=>?@[\\]^_`{|}~")
_WHITESPACE: Final = " \t\r\n"

_IMG_TAG_RE: Final = re.compile(
    rf"<img\b[^<>]{{0,{_MAX_IMG_TAG_CHARS}}}>", re.IGNORECASE
)
_SRC_ATTR_RE: Final = re.compile(
    r"""(?<![\w:.\-])src[ \t\r\n]*=[ \t\r\n]*(?:"([^"]*)"|'([^']*)'|([^\s"'<>=`]+))""",
    re.IGNORECASE,
)
_SCHEME_RE: Final = re.compile(r"[A-Za-z][A-Za-z0-9+.\-]*:")
_DRIVE_RE: Final = re.compile(r"[A-Za-z]:[\\/]")
_WINDOWS_URI_DRIVE_RE: Final = re.compile(r"/[A-Za-z]:")
_FENCE_RE: Final = re.compile(r"(`{3,}|~{3,})([^\n]*)")
_PARAGRAPH_BREAK_RE: Final = re.compile(r"\n[ \t]*\n")
_PLACEHOLDER_UNSAFE_RE: Final = re.compile(r"[`|\x00-\x1f\x7f]")


class Reason(StrEnum):
    """Why a reference was not turned into an image."""

    OUTSIDE = "outside the allowed folders"
    NOT_FOUND = "file not found"
    NOT_IMAGE = "not a png, jpg, gif, webp, bmp or avif image"
    TOO_LARGE = (
        f"too large (max {MAX_IMAGE_BYTES >> 20} MB each, "
        f"{MAX_TOTAL_BYTES >> 20} MB per prompt)"
    )
    TOO_MANY = f"more than {MAX_IMAGES} images in one prompt"
    UNREADABLE = "cannot be read"


@dataclass(frozen=True, slots=True)
class PromptImage:
    """An image attached to a task: the sniffed MIME type and the raw bytes."""

    mime_type: str
    data: bytes


@dataclass(frozen=True, slots=True)
class SkippedImage:
    """A local reference that was replaced by a placeholder."""

    ref: str
    reason: Reason


@dataclass(frozen=True, slots=True)
class PreparedPrompt:
    """A prompt after local images were resolved."""

    prompt: str
    images: tuple[PromptImage, ...] = ()
    skipped: tuple[SkippedImage, ...] = ()


@dataclass(frozen=True, slots=True)
class _Ref:
    full_start: int
    full_end: int
    dest_start: int
    dest_end: int
    dest: str
    markdown: bool


class _Skip(Exception):
    def __init__(self, reason: Reason) -> None:
        super().__init__(reason.value)
        self.reason = reason


def normalize_image_dirs(value: Any) -> list[str]:
    """Coerce a ``local_image_dirs`` setting into a bounded list of strings.

    ``None``, an unsupported type, or a non-empty list without a single usable
    entry falls back to ``["auto"]``; an explicit empty list stays empty and
    turns local images off.
    """
    return normalize_dir_list(value, DEFAULT_IMAGE_DIRS)


def image_url(task_id: str, index: int) -> str:
    """The URL under which the Web UI serves image ``index`` of ``task_id``."""
    return f"/api/tasks/{quote(task_id, safe='')}/images/{index}"


def has_image_candidates(prompt: str) -> bool:
    """Cheap pre-check: does the prompt contain anything that looks like an image?"""
    return "![" in prompt or "<img" in prompt.lower()


def sniff_image_mime(head: bytes) -> str | None:
    """The MIME type the leading bytes of a file declare, or ``None``."""
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if head.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if head.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if len(head) >= 12 and head.startswith(b"RIFF") and head[8:12] == b"WEBP":
        return "image/webp"
    if (
        len(head) >= 18
        and head.startswith(b"BM")
        and int.from_bytes(head[14:18], "little") in _BMP_DIB_SIZES
    ):
        return "image/bmp"
    if len(head) >= 12 and head[4:8] == b"ftyp" and head[8:12] in (b"avif", b"avis"):
        return "image/avif"
    return None


def file_uri_to_path(uri: str) -> Path | None:
    """Convert a ``file://`` URI (as sent in MCP roots) to a path, else ``None``."""
    try:
        parts = urlsplit(uri)
    except ValueError:
        return None
    if parts.scheme.lower() != "file" or parts.netloc not in ("", "localhost"):
        return None
    path = unquote(parts.path)
    if os.name == "nt" and _WINDOWS_URI_DRIVE_RE.match(path):
        path = path[1:]
    if not path or "\x00" in path:
        return None
    return Path(path)


def _realpath(path: Path) -> Path | None:
    try:
        return Path(os.path.realpath(path))
    except (OSError, ValueError):
        return None


def _is_inside(path: Path, root: Path) -> bool:
    for candidate in (path, *path.parents):
        if candidate == root:
            return True
        try:
            if candidate.samefile(root):
                return True
        except OSError:
            continue
    return False


def _temp_dirs() -> list[Path]:
    import tempfile

    dirs = [Path(tempfile.gettempdir())]
    if os.name != "nt":
        dirs.append(Path("/tmp"))
    return dirs


def resolve_allowed_dirs(
    setting: Any,
    client_roots: Sequence[Path] = (),
    *,
    cwd: Path | None = None,
    home: Path | None = None,
) -> list[Path]:
    """Turn a ``local_image_dirs`` setting into existing, real directories.

    ``"auto"`` expands to the client's workspace folders (the working directory
    stands in when the client declares none and it is neither a filesystem root
    nor the home directory) plus the system temporary directory; any other entry
    is a directory where ``~`` is expanded and a relative path is resolved
    against the working directory. Entries that do not exist and filesystem
    roots are dropped.
    """
    home = home if home is not None else safe_home()
    cwd = cwd if cwd is not None else safe_cwd()

    candidates: list[Path] = []
    auto_expanded = False
    for entry in normalize_image_dirs(setting):
        if entry.lower() == AUTO_TOKEN:
            if auto_expanded:
                continue
            auto_expanded = True
            candidates.extend(client_roots)
            if not client_roots and cwd is not None and cwd not in (cwd.parent, home):
                candidates.append(cwd)
            candidates.extend(_temp_dirs())
            continue
        path = expand_user(entry, home)
        if path is None:
            continue
        if not path.is_absolute():
            if cwd is None:
                continue
            path = cwd / path
        candidates.append(path)

    roots: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        real = _realpath(candidate)
        if real is None or real == real.parent:
            continue
        try:
            if not real.is_dir():
                continue
        except OSError:
            continue
        key = os.path.normcase(str(real))
        if key in seen:
            continue
        seen.add(key)
        roots.append(real)
    return roots


def _code_ranges(text: str) -> list[tuple[int, int]]:
    """Half-open spans of fenced code blocks and inline code spans, sorted."""
    fenced: list[tuple[int, int]] = []
    outside: list[tuple[int, int]] = []
    length = len(text)
    position = 0
    outside_start = 0
    fence_char = ""
    fence_len = 0
    fence_start = 0
    while position < length:
        newline = text.find("\n", position)
        line_end = length if newline < 0 else newline
        line = text[position:line_end]
        body = line.lstrip(" ")
        indented_ok = len(line) - len(body) <= 3
        match = _FENCE_RE.match(body) if indented_ok else None
        if fence_char:
            if (
                match
                and match.group(1)[0] == fence_char
                and len(match.group(1)) >= fence_len
                and not match.group(2).strip()
            ):
                fenced.append((fence_start, min(length, line_end + 1)))
                fence_char = ""
                outside_start = min(length, line_end + 1)
        elif match and not (match.group(1)[0] == "`" and "`" in match.group(2)):
            outside.append((outside_start, position))
            fence_char = match.group(1)[0]
            fence_len = len(match.group(1))
            fence_start = position
        position = line_end + 1
    if fence_char:
        fenced.append((fence_start, length))
    else:
        outside.append((outside_start, length))

    spans = list(fenced)
    for start, end in outside:
        segment = text[start:end]
        paragraph_start = 0
        for boundary in (*_PARAGRAPH_BREAK_RE.finditer(segment), None):
            paragraph_end = len(segment) if boundary is None else boundary.start()
            spans.extend(
                (start + a, start + b)
                for a, b in _inline_code_spans(
                    segment[paragraph_start:paragraph_end], paragraph_start
                )
            )
            if boundary is not None:
                paragraph_start = boundary.end()
    spans.sort()
    return spans


def _inline_code_spans(paragraph: str, offset: int) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    length = len(paragraph)
    index = 0
    while True:
        opener = paragraph.find("`", index)
        if opener < 0:
            break
        run_end = opener
        while run_end < length and paragraph[run_end] == "`":
            run_end += 1
        run = run_end - opener
        scan = run_end
        close = -1
        while True:
            candidate = paragraph.find("`", scan)
            if candidate < 0:
                break
            candidate_end = candidate
            while candidate_end < length and paragraph[candidate_end] == "`":
                candidate_end += 1
            if candidate_end - candidate == run:
                close = candidate_end
                break
            scan = candidate_end
        if close < 0:
            index = run_end
        else:
            spans.append((offset + opener, offset + close))
            index = close
    return spans


def _in_code(position: int, spans: list[tuple[int, int]], starts: list[int]) -> bool:
    slot = bisect_right(starts, position) - 1
    return slot >= 0 and spans[slot][0] <= position < spans[slot][1]


def _skip_whitespace(text: str, index: int) -> int:
    length = len(text)
    while index < length and text[index] in _WHITESPACE:
        index += 1
    return index


def _unescape_markdown(text: str) -> str:
    if "\\" not in text:
        return text
    out: list[str] = []
    index = 0
    while index < len(text):
        char = text[index]
        if (
            char == "\\"
            and index + 1 < len(text)
            and text[index + 1] in _ASCII_PUNCTUATION
        ):
            out.append(text[index + 1])
            index += 2
        else:
            out.append(char)
            index += 1
    return "".join(out)


def _match_markdown_image(text: str, bang: int) -> _Ref | None:
    length = len(text)
    index = bang + 2
    depth = 1
    limit = min(length, index + _MAX_ALT_CHARS)
    while index < limit:
        char = text[index]
        if char == "\\":
            index += 2
            continue
        if char == "[":
            depth += 1
        elif char == "]":
            depth -= 1
            if depth == 0:
                break
        index += 1
    else:
        return None
    index += 1
    if index >= length or text[index] != "(":
        return None
    index = _skip_whitespace(text, index + 1)
    if index >= length:
        return None

    if text[index] == "<":
        cursor = index + 1
        end = min(length, cursor + _MAX_DEST_CHARS)
        while cursor < end and text[cursor] not in "<>\n":
            cursor += 2 if text[cursor] == "\\" else 1
        if cursor >= end or text[cursor] != ">":
            return None
        dest_start, dest_end = index, cursor + 1
        raw = text[index + 1 : cursor]
        index = cursor + 1
    else:
        cursor = index
        end = min(length, cursor + _MAX_DEST_CHARS)
        parens = 0
        while cursor < end:
            char = text[cursor]
            if char == "\\":
                cursor += 2
                continue
            if char in _WHITESPACE or ord(char) < 0x20:
                break
            if char == "(":
                parens += 1
            elif char == ")":
                if parens == 0:
                    break
                parens -= 1
            cursor += 1
        if parens or cursor == index or cursor > end or (cursor == end < length):
            return None
        dest_start, dest_end = index, cursor
        raw = text[index:cursor]
        index = cursor

    index = _skip_whitespace(text, index)
    if index < length and text[index] in "\"'(":
        closer = ")" if text[index] == "(" else text[index]
        cursor = index + 1
        end = min(length, cursor + _MAX_TITLE_CHARS)
        while cursor < end and text[cursor] != closer:
            cursor += 2 if text[cursor] == "\\" else 1
        if cursor >= end or text[cursor] != closer:
            return None
        index = _skip_whitespace(text, cursor + 1)
    if index >= length or text[index] != ")":
        return None
    return _Ref(bang, index + 1, dest_start, dest_end, _unescape_markdown(raw), True)


def _find_refs(text: str) -> list[_Ref]:
    if not has_image_candidates(text):
        return []
    spans = _code_ranges(text)
    starts = [span[0] for span in spans]

    refs: list[_Ref] = []
    examined = 0
    cursor = 0
    while examined < _MAX_REFS_SCANNED:
        bang = text.find("![", cursor)
        if bang < 0:
            break
        cursor = bang + 2
        if _in_code(bang, spans, starts):
            continue
        examined += 1
        backslashes = 0
        while bang - backslashes - 1 >= 0 and text[bang - backslashes - 1] == "\\":
            backslashes += 1
        if backslashes % 2:
            continue
        ref = _match_markdown_image(text, bang)
        if ref is not None:
            refs.append(ref)

    examined = 0
    for tag in _IMG_TAG_RE.finditer(text):
        if examined >= _MAX_REFS_SCANNED:
            break
        if _in_code(tag.start(), spans, starts):
            continue
        examined += 1
        source = _SRC_ATTR_RE.search(tag.group(0))
        if source is None:
            continue
        group = next(index for index in (1, 2, 3) if source.group(index) is not None)
        refs.append(
            _Ref(
                tag.start(),
                tag.end(),
                tag.start() + source.start(group),
                tag.start() + source.end(group),
                html.unescape(source.group(group)),
                False,
            )
        )

    refs.sort(key=lambda ref: ref.full_start)
    kept: list[_Ref] = []
    last_end = 0
    for ref in refs:
        if ref.full_start >= last_end:
            kept.append(ref)
            last_end = ref.full_end
    return kept


def _spellings(text: str) -> list[str]:
    spellings = [text]
    trimmed = text.split("#", 1)[0].split("?", 1)[0]
    if trimmed and trimmed != text:
        spellings.append(trimmed)
    for spelling in tuple(spellings):
        decoded = unquote(spelling)
        if decoded not in spellings:
            spellings.append(decoded)
    return spellings


def _local_spellings(dest: str) -> list[str] | None:
    """Path spellings for a local destination; ``None`` when it is not local."""
    text = dest.strip()
    if not text or text[0] == "#" or text.startswith("//"):
        return None
    if _DRIVE_RE.match(text):
        return _spellings(text)
    scheme = _SCHEME_RE.match(text)
    if scheme is None:
        return _spellings(text)
    if scheme.group(0)[:-1].lower() != "file":
        return None
    path = file_uri_to_path(text)
    return [] if path is None else [str(path)]


def _candidate_paths(spelling: str, roots: Sequence[Path]) -> list[Path]:
    if spelling == "~" or spelling.startswith(("~/", "~\\")):
        home = safe_home()
        return [] if home is None else [home / spelling[2:]]
    if spelling.startswith("~"):
        return []
    path = Path(spelling)
    if path.is_absolute():
        return [path]
    return [root / path for root in roots]


def _locate(spellings: Sequence[str], roots: Sequence[Path]) -> Path:
    if not spellings:
        raise _Skip(Reason.OUTSIDE)
    inside_missing = False
    outside = False
    for spelling in spellings:
        if spelling.startswith(("\\\\", "//")):
            outside = True
            continue
        if not spelling or "\x00" in spelling or len(spelling) > _MAX_DEST_CHARS:
            continue
        for path in _candidate_paths(spelling, roots):
            real = _realpath(path)
            if real is None:
                continue
            if not any(_is_inside(real, root) for root in roots):
                outside = True
                continue
            try:
                if real.is_file():
                    return real
            except OSError:
                continue
            inside_missing = True
    raise _Skip(Reason.OUTSIDE if outside and not inside_missing else Reason.NOT_FOUND)


def _read_image(real: Path, remaining_total: int) -> PromptImage:
    if real.suffix.lower() not in _EXTENSIONS:
        raise _Skip(Reason.NOT_IMAGE)
    flags = os.O_RDONLY
    for name in ("O_NOFOLLOW", "O_NONBLOCK", "O_CLOEXEC", "O_BINARY"):
        flags |= getattr(os, name, 0)
    try:
        descriptor = os.open(real, flags)
    except FileNotFoundError:
        raise _Skip(Reason.NOT_FOUND) from None
    except OSError:
        raise _Skip(Reason.UNREADABLE) from None
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode):
            raise _Skip(Reason.NOT_IMAGE)
        limit = min(MAX_IMAGE_BYTES, remaining_total)
        if info.st_size > limit:
            raise _Skip(Reason.TOO_LARGE)
        again = _realpath(real)
        if again is None or again != real:
            raise _Skip(Reason.UNREADABLE)
        try:
            current = os.stat(again)
        except OSError:
            raise _Skip(Reason.UNREADABLE) from None
        if (current.st_dev, current.st_ino) != (info.st_dev, info.st_ino):
            raise _Skip(Reason.UNREADABLE)
        chunks: list[bytes] = []
        left = limit + 1
        while left > 0:
            try:
                chunk = os.read(descriptor, min(left, 1 << 20))
            except OSError:
                raise _Skip(Reason.UNREADABLE) from None
            if not chunk:
                break
            chunks.append(chunk)
            left -= len(chunk)
    finally:
        os.close(descriptor)
    data = b"".join(chunks)
    if len(data) > limit:
        raise _Skip(Reason.TOO_LARGE)
    mime = sniff_image_mime(data[:_SNIFF_BYTES])
    if mime is None:
        raise _Skip(Reason.NOT_IMAGE)
    return PromptImage(mime, data)


def _placeholder(ref: _Ref, reason: Reason) -> str:
    shown = _PLACEHOLDER_UNSAFE_RE.sub(" ", ref.dest.strip())
    if len(shown) > _MAX_PLACEHOLDER_REF_CHARS:
        shown = shown[: _MAX_PLACEHOLDER_REF_CHARS - 1] + "…"
    if ref.markdown:
        return f"🖼️ *(image not shown: {reason.value}) `{shown}`*"
    return html.escape(f"🖼️ (image not shown: {reason.value}) {shown}")


def prepare_prompt_images(
    prompt: str,
    task_id: str,
    roots: Sequence[Path],
) -> PreparedPrompt:
    """Resolve the local images referenced by ``prompt``.

    Every readable image becomes an entry of ``images`` and its reference is
    rewritten to :func:`image_url`; every other local reference becomes a text
    placeholder. ``roots`` are the already resolved allowed folders (see
    :func:`resolve_allowed_dirs`).
    """
    refs = _find_refs(prompt)
    if not refs:
        return PreparedPrompt(prompt)

    images: list[PromptImage] = []
    index_by_path: dict[str, int] = {}
    skipped: list[SkippedImage] = []
    total = 0
    edits: list[tuple[int, int, str]] = []
    for ref in refs:
        spellings = _local_spellings(ref.dest)
        if spellings is None:
            continue
        try:
            real = _locate(spellings, roots)
            key = os.path.normcase(str(real))
            index = index_by_path.get(key)
            if index is None:
                if len(images) >= MAX_IMAGES:
                    raise _Skip(Reason.TOO_MANY)
                image = _read_image(real, MAX_TOTAL_BYTES - total)
                index = len(images)
                images.append(image)
                index_by_path[key] = index
                total += len(image.data)
        except _Skip as skip:
            skipped.append(SkippedImage(ref.dest, skip.reason))
            edits.append((ref.full_start, ref.full_end, _placeholder(ref, skip.reason)))
            continue
        edits.append((ref.dest_start, ref.dest_end, image_url(task_id, index)))

    if not edits:
        return PreparedPrompt(prompt)
    pieces: list[str] = []
    cursor = 0
    for start, end, replacement in edits:
        pieces.append(prompt[cursor:start])
        pieces.append(replacement)
        cursor = end
    pieces.append(prompt[cursor:])
    return PreparedPrompt("".join(pieces), tuple(images), tuple(skipped))


def encode_prompt_images(images: Sequence[PromptImage]) -> list[dict[str, str]]:
    """The JSON shape ``POST /api/tasks`` accepts for ``prompt_images``."""
    return [
        {
            "mime_type": image.mime_type,
            "data": base64.b64encode(image.data).decode("ascii"),
        }
        for image in images
    ]


def _decode_prompt_image(item: Any, remaining_total: int) -> PromptImage | None:
    if not isinstance(item, dict):
        return None
    encoded = item.get("data")
    limit = min(MAX_IMAGE_BYTES, remaining_total)
    if not isinstance(encoded, str) or not encoded or len(encoded) > limit * 4 // 3 + 8:
        return None
    try:
        data = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError):
        return None
    if not data or len(data) > limit:
        return None
    mime = sniff_image_mime(data[:_SNIFF_BYTES])
    return None if mime is None else PromptImage(mime, data)


def parse_prompt_images(raw: Any) -> tuple[PromptImage | None, ...]:
    """Validate the ``prompt_images`` field of a task payload.

    The result keeps the positions of the request: an entry that is malformed,
    not an image, or over a limit becomes ``None`` (so ``/images/<n>`` answers
    404) instead of shifting the later images onto the wrong index. The MIME
    type a client claims is ignored; only the bytes decide.
    """
    if not isinstance(raw, list):
        return ()
    images: list[PromptImage | None] = []
    total = 0
    for item in raw[:MAX_IMAGES]:
        image = _decode_prompt_image(item, MAX_TOTAL_BYTES - total)
        if image is not None:
            total += len(image.data)
        images.append(image)
    return tuple(images)
