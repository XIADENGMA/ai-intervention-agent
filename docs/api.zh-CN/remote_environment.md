# remote_environment

> 英文 signature-only 版本（仅函数 / 类签名速查）：[`docs/api/remote_environment.md`](../api/remote_environment.md)

R225 / Cycle 12: SSH / WSL remote-environment detection.

## 函数

### `_detect_ssh() -> tuple[bool, str | None]`

SSH detection via ``sshd``-propagated env vars.

### `_detect_wsl() -> tuple[bool, str | None]`

WSL detection via env vars (WSL2) plus ``/proc/version`` fallback.

### `detect_remote_environment() -> RemoteEnvironment`

Public entry-point. See module docstring for invariants.

## 类

### `class RemoteEnvironment`

Detection result schema. Keys are stable contract for tests
and for the startup banner integration in ``web_ui.py``.
