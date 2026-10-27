# process_meta

> 英文 signature-only 版本（仅函数 / 类签名速查）：[`docs/api/process_meta.md`](../api/process_meta.md)

Process facts that the MCP server and the Web UI process both report.

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

## 函数

### `resolve_build_info() -> dict[str, str]`

返回 ``{git_commit, git_branch, git_dirty}``，失败字段填 ``"unknown"``。

### `reset_build_info_cache_for_testing() -> None`

R352 (cycle-39 #C2) · **Test-only**: 清空 ``_BUILD_INFO_CACHE`` 让
下次 ``resolve_build_info()`` 重新调用 git subprocess。
