"""R774：几个 ``interactive_feedback`` 同时冷启动 Web UI，只能起一个子进程，一个都不能丢。

现象（真实 stdio MCP 服务 + 真实 Web UI 子进程，端到端复现）
============================================================

Web UI 还没起来时，同一个 MCP 进程同时收到三个 ``interactive_feedback`` 调用
（客户端并行发起工具调用）。三个调用各自 ``ensure_web_ui_running`` →
健康检查失败 → ``asyncio.to_thread(start_web_service)``，三个线程互不等待：

* 日志里出现两行 ``Web 服务进程已启动，PID: …``，同名服务的登记被后者覆盖，
  先起的那个进程不再被 ``ServiceManager`` 跟踪，MCP 退出时可能留下孤儿 Web UI；
* ``_is_port_available`` 用 ``socket.bind`` 探测端口，探测本身会短暂占住端口，
  另一个线程的探测撞上它就得到 ``EADDRINUSE``，于是第三个调用抛
  ``ServiceUnavailableError(code="port_in_use")``，日志 ERROR 加整段 traceback，
  报的却是「端口已被占用（health-check 未识别为本服务）」——占着端口的正是我们
  自己的探测或刚起的 Web UI。这个调用拿到的是兜底的重调提示，任务根本没建出来。

契约
====

1. ``start_web_service`` 在进程内串行：并发进入时只有第一个会起子进程，其余等它
   起完、健康检查通过之后，在锁里重新判断，发现服务已经在跑就直接返回；
2. 并发调用没有一个抛异常；
3. 起子进程失败（抛异常）要释放锁，下一次调用还能重试，不能死锁。

测试矩阵
========

A. 三个线程同时冷启动：Popen 恰好一次，三个都正常返回；
B. 先起失败的那次释放了锁：随后的调用能起成功；
C. ``start_web_service`` 保持原签名与原名，``ensure_web_ui_running`` 仍经由它启动。
"""

from __future__ import annotations

import inspect
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from ai_intervention_agent import service_manager
from ai_intervention_agent.exceptions import ServiceUnavailableError
from ai_intervention_agent.server_config import WebUIConfig

SCRIPT_DIR = Path(service_manager.__file__).resolve().parent
SERVICE_NAME = "web_ui_127.0.0.1_18999"


def _config() -> WebUIConfig:
    return WebUIConfig(host="127.0.0.1", port=18999)


class _Machine:
    """用线程模拟「真实世界」：Popen 要花时间，子进程稍后才绑定端口，探测互相冲突。"""

    def __init__(self, *, popen_delay: float = 0.15, bind_delay: float = 0.2) -> None:
        self.popen_delay = popen_delay
        self.bind_delay = bind_delay
        self.bound = threading.Event()
        self.spawns: list[list[str]] = []
        self.spawn_lock = threading.Lock()
        self.probe_lock = threading.Lock()
        self.popen_error: BaseException | None = None

    def health(self, config: Any) -> bool:
        return self.bound.is_set()

    def port_free(self, host: str, port: int) -> bool:
        if not self.probe_lock.acquire(blocking=False):
            return False
        try:
            time.sleep(0.05)
            return not self.bound.is_set()
        finally:
            self.probe_lock.release()

    def popen(self, args: list[str], **kwargs: Any) -> MagicMock:
        if self.popen_error is not None:
            raise self.popen_error
        time.sleep(self.popen_delay)
        with self.spawn_lock:
            self.spawns.append(args)
        threading.Timer(self.bind_delay, self.bound.set).start()
        process = MagicMock()
        process.pid = 4242 + len(self.spawns)
        process.poll.return_value = None
        return process


@pytest.fixture
def machine() -> Any:
    state = _Machine()
    service_manager.ServiceManager._instance = None
    service_manager.ServiceManager._lock = threading.Lock()
    with (
        patch.object(service_manager, "NOTIFICATION_AVAILABLE", False),
        patch.object(service_manager, "health_check_service", state.health),
        patch.object(service_manager, "_is_port_available", state.port_free),
        patch.object(service_manager.subprocess, "Popen", state.popen),
        patch.object(service_manager, "_get_web_ui_log_path", return_value=None),
    ):
        yield state
    service_manager.ServiceManager._instance = None


def _run_together(
    count: int, target: Callable[[], None]
) -> tuple[list[BaseException], float]:
    errors: list[BaseException] = []
    barrier = threading.Barrier(count)

    def worker() -> None:
        barrier.wait(timeout=5)
        try:
            target()
        except BaseException as exc:
            errors.append(exc)

    started = time.monotonic()
    threads = [threading.Thread(target=worker) for _ in range(count)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
    assert not any(thread.is_alive() for thread in threads), (
        "a start_web_service call hung"
    )
    return errors, time.monotonic() - started


class TestConcurrentColdStart:
    def test_three_simultaneous_calls_spawn_one_web_ui_and_none_fails(
        self, machine: _Machine
    ) -> None:
        config = _config()
        errors, _ = _run_together(
            3, lambda: service_manager.start_web_service(config, SCRIPT_DIR)
        )

        assert not errors, f"concurrent cold start raised: {errors!r}"
        assert len(machine.spawns) == 1, (
            f"expected one Web UI process, {len(machine.spawns)} were started"
        )

    def test_the_one_process_is_the_one_the_service_manager_tracks(
        self, machine: _Machine
    ) -> None:
        config = _config()
        _run_together(3, lambda: service_manager.start_web_service(config, SCRIPT_DIR))

        tracked = service_manager.ServiceManager().get_process(SERVICE_NAME)
        assert tracked is not None
        assert tracked.pid == 4242 + 1

    def test_a_late_call_after_the_start_returns_without_spawning(
        self, machine: _Machine
    ) -> None:
        config = _config()
        service_manager.start_web_service(config, SCRIPT_DIR)
        assert len(machine.spawns) == 1

        service_manager.start_web_service(config, SCRIPT_DIR)

        assert len(machine.spawns) == 1


class TestFailedStartReleasesTheLock:
    def test_a_failed_spawn_does_not_block_the_next_call(
        self, machine: _Machine
    ) -> None:
        config = _config()
        machine.popen_error = PermissionError("denied")
        with pytest.raises(ServiceUnavailableError):
            service_manager.start_web_service(config, SCRIPT_DIR)

        machine.popen_error = None
        outcome: list[BaseException] = []

        def retry() -> None:
            try:
                service_manager.start_web_service(config, SCRIPT_DIR)
            except BaseException as exc:
                outcome.append(exc)

        thread = threading.Thread(target=retry)
        thread.start()
        thread.join(timeout=10)

        assert not thread.is_alive(), "the lock was still held after a failed start"
        assert not outcome, outcome
        assert len(machine.spawns) == 1


class TestEntryPointsAreUnchanged:
    def test_start_web_service_keeps_its_name_and_signature(self) -> None:
        assert service_manager.start_web_service.__name__ == "start_web_service"
        params = list(inspect.signature(service_manager.start_web_service).parameters)
        assert params == ["config", "script_dir"]

    def test_ensure_web_ui_running_starts_through_start_web_service(self) -> None:
        source = inspect.getsource(service_manager.ensure_web_ui_running)
        assert "start_web_service" in source
