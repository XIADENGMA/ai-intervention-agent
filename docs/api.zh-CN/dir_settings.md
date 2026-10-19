# dir_settings

> 英文 signature-only 版本（仅函数 / 类签名速查）：[`docs/api/dir_settings.md`](../api/dir_settings.md)

Shared handling of directory-list settings such as ``[feedback] skill_dirs``.

Several ``[feedback]`` keys name directories the same way: the token ``"auto"``
stands for a built-in set of locations, every other entry is a directory where
``~`` is expanded and a relative path is resolved against the working
directory, and an explicit empty list switches the feature off. This module
holds the pieces those keys have in common: normalising the raw TOML value and
expanding one entry.

## 函数

### `normalize_dir_list(value: Any, default: Sequence[str]) -> list[str]`

Coerce a directory-list setting into a bounded list of non-empty strings.

``None``, an unsupported type, or a non-empty list without a single usable
entry falls back to ``default``; an explicit empty list stays empty so the
feature it configures can be turned off.

### `safe_home() -> Path | None`

The user's home directory, or ``None`` when it cannot be determined.

### `safe_cwd() -> Path | None`

The working directory, or ``None`` when it no longer exists.

### `expand_user(entry: str, home: Path | None) -> Path | None`

Expand a leading ``~`` against ``home``; ``None`` when that is impossible.
