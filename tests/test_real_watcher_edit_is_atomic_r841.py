"""R841 — the R792 test helper must replace ``config.toml`` the way ``ConfigManager`` itself saves it.

``test_the_real_watcher_thread_closes_the_gap`` (R792) failed once on CI — Python 3.13, run 39916947793
on Dependabot pull request #127, which only raises the eslint version in two JavaScript files — with
``assert 0.8 == 0.2 ± 2.0e-07`` *after* the assertion that the watcher had reloaded had passed.

The product was fine; the helper was not.  ``World.edit`` wrote the file in place (``Path.write_text``)
and then moved its modification time *back* to a made-up value (``os.utime``).  ``write_text`` truncates
the file as it opens it, so for a moment ``config.toml`` is empty and carries the real clock's mtime
(2026), far above the made-up one (2023).  The watcher thread polls every 0.2 s in that test.  A poll in
that moment reads an empty file (the defaults, volume 80), notes the 2026 mtime and moves the epoch;
once ``os.utime`` has set the 2023 mtime the watcher never reloads again, because it reloads only on a
*greater* mtime.  The manager keeps 0.8 for good although the file says 20.

Reproduced with the real test and the real watcher by keeping the file empty for 0.5 s between the
truncation and the write: it fails with the CI's exact message.  The same slow writer going through a
temp file and ``os.replace`` — what ``ConfigManager._save_config_immediate`` does — passes.  At natural
speed (real watcher polling every millisecond, 3000 edits per way) writing in place left the manager on
the old value after 194 edits on Linux and 36 on macOS; replacing the file, after none.

A reader polling with no pause is how the first property below is checked: every state of ``config.toml`` it
sees must be a complete one, with the mtime the helper gave it.  The second property pins the mechanism.
"""

from __future__ import annotations

import os
import sys
import threading
from pathlib import Path

import pytest

from tests.test_notification_refresh_after_reload_r792 import World


@pytest.fixture
def world(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> World:
    return World(tmp_path, monkeypatch)


class _Reader(threading.Thread):
    """Reads ``path`` over and over and keeps every ``(content, mtime)`` pair it gets.

    The mtime comes from the open file (``fstat``), so content and mtime belong to the same file even
    if a rename lands between two reads.
    """

    def __init__(self, path: Path) -> None:
        super().__init__(daemon=True)
        self.path = path
        self.halt = threading.Event()
        self.seen: set[tuple[str, float]] = set()
        self.reads = 0

    def run(self) -> None:
        while not self.halt.is_set():
            try:
                with open(self.path, encoding="utf-8") as handle:
                    mtime = os.fstat(handle.fileno()).st_mtime
                    content = handle.read()
            except OSError:
                continue
            self.seen.add((content, mtime))
            self.reads += 1


def _state(world: World) -> tuple[str, float]:
    with open(world.path, encoding="utf-8") as handle:
        return handle.read(), os.fstat(handle.fileno()).st_mtime


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="Windows refuses to rename over a file another thread has open",
)
class TestNoReaderSeesAnEditHalfMade:
    def test_every_state_a_reader_sees_is_a_finished_edit(self, world: World) -> None:
        expected = {_state(world)}
        reader = _Reader(world.path)
        reader.start()
        try:
            for volume in range(1, 301):
                world.edit(volume)
                expected.add(_state(world))
        finally:
            reader.halt.set()
            reader.join(10)

        assert not reader.is_alive()
        assert reader.reads > 0
        strange = sorted(reader.seen - expected)
        assert not strange, (
            f"{len(strange)} state(s) of config.toml were seen that no edit ever finished, "
            f"e.g. {strange[0]!r}: a reader (the config watcher) can take them for the edit"
        )

    def test_an_edit_replaces_the_file_it_does_not_rewrite_it(
        self, world: World
    ) -> None:
        before = world.path.stat().st_ino
        world.edit(20)
        assert world.path.stat().st_ino != before, (
            "World.edit rewrote config.toml in place; build the new file next to it and os.replace it"
        )
