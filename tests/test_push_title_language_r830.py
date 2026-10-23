"""R830: the title of the push for a new request is in the language the user chose.

Symptom (real stdio MCP server, real Web UI child, a Bark stand-in on a loopback port)
=====================================================================================

Bark, the system notification and the sound share one title, and it was written into the
code in Chinese: ``新的反馈请求`` in ``_dispatch_new_task_notification`` (the path of the
``interactive_feedback`` tool) and ``新的交互反馈请求`` in the deprecated
``launch_feedback_ui``. With ``web_ui.language = "en"``, or an English system, the push on
the phone was a Chinese title over the agent's message; with ``zh-TW`` it was Simplified
Chinese. The *Test Bark* button of the settings page (``POST /api/test-bark``) sent a Chinese
title *and* a Chinese body in the same way, whatever language the page was in. The Web UI
page, the in-page hints and the browser notification (R822) all follow the language; the push
that reaches the phone and the desktop was the one thing that did not.

Fix
===

* ``i18n.resolve_lang(configured)``: an explicit ``web_ui.language`` wins; ``auto`` asks
  ``i18n.detect_system_lang()`` for the language of the operating system and falls back to
  English. A server that writes text with no request in hand has no ``Accept-Language`` to
  ask, and the browser's ``navigator.language`` (what ``auto`` means on the page) is not
  available to it.
* ``i18n.detect_system_lang()``: macOS reads ``AppleLanguages`` from the user's global
  preferences (the GUI processes of an editor have ``LANG=C.UTF-8`` there, and a terminal's
  ``LANG`` carries the *region*, not the display language); Windows asks
  ``GetUserDefaultUILanguage``; everywhere the POSIX variables ``LANGUAGE``, ``LC_ALL``,
  ``LC_MESSAGES`` and ``LANG`` are the last resort, with ``C`` / ``POSIX`` / ``C.UTF-8`` meaning
  "not said". It never raises.
* One new key per text in ``i18n._MESSAGES`` (``notify.newRequestTitle``,
  ``notify.barkTestTitle``, ``notify.barkTestBody``), the zh-CN strings are the ones that were
  hard-coded.
* ``i18n`` no longer imports Flask when it is imported: the MCP server process does not load
  Flask (``import ai_intervention_agent.server`` was measured at 0 of the Web UI modules), and
  a title must not change that.

Matrix
======

A. ``detect_system_lang``: POSIX variables (order, lists, ``C`` locales, encodings and
   modifiers), macOS preferences (precedence over a region-only ``LANG``, unusable files),
   Windows language ids.
B. ``resolve_lang``: explicit, ``auto``, undeterminable, odd spellings.
C. The title ``interactive_feedback`` hands to the notification manager, per language.
D. The same for the deprecated ``launch_feedback_ui``.
E. The settings page's *Test Bark* button: title and body per ``Accept-Language``.
F. No ``title=`` of a push is a fixed CJK string (AST scan of the package).
G. Importing the MCP server and ``i18n`` does not load Flask.
H. The message table: all three languages, zh-CN unchanged, zh-TW not a copy of zh-CN.
"""

from __future__ import annotations

import ast
import asyncio
import ctypes
import plistlib
import re
import subprocess
import sys
import textwrap
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

import ai_intervention_agent.i18n as i18n
import ai_intervention_agent.server_feedback as server
from ai_intervention_agent.server_config import WebUIConfig
from tests.test_bark_url_whitespace_r823 import FakeBark
from tests.test_notification_off_event_loop_r776 import _Harness

REPO_ROOT = Path(__file__).resolve().parent.parent
PACKAGE = REPO_ROOT / "src" / "ai_intervention_agent"

TITLES = {
    "en": "New feedback request",
    "zh-CN": "新的反馈请求",
    "zh-TW": "新的回饋請求",
}


def _write_prefs(home: Path, languages: Any, *, raw: bytes | None = None) -> None:
    folder = home / "Library" / "Preferences"
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / ".GlobalPreferences.plist"
    if raw is not None:
        target.write_bytes(raw)
        return
    with target.open("wb") as handle:
        plistlib.dump(
            {"AppleLanguages": languages, "AppleLocale": "en_US"},
            handle,
            fmt=plistlib.FMT_BINARY,
        )


def _detect(
    *,
    platform: str = "linux",
    environ: dict[str, str] | None = None,
    home: Path | None = None,
) -> str | None:
    return i18n.detect_system_lang(
        platform=platform, environ=environ or {}, home=home or Path("/nonexistent-r830")
    )


class TestSystemLanguageFromPosixVariables:
    @pytest.mark.parametrize(
        ("environ", "expected"),
        [
            ({"LANG": "zh_CN.UTF-8"}, "zh-CN"),
            ({"LANG": "zh_TW.UTF-8"}, "zh-TW"),
            ({"LANG": "zh_HK.UTF-8"}, "zh-TW"),
            ({"LANG": "zh_SG.UTF-8"}, "zh-CN"),
            ({"LANG": "zh"}, "zh-CN"),
            ({"LANG": "zh_CN.GB18030@stroke"}, "zh-CN"),
            # A modifier with no charset in front of it, and blanks around a tag.
            ({"LANG": "zh_TW@stroke"}, "zh-TW"),
            ({"LANG": " zh_TW "}, "zh-TW"),
            ({"LANGUAGE": "fr: zh_TW"}, "zh-TW"),
            ({"LANG": "zh-Hant-TW"}, "zh-TW"),
            ({"LANG": "en_US.UTF-8"}, "en"),
            ({"LANG": "en_GB"}, "en"),
            ({"LANG": "EN_us.utf8"}, "en"),
            ({"LC_ALL": "zh_TW.UTF-8", "LANG": "en_US.UTF-8"}, "zh-TW"),
            ({"LC_MESSAGES": "zh_CN.UTF-8", "LANG": "en_US.UTF-8"}, "zh-CN"),
            ({"LC_ALL": "zh_CN.UTF-8", "LC_MESSAGES": "zh_TW.UTF-8"}, "zh-CN"),
            ({"LANGUAGE": "zh_TW:en", "LANG": "en_US.UTF-8"}, "zh-TW"),
            ({"LANGUAGE": "fr:zh_CN:en"}, "zh-CN"),
            ({"LANGUAGE": ":zh_CN"}, "zh-CN"),
            # A variable that is set but says "no language" does not hide the next one.
            ({"LC_ALL": "C", "LANG": "zh_CN.UTF-8"}, "zh-CN"),
            ({"LC_ALL": "", "LANG": "zh_CN.UTF-8"}, "zh-CN"),
            ({"LC_ALL": "POSIX", "LC_MESSAGES": "C.UTF-8", "LANG": "zh_TW"}, "zh-TW"),
        ],
    )
    def test_the_first_language_the_page_can_speak_is_taken(
        self, environ: dict[str, str], expected: str
    ) -> None:
        assert _detect(environ=environ) == expected

    @pytest.mark.parametrize(
        "environ",
        [
            {},
            {"LANG": ""},
            {"LANG": "C"},
            {"LANG": "C.UTF-8"},
            {"LANG": "POSIX"},
            {"LANG": "fr_FR.UTF-8"},
            {"LANG": "ja_JP.UTF-8", "LC_ALL": "de_DE"},
            {"LANGUAGE": "fr:de"},
            {"LANG": "  "},
        ],
        ids=lambda env: repr(env),
    )
    def test_no_language_is_not_a_guess(self, environ: dict[str, str]) -> None:
        assert _detect(environ=environ) is None


class TestSystemLanguageOnMacOS:
    def test_the_display_language_beats_a_lang_that_only_carries_the_region(
        self, tmp_path: Path
    ) -> None:
        # A terminal on a Chinese macOS with the region set to the United States exports
        # LANG=en_US.UTF-8; the language of the system is still Chinese.
        _write_prefs(tmp_path, ["zh-Hans-CN", "en-US"])
        assert (
            _detect(platform="darwin", environ={"LANG": "en_US.UTF-8"}, home=tmp_path)
            == "zh-CN"
        )

    def test_a_gui_process_with_lang_c_utf8_still_gets_the_system_language(
        self, tmp_path: Path
    ) -> None:
        # What an MCP server started by an editor sees: LANG=C.UTF-8 and nothing else.
        _write_prefs(tmp_path, ["zh-Hans-CN"])
        assert (
            _detect(platform="darwin", environ={"LANG": "C.UTF-8"}, home=tmp_path)
            == "zh-CN"
        )

    @pytest.mark.parametrize(
        ("languages", "expected"),
        [
            (["zh-Hant-TW", "en-TW"], "zh-TW"),
            (["zh-Hant-HK"], "zh-TW"),
            (["zh-Hant"], "zh-TW"),
            (["zh-Hans-CN"], "zh-CN"),
            (["zh-Hans-SG"], "zh-CN"),
            (["en-US", "zh-Hans-CN"], "en"),
            (["en"], "en"),
            # The first language the page can speak, as an application would pick it.
            (["fr-FR", "zh-Hans-CN", "en-FR"], "zh-CN"),
            (["ja-JP", "de-DE"], None),
        ],
    )
    def test_the_list_is_read_like_an_application_reads_it(
        self, tmp_path: Path, languages: list[str], expected: str | None
    ) -> None:
        _write_prefs(tmp_path, languages)
        assert _detect(platform="darwin", home=tmp_path) == expected

    @pytest.mark.parametrize(
        "languages",
        [[], "zh-Hans-CN", 5, [1, 2.5, True, {"a": 1}]],
        ids=["empty list", "a bare string", "a number", "no strings"],
    )
    def test_an_unusable_list_falls_back_to_the_variables(
        self, tmp_path: Path, languages: Any
    ) -> None:
        _write_prefs(tmp_path, languages)
        assert (
            _detect(platform="darwin", environ={"LANG": "zh_TW.UTF-8"}, home=tmp_path)
            == "zh-TW"
        )

    @pytest.mark.parametrize(
        "raw",
        [b"", b"not a plist", b"\x00\x01\x02" * 40, b"<plist><dict></plist>"],
        ids=["empty", "text", "binary garbage", "broken xml"],
    )
    def test_a_file_that_is_not_a_plist_falls_back_and_does_not_raise(
        self, tmp_path: Path, raw: bytes
    ) -> None:
        _write_prefs(tmp_path, None, raw=raw)
        assert (
            _detect(platform="darwin", environ={"LANG": "zh_CN.UTF-8"}, home=tmp_path)
            == "zh-CN"
        )

    def test_a_plist_that_is_not_a_dictionary_falls_back(self, tmp_path: Path) -> None:
        folder = tmp_path / "Library" / "Preferences"
        folder.mkdir(parents=True)
        (folder / ".GlobalPreferences.plist").write_bytes(
            plistlib.dumps(["zh-Hans-CN"], fmt=plistlib.FMT_XML)
        )
        assert (
            _detect(platform="darwin", environ={"LANG": "zh_TW.UTF-8"}, home=tmp_path)
            == "zh-TW"
        )

    def test_a_missing_file_or_a_directory_in_its_place_falls_back(
        self, tmp_path: Path
    ) -> None:
        assert (
            _detect(platform="darwin", environ={"LANG": "zh_CN"}, home=tmp_path)
            == "zh-CN"
        )
        (tmp_path / "Library" / "Preferences" / ".GlobalPreferences.plist").mkdir(
            parents=True
        )
        assert (
            _detect(platform="darwin", environ={"LANG": "zh_TW"}, home=tmp_path)
            == "zh-TW"
        )

    def test_a_machine_without_a_home_directory_falls_back_to_the_variables(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def no_home() -> Path:
            raise RuntimeError("Could not determine home directory.")

        monkeypatch.setattr(Path, "home", no_home)
        assert (
            i18n.detect_system_lang(platform="darwin", environ={"LANG": "zh_TW"})
            == "zh-TW"
        )
        assert i18n.detect_system_lang(platform="darwin", environ={}) is None

    def test_the_preferences_are_only_read_on_macos(self, tmp_path: Path) -> None:
        _write_prefs(tmp_path, ["zh-Hans-CN"])
        assert (
            _detect(platform="linux", environ={"LANG": "en_US"}, home=tmp_path) == "en"
        )
        assert _detect(platform="linux", home=tmp_path) is None


class TestSystemLanguageOnWindows:
    @pytest.mark.parametrize(
        ("langid", "expected"),
        [
            (0x0804, "zh-CN"),  # Chinese (Simplified, PRC)
            (0x1004, "zh-CN"),  # Chinese (Simplified, Singapore)
            (0x0004, "zh-CN"),  # Chinese (Simplified), neutral
            (0x0404, "zh-TW"),  # Chinese (Traditional, Taiwan)
            (0x0C04, "zh-TW"),  # Chinese (Traditional, Hong Kong)
            (0x1404, "zh-TW"),  # Chinese (Traditional, Macao)
            (0x7C04, "zh-TW"),  # Chinese (Traditional), neutral
            (0x0409, "en"),  # English (United States)
            (0x0809, "en"),  # English (United Kingdom)
            (0x0C0A, None),  # Spanish
            (0x0411, None),  # Japanese
        ],
    )
    def test_the_language_id_is_mapped(
        self, monkeypatch: pytest.MonkeyPatch, langid: int, expected: str | None
    ) -> None:
        monkeypatch.setattr(i18n, "_windows_ui_langid", lambda: langid)
        assert _detect(platform="win32") == expected

    def test_a_language_the_page_cannot_speak_falls_back_to_the_variables(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(i18n, "_windows_ui_langid", lambda: 0x0411)
        assert _detect(platform="win32", environ={"LANG": "zh_CN"}) == "zh-CN"

    def test_an_unreadable_language_falls_back_to_the_variables(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(i18n, "_windows_ui_langid", lambda: None)
        assert _detect(platform="win32", environ={"LANG": "zh_TW"}) == "zh-TW"
        assert _detect(platform="win32") is None

    @pytest.mark.skipif(sys.platform == "win32", reason="the call exists on Windows")
    def test_the_call_answers_nothing_where_there_is_no_windows(self) -> None:
        assert i18n._windows_ui_langid() is None

    def test_the_display_language_is_asked_from_kernel32(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        asked: list[str] = []

        def get_user_default_ui_language() -> int:
            asked.append("GetUserDefaultUILanguage")
            return 0x0404

        monkeypatch.setattr(
            ctypes,
            "windll",
            SimpleNamespace(
                kernel32=SimpleNamespace(
                    GetUserDefaultUILanguage=get_user_default_ui_language
                )
            ),
            raising=False,
        )
        assert i18n._windows_ui_langid() == 0x0404
        assert _detect(platform="win32", environ={"LANG": "en_US"}) == "zh-TW"
        assert asked == ["GetUserDefaultUILanguage"] * 2

    def test_a_call_that_fails_is_no_answer_and_does_not_raise(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def broken() -> int:
            raise OSError("no kernel32")

        monkeypatch.setattr(
            ctypes,
            "windll",
            SimpleNamespace(kernel32=SimpleNamespace(GetUserDefaultUILanguage=broken)),
            raising=False,
        )
        assert i18n._windows_ui_langid() is None
        assert _detect(platform="win32", environ={"LANG": "zh_CN"}) == "zh-CN"
        assert _detect(platform="win32") is None

    def test_the_call_is_not_made_elsewhere(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        def boom() -> int:
            raise AssertionError("asked Windows for the language on another system")

        monkeypatch.setattr(i18n, "_windows_ui_langid", boom)
        assert _detect(platform="linux", environ={"LANG": "zh_CN"}) == "zh-CN"
        assert _detect(platform="darwin", home=tmp_path) is None


class TestTheRealMachine:
    def test_it_answers_with_a_supported_language_or_nothing_and_never_raises(
        self,
    ) -> None:
        assert i18n.detect_system_lang() in {None, *i18n.SUPPORTED_LANGS}


class TestResolveLang:
    @pytest.mark.parametrize(
        ("configured", "expected"),
        [
            ("en", "en"),
            ("zh-CN", "zh-CN"),
            ("zh-TW", "zh-TW"),
            (" zh-TW ", "zh-TW"),
            ("ZH-tw", "zh-TW"),
        ],
    )
    def test_an_explicit_language_is_used_and_the_system_is_not_asked(
        self, monkeypatch: pytest.MonkeyPatch, configured: str, expected: str
    ) -> None:
        def boom(**_kwargs: Any) -> str:
            raise AssertionError("the system was asked although the language is set")

        monkeypatch.setattr(i18n, "detect_system_lang", boom)
        assert i18n.resolve_lang(configured) == expected

    @pytest.mark.parametrize("configured", ["auto", "AUTO", " auto ", "", "  ", None])
    @pytest.mark.parametrize("system", ["en", "zh-CN", "zh-TW"])
    def test_auto_follows_the_system(
        self, monkeypatch: pytest.MonkeyPatch, configured: str | None, system: str
    ) -> None:
        monkeypatch.setattr(i18n, "detect_system_lang", lambda **_kw: system)
        assert i18n.resolve_lang(configured) == system

    @pytest.mark.parametrize("configured", ["auto", "", None])
    def test_auto_without_a_system_language_is_english(
        self, monkeypatch: pytest.MonkeyPatch, configured: str | None
    ) -> None:
        monkeypatch.setattr(i18n, "detect_system_lang", lambda **_kw: None)
        assert i18n.resolve_lang(configured) == i18n.DEFAULT_LANG == "en"


def _call(harness: _Harness) -> None:
    """Run one ``interactive_feedback`` call of the harness to its end."""

    async def go() -> None:
        await harness.call()

    asyncio.run(go())


def _title_of_the_push(
    monkeypatch: pytest.MonkeyPatch, language: str, system: str | None = None
) -> str:
    monkeypatch.setattr(i18n, "detect_system_lang", lambda **_kw: system)
    harness = _Harness(
        monkeypatch, WebUIConfig(host="127.0.0.1", port=18998, language=language)
    )
    _call(harness)
    harness.notifier.send_notification.assert_called_once()
    return harness.notifier.send_notification.call_args.kwargs["title"]


class TestTheTitleOfThePushForTheMcpTool:
    @pytest.mark.parametrize("language", ["en", "zh-CN", "zh-TW"])
    def test_a_chosen_language_is_the_language_of_the_title(
        self, monkeypatch: pytest.MonkeyPatch, language: str
    ) -> None:
        # The system says something else, to show it is not what decides here.
        other = "zh-CN" if language != "zh-CN" else "en"
        assert _title_of_the_push(monkeypatch, language, other) == TITLES[language]

    @pytest.mark.parametrize("system", ["en", "zh-CN", "zh-TW"])
    def test_auto_follows_the_system(
        self, monkeypatch: pytest.MonkeyPatch, system: str
    ) -> None:
        assert _title_of_the_push(monkeypatch, "auto", system) == TITLES[system]

    def test_auto_on_a_system_that_does_not_say_is_english(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        assert _title_of_the_push(monkeypatch, "auto", None) == TITLES["en"]

    def test_the_rest_of_the_push_is_what_it_was(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(i18n, "detect_system_lang", lambda **_kw: "zh-TW")
        harness = _Harness(
            monkeypatch,
            WebUIConfig(host="127.0.0.1", port=18998, language="en"),
        )
        _call(harness)
        kwargs = harness.notifier.send_notification.call_args.kwargs
        assert kwargs["message"] == "hello"
        assert [t.name for t in kwargs["types"]] == ["SYSTEM", "SOUND", "BARK"]
        assert kwargs["skip_unavailable"] is True
        assert kwargs["metadata"]["source"] == "interactive_feedback"


class TestTheTitleOfThePushForTheDeprecatedLauncher:
    @pytest.mark.parametrize(
        ("language", "system", "expected"),
        [
            ("en", "zh-CN", "en"),
            ("zh-CN", "en", "zh-CN"),
            ("zh-TW", "en", "zh-TW"),
            ("auto", "zh-TW", "zh-TW"),
            ("auto", None, "en"),
        ],
    )
    def test_it_uses_the_same_title(
        self,
        monkeypatch: pytest.MonkeyPatch,
        language: str,
        system: str | None,
        expected: str,
    ) -> None:
        from tests.test_server_functions import _mock_arun_closing

        monkeypatch.setattr(i18n, "detect_system_lang", lambda **_kw: system)
        config = WebUIConfig(host="127.0.0.1", port=18998, language=language)
        notifier = MagicMock()
        notifier.send_notification.return_value = "event-1"
        response = MagicMock()
        response.status_code = 200
        client = MagicMock()
        client.post.return_value = response

        with (
            patch.object(server, "NOTIFICATION_AVAILABLE", True),
            patch.object(server, "notification_manager", notifier),
            patch.object(
                server.service_manager, "get_web_ui_config", return_value=(config, 120)
            ),
            patch.object(
                server.service_manager, "get_sync_client", return_value=client
            ),
            patch.object(
                server.server_config, "_generate_task_id", return_value="task-r830"
            ),
            patch.object(
                server.asyncio,
                "run",
                side_effect=_mock_arun_closing(
                    None, {"user_input": "done", "selected_options": []}
                ),
            ),
        ):
            result = server.launch_feedback_ui("hello")

        assert result["user_input"] == "done"
        notifier.send_notification.assert_called_once()
        assert notifier.send_notification.call_args.kwargs["title"] == TITLES[expected]


@pytest.fixture
def bark() -> Iterator[FakeBark]:
    stand_in = FakeBark()
    try:
        yield stand_in
    finally:
        stand_in.close()


@pytest.fixture
def settings_client() -> Any:
    from ai_intervention_agent.web_ui import WebFeedbackUI

    ui = WebFeedbackUI(prompt="push title", task_id="rt-r830", port=19130)
    ui.app.config["TESTING"] = True
    ui.limiter.enabled = False
    return ui.app.test_client()


TEST_BODIES = {
    "en": "This is a Bark test notification. If you received it, the configuration is correct.",
    "zh-CN": "这是一个 Bark 通知测试，如果收到此消息，说明配置正确。",
    "zh-TW": "這是一則 Bark 通知測試，如果收到這則訊息，代表設定正確。",
}
TEST_TITLES = {
    "en": "AI Intervention Agent test",
    "zh-CN": "AI Intervention Agent 测试",
    "zh-TW": "AI Intervention Agent 測試",
}


class TestTheTestBarkButton:
    @pytest.fixture(autouse=True)
    def _disable_real_network_requests(self) -> None:
        """Replace the guard of ``conftest.py`` for this class only.

        The guard makes every un-mocked ``httpx`` call fail. What these tests read is the
        title and the body that reach the wire, so the real provider talks to a Bark
        stand-in on a loopback port (``FakeBark``), as in R823.
        """

    def _push(
        self, client: Any, bark: FakeBark, accept_language: str
    ) -> dict[str, Any]:
        response = client.post(
            "/api/test-bark",
            json={"bark_device_key": "KEY123", "bark_url": bark.url()},
            headers={"Accept-Language": accept_language},
        )
        assert response.status_code == 200, response.get_data(as_text=True)
        assert [path for path, _ in bark.requests] == ["/push"]
        return bark.requests[-1][1]

    @pytest.mark.parametrize(
        ("accept_language", "language"),
        [
            ("en-US,en;q=0.9", "en"),
            ("zh-CN,zh;q=0.9,en;q=0.8", "zh-CN"),
            ("zh-TW,zh;q=0.9", "zh-TW"),
            ("zh-Hant-HK", "zh-TW"),
        ],
    )
    def test_the_test_push_is_in_the_language_of_the_page(
        self, settings_client: Any, bark: FakeBark, accept_language: str, language: str
    ) -> None:
        sent = self._push(settings_client, bark, accept_language)
        assert sent["title"] == TEST_TITLES[language]
        assert sent["body"] == TEST_BODIES[language]
        assert sent["device_key"] == "KEY123"


def _is_cjk(text: str) -> bool:
    return re.search(r"[\u3400-\u9fff\uff00-\uffef\u3000-\u303f]", text) is not None


def _fixed_cjk_text(node: ast.AST) -> bool:
    """True when ``node`` is a string literal, or an f-string, holding CJK text."""
    if isinstance(node, ast.Constant):
        return isinstance(node.value, str) and _is_cjk(node.value)
    if isinstance(node, ast.JoinedStr):
        return any(_fixed_cjk_text(part) for part in node.values)
    if isinstance(node, ast.IfExp):
        return _fixed_cjk_text(node.body) or _fixed_cjk_text(node.orelse)
    if isinstance(node, ast.BinOp):
        return _fixed_cjk_text(node.left) or _fixed_cjk_text(node.right)
    return False


def _push_titles(tree: ast.AST) -> Iterator[ast.expr]:
    """The ``title`` handed to ``send_notification(...)`` or ``NotificationEvent(...)``."""
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        target = node.func
        name = (
            target.attr
            if isinstance(target, ast.Attribute)
            else target.id
            if isinstance(target, ast.Name)
            else ""
        )
        if name not in {"send_notification", "NotificationEvent"}:
            continue
        for keyword in node.keywords:
            if keyword.arg == "title":
                yield keyword.value
        if name == "send_notification" and node.args:
            yield node.args[0]


class TestNoPushTitleIsFixedInOneLanguage:
    def test_the_scan_sees_the_titles_it_is_about(self) -> None:
        tree = ast.parse((PACKAGE / "server_feedback.py").read_text(encoding="utf-8"))
        assert len(list(_push_titles(tree))) >= 2

    def test_the_scan_catches_a_literal_and_an_f_string(self) -> None:
        for source in (
            'send_notification(title="新的反馈请求", message="m")',
            'mgr.send_notification(title=f"新的 {x}", message="m")',
            'NotificationEvent(id="1", title="中" if a else "b", message="m")',
            'send_notification("新的反馈请求", "m")',
        ):
            titles = list(_push_titles(ast.parse(source)))
            assert titles
            assert any(_fixed_cjk_text(t) for t in titles), source

    def test_the_scan_lets_a_translated_or_ascii_title_through(self) -> None:
        for source in (
            'send_notification(title=title, message="m")',
            'send_notification(title=msg("notify.newRequestTitle"), message="m")',
            'NotificationEvent(id="1", title="AI Intervention Agent", message="中文")',
        ):
            titles = list(_push_titles(ast.parse(source)))
            assert not any(_fixed_cjk_text(t) for t in titles), source

    def test_no_title_in_the_package_is_a_fixed_cjk_string(self) -> None:
        offenders: list[str] = []
        for path in sorted(PACKAGE.rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for title in _push_titles(tree):
                if _fixed_cjk_text(title):
                    offenders.append(f"{path.relative_to(REPO_ROOT)}:{title.lineno}")
        assert offenders == [], (
            "a push title written in one language: "
            f"{offenders}; use i18n.get_locale_message(..., i18n.resolve_lang(...))"
        )


class TestTheMcpServerStaysLean:
    @staticmethod
    def _loaded(module: str) -> set[str]:
        code = textwrap.dedent(
            f"""
            import sys
            import {module}
            heavy = ("flask", "werkzeug", "jinja2", "flask_limiter", "flask_cors")
            print(sorted(name for name in heavy if name in sys.modules))
            """
        )
        done = subprocess.run(
            [sys.executable, "-W", "ignore", "-c", code],
            check=True,
            capture_output=True,
            text=True,
            timeout=120,
            cwd=REPO_ROOT,
        )
        return set(ast.literal_eval(done.stdout.strip().splitlines()[-1]))

    def test_importing_i18n_does_not_load_flask(self) -> None:
        assert self._loaded("ai_intervention_agent.i18n") == set()

    def test_importing_the_mcp_server_does_not_load_flask(self) -> None:
        assert self._loaded("ai_intervention_agent.server") == set()


class TestTheMessageTable:
    KEYS = ("notify.newRequestTitle", "notify.barkTestTitle", "notify.barkTestBody")

    @pytest.mark.parametrize("language", i18n.SUPPORTED_LANGS)
    def test_every_language_has_every_text(self, language: str) -> None:
        for key in self.KEYS:
            assert i18n._MESSAGES[language].get(key), (language, key)

    def test_the_texts_are_the_ones_that_were_written_into_the_code(self) -> None:
        assert (
            i18n.get_locale_message("notify.newRequestTitle", "zh-CN")
            == TITLES["zh-CN"]
        )
        assert (
            i18n.get_locale_message("notify.barkTestTitle", "zh-CN")
            == TEST_TITLES["zh-CN"]
        )
        assert (
            i18n.get_locale_message("notify.barkTestBody", "zh-CN")
            == TEST_BODIES["zh-CN"]
        )

    def test_english_is_english_and_traditional_is_not_a_copy_of_simplified(
        self,
    ) -> None:
        for key in self.KEYS:
            english = i18n._MESSAGES["en"][key]
            assert not _is_cjk(english), key
            assert i18n._MESSAGES["zh-TW"][key] != i18n._MESSAGES["zh-CN"][key], key
        assert i18n.get_locale_message("notify.newRequestTitle", "en") == TITLES["en"]
        assert (
            i18n.get_locale_message("notify.newRequestTitle", "zh-TW")
            == TITLES["zh-TW"]
        )
        assert (
            i18n.get_locale_message("notify.barkTestTitle", "en") == TEST_TITLES["en"]
        )
        assert i18n.get_locale_message("notify.barkTestBody", "en") == TEST_BODIES["en"]
        assert (
            i18n.get_locale_message("notify.barkTestBody", "zh-TW")
            == TEST_BODIES["zh-TW"]
        )
