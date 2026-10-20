"""R779：``interactive_feedback`` 的每个返回出口都要被计数，且只计一次。

现象
====

``aiia://server/info`` 的 ``interactive_feedback`` 子块给出三个累计值：
``created_total``、``completed_total``、``failed_total``。运维靠它判断"建了多少个
任务、多少个有了答案、多少个失败"，``created_total`` 减去另外两个应当等于"还在等
的"那几个。

``interactive_feedback`` 里每个失败出口都先记一条 ``task.failed`` 事件，再给
``failed_total`` 加一，只有一处例外：建任务的 ``POST /api/tasks`` 得到非 200
（队列满或任务 ID 重复的 409、被限流的 429、请求被拒的 400、服务端出错的 500）时，
只记了事件，没有加 ``failed_total``。这样每出现一次，"还在等的"就多一个永远不会
消失的幻影，``failed_total`` 又比真实失败少一个，而这个出口恰恰是 Web UI 过载、
队列被占满时最常走的出口。

契约
====

一次返回了的调用，恰好计入 ``completed_total`` 或 ``failed_total`` 之一：
``created_total == completed_total + failed_total``。被取消的调用不返回，也就不在
这条契约里。

测试矩阵
========

A. 拿到用户答复：completed 加一；
B. 建任务的 POST 得到非 200（400 / 409 / 429 / 500）：failed 加一（旧代码上失败）；
C. 连不上 Web UI：failed 加一；
D. 等待阶段返回 error：failed 加一；
E. 等待阶段超时（只有 text 的结果）：failed 加一；
F. 出口之外的意外异常：failed 加一；
G. 上面所有出口各走一遍之后，created 恰好等于 completed 加 failed。

只有 B 在旧代码上失败，其余是对照：它们锁住"每个出口恰好计一次"，防止以后为了补
B 而把别的出口算两次。
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import MagicMock

import httpx
import pytest

import ai_intervention_agent.server_feedback as server
from tests.test_notification_off_event_loop_r776 import _Client, _Harness


class _RejectingClient(_Client):
    """建任务的 POST 得到给定的 HTTP 状态码；close 照常成功。"""

    def __init__(self, status_code: int) -> None:
        super().__init__()
        self._status_code = status_code

    async def post(self, url: str, **_kwargs: Any) -> MagicMock:
        await asyncio.sleep(0)
        self.posts.append(url)
        if url.endswith("/close"):
            return MagicMock(status_code=200)
        response = MagicMock(status_code=self._status_code)
        response.json.return_value = {"success": False, "error": "rejected"}
        return response


class _UnreachableClient(_Client):
    async def post(self, url: str, **_kwargs: Any) -> MagicMock:
        await asyncio.sleep(0)
        self.posts.append(url)
        raise httpx.ConnectError("no route to the Web UI")


@pytest.fixture
def harness(monkeypatch: pytest.MonkeyPatch) -> _Harness:
    server.reset_feedback_counters_for_testing()
    return _Harness(monkeypatch)


def _counts() -> dict[str, int]:
    return server.get_feedback_counters()


def _call(harness: _Harness) -> list[Any]:
    async def run() -> list[Any]:
        return await harness.call()

    return asyncio.run(run())


def _wait_returns(monkeypatch: pytest.MonkeyPatch, result: dict[str, Any]) -> None:
    async def wait(_task_id: str, **_kwargs: Any) -> dict[str, Any]:
        return result

    monkeypatch.setattr(server, "wait_for_task_completion", wait)


class TestEveryReturningExitIsCountedOnce:
    def test_an_answered_call_is_completed(self, harness: _Harness) -> None:
        _call(harness)

        assert _counts() == {
            "created_total": 1,
            "completed_total": 1,
            "failed_total": 0,
        }

    @pytest.mark.parametrize("status_code", [400, 409, 429, 500])
    def test_a_rejected_task_post_is_failed(
        self, harness: _Harness, status_code: int
    ) -> None:
        harness.use_client(_RejectingClient(status_code))

        _call(harness)

        assert _counts() == {
            "created_total": 1,
            "completed_total": 0,
            "failed_total": 1,
        }

    def test_an_unreachable_web_ui_is_failed(self, harness: _Harness) -> None:
        harness.use_client(_UnreachableClient())

        _call(harness)

        assert _counts() == {
            "created_total": 1,
            "completed_total": 0,
            "failed_total": 1,
        }

    def test_a_wait_error_is_failed(
        self, harness: _Harness, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _wait_returns(monkeypatch, {"error": "the Web UI went away"})

        _call(harness)

        assert _counts() == {
            "created_total": 1,
            "completed_total": 0,
            "failed_total": 1,
        }

    def test_a_wait_timeout_is_failed(
        self, harness: _Harness, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _wait_returns(monkeypatch, {"text": "please call interactive_feedback again"})

        _call(harness)

        assert _counts() == {
            "created_total": 1,
            "completed_total": 0,
            "failed_total": 1,
        }

    def test_an_unexpected_exception_is_failed(
        self, harness: _Harness, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def explode(*_args: Any, **_kwargs: Any) -> None:
            raise RuntimeError("could not start the Web UI")

        monkeypatch.setattr(server.service_manager, "ensure_web_ui_running", explode)

        _call(harness)

        assert _counts() == {
            "created_total": 1,
            "completed_total": 0,
            "failed_total": 1,
        }

    def test_created_always_equals_completed_plus_failed(
        self, harness: _Harness, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        outcomes: list[Any] = [
            lambda: None,
            lambda: harness.use_client(_RejectingClient(409)),
            lambda: harness.use_client(_RejectingClient(429)),
            lambda: harness.use_client(_UnreachableClient()),
            lambda: (
                harness.use_client(_Client()),
                _wait_returns(monkeypatch, {"error": "gone"}),
            ),
            lambda: _wait_returns(monkeypatch, {"text": "again"}),
        ]

        for arrange in outcomes:
            arrange()
            _call(harness)

        counts = _counts()
        assert counts["created_total"] == len(outcomes)
        assert counts["created_total"] == (
            counts["completed_total"] + counts["failed_total"]
        ), counts
