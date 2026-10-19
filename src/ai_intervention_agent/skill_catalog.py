"""Skill and slash-command catalogue behind the ``/`` picker of the feedback box.

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
"""

from __future__ import annotations

import os
import re
import threading
import time
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final, Literal, TypedDict

from ai_intervention_agent.dir_settings import (
    AUTO_TOKEN,
    expand_user,
    normalize_dir_list,
    safe_cwd,
    safe_home,
)
from ai_intervention_agent.enhanced_logging import EnhancedLogger

logger = EnhancedLogger(__name__)

DEFAULT_SKILL_DIRS: Final[tuple[str, ...]] = (AUTO_TOKEN,)
SKILL_FILE_NAME: Final = "SKILL.md"
COMMAND_DIR_NAMES: Final[frozenset[str]] = frozenset({"commands", "prompts"})

MAX_ENTRIES: Final = 1000
MAX_SCAN_DEPTH: Final = 4
MAX_DIR_ENTRIES: Final = 4000
MAX_FRONTMATTER_BYTES: Final = 16 * 1024
MAX_NAME_LENGTH: Final = 64
MAX_DESCRIPTION_LENGTH: Final = 300
SCAN_BUDGET_SECONDS: Final = 3.0
CACHE_TTL_SECONDS: Final = 30.0

_SKIPPED_DIR_NAMES: Final[frozenset[str]] = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        ".idea",
        ".vscode",
        ".venv",
        "venv",
        "node_modules",
        "__pycache__",
    }
)

_AUTO_LOCATIONS: Final[tuple[tuple[Literal["project", "user"], str], ...]] = (
    ("project", ".cursor/skills"),
    ("project", ".agents/skills"),
    ("project", ".claude/skills"),
    ("project", ".codex/skills"),
    ("project", ".cursor/commands"),
    ("project", ".claude/commands"),
    ("user", ".cursor/skills"),
    ("user", ".cursor/skills-cursor"),
    ("user", ".agents/skills"),
    ("user", ".claude/skills"),
    ("user", ".codex/skills"),
    ("user", ".cursor/commands"),
    ("user", ".claude/commands"),
    ("user", ".codex/prompts"),
)

_KEY_RE: Final = re.compile(r"^([A-Za-z0-9_.\-]+)[ \t]*:(?:[ \t]+(.*))?$")
_NESTED_START_RE: Final = re.compile(
    r"^(?:-(?:[ \t]|$)|[A-Za-z0-9_.\-]+[ \t]*:(?:[ \t]|$))"
)
_COMMENT_RE: Final = re.compile(r"[ \t]#.*$")
_WHITESPACE_RE: Final = re.compile(r"\s+")
_TOKEN_SEPARATOR_RE: Final = re.compile(r"[\s/\\]+")
_CONTROL_RE: Final = re.compile(r"[\x00-\x1f\x7f]")
_SLASH_SAFE_RE: Final = re.compile(r"[^\s/\\\x00-\x1f\x7f]+")
_TRIGGER_NAME_RE: Final = re.compile(
    r"(?:触发名|trigger[ \t]+name)[ \t]*[:：=][ \t]*[`'\"]?([A-Za-z0-9][A-Za-z0-9_.:\-]{0,63})",
    re.IGNORECASE,
)


class SkillEntry(TypedDict):
    """One row of the ``/`` picker."""

    name: str
    insert: str
    description: str
    kind: Literal["skill", "command"]
    source: str


class Catalog(TypedDict):
    """Result of :func:`get_catalog`."""

    skills: list[SkillEntry]
    truncated: bool


@dataclass(frozen=True)
class SkillRoot:
    """A directory to scan, with the role implied by its name."""

    path: Path
    kind: Literal["skill", "command"]
    label: str


def parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    """Split a Markdown document into ``(front matter scalars, body)``.

    Only top-level scalar keys survive: plain, single/double quoted and
    ``|`` / ``>`` block scalars (whitespace collapsed to single spaces).
    Nested mappings, lists and flow collections are skipped. A document
    without a leading ``---`` fence yields ``({}, text)``; an unterminated
    fence (for example a file cut at the read limit) is parsed up to the end.
    """
    lines = text.lstrip("\ufeff").replace("\r\n", "\n").replace("\r", "\n").split("\n")
    if not lines or lines[0].rstrip() != "---":
        return {}, "\n".join(lines)

    end = len(lines)
    for index in range(1, len(lines)):
        if lines[index].rstrip() in ("---", "..."):
            end = index
            break

    body = "\n".join(lines[end + 1 :]) if end < len(lines) else ""
    return _parse_mapping(lines[1:end]), body


def _parse_mapping(lines: Sequence[str]) -> dict[str, str]:
    result: dict[str, str] = {}
    index = 0
    while index < len(lines):
        line = lines[index]
        index += 1
        if not line.strip() or line[0] in " \t" or line.lstrip().startswith("#"):
            continue
        matched = _KEY_RE.match(line.rstrip())
        if matched is None:
            continue

        continuation: list[str] = []
        while index < len(lines) and (
            not lines[index].strip() or lines[index][0] in " \t"
        ):
            continuation.append(lines[index])
            index += 1

        value = _parse_scalar((matched.group(2) or "").strip(), continuation)
        if value is not None and matched.group(1) not in result:
            result[matched.group(1)] = _WHITESPACE_RE.sub(" ", value).strip()
    return result


def _parse_scalar(first: str, continuation: Sequence[str]) -> str | None:
    folded = [part.strip() for part in continuation if part.strip()]
    if first[:1] in ("|", ">"):
        return " ".join(folded)
    if first[:1] in ("[", "{"):
        return None
    if not first:
        if not folded or _NESTED_START_RE.match(folded[0]):
            return None
        return " ".join(_strip_comment(part) for part in folded)
    if first[0] in ("'", '"'):
        return _parse_quoted(" ".join([first, *folded]))
    return " ".join(_strip_comment(part) for part in [first, *folded])


def _strip_comment(text: str) -> str:
    return _COMMENT_RE.sub("", text).strip()


def _parse_quoted(text: str) -> str:
    quote = text[0]
    out: list[str] = []
    index = 1
    while index < len(text):
        char = text[index]
        if quote == "'":
            if char == "'":
                if text[index + 1 : index + 2] == "'":
                    out.append("'")
                    index += 2
                    continue
                break
            out.append(char)
            index += 1
            continue
        if char == '"':
            break
        if char == "\\" and index + 1 < len(text):
            escaped, index = _parse_escape(text, index + 1)
            out.append(escaped)
            continue
        out.append(char)
        index += 1
    return "".join(out)


_SIMPLE_ESCAPES: Final[Mapping[str, str]] = MappingProxyType(
    {
        "n": "\n",
        "t": "\t",
        "r": "\r",
        "0": "\0",
        '"': '"',
        "\\": "\\",
        "/": "/",
        " ": " ",
    }
)
_HEX_ESCAPE_LENGTHS: Final[Mapping[str, int]] = MappingProxyType(
    {"x": 2, "u": 4, "U": 8}
)


def _parse_escape(text: str, index: int) -> tuple[str, int]:
    char = text[index]
    if char in _SIMPLE_ESCAPES:
        return _SIMPLE_ESCAPES[char], index + 1
    width = _HEX_ESCAPE_LENGTHS.get(char)
    if width is not None:
        digits = text[index + 1 : index + 1 + width]
        if len(digits) == width and all(c in "0123456789abcdefABCDEF" for c in digits):
            try:
                return chr(int(digits, 16)), index + 1 + width
            except (ValueError, OverflowError):
                pass
    return char, index + 1


def _clip(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _clean_token(text: str) -> str:
    cleaned = _TOKEN_SEPARATOR_RE.sub("-", _CONTROL_RE.sub("", text).strip()).strip("-")
    return cleaned[:MAX_NAME_LENGTH].strip("-")


def slash_token(name: str, description: str, fallback: str) -> str:
    """Return the word inserted after ``/`` for a skill or command.

    ``name`` is the front-matter name, ``fallback`` the folder (or file) name.
    """
    hinted = _TRIGGER_NAME_RE.search(description)
    if hinted is not None:
        return hinted.group(1)
    for candidate in (name, fallback):
        if (
            candidate
            and len(candidate) <= MAX_NAME_LENGTH
            and _SLASH_SAFE_RE.fullmatch(candidate)
        ):
            return candidate
    return _clean_token(name) or _clean_token(fallback)


def _is_false(value: str | None) -> bool:
    return value is not None and value.strip().lower() in ("false", "no", "off", "0")


def _first_body_line(body: str) -> str:
    for line in body.split("\n"):
        stripped = line.strip().lstrip("#").strip()
        if stripped:
            return stripped
    return ""


def build_entry(
    text: str,
    fallback_name: str,
    kind: Literal["skill", "command"],
    source: str,
) -> SkillEntry | None:
    """Build a picker row from a ``SKILL.md`` / command file, or ``None`` to hide it."""
    meta, body = parse_frontmatter(text)
    if kind == "skill" and not meta:
        return None
    if _is_false(meta.get("user-invocable")):
        return None
    raw_name = meta.get("name") or fallback_name
    description = meta.get("description") or meta.get("when_to_use") or ""
    if not description and kind == "command":
        description = _first_body_line(body)
    token = slash_token(raw_name, description, fallback_name)
    if not token:
        return None
    return {
        "name": _clip(raw_name, MAX_NAME_LENGTH),
        "insert": token,
        "description": _clip(description, MAX_DESCRIPTION_LENGTH),
        "kind": kind,
        "source": source,
    }


def normalize_skill_dirs(value: Any) -> list[str]:
    """Coerce a ``skill_dirs`` setting into a bounded list of non-empty strings.

    ``None``, an unsupported type, or a non-empty list without a single usable
    entry falls back to ``["auto"]``; an explicit empty list stays empty and
    turns the picker off.
    """
    return normalize_dir_list(value, DEFAULT_SKILL_DIRS)


def _describe(path: Path, home: Path | None, cwd: Path | None) -> str:
    bases = [(base, prefix) for base, prefix in ((home, "~"), (cwd, ".")) if base]
    bases.sort(key=lambda item: len(item[0].parts), reverse=True)
    for base, prefix in bases:
        try:
            relative = path.relative_to(base)
        except ValueError:
            continue
        return f"{prefix}/{relative.as_posix()}" if relative.parts else prefix
    parts = path.parts[-2:]
    return "/".join(parts) if parts else str(path)


def _role_of(path: Path) -> Literal["skill", "command"]:
    return "command" if path.name.lower() in COMMAND_DIR_NAMES else "skill"


def _identity(path: Path) -> str:
    try:
        return os.path.normcase(os.path.realpath(path))
    except OSError:
        return os.path.normcase(str(path))


def resolve_skill_roots(
    configured: Any,
    *,
    home: Path | None = None,
    cwd: Path | None = None,
) -> list[SkillRoot]:
    """Turn a ``skill_dirs`` setting into existing directories, in priority order."""
    home = home if home is not None else safe_home()
    cwd = cwd if cwd is not None else safe_cwd()

    candidates: list[Path] = []
    auto_expanded = False
    for entry in normalize_skill_dirs(configured):
        if entry.lower() == AUTO_TOKEN:
            if auto_expanded:
                continue
            auto_expanded = True
            for scope, relative in _AUTO_LOCATIONS:
                base = cwd if scope == "project" else home
                if base is not None:
                    candidates.append(base / relative)
            continue
        path = expand_user(entry, home)
        if path is None:
            continue
        if not path.is_absolute():
            if cwd is None:
                continue
            path = cwd / path
        candidates.append(path)

    roots: list[SkillRoot] = []
    seen: set[str] = set()
    for path in candidates:
        try:
            if not path.is_dir():
                continue
        except OSError:
            continue
        identity = _identity(path)
        if identity in seen:
            continue
        seen.add(identity)
        roots.append(SkillRoot(path, _role_of(path), _describe(path, home, cwd)))
    return roots


def _read_head(path: Path) -> str | None:
    try:
        with open(path, "rb") as handle:
            return handle.read(MAX_FRONTMATTER_BYTES).decode("utf-8", errors="replace")
    except OSError:
        return None


def _list_dir(directory: Path) -> list[os.DirEntry[str]]:
    try:
        with os.scandir(directory) as iterator:
            entries: list[os.DirEntry[str]] = []
            for entry in iterator:
                entries.append(entry)
                if len(entries) >= MAX_DIR_ENTRIES:
                    break
    except OSError:
        return []
    entries.sort(key=lambda item: item.name)
    return entries


def _is_dir(entry: os.DirEntry[str]) -> bool:
    try:
        return entry.is_dir()
    except OSError:
        return False


def _is_file(entry: os.DirEntry[str]) -> bool:
    try:
        return entry.is_file()
    except OSError:
        return False


def _walk_skill_files(
    root: Path, deadline: float, clock: Callable[[], float]
) -> Iterator[Path]:
    visited: set[tuple[int, int]] = set()
    stack: list[tuple[Path, int]] = [(root, 0)]
    while stack:
        if clock() > deadline:
            return
        directory, depth = stack.pop()
        try:
            stat = os.stat(directory)
        except OSError:
            continue
        identity = (stat.st_dev, stat.st_ino)
        if identity in visited:
            continue
        visited.add(identity)

        subdirectories: list[Path] = []
        skill_file: Path | None = None
        for entry in _list_dir(directory):
            if entry.name == SKILL_FILE_NAME:
                if _is_file(entry):
                    skill_file = Path(entry.path)
            elif (
                depth < MAX_SCAN_DEPTH
                and entry.name not in _SKIPPED_DIR_NAMES
                and _is_dir(entry)
            ):
                subdirectories.append(Path(entry.path))
        if skill_file is not None:
            yield skill_file
        stack.extend((path, depth + 1) for path in reversed(subdirectories))


def _scan_skill_root(
    root: SkillRoot, deadline: float, clock: Callable[[], float]
) -> Iterator[SkillEntry]:
    for skill_file in _walk_skill_files(root.path, deadline, clock):
        text = _read_head(skill_file)
        if text is None:
            continue
        entry = build_entry(text, skill_file.parent.name, "skill", root.label)
        if entry is not None:
            yield entry


def _scan_command_root(
    root: SkillRoot, deadline: float, clock: Callable[[], float]
) -> Iterator[SkillEntry]:
    for item in _list_dir(root.path):
        if clock() > deadline:
            return
        name = item.name
        if (
            name.startswith(".")
            or not name.lower().endswith(".md")
            or not _is_file(item)
        ):
            continue
        text = _read_head(Path(item.path))
        if text is None:
            continue
        entry = build_entry(text, name[:-3], "command", root.label)
        if entry is not None:
            yield entry


def scan_roots(
    roots: Sequence[SkillRoot],
    *,
    limit: int = MAX_ENTRIES,
    budget: float = SCAN_BUDGET_SECONDS,
    clock: Callable[[], float] = time.monotonic,
) -> Catalog:
    """Scan ``roots`` in order; the first root defining a token wins."""
    deadline = clock() + budget
    entries: list[SkillEntry] = []
    seen: set[str] = set()
    truncated = False
    for root in roots:
        scanner = _scan_command_root if root.kind == "command" else _scan_skill_root
        for entry in scanner(root, deadline, clock):
            key = entry["insert"].casefold()
            if key in seen:
                continue
            if len(entries) >= limit:
                truncated = True
                break
            seen.add(key)
            entries.append(entry)
        if truncated:
            break
        if clock() > deadline:
            truncated = True
            break
    entries.sort(key=lambda item: (item["insert"].casefold(), item["kind"]))
    return {"skills": entries, "truncated": truncated}


_cache_lock = threading.Lock()
_cache_key: tuple[tuple[str, str], ...] | None = None
_cache_value: Catalog | None = None
_cache_stamp: float = 0.0


def invalidate_cache() -> None:
    """Forget the cached catalogue (tests and config reloads)."""
    global _cache_key, _cache_value
    with _cache_lock:
        _cache_key = None
        _cache_value = None


def get_catalog(
    configured: Any = None,
    *,
    home: Path | None = None,
    cwd: Path | None = None,
    ttl: float = CACHE_TTL_SECONDS,
    clock: Callable[[], float] = time.monotonic,
) -> Catalog:
    """Return the catalogue for a ``skill_dirs`` setting, cached for ``ttl`` seconds."""
    global _cache_key, _cache_value, _cache_stamp
    roots = resolve_skill_roots(configured, home=home, cwd=cwd)
    key = tuple((str(root.path), root.kind) for root in roots)
    with _cache_lock:
        now = clock()
        if (
            _cache_value is not None
            and _cache_key == key
            and 0 <= now - _cache_stamp < ttl
        ):
            return _cache_value
        try:
            catalog = scan_roots(roots, clock=clock)
        except Exception as exc:
            logger.warning(f"Skill catalogue scan failed: {exc}")
            return {"skills": [], "truncated": False}
        _cache_key = key
        _cache_value = catalog
        _cache_stamp = clock()
        return catalog
