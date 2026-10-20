"""R763: the suite also passes on pytest 9.1, which the lock file does not install.

``pyproject.toml`` allows ``pytest>=9.0.3`` and ``uv.lock`` pins 9.0.3, so a fresh
unlocked install, or the next lock refresh, runs the tests on 9.1 or later.  The gate
never sees that, and two things failed there.

* A class-scoped fixture written as an instance method is deprecated, which
  ``filterwarnings = error`` turns into an error: every test gets its own instance,
  the fixture runs once per class.  The four fixtures of the R386 and R390 tests are
  class methods now, and ``test_no_class_scoped_fixture_is_an_instance_method`` keeps
  every test file that way.
* pytest 9.1 attaches its log handlers to the loggers that do not propagate, and the
  ``EnhancedLogger`` ones are among them.  A record that reaches the live-log handler
  suspends the output capture and resumes it, and the resume puts pytest's own stream
  into ``sys.stdout``, replacing the buffer a test had set with ``redirect_stdout``.
  Two ``test_server_print_config.py`` tests printed into pytest's capture and found
  their buffer empty: an earlier test had switched the runtime log level to INFO
  through the endpoint and left it there, which lowered the live-log handler too, so
  the INFO record about the environment override reached it.

``tests/conftest.py`` puts the level of the root logger, its handlers and werkzeug
back after each test (``snapshot_global_log_levels``).  The first pair below relies on
pytest running the functions of a module in definition order: the first switches the
level, the second looks for it.  The other tests call the snapshot themselves or
exercise the detector behind the fixture check.
"""

from __future__ import annotations

import ast
import logging
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest

from ai_intervention_agent import enhanced_logging
from tests.conftest import snapshot_global_log_levels

TESTS_DIR = Path(__file__).resolve().parent
LEFT_BEHIND: dict[str, Any] = {}


def a_level_none_of_them_has() -> tuple[str, int]:
    root = logging.getLogger()
    held = {logging.getLogger("werkzeug").level, root.level}
    held.update(handler.level for handler in root.handlers)
    for name in ("DEBUG", "ERROR", "CRITICAL"):
        if enhanced_logging.LOG_LEVEL_MAP[name] not in held:
            return name, enhanced_logging.LOG_LEVEL_MAP[name]
    raise AssertionError(f"every probe level is already in use: {sorted(held)}")


@contextmanager
def probe_handler(level: int) -> Iterator[logging.Handler]:
    handler = logging.NullHandler(level)
    logging.getLogger().addHandler(handler)
    try:
        yield handler
    finally:
        logging.getLogger().removeHandler(handler)


def test_a_test_can_switch_the_runtime_log_level() -> None:
    root = logging.getLogger()
    werkzeug = logging.getLogger("werkzeug")
    LEFT_BEHIND["levels"] = (root.level, werkzeug.level)
    LEFT_BEHIND["handlers"] = [(handler, handler.level) for handler in root.handlers]
    name, level = a_level_none_of_them_has()

    enhanced_logging.apply_runtime_log_level(name)

    assert (root.level, werkzeug.level) == (level, level)
    assert all(handler.level == level for handler in root.handlers)


def test_the_next_test_starts_at_the_original_level() -> None:
    root = logging.getLogger()
    werkzeug = logging.getLogger("werkzeug")
    assert (root.level, werkzeug.level) == LEFT_BEHIND.get(
        "levels", (root.level, werkzeug.level)
    )
    for handler, level in LEFT_BEHIND.get("handlers", []):
        if handler in root.handlers:
            assert handler.level == level


def test_the_restore_puts_back_root_its_handlers_and_werkzeug() -> None:
    root = logging.getLogger()
    werkzeug = logging.getLogger("werkzeug")
    root.setLevel(logging.WARNING)
    werkzeug.setLevel(logging.INFO)
    with probe_handler(logging.CRITICAL) as handler:
        restore = snapshot_global_log_levels()

        enhanced_logging.apply_runtime_log_level("DEBUG")
        assert (root.level, werkzeug.level, handler.level) == (logging.DEBUG,) * 3

        restore()
        assert (root.level, werkzeug.level, handler.level) == (
            logging.WARNING,
            logging.INFO,
            logging.CRITICAL,
        )


def test_the_restore_leaves_a_handler_added_after_the_snapshot_alone() -> None:
    restore = snapshot_global_log_levels()
    with probe_handler(logging.ERROR) as late:
        restore()
        assert late.level == logging.ERROR


def test_the_restore_can_be_called_twice() -> None:
    root = logging.getLogger()
    root.setLevel(logging.WARNING)
    restore = snapshot_global_log_levels()
    root.setLevel(logging.DEBUG)

    restore()
    root.setLevel(logging.ERROR)
    restore()

    assert root.level == logging.WARNING


def is_class_scoped_fixture(function: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    for decorator in function.decorator_list:
        if not isinstance(decorator, ast.Call):
            continue
        target = decorator.func
        if isinstance(target, ast.Attribute):
            name = target.attr
        elif isinstance(target, ast.Name):
            name = target.id
        else:
            continue
        if name != "fixture":
            continue
        for keyword in decorator.keywords:
            value = keyword.value
            if (
                keyword.arg == "scope"
                and isinstance(value, ast.Constant)
                and value.value == "class"
            ):
                return True
    return False


def is_bound_to_the_class(function: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    return any(
        isinstance(decorator, ast.Name)
        and decorator.id in {"classmethod", "staticmethod"}
        for decorator in function.decorator_list
    )


def instance_method_class_fixtures(source: str) -> list[tuple[int, str]]:
    found: list[tuple[int, str]] = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.ClassDef):
            continue
        for item in node.body:
            if (
                isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
                and is_class_scoped_fixture(item)
                and not is_bound_to_the_class(item)
            ):
                found.append((item.lineno, item.name))
    return found


def test_no_class_scoped_fixture_is_an_instance_method() -> None:
    offenders = [
        f"{path.name}:{line} {name}"
        for path in sorted(TESTS_DIR.glob("*.py"))
        for line, name in instance_method_class_fixtures(
            path.read_text(encoding="utf-8")
        )
    ]

    assert offenders == [], (
        "pytest 9.1 deprecates a class-scoped fixture that is an instance method; "
        "add @classmethod below @pytest.fixture and take cls instead of self"
    )


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        pytest.param(
            "class T:\n    @pytest.fixture(scope='class')\n    def f(self): ...\n",
            ["f"],
            id="instance-method",
        ),
        pytest.param(
            "class T:\n    @fixture(scope='class', autouse=True)\n    def f(self): ...\n",
            ["f"],
            id="bare-fixture-name",
        ),
        pytest.param(
            "class T:\n    @pytest.fixture(scope='class')\n    async def f(self): ...\n",
            ["f"],
            id="async",
        ),
        pytest.param(
            "class T:\n    @pytest.fixture(scope='class')\n    @classmethod\n"
            "    def f(cls): ...\n",
            [],
            id="classmethod",
        ),
        pytest.param(
            "class T:\n    @pytest.fixture(scope='class')\n    @staticmethod\n"
            "    def f(): ...\n",
            [],
            id="staticmethod",
        ),
        pytest.param(
            "class T:\n    @pytest.fixture\n    def f(self): ...\n",
            [],
            id="function-scope-bare",
        ),
        pytest.param(
            "class T:\n    @pytest.fixture(scope='module')\n    def f(self): ...\n",
            [],
            id="module-scope",
        ),
        pytest.param(
            "@pytest.fixture(scope='class')\ndef f(): ...\n",
            [],
            id="module-level",
        ),
        pytest.param(
            "class T:\n    def f(self): ...\n",
            [],
            id="not-a-fixture",
        ),
    ],
)
def test_the_detector_flags_only_instance_method_class_fixtures(
    source: str, expected: list[str]
) -> None:
    assert [name for _, name in instance_method_class_fixtures(source)] == expected
