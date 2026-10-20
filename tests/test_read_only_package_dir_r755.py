"""R755: a package folder that cannot be written to does not stop the server.

The task queue keeps its snapshot in ``<package>/data/tasks.json`` and the Web UI
subprocess writes ``<package>/logs/web_ui.log``. Neither folder ships in the wheel;
both are created on first use. When the package sits somewhere the user cannot write
(a system-wide install run by another user, a container that runs as a non-root user,
a read-only store), ``TaskQueue.__init__`` and ``_get_web_ui_log_path`` raised
``PermissionError``, so the first feedback request failed even though neither the
queue nor the Web UI needs the disk to work. The code already called a failed
snapshot "does not affect the run" and discarded the output of a log file it could
not open; creating the folders now falls back the same way.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from ai_intervention_agent import service_manager, task_queue, task_queue_singleton
from ai_intervention_agent.service_manager import ServiceManager, WebUIConfig
from ai_intervention_agent.task_queue import TaskQueue

needs_permission_bits = pytest.mark.skipif(
    os.name == "nt" or (hasattr(os, "geteuid") and os.geteuid() == 0),
    reason="needs POSIX permission bits that the current user does not bypass",
)


def blocked_path(tmp_path: Path) -> Path:
    """A snapshot path whose folder cannot be created, whoever runs the test."""
    blocker = tmp_path / "blocker"
    blocker.write_text("not a folder", encoding="utf-8")
    return blocker / "data" / "tasks.json"


def add_one_task(queue: TaskQueue) -> None:
    assert queue.add_task(task_id="t1", prompt="hello", auto_resubmit_timeout=60)
    assert queue.get_task("t1") is not None


def test_a_snapshot_folder_that_cannot_be_created_leaves_a_working_queue(
    tmp_path: Path,
) -> None:
    with patch.object(task_queue.logger, "warning") as warning:
        queue = TaskQueue(max_tasks=3, persist_path=str(blocked_path(tmp_path)))
    try:
        assert queue._persist_path is None
        add_one_task(queue)
    finally:
        queue.stop_cleanup()
    warning.assert_called_once()


@needs_permission_bits
def test_a_read_only_snapshot_folder_is_noticed_once_and_not_on_every_write(
    tmp_path: Path,
) -> None:
    data = tmp_path / "data"
    data.mkdir()
    data.chmod(0o500)
    try:
        with patch.object(task_queue.logger, "warning") as warning:
            queue = TaskQueue(max_tasks=3, persist_path=str(data / "tasks.json"))
            try:
                assert queue._persist_path is None
                add_one_task(queue)
            finally:
                queue.stop_cleanup()
        assert warning.call_count == 1
        assert list(data.iterdir()) == []
    finally:
        data.chmod(0o700)


def test_a_writable_snapshot_folder_still_persists(tmp_path: Path) -> None:
    path = tmp_path / "data" / "tasks.json"
    queue = TaskQueue(max_tasks=3, persist_path=str(path))
    try:
        assert queue._persist_path == path
        add_one_task(queue)
        assert path.is_file()
    finally:
        queue.stop_cleanup()


def test_the_global_queue_is_built_even_when_its_default_path_is_unusable(
    tmp_path: Path,
) -> None:
    saved = task_queue_singleton._global_task_queue
    task_queue_singleton._global_task_queue = None
    try:
        with (
            patch.object(
                task_queue_singleton,
                "_default_persist_path",
                return_value=blocked_path(tmp_path),
            ),
            patch.object(task_queue.logger, "warning"),
        ):
            queue = task_queue_singleton.get_task_queue()
        assert queue._persist_path is None
        add_one_task(queue)
    finally:
        created = task_queue_singleton._global_task_queue
        task_queue_singleton._global_task_queue = saved
        if created is not None:
            created.stop_cleanup()


def test_no_log_path_when_the_logs_folder_cannot_be_created(tmp_path: Path) -> None:
    (tmp_path / "logs").write_text("not a folder", encoding="utf-8")
    with patch.object(service_manager.logger, "warning") as warning:
        assert service_manager._get_web_ui_log_path(tmp_path) is None
    assert warning.call_count == 1


def test_the_log_path_of_a_writable_folder_is_created(tmp_path: Path) -> None:
    path = service_manager._get_web_ui_log_path(tmp_path)
    assert path is not None
    assert path == tmp_path / "logs" / "web_ui.log"
    assert path.parent.is_dir()


def start_with_package_dir(package_dir: Path) -> MagicMock:
    process = MagicMock()
    process.pid = 4242
    ServiceManager._instance = None
    try:
        with (
            patch.object(service_manager, "_is_port_available", return_value=True),
            patch.object(
                service_manager, "health_check_service", side_effect=[False, True]
            ),
            patch.object(service_manager, "NOTIFICATION_AVAILABLE", False),
            patch.object(
                service_manager.subprocess, "Popen", return_value=process
            ) as popen,
        ):
            service_manager.start_web_service(
                WebUIConfig(host="127.0.0.1", port=18755), package_dir
            )
    finally:
        ServiceManager._instance = None
    return popen


def test_the_web_ui_starts_when_there_is_nowhere_to_write_its_log(
    tmp_path: Path,
) -> None:
    (tmp_path / "web_ui.py").write_text("", encoding="utf-8")
    (tmp_path / "logs").write_text("not a folder", encoding="utf-8")

    with patch.object(service_manager.logger, "warning") as warning:
        popen = start_with_package_dir(tmp_path)

    popen.assert_called_once()
    assert popen.call_args.kwargs["stderr"] == subprocess.DEVNULL
    warning.assert_called_once()


def test_the_web_ui_log_goes_to_the_log_file_when_it_can_be_written(
    tmp_path: Path,
) -> None:
    (tmp_path / "web_ui.py").write_text("", encoding="utf-8")

    popen = start_with_package_dir(tmp_path)

    popen.assert_called_once()
    assert popen.call_args.kwargs["stderr"] != subprocess.DEVNULL
    assert (tmp_path / "logs" / "web_ui.log").is_file()
