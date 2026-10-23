"""R844: replacing a whole file atomically is written once, in ``config_utils.atomic_write_text``.

Four places each wrote the same sequence - temporary file in the target's directory, write,
``flush``, ``fsync``, ``os.replace``, remove the temporary file if anything went wrong:
``ConfigManager._save_config_immediate``, ``IOOperationsMixin.restore_config``,
``NetworkSecurityMixin._atomic_write_config`` and ``TaskQueue._persist``.  They had already
drifted apart (R17.2 was ``_persist`` missing its ``fsync``), and the drift that was left:

* ``_atomic_write_config`` called ``os.fchmod`` on the raw descriptor *before* wrapping it in a
  file object, so a mount that refuses ``fchmod`` leaked one descriptor per failed save;
* ``_persist`` cleaned up on ``Exception`` only, so Ctrl-C / ``SystemExit`` / a cancelled task
  between creating the temporary file and renaming it left ``.tasks_*.tmp`` (the prompts of the
  open tasks) lying in the data directory;
* ``restore_config`` was the only config writer that did not carry over the mode of the file
  it replaced (R827: an existing file is left alone - neither tightened nor loosened), so a
  restore reset a group-readable ``config.toml`` to 0600 while every save kept it.

Now the sequence exists once.  This file pins its contract (order of the system calls, what a
failure at each step leaves behind, the mode rules), the three divergences above at their
call sites, and the structure: each call site calls the helper and holds no copy of the
sequence.  Nothing here patches the writers it tests; a failure is injected into the one
system call that is supposed to fail.
"""

from __future__ import annotations

import ast
import contextlib
import errno
import os
import stat
import subprocess
import sys
import tempfile
import threading
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest

from ai_intervention_agent.config_manager import ConfigManager
from ai_intervention_agent.config_utils import atomic_write_text
from ai_intervention_agent.task_queue import TaskQueue

SRC = Path(__file__).resolve().parents[1] / "src" / "ai_intervention_agent"
TOKEN = "tok_" + "0123456789abcdef" * 2

posix_only = pytest.mark.skipif(
    sys.platform == "win32", reason="POSIX permission bits (Windows has ACLs)"
)


def mode_of(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def names_in(directory: Path) -> list[str]:
    return sorted(entry.name for entry in directory.iterdir())


def raising(error: BaseException) -> Callable[..., Any]:
    def fail(*args: Any, **kwargs: Any) -> Any:
        raise error

    return fail


@contextlib.contextmanager
def umask(value: int) -> Iterator[None]:
    previous = os.umask(value)
    try:
        yield
    finally:
        os.umask(previous)


@pytest.fixture
def open_descriptors(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[Callable[[], list[int]]]:
    """``leaked()``: descriptors that ``mkstemp`` handed out and nobody closed.

    A descriptor counts as leaked only while it still refers to the very file it was handed
    out for, so a number that was closed and then reused by another thread is not a leak.
    """
    real_mkstemp = tempfile.mkstemp
    handed_out: list[tuple[int, int, int]] = []

    def spy(*args: Any, **kwargs: Any) -> tuple[int, str]:
        fd, name = real_mkstemp(*args, **kwargs)
        info = os.fstat(fd)
        handed_out.append((fd, info.st_dev, info.st_ino))
        return fd, name

    monkeypatch.setattr(tempfile, "mkstemp", spy)

    def leaked() -> list[int]:
        still_open: list[int] = []
        for fd, dev, ino in handed_out:
            try:
                info = os.fstat(fd)
            except OSError:
                continue
            if (info.st_dev, info.st_ino) == (dev, ino):
                still_open.append(fd)
        return still_open

    yield leaked
    for fd in leaked():  # a leak must not spill into the next test
        with contextlib.suppress(OSError):
            os.close(fd)


@pytest.fixture
def make_manager() -> Iterator[Callable[[Path], ConfigManager]]:
    created: list[ConfigManager] = []

    def make(path: Path) -> ConfigManager:
        manager = ConfigManager(str(path))
        created.append(manager)
        return manager

    try:
        yield make
    finally:
        for manager in created:
            manager.shutdown()


# ---------------------------------------------------------------------------
# 1. the helper: what it writes, in which order, with which names
# ---------------------------------------------------------------------------
class TestTheSequence:
    def test_the_new_content_replaces_the_old_and_nothing_else_is_left(
        self, tmp_path: Path
    ) -> None:
        target = tmp_path / "config.toml"
        target.write_text("old", encoding="utf-8")

        atomic_write_text(target, "new")

        assert target.read_text(encoding="utf-8") == "new"
        assert names_in(tmp_path) == ["config.toml"]

    def test_the_data_is_flushed_and_synced_before_the_rename(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # R17.2: the name must not point at an inode whose data is still in a buffer.
        # "flush" shows as the temporary file already holding the whole text when fsync
        # runs; "fsync before replace" as the target still holding the old text then.
        target = tmp_path / "config.toml"
        target.write_text("old", encoding="utf-8")
        mine = threading.get_ident()
        events: list[tuple[Any, ...]] = []
        real_fsync, real_replace = os.fsync, os.replace

        def fsync(fd: int) -> None:
            if threading.get_ident() == mine:
                temporaries = [p for p in tmp_path.iterdir() if p != target]
                events.append(
                    (
                        "fsync",
                        [p.read_text(encoding="utf-8") for p in temporaries],
                        target.read_text(encoding="utf-8"),
                    )
                )
            real_fsync(fd)

        def replace(src: Any, dst: Any) -> None:
            if threading.get_ident() == mine:
                events.append(
                    (
                        "replace",
                        Path(src).read_text(encoding="utf-8"),
                        Path(src).parent,
                        Path(dst),
                        target.read_text(encoding="utf-8"),
                    )
                )
            real_replace(src, dst)

        monkeypatch.setattr(os, "fsync", fsync)
        monkeypatch.setattr(os, "replace", replace)

        atomic_write_text(target, "new")

        assert [event[0] for event in events] == ["fsync", "replace"]
        assert events[0][1:] == (["new"], "old")
        assert events[1][1:] == ("new", tmp_path, target, "old")
        assert target.read_text(encoding="utf-8") == "new"

    def test_the_temporary_file_is_named_after_the_caller_and_sits_beside_the_target(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Beside the target = the same filesystem = the rename is atomic.
        seen: list[Path] = []
        real_replace = os.replace

        def replace(src: Any, dst: Any) -> None:
            seen.append(Path(src))
            real_replace(src, dst)

        monkeypatch.setattr(os, "replace", replace)

        atomic_write_text(tmp_path / "one.json", "1")
        atomic_write_text(tmp_path / "two.json", "2", temp_prefix=".two_")

        first, second = seen
        assert first.parent == second.parent == tmp_path
        assert first.suffix == second.suffix == ".tmp"
        assert not first.name.startswith(".")
        assert second.name.startswith(".two_")

    @pytest.mark.parametrize(
        "failing", ["write", "fsync", "replace", "fchmod", "interrupt"]
    )
    def test_a_failure_at_any_step_leaves_the_old_file_and_nothing_else(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        open_descriptors: Callable[[], list[int]],
        failing: str,
    ) -> None:
        target = tmp_path / "config.toml"
        target.write_bytes(b"old content")
        text = "new content"
        injected: BaseException = OSError(errno.EIO, "injected")
        expected: type[BaseException] = OSError
        if failing == "write":
            text = "lone surrogate \ud800"  # cannot be encoded as UTF-8
            expected = UnicodeEncodeError
        elif failing == "fsync":
            monkeypatch.setattr(os, "fsync", raising(injected))
        elif failing == "replace":
            monkeypatch.setattr(os, "replace", raising(injected))
        elif failing == "fchmod" and hasattr(os, "fchmod"):
            monkeypatch.setattr(os, "fchmod", raising(injected))
        elif failing == "interrupt":
            injected = KeyboardInterrupt()
            expected = KeyboardInterrupt
            monkeypatch.setattr(os, "fsync", raising(injected))
        else:
            pytest.skip("this platform has no os.fchmod")

        with pytest.raises(expected) as raised:
            atomic_write_text(target, text, keep_existing_mode=True)

        if failing != "write":
            assert raised.value is injected, "the error must reach the caller unchanged"
        assert target.read_bytes() == b"old content"
        assert names_in(tmp_path) == ["config.toml"]
        assert open_descriptors() == []

    def test_a_failing_cleanup_does_not_hide_the_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        target = tmp_path / "config.toml"
        target.write_bytes(b"old")
        injected = OSError(errno.EIO, "injected")
        real_unlink = os.unlink

        with monkeypatch.context() as patched:
            patched.setattr(os, "fsync", raising(injected))
            patched.setattr(
                os, "unlink", raising(OSError(errno.EACCES, "cannot remove"))
            )
            with pytest.raises(OSError) as raised:
                atomic_write_text(target, "new")

        assert raised.value is injected
        assert target.read_bytes() == b"old"
        for leftover in tmp_path.iterdir():  # the one file the failing cleanup kept
            if leftover != target:
                real_unlink(leftover)

    def test_a_missing_directory_is_the_callers_to_create(
        self, tmp_path: Path, open_descriptors: Callable[[], list[int]]
    ) -> None:
        with pytest.raises(FileNotFoundError):
            atomic_write_text(tmp_path / "missing" / "config.toml", "x")

        assert names_in(tmp_path) == []
        assert open_descriptors() == []

    def test_str_path_and_a_bare_file_name_all_work(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        atomic_write_text(str(tmp_path / "a.txt"), "1")
        atomic_write_text(tmp_path / "b.txt", "2")
        monkeypatch.chdir(tmp_path)
        atomic_write_text("c.txt", "3")

        assert names_in(tmp_path) == ["a.txt", "b.txt", "c.txt"]
        assert [
            (tmp_path / name).read_text(encoding="utf-8")
            for name in ("a.txt", "b.txt", "c.txt")
        ] == ["1", "2", "3"]

    @posix_only
    @pytest.mark.parametrize(
        "text",
        ["", "żółć — 配置 🙂", "a\nb\r\nc\n", "x" * 1_000_000],
        ids=["empty", "non-ascii", "line-endings", "one-megabyte"],
    )
    def test_the_bytes_on_disk_are_the_text_in_utf8(
        self, tmp_path: Path, text: str
    ) -> None:
        atomic_write_text(tmp_path / "out.txt", text)

        assert (tmp_path / "out.txt").read_bytes() == text.encode("utf-8")

    @posix_only
    def test_the_encoding_does_not_depend_on_the_locale(self, tmp_path: Path) -> None:
        # Windows (cp1252 / gbk) and a bare C locale both default to a narrow encoding.
        target = tmp_path / "out.txt"
        script = (
            "import sys; from ai_intervention_agent.config_utils import atomic_write_text; "
            "atomic_write_text(sys.argv[1], '配置 — żółć')"
        )
        environment = {
            **os.environ,
            "LC_ALL": "C",
            "LANG": "C",
            "PYTHONUTF8": "0",
            "PYTHONCOERCECLOCALE": "0",
        }
        environment.pop("PYTHONIOENCODING", None)

        completed = subprocess.run(
            [sys.executable, "-c", script, str(target)],
            env=environment,
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )

        assert completed.returncode == 0, completed.stderr
        assert target.read_bytes() == "配置 — żółć".encode()


# ---------------------------------------------------------------------------
# 2. the helper: the mode of the file
# ---------------------------------------------------------------------------
@posix_only
class TestTheMode:
    def test_a_new_file_is_owner_only_whatever_the_umask(self, tmp_path: Path) -> None:
        with umask(0o000):
            atomic_write_text(tmp_path / "plain", "x")
            atomic_write_text(tmp_path / "kept", "x", keep_existing_mode=True)

        assert mode_of(tmp_path / "plain") == 0o600
        assert mode_of(tmp_path / "kept") == 0o600

    @pytest.mark.parametrize("existing", [0o400, 0o600, 0o640, 0o644, 0o664], ids=oct)
    def test_keep_existing_mode_keeps_the_mode_of_the_file_it_replaces(
        self, tmp_path: Path, existing: int
    ) -> None:
        target = tmp_path / "config.toml"
        target.write_text("old", encoding="utf-8")
        target.chmod(existing)

        atomic_write_text(target, "new", keep_existing_mode=True)

        assert target.read_text(encoding="utf-8") == "new"
        assert mode_of(target) == existing

    def test_without_it_the_new_file_is_owner_only(self, tmp_path: Path) -> None:
        target = tmp_path / "tasks.json"
        target.write_text("old", encoding="utf-8")
        target.chmod(0o644)

        atomic_write_text(target, "new")

        assert mode_of(target) == 0o600

    def test_a_platform_without_fchmod_still_writes(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        target = tmp_path / "config.toml"
        target.write_text("old", encoding="utf-8")
        target.chmod(0o644)
        monkeypatch.delattr(os, "fchmod")

        atomic_write_text(target, "new", keep_existing_mode=True)

        assert target.read_text(encoding="utf-8") == "new"
        assert names_in(tmp_path) == ["config.toml"]


# ---------------------------------------------------------------------------
# 3. the three divergences, at their call sites (real objects, real files)
# ---------------------------------------------------------------------------
@posix_only
class TestConfigSave:
    @pytest.mark.parametrize("existing", [0o600, 0o640, 0o644], ids=oct)
    def test_a_save_keeps_the_mode_of_the_file_it_replaces(
        self,
        tmp_path: Path,
        make_manager: Callable[[Path], ConfigManager],
        existing: int,
    ) -> None:
        config = tmp_path / "config.toml"
        manager = make_manager(config)
        config.chmod(existing)

        manager.set("notification.sound_volume", 33, save=True)
        manager.force_save()

        assert "sound_volume = 33" in config.read_text(encoding="utf-8")
        assert mode_of(config) == existing


@posix_only
class TestNetworkSecuritySave:
    def test_a_refused_fchmod_does_not_leak_a_descriptor(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        make_manager: Callable[[Path], ConfigManager],
        open_descriptors: Callable[[], list[int]],
    ) -> None:
        config = tmp_path / "config.toml"
        manager = make_manager(config)
        config.chmod(0o644)

        with monkeypatch.context() as patched:
            patched.setattr(os, "fchmod", raising(OSError(errno.EPERM, "refused")))
            with pytest.raises(RuntimeError, match="写入配置文件失败"):
                manager.update_network_security_config({"api_token": TOKEN})

        assert open_descriptors() == []
        assert [name for name in names_in(tmp_path) if name.endswith(".tmp")] == []
        assert TOKEN not in config.read_text(encoding="utf-8")

    def test_a_save_keeps_the_mode_of_the_file_it_replaces(
        self, tmp_path: Path, make_manager: Callable[[Path], ConfigManager]
    ) -> None:
        config = tmp_path / "config.toml"
        manager = make_manager(config)
        config.chmod(0o640)

        manager.update_network_security_config({"api_token": TOKEN})

        assert TOKEN in config.read_text(encoding="utf-8")
        assert mode_of(config) == 0o640


@posix_only
class TestRestore:
    @pytest.mark.parametrize("existing", [0o600, 0o640, 0o644], ids=oct)
    def test_a_restore_keeps_the_mode_of_the_file_it_replaces(
        self,
        tmp_path: Path,
        make_manager: Callable[[Path], ConfigManager],
        existing: int,
    ) -> None:
        config = tmp_path / "config.toml"
        manager = make_manager(config)
        manager.set("notification.sound_volume", 33, save=True)
        manager.force_save()
        backup = manager.backup_config()
        manager.set("notification.sound_volume", 77, save=True)
        manager.force_save()
        config.chmod(existing)

        assert manager.restore_config(backup) is True

        assert manager.get("notification.sound_volume") == 33
        assert mode_of(config) == existing
        assert [name for name in names_in(tmp_path) if name.endswith(".tmp")] == []


class TestTaskQueueFile:
    @staticmethod
    def make_queue(path: Path) -> TaskQueue:
        queue = TaskQueue(persist_path=str(path))
        assert queue.add_task("t1", "prompt one")
        return queue

    def test_an_interrupt_between_the_temporary_file_and_the_rename_leaves_no_file(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        open_descriptors: Callable[[], list[int]],
    ) -> None:
        persist = tmp_path / "tasks.json"
        queue = self.make_queue(persist)
        try:
            before = persist.read_bytes()

            with monkeypatch.context() as patched:
                patched.setattr(os, "fsync", raising(KeyboardInterrupt()))
                with pytest.raises(KeyboardInterrupt):
                    queue._persist()

            assert persist.read_bytes() == before
            assert names_in(tmp_path) == ["tasks.json"]
            assert open_descriptors() == []
        finally:
            queue.stop_cleanup()

    def test_the_temporary_file_keeps_its_hidden_prefix(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        persist = tmp_path / "tasks.json"
        queue = self.make_queue(persist)
        try:
            seen: list[Path] = []
            real_replace = os.replace

            def replace(src: Any, dst: Any) -> None:
                if Path(dst) == persist:
                    seen.append(Path(src))
                real_replace(src, dst)

            monkeypatch.setattr(os, "replace", replace)

            queue._persist()

            assert [
                (path.parent, path.name.startswith(".tasks_")) for path in seen
            ] == [(tmp_path, True)]
        finally:
            queue.stop_cleanup()

    @posix_only
    def test_the_task_file_is_always_owner_only(self, tmp_path: Path) -> None:
        # Unlike a config file, tasks.json is state the agent owns: it holds the prompts of
        # the open tasks and is rewritten as 0600 whatever it was before.
        persist = tmp_path / "tasks.json"
        queue = self.make_queue(persist)
        try:
            persist.chmod(0o644)

            assert queue.add_task("t2", "prompt two")

            assert mode_of(persist) == 0o600
        finally:
            queue.stop_cleanup()


# ---------------------------------------------------------------------------
# 4. structure: the call sites call the helper and hold no copy of the sequence
# ---------------------------------------------------------------------------
CALL_SITES = [
    ("config_manager.py", "ConfigManager", "_save_config_immediate"),
    ("config_modules/io_operations.py", "IOOperationsMixin", "restore_config"),
    (
        "config_modules/network_security.py",
        "NetworkSecurityMixin",
        "_atomic_write_config",
    ),
    ("task_queue.py", "TaskQueue", "_persist"),
]
THE_SEQUENCE = {
    "tempfile.mkstemp",
    "os.fdopen",
    "os.fsync",
    "os.replace",
    "os.fchmod",
    "os.unlink",
    "os.stat",
}


def called_names(relative: str, class_name: str, method: str) -> list[str]:
    tree = ast.parse((SRC / relative).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            for item in node.body:
                if isinstance(item, ast.FunctionDef) and item.name == method:
                    return [
                        ast.unparse(call.func)
                        for call in ast.walk(item)
                        if isinstance(call, ast.Call)
                    ]
    raise AssertionError(f"{class_name}.{method} not found in {relative}")


class TestOneHome:
    @pytest.mark.parametrize(
        ("relative", "class_name", "method"),
        CALL_SITES,
        ids=[f"{cls}.{name}" for _, cls, name in CALL_SITES],
    )
    def test_the_call_site_calls_the_helper_and_holds_no_copy_of_the_sequence(
        self, relative: str, class_name: str, method: str
    ) -> None:
        calls = called_names(relative, class_name, method)

        assert calls.count("atomic_write_text") == 1
        assert THE_SEQUENCE.isdisjoint(calls), sorted(THE_SEQUENCE.intersection(calls))

    def test_the_four_call_sites_are_the_only_callers(self) -> None:
        callers: list[str] = []
        for path in sorted(SRC.rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                if any(
                    isinstance(call, ast.Call)
                    and ast.unparse(call.func) == "atomic_write_text"
                    for call in ast.walk(node)
                ):
                    callers.append(f"{path.relative_to(SRC).as_posix()}::{node.name}")

        assert sorted(callers) == sorted(
            f"{relative}::{method}" for relative, _, method in CALL_SITES
        )
