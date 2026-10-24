"""R862: a service name that zeroconf refuses degrades mDNS like every other failure of it.

``MdnsMixin._start_mdns_if_needed`` builds a ``zeroconf.ServiceInfo`` from ``mdns.service_name``.
Zeroconf checks the name there and refuses one that cannot be a DNS label with
``BadTypeInNameException``: an instance name longer than 63 bytes (in UTF-8, so 22 Chinese
characters are already too many) or with an ASCII control character in it.  That exception is
neither an ``OSError`` nor a ``ValueError``, and those two were what the ``try`` around the
construction caught, so it went on up.  ``WebFeedbackUI.run`` calls the method in a thread
(``ai-agent-mdns-register``), so the Web UI itself carried on, but the thread ended with a
traceback on stderr: no ``mDNS`` line in the log, nothing on the console that said mDNS is off or
which setting to change, and none of the "degrade, publish nothing, keep serving by IP" the
method's other failures (``Zeroconf()`` cannot bind, ``register_service`` fails, a host name
that is taken) all do.

What the tests pin:

* the zeroconf behaviour the rest relies on (a table of names it refuses and names it takes), so
  a new zeroconf that changes it makes the table fail, not the tests that follow;
* each refused name leaves the mixin with nothing published, ``Zeroconf`` never constructed, one
  warning in the log that names the value, the key and the limit (with the traceback), and one
  line on the console, and the same name run in a thread as ``run`` does ends the thread without
  an unhandled exception;
* any exception from building the ``ServiceInfo`` takes that way, not only the two classes the
  code used to list;
* a name that is fine is still published as configured (stripped, the default for a blank or
  non-string value), with no warning.
"""

from __future__ import annotations

import logging
import socket
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
import zeroconf

from ai_intervention_agent.web_ui_mdns import MdnsMixin

LOGGER_NAME = "ai_intervention_agent.web_ui_mdns"
PUBLISH_IP = "192.168.1.2"
SERVICE_TYPE = "_http._tcp.local."
DEFAULT_NAME = "AI Intervention Agent"

REFUSED = {
    "64 ASCII characters": "x" * 64,
    "22 CJK characters (66 bytes)": "代" * 22,
    "a NUL character": "a\x00b",
    "a tab": "tab\tname",
    "a DEL character": "a\x7fb",
}
ACCEPTED = {
    "63 ASCII characters": "x" * 63,
    "21 CJK characters (63 bytes)": "代" * 21,
    "a dot": "my.service",
    "text and an emoji": "代理 Agent 🤖",
    "the default": DEFAULT_NAME,
}


class Host(MdnsMixin):
    """The part of ``WebFeedbackUI`` that the mDNS mixin reads and writes."""

    def __init__(self, service_name: Any) -> None:
        self.host = "0.0.0.0"
        self.port = 8081
        self._mdns_zeroconf = None
        self._mdns_service_info = None
        self._mdns_hostname = None
        self._mdns_publish_ip = None
        self._mdns_thread = None
        self._settings = {"enabled": True, "service_name": service_name}

    def _get_mdns_config(self) -> dict[str, Any]:
        return self._settings


class Collect(logging.Handler):
    def __init__(self) -> None:
        super().__init__(logging.WARNING)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


@contextmanager
def warnings_logged() -> Iterator[list[logging.LogRecord]]:
    """The warnings the mDNS module writes, as the ``LogRecord`` the standard library made."""
    handler = Collect()
    target = logging.getLogger(LOGGER_NAME)
    level = target.level
    target.setLevel(logging.WARNING)
    target.addHandler(handler)
    try:
        yield handler.records
    finally:
        target.removeHandler(handler)
        target.setLevel(level)


@contextmanager
def mdns_environment() -> Iterator[MagicMock]:
    """The real ``ServiceInfo`` and a ``Zeroconf`` that opens no socket (its class is yielded)."""
    with (
        patch(
            "ai_intervention_agent.web_ui_mdns.detect_best_publish_ipv4",
            return_value=PUBLISH_IP,
        ),
        patch.object(zeroconf, "Zeroconf") as zeroconf_class,
    ):
        yield zeroconf_class


def service_info(name: str) -> zeroconf.ServiceInfo:
    return zeroconf.ServiceInfo(
        SERVICE_TYPE,
        f"{name}.{SERVICE_TYPE}",
        addresses=[socket.inet_aton(PUBLISH_IP)],
        port=8081,
        properties={"path": "/"},
        server="ai-intervention-agent.local.",
    )


# ---------------------------------------------------------------- what zeroconf does


class TestWhatZeroconfDoes:
    @pytest.mark.parametrize("name", REFUSED.values(), ids=REFUSED.keys())
    def test_it_refuses_the_names_the_mixin_has_to_survive(self, name: str) -> None:
        with pytest.raises(zeroconf.BadTypeInNameException):
            service_info(name)

    def test_what_it_raises_is_neither_of_the_classes_the_code_used_to_catch(
        self,
    ) -> None:
        assert not issubclass(zeroconf.BadTypeInNameException, (OSError, ValueError))

    @pytest.mark.parametrize("name", ACCEPTED.values(), ids=ACCEPTED.keys())
    def test_it_takes_the_names_the_mixin_has_to_keep_publishing(
        self, name: str
    ) -> None:
        assert service_info(name).name == f"{name}.{SERVICE_TYPE}"


# ---------------------------------------------------------------- what the mixin does


class TestARefusedName:
    @pytest.mark.parametrize("name", REFUSED.values(), ids=REFUSED.keys())
    def test_nothing_is_published_and_the_reason_is_logged_and_printed(
        self, name: str, capsys: pytest.CaptureFixture[str]
    ) -> None:
        host = Host(name)
        with mdns_environment() as zeroconf_class, warnings_logged() as records:
            host._start_mdns_if_needed()

        assert host._mdns_zeroconf is None
        assert host._mdns_service_info is None
        assert host._mdns_hostname is None
        assert host._mdns_publish_ip is None
        zeroconf_class.assert_not_called()

        assert len(records) == 1
        record = records[0]
        message = record.getMessage()
        assert record.levelno == logging.WARNING
        assert f"service_name={name!r}" in message
        assert f"publish_ip={PUBLISH_IP!r}" in message
        assert "mdns.service_name" in message
        assert "63" in message
        assert record.exc_info is not None
        assert record.exc_info[0] is zeroconf.BadTypeInNameException

        printed = capsys.readouterr().out
        assert "mDNS 发布失败" in printed
        assert "IP/localhost" in printed

    @pytest.mark.parametrize("name", REFUSED.values(), ids=REFUSED.keys())
    def test_the_thread_that_run_starts_ends_without_an_unhandled_exception(
        self, name: str
    ) -> None:
        unhandled: list[threading.ExceptHookArgs] = []
        host = Host(name)
        with (
            mdns_environment(),
            warnings_logged(),
            patch.object(threading, "excepthook", unhandled.append),
        ):
            thread = threading.Thread(
                target=host._start_mdns_if_needed,
                name="ai-agent-mdns-register",
                daemon=True,
            )
            thread.start()
            thread.join(timeout=10)

        assert not thread.is_alive()
        assert [args.exc_type for args in unhandled] == []
        assert host._mdns_zeroconf is None


class TestAnyFailureOfTheConstruction:
    @pytest.mark.parametrize(
        "error",
        [
            OSError("illegal IP address string passed"),
            ValueError("not a port"),
            zeroconf.BadTypeInNameException("Too long"),
            zeroconf.Error("something zeroconf did not like"),
            RuntimeError("something nobody expected"),
        ],
        ids=lambda error: type(error).__name__,
    )
    def test_degrades_and_says_so(
        self, error: Exception, capsys: pytest.CaptureFixture[str]
    ) -> None:
        host = Host(DEFAULT_NAME)
        with (
            mdns_environment() as zeroconf_class,
            patch.object(zeroconf, "ServiceInfo", side_effect=error),
            warnings_logged() as records,
        ):
            host._start_mdns_if_needed()

        assert host._mdns_zeroconf is None
        zeroconf_class.assert_not_called()
        assert len(records) == 1
        assert str(error) in records[0].getMessage()
        assert records[0].exc_info is not None
        assert "mDNS 发布失败" in capsys.readouterr().out


class TestAGoodName:
    @pytest.mark.parametrize("name", ACCEPTED.values(), ids=ACCEPTED.keys())
    def test_is_published_as_configured(
        self, name: str, capsys: pytest.CaptureFixture[str]
    ) -> None:
        host = Host(name)
        with mdns_environment() as zeroconf_class, warnings_logged() as records:
            host._start_mdns_if_needed()

        assert records == []
        zeroconf_class.assert_called_once_with()
        register = zeroconf_class.return_value.register_service
        register.assert_called_once()
        info = register.call_args.args[0]
        assert info.name == f"{name}.{SERVICE_TYPE}"
        assert info.port == 8081
        assert host._mdns_zeroconf is zeroconf_class.return_value
        assert host._mdns_service_info is info
        assert host._mdns_publish_ip == PUBLISH_IP
        assert "mDNS 发布失败" not in capsys.readouterr().out

    def test_is_stripped_first(self) -> None:
        host = Host("  padded name \t")
        with mdns_environment() as zeroconf_class, warnings_logged() as records:
            host._start_mdns_if_needed()

        assert records == []
        info = zeroconf_class.return_value.register_service.call_args.args[0]
        assert info.name == f"padded name.{SERVICE_TYPE}"

    @pytest.mark.parametrize("configured", ["", "   ", "\t\n", 123, None, ["a"]])
    def test_a_blank_or_non_string_value_publishes_the_default_name(
        self, configured: Any
    ) -> None:
        host = Host(configured)
        with mdns_environment() as zeroconf_class, warnings_logged() as records:
            host._start_mdns_if_needed()

        assert records == []
        info = zeroconf_class.return_value.register_service.call_args.args[0]
        assert info.name == f"{DEFAULT_NAME}.{SERVICE_TYPE}"
