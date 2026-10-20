"""R784：带 UTF-8 BOM 的 ``config.toml`` 照常读取，不再静默回退成默认配置。

现象（真实 stdio MCP 服务 + 真实 Web UI 子进程，端到端复现）
============================================================

Windows 上有几条很常见的路径会给文本文件加 UTF-8 BOM：记事本选"UTF-8"保存（旧版）、
PowerShell 5.1 的 ``Set-Content -Encoding UTF8`` / ``Out-File -Encoding utf8``、一些
"一键改配置"的脚本。``tomlkit`` 不接受 BOM（``EmptyKeyError``），``_load_config`` 于是走失败分支：
记一条 ERROR，内存里用默认配置——用户在文件里写的端口、提示词、Bark 设置全部不生效。

更糟的是 ``network_security``：它有独立的读取路径（``get_network_security_config``），
同样读不了带 BOM 的文件，于是返回默认值。用户在文件里配置的 ``bind_interface`` 和
``allowed_networks`` / ``blocked_ips`` 访问控制被默认值替换——没有任何界面提示，只有日志里
一条没人看的 ERROR。

（R783 之后这类文件不会再被默认配置覆盖，但读不了的问题还在。）

修复
====

读用户配置文件时用 ``utf-8-sig`` 解码：有 BOM 就去掉，没有就和 ``utf-8`` 完全一样。覆盖
``_load_config``、保存后的校验、``network_security`` 的两处读取和 JSONC 迁移。BOM 不会进入
``_original_content``，所以什么都没改时退出不会因为"内容不一样"而重写文件（文件字节保持
不变）；真有改动被保存时写出的是不带 BOM 的 UTF-8（BOM 对 UTF-8 没有意义）。

测试矩阵
========

A. 带 BOM 的文件：设置生效、``network_security`` 来自文件而不是默认值、没有 ERROR 日志、
   不触发 R783 的"文件无法解析"保护；
B. 什么都不改，``force_save`` / 进程退出后文件字节不变；
C. 改了值之后保存：值落盘、其余设置保留、结果是合法的 TOML；
D. ``set_network_security_config`` 在带 BOM 的文件上正常写入，其余段保留；
E. 旧版 JSON 配置带 BOM 同样可读；
F. 对照：不带 BOM 的文件行为不变。

A、B、C、D、E 在旧代码上失败；F 在新旧代码上都通过。
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

from ai_intervention_agent.config_manager import ConfigManager

BOM = b"\xef\xbb\xbf"

TEMPLATE = Path(__file__).resolve().parent.parent / "config.toml.default"


def _user_edited_template() -> str:
    """带全部默认键的配置文件（保存时不会被补默认值），再改几个和默认值不同的设置。"""
    text = TEMPLATE.read_text(encoding="utf-8")
    for pattern, replacement in (
        (r"^port = 8080$", "port = 18793"),
        (r"^sound_volume = 80$", "sound_volume = 77"),
        (r'^bind_interface = "0\.0\.0\.0"$', 'bind_interface = "192.168.1.1"'),
        (r"^blocked_ips = \[\]$", 'blocked_ips = ["203.0.113.7"]'),
    ):
        text, count = re.subn(pattern, replacement, text, flags=re.MULTILINE)
        assert count == 1, pattern
    return text


BODY = _user_edited_template()


@pytest.fixture(params=["with-bom", "without-bom"])
def config_path(request: pytest.FixtureRequest, tmp_path: Path) -> Path:
    path = tmp_path / "config.toml"
    prefix = BOM if request.param == "with-bom" else b""
    path.write_bytes(prefix + BODY.encode("utf-8"))
    return path


@pytest.fixture
def bom_path(tmp_path: Path) -> Path:
    path = tmp_path / "config.toml"
    path.write_bytes(BOM + BODY.encode("utf-8"))
    return path


class TestTheFileIsRead:
    """带 / 不带 BOM 的文件读出来的东西一样。"""

    def test_settings_come_from_the_file(self, config_path: Path) -> None:
        manager = ConfigManager(str(config_path))

        assert manager.get_section("web_ui")["port"] == 18793
        assert manager.get_section("notification")["sound_volume"] == 77

    def test_network_security_comes_from_the_file_not_the_defaults(
        self, config_path: Path
    ) -> None:
        manager = ConfigManager(str(config_path))

        network_security = manager.get_network_security_config()

        assert network_security["bind_interface"] == "192.168.1.1"
        assert network_security["blocked_ips"] == ["203.0.113.7"]

    def test_nothing_is_reported_as_an_error(
        self, config_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        with caplog.at_level(logging.WARNING, logger="ai_intervention_agent"):
            manager = ConfigManager(str(config_path))
            manager.get_network_security_config()

        assert [r.getMessage() for r in caplog.records] == []
        assert manager._on_disk_config_invalid is False


class TestTheFileIsNotRewrittenForNothing:
    def test_force_save_leaves_the_bytes_alone(self, config_path: Path) -> None:
        manager = ConfigManager(str(config_path))
        before = config_path.read_bytes()

        manager.force_save()

        assert config_path.read_bytes() == before

    def test_a_process_that_exits(self, config_path: Path) -> None:
        before = config_path.read_bytes()
        env = dict(os.environ, AI_INTERVENTION_AGENT_CONFIG_FILE=str(config_path))

        subprocess.run(
            [
                sys.executable,
                "-c",
                "from ai_intervention_agent.config_manager import config_manager;"
                "config_manager.get_network_security_config()",
            ],
            env=env,
            cwd=config_path.parent,
            check=True,
            timeout=60,
        )

        assert config_path.read_bytes() == before


class TestASavedChange:
    def test_is_written_and_the_rest_is_kept(self, bom_path: Path) -> None:
        manager = ConfigManager(str(bom_path))

        manager.update_section("notification", {"sound_volume": 55})
        manager.force_save()

        saved = tomllib.loads(bom_path.read_text(encoding="utf-8"))
        assert saved["notification"]["sound_volume"] == 55
        assert saved["web_ui"]["port"] == 18793
        assert saved["network_security"]["bind_interface"] == "192.168.1.1"
        assert saved["network_security"]["blocked_ips"] == ["203.0.113.7"]

    def test_network_security_update_keeps_the_other_sections(
        self, bom_path: Path
    ) -> None:
        manager = ConfigManager(str(bom_path))

        manager.update_network_security_config({"blocked_ips": ["203.0.113.8"]})

        saved = tomllib.loads(bom_path.read_text(encoding="utf-8"))
        assert saved["network_security"]["blocked_ips"] == ["203.0.113.8"]
        assert saved["network_security"]["bind_interface"] == "192.168.1.1"
        assert saved["web_ui"]["port"] == 18793
        assert saved["notification"]["sound_volume"] == 77


class TestTheLegacyJsonFormat:
    def test_a_json_file_with_a_bom_is_read(self, tmp_path: Path) -> None:
        path = tmp_path / "config.json"
        path.write_bytes(
            BOM
            + json.dumps(
                {"web_ui": {"port": 18794}, "notification": {"sound_volume": 66}}
            ).encode("utf-8")
        )

        manager = ConfigManager(str(path))

        assert manager.get_section("web_ui")["port"] == 18794
        assert manager.get_section("notification")["sound_volume"] == 66
        assert manager._on_disk_config_invalid is False
