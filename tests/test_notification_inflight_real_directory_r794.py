"""R794 — 通知的 in-flight 文件真的写在配置文件旁边（之前一个字节都没写过）。

事故现场
--------
R136 的功能是：通知事件入队时把它写进配置目录里的 ``notification_inflight.json``，投递完成时
摘掉；进程被杀（崩溃 / SIGKILL / OOM）之后重新启动，``get_status()["inflight_seen_at_startup"]``
能告诉运维"上次还有 N 条没投递出去"。

``_get_inflight_file_dir()`` 向配置管理器要的是 ``config_path``：

    path = getattr(config_mgr, "config_path", None)
    if path is None:
        return None

``ConfigManager`` 没有这个属性——配置文件路径叫 ``config_file``。``getattr(..., None)`` 把拼写
错误吞成了 ``None``，而上面每一层都把 ``None`` 当成"持久化不可用"静默跳过，于是这个功能从
R136 起就没有真正运行过：真实进程里事件在飞行中时磁盘上没有任何文件，
``get_status()["inflight_persisted_count"]`` 却一本正经地报 1；进程被杀后重启，
``inflight_seen_at_startup`` 永远是空的。

没人发现，是因为 R136 / R504 / R506 / R510 / R511 / R513 / R785 的所有测试都把
``_get_inflight_file_dir`` 本身 patch 掉了——被 patch 的恰好就是出错的那一个函数。

本文件不 patch 它：配置文件用真实的 ``ConfigManager``，事件走真实的 ``send_notification`` →
``_process_event`` → ``_mark_event_finalized`` 全链路，"重启"用一个新实例读同一个目录。
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import pytest

from ai_intervention_agent import notification_manager as nm
from ai_intervention_agent.config_manager import ConfigManager, get_config
from ai_intervention_agent.notification_manager import (
    _INFLIGHT_FILE_NAME,
    NotificationManager,
    NotificationTrigger,
    NotificationType,
)


@pytest.fixture
def config_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """一个真实的 ``ConfigManager``，配置文件在 ``tmp_path`` 里。"""
    manager = ConfigManager(str(tmp_path / "config.toml"))
    monkeypatch.setattr(nm, "get_config", lambda: manager)
    try:
        yield tmp_path
    finally:
        manager.shutdown()


# ---------------------------------------------------------------------------
# 1. 目录
# ---------------------------------------------------------------------------
class TestTheDirectory:
    def test_it_is_the_directory_of_the_config_file(self, config_dir: Path) -> None:
        assert nm._get_inflight_file_dir() == config_dir

    def test_the_process_wide_config_manager_gives_a_directory(self) -> None:
        # 不换掉 get_config：这就是生产进程里实际发生的查找
        found = nm._get_inflight_file_dir()
        assert found is not None
        assert found == get_config().config_file.parent

    def test_a_config_manager_without_a_file_gives_none(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(nm, "get_config", lambda: object())
        assert nm._get_inflight_file_dir() is None

    def test_a_failing_config_manager_gives_none(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def broken() -> object:
            raise RuntimeError("config manager is gone")

        monkeypatch.setattr(nm, "get_config", broken)
        assert nm._get_inflight_file_dir() is None

    def test_without_the_config_module_there_is_no_directory(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(nm, "CONFIG_FILE_AVAILABLE", False)
        assert nm._get_inflight_file_dir() is None


# ---------------------------------------------------------------------------
# 2. 真实全链路：文件的生命周期 = 事件在飞行中的时间
# ---------------------------------------------------------------------------
class Blocking:
    """渠道提供者：``send`` 一直占着，直到测试放行。"""

    def __init__(self) -> None:
        self.entered = threading.Event()
        self.release = threading.Event()

    def send(self, event: object) -> bool:
        self.entered.set()
        self.release.wait(30)
        return True


def _send_in_background(manager: NotificationManager) -> threading.Thread:
    sender = threading.Thread(
        target=lambda: manager.send_notification(
            title="in flight",
            message="the channel has not answered yet",
            trigger=NotificationTrigger.IMMEDIATE,
            types=[NotificationType.WEB],
            metadata={"task_id": "t-1"},
        ),
        daemon=True,
    )
    sender.start()
    return sender


def _wait_until(predicate, timeout: float = 10.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return predicate()


class TestTheFileFollowsTheEvent:
    def test_the_file_exists_while_the_event_is_in_flight_and_is_gone_after(
        self, config_dir: Path
    ) -> None:
        manager = nm.notification_manager
        manager.config.enabled = True
        channel = Blocking()
        manager.register_provider(NotificationType.WEB, channel)
        path = config_dir / _INFLIGHT_FILE_NAME

        sender = _send_in_background(manager)
        try:
            assert channel.entered.wait(10), "the provider was never asked to send"
            assert path.exists(), "an event is in flight but nothing is on disk"
            data = json.loads(path.read_text(encoding="utf-8"))
            assert [event["title"] for event in data["events"]] == ["in flight"]
            assert data["events"][0]["metadata"] == {"task_id": "t-1"}
            assert manager.get_status()["inflight_persisted_count"] == 1
        finally:
            channel.release.set()
            sender.join(10)

        assert _wait_until(lambda: not path.exists()), "the file outlived the event"
        assert manager.get_status()["inflight_persisted_count"] == 0

    def test_a_restart_after_a_crash_sees_what_was_in_flight(
        self, config_dir: Path
    ) -> None:
        manager = nm.notification_manager
        manager.config.enabled = True
        channel = Blocking()
        manager.register_provider(NotificationType.WEB, channel)

        sender = _send_in_background(manager)
        try:
            assert channel.entered.wait(10)
            # "新进程"：另一个实例按启动时的方式读同一个目录
            restarted = NotificationManager._create_test_instance()
            try:
                seen = restarted._load_persisted_inflight_events()
            finally:
                restarted.shutdown(wait=False)
        finally:
            channel.release.set()
            sender.join(10)

        assert [event["title"] for event in seen] == ["in flight"]
        assert seen[0]["metadata"] == {"task_id": "t-1"}

    def test_two_events_in_flight_and_one_finishes(self, config_dir: Path) -> None:
        manager = nm.notification_manager
        manager.config.enabled = True
        first, second = Blocking(), Blocking()
        # 两个事件用同一个渠道类型，所以用两个提供者依次登记
        manager.register_provider(NotificationType.WEB, first)
        path = config_dir / _INFLIGHT_FILE_NAME

        sender_one = _send_in_background(manager)
        try:
            assert first.entered.wait(10)
            manager.register_provider(NotificationType.WEB, second)
            sender_two = _send_in_background(manager)
            try:
                assert second.entered.wait(10)
                data = json.loads(path.read_text(encoding="utf-8"))
                assert len(data["events"]) == 2
                first.release.set()
                sender_one.join(10)
                assert _wait_until(
                    lambda: len(json.loads(path.read_text(encoding="utf-8"))["events"])
                    == 1
                ), "finishing one event must leave exactly the other one on disk"
            finally:
                second.release.set()
                sender_two.join(10)
        finally:
            first.release.set()
            sender_one.join(10)
        assert _wait_until(lambda: not path.exists())

    def test_a_directory_that_cannot_be_written_never_hurts_the_notification(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # 配置文件所在的"目录"其实是个普通文件：mkdir / 写临时文件都会失败
        blocker = tmp_path / "not-a-directory"
        blocker.write_text("", encoding="utf-8")

        class Stub:
            config_file = blocker / "config.toml"

        monkeypatch.setattr(nm, "get_config", lambda: Stub())
        manager = nm.notification_manager
        manager.config.enabled = True
        delivered: list[object] = []

        class Records:
            def send(self, event: object) -> bool:
                delivered.append(event)
                return True

        manager.register_provider(NotificationType.WEB, Records())
        event_id = manager.send_notification(
            title="still delivered",
            message="persistence is best effort",
            trigger=NotificationTrigger.IMMEDIATE,
            types=[NotificationType.WEB],
        )
        assert event_id
        assert len(delivered) == 1
