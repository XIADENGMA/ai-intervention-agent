"""R792 — a ``config.toml`` edit that arrives while the config watcher is still asleep must not be lost.

Two caches sit between the file and ``NotificationManager``:

* ``ConfigManager`` keeps the parsed file in memory and a watcher thread re-reads it when
  the file's mtime moves — up to 2 seconds after the edit;
* ``NotificationManager.refresh_config_from_file`` skipped its work whenever the file's mtime
  equalled the one it had seen last, and it did that *without asking whether the watcher had
  loaded the new content yet*.

A refresh that ran in that window — the MCP server calls it for every new task — saw the new
mtime, wrote it down, read the still-old section out of memory and applied it.  When the
watcher then loaded the edit, the next refresh compared mtimes again, found them equal and
returned: the edit was never applied.  Measured with a real watcher thread
(``sound_volume`` 80 -> 20 written to the file, one refresh 0.3 s later, five more seconds
for the watcher): the manager stayed at 0.8 until the process restarted or the file was
touched again; ``force=True`` was the only way out.  Switching Bark off in the Web UI, which
the *other* process picks up through the file, could leave pushes going out indefinitely.

``ConfigManager`` now counts how often its caches were invalidated wholesale (``reload()``,
``restore_config()`` — every time the in-memory configuration was replaced) as
``cache_epoch``.  The refresh skips only when both the mtime and the epoch are the ones it
last applied, and it reads the epoch *before* the section, so a refresh that got old content
also holds the old epoch and runs again after the reload.
"""

from __future__ import annotations

import ast
import inspect
import os
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from ai_intervention_agent.config_manager import ConfigManager
from ai_intervention_agent.notification_manager import NotificationManager

MODULE = "ai_intervention_agent.notification_manager"
FIRST_MTIME = 1_700_000_000.0


class World:
    """A config file, a real ``ConfigManager`` on it (no watcher thread), and a notification manager."""

    def __init__(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self.path = tmp_path / "config.toml"
        self._mtime = FIRST_MTIME
        self.edit(80)
        self.config = ConfigManager(str(self.path))
        self.manager = NotificationManager._create_test_instance()
        monkeypatch.setattr(f"{MODULE}.get_config", lambda: self.config)
        monkeypatch.setattr(f"{MODULE}.CONFIG_FILE_AVAILABLE", True)

    def edit(self, volume: int) -> None:
        """Replace the file, as ``ConfigManager`` saves it, with a modification time that cannot equal the last one.

        The new file is finished and dated next to the old one and then renamed over it, so the
        watcher thread of the real-watcher test sees the old file or the new one and nothing in
        between.  Writing in place left the file empty for a moment, dated by the real clock and
        therefore *above* the made-up one the next ``os.utime`` set; a poll landing in that moment
        read the empty file, noted the high mtime and never reloaded again, because the watcher
        reloads only on a greater one (R841: ``assert 0.8 == 0.2`` on CI).
        """
        new = self.path.with_name(self.path.name + ".new")
        new.write_text(f"[notification]\nsound_volume = {volume}\n", encoding="utf-8")
        self._mtime += 10
        os.utime(new, (self._mtime, self._mtime))
        os.replace(new, self.path)

    def refresh(self) -> None:
        self.manager.refresh_config_from_file()

    @property
    def volume(self) -> float:
        return self.manager.config.sound_volume

    def count_section_reads(self, monkeypatch: pytest.MonkeyPatch) -> list[str]:
        calls: list[str] = []
        real = self.config.get_section

        def counting(section: str, *args: Any, **kwargs: Any) -> dict[str, Any]:
            calls.append(section)
            return real(section, *args, **kwargs)

        monkeypatch.setattr(self.config, "get_section", counting)
        return calls


@pytest.fixture
def world(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> World:
    return World(tmp_path, monkeypatch)


# ---------------------------------------------------------------------------
# The gap between the edit and the watcher
# ---------------------------------------------------------------------------
class TestAnEditThatBeatsTheWatcherIsStillApplied:
    def test_it_is_applied_once_the_watcher_has_loaded_it(self, world: World) -> None:
        world.refresh()
        assert world.volume == pytest.approx(0.8)

        world.edit(20)
        world.refresh()  # a task arrives before the watcher has polled
        assert world.volume == pytest.approx(0.8)  # nothing newer is in memory yet

        world.config.reload()  # the watcher's poll, up to 2 s later
        world.refresh()
        assert world.volume == pytest.approx(0.2)

    def test_it_is_applied_when_several_refreshes_ran_in_the_gap(
        self, world: World
    ) -> None:
        world.refresh()
        world.edit(20)
        for _ in range(3):
            world.refresh()
        world.config.reload()
        world.refresh()
        assert world.volume == pytest.approx(0.2)

    def test_a_later_edit_is_still_picked_up_as_before(self, world: World) -> None:
        world.refresh()
        world.edit(20)
        world.config.reload()
        world.refresh()
        assert world.volume == pytest.approx(0.2)

        world.edit(55)
        world.config.reload()
        world.refresh()
        assert world.volume == pytest.approx(0.55)

    def test_a_reload_that_lands_between_the_epoch_and_the_section_is_not_lost(
        self, world: World, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The watcher can finish a reload right after the refresh read the section; what
        the refresh holds is then old content, and it must not be filed under the new epoch."""
        world.refresh()
        world.edit(20)  # on disk, not loaded yet
        real = world.config.get_section

        def read_then_reload(section: str, *args: Any, **kwargs: Any) -> dict[str, Any]:
            data = real(section, *args, **kwargs)  # still the old content
            world.config.reload()  # the watcher finishes right after
            return data

        monkeypatch.setattr(world.config, "get_section", read_then_reload)
        world.refresh()
        assert world.volume == pytest.approx(0.8)

        monkeypatch.setattr(world.config, "get_section", real)
        world.refresh()
        assert world.volume == pytest.approx(0.2)

    def test_the_real_watcher_thread_closes_the_gap(self, world: World) -> None:
        """Same thing with the actual watcher thread; the refresh right after the edit
        almost always beats its poll, and whichever wins the result must be the same."""
        world.config.start_file_watcher(interval=0.2)
        try:
            world.refresh()
            before = world.config.cache_epoch
            world.edit(20)
            world.refresh()

            deadline = time.monotonic() + 15
            while world.config.cache_epoch == before and time.monotonic() < deadline:
                time.sleep(0.01)
            assert world.config.cache_epoch > before, "the watcher never reloaded"

            world.refresh()
            assert world.volume == pytest.approx(0.2)
        finally:
            world.config.stop_file_watcher()


class TestTheCacheStillSkipsWhatDidNotChange:
    def test_nothing_changed_reads_nothing(
        self, world: World, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        world.refresh()
        reads = world.count_section_reads(monkeypatch)
        for _ in range(5):
            world.refresh()
        assert reads == []

    def test_a_reload_of_an_unchanged_file_is_applied_once_then_skipped(
        self, world: World, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        world.refresh()
        reads = world.count_section_reads(monkeypatch)
        world.config.reload()
        for _ in range(4):
            world.refresh()
        assert reads == ["notification"]
        assert world.volume == pytest.approx(0.8)

    def test_force_applies_even_when_nothing_changed(
        self, world: World, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        world.refresh()
        reads = world.count_section_reads(monkeypatch)
        world.manager.refresh_config_from_file(force=True)
        world.manager.refresh_config_from_file(force=True)
        assert reads == ["notification", "notification"]

    def test_a_file_that_cannot_be_stat_ed_is_never_cached(
        self, world: World, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        world.refresh()
        reads = world.count_section_reads(monkeypatch)
        world.path.unlink()
        world.refresh()
        world.refresh()
        assert reads == ["notification", "notification"]


# ---------------------------------------------------------------------------
# The counter on ConfigManager
# ---------------------------------------------------------------------------
@pytest.fixture
def config(tmp_path: Path) -> Iterator[ConfigManager]:
    path = tmp_path / "config.toml"
    path.write_text("[notification]\nsound_volume = 80\n", encoding="utf-8")
    yield ConfigManager(str(path))


class TestTheEpoch:
    def test_it_moves_with_every_wholesale_invalidation(
        self, config: ConfigManager
    ) -> None:
        start = config.cache_epoch
        config.invalidate_all_caches()
        assert config.cache_epoch == start + 1
        config.reload()
        assert config.cache_epoch == start + 2

    def test_restoring_a_backup_moves_it(
        self, config: ConfigManager, tmp_path: Path
    ) -> None:
        backup = config.backup_config(str(tmp_path / "backup.json"))
        start = config.cache_epoch
        assert config.restore_config(backup) is True
        assert config.cache_epoch > start

    def test_invalidating_one_section_does_not_move_it(
        self, config: ConfigManager
    ) -> None:
        config.get_section("notification")
        start = config.cache_epoch
        config.invalidate_section_cache("notification")
        assert config.cache_epoch == start

    def test_reading_does_not_move_it(self, config: ConfigManager) -> None:
        start = config.cache_epoch
        for _ in range(3):
            config.get_section("notification")
            config.get_section("web_ui")
        assert config.cache_epoch == start

    def test_it_is_a_read_only_integer(self, config: ConfigManager) -> None:
        assert isinstance(config.cache_epoch, int)
        with pytest.raises(AttributeError):
            object.__setattr__(config, "cache_epoch", 5)

    def test_an_instance_built_without_init_still_counts(self) -> None:
        """Several tests build a ``ConfigManager`` through ``__new__`` and set attributes by hand."""
        bare = ConfigManager.__new__(ConfigManager)
        bare._lock = threading.RLock()
        bare._section_cache = {}
        bare._section_cache_time = {}
        bare._network_security_cache = None
        bare._network_security_cache_time = 0
        bare._cache_stats = {"hits": 0, "misses": 0, "invalidations": 0}
        bare.invalidate_all_caches()
        bare.invalidate_all_caches()
        assert bare.cache_epoch == 2


class TestTheManagerSide:
    def test_a_test_instance_starts_without_an_epoch(self) -> None:
        instance = NotificationManager._create_test_instance()
        assert instance._config_cache_epoch == -1

    def test_the_epoch_is_read_before_the_section(self) -> None:
        """Source guard for the ordering the dynamic test above exercises: reading it after
        would file old content under the new epoch."""
        source = inspect.getsource(NotificationManager.refresh_config_from_file)
        tree = ast.parse(source.lstrip())
        epoch_lines: list[int] = []
        section_lines: list[int] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr == "cache_epoch":
                epoch_lines.append(node.lineno)
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "get_section"
            ):
                section_lines.append(node.lineno)
        assert epoch_lines, (
            "refresh_config_from_file must look at ConfigManager.cache_epoch"
        )
        assert section_lines, (
            "refresh_config_from_file must read the notification section"
        )
        assert min(epoch_lines) < min(section_lines)
