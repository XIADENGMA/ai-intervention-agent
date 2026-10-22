"""R825 — 等待回复期间 Web UI 进程没了，要把它拉起来，而不是静等到后端超时。

事故链（修复前，由真实 stdio MCP 服务器 + 真实 Web UI 子进程的故障注入复现）
------------------------------------------------------------------------

1. 两个 IDE 窗口各有一个 MCP 服务器，配置相同，所以共用同一个端口上的 Web UI：谁先调用
   ``interactive_feedback`` 谁起子进程，另一个发现服务已在运行就直接用，不拥有它。
2. 起子进程的那个窗口关闭 → 它的 MCP 服务器退出 → ``ServiceManager.cleanup_all`` 终止它起的
   Web UI。另一个窗口里的 ``wait_for_task_completion`` 还在等：SSE 读结束，轮询每 2 s
   一次拿到 ``ConnectError``，``_fetch_result`` 把它吞成 ``None``，循环永远继续。
3. 没人再起 Web UI，页面打不开，问题也没地方回答。真实运行里 80 s 之后调用还在挂着；默认配置
   （倒计时 240 s）要等满 280 s 的后端超时才拿到 "请重新调用" 的提示，``timeout=0`` 则永远。
   ``kill -9`` Web UI 同样 272 s。持久化文件里明明还留着这个任务，新起的 Web UI 会把它恢复出来。

修复：轮询连续 3 次被拒绝连接（没有任何进程在监听）就调用 ``ensure_web_ui_running``，它会
重新起 Web UI（并恢复持久化的任务）；每次中断最多尝试 3 次，Web UI 一旦回应（任何 HTTP 状态）
计数清零。被恢复的任务继续等；没被恢复（404）则立刻拿到重新调用的提示。只有 ``ConnectError``
算“没了”：超时、读错误、5xx 都说明进程还在。

测试对着真实的回环 HTTP 服务器（假 Web UI），``kill`` 会关掉监听 socket 和所有已接受的连接，
和进程退出一致；``ensure_web_ui_running`` 换成在同一端口重新起一个假 Web UI。
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import socket
import threading
import time
import unittest
from collections.abc import AsyncIterator, Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from unittest.mock import AsyncMock, patch

import httpx

import ai_intervention_agent.server_config as server_config
import ai_intervention_agent.server_feedback as server_feedback
from ai_intervention_agent import service_manager
from ai_intervention_agent.exceptions import ServiceUnavailableError
from ai_intervention_agent.service_manager import WebUIConfig

TASK_ID = "r825-task"
ANSWER = {"user_feedback": "the answer", "selected_options": []}

# conftest 的 autouse fixture 会把 ``httpx.AsyncClient.send`` 换成抛错的桩（离线保证）。
# 本文件要对着回环上的假 Web UI 说真的 HTTP，所以在导入时（fixture 生效之前）留一份原件。
_REAL_ASYNC_SEND = httpx.AsyncClient.send


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _config(port: int) -> WebUIConfig:
    return WebUIConfig(
        host="127.0.0.1",
        port=port,
        language="auto",
        timeout=5,
        max_retries=0,
        retry_delay=0.1,
        external_base_url="",
    )


class _FakeWebUI:
    """说着等待循环用到的三个端点的回环服务器，``kill`` 的效果与进程退出一致。"""

    def __init__(self, port: int, state: str, *, sse: bool = True) -> None:
        self.port = port
        self.state = state  # pending | completed | missing | error
        self.sse = sse  # False：事件流立刻结束，等待循环只剩 2 s 轮询
        self.paths: list[str] = []
        self._dead = threading.Event()
        self._connections: list[socket.socket] = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, format: str, *args: Any) -> None:
                return

            def _send_json(self, status: int, payload: dict[str, Any]) -> None:
                body = json.dumps(payload).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _serve_events(self) -> None:
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                if not outer.sse:
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                self.end_headers()
                self.wfile.write(b": connected\n\n")
                self.wfile.flush()
                announced = False
                while not outer._dead.is_set():
                    if outer.state == "completed" and not announced:
                        announced = True
                        event = {
                            "type": "task_changed",
                            "task_id": TASK_ID,
                            "new_status": "completed",
                        }
                        frame = f"event: task_changed\ndata: {json.dumps(event)}\n\n"
                        self.wfile.write(frame.encode())
                        self.wfile.flush()
                    time.sleep(0.02)

            def do_GET(self) -> None:
                outer.paths.append(self.path)
                if self.path == "/api/health":
                    self._send_json(200, {"status": "ok"})
                elif self.path == "/api/events":
                    self._serve_events()
                elif self.path.startswith("/api/tasks/"):
                    if outer.state == "missing":
                        self._send_json(404, {"success": False})
                    elif outer.state == "error":
                        self._send_json(500, {"success": False})
                    else:
                        task: dict[str, Any] = {
                            "task_id": TASK_ID,
                            "status": outer.state,
                        }
                        if outer.state == "completed":
                            task["result"] = ANSWER
                        self._send_json(200, {"success": True, "task": task})
                else:
                    self._send_json(404, {})

            def do_POST(self) -> None:
                outer.paths.append(self.path)
                self._send_json(200, {"success": True})

        class Server(ThreadingHTTPServer):
            daemon_threads = True
            allow_reuse_address = True

            def get_request(self) -> Any:
                request, address = super().get_request()
                outer._connections.append(request)
                return request, address

        self.server = Server(("127.0.0.1", port), Handler)
        self.thread = threading.Thread(
            target=self.server.serve_forever,
            kwargs={"poll_interval": 0.02},
            daemon=True,
        )
        self.thread.start()

    @property
    def alive(self) -> bool:
        return not self._dead.is_set()

    def kill(self) -> None:
        self._dead.set()
        self.server.shutdown()
        self.server.server_close()
        for connection in self._connections:
            with contextlib.suppress(OSError):
                connection.shutdown(socket.SHUT_RDWR)
            with contextlib.suppress(OSError):
                connection.close()

    def hits(self, prefix: str) -> int:
        return sum(1 for path in list(self.paths) if path.startswith(prefix))


class _Scenario:
    """把一次 ``wait_for_task_completion`` 跑在假 Web UI 上，带可替换的 ``ensure_web_ui_running``。"""

    def __init__(self, first_state: str = "pending", *, sse: bool = True) -> None:
        self.port = _free_port()
        self.sse = sse
        self.uis: list[_FakeWebUI] = [_FakeWebUI(self.port, first_state, sse=sse)]
        self.ensure = AsyncMock(side_effect=self._revive)
        self.revived_state = "pending"

    async def _revive(self, config: Any, client: Any = None) -> None:
        # 和真的 ``ensure_web_ui_running`` 一样：已经有人起好了（健康检查通过）就什么也不做。
        if self.ui.alive:
            return
        self.uis.append(_FakeWebUI(self.port, self.revived_state, sse=self.sse))

    @property
    def ui(self) -> _FakeWebUI:
        return self.uis[-1]

    def close(self) -> None:
        for ui in self.uis:
            with contextlib.suppress(Exception):
                ui.kill()

    @contextlib.asynccontextmanager
    async def patched(self, client: Any | None = None) -> AsyncIterator[None]:
        async with httpx.AsyncClient(trust_env=False) as real:
            with (
                patch.object(httpx.AsyncClient, "send", _REAL_ASYNC_SEND),
                patch.object(
                    service_manager,
                    "get_web_ui_config",
                    return_value=(_config(self.port), 240),
                ),
                patch.object(
                    service_manager,
                    "get_async_client",
                    return_value=client if client is not None else real,
                ),
                patch.object(service_manager, "ensure_web_ui_running", self.ensure),
                patch.object(server_config, "BACKEND_MIN", 1),
                patch.object(server_feedback, "_POLL_INTERVAL_FAST_S", 0.03),
                patch.object(server_feedback, "_FETCH_RETRY_BACKOFF_S", (0.0,)),
            ):
                yield

    async def until(self, predicate: Callable[[], bool], timeout: float = 5.0) -> None:
        deadline = time.monotonic() + timeout
        while not predicate():
            if time.monotonic() > deadline:
                raise AssertionError("条件没有在期限内成立")
            await asyncio.sleep(0.02)

    async def kill_and_wait_for_revival(self, nth: int) -> None:
        self.ui.kill()
        await self.until(lambda: len(self.uis) == nth + 1)


def _run(coro: Any) -> Any:
    return asyncio.run(asyncio.wait_for(coro, timeout=30))


class TestWebUIRevivedDuringWait(unittest.TestCase):
    def setUp(self) -> None:
        self.scenario = _Scenario()
        self.addCleanup(self.scenario.close)

    def test_a_dead_web_ui_is_restarted_and_the_restored_task_is_answered(self) -> None:
        s = self.scenario

        async def run() -> tuple[dict[str, Any], float]:
            async with s.patched():
                waiter = asyncio.ensure_future(
                    server_feedback.wait_for_task_completion(TASK_ID, timeout=20)
                )
                await s.until(lambda: s.ui.hits("/api/events") >= 1)
                started = time.monotonic()
                await s.kill_and_wait_for_revival(1)
                revived_after = time.monotonic() - started
                s.ui.state = "completed"  # 恢复出来的任务之后被人回答了
                return await waiter, revived_after

        result, revived_after = _run(run())
        self.assertEqual(result, ANSWER)
        self.assertEqual(s.ensure.await_count, 1)
        awaited = s.ensure.await_args
        assert awaited is not None
        self.assertEqual(awaited.args[0].port, s.port, "按等待开始时的配置重启 Web UI")
        self.assertLess(revived_after, 5, "Web UI 没了之后应该很快被拉起来")

    def test_an_infinite_wait_recovers_too(self) -> None:
        s = self.scenario

        async def run() -> dict[str, Any]:
            async with s.patched():
                waiter = asyncio.ensure_future(
                    server_feedback.wait_for_task_completion(TASK_ID, timeout=0)
                )
                await s.until(lambda: s.ui.hits("/api/events") >= 1)
                await s.kill_and_wait_for_revival(1)
                s.ui.state = "completed"
                return await waiter

        self.assertEqual(_run(run()), ANSWER)
        self.assertEqual(s.ensure.await_count, 1)

    def test_a_task_the_new_web_ui_does_not_know_returns_the_resubmit_prompt_at_once(
        self,
    ) -> None:
        s = self.scenario
        s.revived_state = "missing"

        async def run() -> tuple[dict[str, Any], float]:
            async with s.patched():
                started = time.monotonic()
                waiter = asyncio.ensure_future(
                    server_feedback.wait_for_task_completion(TASK_ID, timeout=60)
                )
                await s.until(lambda: s.ui.hits("/api/events") >= 1)
                s.ui.kill()
                result = await waiter
                return result, time.monotonic() - started

        result, elapsed = _run(run())
        self.assertEqual(result, server_config._make_resubmit_response(as_mcp=False))
        self.assertEqual(s.ensure.await_count, 1)
        self.assertLess(elapsed, 10, "没有等到 60 s 的后端超时")

    def test_it_gives_up_after_three_attempts_and_keeps_waiting_for_the_timeout(
        self,
    ) -> None:
        s = self.scenario
        s.ensure.side_effect = ServiceUnavailableError("busy", code="port_in_use")

        async def run() -> dict[str, Any]:
            async with s.patched():
                waiter = asyncio.ensure_future(
                    server_feedback.wait_for_task_completion(TASK_ID, timeout=3)
                )
                await s.until(lambda: s.ui.hits("/api/events") >= 1)
                s.ui.kill()
                return await waiter

        result = _run(run())
        self.assertEqual(result, server_config._make_resubmit_response(as_mcp=False))
        self.assertEqual(
            s.ensure.await_count, 3, "每次中断最多 3 次尝试；失败只记日志，等待照旧"
        )

    def test_every_outage_gets_its_own_attempts(self) -> None:
        s = self.scenario
        outages = 4  # 比 _WEB_UI_REVIVE_MAX 多：次数按“每次中断”算，不按整个等待算

        async def run() -> dict[str, Any]:
            async with s.patched():
                waiter = asyncio.ensure_future(
                    server_feedback.wait_for_task_completion(TASK_ID, timeout=30)
                )
                await s.until(lambda: s.ui.hits("/api/events") >= 1)
                for nth in range(1, outages + 1):
                    await s.kill_and_wait_for_revival(nth)
                    await s.until(lambda: s.ui.hits("/api/tasks/") >= 2)
                s.ui.state = "completed"
                return await waiter

        self.assertEqual(_run(run()), ANSWER)
        self.assertEqual(s.ensure.await_count, outages)

    def test_two_calls_waiting_in_parallel_both_recover_and_one_web_ui_is_started(
        self,
    ) -> None:
        """同一个 MCP 进程里并行的两个调用各自发现、各自请求重启。

        真的 ``ensure_web_ui_running`` 有进程内的启动锁：第一个起好了，第二个在锁里看到
        服务已经在了，什么也不做（真实栈里两个调用的日志各有一条警告，进程只起了一个）。
        假替身照同样的规则，所以这里数的是起了几个 Web UI，而不是请求了几次。
        """
        s = self.scenario

        async def run() -> list[dict[str, Any]]:
            async with s.patched():
                waiters = [
                    asyncio.ensure_future(
                        server_feedback.wait_for_task_completion(
                            f"{TASK_ID}-{n}", timeout=20
                        )
                    )
                    for n in (1, 2)
                ]
                await s.until(lambda: s.ui.hits("/api/events") >= 2)
                await s.kill_and_wait_for_revival(1)
                s.ui.state = "completed"
                return list(await asyncio.gather(*waiters))

        self.assertEqual(_run(run()), [ANSWER, ANSWER])
        self.assertGreaterEqual(s.ensure.await_count, 1)
        self.assertEqual(len(s.uis), 2, "两个调用也只起了一个新的 Web UI")

    def test_cancelling_the_wait_during_a_restart_is_not_swallowed(self) -> None:
        s = self.scenario

        async def stuck(config: Any, client: Any = None) -> None:
            await asyncio.Event().wait()

        s.ensure.side_effect = stuck

        async def run() -> bool:
            async with s.patched():
                waiter = asyncio.ensure_future(
                    server_feedback.wait_for_task_completion(TASK_ID, timeout=60)
                )
                await s.until(lambda: s.ui.hits("/api/events") >= 1)
                s.ui.kill()
                await s.until(lambda: s.ensure.await_count == 1)
                waiter.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await asyncio.wait_for(waiter, timeout=5)
                return waiter.cancelled()

        self.assertTrue(_run(run()))


class TestWebUIThatAnswersIsNeverRestarted(unittest.TestCase):
    def setUp(self) -> None:
        self.scenario = _Scenario("error", sse=False)
        self.addCleanup(self.scenario.close)

    def test_http_errors_are_not_a_dead_web_ui(self) -> None:
        s = self.scenario

        async def run() -> dict[str, Any]:
            async with s.patched():
                waiter = asyncio.ensure_future(
                    server_feedback.wait_for_task_completion(TASK_ID, timeout=20)
                )
                await s.until(lambda: s.ui.hits("/api/tasks/") >= 8)
                s.ui.state = "completed"
                return await waiter

        self.assertEqual(_run(run()), ANSWER)
        self.assertEqual(s.ensure.await_count, 0)


class _FlakyClient:
    """按剧本让 ``get`` 抛异常（``None`` = 放行给真的 client），其余转给真的 client。"""

    def __init__(self, real: httpx.AsyncClient, script: list[Exception | None]) -> None:
        self._real = real
        self._script = list(script)
        self.is_closed = False
        self.calls = 0

    async def get(self, url: str, **kwargs: Any) -> httpx.Response:
        self.calls += 1
        if self._script:
            failure = self._script.pop(0)
            if failure is not None:
                raise failure
        return await self._real.get(url, **kwargs)

    def stream(self, *args: Any, **kwargs: Any) -> Any:
        return self._real.stream(*args, **kwargs)

    async def post(self, url: str, **kwargs: Any) -> httpx.Response:
        return await self._real.post(url, **kwargs)


def _refused() -> Exception:
    return httpx.ConnectError("refused")


class TestOnlyConsecutiveRefusalsCount(unittest.TestCase):
    def setUp(self) -> None:
        self.scenario = _Scenario("pending", sse=False)
        self.addCleanup(self.scenario.close)

    def _answered_after(self, script: list[Exception | None]) -> _FlakyClient:
        """``get`` 按剧本失败，之后任务被回答；返回时等待已经拿到答案。"""
        s = self.scenario

        async def run() -> _FlakyClient:
            async with httpx.AsyncClient(trust_env=False) as real:
                flaky = _FlakyClient(real, script)
                async with s.patched(client=flaky):
                    waiter = asyncio.ensure_future(
                        server_feedback.wait_for_task_completion(TASK_ID, timeout=20)
                    )
                    await s.until(lambda: flaky.calls >= len(script) + 3)
                    s.ui.state = "completed"
                    self.assertEqual(await waiter, ANSWER)
                    return flaky

        return _run(run())

    def test_two_refusals_in_a_row_are_a_blip(self) -> None:
        self._answered_after([_refused(), _refused()])
        self.assertEqual(self.scenario.ensure.await_count, 0)

    def test_an_answer_in_between_resets_the_count(self) -> None:
        self._answered_after([_refused(), _refused(), None, _refused(), _refused()])
        self.assertEqual(self.scenario.ensure.await_count, 0)

    def test_three_refusals_in_a_row_restart_the_web_ui(self) -> None:
        self._answered_after([_refused(), _refused(), _refused()])
        self.assertEqual(self.scenario.ensure.await_count, 1)

    def test_only_a_refused_connection_means_the_web_ui_is_gone(self) -> None:
        """超时 / 读错误 / 协议错误都说明那头有进程，重启只会添乱。"""
        failures: list[Exception | None] = [
            httpx.ReadTimeout("slow"),
            httpx.ConnectTimeout("dropped"),
            httpx.ReadError("reset"),
            httpx.RemoteProtocolError("closed without a response"),
            httpx.ReadTimeout("slow"),
            httpx.ReadTimeout("slow"),
        ]
        self._answered_after(failures)
        self.assertEqual(self.scenario.ensure.await_count, 0)

    def test_attempts_are_three_refused_polls_apart(self) -> None:
        s = self.scenario
        polls_at_attempt: list[int] = []

        async def run() -> None:
            async with httpx.AsyncClient(trust_env=False) as real:
                flaky = _FlakyClient(real, [_refused() for _ in range(40)])

                async def record(config: Any, client: Any = None) -> None:
                    polls_at_attempt.append(flaky.calls)

                s.ensure.side_effect = record
                async with s.patched(client=flaky):
                    waiter = asyncio.ensure_future(
                        server_feedback.wait_for_task_completion(TASK_ID, timeout=20)
                    )
                    await s.until(lambda: len(polls_at_attempt) == 3)
                    await asyncio.sleep(0.3)  # 第 4 次不应该来
                    waiter.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await waiter

        _run(run())
        self.assertEqual(polls_at_attempt, [3, 6, 9])


class TestLossWatchPolicy(unittest.TestCase):
    """“几次拒绝算没了、试几次、什么时候重新计”本身——不起任何服务器，直接问策略。"""

    @staticmethod
    def _due_at(watch: Any, refusals: int) -> list[int]:
        """连续被拒绝 ``refusals`` 次；返回哪几次拒绝之后该重启了（从 1 数）。"""
        due: list[int] = []
        for nth in range(1, refusals + 1):
            watch.refusal()
            if watch.revive_due():
                due.append(nth)
        return due

    def test_the_documented_numbers(self) -> None:
        """文档（排查指南、CHANGELOG）写的就是这两个数：改它们要同时改文档。"""
        self.assertEqual(server_feedback._WEB_UI_LOST_PROBES, 3)
        self.assertEqual(server_feedback._WEB_UI_REVIVE_MAX, 3)

    def test_a_fresh_watch_has_seen_nothing(self) -> None:
        watch = server_feedback._WebUILossWatch()
        self.assertEqual((watch.refused, watch.revives), (0, 0))
        self.assertFalse(watch.revive_due())

    def test_two_refusals_are_not_enough(self) -> None:
        watch = server_feedback._WebUILossWatch()
        self.assertEqual(self._due_at(watch, 2), [])

    def test_attempts_are_three_refusals_apart_and_stop_at_the_cap(self) -> None:
        watch = server_feedback._WebUILossWatch()
        self.assertEqual(self._due_at(watch, 30), [3, 6, 9])
        self.assertEqual((watch.refused, watch.revives), (30, 3))

    def test_asking_does_not_count_unless_the_answer_is_yes(self) -> None:
        watch = server_feedback._WebUILossWatch()
        watch.refusal()
        self.assertFalse(watch.revive_due())
        self.assertEqual(watch.revives, 0)
        watch.refusal()
        watch.refusal()
        self.assertTrue(watch.revive_due())
        self.assertEqual(watch.revives, 1)
        self.assertFalse(watch.revive_due(), "同一次拒绝不能触发两次重启")
        self.assertEqual(watch.revives, 1)

    def test_an_answer_means_the_refusals_must_start_over(self) -> None:
        watch = server_feedback._WebUILossWatch()
        self.assertEqual(self._due_at(watch, 2), [])
        watch.answered()
        self.assertEqual(watch.refused, 0)
        self.assertEqual(self._due_at(watch, 2), [], "2 + 2 不是连续的 4")

    def test_an_answer_gives_the_next_outage_a_full_budget(self) -> None:
        watch = server_feedback._WebUILossWatch()
        self.assertEqual(self._due_at(watch, 30), [3, 6, 9])
        watch.answered()
        self.assertEqual((watch.refused, watch.revives), (0, 0))
        self.assertEqual(self._due_at(watch, 30), [3, 6, 9])


class TestReviveWebUi(unittest.TestCase):
    """``_revive_web_ui``：该重启时怎么做，重启失败时怎么办——不起任何服务器。"""

    def _watch_due(self) -> Any:
        watch = server_feedback._WebUILossWatch()
        for _ in range(3):
            watch.refusal()
        self.assertTrue(watch.revive_due())
        return watch

    def test_it_restarts_with_the_waits_own_config_and_says_so_in_the_log(self) -> None:
        config = _config(4321)
        watch = self._watch_due()
        ensure = AsyncMock()
        with (
            patch.object(service_manager, "ensure_web_ui_running", ensure),
            patch.object(server_feedback, "logger") as log,
        ):
            asyncio.run(server_feedback._revive_web_ui(config, "task-x", watch))
        ensure.assert_awaited_once_with(config)
        warned = " ".join(str(call.args[0]) for call in log.warning.call_args_list)
        self.assertIn("task-x", warned)
        self.assertIn("连续 3 次", warned)
        self.assertIn("第 1/3 次", warned)

    def test_a_failed_restart_is_logged_and_not_raised(self) -> None:
        watch = self._watch_due()
        ensure = AsyncMock(
            side_effect=ServiceUnavailableError("busy", code="port_in_use")
        )
        with (
            patch.object(service_manager, "ensure_web_ui_running", ensure),
            patch.object(server_feedback, "logger") as log,
        ):
            asyncio.run(server_feedback._revive_web_ui(_config(4321), "t", watch))
        self.assertEqual(log.warning.call_count, 2)
        self.assertIn(
            "重新启动 Web UI 失败", str(log.warning.call_args_list[-1].args[0])
        )

    def test_cancellation_goes_through(self) -> None:
        watch = self._watch_due()
        ensure = AsyncMock(side_effect=asyncio.CancelledError())
        with (
            patch.object(service_manager, "ensure_web_ui_running", ensure),
            patch.object(server_feedback, "logger"),
            self.assertRaises(asyncio.CancelledError),
        ):
            asyncio.run(server_feedback._revive_web_ui(_config(4321), "t", watch))


if __name__ == "__main__":
    unittest.main()
