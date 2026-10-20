"""R776：给用户发"新任务"通知时，不能把 MCP 服务的事件循环冻住。

现象（真实 stdio MCP 服务 + 真实 Web UI 子进程，端到端复现）
============================================================

``interactive_feedback`` 在任务建好之后调用 ``notification_manager.send_notification``。
它的 ``IMMEDIATE`` 触发会一直等到每个渠道（system / sound / Bark）都答复，最长
``bark_timeout`` + 5 秒（默认 15 秒），而且这一步直接写在 async handler 里，跑在事件
循环的线程上。Bark 服务器不应答（手机端的自建服务离线、网络抖动）时：

* ``bark_timeout = 3`` 的复现里，一个 MCP ``ping`` 发出去后等了 3.01 秒才得到回答，
  正常情况是 0.01 秒；服务器健康时则没有可见的停顿；
* 冻住期间，所有别的请求都不动：并发的另一个 ``interactive_feedback``、取消通知、
  这个任务自己开始等用户回复的那一步，以及其它任务的 SSE 结果都停着。

事件循环里不应该有阻塞的网络调用；``_prepare_local_images``（R726）早就走线程了，
这一步是漏网的一处。

修复带来的另一个取消窗口
==========================

通知挪到线程里，``await`` 它就成了新的取消点：用户点「停止」恰好落在这里，取消
在任务已经建好、``wait_for_task_completion`` 还没进入的时候送达，R775 的清理就
接不上了。``interactive_feedback`` 因此在任务建好之后到开始等待之前的整段
（POST 本身、``ctx`` 的进度消息、通知）上多了一个取消守卫：收到取消就把刚建的任务
关掉（走 R775 的独立 task），再把取消照常抛出去。

契约
====

1. 通知（含读配置文件）不在事件循环的线程上跑；它慢的时候事件循环照常转；
2. 通知出错只记 WARNING，任务照常等用户回复（不能因此把已建好的任务弃在 Web UI 里）；
3. 任务建好后、开始等待前的任何一处被取消（POST 在途、通知在途），任务都被关掉，
   取消仍传给调用方；
4. ``interactive_feedback`` 本身不直接调用 ``send_notification``。

测试矩阵
========

A. 慢渠道（0.8 秒）期间事件循环继续转；通知跑在别的线程上；
B. 通知在途时被 anyio scope 取消：close 恰好 POST 一次，取消传给调用方；
C. 任务 POST 在途时被取消：同样 close 一次；
D. 通知抛异常：记 WARNING，调用照常得到用户的回复；
E. 源码：通知经 ``asyncio.to_thread`` 发出，``interactive_feedback`` 里没有 ``send_notification``。

A、C 在旧代码上失败；B 守住新增的 ``await`` 窗口（去掉取消守卫就失败）。
"""

from __future__ import annotations

import asyncio
import contextlib
import inspect
import threading
import time
from collections.abc import Awaitable, Callable
from typing import Any
from unittest.mock import MagicMock

import anyio
import pytest

import ai_intervention_agent.server_feedback as server
from ai_intervention_agent.server_config import WebUIConfig

TASK_ID = "t-notify"
TASKS_URL = "http://127.0.0.1:18998/api/tasks"
CLOSE_URL = f"{TASKS_URL}/{TASK_ID}/close"


class _Client:
    """记录 POST；``hold_task_post`` 让建任务的 POST 一直挂着（模拟请求在途）。

    ``await asyncio.sleep(0)`` 模拟真实网络请求一定会挂起：``AsyncMock`` 本身不挂起，
    取消就没有机会被送达。
    """

    def __init__(self, *, hold_task_post: bool = False) -> None:
        self.posts: list[str] = []
        self.task_post_started = asyncio.Event()
        self.closed = asyncio.Event()
        self._hold = hold_task_post

    async def post(self, url: str, **_kwargs: Any) -> MagicMock:
        await asyncio.sleep(0)
        self.posts.append(url)
        if url.endswith("/close"):
            self.closed.set()
        elif self._hold:
            self.task_post_started.set()
            await asyncio.Event().wait()
        return MagicMock(status_code=200)


class _Harness:
    def __init__(
        self,
        monkeypatch: pytest.MonkeyPatch,
        web_ui_config: WebUIConfig | None = None,
    ) -> None:
        self.monkeypatch = monkeypatch
        self.notifier = MagicMock()
        self.notifier.send_notification.return_value = "event-1"
        self.client = _Client()
        self.waited: list[str] = []

        async def noop(*_args: Any, **_kwargs: Any) -> None:
            return None

        async def finished(task_id: str, **_kwargs: Any) -> dict[str, str]:
            self.waited.append(task_id)
            return {"interactive_feedback": "the answer"}

        sm = server.service_manager
        web_ui = web_ui_config or WebUIConfig(host="127.0.0.1", port=18998)
        monkeypatch.setattr(sm, "get_web_ui_config", lambda: (web_ui, 30))
        monkeypatch.setattr(sm, "get_async_client", lambda _config: self.client)
        monkeypatch.setattr(sm, "ensure_web_ui_running", noop)
        monkeypatch.setattr(server, "wait_for_task_completion", finished)
        monkeypatch.setattr(server, "NOTIFICATION_AVAILABLE", True)
        monkeypatch.setattr(server, "notification_manager", self.notifier)
        monkeypatch.setattr(server.server_config, "_generate_task_id", lambda: TASK_ID)

    def use_client(self, client: _Client) -> None:
        self.client = client

    def call(self) -> Awaitable[list[Any]]:
        return server.interactive_feedback(
            message="hello",
            predefined_options=None,
            feedback_placeholder=None,
            header_label=None,
            loop_id=None,
            loop_objective=None,
            loop_phase=None,
            success_criteria=None,
            iteration_label=None,
            ctx=None,
        )


@pytest.fixture
def harness(monkeypatch: pytest.MonkeyPatch) -> _Harness:
    return _Harness(monkeypatch)


async def _until_idle() -> None:
    for _ in range(200):
        if not server._DETACHED_CLEANUPS:
            return
        await asyncio.sleep(0.01)


class TestTheEventLoopKeepsRunning:
    def test_ticks_continue_while_a_channel_is_slow(self, harness: _Harness) -> None:
        window: list[float] = []

        def slow_channel(**_kwargs: Any) -> str:
            window.append(time.monotonic())
            time.sleep(0.8)
            window.append(time.monotonic())
            return "event-1"

        harness.notifier.send_notification.side_effect = slow_channel

        async def main() -> list[float]:
            ticks: list[float] = []

            async def ticker() -> None:
                while True:
                    await asyncio.sleep(0.01)
                    ticks.append(time.monotonic())

            task = asyncio.ensure_future(ticker())
            try:
                await harness.call()
            finally:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
            return ticks

        ticks = asyncio.run(main())

        started, ended = window
        during = [t for t in ticks if started < t < ended]
        assert len(during) >= 10, (
            f"event loop ran {len(during)} ticks while the channel was busy"
        )

    def test_the_notification_does_not_run_on_the_loop_thread(
        self, harness: _Harness
    ) -> None:
        seen: list[int] = []
        harness.notifier.send_notification.side_effect = lambda **_kwargs: (
            seen.append(threading.get_ident()) or "event-1"
        )
        harness.notifier.refresh_config_from_file.side_effect = lambda: seen.append(
            threading.get_ident()
        )

        async def main() -> int:
            await harness.call()
            return threading.get_ident()

        loop_thread = asyncio.run(main())

        assert len(seen) == 2
        assert loop_thread not in seen

    def test_the_task_is_still_waited_for_afterwards(self, harness: _Harness) -> None:
        result = asyncio.run(_collect(harness))

        assert harness.waited == [TASK_ID]
        assert "the answer" in result[0].text
        harness.notifier.send_notification.assert_called_once()
        kwargs = harness.notifier.send_notification.call_args.kwargs
        assert kwargs["metadata"] == {
            "task_id": TASK_ID,
            "source": "interactive_feedback",
        }
        assert kwargs["skip_unavailable"] is True


async def _collect(harness: _Harness) -> list[Any]:
    return await harness.call()


async def _cancel_like_the_mcp_runner(
    harness: _Harness,
    client: _Client,
    *,
    armed: Callable[[], Awaitable[None]],
    release: threading.Event | None = None,
) -> list[str]:
    """用 anyio cancel scope 取消 ``interactive_feedback``，和 MCP SDK 取消请求一致。

    ``release`` 让一直卡着的通知线程在断言之前放行：``asyncio.run`` 收尾时会等默认
    线程池里的线程结束，不放行就得等满它自己的安全超时。
    """
    outcome: list[str] = []

    async def handler() -> None:
        try:
            await harness.call()
        except asyncio.CancelledError:
            outcome.append("cancelled")
            raise

    try:
        async with anyio.create_task_group() as group:
            group.start_soon(handler)
            await armed()
            group.cancel_scope.cancel()
        await asyncio.wait_for(client.closed.wait(), 5)
        await _until_idle()
    finally:
        if release is not None:
            release.set()
    return outcome


class TestCancelledBeforeTheWaitStarts:
    def test_cancel_while_the_notification_is_in_flight(
        self, harness: _Harness
    ) -> None:
        client = harness.client
        started = threading.Event()
        release = threading.Event()

        def stuck_channel(**_kwargs: Any) -> str:
            started.set()
            release.wait(timeout=10)
            return "event-1"

        harness.notifier.send_notification.side_effect = stuck_channel

        async def armed() -> None:
            for _ in range(500):
                if started.is_set():
                    return
                await asyncio.sleep(0.01)
            raise AssertionError("the notification never started")

        outcome = asyncio.run(
            _cancel_like_the_mcp_runner(harness, client, armed=armed, release=release)
        )

        assert client.posts == [TASKS_URL, CLOSE_URL]
        assert outcome == ["cancelled"]
        assert harness.waited == []

    def test_cancel_while_the_task_is_being_created(self, harness: _Harness) -> None:
        client = _Client(hold_task_post=True)
        harness.use_client(client)

        async def armed() -> None:
            await asyncio.wait_for(client.task_post_started.wait(), 5)

        outcome = asyncio.run(_cancel_like_the_mcp_runner(harness, client, armed=armed))

        assert client.posts == [TASKS_URL, CLOSE_URL]
        assert outcome == ["cancelled"]
        harness.notifier.send_notification.assert_not_called()


class TestAFailingChannel:
    def test_the_error_is_logged_and_the_task_is_still_waited_for(
        self, harness: _Harness, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        warnings: list[str] = []
        monkeypatch.setattr(
            server.logger,
            "warning",
            lambda message, **_kwargs: warnings.append(message),
        )
        harness.notifier.send_notification.side_effect = RuntimeError("bark is down")

        result = asyncio.run(_collect(harness))

        assert harness.waited == [TASK_ID]
        assert "the answer" in result[0].text
        assert len(warnings) == 1
        assert "bark is down" in warnings[0]
        assert TASK_ID in warnings[0]

    def test_a_failing_config_refresh_is_handled_the_same_way(
        self, harness: _Harness, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        warnings: list[str] = []
        monkeypatch.setattr(
            server.logger,
            "warning",
            lambda message, **_kwargs: warnings.append(message),
        )
        harness.notifier.refresh_config_from_file.side_effect = RuntimeError(
            "config unreadable"
        )

        result = asyncio.run(_collect(harness))

        assert harness.waited == [TASK_ID]
        assert "the answer" in result[0].text
        assert len(warnings) == 1
        harness.notifier.send_notification.assert_not_called()


class TestSourceContract:
    def test_the_handler_sends_through_a_worker_thread(self) -> None:
        source = inspect.getsource(server.interactive_feedback)

        assert "asyncio.to_thread(" in source
        assert "_dispatch_new_task_notification" in source
        assert "send_notification" not in source
        assert "refresh_config_from_file" not in source

    def test_the_cancellation_guard_hands_the_cleanup_to_its_own_task(self) -> None:
        source = inspect.getsource(server.interactive_feedback)

        guard = source[source.index("except asyncio.CancelledError:") :]
        assert "_run_to_completion(" in guard.split("raise")[0]
        assert "_close_orphan_task_best_effort" in guard.split("raise")[0]
