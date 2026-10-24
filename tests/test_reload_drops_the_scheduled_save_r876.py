"""R876: a reload drops the save that was scheduled before it, whoever scheduled it.

``ConfigManager`` writes behind a 3 s debounce: ``set``, ``update``, ``import_config`` and
``update_section`` start a ``threading.Timer`` whose callback writes the in-memory config to the
file.  ``reload()`` (what the file watcher calls when the file changed on disk) and
``restore_config()`` replace the in-memory config with what is on disk, and the policy is "the
external edit wins": whatever was waiting to be saved is thrown away.  ``_load_config`` did that
for the saves that had a key in ``_pending_changes`` (``set``, ``update``, ``import_config``) and
forgot the one that has none: ``update_section`` marks nothing as pending, so its timer survived the
reload and fired up to three seconds later on top of the config that had just been loaded.

That save serialises the config into the file it was just told is the truth.  A file that lacks a
key the defaults have, such as a hand-written minimal config, comes back with every default key
added: a hand edit rewritten behind the editor's back.  A save of this kind, parsing the default
config in the middle of another test's ``tracemalloc`` window, is also what made a memory test of
R845 fail at random in the CI (R828 has one of the same pattern); those tests now measure in a
clean interpreter (see ``tests/conftest.py``).

The timer is cancelled by the reload itself, not by whoever scheduled it.  These tests pin that for
every way of scheduling, for ``restore_config`` (the other caller of ``_load_config``), and that a
save scheduled after the reload still runs.  Nothing here waits for a timer: the delay is parked far
away, and "the time has come" is done by hand, as the timer thread would, for a timer that was not
cancelled.
"""

from __future__ import annotations

import json
import logging
import threading
import tomllib
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from ai_intervention_agent.config_manager import ConfigManager

#: A delay nobody waits for: these timers are never left to run by themselves.
PARKED = 600.0

#: A hand-written file that has none of the keys the defaults add.
MINIMAL = '[notification]\nbark_url = "https://A"\n'

#: The same file after someone edited it by hand while a save was waiting.
HAND_EDITED = '# edited by hand\n[notification]\nbark_url = "https://B"\n'

PROCESS_SIDE = "https://process-side"


def _set(manager: ConfigManager) -> None:
    manager.set("notification.bark_url", PROCESS_SIDE)


def _update(manager: ConfigManager) -> None:
    manager.update({"notification.bark_url": PROCESS_SIDE})


def _update_section(manager: ConfigManager) -> None:
    manager.update_section("notification", {"bark_url": PROCESS_SIDE})


def _import_config(manager: ConfigManager) -> None:
    manager.import_config({"notification": {"bark_url": PROCESS_SIDE}})


#: Every way the manager has of scheduling a save; only the last one records no pending key.
SCHEDULERS: dict[str, Callable[[ConfigManager], None]] = {
    "set": _set,
    "update": _update,
    "import_config": _import_config,
    "update_section": _update_section,
}


def fire_if_still_scheduled(timer: threading.Timer) -> bool:
    """Do what the timer thread does when its time has come, unless the timer was cancelled."""
    if timer.finished.is_set():
        return False
    timer.cancel()  # the thread must not run the callback a second time
    timer.function(*timer.args, **timer.kwargs)
    return True


@pytest.fixture
def manager(tmp_path: Path) -> Iterator[ConfigManager]:
    path = tmp_path / "config.toml"
    path.write_text(MINIMAL, encoding="utf-8")
    manager = ConfigManager(str(path))
    manager.stop_file_watcher()
    manager._save_delay = PARKED
    try:
        yield manager
    finally:
        with manager._lock:
            if manager._save_timer is not None:
                manager._save_timer.cancel()
                manager._save_timer = None


class TestAReloadDropsTheSaveScheduledBeforeIt:
    @pytest.mark.parametrize("how", list(SCHEDULERS))
    def test_the_timer_is_cancelled(self, manager: ConfigManager, how: str) -> None:
        SCHEDULERS[how](manager)
        timer = manager._save_timer
        assert timer is not None
        assert not timer.finished.is_set(), "nothing has run or cancelled it yet"

        manager.reload()

        assert manager._save_timer is None
        assert timer.finished.is_set(), (
            "the timer that was waiting must not be left to fire"
        )

    @pytest.mark.parametrize("how", list(SCHEDULERS))
    def test_a_hand_edited_file_is_left_alone_when_its_time_comes(
        self, manager: ConfigManager, how: str
    ) -> None:
        SCHEDULERS[how](manager)
        timer = manager._save_timer
        assert timer is not None
        manager.config_file.write_text(HAND_EDITED, encoding="utf-8")

        manager.reload()
        fire_if_still_scheduled(timer)

        assert manager.config_file.read_text(encoding="utf-8") == HAND_EDITED
        assert manager.get("notification.bark_url") == "https://B", (
            "the external edit wins"
        )

    def test_dropping_a_save_that_has_no_pending_key_is_not_a_warning(
        self, manager: ConfigManager, caplog: pytest.LogCaptureFixture
    ) -> None:
        _update_section(manager)

        with caplog.at_level(logging.WARNING):
            manager.reload()

        assert [
            r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING
        ] == []

    def test_a_reload_with_nothing_scheduled_changes_nothing(
        self, manager: ConfigManager
    ) -> None:
        assert manager._save_timer is None
        before = manager.config_file.read_text(encoding="utf-8")

        manager.reload()
        manager.reload()

        assert manager._save_timer is None
        assert manager.config_file.read_text(encoding="utf-8") == before

    def test_a_save_scheduled_after_the_reload_still_runs(
        self, manager: ConfigManager
    ) -> None:
        manager.update_section("feedback", {"frontend_countdown": 124})
        manager.reload()

        manager.update_section("feedback", {"frontend_countdown": 125})
        timer = manager._save_timer
        assert timer is not None
        assert not timer.finished.is_set()
        assert fire_if_still_scheduled(timer)

        saved = tomllib.loads(manager.config_file.read_text(encoding="utf-8"))
        assert saved["feedback"]["frontend_countdown"] == 125


class TestRestoreConfigDropsItToo:
    """``restore_config`` swaps the in-memory config for the restored file through ``_load_config``."""

    def test_the_save_scheduled_before_the_restore_does_not_rewrite_the_restored_file(
        self, manager: ConfigManager, tmp_path: Path
    ) -> None:
        backup = tmp_path / "backup.json"
        backup.write_text(
            json.dumps({"config": {"notification": {"bark_url": "https://R"}}}),
            encoding="utf-8",
        )
        _update_section(manager)
        timer = manager._save_timer
        assert timer is not None

        assert manager.restore_config(str(backup)) is True
        restored = manager.config_file.read_text(encoding="utf-8")
        assert tomllib.loads(restored) == {"notification": {"bark_url": "https://R"}}, (
            "the restored file must lack the default keys, or the stray save would have nothing to add"
        )
        fire_if_still_scheduled(timer)

        assert manager._save_timer is None
        assert manager.config_file.read_text(encoding="utf-8") == restored
