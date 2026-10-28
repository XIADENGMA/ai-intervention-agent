"""R918：``bind_interface`` 没写的时候，Web UI 只监听本机，不再是所有网卡。

现象（旧代码实测）
==================

默认的监听地址是 ``0.0.0.0``。全新安装（模板里就写着 ``bind_interface = "0.0.0.0"``）、或者配置里
没有这一项，Web UI 都监听在每一块网卡上，默认放行的内网网段（``192.168.0.0/16`` 等）里的任何一台
机器都能打开页面。页面和接口里有 Bark device key、任务内容、自动重调提示词，这些不该因为“没改过
配置”就对整个局域网开放。不是地址的值早就退回 ``127.0.0.1``，两条日志把它叫作“默认值”（README 在
R855 之前也这么写，R855 把 README 改成了和代码一致）：代码对“什么都没写时监听哪里”有两个答案，
真正的默认值是不安全的那个。

真实进程，另一块网卡（本机的局域网地址）上的连接：

====================================  ==================  ==================
启动方式                               旧代码               新代码
====================================  ==================  ==================
命令行 ``web_ui.py``，不带 ``--host``   **能连上**           连接被拒绝
MCP 服务的启动路径，全新安装（无文件）    **能连上**           连接被拒绝
MCP 服务的启动路径，配置里没有这一项     **能连上**           连接被拒绝
配置里写了 ``"0.0.0.0"``（对照）        能连上               能连上
====================================  ==================  ==================

修复
====

默认值只在一个地方：``web_ui_validators.DEFAULT_BIND_INTERFACE = "127.0.0.1"``。配置段的模型
（``NetworkSecuritySectionConfig``，默认配置由它生成）、Web UI 一侧的校验、管理器读 ``network_security``
时的兜底、``WebFeedbackUI`` 和 ``web_feedback_ui`` 的 ``host`` 参数、命令行的 ``--host`` 都用它。
``config.toml.default`` 里写成 ``"127.0.0.1"``；全新安装是把这份模板复制成 ``config.toml``，所以模板
才是全新安装真正读到的那一份。要让手机、别的电脑访问，自己写 ``bind_interface = "0.0.0.0"`` 或某个
网卡地址（环境变量 ``AI_INTERVENTION_AGENT_WEB_UI_HOST`` 照旧优先）。

早先版本生成的 ``config.toml`` 里已经写着 ``bind_interface = "0.0.0.0"``，不受影响：改的是“没写的
时候”，不是“写了的值”。其余各项默认值（放行的网段、黑名单、令牌……）原样不动；mDNS 的 ``auto``
本来就是“监听地址不是回环才发布”，所以默认值改了之后改成局域网地址才会发布。

测试矩阵
========

A. 默认值只有一个出处：常量、配置段模型、默认配置、两处校验的兜底、模板、``web_ui`` 里三处 ``host``
   默认值都指向它；源码里别处不再把 ``"0.0.0.0"`` 当字面量用（白名单里是“认得这个值”的几处）；
B. 读配置（真实文件）：没有文件、空文件、只有注释、没有 ``[network_security]``、有这一段但没写这一项、
   写成空串 / 不是地址 / 不是字符串：都是 ``127.0.0.1``；写了的地址原样保留；其余各项默认值没动；
   全新安装写出来的文件里是 ``127.0.0.1``；
C. MCP 服务选的监听地址（``get_web_ui_config``）：默认回环，文件里写了就用文件的，环境变量优先；
D. mDNS ``auto`` 和 Bark 通知的点击链接：默认地址下不发布 mDNS，也没有链接（回环地址发给手机没用，
   又没配 ``external_base_url``）；写了局域网地址、或配了 ``external_base_url``，照旧有链接；
E. 文档、README、模板的说法：新的默认值写对了，没有哪一处还把 ``0.0.0.0`` 写成默认；手机要访问
   就得改 ``bind_interface``，iPhone 一节第一件事就写这个，workflow 指南里列局域网地址的那一行也写明；
F. 真实进程：命令行不带 ``--host``、MCP 服务启动路径（全新安装和“配置里没有这一项”两种）都只在本机
   监听，本机的局域网地址上连接被拒绝；对照：写了 ``0.0.0.0`` 就能从局域网地址连上。

旧代码上 46 个失败，通过的 24 个是对照：写了的地址原样保留、其余默认值不变、早先版本的文件不变、文件和
环境变量优先、局域网地址下 mDNS 照常发布、写了地址或 ``external_base_url`` 时 Bark 链接照旧、F 里写了
``0.0.0.0`` 的对照。全新安装的真实进程用例没有在旧代码上跑（旧代码上它会通过 mDNS 在网络上宣告
Web UI），同一条路径由“配置里没有这一项”那个用例在旧代码上失败来证明。旧代码没有
``DEFAULT_BIND_INTERFACE``，在旧代码上跑这个文件时把那一行 import 换成
``DEFAULT_BIND_INTERFACE = None``。每个测试的 docstring 写着它在旧代码上的结果。
"""

from __future__ import annotations

import ast
import contextlib
import inspect
import json
import os
import re
import socket
import subprocess
import sys
import textwrap
import time
import tomllib
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from ai_intervention_agent import server_config, service_manager
from ai_intervention_agent.config_manager import ConfigManager
from ai_intervention_agent.shared_types import NetworkSecuritySectionConfig
from ai_intervention_agent.web_ui import WebFeedbackUI, web_feedback_ui
from ai_intervention_agent.web_ui_mdns import MdnsMixin
from ai_intervention_agent.web_ui_validators import (
    DEFAULT_BIND_INTERFACE,
    validate_network_security_config,
)

REPO = Path(__file__).resolve().parent.parent
PACKAGE = REPO / "src" / "ai_intervention_agent"
WEB_UI = PACKAGE / "web_ui.py"
TEMPLATE = REPO / "config.toml.default"
ENV_HOST = "AI_INTERVENTION_AGENT_WEB_UI_HOST"
ENV_PORT = "AI_INTERVENTION_AGENT_WEB_UI_PORT"
ENV_CONFIG = "AI_INTERVENTION_AGENT_CONFIG_FILE"

LOOPBACK = "127.0.0.1"
WILDCARD = "0.0.0.0"

# 没配置过的 [network_security]：只有监听地址是 R918 改的，别的没动
DEFAULT_SECTION = {
    "bind_interface": LOOPBACK,
    "allowed_networks": [
        "127.0.0.0/8",
        "::1/128",
        "192.168.0.0/16",
        "10.0.0.0/8",
        "172.16.0.0/12",
    ],
    "blocked_ips": [],
    "trusted_hosts": [],
    "trusted_proxy_hops": 1,
    "access_control_enabled": True,
    "api_token": "",
    "api_token_rotated_at": "",
}


def _manager(tmp_path: Path, text: str | bytes | None) -> ConfigManager:
    path = tmp_path / "config.toml"
    if isinstance(text, str):
        path.write_text(text, encoding="utf-8")
    elif isinstance(text, bytes):
        path.write_bytes(text)
    return ConfigManager(str(path))


# ---- A. 默认值只有一个出处 ------------------------------------------------------------------


# 这几个文件里 "0.0.0.0" 是“认得这个值”：合法取值、通配地址换成 localhost、通配地址不作 Host 名、
# 启动时给 0.0.0.0 打的提示。别处出现新的 "0.0.0.0" 字面量，多半是又写了一份默认值
WILDCARD_LITERAL_ALLOWED = {
    "web_ui.py",
    "web_ui_validators.py",
    "web_ui_security.py",
    "server_config.py",
}


def _exact_wildcard_literals(path: Path) -> list[int]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and node.value == WILDCARD
    ]


def _function(tree: ast.AST, name: str, owner: str | None = None) -> ast.FunctionDef:
    scope: ast.AST = tree
    if owner is not None:
        scope = next(
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.ClassDef) and node.name == owner
        )
    for node in ast.walk(scope):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"{owner or 'module'}.{name} not found")


def _parameter_default(function: ast.FunctionDef, parameter: str) -> ast.expr:
    arguments = function.args
    names = [arg.arg for arg in [*arguments.posonlyargs, *arguments.args]]
    defaults = [None] * (len(names) - len(arguments.defaults)) + list(
        arguments.defaults
    )
    for arg, default in zip(names, defaults, strict=True):
        if arg == parameter and default is not None:
            return default
    for arg, default in zip(arguments.kwonlyargs, arguments.kw_defaults, strict=True):
        if arg.arg == parameter and default is not None:
            return default
    raise AssertionError(f"{function.name} has no default for {parameter}")


class TestOneDefaultOneHome:
    def test_the_default_is_this_computer_only(self) -> None:
        """旧代码：没有这个常量（import 失败，换成 None 之后这里不等于 127.0.0.1）。"""
        assert DEFAULT_BIND_INTERFACE == LOOPBACK

    def test_the_section_model_carries_it(self) -> None:
        """旧代码：模型默认 ``"0.0.0.0"``。"""
        assert NetworkSecuritySectionConfig().bind_interface == LOOPBACK

    def test_the_default_config_comes_from_the_model(self, tmp_path: Path) -> None:
        """旧代码：``"0.0.0.0"``。"""
        manager = _manager(tmp_path, None)

        assert manager._get_default_config()["network_security"] == {
            "bind_interface": LOOPBACK,
            "allowed_networks": DEFAULT_SECTION["allowed_networks"],
            "blocked_ips": [],
            "trusted_hosts": [],
            "trusted_proxy_hops": 1,
            "access_control_enabled": True,
            "api_token": "",
            "api_token_rotated_at": "",
        }

    def test_the_web_ui_validator_falls_back_to_it(self) -> None:
        """旧代码：``validate_network_security_config({})`` 给 ``"0.0.0.0"``。"""
        assert validate_network_security_config({})["bind_interface"] == LOOPBACK
        assert validate_network_security_config(None)["bind_interface"] == LOOPBACK
        assert (
            validate_network_security_config({"blocked_ips": []})["bind_interface"]
            == LOOPBACK
        )

    def test_the_manager_falls_back_to_it(self, tmp_path: Path) -> None:
        """旧代码：``"0.0.0.0"``。"""
        manager = _manager(tmp_path, None)

        assert manager._validate_network_security_config({})["bind_interface"] == (
            LOOPBACK
        )

    def test_the_template_ships_it(self) -> None:
        """旧代码：模板里是 ``"0.0.0.0"``，全新安装就把它复制成了用户的配置。"""
        shipped = tomllib.loads(TEMPLATE.read_text(encoding="utf-8"))
        assert shipped["network_security"]["bind_interface"] == LOOPBACK

    def test_the_web_ui_entry_points_default_to_the_one_constant(self) -> None:
        """旧代码：三处各写了一个 ``"0.0.0.0"``。"""
        tree = ast.parse(WEB_UI.read_text(encoding="utf-8"))
        for function in (
            _function(tree, "__init__", owner="WebFeedbackUI"),
            _function(tree, "web_feedback_ui"),
        ):
            default = _parameter_default(function, "host")
            assert isinstance(default, ast.Name), function.name
            assert default.id == "DEFAULT_BIND_INTERFACE", function.name

        host_options = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "add_argument"
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and node.args[0].value == "--host"
        ]
        assert len(host_options) == 1
        default = next(k.value for k in host_options[0].keywords if k.arg == "default")
        assert isinstance(default, ast.Name)
        assert default.id == "DEFAULT_BIND_INTERFACE"

    def test_the_constructor_defaults_are_the_loopback_address(self) -> None:
        """旧代码：``"0.0.0.0"``。"""
        for function in (WebFeedbackUI.__init__, web_feedback_ui):
            default = inspect.signature(function).parameters["host"].default
            assert default == LOOPBACK, function.__qualname__

    def test_no_other_module_spells_the_wildcard_as_a_value(self) -> None:
        offenders = {
            f"{path.relative_to(REPO)}:{line}"
            for path in sorted(PACKAGE.rglob("*.py"))
            if path.name not in WILDCARD_LITERAL_ALLOWED
            for line in _exact_wildcard_literals(path)
        }
        assert offenders == set(), (
            "a new '0.0.0.0' literal: if it is a default listen address, use "
            "DEFAULT_BIND_INTERFACE; if it only recognises the value, add the file to "
            "WILDCARD_LITERAL_ALLOWED"
        )

    def test_nothing_in_the_allowed_files_is_a_default_listen_address(self) -> None:
        """白名单里的几处只在“认得”这个值：比较、集合成员；不是参数默认值、也不是 ``.get`` 的默认。"""
        for name in sorted(WILDCARD_LITERAL_ALLOWED):
            tree = ast.parse((PACKAGE / name).read_text(encoding="utf-8"))
            defaults: list[ast.expr] = []
            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                    defaults += [*node.args.defaults]
                    defaults += [d for d in node.args.kw_defaults if d is not None]
                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "get"
                    and len(node.args) == 2
                ):
                    defaults.append(node.args[1])
            for default in defaults:
                assert not (
                    isinstance(default, ast.Constant) and default.value == WILDCARD
                ), f"{name}:{default.lineno} uses '0.0.0.0' as a default"


# ---- B. 读配置 ----------------------------------------------------------------------------------

NOT_SET = [
    pytest.param(None, id="no file"),
    pytest.param("", id="empty file"),
    pytest.param("# nothing here\n", id="only a comment"),
    pytest.param("[web_ui]\nport = 18918\n", id="no [network_security] at all"),
    pytest.param("[network_security]\n", id="an empty [network_security]"),
    pytest.param(
        '[network_security]\nblocked_ips = ["203.0.113.7"]\n',
        id="the section without the key",
    ),
    pytest.param(
        '[network_security]\nallowed_networks = ["10.0.0.0/8"]\ntrusted_hosts = ["a.example"]\n',
        id="other keys written, this one not",
    ),
]

NOT_AN_ADDRESS = [
    pytest.param('bind_interface = ""', id="empty string"),
    pytest.param('bind_interface = "   "', id="blanks"),
    pytest.param('bind_interface = "not-an-address"', id="a word"),
    pytest.param('bind_interface = "300.1.1.1"', id="an impossible address"),
    pytest.param("bind_interface = 5", id="an integer"),
    pytest.param("bind_interface = true", id="a boolean"),
    pytest.param('bind_interface = ["0.0.0.0"]', id="a list"),
]

WRITTEN = [
    pytest.param("0.0.0.0", id="all interfaces"),
    pytest.param("192.168.1.5", id="a LAN address"),
    pytest.param("10.1.2.3", id="another private address"),
    pytest.param("::", id="IPv6 wildcard"),
    pytest.param("::1", id="IPv6 loopback"),
    pytest.param("localhost", id="localhost"),
    pytest.param("127.0.0.1", id="loopback"),
]


class TestReadingTheConfiguration:
    @pytest.mark.parametrize("text", NOT_SET)
    def test_not_set_means_this_computer_only(
        self, tmp_path: Path, text: str | None
    ) -> None:
        """旧代码：``"0.0.0.0"``（七种写法都是）。"""
        manager = _manager(tmp_path, text)

        assert manager.get_network_security_config()["bind_interface"] == LOOPBACK
        assert manager.get_section("network_security")["bind_interface"] == LOOPBACK

    @pytest.mark.parametrize("line", NOT_AN_ADDRESS)
    def test_a_value_that_is_not_an_address_means_this_computer_only(
        self, tmp_path: Path, line: str
    ) -> None:
        """旧代码也是 ``127.0.0.1``：写坏的值退回本机，不是退回默认值，两者现在是同一个。"""
        manager = _manager(tmp_path, f"[network_security]\n{line}\n")

        assert manager.get_network_security_config()["bind_interface"] == LOOPBACK

    @pytest.mark.parametrize("address", WRITTEN)
    def test_an_address_that_is_written_is_kept(
        self, tmp_path: Path, address: str
    ) -> None:
        """新旧代码都通过：改的是“没写的时候”。"""
        manager = _manager(
            tmp_path, f'[network_security]\nbind_interface = "{address}"\n'
        )

        assert manager.get_network_security_config()["bind_interface"] == address
        assert manager.get_section("network_security")["bind_interface"] == address

    def test_only_the_listen_address_changed(self, tmp_path: Path) -> None:
        """新旧代码都通过（旧代码只在监听地址上不同）：其余各项默认值没动。"""
        manager = _manager(tmp_path, "[web_ui]\nport = 18918\n")

        section = manager.get_network_security_config()

        assert {k: v for k, v in section.items() if k != "bind_interface"} == {
            k: v for k, v in DEFAULT_SECTION.items() if k != "bind_interface"
        }

    def test_a_fresh_install_writes_the_loopback_address_into_the_file(
        self, tmp_path: Path
    ) -> None:
        """旧代码：全新安装复制出来的模板里是 ``"0.0.0.0"``。"""
        path = tmp_path / "config.toml"
        assert not path.exists()

        manager = ConfigManager(str(path))

        written = tomllib.loads(path.read_text(encoding="utf-8"))
        assert written["network_security"]["bind_interface"] == LOOPBACK
        assert manager.get_network_security_config()["bind_interface"] == LOOPBACK

    def test_a_file_from_an_earlier_version_keeps_what_it_says(
        self, tmp_path: Path
    ) -> None:
        """早先版本的模板写着 ``0.0.0.0``：这样的文件不会因为默认值变了而变。新旧代码都通过。"""
        old_template = TEMPLATE.read_text(encoding="utf-8").replace(
            f'bind_interface = "{LOOPBACK}"', f'bind_interface = "{WILDCARD}"'
        )
        assert f'bind_interface = "{WILDCARD}"' in old_template
        manager = _manager(tmp_path, old_template)

        assert manager.get_network_security_config()["bind_interface"] == WILDCARD


# ---- C. MCP 服务选的监听地址 ---------------------------------------------------------------------


@contextlib.contextmanager
def _real_config(
    text: str | None, tmp_path: Path, env: str | None = None
) -> Iterator[None]:
    """真实的 ``ConfigManager`` 读 ``text``，``ENV_HOST`` 为 ``env``（不碰全局配置管理器）。"""
    manager = _manager(tmp_path, text)
    with (
        patch.dict(os.environ),
        patch.object(service_manager, "get_config", return_value=manager),
        patch.object(service_manager, "_ensure_config_change_callbacks_registered"),
    ):
        os.environ.pop(ENV_HOST, None)
        if env is not None:
            os.environ[ENV_HOST] = env
        service_manager.reset_config_cache_for_testing()
        try:
            yield
        finally:
            service_manager.reset_config_cache_for_testing()


def _started_on(text: str | None, tmp_path: Path, env: str | None = None) -> str:
    with _real_config(text, tmp_path, env):
        config, _ = service_manager.get_web_ui_config()
        return config.host


class TestWhereTheMcpServerStartsTheWebUi:
    @pytest.mark.parametrize("text", NOT_SET)
    def test_not_set_means_loopback(self, tmp_path: Path, text: str | None) -> None:
        """旧代码：``0.0.0.0``。"""
        assert _started_on(text, tmp_path) == LOOPBACK

    def test_the_file_wins_over_the_default(self, tmp_path: Path) -> None:
        """新旧代码都通过。"""
        text = f'[network_security]\nbind_interface = "{WILDCARD}"\n'

        assert _started_on(text, tmp_path) == WILDCARD

    def test_the_env_var_wins_over_both(self, tmp_path: Path) -> None:
        """新旧代码都通过。"""
        assert _started_on(None, tmp_path, env=WILDCARD) == WILDCARD
        text = f'[network_security]\nbind_interface = "{WILDCARD}"\n'
        assert _started_on(text, tmp_path, env=LOOPBACK) == LOOPBACK


# ---- D. mDNS ----------------------------------------------------------------------------------


class _Publisher(MdnsMixin):
    def __init__(self, host: str) -> None:
        self.host = host


class TestMdnsFollowsTheDefault:
    def test_auto_does_not_publish_on_the_default_address(self) -> None:
        """旧代码：默认地址是 ``0.0.0.0``，``auto`` 会发布。"""
        assert (
            _Publisher(DEFAULT_BIND_INTERFACE)._should_enable_mdns({"enabled": "auto"})
            is False
        )

    def test_auto_publishes_on_a_lan_address(self) -> None:
        """新旧代码都通过。"""
        for host in (WILDCARD, "192.168.1.5"):
            assert _Publisher(host)._should_enable_mdns({"enabled": "auto"}) is True


def _external_base_url(text: str | None, tmp_path: Path) -> str:
    """Bark 通知的点击链接用的地址（``for_external_use``：回环地址发给手机没用，给空串）。"""
    manager = _manager(tmp_path, text)
    with patch.object(server_config, "get_config", return_value=manager):
        return server_config.resolve_external_base_url(for_external_use=True)


class TestTheBarkClickLinkFollowsTheDefault:
    """点击链接要手机够得到的地址：监听地址是回环、又没配 ``external_base_url``，就没有链接。"""

    @pytest.mark.parametrize("text", NOT_SET)
    def test_not_set_means_no_address_for_a_phone(
        self, tmp_path: Path, text: str | None
    ) -> None:
        """旧代码：默认地址 ``0.0.0.0``，mDNS ``auto`` 发布，链接是 ``http://ai.local:<端口>``。"""
        assert _external_base_url(text, tmp_path) == ""

    @pytest.mark.parametrize(
        ("address", "port_section", "expected"),
        [
            pytest.param(WILDCARD, "", "http://ai.local:8080", id="all interfaces"),
            pytest.param("192.168.1.5", "", "http://ai.local:8080", id="a LAN address"),
            pytest.param(
                WILDCARD,
                "[web_ui]\nport = 18918\n",
                "http://ai.local:18918",
                id="another port",
            ),
        ],
    )
    def test_a_written_address_brings_the_link_back(
        self, tmp_path: Path, address: str, port_section: str, expected: str
    ) -> None:
        """新旧代码都通过：写了地址就和以前一样。"""
        text = f'{port_section}[network_security]\nbind_interface = "{address}"\n'

        assert _external_base_url(text, tmp_path) == expected

    def test_external_base_url_brings_the_link_back(self, tmp_path: Path) -> None:
        """新旧代码都通过：配了 ``external_base_url`` 就用它，和监听地址无关。"""
        text = '[web_ui]\nexternal_base_url = "https://agent.example.test"\n'

        assert _external_base_url(text, tmp_path) == "https://agent.example.test"


# ---- E. 文档 ----------------------------------------------------------------------------------

# 不写“默认值”的历史记录：贡献者指南、性能审计、CHANGELOG
GUIDES = [
    REPO / "README.md",
    REPO / "README.zh-CN.md",
    *sorted(
        path
        for path in (REPO / "docs").glob("*.md")
        if not path.name.startswith(("contributor-guide", "perf-audit"))
    ),
]

STALE_DEFAULT = [
    r"default `0\.0\.0\.0`",
    r"default \"0\.0\.0\.0\"",
    r"默认 `0\.0\.0\.0`",
    r"默认 \"0\.0\.0\.0\"",
    r"(default|默认) 0\.0\.0\.0",
    r"listens on all interfaces unless",
    r"默认监听所有网卡",
    r"Web UI 默认监听所有",
]


def _row(path: Path, prefix: str) -> str:
    rows = [
        r for r in path.read_text(encoding="utf-8").split("\n") if r.startswith(prefix)
    ]
    assert len(rows) == 1, (path.name, prefix, len(rows))
    return rows[0]


def _section(path: Path, heading: str) -> str:
    text = path.read_text(encoding="utf-8")
    start = text.index(f"\n{heading}\n")
    end = text.find("\n## ", start + 1)
    return text[start : end if end != -1 else len(text)]


class TestTheGuidesSayTheNewDefault:
    @pytest.mark.parametrize(
        ("name", "rule_start", "default_words"),
        [
            (
                "configuration.md",
                "- The Web UI listens on the env var",
                "(default `127.0.0.1`",
            ),
            (
                "configuration.zh-CN.md",
                "- Web UI 监听的地址：",
                "（默认 `127.0.0.1`",
            ),
        ],
    )
    def test_the_host_selection_rule_and_the_rows_give_it(
        self, name: str, rule_start: str, default_words: str
    ) -> None:
        """旧代码：``(default `0.0.0.0`)``。"""
        path = REPO / "docs" / name

        assert default_words in _row(path, rule_start)
        assert default_words in _row(path, "| `host`")
        cells = [cell.strip() for cell in _row(path, "| `bind_interface`").split("|")]
        assert cells[3] == f"`{LOOPBACK}`"

    def test_no_guide_still_gives_the_wildcard_as_the_default(self) -> None:
        """旧代码：configuration、troubleshooting、两份 README 里都有。"""
        offenders = [
            f"{path.relative_to(REPO)}: {pattern}"
            for path in GUIDES
            for pattern in STALE_DEFAULT
            if re.search(pattern, path.read_text(encoding="utf-8"))
        ]
        assert offenders == []

    @pytest.mark.parametrize(
        ("name", "heading"),
        [
            ("configuration.md", "## Recommended iPhone setup: Shortcuts + Bark"),
            ("configuration.zh-CN.md", "## iPhone 推荐用法：快捷指令 + Bark"),
        ],
    )
    def test_the_iphone_setup_starts_with_making_the_web_ui_reachable(
        self, name: str, heading: str
    ) -> None:
        """旧代码：没有这一段（默认就监听所有网卡）。"""
        section = _section(REPO / "docs" / name, heading)
        first_steps = section[: section.index("\n1. ")]

        assert "network_security.bind_interface" in first_steps
        assert f'"{WILDCARD}"' in first_steps
        assert LOOPBACK in first_steps

    def test_the_guides_say_which_installs_keep_their_old_address(self) -> None:
        """早先版本生成的 config.toml 里写着 0.0.0.0，不改就不变：配置指南里要说。"""
        for name, words in (
            ("configuration.md", f'`bind_interface = "{WILDCARD}"` written in it'),
            ("configuration.zh-CN.md", f'`bind_interface = "{WILDCARD}"`，不改这一行'),
        ):
            assert words in (REPO / "docs" / name).read_text(encoding="utf-8"), name

    @pytest.mark.parametrize(
        ("name", "line_start"),
        [
            ("workflow.md", "- Open (local):"),
            ("workflow.zh-CN.md", "- 打开（本机）："),
        ],
    )
    def test_the_workflow_guide_says_the_lan_addresses_need_the_key(
        self, name: str, line_start: str
    ) -> None:
        """旧代码：只列出 ``ai.local`` 和局域网 IP，没说要先改监听地址。"""
        line = _row(REPO / "docs" / name, line_start)

        assert "network_security.bind_interface" in line
        assert f'"{WILDCARD}"' in line
        assert line.index("network_security.bind_interface") < line.index("ai.local")

    def test_the_readmes_name_the_default_next_to_the_env_var(self) -> None:
        for name, words in (
            ("README.md", "default 127.0.0.1 (this computer only)"),
            ("README.zh-CN.md", "默认 127.0.0.1（只有本机）"),
        ):
            line = _row(REPO / name, f"export {ENV_HOST}=")
            assert words in line, name

    def test_the_template_comment_names_the_default(self) -> None:
        lines = TEMPLATE.read_text(encoding="utf-8").split("\n")
        index = next(
            i for i, line in enumerate(lines) if line.startswith("bind_interface = ")
        )
        comment = "\n".join(lines[index - 3 : index])

        assert "127.0.0.1=this computer only, the default" in comment
        assert lines[index] == f'bind_interface = "{LOOPBACK}"'

    def test_the_manual_test_help_names_the_default(self) -> None:
        """旧代码：``--host`` 的帮助写着“默认 … 或0.0.0.0”。"""
        source = (REPO / "scripts" / "manual_test.py").read_text(encoding="utf-8")

        assert "没写则 127.0.0.1" in source
        assert "或0.0.0.0" not in source


# ---- F. 真实进程 --------------------------------------------------------------------------------


# 测试不在局域网上发布 mDNS（模板里是 auto：监听地址不是回环就发布）
QUIET_MDNS = "[mdns]\nenabled = false\n"


def lan_address() -> str | None:
    """本机的一个非回环 IPv4 地址（不发包，只让系统选路由）；没有就是 ``None``。"""
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect(("192.0.2.1", 9))  # TEST-NET-1：只选路由，不会真的发出去
        address = probe.getsockname()[0]
    except OSError:
        return None
    finally:
        probe.close()
    return None if address.startswith("127.") or address == WILDCARD else address


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind((LOOPBACK, 0))
        return probe.getsockname()[1]


def accepts(address: str, port: int, timeout: float = 3.0) -> bool:
    try:
        socket.create_connection((address, port), timeout=timeout).close()
    except OSError:
        return False
    return True


def child_environment(config_path: Path, **extra: str) -> dict[str, str]:
    env = {
        name: value
        for name, value in os.environ.items()
        if not name.startswith("AI_INTERVENTION_AGENT_WEB_UI")
    }
    env[ENV_CONFIG] = str(config_path)
    env.update(extra)
    return env


@contextlib.contextmanager
def web_ui_command_line(
    tmp_path: Path, *arguments: str
) -> Iterator[tuple[int, subprocess.Popen[bytes]]]:
    """命令行起的真实 Web UI（和 MCP 服务起子进程是同一个脚本），等它在本机上能连。"""
    port = free_port()
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        QUIET_MDNS, encoding="utf-8"
    )  # nothing is announced on the LAN
    log = (tmp_path / "web_ui.log").open("wb")
    process = subprocess.Popen(
        [
            sys.executable,
            "-u",
            str(WEB_UI),
            "--prompt",
            "x",
            "--port",
            str(port),
            *arguments,
        ],
        env=child_environment(config_path),
        cwd=tmp_path,
        stdin=subprocess.DEVNULL,
        stdout=log,
        stderr=log,
    )
    try:
        deadline = time.monotonic() + 90
        while not accepts(LOOPBACK, port, timeout=0.5):
            assert process.poll() is None, (tmp_path / "web_ui.log").read_text(
                "utf-8", "replace"
            )[-2000:]
            assert time.monotonic() < deadline, "the Web UI did not start"
            time.sleep(0.1)
        yield port, process
    finally:
        process.terminate()
        try:
            process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=15)
        log.close()


SERVICE_SCRIPT = textwrap.dedent(
    """
    import json
    import logging
    import socket
    from pathlib import Path

    logging.disable(logging.CRITICAL)
    from ai_intervention_agent import service_manager


    def accepts(address, port):
        try:
            socket.create_connection((address, port), timeout=3).close()
        except OSError:
            return False
        return True


    def lan_address():
        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            probe.connect(("192.0.2.1", 9))
            address = probe.getsockname()[0]
        except OSError:
            return None
        finally:
            probe.close()
        return None if address.startswith("127.") or address == "0.0.0.0" else address


    config, _ = service_manager.get_web_ui_config()
    script_dir = Path(service_manager.__file__).resolve().parent
    result = {"host": config.host}
    try:
        service_manager.start_web_service(config, script_dir)
        lan = lan_address()
        result["loopback"] = accepts("127.0.0.1", config.port)
        result["lan_address"] = lan
        result["lan"] = None if lan is None else accepts(lan, config.port)
    finally:
        service_manager.ServiceManager().cleanup_all()
    print(json.dumps(result))
    """
)


def started_by_the_mcp_server(tmp_path: Path, text: str | None) -> dict[str, Any]:
    """MCP 服务的启动路径（``start_web_service``）在全新进程里起真实的 Web UI 子进程。"""
    path = tmp_path / "config.toml"
    port = free_port()
    if text is not None:
        path.write_text(text.replace("PORT", str(port)), encoding="utf-8")
    done = subprocess.run(
        [sys.executable, "-c", SERVICE_SCRIPT],
        env=child_environment(path, **{ENV_PORT: str(port)}),
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=240,
    )
    assert done.returncode == 0, done.stderr[-2000:]
    result: dict[str, Any] = json.loads(done.stdout.strip().splitlines()[-1])
    return result


class TestRealProcesses:
    def test_the_command_line_without_host_listens_on_this_computer_only(
        self, tmp_path: Path
    ) -> None:
        """旧代码：本机的局域网地址上能连上。"""
        lan = lan_address()
        if lan is None:
            pytest.skip("this computer has no address besides loopback")

        with web_ui_command_line(tmp_path) as (port, _):
            assert accepts(LOOPBACK, port)
            assert not accepts(lan, port)

    @pytest.mark.parametrize(
        "text",
        [None, f"[web_ui]\nport = PORT\n\n{QUIET_MDNS}"],
        ids=["fresh install: no file", "a file without the key"],
    )
    def test_the_mcp_servers_start_path_listens_on_this_computer_only(
        self, tmp_path: Path, text: str | None
    ) -> None:
        """旧代码：``host`` 是 ``0.0.0.0``，局域网地址上能连上。"""
        result = started_by_the_mcp_server(tmp_path, text)
        if result["lan"] is None:
            pytest.skip("this computer has no address besides loopback")

        assert result["host"] == LOOPBACK
        assert result["loopback"] is True
        assert result["lan"] is False, f"reachable on {result['lan_address']}"

    def test_control_a_written_wildcard_is_reachable_from_the_lan_address(
        self, tmp_path: Path
    ) -> None:
        """对照，新旧代码都通过：要让手机访问的人写 ``0.0.0.0``，照旧能连上。"""
        text = (
            f"[web_ui]\nport = PORT\n\n{QUIET_MDNS}\n"
            f'[network_security]\nbind_interface = "{WILDCARD}"\n'
        )
        result = started_by_the_mcp_server(tmp_path, text)
        if result["lan"] is None:
            pytest.skip("this computer has no address besides loopback")

        assert result["host"] == WILDCARD
        assert result["loopback"] is True
        assert result["lan"] is True, f"not reachable on {result['lan_address']}"
