"""R836 - each Web UI keeps its own task snapshot, named after its port.

Symptom: ``get_task_queue()`` put the snapshot at ``<package>/data/tasks.json`` for every
Web UI process of an installation. Two projects with two configs (so two ports) from the
same ``uvx`` environment therefore shared one file: the second Web UI restored the first
one's pending questions at start-up and listed them as its own, and from then on each
process rewrote the file with only its own tasks, erasing the other's. A real two-server
run showed the second Web UI listing ``QUESTION FROM A`` next to ``QUESTION FROM B``.

Fix: the Web UI binds the task queue to its listening port before the queue is built
(``bind_task_queue_to_port`` from ``web_feedback_ui``), and the snapshot becomes
``tasks-<port>.json`` next to the old name. The same port (a Web UI that was killed and
started again, R825) finds its own file; another port never sees it. Unbound users of
the singleton (tests, the WSGI entry point) keep ``tasks.json``.
"""

from __future__ import annotations

import ast
import inspect
import textwrap
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

import ai_intervention_agent.task_queue_singleton as singleton
from ai_intervention_agent.task_queue import TaskQueue


@pytest.fixture
def fresh_singleton(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[Any]:
    """The singleton module with no queue built and no port bound, over a private folder."""
    monkeypatch.setattr(singleton, "_global_task_queue", None)
    monkeypatch.setattr(singleton, "_bound_port", None, raising=False)
    monkeypatch.setattr(
        singleton, "_default_persist_path", lambda: tmp_path / "tasks.json"
    )
    try:
        yield singleton
    finally:
        queue = singleton._global_task_queue
        if queue is not None:
            queue.stop_cleanup()


def _built_queue(module: Any) -> TaskQueue:
    queue = module.get_task_queue()
    assert queue._persist_path is not None
    return queue


class TestSnapshotNamedAfterThePortR836:
    def test_unbound_queue_keeps_the_plain_name(
        self, fresh_singleton: Any, tmp_path: Path
    ) -> None:
        queue = _built_queue(fresh_singleton)
        assert queue._persist_path == tmp_path / "tasks.json"

    def test_bound_queue_uses_the_port_in_the_name(
        self, fresh_singleton: Any, tmp_path: Path
    ) -> None:
        assert fresh_singleton.bind_task_queue_to_port(8123) is True

        queue = _built_queue(fresh_singleton)

        assert queue._persist_path == tmp_path / "tasks-8123.json"

    def test_the_default_folder_and_extension_are_kept(
        self, fresh_singleton: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setattr(
            fresh_singleton,
            "_default_persist_path",
            lambda: tmp_path / "data" / "q.state",
        )
        assert fresh_singleton.bind_task_queue_to_port(9001)

        assert fresh_singleton._snapshot_path() == tmp_path / "data" / "q-9001.state"


class TestInstancesDoNotShareTasksR836:
    def test_another_port_does_not_restore_the_first_ones_tasks(
        self, fresh_singleton: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        assert fresh_singleton.bind_task_queue_to_port(8100)
        first = _built_queue(fresh_singleton)
        assert first.add_task("question-from-8100", "asked on 8100")
        first.stop_cleanup()

        # A second Web UI process: its own module state, the same package folder.
        monkeypatch.setattr(fresh_singleton, "_global_task_queue", None)
        monkeypatch.setattr(fresh_singleton, "_bound_port", None)
        assert fresh_singleton.bind_task_queue_to_port(8101)
        second = _built_queue(fresh_singleton)

        assert second.get_task("question-from-8100") is None
        assert second.get_task_count()["total"] == 0
        assert second.add_task("question-from-8101", "asked on 8101")
        second.stop_cleanup()

        # And the first one's file still holds exactly its own question.
        restarted = TaskQueue(persist_path=str(first._persist_path))
        try:
            assert restarted.get_task("question-from-8100") is not None
            assert restarted.get_task("question-from-8101") is None
        finally:
            restarted.stop_cleanup()

    def test_the_same_port_after_a_restart_gets_its_tasks_back(
        self, fresh_singleton: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        assert fresh_singleton.bind_task_queue_to_port(8100)
        before = _built_queue(fresh_singleton)
        assert before.add_task("waiting", "still waiting")
        before.stop_cleanup()

        monkeypatch.setattr(fresh_singleton, "_global_task_queue", None)
        monkeypatch.setattr(fresh_singleton, "_bound_port", None)
        assert fresh_singleton.bind_task_queue_to_port(8100)
        after = _built_queue(fresh_singleton)

        assert after.get_task("waiting") is not None


class TestBindingRulesR836:
    @pytest.mark.parametrize("bad", [0, -1, 65536, 99999, "8080", None, 80.5, True])
    def test_an_unusable_port_binds_nothing(
        self, fresh_singleton: Any, bad: Any
    ) -> None:
        assert fresh_singleton.bind_task_queue_to_port(bad) is False
        assert fresh_singleton._bound_port is None
        assert fresh_singleton._snapshot_path().name == "tasks.json"

    @pytest.mark.parametrize("port", [1, 8080, 65535])
    def test_every_valid_port_is_accepted(
        self, fresh_singleton: Any, port: int
    ) -> None:
        assert fresh_singleton.bind_task_queue_to_port(port) is True
        assert fresh_singleton._snapshot_path().name == f"tasks-{port}.json"

    def test_binding_after_the_queue_exists_changes_nothing(
        self, fresh_singleton: Any, tmp_path: Path
    ) -> None:
        queue = _built_queue(fresh_singleton)

        assert fresh_singleton.bind_task_queue_to_port(8123) is False

        assert fresh_singleton.get_task_queue() is queue
        assert queue._persist_path == tmp_path / "tasks.json"

    def test_rebinding_the_same_port_after_the_queue_exists_is_still_true(
        self, fresh_singleton: Any
    ) -> None:
        assert fresh_singleton.bind_task_queue_to_port(8123)
        _built_queue(fresh_singleton)

        assert fresh_singleton.bind_task_queue_to_port(8123) is True
        assert fresh_singleton.bind_task_queue_to_port(8124) is False

    def test_the_binding_is_part_of_the_public_surface(self) -> None:
        assert "bind_task_queue_to_port" in singleton.__all__


class TestEntryPointsBindTheirPortR836:
    def test_web_feedback_ui_binds_before_it_builds_the_ui(self) -> None:
        import ai_intervention_agent.web_ui as web_ui

        order: list[str] = []

        class StubUI:
            def __init__(self, *args: Any, **kwargs: Any) -> None:
                order.append("ui-built")

            def run(self) -> None:
                order.append("ui-run")
                return None

        def record_bind(port: int) -> bool:
            order.append(f"bind:{port}")
            return True

        with (
            patch.object(web_ui, "WebFeedbackUI", StubUI),
            patch.object(singleton, "bind_task_queue_to_port", record_bind),
        ):
            web_ui.web_feedback_ui("", port=8777)

        assert order == ["bind:8777", "ui-built", "ui-run"]

    def test_the_cli_main_passes_its_port_through_web_feedback_ui(self) -> None:
        import ai_intervention_agent.web_ui as web_ui

        source = textwrap.dedent(inspect.getsource(web_ui))
        tree = ast.parse(source)
        calls = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and ast.unparse(node.func) == "web_feedback_ui"
            and any(kw.arg == "port" for kw in node.keywords)
        ]
        assert calls, "the CLI must hand --port to web_feedback_ui"
