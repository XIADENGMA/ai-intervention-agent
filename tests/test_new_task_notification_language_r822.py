"""R822: the notification for a new request speaks the page's language and says what happened.

The desktop notification that ``notifyNewTasks`` raises when the page is hidden or
unfocused (the moment a notification is for: the user is in the editor, the browser is
somewhere else) had two defects, seen in a real Chrome with the page in Chinese:

1. Its body was a fixed English sentence: ``Received 1 new task(s)``. The in-page hint
   for the same event, a few lines further down in the same function's sibling
   (``showNewTaskVisualHint``), already used the translated
   ``page.noContent.newTasks``; the notification, the one the user sees outside the
   browser, did not.
2. On a page that is not a secure context (``http://192.168.x.x:8081``, ``http://ai.local``:
   the documented way to open the Web UI from a phone or another machine) the notification
   API does not exist, and the fallback was raised with an English *explanation* in place of
   the event: the toast read ``Browser native notifications unavailable: Current origin
   (http://...) is not a secure context. Please access over HTTPS or localhost/127.0.0.1 and
   retry. — <translated hint>``, on every new request, and never said that a request had
   arrived. Every other reason (permission denied, unsupported, ...) hands the fallback the
   real title and message and lets the translated hint explain why; this branch was the odd
   one out, and its English sentence said what the translated ``status.notifFallbackInsecure``
   already says.

The fix keeps the English text as the last resort (the i18n module did not load) and never
shows a raw key, uses the translated strings otherwise, and hands the real title and message
to the fallback in an insecure page.

The script is loaded into Node with a fake browser whose ``AIIA_I18N.t`` returns
``<<key|params>>``, so a test can tell the text came from the translation table and with
which parameters.
"""

from __future__ import annotations

import functools
import json
import shutil
import subprocess
import textwrap
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
STATIC = REPO_ROOT / "src" / "ai_intervention_agent" / "static"
NOTIFICATION_MANAGER_JS = STATIC / "js" / "notification-manager.js"
LOCALES = STATIC / "locales"

pytestmark = pytest.mark.skipif(
    shutil.which("node") is None, reason="node runtime unavailable"
)

AWAY = "{ title: 'AI Intervention Agent', hidden: true, hasFocus() { return false; } }"
VISIBLE = (
    "{ title: 'AI Intervention Agent', hidden: false, hasFocus() { return true; } }"
)
TRANSLATING = "{ t(key, params) { return '<<' + key + '|' + JSON.stringify(params || {}) + '>>'; } }"


def _harness(
    case_js: str, *, document: str, secure: bool, i18n: str | None = TRANSLATING
) -> str:
    i18n_entry = f"AIIA_I18N: {i18n}," if i18n else ""
    return textwrap.dedent(
        f"""
        const fs = require('fs');
        const vm = require('vm');
        const code = fs.readFileSync({str(NOTIFICATION_MANAGER_JS)!r}, 'utf8')
          + '\\nglobalThis.__notificationManager = notificationManager;';

        const statusCalls = [];
        const visualHints = [];
        const sandbox = {{
          Audio: function Audio() {{}},
          Blob: function Blob() {{}},
          CustomEvent: function CustomEvent(type, init) {{
            this.type = type;
            this.detail = init && init.detail;
          }},
          Date, Error, JSON, Map, Math, Number, Object, Promise, RegExp, String,
          Notification: {{ permission: 'granted' }},
          console: {{ debug() {{}}, error() {{}}, info() {{}}, log() {{}}, warn() {{}} }},
          document: {document},
          localStorage: {{ getItem() {{ return null; }}, setItem() {{}}, removeItem() {{}} }},
          navigator: {{ userAgent: 'node' }},
          setInterval() {{ return 1; }},
          clearInterval() {{}},
          setTimeout(fn) {{ fn(); return 1; }},
          clearTimeout() {{}},
          dispatchEvent() {{}},
          isSecureContext: {str(secure).lower()},
          location: {{ origin: 'http://192.168.1.5:8081', host: '192.168.1.5:8081', href: 'http://192.168.1.5:8081/' }},
          {i18n_entry}
          showStatus(message, type) {{ statusCalls.push({{ message, type }}); }},
          showNewTaskVisualHint(count) {{ visualHints.push(count); }},
        }};
        sandbox.window = sandbox;
        vm.createContext(sandbox);
        vm.runInContext(code, sandbox);

        const manager = sandbox.__notificationManager;
        const shown = [];
        const inPage = [];
        const flashed = [];
        manager.playSound = async () => true;
        manager.registerServiceWorker = async () => null;
        manager.flashTitle = (text) => flashed.push(text);
        manager.showInPageNotification = (title, message) => {{ inPage.push({{ title, message }}); return {{}}; }};
        manager.showSystemNotification = async (title, options) => {{
          shown.push({{ title, body: options.body, tag: options.tag }});
          return {{ close() {{}} }};
        }};
        const report = (extra) => process.stdout.write(JSON.stringify(Object.assign({{
          shown, inPage, flashed, statusCalls, visualHints,
        }}, extra || {{}})));

        (async () => {{
        {textwrap.indent(case_js, "  ")}
        }})().catch((err) => {{
          console.error(err && err.stack ? err.stack : err);
          process.exit(1);
        }});
        """
    )


@functools.cache
def _run(
    case_js: str, document: str, secure: bool, i18n: str | None = TRANSLATING
) -> dict[str, Any]:
    proc = subprocess.run(
        ["node", "-e", _harness(case_js, document=document, secure=secure, i18n=i18n)],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.returncode == 0, (
        f"node exited {proc.returncode}\nstdout={proc.stdout!r}\nstderr={proc.stderr!r}"
    )
    return json.loads(proc.stdout)


COUNT_TWO = "await manager.notifyNewTasks({ count: 2 }); report();"
ONE_NAMED = "await manager.notifyNewTasks({ count: 1, taskIds: ['task-a'] }); report();"
PLAIN_TEST = (
    "const results = await manager.sendNotification('Settings Test', 'Everything works'); "
    "report({ results });"
)
NO_IDS = "await manager.notifyNewTasks({ count: 1 }); report();"


class TestTheDesktopNotificationSpeaksThePagesLanguage:
    def test_the_body_for_several_requests_is_the_translated_count(self) -> None:
        out = _run(COUNT_TWO, AWAY, True)
        assert out["shown"] == [
            {
                "title": "AI Intervention Agent",
                "body": '<<page.noContent.newTasks|{"count":2}>>',
                "tag": "aiia-new-tasks",
            }
        ]

    def test_the_body_for_one_named_request_is_the_translated_sentence(self) -> None:
        out = _run(ONE_NAMED, AWAY, True)
        assert [n["body"] for n in out["shown"]] == [
            '<<notify.newTask|{"id":"task-a"}>>'
        ]

    def test_one_request_without_an_id_is_counted_not_named(self) -> None:
        # Every real call site passes a count and no ids; naming "undefined" would be worse
        # than the count.
        out = _run(NO_IDS, AWAY, True)
        assert [n["body"] for n in out["shown"]] == [
            '<<page.noContent.newTasks|{"count":1}>>'
        ]

    def test_it_is_the_same_sentence_the_in_page_hint_uses(self) -> None:
        # The hint (page in front) and the notification (page away) tell the user the
        # same thing in the same words: the key is the one the hint already used.
        source = NOTIFICATION_MANAGER_JS.read_text(encoding="utf-8")
        app = (STATIC / "js" / "multi_task.js").read_text(encoding="utf-8")
        assert '"page.noContent.newTasks"' in app
        assert "'page.noContent.newTasks'" in source

    def test_without_the_i18n_module_the_english_sentences_remain(self) -> None:
        several = _run(COUNT_TWO, AWAY, True, None)
        named = _run(ONE_NAMED, AWAY, True, None)
        assert [n["body"] for n in several["shown"]] == ["Received 2 new task(s)"]
        assert [n["body"] for n in named["shown"]] == ["New task added: task-a"]

    def test_a_missing_translation_never_shows_a_raw_key(self) -> None:
        # ``t`` that echoes the key (what the real one does for an unknown key)
        echo = "{ t(key) { return key; } }"
        out = _run(COUNT_TWO, AWAY, True, echo)
        body = out["shown"][0]["body"]
        assert body == "Received 2 new task(s)"
        assert "page.noContent" not in body

    def test_the_page_in_front_still_gets_the_hint_and_no_notification(self) -> None:
        out = _run(COUNT_TWO, VISIBLE, True)
        assert out["shown"] == []
        assert out["visualHints"] == [2]


class TestAnInsecurePageStillTellsTheUserAboutTheRequest:
    def test_the_toast_carries_the_event_and_the_translated_hint(self) -> None:
        out = _run(ONE_NAMED, AWAY, False)
        calls = out["statusCalls"]
        assert len(calls) == 1
        call = calls[0]
        assert call["type"] == "warning"
        message = call["message"]
        assert message.startswith(
            'AI Intervention Agent: <<notify.newTask|{"id":"task-a"}>>'
        )
        assert message.endswith("<<status.notifFallbackInsecure|{}>>")

    def test_the_in_page_notification_carries_the_event(self) -> None:
        out = _run(ONE_NAMED, AWAY, False)
        assert out["inPage"] == [
            {
                "title": "AI Intervention Agent",
                "message": '<<notify.newTask|{"id":"task-a"}>>',
            }
        ]

    def test_nothing_is_a_system_notification(self) -> None:
        out = _run(ONE_NAMED, AWAY, False)
        assert out["shown"] == []

    def test_no_english_explanation_replaces_the_event(self) -> None:
        for out in (_run(ONE_NAMED, AWAY, False), _run(COUNT_TWO, AWAY, False)):
            text = json.dumps(out, ensure_ascii=False)
            assert "secure context" not in text
            assert "Browser native notifications unavailable" not in text
            assert "http://192.168.1.5:8081" not in text

    def test_the_settings_test_notification_keeps_its_own_text(self) -> None:
        # The "send a test notification" button goes through the same branch: the user
        # must see the test text, not an error sentence.
        out = _run(PLAIN_TEST, VISIBLE, False)
        assert out["inPage"] == [
            {"title": "Settings Test", "message": "Everything works"}
        ]
        assert out["statusCalls"][0]["message"].startswith(
            "Settings Test: Everything works"
        )
        # ...and the page is told the web notification was not delivered (``null``, not
        # ``undefined``): the sound still plays.
        assert out["results"] == [
            {"type": "web", "success": False},
            {"type": "sound", "success": True},
        ]

    def test_the_fallback_still_happens_without_the_i18n_module(self) -> None:
        out = _run(ONE_NAMED, AWAY, False, None)
        assert out["inPage"] == [
            {"title": "AI Intervention Agent", "message": "New task added: task-a"}
        ]
        assert out["shown"] == []


def _helper(call: str, i18n: str | None) -> Any:
    case = f"report({{ value: sandbox.t({call}) }});"
    return _run(case, VISIBLE, True, i18n)["value"]


class TestTheTranslationHelperKeepsItsContract:
    """``t(key, params)`` is used all over the script; the optional third argument is new."""

    def test_without_a_fallback_the_key_is_the_answer_when_there_is_no_module(
        self,
    ) -> None:
        assert _helper("'a.b', { x: 1 }", None) == "a.b"

    def test_without_a_fallback_the_module_is_answered_as_it_is(self) -> None:
        assert _helper("'a.b'", "{ t(key) { return key; } }") == "a.b"
        assert _helper("'a.b'", "{ t() { return ''; } }") == ""
        assert _helper("'a.b', { x: 1 }", TRANSLATING) == '<<a.b|{"x":1}>>'

    def test_with_a_fallback_a_translation_wins(self) -> None:
        assert _helper("'a.b', { x: 1 }, 'English'", TRANSLATING) == '<<a.b|{"x":1}>>'

    def test_with_a_fallback_a_missing_translation_gives_way_to_it(self) -> None:
        assert (
            _helper("'a.b', {}, 'English'", "{ t(key) { return key; } }") == "English"
        )
        assert _helper("'a.b', {}, 'English'", "{ t() { return ''; } }") == "English"
        assert _helper("'a.b', {}, 'English'", None) == "English"

    def test_a_module_that_throws_gives_way_to_the_fallback_or_the_key(self) -> None:
        broken = "{ t() { throw new Error('boom'); } }"
        assert _helper("'a.b', {}, 'English'", broken) == "English"
        assert _helper("'a.b'", broken) == "a.b"


class TestTheScriptHoldsNoLanguageOfItsOwn:
    def test_the_sentences_of_the_insecure_branch_are_gone(self) -> None:
        source = NOTIFICATION_MANAGER_JS.read_text(encoding="utf-8")
        assert "Browser native notifications unavailable" not in source
        assert "is not a secure context" not in source
        assert "Please access over HTTPS" not in source

    def test_the_insecure_branch_hands_over_the_real_title_and_message(self) -> None:
        source = NOTIFICATION_MANAGER_JS.read_text(encoding="utf-8")
        start = source.index(
            "window.isSecureContext === false) {",
            source.index("async showNotification("),
        )
        branch = source[start : source.index("return null", start)]
        assert "this.showFallbackNotification(title, message," in branch
        assert "reason: 'insecure_context'" in branch


class TestTheLocaleTables:
    @pytest.mark.parametrize("locale", ["en", "zh-CN", "zh-TW"])
    def test_the_named_request_sentence_exists_and_takes_the_id(
        self, locale: str
    ) -> None:
        table = json.loads((LOCALES / f"{locale}.json").read_text(encoding="utf-8"))
        text = table["notify"]["newTask"]
        assert isinstance(text, str) and text.strip()
        assert "{id}" in text

    @pytest.mark.parametrize("locale", ["zh-CN", "zh-TW"])
    def test_the_sentence_is_translated(self, locale: str) -> None:
        en = json.loads((LOCALES / "en.json").read_text(encoding="utf-8"))
        other = json.loads((LOCALES / f"{locale}.json").read_text(encoding="utf-8"))
        assert en["notify"]["newTask"] == "New task added: {id}"
        assert other["notify"]["newTask"] != en["notify"]["newTask"]
