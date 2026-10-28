"""R913：``[network_security]`` 里一个值写错，不再让整个配置文件作废。

现象（全新进程 + 真实 Web UI，旧代码实测）
==========================================

配置里写着只监听本机、有黑名单和令牌，手滑把 ``allowed_networks`` 写成了字符串，而不是列表::

    [network_security]
    bind_interface = "127.0.0.1"
    allowed_networks = "192.168.1.0/24"        # 应该是 ["192.168.1.0/24"]
    blocked_ips = ["192.168.1.66"]
    trusted_hosts = ["my.example"]
    api_token = "…32 个字符…"

读文件时 ``_validate_config_structure`` 对这种值直接抛 ``ConfigValidationError``。``_load_config``
把它当成“文件解析失败”：**所有段**回到默认值，``get_network_security_config`` 也读不出来，
退回默认。重启之后：

==============================  ==================  ==================
                                笔误之前             一处笔误之后
==============================  ==================  ==================
监听地址                         127.0.0.1           0.0.0.0
端口（``[web_ui] port``）         19913               8080（默认）
192.168.1.50 能否访问            200（白名单里）      200
10.1.2.3 能否访问                403                 200（整个内网放开）
被拉黑的 192.168.1.66            403                 200
``api_token``、``trusted_hosts``  生效                 没了
日志                             —                   一条 ERROR，之后什么都没说
==============================  ==================  ==================

这和 R843 写在 CHANGELOG 里的承诺相反：逐项的校验已经收到 ``web_ui_validators`` 一处，写坏的
``allowed_networks`` 退回“只放行本机”，“一处笔误不会放开内网”。读文件这条路上还留着一份没
跟着改的检查（``allowed_networks`` 不是列表、列表里有非字符串、整段不是表，就抛错），在文件
层把这个承诺打破了：R843 的单元测试只直接调 ``_validate_network_security_config``，没有一个
经过文件。

修复
====

结构检查只留文件本身的损坏（JSON 里重复的数组定义）。值写得对不对，只在
``_validate_network_security_config`` 一个地方判断：留下写对的项，写坏的那一项退回安全的值。
现在同一份文件：监听 127.0.0.1、端口 19913、只有本机能访问、黑名单和令牌照常生效、日志里一条
WARNING 说 ``allowed_networks`` 不是列表。

保存之后的核对（``_validate_saved_config``）用同一条规则。第一版修复漏了这里：读文件放行之后，
任何保存都会把用户写的 ``network_security`` 原样写回去，再被保存之后的严格检查拒绝，抛出
``ConfigValidationError``，每次保存记一条带堆栈的 ERROR。

测试矩阵
========

A. 十种 ``allowed_networks`` 写法（八种坏的，两种对照）经过真实文件：``network_security`` 其余
   各项原样保留，其他段照常读，文件不标记为无效，日志里有一条 ``allowed_networks`` 的 WARNING；
B. 保存：笔误一行原样留在文件里、注释保留、其他改动落盘、没有 ERROR；
C. 运行中把文件改坏再 ``reload()``：逐项退回，同一次编辑里别的改动照常生效，改好之后恢复；
D. ``network_security`` 整段不是表（四种写法）：本轮按没有这一段处理（WARNING）；R919 改成和读不出来的
   文件一样（只放行本机，ERROR），其他段照常读；
E. 真的损坏的文件（JSON 重复数组、TOML 语法错）仍然被拒绝，保存之后的核对也是；
F. 修复路径：Web UI 里保存网络设置，能盖掉上面五种写坏的内容；
G. 随机对照：500 份随机、写坏的 ``[network_security]`` 表，经过文件读出来的和直接校验解析结果
   完全一样（文件这一层不再自己拒绝任何值）；R920 起只有一个例外：``blocked_ips`` 里有读不懂的
   东西时，这一段按读不出来处理（只放行本机），随机对照里单独算这一类；
H. 全新进程：监听地址、端口和各个来源地址实际得到的状态码。

旧代码上 70 个失败。通过的 19 个是对照，新旧代码行为相同：两种对照写法（空列表、写对的列表）、
笔误之后保存、实际生效的安全设置不变、没有这一段读出默认值、真的损坏的文件仍被拒绝
（E 里只有“保存之后的核对接受读文件接受的内容”在旧代码上失败）、写对的同一份配置在全新进程里的结果。
"""

from __future__ import annotations

import json
import logging
import os
import random
import subprocess
import sys
import textwrap
import tomllib
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from ai_intervention_agent.config_manager import ConfigManager
from ai_intervention_agent.enhanced_logging import EnhancedLogger
from ai_intervention_agent.exceptions import ConfigValidationError
from ai_intervention_agent.web_ui_validators import blocked_ips_problem

LOOPBACK = ["127.0.0.0/8", "::1/128"]
TOKEN = "0123456789abcdef0123456789abcdef"
SUFFIX = "R913-SUFFIX"
PORT = 19913
VOLUME = 55

# 除 allowed_networks 以外全写对，而且每一项都和默认值不一样：退回默认值的话看得出来
RIGHT = {
    "bind_interface": "127.0.0.1",
    "blocked_ips": ["192.168.1.66"],
    "trusted_hosts": ["my.example"],
    "trusted_proxy_hops": 2,
    "access_control_enabled": False,
    "api_token": TOKEN,
}
EXPECTED_OTHERS = {
    "bind_interface": "127.0.0.1",
    "blocked_ips": ["192.168.1.66"],
    "trusted_hosts": ["my.example"],
    "trusted_proxy_hops": 2,
    "access_control_enabled": False,
    "api_token": TOKEN,
    "api_token_rotated_at": "",
}

# 写法 -> 读出来的 allowed_networks。前八种旧代码抛错；后两种是对照，新旧都通过
ALLOWED_NETWORKS = [
    pytest.param("192.168.1.0/24", LOOPBACK, id="a string"),
    pytest.param(5, LOOPBACK, id="an integer"),
    pytest.param(1.5, LOOPBACK, id="a float"),
    pytest.param(True, LOOPBACK, id="a boolean"),
    pytest.param({"net": "192.168.1.0/24"}, LOOPBACK, id="an inline table"),
    pytest.param([["192.168.1.0/24"]], LOOPBACK, id="a list of lists"),
    pytest.param([5, 6], LOOPBACK, id="numbers only"),
    pytest.param(
        [5, "192.168.1.0/24"], ["192.168.1.0/24"], id="a number next to a network"
    ),
    pytest.param([], LOOPBACK, id="control: an empty list"),
    pytest.param(["192.168.1.0/24"], ["192.168.1.0/24"], id="control: a correct list"),
]
CONTROLS = {"control: an empty list", "control: a correct list"}
BROKEN_VALUES = [p.values[0] for p in ALLOWED_NETWORKS if p.id not in CONTROLS]


def toml_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float):
        return repr(value)
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, list):
        return "[" + ", ".join(toml_value(item) for item in value) + "]"
    if isinstance(value, dict):
        pairs = ", ".join(f"{key} = {toml_value(item)}" for key, item in value.items())
        return "{ " + pairs + " }"
    raise TypeError(value)


OTHER_SECTIONS = f"""\
[feedback]
prompt_suffix = "{SUFFIX}"

[web_ui]
port = {PORT}

[notification]
sound_volume = {VOLUME}
"""


def config_text(table: dict[str, Any] | None, *, suffix: str = SUFFIX) -> str:
    """别的段在前，``[network_security]`` 在后；``table`` 为 ``None`` 时不写这一段。"""
    text = OTHER_SECTIONS.replace(SUFFIX, suffix)
    if table is None:
        return text
    lines = "".join(f"{key} = {toml_value(value)}\n" for key, value in table.items())
    return f"{text}\n[network_security]\n{lines}"


def write(tmp_path: Path, text: str, name: str = "config.toml") -> Path:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def load(tmp_path: Path, table: dict[str, Any] | None) -> ConfigManager:
    return ConfigManager(str(write(tmp_path, config_text(table))))


Line = tuple[int, str]


class Collect(logging.Handler):
    def __init__(self, seen: list[Line]) -> None:
        super().__init__()
        self.seen = seen

    def emit(self, record: logging.LogRecord) -> None:
        self.seen.append((record.levelno, record.getMessage()))


@pytest.fixture
def lines(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[Line]]:
    """Every log call of the package as ``(level, text)``.

    ``EnhancedLogger`` (the validators, ``network_security``) drops a message it already
    wrote in the last five seconds, so looking for a warning in ``caplog`` finds nothing
    when an earlier test wrote the same one: it is recorded here before that filter.
    ``config_manager`` uses a plain ``logging`` logger, which a handler on the package
    logger collects.
    """
    seen: list[Line] = []

    def record(
        self: EnhancedLogger, level: int, message: str, *args: Any, **_kwargs: Any
    ) -> None:
        seen.append((level, EnhancedLogger._render(message, args)))

    monkeypatch.setattr(EnhancedLogger, "log", record)
    package_logger = logging.getLogger("ai_intervention_agent")
    handler = Collect(seen)
    package_logger.addHandler(handler)
    try:
        yield seen
    finally:
        package_logger.removeHandler(handler)


def at_least(lines: list[Line], level: int) -> list[str]:
    return [text for line_level, text in lines if line_level >= level]


class TestOneWrongValueDoesNotVoidTheFile:
    @pytest.mark.parametrize(("value", "expected"), ALLOWED_NETWORKS)
    def test_the_other_keys_of_the_section_keep_what_was_written(
        self, tmp_path: Path, value: Any, expected: list[str]
    ) -> None:
        manager = load(tmp_path, {**RIGHT, "allowed_networks": value})

        assert manager.get_network_security_config() == {
            **EXPECTED_OTHERS,
            "allowed_networks": expected,
        }

    @pytest.mark.parametrize(("value", "expected"), ALLOWED_NETWORKS)
    def test_a_broken_value_never_opens_the_network(
        self, tmp_path: Path, value: Any, expected: list[str]
    ) -> None:
        """写坏的 allowed_networks 只会变窄（本机），或只留下写对的那几项；不会回到默认的内网段。"""
        manager = load(tmp_path, {**RIGHT, "allowed_networks": value})

        allowed = manager.get_section("network_security")["allowed_networks"]

        assert not {"192.168.0.0/16", "10.0.0.0/8", "172.16.0.0/12"} & set(allowed)

    @pytest.mark.parametrize(("value", "expected"), ALLOWED_NETWORKS)
    def test_the_other_sections_are_read(
        self, tmp_path: Path, value: Any, expected: list[str]
    ) -> None:
        manager = load(tmp_path, {**RIGHT, "allowed_networks": value})

        assert manager.get_section("feedback")["prompt_suffix"] == SUFFIX
        assert manager.get_section("web_ui")["port"] == PORT
        assert manager.get_section("notification")["sound_volume"] == VOLUME

    @pytest.mark.parametrize(("value", "expected"), ALLOWED_NETWORKS)
    def test_the_file_is_not_marked_invalid(
        self, tmp_path: Path, value: Any, expected: list[str]
    ) -> None:
        manager = load(tmp_path, {**RIGHT, "allowed_networks": value})

        assert manager._on_disk_config_invalid is False

    @pytest.mark.parametrize("value", BROKEN_VALUES)
    def test_the_log_names_the_key_and_has_no_error(
        self, tmp_path: Path, lines: list[Line], value: Any
    ) -> None:
        """旧代码在这里记一条 ERROR（加载配置文件失败），之后什么都不说；现在是一条 WARNING。"""
        path = write(tmp_path, config_text({**RIGHT, "allowed_networks": value}))

        ConfigManager(str(path)).get_network_security_config()

        warnings = at_least(lines, logging.WARNING)
        assert [text for text in warnings if text.startswith("allowed_networks")]
        assert at_least(lines, logging.ERROR) == []


TYPO_FILE = """\
# my config
[feedback]
prompt_suffix = "R913-SUFFIX"   # keep this comment

[web_ui]
port = 19913

[network_security]
# only my LAN
bind_interface = "127.0.0.1"
allowed_networks = "192.168.1.0/24"   # typo: should be an array
blocked_ips = ["192.168.1.66"]
trusted_hosts = ["my.example"]
api_token = "0123456789abcdef0123456789abcdef"
"""
TYPO_LINE = 'allowed_networks = "192.168.1.0/24"   # typo: should be an array'


class TestSavingAfterTheTypo:
    def test_a_save_writes_the_change_and_keeps_the_text_the_user_wrote(
        self, tmp_path: Path
    ) -> None:
        path = write(tmp_path, TYPO_FILE)
        manager = ConfigManager(str(path))

        manager.update_section("feedback", {"prompt_suffix": "CHANGED"}, save=False)
        manager.force_save()

        text = path.read_text(encoding="utf-8")
        assert 'prompt_suffix = "CHANGED"   # keep this comment' in text
        assert "# only my LAN" in text
        assert TYPO_LINE in text
        assert tomllib.loads(text)["web_ui"]["port"] == 19913

    def test_a_save_does_not_log_an_error(
        self, tmp_path: Path, lines: list[Line]
    ) -> None:
        """第一版修复在这里记一条带堆栈的 ERROR：保存之后的核对拒绝用户自己的笔误。"""
        manager = ConfigManager(str(write(tmp_path, TYPO_FILE)))

        manager.update_section("feedback", {"prompt_suffix": "CHANGED"}, save=False)
        manager.force_save()

        assert at_least(lines, logging.ERROR) == []

    def test_the_delayed_save_of_a_web_ui_change_works_too(
        self, tmp_path: Path
    ) -> None:
        path = write(tmp_path, TYPO_FILE)
        manager = ConfigManager(str(path))

        manager.update_section("notification", {"sound_volume": 33})
        manager.force_save()

        saved = tomllib.loads(path.read_text(encoding="utf-8"))
        assert saved["notification"]["sound_volume"] == 33

    def test_the_effective_security_is_the_same_after_the_save(
        self, tmp_path: Path
    ) -> None:
        path = write(tmp_path, TYPO_FILE)
        manager = ConfigManager(str(path))
        before = manager.get_network_security_config()

        manager.update_section("feedback", {"prompt_suffix": "CHANGED"}, save=False)
        manager.force_save()

        assert ConfigManager(str(path)).get_network_security_config() == before


class TestATypoIntroducedWhileTheServiceRuns:
    def test_the_section_narrows_per_key_and_the_rest_of_the_edit_applies(
        self, tmp_path: Path
    ) -> None:
        path = write(
            tmp_path,
            config_text({**RIGHT, "allowed_networks": ["192.168.1.0/24"]}),
        )
        manager = ConfigManager(str(path))
        assert manager.get_network_security_config()["allowed_networks"] == [
            "192.168.1.0/24"
        ]

        path.write_text(
            config_text(
                {**RIGHT, "allowed_networks": "192.168.1.0/24"}, suffix="EDITED"
            ),
            encoding="utf-8",
        )
        manager.reload()

        section = manager.get_network_security_config()
        assert section == {**EXPECTED_OTHERS, "allowed_networks": LOOPBACK}
        assert manager.get_section("feedback")["prompt_suffix"] == "EDITED"
        assert manager._on_disk_config_invalid is False

    def test_fixing_the_typo_takes_effect_on_the_next_reload(
        self, tmp_path: Path
    ) -> None:
        path = write(
            tmp_path,
            config_text({**RIGHT, "allowed_networks": "192.168.1.0/24"}),
        )
        manager = ConfigManager(str(path))
        assert manager.get_network_security_config()["allowed_networks"] == LOOPBACK

        path.write_text(
            config_text({**RIGHT, "allowed_networks": ["192.168.1.0/24"]}),
            encoding="utf-8",
        )
        manager.reload()

        assert manager.get_network_security_config()["allowed_networks"] == [
            "192.168.1.0/24"
        ]


# 没有 [network_security] 这一段时读出来的样子（R918 起默认只监听本机）
DEFAULTS = {
    "bind_interface": "127.0.0.1",
    "allowed_networks": [*LOOPBACK, "192.168.0.0/16", "10.0.0.0/8", "172.16.0.0/12"],
    "blocked_ips": [],
    "trusted_hosts": [],
    "trusted_proxy_hops": 1,
    "access_control_enabled": True,
    "api_token": "",
    "api_token_rotated_at": "",
}


NOT_A_TABLE = [
    pytest.param(f'network_security = "oops"\n\n{OTHER_SECTIONS}', id="a string"),
    pytest.param(f"network_security = 5\n\n{OTHER_SECTIONS}", id="an integer"),
    pytest.param(f"network_security = [1, 2]\n\n{OTHER_SECTIONS}", id="an array"),
    pytest.param(
        f'{OTHER_SECTIONS}\n[[network_security]]\nbind_interface = "127.0.0.1"\n',
        id="an array of tables",
    ),
]


class TestTheSectionIsNotATable:
    def test_control_a_missing_section_gives_the_defaults(self, tmp_path: Path) -> None:
        manager = ConfigManager(str(write(tmp_path, config_text(None))))

        assert manager.get_network_security_config() == DEFAULTS

    @pytest.mark.parametrize("text", NOT_A_TABLE)
    def test_it_is_treated_like_a_file_that_cannot_be_read(
        self, tmp_path: Path, text: str
    ) -> None:
        """R913 当它没写（读出默认值，放行整个内网）；R919 起不知道用户想要什么，只放行本机。"""
        manager = ConfigManager(str(write(tmp_path, text)))

        assert manager.get_network_security_config() == {
            **DEFAULTS,
            "allowed_networks": LOOPBACK,
        }

    @pytest.mark.parametrize("text", NOT_A_TABLE)
    def test_the_other_sections_are_read(self, tmp_path: Path, text: str) -> None:
        manager = ConfigManager(str(write(tmp_path, text)))

        assert manager.get_section("feedback")["prompt_suffix"] == SUFFIX
        assert manager.get_section("web_ui")["port"] == PORT
        assert manager._on_disk_config_invalid is False

    @pytest.mark.parametrize("text", NOT_A_TABLE)
    def test_the_log_says_so(
        self, tmp_path: Path, lines: list[Line], text: str
    ) -> None:
        path = write(tmp_path, text)

        ConfigManager(str(path)).get_network_security_config()

        said = [t for t in at_least(lines, logging.ERROR) if "不是表" in t]
        assert len(said) == 1
        assert str(path) in said[0]

    @pytest.mark.parametrize("text", NOT_A_TABLE)
    def test_a_save_works_and_keeps_the_line(self, tmp_path: Path, text: str) -> None:
        path = write(tmp_path, text)
        manager = ConfigManager(str(path))

        manager.update_section("feedback", {"prompt_suffix": "CHANGED"}, save=False)
        manager.force_save()

        saved = path.read_text(encoding="utf-8")
        assert 'prompt_suffix = "CHANGED"' in saved
        assert "network_security" in saved


JSON_TWICE = (
    '{\n  "network_security": {\n    "blocked_ips": ["1.2.3.4"],\n'
    '    "blocked_ips": ["5.6.7.8"]\n  }\n}\n'
)


class TestAFileThatIsReallyBrokenIsStillRejected:
    def test_duplicate_arrays_in_json(self, tmp_path: Path) -> None:
        manager = ConfigManager(str(write(tmp_path, JSON_TWICE, name="config.json")))

        assert manager._on_disk_config_invalid is True

    def test_the_check_after_a_save_rejects_duplicate_arrays_too(
        self, tmp_path: Path
    ) -> None:
        manager = ConfigManager(str(write(tmp_path, config_text({**RIGHT}))))
        # 好文件换成有重复数组的 JSON：核对写出去的文件时要拒绝
        manager.config_file = write(tmp_path, JSON_TWICE, name="twice.json")

        with pytest.raises(ConfigValidationError):
            manager._validate_saved_config()

    def test_the_check_after_a_save_rejects_a_file_that_does_not_parse(
        self, tmp_path: Path
    ) -> None:
        manager = ConfigManager(str(write(tmp_path, config_text({**RIGHT}))))
        manager.config_file = write(
            tmp_path, "[web_ui\nport = = 1\n", name="broken.toml"
        )

        with pytest.raises(ValueError):
            manager._validate_saved_config()

    def test_the_security_section_of_such_a_json_file_is_not_trusted_either(
        self, tmp_path: Path
    ) -> None:
        """后一份数组不能顶掉前一份：读 network_security 时也核对，读不出来就是默认值。"""
        manager = ConfigManager(str(write(tmp_path, JSON_TWICE, name="config.json")))

        assert manager.get_network_security_config()["blocked_ips"] == []

    def test_the_check_after_a_save_accepts_what_the_load_accepts(
        self, tmp_path: Path
    ) -> None:
        manager = ConfigManager(str(write(tmp_path, TYPO_FILE)))

        manager._validate_saved_config()


class TestSavingNetworkSecurityRepairsTheFile:
    """Web UI 里保存网络设置：写坏的内容被换成一张正确的表，别的段原样留着。"""

    BROKEN = [
        pytest.param(TYPO_FILE, id="a string for allowed_networks"),
        *NOT_A_TABLE,
    ]

    @pytest.mark.parametrize("text", BROKEN)
    def test_the_save_goes_through(self, tmp_path: Path, text: str) -> None:
        path = write(tmp_path, text)
        manager = ConfigManager(str(path))

        manager.set_network_security_config(
            {
                "bind_interface": "127.0.0.1",
                "allowed_networks": ["192.168.1.0/24"],
                "blocked_ips": ["192.168.1.66"],
            }
        )

        saved = tomllib.loads(path.read_text(encoding="utf-8"))
        assert saved["network_security"]["allowed_networks"] == ["192.168.1.0/24"]
        assert saved["web_ui"]["port"] == 19913
        assert saved["feedback"]["prompt_suffix"] == "R913-SUFFIX"

    @pytest.mark.parametrize("text", BROKEN)
    def test_a_fresh_load_reads_the_repaired_values(
        self, tmp_path: Path, text: str
    ) -> None:
        path = write(tmp_path, text)
        ConfigManager(str(path)).set_network_security_config(
            {
                "bind_interface": "127.0.0.1",
                "allowed_networks": ["192.168.1.0/24"],
                "blocked_ips": ["192.168.1.66"],
            }
        )

        section = ConfigManager(str(path)).get_network_security_config()

        assert section["allowed_networks"] == ["192.168.1.0/24"]
        assert section["blocked_ips"] == ["192.168.1.66"]
        assert section["bind_interface"] == "127.0.0.1"


# ---- 随机对照：文件这一层不自己拒绝任何值 -------------------------------------------------

CASES = 500

POOLS: dict[str, list[Any]] = {
    "bind_interface": [
        "127.0.0.1",
        "0.0.0.0",
        "::1",
        "::",
        "localhost",
        "",
        "999.1.1.1",
        "  127.0.0.1  ",
        5,
        True,
        1.5,
        ["127.0.0.1"],
    ],
    "allowed_networks": [
        ["192.168.1.0/24"],
        ["10.0.0.0/8", "172.16.0.0/12"],
        [],
        ["nonsense"],
        [5, "192.168.0.0/16"],
        ["  10.0.0.0/8  ", ""],
        "192.168.1.0/24",
        5,
        1.5,
        True,
        {"net": "10.0.0.0/8"},
        [["10.0.0.0/8"]],
        ["::ffff:1.2.3.4"],
        ["10.0.0.5/8", "10.0.0.0/8"],
        [True],
        [1.5, "10.0.0.0/8"],
    ],
    "blocked_ips": [
        [],
        ["192.168.1.66"],
        ["1.2.3.4/32", "bad"],
        "192.168.1.66",
        5,
        [5],
        {"ip": "1.2.3.4"},
    ],
    "trusted_hosts": [
        [],
        ["my.example"],
        ["A.Example", " b.example "],
        "my.example",
        5,
        [5, "ok.example"],
        ["not a host!!"],
    ],
    "trusted_proxy_hops": [0, 1, 3, 8, 9, -1, "2", 1.5, True, [1]],
    "access_control_enabled": [True, False, "false", "true", 0, 1, "yes", [], {"a": 1}],
    "enable_access_control": [True, False, "no", 0],
    "api_token": [
        TOKEN,
        "short",
        "",
        5,
        True,
        [TOKEN],
        "  " + TOKEN + "  ",
        "has space in it 0123456789",
    ],
    "api_token_rotated_at": [
        "2026-01-02T03:04:05Z",
        "2026-01-02T03:04:05+00:00",
        "yesterday",
        5,
        "",
    ],
    "some_other_key": [1, "x", [1], {"a": 1}],
}


def random_table(rng: random.Random) -> dict[str, Any]:
    return {key: rng.choice(pool) for key, pool in POOLS.items() if rng.random() < 0.55}


class TestTheFileLayerRejectsNothingOfItsOwn:
    def test_reading_a_file_equals_validating_the_parsed_table(
        self, tmp_path: Path
    ) -> None:
        rng = random.Random(913)
        verifier = ConfigManager(str(tmp_path / "verifier.toml"))
        wrongly_typed_allowed_networks = 0
        unusable_block_lists = 0
        mismatches: list[tuple[Any, Any, Any]] = []

        for index in range(CASES):
            table = random_table(rng)
            if "allowed_networks" in table and not (
                isinstance(table["allowed_networks"], list)
                and all(isinstance(item, str) for item in table["allowed_networks"])
            ):
                wrongly_typed_allowed_networks += 1
            path = write(tmp_path, config_text(table), name=f"case{index}.toml")
            manager = ConfigManager(str(path))

            parsed = tomllib.loads(path.read_text(encoding="utf-8"))
            if blocked_ips_problem(table.get("blocked_ips")) is not None:
                # R920：拦截名单读不懂，这一段不当成一份能用的配置；没有上一份，就只放行本机
                unusable_block_lists += 1
                expected = {**DEFAULTS, "allowed_networks": LOOPBACK}
            else:
                expected = verifier._validate_network_security_config(
                    parsed.get("network_security")
                )
            actual = manager.get_network_security_config()
            others_read = (
                manager.get_section("feedback")["prompt_suffix"] == SUFFIX
                and manager.get_section("web_ui")["port"] == PORT
                and manager._on_disk_config_invalid is False
            )
            if actual != expected or not others_read:
                mismatches.append((table, actual, expected))

        # 生成器要真的撞上写坏的 allowed_networks，否则这条测试什么都没证明
        assert wrongly_typed_allowed_networks >= 100
        assert unusable_block_lists >= 100
        assert not mismatches, mismatches[:3]


# ---- 全新进程：真实的监听地址、端口、各来源地址的状态码 ------------------------------

PEERS = ["127.0.0.1", "192.168.1.50", "192.168.1.66", "10.1.2.3", "8.8.8.8"]

SCRIPT = textwrap.dedent(
    """
    import json
    import sys

    from ai_intervention_agent.service_manager import get_web_ui_config
    from ai_intervention_agent.web_ui import WebFeedbackUI

    config, _ = get_web_ui_config()
    ui = WebFeedbackUI(prompt="x", task_id="t", auto_resubmit_timeout=0, port=config.port)
    ui.app.config["TESTING"] = False
    ui.limiter.enabled = False
    client = ui.app.test_client()
    status = {}
    for ip in json.loads(sys.argv[1]):
        response = client.get(
            "/api/health",
            environ_base={"REMOTE_ADDR": ip},
            headers={"Host": "127.0.0.1:%d" % config.port},
        )
        status[ip] = response.status_code
    print(json.dumps({"host": config.host, "port": config.port, "status": status}))
    """
)


def in_a_fresh_process(path: Path) -> dict[str, Any]:
    env = {
        name: value
        for name, value in os.environ.items()
        if not name.startswith("AI_INTERVENTION_AGENT_WEB_UI")
    }
    env["AI_INTERVENTION_AGENT_CONFIG_FILE"] = str(path)
    done = subprocess.run(
        [sys.executable, "-c", SCRIPT, json.dumps(PEERS)],
        env=env,
        cwd=path.parent,
        capture_output=True,
        text=True,
        check=True,
        timeout=120,
    )
    return json.loads(done.stdout.strip().splitlines()[-1])


ENFORCED = {**RIGHT, "access_control_enabled": True}


class TestAFreshProcessEnforcesWhatTheFileSays:
    def test_one_wrong_value_leaves_the_server_on_loopback_and_closed(
        self, tmp_path: Path
    ) -> None:
        path = write(
            tmp_path, config_text({**ENFORCED, "allowed_networks": "192.168.1.0/24"})
        )

        result = in_a_fresh_process(path)

        assert result["host"] == "127.0.0.1"
        assert result["port"] == PORT
        assert result["status"] == {
            "127.0.0.1": 200,
            "192.168.1.50": 403,
            "192.168.1.66": 403,
            "10.1.2.3": 403,
            "8.8.8.8": 403,
        }

    def test_the_same_file_written_correctly_gives_the_listed_network_access(
        self, tmp_path: Path
    ) -> None:
        """对照：写对的同一份配置，只有 192.168.1.0/24 放行，被拉黑的那个仍然拒绝。"""
        path = write(
            tmp_path,
            config_text({**ENFORCED, "allowed_networks": ["192.168.1.0/24"]}),
        )

        result = in_a_fresh_process(path)

        assert result["host"] == "127.0.0.1"
        assert result["port"] == PORT
        assert result["status"] == {
            "127.0.0.1": 403,
            "192.168.1.50": 200,
            "192.168.1.66": 403,
            "10.1.2.3": 403,
            "8.8.8.8": 403,
        }
