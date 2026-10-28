"""R920：``blocked_ips`` 里有读不懂的东西，这一段和读不出来的文件一样不放开任何东西。

现象（全新进程 + 真实 Web UI，旧代码实测）
==========================================

``network_security`` 里每一项写坏了，退回的都是更保守的值：``bind_interface`` 退回 ``127.0.0.1``，
``access_control_enabled`` 退回 ``True``，``allowed_networks`` 退回只放行本机，``trusted_hosts`` 丢掉
读不懂的就是少信任一个，令牌写坏了就当没配置。只有 ``blocked_ips`` 反过来：拦截名单丢掉一项，
那个地址就没有被拦住。

配置：``allowed_networks = ["127.0.0.0/8", "10.0.0.0/8"]``，要拦的是 ``10.9.9.9``。

  新进程，各个来源得到的状态码（旧代码 → 新代码）::

    blocked_ips 写成               10.1.2.3    10.9.9.9
    ["10.9.9.9"]（写对）           200         403          新旧一样
    "10.9.9.9"（字符串）           200 → 403   200 → 403
    5 / { ip = "10.9.9.9" }        200 → 403   200 → 403
    ["10.9.9.999"]（拼错）         200 → 403   200 → 403
    ["10.9.9.9", "10.9.9.999"]     200 → 403   403          旧代码里还拦着写对的那一项
    ["10.9.9.9", 7]                200 → 403   403          同上

  运行中的 Web UI，文件依次改成：好、字符串、好、拼错、好；10.9.9.9 的状态码，旧代码是
  403、200、403、200、403（每次改坏，拦截名单就被忘掉），新代码一直是 403，10.1.2.3 一直是 200
  （改坏的那一版没有生效，生效的还是上一份好配置）。

修复
====

``ConfigManager.get_network_security_config`` 读到的 ``blocked_ips`` 不是列表、或者有不是 IP 地址也
不是网段的条目，就交给读不出来的文件用的那个函数（``_network_security_when_unreadable``，R915）：
服务已经在跑，就继续用上一份读到的配置；刚启动、没有上一份，就只监听 ``127.0.0.1``、只放行本机
回环。日志里一条 ERROR，写明文件路径、``network_security.blocked_ips`` 和哪几项读不懂（第几项，
最多列五个，再多写个数），不写内容：读不懂的那一项可能是贴错了地方的令牌。文件里的其他段照常读，
文件不标记为无效。

这是 nginx 对待写错的配置的办法：旧的继续跑，新的不上线，直到改好。放行名单不需要这样：丢掉一项只是
少放行一个，本来就更保守。

不变的：没写（TOML 里没有这个键，JSON 里是 ``null``）、空列表、只有空白的条目（静默跳过）、写成
``::ffff:10.9.9.9`` 的地址、带主机位的网段（``10.9.9.5/24``）、重复的条目，都和以前一样。写入一侧
（``set_network_security_config`` / ``update_network_security_config``）不变：调用方给了读不懂的条目，
照旧丢掉并记 WARNING。

判断“哪些条目读不懂”和 ``normalize_ip_entries`` 用的是同一份（``_judge_ip_entry``），不会出现一边
丢掉了、另一边觉得没问题。

测试矩阵
========

A. 十七种写法（九种不是列表，其中四种是“空”的值；八种条目有问题）× TOML / JSON，刚启动：
   只放行本机回环；``get_section`` 给同样的结果；一条 ERROR 写明文件路径、键名、说明；写的内容
   不出现在日志里；文件里的其他段照常读、文件不标记为无效；修好之后下一次 ``reload()`` 就生效；
   第二次又读坏时日志仍然说“没有读到过任何配置”（关死的配置不会被记成上一份好配置）；
B. 对照：没写、空列表、只有空白、带空白的地址、IPv4-mapped 地址、带主机位的网段、重复的条目、
   JSON 的 ``null`` 都照旧读出来，没有 ERROR；
C. 运行中改坏：``reload()`` 之后仍是上一份好配置；日志说沿用了上一份；好、坏、读不出来交替时跟着
   最近一份好的；一次都没读过就没有可沿用的；``invalidate_all_caches()`` 不会让它忘掉；
D. 保存：整段设置能把坏的一行换成好的；``update`` 在“只放行本机”或正在生效的那一份上改；
E. 随机对照：24 个种子、每个 100 步，在好表、拦截名单读不懂、不是表、读不出来、没有这一段、重启之间
   随机切换，每一步读出来的都等于“最近一次读到的好配置，没有就只放行本机”这个模型的结果；
F. 全新进程：真实 ``WebFeedbackUI`` 里各个来源的状态码；写对的名单仍然拦着；运行中的 Web UI 在
   好、字符串、另一份好、拼错、好之间一直在执行访问控制；
G. 判断本身：``blocked_ips_problem`` 的说明（含五个以内列位置、再多写个数）、不含内容、空白和
   IPv4-mapped 不算问题、``unusable_ip_entries`` 的位置、一份判断（AST）；
H. 文档：两份配置指南写明拦截名单读不懂时的处理。

每个测试的 docstring 写着它在旧代码上的结果（“对照，新旧代码都通过”的是对照）。
"""

from __future__ import annotations

import ast
import json
import logging
import random
from collections import Counter
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from ai_intervention_agent import web_ui_validators as validators
from ai_intervention_agent.config_manager import ConfigManager
from ai_intervention_agent.enhanced_logging import EnhancedLogger
from tests.test_network_security_not_a_table_fails_closed_r919 import (
    ARRAY_OF_TABLES,
    NO_SECTION,
    NON_TABLES,
    SECRET,
    STRING,
    SUFFIX,
    TABLE_C,
    UNREADABLE_TOML,
)
from tests.test_unreadable_network_security_fails_closed_r915 import (
    DEFAULTS,
    FAIL_CLOSED,
    FIRST_LOAD_SCRIPT,
    KEY_TWICE,
    PEERS,
    STATUS_A,
    STATUS_B,
    STATUS_LOOPBACK_ONLY,
    TABLE_A,
    TABLE_B,
    WATCHED_SCRIPT,
    Collect,
    Line,
    errors,
    expected,
    fresh_process,
    manager_for,
    put,
)
from tests.test_unreadable_network_security_fails_closed_r915 import (
    table_text as r915_table_text,
)

REPO = Path(__file__).resolve().parent.parent
SRC = REPO / "src" / "ai_intervention_agent"
PORT = 19920
GOOD_TABLES = [TABLE_A, TABLE_B, TABLE_C]

# (写在 blocked_ips 里的值, ERROR 里要有的说明, 名字)
NOT_A_LIST: list[tuple[Any, str, str]] = [
    ("10.9.9.9", "不是列表（实际类型 str）", "a string"),
    (5, "不是列表（实际类型 int）", "an integer"),
    (1.5, "不是列表（实际类型 float）", "a float"),
    (True, "不是列表（实际类型 bool）", "a boolean"),
    ({"ip": "10.9.9.9"}, "不是列表（实际类型 dict）", "a table"),
    # 写了、却是“空”的东西：和没写（``None``）不一样
    ("", "不是列表（实际类型 str）", "an empty string"),
    (0, "不是列表（实际类型 int）", "zero"),
    (False, "不是列表（实际类型 bool）", "false"),
    ({}, "不是列表（实际类型 dict）", "an empty table"),
]
BAD_ENTRIES: list[tuple[Any, str, str]] = [
    (
        ["10.9.9.999"],
        "第 1 项不是 IP 地址或网段（名单共 1 项）",
        "a typo in the only entry",
    ),
    (
        ["10.9.9.9", "10.9.9.999"],
        "第 2 项不是 IP 地址或网段（名单共 2 项）",
        "one good entry, one typo",
    ),
    (
        ["10.9.9.9", 7],
        "第 2 项不是 IP 地址或网段（名单共 2 项）",
        "a number among the addresses",
    ),
    (
        ["10.9.9.9", ["1.2.3.4"]],
        "第 2 项不是 IP 地址或网段（名单共 2 项）",
        "a list among the addresses",
    ),
    (["evil.example.com"], "第 1 项不是 IP 地址或网段（名单共 1 项）", "a host name"),
    (
        ["10.9.9.9/33"],
        "第 1 项不是 IP 地址或网段（名单共 1 项）",
        "a mask that is too long",
    ),
    (
        ["10.9.9.9", True],
        "第 2 项不是 IP 地址或网段（名单共 2 项）",
        "a boolean among the addresses",
    ),
    (
        [{"ip": "1.2.3.4"}],
        "第 1 项不是 IP 地址或网段（名单共 1 项）",
        "a table in the list",
    ),
]
UNUSABLE = NOT_A_LIST + BAD_ENTRIES
SUFFIXES = [".toml", ".json"]

# (文件后缀, 写在 blocked_ips 里的值, ERROR 里要有的说明)
SHAPES = [
    pytest.param(suffix, value, said, id=f"{suffix[1:]}: {name}")
    for suffix in SUFFIXES
    for value, said, name in UNUSABLE
]
SHAPES_TOML = [p for p in SHAPES if p.values[0] == ".toml"]

# 文件里别的段：读不懂的拦截名单不该连累它们
OTHER_SECTIONS = {"web_ui": {"port": PORT}, "feedback": {"prompt_suffix": SUFFIX}}


def file_text(table: dict[str, Any], suffix: str = ".toml") -> str:
    """``[network_security]`` 加上别的段。TOML 里别的段写在后面。"""
    if suffix == ".json":
        return json.dumps({"network_security": table, **OTHER_SECTIONS}, indent=2)
    other = f'\n[web_ui]\nport = {PORT}\n\n[feedback]\nprompt_suffix = "{SUFFIX}"\n'
    return r915_table_text(table, ".toml") + other


def with_block_list(value: Any, suffix: str = ".toml") -> str:
    """配置 B（放行 127.0.0.0/8 和 10.0.0.0/8，要拦 10.9.9.9），``blocked_ips`` 换成 ``value``。"""
    return file_text({**TABLE_B, "blocked_ips": value}, suffix)


@pytest.fixture
def lines(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[Line]]:
    """包里每一条日志的 ``(级别, 文本)``（``EnhancedLogger`` 去重之前记下来，和 R915 一样）。"""
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


def said_by_the_reader(lines: list[Line]) -> list[str]:
    return [t for t in errors(lines) if "读取 network_security 配置失败" in t]


# ---- A. 刚启动，没有上一份好配置 -----------------------------------------------------------------


class TestFirstLoadWithAnUnusableBlockList:
    @pytest.mark.parametrize(("suffix", "value", "said"), SHAPES)
    def test_only_the_own_machine_is_let_in(
        self, tmp_path: Path, suffix: str, value: Any, said: str
    ) -> None:
        """旧代码：``allowed_networks`` 照写的放行（10.0.0.0/8），拦截名单要么是空的，要么只剩写对
        的那几项。"""
        _, manager = manager_for(tmp_path, suffix, with_block_list(value, suffix))

        assert manager.get_network_security_config() == FAIL_CLOSED

    @pytest.mark.parametrize(("suffix", "value", "said"), SHAPES)
    def test_get_section_gives_the_same(
        self, tmp_path: Path, suffix: str, value: Any, said: str
    ) -> None:
        """旧代码：照写的放行。"""
        _, manager = manager_for(tmp_path, suffix, with_block_list(value, suffix))

        assert manager.get_section("network_security") == FAIL_CLOSED

    @pytest.mark.parametrize(("suffix", "value", "said"), SHAPES)
    def test_one_error_names_the_file_the_key_and_what_is_wrong(
        self,
        tmp_path: Path,
        lines: list[Line],
        suffix: str,
        value: Any,
        said: str,
    ) -> None:
        """旧代码：只有 WARNING（“已忽略”或“无效条目已忽略”），没有 ERROR。"""
        path, manager = manager_for(tmp_path, suffix, with_block_list(value, suffix))
        del lines[:]

        manager.get_network_security_config()

        seen = said_by_the_reader(lines)
        assert len(seen) == 1
        assert str(path) in seen[0]
        assert "network_security.blocked_ips" in seen[0]
        assert said in seen[0]
        assert "只监听本机" in seen[0]
        assert "只放行本机" in seen[0]

    @pytest.mark.parametrize(
        "value",
        [SECRET, [SECRET], ["10.9.9.9", SECRET], [{"token": SECRET}]],
        ids=["a string", "the only entry", "an entry among addresses", "a table entry"],
    )
    def test_what_was_written_is_never_logged(
        self, tmp_path: Path, lines: list[Line], value: Any
    ) -> None:
        """那一项可能是贴错了地方的令牌：日志里只有位置，没有内容。旧代码：每个读不懂的条目各有一条
        WARNING，把条目原样写进日志。"""
        _, manager = manager_for(tmp_path, ".toml", with_block_list(value))
        del lines[:]

        manager.get_network_security_config()

        assert lines
        assert [text for _, text in lines if SECRET in text] == []

    @pytest.mark.parametrize(("suffix", "value", "said"), SHAPES)
    def test_the_other_sections_are_read(
        self, tmp_path: Path, suffix: str, value: Any, said: str
    ) -> None:
        """对照，新旧代码都通过：文件是合法的，只有拦截名单不能用。"""
        _, manager = manager_for(tmp_path, suffix, with_block_list(value, suffix))
        manager.get_network_security_config()

        assert manager.get_section("feedback")["prompt_suffix"] == SUFFIX
        assert manager.get_section("web_ui")["port"] == PORT
        assert manager._on_disk_config_invalid is False

    @pytest.mark.parametrize(("suffix", "value", "said"), SHAPES)
    def test_fixing_the_file_takes_effect_on_the_next_reload(
        self, tmp_path: Path, suffix: str, value: Any, said: str
    ) -> None:
        """对照，新旧代码都通过。"""
        path, manager = manager_for(tmp_path, suffix, with_block_list(value, suffix))
        manager.get_network_security_config()

        put(path, file_text(TABLE_B, suffix))
        manager.reload()

        assert manager.get_network_security_config() == expected(TABLE_B)

    def test_a_second_failure_still_says_that_nothing_was_ever_read(
        self, tmp_path: Path, lines: list[Line]
    ) -> None:
        """启动时没有上一份：再读一次，仍然说“没有上一份可用的配置”。如果第二次起说“沿用上一次读到的
        配置”，就是把启动时那份只放行本机的当成了读到过的好配置。旧代码：没有 ERROR。"""
        _, manager = manager_for(tmp_path, ".toml", with_block_list("10.9.9.9"))
        del lines[:]

        manager.get_network_security_config()
        manager.reload()
        manager.get_network_security_config()

        seen = said_by_the_reader(lines)
        assert len(seen) == 2
        assert all("又没有上一份可用的配置" in t for t in seen)
        assert not any("沿用上一次读到的配置" in t for t in seen)

    def test_the_closed_configuration_is_not_remembered_as_a_good_one(
        self, tmp_path: Path
    ) -> None:
        """修好、再改坏：退回修好的那一份，不是启动时那份只放行本机的。"""
        path, manager = manager_for(tmp_path, ".toml", with_block_list("10.9.9.9"))
        assert manager.get_network_security_config() == FAIL_CLOSED
        put(path, file_text(TABLE_A))
        manager.reload()
        assert manager.get_network_security_config() == expected(TABLE_A)

        put(path, with_block_list(["10.9.9.999"]))
        manager.reload()

        assert manager.get_network_security_config() == expected(TABLE_A)


# ---- B. 对照：这些读得懂，或者没写 ---------------------------------------------------------------

STILL_A_BLOCK_LIST = [
    pytest.param(".toml", [], [], id="toml: an empty list"),
    pytest.param(".toml", ["10.9.9.9"], ["10.9.9.9"], id="toml: one address"),
    pytest.param(
        ".toml", [" 10.9.9.9 ", ""], ["10.9.9.9"], id="toml: padded, and a blank one"
    ),
    pytest.param(".toml", ["", "   "], [], id="toml: only blanks"),
    pytest.param(
        ".toml", ["::ffff:10.9.9.9"], ["10.9.9.9"], id="toml: an IPv4-mapped address"
    ),
    pytest.param(
        ".toml", ["10.9.9.5/24"], ["10.9.9.0/24"], id="toml: a network with host bits"
    ),
    pytest.param(
        ".toml", ["10.9.9.9", "10.9.9.9"], ["10.9.9.9"], id="toml: a duplicate"
    ),
    pytest.param(
        ".toml", ["2001:db8::/32"], ["2001:db8::/32"], id="toml: an IPv6 network"
    ),
    pytest.param(".json", [], [], id="json: an empty list"),
    pytest.param(".json", None, [], id="json: null is the same as not written"),
    pytest.param(".json", ["10.9.9.9"], ["10.9.9.9"], id="json: one address"),
]


class TestWhatIsStillABlockList:
    @pytest.mark.parametrize(("suffix", "value", "want"), STILL_A_BLOCK_LIST)
    def test_it_reads_as_before(
        self,
        tmp_path: Path,
        lines: list[Line],
        suffix: str,
        value: Any,
        want: list[str],
    ) -> None:
        """对照，新旧代码都通过：这一条规则只管“读不懂”。"""
        _, manager = manager_for(tmp_path, suffix, with_block_list(value, suffix))
        del lines[:]

        got = manager.get_network_security_config()

        assert got == {**expected(TABLE_B), "blocked_ips": want}
        assert errors(lines) == []

    def test_a_missing_key_reads_as_before(self, tmp_path: Path) -> None:
        """对照，新旧代码都通过：没写这个键，没有拦截名单。"""
        table = {k: v for k, v in TABLE_B.items() if k != "blocked_ips"}
        _, manager = manager_for(tmp_path, ".toml", file_text(table))

        assert manager.get_network_security_config() == {
            **expected(TABLE_B),
            "blocked_ips": [],
        }


# ---- C. 运行中改坏 -------------------------------------------------------------------------------


class TestTheConfigurationInForceSurvivesAnUnusableBlockList:
    @pytest.mark.parametrize(("suffix", "value", "said"), SHAPES)
    def test_reload_keeps_what_was_in_force(
        self, tmp_path: Path, suffix: str, value: Any, said: str
    ) -> None:
        """旧代码：改坏的那一版生效了：``allowed_networks`` 换成了 B 的，拦截名单丢掉了读不懂的。"""
        path, manager = manager_for(tmp_path, suffix, file_text(TABLE_A, suffix))
        assert manager.get_network_security_config() == expected(TABLE_A)

        put(path, with_block_list(value, suffix))
        manager.reload()

        assert manager.get_network_security_config() == expected(TABLE_A)
        assert manager.get_section("network_security") == expected(TABLE_A)

    @pytest.mark.parametrize(("suffix", "value", "said"), SHAPES_TOML)
    def test_the_log_says_the_previous_configuration_is_kept(
        self,
        tmp_path: Path,
        lines: list[Line],
        suffix: str,
        value: Any,
        said: str,
    ) -> None:
        """旧代码：一条 WARNING，没有 ERROR。"""
        path, manager = manager_for(tmp_path, suffix, file_text(TABLE_A, suffix))
        manager.get_network_security_config()
        put(path, with_block_list(value, suffix))
        del lines[:]

        manager.reload()
        manager.get_network_security_config()

        seen = said_by_the_reader(lines)
        assert len(seen) == 1
        assert str(path) in seen[0]
        assert "沿用上一次读到的配置" in seen[0]
        assert said in seen[0]

    def test_the_configuration_follows_the_latest_good_file(
        self, tmp_path: Path
    ) -> None:
        """好、坏名单、好、坏名单、读不出来、好、不是表：停在最近一次读到的好配置上。"""
        path, manager = manager_for(tmp_path, ".toml", file_text(TABLE_A))
        assert manager.get_network_security_config() == expected(TABLE_A)
        seen = []

        for content in (
            with_block_list("10.9.9.9"),
            file_text(TABLE_B),
            with_block_list(["10.9.9.9", "10.9.9.999"]),
            KEY_TWICE,
            file_text(TABLE_A),
            STRING,
        ):
            put(path, content)
            manager.reload()
            seen.append(manager.get_network_security_config())

        assert seen == [
            expected(TABLE_A),
            expected(TABLE_B),
            expected(TABLE_B),
            expected(TABLE_B),
            expected(TABLE_A),
            expected(TABLE_A),
        ]

    def test_a_manager_that_never_read_the_section_has_nothing_to_keep(
        self, tmp_path: Path
    ) -> None:
        """一次都没读过（服务启动后还没有任何请求）就没有可沿用的，按刚启动处理：只放行本机。"""
        path, manager = manager_for(tmp_path, ".toml", file_text(TABLE_A))

        put(path, with_block_list("10.9.9.9"))
        manager.reload()

        assert manager.get_network_security_config() == FAIL_CLOSED

    def test_invalidating_the_caches_does_not_make_it_forget(
        self, tmp_path: Path
    ) -> None:
        path, manager = manager_for(tmp_path, ".toml", file_text(TABLE_A))
        manager.get_network_security_config()
        put(path, with_block_list("10.9.9.9"))

        manager.invalidate_all_caches()

        assert manager.get_network_security_config() == expected(TABLE_A)


# ---- D. 保存 -------------------------------------------------------------------------------------


class TestSavingRepairsTheList:
    @pytest.mark.parametrize(("suffix", "value", "said"), SHAPES_TOML)
    def test_set_replaces_the_list_and_keeps_the_other_sections(
        self, tmp_path: Path, suffix: str, value: Any, said: str
    ) -> None:
        """对照，新旧代码都通过。"""
        path, manager = manager_for(tmp_path, suffix, with_block_list(value, suffix))

        manager.set_network_security_config(TABLE_A)

        assert manager.get_network_security_config() == expected(TABLE_A)
        assert ConfigManager(str(path)).get_network_security_config() == expected(
            TABLE_A
        )
        assert ConfigManager(str(path)).get_section("web_ui")["port"] == PORT

    def test_update_starts_from_what_is_in_force(self, tmp_path: Path) -> None:
        """刚启动、没有上一份：在“只放行本机”的基础上改，写进文件的是这一份，不是照写的 10.0.0.0/8。
        旧代码：写进文件的是读出来的（放行 10.0.0.0/8）加上这一处改动。"""
        path, manager = manager_for(tmp_path, ".toml", with_block_list("10.9.9.9"))

        manager.update_network_security_config({"blocked_ips": ["1.2.3.4"]})

        want = {**FAIL_CLOSED, "blocked_ips": ["1.2.3.4"]}
        assert manager.get_network_security_config() == want
        assert ConfigManager(str(path)).get_network_security_config() == want

    def test_update_over_a_running_configuration_keeps_it(self, tmp_path: Path) -> None:
        """服务在跑、沿用着 A：改一处，写进文件的是 A 加上这一处。旧代码：B 的放行范围加这一处。"""
        path, manager = manager_for(tmp_path, ".toml", file_text(TABLE_A))
        manager.get_network_security_config()
        put(path, with_block_list("10.9.9.9"))
        manager.reload()

        manager.update_network_security_config({"trusted_proxy_hops": 5})

        want = {**expected(TABLE_A), "trusted_proxy_hops": 5}
        assert manager.get_network_security_config() == want
        assert ConfigManager(str(path)).get_network_security_config() == want


# ---- E. 随机对照 ---------------------------------------------------------------------------------

BAD_BLOCK_LISTS = [with_block_list(value) for value, _, _ in UNUSABLE]
KINDS = [
    "good",
    "good",
    "bad block list",
    "bad block list",
    "bad block list",
    "not a table",
    "unreadable",
    "no section",
    "restart",
]
SEEDS = range(24)
STEPS_PER_SEED = 100


class TestAgainstAModelThatOnlyRemembersTheLatestGoodConfiguration:
    def test_random_sequences(self, tmp_path: Path) -> None:
        """模型：文件里是好表就是那张表；没有这一段就是默认值；其余（拦截名单读不懂、不是表、读不出来）
        都是最近一次读到的好配置，没有就只放行本机。重启忘掉“最近一次”。旧代码：拦截名单读不懂时
        读出照写的配置。"""
        checks: Counter[str] = Counter()
        for seed in SEEDS:
            rng = random.Random(seed)
            path = tmp_path / f"seed{seed}.toml"
            table = rng.choice(GOOD_TABLES)
            put(path, file_text(table))
            file_state: tuple[str, dict[str, Any] | None] = ("good", table)
            manager = ConfigManager(str(path))
            in_force: dict[str, Any] | None = None

            for step in range(STEPS_PER_SEED):
                kind = rng.choice(KINDS)
                if kind == "restart":
                    manager = ConfigManager(str(path))
                    in_force = None
                    checks["restart"] += 1
                else:
                    if kind == "good":
                        table = rng.choice(GOOD_TABLES)
                        put(path, file_text(table))
                        file_state = ("good", table)
                    elif kind == "no section":
                        put(path, rng.choice(NO_SECTION))
                        file_state = ("none", None)
                    elif kind == "bad block list":
                        put(path, rng.choice(BAD_BLOCK_LISTS))
                        file_state = ("bad", None)
                    elif kind == "not a table":
                        put(path, rng.choice(NON_TABLES))
                        file_state = ("bad", None)
                    else:
                        put(path, rng.choice(UNREADABLE_TOML))
                        file_state = ("bad", None)
                    manager.reload()

                state, good = file_state
                if state == "good":
                    assert good is not None
                    want = expected(good)
                elif state == "none":
                    want = DEFAULTS
                else:
                    want = in_force if in_force is not None else FAIL_CLOSED
                    checks[
                        "broken, a configuration in force"
                        if in_force is not None
                        else "broken, nothing in force"
                    ] += 1
                    if kind == "bad block list":
                        checks["bad block list"] += 1

                got = manager.get_network_security_config()

                assert got == want, (seed, step, kind, state)
                if state != "bad":
                    in_force = got

        assert checks["broken, a configuration in force"] >= 600, checks
        assert checks["broken, nothing in force"] >= 150, checks
        assert checks["bad block list"] >= 600, checks
        assert checks["restart"] >= 200, checks


# ---- F. 全新进程：真实 Web UI ---------------------------------------------------------------------


class TestAFreshProcess:
    @pytest.mark.parametrize(("suffix", "value", "said"), SHAPES_TOML)
    def test_only_the_own_machine_is_let_in(
        self, tmp_path: Path, suffix: str, value: Any, said: str
    ) -> None:
        """旧代码：10.1.2.3 是 200，10.9.9.9 在名单是字符串、整数、表、拼错时是 200。"""
        path = tmp_path / "config.toml"
        put(path, with_block_list(value))

        result = fresh_process(FIRST_LOAD_SCRIPT, path, json.dumps(PEERS))

        assert result == {"host": "127.0.0.1", "status": STATUS_LOOPBACK_ONLY}

    def test_control_a_good_block_list_still_blocks(self, tmp_path: Path) -> None:
        """对照，新旧代码都通过：写对的名单照旧拦着 10.9.9.9，10.1.2.3 放行。"""
        path = tmp_path / "config.toml"
        put(path, with_block_list(["10.9.9.9"]))

        result = fresh_process(FIRST_LOAD_SCRIPT, path, json.dumps(PEERS))

        assert result == {"host": "127.0.0.1", "status": STATUS_B}

    def test_the_running_web_ui_keeps_enforcing(self, tmp_path: Path) -> None:
        """旧代码：第二步和第四步里 10.9.9.9 是 200（拦截名单被忘掉）。"""
        path = tmp_path / "config.toml"
        put(path, file_text(TABLE_A))
        steps = [
            with_block_list("10.9.9.9"),
            file_text(TABLE_B),
            with_block_list(["10.9.9.999"]),
            file_text(TABLE_A),
        ]

        seen = fresh_process(
            WATCHED_SCRIPT, path, json.dumps(PEERS), json.dumps(steps), str(PORT)
        )

        assert seen == [
            STATUS_A,  # 启动
            STATUS_A,  # 名单写成字符串：照旧，A 还在
            STATUS_B,  # 改成另一份好的：马上生效
            STATUS_B,  # 名单拼错：停在 B，10.9.9.9 仍被拦着
            STATUS_A,  # 改好：回到 A
        ]


# ---- G. 判断本身 ---------------------------------------------------------------------------------


class TestBlockedIpsProblem:
    @pytest.mark.parametrize(
        "value",
        [
            None,
            [],
            ["10.9.9.9"],
            [" 10.9.9.9 ", ""],
            ["", "   ", "\t"],
            ["::ffff:10.9.9.9"],
            ["10.9.9.5/24"],
            ["10.9.9.9", "10.9.9.9"],
            ["2001:db8::/32", "::1"],
        ],
    )
    def test_a_list_that_can_be_enforced_is_no_problem(self, value: Any) -> None:
        """旧代码：没有这个函数。"""
        assert validators.blocked_ips_problem(value) is None

    @pytest.mark.parametrize(
        ("value", "said", "name"), UNUSABLE, ids=[name for _, _, name in UNUSABLE]
    )
    def test_the_problem_is_described(self, value: Any, said: str, name: str) -> None:
        """旧代码：没有这个函数。"""
        problem = validators.blocked_ips_problem(value)

        assert problem is not None
        assert said in problem

    def test_up_to_five_positions_are_listed_and_then_a_count(self) -> None:
        """旧代码：没有这个函数。"""
        five = validators.blocked_ips_problem(["x"] * 5 + ["10.0.0.1"])
        seven = validators.blocked_ips_problem(["x"] * 7 + ["10.0.0.1"])

        assert five == "第 1、2、3、4、5 项不是 IP 地址或网段（名单共 6 项）"
        assert seven == "第 1、2、3、4、5 项等共 7 项不是 IP 地址或网段（名单共 8 项）"

    def test_the_positions_count_from_one_in_the_list_as_written(self) -> None:
        """空白条目和重复的条目也占位置：用户在文件里数到的第几项。"""
        problem = validators.blocked_ips_problem(
            ["10.0.0.1", "", "10.0.0.1", "bad", "  ", "worse"]
        )

        assert problem == "第 4、6 项不是 IP 地址或网段（名单共 6 项）"

    @pytest.mark.parametrize(
        "value",
        [SECRET, [SECRET], ["10.9.9.9", SECRET], [{"token": SECRET}], {"k": SECRET}],
    )
    def test_the_description_never_contains_what_was_written(self, value: Any) -> None:
        """旧代码：没有这个函数。"""
        problem = validators.blocked_ips_problem(value)

        assert problem is not None
        assert SECRET not in problem

    def test_unusable_ip_entries_are_the_ones_the_normaliser_drops(self) -> None:
        """旧代码：没有 ``unusable_ip_entries``。判断只有一份：它说读不懂的，正是
        ``normalize_ip_entries`` 丢掉的，反过来也一样。"""
        rng = random.Random(920)
        pool: list[Any] = [
            "10.0.0.1",
            " 10.0.0.2 ",
            "",
            "   ",
            "::ffff:10.0.0.3",
            "10.0.0.0/8",
            "10.0.0.5/24",
            "nope",
            "10.0.0.999",
            "10.0.0.1/33",
            7,
            None,
            True,
            ["10.0.0.1"],
            {"ip": "10.0.0.1"},
        ]

        def dropped_by_the_normaliser(item: Any) -> bool:
            if isinstance(item, str) and not item.strip():
                return False  # 空白：静默跳过，不是读不懂
            return validators.normalize_ip_entries([item], "x") == []

        for _ in range(300):
            items = [rng.choice(pool) for _ in range(rng.randrange(0, 9))]

            assert validators.unusable_ip_entries(items) == [
                i for i, item in enumerate(items) if dropped_by_the_normaliser(item)
            ], items

    def test_there_is_one_judgement_of_a_list_entry(self) -> None:
        """旧代码：没有 ``_judge_ip_entry``，``normalize_ip_entries`` 自己判断。"""
        tree = ast.parse((SRC / "web_ui_validators.py").read_text(encoding="utf-8"))
        functions = {
            node.name: node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef)
        }

        def called(name: str) -> set[str]:
            return {
                call.func.id
                for call in ast.walk(functions[name])
                if isinstance(call, ast.Call) and isinstance(call.func, ast.Name)
            }

        assert "_judge_ip_entry" in called("normalize_ip_entries")
        assert "_judge_ip_entry" in called("unusable_ip_entries")
        assert "unusable_ip_entries" in called("blocked_ips_problem")
        for name in (
            "normalize_ip_entries",
            "unusable_ip_entries",
            "blocked_ips_problem",
        ):
            assert not {"ip_network", "ip_address", "_canonical_ip_entry"} & called(
                name
            )
        assert called("_judge_ip_entry") >= {"_canonical_ip_entry"}


# ---- H. 文档 -------------------------------------------------------------------------------------


class TestTheGuidesSayWhatAnUnusableBlockListDoes:
    @pytest.mark.parametrize(
        ("name", "now", "before"),
        [
            (
                "configuration.md",
                "A `blocked_ips` that is not a list, or that has an entry that is not an IP address or network, is treated the same way",
                "are read as written. `allowed_networks",
            ),
            (
                "configuration.zh-CN.md",
                "`blocked_ips` 不是列表、或有不是 IP 地址也不是网段的条目时同样处理",
                "照常读取。`allowed_networks",
            ),
        ],
    )
    def test_the_rule_is_stated(self, name: str, now: str, before: str) -> None:
        """旧代码：只说 ``allowed_networks`` 写坏了怎么办，没有例外。"""
        text = (REPO / "docs" / name).read_text(encoding="utf-8")

        assert now in text
        assert before not in text

    @pytest.mark.parametrize(
        ("name", "exception"),
        [
            ("configuration.md", "(`blocked_ips` is the exception, see below)"),
            ("configuration.zh-CN.md", "（`blocked_ips` 是例外，见下）"),
        ],
    )
    def test_the_per_key_rule_names_its_exception(
        self, name: str, exception: str
    ) -> None:
        """旧代码：“只有那一项退回安全的值”，没有说 ``blocked_ips`` 不是这样。"""
        text = (REPO / "docs" / name).read_text(encoding="utf-8")

        assert exception in text


# 两个固定的“不是表”的例子，保证 R919 的规则在这里也还成立：拦截名单读不懂的检查不能把它们挡在前面
class TestTheRulesOfR919AreStillTheFirstCheck:
    @pytest.mark.parametrize("content", [STRING, ARRAY_OF_TABLES])
    def test_a_section_that_is_not_a_table_is_still_reported_as_such(
        self, tmp_path: Path, lines: list[Line], content: str
    ) -> None:
        """对照，新旧代码都通过（R919）：不是表的那一段不会走到拦截名单的检查。"""
        _, manager = manager_for(tmp_path, ".toml", content)
        del lines[:]

        manager.get_network_security_config()

        seen = said_by_the_reader(lines)
        assert len(seen) == 1
        assert "不是表" in seen[0]
        assert "blocked_ips" not in seen[0]
