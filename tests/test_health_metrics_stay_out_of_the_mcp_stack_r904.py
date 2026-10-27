"""R904 (TODO "health/metrics 不再 import MCP 栈"): a health check must not cost the Web UI the MCP stack.

What was wrong. The Web UI subprocess answers ``/api/system/health`` and
``/api/system/metrics``. To read two small facts, the helpers behind them imported the
MCP server: ``_safe_uptime_seconds`` and ``_safe_build_info`` did
``from ai_intervention_agent import server``, and the metrics lookup imported
``mcp_tool_call_metrics`` (which imports fastmcp at its top). The first call of either
endpoint loaded about 570 modules (fastmcp, mcp, pydantic, starlette, uvicorn,
cryptography, ...) into a process that never runs any MCP code: in a real Web UI
process (Python 3.13, 20 s old) the footprint went from 41.0 to 81.9 MiB and the call
took 329 ms; it never came back, so a Prometheus scrape or a probe left the Web UI 41
MiB heavier for good. And since ``server`` stamped "the start time" when it was first
imported, the Web UI reported the age of its first health request as its uptime
(0.27 s for a process that was 20.26 s old; ``aiia_uptime_seconds`` the same).

What it is now. The start time and the build info live in ``process_meta``, which needs
nothing but the standard library; ``web_ui`` imports it before Flask, ``server`` before
fastmcp, so each process counts from its own start. The metrics helper only looks the
MCP metrics module up in ``sys.modules`` (the counters are filled by the MCP
middleware, which only the MCP process runs; in the Web UI process they are always
empty, and "no module" renders exactly what "empty snapshots" did). Real Web UI
process: +0.6 MiB and 70 ms on the first health call, uptime 20.243 s (real age
20.25 s), the same for a scrape of ``/metrics`` first.

What is checked.

* In a fresh interpreter, built like the Web UI process (``WebFeedbackUI`` plus the
  requests every used Web UI has answered), the MCP stack is not loaded before the
  first health / metrics call and is not loaded after it, in either order (the first
  call of one endpoint must not hide a load made by the other).
* The uptime of the first answer counts from the start of the process (a pause taken
  before the first request is part of it), in both endpoints.
* ``process_meta`` imports nothing but the standard library, before and after the build
  info was read.
* No module of the Web UI side of the package imports the MCP stack (a static guard
  for what the subprocess cannot see: a path nobody asked in the test).
* ``web_ui`` imports ``process_meta`` before Flask and ``server`` before fastmcp (the
  stamp is the first import), and ``server`` takes its start time and build info from
  ``process_meta``, so the two processes use one definition.
* The helpers read ``process_meta``; the metrics helper never imports.

Against the code before the change 15 of these 44 tests fail (the other 29 guard what
must stay true: both endpoints answer, the build info is still reported, no other module
imports the MCP stack). And 25 hand-made breakages of the new code are each caught by at
least one of them: importing the server or the counters module again (plainly, through
importlib, through ``__import__``), stamping the start late, early, as zero or as an int,
keeping a second start time or a build cache in ``server``, dropping a build field, and
pulling a heavy import into ``process_meta``.
"""

from __future__ import annotations

import ast
import inspect
import json
import os
import subprocess
import sys
import textwrap
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast
from unittest.mock import patch

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC = REPO_ROOT / "src"
PKG = SRC / "ai_intervention_agent"

# What a Web UI process must never load: the MCP server, its tool-call counters (they
# import fastmcp) and the SDKs underneath.
MCP_STACK = (
    "fastmcp",
    "mcp",
    "ai_intervention_agent.server",
    "ai_intervention_agent.mcp_tool_call_metrics",
)

SETTLE_SECONDS = 1.2

PROBE = r"""
import json
import sys
import time
from pathlib import Path

order, settle, stack, scratch = sys.argv[1:5]
stack = stack.split(",")


def loaded():
    return sorted(name for name in stack if name in sys.modules)


# the same isolation tests/conftest.py gives the in-process tests
import ai_intervention_agent.task_queue_singleton as task_queue_singleton

task_queue_singleton._default_persist_path = lambda: Path(scratch) / "tasks.json"

from ai_intervention_agent.web_ui import WebFeedbackUI

ui = WebFeedbackUI(prompt="", port=18904)
client = ui.app.test_client()

# what a Web UI that is in use has answered before anyone asks for health
for path in ("/api/health", "/", "/api/tasks", "/api/config"):
    client.get(path)

time.sleep(float(settle))

paths = {"health": "/api/system/health", "metrics": "/api/system/metrics"}
first = order.split("-")[0]
second = "metrics" if first == "health" else "health"
result = {"loaded_before": loaded(), "calls": []}
for name in (first, second):
    response = client.get(paths[name])
    call = {"name": name, "status": response.status_code, "loaded_after": loaded()}
    if name == "health":
        body = response.get_json()
        call["uptime_seconds"] = body.get("uptime_seconds")
        call["build"] = body.get("build")
    else:
        text = response.get_data(as_text=True)
        line = next(
            (ln for ln in text.splitlines() if ln.startswith("aiia_uptime_seconds ")),
            None,
        )
        call["uptime_seconds"] = float(line.split()[1]) if line else None
        call["build_info_line"] = next(
            (ln for ln in text.splitlines() if ln.startswith("aiia_build_info{")), None
        )
    result["calls"].append(call)
print("RESULT " + json.dumps(result))
"""

LIGHT_PROBE = r"""
import json
import sys

before = set(sys.modules)
import ai_intervention_agent.process_meta as process_meta


def foreign():
    added = set(sys.modules) - before
    return sorted(
        name
        for name in added
        if name.split(".")[0] not in sys.stdlib_module_names
        and not name.startswith("ai_intervention_agent")
    )


at_import = foreign()
process_meta.resolve_build_info()
print(
    "RESULT "
    + json.dumps({"foreign_at_import": at_import, "foreign_after_build": foreign()})
)
"""


def _run(code: str, *args: str) -> dict[str, Any]:
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(
        [str(SRC), *([env["PYTHONPATH"]] if env.get("PYTHONPATH") else [])]
    )
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    done = subprocess.run(
        [sys.executable, "-c", code, *args],
        capture_output=True,
        text=True,
        timeout=120,
        env=env,
        cwd=str(REPO_ROOT),
    )
    lines = [ln for ln in done.stdout.splitlines() if ln.startswith("RESULT ")]
    assert lines, f"probe printed no result (exit {done.returncode}):\n{done.stderr}"
    return json.loads(lines[-1][len("RESULT ") :])


@pytest.fixture(scope="module", params=["health-first", "metrics-first"])
def probe(
    request: pytest.FixtureRequest, tmp_path_factory: pytest.TempPathFactory
) -> dict[str, Any]:
    scratch = tmp_path_factory.mktemp("r904_probe")
    started = time.monotonic()
    result = _run(
        PROBE, request.param, str(SETTLE_SECONDS), ",".join(MCP_STACK), str(scratch)
    )
    # the process cannot have been asked for its age later than it lived, seen from here
    result["lived_seconds"] = time.monotonic() - started
    return result


# ------------------------------------------------------------------ the real process


def test_a_web_ui_process_in_use_has_not_loaded_the_mcp_stack(
    probe: dict[str, Any],
) -> None:
    assert probe["loaded_before"] == []


def test_both_endpoints_answer(probe: dict[str, Any]) -> None:
    assert sorted((c["name"], c["status"]) for c in probe["calls"]) == [
        ("health", 200),
        ("metrics", 200),
    ]


def test_neither_first_call_loads_the_mcp_stack(probe: dict[str, Any]) -> None:
    for call in probe["calls"]:
        assert call["loaded_after"] == [], (
            f"{call['name']} pulled the MCP stack into the Web UI process"
        )


def test_the_uptime_of_the_first_answer_counts_from_the_process_start(
    probe: dict[str, Any],
) -> None:
    for call in probe["calls"]:
        assert call["uptime_seconds"] is not None, call["name"]
        assert call["uptime_seconds"] >= SETTLE_SECONDS - 0.05, (
            f"{call['name']} reported {call['uptime_seconds']} s for a process that "
            f"had been idle for {SETTLE_SECONDS} s before the request"
        )
        assert call["uptime_seconds"] <= probe["lived_seconds"] + 0.05, (
            f"{call['name']} reported {call['uptime_seconds']} s for a process that "
            f"lived {probe['lived_seconds']:.2f} s in all"
        )


def test_the_second_answer_is_never_younger_than_the_first(
    probe: dict[str, Any],
) -> None:
    first, second = probe["calls"]
    assert second["uptime_seconds"] >= first["uptime_seconds"]


def test_the_metrics_still_carry_the_build_info_family(probe: dict[str, Any]) -> None:
    (metrics,) = [c for c in probe["calls"] if c["name"] == "metrics"]
    line = metrics["build_info_line"]
    assert line is not None
    for label in ("version", "git_commit", "git_branch", "git_dirty"):
        assert f'{label}="' in line, line


def test_the_health_answer_still_carries_the_three_build_fields(
    probe: dict[str, Any],
) -> None:
    (health,) = [c for c in probe["calls"] if c["name"] == "health"]
    assert sorted(health["build"]) == ["git_branch", "git_commit", "git_dirty"]


def test_process_meta_needs_nothing_but_the_standard_library() -> None:
    result = _run(LIGHT_PROBE)
    assert result["foreign_at_import"] == []
    assert result["foreign_after_build"] == []


# ------------------------------------------------------------------ the code


def _imports_of_tree(tree: ast.AST) -> list[tuple[int, str]]:
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found += [(node.lineno, alias.name) for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            found.append((node.lineno, base))
            found += [(node.lineno, f"{base}.{alias.name}") for alias in node.names]
    return found


def _imports_of(path: Path) -> list[tuple[int, str]]:
    return _imports_of_tree(ast.parse(path.read_text(encoding="utf-8")))


def _imports_in(function: Callable[..., object]) -> list[str]:
    tree = ast.parse(textwrap.dedent(inspect.getsource(function)))
    return [name for _, name in _imports_of_tree(tree)]


def _calls_in(function: Callable[..., object]) -> set[str]:
    """The dotted names of everything the function calls (``sys.modules.get``)."""
    tree = ast.parse(textwrap.dedent(inspect.getsource(function)))
    names: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        parts: list[str] = []
        target: ast.expr = node.func
        while isinstance(target, ast.Attribute):
            parts.append(target.attr)
            target = target.value
        if isinstance(target, ast.Name):
            parts.append(target.id)
            names.add(".".join(reversed(parts)))
    return names


def _is_mcp_stack(name: str) -> bool:
    return any(name == root or name.startswith(root + ".") for root in MCP_STACK)


def _web_ui_side_files() -> list[Path]:
    return sorted(
        [
            PKG / "web_ui.py",
            *PKG.glob("web_ui_*.py"),
            *(PKG / "web_ui_routes").glob("*.py"),
        ]
    )


def test_the_guard_looks_at_the_files_of_the_web_ui_side() -> None:
    names = {p.relative_to(PKG).as_posix() for p in _web_ui_side_files()}
    assert {"web_ui.py", "web_ui_routes/system.py", "web_ui_wsgi.py"} <= names
    assert len(names) >= 15


@pytest.mark.parametrize("path", _web_ui_side_files(), ids=lambda p: p.name)
def test_no_module_of_the_web_ui_side_imports_the_mcp_stack(path: Path) -> None:
    offenders = [(n, name) for n, name in _imports_of(path) if _is_mcp_stack(name)]
    assert offenders == [], (
        f"{path.relative_to(PKG)} imports the MCP stack (line, module): {offenders}"
    )


def test_the_import_guard_sees_the_forms_the_old_code_used(tmp_path: Path) -> None:
    sample = tmp_path / "sample.py"
    sample.write_text(
        "def f():\n"
        "    from ai_intervention_agent import server\n"
        "def g():\n"
        "    from ai_intervention_agent import mcp_tool_call_metrics\n"
        "def h():\n"
        "    import fastmcp.server\n"
        "def i():\n"
        "    from mcp.types import Icon\n"
        "def ok():\n"
        "    from ai_intervention_agent import server_config\n"
        "    import ai_intervention_agent.service_manager\n",
        encoding="utf-8",
    )
    flagged = sorted({n for n, name in _imports_of(sample) if _is_mcp_stack(name)})
    assert flagged == [2, 4, 6, 8]


def _first_import_line(path: Path, root: str) -> int:
    lines = [
        n
        for n, name in _imports_of(path)
        if name == root or name.startswith(root + ".")
    ]
    assert lines, f"{path.name} does not import {root}"
    return min(lines)


def test_the_web_ui_stamps_the_start_before_it_imports_flask() -> None:
    web_ui = PKG / "web_ui.py"
    stamp = _first_import_line(web_ui, "ai_intervention_agent.process_meta")
    assert stamp < _first_import_line(web_ui, "flask")


def test_the_mcp_server_stamps_the_start_before_it_imports_fastmcp() -> None:
    server = PKG / "server.py"
    stamp = _first_import_line(server, "ai_intervention_agent.process_meta")
    assert stamp < _first_import_line(server, "fastmcp")
    assert stamp < _first_import_line(server, "mcp")


def test_the_server_does_not_keep_a_second_start_time_or_build_cache() -> None:
    source = (PKG / "server.py").read_text(encoding="utf-8")
    for leftover in (
        "_PROCESS_STARTED_AT_UNIX",
        "_BUILD_INFO_CACHE",
        "def _resolve_build_info",
        "def reset_build_info_cache_for_testing",
    ):
        assert leftover not in source, leftover


def test_the_server_info_resource_reads_the_shared_start_and_build() -> None:
    from ai_intervention_agent import process_meta, server

    before = time.time()
    info = server.server_info_resource()
    after = time.time()
    assert isinstance(info["runtime"], dict)
    runtime = cast("dict[str, Any]", info["runtime"])
    assert runtime["started_at_unix"] == round(process_meta.PROCESS_STARTED_AT_UNIX, 3)
    started = process_meta.PROCESS_STARTED_AT_UNIX
    assert before - started - 0.001 <= runtime["uptime_seconds"] <= after - started
    assert info["build"] == process_meta.resolve_build_info()


def test_health_reads_the_same_start_and_build_as_the_server_info() -> None:
    from ai_intervention_agent import process_meta
    from ai_intervention_agent.web_ui_routes import system

    started = time.time() - 1234.5
    with patch.object(process_meta, "PROCESS_STARTED_AT_UNIX", started):
        uptime = system._safe_uptime_seconds()
    assert uptime is not None
    assert 1234.5 <= uptime < 1240.0
    assert system._safe_build_info() == process_meta.resolve_build_info()


def test_the_build_info_keeps_its_three_fields() -> None:
    from ai_intervention_agent import process_meta

    info = process_meta.resolve_build_info()
    assert sorted(info) == ["git_branch", "git_commit", "git_dirty"]
    assert all(isinstance(value, str) and value for value in info.values())
    assert info["git_dirty"] in {"yes", "no", "unknown"}
    assert process_meta.resolve_build_info() == info


def test_the_start_time_is_one_float_that_never_moves() -> None:
    from ai_intervention_agent import process_meta

    first = process_meta.PROCESS_STARTED_AT_UNIX
    time.sleep(0.02)
    assert isinstance(first, float)
    assert first == process_meta.PROCESS_STARTED_AT_UNIX
    assert 0 < time.time() - first < 86400 * 3650


def test_the_health_helpers_read_process_meta_and_not_the_server() -> None:
    from ai_intervention_agent.web_ui_routes import system

    for helper in (system._safe_uptime_seconds, system._safe_build_info):
        imports = _imports_in(helper)
        assert "ai_intervention_agent.process_meta" in imports, helper.__name__
        assert [name for name in imports if _is_mcp_stack(name)] == [], helper.__name__


def test_the_metrics_helper_only_looks_the_counters_module_up() -> None:
    from ai_intervention_agent.web_ui_routes import system

    helper = system._get_mcp_tool_call_metrics_module
    assert _imports_in(helper) == []
    calls = _calls_in(helper)
    assert "sys.modules.get" in calls
    assert not calls & {"__import__", "import_module", "importlib.import_module"}
