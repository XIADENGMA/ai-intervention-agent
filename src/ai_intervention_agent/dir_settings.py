"""Shared handling of directory-list settings such as ``[feedback] skill_dirs``.

Several ``[feedback]`` keys name directories the same way: the token ``"auto"``
stands for a built-in set of locations, every other entry is a directory where
``~`` is expanded and a relative path is resolved against the working
directory, and an explicit empty list switches the feature off. This module
holds the pieces those keys have in common: normalising the raw TOML value and
expanding one entry.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any, Final

AUTO_TOKEN: Final = "auto"
MAX_CONFIGURED_DIRS: Final = 32
MAX_PATH_LENGTH: Final = 1024


def normalize_dir_list(value: Any, default: Sequence[str]) -> list[str]:
    """Coerce a directory-list setting into a bounded list of non-empty strings.

    ``None``, an unsupported type, or a non-empty list without a single usable
    entry falls back to ``default``; an explicit empty list stays empty so the
    feature it configures can be turned off.
    """
    if value is None:
        return list(default)
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, (list, tuple)):
        return list(default)
    cleaned: list[str] = []
    for item in value:
        if not isinstance(item, str):
            continue
        text = item.strip()
        if not text or len(text) > MAX_PATH_LENGTH or "\x00" in text:
            continue
        cleaned.append(text)
        if len(cleaned) >= MAX_CONFIGURED_DIRS:
            break
    if not cleaned and value:
        return list(default)
    return cleaned


def safe_home() -> Path | None:
    """The user's home directory, or ``None`` when it cannot be determined."""
    try:
        return Path.home()
    except (RuntimeError, OSError):
        return None


def safe_cwd() -> Path | None:
    """The working directory, or ``None`` when it no longer exists."""
    try:
        return Path.cwd()
    except OSError:
        return None


def expand_user(entry: str, home: Path | None) -> Path | None:
    """Expand a leading ``~`` against ``home``; ``None`` when that is impossible."""
    if entry == "~" or entry.startswith(("~/", "~\\")):
        return None if home is None else home / entry[2:]
    try:
        return Path(entry).expanduser()
    except RuntimeError:
        return None
