"""R754: a Web UI started as a script picks up ``network_security`` edits.

``ServiceManager`` starts the Web UI as ``python web_ui.py``, so the file runs as
``__main__``. The config-change callbacks find the running instance through
``import ai_intervention_agent.web_ui``, and in that process this was a second copy
of the file, one that had never created an instance. ``blocked_ips``,
``allowed_networks`` and ``access_control_enabled`` edits therefore never reached
the running server: it kept the rules it started with until it was restarted. The
unit tests could not see it, because they set the instance on the one module they
import.

The file now registers itself under its package name when it runs as a script, so
the process holds one copy.
"""

from __future__ import annotations

import ast
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Iterator
from pathlib import Path

import pytest

import ai_intervention_agent.web_ui as web_ui

WEB_UI_PATH = Path(web_ui.__file__).resolve()
TEMPLATE = Path(__file__).resolve().parent.parent / "config.toml.default"
PACKAGE_NAME = "ai_intervention_agent.web_ui"


def is_main_guard(node: ast.stmt) -> bool:
    if not isinstance(node, ast.If):
        return False
    test = node.test
    return (
        isinstance(test, ast.Compare)
        and isinstance(test.left, ast.Name)
        and test.left.id == "__name__"
        and len(test.comparators) == 1
        and isinstance(test.comparators[0], ast.Constant)
        and test.comparators[0].value == "__main__"
    )


def registers_package_name(node: ast.If) -> bool:
    for statement in node.body:
        if not isinstance(statement, ast.Assign) or len(statement.targets) != 1:
            continue
        target = statement.targets[0]
        if (
            isinstance(target, ast.Subscript)
            and ast.unparse(target.value) == "sys.modules"
            and isinstance(target.slice, ast.Constant)
            and target.slice.value == PACKAGE_NAME
            and ast.unparse(statement.value) == "sys.modules[__name__]"
        ):
            return True
    return False


def test_the_script_registers_itself_under_its_package_name_before_anything_runs():
    body = ast.parse(WEB_UI_PATH.read_text(encoding="utf-8")).body
    guards = [
        index
        for index, node in enumerate(body)
        if is_main_guard(node)
        and isinstance(node, ast.If)
        and registers_package_name(node)
    ]
    assert len(guards) == 1, "web_ui.py must alias itself when it runs as __main__"
    first_definition = next(
        index
        for index, node in enumerate(body)
        if isinstance(node, (ast.ClassDef, ast.FunctionDef))
    )
    assert guards[0] < first_definition


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def status_of(url: str) -> int:
    try:
        with urllib.request.urlopen(url, timeout=5) as response:
            return int(response.status)
    except urllib.error.HTTPError as error:
        return int(error.code)
    except OSError:
        return 0


def wait_for_status(url: str, expected: int, seconds: float) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if status_of(url) == expected:
            return True
        time.sleep(0.25)
    return False


def write_config(path: Path, blocked_ips: str) -> None:
    text = TEMPLATE.read_text(encoding="utf-8")
    for old, new in (
        ('enabled = "auto"', "enabled = false"),
        ("blocked_ips = []", f"blocked_ips = {blocked_ips}"),
    ):
        assert text.count(old) == 1, old
        text = text.replace(old, new)
    scratch = path.with_suffix(".tmp")
    scratch.write_text(text, encoding="utf-8")
    os.replace(scratch, path)


@pytest.fixture
def script_web_ui(tmp_path: Path) -> Iterator[tuple[str, Path, Path]]:
    config = tmp_path / "config.toml"
    write_config(config, "[]")
    log_path = tmp_path / "web_ui.log"
    port = free_port()
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("AI_INTERVENTION_AGENT_")
    }
    env["AI_INTERVENTION_AGENT_CONFIG_FILE"] = str(config)
    with log_path.open("wb") as log:
        process = subprocess.Popen(
            [
                sys.executable,
                "-u",
                str(WEB_UI_PATH),
                "--prompt",
                "",
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
            ],
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
        )
        try:
            base = f"http://127.0.0.1:{port}"
            assert wait_for_status(f"{base}/api/health", 200, 60), log_path.read_text(
                encoding="utf-8", errors="replace"
            )
            yield base, config, log_path
        finally:
            process.terminate()
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


def test_a_running_script_follows_edits_to_blocked_ips(script_web_ui):
    base, config, log_path = script_web_ui
    url = f"{base}/api/tasks"
    assert status_of(url) == 200

    write_config(config, '["127.0.0.1"]')
    assert wait_for_status(url, 403, 20), (
        "the running Web UI never applied the new blocked_ips\n"
        + log_path.read_text(encoding="utf-8", errors="replace")
    )

    write_config(config, "[]")
    assert wait_for_status(url, 200, 20), (
        "the running Web UI never lifted the block\n"
        + log_path.read_text(encoding="utf-8", errors="replace")
    )
