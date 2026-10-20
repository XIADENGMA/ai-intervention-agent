"""R783：解析不了的 config.toml 不会被默认配置覆盖。

现象（真实 stdio MCP 服务 + 真实 Web UI 子进程，端到端复现）
============================================================

手改 ``config.toml`` 时手滑一个字符、文件存成了 GBK 而不是 UTF-8、被别的工具写进了二进制——
文件解析不了。``_load_config`` 对这种文件的处理是：记一条 ERROR，内存里用默认配置，
``_original_content`` 置为 ``None``，服务照常运行。这一步本身没问题。

问题在退出时。MCP 服务和 Web UI 子进程退出时各自走 ``atexit`` →
``ConfigManager.shutdown()`` → ``force_save()`` → ``_save_config_immediate()``。这条路径不
管有没有变更都会走；``_original_content`` 是 ``None`` 时它把内存里的**默认配置**整个序列化出来，
和 ``None`` 比较当然不相等，于是**原子地写进用户的文件**。实测（每个场景跑一次
``interactive_feedback``，什么设置都没碰）：

======================  ================  ==================
文件                    运行前            运行后
======================  ================  ==================
语法错误（1059 字节）    用户的内容        默认配置（1050 字节）
二进制垃圾（2048 字节）  用户的内容        默认配置
权限 000 的文件          用户的内容        默认配置（权限位还是 000）
======================  ================  ==================

也就是说：一个手滑，下一次启动再退出，整份配置（端口、``bind_interface`` 和访问控制、
Bark 的 ``device_key``、提示词……）就被默认值换掉了，磁盘上留下的只有一条没人看的 ERROR。

另有两条变体：

* 服务运行中用户把文件改坏（热重载失败，沿用上一份内存配置），之后任何一次写入——Web UI 里
  改个设置、退出时的 ``force_save``——都会用上一份内容把用户**刚改的那一版**盖掉；
* ``set_network_security_config`` 在没有 ``_original_content`` 时拿到的是空串，
  ``_atomic_write_config("")`` 会把文件写成 0 字节。

修复
====

``ConfigManager`` 记下"磁盘上的配置文件内容加载失败"（``_on_disk_config_invalid``）：
``_load_config`` 因解码、解析或结构校验失败（``ValueError`` / ``ConfigValidationError``）时置位，
成功加载时清除。置位期间所有自动写入都不动文件：``_save_config_immediate`` 记一条 WARNING
后跳过，``_save_network_security_config_immediate`` 抛 ``RuntimeError``（调用方本来就处理
这个异常）。用户修好文件（热重载成功）后恢复正常；删掉文件则下次启动重新生成默认配置；
内存里的改动在本进程内照常生效，只是不落盘。

只对**内容**错误置位。读文件时的 ``OSError``（权限、占用）不置位：Windows 上杀毒软件或另一个
进程刚好占着文件时会瞬时失败，而这类失败不会让文件的 mtime 变化、热重载不会再来一次——置位
的话一次瞬时错误就让之后所有的保存作废。上表里权限 000 那一行因此不在保护范围内（那是用户
自己把文件设成不可读）。

测试矩阵
========

A. 四种解析不了的文件 × 五条写入路径：``force_save``、``shutdown``、改了值之后的
   ``force_save``、``set_network_security_config``、真实进程退出时的 ``atexit``，文件字节不变
   （改的值在内存里生效）；
B. 用户修好文件、热重载成功后，写入恢复；
C. 服务运行中文件被改坏：用户那一版不被盖掉，修好后写入恢复；
D. 对照：正常文件的改动照常落盘。

A、C 在旧代码上失败；B、D 在新旧代码上都通过。
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import tomllib
from pathlib import Path
from unittest.mock import patch

import pytest

from ai_intervention_agent.config_manager import ConfigManager

REPO_ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = REPO_ROOT / "config.toml.default"

VALID = b"[web_ui]\nport = 18792\n\n[notification]\nsound_volume = 80\n"

BROKEN = {
    "syntax-error": b"[web_ui]\nport = 18792\n\n[notification\nsound_volume = = 80\n",
    "binary-garbage": bytes(range(256)) * 4,
    "saved-as-gbk": '[feedback]\nresubmit_prompt = "请立即调用 interactive_feedback"\n'.encode(
        "gbk"
    ),
    "json-not-toml": b'{"web_ui": {"port": 18792}}\n',
}


def volume(path: Path) -> int:
    return tomllib.loads(path.read_text(encoding="utf-8"))["notification"][
        "sound_volume"
    ]


@pytest.fixture(params=sorted(BROKEN))
def broken_file(request: pytest.FixtureRequest, tmp_path: Path) -> Path:
    path = tmp_path / "config.toml"
    path.write_bytes(BROKEN[request.param])
    return path


class TestAnUnparseableFileIsLeftAlone:
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

    def test_a_process_that_exits(self, broken_file: Path) -> None:
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


class TestTheFileIsUsableAgainOnceItIsFixed:
    def test_a_fixed_file_is_saved_again(self, broken_file: Path) -> None:
        manager = ConfigManager(str(broken_file))
        broken_file.write_bytes(VALID)
        manager._load_config()

        manager.update_section("notification", {"sound_volume": 55})
        manager.force_save()

        assert volume(broken_file) == 55
        assert tomllib.loads(broken_file.read_text(encoding="utf-8"))["web_ui"][
            "port"
        ] == (18792)

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


class TestAFileBrokenWhileTheServiceRuns:
    def test_the_users_edit_is_not_overwritten(self, tmp_path: Path) -> None:
        path = tmp_path / "config.toml"
        path.write_bytes(VALID)
        manager = ConfigManager(str(path))
        edited = VALID + b"[oops\nvalue = = =\n"
        path.write_bytes(edited)
        manager._load_config()

        manager.update_section("notification", {"sound_volume": 55})
        manager.force_save()

        assert path.read_bytes() == edited

    def test_saving_resumes_after_the_edit_is_fixed(self, tmp_path: Path) -> None:
        path = tmp_path / "config.toml"
        path.write_bytes(VALID)
        manager = ConfigManager(str(path))
        path.write_bytes(VALID + b"[oops\nvalue = = =\n")
        manager._load_config()
        path.write_bytes(VALID)
        manager._load_config()

        manager.update_section("notification", {"sound_volume": 57})
        manager.force_save()

        assert volume(path) == 57


class TestHealthyFilesAreUnaffected:
    def test_a_changed_value_is_still_written(self, tmp_path: Path) -> None:
        path = tmp_path / "config.toml"
        path.write_bytes(TEMPLATE.read_bytes())
        manager = ConfigManager(str(path))

        manager.update_section("notification", {"sound_volume": 58})
        manager.force_save()

        assert volume(path) == 58


class TestWhatTheGuardLeavesAlone:
    """守卫只管"有内容但解析不了"的文件；下面这些照旧。"""

    def test_a_zero_byte_toml_file_is_filled(self, tmp_path: Path) -> None:
        path = tmp_path / "config.toml"
        path.write_bytes(b"")
        manager = ConfigManager(str(path))

        manager.update_section("notification", {"sound_volume": 59})
        manager.force_save()

        assert volume(path) == 59

    def test_a_zero_byte_json_file_is_filled(self, tmp_path: Path) -> None:
        path = tmp_path / "config.json"
        path.write_bytes(b"")
        manager = ConfigManager(str(path))

        manager.set_network_security_config(manager.get_network_security_config())

        assert "network_security" in json.loads(path.read_text(encoding="utf-8"))

    def test_a_transient_read_error_does_not_block_later_saves(
        self, tmp_path: Path
    ) -> None:
        """读文件时的 OSError 可能只是瞬时的（杀毒软件、另一个进程占着），不能让之后的保存全部作废。"""
        path = tmp_path / "config.toml"
        path.write_bytes(VALID)
        manager = ConfigManager(str(path))

        with patch(
            "ai_intervention_agent.config_manager.open",
            side_effect=PermissionError("locked by another process"),
            create=True,
        ):
            manager._load_config()
        manager.update_section("notification", {"sound_volume": 61})
        manager.force_save()

        assert volume(path) == 61
