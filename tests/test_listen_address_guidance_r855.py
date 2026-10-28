"""R855: the Web UI listens on ``network_security.bind_interface`` - ``web_ui.host`` decides nothing.

``service_manager.get_web_ui_config`` picks the address the Web UI is started on: the env
var ``AI_INTERVENTION_AGENT_WEB_UI_HOST``, else ``network_security.bind_interface``, else
(only when that key is missing) ``web_ui.host``.  The key is never missing - the section is
merged with the defaults, which carry ``bind_interface`` (``"0.0.0.0"`` when this was written,
``"127.0.0.1"`` since R918) - so ``web_ui.host`` is dead.  A real start of the Web UI with
``web_ui.host = "127.0.0.1"`` and nothing else listened on ``*:PORT`` (every interface),
exactly as with no setting at all - that was the default then.

The product kept sending people to the dead key: the Bark hint of the settings page and of
the VS Code panel ("... or change web_ui.host to 0.0.0.0"), two Bark log lines, the two
"cannot reach the Web UI" errors, the troubleshooting guide, the comment of ``host`` in
``config.toml.default``, a table of the configuration guide, the README ("default
127.0.0.1" - the real default is ``0.0.0.0``), and ``scripts/manual_test.py --host``, which
wrote the dead key and so never changed the address.  Someone who followed any of them to
keep the Web UI local ended up with a listener on every interface.

Behaviour was **not** changed by R855 - the default stayed ``0.0.0.0`` and ``web_ui.host``
stayed a fallback.  This file pins what is true (which setting wins, with the real config
loader), and that every place that talks about the listen address names the setting that
works.  R918 changed the default to ``127.0.0.1`` (this computer only); the dead key is still
dead, so ``web_ui.host = "0.0.0.0"`` alone does not open the Web UI to the network either.
"""

from __future__ import annotations

import ast
import contextlib
import importlib.util
import json
import os
import re
import sys
import tempfile
import unittest
from argparse import Namespace
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import patch

from ai_intervention_agent import service_manager
from ai_intervention_agent.config_manager import ConfigManager

REPO = Path(__file__).resolve().parent.parent
PACKAGE = REPO / "src" / "ai_intervention_agent"
ENV_HOST = "AI_INTERVENTION_AGENT_WEB_UI_HOST"
DEAD_KEY = "web_ui.host"
LIVE_KEY = "network_security.bind_interface"

WEB_LOCALES = PACKAGE / "static" / "locales"
PANEL_LOCALES = REPO / "packages" / "vscode" / "locales"
LANGS = ("en", "zh-CN", "zh-TW")


@contextlib.contextmanager
def _real_config(toml: str, *, env: str | None = None) -> Iterator[None]:
    """Run with a real ``ConfigManager`` over ``toml`` and ``ENV_HOST`` set to ``env``.

    The first call of ``get_web_ui_config`` hooks its cache invalidation onto whatever
    ``get_config()`` returns; that is stubbed out so it cannot hook onto this throw-away
    manager and leave the real one unhooked for the tests that run after this one.
    """
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "config.toml"
        path.write_text(toml, encoding="utf-8")
        manager = ConfigManager(str(path))
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


def _listen_address(
    web_ui: str = "", network_security: str = "", env: str | None = None
) -> str:
    toml = f"[web_ui]\nport = 18080\n{web_ui}\n[network_security]\n{network_security}\n"
    with _real_config(toml, env=env):
        config, _ = service_manager.get_web_ui_config()
        return config.host


# (name, [web_ui] lines, [network_security] lines, env var, address the Web UI listens on)
LISTEN_CASES = [
    ("nothing set: this computer only", "", "", None, "127.0.0.1"),
    ("web_ui.host=127.0.0.1 alone", 'host = "127.0.0.1"', "", None, "127.0.0.1"),
    ("web_ui.host=0.0.0.0 alone", 'host = "0.0.0.0"', "", None, "127.0.0.1"),
    ("web_ui.host=192.168.1.5 alone", 'host = "192.168.1.5"', "", None, "127.0.0.1"),
    ("bind_interface=127.0.0.1", "", 'bind_interface = "127.0.0.1"', None, "127.0.0.1"),
    ("bind_interface=0.0.0.0", "", 'bind_interface = "0.0.0.0"', None, "0.0.0.0"),
    (
        "bind_interface beats web_ui.host=0.0.0.0",
        'host = "0.0.0.0"',
        'bind_interface = "127.0.0.1"',
        None,
        "127.0.0.1",
    ),
    (
        "bind_interface beats web_ui.host=127.0.0.1",
        'host = "127.0.0.1"',
        'bind_interface = "0.0.0.0"',
        None,
        "0.0.0.0",
    ),
    ("env var beats the default", "", "", "0.0.0.0", "0.0.0.0"),
    (
        "env var beats bind_interface",
        "",
        'bind_interface = "127.0.0.1"',
        "0.0.0.0",
        "0.0.0.0",
    ),
    (
        "env var beats both",
        'host = "0.0.0.0"',
        'bind_interface = "0.0.0.0"',
        "127.0.0.1",
        "127.0.0.1",
    ),
    ("a blank env var is ignored", "", 'bind_interface = "127.0.0.1"', "  ", "127.0.0.1"),
]  # fmt: skip


class TestWhichSettingChoosesTheListenAddress(unittest.TestCase):
    """What the docs and the hints say must be what the config loader does."""

    def test_the_address_follows_bind_interface_and_the_env_var_only(self) -> None:
        for name, web_ui, network_security, env, expected in LISTEN_CASES:
            with self.subTest(name):
                self.assertEqual(
                    _listen_address(web_ui, network_security, env), expected
                )

    def test_web_ui_host_alone_cannot_open_the_web_ui_to_the_network(self) -> None:
        # The case the advice leads to: "I set web_ui.host to 0.0.0.0 so my phone can
        # connect" - the Web UI still listens on this computer only.
        self.assertEqual(_listen_address(web_ui='host = "0.0.0.0"'), "127.0.0.1")
        self.assertEqual(
            _listen_address(network_security='bind_interface = "0.0.0.0"'),
            "0.0.0.0",
        )


def _string_constants(path: Path) -> Iterator[tuple[int, str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            yield node.lineno, node.value


def _json_strings(value: object, where: str = "") -> Iterator[tuple[str, str]]:
    if isinstance(value, str):
        yield where, value
    elif isinstance(value, dict):
        for key, item in value.items():
            yield from _json_strings(item, f"{where}.{key}" if where else str(key))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from _json_strings(item, f"{where}[{index}]")


# The only sentences of the guides that may name ``web_ui.host`` - each says it decides
# nothing.  Matched against the text with its whitespace collapsed (the guides wrap lines).
GUIDES_ALLOWED_MENTIONS = {
    "troubleshooting.md": [r"`web_ui\.host` does not choose the listen address"],
    "troubleshooting.zh-CN.md": [r"`web_ui\.host` 不决定监听地址"],
    "configuration.md": [
        r"`web_ui\.host` is only a fallback for a config that has no `bind_interface`",
        r"setting `web_ui\.host` alone does \*\*not\*\* change the listen address",
        r'`web_ui\.host = "0\.0\.0\.0"` does not open the Web UI to the network',
    ],
    "configuration.zh-CN.md": [
        r"`web_ui\.host` 只是没有 `bind_interface` 时的回退",
        r"只改 `web_ui\.host` \*\*不会\*\*改变监听地址",
        r'`web_ui\.host = "0\.0\.0\.0"` 不会让 Web UI 对网络开放',
    ],
}


class TestNothingSendsPeopleToTheDeadKey(unittest.TestCase):
    def test_no_string_in_the_package_or_the_manual_test_names_web_ui_host(
        self,
    ) -> None:
        files = [*sorted(PACKAGE.rglob("*.py")), REPO / "scripts" / "manual_test.py"]
        offenders = [
            f"{path.relative_to(REPO)}:{line}: {text.strip()[:70]!r}"
            for path in files
            for line, text in _string_constants(path)
            if DEAD_KEY in text
        ]
        self.assertEqual(offenders, [], "a message or docstring names the dead key")

    def test_no_locale_string_names_web_ui_host(self) -> None:
        offenders = []
        for folder in (WEB_LOCALES, PANEL_LOCALES):
            for lang in LANGS:
                path = folder / f"{lang}.json"
                data = json.loads(path.read_text(encoding="utf-8"))
                offenders += [
                    f"{path.relative_to(REPO)}: {where}"
                    for where, text in _json_strings(data)
                    if DEAD_KEY in text
                ]
        self.assertEqual(offenders, [])

    def test_the_bark_hint_of_the_page_and_the_panel_names_the_live_key(self) -> None:
        for folder, section in (
            (WEB_LOCALES, ("settings",)),
            (PANEL_LOCALES, ("settings", "bark")),
        ):
            for lang in LANGS:
                with self.subTest(folder=folder.parent.name, lang=lang):
                    data = json.loads((folder / f"{lang}.json").read_text("utf-8"))
                    for part in section:
                        data = data[part]
                    text = data["baseUrlSuggestLan"]
                    self.assertIn(LIVE_KEY, text)
                    # still offers the other fix: put the LAN address into external_base_url
                    self.assertIn("web_ui.external_base_url", text)

    def test_the_bark_log_lines_name_the_live_key(self) -> None:
        source = (PACKAGE / "notification_providers.py").read_text(encoding="utf-8")
        self.assertEqual(
            source.count(LIVE_KEY), 2, "two Bark log lines talk about the address"
        )

    def test_the_connection_errors_name_the_live_key(self) -> None:
        for name in ("server_feedback.py", "service_manager.py"):
            with self.subTest(name):
                source = (PACKAGE / name).read_text(encoding="utf-8")
                self.assertRegex(source, rf"{re.escape(LIVE_KEY)}、web_ui\.port")

    def test_the_guides_name_web_ui_host_only_to_say_it_decides_nothing(self) -> None:
        guides = [
            REPO / "README.md",
            REPO / "README.zh-CN.md",
            *sorted((REPO / "docs").glob("configuration*.md")),
            *sorted((REPO / "docs").glob("troubleshooting*.md")),
            *sorted((REPO / "docs").glob("deployment*.md")),
        ]
        for path in guides:
            with self.subTest(path.name):
                flat = " ".join(path.read_text(encoding="utf-8").split())
                allowed = GUIDES_ALLOWED_MENTIONS.get(path.name, [])
                covered = sum(len(re.findall(pattern, flat)) for pattern in allowed)
                self.assertEqual(
                    flat.count(DEAD_KEY),
                    covered,
                    f"{path.name} names web_ui.host outside a sentence that says it decides nothing",
                )
                for pattern in allowed:
                    self.assertTrue(re.search(pattern, flat), pattern)

    def test_the_configuration_guides_say_that_web_ui_host_alone_changes_nothing(
        self,
    ) -> None:
        for name, phrase, row_phrase in (
            (
                "configuration.md",
                "does **not** change the listen address",
                "Not the listen address",
            ),
            ("configuration.zh-CN.md", "**不会**改变监听地址", "不是监听地址"),
        ):
            with self.subTest(name):
                text = (REPO / "docs" / name).read_text(encoding="utf-8")
                self.assertIn(phrase, text)
                rows = [row for row in text.split("\n") if row.startswith("| `host`")]
                self.assertEqual(len(rows), 1)
                self.assertIn(row_phrase, rows[0])
                self.assertIn(LIVE_KEY, rows[0])

    def test_the_configuration_guides_name_bind_interface_for_the_env_var(self) -> None:
        for name in ("configuration.md", "configuration.zh-CN.md"):
            with self.subTest(name):
                text = (REPO / "docs" / name).read_text(encoding="utf-8")
                rows = [
                    row for row in text.split("\n") if row.startswith(f"| `{ENV_HOST}`")
                ]
                self.assertEqual(len(rows), 1)
                self.assertIn(f"| `{LIVE_KEY}`", rows[0])

    def test_the_restart_table_lists_the_key_that_needs_a_restart(self) -> None:
        for name, marker in (
            ("configuration.md", "Read once when the process starts"),
            ("configuration.zh-CN.md", "进程启动时读取一次"),
        ):
            with self.subTest(name):
                text = (REPO / "docs" / name).read_text(encoding="utf-8")
                rows = [
                    row
                    for row in text.split("\n")
                    if row.startswith("|") and marker in row
                ]
                self.assertEqual(len(rows), 1)
                self.assertIn(LIVE_KEY, rows[0])
                self.assertNotIn(DEAD_KEY, rows[0])

    def test_the_readme_gives_the_real_default_listen_address(self) -> None:
        for name in ("README.md", "README.zh-CN.md"):
            with self.subTest(name):
                lines = [
                    line
                    for line in (REPO / name).read_text(encoding="utf-8").split("\n")
                    if line.startswith(f"export {ENV_HOST}=")
                ]
                self.assertEqual(len(lines), 1)
                self.assertIn(
                    "默认 127.0.0.1（"
                    if name.endswith("CN.md")
                    else "default 127.0.0.1 (",
                    lines[0],
                )
                self.assertNotRegex(lines[0], r"(default|默认) 0\.0\.0\.0")

    def test_the_default_config_says_which_key_decides(self) -> None:
        lines = (REPO / "config.toml.default").read_text(encoding="utf-8").split("\n")

        def comment_above(prefix: str) -> str:
            index = next(i for i, line in enumerate(lines) if line.startswith(prefix))
            block = []
            while index > 0 and lines[index - 1].startswith("#"):
                index -= 1
                block.insert(0, lines[index])
            return "\n".join(block)

        host = comment_above('host = "')
        self.assertIn("does NOT choose the listen address", host)
        self.assertIn(LIVE_KEY, host)
        self.assertIn(ENV_HOST, host)
        bind = comment_above("bind_interface = ")
        self.assertIn("the address the Web UI listens on", bind)
        self.assertIn(ENV_HOST, bind)


def _load_manual_test():
    """``scripts/manual_test.py`` as a module (it puts ``scripts/`` on ``sys.path``)."""
    spec = importlib.util.spec_from_file_location(
        "_aiia_manual_test_r855", REPO / "scripts" / "manual_test.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    with patch.object(sys, "path", list(sys.path)):
        spec.loader.exec_module(module)
    return module


def _manual_test_args(host: str | None) -> Namespace:
    return Namespace(
        verbose=False,
        port=None,
        host=host,
        timeout=None,
        thread_timeout=None,
        resubmit_prompt=None,
        prompt_suffix=None,
    )


class TestManualTestHostOption(unittest.TestCase):
    """``scripts/manual_test.py --host`` used to write the dead ``web_ui.host``."""

    def test_the_host_option_changes_the_address_the_web_ui_would_start_on(
        self,
    ) -> None:
        module = _load_manual_test()
        with _real_config("[web_ui]\nport = 18080\n"):
            self.assertEqual(service_manager.get_web_ui_config()[0].host, "127.0.0.1")
            service_manager.reset_config_cache_for_testing()
            self.assertTrue(module.setup_test_environment(_manual_test_args("0.0.0.0")))
            service_manager.reset_config_cache_for_testing()
            self.assertEqual(service_manager.get_web_ui_config()[0].host, "0.0.0.0")

    def test_without_the_host_option_the_environment_is_left_alone(self) -> None:
        module = _load_manual_test()
        with _real_config("[web_ui]\nport = 18080\n"):
            self.assertTrue(module.setup_test_environment(_manual_test_args(None)))
            self.assertNotIn(ENV_HOST, os.environ)
            self.assertEqual(service_manager.get_web_ui_config()[0].host, "127.0.0.1")


if __name__ == "__main__":
    unittest.main()
