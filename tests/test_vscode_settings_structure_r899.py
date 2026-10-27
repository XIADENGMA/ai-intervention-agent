"""R899: the settings page of the VS Code panel is organised around what the user does there.

TODO "界面优化 8": the logic of the settings page (function, UX, display) "has some problems".  Looked at
in a real VS Code, the page had these:

* the title said "Notification Settings" over a page that also holds the feedback and configuration
  settings, and the first two rows had no section title of their own;
* "Enable Notifications" and "macOS Native Notification" were two bare switches: nothing said that the
  first one is a master switch, or what the second one does and what happens without it;
* the "macOS Native Notification" row was shown on Windows, Linux and remote hosts, where it can never work;
* the test buttons lived in a row at the very bottom, next to the "Auto-save" badge, two screens away from
  the switches they test (and the Bark test button was not next to the Bark fields);
* the status line below the header reserved an empty strip at the top of every page;
* turning the master switch off left every channel looking active.

Now the page reads top to bottom as "Notifications / Feedback / Configuration": a header with the title,
the "Auto-save" badge and the close button, the status line (only when it has something to say), the
master switch with a line of explanation, and under it the channels (the macOS row only on a macOS host,
the "Test Notification" button, Bark with its own "Test Bark" button at the end of its fields).  Switching
the master switch off dims the channels - they stay usable, so Bark can be set up first.

This file checks the markup (parsed, not grepped), the styles that carry the behaviour, the strings, and the
real script in Node against a small fake DOM.  The extension-host half (the macOS row is hidden in the
markup unless the host is macOS) is in ``packages/vscode/test/settings-structure.test.js``.
"""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from typing import Any, cast

import pytest

from tests.test_bark_settings_display_r852 import Dom, Node, _plugin_dom
from tests.test_vscode_notification_test_button_r898 import _run

REPO_ROOT = Path(__file__).resolve().parents[1]
VSCODE = REPO_ROOT / "packages" / "vscode"
WEBVIEW_TS = VSCODE / "webview.ts"
WEBVIEW_CSS = VSCODE / "webview.css"
SETTINGS_UI_JS = VSCODE / "webview-settings-ui.js"
LOCALES = ["en", "zh-CN", "zh-TW"]
CJK = re.compile(r"[\u4e00-\u9fff]")

needs_node = pytest.mark.skipif(
    shutil.which("node") is None, reason="node runtime unavailable"
)


def _classes(node: Node) -> set[str]:
    return set(node.attr("class").split())


def _find(root: Node, cls: str) -> list[Node]:
    return [n for n in root.descendants() if cls in _classes(n)]


def _order(dom: Dom) -> list[str]:
    """Ids in document order."""
    return [n.attr("id") for n in dom.root.descendants() if n.attr("id")]


def _locale(lang: str) -> dict[str, Any]:
    return json.loads((VSCODE / "locales" / f"{lang}.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def dom() -> Dom:
    return _plugin_dom()


# --- the frame: a labelled dialog with a tidy header ----------------------------------------------


def test_the_panel_is_a_labelled_dialog(dom: Dom) -> None:
    panel = dom.get("settingsPanel")
    assert panel.attr("role") == "dialog"
    assert panel.attr("aria-modal") == "true"
    title = dom.get(panel.attr("aria-labelledby"))
    assert title.attr("id") == "settingsTitle"
    assert title.attr("data-i18n") == "settings.title"


def test_the_header_keeps_title_badge_and_close_button_together(dom: Dom) -> None:
    (header,) = _find(dom.get("settingsPanel"), "settings-header")
    title, right = header.children
    assert title.attr("id") == "settingsTitle"
    assert "settings-header-right" in _classes(right)
    badge, close = right.children
    assert "settings-auto-save" in _classes(badge)
    assert close.attr("id") == "settingsClose"
    assert close.tag == "button" and close.attr("type") == "button"
    assert close.attr("aria-label") and close.attr("data-i18n-aria-label")


def test_the_status_line_sits_between_the_header_and_the_body(dom: Dom) -> None:
    panel = dom.get("settingsPanel")
    kinds = [
        _classes(c) & {"settings-header", "settings-hint", "settings-body"}
        for c in panel.children
    ]
    assert kinds[:3] == [{"settings-header"}, {"settings-hint"}, {"settings-body"}]
    hint = dom.get("settingsHint")
    assert hint.attr("role") == "status" and hint.attr("aria-live") == "polite"


# --- the notifications section -------------------------------------------------------------------


def test_the_notifications_section_is_titled_and_comes_first(dom: Dom) -> None:
    (body,) = _find(dom.get("settingsPanel"), "settings-body")
    first = body.children[0]
    assert "settings-section-title" in _classes(first)
    assert first.attr("data-i18n") == "settings.notifications.title"
    titles = [n.attr("data-i18n") for n in _find(body, "settings-section-title")]
    assert titles == [
        "settings.notifications.title",
        "settings.feedback.title",
        "settings.config.title",
    ]


def test_the_master_switch_explains_itself_and_controls_the_channels(dom: Dom) -> None:
    master = dom.get("notifyEnabled")
    assert master.attr("aria-controls") == "settingsChannels"
    assert (
        dom.get(master.attr("aria-labelledby")).attr("data-i18n") == "settings.enabled"
    )
    assert (
        dom.get(master.attr("aria-describedby")).attr("data-i18n")
        == "settings.enabledHint"
    )
    channels = dom.get("settingsChannels")
    assert not master.inside(channels), (
        "the master switch must stay outside what it governs"
    )
    # the explanation is part of the row, so a click on it flips the switch as well
    row = master.parent
    assert row is not None and row.tag == "label"
    assert dom.get("notifyEnabledHint").inside(row)


def test_the_channels_group_holds_everything_the_master_switch_governs(
    dom: Dom,
) -> None:
    channels = dom.get("settingsChannels")
    for element_id in (
        "settingsMacosRow",
        "notifyMacOSNativeEnabled",
        "settingsTestNotifyBtn",
        "notifyBarkEnabled",
        "settingsBarkFields",
        "settingsTestBarkBtn",
    ):
        assert dom.get(element_id).inside(channels), element_id
    order = _order(dom)
    assert order.index("notifyEnabled") < order.index("settingsChannels")
    assert (
        order.index("settingsMacosRow")
        < order.index("settingsTestNotifyBtn")
        < order.index("notifyBarkEnabled")
    )


def test_the_macos_row_says_what_it_does_and_the_host_can_hide_it(dom: Dom) -> None:
    box = dom.get("notifyMacOSNativeEnabled")
    hint = dom.get(box.attr("aria-describedby"))
    assert hint.attr("data-i18n") == "settings.macosNativeHint"
    assert (
        dom.get(box.attr("aria-labelledby")).attr("data-i18n") == "settings.macosNative"
    )
    row = dom.get("settingsMacosRow")
    assert box.inside(row) and hint.inside(row)
    # `${macosRowHidden}` sits in the opening tag of the row (the helper renders it as an attribute "x")
    ts = WEBVIEW_TS.read_text(encoding="utf-8")
    assert 'id="settingsMacosRow"${macosRowHidden}' in ts
    assert 'const macosRowHidden = hostPlatform === "darwin" ? "" : " hidden";' in ts


def test_each_test_button_sits_next_to_what_it_tests(dom: Dom) -> None:
    channels = dom.get("settingsChannels")
    notify = dom.get("settingsTestNotifyBtn")
    assert notify.inside(channels) and not notify.inside(dom.get("settingsBarkFields"))
    bark_group = dom.get("settingsBarkFields")
    bark = dom.get("settingsTestBarkBtn")
    assert bark.inside(bark_group)
    # at the end of the Bark fields, after the last field and not in a row of its own further down
    last_field = _order(dom).index("notifyBarkUrlTemplate")
    assert _order(dom).index("settingsTestBarkBtn") > last_field


def test_there_is_no_bottom_action_row_any_more(dom: Dom) -> None:
    panel = dom.get("settingsPanel")
    (body,) = _find(panel, "settings-body")
    # the body ends with the footer; the only `settings-actions` rows are the two test-button rows
    rows = _find(body, "settings-actions")
    assert [{n.attr("id") for n in r.children} for r in rows] == [
        {"settingsTestNotifyBtn"},
        {"settingsTestBarkBtn"},
    ]
    assert "settings-footer" in _classes(body.children[-1])
    ts = WEBVIEW_TS.read_text(encoding="utf-8")
    css = WEBVIEW_CSS.read_text(encoding="utf-8")
    assert "settings-actions-right" not in ts
    assert "settings-actions-right" not in css


def test_every_button_in_the_overlay_declares_its_type(dom: Dom) -> None:
    overlay = dom.get("settingsOverlay")
    buttons = [n for n in overlay.descendants() if n.tag == "button"]
    assert len(buttons) >= 6
    assert [n.attr("id") for n in buttons if n.attr("type") != "button"] == []


# --- the styles that carry the behaviour -----------------------------------------------------------


def _rule(css: str, selector: str) -> str:
    m = re.search(re.escape(selector) + r"\s*\{([^}]*)\}", css)
    assert m, f"no rule for {selector}"
    return m.group(1)


def test_an_empty_status_line_takes_no_room() -> None:
    css = WEBVIEW_CSS.read_text(encoding="utf-8")
    assert "display: none" in _rule(css, ".settings-hint:empty")
    assert "min-height" not in _rule(css, ".settings-hint")


def test_muted_channels_are_dimmed_but_stay_usable() -> None:
    css = WEBVIEW_CSS.read_text(encoding="utf-8")
    muted = _rule(css, ".settings-channels.is-muted")
    opacity = re.search(r"opacity:\s*([0-9.]+)", muted)
    assert opacity and 0.4 <= float(opacity.group(1)) < 1
    assert "pointer-events" not in muted and "filter" not in muted


def test_the_hidden_attribute_still_beats_the_toggle_display() -> None:
    # `.settings-toggle` is `display: flex`; the macOS row relies on this rule to disappear.
    css = WEBVIEW_CSS.read_text(encoding="utf-8")
    assert re.search(r"^\[hidden\]\s*\{\s*display:\s*none\s*!important;", css, re.M)


# --- strings ----------------------------------------------------------------------------------------


@pytest.mark.parametrize("lang", LOCALES)
def test_the_new_strings_exist_in_every_language(lang: str) -> None:
    loc = _locale(lang)
    s = loc["settings"]
    for text in (
        s["title"],
        s["notifications"]["title"],
        s["enabledHint"],
        s["macosNativeHint"],
    ):
        assert isinstance(text, str) and text.strip()
    # one word for the thing that opens the panel and the panel it opens
    assert s["title"] == loc["ui"]["settingsBtn"]
    assert (lang == "en") == (
        not CJK.search(s["title"] + s["enabledHint"] + s["macosNativeHint"])
    )


def test_the_title_no_longer_claims_the_page_is_only_about_notifications() -> None:
    assert _locale("en")["settings"]["title"] == "Settings"
    assert _locale("zh-CN")["settings"]["title"] == "设置"
    assert _locale("zh-TW")["settings"]["title"] == "設定"


def test_the_macos_hint_says_where_the_notification_goes_instead() -> None:
    for lang in LOCALES:
        hint = _locale(lang)["settings"]["macosNativeHint"]
        assert "VS Code" in hint, lang


# --- the script -------------------------------------------------------------------------------------

SETTINGS = (
    "{ enabled: __ENABLED__, macosNativeEnabled: __NATIVE__, barkEnabled: false,"
    ' barkUrl: "https://api.day.app/push", barkDeviceKey: "", barkIcon: "",'
    ' barkAction: "none", barkUrlTemplate: "{base_url}/?task_id={task_id}" }'
)


def _settings(enabled: bool, native: bool = False) -> str:
    return SETTINGS.replace("__ENABLED__", json.dumps(enabled)).replace(
        "__NATIVE__", json.dumps(native)
    )


@needs_node
def test_the_channels_are_muted_exactly_when_the_master_switch_is_off() -> None:
    case = """
        const channels = __element("settingsChannels");
        const states = [];
        for (const enabled of [false, true, false]) {
          AIIAWebviewNotifyCore.setCachedNotificationSettings(__SETTINGS__(enabled));
          await AIIAWebviewSettingsUi.openSettings();
          states.push([enabled, channels.classList.contains("is-muted")]);
        }
        return JSON.stringify(states);
    """.replace(
        "__SETTINGS__(enabled)",
        "Object.assign(" + _settings(True) + ", { enabled })",
    )
    assert _run(case) == [[False, True], [True, False], [False, True]]


@needs_node
def test_flipping_the_master_switch_mutes_and_unmutes_at_once() -> None:
    case = """
        const channels = __element("settingsChannels");
        const master = __element("notifyEnabled");
        await AIIAWebviewSettingsUi.openSettings();
        const seen = [channels.classList.contains("is-muted")];
        for (const checked of [false, true, false]) {
          master.checked = checked;
          __element("settingsPanel").dispatch("change", { target: master });
          seen.push(channels.classList.contains("is-muted"));
        }
        return JSON.stringify(seen);
    """
    out = _run(
        f"AIIAWebviewNotifyCore.setCachedNotificationSettings({_settings(True)});"
        + case
    )
    assert out == [False, True, False, True]


@needs_node
def test_a_page_without_the_channels_group_still_works() -> None:
    case = """
        AIIAWebviewNotifyCore.setCachedNotificationSettings(__S__);
        await AIIAWebviewSettingsUi.openSettings();
        __element("notifyEnabled").checked = false;
        __element("settingsPanel").dispatch("change", { target: __element("notifyEnabled") });
        return JSON.stringify({ ok: true });
    """.replace("__S__", _settings(True))
    assert _run(case) == {"ok": True}


@needs_node
@pytest.mark.parametrize("platform", ["linux", "win32"])
def test_a_hidden_macos_switch_keeps_its_saved_value(platform: str) -> None:
    """Hiding the row on a non-macOS host must not turn the setting off behind the user's back.

    The settings are shared with the Web UI and other machines; a Windows window that saves the Bark
    key must leave "macOS banner: on" alone.
    """
    case = """
        AIIAWebviewNotifyCore.setCachedNotificationSettings(__S__);
        await AIIAWebviewSettingsUi.openSettings();
        const bark = __element("notifyBarkEnabled");
        bark.checked = true;
        __element("settingsPanel").dispatch("change", { target: bark });
        const timer = __timers.find((t) => t.ms === 500 && !t.cleared && !t.ran);
        timer.ran = true;
        timer.fn();
        for (let i = 0; i < 20; i++) await Promise.resolve();
        return JSON.stringify(__saveRequests.map((r) => r.body));
    """.replace("__S__", _settings(True, native=True))
    # the harness is typed for objects; this case returns the list of save requests' bodies
    (body,) = cast("list[dict[str, Any]]", _run(case, platform=platform))
    assert body["macosNativeEnabled"] is True
    assert body["barkEnabled"] is True
