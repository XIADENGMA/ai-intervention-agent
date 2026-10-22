"""R803 regression coverage: a loop keeps its objective and its "Rounds" list across rounds.

``interactive_feedback`` tells the agent to pass ``loop_objective`` on the first round of
a ``loop_id`` and that later rounds "may omit it", and that the objective and
``success_criteria`` are "shown to the reviewer as loop context above the prompt". The
ledger honours that (``GET /api/loops`` keeps the last non-empty value), but the strip
above the prompt is drawn from the *task's own* fields, so from the second round on the
reviewer saw only the three chips: the objective and the success criteria they are meant to
judge the evidence against were gone after one round, in the browser and in the VS Code
webview alike.

Two more defects sat in the same "Rounds" panel:

* the list was filled by an ``await``-ing click handler that only checked "is the panel
  still expanded" after the response. Expand, collapse and expand again within the
  response time and both responses passed that check, so every round was drawn twice
  (and a failing response wrote its error row into the newer list);
* an expanded panel never refreshed. Submitting round N while it was open brought round
  N+1 up under a list that still said "No completed rounds yet" (or lacked round N).

The fix:

* ``TaskQueue.add_task`` fills a missing ``loop_objective`` / ``success_criteria`` of a
  round that belongs to a loop with the loop's most recent value (a round still in the
  queue, or the ledger, whichever was supplied last). ``loop_phase`` and
  ``iteration_label`` describe one round and are never carried;
* each expansion of the panel is a generation; a response only draws when its generation
  is still current (collapsing also ends the generation), and a new task of the same loop
  re-draws an open panel.
"""

from __future__ import annotations

import json
import shutil
import subprocess
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
MULTI_TASK_JS = (
    REPO_ROOT / "src" / "ai_intervention_agent" / "static" / "js" / "multi_task.js"
)
WEBVIEW_JS = REPO_ROOT / "packages" / "vscode" / "webview-ui.js"

needs_node = pytest.mark.skipif(
    shutil.which("node") is None, reason="node runtime unavailable"
)

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


# ---------------------------------------------------------------------------
# The "Rounds" panel, run for real (node + a fake DOM), in both front ends.
# ---------------------------------------------------------------------------


def _segment(source: str, start_marker: str, end_marker: str) -> str:
    start = source.index(start_marker)
    end = source.index(end_marker, start)
    return source[start:end]


def _web_segment() -> str:
    return _segment(
        MULTI_TASK_JS.read_text(encoding="utf-8"),
        "function updateLoopContext(task) {",
        "function updateFeedbackPlaceholder(placeholder) {",
    )


def _webview_segment() -> str:
    return _segment(
        WEBVIEW_JS.read_text(encoding="utf-8"),
        "function updateLoopContext(task) {",
        "function updateFeedbackPlaceholder(placeholder) {",
    )


HARNESS = r"""
const vm = require('vm');
const fs = require('fs');
const flavor = process.argv[2];
const segment = fs.readFileSync(process.argv[3], 'utf8');
const scenario = process.argv[4];

class El {
  constructor(id) {
    this.id = id;
    this.children = [];
    this.attrs = {};
    this.dataset = {};
    this.style = { display: '' };
    this.className = '';
    this._text = '';
    this._classes = new Set();
    this.listeners = {};
    const self = this;
    this.classList = {
      add: (c) => self._classes.add(c),
      remove: (c) => self._classes.delete(c),
      contains: (c) => self._classes.has(c),
    };
  }
  setAttribute(k, v) { this.attrs[k] = String(v); }
  getAttribute(k) { return Object.prototype.hasOwnProperty.call(this.attrs, k) ? this.attrs[k] : null; }
  removeAttribute(k) { delete this.attrs[k]; }
  appendChild(c) { this.children.push(c); return c; }
  addEventListener(type, fn) { (this.listeners[type] = this.listeners[type] || []).push(fn); }
  get textContent() { return this._text; }
  set textContent(v) { this._text = String(v); if (String(v) === '') this.children = []; }
}

const IDS = flavor === 'web'
  ? { toggle: 'loop-history-toggle', list: 'loop-history-list', count: 'loop-history-count' }
  : { toggle: 'loopHistoryToggle', list: 'loopHistoryList', count: 'loopHistoryCount' };

const els = {};
const getEl = (id) => (els[id] = els[id] || new El(id));
const document = { getElementById: getEl, createElement: () => new El('created') };
const pending = [];
const request = () => new Promise((resolve, reject) => { pending.push({ resolve, reject }); });
const sandbox = { document, console, Date, isNaN, Array, Object, String, Number };
if (flavor === 'web') {
  sandbox.window = {};
  sandbox.fetchWithTimeout = () => request();
} else {
  sandbox.SERVER_URL = 'http://web-ui.test';
  sandbox.fetch = () => request();
  sandbox.t = (key) => key;
}
const ctx = vm.createContext(sandbox);
vm.runInContext(segment, ctx);

const tick = () => new Promise((resolve) => setImmediate(resolve));
const rounds = (n, tag) => Array.from({ length: n }, (_, i) => ({
  task_id: 'task-' + i,
  iteration_label: (tag || 'iter') + ' ' + i,
  loop_phase: 'build',
  completed_at: '2026-01-01T00:00:00Z',
  verdict: { user_input: 'verdict ' + i, selected_options: [], image_count: 0 },
}));
const ok = (n, tag) => ({ ok: true, json: async () => ({ success: true, loops: [{ loop_id: 'lp', rounds: rounds(n, tag) }] }) });
const loopTask = (id, loopId) => ({ task_id: id, loop_id: loopId === undefined ? 'lp' : loopId });
const list = () => getEl(IDS.list);
const toggle = () => getEl(IDS.toggle);
const rowCount = () => list().children.filter((c) => c.className === 'loop-history-row').length;
const snapshot = (extra) => Object.assign({
  rows: rowCount(),
  children: list().children.length,
  expanded: toggle().getAttribute('aria-expanded'),
  requests: pending.length,
}, extra || {});

async function run() {
  const call = (fn) => vm.runInContext(fn, ctx);
  if (scenario === 'rapid_toggle') {
    call('updateLoopContext')(loopTask('t1'));
    const a = call('toggleLoopHistory')();
    const b = call('toggleLoopHistory')();
    const c = call('toggleLoopHistory')();
    pending[0].resolve(ok(2));
    await tick();
    pending[1].resolve(ok(2));
    await Promise.all([a, b, c]);
    await tick();
    return snapshot();
  }
  if (scenario === 'collapse_before_response') {
    call('updateLoopContext')(loopTask('t1'));
    const a = call('toggleLoopHistory')();
    await call('toggleLoopHistory')();
    pending[0].resolve(ok(2));
    await a;
    await tick();
    return snapshot();
  }
  if (scenario === 'stale_error_after_reexpand') {
    call('updateLoopContext')(loopTask('t1'));
    const a = call('toggleLoopHistory')();
    await call('toggleLoopHistory')();
    const c = call('toggleLoopHistory')();
    pending[0].reject(new Error('network down'));
    await a;
    await tick();
    const afterStaleError = snapshot();
    pending[1].resolve(ok(2));
    await c;
    await tick();
    return { afterStaleError, final: snapshot() };
  }
  if (scenario === 'refresh_same_loop') {
    call('updateLoopContext')(loopTask('t1'));
    const a = call('toggleLoopHistory')();
    pending[0].resolve(ok(1));
    await a;
    await tick();
    const before = snapshot();
    call('updateLoopContext')(loopTask('t2'));
    const requestsAfterTaskChange = pending.length;
    pending[1].resolve(ok(2));
    await tick();
    await tick();
    return { before, requestsAfterTaskChange, after: snapshot() };
  }
  if (scenario === 'refresh_stale_ordering') {
    call('updateLoopContext')(loopTask('t1'));
    const a = call('toggleLoopHistory')();
    call('updateLoopContext')(loopTask('t2'));
    pending[1].resolve(ok(2));
    await tick();
    await tick();
    pending[0].resolve(ok(1));
    await a;
    await tick();
    return snapshot();
  }
  if (scenario === 'no_refresh_when_collapsed') {
    call('updateLoopContext')(loopTask('t1'));
    call('updateLoopContext')(loopTask('t2'));
    call('updateLoopContext')(loopTask('t3'));
    await tick();
    return snapshot();
  }
  if (scenario === 'no_refresh_for_the_same_task') {
    call('updateLoopContext')(loopTask('t1'));
    const a = call('toggleLoopHistory')();
    pending[0].resolve(ok(1));
    await a;
    await tick();
    call('updateLoopContext')(loopTask('t1'));
    call('updateLoopContext')(loopTask('t1'));
    await tick();
    return snapshot();
  }
  if (scenario === 'no_refresh_without_a_task_id') {
    call('updateLoopContext')(loopTask('t1'));
    const a = call('toggleLoopHistory')();
    pending[0].resolve(ok(1));
    await a;
    await tick();
    call('updateLoopContext')({ loop_id: 'lp' });
    await tick();
    return snapshot();
  }
  if (scenario === 'other_loop_collapses') {
    call('updateLoopContext')(loopTask('t1'));
    const a = call('toggleLoopHistory')();
    pending[0].resolve(ok(1));
    await a;
    await tick();
    call('updateLoopContext')(loopTask('t9', 'another-loop'));
    await tick();
    return snapshot();
  }
  if (scenario === 'plain_task_collapses') {
    call('updateLoopContext')(loopTask('t1'));
    const a = call('toggleLoopHistory')();
    pending[0].resolve(ok(1));
    await a;
    await tick();
    call('updateLoopContext')({ task_id: 'plain' });
    await tick();
    return snapshot();
  }
  if (scenario === 'refresh_failure_shows_one_message') {
    call('updateLoopContext')(loopTask('t1'));
    const a = call('toggleLoopHistory')();
    pending[0].resolve(ok(1));
    await a;
    await tick();
    call('updateLoopContext')(loopTask('t2'));
    pending[1].reject(new Error('boom'));
    await tick();
    await tick();
    return snapshot({ message: list().children.map((c) => c.textContent) });
  }
  throw new Error('unknown scenario ' + scenario);
}

run().then((result) => { process.stdout.write(JSON.stringify(result)); }, (error) => {
  process.stderr.write(String(error && error.stack || error));
  process.exit(1);
});
"""


def _run(flavor: str, scenario: str, tmp_path: Path) -> Any:
    segment = _web_segment() if flavor == "web" else _webview_segment()
    segment_path = tmp_path / f"{flavor}-segment.js"
    segment_path.write_text(segment, encoding="utf-8")
    harness_path = tmp_path / "harness.js"
    harness_path.write_text(HARNESS, encoding="utf-8")
    completed = subprocess.run(
        ["node", str(harness_path), flavor, str(segment_path), scenario],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout)


FLAVORS = ["web", "webview"]


@needs_node
@pytest.mark.parametrize("flavor", FLAVORS)
class TestRoundsPanel:
    def test_expand_collapse_expand_draws_each_round_once(
        self, flavor: str, tmp_path: Path
    ) -> None:
        state = _run(flavor, "rapid_toggle", tmp_path)
        assert state["rows"] == 2
        assert state["children"] == 2
        assert state["expanded"] == "true"

    def test_a_response_after_collapsing_draws_nothing(
        self, flavor: str, tmp_path: Path
    ) -> None:
        state = _run(flavor, "collapse_before_response", tmp_path)
        assert state["children"] == 0
        assert state["expanded"] == "false"

    def test_an_old_failure_does_not_write_into_the_newer_list(
        self, flavor: str, tmp_path: Path
    ) -> None:
        state = _run(flavor, "stale_error_after_reexpand", tmp_path)
        assert state["afterStaleError"]["children"] == 0
        assert state["final"]["rows"] == 2
        assert state["final"]["children"] == 2

    def test_an_open_panel_is_redrawn_when_the_next_round_of_the_loop_arrives(
        self, flavor: str, tmp_path: Path
    ) -> None:
        state = _run(flavor, "refresh_same_loop", tmp_path)
        assert state["before"]["rows"] == 1
        assert state["requestsAfterTaskChange"] == 2
        assert state["after"]["rows"] == 2
        assert state["after"]["children"] == 2
        assert state["after"]["expanded"] == "true"

    def test_an_older_response_never_overwrites_the_refresh(
        self, flavor: str, tmp_path: Path
    ) -> None:
        state = _run(flavor, "refresh_stale_ordering", tmp_path)
        assert state["rows"] == 2
        assert state["children"] == 2

    def test_a_closed_panel_is_not_fetched_for_on_every_round(
        self, flavor: str, tmp_path: Path
    ) -> None:
        state = _run(flavor, "no_refresh_when_collapsed", tmp_path)
        assert state["requests"] == 0
        assert state["expanded"] == "false"

    def test_polling_the_same_task_does_not_refetch(
        self, flavor: str, tmp_path: Path
    ) -> None:
        state = _run(flavor, "no_refresh_for_the_same_task", tmp_path)
        assert state["requests"] == 1
        assert state["rows"] == 1

    def test_a_payload_without_a_task_id_does_not_refetch(
        self, flavor: str, tmp_path: Path
    ) -> None:
        state = _run(flavor, "no_refresh_without_a_task_id", tmp_path)
        assert state["requests"] == 1
        assert state["rows"] == 1

    def test_another_loop_still_closes_the_panel(
        self, flavor: str, tmp_path: Path
    ) -> None:
        state = _run(flavor, "other_loop_collapses", tmp_path)
        assert state["expanded"] == "false"
        assert state["children"] == 0

    def test_a_plain_task_still_closes_the_panel(
        self, flavor: str, tmp_path: Path
    ) -> None:
        state = _run(flavor, "plain_task_collapses", tmp_path)
        assert state["expanded"] == "false"
        assert state["children"] == 0

    def test_a_failed_refresh_shows_one_message_not_a_stale_list(
        self, flavor: str, tmp_path: Path
    ) -> None:
        state = _run(flavor, "refresh_failure_shows_one_message", tmp_path)
        assert state["rows"] == 0
        assert state["children"] == 1
