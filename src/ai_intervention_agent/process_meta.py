"""Process facts that the MCP server and the Web UI process both report.

Two things live here, in a module that needs nothing but the standard library:

* ``PROCESS_STARTED_AT_UNIX`` — the wall-clock time this process started: the moment
  this module is first imported, which the entry modules (``server`` and ``web_ui``)
  do before any heavy import, so the figure includes their import time;
* ``resolve_build_info()`` — the git commit / branch / dirty flag of the running
  checkout, read once and cached.

They are not in ``server.py`` because ``/api/system/health`` and
``/api/system/metrics`` are answered by the Web UI subprocess, and importing
``server`` there loads the whole MCP stack (fastmcp, mcp, pydantic, starlette,
uvicorn, cryptography, ... about 570 modules, roughly 40 MiB) into a process that
never uses it. It also made "the start time" the moment of the first request, so
``uptime_seconds`` of a Web UI that had been running for hours read a fraction of a
second.
"""

from __future__ import annotations

__all__ = [
    "PROCESS_STARTED_AT_UNIX",
    "reset_build_info_cache_for_testing",
    "resolve_build_info",
]

import threading
import time

PROCESS_STARTED_AT_UNIX: float = time.time()
"""Wall-clock time (``time.time()``) of the first import of this module."""

_BUILD_INFO_CACHE: dict[str, str] = {}
_BUILD_INFO_CACHE_LOCK: threading.Lock = threading.Lock()


def resolve_build_info() -> dict[str, str]:
    """返回 ``{git_commit, git_branch, git_dirty}``，失败字段填 ``"unknown"``。"""
    global _BUILD_INFO_CACHE
    if _BUILD_INFO_CACHE:
        return _BUILD_INFO_CACHE.copy()

    with _BUILD_INFO_CACHE_LOCK:
        if _BUILD_INFO_CACHE:
            return _BUILD_INFO_CACHE.copy()

        import subprocess as _subprocess
        from pathlib import Path as _Path

        repo_root = _Path(__file__).resolve().parent
        cache: dict[str, str] = {}

        def _git(args: list[str]) -> str:
            try:
                out = _subprocess.check_output(
                    ["git", *args],
                    cwd=str(repo_root),
                    stderr=_subprocess.DEVNULL,
                    timeout=2.0,
                )
                return out.decode("utf-8", errors="replace").strip()
            except Exception:
                return "unknown"

        cache["git_commit"] = _git(["rev-parse", "--short", "HEAD"])
        cache["git_branch"] = _git(["rev-parse", "--abbrev-ref", "HEAD"])

        try:
            porc = (
                _subprocess.check_output(
                    ["git", "status", "--porcelain"],
                    cwd=str(repo_root),
                    stderr=_subprocess.DEVNULL,
                    timeout=2.0,
                )
                .decode("utf-8", errors="replace")
                .strip()
            )
            cache["git_dirty"] = "yes" if porc else "no"
        except Exception:
            cache["git_dirty"] = "unknown"

        _BUILD_INFO_CACHE = cache
        return cache.copy()


def reset_build_info_cache_for_testing() -> None:
    """R352 (cycle-39 #C2) · **Test-only**: 清空 ``_BUILD_INFO_CACHE`` 让
    下次 ``resolve_build_info()`` 重新调用 git subprocess。"""
    global _BUILD_INFO_CACHE
    with _BUILD_INFO_CACHE_LOCK:
        _BUILD_INFO_CACHE = {}
