r"""R885: after a language switch the texts that scripts built are written again.

Switching the language in the settings panel runs ``i18n.setLang()`` and ``i18n.translateDOM()``.
``translateDOM()`` knows only the strings that carry a ``data-i18n*`` attribute, and it writes the
*static* sentence of each one.  Four strings that the page builds by script were left behind (found
by taking the same page twice in a real Chromium, once switched at run time and once loaded in the
new language, and diffing every text node and every ``title`` / ``aria-label``):

1. the tooltip of each task tab (``Double-click to copy ID ...``), built when the tab is made and
   named by no ``data-i18n`` attribute: it stayed in the old language;
2. ``#bark-base-url-status-message`` (and the suggestion under it), a server answer turned into
   text when the panel is set up: it stayed in the old language, right next to the language select;
3. ``#theme-toggle-btn``: the script writes ``Theme: Dark`` into its ``title`` and ``aria-label``,
   the template also gives it ``data-i18n-title="page.themeToggle"``, and ``translateDOM()`` put the
   generic ``Toggle theme`` over it: the state it reports was gone;
4. ``#open-config-file-btn``: the same, ``Open with cursor`` replaced by ``Open config file in IDE``.

A freshly loaded page had them right (the theme button in English only, see the end of this
docstring), which is the trap: the page that has just switched language is not the page a load
gives.  The settings panel now announces ``aiia:langchange`` once, after ``translateDOM()``
(the one place the language is changed at run time), and each owner writes its own text again:

* the tabs read the hint again;
* ``ThemeManager`` runs ``updateToggleButton()``;
* the settings panel asks its two server answers again through the code that painted them on page
  load (``initOpenConfigFileButton()``, the Bark status ``renderStatus``), so that a switched page and
  a loaded one cannot differ.

The tests run the real ``i18n.js`` with the real ``en`` and ``zh-CN`` tables and the real
``translateDOM()``, so the overwrite that caused the defect is part of the setup rather than
assumed.  A tab is rebuilt with the real ``createTaskTab()`` after the switch, as a reload would, and
the refreshed tab must read exactly like it.

Not touched here: a fresh *load* in a language other than English still ends with the generic theme
label.  The English fallback table arrives after ``ThemeManager.init()`` has labelled the button, and
``translateDOM()`` runs again over it (seen in a real Chromium as three writes to the button's
``title``: generic, state, generic).  That is the page-load path, not the switch, and it is left as
it was; the switched page keeps the state label in every language.
"""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from typing import Any

import pytest

from tests.test_multi_task_poll_controller_lifecycle_r452 import _poll_harness
from tests.test_settings_manager_language_change_r452 import (
    _run_node,
    _settings_manager_harness,
)
from tests.test_theme_manager_lifecycle_r452 import _theme_harness

REPO_ROOT = Path(__file__).resolve().parent.parent
STATIC = REPO_ROOT / "src" / "ai_intervention_agent" / "static"
JS = STATIC / "js"
LOCALES = STATIC / "locales"

pytestmark = pytest.mark.skipif(
    shutil.which("node") is None, reason="node runtime unavailable"
)


def _locale(lang: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads(
        (LOCALES / f"{lang}.json").read_text(encoding="utf-8")
    )
    return data


EN = _locale("en")
ZH = _locale("zh-CN")


def _text(table: dict[str, Any], key: str) -> str:
    node: Any = table
    for part in key.split("."):
        node = node[part]
    assert isinstance(node, str)
    return node


# The real i18n module with the real tables, loaded into the case's sandbox (read from disk by
# node: the tables are too large to travel on a command line).
REAL_I18N = f"""
vm.runInContext(fs.readFileSync({str(JS / "i18n.js")!r}, 'utf8'), sandbox);
const I18N = sandbox.AIIA_I18N;
for (const lang of ['en', 'zh-CN']) {{
  I18N.registerLocale(lang, JSON.parse(fs.readFileSync({str(LOCALES)!r} + '/' + lang + '.json', 'utf8')));
}}
I18N.setLang('en');
"""

# A fake document that can answer the selectors ``translateDOM()`` uses for the elements in
# ``domElements`` (each with a ``dataI18n`` map of attribute -> key).
FAKE_TRANSLATABLE_DOM = """
function bindTranslatableDom(elements) {
  const previous = sandbox.document.querySelectorAll;
  sandbox.document.querySelectorAll = (selector) => {
    const match = /^\\[(data-i18n[\\w-]*)\\]$/.exec(selector);
    if (!match) return previous ? previous(selector) : [];
    return elements.filter((el) => el.getAttribute(match[1]) !== null);
  };
}
"""


# ---------------------------------------------------------------------------
# settings panel: the two server answers, and the announcement itself
# ---------------------------------------------------------------------------

SETTINGS_PRELUDE = (
    REAL_I18N
    + FAKE_TRANSLATABLE_DOM
    + """
const windowListeners = [];
const order = [];
const events = [];
sandbox.addEventListener = (type, handler) => { windowListeners.push({ type, handler }); };
sandbox.CustomEvent = class CustomEvent {
  constructor(type, init) { this.type = type; this.detail = init && init.detail; }
};
const openBtn = sandbox.__getElement('open-config-file-btn');
const dataAttrs = {
  'data-i18n-title': 'settings.openConfigInIde',
  'data-i18n-aria-label': 'settings.openConfigInIde',
};
openBtn.getAttribute = (name) =>
  Object.prototype.hasOwnProperty.call(dataAttrs, name) ? dataAttrs[name] : null;
bindTranslatableDom([openBtn]);

sandbox.dispatchEvent = (event) => {
  // what translateDOM() has just done to the button, before any owner answers
  events.push({ type: event.type, lang: event.detail && event.detail.lang, titleAtEvent: openBtn.title });
  order.push(event.type + ':' + (event.detail && event.detail.lang));
  for (const entry of windowListeners.filter((l) => l.type === event.type)) entry.handler(event);
  return true;
};
const realSetLang = I18N.setLang;
const realTranslateDOM = I18N.translateDOM;
I18N.setLang = (lang) => { order.push('setLang:' + lang); return realSetLang(lang); };
I18N.translateDOM = (root) => { order.push('translateDOM'); return realTranslateDOM(root); };

let openConfigInfo = { status: 200, body: { success: true, editor: 'cursor', editor_available: true, system_fallback_available: true } };
let barkStatus = { success: true, recommendation: 'ok', is_loopback: false,
  effective_base_url: 'http://192.168.1.5:8081', suggested_lan_base_url: '' };
sandbox.fetch = (url) => {
  const isOpenConfig = String(url).includes('/api/system/open-config-file/info');
  const isBark = String(url).includes('/api/system/network-base-url-status');
  const reply = isOpenConfig ? openConfigInfo : { status: 200, body: isBark ? barkStatus : { status: 'success' } };
  return Promise.resolve({
    ok: reply.status >= 200 && reply.status < 300,
    status: reply.status,
    json: () => Promise.resolve(reply.body),
  });
};
const settle = () => new Promise((resolve) => setImmediate(resolve));
const message = sandbox.__getElement('bark-base-url-status-message');
const suggestion = sandbox.__getElement('bark-base-url-status-suggestion');
const openStatus = sandbox.__getElement('open-config-file-status');

async function openThePanelIn(manager) {
  manager.initEventListeners();
  await manager.initOpenConfigFileButton();
  await manager.initBarkBaseUrlStatus();
}
async function switchTo(lang) {
  const select = sandbox.__getElement('language-select');
  select.value = lang;
  const change = sandbox.__elementListeners.find((e) => e.id === 'language-select' && e.type === 'change');
  await change.handler();
  await settle();
}
function snapshot() {
  return {
    openTitle: openBtn.title,
    openStatus: openStatus.textContent,
    barkMessage: message.textContent,
    barkSuggestion: suggestion.textContent,
  };
}
"""
)


def _settings_case(case_js: str) -> dict[str, Any]:
    out = _run_node(_settings_manager_harness(SETTINGS_PRELUDE + case_js))
    parsed: dict[str, Any] = json.loads(out)
    return parsed


class TestSettingsPanel:
    def test_the_open_in_ide_title_is_written_again_after_translatedom_reset_it(
        self,
    ) -> None:
        out = _settings_case(
            """
            const manager = new exported.SettingsManager();
            await openThePanelIn(manager);
            const before = snapshot();
            await switchTo('zh-CN');
            process.stdout.write(JSON.stringify({ before, after: snapshot(), events }));
            """
        )
        ready_en = _text(EN, "settings.openConfigInIdeReady").replace(
            "{editor}", "cursor"
        )
        ready_zh = _text(ZH, "settings.openConfigInIdeReady").replace(
            "{editor}", "cursor"
        )
        assert out["before"]["openTitle"] == ready_en
        # translateDOM() really did put the generic sentence over it ...
        assert [e["titleAtEvent"] for e in out["events"]] == [
            _text(ZH, "settings.openConfigInIde")
        ]
        # ... and the panel put the state back, in the new language
        assert out["after"]["openTitle"] == ready_zh

    def test_the_bark_status_is_written_again_in_the_new_language(self) -> None:
        out = _settings_case(
            """
            const manager = new exported.SettingsManager();
            await openThePanelIn(manager);
            const before = snapshot();
            await switchTo('zh-CN');
            process.stdout.write(JSON.stringify({ before, after: snapshot() }));
            """
        )
        url = "http://192.168.1.5:8081"
        assert out["before"]["barkMessage"] == _text(
            EN, "settings.baseUrlStatusOk"
        ).replace("{url}", url)
        assert out["after"]["barkMessage"] == _text(
            ZH, "settings.baseUrlStatusOk"
        ).replace("{url}", url)

    def test_the_warning_texts_of_the_bark_status_follow_too(self) -> None:
        out = _settings_case(
            """
            barkStatus = { success: true, recommendation: 'warn', is_loopback: true,
              effective_base_url: 'http://127.0.0.1:8081',
              suggested_lan_base_url: 'http://192.168.1.5:8081' };
            const manager = new exported.SettingsManager();
            await openThePanelIn(manager);
            const before = snapshot();
            await switchTo('zh-CN');
            process.stdout.write(JSON.stringify({ before, after: snapshot() }));
            """
        )
        url = "http://127.0.0.1:8081"
        assert out["before"]["barkMessage"] == _text(
            EN, "settings.baseUrlStatusLoopback"
        ).replace("{url}", url)
        assert out["before"]["barkSuggestion"] == _text(
            EN, "settings.baseUrlSuggestLan"
        )
        assert out["after"]["barkMessage"] == _text(
            ZH, "settings.baseUrlStatusLoopback"
        ).replace("{url}", url)
        assert out["after"]["barkSuggestion"] == _text(ZH, "settings.baseUrlSuggestLan")

    def test_a_blocked_open_in_ide_gives_its_reason_in_the_new_language(self) -> None:
        out = _settings_case(
            """
            openConfigInfo = { status: 403, body: {} };
            const manager = new exported.SettingsManager();
            await openThePanelIn(manager);
            const before = snapshot();
            await switchTo('zh-CN');
            process.stdout.write(JSON.stringify({ before, after: snapshot() }));
            """
        )
        key = "settings.openConfigInIdeRemoteBlocked"
        assert out["before"]["openTitle"] == _text(EN, key)
        assert out["before"]["openStatus"] == _text(EN, key)
        assert out["after"]["openTitle"] == _text(ZH, key)
        assert out["after"]["openStatus"] == _text(ZH, key)

    def test_the_announcement_comes_after_translatedom_and_names_the_language(
        self,
    ) -> None:
        out = _settings_case(
            """
            const manager = new exported.SettingsManager();
            await openThePanelIn(manager);
            order.length = 0;
            await switchTo('zh-CN');
            process.stdout.write(JSON.stringify({ order }));
            """
        )
        assert out["order"] == [
            "setLang:zh-CN",
            "translateDOM",
            "aiia:langchange:zh-CN",
        ]

    def test_switching_back_restores_the_first_language(self) -> None:
        out = _settings_case(
            """
            const manager = new exported.SettingsManager();
            await openThePanelIn(manager);
            const first = snapshot();
            await switchTo('zh-CN');
            await switchTo('en');
            process.stdout.write(JSON.stringify({ first, last: snapshot() }));
            """
        )
        assert out["last"] == out["first"]

    def test_the_listener_is_installed_once_however_often_the_panel_wires_up(
        self,
    ) -> None:
        out = _settings_case(
            """
            const manager = new exported.SettingsManager();
            manager.initEventListeners();
            manager.initEventListeners();
            process.stdout.write(JSON.stringify({
              listeners: windowListeners.filter((l) => l.type === 'aiia:langchange').length,
            }));
            """
        )
        assert out["listeners"] == 1

    def test_a_page_without_the_two_panels_is_left_alone(self) -> None:
        out = _settings_case(
            """
            sandbox.document.getElementById = () => null;
            const manager = new exported.SettingsManager();
            let threw = null;
            try { manager._refreshLanguageDependentTexts(); await settle(); }
            catch (error) { threw = String(error); }
            process.stdout.write(JSON.stringify({ threw, fetches: sandbox.__fetchCalls.length }));
            """
        )
        assert out == {"threw": None, "fetches": 0}


# ---------------------------------------------------------------------------
# the theme button
# ---------------------------------------------------------------------------

THEME_PRELUDE = (
    REAL_I18N
    + FAKE_TRANSLATABLE_DOM
    + """
const dataAttrs = { 'data-i18n-title': 'page.themeToggle', 'data-i18n-aria-label': 'page.themeToggle' };
button.getAttribute = (name) =>
  Object.prototype.hasOwnProperty.call(dataAttrs, name) ? dataAttrs[name] : null;
Object.defineProperty(button, 'title', {
  get() { return sandbox.__buttonAttrs.title; },
  set(value) { sandbox.__buttonAttrs.title = String(value); },
});
bindTranslatableDom([button]);
function announce(lang) {
  for (const entry of sandbox.__windowListeners.filter((l) => l.type === 'aiia:langchange')) {
    entry.handler({ type: 'aiia:langchange', detail: { lang } });
  }
}
function label() {
  return { title: sandbox.__buttonAttrs.title, aria: sandbox.__buttonAttrs['aria-label'] };
}
"""
)


def _theme_case(case_js: str) -> dict[str, Any]:
    out = _run_node(_theme_harness(THEME_PRELUDE + case_js))
    parsed: dict[str, Any] = json.loads(out)
    return parsed


class TestThemeButton:
    def test_the_label_that_translatedom_reset_comes_back_in_the_new_language(
        self,
    ) -> None:
        out = _theme_case(
            """
            ThemeManager.init();
            ThemeManager.setTheme('dark');
            const before = label();
            I18N.setLang('zh-CN');
            I18N.translateDOM();
            const reset = label();
            announce('zh-CN');
            process.stdout.write(JSON.stringify({ before, reset, after: label() }));
            """
        )
        dark_en = _text(EN, "theme.dark")
        dark_zh = _text(ZH, "theme.dark")
        assert out["before"] == {"title": dark_en, "aria": dark_en}
        # translateDOM() replaced the state with the generic sentence ...
        generic = _text(ZH, "page.themeToggle")
        assert out["reset"] == {"title": generic, "aria": generic}
        # ... and the state is back, in the new language
        assert out["after"] == {"title": dark_zh, "aria": dark_zh}

    def test_every_theme_state_is_reported_in_the_new_language(self) -> None:
        out = _theme_case(
            """
            ThemeManager.init();
            const seen = {};
            for (const theme of ['auto', 'light', 'dark']) {
              ThemeManager.setTheme(theme);
              I18N.setLang('zh-CN');
              I18N.translateDOM();
              announce('zh-CN');
              seen[theme] = label();
              I18N.setLang('en');
              I18N.translateDOM();
              announce('en');
            }
            process.stdout.write(JSON.stringify(seen));
            """
        )
        for theme in ("auto", "light", "dark"):
            expected = _text(ZH, f"theme.{theme}")
            assert out[theme] == {"title": expected, "aria": expected}

    def test_repeated_init_installs_one_language_listener(self) -> None:
        out = _theme_case(
            """
            ThemeManager.init();
            ThemeManager.init();
            process.stdout.write(JSON.stringify({
              listeners: sandbox.__windowListeners.filter((l) => l.type === 'aiia:langchange').length,
            }));
            """
        )
        assert out["listeners"] == 1


# ---------------------------------------------------------------------------
# the task tabs
# ---------------------------------------------------------------------------

TAB_PRELUDE = f"""
const HINTS = {json.dumps({"en": _text(EN, "page.taskTabCopyHint"), "zh-CN": _text(ZH, "page.taskTabCopyHint")})};
let lang = 'en';
window.AIIA_I18N = {{ t: (key) => (key === 'page.taskTabCopyHint' ? HINTS[lang] : key) }};
const made = [];
const createElement = document.createElement;
document.createElement = (tag) => {{
  const el = createElement(tag);
  el.getAttribute = (name) => (name in el.attributes ? el.attributes[name] : null);
  made.push(el);
  return el;
}};
function tabTextOf(task) {{
  createTaskTab(task);
  return made.filter((el) => el.className === 'task-tab-text').pop();
}}
function announce() {{
  for (const entry of __windowListeners.filter((l) => l.type === 'aiia:langchange')) {{
    entry.handler({{ type: 'aiia:langchange', detail: {{ lang }} }});
  }}
}}
"""


def _tab_case(case_js: str) -> dict[str, Any]:
    out = _run_node(_poll_harness(TAB_PRELUDE + case_js))
    parsed: dict[str, Any] = json.loads(out)
    return parsed


class TestTaskTabTooltips:
    def test_a_refreshed_tab_reads_like_a_tab_built_after_the_switch(self) -> None:
        out = _tab_case(
            """
            const first = tabTextOf({ task_id: 'task-aaa-001', status: 'active' });
            const second = tabTextOf({ task_id: 'task-bbb-002', status: 'pending' });
            document.querySelectorAll = (selector) =>
              selector === '.task-tab-text[data-copyable-task-id]' ? [first, second] : [];
            const before = [first.title, second.title];

            lang = 'zh-CN';
            announce();

            // what a reload gives: the same tabs, made in the new language
            const freshFirst = tabTextOf({ task_id: 'task-aaa-001', status: 'active' });
            const freshSecond = tabTextOf({ task_id: 'task-bbb-002', status: 'pending' });
            process.stdout.write(JSON.stringify({
              before,
              after: [first.title, second.title],
              fresh: [freshFirst.title, freshSecond.title],
              suffixAfter: first.attributes['data-copy-hint-suffix'],
              suffixFresh: freshFirst.attributes['data-copy-hint-suffix'],
            }));
            """
        )
        hint_en = _text(EN, "page.taskTabCopyHint")
        hint_zh = _text(ZH, "page.taskTabCopyHint")
        assert out["before"] == [f"task-aaa-001\n{hint_en}", f"task-bbb-002\n{hint_en}"]
        assert out["after"] == [f"task-aaa-001\n{hint_zh}", f"task-bbb-002\n{hint_zh}"]
        assert out["after"] == out["fresh"]
        assert out["suffixAfter"] == out["suffixFresh"] == hint_zh

    def test_the_refresh_is_registered_when_the_script_loads(self) -> None:
        out = _tab_case(
            """
            const listeners = __windowListeners.filter((l) => l.type === 'aiia:langchange');
            process.stdout.write(JSON.stringify({
              count: listeners.length,
              isTheRefresh: listeners.length === 1 && listeners[0].handler === refreshTaskTabTooltips,
            }));
            """
        )
        assert out == {"count": 1, "isTheRefresh": True}

    def test_a_page_with_no_tabs_is_left_alone(self) -> None:
        out = _tab_case(
            """
            document.querySelectorAll = () => [];
            let threw = null;
            try { announce(); } catch (error) { threw = String(error); }
            process.stdout.write(JSON.stringify({ threw }));
            """
        )
        assert out == {"threw": None}


# ---------------------------------------------------------------------------
# the four places agree on the event, and the language is changed in one place
# ---------------------------------------------------------------------------


def _source(name: str) -> str:
    return (JS / name).read_text(encoding="utf-8")


class TestOneEventName:
    def test_the_announcer_and_every_owner_use_the_same_name(self) -> None:
        settings = _source("settings-manager.js")
        assert 'new CustomEvent("aiia:langchange"' in settings
        assert 'window.addEventListener("aiia:langchange"' in settings
        assert (
            'window.addEventListener("aiia:langchange", refreshTaskTabTooltips)'
            in _source("multi_task.js")
        )
        assert (
            "window.addEventListener('aiia:langchange', updateToggleButton)"
            in _source("theme.js")
        )

    def test_the_language_is_changed_in_one_place_and_announced_right_after(
        self,
    ) -> None:
        # Every other ``translateDOM(`` is a pass over part of the page or the first paint; only
        # the settings panel changes the language while the page is open.
        for name in sorted(p.name for p in JS.glob("*.js") if ".min." not in p.name):
            if name == "i18n.js":
                continue
            calls = re.findall(r"\.setLang\(", _source(name))
            assert len(calls) == (1 if name == "settings-manager.js" else 0), name
        assert re.search(
            r"i18n\.setLang\(targetLang\);\s*i18n\.translateDOM\(\);\s*"
            r"this\._announceLanguageChange\(targetLang\);",
            _source("settings-manager.js"),
        )
