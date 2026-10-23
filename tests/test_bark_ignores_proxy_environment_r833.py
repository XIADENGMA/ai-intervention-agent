"""R833: the docs say that the Bark push does not use a proxy, and that is what it does.

``BarkNotificationProvider`` builds its client with an explicit ``trust_env=False`` (R782), so the
push goes straight to ``bark_url`` whatever ``HTTP_PROXY`` / ``HTTPS_PROXY`` / ``ALL_PROXY`` (either
case) or the operating system's proxy settings say, and the notification settings have no proxy
option. The behaviour is not new (a client that is handed a transport never read the environment, so
R782 only had to write it down in the code), but nothing in the documentation said so, and on a
network that reaches the Internet only through a proxy it looks like a bug:
``curl -v "$BARK_URL/$DEVICE_KEY/test"`` works in the terminal (which has the proxy variables), the
push never arrives, and nothing in the log says why.

The configuration reference and the troubleshooting guide (both languages) now say it, and say what
to do about it. This module keeps the sentence true and in place:

A. The real provider against a real HTTP server on a loopback port, with every proxy variable in the
   environment pointing at a stand-in proxy: the Bark server gets the push, the proxy hears nothing,
   and the client declares ``trust_env=False`` (the one switch that covers ``HTTPS_PROXY`` too: a TLS
   server on a loopback port is not worth a test, and R782 scans the package for every ``httpx`` call
   that leaves it out). A control run with a default ``httpx`` client and the same environment *does*
   go through the proxy, per variable, so the stand-in is able to catch what it should (the test would
   pass for the wrong reason otherwise: httpx does not bypass ``localhost``).
B. There is no proxy setting for Bark to read: no field of ``NotificationConfig`` mentions one.
C. The documentation, in English and zh-CN: one paragraph of the troubleshooting section for
   notifications (§4) names the three variables and ``bark_url`` and tells the symptom; the
   configuration reference says it under the notification table and links to that section; the
   link's anchor is the heading's own slug; both languages say the same things.

A is a pin: it passes on the code before this change. C is what was missing.
"""

from __future__ import annotations

import http.server
import re
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any, NamedTuple

import httpx
import pytest

from ai_intervention_agent.notification_manager import NotificationConfig
from ai_intervention_agent.notification_providers import BarkNotificationProvider
from tests.test_bark_url_whitespace_r823 import FakeBark, PlainConfig, _event

REPO = Path(__file__).resolve().parent.parent
DOCS = REPO / "docs"

PROXY_VARIABLES = (
    "HTTP_PROXY",
    "http_proxy",
    "HTTPS_PROXY",
    "https_proxy",
    "ALL_PROXY",
    "all_proxy",
)
# the ones that decide for an ``http://`` address, which is what a loopback stand-in can be
HTTP_ADDRESS_VARIABLES = ("HTTP_PROXY", "http_proxy", "ALL_PROXY", "all_proxy")


@pytest.fixture(autouse=True)
def _disable_real_network_requests() -> None:
    """Replace the guard of ``conftest.py`` for this module only (see R823): the tests talk to
    servers of their own on loopback ports."""


class FakeProxy:
    """An HTTP proxy on a loopback port that records the request line of everything it is sent."""

    def __init__(self) -> None:
        outer = self
        self.request_lines: list[str] = []

        class Handler(http.server.BaseHTTPRequestHandler):
            def _record(self) -> None:
                outer.request_lines.append(self.requestline)
                self.send_response(502)
                self.send_header("Content-Length", "0")
                self.end_headers()

            do_GET = do_POST = do_CONNECT = _record

            def log_message(self, format: str, *args: Any) -> None:
                return

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.thread = threading.Thread(
            target=self.server.serve_forever,
            kwargs={"poll_interval": 0.01},
            daemon=True,
        )
        self.thread.start()

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


@pytest.fixture
def proxy(monkeypatch: pytest.MonkeyPatch) -> Iterator[FakeProxy]:
    """A stand-in proxy that every proxy variable of the environment points at."""
    stand_in = FakeProxy()
    for name in PROXY_VARIABLES:
        monkeypatch.setenv(name, stand_in.url)
    for name in ("NO_PROXY", "no_proxy"):
        monkeypatch.delenv(name, raising=False)
    try:
        yield stand_in
    finally:
        stand_in.close()


# --------------------------------------------------------------------------------------
# A. The behaviour the documentation describes
# --------------------------------------------------------------------------------------


class TestTheBarkPushIgnoresTheProxyEnvironment:
    def test_the_control_a_default_client_does_use_the_proxy(
        self, bark: FakeBark, proxy: FakeProxy
    ) -> None:
        response = httpx.post(bark.url(), json={}, trust_env=True)
        assert response.status_code == 502  # the answer of the stand-in
        assert bark.requests == []
        assert len(proxy.request_lines) == 1
        assert f"127.0.0.1:{bark.port}/push" in proxy.request_lines[0]

    def test_the_push_goes_straight_to_the_bark_server(
        self, bark: FakeBark, proxy: FakeProxy
    ) -> None:
        provider = BarkNotificationProvider(PlainConfig(bark.url()))
        try:
            assert provider.send(_event()) is True
        finally:
            provider.close()
        assert [path for path, _ in bark.requests] == ["/push"]
        assert proxy.request_lines == []

    def test_the_client_declares_it(self, proxy: FakeProxy) -> None:
        provider = BarkNotificationProvider(PlainConfig("http://127.0.0.1:1/push"))
        try:
            assert provider.session.trust_env is False
        finally:
            provider.close()

    @pytest.mark.parametrize("variable", HTTP_ADDRESS_VARIABLES)
    def test_each_variable_alone_changes_nothing(
        self,
        bark: FakeBark,
        proxy: FakeProxy,
        monkeypatch: pytest.MonkeyPatch,
        variable: str,
    ) -> None:
        for name in PROXY_VARIABLES:
            if name != variable:
                monkeypatch.delenv(name, raising=False)

        # the control: a default client takes this one variable
        assert httpx.post(bark.url(), json={}, trust_env=True).status_code == 502
        assert len(proxy.request_lines) == 1
        proxy.request_lines.clear()

        provider = BarkNotificationProvider(PlainConfig(bark.url()))
        try:
            assert provider.send(_event()) is True
        finally:
            provider.close()
        assert len(bark.requests) == 1
        assert proxy.request_lines == []


# --------------------------------------------------------------------------------------
# B. There is no proxy setting
# --------------------------------------------------------------------------------------


class TestThereIsNoProxyOption:
    def test_no_notification_setting_is_about_a_proxy(self) -> None:
        names = list(NotificationConfig.model_fields)
        assert names, (
            "the model has no fields: the check would pass for the wrong reason"
        )
        assert [name for name in names if "proxy" in name.lower()] == []
        assert "bark_url" in names


# --------------------------------------------------------------------------------------
# C. The documentation
# --------------------------------------------------------------------------------------


class Docs(NamedTuple):
    troubleshooting: Path
    configuration: Path
    does_not_read: str  # how the language says "does not read"


LANGUAGES = {
    "en": Docs(DOCS / "troubleshooting.md", DOCS / "configuration.md", "does not read"),
    "zh-CN": Docs(
        DOCS / "troubleshooting.zh-CN.md", DOCS / "configuration.zh-CN.md", "不读"
    ),
}
SECTION = (
    r"^## 4\. "  # "No notifications arrive": the table of channels, Bark's row included
)
NEXT_SECTION = r"^## 5\. "
TABLE_END = (
    "| `bark_timeout`"  # the last row of the notification table of the reference
)

VARIABLES = ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY")


def _troubleshooting_section(language: str) -> str:
    text = LANGUAGES[language].troubleshooting.read_text(encoding="utf-8")
    start = re.search(SECTION, text, re.M)
    end = re.search(NEXT_SECTION, text, re.M)
    assert start and end and start.start() < end.start()
    return text[start.start() : end.start()]


def _the_proxy_paragraph(language: str) -> str:
    """The one paragraph of the section that is about proxy variables (the section's table names
    ``bark_url`` and the check with ``curl`` by itself, so the section as a whole proves nothing)."""
    paragraphs = [
        paragraph
        for paragraph in _troubleshooting_section(language).split("\n\n")
        if "_PROXY" in paragraph
    ]
    assert len(paragraphs) == 1, paragraphs
    return paragraphs[0]


def _paragraph_after_the_notification_table(language: str) -> str:
    text = LANGUAGES[language].configuration.read_text(encoding="utf-8")
    after = text[text.index(TABLE_END) :]
    # the table's last row ends at the first blank line; the paragraph runs to the next one
    _, _, rest = after.partition("\n\n")
    paragraph, _, _ = rest.partition("\n\n")
    assert paragraph.strip(), "nothing follows the notification table"
    assert not paragraph.lstrip().startswith("#"), (
        "the notification table is followed by a heading, not by the note"
    )
    return paragraph


def _slug(heading: str) -> str:
    """The anchor GitHub gives a heading: lower-case, punctuation dropped, blanks to hyphens."""
    text = heading.lstrip("#").strip().lower()
    text = re.sub(r"[^\w\s-]", "", text, flags=re.UNICODE)
    return re.sub(r"\s", "-", text)


@pytest.mark.parametrize("language", LANGUAGES)
class TestTheDocumentationSaysSo:
    def test_the_troubleshooting_section_names_the_variables_and_the_setting(
        self, language: str
    ) -> None:
        paragraph = _the_proxy_paragraph(language)
        for name in (*VARIABLES, "bark_url"):
            assert name in paragraph, name
        assert LANGUAGES[language].does_not_read in paragraph

    def test_the_troubleshooting_section_tells_the_symptom(self, language: str) -> None:
        # the check the table already recommends, which works where the push does not
        assert 'curl -v "$BARK_URL/$DEVICE_KEY/test"' in _the_proxy_paragraph(language)

    def test_the_configuration_reference_says_it_under_the_table(
        self, language: str
    ) -> None:
        paragraph = _paragraph_after_the_notification_table(language)
        for name in (*VARIABLES, "bark_url"):
            assert name in paragraph, name
        assert LANGUAGES[language].does_not_read in paragraph

    def test_the_link_leads_to_the_section(self, language: str) -> None:
        paragraph = _paragraph_after_the_notification_table(language)
        match = re.search(r"\]\((troubleshooting[^)#]*\.md)#([^)]+)\)", paragraph)
        assert match, paragraph
        target = DOCS / match.group(1)
        assert target == LANGUAGES[language].troubleshooting
        headings = [
            line
            for line in target.read_text(encoding="utf-8").splitlines()
            if re.match(SECTION, line)
        ]
        assert len(headings) == 1
        assert match.group(2) == _slug(headings[0])
