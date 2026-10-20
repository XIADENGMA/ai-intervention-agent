"""R795 — 配置文件里写旧名字（文档承诺兼容的那几个）真的生效。

事故现场
--------
``docs/configuration.md`` 的 "Backward compatibility" 一节承诺：

* feedback：``timeout`` → ``backend_max_wait``，``auto_resubmit_timeout`` → ``frontend_countdown``
* web_ui：``max_retries`` → ``http_max_retries``，``retry_delay`` → ``http_retry_delay``

代码里也确实有读取逻辑——``get_compat_config(section, new, old, default)``："新键在就用新键，
否则用旧键，再否则用默认值"。可是 ``ConfigManager._load_config`` 在任何人读取之前就把默认值合并进了
配置（``_merge_config``），于是 **新键永远在**，值是默认值，旧键一次都没被读到：

* 只写了 ``auto_resubmit_timeout = 120`` 的配置文件，倒计时跑的是 240；
* 只写了 ``timeout = 900``，MCP 侧的等待跑的是 600；
* 只写了 ``max_retries = 7``，Web UI 的 HTTP 重试是 3 次；
* ``web_ui.timeout`` → ``http_request_timeout`` 代码里有、文档没写，同样失效。

更糟的是第一次保存：``_update_toml_table`` 把内存配置里 **所有** 键写回文件，包括默认值填出来的
新键。只写了旧名字的文件，在 Web UI 里改任何一项设置之后多出一行 ``frontend_countdown = 240``，
把用户自己写的旧值永久盖掉。

没人发现，是因为这几个读取点的测试都把 ``get_section`` 换成了手写的 dict（里面没有被默认值填满的
新键）；``get_compat_config`` 自己的测试也只喂手写 dict。

契约
----
* 文件里只有旧名字：加载时把它的值放到新名字上，之后和直接写新名字完全一样——同样的校验、范围
  裁剪、R791 的"读不出来就用默认值"。
* 两个都有：新名字赢（哪怕新名字写的恰好是默认值）。
* 只认表里的 5 对，而且只在对应的那一段里；别的段里同名的键（``notification.retry_delay`` 是现行
  名字）不动。
* 加载本身不改文件，旧键留在原处；日志里有一条 INFO 提示"这是旧名字，已按新名字读取"。
* 旧版的 ``config.jsonc`` / ``config.json`` 迁移成 TOML 时也一样：模板里的新键带着默认值，
  旧名字不先放到新名字上就会被盖住。
* 进程退出时会把合并了默认值的配置写回文件（既有行为）；写回去的是旧名字对应的值，不是默认值——
  否则退出一次，用户写的旧值就在文件里被默认值永久盖掉。
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import sys
import tomllib
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from ai_intervention_agent import server_config, service_manager
from ai_intervention_agent.config_manager import ConfigManager
from ai_intervention_agent.config_utils import (
    LEGACY_KEY_ALIASES,
    apply_legacy_key_aliases,
)
from ai_intervention_agent.shared_types import SECTION_MODELS

CONFIG_LOGGER = "ai_intervention_agent.config_manager"
HINT_LOGGER = "ai_intervention_agent.config_utils"
REPO = Path(__file__).resolve().parent.parent

# (段, 旧名, 新名, 写在文件里的值, 加载后新名上的值)——写的值都和默认值不同
PAIRS: list[tuple[str, str, str, Any, Any]] = [
    ("feedback", "timeout", "backend_max_wait", 900, 900),
    ("feedback", "auto_resubmit_timeout", "frontend_countdown", 120, 120),
    ("web_ui", "max_retries", "http_max_retries", 7, 7),
    ("web_ui", "retry_delay", "http_retry_delay", 2.5, 2.5),
    ("web_ui", "timeout", "http_request_timeout", 41, 41),
]
PAIR_IDS = [f"{section}.{old}" for section, old, *_ in PAIRS]

LEGACY_ONLY: dict[str, dict[str, Any]] = {
    "feedback": {"timeout": 900, "auto_resubmit_timeout": 120},
    "web_ui": {"max_retries": 7, "retry_delay": 2.5, "timeout": 41},
}


def _default(section: str, field: str) -> Any:
    return SECTION_MODELS[section]().model_dump()[field]


def _toml(sections: dict[str, dict[str, Any]]) -> str:
    """数字和简单字符串的 JSON 写法恰好也是合法的 TOML 字面量。"""
    lines: list[str] = []
    for name, keys in sections.items():
        lines.append(f"[{name}]")
        lines.extend(f"{key} = {json.dumps(value)}" for key, value in keys.items())
        lines.append("")
    return "\n".join(lines)


@pytest.fixture
def make_manager(tmp_path: Path) -> Iterator[Callable[..., ConfigManager]]:
    created: list[ConfigManager] = []

    def make(
        sections: dict[str, dict[str, Any]], name: str = "config.toml"
    ) -> ConfigManager:
        path = tmp_path / name
        text = json.dumps(sections) if name.endswith(".json") else _toml(sections)
        path.write_text(text, encoding="utf-8")
        manager = ConfigManager(str(path))
        created.append(manager)
        return manager

    try:
        yield make
    finally:
        for manager in created:
            manager.shutdown()


# ---------------------------------------------------------------------------
# 1. 表
# ---------------------------------------------------------------------------
class TestTheTable:
    def test_the_table_has_the_five_pairs(self) -> None:
        assert {(s, o, n) for s, o, n, *_ in PAIRS} == set(LEGACY_KEY_ALIASES)

    @pytest.mark.parametrize(("section", "old", "new"), LEGACY_KEY_ALIASES)
    def test_every_pair_maps_an_old_name_to_a_current_field(
        self, section: str, old: str, new: str
    ) -> None:
        fields = SECTION_MODELS[section].model_fields
        assert new in fields, f"{section}.{new} 不是 {section} 段的字段"
        assert old not in fields, f"{section}.{old} 是现行字段，不能当旧名字"

    @pytest.mark.parametrize(("section", "old", "new"), LEGACY_KEY_ALIASES)
    def test_the_template_declares_the_new_name_and_not_the_old_one(
        self, section: str, old: str, new: str
    ) -> None:
        """``tests/test_config_docs_inline_parity.py`` 因为这张表而允许文档引用旧名字；
        模板里要是已经有了旧名字，或者没有新名字，这个豁免就是过期的。"""
        template = tomllib.loads((REPO / "config.toml.default").read_text("utf-8"))
        assert new in template[section]
        assert old not in template[section]

    @pytest.mark.parametrize(
        ("doc", "heading"),
        [
            ("docs/configuration.md", "## Backward compatibility"),
            ("docs/configuration.zh-CN.md", "## 向后兼容"),
        ],
    )
    def test_the_docs_list_exactly_the_aliases_the_code_honours(
        self, doc: str, heading: str
    ) -> None:
        text = (REPO / doc).read_text(encoding="utf-8")
        block = text.split(heading, 1)[1].split("\n## ", 1)[0]
        documented: set[tuple[str, str, str]] = set()
        section = ""
        for line in block.splitlines():
            head = re.match(r"- \*\*(\w+)\*\*", line)
            if head:
                section = head.group(1)
                continue
            pair = re.match(r"\s+- `(\w+)` → `(\w+)`", line)
            if pair:
                documented.add((section, pair.group(1), pair.group(2)))
        # network_security 的别名由 NetworkSecurityMixin 直接读文件里的原始值，
        # 不经过默认值合并，所以不在这张表里
        expected = set(LEGACY_KEY_ALIASES) | {
            ("network_security", "enable_access_control", "access_control_enabled")
        }
        assert documented == expected


# ---------------------------------------------------------------------------
# 2. 函数本身
# ---------------------------------------------------------------------------
class TestTheFunction:
    def test_it_copies_the_old_value_to_the_new_name_in_place(self) -> None:
        config: dict[str, Any] = {"feedback": {"timeout": 5}}
        applied = apply_legacy_key_aliases(config)
        assert config == {"feedback": {"timeout": 5, "backend_max_wait": 5}}
        assert applied == [("feedback", "timeout", "backend_max_wait")]

    def test_it_leaves_a_new_name_alone_even_when_it_is_falsy(self) -> None:
        config: dict[str, Any] = {
            "feedback": {"timeout": 5, "backend_max_wait": 0},
            "web_ui": {"max_retries": 9, "http_max_retries": 0},
        }
        before = json.dumps(config, sort_keys=True)
        assert apply_legacy_key_aliases(config) == []
        assert json.dumps(config, sort_keys=True) == before

    @pytest.mark.parametrize(
        "config",
        [
            {},
            {"feedback": 5},
            {"feedback": None, "web_ui": "x"},
            {"feedback": [], "web_ui": [("timeout", 1)]},
            {"notification": {"retry_delay": 5, "timeout": 3}},
        ],
        ids=repr,
    )
    def test_it_ignores_what_is_not_a_section_or_not_in_the_table(
        self, config: dict[str, Any]
    ) -> None:
        before = json.dumps(config, sort_keys=True, default=repr)
        assert apply_legacy_key_aliases(config) == []
        assert json.dumps(config, sort_keys=True, default=repr) == before


# ---------------------------------------------------------------------------
# 3. 只有旧名字
# ---------------------------------------------------------------------------
class TestAnOldNameAloneIsHonoured:
    @pytest.mark.parametrize(
        ("section", "old", "new", "written", "expected"), PAIRS, ids=PAIR_IDS
    )
    def test_each_pair(
        self,
        make_manager: Callable[..., ConfigManager],
        section: str,
        old: str,
        new: str,
        written: Any,
        expected: Any,
    ) -> None:
        manager = make_manager({section: {old: written}})
        values = manager.get_section(section)
        assert values[new] == expected
        assert values[new] != _default(section, new), "测试值不能恰好等于默认值"
        assert values[old] == written, "旧键留在原处"

    def test_all_five_at_once(self, make_manager: Callable[..., ConfigManager]) -> None:
        manager = make_manager(LEGACY_ONLY)
        feedback = manager.get_section("feedback")
        web_ui = manager.get_section("web_ui")
        assert (feedback["backend_max_wait"], feedback["frontend_countdown"]) == (
            900,
            120,
        )
        assert (
            web_ui["http_max_retries"],
            web_ui["http_retry_delay"],
            web_ui["http_request_timeout"],
        ) == (7, 2.5, 41)

    def test_loading_does_not_rewrite_the_file(
        self, make_manager: Callable[..., ConfigManager], tmp_path: Path
    ) -> None:
        manager = make_manager(LEGACY_ONLY)
        path = tmp_path / "config.toml"
        before = path.read_bytes()
        manager.reload()
        manager.get_section("feedback")
        assert path.read_bytes() == before

    def test_a_json_config_file_works_too(
        self, make_manager: Callable[..., ConfigManager]
    ) -> None:
        manager = make_manager(LEGACY_ONLY, name="config.json")
        assert manager.get_section("feedback")["frontend_countdown"] == 120
        assert manager.get_section("web_ui")["http_max_retries"] == 7

    @pytest.mark.parametrize(
        "text",
        [
            "feedback.auto_resubmit_timeout = 120\nfeedback.timeout = 900\n"
            "web_ui.max_retries = 7\nweb_ui.retry_delay = 2.5\nweb_ui.timeout = 41\n",
            "feedback = { auto_resubmit_timeout = 120, timeout = 900 }\n"
            "web_ui = { max_retries = 7, retry_delay = 2.5, timeout = 41 }\n",
        ],
        ids=["dotted-keys", "inline-tables"],
    )
    def test_other_ways_to_spell_a_toml_table(self, tmp_path: Path, text: str) -> None:
        path = tmp_path / "config.toml"
        path.write_text(text, encoding="utf-8")
        manager = ConfigManager(str(path))
        try:
            feedback = manager.get_section("feedback")
            web_ui = manager.get_section("web_ui")
            assert (feedback["frontend_countdown"], feedback["backend_max_wait"]) == (
                120,
                900,
            )
            assert (
                web_ui["http_max_retries"],
                web_ui["http_retry_delay"],
                web_ui["http_request_timeout"],
            ) == (7, 2.5, 41)
        finally:
            manager.shutdown()

    def test_a_hint_names_the_old_and_the_new_key(
        self,
        make_manager: Callable[..., ConfigManager],
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        with caplog.at_level(logging.INFO, logger=HINT_LOGGER):
            make_manager({"feedback": {"auto_resubmit_timeout": 120}})
        hints = [
            r.getMessage()
            for r in caplog.records
            if "feedback.auto_resubmit_timeout" in r.getMessage()
        ]
        assert len(hints) == 1, hints
        assert "feedback.frontend_countdown" in hints[0]
        assert [r for r in caplog.records if r.levelno >= logging.WARNING] == []


# ---------------------------------------------------------------------------
# 4. 新名字赢
# ---------------------------------------------------------------------------
class TestTheNewNameWins:
    @pytest.mark.parametrize(
        ("section", "old", "new", "written", "expected"), PAIRS, ids=PAIR_IDS
    )
    def test_both_present(
        self,
        make_manager: Callable[..., ConfigManager],
        section: str,
        old: str,
        new: str,
        written: Any,
        expected: Any,
    ) -> None:
        other = 15 if isinstance(expected, int) else 3.5
        manager = make_manager({section: {old: written, new: other}})
        assert manager.get_section(section)[new] == other

    @pytest.mark.parametrize(
        ("section", "old", "new", "written", "expected"), PAIRS, ids=PAIR_IDS
    )
    def test_a_new_name_that_equals_its_default_still_wins(
        self,
        make_manager: Callable[..., ConfigManager],
        section: str,
        old: str,
        new: str,
        written: Any,
        expected: Any,
    ) -> None:
        default = _default(section, new)
        manager = make_manager({section: {old: written, new: default}})
        assert manager.get_section(section)[new] == default

    def test_the_hint_is_not_logged_when_the_new_name_is_there(
        self,
        make_manager: Callable[..., ConfigManager],
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        with caplog.at_level(logging.DEBUG, logger=HINT_LOGGER):
            make_manager(
                {"feedback": {"auto_resubmit_timeout": 120, "frontend_countdown": 300}}
            )
        assert not [
            r
            for r in caplog.records
            if "feedback.auto_resubmit_timeout" in r.getMessage()
        ]


# ---------------------------------------------------------------------------
# 5. 只认表里的、只在对应的段里
# ---------------------------------------------------------------------------
class TestOnlyTheListedPairsInTheirOwnSections:
    def test_notification_keeps_its_own_current_names(
        self, make_manager: Callable[..., ConfigManager]
    ) -> None:
        manager = make_manager({"notification": {"retry_delay": 5, "retry_count": 4}})
        notification = manager.get_section("notification")
        assert notification["retry_delay"] == 5
        assert notification["retry_count"] == 4
        # web_ui 里没有写旧名字，notification 的同名键不能漏过去
        assert manager.get_section("web_ui")["http_retry_delay"] == 1.0

    def test_a_key_in_the_wrong_section_is_not_mapped(
        self, make_manager: Callable[..., ConfigManager]
    ) -> None:
        manager = make_manager(
            {
                "web_ui": {"auto_resubmit_timeout": 99},
                "feedback": {"max_retries": 9, "retry_delay": 4},
            }
        )
        assert manager.get_section("feedback")["frontend_countdown"] == 240
        assert manager.get_section("web_ui")["http_max_retries"] == 3
        assert manager.get_section("web_ui")["http_retry_delay"] == 1.0

    def test_the_same_old_name_means_different_things_in_different_sections(
        self, make_manager: Callable[..., ConfigManager]
    ) -> None:
        manager = make_manager(
            {"feedback": {"timeout": 900}, "web_ui": {"timeout": 41}}
        )
        assert manager.get_section("feedback")["backend_max_wait"] == 900
        assert manager.get_section("feedback").get("http_request_timeout") is None
        assert manager.get_section("web_ui")["http_request_timeout"] == 41
        assert manager.get_section("web_ui").get("backend_max_wait") is None


# ---------------------------------------------------------------------------
# 6. 旧值照样被校验
# ---------------------------------------------------------------------------
class TestTheValueIsValidatedLikeAnyOther:
    @pytest.mark.parametrize(
        ("section", "old", "new", "written", "expected"),
        [
            ("feedback", "timeout", "backend_max_wait", 1, 10),
            ("feedback", "timeout", "backend_max_wait", 10**6, 7200),
            ("feedback", "auto_resubmit_timeout", "frontend_countdown", 5, 10),
            ("feedback", "auto_resubmit_timeout", "frontend_countdown", 99999, 3600),
            ("web_ui", "max_retries", "http_max_retries", 99, 20),
            ("web_ui", "max_retries", "http_max_retries", -3, 0),
            ("web_ui", "retry_delay", "http_retry_delay", 1000, 60),
            ("web_ui", "timeout", "http_request_timeout", 0, 1),
            ("web_ui", "timeout", "http_request_timeout", 99999, 600),
        ],
    )
    def test_out_of_range_is_clamped(
        self,
        make_manager: Callable[..., ConfigManager],
        section: str,
        old: str,
        new: str,
        written: Any,
        expected: Any,
    ) -> None:
        manager = make_manager({section: {old: written}})
        assert manager.get_section(section)[new] == expected

    def test_zero_still_means_the_countdown_is_off(
        self, make_manager: Callable[..., ConfigManager]
    ) -> None:
        manager = make_manager({"feedback": {"auto_resubmit_timeout": 0}})
        assert manager.get_section("feedback")["frontend_countdown"] == 0

    @pytest.mark.parametrize(
        ("section", "old", "new", "written", "expected"), PAIRS, ids=PAIR_IDS
    )
    def test_an_unreadable_old_value_becomes_the_default_not_an_error(
        self,
        make_manager: Callable[..., ConfigManager],
        section: str,
        old: str,
        new: str,
        written: Any,
        expected: Any,
    ) -> None:
        manager = make_manager({section: {old: "soon"}})
        assert manager.get_section(section)[new] == _default(section, new)

    @pytest.mark.parametrize(
        ("section", "old", "new", "written", "expected"), PAIRS, ids=PAIR_IDS
    )
    def test_a_json_null_becomes_the_default(
        self,
        make_manager: Callable[..., ConfigManager],
        section: str,
        old: str,
        new: str,
        written: Any,
        expected: Any,
    ) -> None:
        manager = make_manager({section: {old: None}}, name="config.json")
        assert manager.get_section(section)[new] == _default(section, new)


# ---------------------------------------------------------------------------
# 7. reload
# ---------------------------------------------------------------------------
class TestReload:
    def test_edits_are_followed_in_both_directions(
        self, make_manager: Callable[..., ConfigManager], tmp_path: Path
    ) -> None:
        manager = make_manager({"feedback": {"auto_resubmit_timeout": 120}})
        path = tmp_path / "config.toml"
        assert manager.get_section("feedback")["frontend_countdown"] == 120

        path.write_text(
            _toml({"feedback": {"auto_resubmit_timeout": 150}}), encoding="utf-8"
        )
        manager.reload()
        assert manager.get_section("feedback")["frontend_countdown"] == 150

        path.write_text(
            _toml(
                {"feedback": {"auto_resubmit_timeout": 150, "frontend_countdown": 300}}
            ),
            encoding="utf-8",
        )
        manager.reload()
        assert manager.get_section("feedback")["frontend_countdown"] == 300

        path.write_text(_toml({"feedback": {}}), encoding="utf-8")
        manager.reload()
        assert manager.get_section("feedback")["frontend_countdown"] == 240


# ---------------------------------------------------------------------------
# 8. 保存
# ---------------------------------------------------------------------------
class TestSaving:
    def test_a_save_keeps_the_value_the_user_wrote(
        self, make_manager: Callable[..., ConfigManager], tmp_path: Path
    ) -> None:
        """修之前：保存把默认值填出来的 ``frontend_countdown = 240`` 写进文件，
        盖掉用户写的 ``auto_resubmit_timeout = 120``——这个旧值永远丢了。"""
        manager = make_manager(LEGACY_ONLY)
        manager.set("feedback.prompt_suffix", "\nnext", save=False)
        manager._save_config_immediate()

        path = tmp_path / "config.toml"
        written = path.read_text(encoding="utf-8")
        assert re.search(r"^frontend_countdown = 120$", written, re.MULTILINE), written
        assert re.search(r"^backend_max_wait = 900$", written, re.MULTILINE), written
        assert re.search(r"^auto_resubmit_timeout = 120$", written, re.MULTILINE)

        again = ConfigManager(str(path))
        try:
            feedback = again.get_section("feedback")
            web_ui = again.get_section("web_ui")
            assert feedback["frontend_countdown"] == 120
            assert feedback["backend_max_wait"] == 900
            assert (web_ui["http_max_retries"], web_ui["http_retry_delay"]) == (7, 2.5)
        finally:
            again.shutdown()

    def test_changing_the_new_name_afterwards_wins_over_the_old_one(
        self, make_manager: Callable[..., ConfigManager], tmp_path: Path
    ) -> None:
        manager = make_manager({"feedback": {"auto_resubmit_timeout": 120}})
        manager.set("feedback.frontend_countdown", 300, save=False)
        manager._save_config_immediate()

        again = ConfigManager(str(tmp_path / "config.toml"))
        try:
            assert again.get_section("feedback")["frontend_countdown"] == 300
        finally:
            again.shutdown()


# ---------------------------------------------------------------------------
# 8b. 旧版 JSONC / JSON 迁移成 TOML
# ---------------------------------------------------------------------------
class TestMigrationFromTheOldFileFormats:
    """``config.jsonc`` / ``config.json`` 首次加载时迁移成 TOML：模板里的新键带着默认值，
    叠加用户的键时把旧名字盖住。迁移前先把旧名字的值放到新名字上。"""

    # 显式路径加载 .jsonc 时按普通 JSON 解析（不认注释），所以直接调迁移函数的测试用没有注释的内容；
    # 真正会带注释的是下面"首次加载"那个测试，它走的是 parse_jsonc
    LEGACY_JSON = (
        "{\n"
        '  "feedback": {"timeout": 900, "auto_resubmit_timeout": 120},\n'
        '  "web_ui": {"max_retries": 7, "retry_delay": 2.5, "timeout": 41}\n'
        "}\n"
    )
    LEGACY_JSONC = "// 旧版配置\n" + LEGACY_JSON

    def _assert_migrated_values(self, toml_path: Path) -> None:
        assert toml_path.suffix == ".toml"
        text = toml_path.read_text(encoding="utf-8")
        assert re.search(r"^frontend_countdown = 120$", text, re.MULTILINE), text
        assert re.search(r"^backend_max_wait = 900$", text, re.MULTILINE), text
        assert re.search(r"^http_max_retries = 7$", text, re.MULTILINE), text
        # 旧名字也还在
        assert re.search(r"^auto_resubmit_timeout = 120$", text, re.MULTILINE), text

        reloaded = ConfigManager(str(toml_path))
        try:
            feedback = reloaded.get_section("feedback")
            web_ui = reloaded.get_section("web_ui")
            assert (feedback["frontend_countdown"], feedback["backend_max_wait"]) == (
                120,
                900,
            )
            assert (
                web_ui["http_max_retries"],
                web_ui["http_retry_delay"],
                web_ui["http_request_timeout"],
            ) == (7, 2.5, 41)
        finally:
            reloaded.shutdown()

    def test_migrating_a_jsonc_file_keeps_the_values_of_the_old_names(
        self, tmp_path: Path
    ) -> None:
        old = tmp_path / "config.jsonc"
        old.write_text(self.LEGACY_JSON, encoding="utf-8")
        manager = ConfigManager(str(old))
        try:
            assert manager._migrate_jsonc_to_toml() is True
            manager.reload()  # 生产里 _load_config 迁移之后紧接着读新文件
            self._assert_migrated_values(manager.config_file)
        finally:
            manager.shutdown()

    def test_the_first_load_of_a_found_jsonc_file_does_the_whole_thing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """没有显式路径（环境变量覆盖）时，``_load_config`` 自己发现 ``.jsonc`` 并迁移。"""
        old = tmp_path / "config.jsonc"
        old.write_text(self.LEGACY_JSONC, encoding="utf-8")
        monkeypatch.setenv("AI_INTERVENTION_AGENT_CONFIG_FILE", str(old))
        manager = ConfigManager()
        try:
            assert manager.config_file == tmp_path / "config.toml"
            assert manager.get_section("feedback")["frontend_countdown"] == 120
            assert manager.get_section("web_ui")["http_max_retries"] == 7
            self._assert_migrated_values(manager.config_file)
        finally:
            manager.shutdown()

    def test_migrating_without_a_template_keeps_them_too(self, tmp_path: Path) -> None:
        old = tmp_path / "config.jsonc"
        old.write_text(self.LEGACY_JSON, encoding="utf-8")
        manager = ConfigManager(str(old))
        try:
            with patch(
                "ai_intervention_agent.config_manager.find_default_config_template",
                return_value=None,
            ):
                assert manager._migrate_jsonc_to_toml() is True
            manager.reload()
            text = manager.config_file.read_text(encoding="utf-8")
            assert re.search(r"^frontend_countdown = 120$", text, re.MULTILINE), text
        finally:
            manager.shutdown()

    def test_a_new_name_in_the_old_file_still_wins(self, tmp_path: Path) -> None:
        old = tmp_path / "config.jsonc"
        old.write_text(
            '{"feedback": {"auto_resubmit_timeout": 120, "frontend_countdown": 300}}',
            encoding="utf-8",
        )
        manager = ConfigManager(str(old))
        try:
            assert manager._migrate_jsonc_to_toml() is True
            manager.reload()
            text = manager.config_file.read_text(encoding="utf-8")
            assert re.search(r"^frontend_countdown = 300$", text, re.MULTILINE), text
        finally:
            manager.shutdown()


# ---------------------------------------------------------------------------
# 9. 每个读取点都看得到
# ---------------------------------------------------------------------------
class TestEveryReaderSeesIt:
    def test_the_mcp_side_feedback_config(
        self,
        make_manager: Callable[..., ConfigManager],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        manager = make_manager(LEGACY_ONLY)
        monkeypatch.setattr(server_config, "get_config", lambda: manager)
        config = server_config.get_feedback_config()
        assert config.timeout == 900
        assert config.auto_resubmit_timeout == 120

    def test_the_web_ui_config(
        self,
        make_manager: Callable[..., ConfigManager],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        manager = make_manager(LEGACY_ONLY)
        monkeypatch.setattr(service_manager, "get_config", lambda: manager)
        monkeypatch.setitem(service_manager._config_cache, "config", None)
        monkeypatch.setitem(service_manager._config_cache, "timestamp", 0.0)
        config, auto_resubmit_timeout = service_manager.get_web_ui_config()
        assert auto_resubmit_timeout == 120
        assert config.max_retries == 7
        assert config.retry_delay == 2.5
        assert config.timeout == 41

    def test_the_default_countdown_the_web_ui_gives_new_tasks(
        self,
        make_manager: Callable[..., ConfigManager],
    ) -> None:
        import ai_intervention_agent.web_ui as web_ui_module
        from ai_intervention_agent.web_ui_config_sync import (
            _get_default_auto_resubmit_timeout_from_config,
        )

        manager = make_manager(LEGACY_ONLY)
        with patch.object(web_ui_module, "get_config", lambda: manager):
            assert _get_default_auto_resubmit_timeout_from_config() == 120

    def test_the_feedback_prompts_route(
        self, make_manager: Callable[..., ConfigManager]
    ) -> None:
        from ai_intervention_agent.web_ui import WebFeedbackUI

        manager = make_manager(LEGACY_ONLY)
        web_ui = WebFeedbackUI(prompt="r795", task_id="r795", port=19795)
        web_ui.app.config["TESTING"] = True
        client = web_ui.app.test_client()
        with patch(
            "ai_intervention_agent.web_ui_routes.notification.get_config",
            return_value=manager,
        ):
            response = client.get("/api/get-feedback-prompts")
        assert response.status_code == 200
        assert response.get_json()["config"]["frontend_countdown"] == 120


# ---------------------------------------------------------------------------
# 10. 真实进程
# ---------------------------------------------------------------------------
class TestRealProcess:
    def test_print_config_shows_the_values_from_the_old_names(
        self, tmp_path: Path
    ) -> None:
        path = tmp_path / "config.toml"
        path.write_text(_toml(LEGACY_ONLY), encoding="utf-8")
        env = {
            **os.environ,
            "AI_INTERVENTION_AGENT_CONFIG_FILE": str(path),
            "HOME": str(tmp_path / "home"),
            "XDG_CONFIG_HOME": str(tmp_path / "xdg"),
            "APPDATA": str(tmp_path / "appdata"),
            "AI_INTERVENTION_AGENT_USER_MODE": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
        }
        env.pop("AI_INTERVENTION_AGENT_DEV_MODE", None)
        proc = subprocess.run(
            [sys.executable, "-m", "ai_intervention_agent.server", "--print-config"],
            env=env,
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        assert proc.returncode == 0, proc.stderr[-2000:]
        sections = json.loads(proc.stdout)["sections"]
        assert sections["feedback"]["frontend_countdown"] == 120
        assert sections["feedback"]["backend_max_wait"] == 900
        assert sections["web_ui"]["http_max_retries"] == 7
        assert sections["web_ui"]["http_retry_delay"] == 2.5
        assert sections["web_ui"]["http_request_timeout"] == 41

        # 进程退出时会把合并了默认值的配置写回文件（既有行为）。写回去的必须是旧名字对应的值：
        # 修之前这里是默认值（frontend_countdown = 240），旧值在第一次退出时就被盖死了。
        text = path.read_text(encoding="utf-8")
        assert re.search(r"^frontend_countdown = 120$", text, re.MULTILINE), text
        assert re.search(r"^backend_max_wait = 900$", text, re.MULTILINE), text
        assert re.search(r"^http_retry_delay = 2.5$", text, re.MULTILINE), text
        assert re.search(r"^auto_resubmit_timeout = 120$", text, re.MULTILINE), text
