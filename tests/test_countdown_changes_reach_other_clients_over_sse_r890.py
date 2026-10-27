"""R890：页面在 SSE 连着时只做 30 s 兜底轮询，倒计时的变化改由 ``task_changed`` 推给其他客户端。

现象（真实 Chrome 156 + CDP，页面连着真实 Web UI，SSE 已连）
==========================================================

``multi_task.js`` 的 ``source.onopen`` 把轮询间隔降到 30 s（``TASKS_POLL_SSE_FALLBACK_MS``），
注释和文档都说“SSE 连上后轮询降为 30 s 兜底”。但轮询回调每次成功都无条件把间隔写回 2 s
（``TASKS_POLL_BASE_MS``），所以 30 s 只管到第一次轮询（页面打开后 0.7 s 内三次请求，然后静默
30 s，第一次轮询之后就是每 2 s 一次）：之后 SSE 在线的页面照样每 2 s 一次 ``GET /api/tasks``，
有任务时每次再加一次 ``GET /api/tasks/<id>``。页面打开 45 s 之后的 60 s 窗口里实测：任务列表
30 次/分，有任务时合计 60 次/分。VS Code 面板（``webview-ui.js``）一直是对的：成功后按
``_sseConnected`` 选 30 s 或 2 s。

只把页面改对还不够：``POST /api/tasks/<id>/extend`` 和 ``/freeze`` 以前不发任何 SSE 事件，别的客户端
靠那个 2 s 轮询才看到倒计时变了。轮询降到 30 s 之后，另一个客户端可能最长 30 s 还在用旧的倒计时，
到点就自动提交。所以这两个操作成功后要补一条事件。配置里的默认倒计时改了（热更新，
``update_auto_resubmit_timeout_for_all``）时，未完成任务的倒计时也跟着变，是第三条同样的路径，
同样要补。事件沿用 ``task_changed``（不新增事件类型，schema 不变），``old_status`` 与
``new_status`` 都是任务当前状态；所有客户端对 ``task_changed`` 的反应都是重新拉任务列表，
同状态的事件无害。MCP 侧的 SSE 监听只认 ``new_status == "completed"``，而已完成的任务不能再
延长、冻结，也不再随默认倒计时变，所以它永远收不到这种事件。

修复后同一页面（同样的窗口）：任务列表 2 次/分，有任务时合计 4 次/分；经 API 续期后页面重读任务
列表 87–93 ms（8 次，中位 89 ms；修复前中位 1.48 s，范围 0.5–1.9 s，页面刚打开时的第一次是
15.7 s，因为要等那次 30 s 之后的第一次轮询）。

契约
====

1. 轮询回调成功后：SSE 连着 → 下一次 30 s，没连 → 2 s；连着时连续成功也不回到 2 s；SSE 断开后的
   下一次成功回到 2 s；VS Code 面板的同一处与之一致；
2. ``extend_task_deadline`` / ``freeze_task_deadline`` 成功后恰好触发一次状态回调，参数是
   ``(task_id, 当前状态, 当前状态)``；被拒绝（找不到、超配额、已完成、已冻结、秒数不合法）时不触发；
   ``update_auto_resubmit_timeout_for_all`` 对每个倒计时真的变了的任务各触发一次（显式指定过
   倒计时的、已完成的、本来就是这个值的不触发；再用同一个值调一次什么都不发）；
3. 回调在写锁之外触发（回调运行时，别的线程读队列不会被挡住；读写锁是 RLock 做的，
   写者自己线程里的读永远通得过，所以必须换一个线程来探），回调抛异常不影响延长 / 冻结 /
   默认倒计时更新的结果，也不会让后面的任务漏掉通知；
4. 经真实路由 + SSE 总线：``POST /extend``（手动和输入两种）和 ``POST /freeze`` 成功后总线上多出
   一条 ``task_changed``，payload 通过 schema 校验，且带 ``stats``；被拒绝的请求没有；配置热更新
   回调 ``_sync_existing_tasks_timeout_from_config`` 在默认倒计时变了之后也发一条，没变就不发；
5. 三个前端消费者（页面、VS Code 面板、VS Code 扩展）都不比较 ``old_status`` 和 ``new_status``
   来决定要不要刷新，同状态事件和别的事件一样触发重新拉取。
"""

from __future__ import annotations

import json
import re
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from flask.testing import FlaskClient

import ai_intervention_agent.web_ui as web_ui
from ai_intervention_agent.sse_event_schemas import validate_payload
from ai_intervention_agent.task_queue import TaskQueue
from ai_intervention_agent.task_queue_singleton import get_task_queue
from ai_intervention_agent.web_ui import WebFeedbackUI
from ai_intervention_agent.web_ui_routes.task import (
    COUNTDOWN_EXTEND_SECONDS_MAX,
    COUNTDOWN_EXTEND_SECONDS_MIN,
    COUNTDOWN_EXTENDS_MAX,
    COUNTDOWN_TYPING_EXTENDS_MAX,
    _on_task_status_change,
    _sse_bus,
)
from tests.test_multi_task_poll_controller_lifecycle_r452 import (
    MULTI_TASK_JS,
    _node_available,
    _poll_harness,
    _run_node,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
WEBVIEW_UI_JS = REPO_ROOT / "packages" / "vscode" / "webview-ui.js"
EXTENSION_TS = REPO_ROOT / "packages" / "vscode" / "extension.ts"
LOOPBACK = {"REMOTE_ADDR": "127.0.0.1"}
TASK = "r890-task"

KW: dict[str, int] = {
    "max_extends": COUNTDOWN_EXTENDS_MAX,
    "min_seconds": COUNTDOWN_EXTEND_SECONDS_MIN,
    "max_seconds": COUNTDOWN_EXTEND_SECONDS_MAX,
}

Event = tuple[str, str | None, str]


# ---------------------------------------------------------------------------
# TaskQueue: who is told, and when
# ---------------------------------------------------------------------------


@pytest.fixture
def queue() -> Iterator[TaskQueue]:
    q = TaskQueue(max_tasks=5)
    try:
        yield q
    finally:
        q.stop_cleanup()


def _watched(q: TaskQueue) -> list[Event]:
    events: list[Event] = []
    q.register_status_change_callback(
        lambda task_id, old, new: events.append((task_id, old, new))
    )
    return events


def _status(q: TaskQueue, task_id: str) -> str:
    task = q.get_task(task_id)
    assert task is not None
    return str(task.status)


def _timeout(q: TaskQueue, task_id: str) -> int:
    task = q.get_task(task_id)
    assert task is not None
    return task.auto_resubmit_timeout


def _lock_probe(q: TaskQueue) -> list[bool]:
    """Registers a callback that tells, per call, whether the queue's write lock was free.

    Another thread reads the queue while the callback is still running. It only gets through
    if the write lock has been released: the writer, which is the calling thread, waits for it.
    (A read from the writer's own thread would always get through, the lock is built on an
    RLock, so it proves nothing.)
    """
    reached: list[bool] = []

    def callback(task_id: str, old: str | None, new: str) -> None:
        reader = threading.Thread(target=lambda: q.get_task(task_id), daemon=True)
        reader.start()
        reader.join(timeout=3)
        reached.append(not reader.is_alive())

    q.register_status_change_callback(callback)
    return reached


class TestQueueAnnouncesCountdownChanges:
    def test_a_successful_extension_announces_the_task_once(
        self, queue: TaskQueue
    ) -> None:
        queue.add_task(task_id="t1", prompt="p", auto_resubmit_timeout=300)
        events = _watched(queue)
        status = _status(queue, "t1")

        ok, code, used, timeout = queue.extend_task_deadline("t1", 60, **KW)

        assert (ok, code, used, timeout) == (True, None, 1, 360)
        assert events == [("t1", status, status)]
        assert _status(queue, "t1") == status

    def test_a_typing_extension_announces_it_too(self, queue: TaskQueue) -> None:
        queue.add_task(task_id="t1", prompt="p", auto_resubmit_timeout=300)
        events = _watched(queue)
        status = _status(queue, "t1")

        ok, _code, used, _timeout = queue.extend_task_deadline(
            "t1", 60, typing_max_extends=COUNTDOWN_TYPING_EXTENDS_MAX, **KW
        )

        assert ok is True
        assert used == 0  # the manual quota is not touched
        assert events == [("t1", status, status)]

    def test_a_successful_freeze_announces_the_task_once(
        self, queue: TaskQueue
    ) -> None:
        queue.add_task(task_id="t1", prompt="p", auto_resubmit_timeout=300)
        events = _watched(queue)
        status = _status(queue, "t1")

        assert queue.freeze_task_deadline("t1") == (True, None, 0)

        assert events == [("t1", status, status)]

    def test_refusals_say_nothing(self, queue: TaskQueue) -> None:
        queue.add_task(task_id="t1", prompt="p", auto_resubmit_timeout=300)
        events = _watched(queue)
        status = _status(queue, "t1")

        # the task is not there; the seconds are out of range
        assert queue.extend_task_deadline("nope", 60, **KW)[:2] == (
            False,
            "task_not_found",
        )
        assert queue.freeze_task_deadline("nope")[:2] == (False, "task_not_found")
        assert queue.extend_task_deadline("t1", 1, **KW)[:2] == (
            False,
            "invalid_seconds",
        )
        assert events == []

        # the manual quota is spent: three announcements for three extensions, then silence
        for _ in range(COUNTDOWN_EXTENDS_MAX):
            assert queue.extend_task_deadline("t1", 60, **KW)[0] is True
        assert events == [("t1", status, status)] * COUNTDOWN_EXTENDS_MAX
        assert queue.extend_task_deadline("t1", 60, **KW)[:2] == (
            False,
            "extends_limit_reached",
        )
        assert len(events) == COUNTDOWN_EXTENDS_MAX

        # frozen once: announced; frozen already: silence; nothing left to extend either
        assert queue.freeze_task_deadline("t1")[0] is True
        assert len(events) == COUNTDOWN_EXTENDS_MAX + 1
        assert queue.freeze_task_deadline("t1")[:2] == (False, "already_frozen")
        assert queue.extend_task_deadline("t1", 60, **KW)[:2] == (
            False,
            "auto_resubmit_disabled",
        )
        assert len(events) == COUNTDOWN_EXTENDS_MAX + 1

        # a task that has an answer cannot be extended or frozen any more
        queue.add_task(task_id="t2", prompt="p", auto_resubmit_timeout=300)
        assert queue.complete_task("t2", {"user_input": "x"}) is True
        settled = list(events)
        assert queue.extend_task_deadline("t2", 60, **KW)[:2] == (
            False,
            "task_completed",
        )
        assert queue.freeze_task_deadline("t2")[:2] == (False, "task_completed")
        assert events == settled
        # so the MCP side, which only reacts to new_status == "completed", never sees one of these
        assert all(
            new != "completed" for task_id, _old, new in events if task_id == "t1"
        )

    def test_the_callback_runs_outside_the_write_lock(self, queue: TaskQueue) -> None:
        queue.add_task(task_id="t1", prompt="p", auto_resubmit_timeout=300)
        reached = _lock_probe(queue)

        assert queue.extend_task_deadline("t1", 60, **KW)[0] is True
        assert queue.freeze_task_deadline("t1")[0] is True

        assert reached == [True, True], "the callback ran while the write lock was held"

    def test_a_failing_callback_does_not_undo_the_change(
        self, queue: TaskQueue
    ) -> None:
        queue.add_task(task_id="t1", prompt="p", auto_resubmit_timeout=300)

        def broken(task_id: str, old: str | None, new: str) -> None:
            raise RuntimeError("subscriber is gone")

        queue.register_status_change_callback(broken)

        ok, _code, used, timeout = queue.extend_task_deadline("t1", 60, **KW)

        assert (ok, used, timeout) == (True, 1, 360)
        assert _timeout(queue, "t1") == 360
        assert queue.freeze_task_deadline("t1")[0] is True
        assert _timeout(queue, "t1") == 0

    def test_a_new_default_timeout_announces_each_task_whose_countdown_moved(
        self, queue: TaskQueue
    ) -> None:
        queue.add_task(task_id="t1", prompt="p", auto_resubmit_timeout=300)
        queue.add_task(task_id="t2", prompt="p", auto_resubmit_timeout=300)
        # asked for by name: not the default's to move
        queue.add_task(
            task_id="t3",
            prompt="p",
            auto_resubmit_timeout=300,
            auto_resubmit_timeout_explicit=True,
        )
        # already at the new value
        queue.add_task(task_id="t4", prompt="p", auto_resubmit_timeout=600)
        # it has its answer: no countdown is left to move
        queue.add_task(task_id="t5", prompt="p", auto_resubmit_timeout=300)
        assert queue.complete_task("t5", {"user_input": "x"}) is True
        events = _watched(queue)
        status = {name: _status(queue, name) for name in ("t1", "t2", "t3", "t4")}

        assert queue.update_auto_resubmit_timeout_for_all(600) == 2

        assert events == [
            ("t1", status["t1"], status["t1"]),
            ("t2", status["t2"], status["t2"]),
        ]
        assert [_timeout(queue, name) for name in ("t1", "t2", "t3", "t4", "t5")] == [
            600,
            600,
            300,
            600,
            300,
        ]
        # the same value again moves nothing and says nothing
        assert queue.update_auto_resubmit_timeout_for_all(600) == 0
        assert len(events) == 2

    def test_the_timeout_announcements_are_made_outside_the_write_lock(
        self, queue: TaskQueue
    ) -> None:
        queue.add_task(task_id="t1", prompt="p", auto_resubmit_timeout=300)
        queue.add_task(task_id="t2", prompt="p", auto_resubmit_timeout=300)
        reached = _lock_probe(queue)

        assert queue.update_auto_resubmit_timeout_for_all(600) == 2

        assert reached == [True, True], "the callback ran while the write lock was held"

    def test_a_failing_callback_does_not_undo_a_new_default_timeout(
        self, queue: TaskQueue
    ) -> None:
        queue.add_task(task_id="t1", prompt="p", auto_resubmit_timeout=300)
        queue.add_task(task_id="t2", prompt="p", auto_resubmit_timeout=300)
        told: list[str] = []

        def broken(task_id: str, old: str | None, new: str) -> None:
            told.append(task_id)
            raise RuntimeError("subscriber is gone")

        queue.register_status_change_callback(broken)

        assert queue.update_auto_resubmit_timeout_for_all(600) == 2

        assert [_timeout(queue, "t1"), _timeout(queue, "t2")] == [600, 600]
        # the second task is announced although the announcement of the first one failed
        assert told == ["t1", "t2"]


# ---------------------------------------------------------------------------
# Through the real routes and the real SSE bus
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def ui() -> WebFeedbackUI:
    instance = WebFeedbackUI(
        prompt="r890", task_id="r890-initial", auto_resubmit_timeout=0, port=19890
    )
    instance.app.config["TESTING"] = True
    instance.limiter.enabled = False
    object.__setattr__(instance, "shutdown_server", lambda: None)
    return instance


class Bus:
    """Subscribes to the real SSE bus and reads the ``task_changed`` events off it."""

    def __init__(self) -> None:
        self.q = _sse_bus.subscribe()

    def drain(self) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        while True:
            try:
                item = self.q.get_nowait()
            except Exception:
                return events
            if item.get("type") == "task_changed":
                events.append(item["data"])

    def close(self) -> None:
        _sse_bus.unsubscribe(self.q)


@pytest.fixture
def client(ui: WebFeedbackUI) -> Iterator[tuple[FlaskClient, Bus]]:
    tq = get_task_queue()
    tq.clear_all_tasks()
    tq.add_task(task_id=TASK, prompt="p", auto_resubmit_timeout=300)
    # what the first ``GET /api/events`` does in a running Web UI
    tq.register_status_change_callback(_on_task_status_change)
    bus = Bus()
    try:
        yield ui.app.test_client(), bus
    finally:
        bus.close()
        tq.clear_all_tasks()


def _post(client: FlaskClient, task_id: str, action: str, body: Any = None) -> Any:
    return client.post(
        f"/api/tasks/{task_id}/{action}", json=body, environ_base=LOOPBACK
    )


def _mine(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [e for e in events if e["task_id"] == TASK]


class TestRoutesPushTheChange:
    def test_extend_puts_a_task_changed_on_the_bus(
        self, client: tuple[FlaskClient, Bus]
    ) -> None:
        http, bus = client
        status = _status(get_task_queue(), TASK)
        bus.drain()

        resp = _post(http, TASK, "extend", {"seconds": 60})

        assert resp.status_code == 200
        events = _mine(bus.drain())
        assert len(events) == 1
        event = events[0]
        assert (event["old_status"], event["new_status"]) == (status, status)
        assert validate_payload("task_changed", event) == []
        assert set(event["stats"]) >= {"active", "pending", "completed"}

    def test_a_typing_extension_does_too(self, client: tuple[FlaskClient, Bus]) -> None:
        http, bus = client
        bus.drain()

        resp = _post(http, TASK, "extend", {"seconds": 60, "reason": "typing"})

        assert resp.status_code == 200
        assert len(_mine(bus.drain())) == 1

    def test_freeze_puts_a_task_changed_on_the_bus(
        self, client: tuple[FlaskClient, Bus]
    ) -> None:
        http, bus = client
        status = _status(get_task_queue(), TASK)
        bus.drain()

        resp = _post(http, TASK, "freeze")

        assert resp.status_code == 200
        events = _mine(bus.drain())
        assert [(e["old_status"], e["new_status"]) for e in events] == [
            (status, status)
        ]

    def test_refused_requests_put_nothing_on_the_bus(
        self, client: tuple[FlaskClient, Bus]
    ) -> None:
        http, bus = client
        for _ in range(COUNTDOWN_EXTENDS_MAX):
            assert _post(http, TASK, "extend", {"seconds": 60}).status_code == 200
        bus.drain()

        # the manual quota is spent
        assert _post(http, TASK, "extend", {"seconds": 60}).status_code == 422
        # the request itself is wrong
        assert _post(http, TASK, "extend", {"seconds": "60"}).status_code == 400
        assert _post(http, TASK, "extend", {"reason": "nope"}).status_code == 400
        assert (
            _post(http, TASK, "extend", {"seconds": 1, "reason": "typing"}).status_code
            == 400
        )
        # no such task
        assert _post(http, "ghost", "extend", {}).status_code == 404
        assert _post(http, "ghost", "freeze").status_code == 404
        assert bus.drain() == []

        # frozen: announced once, and the second freeze is turned down quietly
        assert _post(http, TASK, "freeze").status_code == 200
        assert len(_mine(bus.drain())) == 1
        assert _post(http, TASK, "freeze").status_code == 409
        assert bus.drain() == []

    def test_a_new_default_countdown_in_the_config_puts_it_on_the_bus(
        self, client: tuple[FlaskClient, Bus], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _http, bus = client
        status = _status(get_task_queue(), TASK)
        # what the config file watcher finds after ``frontend_countdown`` was edited
        config = MagicMock()
        config.get_section.return_value = {"frontend_countdown": 450}
        monkeypatch.setattr(web_ui, "get_config", lambda: config)
        monkeypatch.setattr(web_ui, "_LAST_APPLIED_AUTO_RESUBMIT_TIMEOUT", 300)
        monkeypatch.setattr(web_ui, "_CURRENT_WEB_UI_INSTANCE", None)
        bus.drain()

        web_ui._sync_existing_tasks_timeout_from_config()

        events = _mine(bus.drain())
        assert [(e["old_status"], e["new_status"]) for e in events] == [
            (status, status)
        ]
        assert validate_payload("task_changed", events[0]) == []
        assert _timeout(get_task_queue(), TASK) == 450

        # the default has not changed since: nothing moves, nothing is announced
        web_ui._sync_existing_tasks_timeout_from_config()
        assert bus.drain() == []


# ---------------------------------------------------------------------------
# The pages: how often they poll while SSE is connected
# ---------------------------------------------------------------------------

TASKS_POLL_BASE_MS = 2000
TASKS_POLL_SSE_FALLBACK_MS = 30000


def _poll_after_success(case_js: str) -> Any:
    """Runs ``multi_task.js`` in a sandbox with a poll that always succeeds.

    ``runPoll()`` fires the scheduled poll timer once and returns the delay of the next one.
    """
    script = _poll_harness(
        "fetchAndApplyTasks = async () => true;\n"
        "async function runPoll() {\n"
        "  const before = __timeouts.length;\n"
        "  scheduleNextTasksPoll(0);\n"
        "  await __timeouts[before].fn();\n"
        "  return __timeouts[__timeouts.length - 1].delay;\n"
        "}\n" + case_js
    )
    return json.loads(_run_node(script))


@pytest.mark.skipif(not _node_available(), reason="node runtime unavailable")
class TestWebPagePollCadence:
    def test_constants_are_the_ones_these_tests_assume(self) -> None:
        source = MULTI_TASK_JS.read_text(encoding="utf-8")
        assert f"var TASKS_POLL_BASE_MS = {TASKS_POLL_BASE_MS};" in source
        assert (
            f"var TASKS_POLL_SSE_FALLBACK_MS = {TASKS_POLL_SSE_FALLBACK_MS};" in source
        )

    def test_a_connected_page_keeps_the_safety_net_pace(self) -> None:
        result = _poll_after_success(
            """
            _sseConnected = true;
            tasksPollBackoffMs = 30000;
            const delays = [];
            for (let i = 0; i < 4; i += 1) delays.push(await runPoll());
            process.stdout.write(JSON.stringify({ delays, backoff: tasksPollBackoffMs }));
            """
        )
        assert result == {
            "delays": [TASKS_POLL_SSE_FALLBACK_MS] * 4,
            "backoff": TASKS_POLL_SSE_FALLBACK_MS,
        }

    def test_a_page_without_sse_polls_every_two_seconds(self) -> None:
        result = _poll_after_success(
            """
            _sseConnected = false;
            const delays = [];
            for (let i = 0; i < 3; i += 1) delays.push(await runPoll());
            process.stdout.write(JSON.stringify({ delays, backoff: tasksPollBackoffMs }));
            """
        )
        assert result == {
            "delays": [TASKS_POLL_BASE_MS] * 3,
            "backoff": TASKS_POLL_BASE_MS,
        }

    def test_the_pace_follows_the_stream_when_it_drops_and_comes_back(self) -> None:
        result = _poll_after_success(
            """
            _sseConnected = true;
            const seen = [];
            seen.push(await runPoll());
            _sseConnected = false;      // the stream broke
            seen.push(await runPoll());
            _sseConnected = true;       // and came back
            seen.push(await runPoll());
            process.stdout.write(JSON.stringify({ seen }));
            """
        )
        assert result == {
            "seen": [
                TASKS_POLL_SSE_FALLBACK_MS,
                TASKS_POLL_BASE_MS,
                TASKS_POLL_SSE_FALLBACK_MS,
            ]
        }


def _squash(text: str) -> str:
    return "".join(text.split())


def _between(source: str, start: str, end: str) -> str:
    begin = source.index(start)
    return source[begin : source.index(end, begin)]


class TestFrontendsAgree:
    def test_both_polls_pick_the_pace_by_the_stream_on_success(self) -> None:
        page = _squash(
            _between(
                MULTI_TASK_JS.read_text(encoding="utf-8"),
                "function scheduleNextTasksPoll(",
                "function startTasksPolling(",
            )
        )
        panel = _squash(
            _between(
                WEBVIEW_UI_JS.read_text(encoding="utf-8"),
                "function scheduleNextPoll(",
                "function stopPolling(",
            )
        )
        assert (
            "tasksPollBackoffMs=_sseConnected?TASKS_POLL_SSE_FALLBACK_MS:TASKS_POLL_BASE_MS;"
            in page
        )
        assert "constbase=_sseConnected?POLL_SSE_FALLBACK_MS:POLL_BASE_MS" in panel
        # the base pace is never written back on its own in the page's success branch
        assert "tasksPollBackoffMs=TASKS_POLL_BASE_MS;" not in page

    def test_no_consumer_decides_by_comparing_the_two_statuses(self) -> None:
        compare = re.compile(
            r"old_status\s*[!=]==?\s*[\w.]*new_status|new_status\s*[!=]==?\s*[\w.]*old_status"
        )
        for path in (MULTI_TASK_JS, WEBVIEW_UI_JS, EXTENSION_TS):
            assert compare.search(path.read_text(encoding="utf-8")) is None, path.name

    def test_every_consumer_refetches_on_any_task_changed(self) -> None:
        page = _squash(
            _between(
                MULTI_TASK_JS.read_text(encoding="utf-8"),
                'source.addEventListener("task_changed"',
                'source.addEventListener("gap_warning"',
            )
        )
        panel = _squash(
            _between(
                WEBVIEW_UI_JS.read_text(encoding="utf-8"),
                "source.addEventListener('task_changed'",
                "source.addEventListener('config_changed'",
            )
        )
        extension = _squash(
            _between(
                EXTENSION_TS.read_text(encoding="utf-8"),
                "const ev = JSON.parse(dataStr);",
                "} catch {",
            )
        )
        assert '_scheduleSharedSseFetch("sse",80);' in page
        assert "pollAllData('sse')" in panel and "},80)" in panel
        assert "scheduleStatusPoll(0);" in extension and "},80);" in extension
