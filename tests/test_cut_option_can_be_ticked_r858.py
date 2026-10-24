"""R858: an option the server itself cut to fit can still be ticked and sent back.

``validate_input_with_defaults`` cuts an option longer than ``MAX_OPTION_LENGTH`` (10 000
characters) at that length and adds ``...``, so the page shows (and the user can tick) an
option of 10 003 characters.  ``POST /api/submit`` cleaned ``selected_options`` with a limit of
``MAX_OPTION_LENGTH`` itself: the cut option was thrown away without a word, in all three
encodings the route reads (urlencoded form, multipart with files, JSON), and the route
answered ``200``.  The page cleared the text box, and the AI got the other ticks but not this
one.  (Real stack, before: the AI sent a 20 000-character option and a short one, the page showed
``[10003, 12]``, the user ticked both through each encoding, and the AI got ``选择的选项:
short option`` three times.)

The limit is ``MAX_STORED_OPTION_LENGTH``: the longest option the server can have stored.  A
string longer than that is still dropped (the limit is there against abuse).  The task
route (``/api/tasks/<id>/submit``) never had a length limit, so it is not touched.
"""

from __future__ import annotations

import io
import json
from collections.abc import Iterator
from typing import Any

import pytest
from flask.testing import FlaskClient

from ai_intervention_agent import server_config
from ai_intervention_agent.server_config import (
    MAX_OPTION_LENGTH,
    MAX_STORED_OPTION_LENGTH,
    OPTION_TRUNCATION_MARK,
    validate_input_with_defaults,
)
from ai_intervention_agent.task_queue_singleton import get_task_queue
from ai_intervention_agent.web_ui import WebFeedbackUI
from ai_intervention_agent.web_ui_routes.feedback import (
    _sanitize_selected_options,
    _selected_options_from_form,
)

LOOPBACK = {"REMOTE_ADDR": "127.0.0.1"}
TASK = "r858-task"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
SHORT = "short option"


def _stored(option: str) -> str:
    """The option as the server shows it: what ``interactive_feedback`` stores."""
    _, options, _ = validate_input_with_defaults("prompt", [option])
    assert len(options) == 1
    return options[0]


LENGTHS = [
    1,
    MAX_OPTION_LENGTH - 1,
    MAX_OPTION_LENGTH,
    MAX_OPTION_LENGTH + 1,
    MAX_STORED_OPTION_LENGTH,
    MAX_STORED_OPTION_LENGTH + 1,
    3 * MAX_OPTION_LENGTH,
]


class TestWhatTheServerCanStore:
    def test_the_longest_option_it_stores_is_the_cut_one_plus_the_mark(self) -> None:
        cut_plus_mark = MAX_OPTION_LENGTH + len(OPTION_TRUNCATION_MARK)
        assert cut_plus_mark == MAX_STORED_OPTION_LENGTH
        longest = _stored("x" * (5 * MAX_OPTION_LENGTH))
        assert len(longest) == MAX_STORED_OPTION_LENGTH
        assert longest == "x" * MAX_OPTION_LENGTH + OPTION_TRUNCATION_MARK

    def test_nothing_it_stores_is_longer_than_that(self) -> None:
        for length in LENGTHS:
            assert len(_stored("o" * length)) <= MAX_STORED_OPTION_LENGTH

    def test_the_mark_is_three_dots(self) -> None:
        assert OPTION_TRUNCATION_MARK == "..."


class TestAStoredOptionComesBackWhole:
    @pytest.mark.parametrize("length", LENGTHS)
    def test_the_json_cleaner_keeps_every_option_the_server_stores(
        self, length: int
    ) -> None:
        stored = _stored("o" * length)
        assert _sanitize_selected_options([stored]) == [stored]

    @pytest.mark.parametrize("length", LENGTHS)
    def test_the_form_field_cleaner_keeps_it_too(self, length: int) -> None:
        stored = _stored("o" * length)
        assert _selected_options_from_form(json.dumps([stored])) == [stored]

    def test_the_options_around_it_and_their_order_are_untouched(self) -> None:
        stored = _stored("o" * (2 * MAX_OPTION_LENGTH))
        assert _sanitize_selected_options(["first", stored, SHORT]) == [
            "first",
            stored,
            SHORT,
        ]

    def test_a_cut_that_lands_on_a_space_comes_back_whole(self) -> None:
        # "word " * 5000 is 25 000 characters; character 9 999 is the space after the
        # 2 000th word, so the cut text ends in a space and only the mark follows it.
        stored = _stored("word " * 5000)
        assert stored.endswith(" " + OPTION_TRUNCATION_MARK)
        assert _sanitize_selected_options([stored]) == [stored]

    def test_a_cut_through_non_ascii_text_comes_back_whole(self) -> None:
        stored = _stored("选项😀" * 9000)
        assert len(stored) == MAX_STORED_OPTION_LENGTH
        assert _sanitize_selected_options([stored]) == [stored]


class TestTheLimitIsStillALimit:
    def test_a_string_one_longer_than_anything_stored_is_dropped(self) -> None:
        too_long = "x" * (MAX_STORED_OPTION_LENGTH + 1)
        assert _sanitize_selected_options(["ok", too_long, "also ok"]) == [
            "ok",
            "also ok",
        ]

    def test_a_string_of_exactly_the_limit_is_kept(self) -> None:
        exact = "x" * MAX_STORED_OPTION_LENGTH
        assert _sanitize_selected_options([exact]) == [exact]

    def test_a_huge_string_is_dropped_by_the_form_field_cleaner_too(self) -> None:
        huge = "x" * (10 * MAX_STORED_OPTION_LENGTH)
        assert _selected_options_from_form(json.dumps([huge, SHORT])) == [SHORT]

    def test_the_other_rules_of_the_cleaner_are_unchanged(self) -> None:
        stored = _stored("o" * (2 * MAX_OPTION_LENGTH))
        cleaned = _sanitize_selected_options(
            [f"  {stored}  ", stored, "", "  ", None, 5, SHORT, SHORT]
        )
        assert cleaned == [stored, "5", SHORT]
        assert len(_sanitize_selected_options([f"o{i}" for i in range(80)])) == 50


@pytest.fixture(scope="module")
def ui() -> WebFeedbackUI:
    instance = WebFeedbackUI(
        prompt="r858", task_id="r858-initial", auto_resubmit_timeout=0, port=19858
    )
    instance.app.config["TESTING"] = True
    instance.limiter.enabled = False
    object.__setattr__(instance, "shutdown_server", lambda: None)
    return instance


@pytest.fixture
def client(ui: WebFeedbackUI) -> Iterator[FlaskClient]:
    queue = get_task_queue()
    queue.clear_all_tasks()
    ui.feedback_result = None
    try:
        yield ui.app.test_client()
    finally:
        queue.clear_all_tasks()


def _open_task_with(options: list[str]) -> None:
    assert get_task_queue().add_task(
        task_id=TASK, prompt="p", predefined_options=options, auto_resubmit_timeout=300
    )


def _answer(task_id: str) -> dict[str, Any]:
    task = get_task_queue().get_task(task_id)
    assert task is not None and task.result is not None, f"{task_id} was not answered"
    return dict(task.result)


def _post(client: FlaskClient, encoding: str, ticked: list[str]) -> Any:
    if encoding == "form":
        return client.post(
            "/api/submit",
            data={"feedback_text": "ticked", "selected_options": json.dumps(ticked)},
            environ_base=LOOPBACK,
        )
    if encoding == "multipart":
        return client.post(
            "/api/submit",
            data={
                "feedback_text": "ticked",
                "selected_options": json.dumps(ticked),
                "image_0": (io.BytesIO(PNG), "a.png", "image/png"),
            },
            content_type="multipart/form-data",
            environ_base=LOOPBACK,
        )
    assert encoding == "json"
    return client.post(
        "/api/submit",
        json={"feedback_text": "ticked", "selected_options": ticked},
        environ_base=LOOPBACK,
    )


ENCODINGS = ["form", "multipart", "json"]


class TestTheLegacySubmitRouteGivesTheTickBack:
    @pytest.mark.parametrize("encoding", ENCODINGS)
    def test_ticking_the_cut_option_and_a_short_one_reaches_the_task(
        self, client: FlaskClient, ui: WebFeedbackUI, encoding: str
    ) -> None:
        stored = _stored("L" * (2 * MAX_OPTION_LENGTH))
        _open_task_with([stored, SHORT])

        response = _post(client, encoding, [stored, SHORT])

        assert response.status_code == 200
        assert _answer(TASK)["selected_options"] == [stored, SHORT]
        assert ui.feedback_result is not None
        assert ui.feedback_result["selected_options"] == [stored, SHORT]

    @pytest.mark.parametrize("encoding", ENCODINGS)
    def test_ticking_only_the_cut_option_is_not_an_empty_answer(
        self, client: FlaskClient, encoding: str
    ) -> None:
        stored = _stored("L" * (2 * MAX_OPTION_LENGTH))
        _open_task_with([stored, SHORT])

        assert _post(client, encoding, [stored]).status_code == 200

        assert _answer(TASK)["selected_options"] == [stored]

    @pytest.mark.parametrize("encoding", ENCODINGS)
    def test_a_string_nobody_stored_is_still_dropped_on_the_way_in(
        self, client: FlaskClient, encoding: str
    ) -> None:
        _open_task_with([SHORT])
        forged = "x" * (MAX_STORED_OPTION_LENGTH + 1)

        assert _post(client, encoding, [forged, SHORT]).status_code == 200

        assert _answer(TASK)["selected_options"] == [SHORT]


class TestTheTaskRouteWasNeverAffected:
    def test_it_keeps_the_cut_option_as_before(self, client: FlaskClient) -> None:
        stored = _stored("L" * (2 * MAX_OPTION_LENGTH))
        _open_task_with([stored, SHORT])

        response = client.post(
            f"/api/tasks/{TASK}/submit",
            data={
                "feedback_text": "ticked",
                "selected_options": json.dumps([stored, SHORT]),
            },
            environ_base=LOOPBACK,
        )

        assert response.status_code == 200
        assert _answer(TASK)["selected_options"] == [stored, SHORT]


class TestTheConstantsAreTheOnesTheServerUses:
    def test_the_cut_is_made_with_the_named_mark(self) -> None:
        stored = _stored("o" * (MAX_OPTION_LENGTH + 50))
        assert stored.endswith(server_config.OPTION_TRUNCATION_MARK)
        assert len(stored) == MAX_OPTION_LENGTH + len(
            server_config.OPTION_TRUNCATION_MARK
        )

    def test_an_option_of_exactly_the_limit_is_not_cut_and_gets_no_mark(self) -> None:
        stored = _stored("o" * MAX_OPTION_LENGTH)
        assert stored == "o" * MAX_OPTION_LENGTH
