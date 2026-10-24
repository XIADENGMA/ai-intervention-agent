"""R845: one lone surrogate in a request used to end the MCP server process.

Python's ``json.loads`` turns an unpaired escape (``"\\ud800"``) - or, for a ``bytes`` body, the
bytes ``ED A0 80`` - into a ``str`` that has no UTF-8 encoding.  pydantic-core's own JSON parser
refuses such input, so nothing arrives that way through the MCP stdio transport; the Web UI reads
bodies and the ``selected_options`` form field with the standard library.  Real stack, one form
field on the route the browser page and the VS Code view use::

    POST /api/tasks/<id>/submit   selected_options=["ok", "a\\ud800b"]      -> 200, "submitted"

    mcp.server.stdio.stdout_writer: PydanticSerializationError: ... can't encode character
    '\\ud800' ... surrogates not allowed        (the task group fails; the server shuts down,
    the Web UI child and every queued task go with it, the agent's call never returns)

The same value reached through ``/api/update-feedback-config`` (``prompt_suffix``) is worse: it
sits in the config and is appended to *every* later tool result, and every later save of
``config.toml`` raises ``UnicodeEncodeError`` until the process is restarted.

Now:

* ``text_safety.scrub_lone_surrogates`` replaces each lone surrogate by U+FFFD (what browsers and
  Werkzeug do with invalid UTF-8) - in place for ``dict`` / ``list``, with an explicit stack so
  neither a deep nor a wide document costs recursion or memory;
* ``_request_body.loads_bounded`` is the one reader of untrusted JSON text: depth bound (R828) and
  that repair.  The app's JSON provider and both ``selected_options`` form parsers use it;
* ``server_feedback`` repairs the result it gets back from the Web UI as well - the process
  boundary, whatever version of the Web UI answers.

This file pins the helper (every code point, containers, keys, depth, memory, a differential test
against a naive copy), the reader (escapes, ``bytes``, UTF-16 bodies, pairs), the routes (both
submit routes, the config route, task creation, the snapshot on disk), the MCP side (the tool
result survives the serialisation the stdio writer performs) and the structure (no route parses
JSON text on its own).
"""

from __future__ import annotations

import ast
import asyncio
import itertools
import json
import random
import threading
import time
import tracemalloc
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import mcp.types as mt
import pytest
from flask.testing import FlaskClient
from pydantic_core import PydanticSerializationError

import ai_intervention_agent.server_feedback as server_feedback
from ai_intervention_agent import text_safety
from ai_intervention_agent.server_config import parse_structured_response
from ai_intervention_agent.task_queue_singleton import get_task_queue
from ai_intervention_agent.text_safety import scrub_lone_surrogates
from ai_intervention_agent.web_ui import WebFeedbackUI
from ai_intervention_agent.web_ui_routes import _request_body as body_contract
from tests.conftest import peak_traced_bytes_in_a_clean_interpreter

SRC = Path(__file__).resolve().parents[1] / "src" / "ai_intervention_agent"
LOOPBACK = {"REMOTE_ADDR": "127.0.0.1"}
FFFD = "\ufffd"
SURROGATES = [chr(code) for code in range(0xD800, 0xE000)]


def encodable(value: Any) -> bool:
    """Can ``value`` be written as UTF-8 JSON, the way the snapshot and the config are?"""
    try:
        json.dumps(value, ensure_ascii=False).encode("utf-8")
    except UnicodeEncodeError:
        return False
    return True


def wire(blocks: list[Any]) -> str:
    """What ``mcp.server.stdio.stdout_writer`` does with the content of a tool result."""
    result = mt.CallToolResult(content=blocks)
    response = mt.JSONRPCResponse(
        jsonrpc="2.0",
        id=1,
        result=result.model_dump(by_alias=True, mode="json", exclude_none=True),
    )
    return response.model_dump_json(by_alias=True, exclude_unset=True)


def naive_copy(value: Any) -> Any:
    """The obvious implementation: build a new document, one character at a time."""
    if isinstance(value, str):
        return "".join(
            FFFD if 0xD800 <= ord(char) <= 0xDFFF else char for char in value
        )
    if isinstance(value, list):
        return [naive_copy(item) for item in value]
    if isinstance(value, dict):
        copy: dict[Any, Any] = {}
        for key, item in value.items():
            copy[naive_copy(key) if isinstance(key, str) else key] = naive_copy(item)
        return copy
    return value


def stored_result(task_id: str) -> dict[str, Any]:
    """The result the queue holds for a task that has been submitted."""
    task = get_task_queue().get_task(task_id)
    assert task is not None
    assert task.result is not None
    return task.result


def snapshot_on_disk() -> dict[str, Any]:
    """The queue's persisted snapshot, read back from the disk."""
    path = get_task_queue()._persist_path
    assert path is not None
    return json.loads(Path(path).read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# The helper
# ---------------------------------------------------------------------------
class TestWhatTheInterpreterDoes:
    """The facts the fix rests on.  If one of them stops being true, the guard may go."""

    def test_json_loads_makes_a_string_that_has_no_utf8(self) -> None:
        value = json.loads('"a\\ud800b"')
        assert value == "a\ud800b"
        with pytest.raises(UnicodeEncodeError):
            value.encode("utf-8")

    def test_json_loads_of_bytes_decodes_with_surrogatepass(self) -> None:
        assert json.loads(b'"a\xed\xa0\x80b"') == "a\ud800b"

    def test_pydantic_core_refuses_such_input_so_the_mcp_transport_never_sees_it(
        self,
    ) -> None:
        with pytest.raises(ValueError, match="hex escape"):
            mt.jsonrpc_message_adapter.validate_json(
                '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":'
                '{"name":"x","arguments":{"message":"a\\ud800b"}}}',
                by_name=False,
            )

    def test_the_stdio_writer_cannot_serialise_a_tool_result_that_holds_one(
        self,
    ) -> None:
        with pytest.raises(PydanticSerializationError, match="surrogates not allowed"):
            wire([mt.TextContent(type="text", text="a\ud800b")])

    def test_a_valid_pair_of_escapes_is_one_character(self) -> None:
        assert json.loads('"\\ud83d\\ude00"') == "\U0001f600"


class TestScrub:
    def test_every_surrogate_code_point_becomes_one_replacement_character(self) -> None:
        assert len(SURROGATES) == 2048
        for char in SURROGATES:
            assert scrub_lone_surrogates("a" + char + "b") == "a" + FFFD + "b", hex(
                ord(char)
            )

    def test_the_neighbours_of_the_range_are_text(self) -> None:
        for char in ("\ud7ff", "\ue000", "\uffff", "\U0010ffff", "\U0001f600"):
            assert scrub_lone_surrogates(char) == char

    def test_each_one_is_replaced_not_the_whole_run(self) -> None:
        assert scrub_lone_surrogates("\ud800\ud800x\udc00") == FFFD * 2 + "x" + FFFD

    def test_two_surrogate_code_points_in_a_row_are_not_joined(self) -> None:
        """``json.loads`` joins a pair of *escapes*; two characters that are already
        surrogates (CESU-8 bytes) are not text, whatever order they come in."""
        assert scrub_lone_surrogates("\ud83d\ude00") == FFFD * 2
        assert scrub_lone_surrogates("\ude00\ud83d") == FFFD * 2

    @pytest.mark.parametrize(
        "text",
        [
            "",
            "plain ascii",
            "中文 ünï ç ß",
            "emoji \U0001f600 \U0001f468\u200d\U0001f469",
            "\x00\n\t",
        ],
    )
    def test_fine_text_comes_back_as_the_same_object(self, text: str) -> None:
        assert scrub_lone_surrogates(text) is text

    def test_ascii_is_never_scanned(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """``str.isascii()`` is O(1): a 20 MB base64 image costs nothing."""

        class Boom:
            def sub(self, *args: Any) -> str:
                raise AssertionError("an ASCII string was scanned")

            search = sub

        monkeypatch.setattr(text_safety, "_LONE_SURROGATE", Boom())
        big = "A" * 20_000_000
        assert scrub_lone_surrogates(big) is big
        assert scrub_lone_surrogates({"image": big, "k": [big]}) == {
            "image": big,
            "k": [big],
        }

    def test_a_list_is_repaired_in_place(self) -> None:
        value = ["ok", "a\ud800b", ["\udfff", 1, None]]
        inner = value[2]
        assert scrub_lone_surrogates(value) is value
        assert value == ["ok", f"a{FFFD}b", [FFFD, 1, None]]
        assert value[2] is inner

    def test_a_dict_is_repaired_in_place(self) -> None:
        value = {"a": "x\ud800", "b": {"c": ["\udc00"]}, "n": 1.5, "t": True}
        nested = value["b"]
        assert scrub_lone_surrogates(value) is value
        assert value == {"a": f"x{FFFD}", "b": {"c": [FFFD]}, "n": 1.5, "t": True}
        assert value["b"] is nested

    def test_keys_are_text_too_and_keep_their_order(self) -> None:
        value = {"first": 1, "k\ud800": 2, "last": 3}
        scrub_lone_surrogates(value)
        assert list(value.items()) == [("first", 1), (f"k{FFFD}", 2), ("last", 3)]

    def test_two_keys_that_become_the_same_collapse_the_later_wins(self) -> None:
        first, second = "\ud800", "\ud801"
        value = {first: "one", second: "two"}
        scrub_lone_surrogates(value)
        assert value == {FFFD: "two"}

    def test_a_key_and_its_value_in_one_dict(self) -> None:
        value = {"k\ud800": "v\ud800"}
        scrub_lone_surrogates(value)
        assert value == {f"k{FFFD}": f"v{FFFD}"}

    def test_keys_that_are_not_strings_are_left_alone(self) -> None:
        value: dict[Any, Any] = {1: "a\ud800", None: "b", ("t",): "c"}
        scrub_lone_surrogates(value)
        assert value == {1: f"a{FFFD}", None: "b", ("t",): "c"}

    @pytest.mark.parametrize(
        "value", [None, True, 0, 1.5, b"a\xed\xa0\x80", ("a\ud800",)]
    )
    def test_what_is_not_json_text_is_returned_untouched(self, value: Any) -> None:
        assert scrub_lone_surrogates(value) is value

    def test_a_document_with_nothing_to_repair_is_equal_afterwards(self) -> None:
        value = {"a": ["x", {"b": "中文"}], "c": [[], {}], "d": None}
        expected = json.loads(json.dumps(value))
        scrub_lone_surrogates(value)
        assert value == expected

    def test_a_deep_document_costs_no_recursion(self) -> None:
        root: list[Any] = []
        node = root
        for _ in range(100_000):
            child: list[Any] = []
            node.append(child)
            node = child
        node.append("deep\ud800")
        scrub_lone_surrogates(root)
        assert node == [f"deep{FFFD}"]

    def test_a_wide_document_costs_no_memory(self) -> None:
        """R828's reason for an explicit stack of iterators: a 10 MB body of ``[]`` is 3.3
        million lists, and a copy of it is 200 MB.  Measured in a clean interpreter: in this
        process any thread another test left running (the debounced config save, the config
        watcher) allocates megabytes inside the window."""
        peak = peak_traced_bytes_in_a_clean_interpreter(
            imports="from ai_intervention_agent.text_safety import scrub_lone_surrogates",
            build=r"""
                value = [[] for _ in range(300_000)]
                value.append(["tail\ud800"])
            """,
            measured="scrub_lone_surrogates(value)",
            check=r'assert value[-1] == ["tail\ufffd"]',
        )
        assert peak < 256 * 1024, f"{peak} bytes"

    def test_a_wide_dict_costs_no_memory_either(self) -> None:
        peak = peak_traced_bytes_in_a_clean_interpreter(
            imports="from ai_intervention_agent.text_safety import scrub_lone_surrogates",
            build=r"""
                value = {f"k{n}": [] for n in range(100_000)}
                value["tail"] = "x\ud800"
            """,
            measured="scrub_lone_surrogates(value)",
            check=r'assert value["tail"] == "x\ufffd"',
        )
        assert peak < 256 * 1024, f"{peak} bytes"

    def test_the_replacement_character_is_u_fffd(self) -> None:
        assert text_safety.REPLACEMENT_CHARACTER == FFFD


class TestTheMeasurementIsTakenInACleanInterpreter:
    """Why the two memory tests above do not measure in the pytest process.

    The CI run of 7a99e3dd failed on Python 3.13 with ``AssertionError: 2563213 bytes`` for the
    wide-document test.  ``tracemalloc`` counts what every thread allocates, and a
    ``threading.Timer`` that an earlier test's ``update_section`` had started (the debounced
    config save, which ``reload`` does not cancel when nothing is pending) fired inside the
    window and parsed the config with tomlkit: 2-3 MB for a function that allocates 2 KB.
    """

    def test_a_thread_of_this_process_does_not_change_the_number(self) -> None:
        stop = threading.Event()
        running = threading.Event()

        def noisy() -> None:
            while not stop.is_set():
                held = [bytearray(1024) for _ in range(2_000)]  # about 2 MB at a time
                running.set()
                time.sleep(0.001)
                del held

        thread = threading.Thread(target=noisy, daemon=True)
        thread.start()
        try:
            assert running.wait(30)
            tracemalloc.start()
            try:
                time.sleep(0.2)
                in_this_process = tracemalloc.get_traced_memory()[1]
            finally:
                tracemalloc.stop()
            clean = peak_traced_bytes_in_a_clean_interpreter(
                imports="", build="", measured="pass"
            )
        finally:
            stop.set()
            thread.join()

        assert in_this_process > 1_000_000, (
            "the control: this thread must be loud enough"
        )
        assert clean < 10_000, f"{clean} bytes"

    def test_what_the_child_prints_while_importing_is_not_the_number(self) -> None:
        peak = peak_traced_bytes_in_a_clean_interpreter(
            imports="print('a banner')\nprint('and another line')",
            build="",
            measured="pass",
        )

        assert 0 <= peak < 10_000

    def test_a_failing_check_in_the_child_fails_the_test_with_its_exit_status(
        self,
    ) -> None:
        with pytest.raises(AssertionError, match="exit 3"):
            peak_traced_bytes_in_a_clean_interpreter(
                imports="", build="", measured="pass", check="raise SystemExit(3)"
            )

    def test_an_error_in_the_measured_code_is_reported_with_its_traceback(self) -> None:
        with pytest.raises(AssertionError, match="ZeroDivisionError"):
            peak_traced_bytes_in_a_clean_interpreter(
                imports="", build="", measured="1 / 0"
            )

    def test_no_other_test_starts_tracemalloc_in_the_pytest_process(self) -> None:
        tests_dir = Path(__file__).resolve().parent
        starters = sorted(
            path.name
            for path in tests_dir.glob("test_*.py")
            if "tracemalloc.start(" in path.read_text(encoding="utf-8")
        )

        # this file only, for the control above; everything else measures through the helper
        assert starters == [Path(__file__).name], starters


def random_document(rng: random.Random, depth: int = 0) -> Any:
    pieces = [
        "a",
        "Z9",
        "中",
        "é",
        "\U0001f600",
        "\ud800",
        "\udbff",
        "\udc00",
        "\udfff",
        " ",
    ]

    def text() -> str:
        return "".join(rng.choice(pieces) for _ in range(rng.randint(0, 6)))

    kind = rng.random()
    if depth >= 4 or kind < 0.35:
        return rng.choice([text(), text(), text(), 1, 2.5, None, True])
    if kind < 0.7:
        return [random_document(rng, depth + 1) for _ in range(rng.randint(0, 4))]
    return {text(): random_document(rng, depth + 1) for _ in range(rng.randint(0, 4))}


def shape(value: Any) -> Any:
    """``value`` with every dict as a list of pairs, so that equality also compares key order."""
    if isinstance(value, dict):
        return [(key, shape(item)) for key, item in value.items()]
    if isinstance(value, list):
        return [shape(item) for item in value]
    return value


class TestAgainstTheNaiveCopy:
    def test_three_hundred_random_documents(self) -> None:
        rng = random.Random(845)
        for _ in range(300):
            document = random_document(rng)
            expected = naive_copy(document)
            actual = scrub_lone_surrogates(document)
            assert shape(actual) == shape(expected)
            assert encodable(actual)
            if isinstance(document, dict | list):
                assert actual is document

    def test_the_random_documents_do_contain_surrogates(self) -> None:
        rng = random.Random(845)
        documents = [random_document(rng) for _ in range(300)]
        assert sum(not encodable(d) for d in documents) > 60


# ---------------------------------------------------------------------------
# The reader
# ---------------------------------------------------------------------------
class TestLoadsBounded:
    def test_an_escape_becomes_a_replacement_character(self) -> None:
        assert body_contract.loads_bounded('"a\\ud800b"') == f"a{FFFD}b"

    @pytest.mark.parametrize(
        "body",
        [
            b'"a\\ud800b"',
            b'"a\xed\xa0\x80b"',
            '"a\\ud800b"'.encode("utf-16"),
            '"a\\ud800b"'.encode("utf-32"),
            b'\xef\xbb\xbf"a\\ud800b"',
        ],
        ids=["utf8-escape", "cesu8-bytes", "utf16", "utf32", "utf8-bom"],
    )
    def test_whatever_json_loads_accepts_as_bytes(self, body: bytes) -> None:
        assert body_contract.loads_bounded(body) == f"a{FFFD}b"

    def test_a_pair_of_escapes_stays_one_character(self) -> None:
        assert body_contract.loads_bounded('"\\ud83d\\ude00"') == "\U0001f600"

    def test_a_pair_in_the_wrong_order_is_two_replacements(self) -> None:
        assert body_contract.loads_bounded('"\\ude00\\ud83d"') == FFFD * 2

    def test_a_high_surrogate_before_a_plain_escape(self) -> None:
        assert body_contract.loads_bounded('"\\ud83d\\u0041"') == FFFD + "A"

    def test_an_escaped_backslash_is_not_an_escape(self) -> None:
        assert body_contract.loads_bounded('"\\\\ud800"') == "\\ud800"

    def test_keys_and_nested_values(self) -> None:
        value = body_contract.loads_bounded(
            '{"k\\ud800": ["v\\udc00", {"x": "\\udfff"}]}'
        )
        assert value == {f"k{FFFD}": [f"v{FFFD}", {"x": FFFD}]}

    def test_every_document_it_returns_can_be_written_as_utf8(self) -> None:
        rng = random.Random(8450)
        for _ in range(200):
            text = json.dumps(
                random_document(rng)
            )  # ensure_ascii: lone ones become escapes
            assert encodable(body_contract.loads_bounded(text))

    def test_keywords_reach_json_loads(self) -> None:
        assert body_contract.loads_bounded('{"a": 1.5}', parse_float=str) == {
            "a": "1.5"
        }

    def test_the_depth_bound_is_still_there(self) -> None:
        over = body_contract.MAX_JSON_NESTING + 1
        with pytest.raises(ValueError, match="nest"):
            body_contract.loads_bounded("[" * over + "]" * over)

    def test_what_the_interpreter_cannot_read_is_a_valueerror_too(self) -> None:
        """``RecursionError`` is not a ``ValueError``; Werkzeug's ``silent=True`` needs one."""
        text = "[" * 3_000_000 + "]" * 3_000_000
        with pytest.raises(ValueError, match="nest"):
            body_contract.loads_bounded(text)

    def test_a_syntax_error_is_still_a_jsondecodeerror(self) -> None:
        with pytest.raises(json.JSONDecodeError):
            body_contract.loads_bounded("{")

    def test_the_apps_provider_reads_with_it(self) -> None:
        from flask import Flask

        provider = body_contract.BoundedJSONProvider(Flask("r845"))
        assert provider.loads('["a\\ud800"]') == [f"a{FFFD}"]
        assert provider.loads(b'{"k": "\\udc00"}') == {"k": FFFD}


# ---------------------------------------------------------------------------
# The routes
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def ui() -> WebFeedbackUI:
    instance = WebFeedbackUI(
        prompt="r845", task_id="r845-ui", auto_resubmit_timeout=0, port=19845
    )
    instance.app.config["TESTING"] = True
    instance.limiter.enabled = False
    object.__setattr__(instance, "shutdown_server", lambda: None)
    return instance


@pytest.fixture
def client(ui: WebFeedbackUI) -> FlaskClient:
    ui.feedback_result = None
    return ui.app.test_client()


_task_numbers = itertools.count(1)


@pytest.fixture
def task() -> Iterator[str]:
    """A queued task to answer; removed afterwards."""
    queue = get_task_queue()
    task_id = f"r845-task-{next(_task_numbers)}"
    queue.add_task(
        task_id=task_id, prompt="p", predefined_options=["x"], auto_resubmit_timeout=0
    )
    try:
        yield task_id
    finally:
        queue.remove_task(task_id)


SELECTED = '["ok", "a\\ud800b", "\\ud83d\\ude00", "\\udfff"]'
SELECTED_REPAIRED = ["ok", f"a{FFFD}b", "\U0001f600", FFFD]


class TestSubmitRoutes:
    def test_the_task_scoped_submit_keeps_text_that_can_be_encoded(
        self, client: FlaskClient, task: str
    ) -> None:
        resp = client.post(
            f"/api/tasks/{task}/submit",
            data={"feedback_text": "hi", "selected_options": SELECTED},
            environ_base=LOOPBACK,
        )
        assert resp.status_code == 200, resp.get_data(as_text=True)[:200]
        result = stored_result(task)
        assert result["selected_options"] == SELECTED_REPAIRED
        assert result["user_input"] == "hi"
        assert encodable(result)

    def test_the_task_scoped_submit_reports_it_to_the_poller_as_text(
        self, client: FlaskClient, task: str
    ) -> None:
        """What the MCP server fetches: ``GET /api/tasks/<id>`` carries the repaired text."""
        client.post(
            f"/api/tasks/{task}/submit",
            data={"feedback_text": "hi", "selected_options": SELECTED},
            environ_base=LOOPBACK,
        )
        body = client.get(f"/api/tasks/{task}", environ_base=LOOPBACK).get_json()
        assert body["task"]["result"]["selected_options"] == SELECTED_REPAIRED
        raw = client.get(f"/api/tasks/{task}", environ_base=LOOPBACK).get_data(
            as_text=True
        )
        assert "\\ud800" not in raw and "\\udfff" not in raw

    def test_the_legacy_submit_keeps_text_that_can_be_encoded(
        self, ui: WebFeedbackUI, client: FlaskClient
    ) -> None:
        resp = client.post(
            "/api/submit",
            data={"feedback_text": "hi", "selected_options": SELECTED},
            environ_base=LOOPBACK,
        )
        assert resp.status_code == 200, resp.get_data(as_text=True)[:200]
        assert ui.feedback_result is not None
        assert ui.feedback_result["selected_options"] == SELECTED_REPAIRED
        assert encodable(ui.feedback_result)

    def test_the_legacy_submit_with_a_json_body(
        self, ui: WebFeedbackUI, client: FlaskClient
    ) -> None:
        resp = client.post(
            "/api/submit",
            data=(
                b'{"feedback_text": "a\\ud800b", "selected_options": ["\\udc00", "ok"],'
                b' "images": [{"data": "QUJD", "filename": "\\udfff.png"}]}'
            ),
            content_type="application/json",
            environ_overrides=LOOPBACK,
        )
        assert resp.status_code == 200, resp.get_data(as_text=True)[:200]
        assert ui.feedback_result is not None
        assert ui.feedback_result["user_input"] == f"a{FFFD}b"
        assert ui.feedback_result["selected_options"] == [FFFD, "ok"]
        assert ui.feedback_result["images"][0]["filename"] == f"{FFFD}.png"
        assert encodable(ui.feedback_result)

    @pytest.mark.parametrize(
        "raw",
        ["{", "not json", "[1" + "0" * 5000 + "]", "[" * 100 + "]" * 100, "5", "{}"],
        ids=["syntax", "text", "5000-digit-int", "too-deep", "scalar", "object"],
    )
    def test_the_legacy_submit_selects_nothing_when_the_field_is_not_a_readable_array(
        self, ui: WebFeedbackUI, client: FlaskClient, raw: str
    ) -> None:
        resp = client.post(
            "/api/submit",
            data={"feedback_text": "t", "selected_options": raw},
            environ_base=LOOPBACK,
        )
        assert resp.status_code == 200, resp.get_data(as_text=True)[:200]
        assert ui.feedback_result is not None
        assert ui.feedback_result["selected_options"] == []

    def test_a_form_text_field_cannot_carry_one_in_the_first_place(
        self, client: FlaskClient, task: str
    ) -> None:
        """Werkzeug decodes the bytes of a form with ``errors="replace"``: pinned, because the
        scrub does not look at ``feedback_text``."""
        resp = client.post(
            f"/api/tasks/{task}/submit",
            data=b"feedback_text=a%ED%A0%80b&selected_options=%5B%5D",
            content_type="application/x-www-form-urlencoded",
            environ_base=LOOPBACK,
        )
        assert resp.status_code == 200
        user_input = stored_result(task)["user_input"]
        assert encodable(user_input)
        assert "a" in user_input and "b" in user_input

    def test_an_array_of_only_surrogates_selects_replacement_characters(
        self, client: FlaskClient, task: str
    ) -> None:
        resp = client.post(
            f"/api/tasks/{task}/submit",
            data={"feedback_text": "", "selected_options": '["\\ud800", "\\udc00"]'},
            environ_base=LOOPBACK,
        )
        assert resp.status_code == 200
        assert stored_result(task)["selected_options"] == [FFFD] * 2

    def test_a_document_over_the_depth_bound_is_still_refused_by_the_task_route(
        self, client: FlaskClient, task: str
    ) -> None:
        resp = client.post(
            f"/api/tasks/{task}/submit",
            data={
                "feedback_text": "t",
                "selected_options": "[" * 100 + "]" * 100,
            },
            environ_base=LOOPBACK,
        )
        assert resp.status_code == 400
        assert resp.get_json()["success"] is False

    def test_the_task_route_refuses_a_syntax_error_and_a_non_array_as_before(
        self, client: FlaskClient, task: str
    ) -> None:
        for raw in ("{", "not json", '{"a": 1}', "5"):
            resp = client.post(
                f"/api/tasks/{task}/submit",
                data={"feedback_text": "t", "selected_options": raw},
                environ_base=LOOPBACK,
            )
            assert resp.status_code == 400, raw


class TestJsonBodies:
    def test_the_feedback_config_never_holds_one(self, client: FlaskClient) -> None:
        with patch(
            "ai_intervention_agent.web_ui_routes.notification.get_config"
        ) as get_config:
            get_config.return_value.get_section.return_value = {}
            resp = client.post(
                "/api/update-feedback-config",
                data=b'{"prompt_suffix": "x\\ud800y", "resubmit_prompt": "p\\udfffq"}',
                content_type="application/json",
                environ_overrides=LOOPBACK,
            )
        assert resp.status_code == 200, resp.get_data(as_text=True)[:200]
        (section, values), _ = get_config.return_value.update_section.call_args
        assert section == "feedback"
        assert values["prompt_suffix"] == f"x{FFFD}y"
        assert values["resubmit_prompt"] == f"p{FFFD}q"
        assert encodable(values)

    def test_a_task_created_by_json_is_stored_and_persisted_as_text(
        self, client: FlaskClient
    ) -> None:
        queue = get_task_queue()
        try:
            resp = client.post(
                "/api/tasks",
                data=(
                    b'{"task_id": "r845-created", "prompt": "a\\ud800b \\ud83d\\ude00",'
                    b' "predefined_options": ["x\\udfffy"],'
                    b' "header_label": "\\ud800", "auto_resubmit_timeout": 0}'
                ),
                content_type="application/json",
                environ_overrides=LOOPBACK,
            )
            assert resp.status_code == 200, resp.get_data(as_text=True)[:200]
            stored = queue.get_task("r845-created")
            assert stored is not None
            assert stored.prompt == f"a{FFFD}b \U0001f600"
            assert stored.predefined_options == [f"x{FFFD}y"]
            assert stored.header_label == FFFD
            on_disk = {entry["task_id"]: entry for entry in snapshot_on_disk()["tasks"]}
            assert on_disk["r845-created"]["prompt"] == f"a{FFFD}b \U0001f600"
        finally:
            queue.remove_task("r845-created")

    def test_the_loop_ledger_keeps_being_persisted_after_a_submit_with_one(
        self, client: FlaskClient
    ) -> None:
        """A completed task is not in the snapshot, but a loop round's verdict is (the ledger).
        Before: that verdict held the surrogate, every ``_persist`` raised ``UnicodeEncodeError``
        (logged, swallowed) and nothing reached the disk until the round left the ledger."""
        queue = get_task_queue()
        queue.add_task(
            task_id="r845-loop-task",
            prompt="p",
            predefined_options=["x"],
            auto_resubmit_timeout=0,
            loop_id="r845-loop",
            iteration_label="iter-1",
        )
        try:
            resp = client.post(
                "/api/tasks/r845-loop-task/submit",
                data={"feedback_text": "t", "selected_options": SELECTED},
                environ_base=LOOPBACK,
            )
            assert resp.status_code == 200, resp.get_data(as_text=True)[:200]
            rounds = snapshot_on_disk()["loop_history"]["r845-loop"]["rounds"]
            assert rounds[-1]["verdict"]["selected_options"] == SELECTED_REPAIRED
        finally:
            queue.remove_task("r845-loop-task")
            queue._loop_history.pop("r845-loop", None)
            queue._persist()

    def test_json_without_any_surrogate_is_read_as_before(
        self, client: FlaskClient
    ) -> None:
        with patch(
            "ai_intervention_agent.web_ui_routes.notification.get_config"
        ) as get_config:
            get_config.return_value.get_section.return_value = {}
            resp = client.post(
                "/api/update-feedback-config",
                data=json.dumps(
                    {"prompt_suffix": "后缀 \U0001f600 ünï", "resubmit_prompt": "再来"}
                ).encode(),
                content_type="application/json",
                environ_overrides=LOOPBACK,
            )
        assert resp.status_code == 200
        values = get_config.return_value.update_section.call_args.args[1]
        assert values["prompt_suffix"] == "后缀 \U0001f600 ünï"
        assert values["resubmit_prompt"] == "再来"


# ---------------------------------------------------------------------------
# The MCP side
# ---------------------------------------------------------------------------
def _config() -> Any:
    from ai_intervention_agent.service_manager import WebUIConfig

    return WebUIConfig(
        host="127.0.0.1",
        port=8090,
        language="auto",
        timeout=5,
        max_retries=0,
        retry_delay=0.1,
        external_base_url="",
    )


def _web_ui_that_answers(result: dict[str, Any]) -> MagicMock:
    live = MagicMock(name="web_ui")
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = {
        "success": True,
        "task": {"status": "completed", "result": result},
    }
    live.get = AsyncMock(return_value=response)
    live.post = AsyncMock()
    live.stream = MagicMock(side_effect=RuntimeError("SSE blocked in test"))
    live.is_closed = False
    return live


def _wait_for(result: dict[str, Any]) -> dict[str, Any]:
    with (
        patch(
            "ai_intervention_agent.service_manager.get_web_ui_config",
            return_value=(_config(), 60),
        ),
        patch(
            "ai_intervention_agent.service_manager.get_async_client",
            return_value=_web_ui_that_answers(result),
        ),
        patch("ai_intervention_agent.server_config.BACKEND_MIN", 1),
        patch.object(server_feedback, "_POLL_INTERVAL_FAST_S", 0.05),
    ):
        return asyncio.run(server_feedback.wait_for_task_completion("r845", timeout=5))


def poisoned_result() -> dict[str, Any]:
    return {
        "user_input": "typed \ud800 here",
        "selected_options": ["ok", "a\udc00b"],
        "images": [
            {"data": "QUJD", "content_type": "image/png", "filename": "x\ud800.png"}
        ],
    }


class TestTheToolResult:
    """A Web UI of any version may answer with a result that holds one."""

    def test_the_result_the_wait_returns_can_be_encoded(self) -> None:
        result = _wait_for(poisoned_result())
        assert encodable(result)
        assert result["user_input"] == f"typed {FFFD} here"
        assert result["selected_options"] == ["ok", f"a{FFFD}b"]
        assert result["images"][0]["filename"] == f"x{FFFD}.png"

    def test_the_content_blocks_go_through_the_stdio_writers_serialisation(
        self,
    ) -> None:
        blocks = parse_structured_response(_wait_for(poisoned_result()))
        sent = json.loads(wire(blocks))["result"]["content"]
        text = next(block["text"] for block in sent if block["type"] == "text")
        assert f"ok, a{FFFD}b" in text
        assert f"typed {FFFD} here" in text
        assert f"x{FFFD}.png" in text

    def test_that_serialisation_is_what_failed_before(self) -> None:
        """The same blocks built from the unrepaired result: the writer raises."""
        blocks = parse_structured_response(poisoned_result())
        with pytest.raises(PydanticSerializationError):
            wire(blocks)

    def test_a_result_without_any_is_returned_as_it_came(self) -> None:
        sent = {"user_input": "中文 \U0001f600", "selected_options": ["a"]}
        assert _wait_for(dict(sent)) == sent


# ---------------------------------------------------------------------------
# The structure
# ---------------------------------------------------------------------------
class TestStructure:
    def test_no_route_parses_json_text_on_its_own(self) -> None:
        """``loads_bounded`` is the one reader: a route that calls ``json.loads`` itself
        brings back both holes (no depth bound, no repair)."""
        offenders: list[str] = []
        for path in sorted((SRC / "web_ui_routes").glob("*.py")):
            if path.name == "_request_body.py":
                continue
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr in {"loads", "load"}
                    and isinstance(node.func.value, ast.Name)
                    and node.func.value.id == "json"
                ):
                    offenders.append(f"{path.name}:{node.lineno}")
        assert offenders == []

    def test_both_selected_options_parsers_use_the_reader(self) -> None:
        for name in ("feedback.py", "task.py"):
            tree = ast.parse((SRC / "web_ui_routes" / name).read_text(encoding="utf-8"))
            calls = [
                node
                for node in ast.walk(tree)
                if isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "loads_bounded"
            ]
            assert len(calls) == 1, name

    def test_the_provider_is_the_reader_and_nothing_more(self) -> None:
        tree = ast.parse(
            (SRC / "web_ui_routes" / "_request_body.py").read_text("utf-8")
        )
        provider = next(
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.ClassDef) and node.name == "BoundedJSONProvider"
        )
        loads = next(
            node
            for node in provider.body
            if isinstance(node, ast.FunctionDef) and node.name == "loads"
        )
        assert [type(statement).__name__ for statement in loads.body] == ["Return"]
        assert "loads_bounded" in ast.unparse(loads)

    def test_the_helper_has_no_dependency_on_the_rest_of_the_package(self) -> None:
        """It is imported by the MCP process and by the Web UI process alike."""
        tree = ast.parse((SRC / "text_safety.py").read_text(encoding="utf-8"))
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imported.add(node.module or ".")
        assert imported <= {"__future__", "re", "collections.abc", "typing"}
