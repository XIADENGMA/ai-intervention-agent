"""R827 — 可能装着密钥的文件，只有它的主人读得到。

事故现场
--------
``config.toml`` 里放着 ``notification.bark_device_key``（拿到它的人可以往用户手机推任意通知）和
``network_security.api_token``（局域网访问的钥匙）。第一次运行时，文件是这样建出来的：

    shutil.copyfile(toml_template, self.config_file)      # 模式 = 0666 & ~umask

umask 是 022（几乎所有 Linux 发行版的默认值）时文件是 0644：同一台机器上的任何账号都能读。
umask 是 0（容器、某些 CI、``systemd`` 的 ``UMask=0000``）时文件是 0666：任何账号还能改——比如把
``network_security.allowed_networks`` 改成 ``0.0.0.0/0``。

之后保存配置时走的是 ``tempfile.mkstemp``（0600）+ ``os.fchmod(fd, 原文件的模式)``：那一步是对的——
用户自己放宽的权限（组共享）不该被悄悄收回——但它让 0644 一直是 0644：用户在设置页填进去的密钥
落进一个所有人可读的文件。

同类的还有三处：``backup_config()`` 导出的备份 JSON（``include_network_security=True``，里面有
``api_token``）、JSON→TOML 迁移写出来的新文件、``notification_inflight.json``（还没送达的通知
的标题和正文）。它们都是 ``open(path, "w")`` / ``Path.write_text``，模式取决于 umask。

macOS 上这个问题碰不到——``~/Library`` 是 0700，别的账号走不进去——所以没人发现；
Linux 上 ``~/.config`` 往往是 0755，家目录是 0755（Debian / Ubuntu 21.04 之前）或 0750。

修法
----
新建这几类文件时，模式直接是 0600（``config_utils.write_text_owner_only`` /
``restrict_to_owner``）。**已经存在的文件不动**——不替用户收回，也不替用户放宽。

本文件不 patch 任何一个写文件的函数：真实的 ``ConfigManager`` / ``NotificationManager``，
真的 ``stat`` 磁盘上的文件。
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import stat
import sys
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import IO, Any

import pytest

from ai_intervention_agent import config_manager as config_manager_module
from ai_intervention_agent import config_utils
from ai_intervention_agent import notification_manager as nm
from ai_intervention_agent.config_manager import ConfigManager
from ai_intervention_agent.notification_manager import (
    _INFLIGHT_FILE_NAME,
    NotificationTrigger,
    NotificationType,
)

pytestmark = pytest.mark.skipif(
    sys.platform == "win32", reason="POSIX permission bits (Windows has ACLs)"
)

TEMPLATE = Path(__file__).resolve().parents[1] / "config.toml.default"
SECRET = "DEVKEY_s3cr3t_ABCDEF1234567890"
TOKEN = "tok_" + "0123456789abcdef" * 2


def mode_of(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


@contextlib.contextmanager
def umask(value: int) -> Iterator[None]:
    previous = os.umask(value)
    try:
        yield
    finally:
        os.umask(previous)


@pytest.fixture(autouse=True)
def _common_umask() -> Iterator[None]:
    """022：几乎所有 Linux 发行版的默认值——旧代码在这个 umask 下建出 0644。"""
    with umask(0o022):
        yield


@pytest.fixture
def quiet_config_logs(caplog: pytest.LogCaptureFixture) -> None:
    """有几个测试故意走降级 / 失败路径，配置模块会如实记 WARNING / ERROR；本文件只关心文件模式。

    要排在 ``make_manager`` 前面请求：fixture 按相反顺序收尾，这样 ``make_manager`` 收尾时
    （``shutdown`` 会再试着保存）日志级别还没恢复。"""
    caplog.set_level(logging.CRITICAL, logger="ai_intervention_agent.config_manager")


@pytest.fixture
def make_manager() -> Iterator[object]:
    created: list[ConfigManager] = []

    def make(path: Path | None = None) -> ConfigManager:
        # 不给路径 = 生产里的"环境变量 / 标准位置"查找（只有这条路会发现并迁移旧的 .jsonc）
        manager = ConfigManager(str(path)) if path is not None else ConfigManager()
        created.append(manager)
        return manager

    try:
        yield make
    finally:
        for manager in created:
            manager.shutdown()


# ---------------------------------------------------------------------------
# 1. 第一次运行建出来的默认配置文件
# ---------------------------------------------------------------------------
class TestTheFirstRunConfigFile:
    @pytest.mark.parametrize("mask", [0o000, 0o022, 0o077])
    def test_a_file_copied_from_the_template_is_owner_only(
        self, tmp_path: Path, make_manager, mask: int
    ) -> None:
        created = tmp_path / "config.toml"
        with umask(mask):
            make_manager(created)

        assert created.read_text(encoding="utf-8") == TEMPLATE.read_text("utf-8")
        assert mode_of(created) == 0o600

    @pytest.mark.parametrize("mask", [0o000, 0o022])
    def test_a_file_written_without_a_template_is_owner_only(
        self,
        tmp_path: Path,
        quiet_config_logs,
        make_manager,
        monkeypatch: pytest.MonkeyPatch,
        mask: int,
    ) -> None:
        monkeypatch.setattr(
            config_manager_module, "find_default_config_template", lambda: None
        )
        created = tmp_path / "config.toml"
        with umask(mask):
            make_manager(created)

        assert created.stat().st_size > 0
        assert mode_of(created) == 0o600

    def test_the_json_fallback_file_is_owner_only(
        self,
        tmp_path: Path,
        quiet_config_logs,
        make_manager,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        def refuse(*args: object, **kwargs: object) -> None:
            raise OSError("the template cannot be copied")

        monkeypatch.setattr(config_manager_module.shutil, "copyfile", refuse)
        created = tmp_path / "config.toml"
        with umask(0o000):
            make_manager(created)

        assert created.stat().st_size > 0
        assert mode_of(created) == 0o600

    def test_a_read_only_packaged_template_still_gives_a_file_its_owner_can_edit(
        self, tmp_path: Path, make_manager, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # R752 的约定：``copyfile`` 不带模式，Nix store / 只读卷里的模板（0444）拷出来仍可写。
        shipped = tmp_path / "shipped" / "config.toml.default"
        shipped.parent.mkdir()
        shipped.write_text(TEMPLATE.read_text("utf-8"), encoding="utf-8")
        shipped.chmod(0o444)
        monkeypatch.setattr(
            config_manager_module, "find_default_config_template", lambda: shipped
        )
        created = tmp_path / "config.toml"

        make_manager(created)

        assert mode_of(created) == 0o600
        created.write_text("# the owner can still edit it\n", encoding="utf-8")

    def test_a_filesystem_that_refuses_chmod_never_stops_the_first_run(
        self, tmp_path: Path, make_manager, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # FAT / 某些网络盘上 chmod 会失败：文件照样要建出来，只是没法收紧
        def refuse(*args: object, **kwargs: object) -> None:
            raise PermissionError(1, "Operation not permitted")

        monkeypatch.setattr(config_utils.os, "chmod", refuse)
        created = tmp_path / "config.toml"

        manager = make_manager(created)

        assert created.read_text(encoding="utf-8") == TEMPLATE.read_text("utf-8")
        assert manager.get("notification.sound_volume") == 80


# ---------------------------------------------------------------------------
# 2. 之后存进去的密钥
# ---------------------------------------------------------------------------
class TestASecretSavedLaterStaysPrivate:
    def test_a_bark_key_saved_through_the_manager(
        self, tmp_path: Path, make_manager
    ) -> None:
        created = tmp_path / "config.toml"
        manager = make_manager(created)

        manager.set("notification.bark_device_key", SECRET, save=True)
        manager.force_save()  # ``set`` 只是排了一个 3 秒后的保存

        assert SECRET in created.read_text(encoding="utf-8")
        assert mode_of(created) == 0o600

    def test_an_api_token_saved_through_network_security(
        self, tmp_path: Path, make_manager
    ) -> None:
        created = tmp_path / "config.toml"
        manager = make_manager(created)

        manager.update_network_security_config({"api_token": TOKEN})

        assert TOKEN in created.read_text(encoding="utf-8")
        assert mode_of(created) == 0o600


# ---------------------------------------------------------------------------
# 3. 已经存在的文件：不动
# ---------------------------------------------------------------------------
class TestAFileThatAlreadyExistsIsLeftAlone:
    @pytest.mark.parametrize("existing", [0o644, 0o640])
    def test_saving_a_secret_keeps_the_mode_the_user_or_an_older_version_left(
        self, tmp_path: Path, make_manager, existing: int
    ) -> None:
        path = tmp_path / "config.toml"
        path.write_text(TEMPLATE.read_text("utf-8"), encoding="utf-8")
        path.chmod(existing)
        manager = make_manager(path)

        manager.set("notification.bark_device_key", SECRET, save=True)
        manager.force_save()
        manager.update_network_security_config({"api_token": TOKEN})

        text = path.read_text(encoding="utf-8")
        assert SECRET in text and TOKEN in text
        assert mode_of(path) == existing

    def test_just_loading_it_changes_nothing(
        self, tmp_path: Path, make_manager
    ) -> None:
        path = tmp_path / "config.toml"
        path.write_text(TEMPLATE.read_text("utf-8"), encoding="utf-8")
        path.chmod(0o664)

        make_manager(path)

        assert mode_of(path) == 0o664


# ---------------------------------------------------------------------------
# 4. JSONC / JSON → TOML 迁移写出来的新文件
# ---------------------------------------------------------------------------
class TestTheMigratedFile:
    @pytest.mark.parametrize("name", ["config.jsonc", "config.json"])
    @pytest.mark.parametrize("mask", [0o000, 0o022])
    def test_the_toml_written_by_the_migration_is_owner_only(
        self,
        tmp_path: Path,
        make_manager,
        monkeypatch: pytest.MonkeyPatch,
        name: str,
        mask: int,
    ) -> None:
        old = tmp_path / name
        old.write_text(
            json.dumps({"notification": {"bark_device_key": SECRET}}),
            encoding="utf-8",
        )
        old.chmod(0o644)
        monkeypatch.setenv("AI_INTERVENTION_AGENT_CONFIG_FILE", str(old))

        with umask(mask):
            manager = make_manager()

        migrated = tmp_path / "config.toml"
        assert manager.config_file == migrated
        assert SECRET in migrated.read_text(encoding="utf-8")
        assert mode_of(migrated) == 0o600
        assert mode_of(tmp_path / (name + ".bak")) == 0o644  # 改名而已，旧文件不动


# ---------------------------------------------------------------------------
# 5. backup_config()：JSON 里有 api_token
# ---------------------------------------------------------------------------
class TestTheBackup:
    def test_a_new_backup_with_the_api_token_is_owner_only(
        self, tmp_path: Path, make_manager
    ) -> None:
        manager = make_manager(tmp_path / "config.toml")
        manager.update_network_security_config({"api_token": TOKEN})

        backup = Path(manager.backup_config())

        assert TOKEN in backup.read_text(encoding="utf-8")
        assert mode_of(backup) == 0o600

    def test_it_is_owner_only_under_umask_zero(
        self, tmp_path: Path, make_manager
    ) -> None:
        manager = make_manager(tmp_path / "config.toml")
        target = tmp_path / "elsewhere" / "backup.json"
        target.parent.mkdir()

        with umask(0o000):
            backup = Path(manager.backup_config(str(target)))

        assert backup == target
        assert mode_of(backup) == 0o600

    def test_an_older_world_readable_backup_is_tightened_when_it_is_overwritten(
        self, tmp_path: Path, make_manager
    ) -> None:
        # 备份是代理自己生成的、每次都会写进当前的密钥，所以这里是"覆盖写 = 重新收紧"
        manager = make_manager(tmp_path / "config.toml")
        manager.update_network_security_config({"api_token": TOKEN})
        old_backup = tmp_path / "config.toml.backup"
        old_backup.write_text("{}", encoding="utf-8")
        old_backup.chmod(0o644)

        backup = Path(manager.backup_config())

        assert backup == old_backup
        assert TOKEN in backup.read_text(encoding="utf-8")
        assert mode_of(backup) == 0o600

    def test_the_backup_still_restores(self, tmp_path: Path, make_manager) -> None:
        manager = make_manager(tmp_path / "config.toml")
        manager.set("notification.sound_volume", 33, save=True)
        manager.force_save()
        backup = manager.backup_config()
        manager.set("notification.sound_volume", 77, save=True)
        manager.force_save()

        assert manager.restore_config(backup) is True

        assert manager.get("notification.sound_volume") == 33


# ---------------------------------------------------------------------------
# 6. notification_inflight.json：还没送达的通知的标题和正文
# ---------------------------------------------------------------------------
class Blocking:
    def __init__(self) -> None:
        self.entered = threading.Event()
        self.release = threading.Event()

    def send(self, event: object) -> bool:
        self.entered.set()
        self.release.wait(30)
        return True


@pytest.fixture
def config_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    manager = ConfigManager(str(tmp_path / "config.toml"))
    monkeypatch.setattr(nm, "get_config", lambda: manager)
    try:
        yield tmp_path
    finally:
        manager.shutdown()


@contextlib.contextmanager
def in_flight(config_dir: Path) -> Iterator[Path]:
    """一条通知停在渠道里没送完：它的 in-flight 文件就在磁盘上。"""
    manager = nm.notification_manager
    manager.config.enabled = True
    channel = Blocking()
    manager.register_provider(NotificationType.WEB, channel)
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
    path = config_dir / _INFLIGHT_FILE_NAME
    try:
        assert channel.entered.wait(10), "the provider was never asked to send"
        yield path
    finally:
        channel.release.set()
        sender.join(10)
        deadline = time.monotonic() + 10
        while path.exists() and time.monotonic() < deadline:
            time.sleep(0.02)


class TestTheInflightFile:
    @pytest.mark.parametrize("mask", [0o000, 0o022])
    def test_the_file_with_the_notification_text_is_owner_only(
        self, config_dir: Path, mask: int
    ) -> None:
        with umask(mask), in_flight(config_dir) as path:
            data = json.loads(path.read_text(encoding="utf-8"))
            assert data["events"][0]["message"] == "the channel has not answered yet"
            assert mode_of(path) == 0o600

    def test_no_temporary_file_is_left_behind(self, config_dir: Path) -> None:
        with in_flight(config_dir) as path:
            assert path.exists()
            assert not path.with_suffix(path.suffix + ".tmp").exists()

    def test_a_world_readable_file_from_an_older_version_is_replaced_by_a_private_one(
        self, config_dir: Path
    ) -> None:
        stale = config_dir / _INFLIGHT_FILE_NAME
        stale.write_text("{}", encoding="utf-8")
        stale.chmod(0o644)

        with in_flight(config_dir) as path:
            assert path == stale
            assert mode_of(path) == 0o600

    def test_a_leftover_temporary_file_from_an_older_version_does_not_leak_its_mode(
        self, config_dir: Path
    ) -> None:
        # 旧版本在 replace 之前被杀，留下一个 0644 的 .tmp；新版本复用它写下一份，
        # 然后 replace 成正式文件——模式得在这一步之前收紧，而不是跟着旧 inode 走
        leftover = config_dir / (_INFLIGHT_FILE_NAME + ".tmp")
        leftover.write_text("{}", encoding="utf-8")
        leftover.chmod(0o644)

        with in_flight(config_dir) as path:
            assert mode_of(path) == 0o600
            assert not leftover.exists()


# ---------------------------------------------------------------------------
# 7. 两个小工具本身
# ---------------------------------------------------------------------------
class TestTheHelpers:
    def test_a_new_file_is_created_owner_only_whatever_the_umask(
        self, tmp_path: Path
    ) -> None:
        target = tmp_path / "new.json"
        with umask(0o000):
            config_utils.write_text_owner_only(target, "żółć — 配置\n")

        assert target.read_text(encoding="utf-8") == "żółć — 配置\n"
        assert mode_of(target) == 0o600

    def test_an_existing_file_is_rewritten_in_full_and_keeps_its_mode_by_default(
        self, tmp_path: Path
    ) -> None:
        target = tmp_path / "old.json"
        target.write_text("x" * 500, encoding="utf-8")
        target.chmod(0o640)

        config_utils.write_text_owner_only(target, "short")

        assert target.read_text(encoding="utf-8") == "short"
        assert mode_of(target) == 0o640

    def test_tighten_existing_narrows_an_existing_file(self, tmp_path: Path) -> None:
        target = tmp_path / "old.json"
        target.write_text("x", encoding="utf-8")
        target.chmod(0o666)

        config_utils.write_text_owner_only(target, "y", tighten_existing=True)

        assert mode_of(target) == 0o600

    def test_an_existing_file_is_tightened_before_the_first_byte_is_written(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # 写完再 chmod 的话，新内容（备份里的 api_token）会先躺在一个 0644 的文件里
        target = tmp_path / "old.json"
        target.write_text("old", encoding="utf-8")
        target.chmod(0o644)
        seen: dict[str, int] = {}
        real = config_utils.os.fdopen

        def spy(fd: int, *args: Any, **kwargs: Any) -> IO[Any]:
            seen["mode"] = stat.S_IMODE(os.fstat(fd).st_mode)
            return real(fd, *args, **kwargs)

        monkeypatch.setattr(config_utils.os, "fdopen", spy)

        config_utils.write_text_owner_only(target, "SECRET", tighten_existing=True)

        assert seen["mode"] == 0o600, "bytes would have been written into a wider file"
        assert target.read_text(encoding="utf-8") == "SECRET"

    def test_when_fchmod_fails_the_write_still_happens_and_the_path_is_tightened(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        target = tmp_path / "old.json"
        target.write_text("old", encoding="utf-8")
        target.chmod(0o644)

        def refuse(*args: object, **kwargs: object) -> None:
            raise PermissionError(1, "Operation not permitted")

        monkeypatch.setattr(config_utils.os, "fchmod", refuse)

        config_utils.write_text_owner_only(target, "SECRET", tighten_existing=True)

        assert target.read_text(encoding="utf-8") == "SECRET"
        assert mode_of(target) == 0o600

    def test_without_fchmod_the_path_is_tightened_after_the_write(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Windows 没有 os.fchmod
        target = tmp_path / "old.json"
        target.write_text("old", encoding="utf-8")
        target.chmod(0o644)
        monkeypatch.delattr(config_utils.os, "fchmod")

        config_utils.write_text_owner_only(target, "SECRET", tighten_existing=True)

        assert target.read_text(encoding="utf-8") == "SECRET"
        assert mode_of(target) == 0o600

    def test_restrict_to_owner_narrows_and_never_raises(self, tmp_path: Path) -> None:
        target = tmp_path / "f"
        target.write_text("x", encoding="utf-8")
        target.chmod(0o666)

        config_utils.restrict_to_owner(target)
        config_utils.restrict_to_owner(tmp_path / "does-not-exist")

        assert mode_of(target) == 0o600
