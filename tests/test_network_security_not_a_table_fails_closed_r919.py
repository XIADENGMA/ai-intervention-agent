"""R919：``network_security`` 写成不是表的东西，和读不出来的文件一样不放开任何东西。

现象（全新进程 + 真实 Web UI，旧代码实测）
==========================================

R913 之后，配置里的 ``network_security`` 如果不是表（``network_security = "oops"``、``= 5``、
``= [1, 2]``、``[[network_security]]``），整段会被当成“没有这一段”：读出默认值，``allowed_networks``
是回环加三个内网网段，黑名单和令牌都没了。R915 刚刚规定了“读不出来的文件不放开任何东西”，这一种写法
却还停在旧规则上：文件是合法的 TOML，所以不算“读不出来”，可是用户写的东西我们一个字也没用上，
和读不出来没有区别。

R915 的脚本（真实的 ``WebFeedbackUI``，来源地址用 ``REMOTE_ADDR`` 指定）：

  新进程，``network_security = "oops"``，各个来源得到的状态码::

    来源            旧代码     新代码
    127.0.0.1       200        200
    192.168.1.50    200        403
    192.168.1.66    200        403
    10.1.2.3        200        403
    10.9.9.9        200        403
    8.8.8.8         403        403

  运行中的 Web UI（配置 A 拉黑 192.168.1.66、配置 B 拉黑 10.9.9.9），文件依次改成
  A、字符串、B、表的数组、A，每一步之后各个来源的状态码：

    第二步（字符串）：旧代码 192.168.1.66 和 10.9.9.9 都是 200（黑名单被忘掉，内网放开）；
                      新代码和 A 一样（192.168.1.66 仍是 403）
    第四步（表的数组）：旧代码同样放开；新代码和 B 一样
    第三、五步（写回好的）：两边都立刻生效

修复
====

``ConfigManager.get_network_security_config`` 发现 ``network_security`` 写了、却不是表，就交给读不出来
的文件用的那个函数（``_network_security_when_unreadable``）：服务已经在跑，就继续用上一份读到的配置
（黑名单不会被一次手滑忘掉）；刚启动、没有上一份，就只监听 ``127.0.0.1``、只放行本机回环。日志里一条
ERROR，写明文件路径和写的是什么类型，不写内容（那一行可能是贴错了地方的令牌）。文件里的其他段照常读，
文件不标记为无效，Web UI 里保存网络设置仍然能把这一行换成一张正确的表（R913）。

不变的：``network_security = {}``、空的 ``[network_security]``、点号写法、没有这一段都是表或者没写，
读出默认值；JSON 里的 ``null`` 和没写一样。两个校验器自己收到不是 dict 的值仍然返回默认值，但文件
读出来的东西到不了那里。

测试矩阵
========

A. 十二种不是表的写法（TOML 八种、JSON 四种）经过真实文件，刚启动：只放行本机回环；``get_section``
   给同样的结果；一条 ERROR 写明文件路径、``不是表``、类型名；日志里没有那一行的内容；文件里的其他段
   照常读、文件不标记为无效；修好之后下一次 ``reload()`` 就生效；第二次又不是表时，日志仍然说“没有读到过
   任何配置”（关死的配置不会被记成上一份好配置）；
B. 对照：空表、空的 ``[network_security]``、点号写法、没有这一段、JSON 的 ``null`` 和空对象都是默认值，
   没有 ERROR；
C. 运行中改成不是表：``reload()`` 之后仍是上一份好配置；日志说沿用上一份；好、不是表、好、不是表、
   好的任意交替；没读过就没有可沿用的；``invalidate_all_caches()`` 不会让它忘掉；保存网络设置能换掉
   那一行，保存的东西就是之后沿用的；
D. 随机对照：24 个种子、每个 100 步，在好表、不是表、读不出来、没有这一段、重启之间随机切换，
   每一步读出来的配置都等于“最近一次读到的好配置，没有就只放行本机”这个模型的结果；
E. 全新进程：真实 ``WebFeedbackUI`` 里八种 TOML 写法各个来源的状态码；对照：空表照旧放行内网；
   运行中的 Web UI 在好、不是表、另一份好、不是表、好之间逐步得到的状态码；
F. 文档：两份配置指南说“不是表”和读不出来一样处理，不再说“整段被忽略”。

共 119 个测试，旧代码上 79 个失败，通过的 40 个是对照：A 里“其他段照常读”（12 个）、“修好之后下一次
reload 就生效”（12 个）和“日志里没有那一行的内容”，B 的全部（6 个），C 里保存网络设置换掉那一行（八种
TOML 写法各一个），E 里的空表对照。16 个单点变异体（改回放行默认值、永远关死而忘掉在用的配置、没有上
一份时放行默认值、日志不写类型、日志写出值、日志不说“不是表”、把数组当表、只认字符串、把空值当没写、
把 null 和没写也拦下、把文件标成无效、把关死的配置记成上一份好的、两条日志降成 WARNING、两份指南改回
“忽略”）全部被抓到。每个测试的 docstring 写着它在旧代码上的结果。
"""

from __future__ import annotations

import json
import logging
import random
import tomllib
from collections import Counter
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from ai_intervention_agent.config_manager import ConfigManager
from ai_intervention_agent.enhanced_logging import EnhancedLogger
from tests.test_unreadable_network_security_fails_closed_r915 import (
    ARRAY_NEVER_CLOSED,
    DEFAULTS,
    FAIL_CLOSED,
    FIRST_LOAD_SCRIPT,
    HEADER_NEVER_CLOSED,
    KEY_TWICE,
    NOT_UTF8,
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
PORT = 19919
SUFFIX = "R919-SUFFIX"
SECRET = "tok-0123456789abcdef0123456789abcdef"

# 第三份写对的配置，和 A、B、默认值都不一样
TABLE_C: dict[str, Any] = {
    "bind_interface": "127.0.0.1",
    "allowed_networks": ["127.0.0.0/8", "172.16.0.0/12"],
    "blocked_ips": ["172.16.1.1"],
    "trusted_hosts": ["c.example"],
    "trusted_proxy_hops": 4,
    "access_control_enabled": True,
    "api_token": "",
}

# 没有配置过的 Web UI：默认值放行内网网段、没有黑名单
STATUS_DEFAULTS = {
    "127.0.0.1": 200,
    "192.168.1.50": 200,
    "192.168.1.66": 200,
    "10.1.2.3": 200,
    "10.9.9.9": 200,
    "8.8.8.8": 403,
}


def table_text(table: dict[str, Any], suffix: str = ".toml") -> str:
    return r915_table_text(table, suffix)


# 文件里别的段：不是表的 network_security 不该连累它们
OTHER_SECTIONS = f'[web_ui]\nport = {PORT}\n\n[feedback]\nprompt_suffix = "{SUFFIX}"\n'


def toml_shape(first_line: str) -> str:
    """根上的一行（必须写在所有表头之前），后面跟着别的段。"""
    return f"{first_line}\n\n{OTHER_SECTIONS}"


def json_shape(value: Any) -> str:
    return json.dumps(
        {
            "network_security": value,
            "web_ui": {"port": PORT},
            "feedback": {"prompt_suffix": SUFFIX},
        },
        indent=2,
    )


STRING = toml_shape('network_security = "oops"')
ARRAY_OF_TABLES = (
    f'{OTHER_SECTIONS}\n[[network_security]]\nbind_interface = "0.0.0.0"\n'
)
INTEGER = toml_shape("network_security = 5")

# (文件后缀, 内容, 写的类型名)
NOT_A_TABLE = [
    pytest.param(".toml", STRING, "str", id="toml: a string"),
    pytest.param(".toml", INTEGER, "int", id="toml: an integer"),
    pytest.param(
        ".toml", toml_shape("network_security = 1.5"), "float", id="toml: a float"
    ),
    pytest.param(
        ".toml", toml_shape("network_security = true"), "bool", id="toml: a boolean"
    ),
    pytest.param(
        ".toml",
        toml_shape("network_security = 2026-10-28T10:00:00"),
        "datetime",
        id="toml: a date",
    ),
    pytest.param(
        ".toml", toml_shape("network_security = [1, 2]"), "list", id="toml: an array"
    ),
    pytest.param(
        ".toml", toml_shape("network_security = []"), "list", id="toml: an empty array"
    ),
    pytest.param(".toml", ARRAY_OF_TABLES, "list", id="toml: an array of tables"),
    pytest.param(".json", json_shape("oops"), "str", id="json: a string"),
    pytest.param(".json", json_shape(5), "int", id="json: a number"),
    pytest.param(".json", json_shape([1, 2]), "list", id="json: an array"),
    pytest.param(".json", json_shape(False), "bool", id="json: a boolean"),
]
NOT_A_TABLE_TOML = [p for p in NOT_A_TABLE if p.values[0] == ".toml"]


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


# ---- A. 刚启动，没有上一份好配置 -----------------------------------------------------------------


class TestFirstLoadOfASectionThatIsNotATable:
    @pytest.mark.parametrize(("suffix", "content", "type_name"), NOT_A_TABLE)
    def test_only_the_own_machine_is_let_in(
        self, tmp_path: Path, suffix: str, content: str, type_name: str
    ) -> None:
        """旧代码：当没写，读出默认值，放行整个内网。"""
        _, manager = manager_for(tmp_path, suffix, content)

        assert manager.get_network_security_config() == FAIL_CLOSED

    @pytest.mark.parametrize(("suffix", "content", "type_name"), NOT_A_TABLE)
    def test_get_section_gives_the_same(
        self, tmp_path: Path, suffix: str, content: str, type_name: str
    ) -> None:
        """旧代码：默认值。"""
        _, manager = manager_for(tmp_path, suffix, content)

        assert manager.get_section("network_security") == FAIL_CLOSED

    @pytest.mark.parametrize(("suffix", "content", "type_name"), NOT_A_TABLE)
    def test_one_error_names_the_file_and_the_type(
        self,
        tmp_path: Path,
        lines: list[Line],
        suffix: str,
        content: str,
        type_name: str,
    ) -> None:
        """旧代码：一条 WARNING “整段已忽略，使用默认配置”，没有 ERROR。"""
        path, manager = manager_for(tmp_path, suffix, content)
        del lines[:]

        manager.get_network_security_config()

        said = [t for t in errors(lines) if "读取 network_security 配置失败" in t]
        assert len(said) == 1
        assert str(path) in said[0]
        assert "不是表" in said[0]
        assert f"实际类型 {type_name}" in said[0]
        assert "只监听本机" in said[0]
        assert "只放行本机" in said[0]

    def test_a_second_failure_still_says_that_nothing_was_ever_read(
        self, tmp_path: Path, lines: list[Line]
    ) -> None:
        """启动时没有上一份：再读一次，仍然说“没有上一份可用的配置”。如果第二次起说“沿用上一次读到的
        配置”，就是把启动时那份只放行本机的当成了读到过的好配置。旧代码：没有 ERROR。"""
        _, manager = manager_for(tmp_path, ".toml", STRING)
        del lines[:]

        manager.get_network_security_config()
        manager.reload()
        manager.get_network_security_config()

        said = [t for t in errors(lines) if "读取 network_security 配置失败" in t]
        assert len(said) == 2
        assert all("又没有上一份可用的配置" in t for t in said)
        assert not any("沿用上一次读到的配置" in t for t in said)

    def test_the_value_is_never_logged(self, tmp_path: Path, lines: list[Line]) -> None:
        """那一行可能是贴错了地方的令牌：日志里只有类型，没有内容。新旧代码都通过。"""
        _, manager = manager_for(
            tmp_path, ".toml", toml_shape(f'network_security = "{SECRET}"')
        )
        del lines[:]

        manager.get_network_security_config()

        assert lines
        assert [text for _, text in lines if SECRET in text] == []

    @pytest.mark.parametrize(("suffix", "content", "type_name"), NOT_A_TABLE)
    def test_the_other_sections_are_read(
        self, tmp_path: Path, suffix: str, content: str, type_name: str
    ) -> None:
        """对照，新旧代码都通过：文件是合法的，只有这一段不能用。"""
        _, manager = manager_for(tmp_path, suffix, content)
        manager.get_network_security_config()

        assert manager.get_section("feedback")["prompt_suffix"] == SUFFIX
        assert manager.get_section("web_ui")["port"] == PORT
        assert manager._on_disk_config_invalid is False

    @pytest.mark.parametrize(("suffix", "content", "type_name"), NOT_A_TABLE)
    def test_fixing_the_file_takes_effect_on_the_next_reload(
        self, tmp_path: Path, suffix: str, content: str, type_name: str
    ) -> None:
        """对照，新旧代码都通过。"""
        path, manager = manager_for(tmp_path, suffix, content)
        manager.get_network_security_config()

        put(path, table_text(TABLE_A, suffix))
        manager.reload()

        assert manager.get_network_security_config() == expected(TABLE_A)

    def test_the_closed_configuration_is_not_remembered_as_a_good_one(
        self, tmp_path: Path
    ) -> None:
        """修好、再改坏：退回修好的那一份，不是启动时那份只放行本机的。"""
        path, manager = manager_for(tmp_path, ".toml", STRING)
        assert manager.get_network_security_config() == FAIL_CLOSED
        put(path, table_text(TABLE_A))
        manager.reload()
        assert manager.get_network_security_config() == expected(TABLE_A)

        put(path, ARRAY_OF_TABLES)
        manager.reload()

        assert manager.get_network_security_config() == expected(TABLE_A)


# ---- B. 对照：这些是表，或者没写 -----------------------------------------------------------------

STILL_A_CONFIGURATION = [
    pytest.param(
        ".toml",
        toml_shape("network_security = {}"),
        DEFAULTS,
        id="toml: an inline empty table",
    ),
    pytest.param(
        ".toml",
        f"[network_security]\n\n{OTHER_SECTIONS}",
        DEFAULTS,
        id="toml: an empty table",
    ),
    pytest.param(
        ".toml",
        toml_shape(
            'network_security.bind_interface = "127.0.0.1"\n'
            'network_security.blocked_ips = ["192.168.1.66"]'
        ),
        {**DEFAULTS, "blocked_ips": ["192.168.1.66"]},
        id="toml: dotted keys",
    ),
    pytest.param(".toml", OTHER_SECTIONS, DEFAULTS, id="toml: no section at all"),
    pytest.param(
        ".json", json_shape(None), DEFAULTS, id="json: null is the same as not written"
    ),
    pytest.param(".json", json_shape({}), DEFAULTS, id="json: an empty object"),
]


class TestWhatIsStillAConfiguration:
    @pytest.mark.parametrize(("suffix", "content", "want"), STILL_A_CONFIGURATION)
    def test_a_table_or_nothing_reads_as_before(
        self,
        tmp_path: Path,
        lines: list[Line],
        suffix: str,
        content: str,
        want: dict[str, Any],
    ) -> None:
        """对照，新旧代码都通过：这一条规则只管“写了、却不是表”。"""
        _, manager = manager_for(tmp_path, suffix, content)
        del lines[:]

        assert manager.get_network_security_config() == want
        assert errors(lines) == []


# ---- C. 运行中改成不是表 -------------------------------------------------------------------------


class TestTheConfigurationInForceSurvivesASectionThatIsNotATable:
    @pytest.mark.parametrize(("suffix", "content", "type_name"), NOT_A_TABLE)
    def test_reload_keeps_what_was_in_force(
        self, tmp_path: Path, suffix: str, content: str, type_name: str
    ) -> None:
        """旧代码：读出默认值，黑名单被忘掉、整个内网放开。"""
        path, manager = manager_for(tmp_path, suffix, table_text(TABLE_A, suffix))
        assert manager.get_network_security_config() == expected(TABLE_A)

        put(path, content)
        manager.reload()

        assert manager.get_network_security_config() == expected(TABLE_A)
        assert manager.get_section("network_security") == expected(TABLE_A)

    @pytest.mark.parametrize(("suffix", "content", "type_name"), NOT_A_TABLE)
    def test_the_log_says_the_previous_configuration_is_kept(
        self,
        tmp_path: Path,
        lines: list[Line],
        suffix: str,
        content: str,
        type_name: str,
    ) -> None:
        """旧代码：一条 WARNING，没有 ERROR。"""
        path, manager = manager_for(tmp_path, suffix, table_text(TABLE_A, suffix))
        manager.get_network_security_config()
        put(path, content)
        del lines[:]

        manager.reload()
        manager.get_network_security_config()

        said = [t for t in errors(lines) if "读取 network_security 配置失败" in t]
        assert len(said) == 1
        assert str(path) in said[0]
        assert "沿用上一次读到的配置" in said[0]
        assert f"实际类型 {type_name}" in said[0]

    def test_the_configuration_follows_the_latest_good_file(
        self, tmp_path: Path
    ) -> None:
        """好、不是表、好、不是表、读不出来、好、不是表：停在最近一次读到的好配置上。"""
        path, manager = manager_for(tmp_path, ".toml", table_text(TABLE_A))
        assert manager.get_network_security_config() == expected(TABLE_A)
        seen = []

        for content in (
            STRING,
            table_text(TABLE_B),
            ARRAY_OF_TABLES,
            KEY_TWICE,
            table_text(TABLE_A),
            INTEGER,
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
        path, manager = manager_for(tmp_path, ".toml", table_text(TABLE_A))

        put(path, STRING)
        manager.reload()

        assert manager.get_network_security_config() == FAIL_CLOSED

    def test_invalidating_the_caches_does_not_make_it_forget(
        self, tmp_path: Path
    ) -> None:
        path, manager = manager_for(tmp_path, ".toml", table_text(TABLE_A))
        manager.get_network_security_config()
        put(path, STRING)

        manager.invalidate_all_caches()

        assert manager.get_network_security_config() == expected(TABLE_A)


class TestSavingRepairsTheLine:
    """Web UI 里保存网络设置：把那一行换成一张正确的表（R913 F）；保存的就是之后沿用的。"""

    @pytest.mark.parametrize(("suffix", "content", "type_name"), NOT_A_TABLE_TOML)
    def test_set_replaces_the_line_and_keeps_the_other_sections(
        self, tmp_path: Path, suffix: str, content: str, type_name: str
    ) -> None:
        """对照，新旧代码都通过。"""
        path, manager = manager_for(tmp_path, suffix, content)

        manager.set_network_security_config(TABLE_B)

        written = tomllib.loads(path.read_text(encoding="utf-8"))
        assert written["network_security"]["blocked_ips"] == TABLE_B["blocked_ips"]
        assert written["web_ui"]["port"] == PORT
        assert written["feedback"]["prompt_suffix"] == SUFFIX
        assert manager.get_network_security_config() == expected(TABLE_B)
        assert ConfigManager(str(path)).get_network_security_config() == expected(
            TABLE_B
        )

    def test_update_starts_from_what_is_in_force(self, tmp_path: Path) -> None:
        """刚启动、没有上一份：在“只放行本机”的基础上改，写进文件的是这一份，不是默认值。
        旧代码：写进文件的是默认值（放行内网网段）加上这一处改动。"""
        path, manager = manager_for(tmp_path, ".toml", STRING)

        manager.update_network_security_config({"blocked_ips": ["1.2.3.4"]})

        want = {**FAIL_CLOSED, "blocked_ips": ["1.2.3.4"]}
        assert manager.get_network_security_config() == want
        assert ConfigManager(str(path)).get_network_security_config() == want

    def test_update_over_a_running_configuration_keeps_it(self, tmp_path: Path) -> None:
        """服务在跑、沿用着 A：改一处，写进文件的是 A 加上这一处。旧代码：默认值加这一处。"""
        path, manager = manager_for(tmp_path, ".toml", table_text(TABLE_A))
        manager.get_network_security_config()
        put(path, STRING)
        manager.reload()

        manager.update_network_security_config({"blocked_ips": ["1.2.3.4"]})

        want = {**expected(TABLE_A), "blocked_ips": ["1.2.3.4"]}
        assert manager.get_network_security_config() == want
        assert ConfigManager(str(path)).get_network_security_config() == want


# ---- D. 随机对照 ---------------------------------------------------------------------------------

GOOD_TABLES = [TABLE_A, TABLE_B, TABLE_C]
NON_TABLES = [str(p.values[1]) for p in NOT_A_TABLE_TOML]
UNREADABLE_TOML = [HEADER_NEVER_CLOSED, ARRAY_NEVER_CLOSED, KEY_TWICE, NOT_UTF8]
NO_SECTION = [OTHER_SECTIONS, "", "# nothing here\n"]
KINDS = [
    "good",
    "good",
    "not a table",
    "not a table",
    "not a table",
    "unreadable",
    "no section",
    "restart",
]
SEEDS = range(24)
STEPS_PER_SEED = 100


class TestAgainstAModelThatOnlyRemembersTheLatestGoodConfiguration:
    def test_random_sequences(self, tmp_path: Path) -> None:
        """模型：文件里是好表就是那张表；没有这一段就是默认值；其余（不是表、读不出来）都是最近一次
        读到的好配置，没有就只放行本机。重启忘掉“最近一次”。旧代码：不是表读出默认值。"""
        checks: Counter[str] = Counter()
        for seed in SEEDS:
            rng = random.Random(seed)
            path = tmp_path / f"seed{seed}.toml"
            table = rng.choice(GOOD_TABLES)
            put(path, table_text(table))
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
                        put(path, table_text(table))
                        file_state = ("good", table)
                    elif kind == "no section":
                        put(path, rng.choice(NO_SECTION))
                        file_state = ("none", None)
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
                    if kind == "not a table":
                        checks["not a table"] += 1

                got = manager.get_network_security_config()

                assert got == want, (seed, step, kind, state)
                if state != "bad":
                    in_force = got

        assert checks["broken, a configuration in force"] >= 600, checks
        assert checks["broken, nothing in force"] >= 150, checks
        assert checks["not a table"] >= 600, checks
        assert checks["restart"] >= 200, checks


# ---- E. 全新进程：真实 Web UI ---------------------------------------------------------------------


class TestAFreshProcess:
    @pytest.mark.parametrize(("suffix", "content", "type_name"), NOT_A_TABLE_TOML)
    def test_only_the_own_machine_is_let_in(
        self, tmp_path: Path, suffix: str, content: str, type_name: str
    ) -> None:
        """旧代码：192.168.1.50、192.168.1.66、10.1.2.3、10.9.9.9 都是 200。"""
        path = tmp_path / "config.toml"
        put(path, content)

        result = fresh_process(FIRST_LOAD_SCRIPT, path, json.dumps(PEERS))

        assert result == {"host": "127.0.0.1", "status": STATUS_LOOPBACK_ONLY}

    def test_control_an_empty_table_keeps_the_defaults(self, tmp_path: Path) -> None:
        """对照，新旧代码都通过：空表是一张表，没配置过，用默认值。"""
        path = tmp_path / "config.toml"
        put(path, toml_shape("network_security = {}"))

        result = fresh_process(FIRST_LOAD_SCRIPT, path, json.dumps(PEERS))

        assert result == {"host": "127.0.0.1", "status": STATUS_DEFAULTS}

    def test_the_running_web_ui_keeps_enforcing(self, tmp_path: Path) -> None:
        """旧代码：第二步和第四步的黑名单被忘掉、内网放开（192.168.1.66、10.9.9.9 都是 200）。"""
        path = tmp_path / "config.toml"
        put(path, table_text(TABLE_A))
        steps = [STRING, table_text(TABLE_B), ARRAY_OF_TABLES, table_text(TABLE_A)]

        seen = fresh_process(
            WATCHED_SCRIPT, path, json.dumps(PEERS), json.dumps(steps), str(PORT)
        )

        assert seen == [
            STATUS_A,  # 启动
            STATUS_A,  # 改成字符串：照旧，黑名单还在，内网没有放开
            STATUS_B,  # 改成另一份好的：马上生效
            STATUS_B,  # 改成表的数组：停在 B
            STATUS_A,  # 改好：回到 A
        ]


# ---- F. 文档 ----------------------------------------------------------------------------------


class TestTheGuidesSayItIsTreatedLikeAFileThatCannotBeRead:
    @pytest.mark.parametrize(
        ("name", "now", "before"),
        [
            (
                "configuration.md",
                "a `network_security` that is not a table (a string, a number, an array, an array of tables) is treated the same way",
                "is ignored, as if the section were missing",
            ),
            (
                "configuration.zh-CN.md",
                "`network_security` 写成不是表的东西（字符串、数字、数组、表的数组）也一样处理",
                "整段不是表时整段被忽略",
            ),
        ],
    )
    def test_the_rule_is_stated(self, name: str, now: str, before: str) -> None:
        """旧代码：“整段被忽略，和没有这一段一样”。"""
        text = (REPO / "docs" / name).read_text(encoding="utf-8")

        assert now in text
        assert before not in text
