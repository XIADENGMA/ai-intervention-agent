"""R831: the desktop notification for a new request says what the AI asked.

Real Chrome 153 against a real Web UI, page in Chinese, notification permission granted, the
page in the background (the moment a desktop notification is for: the user is in the editor):
a request that began "请确认是否可以删除迁移文件？" raised a notification that read
``AI Intervention Agent`` over ``收到 1 个新的交互反馈请求`` (Received 1 new feedback request).
That says that something arrived and nothing about what is waiting, so the user had to bring the
browser to the front to find out whether it was urgent. The Bark push and the system notification
for the same request (``_dispatch_new_task_notification``) have always carried the first 100
characters of what the AI wrote, so the phone knew more than the desktop did.

The task list the page already polls (``GET /api/tasks``) carries the first 100 characters of every
prompt. ``updateTasksList`` now hands the words of the one new request to
``showNewTaskNotification`` as ``summary`` and ``notifyNewTasks`` says them in place of the count:

* one new request with something to say: the body is its first words, white space collapsed to
  single spaces (a notification is one block of text, a prompt is not), cut at 100 characters
  (by code point: a surrogate pair is never split) with an ellipsis;
* several new requests, or none that says anything (no prompt, an empty one, one that is not text):
  what it said before, the translated count or the translated "New task added: <id>";
* the page in front, the insecure page that falls back to a toast, the sound, the title, the tag
  and the contract of the return value are what they were.

Two Node harnesses are used: the fake browser of R822 (``notifyNewTasks`` on its own, with an
``AIIA_I18N.t`` that returns ``<<key|params>>`` so a test can tell where a text came from) and the
sandbox of R452 that loads the whole of ``multi_task.js`` (``updateTasksList`` and the debounce of
the pending count, with a ``notificationManager`` that records what it is asked).
"""

from __future__ import annotations

import json
import re
import shutil
import textwrap
from pathlib import Path
from typing import Any

import pytest

from tests.test_multi_task_poll_controller_lifecycle_r452 import (
    MULTI_TASK_JS,
    _poll_harness,
    _run_node,
)
from tests.test_new_task_notification_language_r822 import (
    AWAY,
    NOTIFICATION_MANAGER_JS,
    VISIBLE,
    _run,
)

pytestmark = pytest.mark.skipif(
    shutil.which("node") is None, reason="node runtime unavailable"
)

QUESTION = "请确认是否可以删除迁移文件？"
COUNT_ONE = '<<page.noContent.newTasks|{"count":1}>>'
COUNT_TWO = '<<page.noContent.newTasks|{"count":2}>>'
NAMED_A = '<<notify.newTask|{"id":"task-a"}>>'


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False)


def _notify(event: object, *, document: str = AWAY, secure: bool = True) -> Any:
    case = f"const result = await manager.notifyNewTasks({_json(event)}); report({{ result }});"
    return _run(case, document, secure)


def _bodies(out: dict[str, Any]) -> list[str]:
    return [shown["body"] for shown in out["shown"]]


# --------------------------------------------------------------------------------------
# A. notifyNewTasks: what the notification says


class TestTheNotificationSaysWhatWasAsked:
    def test_one_request_with_words_is_the_words(self) -> None:
        out = _notify({"count": 1, "summary": QUESTION})
        assert out["shown"] == [
            {
                "title": "AI Intervention Agent",
                "body": QUESTION,
                "tag": "aiia-new-tasks",
            }
        ]

    def test_the_words_are_not_run_through_the_translation(self) -> None:
        out = _notify({"count": 1, "summary": "page.noContent.newTasks"})
        assert _bodies(out) == ["page.noContent.newTasks"]

    def test_the_words_beat_the_named_request_sentence(self) -> None:
        out = _notify({"count": 1, "taskIds": ["task-a"], "summary": QUESTION})
        assert _bodies(out) == [QUESTION]

    def test_the_return_value_carries_the_same_text(self) -> None:
        out = _notify({"count": 1, "taskIds": ["task-a"], "summary": QUESTION})
        assert out["result"] == {
            "title": "AI Intervention Agent",
            "message": QUESTION,
            "count": 1,
            "taskIds": ["task-a"],
        }

    def test_the_title_an_event_asks_for_is_still_the_title(self) -> None:
        out = _notify({"count": 1, "title": "Custom", "summary": QUESTION})
        assert out["shown"][0]["title"] == "Custom"
        assert out["shown"][0]["body"] == QUESTION

    def test_the_event_goes_through_dispatch_event_unchanged(self) -> None:
        case = (
            "const result = await manager.dispatchEvent("
            f"{_json({'type': 'new_tasks', 'count': 1, 'summary': QUESTION})}); "
            "report({ result });"
        )
        out = _run(case, AWAY, True)
        assert _bodies(out) == [QUESTION]

    def test_the_words_are_used_without_the_i18n_module_too(self) -> None:
        case = f"await manager.notifyNewTasks({_json({'count': 1, 'summary': QUESTION})}); report();"
        out = _run(case, AWAY, True, None)
        assert _bodies(out) == [QUESTION]

    def test_the_sound_still_plays_and_the_notification_is_not_repeated(self) -> None:
        out = _notify({"count": 1, "summary": QUESTION})
        assert len(out["shown"]) == 1
        assert out["flashed"] == []
        assert out["visualHints"] == []


class TestWhiteSpaceIsCollapsed:
    @pytest.mark.parametrize(
        ("summary", "expected"),
        [
            ("line one\nline two", "line one line two"),
            ("line one\n\n\n  line two", "line one line two"),
            ("  padded  ", "padded"),
            ("tab\tseparated\t\twords", "tab separated words"),
            ("windows\r\nline breaks", "windows line breaks"),
            ("no\u00a0break\u2003space", "no break space"),
            (f"{QUESTION}\n\n选项 A / B", f"{QUESTION} 选项 A / B"),
            ("- item one\n- item two", "- item one - item two"),
            ("a  b   c", "a b c"),
        ],
    )
    def test_a_notification_is_one_block_of_text(
        self, summary: str, expected: str
    ) -> None:
        assert _bodies(_notify({"count": 1, "summary": summary})) == [expected]


class TestTheWordsAreCutAtOneHundredCharacters:
    """The task list keeps 100 characters of a prompt: words that long were probably cut."""

    def test_ninety_nine_characters_stay_as_they_are(self) -> None:
        summary = "x" * 99
        assert _bodies(_notify({"count": 1, "summary": summary})) == [summary]

    def test_a_hundred_characters_were_probably_cut_by_the_sender(self) -> None:
        summary = "x" * 100
        assert _bodies(_notify({"count": 1, "summary": summary})) == [summary + "…"]

    def test_a_hundred_and_one_are_cut_with_an_ellipsis(self) -> None:
        summary = "a" * 60 + "b" * 41
        assert _bodies(_notify({"count": 1, "summary": summary})) == [
            "a" * 60 + "b" * 40 + "…"
        ]

    def test_the_cut_counts_after_the_white_space_is_collapsed(self) -> None:
        # 300 characters that are 149 once each run of line breaks is one space: the first 100 of
        # those, not of the 300, are what is said
        summary = ("ab" + "\n" * 4) * 50
        assert len(summary) == 300
        body = _bodies(_notify({"count": 1, "summary": summary}))[0]
        assert body == ("ab " * 50).strip()[:100] + "…"
        assert len(body) == 101

    def test_words_that_collapse_short_but_were_cut_by_the_sender_end_in_an_ellipsis(
        self,
    ) -> None:
        # the sender kept 100 characters, only 7 of them words: it cut the rest of the prompt
        summary = "abc" + "\n" * 90 + "def" + "\n" * 4
        assert len(summary) == 100
        assert _bodies(_notify({"count": 1, "summary": summary})) == ["abc def…"]

    def test_the_same_words_with_a_little_less_white_space_were_not_cut(self) -> None:
        summary = "abc" + "\n" * 90 + "def" + "\n" * 3
        assert len(summary) == 99
        assert _bodies(_notify({"count": 1, "summary": summary})) == ["abc def"]

    def test_the_length_is_counted_in_code_points_not_utf16_units(self) -> None:
        # 99 emoji are 198 UTF-16 code units but 99 characters: nothing was cut
        summary = "😀" * 99
        assert _bodies(_notify({"count": 1, "summary": summary})) == [summary]

    def test_a_surrogate_pair_is_never_split(self) -> None:
        # 100 emoji, each two UTF-16 code units, then one more: the cut is after the 100th
        summary = "😀" * 101
        body = _bodies(_notify({"count": 1, "summary": summary}))[0]
        assert body == "😀" * 100 + "…"
        body.encode("utf-8")  # a lone surrogate would raise

    def test_chinese_text_is_cut_by_character(self) -> None:
        summary = "确" * 150
        assert _bodies(_notify({"count": 1, "summary": summary})) == ["确" * 100 + "…"]


# white space the sender cut at 100 characters: still nothing to say, and no lone ellipsis
LONG_BLANKS = " " * 150
LONG_BREAKS = "\n" * 100


class TestWithoutWordsTheCountIsWhatItWas:
    @pytest.mark.parametrize(
        "summary",
        [
            None,
            "",
            "   ",
            "\n\t \n",
            "\u00a0\u2003",
            LONG_BLANKS,
            LONG_BREAKS,
            5,
            True,
            {},
            [],
            ["x"],
            {"a": 1},
        ],
        ids=repr,
    )
    def test_a_summary_that_says_nothing_falls_back_to_the_count(
        self, summary: object
    ) -> None:
        assert _bodies(_notify({"count": 1, "summary": summary})) == [COUNT_ONE]

    @pytest.mark.parametrize("summary", [None, "", "  ", 5, {}], ids=repr)
    def test_and_to_the_named_sentence_when_the_request_has_an_id(
        self, summary: object
    ) -> None:
        event = {"count": 1, "taskIds": ["task-a"], "summary": summary}
        assert _bodies(_notify(event)) == [NAMED_A]

    def test_an_event_without_a_summary_is_what_it_was(self) -> None:
        assert _bodies(_notify({"count": 1})) == [COUNT_ONE]
        assert _bodies(_notify({"count": 1, "taskIds": ["task-a"]})) == [NAMED_A]
        assert _bodies(_notify({"count": 2})) == [COUNT_TWO]

    def test_the_english_sentences_remain_without_the_i18n_module(self) -> None:
        one = _run(
            "await manager.notifyNewTasks({ count: 1, summary: '  ' }); report();",
            AWAY,
            True,
            None,
        )
        assert _bodies(one) == ["Received 1 new task(s)"]

    def test_several_requests_are_counted_whatever_the_summary_says(self) -> None:
        out = _notify({"count": 2, "summary": QUESTION})
        assert _bodies(out) == [COUNT_TWO]
        out = _notify({"count": 3, "taskIds": ["a", "b", "c"], "summary": QUESTION})
        assert _bodies(out) == ['<<page.noContent.newTasks|{"count":3}>>']

    def test_no_request_is_no_notification(self) -> None:
        for event in ({"count": 0, "summary": QUESTION}, {"summary": QUESTION}):
            out = _notify(event)
            assert out["shown"] == []
            assert out["result"] is None


class TestThePageInFrontAndTheInsecurePageAreAsTheyWere:
    def test_the_page_in_front_gets_the_hint_and_no_notification(self) -> None:
        out = _notify({"count": 1, "summary": QUESTION}, document=VISIBLE)
        assert out["shown"] == []
        assert out["visualHints"] == [1]

    def test_the_insecure_page_shows_the_words_in_its_toast_and_in_page(self) -> None:
        out = _notify({"count": 1, "summary": QUESTION}, secure=False)
        assert out["shown"] == []
        assert out["inPage"] == [
            {"title": "AI Intervention Agent", "message": QUESTION}
        ]
        [call] = out["statusCalls"]
        assert call["type"] == "warning"
        assert call["message"].startswith(f"AI Intervention Agent: {QUESTION}")
        assert call["message"].endswith("<<status.notifFallbackInsecure|{}>>")

    def test_the_insecure_page_without_words_says_what_it_said(self) -> None:
        out = _notify({"count": 1, "taskIds": ["task-a"]}, secure=False)
        assert out["inPage"] == [{"title": "AI Intervention Agent", "message": NAMED_A}]

    def test_the_settings_test_notification_keeps_its_own_text(self) -> None:
        out = _run(
            "await manager.sendNotification('Settings Test', 'Everything works'); report();",
            VISIBLE,
            False,
        )
        assert out["inPage"] == [
            {"title": "Settings Test", "message": "Everything works"}
        ]


# --------------------------------------------------------------------------------------
# B. updateTasksList: which words go with the event


def _flow(case_js: str) -> Any:
    prologue = textwrap.dedent(
        """
        const events = [];
        globalThis.notificationManager = {
          dispatchEvent(event) { events.push(JSON.parse(JSON.stringify(event))); return Promise.resolve(); },
        };
        const task = (id, prompt, extra) => Object.assign(
          { task_id: id, prompt, status: 'pending', auto_resubmit_timeout: 0 }, extra || {});
        const flush = () => {
          // the debounce of the pending count: every timer of 150 ms that is not cleared
          for (const timer of __timeouts) {
            if (!timer.cleared && timer.delay === 150) { timer.cleared = true; timer.fn(); }
          }
        };
        const out = (extra) => process.stdout.write(JSON.stringify(Object.assign({ events }, extra || {})));
        """
    )
    return json.loads(_run_node(_poll_harness(prologue + textwrap.dedent(case_js))))


FRONT = "document.hidden = false; activeTaskId = 'task-old';"
BACK = "document.hidden = true; activeTaskId = 'task-old';"
NO_ACTIVE = "document.hidden = false; activeTaskId = null;"


class TestOneNewRequestCarriesItsWords:
    @pytest.mark.parametrize(
        "setup", [FRONT, BACK, NO_ACTIVE], ids=["front", "back", "idle"]
    )
    def test_the_event_has_the_first_words_of_the_new_request(self, setup: str) -> None:
        got = _flow(
            f"""
            {setup}
            currentTasks = [task('task-old', 'an old question')];
            updateTasksList([task('task-old', 'an old question'), task('task-new', {_json(QUESTION)})]);
            flush();
            out();
            """
        )
        assert got["events"] == [
            {"type": "new_tasks", "count": 1, "taskIds": [], "summary": QUESTION}
        ]

    def test_it_is_the_new_request_and_not_an_old_one(self) -> None:
        got = _flow(
            f"""
            {BACK}
            currentTasks = [task('task-1', 'first'), task('task-2', 'second')];
            updateTasksList([task('task-1', 'first'), task('task-2', 'second'), task('task-3', 'third')]);
            out();
            """
        )
        assert [e["summary"] for e in got["events"]] == ["third"]

    @pytest.mark.parametrize("position", [0, 1, 2], ids=["first", "middle", "last"])
    def test_the_new_request_is_found_wherever_the_list_puts_it(
        self, position: int
    ) -> None:
        got = _flow(
            f"""
            {BACK}
            currentTasks = [task('o1', 'old one'), task('o2', 'old two')];
            const list = [task('o1', 'old one'), task('o2', 'old two')];
            list.splice({position}, 0, task('task-new', {_json(QUESTION)}));
            updateTasksList(list);
            out();
            """
        )
        assert [e["summary"] for e in got["events"]] == [QUESTION]

    def test_the_task_list_prompt_is_given_as_the_server_sent_it(self) -> None:
        prompt = "p" * 100  # what GET /api/tasks sends of a long prompt
        got = _flow(
            f"""
            {BACK}
            currentTasks = [];
            updateTasksList([task('task-new', {_json(prompt)})]);
            out();
            """
        )
        assert [e["summary"] for e in got["events"]] == [prompt]

    def test_the_prompt_is_handed_over_untouched_so_its_length_says_if_it_was_cut(
        self,
    ) -> None:
        prompt = "words" + "\n" * 95  # 100 characters, the last 95 of them white space
        got = _flow(
            f"""
            {BACK}
            currentTasks = [];
            updateTasksList([task('task-new', {_json(prompt)})]);
            out();
            """
        )
        assert [e["summary"] for e in got["events"]] == [prompt]

    @pytest.mark.parametrize(
        "prompt",
        ["null", "undefined", "''", "'   '", "5", "{}", "['x']", "true"],
    )
    def test_a_request_with_no_usable_prompt_has_an_empty_summary(
        self, prompt: str
    ) -> None:
        got = _flow(
            f"""
            {BACK}
            currentTasks = [];
            updateTasksList([task('task-new', {prompt})]);
            out();
            """
        )
        assert got["events"] == [
            {"type": "new_tasks", "count": 1, "taskIds": [], "summary": ""}
        ]

    def test_a_task_without_a_prompt_field_is_an_empty_summary(self) -> None:
        got = _flow(
            f"""
            {BACK}
            currentTasks = [];
            updateTasksList([{{ task_id: 'task-new', status: 'pending', auto_resubmit_timeout: 0 }}]);
            out();
            """
        )
        assert [e["summary"] for e in got["events"]] == [""]


class TestSeveralNewRequestsAreCounted:
    @pytest.mark.parametrize(
        "setup", [FRONT, BACK, NO_ACTIVE], ids=["front", "back", "idle"]
    )
    def test_two_in_one_update_have_no_summary(self, setup: str) -> None:
        got = _flow(
            f"""
            {setup}
            currentTasks = [task('task-old', 'old')];
            updateTasksList([task('task-old', 'old'), task('a', 'first words'), task('b', 'second words')]);
            flush();
            out();
            """
        )
        assert got["events"] == [
            {"type": "new_tasks", "count": 2, "taskIds": [], "summary": ""}
        ]

    def test_two_updates_inside_the_debounce_are_one_event_without_summary(
        self,
    ) -> None:
        got = _flow(
            f"""
            {FRONT}
            currentTasks = [task('task-old', 'old')];
            updateTasksList([task('task-old', 'old'), task('a', 'first words')]);
            currentTasks = [task('task-old', 'old'), task('a', 'first words')];
            updateTasksList([task('task-old', 'old'), task('a', 'first words'), task('b', 'second words')]);
            flush();
            out();
            """
        )
        assert got["events"] == [
            {"type": "new_tasks", "count": 2, "taskIds": [], "summary": ""}
        ]

    def test_the_next_request_after_a_flush_has_its_own_words(self) -> None:
        got = _flow(
            f"""
            {FRONT}
            currentTasks = [task('task-old', 'old')];
            updateTasksList([task('task-old', 'old'), task('a', 'first words')]);
            flush();
            currentTasks = [task('task-old', 'old'), task('a', 'first words')];
            updateTasksList([task('task-old', 'old'), task('a', 'first words'), task('b', 'second words')]);
            flush();
            out();
            """
        )
        assert [(e["count"], e["summary"]) for e in got["events"]] == [
            (1, "first words"),
            (1, "second words"),
        ]

    def test_words_of_a_pair_do_not_leak_into_a_later_single_request(self) -> None:
        got = _flow(
            f"""
            {FRONT}
            currentTasks = [task('task-old', 'old')];
            updateTasksList([task('task-old', 'old'), task('a', 'x one'), task('b', 'x two')]);
            flush();
            currentTasks = [task('task-old', 'old'), task('a', 'x one'), task('b', 'x two')];
            updateTasksList([task('task-old', 'old'), task('a', 'x one'), task('b', 'x two'), task('c', 'only c')]);
            flush();
            out();
            """
        )
        assert [(e["count"], e["summary"]) for e in got["events"]] == [
            (2, ""),
            (1, "only c"),
        ]


class TestNothingNewIsNoEvent:
    def test_the_first_snapshot_is_not_announced(self) -> None:
        got = _flow(
            f"""
            {BACK}
            hasLoadedTaskSnapshot = false;
            currentTasks = [];
            updateTasksList([task('a', 'first words')]);
            flush();
            out();
            """
        )
        assert got["events"] == []

    def test_an_unchanged_list_is_not_announced(self) -> None:
        got = _flow(
            f"""
            {BACK}
            currentTasks = [task('a', 'first words')];
            updateTasksList([task('a', 'first words')]);
            flush();
            out();
            """
        )
        assert got["events"] == []


# --------------------------------------------------------------------------------------
# C. the source


def _source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


class TestTheSourceKeepsTheContract:
    def test_the_event_carries_the_summary_as_text_or_empty(self) -> None:
        source = _source(MULTI_TASK_JS)
        match = re.search(
            r"function showNewTaskNotification\(([^)]*)\)\s*\{(.*?)\n\}\n", source, re.S
        )
        assert match, "showNewTaskNotification not found"
        params, body = match.groups()
        assert [p.strip() for p in params.split(",")] == ["count", "taskIds", "summary"]
        assert re.search(r"summary:\s*typeof summary === ['\"]string['\"]", body)

    def test_the_notification_manager_never_puts_the_summary_into_html(self) -> None:
        source = _source(NOTIFICATION_MANAGER_JS)
        assert "innerHTML" not in source
        assert "insertAdjacentHTML" not in source

    def test_the_only_emitter_of_new_task_events_is_the_task_list(self) -> None:
        static = MULTI_TASK_JS.parent
        emitters = [
            path.name
            for path in sorted(static.glob("*.js"))
            if not path.name.endswith(".min.js")
            and re.search(r"type:\s*[\"']new_tasks[\"']", _source(path))
        ]
        assert emitters == ["multi_task.js"]
