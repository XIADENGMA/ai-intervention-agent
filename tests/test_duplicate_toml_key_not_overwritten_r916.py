"""R916：同一个键写了两次的 config.toml，也不会被默认配置覆盖。

现象（旧代码实测）
==================

R783 让 ``_load_config`` 在磁盘上的文件内容有问题时置位 ``_on_disk_config_invalid``，置位期间所有
自动写入都不动文件。置位的条件是异常 ``isinstance(e, ValueError | ConfigValidationError)``。
tomlkit 的解析错误几乎都是 ``ParseError``（``ValueError`` 的子类），只有**重复的键**例外：
抛出的 ``KeyAlreadyPresent`` 只继承 ``TOMLKitError``，不是 ``ValueError``。三种写法都会走到它::

    [web_ui]                      # 同一张表里同一个键写了两次（复制粘贴一行、忘了改名字）
    port = 18792
    port = 18793

    [web_ui]                      # ``[web_ui.port]`` 压在已有的值 ``port`` 上
    port = 18792
    [web_ui.port]
    x = 1

    extra = {a = 1, a = 2}        # 内联表里的键重复

这样的文件，``_load_config`` 记一条 ERROR、内存里用默认配置（热重载时沿用上一份），却不置位，
R783 的保护不生效。三种写法 × 五条写入路径，用户的文件原来是 69 / 77 / 79 字节：

==============================  ========================
路径                             旧代码之后文件变成
==============================  ========================
退出时的 ``force_save``          1,050 字节的默认配置
改了一个值之后的 ``force_save``  1,050 字节的默认配置
``set_network_security_config``  **0 字节**
服务运行中文件被改成这样         1,051 字节（上一份内存配置）
一个只启动、再退出的进程         1,050 字节的默认配置
==============================  ========================

十五格全部被覆盖。最后一行最说明问题：进程什么设置都没碰，只是退出时 ``atexit`` →
``force_save``，用户的配置（端口、``bind_interface`` 和访问控制、Bark 的 ``device_key``……）就被
默认值换掉了，磁盘上只留一条没人看的 ERROR。这和 R783 修掉的是同一类损失，只是漏了一种写法。

修复
====

``_load_config`` 把 ``TOMLKitError``（tomlkit 自己的错误基类）也算作文件内容的错误。认基类而不是
``KeyAlreadyPresent``：要保护的是“tomlkit 读不懂这个文件”这一整类，而不是某一个子类。

测试矩阵
========

A. 三种写法的前提：tomlkit 的确因此抛 ``KeyAlreadyPresent``（``TOMLKitError`` 的子类）；加载之后置位；
B. 三种写法 × 五条写入路径（``force_save``、``shutdown``、改了值之后的 ``force_save``、
   ``set_network_security_config``、真实进程退出时的 ``atexit``）：文件字节不变，改的值在内存里生效；
C. 服务运行中，文件被改成这样（复制粘贴多出一行）：用户那一版不被盖掉，内存里仍是上一份配置；
   修好之后写入恢复，保存时写进去的是修好之后的文件；
D. 对照：不同的表里有同名的键、数组表（``[[x]]``）重复出现，这些都是合法的 TOML，加载、保存照常；
E. 分类：任意 ``TOMLKitError`` 都算内容错误；读文件时的 ``OSError`` 仍不算（R783 的约定）；
F. ``network_security`` 里的三种写法，``get_network_security_config`` 都只放行本机（R915）。

共 44 个测试，旧代码上 26 个失败：A 里“加载之后置位”、B 的全部、C 里“用户那一版不被盖掉”、E 里两个
tomlkit 错误。其余 18 个是对照，新旧代码上都通过：前提、日志、修好之后写入恢复、删掉重建、合法的
TOML、``OSError``，以及 F（R915 已经管住了 ``network_security`` 的读取）。7 个单点变异体全部被抓到。
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import tomllib
from pathlib import Path
from unittest.mock import patch

import pytest
import tomlkit
from tomlkit.exceptions import KeyAlreadyPresent, TOMLKitError

from ai_intervention_agent.config_manager import ConfigManager

GOOD = b"[web_ui]\nport = 18792\n\n[notification]\nsound_volume = 80\n"

FORMS = {
    "a-key-twice-in-one-table": (
        b"[web_ui]\nport = 18792\nport = 18793\n\n[notification]\nsound_volume = 80\n"
    ),
    "a-table-on-top-of-a-value": (
        b"[web_ui]\nport = 18792\n\n[web_ui.port]\nx = 1\n\n"
        b"[notification]\nsound_volume = 80\n"
    ),
    "a-key-twice-in-an-inline-table": (
        b"[web_ui]\nport = 18792\n\n[notification]\nsound_volume = 80\n"
        b"extra = {a = 1, a = 2}\n"
    ),
}

#: ``network_security`` 里的同样三种写法
NETWORK_SECURITY_FORMS = {
    "a-key-twice-in-one-table": (
        b'[network_security]\nbind_interface = "127.0.0.1"\nbind_interface = "0.0.0.0"\n'
    ),
    "a-table-on-top-of-a-value": (
        b'[network_security]\nbind_interface = "127.0.0.1"\n\n'
        b"[network_security.bind_interface]\nx = 1\n"
    ),
    "a-key-twice-in-an-inline-table": (
        b'[network_security]\nbind_interface = "127.0.0.1"\nextra = {a = 1, a = 2}\n'
    ),
}

LOOPBACK = ["127.0.0.0/8", "::1/128"]


def volume(path: Path) -> int:
    return tomllib.loads(path.read_text(encoding="utf-8"))["notification"][
        "sound_volume"
    ]


@pytest.fixture(params=sorted(FORMS))
def form(request: pytest.FixtureRequest) -> str:
    return str(request.param)


@pytest.fixture
def broken_file(form: str, tmp_path: Path) -> Path:
    path = tmp_path / "config.toml"
    path.write_bytes(FORMS[form])
    return path


# ---- A. 前提 --------------------------------------------------------------------------------------


class TestThePremise:
    def test_tomlkit_refuses_each_form_with_its_own_error_family(
        self, form: str
    ) -> None:
        with pytest.raises(TOMLKitError) as caught:
            tomlkit.parse(FORMS[form].decode("utf-8"))

        # tomlkit 的解析错误里只有重复的键不是 ValueError，所以 R783 的分类漏了它
        assert isinstance(caught.value, KeyAlreadyPresent)

    def test_the_file_is_marked_as_unusable_after_it_is_loaded(
        self, broken_file: Path
    ) -> None:
        manager = ConfigManager(str(broken_file))

        assert manager._on_disk_config_invalid is True

    def test_the_load_failure_is_reported(
        self, broken_file: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        with caplog.at_level(logging.ERROR, logger="ai_intervention_agent"):
            ConfigManager(str(broken_file))

        failed = [r for r in caplog.records if "加载配置文件失败" in r.getMessage()]
        assert failed


# ---- B. 五条写入路径 ------------------------------------------------------------------------------


class TestAFileWithADuplicateKeyIsLeftAlone:
    def test_force_save(self, broken_file: Path) -> None:
        manager = ConfigManager(str(broken_file))
        before = broken_file.read_bytes()

        manager.force_save()

        assert broken_file.read_bytes() == before

    def test_shutdown(self, broken_file: Path) -> None:
        manager = ConfigManager(str(broken_file))
        before = broken_file.read_bytes()

        manager.shutdown()

        assert broken_file.read_bytes() == before

    def test_a_changed_value_is_used_in_memory_but_not_written(
        self, broken_file: Path
    ) -> None:
        manager = ConfigManager(str(broken_file))
        before = broken_file.read_bytes()

        manager.update_section("notification", {"sound_volume": 55})
        manager.force_save()

        assert manager.get_section("notification")["sound_volume"] == 55
        assert broken_file.read_bytes() == before

    def test_the_network_security_save_refuses_instead_of_blanking_the_file(
        self, broken_file: Path
    ) -> None:
        manager = ConfigManager(str(broken_file))
        before = broken_file.read_bytes()
        current = manager.get_network_security_config()

        with pytest.raises(RuntimeError):
            manager.set_network_security_config(current)

        assert broken_file.read_bytes() == before

    def test_the_skip_is_explained_in_the_log(
        self, broken_file: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        manager = ConfigManager(str(broken_file))
        caplog.clear()

        with caplog.at_level(logging.WARNING, logger="ai_intervention_agent"):
            manager.force_save()

        skipped = [r for r in caplog.records if "已跳过写入" in r.getMessage()]
        assert skipped
        assert str(broken_file) in skipped[0].getMessage()

    def test_a_process_that_only_starts_and_exits(self, broken_file: Path) -> None:
        before = broken_file.read_bytes()
        env = dict(os.environ, AI_INTERVENTION_AGENT_CONFIG_FILE=str(broken_file))

        subprocess.run(
            [
                sys.executable,
                "-c",
                "from ai_intervention_agent.config_manager import config_manager",
            ],
            env=env,
            cwd=broken_file.parent,
            check=True,
            timeout=60,
        )

        assert broken_file.read_bytes() == before


# ---- C. 服务运行中 --------------------------------------------------------------------------------


class TestADuplicateAppearsWhileTheServiceRuns:
    def test_the_users_edit_is_not_overwritten_and_the_old_settings_stay(
        self, form: str, tmp_path: Path
    ) -> None:
        path = tmp_path / "config.toml"
        path.write_bytes(GOOD)
        manager = ConfigManager(str(path))
        path.write_bytes(FORMS[form])
        manager._load_config()

        manager.update_section("notification", {"sound_volume": 55})
        manager.force_save()

        assert path.read_bytes() == FORMS[form]
        # 热重载失败时沿用上一份内存配置；刚改的值在内存里生效
        assert manager.get_section("web_ui")["port"] == 18792
        assert manager.get_section("notification")["sound_volume"] == 55

    def test_saving_resumes_once_the_file_is_fixed(
        self, form: str, tmp_path: Path
    ) -> None:
        path = tmp_path / "config.toml"
        path.write_bytes(GOOD)
        manager = ConfigManager(str(path))
        path.write_bytes(FORMS[form])
        manager._load_config()
        fixed = GOOD.replace(b"18792", b"18800")
        path.write_bytes(fixed)
        manager._load_config()

        assert manager._on_disk_config_invalid is False
        manager.update_section("notification", {"sound_volume": 57})
        manager.force_save()

        saved = tomllib.loads(path.read_text(encoding="utf-8"))
        assert saved["notification"]["sound_volume"] == 57
        assert saved["web_ui"]["port"] == 18800

    def test_a_deleted_file_is_recreated_and_saved_again(
        self, broken_file: Path
    ) -> None:
        manager = ConfigManager(str(broken_file))
        broken_file.unlink()
        manager._load_config()
        assert broken_file.exists()

        manager.update_section("notification", {"sound_volume": 56})
        manager.force_save()

        assert volume(broken_file) == 56


# ---- D. 对照：合法的 TOML 不受影响 ----------------------------------------------------------------

LEGAL = {
    "the-same-key-name-in-different-tables": (
        b"[web_ui]\nport = 18792\n\n[notification]\nsound_volume = 80\nport = 1\n"
    ),
    "an-array-of-tables-repeated": (
        b"[web_ui]\nport = 18792\n\n[notification]\nsound_volume = 80\n\n"
        b'[[extra]]\nname = "a"\n\n[[extra]]\nname = "b"\n'
    ),
}


class TestLegalTomlIsStillUsedAndSaved:
    @pytest.mark.parametrize("name", sorted(LEGAL))
    def test_it_is_loaded_and_a_changed_value_is_written(
        self, name: str, tmp_path: Path
    ) -> None:
        path = tmp_path / "config.toml"
        path.write_bytes(LEGAL[name])
        manager = ConfigManager(str(path))

        assert manager._on_disk_config_invalid is False
        assert manager.get_section("web_ui")["port"] == 18792

        manager.update_section("notification", {"sound_volume": 58})
        manager.force_save()

        assert volume(path) == 58


# ---- E. 分类 --------------------------------------------------------------------------------------


class TestWhichErrorsMarkTheFileAsUnusable:
    @pytest.mark.parametrize(
        "error",
        [KeyAlreadyPresent("x"), TOMLKitError("tomlkit could not read it")],
        ids=["KeyAlreadyPresent", "TOMLKitError"],
    )
    def test_any_tomlkit_error_does_(self, error: Exception, tmp_path: Path) -> None:
        path = tmp_path / "config.toml"
        path.write_bytes(GOOD)
        manager = ConfigManager(str(path))

        with patch.object(manager, "_parse_config_content", side_effect=error):
            manager._load_config()

        assert manager._on_disk_config_invalid is True
        before = path.read_bytes()
        manager.update_section("notification", {"sound_volume": 55})
        manager.force_save()
        assert path.read_bytes() == before

    def test_a_read_error_does_not(self, tmp_path: Path) -> None:
        """读文件时的 OSError 可能只是瞬时的（R783 的约定），仍然不置位。"""
        path = tmp_path / "config.toml"
        path.write_bytes(GOOD)
        manager = ConfigManager(str(path))

        with patch(
            "ai_intervention_agent.config_manager.open",
            side_effect=PermissionError("locked by another process"),
            create=True,
        ):
            manager._load_config()

        assert manager._on_disk_config_invalid is False


# ---- F. network_security --------------------------------------------------------------------------


class TestTheNetworkSettingsInsideSuchAFileAreNotOpenedUp:
    @pytest.mark.parametrize("name", sorted(NETWORK_SECURITY_FORMS))
    def test_only_the_own_machine_is_let_in(self, name: str, tmp_path: Path) -> None:
        path = tmp_path / "config.toml"
        path.write_bytes(NETWORK_SECURITY_FORMS[name])
        manager = ConfigManager(str(path))

        settings = manager.get_network_security_config()

        assert settings["bind_interface"] == "127.0.0.1"
        assert settings["allowed_networks"] == LOOPBACK
