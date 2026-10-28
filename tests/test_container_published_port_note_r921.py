"""R921：配置指南写明容器里发布端口该怎么写。

背景
====

R918 把没写 ``bind_interface`` 时的监听地址从 ``0.0.0.0`` 改成 ``127.0.0.1``。容器里发布的端口，是经过
容器自己的网络地址到达 Web UI 的，不走回环地址：监听 ``127.0.0.1`` 的 Web UI 从容器外面什么也连不上。
配置指南的环境变量一节提到了 Docker，却没有说这件事，用户只会看到“连不上”，然后很可能顺手写成不带地址的
``-p 8080:8080``：Docker 会在宿主机的所有地址上打开这个端口（Docker 文档：发布的端口默认不只对宿主机可用，
对外面的世界也可用，只有在发布参数里写上 ``127.0.0.1`` 才只有宿主机能访问），而容器里的 Web UI 看到的来源
地址又可能是容器网络的网关（用户态代理等），``allowed_networks`` 和 ``blocked_ips`` 分不出访问者。

本轮只改文档：两份配置指南各加一节“容器里发布端口”（命令 + 一段说明）。代码没动。

钉住的东西
==========

A. 位置和内容：这一节在“SSH 远程绑定”一节之后、“验证当前生效的配置”一节之前；两份指南里的命令一字不差；
   说明里的四句话都在（经过容器自己的地址、只在宿主机回环地址上发布、不要用不带地址的 ``-p``、来源地址可能是
   网关所以访问控制分不出访问者），并指向存在的部署指南；
B. 说明依赖的代码事实：环境变量名就是代码读的那个；默认监听地址是 ``127.0.0.1``；写了 ``"0.0.0.0"`` 的文件读出
   ``0.0.0.0``，没写这个键读出 ``127.0.0.1``（“默认值只在没写这个键时才起作用”）；命令里的端口 8080 是
   ``web_ui.port`` 的默认值（模板、段模型、模型里的取值范围）；
C. 说明说“本项目没有提供容器镜像”：仓库里确实没有 Dockerfile、compose 文件、Containerfile、devcontainer。以后
   谁加了容器支持，这条测试会提醒他把这句话改掉。

每个测试的 docstring 写着它在旧文档上的结果（“对照”是新旧都通过）。
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

from ai_intervention_agent import service_manager
from ai_intervention_agent.config_manager import ConfigManager
from ai_intervention_agent.shared_types import WebUISectionConfig
from ai_intervention_agent.web_ui_validators import (
    DEFAULT_BIND_INTERFACE,
    VALID_BIND_INTERFACES,
)

REPO = Path(__file__).resolve().parent.parent
DOCS = REPO / "docs"

COMMAND = "docker run -e AI_INTERVENTION_AGENT_WEB_UI_HOST=0.0.0.0 -p 127.0.0.1:8080:8080 <your-image>"

# (文件, 上一节标题, 这一节标题, 下一节标题)
GUIDES = [
    (
        "configuration.md",
        "#### Example: SSH-remote bind on a non-default port",
        "#### Example: a container with a published port",
        "#### Verifying the effective config",
    ),
    (
        "configuration.zh-CN.md",
        "#### 示例：SSH 远程绑定到非默认端口",
        "#### 示例：容器里发布端口",
        "#### 验证当前生效的配置",
    ),
]

# (文件, 说明里必须有的句子)
SAYS = [
    (
        "configuration.md",
        [
            "reaches the Web UI through the container's own network address, not through loopback",
            "so the default `127.0.0.1` answers nothing from outside the container",
            "publish the port on the host's loopback address only",
            'A `config.toml` that says `bind_interface = "0.0.0.0"` works the same way '
            "(the default only applies when the key is missing)",
            "Do not publish with a bare `-p 8080:8080`: Docker then opens the port on every address "
            "of the host",
            "the address the Web UI sees for a connection can be the gateway of the container network "
            "instead of the visitor's, and then `allowed_networks` and `blocked_ips` cannot tell "
            "visitors apart",
            "use an SSH tunnel to the host's loopback port, or a reverse proxy on the host that "
            "passes the visitor's address on ([deployment.md](deployment.md))",
            "this project ships no container image",
        ],
    ),
    (
        "configuration.zh-CN.md",
        [
            "是经过容器自己的网络地址到达 Web UI 的，不走回环地址，所以默认的 `127.0.0.1` 从容器外面什么也连不上",
            "并且只在宿主机的回环地址上发布端口",
            '`config.toml` 里写 `bind_interface = "0.0.0.0"` 效果一样（默认值只在没写这个键时才起作用）',
            "不要用不带地址的 `-p 8080:8080` 发布：Docker 会在宿主机的所有地址上打开这个端口",
            "Web UI 看到的连接来源地址可能是容器网络的网关，而不是访问者本人的地址，"
            "这时 `allowed_networks` 和 `blocked_ips` 分不出谁是谁",
            "用 SSH 隧道连到宿主机的回环端口，或者在宿主机上放一个把访问者地址传过来的反向代理"
            "（见 [deployment.zh-CN.md](deployment.zh-CN.md)）",
            "本项目没有提供容器镜像",
        ],
    ),
]


def section(name: str, start: str, end: str) -> str:
    text = (DOCS / name).read_text(encoding="utf-8")
    assert text.count(start) == 1, (name, start, text.count(start))
    assert text.count(end) == 1, (name, end, text.count(end))
    begin = text.index(start)
    stop = text.index(end)
    assert begin < stop, (name, "the order of the sections")
    return text[begin:stop]


def command_of(body: str) -> str:
    opening = "```bash\n"
    assert body.count(opening) == 1, body
    after = body.index(opening) + len(opening)
    return body[after : body.index("\n```", after)]


# ---- A. 位置和内容 -----------------------------------------------------------------------------


class TestTheGuidesHaveTheContainerExample:
    @pytest.mark.parametrize(("name", "previous", "heading", "following"), GUIDES)
    def test_the_section_sits_between_the_ssh_example_and_the_verification_section(
        self, name: str, previous: str, heading: str, following: str
    ) -> None:
        """旧文档：没有这一节（标题出现 0 次）。"""
        text = (DOCS / name).read_text(encoding="utf-8")

        assert text.count(heading) == 1
        assert text.index(previous) < text.index(heading) < text.index(following)

    @pytest.mark.parametrize(("name", "previous", "heading", "following"), GUIDES)
    def test_the_command_is_the_same_in_both_guides(
        self, name: str, previous: str, heading: str, following: str
    ) -> None:
        """旧文档：没有这一节。"""
        body = section(name, heading, following)

        assert command_of(body) == COMMAND

    @pytest.mark.parametrize(("name", "phrases"), SAYS)
    def test_the_text_says_what_matters(self, name: str, phrases: list[str]) -> None:
        """旧文档：这些句子一句也没有。"""
        text = (DOCS / name).read_text(encoding="utf-8")

        missing = [phrase for phrase in phrases if text.count(phrase) != 1]
        assert not missing, missing

    @pytest.mark.parametrize(
        ("name", "heading", "following", "guide"),
        [
            (
                "configuration.md",
                "#### Example: a container with a published port",
                "#### Verifying the effective config",
                "deployment.md",
            ),
            (
                "configuration.zh-CN.md",
                "#### 示例：容器里发布端口",
                "#### 验证当前生效的配置",
                "deployment.zh-CN.md",
            ),
        ],
    )
    def test_the_linked_deployment_guide_exists(
        self, name: str, heading: str, following: str, guide: str
    ) -> None:
        """旧文档：没有这一节，也就没有这个链接。"""
        body = section(name, heading, following)

        assert f"]({guide})" in body
        assert (DOCS / guide).is_file()


# ---- B. 说明依赖的代码事实 ----------------------------------------------------------------------


class TestWhatTheNoteReliesOn:
    def test_the_environment_variable_is_the_one_the_code_reads(self) -> None:
        """对照，新旧文档都通过：命令里的环境变量名就是代码读的那个，两份指南的环境变量表里也有。"""
        assert service_manager._ENV_WEB_UI_HOST == "AI_INTERVENTION_AGENT_WEB_UI_HOST"
        for name in ("configuration.md", "configuration.zh-CN.md"):
            text = (DOCS / name).read_text(encoding="utf-8")
            assert "| `AI_INTERVENTION_AGENT_WEB_UI_HOST`" in text

    def test_the_default_listen_address_is_loopback_and_0000_is_a_valid_value(
        self,
    ) -> None:
        """对照，新旧文档都通过：默认值是 127.0.0.1，说明里让用户写的 0.0.0.0 是合法值。"""
        assert DEFAULT_BIND_INTERFACE == "127.0.0.1"
        assert "0.0.0.0" in VALID_BIND_INTERFACES

    def test_a_file_that_says_0000_listens_there_and_a_missing_key_does_not(
        self, tmp_path: Path
    ) -> None:
        """对照，新旧文档都通过：“默认值只在没写这个键时才起作用”。"""
        written = tmp_path / "written.toml"
        written.write_text(
            '[network_security]\nbind_interface = "0.0.0.0"\n', encoding="utf-8"
        )
        missing = tmp_path / "missing.toml"
        missing.write_text(
            '[network_security]\nallowed_networks = ["127.0.0.0/8"]\n',
            encoding="utf-8",
        )

        assert (
            ConfigManager(str(written)).get_network_security_config()["bind_interface"]
            == "0.0.0.0"
        )
        assert (
            ConfigManager(str(missing)).get_network_security_config()["bind_interface"]
            == "127.0.0.1"
        )

    def test_the_port_in_the_command_is_the_default_port(self) -> None:
        """对照，新旧文档都通过：命令里的 8080 是 web_ui.port 的默认值（模板、段模型）。"""
        template = tomllib.loads(
            (REPO / "config.toml.default").read_text(encoding="utf-8")
        )

        assert template["web_ui"]["port"] == 8080
        assert WebUISectionConfig().port == 8080
        assert COMMAND.count(":8080:8080") == 1


# ---- C. “本项目没有提供容器镜像” -----------------------------------------------------------------


class TestTheProjectShipsNoContainerImage:
    def test_there_is_no_container_file_at_the_top_of_the_repository(self) -> None:
        """对照，新旧文档都通过：说明说“没有提供容器镜像”，仓库里确实没有；有了就要把这句话改掉。"""
        names = {path.name.lower() for path in REPO.iterdir()}
        container_files = {
            name
            for name in names
            if name in {"dockerfile", "containerfile", ".devcontainer", ".dockerignore"}
            or name.startswith(("dockerfile.", "docker-compose", "compose."))
        }

        assert not container_files, (
            f"{sorted(container_files)} exist now: both configuration guides say "
            '"this project ships no container image" / "本项目没有提供容器镜像", '
            "and the container example next to it has to change"
        )
