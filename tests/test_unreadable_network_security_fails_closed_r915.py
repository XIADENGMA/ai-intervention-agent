"""R915：配置文件读不出来时，network_security 不再退回放开内网的默认值。

现象（旧代码实测）
==================

配置里写着只监听本机、放行一个网段、拉黑一个地址::

    [network_security]
    bind_interface = "127.0.0.1"
    allowed_networks = ["127.0.0.0/8", "192.168.1.0/24"]
    blocked_ips = ["192.168.1.66"]

**一、服务运行中，文件被改成读不出来的样子**（编辑器自动保存下来半截内容，两秒的文件监听
就够了）。``reload()`` 失败后照样清空 network_security 的缓存，随后的配置变更回调重新读文件，
读不出来，又没有缓存可退，于是 Web UI 把正在生效的访问控制换成了默认值。真实 Web UI + 真实文件监听：

====================  ==================  ==================
来源地址               文件改坏之前          文件改坏之后（旧）
====================  ==================  ==================
192.168.1.50          200                 200
192.168.1.66（拉黑）   403                 **200**
10.1.2.3              403                 **200**
172.20.0.5            403                 **200**
====================  ==================  ==================

黑名单被清空、整个内网放行，一直到文件改好为止；改好之后还要等下一轮监听才恢复。

**二、服务启动时文件就读不出来**（TOML 语法错、同一个键写了两次、不是 UTF-8、被截断的
JSON）。MCP 一侧选监听地址、Web UI 一侧选访问控制，读到的都是默认值：

====================  ==================  ==================
全新进程               文件写对              文件读不出来（旧）
====================  ==================  ==================
监听地址               127.0.0.1           **0.0.0.0**
192.168.1.50          200                 200
192.168.1.66（拉黑）   403                 **200**
10.1.2.3              403                 **200**
8.8.8.8               403                 403
====================  ==================  ==================

这和 ``docs/configuration.md`` 的说法也对不上：文档写着文件读不出来时“启动时用默认值，编辑之后沿用
上一份设置”。其他段确实如此（R783：内存里留着上一份好配置），network_security 不在内存里，每次
都重新读文件，两条都落到了默认值。

修复
====

文件存在、有内容、却读不出来时，不知道用户想要什么，就不放开任何东西：

- 之前读到过好的（服务在跑）：继续用它。这一份存在 ``_network_security_last_good``，成功读到文件、
  或成功保存时更新，``invalidate_all_caches()`` 不清它；
- 没有（进程刚启动）：只监听 127.0.0.1、只放行本机回环，其余各项取默认值，日志里一条 ERROR 写明
  文件路径和现在的状态。文件修好之后访问控制自动恢复，监听地址在下次启动服务时恢复。

文件不存在、或没有内容，不走这条路：那是没配置过，仍然是默认值（只监听本机，放行本机和内网网段的来源；
默认监听地址在 R918 之前是所有网卡）。
``WebFeedbackUI._load_network_security_config`` 里“连配置管理器都用不了”的兜底也一样改成只放行本机。

测试矩阵
========

A. 启动时读不出来（六种写法，另有一个没有读取权限的文件）：``get_network_security_config`` 和
   ``get_section`` 给出同一份只放行本机的配置；ERROR 日志写明文件路径和现在的状态；修好之后下一次
   ``reload()`` 就恢复，启动时那份只放行本机的配置不会被当成“上一份好配置”；
B. 对照：文件不存在、空文件、只有注释、只有空行、运行中被删掉，仍然是默认值；
C. 运行中改坏：``reload()`` 之后仍是改坏之前的那一份（六种写法，JSON 和 TOML 各有）；日志说明沿用了
   上一份；好、坏交替时始终跟着最近一份好的；一次都没读过这一段就没有可保留的；
   ``invalidate_all_caches()`` 不会让它被忘记；``reload()`` 之后读到的仍是新文件（R193）；成功保存
   （``update`` / ``set``）之后的那一份也算；文件读不出来时保存仍被拒绝（R783）、不改变生效的配置；
D. ``_load_network_security_config`` 的兜底只放行本机，记 ERROR；
E. 随机对照：24 个种子、每个 100 步（好、坏、读取、失效缓存、保存、重启），对照一个只记“最近一份好配置”
   的模型（2,400 次对照：1,153 次文件是好的，911 次文件是坏的而有好配置在用，336 次文件是坏的、
   没有好配置，159 次保存成功、191 次保存被拒绝）；
F. 真实 Web UI + 真实文件监听（全新进程）：好 → 坏 → 另一份好 → 坏 → 好，每一步各来源地址的状态码；
G. 全新进程启动：监听地址和各来源地址的状态码（四种 TOML 写法），以及写对的文件、没有文件两个对照。

旧代码上 46 个失败；通过的 8 个是对照（B 的五个、``reload()`` 之后读到新文件、全新进程里的两个对照）。
"""

from __future__ import annotations

import json
import logging
import os
import random
import subprocess
import sys
import textwrap
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
import tomlkit

from ai_intervention_agent.config_manager import ConfigManager
from ai_intervention_agent.enhanced_logging import EnhancedLogger
from ai_intervention_agent.web_ui_security import SecurityMixin

LOOPBACK = ["127.0.0.0/8", "::1/128"]
TOKEN = "0123456789abcdef0123456789abcdef"
PORT = 19915

# 读不出来、又没有上一份好配置：只监听本机、只放行本机回环，其余各项取默认值
FAIL_CLOSED = {
    "bind_interface": "127.0.0.1",
    "allowed_networks": LOOPBACK,
    "blocked_ips": [],
    "trusted_hosts": [],
    "trusted_proxy_hops": 1,
    "access_control_enabled": True,
    "api_token": "",
    "api_token_rotated_at": "",
}

# 没配置过（文件不存在、空文件、只有注释）：默认值，只监听本机（R918）、放行内网网段
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

# 两份写对的配置：每一项都和默认值、和彼此不一样，退回默认值或串到另一份都看得出来
TABLE_A: dict[str, Any] = {
    "bind_interface": "127.0.0.1",
    "allowed_networks": ["127.0.0.0/8", "192.168.1.0/24"],
    "blocked_ips": ["192.168.1.66"],
    "trusted_hosts": ["a.example"],
    "trusted_proxy_hops": 2,
    "access_control_enabled": True,
    "api_token": TOKEN,
}
TABLE_B: dict[str, Any] = {
    "bind_interface": "127.0.0.1",
    "allowed_networks": ["127.0.0.0/8", "10.0.0.0/8"],
    "blocked_ips": ["10.9.9.9"],
    "trusted_hosts": ["b.example"],
    "trusted_proxy_hops": 3,
    "access_control_enabled": True,
    "api_token": "",
}


def expected(table: dict[str, Any]) -> dict[str, Any]:
    return {**table, "api_token_rotated_at": ""}


HEADER_NEVER_CLOSED = b'[network_security\nbind_interface = "127.0.0.1"\n'
ARRAY_NEVER_CLOSED = b'[network_security]\nallowed_networks = ["127.0.0.0/8"\n'
KEY_TWICE = (
    b'[network_security]\nbind_interface = "127.0.0.1"\nbind_interface = "0.0.0.0"\n'
)
NOT_UTF8 = b'[network_security]\nbind_interface = "127.0.0.1"\n\xff\xfe\x00 junk\n'
JSON_TRUNCATED = b'{"network_security": {"bind_interface": "127.0.0.1", '
JSON_TWICE = (
    b'{\n  "network_security": {\n    "blocked_ips": ["1.2.3.4"],\n'
    b'    "blocked_ips": ["5.6.7.8"]\n  }\n}\n'
)

# (文件名后缀, 读不出来的内容)。TOML 的四种、JSON 的两种
UNREADABLE = [
    pytest.param(".toml", HEADER_NEVER_CLOSED, id="toml: table header never closed"),
    pytest.param(".toml", ARRAY_NEVER_CLOSED, id="toml: array never closed"),
    pytest.param(".toml", KEY_TWICE, id="toml: a key defined twice"),
    pytest.param(".toml", NOT_UTF8, id="toml: not utf-8"),
    pytest.param(".json", JSON_TRUNCATED, id="json: truncated"),
    pytest.param(".json", JSON_TWICE, id="json: an array defined twice"),
]


def table_text(table: dict[str, Any], suffix: str) -> str:
    if suffix == ".json":
        return json.dumps({"network_security": table}, indent=2)
    return tomlkit.dumps({"network_security": table})


def put(path: Path, content: bytes | str, *, stamp: float | None = None) -> None:
    """换掉文件内容：先写临时文件再 ``os.replace``，监听线程不会读到写了一半的内容。"""
    data = content if isinstance(content, bytes) else content.encode("utf-8")
    scratch = path.with_name(path.name + ".part")
    scratch.write_bytes(data)
    if stamp is not None:
        os.utime(scratch, (stamp, stamp))
    os.replace(scratch, path)


def manager_for(
    tmp_path: Path, suffix: str, content: bytes | str
) -> tuple[Path, ConfigManager]:
    path = tmp_path / f"config{suffix}"
    put(path, content)
    return path, ConfigManager(str(path))


Line = tuple[int, str]


class Collect(logging.Handler):
    def __init__(self, seen: list[Line]) -> None:
        super().__init__()
        self.seen = seen

    def emit(self, record: logging.LogRecord) -> None:
        self.seen.append((record.levelno, record.getMessage()))


@pytest.fixture
def lines(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[Line]]:
    """包里每一条日志的 ``(级别, 文本)``。

    ``EnhancedLogger`` 五秒内不重复写同一条，在 ``caplog`` 里找某条 ERROR，前面的测试写过同样的
    就找不到；这里在去重之前记下来。``config_manager`` 用的是标准 ``logging``，由包 logger 上的
    handler 收集。
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


def errors(lines: list[Line]) -> list[str]:
    return [text for level, text in lines if level >= logging.ERROR]


# ---- A. 启动时读不出来 ---------------------------------------------------------------------------


class TestFirstLoadOfAFileThatCannotBeRead:
    @pytest.mark.parametrize(("suffix", "content"), UNREADABLE)
    def test_only_the_own_machine_is_let_in(
        self, tmp_path: Path, suffix: str, content: bytes
    ) -> None:
        _, manager = manager_for(tmp_path, suffix, content)

        assert manager.get_network_security_config() == FAIL_CLOSED

    @pytest.mark.parametrize(("suffix", "content"), UNREADABLE)
    def test_get_section_gives_the_same(
        self, tmp_path: Path, suffix: str, content: bytes
    ) -> None:
        _, manager = manager_for(tmp_path, suffix, content)

        assert manager.get_section("network_security") == FAIL_CLOSED

    @pytest.mark.skipif(
        sys.platform == "win32" or (hasattr(os, "geteuid") and os.geteuid() == 0),
        reason="needs a file the current user is really not allowed to read",
    )
    def test_a_file_without_read_permission(self, tmp_path: Path) -> None:
        path = tmp_path / "config.toml"
        put(path, table_text(TABLE_A, ".toml"))
        path.chmod(0)
        try:
            assert not os.access(path, os.R_OK)

            assert ConfigManager(str(path)).get_network_security_config() == FAIL_CLOSED
        finally:
            path.chmod(0o600)

    @pytest.mark.parametrize(("suffix", "content"), UNREADABLE)
    def test_one_error_names_the_file_and_what_is_in_force(
        self, tmp_path: Path, lines: list[Line], suffix: str, content: bytes
    ) -> None:
        path, manager = manager_for(tmp_path, suffix, content)
        del lines[:]

        manager.get_network_security_config()

        unreadable = [t for t in errors(lines) if "读取 network_security 配置失败" in t]
        assert len(unreadable) == 1
        assert str(path) in unreadable[0]
        assert "只监听本机" in unreadable[0]
        assert "只放行本机" in unreadable[0]

    def test_fixing_the_file_takes_effect_on_the_next_reload(
        self, tmp_path: Path
    ) -> None:
        path, manager = manager_for(tmp_path, ".toml", HEADER_NEVER_CLOSED)
        assert manager.get_network_security_config() == FAIL_CLOSED

        put(path, table_text(TABLE_A, ".toml"))
        manager.reload()

        assert manager.get_network_security_config() == expected(TABLE_A)

    def test_the_closed_configuration_is_not_remembered_as_a_good_one(
        self, tmp_path: Path
    ) -> None:
        """修好、再改坏：退回修好的那一份，不是启动时那份只放行本机的。"""
        path, manager = manager_for(tmp_path, ".toml", HEADER_NEVER_CLOSED)
        put(path, table_text(TABLE_A, ".toml"))
        manager.reload()
        assert manager.get_network_security_config() == expected(TABLE_A)

        put(path, ARRAY_NEVER_CLOSED)
        manager.reload()

        assert manager.get_network_security_config() == expected(TABLE_A)


# ---- B. 对照：没配置过 ---------------------------------------------------------------------------


class TestNothingConfiguredMeansTheDefaults:
    """文件不存在、空文件、只有注释：没有要读的东西，不是读不出来。用默认值：只监听本机，放行内网网段。"""

    def test_a_missing_file(self, tmp_path: Path) -> None:
        manager = ConfigManager(str(tmp_path / "config.toml"))

        assert manager.get_network_security_config() == DEFAULTS

    @pytest.mark.parametrize(
        "content",
        [b"", b"# nothing here\n", b"\n\n  \n"],
        ids=["empty", "only a comment", "only blank lines"],
    )
    def test_a_file_with_nothing_in_it(self, tmp_path: Path, content: bytes) -> None:
        _, manager = manager_for(tmp_path, ".toml", content)

        assert manager.get_network_security_config() == DEFAULTS

    def test_a_file_deleted_while_the_service_runs(self, tmp_path: Path) -> None:
        """删掉配置文件就是“重置”（R783：删掉后重新生成默认文件），不是“读不出来”。"""
        path, manager = manager_for(tmp_path, ".toml", table_text(TABLE_A, ".toml"))
        assert manager.get_network_security_config() == expected(TABLE_A)
        path.unlink()

        manager.invalidate_all_caches()

        assert manager.get_network_security_config() == DEFAULTS


# ---- C. 运行中改坏 -------------------------------------------------------------------------------


class TestTheConfigurationInForceSurvivesAFileThatBreaks:
    @pytest.mark.parametrize(("suffix", "content"), UNREADABLE)
    def test_reload_keeps_what_was_in_force(
        self, tmp_path: Path, suffix: str, content: bytes
    ) -> None:
        path, manager = manager_for(tmp_path, suffix, table_text(TABLE_A, suffix))
        assert manager.get_network_security_config() == expected(TABLE_A)

        put(path, content)
        manager.reload()

        assert manager.get_network_security_config() == expected(TABLE_A)
        assert manager.get_section("network_security") == expected(TABLE_A)

    @pytest.mark.parametrize(("suffix", "content"), UNREADABLE)
    def test_the_log_says_the_previous_configuration_is_kept(
        self, tmp_path: Path, lines: list[Line], suffix: str, content: bytes
    ) -> None:
        path, manager = manager_for(tmp_path, suffix, table_text(TABLE_A, suffix))
        manager.get_network_security_config()
        put(path, content)
        del lines[:]

        manager.reload()
        manager.get_network_security_config()

        unreadable = [t for t in errors(lines) if "读取 network_security 配置失败" in t]
        assert len(unreadable) == 1
        assert str(path) in unreadable[0]
        assert "沿用上一次读到的配置" in unreadable[0]

    def test_the_configuration_follows_the_latest_good_file(
        self, tmp_path: Path
    ) -> None:
        path, manager = manager_for(tmp_path, ".toml", table_text(TABLE_A, ".toml"))
        assert manager.get_network_security_config() == expected(TABLE_A)
        seen = []

        for content in (
            HEADER_NEVER_CLOSED,
            table_text(TABLE_B, ".toml"),
            KEY_TWICE,
            NOT_UTF8,
            table_text(TABLE_A, ".toml"),
            ARRAY_NEVER_CLOSED,
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
        """“在用的配置”是最近一次读到的那份；一次都没读过（服务启动后还没有任何请求）就没有可保留的，
        按启动时读不出来处理：只放行本机。"""
        path, manager = manager_for(tmp_path, ".toml", table_text(TABLE_A, ".toml"))

        put(path, HEADER_NEVER_CLOSED)
        manager.reload()

        assert manager.get_network_security_config() == FAIL_CLOSED

    def test_invalidating_the_caches_does_not_make_it_forget(
        self, tmp_path: Path
    ) -> None:
        """``invalidate_all_caches()`` 逼下一次重新读文件，不是让我们忘掉正在生效的配置。"""
        path, manager = manager_for(tmp_path, ".toml", table_text(TABLE_A, ".toml"))
        manager.get_network_security_config()
        put(path, HEADER_NEVER_CLOSED)

        manager.invalidate_all_caches()

        assert manager.get_network_security_config() == expected(TABLE_A)

    def test_a_good_file_is_still_read_fresh_after_a_reload(
        self, tmp_path: Path
    ) -> None:
        """R193 的承诺不变：``reload()`` 之后读到的是新文件，没有 30 秒的旧缓存窗口。"""
        path, manager = manager_for(tmp_path, ".toml", table_text(TABLE_A, ".toml"))
        manager.get_network_security_config()

        put(path, table_text(TABLE_B, ".toml"))
        manager.reload()

        assert manager.get_network_security_config() == expected(TABLE_B)

    @pytest.mark.parametrize("how", ["update", "set"])
    def test_what_a_save_put_in_force_is_what_is_kept(
        self, tmp_path: Path, how: str
    ) -> None:
        path, manager = manager_for(tmp_path, ".toml", table_text(TABLE_A, ".toml"))
        manager.get_network_security_config()
        if how == "update":
            manager.update_network_security_config({"blocked_ips": ["1.2.3.4"]})
            saved = {**expected(TABLE_A), "blocked_ips": ["1.2.3.4"]}
        else:
            manager.set_network_security_config(TABLE_B)
            saved = expected(TABLE_B)
        assert manager.get_network_security_config() == saved

        put(path, HEADER_NEVER_CLOSED)
        manager.reload()

        assert manager.get_network_security_config() == saved

    def test_a_save_is_still_refused_while_the_file_cannot_be_read(
        self, tmp_path: Path
    ) -> None:
        """R783 不变：读不出来的文件不被覆盖；生效的配置也不因为这次被拒绝的保存而变。"""
        path, manager = manager_for(tmp_path, ".toml", table_text(TABLE_A, ".toml"))
        manager.get_network_security_config()
        broken = HEADER_NEVER_CLOSED
        put(path, broken)
        manager.reload()

        with pytest.raises(RuntimeError):
            manager.update_network_security_config({"blocked_ips": ["1.2.3.4"]})

        assert path.read_bytes() == broken
        assert manager.get_network_security_config() == expected(TABLE_A)


# ---- D. Web UI 一侧的兜底 ------------------------------------------------------------------------


class TestTheWebUiFallbackWhenTheConfigManagerIsUnusable:
    def test_only_the_own_machine_is_let_in(self, lines: list[Line]) -> None:
        class Stub(SecurityMixin):
            pass

        with patch(
            "ai_intervention_agent.web_ui_security.get_config",
            side_effect=RuntimeError("config not initialized"),
        ):
            result = Stub()._load_network_security_config()

        assert result["bind_interface"] == "127.0.0.1"
        assert result["allowed_networks"] == LOOPBACK
        assert result["blocked_ips"] == []
        assert result["access_control_enabled"] is True
        assert [t for t in errors(lines) if "无法加载网络安全配置" in t]


# ---- E. 随机对照 ---------------------------------------------------------------------------------

NETWORK_POOL = [
    "127.0.0.0/8",
    "::1/128",
    "192.168.1.0/24",
    "192.168.0.0/16",
    "10.0.0.0/8",
    "172.16.0.0/12",
    "203.0.113.0/24",
]
BLOCKED_POOL = ["192.168.1.66", "10.9.9.9", "203.0.113.7", "198.51.100.0/24"]
BROKEN_TOML = [
    HEADER_NEVER_CLOSED,
    ARRAY_NEVER_CLOSED,
    b"[network_security]\nbind_interface = \xff\xfe\n",
    b"= = =\n",
]
SEEDS = range(24)
STEPS_PER_SEED = 100


def random_table(rng: random.Random) -> dict[str, Any]:
    return {
        "bind_interface": rng.choice(["127.0.0.1", "0.0.0.0"]),
        "allowed_networks": rng.sample(NETWORK_POOL, rng.randint(1, 4)),
        "blocked_ips": rng.sample(BLOCKED_POOL, rng.randint(0, 3)),
        "trusted_hosts": rng.sample(["a.example", "b.example"], rng.randint(0, 2)),
        "trusted_proxy_hops": rng.randint(0, 3),
        "access_control_enabled": rng.choice([True, False]),
        "api_token": rng.choice(["", TOKEN]),
    }


class TestAgainstAModelThatOnlyRemembersTheLatestGoodConfiguration:
    def test_random_sequences(self, tmp_path: Path) -> None:
        # 每次 ``get_network_security_config`` 对照时，文件和生效配置处于哪种状况
        checks = {
            "good file": 0,
            "broken file, a good one in force": 0,
            "broken file, nothing in force": 0,
        }
        refused_saves = 0
        saves = 0
        mismatches: list[str] = []

        for seed in SEEDS:
            rng = random.Random(seed)
            path = tmp_path / f"seed{seed}.toml"
            in_force: dict[str, Any] | None = None
            file_is_good = rng.random() < 0.5
            if file_is_good:
                table = random_table(rng)
                put(path, table_text(table, ".toml"))
                in_force = expected(table)
            else:
                put(path, rng.choice(BROKEN_TOML))
            manager = ConfigManager(str(path))
            manager.get_network_security_config()  # 服务启动时读一次
            want = in_force if in_force is not None else FAIL_CLOSED

            for step in range(STEPS_PER_SEED):
                operation = rng.choices(
                    ["good", "broken", "read", "invalidate", "save", "restart"],
                    weights=[3, 3, 2, 1, 2, 1],
                )[0]
                label = f"seed {seed} step {step} {operation}"
                if operation == "good":
                    table = random_table(rng)
                    put(path, table_text(table, ".toml"))
                    manager.reload()
                    in_force = expected(table)
                    want = in_force
                    file_is_good = True
                elif operation == "broken":
                    put(path, rng.choice(BROKEN_TOML))
                    manager.reload()
                    want = in_force if in_force is not None else FAIL_CLOSED
                    file_is_good = False
                elif operation == "invalidate":
                    manager.invalidate_all_caches()
                elif operation == "restart":
                    # 新进程：什么都不记得，只看文件
                    manager = ConfigManager(str(path))
                    manager.get_network_security_config()
                    if not file_is_good:
                        in_force = None
                    want = in_force if in_force is not None else FAIL_CLOSED
                elif operation == "save":
                    blocked = rng.sample(BLOCKED_POOL, rng.randint(0, 3))
                    if file_is_good:
                        assert in_force is not None
                        manager.update_network_security_config({"blocked_ips": blocked})
                        in_force = {**in_force, "blocked_ips": blocked}
                        want = in_force
                        saves += 1
                    else:
                        before = path.read_bytes()
                        try:
                            manager.update_network_security_config(
                                {"blocked_ips": blocked}
                            )
                        except RuntimeError:
                            refused_saves += 1
                        else:
                            mismatches.append(f"{label}: a save went through")
                        if path.read_bytes() != before:
                            mismatches.append(f"{label}: the broken file was rewritten")
                if file_is_good:
                    checks["good file"] += 1
                elif in_force is not None:
                    checks["broken file, a good one in force"] += 1
                else:
                    checks["broken file, nothing in force"] += 1
                actual = manager.get_network_security_config()
                if actual != want:
                    mismatches.append(f"{label}: {actual!r} != {want!r}")

        assert mismatches[:5] == []
        # 序列里真的走到了各条路径，不是空转
        assert checks["good file"] >= 800, checks
        assert checks["broken file, a good one in force"] >= 600, checks
        assert checks["broken file, nothing in force"] >= 250, checks
        assert refused_saves >= 120, refused_saves
        assert saves >= 100, saves


# ---- F / G. 全新进程：真实 Web UI、真实文件监听 --------------------------------------------------

PEERS = ["127.0.0.1", "192.168.1.50", "192.168.1.66", "10.1.2.3", "10.9.9.9", "8.8.8.8"]

# 配置 A 放行 127.0.0.0/8 和 192.168.1.0/24、拉黑 192.168.1.66；
# 配置 B 放行 127.0.0.0/8 和 10.0.0.0/8、拉黑 10.9.9.9
STATUS_A = {
    "127.0.0.1": 200,
    "192.168.1.50": 200,
    "192.168.1.66": 403,
    "10.1.2.3": 403,
    "10.9.9.9": 403,
    "8.8.8.8": 403,
}
STATUS_B = {
    "127.0.0.1": 200,
    "192.168.1.50": 403,
    "192.168.1.66": 403,
    "10.1.2.3": 200,
    "10.9.9.9": 403,
    "8.8.8.8": 403,
}
STATUS_LOOPBACK_ONLY = {
    "127.0.0.1": 200,
    "192.168.1.50": 403,
    "192.168.1.66": 403,
    "10.1.2.3": 403,
    "10.9.9.9": 403,
    "8.8.8.8": 403,
}

WATCHED_SCRIPT = textwrap.dedent(
    """
    import json
    import logging
    import os
    import sys
    import threading
    import time
    from pathlib import Path

    logging.disable(logging.CRITICAL)
    from ai_intervention_agent.config_manager import config_manager, get_config
    from ai_intervention_agent.web_ui import WebFeedbackUI

    path = Path(os.environ["AI_INTERVENTION_AGENT_CONFIG_FILE"])
    peers = json.loads(sys.argv[1])
    steps = json.loads(sys.argv[2])
    port = int(sys.argv[3])

    config_manager.start_file_watcher(interval=0.1)  # before get_config() starts the 2 s one
    ui = WebFeedbackUI(prompt="x", task_id="t", auto_resubmit_timeout=0, port=port)
    ui.app.config["TESTING"] = False
    ui.limiter.enabled = False
    client = ui.app.test_client()


    def ask():
        return {
            ip: client.get(
                "/api/health",
                environ_base={"REMOTE_ADDR": ip},
                headers={"Host": "127.0.0.1:%d" % port},
            ).status_code
            for ip in peers
        }


    seen = [ask()]  # the first request loads the config and registers the hot-reload hook
    changed = threading.Event()
    get_config().register_config_change_callback(changed.set)  # runs after the Web UI's own
    stamp = time.time()
    for text in steps:
        changed.clear()
        stamp += 10  # a strictly newer mtime whatever the file system's resolution
        part = path.with_name(path.name + ".part")
        part.write_bytes(text.encode("utf-8"))
        os.utime(part, (stamp, stamp))
        os.replace(part, path)
        if not changed.wait(30):
            raise SystemExit("the file watcher did not report the change")
        seen.append(ask())
    print(json.dumps(seen))
    """
)

FIRST_LOAD_SCRIPT = textwrap.dedent(
    """
    import json
    import logging
    import sys

    logging.disable(logging.CRITICAL)
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
    print(json.dumps({"host": config.host, "status": status}))
    """
)


def fresh_process(script: str, path: Path, *arguments: str) -> Any:
    env = {
        name: value
        for name, value in os.environ.items()
        if not name.startswith("AI_INTERVENTION_AGENT_WEB_UI")
    }
    env["AI_INTERVENTION_AGENT_CONFIG_FILE"] = str(path)
    done = subprocess.run(
        [sys.executable, "-c", script, *arguments],
        env=env,
        cwd=path.parent,
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert done.returncode == 0, done.stderr[-2000:]
    return json.loads(done.stdout.strip().splitlines()[-1])


class TestTheRunningWebUiKeepsEnforcingWhileTheFileIsBroken:
    def test_good_then_broken_then_another_good_then_broken(
        self, tmp_path: Path
    ) -> None:
        path = tmp_path / "config.toml"
        put(path, table_text(TABLE_A, ".toml"))
        steps = [
            HEADER_NEVER_CLOSED.decode(),
            table_text(TABLE_B, ".toml"),
            KEY_TWICE.decode(),
            table_text(TABLE_A, ".toml"),
        ]

        seen = fresh_process(
            WATCHED_SCRIPT, path, json.dumps(PEERS), json.dumps(steps), str(PORT)
        )

        assert seen == [
            STATUS_A,  # 启动
            STATUS_A,  # 改坏：照旧，黑名单还在，内网没有放开
            STATUS_B,  # 改成另一份好的：马上生效
            STATUS_B,  # 又改坏：停在 B
            STATUS_A,  # 改好：回到 A
        ]


# 全新进程里 ``AI_INTERVENTION_AGENT_CONFIG_FILE`` 指向旧的 ``config.json`` 时，全局的配置管理器会先把它迁移成
# ``config.toml``（旧版本留下的 JSON 配置），所以这里只用 TOML 的写法
UNREADABLE_TOML = [p for p in UNREADABLE if p.values[0] == ".toml"]


class TestAFreshProcessWithAFileThatCannotBeRead:
    @pytest.mark.parametrize(("suffix", "content"), UNREADABLE_TOML)
    def test_it_listens_on_loopback_and_lets_only_the_own_machine_in(
        self, tmp_path: Path, suffix: str, content: bytes
    ) -> None:
        path = tmp_path / f"config{suffix}"
        put(path, content)

        result = fresh_process(FIRST_LOAD_SCRIPT, path, json.dumps(PEERS))

        assert result == {"host": "127.0.0.1", "status": STATUS_LOOPBACK_ONLY}

    def test_control_the_same_file_written_correctly(self, tmp_path: Path) -> None:
        path = tmp_path / "config.toml"
        put(path, table_text(TABLE_A, ".toml"))

        result = fresh_process(FIRST_LOAD_SCRIPT, path, json.dumps(PEERS))

        assert result == {"host": "127.0.0.1", "status": STATUS_A}

    def test_control_no_file_at_all_keeps_the_defaults(self, tmp_path: Path) -> None:
        """全新安装：只监听本机（R918），放行内网网段的来源，其余和以前一样。"""
        result = fresh_process(
            FIRST_LOAD_SCRIPT, tmp_path / "config.toml", json.dumps(PEERS)
        )

        assert result["host"] == "127.0.0.1"
        assert result["status"] == {
            "127.0.0.1": 200,
            "192.168.1.50": 200,
            "192.168.1.66": 200,
            "10.1.2.3": 200,
            "10.9.9.9": 200,
            "8.8.8.8": 403,
        }
