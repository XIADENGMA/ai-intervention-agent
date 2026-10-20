"""R749: the configured log level is applied when a process starts.

``web_ui.log_level`` in ``config.toml`` and ``AI_INTERVENTION_AGENT_LOG_LEVEL``
were read by ``get_log_level_from_config()``, but nothing ever called
``configure_logging_from_config()``, so both settings did nothing: the MCP server
stayed pinned to WARNING, and the Web UI process kept werkzeug's request lines at
INFO whatever the setting said. The troubleshooting guide tells people to set
``DEBUG`` to diagnose problems, and they got no debug lines.

Applying the level at the two process entry points also has to take werkzeug into
account. It pins its own logger to INFO on first use and, when no root handler
accepts INFO, adds a plain stderr handler that skips the log sanitiser. At the
default level that would print raw request lines, so werkzeug follows the global
level (and the runtime switch of ``/api/system/log-level``).
"""

from __future__ import annotations

import ast
import logging
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import ai_intervention_agent.enhanced_logging as enhanced_logging
import ai_intervention_agent.server as server

ENV_VAR = "AI_INTERVENTION_AGENT_LOG_LEVEL"
WEB_UI = Path(server.__file__).resolve().with_name("web_ui.py")

LEVELS = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
}


@pytest.fixture(autouse=True)
def restore_logging():
    root = logging.getLogger()
    werkzeug = logging.getLogger("werkzeug")
    root_level = root.level
    handler_levels = [(handler, handler.level) for handler in root.handlers]
    werkzeug_level = werkzeug.level
    yield
    root.setLevel(root_level)
    for handler, level in handler_levels:
        handler.setLevel(level)
    werkzeug.setLevel(werkzeug_level)
    enhanced_logging.clear_recent_logs()


def run_main(env: dict[str, str]) -> None:
    with (
        patch.dict(os.environ, env),
        patch.object(server.mcp, "run", side_effect=KeyboardInterrupt),
        patch.object(server, "cleanup_services"),
        patch.object(server, "logger"),
    ):
        server.main()


def assert_levels(expected: int) -> None:
    root = logging.getLogger()
    assert root.level == expected
    assert root.handlers
    assert [handler.level for handler in root.handlers] == [expected] * len(
        root.handlers
    )
    assert logging.getLogger("werkzeug").level == expected


@pytest.mark.parametrize("name", LEVELS)
def test_mcp_server_start_applies_the_level_from_the_environment(name):
    run_main({ENV_VAR: name})
    assert_levels(LEVELS[name])


def test_mcp_server_start_applies_the_level_from_the_config_file():
    from ai_intervention_agent.config_manager import config_manager

    real_get = config_manager.get

    def get(key, *args, **kwargs):
        if key == "web_ui":
            return {"log_level": "ERROR"}
        return real_get(key, *args, **kwargs)

    with (
        patch.dict(os.environ),
        patch.object(config_manager, "get", side_effect=get),
    ):
        os.environ.pop(ENV_VAR, None)
        with (
            patch.object(server.mcp, "run", side_effect=KeyboardInterrupt),
            patch.object(server, "cleanup_services"),
            patch.object(server, "logger"),
        ):
            server.main()
    assert_levels(logging.ERROR)


def test_mcp_server_start_applies_the_level_before_the_boot_banner():
    order = MagicMock()
    with (
        patch.object(server.mcp, "run", side_effect=KeyboardInterrupt),
        patch.object(server, "cleanup_services"),
        patch.object(server, "configure_logging_from_config", order.configure),
        patch.object(server, "logger", order.logger),
    ):
        server.main()

    names = [call[0] for call in order.mock_calls]
    boot = next(
        index
        for index, call in enumerate(order.mock_calls)
        if call[0] == "logger.warning" and "event=server.boot" in call[1][0]
    )
    assert "configure" in names[:boot]
    assert names.count("configure") == 1


@pytest.mark.parametrize("name", ["DEBUG", "INFO", "WARNING", "ERROR"])
def test_runtime_switch_moves_werkzeug_with_the_root_logger(name):
    enhanced_logging.apply_runtime_log_level(name.lower())
    assert_levels(LEVELS[name])


def is_main_guard(test: ast.expr) -> bool:
    return (
        isinstance(test, ast.Compare)
        and isinstance(test.left, ast.Name)
        and test.left.id == "__name__"
        and len(test.comparators) == 1
        and isinstance(test.comparators[0], ast.Constant)
        and test.comparators[0].value == "__main__"
    )


def called_names(statement: ast.stmt) -> set[str]:
    return {
        node.func.id
        for node in ast.walk(statement)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }


def web_ui_main_block() -> list[ast.stmt]:
    tree = ast.parse(WEB_UI.read_text(encoding="utf-8"))
    blocks = [
        node.body
        for node in tree.body
        if isinstance(node, ast.If)
        and is_main_guard(node.test)
        and any("web_feedback_ui" in called_names(item) for item in node.body)
    ]
    assert len(blocks) == 1, "web_ui.py needs exactly one __main__ block that serves"
    return blocks[0]


def test_web_ui_script_applies_the_level_before_it_serves():
    body = web_ui_main_block()
    applies = [
        index
        for index, statement in enumerate(body)
        if isinstance(statement, ast.Expr)
        and called_names(statement) == {"configure_logging_from_config"}
    ]
    serves = [
        index
        for index, statement in enumerate(body)
        if "web_feedback_ui" in called_names(statement)
    ]
    assert len(applies) == 1
    assert len(serves) == 1
    assert applies[0] < serves[0]


def test_web_ui_script_uses_the_shared_configure_function():
    import ai_intervention_agent.web_ui as web_ui

    assert (
        web_ui.configure_logging_from_config
        is enhanced_logging.configure_logging_from_config
    )


SERVE_ONE_REQUEST = """
import logging
import threading
import urllib.request

import ai_intervention_agent.enhanced_logging as enhanced_logging
from werkzeug.serving import make_server

enhanced_logging.configure_logging_from_config()


def app(environ, start_response):
    start_response("200 OK", [("Content-Type", "text/plain")])
    return [b"ok"]


server = make_server("127.0.0.1", 0, app)
thread = threading.Thread(target=server.serve_forever, daemon=True)
thread.start()
urllib.request.urlopen(f"http://127.0.0.1:{server.server_port}/probe-path").read()
server.shutdown()
thread.join()
print("werkzeug_handlers=%d" % len(logging.getLogger("werkzeug").handlers))
"""


def serve_one_request(level: str | None) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env.pop(ENV_VAR, None)
    if level is not None:
        env[ENV_VAR] = level
    return subprocess.run(
        [sys.executable, "-c", SERVE_ONE_REQUEST],
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )


@pytest.mark.parametrize("level", [None, "WARNING", "ERROR"])
def test_request_lines_stay_quiet_at_warning_and_above(level):
    result = serve_one_request(level)
    assert result.returncode == 0, result.stderr
    assert "probe-path" not in result.stderr
    assert "werkzeug_handlers=0" in result.stdout


def test_request_lines_at_info_go_through_the_sanitising_sink():
    result = serve_one_request("INFO")
    assert result.returncode == 0, result.stderr
    lines = [line for line in result.stderr.splitlines() if "probe-path" in line]
    assert len(lines) == 1
    assert " - werkzeug - INFO - " in lines[0]
    assert "werkzeug_handlers=0" in result.stdout
