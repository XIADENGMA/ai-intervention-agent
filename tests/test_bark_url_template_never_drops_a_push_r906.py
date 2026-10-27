"""R906: a Bark click-link template that cannot be rendered no longer costs the push.

``render_bark_url_template`` is where text the user typed (the click-link template of the
settings page, or ``bark_url_template`` in the config file) meets ``str.format``. It promised to
turn a template it cannot render into an empty URL ("已退化为空 URL"), after which
``BarkNotificationProvider.send`` posts the push without a click link. It caught ``ValueError``
and ``IndexError`` only, but ``str.format`` has two more ways to fail on a text whose braces are
all balanced:

* ``AttributeError``: ``{task.id}`` (the dotted way most systems spell it; ``task`` is not a
  placeholder, so it stays the literal text ``{task}``, and a text has no attribute ``id``),
  ``{task_id.foo}``, ``{event_id.a.b}``;
* ``TypeError``: ``{task_id[abc]}``, ``{task_id[-1]}``, ``{task_id[1:2]}`` (a text is indexed by
  an integer, and ``-1`` and ``1:2`` are not integers inside a format field);
* ``MemoryError``: ``{task_id:>9223372036854775807}`` (a width no string can have; it is refused
  at once, nothing is allocated).

All of them travelled up to the broad ``except`` at the end of ``send``. Against a real HTTP server (a
local fake Bark that answers ``200`` to ``POST /push``):

=======================  =======================================  ===============================
template ends in         old provider                             now
=======================  =======================================  ===============================
``{task_id``             push sent, no ``url``                    the same
``{task_id[99]}``        push sent, no ``url``                    the same
``{task.id}``            nothing sent, ``send()`` is ``False``    push sent, no ``url``
``{task_id[abc]}``       nothing sent, ``send()`` is ``False``    push sent, no ``url``
=======================  =======================================  ===============================

For the cases in the last two rows the log held "Bark通知发送失败: 'str' object has no attribute
'id'" with a traceback and nothing that said the template was the reason; the phone got
nothing. The *Test* button of the settings page took the same path and answered ``500`` ("send
failed") although the Bark server was fine.

Now every failure to render is the same thing: a warning that names the template and the reason,
an empty URL, and a push that goes out without a link.
"""

from __future__ import annotations

import http.server
import json
import random
import re
import threading
from collections.abc import Iterator
from typing import Any
from unittest.mock import patch

import pytest

from ai_intervention_agent import notification_providers
from ai_intervention_agent.notification_models import (
    NotificationEvent,
    NotificationTrigger,
    NotificationType,
)
from ai_intervention_agent.notification_providers import (
    BarkNotificationProvider,
    render_bark_url_template,
)


@pytest.fixture(autouse=True)
def _disable_real_network_requests() -> None:
    """Replace the guard of ``conftest.py`` for this module only.

    The guard makes every un-mocked ``httpx`` call fail, which is right everywhere else. What
    these tests need to see is whether a push is *on the wire*, so they start a Bark server of
    their own on a loopback port (``FakeBark``) and let the provider talk to it.
    """


class FakeBark:
    """A Bark server on a loopback port: ``POST /push`` is ``200``, any other path ``404``."""

    def __init__(self) -> None:
        outer = self
        self.requests: list[tuple[str, dict[str, Any]]] = []

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                length = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(length) or b"{}")
                outer.requests.append((self.path, body))
                ok = self.path == "/push"
                self.send_response(200 if ok else 404)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(
                    b'{"code":200,"message":"success"}'
                    if ok
                    else b'{"code":404,"message":"page not found"}'
                )

            def log_message(self, format: str, *args: Any) -> None:
                return

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = int(self.server.server_address[1])
        self.thread = threading.Thread(
            target=self.server.serve_forever,
            kwargs={"poll_interval": 0.01},
            daemon=True,
        )
        self.thread.start()

    def url(self, path: str = "/push") -> str:
        return f"http://127.0.0.1:{self.port}{path}"

    def bodies(self) -> list[dict[str, Any]]:
        return [body for _path, body in self.requests]

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)


@pytest.fixture
def bark() -> Iterator[FakeBark]:
    server = FakeBark()
    try:
        yield server
    finally:
        server.close()


PARAMS = {"task_id": "t1", "event_id": "ev1", "base_url": "https://h.test"}
PREFIX = "{base_url}/?t="

# The old renderer already turned these into an empty URL.
HANDLED_BEFORE = {
    "an open brace": PREFIX + "{task_id",
    "a lone closing brace": PREFIX + "}",
    "an empty field": PREFIX + "{}",
    "a positional field": PREFIX + "{0}",
    "an index past the end": PREFIX + "{task_id[99]}",
    "an empty attribute": PREFIX + "{task_id.}",
    "an unknown conversion": PREFIX + "{task_id!z}",
    "a format code a text does not have": PREFIX + "{task_id:d}",
    "an alignment a text does not allow": PREFIX + "{task_id:=5}",
    "a format spec nested too deep": PREFIX + "{task_id:{task_id:{task_id}}}",
    "a width too large to count": PREFIX + "{task_id:>99999999999999999999}",
}

# These raised ``AttributeError`` / ``TypeError`` out of the renderer, on every Python version.
RAISED_BEFORE = {
    "an attribute a text does not have": PREFIX + "{task_id.foo}",
    "a name written the dotted way": PREFIX + "{task.id}",
    "an attribute of an attribute": PREFIX + "{event_id.a.b}",
    "an attribute of a name that is not a placeholder": PREFIX + "{missing.foo}",
    "a key that is a word": PREFIX + "{task_id[abc]}",
    "a negative index": PREFIX + "{task_id[-1]}",
    "a slice": PREFIX + "{task_id[1:2]}",
    "a key of a key": PREFIX + "{task_id[0][x]}",
    # Raises at once, nothing is allocated: no text can be that long.
    "a width no string can have": PREFIX + "{task_id:>9223372036854775807}",
}

# Fails on every version, but with a different exception on each (3.14 reads the empty name as
# an automatic field number and raises ``IndexError``, 3.11 to 3.13 raise ``AttributeError``).
VARIES_BY_PYTHON = {
    "an attribute of an empty name": PREFIX + "{.foo}",
}

BROKEN = {**HANDLED_BEFORE, **RAISED_BEFORE, **VARIES_BY_PYTHON}
BROKEN_IDS = list(BROKEN)
BROKEN_TEMPLATES = list(BROKEN.values())

# Templates that render, with what they render to.
RENDERS = {
    "the default template": (
        "{base_url}/?task_id={task_id}",
        "https://h.test/?task_id=t1",
    ),
    "all three placeholders": (
        "{base_url}/?t={task_id}&e={event_id}",
        "https://h.test/?t=t1&e=ev1",
    ),
    "blanks around it": ("  {base_url}/t/{task_id}\n", "https://h.test/t/t1"),
    "an index that exists": ("{base_url}/?t={task_id[0]}", "https://h.test/?t=t"),
    "a precision": ("{base_url}/?t={task_id:.1}", "https://h.test/?t=t"),
    "a padded field at the start is trimmed": ("{task_id:>5}/x", "t1/x"),
    "a padded field at the end is trimmed": ("x/{event_id:<6}", "x/ev1"),
    "a conversion": ("{base_url}/?t={task_id!s}", "https://h.test/?t=t1"),
    "doubled braces": ("{base_url}/?t={{task_id}}", "https://h.test/?t={task_id}"),
    "an unknown placeholder stays as written": (
        "{base_url}/?t={nothing}",
        "https://h.test/?t={nothing}",
    ),
    "no placeholder at all": ("https://fixed.test/page", "https://fixed.test/page"),
}


def _render(template: str) -> str:
    return render_bark_url_template(template, PARAMS)


class TestARenderThatFailsIsAnEmptyUrl:
    @pytest.mark.parametrize("template", BROKEN_TEMPLATES, ids=BROKEN_IDS)
    def test_it_returns_an_empty_url_and_does_not_raise(self, template: str) -> None:
        assert _render(template) == ""

    @pytest.mark.parametrize("template", BROKEN_TEMPLATES, ids=BROKEN_IDS)
    def test_it_says_so_once_in_the_log(self, template: str) -> None:
        with patch.object(notification_providers.logger, "warning") as warning:
            _render(template)
        assert warning.call_count == 1
        message = warning.call_args.args[0]
        assert "渲染 Bark URL 模板失败" in message
        assert repr(template) in message
        assert "已退化为空 URL" in message

    @pytest.mark.parametrize(
        ("template", "kind"),
        [
            (PREFIX + "{task_id", "ValueError"),
            (PREFIX + "{task_id[99]}", "IndexError"),
            (PREFIX + "{task.id}", "AttributeError"),
            (PREFIX + "{task_id[abc]}", "TypeError"),
        ],
    )
    def test_the_log_names_the_kind_of_failure(self, template: str, kind: str) -> None:
        with patch.object(notification_providers.logger, "warning") as warning:
            _render(template)
        assert f"error={kind}:" in warning.call_args.args[0]

    @pytest.mark.parametrize(
        ("template", "expected"),
        list(RENDERS.values()),
        ids=list(RENDERS),
    )
    def test_a_template_that_renders_is_rendered_exactly(
        self, template: str, expected: str
    ) -> None:
        with patch.object(notification_providers.logger, "warning") as warning:
            assert _render(template) == expected
        warning.assert_not_called()

    @pytest.mark.parametrize("interrupt", [KeyboardInterrupt, SystemExit])
    def test_an_interrupt_is_not_swallowed(
        self, interrupt: type[BaseException]
    ) -> None:
        """Catching every failure of the template is not catching a request to stop."""
        with (
            patch.object(
                notification_providers._BARK_TEMPLATE_FORMATTER,
                "vformat",
                side_effect=interrupt,
            ),
            pytest.raises(interrupt),
        ):
            _render(PREFIX + "{task_id}")

    @pytest.mark.parametrize("template", ["", "   ", "\n\t"])
    def test_a_blank_template_is_an_empty_url_and_not_a_failure(
        self, template: str
    ) -> None:
        with patch.object(notification_providers.logger, "warning") as warning:
            assert _render(template) == ""
        warning.assert_not_called()


FUZZ_TOKENS = [
    "{",
    "}",
    "{{",
    "}}",
    ".",
    "[",
    "]",
    ":",
    "!",
    "r",
    "s",
    "d",
    "x",
    "0",
    "1",
    "9",
    "-",
    " ",
    "/",
    "?",
    "=",
    "&",
    ">",
    "^",
    "task_id",
    "event_id",
    "base_url",
    "task",
    "id",
    "foo",
    "__class__",
    "{task_id}",
    "{base_url}",
    "{task_id:>5}",
    "{event_id:<6}",
    "https://h.test",
]


def _fuzz_templates(count: int, seed: int) -> list[str]:
    """Templates made of the pieces above, in random order. A run of four digits or more is
    left out: ``{task_id:99999999}`` is a valid template that pads to a hundred megabytes."""
    rng = random.Random(seed)
    found: list[str] = []
    while len(found) < count:
        template = "".join(rng.choice(FUZZ_TOKENS) for _ in range(rng.randint(1, 10)))
        if re.search(r"\d{4,}", template):
            continue
        found.append(template)
    return found


class TestWhateverTheTemplateIs:
    def test_the_renderer_never_raises_and_never_degrades_what_renders(self) -> None:
        """Six thousand templates, none written by hand.

        Whatever the text, the answer is a trimmed string; and whenever plain
        ``str.format_map`` can render the template the renderer gives the same text, so
        catching everything does not turn a template that works into an empty URL.
        """
        safe = notification_providers._BarkSafeFormatDict(PARAMS)
        rendered_ok = 0
        for template in _fuzz_templates(6000, seed=906):
            result = _render(template)
            assert isinstance(result, str), template
            assert result == result.strip(), template
            try:
                reference = template.strip().format_map(safe).strip()
            except Exception:
                continue
            rendered_ok += 1
            assert result == reference, template
        # a sample that never rendered anything would prove nothing
        assert rendered_ok > 300


def _event(**metadata: Any) -> NotificationEvent:
    return NotificationEvent(
        id="r906",
        title="Title",
        message="Message",
        trigger=NotificationTrigger.IMMEDIATE,
        types=[NotificationType.BARK],
        metadata={"task_id": "t1", "base_url": "https://h.test", **metadata},
    )


class PlainConfig:
    """What ``/api/test-bark`` hands the provider: a plain object, no model, no validator."""

    def __init__(self, url: str, template: str, action: str = "url") -> None:
        self.bark_enabled = True
        self.bark_url = url
        self.bark_device_key = "KEY123"
        self.bark_icon = ""
        self.bark_action = action
        self.bark_url_template = template
        self.bark_timeout = 3


def _send(config: PlainConfig, event: NotificationEvent | None = None) -> bool:
    provider = BarkNotificationProvider(config)
    try:
        return provider.send(event or _event())
    finally:
        provider.close()


class TestAPushWithABrokenTemplateIsStillSent:
    @pytest.mark.parametrize("template", BROKEN_TEMPLATES, ids=BROKEN_IDS)
    def test_the_push_goes_out_without_a_link(
        self, bark: FakeBark, template: str
    ) -> None:
        assert _send(PlainConfig(bark.url(), template)) is True
        assert [path for path, _ in bark.requests] == ["/push"]
        (body,) = bark.bodies()
        assert "url" not in body
        assert body["title"] == "Title"
        assert body["body"] == "Message"
        assert body["device_key"] == "KEY123"

    @pytest.mark.parametrize("template", BROKEN_TEMPLATES, ids=BROKEN_IDS)
    def test_the_template_is_blamed_in_the_log_and_the_send_is_not_called_failed(
        self, bark: FakeBark, template: str
    ) -> None:
        with (
            patch.object(notification_providers.logger, "warning") as warning,
            patch.object(notification_providers.logger, "error") as error,
        ):
            assert _send(PlainConfig(bark.url(), template)) is True
        error.assert_not_called()
        blamed = [
            call.args[0]
            for call in warning.call_args_list
            if "渲染 Bark URL 模板失败" in call.args[0]
        ]
        assert len(blamed) == 1

    def test_a_template_that_renders_still_puts_the_link_in(
        self, bark: FakeBark
    ) -> None:
        assert _send(PlainConfig(bark.url(), "{base_url}/?t={task_id}")) is True
        (body,) = bark.bodies()
        assert body["url"] == "https://h.test/?t=t1"

    def test_a_link_the_event_carries_is_used_and_the_template_is_not_looked_at(
        self, bark: FakeBark
    ) -> None:
        broken = PREFIX + "{task.id}"
        with patch.object(notification_providers.logger, "warning") as warning:
            assert (
                _send(
                    PlainConfig(bark.url(), broken),
                    _event(url="https://example.test/page"),
                )
                is True
            )
        (body,) = bark.bodies()
        assert body["url"] == "https://example.test/page"
        assert not [
            call
            for call in warning.call_args_list
            if "渲染 Bark URL 模板失败" in call.args[0]
        ]

    def test_without_the_url_action_the_template_is_not_looked_at(
        self, bark: FakeBark
    ) -> None:
        with patch.object(notification_providers.logger, "warning") as warning:
            assert _send(PlainConfig(bark.url(), PREFIX + "{task.id}", "none")) is True
        (body,) = bark.bodies()
        assert "url" not in body
        warning.assert_not_called()

    def test_the_push_is_dropped_for_the_reasons_that_are_not_the_template(
        self, bark: FakeBark
    ) -> None:
        """A control that the loopback server really decides: a path it does not know is 404."""
        assert _send(PlainConfig(bark.url("/nowhere"), PREFIX + "{task.id}")) is False
        assert [path for path, _ in bark.requests] == ["/nowhere"]


@pytest.fixture(scope="module")
def web_client() -> Any:
    """The Flask test client of a Web UI that is never started (as in R63a)."""
    from ai_intervention_agent.web_ui import WebFeedbackUI

    ui = WebFeedbackUI(prompt="bark template test", task_id="rt-r906", port=19096)
    ui.app.config["TESTING"] = True
    ui.limiter.enabled = False
    return ui.app.test_client()


def _press_test(web_client: Any, bark: FakeBark, template: str) -> Any:
    with patch(
        "ai_intervention_agent.web_ui_routes.notification.NOTIFICATION_AVAILABLE", True
    ):
        return web_client.post(
            "/api/test-bark",
            json={
                "bark_url": bark.url(),
                "bark_device_key": "KEY123",
                "bark_action": "url",
                "bark_url_template": template,
            },
        )


class TestTheTestButton:
    @pytest.mark.parametrize(
        "template",
        [PREFIX + "{task.id}", PREFIX + "{task_id[abc]}", PREFIX + "{task_id"],
        ids=["dotted name", "word as index", "open brace"],
    )
    def test_a_broken_template_does_not_fail_the_test_push(
        self, web_client: Any, bark: FakeBark, template: str
    ) -> None:
        response = _press_test(web_client, bark, template)
        assert response.status_code == 200, response.get_data(as_text=True)
        assert response.get_json()["status"] == "success"
        assert [path for path, _ in bark.requests] == ["/push"]
        (body,) = bark.bodies()
        assert "url" not in body

    def test_a_template_that_renders_still_reaches_the_phone_with_its_link(
        self, web_client: Any, bark: FakeBark
    ) -> None:
        response = _press_test(
            web_client, bark, "https://example.test/?task_id={task_id}"
        )
        assert response.status_code == 200, response.get_data(as_text=True)
        (body,) = bark.bodies()
        assert body["url"] == "https://example.test/?task_id=test-task-id&aiia_test=1"
