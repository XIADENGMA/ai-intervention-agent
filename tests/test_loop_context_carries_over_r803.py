"""R803 regression coverage: a loop keeps its objective and success criteria across rounds.

``interactive_feedback`` tells the agent to pass ``loop_objective`` on the first round of
a ``loop_id`` and that later rounds "may omit it". The ledger honours that
(``GET /api/loops`` keeps the last non-empty value), but a task row only carried what that
one call passed, so from the second round on ``GET /api/tasks`` and ``GET /api/config``
returned an empty ``loop_objective`` and ``success_criteria``: the objective and the
criteria the human judges the evidence against were gone after one round.

The fix: ``TaskQueue.add_task`` fills a missing ``loop_objective`` / ``success_criteria``
of a round that belongs to a loop with the loop's most recent value (a round still in the
queue, or the ledger, whichever was supplied last). ``loop_phase`` and
``iteration_label`` describe one round and are never carried.

R896 note: this module used to cover the "Rounds" panel of the loop-context card as well
(expand / collapse / expand drew every round twice; an open panel never refreshed), run
for real in Node against both front ends. The card, and with it that panel, was removed
from the Web page and the VS Code panel in R896 and those tests went with it. What is
left is the backend contract (task rows, snapshot, HTTP) that the API still serves.
"""

from __future__ import annotations

import json
import tempfile
import time
from pathlib import Path
from typing import Any

import pytest

from ai_intervention_agent.task_constants import (
    LOOP_HISTORY_MAX_LOOPS,
    LOOP_TEXT_MAX_LENGTH,
)
from ai_intervention_agent.task_queue import TaskQueue

REPO_ROOT = Path(__file__).resolve().parent.parent
# 给时间戳比较留出分辨率（Windows 的时钟粒度约 15 ms）
_CLOCK_GAP_S = 0.05


def _result(text: str = "ok") -> dict[str, Any]:
    return {"user_input": text, "selected_options": [], "images": []}


def _queue(persist_path: str | None = None, max_tasks: int = 50) -> TaskQueue:
    queue = TaskQueue(max_tasks=max_tasks, persist_path=persist_path)
    return queue


def _fields(queue: TaskQueue, task_id: str) -> tuple[str | None, str | None]:
    task = queue.get_task(task_id)
    assert task is not None, task_id
    return task.loop_objective, task.success_criteria


class TestLoopTextCarriedOver:
    @pytest.fixture
    def queue(self) -> Any:
        queue = _queue()
        yield queue
        queue.stop_cleanup()

    def test_round_two_keeps_what_round_one_said(self, queue: TaskQueue) -> None:
        queue.add_task(
            task_id="r1",
            prompt="p",
            loop_id="lp",
            loop_objective="make the tests pass",
            success_criteria="all green",
        )
        queue.complete_task("r1", _result())
        queue.add_task(task_id="r2", prompt="p", loop_id="lp", loop_phase="verify")
        assert _fields(queue, "r2") == ("make the tests pass", "all green")

    def test_carried_from_a_round_that_is_still_waiting(self, queue: TaskQueue) -> None:
        queue.add_task(
            task_id="r1",
            prompt="p",
            loop_id="lp",
            loop_objective="obj",
            success_criteria="crit",
        )
        queue.add_task(task_id="r2", prompt="p", loop_id="lp")
        assert _fields(queue, "r2") == ("obj", "crit")

    def test_carried_from_the_ledger_once_the_rounds_are_gone(
        self, queue: TaskQueue
    ) -> None:
        queue.add_task(
            task_id="r1",
            prompt="p",
            loop_id="lp",
            loop_objective="obj",
            success_criteria="crit",
        )
        queue.complete_task("r1", _result())
        assert queue.cleanup_completed_tasks(age_seconds=0) == 1
        assert queue.get_task("r1") is None
        queue.add_task(task_id="r2", prompt="p", loop_id="lp")
        assert _fields(queue, "r2") == ("obj", "crit")

    def test_carried_through_many_rounds(self, queue: TaskQueue) -> None:
        queue.add_task(task_id="r0", prompt="p", loop_id="lp", loop_objective="obj-0")
        for index in range(1, 6):
            queue.complete_task(f"r{index - 1}", _result())
            queue.cleanup_completed_tasks(age_seconds=0)
            queue.add_task(task_id=f"r{index}", prompt="p", loop_id="lp")
            assert _fields(queue, f"r{index}")[0] == "obj-0", index

    def test_explicit_value_wins_and_becomes_the_loop_value(
        self, queue: TaskQueue
    ) -> None:
        queue.add_task(
            task_id="r1", prompt="p", loop_id="lp", loop_objective="old objective"
        )
        queue.complete_task("r1", _result())
        queue.add_task(
            task_id="r2",
            prompt="p",
            loop_id="lp",
            loop_objective="new objective",
            success_criteria="new criteria",
        )
        assert _fields(queue, "r2") == ("new objective", "new criteria")
        queue.add_task(task_id="r3", prompt="p", loop_id="lp")
        assert _fields(queue, "r3") == ("new objective", "new criteria")

    def test_each_field_is_carried_on_its_own(self, queue: TaskQueue) -> None:
        queue.add_task(
            task_id="r1",
            prompt="p",
            loop_id="lp",
            loop_objective="obj",
            success_criteria="crit-1",
        )
        queue.add_task(
            task_id="r2", prompt="p", loop_id="lp", success_criteria="crit-2"
        )
        assert _fields(queue, "r2") == ("obj", "crit-2")
        queue.add_task(task_id="r3", prompt="p", loop_id="lp", loop_objective="obj-3")
        assert _fields(queue, "r3") == ("obj-3", "crit-2")

    def test_the_newest_round_in_the_queue_wins(self, queue: TaskQueue) -> None:
        queue.add_task(task_id="r1", prompt="p", loop_id="lp", loop_objective="v1")
        queue.add_task(task_id="r2", prompt="p", loop_id="lp", loop_objective="v2")
        queue.add_task(task_id="r3", prompt="p", loop_id="lp")
        assert _fields(queue, "r3")[0] == "v2"

    def test_a_round_that_is_newer_than_the_ledger_wins(self, queue: TaskQueue) -> None:
        queue.add_task(
            task_id="r1", prompt="p", loop_id="lp", loop_objective="ledger value"
        )
        queue.complete_task("r1", _result())
        queue.cleanup_completed_tasks(age_seconds=0)
        time.sleep(_CLOCK_GAP_S)
        queue.add_task(
            task_id="r2", prompt="p", loop_id="lp", loop_objective="live value"
        )
        queue.add_task(task_id="r3", prompt="p", loop_id="lp")
        assert _fields(queue, "r3")[0] == "live value"

    def test_a_stale_waiting_round_does_not_beat_a_newer_ledger_value(
        self, queue: TaskQueue
    ) -> None:
        """A round nobody answered (its agent run died) keeps an old objective in the
        queue; the loop was restarted with a new one, which the ledger holds."""
        queue.add_task(
            task_id="stuck", prompt="p", loop_id="lp", loop_objective="old objective"
        )
        time.sleep(_CLOCK_GAP_S)
        queue.add_task(
            task_id="r2", prompt="p", loop_id="lp", loop_objective="new objective"
        )
        queue.complete_task("r2", _result())
        queue.cleanup_completed_tasks(age_seconds=0)
        assert queue.get_task("stuck") is not None
        time.sleep(_CLOCK_GAP_S)
        queue.add_task(task_id="r3", prompt="p", loop_id="lp")
        assert _fields(queue, "r3")[0] == "new objective"

    @pytest.mark.parametrize(
        "omitted", [None, "", "   ", "\n\t", 0, 12345, ["list"], {"k": "v"}]
    )
    def test_anything_that_is_not_text_counts_as_omitted(
        self, queue: TaskQueue, omitted: Any
    ) -> None:
        queue.add_task(
            task_id="r1",
            prompt="p",
            loop_id="lp",
            loop_objective="obj",
            success_criteria="crit",
        )
        queue.add_task(
            task_id="r2",
            prompt="p",
            loop_id="lp",
            loop_objective=omitted,
            success_criteria=omitted,
        )
        assert _fields(queue, "r2") == ("obj", "crit")

    def test_other_loops_and_plain_tasks_never_receive_it(
        self, queue: TaskQueue
    ) -> None:
        queue.add_task(
            task_id="r1",
            prompt="p",
            loop_id="lp",
            loop_objective="obj",
            success_criteria="crit",
        )
        queue.complete_task("r1", _result())
        queue.add_task(task_id="other", prompt="p", loop_id="other-loop")
        queue.add_task(task_id="plain", prompt="p")
        queue.add_task(task_id="blank-id", prompt="p", loop_id="   ")
        assert _fields(queue, "other") == (None, None)
        assert _fields(queue, "plain") == (None, None)
        assert _fields(queue, "blank-id") == (None, None)

    def test_text_without_a_loop_id_is_not_a_loop(self, queue: TaskQueue) -> None:
        queue.add_task(
            task_id="plain-1",
            prompt="p",
            loop_objective="objective of nothing",
            success_criteria="criteria of nothing",
        )
        queue.add_task(task_id="plain-2", prompt="p")
        queue.add_task(task_id="blank-id", prompt="p", loop_id="   ")
        assert _fields(queue, "plain-1") == (
            "objective of nothing",
            "criteria of nothing",
        )
        assert _fields(queue, "plain-2") == (None, None)
        assert _fields(queue, "blank-id") == (None, None)

    def test_loop_ids_match_after_normalisation(self, queue: TaskQueue) -> None:
        queue.add_task(task_id="r1", prompt="p", loop_id="lp", loop_objective="obj")
        queue.add_task(task_id="r2", prompt="p", loop_id="  lp  ")
        assert _fields(queue, "r2")[0] == "obj"

    def test_phase_and_iteration_label_describe_one_round_only(
        self, queue: TaskQueue
    ) -> None:
        queue.add_task(
            task_id="r1",
            prompt="p",
            loop_id="lp",
            loop_objective="obj",
            loop_phase="build",
            iteration_label="iter 1",
        )
        queue.add_task(task_id="r2", prompt="p", loop_id="lp")
        task = queue.get_task("r2")
        assert task is not None
        assert task.loop_phase is None
        assert task.iteration_label is None
        assert task.header_label is None

    def test_carried_text_respects_the_length_limit(self, queue: TaskQueue) -> None:
        queue.add_task(
            task_id="r1",
            prompt="p",
            loop_id="lp",
            loop_objective="o" * (LOOP_TEXT_MAX_LENGTH + 100),
        )
        queue.add_task(task_id="r2", prompt="p", loop_id="lp")
        assert _fields(queue, "r2")[0] == "o" * LOOP_TEXT_MAX_LENGTH

    def test_a_loop_dropped_from_the_ledger_has_nothing_to_carry(
        self, queue: TaskQueue
    ) -> None:
        queue.add_task(
            task_id="first", prompt="p", loop_id="loop-0", loop_objective="obj-0"
        )
        queue.complete_task("first", _result())
        queue.cleanup_completed_tasks(age_seconds=0)
        for index in range(1, LOOP_HISTORY_MAX_LOOPS + 1):
            task_id = f"t{index}"
            queue.add_task(task_id=task_id, prompt="p", loop_id=f"loop-{index}")
            queue.complete_task(task_id, _result())
            queue.cleanup_completed_tasks(age_seconds=0)
        assert all(loop["loop_id"] != "loop-0" for loop in queue.get_loops_snapshot())
        queue.add_task(task_id="again", prompt="p", loop_id="loop-0")
        assert _fields(queue, "again") == (None, None)

    def test_rounds_added_without_a_queue_slot_do_not_change_anything(self) -> None:
        queue = _queue(max_tasks=1)
        try:
            queue.add_task(task_id="r1", prompt="p", loop_id="lp", loop_objective="obj")
            assert queue.add_task(task_id="r2", prompt="p", loop_id="lp") is False
            assert queue.get_task("r2") is None
        finally:
            queue.stop_cleanup()

    def test_clear_all_forgets_the_loop(self, queue: TaskQueue) -> None:
        queue.add_task(task_id="r1", prompt="p", loop_id="lp", loop_objective="obj")
        queue.complete_task("r1", _result())
        queue.clear_all_tasks()
        queue.add_task(task_id="r2", prompt="p", loop_id="lp")
        assert _fields(queue, "r2") == (None, None)


class TestCarriedTextSurvivesARestart:
    def test_carried_values_are_stored_on_the_task_and_in_the_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            persist = Path(tmp) / "tasks.json"
            first = _queue(str(persist))
            try:
                first.add_task(
                    task_id="r1",
                    prompt="p",
                    loop_id="lp",
                    loop_objective="obj",
                    success_criteria="crit",
                )
                first.add_task(task_id="r2", prompt="p", loop_id="lp")
            finally:
                first.stop_cleanup()
            snapshot = json.loads(persist.read_text(encoding="utf-8"))
            by_id = {item["task_id"]: item for item in snapshot["tasks"]}
            assert by_id["r2"]["loop_objective"] == "obj"
            assert by_id["r2"]["success_criteria"] == "crit"

            second = _queue(str(persist))
            try:
                assert _fields(second, "r2") == ("obj", "crit")
            finally:
                second.stop_cleanup()

    def test_a_round_added_after_a_restart_still_inherits_from_the_ledger(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            persist = Path(tmp) / "tasks.json"
            first = _queue(str(persist))
            try:
                first.add_task(
                    task_id="r1",
                    prompt="p",
                    loop_id="lp",
                    loop_objective="obj",
                    success_criteria="crit",
                )
                first.complete_task("r1", _result())
                first.cleanup_completed_tasks(age_seconds=0)
            finally:
                first.stop_cleanup()

            second = _queue(str(persist))
            try:
                assert second.get_task("r1") is None
                second.add_task(task_id="r2", prompt="p", loop_id="lp")
                assert _fields(second, "r2") == ("obj", "crit")
            finally:
                second.stop_cleanup()

    def test_a_ledger_without_a_readable_timestamp_still_gives_its_value(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            persist = Path(tmp) / "tasks.json"
            first = _queue(str(persist))
            try:
                first.add_task(
                    task_id="r1", prompt="p", loop_id="lp", loop_objective="obj"
                )
                first.complete_task("r1", _result())
                first.cleanup_completed_tasks(age_seconds=0)
            finally:
                first.stop_cleanup()
            snapshot = json.loads(persist.read_text(encoding="utf-8"))
            snapshot["loop_history"]["lp"]["updated_at"] = "not a timestamp"
            persist.write_text(json.dumps(snapshot), encoding="utf-8")

            second = _queue(str(persist))
            try:
                second.add_task(task_id="r2", prompt="p", loop_id="lp")
                assert _fields(second, "r2")[0] == "obj"
            finally:
                second.stop_cleanup()


class TestCarriedTextOverHttp:
    """The browser and the VS Code webview read the task rows the Web UI serves."""

    @pytest.fixture
    def client(self) -> Any:
        from ai_intervention_agent.task_queue_singleton import get_task_queue
        from ai_intervention_agent.web_ui import WebFeedbackUI

        ui = WebFeedbackUI(
            prompt="loop r803 base", task_id="loop-r803-base", port=19621
        )
        ui.app.config["TESTING"] = True
        ui.limiter.enabled = False
        get_task_queue().clear_all_tasks()
        yield ui.app.test_client()
        get_task_queue().clear_all_tasks()

    def test_round_two_rows_carry_the_loop_objective(self, client: Any) -> None:
        from ai_intervention_agent.task_queue_singleton import get_task_queue

        queue = get_task_queue()
        first = client.post(
            "/api/tasks",
            json={
                "task_id": "http-r1",
                "prompt": "round one",
                "loop_id": "http-loop",
                "loop_objective": "migrate auth",
                "success_criteria": "pytest green",
                "loop_phase": "build",
                "iteration_label": "iter 1",
            },
        )
        assert first.status_code == 200
        assert queue.complete_task("http-r1", _result("go on"))

        second = client.post(
            "/api/tasks",
            json={
                "task_id": "http-r2",
                "prompt": "round two",
                "loop_id": "http-loop",
                "loop_phase": "verify",
                "iteration_label": "iter 2",
            },
        )
        assert second.status_code == 200

        rows = {
            row["task_id"]: row for row in client.get("/api/tasks").get_json()["tasks"]
        }
        assert rows["http-r2"]["loop_objective"] == "migrate auth"
        assert rows["http-r2"]["success_criteria"] == "pytest green"
        assert rows["http-r2"]["loop_phase"] == "verify"
        assert rows["http-r2"]["iteration_label"] == "iter 2"

        detail = client.get("/api/tasks/http-r2").get_json()["task"]
        assert detail["loop_objective"] == "migrate auth"

        config = client.get("/api/config").get_json()
        assert config["task_id"] == "http-r2"
        assert config["loop_objective"] == "migrate auth"
        assert config["success_criteria"] == "pytest green"

        loops = client.get("/api/loops").get_json()["loops"]
        loop = next(item for item in loops if item["loop_id"] == "http-loop")
        assert loop["objective"] == "migrate auth"
        assert loop["success_criteria"] == "pytest green"
