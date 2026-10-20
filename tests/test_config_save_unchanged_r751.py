"""R751: saving a config that did not change leaves the file alone.

``ConfigManager.shutdown()`` runs at interpreter exit and calls ``force_save()``,
which wrote ``config.toml`` whether or not anything had changed. The text it wrote
was byte-identical to the file, but the atomic write (temp file plus
``os.replace``) gave the file a new inode and a new mtime. Every other process
watching that file (the MCP server and the Web UI process, a second IDE window)
then reloaded and broadcast ``config_changed``, and the Web UI showed
"Configuration file changed" for a change nobody made. The same write could also
put one process's stale copy over a setting saved from another process.

``_save_config_immediate`` now skips the write when the text it would write equals
the text this process last read or wrote, and the file still exists.
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import tomllib
from pathlib import Path
from unittest.mock import patch

import pytest

from ai_intervention_agent import config_manager
from ai_intervention_agent.config_manager import ConfigManager

REPO_ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = REPO_ROOT / "config.toml.default"
VOLUME_LINE = "sound_volume = 80"


def snapshot(path: Path) -> tuple[int, int, bytes]:
    stat = path.stat()
    return stat.st_ino, stat.st_mtime_ns, path.read_bytes()


def volume(path: Path) -> int:
    return tomllib.loads(path.read_text(encoding="utf-8"))["notification"][
        "sound_volume"
    ]


@pytest.fixture(params=["commented-template", "generated-by-manager"])
def config_file(request: pytest.FixtureRequest, tmp_path: Path) -> Path:
    path = tmp_path / "config.toml"
    if request.param == "commented-template":
        path.write_bytes(TEMPLATE.read_bytes())
    else:
        with patch.object(
            config_manager, "find_default_config_template", return_value=None
        ):
            ConfigManager(str(path)).shutdown()
        assert "#" not in path.read_text(encoding="utf-8")
    assert path.exists()
    return path


def test_force_save_leaves_an_unchanged_file_alone(config_file: Path) -> None:
    manager = ConfigManager(str(config_file))
    before = snapshot(config_file)

    manager.force_save()

    assert snapshot(config_file) == before


def test_shutdown_leaves_an_unchanged_file_alone(config_file: Path) -> None:
    manager = ConfigManager(str(config_file))
    before = snapshot(config_file)

    manager.shutdown()

    assert snapshot(config_file) == before


def test_exiting_process_leaves_the_file_alone(config_file: Path) -> None:
    before = snapshot(config_file)
    env = dict(os.environ, AI_INTERVENTION_AGENT_CONFIG_FILE=str(config_file))

    subprocess.run(
        [
            sys.executable,
            "-c",
            "from ai_intervention_agent.config_manager import config_manager",
        ],
        env=env,
        cwd=config_file.parent,
        check=True,
        timeout=60,
    )

    assert snapshot(config_file) == before


def test_shutdown_still_flushes_a_pending_change(config_file: Path) -> None:
    manager = ConfigManager(str(config_file))
    manager.update_section("notification", {"sound_volume": 55})
    assert volume(config_file) != 55

    manager.shutdown()

    assert volume(config_file) == 55


def test_force_save_still_writes_a_changed_value(config_file: Path) -> None:
    manager = ConfigManager(str(config_file))
    manager.update_section("notification", {"sound_volume": 56}, save=False)

    manager.force_save()

    assert volume(config_file) == 56


def test_comments_survive_a_flushed_change(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_bytes(TEMPLATE.read_bytes())
    comment_lines = [
        ln for ln in path.read_text("utf-8").split("\n") if ln.startswith("#")
    ]
    manager = ConfigManager(str(path))
    manager.update_section("notification", {"sound_volume": 57})

    manager.shutdown()

    saved = path.read_text(encoding="utf-8")
    assert [ln for ln in saved.split("\n") if ln.startswith("#")] == comment_lines
    assert volume(path) == 57


def test_shutdown_does_not_put_a_stale_copy_over_an_external_edit(
    config_file: Path,
) -> None:
    manager = ConfigManager(str(config_file))
    original = config_file.read_text("utf-8")
    edited = original.replace(VOLUME_LINE, "sound_volume = 33")
    assert edited != original
    config_file.write_text(edited, encoding="utf-8")

    manager.shutdown()

    assert config_file.read_text("utf-8") == edited


def test_a_skipped_save_does_not_hide_an_external_edit_from_the_watcher(
    config_file: Path,
) -> None:
    manager = ConfigManager(str(config_file))
    known = manager._last_file_mtime
    edited = config_file.read_text("utf-8") + "\n# edited elsewhere\n"
    config_file.write_text(edited, encoding="utf-8")
    newer_ns = int(known * 1e9) + 5_000_000_000
    os.utime(config_file, ns=(newer_ns, newer_ns))

    manager.force_save()

    assert config_file.stat().st_mtime > manager._last_file_mtime
    assert config_file.read_text("utf-8") == edited


def test_force_save_recreates_a_deleted_file(config_file: Path) -> None:
    manager = ConfigManager(str(config_file))
    config_file.unlink()

    manager.force_save()

    assert config_file.exists()
    assert volume(config_file) == 80


def test_a_process_exiting_unchanged_does_not_wake_another_watcher(
    config_file: Path,
) -> None:
    watcher_owner = ConfigManager(str(config_file))
    woken = threading.Event()
    watcher_owner.register_config_change_callback(woken.set)
    watcher_owner.start_file_watcher(interval=0.05)
    try:
        ConfigManager(str(config_file)).shutdown()
        assert not woken.wait(0.6)

        changer = ConfigManager(str(config_file))
        changer.update_section("notification", {"sound_volume": 41}, save=False)
        changer.force_save()
        assert woken.wait(10)
        assert watcher_owner.get("notification")["sound_volume"] == 41
    finally:
        watcher_owner.shutdown()
