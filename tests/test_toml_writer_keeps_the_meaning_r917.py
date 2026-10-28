"""R917：保存配置时，写出去的 TOML 读回来必须还是原来的意思。

现象（旧代码实测）
==================

保存配置时，TOML 文件是让 tomlkit 在原来的排版上改的（保留注释和格式）。有两类排版，它改出来的
是另一份意思的文件，而保存函数不核对，直接把文件换掉。

**一、用点号键写的段**（``notification.sound_volume = 33`` 再接一行 ``notification.bark_enabled =
false``）。同一段由几行拼成，tomlkit 给出的是 ``OutOfOrderTableProxy``，不是 ``Table``；保存函数以为
它“不是表”，把整段换成一个 dict，输出 ``[notification]``，后面接着 ``notification.sound_volume =
58``——表里套着自己。读回来 ``notification`` 里只有一个叫 ``notification`` 的键，所有设置都回到默认值：

====================================  =========================  ====================
保存之后重新读文件                      文件里原来                  旧代码读回来
====================================  =========================  ====================
``notification.sound_volume``          33                         **80**（默认）
``notification.retry_count``           刚设成 7                    **3**（默认）
====================================  =========================  ====================

``network_security`` 也一样（它有自己的保存函数，同样的写法）。点号键写的 ``bind_interface`` 和
``blocked_ips``，一次令牌更新（``update_network_security_config``）之后：``bind_interface`` 读回来是
**``0.0.0.0``**，黑名单 **没了**，令牌也没保存上。和 R915 是同一类结果：悄悄放开访问控制。

**二、内联表和点号键混用**。``web_ui = {...}`` 这样的内联表被换成 ``[web_ui]`` 表头，原地换，而它
后面根部的点号键（``network_security.bind_interface = ...``）就归到了这张表底下::

    web_ui = {port = 18792, host = "127.0.0.1"}
    network_security.bind_interface = "127.0.0.1"
    network_security.blocked_ips = ["192.168.1.66"]

    [notification]
    sound_volume = 33

只改一个 ``web_ui`` 的设置再保存：``network_security`` 被收进 ``web_ui`` 里，读回来 ``bind_interface``
是 ``0.0.0.0``、黑名单是空的。

随机排版（表、点号键、内联表、被别的表隔开的表，混着来）经真实 ``ConfigManager`` 保存：旧代码
300 个里有 199 个读回来不对（通用保存 166 个，``network_security`` 的保存 33 个），全都和点号键有关。

修复
====

两层：

1. **能原地改的就原地改**。``OutOfOrderTableProxy`` 和 ``Table`` 一样按键读写，写进去的地方也对，
   ``_update_toml_table`` 把它当表处理（嵌套的也是）。点号键的文件保存之后仍是点号键，被别的表隔开
   的表仍在原来的位置，注释照旧保留；
2. **写出去之前核对**（``_toml_as_intended``）：读回来必须包含这次的更改，原文件里没动的顶层键
   （比如 ``network_security``）必须原样还在。对不上，就改用整份重新生成：注释和排版不再保留，设置
   不变，日志里一条 WARNING；重新生成的也对不上，就放弃写入（抛 ``ValueError``），文件保持原样。

测试矩阵
========

A. 点号键写的段（通用保存）：用户的值保留、新值写进去、不出现表里套着自己，重新读文件一致；点号键
   的排版保留、没有触发重新生成；每段一个点号键的写法（旧代码也对）；
B. 点号键写的 ``network_security``（令牌更新、整段设置两条路）：重新读文件，监听地址、黑名单、
   令牌都在，排版保留；
C. 被别的表隔开的表：嵌套的子表保留，表头的先后顺序不变；表里嵌套的点号键也原地改；
D. 内联表和点号键混用：``network_security`` 仍在顶层、值不变，其他段的值不变，重新生成只告警一次，
   下一次保存不再告警；
E. 对照：带注释的普通表、随包的 ``config.toml.default`` 保存之后注释都在，不触发重新生成；
F. 重新生成的也读不回来：放弃写入，文件保持原样；
G. 核对用的三个小函数（相同、包含、叠加）；
H. 随机排版：200 种，两条保存路径，每一种读回来的内容都要对，两条路径（原地改、重新生成）都走到。

共 30 个。旧代码上 26 个失败、4 个通过：A、B、C、D、H 的 13 个是上面的两类问题；F、G 的 13 个测的是
这次新增的核对和小函数，旧代码里没有；通过的 4 个是对照（E 的 3 个，A 里每段一个点号键的 1 个）。
一点改动的变异检验 15 个，全部被杀。
"""

from __future__ import annotations

import copy
import logging
import math
import random
import tomllib
from collections import Counter
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
import tomlkit

from ai_intervention_agent.config_manager import ConfigManager
from ai_intervention_agent.config_modules import toml_engine
from ai_intervention_agent.config_modules.toml_engine import (
    TomlEngineMixin,
    _contains_toml_data,
    _merged_toml_data,
    _same_toml_data,
)
from ai_intervention_agent.enhanced_logging import EnhancedLogger

REPO_ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = REPO_ROOT / "config.toml.default"
TOKEN = "0123456789abcdef0123456789abcdef"

Line = tuple[int, str]


class Collect(logging.Handler):
    def __init__(self, seen: list[Line]) -> None:
        super().__init__()
        self.seen = seen

    def emit(self, record: logging.LogRecord) -> None:
        self.seen.append((record.levelno, record.getMessage()))


@pytest.fixture
def lines(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[Line]]:
    """包里每一条日志的 ``(级别, 文本)``，在 ``EnhancedLogger`` 去重之前记下来。"""
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


def rebuilt(lines: list[Line]) -> list[str]:
    """改用整份重新生成时记的那条 WARNING。"""
    return [
        text
        for level, text in lines
        if level == logging.WARNING and "重新生成整个文件" in text
    ]


def put(tmp_path: Path, text: str, name: str = "config.toml") -> Path:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def read(path: Path) -> dict[str, Any]:
    return tomllib.loads(path.read_text(encoding="utf-8"))


def save_notification(manager: ConfigManager, **changes: Any) -> None:
    manager.update_section("notification", changes)
    manager.force_save()


# ---- A. 点号键写的段（通用保存）--------------------------------------------------------------------

DOTTED = (
    "web_ui.port = 18792\n"
    'web_ui.host = "127.0.0.1"\n'
    "notification.sound_volume = 33\n"
    "notification.bark_enabled = false\n"
)


class TestSectionsWrittenWithDottedKeys:
    def test_the_users_values_survive_and_the_new_one_is_written(
        self, tmp_path: Path
    ) -> None:
        path = put(tmp_path, DOTTED)
        manager = ConfigManager(str(path))

        save_notification(manager, retry_count=7)

        saved = read(path)
        assert saved["notification"]["sound_volume"] == 33
        assert saved["notification"]["bark_enabled"] is False
        assert saved["notification"]["retry_count"] == 7
        assert saved["web_ui"]["port"] == 18792
        assert saved["web_ui"]["host"] == "127.0.0.1"
        assert "notification" not in saved["notification"]
        assert "web_ui" not in saved["web_ui"]

    def test_reading_the_file_again_gives_the_same_settings(
        self, tmp_path: Path
    ) -> None:
        path = put(tmp_path, DOTTED)
        save_notification(ConfigManager(str(path)), retry_count=7)

        fresh = ConfigManager(str(path))

        assert fresh.get_section("notification")["sound_volume"] == 33
        assert fresh.get_section("notification")["retry_count"] == 7
        assert fresh.get_section("web_ui")["port"] == 18792

    def test_the_dotted_layout_is_kept_and_nothing_is_rebuilt(
        self, tmp_path: Path, lines: list[Line]
    ) -> None:
        path = put(tmp_path, DOTTED)

        save_notification(ConfigManager(str(path)), retry_count=7)

        text = path.read_text(encoding="utf-8")
        assert "notification.sound_volume = 33" in text
        assert "notification.retry_count = 7" in text
        assert "[notification]" not in text
        assert "[web_ui]" not in text
        assert rebuilt(lines) == []

    def test_one_key_per_section_was_already_fine(self, tmp_path: Path) -> None:
        path = put(tmp_path, "web_ui.port = 18792\nnotification.sound_volume = 33\n")

        save_notification(ConfigManager(str(path)), retry_count=7)

        saved = read(path)
        assert saved["notification"]["sound_volume"] == 33
        assert saved["notification"]["retry_count"] == 7
        assert saved["web_ui"]["port"] == 18792


# ---- B. 点号键写的 network_security -----------------------------------------------------------------

DOTTED_NETWORK = (
    'network_security.bind_interface = "127.0.0.1"\n'
    'network_security.blocked_ips = ["192.168.1.66"]\n'
    "\n"
    "[web_ui]\n"
    "port = 18792\n"
)


class TestNetworkSecurityWrittenWithDottedKeys:
    def test_a_token_update_keeps_the_listen_address_and_the_block_list(
        self, tmp_path: Path
    ) -> None:
        path = put(tmp_path, DOTTED_NETWORK)
        manager = ConfigManager(str(path))

        manager.update_network_security_config({"api_token": TOKEN})

        settings = ConfigManager(str(path)).get_network_security_config()
        assert settings["bind_interface"] == "127.0.0.1"
        assert settings["blocked_ips"] == ["192.168.1.66"]
        assert settings["api_token"] == TOKEN
        assert "network_security" not in read(path)["network_security"]

    def test_setting_the_whole_section_keeps_the_rest_of_the_file(
        self, tmp_path: Path
    ) -> None:
        path = put(tmp_path, DOTTED_NETWORK)
        manager = ConfigManager(str(path))
        wanted = manager.get_network_security_config()
        wanted["blocked_ips"] = ["192.168.1.66", "10.9.9.9"]

        manager.set_network_security_config(wanted)

        settings = ConfigManager(str(path)).get_network_security_config()
        assert settings["bind_interface"] == "127.0.0.1"
        assert settings["blocked_ips"] == ["192.168.1.66", "10.9.9.9"]
        assert read(path)["web_ui"]["port"] == 18792

    def test_the_dotted_layout_is_kept_and_nothing_is_rebuilt(
        self, tmp_path: Path, lines: list[Line]
    ) -> None:
        path = put(tmp_path, DOTTED_NETWORK)

        ConfigManager(str(path)).update_network_security_config({"api_token": TOKEN})

        text = path.read_text(encoding="utf-8")
        assert 'network_security.bind_interface = "127.0.0.1"' in text
        assert "[network_security]" not in text
        assert rebuilt(lines) == []


# ---- C. 被别的表隔开的表 -----------------------------------------------------------------------------

SPLIT = (
    "[notification]\n"
    "sound_volume = 33\n"
    "\n"
    "[feedback]\n"
    "backend_max_wait = 500\n"
    "\n"
    "[notification.extra]\n"
    "note = 1\n"
)


class TestATableSplitByAnotherTable:
    def test_the_sub_table_survives_and_the_headers_keep_their_order(
        self, tmp_path: Path, lines: list[Line]
    ) -> None:
        path = put(tmp_path, SPLIT)

        save_notification(ConfigManager(str(path)), retry_count=7)

        text = path.read_text(encoding="utf-8")
        saved = read(path)
        assert saved["notification"]["extra"] == {"note": 1}
        assert saved["notification"]["sound_volume"] == 33
        assert saved["notification"]["retry_count"] == 7
        assert saved["feedback"]["backend_max_wait"] == 500
        assert (
            text.index("[notification]")
            < text.index("[feedback]")
            < text.index("[notification.extra]")
        )
        assert rebuilt(lines) == []

    def test_dotted_keys_inside_a_table_are_updated_in_place(
        self, tmp_path: Path, lines: list[Line]
    ) -> None:
        path = put(
            tmp_path, "[feedback]\nsub.a = 1\nsub.b = 2\nbackend_max_wait = 500\n"
        )
        manager = ConfigManager(str(path))

        manager.update_section("feedback", {"sub": {"a": 5, "b": 2, "c": 3}})
        manager.force_save()

        saved = read(path)
        assert saved["feedback"]["sub"] == {"a": 5, "b": 2, "c": 3}
        assert saved["feedback"]["backend_max_wait"] == 500
        assert "feedback" not in saved["feedback"]
        assert "[feedback.sub]" not in path.read_text(encoding="utf-8")
        assert rebuilt(lines) == []


# ---- D. 内联表和点号键混用 ---------------------------------------------------------------------------

INLINE_THEN_DOTTED = (
    'web_ui = {port = 18792, host = "127.0.0.1"}\n'
    'network_security.bind_interface = "127.0.0.1"\n'
    'network_security.blocked_ips = ["192.168.1.66"]\n'
    "\n"
    "[notification]\n"
    "sound_volume = 33\n"
)

INLINE_BETWEEN_DOTTED = (
    "notification.retry_count = 4\n"
    'network_security.bind_interface = "127.0.0.1"\n'
    "notification.sound_volume = 33\n"
    'feedback = {resubmit_prompt = "go on", backend_max_wait = 500}\n'
    'network_security.blocked_ips = ["192.168.1.66"]\n'
    "notification.bark_enabled = false\n"
)


class TestAnInlineTableNextToDottedKeys:
    def test_network_security_is_not_pulled_into_the_section_that_was_edited(
        self, tmp_path: Path, lines: list[Line]
    ) -> None:
        path = put(tmp_path, INLINE_THEN_DOTTED)
        manager = ConfigManager(str(path))

        manager.update_section("web_ui", {"debug": True})
        manager.force_save()

        saved = read(path)
        assert saved["network_security"] == {
            "bind_interface": "127.0.0.1",
            "blocked_ips": ["192.168.1.66"],
        }
        assert "network_security" not in saved["web_ui"]
        assert saved["web_ui"]["debug"] is True
        assert saved["web_ui"]["port"] == 18792
        assert saved["notification"]["sound_volume"] == 33
        settings = ConfigManager(str(path)).get_network_security_config()
        assert settings["bind_interface"] == "127.0.0.1"
        assert settings["blocked_ips"] == ["192.168.1.66"]
        assert len(rebuilt(lines)) == 1

    def test_every_section_keeps_its_values(
        self, tmp_path: Path, lines: list[Line]
    ) -> None:
        path = put(tmp_path, INLINE_BETWEEN_DOTTED)
        manager = ConfigManager(str(path))

        manager.update_section("feedback", {"backend_max_wait": 700})
        manager.force_save()

        saved = read(path)
        assert saved["notification"]["retry_count"] == 4
        assert saved["notification"]["sound_volume"] == 33
        assert saved["notification"]["bark_enabled"] is False
        assert saved["feedback"]["resubmit_prompt"] == "go on"
        assert saved["feedback"]["backend_max_wait"] == 700
        assert saved["network_security"] == {
            "bind_interface": "127.0.0.1",
            "blocked_ips": ["192.168.1.66"],
        }
        assert len(rebuilt(lines)) == 1

    def test_the_next_save_does_not_warn_again(
        self, tmp_path: Path, lines: list[Line]
    ) -> None:
        path = put(tmp_path, INLINE_THEN_DOTTED)
        manager = ConfigManager(str(path))
        manager.update_section("web_ui", {"debug": True})
        manager.force_save()
        assert len(rebuilt(lines)) == 1

        manager.update_section("web_ui", {"debug": False})
        manager.force_save()

        assert len(rebuilt(lines)) == 1
        assert read(path)["web_ui"]["debug"] is False

    def test_the_warning_says_what_happens(
        self, tmp_path: Path, lines: list[Line]
    ) -> None:
        path = put(tmp_path, INLINE_THEN_DOTTED)

        manager = ConfigManager(str(path))
        manager.update_section("web_ui", {"debug": True})
        manager.force_save()

        (warning,) = rebuilt(lines)
        assert "设置不变" in warning
        assert "注释和排版不再保留" in warning


# ---- E. 对照：普通文件不受影响 -----------------------------------------------------------------------

COMMENTED = """\
# my settings
[notification]
# how loud
sound_volume = 33  # percent
bark_enabled = false

# the web page
[web_ui]
port = 18792
"""


def comment_lines(text: str) -> set[str]:
    """整行都是注释的那些行（数组里跟在元素后面的注释，数组被整个改写时本来就不保留）。"""
    return {line.strip() for line in text.splitlines() if line.strip().startswith("#")}


class TestOrdinaryFilesKeepTheirComments:
    def test_a_table_file_with_comments(
        self, tmp_path: Path, lines: list[Line]
    ) -> None:
        path = put(tmp_path, COMMENTED)

        save_notification(ConfigManager(str(path)), retry_count=7)

        text = path.read_text(encoding="utf-8")
        for comment in ("# my settings", "# how loud", "# percent", "# the web page"):
            assert comment in text
        assert read(path)["notification"]["retry_count"] == 7
        assert rebuilt(lines) == []

    def test_the_shipped_template(self, tmp_path: Path, lines: list[Line]) -> None:
        path = put(tmp_path, TEMPLATE.read_text(encoding="utf-8"))
        before = comment_lines(path.read_text(encoding="utf-8"))

        save_notification(ConfigManager(str(path)), sound_volume=41)

        text = path.read_text(encoding="utf-8")
        assert read(path)["notification"]["sound_volume"] == 41
        assert before <= comment_lines(text)
        assert rebuilt(lines) == []

    def test_a_token_update_on_the_shipped_template(
        self, tmp_path: Path, lines: list[Line]
    ) -> None:
        path = put(tmp_path, TEMPLATE.read_text(encoding="utf-8"))
        before = comment_lines(path.read_text(encoding="utf-8"))

        ConfigManager(str(path)).update_network_security_config({"api_token": TOKEN})

        assert read(path)["network_security"]["api_token"] == TOKEN
        assert before <= comment_lines(path.read_text(encoding="utf-8"))
        assert rebuilt(lines) == []


# ---- F. 重新生成的也读不回来 -------------------------------------------------------------------------


class _Engine(TomlEngineMixin):
    _original_content: str = ""

    @staticmethod
    def _exclude_network_security(config: dict[str, Any]) -> dict[str, Any]:
        return {k: v for k, v in config.items() if k != "network_security"}


class TestWhenTheRebuiltFileCannotBeReadBackEither:
    def test_nothing_is_written(self, tmp_path: Path) -> None:
        path = put(tmp_path, INLINE_THEN_DOTTED)
        manager = ConfigManager(str(path))
        before = path.read_bytes()
        manager.update_section("web_ui", {"debug": True})

        with (
            patch.object(toml_engine, "_same_toml_data", return_value=False),
            pytest.raises(ValueError, match="放弃写入"),
        ):
            manager.force_save()

        assert path.read_bytes() == before

    def test_the_engine_raises_instead_of_returning_a_wrong_file(self) -> None:
        engine = _Engine()
        engine._original_content = INLINE_THEN_DOTTED

        with (
            patch.object(toml_engine, "_same_toml_data", return_value=False),
            pytest.raises(ValueError, match="放弃写入"),
        ):
            engine._save_toml_with_comments({"web_ui": {"port": 18792, "debug": True}})


# ---- G. 核对用的小函数 -------------------------------------------------------------------------------


class TestTheComparisonHelpers:
    def test_same_ignores_the_order_of_keys(self) -> None:
        assert _same_toml_data({"a": 1, "b": 2}, {"b": 2, "a": 1})

    def test_same_sees_a_missing_or_extra_key(self) -> None:
        assert not _same_toml_data({"a": 1}, {"a": 1, "b": 2})
        assert not _same_toml_data({"a": 1, "b": 2}, {"a": 1})

    def test_same_treats_a_tuple_as_a_list_but_keeps_the_order(self) -> None:
        assert _same_toml_data(("a", "b"), ["a", "b"])
        assert not _same_toml_data(["a", "b"], ["b", "a"])
        assert not _same_toml_data(["a"], ["a", "b"])

    def test_same_does_not_mix_a_bool_with_an_integer(self) -> None:
        assert not _same_toml_data(True, 1)
        assert not _same_toml_data(0, False)
        assert _same_toml_data(True, True)

    def test_same_treats_nan_as_nan(self) -> None:
        assert _same_toml_data({"x": math.nan}, {"x": math.nan})
        assert not _same_toml_data(math.nan, 1.0)

    def test_same_looks_inside_nested_values(self) -> None:
        assert _same_toml_data({"a": [{"b": (1, 2)}]}, {"a": [{"b": [1, 2]}]})
        assert not _same_toml_data({"a": [{"b": 1}]}, {"a": [{"b": 2}]})

    def test_contains_ignores_extra_keys_in_the_whole(self) -> None:
        assert _contains_toml_data({"a": 1, "b": {"c": 2, "d": 3}}, {"b": {"c": 2}})

    def test_contains_needs_every_key_of_the_part(self) -> None:
        assert not _contains_toml_data({"a": 1}, {"a": 1, "b": 2})
        assert not _contains_toml_data({"a": {"c": 1}}, {"a": {"c": 1, "d": 2}})

    def test_contains_compares_values_that_are_not_tables_exactly(self) -> None:
        assert not _contains_toml_data({"a": [1, 2, 3]}, {"a": [1, 2]})
        assert not _contains_toml_data({"a": 1}, {"a": {"b": 1}})
        assert not _contains_toml_data({"a": {"b": 1}}, {"a": 1})

    def test_merged_merges_tables_and_replaces_everything_else(self) -> None:
        original = {"a": {"x": 1, "y": 2}, "b": [1, 2], "c": "text", "keep": 9}
        update = {"a": {"y": 5, "z": 6}, "b": [3], "c": {"now": "a table"}}

        assert _merged_toml_data(original, update) == {
            "a": {"x": 1, "y": 5, "z": 6},
            "b": [3],
            "c": {"now": "a table"},
            "keep": 9,
        }

    def test_merged_does_not_change_its_arguments(self) -> None:
        original = {"a": {"x": 1}}
        update = {"a": {"y": 2}}

        _merged_toml_data(original, update)

        assert original == {"a": {"x": 1}}
        assert update == {"a": {"y": 2}}


# ---- H. 随机排版 -------------------------------------------------------------------------------------

SECTIONS: dict[str, dict[str, Any]] = {
    "web_ui": {"port": 18792, "host": "127.0.0.1", "debug": True},
    "notification": {
        "sound_volume": 33,
        "retry_count": 4,
        "bark_enabled": False,
        "bark_url": "https://bark.example",
    },
    "feedback": {
        "backend_max_wait": 500,
        "resubmit_prompt": "go on",
        "skill_dirs": ["auto", "/tmp/skills"],
    },
    "mdns": {"enabled": False, "hostname": "box.local"},
}
NETWORK = {
    "bind_interface": "127.0.0.1",
    "allowed_networks": ["127.0.0.0/8", "192.168.1.0/24"],
    "blocked_ips": ["192.168.1.66"],
}
NEW_VALUES: dict[str, Any] = {
    "port": 18793,
    "host": "0.0.0.0",
    "debug": False,
    "sound_volume": 55,
    "retry_count": 9,
    "bark_enabled": True,
    "bark_url": "https://other.example",
    "backend_max_wait": 700,
    "resubmit_prompt": "again",
    "skill_dirs": ["auto"],
    "enabled": True,
    "hostname": "other.local",
}
STYLES = ["table", "table", "dotted", "inline", "split"]
LAYOUTS = 200


def value_text(value: Any) -> str:
    return tomlkit.item(value).as_string()


def render(rng: random.Random) -> tuple[str, dict[str, str]]:
    """一份随机排版的配置文件：每一段随机选一种写法，根部的行和表块的先后也随机。"""
    styles: dict[str, str] = {}
    root: list[str] = []
    blocks: list[str] = []
    sub_tables: list[str] = []
    for name, values in {**SECTIONS, "network_security": NETWORK}.items():
        style = rng.choice(STYLES)
        styles[name] = style
        items = list(values.items())
        rng.shuffle(items)
        if style == "dotted":
            root += [f"{name}.{k} = {value_text(v)}" for k, v in items]
        elif style == "inline":
            body = ", ".join(f"{k} = {value_text(v)}" for k, v in items)
            root.append(f"{name} = {{{body}}}")
        else:
            body_lines = [f"[{name}]"]
            for k, v in items:
                if rng.random() < 0.3:
                    body_lines.append(f"# about {k}")
                body_lines.append(f"{k} = {value_text(v)}")
            blocks.append("\n".join(body_lines))
            if style == "split":
                sub_tables.append(f"[{name}.extra]\nnote = 1")
    rng.shuffle(root)
    rng.shuffle(blocks)
    parts = ["\n".join(root)] if root else []
    return "\n\n".join(parts + blocks + sub_tables) + "\n", styles


class TestRandomLayouts:
    def test_both_writers_keep_the_meaning_of_every_layout(
        self, tmp_path: Path, lines: list[Line]
    ) -> None:
        tallies: Counter[str] = Counter()
        problems: list[str] = []

        for seed in range(LAYOUTS):
            rng = random.Random(seed)
            text, styles = render(rng)
            try:
                truth = tomllib.loads(text)
                if truth != tomlkit.parse(text).unwrap():
                    raise ValueError("the two parsers disagree")
            except ValueError as error:  # 排版生成器本身出了问题，不是被测代码的事
                problems.append(
                    f"seed {seed}: the generated file is not valid: {error}"
                )
                continue
            path = put(tmp_path, text, f"layout{seed}.toml")
            manager = ConfigManager(str(path))

            want = copy.deepcopy(SECTIONS)
            for name, style in styles.items():
                if style == "split":
                    want.setdefault(name, {})["extra"] = {"note": 1}
            for name in SECTIONS:
                key = rng.choice(list(SECTIONS[name]))
                manager.update_section(name, {key: NEW_VALUES[key]})
                want[name][key] = NEW_VALUES[key]

            warned = len(rebuilt(lines))
            manager.force_save()
            tallies["rebuilt" if len(rebuilt(lines)) > warned else "in place"] += 1
            saved = read(path)
            for name, values in want.items():
                if name == "network_security":
                    continue
                section = saved.get(name, {})
                if name in section:
                    problems.append(f"seed {seed}: {name} is nested inside itself")
                for key, value in values.items():
                    if section.get(key) != value:
                        problems.append(
                            f"seed {seed}: {name}.{key} is {section.get(key)!r}, "
                            f"want {value!r} ({styles})"
                        )
            expected_network = (
                {**NETWORK, "extra": {"note": 1}}
                if (styles["network_security"] == "split")
                else NETWORK
            )
            if saved.get("network_security") != expected_network:
                problems.append(
                    f"seed {seed}: network_security became {saved.get('network_security')!r}"
                )

            manager.update_network_security_config(
                {"api_token": TOKEN, "blocked_ips": ["192.168.1.66", "10.9.9.9"]}
            )
            after_network = read(path)
            for name in want:
                if name != "network_security" and after_network.get(name) != saved.get(
                    name
                ):
                    problems.append(
                        f"seed {seed}: the network_security save changed {name}"
                    )
            settings = ConfigManager(str(path)).get_network_security_config()
            if (
                settings["bind_interface"] != "127.0.0.1"
                or settings["blocked_ips"] != ["192.168.1.66", "10.9.9.9"]
                or settings["api_token"] != TOKEN
            ):
                problems.append(
                    f"seed {seed}: reloaded network settings are {settings!r}"
                )

        assert problems[:5] == []
        # 两条路径都走到了，不是只走了其中一条
        assert tallies["in place"] >= 100, tallies
        assert tallies["rebuilt"] >= 30, tallies
