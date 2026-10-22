"""R823: a Bark server address pasted with a stray space or newline, or with an upper-case scheme, works.

``BarkNotificationProvider.send`` stripped the device key (``device_key_stripped``) and
checked the address as typed: nothing between the settings field, the config file, the
``NotificationConfig`` model and the HTTP call ever trimmed ``bark_url``. An address copied
from a chat, a note or a terminal carries a space or a line break at its end all the time, and
the field of the settings page keeps what is pasted. Against a real HTTP server (a local fake
Bark that answers ``200`` to ``POST /push`` and ``404`` to everything else):

=====================================  ==========================================================
``bark_url``                           what the old provider did
=====================================  ==========================================================
``http://host/push␠``                  ``POST /push%20``, answered ``404``: not sent
``␠http://host/push``                  refused before sending ("format invalid"): not sent
``http://host/push⏎``                  ``httpx.InvalidURL`` with a traceback in the log: not sent
``HTTP://host/push``                   refused before sending ("format invalid"): not sent
=====================================  ==========================================================

The user saw "Bark push failed (HTTP 404) page not found" in the *Test* result, or nothing at
all for a real task, and nothing pointed at a character they could not see.

Now the provider trims the address (and the icon address) before it checks and uses it, and
accepts any case of ``http://`` / ``https://`` (a scheme is case-insensitive, and ``httpx``
lower-cases it); ``NotificationConfig`` trims the three strings on every assignment so the
value that is saved, shown and compared is the clean one, and its own "format invalid" warning
agrees with the provider. Nothing else about the address is touched: a path, a trailing
slash or a query string stays as typed, and an address that is not ``http(s)://`` after
trimming (empty, ``ftp://``, no scheme) is still refused without a request.
"""

from __future__ import annotations

import http.server
import json
import threading
from collections.abc import Iterator
from typing import Any
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from ai_intervention_agent.notification_manager import (
    NotificationConfig,
    NotificationManager,
)
from ai_intervention_agent.notification_models import (
    NotificationEvent,
    NotificationTrigger,
    NotificationType,
)
from ai_intervention_agent.notification_providers import BarkNotificationProvider


@pytest.fixture(autouse=True)
def _disable_real_network_requests() -> None:
    """Replace the guard of ``conftest.py`` for this module only.

    The guard makes every un-mocked ``httpx`` call fail, which is right everywhere else. What
    these tests need to see is the path that a stray blank puts *on the wire*, so they start
    a Bark server of their own on a loopback port (``FakeBark``) and let the provider talk to
    it: a mocked ``session.post`` would never show ``/push%20``.
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


class PlainConfig:
    """What ``/api/test-bark`` hands the provider: a plain object, no model, no validator."""

    def __init__(
        self,
        url: str,
        key: str = "KEY123",
        icon: str | None = "",
    ) -> None:
        self.bark_enabled = True
        self.bark_url = url
        self.bark_device_key = key
        self.bark_icon = icon
        self.bark_action = "none"
        self.bark_url_template = ""
        self.bark_timeout = 3


def _event() -> NotificationEvent:
    return NotificationEvent(
        id="r823",
        title="Title",
        message="Message",
        trigger=NotificationTrigger.IMMEDIATE,
        types=[NotificationType.BARK],
        metadata={},
    )


def _send(config: Any) -> bool:
    provider = BarkNotificationProvider(config)
    try:
        return provider.send(_event())
    finally:
        provider.close()


SENT_AFTER_TRIMMING = {
    "a space at the end": "{u} ",
    "a space at the start": " {u}",
    "a line break at the end": "{u}\n",
    "a CRLF at the end": "{u}\r\n",
    "tabs around it": "\t{u}\t",
    "several blanks around it": "  \n {u} \t ",
}


class TestAnAddressWithBlanksAroundItIsSent:
    @pytest.mark.parametrize(
        "template", list(SENT_AFTER_TRIMMING.values()), ids=list(SENT_AFTER_TRIMMING)
    )
    def test_the_request_goes_to_the_address_that_was_meant(
        self, bark: FakeBark, template: str
    ) -> None:
        assert _send(PlainConfig(template.format(u=bark.url()))) is True
        assert [path for path, _ in bark.requests] == ["/push"]

    def test_the_body_is_the_same_as_for_a_clean_address(self, bark: FakeBark) -> None:
        assert _send(PlainConfig(bark.url())) is True
        assert _send(PlainConfig(f"  {bark.url()}\n")) is True
        (_, clean), (_, padded) = bark.requests
        assert padded == clean
        assert clean["device_key"] == "KEY123"
        assert clean["title"] == "Title"

    def test_a_query_string_survives_and_only_the_ends_are_trimmed(
        self, bark: FakeBark
    ) -> None:
        _send(PlainConfig(f" {bark.url('/push?group=aiia')} "))
        assert [path for path, _ in bark.requests] == ["/push?group=aiia"]

    def test_a_blank_inside_the_address_is_left_to_the_http_library(
        self, bark: FakeBark
    ) -> None:
        _send(PlainConfig(f"  {bark.url('/push?group=my group')}\n"))
        assert [path for path, _ in bark.requests] == ["/push?group=my%20group"]

    def test_a_trailing_slash_and_a_missing_path_are_not_rewritten(
        self, bark: FakeBark
    ) -> None:
        assert _send(PlainConfig(bark.url("/push/"))) is False
        assert _send(PlainConfig(f"http://127.0.0.1:{bark.port}")) is False
        # A path is case-sensitive: only the ends and the scheme are looked at.
        assert _send(PlainConfig(bark.url("/PuSh"))) is False
        assert [path for path, _ in bark.requests] == ["/push/", "/", "/PuSh"]


class TestTheSchemeIsNotCaseSensitive:
    @pytest.mark.parametrize("scheme", ["HTTP", "Http", "hTTp"])
    def test_an_upper_case_http_scheme_is_sent(
        self, bark: FakeBark, scheme: str
    ) -> None:
        url = bark.url().replace("http", scheme, 1)
        assert url.startswith(scheme + "://")
        assert _send(PlainConfig(url)) is True
        assert [path for path, _ in bark.requests] == ["/push"]

    def test_the_https_check_ignores_case_too(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # No server: the stub records the address the provider would have posted to, which
        # is all that distinguishes "accepted" from "refused as not an http(s) address";
        # the address itself is not rewritten (only its ends are trimmed).
        provider = BarkNotificationProvider(PlainConfig("HTTPS://127.0.0.1:9/push"))
        calls: list[str] = []

        class Recorder:
            status_code = 200

            def json(self) -> dict[str, int]:
                return {"code": 200}

        def post(url: str, **_kwargs: Any) -> Recorder:
            calls.append(url)
            return Recorder()

        monkeypatch.setattr(provider.session, "post", post)
        try:
            assert provider.send(_event()) is True
        finally:
            provider.close()
        assert calls == ["HTTPS://127.0.0.1:9/push"]


class TestTheClickActionGivenAsAnAddress:
    """``bark_action`` may be a fixed address to open instead of ``url`` / ``copy``."""

    def _body(self, bark: FakeBark, action: str) -> dict[str, Any]:
        config = PlainConfig(bark.url())
        config.bark_action = action
        assert _send(config) is True
        return bark.requests[-1][1]

    @pytest.mark.parametrize("scheme", ["https", "HTTPS", "Https"])
    def test_the_scheme_is_not_case_sensitive(
        self, bark: FakeBark, scheme: str
    ) -> None:
        body = self._body(bark, f"{scheme}://example.test/open")
        assert body["url"] == f"{scheme}://example.test/open"

    def test_an_address_with_blanks_around_it_is_trimmed_by_the_model(self) -> None:
        config = NotificationConfig(bark_action="  HTTPS://example.test/open \n")
        assert config.bark_action == "HTTPS://example.test/open"

    def test_something_that_is_not_an_address_still_becomes_none(self) -> None:
        assert (
            NotificationConfig(bark_action="ftp://example.test").bark_action == "none"
        )
        assert NotificationConfig(bark_action="open it").bark_action == "none"


class TestAnAddressThatIsNotHttpIsStillRefused:
    @pytest.mark.parametrize(
        "url",
        [
            "",
            "   ",
            "\n",
            "ftp://127.0.0.1/push",
            "127.0.0.1:9/push",
            "//127.0.0.1/push",
            "https:/missing-slash/push",
            "javascript:alert(1)",
        ],
    )
    def test_nothing_is_requested_and_nothing_is_raised(
        self, bark: FakeBark, url: str
    ) -> None:
        assert _send(PlainConfig(url)) is False
        assert bark.requests == []

    @pytest.mark.parametrize(
        "url",
        ["ftp://127.0.0.1/push", "127.0.0.1:9/push", "//host/push", "  ftp://x/push "],
    )
    def test_it_is_refused_before_a_request_is_attempted(
        self, monkeypatch: pytest.MonkeyPatch, url: str
    ) -> None:
        # The HTTP library would refuse most of these too, but with a traceback in the log;
        # the provider says what is wrong with the address and never builds a request.
        provider = BarkNotificationProvider(PlainConfig(url))
        attempted: list[str] = []

        def post(address: str, **_kwargs: Any) -> None:
            attempted.append(address)
            raise AssertionError("a request was attempted")

        monkeypatch.setattr(provider.session, "post", post)
        try:
            assert provider.send(_event()) is False
        finally:
            provider.close()
        assert attempted == []


class TestTheKeyAndTheIconAreTrimmedToo:
    def test_the_device_key_still_is(self, bark: FakeBark) -> None:
        _send(PlainConfig(bark.url(), key="  KEY123 \n"))
        assert bark.requests[0][1]["device_key"] == "KEY123"

    def test_an_icon_address_is(self, bark: FakeBark) -> None:
        _send(PlainConfig(bark.url(), icon="  https://example.test/icon.png \n"))
        assert bark.requests[0][1]["icon"] == "https://example.test/icon.png"

    def test_an_icon_of_blanks_is_left_out(self, bark: FakeBark) -> None:
        _send(PlainConfig(bark.url(), icon="   "))
        assert "icon" not in bark.requests[0][1]

    def test_no_icon_at_all_is_still_fine(self, bark: FakeBark) -> None:
        # A plain config object (not the model) may carry ``None`` for a field it has no
        # value for; that is "no icon", not a failure.
        assert _send(PlainConfig(bark.url(), icon=None)) is True
        assert "icon" not in bark.requests[0][1]


class TestTheConfigModelTrimsWhatItHolds:
    def test_construction(self) -> None:
        config = NotificationConfig(
            bark_url="  https://api.day.app/push \n",
            bark_device_key=" abc123\t",
            bark_icon=" https://example.test/i.png ",
        )
        assert config.bark_url == "https://api.day.app/push"
        assert config.bark_device_key == "abc123"
        assert config.bark_icon == "https://example.test/i.png"

    def test_assignment(self) -> None:
        # ``refresh_config_from_file`` and ``update_config_without_save`` assign.
        config = NotificationConfig()
        config.bark_url = "\thttps://api.day.app/push  "
        config.bark_device_key = "  key "
        config.bark_icon = " icon "
        assert (config.bark_url, config.bark_device_key, config.bark_icon) == (
            "https://api.day.app/push",
            "key",
            "icon",
        )

    def test_blanks_alone_become_empty(self) -> None:
        config = NotificationConfig(bark_url="  \n", bark_device_key="\t ")
        assert config.bark_url == ""
        assert config.bark_device_key == ""

    def test_the_inside_of_a_value_is_not_touched(self) -> None:
        config = NotificationConfig(bark_url="https://h/push?a=1 &b=2")
        assert config.bark_url == "https://h/push?a=1 &b=2"

    def test_the_letter_case_is_kept(self) -> None:
        # A device key and a path are case-sensitive; only the scheme is not.
        config = NotificationConfig(
            bark_url=" HTTPS://H.test/PuSh?A=1 ",
            bark_device_key=" AbC123xyz ",
            bark_icon=" HTTPS://H.test/I.PNG ",
        )
        assert config.bark_url == "HTTPS://H.test/PuSh?A=1"
        assert config.bark_device_key == "AbC123xyz"
        assert config.bark_icon == "HTTPS://H.test/I.PNG"

    @pytest.mark.parametrize("field", ["bark_url", "bark_device_key", "bark_icon"])
    @pytest.mark.parametrize("bad", [None, 123, ["x"], {"a": 1}], ids=repr)
    def test_a_value_that_is_not_text_is_refused_as_before(
        self, field: str, bad: Any
    ) -> None:
        # The trimming must not turn "not a string" into an ``AttributeError``: the
        # settings route answers a ``ValidationError`` with 400, anything else with 500.
        with pytest.raises(ValidationError):
            NotificationConfig(**{field: bad})
        config = NotificationConfig()
        with pytest.raises(ValidationError):
            setattr(config, field, bad)
        assert getattr(config, field) == ""


class TestTheModelsWarningAgreesWithTheProvider:
    def _warnings(self, url: str) -> list[str]:
        with patch("ai_intervention_agent.notification_manager.logger") as logger:
            NotificationConfig(bark_url=url)
        return [str(call.args[0]) for call in logger.warning.call_args_list]

    @pytest.mark.parametrize(
        "url",
        [
            "HTTPS://api.day.app/push",
            " https://api.day.app/push ",
            "Http://lan.test/push\n",
            "https://api.day.app/push",
            "",
        ],
    )
    def test_no_warning_for_an_address_the_provider_accepts(self, url: str) -> None:
        assert [w for w in self._warnings(url) if "格式无效" in w] == []

    @pytest.mark.parametrize("url", ["ftp://x/push", "api.day.app/push"])
    def test_a_warning_for_an_address_it_refuses(self, url: str) -> None:
        assert [w for w in self._warnings(url) if "格式无效" in w]


def _manager_for_the_route() -> NotificationManager:
    """A manager that is not the process singleton (``__new__`` would hand that one out)."""
    manager = object.__new__(NotificationManager)
    manager.config = NotificationConfig()
    manager._config_lock = threading.RLock()
    return manager


@pytest.fixture(scope="module")
def settings_client() -> Any:
    from ai_intervention_agent.web_ui import WebFeedbackUI

    ui = WebFeedbackUI(prompt="bark whitespace", task_id="rt-r823", port=19123)
    ui.app.config["TESTING"] = True
    ui.limiter.enabled = False
    return ui.app.test_client()


class TestTheSettingsRouteSavesAndAppliesTheCleanValues:
    """``POST /api/update-notification-config`` writes ``config.toml`` and the manager."""

    def _post(self, client: Any, body: dict[str, Any]) -> tuple[Any, Any, Any]:
        module = "ai_intervention_agent.web_ui_routes.notification"
        manager = _manager_for_the_route()
        with (
            patch.multiple(
                module, notification_manager=manager, NOTIFICATION_AVAILABLE=True
            ),
            patch(f"{module}.get_config") as get_config,
        ):
            get_config.return_value.get_section.return_value = {}
            response = client.post("/api/update-notification-config", json=body)
        return response, manager, get_config.return_value

    @pytest.mark.parametrize(
        "body",
        [
            {
                "barkUrl": "  https://h.test/push \n",
                "barkDeviceKey": " key\t",
                "barkIcon": " https://h.test/i.png ",
            },
            {
                "bark_url": "\nhttps://h.test/push",
                "bark_device_key": "key  ",
                "bark_icon": "\thttps://h.test/i.png",
            },
        ],
        ids=["camelCase", "snake_case"],
    )
    def test_the_file_and_the_manager_get_the_trimmed_values(
        self, settings_client: Any, body: dict[str, Any]
    ) -> None:
        response, manager, config_manager = self._post(settings_client, body)
        assert response.status_code == 200, response.get_data(as_text=True)
        saved = config_manager.update_section.call_args.args[1]
        assert saved["bark_url"] == "https://h.test/push"
        assert saved["bark_device_key"] == "key"
        assert saved["bark_icon"] == "https://h.test/i.png"
        assert manager.config.bark_url == "https://h.test/push"
        assert manager.config.bark_device_key == "key"
        assert manager.config.bark_icon == "https://h.test/i.png"

    def test_the_other_text_fields_are_saved_as_typed(
        self, settings_client: Any
    ) -> None:
        response, _, config_manager = self._post(
            settings_client,
            {
                "barkUrlTemplate": " {base_url}/?task_id={task_id} ",
                "webIcon": " x.png ",
            },
        )
        assert response.status_code == 200
        saved = config_manager.update_section.call_args.args[1]
        assert saved["bark_url_template"] == " {base_url}/?task_id={task_id} "
        assert saved["web_icon"] == " x.png "

    def test_a_field_that_is_null_is_still_the_empty_string(
        self, settings_client: Any
    ) -> None:
        response, manager, config_manager = self._post(
            settings_client, {"barkUrl": None, "barkIcon": None}
        )
        assert response.status_code == 200
        saved = config_manager.update_section.call_args.args[1]
        assert saved["bark_url"] == ""
        assert saved["bark_icon"] == ""
        assert manager.config.bark_url == ""


class TestTheTestButtonOfTheSettingsPage:
    """``POST /api/test-bark`` builds a plain object and a real provider: no model."""

    @pytest.mark.parametrize("template", ["{u} ", " {u}", "{u}\n", "\t{u}  "])
    def test_it_succeeds_with_blanks_around_the_address(
        self, settings_client: Any, bark: FakeBark, template: str
    ) -> None:
        response = settings_client.post(
            "/api/test-bark",
            json={
                "bark_device_key": "KEY123",
                "bark_url": template.format(u=bark.url()),
            },
        )
        assert response.status_code == 200, response.get_data(as_text=True)
        assert response.get_json()["status"] == "success"
        assert [path for path, _ in bark.requests] == ["/push"]

    def test_a_key_of_blanks_is_an_empty_key_not_a_failed_send(
        self, settings_client: Any, bark: FakeBark
    ) -> None:
        response = settings_client.post(
            "/api/test-bark",
            json={"bark_device_key": " \t\n", "bark_url": bark.url()},
        )
        assert response.status_code == 400, response.get_data(as_text=True)
        assert response.get_json()["status"] == "error"
        assert bark.requests == []

    @pytest.mark.parametrize("empty", [None, "", " ", "\n\t "])
    def test_every_kind_of_empty_key_is_the_same_400(
        self, settings_client: Any, bark: FakeBark, empty: Any
    ) -> None:
        # ``null`` counts as absent for the "is it text" check and must reach the
        # "enter the key" answer, not a crash in the trimming.
        response = settings_client.post(
            "/api/test-bark", json={"bark_device_key": empty, "bark_url": bark.url()}
        )
        assert response.status_code == 400, response.get_data(as_text=True)
        assert response.get_json()["status"] == "error"
        assert bark.requests == []

    def test_the_icon_with_blanks_is_sent_clean(
        self, settings_client: Any, bark: FakeBark
    ) -> None:
        response = settings_client.post(
            "/api/test-bark",
            json={
                "bark_device_key": "KEY123",
                "bark_url": bark.url(),
                "bark_icon": " https://example.test/icon.png\n",
            },
        )
        assert response.status_code == 200, response.get_data(as_text=True)
        assert bark.requests[0][1]["icon"] == "https://example.test/icon.png"
