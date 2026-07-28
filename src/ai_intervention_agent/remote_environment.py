"""R225 / Cycle 12: SSH / WSL remote-environment detection."""

from __future__ import annotations

import os
from typing import TypedDict


class RemoteEnvironment(TypedDict):
    """Detection result schema. Keys are stable contract for tests
    and for the startup banner integration in ``web_ui.py``."""

    is_ssh: bool
    is_wsl: bool
    ssh_source: str | None
    wsl_source: str | None


_PROC_VERSION_PATH: str = "/proc/version"


def _detect_ssh() -> tuple[bool, str | None]:
    """SSH detection via ``sshd``-propagated env vars."""
    for var in ("SSH_CONNECTION", "SSH_CLIENT"):
        val = os.environ.get(var)
        if val and val.strip():
            return True, var
    return False, None


def _detect_wsl() -> tuple[bool, str | None]:
    """WSL detection via env vars (WSL2) plus ``/proc/version`` fallback."""
    for var in ("WSL_DISTRO_NAME", "WSL_INTEROP"):
        val = os.environ.get(var)
        if val and val.strip():
            return True, var
    try:
        with open(_PROC_VERSION_PATH, encoding="utf-8") as fh:
            if "microsoft" in fh.read().lower():
                return True, _PROC_VERSION_PATH
    except (OSError, UnicodeDecodeError):
        pass
    return False, None


def detect_remote_environment() -> RemoteEnvironment:
    """Public entry-point. See module docstring for invariants."""
    is_ssh, ssh_source = _detect_ssh()
    is_wsl, wsl_source = _detect_wsl()
    return {
        "is_ssh": is_ssh,
        "is_wsl": is_wsl,
        "ssh_source": ssh_source,
        "wsl_source": wsl_source,
    }
