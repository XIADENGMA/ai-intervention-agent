"""R729 · A bracketed IPv6 entry in ``TRUSTED_HOSTS`` keeps matching on Werkzeug 3.1.9.

Background
----------
Flask's ``TRUSTED_HOSTS`` ends in ``werkzeug.sansio.utils.host_is_trusted``.
Werkzeug 3.1.9 (2026-09-27) validates the ``Host`` header as one token, so
``[::1]:8080`` stays whole, but it still cuts every allowlist entry at its
first colon, so the ``[::1]`` entry turns into ``[`` and no IPv6 ``Host`` is
ever trusted (pallets/werkzeug#3312: fixed on ``main``, no patch release yet).
Releases up to 3.1.8 matched by accident (both sides were cut at the first
colon, so every bracketed host matched every bracketed entry).

Dependabot merged the 3.1.9 bump (PR #123) with the Python 3.11/3.12/3.13 CI
jobs red, so ``http://[::1]:<port>/`` answered 400 and ``main`` stayed red.

What this module locks
----------------------
``ensure_ipv6_trusted_hosts_support`` wraps Werkzeug's function only when a
probe shows the loopback entry being refused, and the wrapper:

* returns what Werkzeug returns and only ever turns a refusal into a trust;
* trusts a bracketed IPv6 ``Host`` only when Werkzeug itself validates the
  value (characters, port range) and a bracketed entry names the same address
  (other spellings of one address match, other addresses never do);
* leaves every domain and IPv4 decision alone;
* is idempotent, leaves a Werkzeug that already matches untouched, never raises
  and stays silent about Werkzeug 3.2's deprecation of the helper.

``WebFeedbackUI`` calls it before it sets ``TRUSTED_HOSTS``; the real-app tests
run against whichever Werkzeug is installed.
"""

from __future__ import annotations

import inspect
import random
import re
import warnings
from collections.abc import Callable, Collection
from importlib.metadata import version
from ipaddress import ip_address
from pathlib import Path
from typing import Any

import pytest
from werkzeug.sansio import utils as werkzeug_utils

from ai_intervention_agent.web_ui import WebFeedbackUI
from ai_intervention_agent.web_ui_security import (
    _host_is_trusted_with_ipv6,
    ensure_ipv6_trusted_hosts_support,
)

SRC = Path(__file__).resolve().parent.parent / "src" / "ai_intervention_agent"

_HOST_RE = re.compile(
    r"""
    (
        [a-z0-9.-]+  # domain or ipv4
    |
        \[[a-f0-9]*:[a-f0-9.:]+]  # ipv6
    )
    (?::([1-9][0-9]{,4}))?  # optional port
    """,
    flags=re.ASCII | re.IGNORECASE | re.VERBOSE,
)


def _walk(
    hostname: str | None,
    trusted_list: Collection[str] | None,
    cut_entry: Callable[[str], str],
) -> bool:
    """The shared body of Werkzeug 3.1.9 and main; only the entry cut differs."""
    if not hostname:
        return False
    if (m := _HOST_RE.fullmatch(hostname)) is None:
        return False
    hostname, port_str = m.groups()
    if port_str and not (1 <= int(port_str) <= 65535):
        return False
    if not trusted_list:
        return True
    if isinstance(trusted_list, str):
        trusted_list = [trusted_list]
    for ref in trusted_list:
        if ref.startswith("."):
            ref = ref[1:]
            suffix_match = True
        else:
            suffix_match = False
        try:
            ref = cut_entry(ref).encode("idna").decode("ascii")
        except UnicodeEncodeError:
            return False
        if ref == hostname or (suffix_match and hostname.endswith(f".{ref}")):
            return True
    return False


def werkzeug_319(
    hostname: str | None, trusted_list: Collection[str] | None = None
) -> bool:
    """Werkzeug 3.1.9: entries are cut at the first colon (the bug)."""
    return _walk(hostname, trusted_list, lambda ref: ref.partition(":")[0])


def werkzeug_main(
    hostname: str | None, trusted_list: Collection[str] | None = None
) -> bool:
    """Upstream main: entries are used as they are (the fix)."""
    return _walk(hostname, trusted_list, lambda ref: ref)


def werkzeug_318(
    hostname: str | None, trusted_list: Collection[str] | None = None
) -> bool:
    """Up to 3.1.8: both sides cut at the first colon (IPv6 matched by accident)."""
    if not hostname or _HOST_RE.fullmatch(hostname) is None:
        return False
    hostname = hostname.partition(":")[0]
    if not trusted_list:
        return True
    if isinstance(trusted_list, str):
        trusted_list = [trusted_list]
    return any(ref.partition(":")[0] == hostname for ref in trusted_list)


def install(monkeypatch: pytest.MonkeyPatch, double: Any) -> Any:
    monkeypatch.setattr(werkzeug_utils, "host_is_trusted", double, raising=False)
    return double


# --- the test doubles are faithful -----------------------------------------


@pytest.mark.skipif(
    version("werkzeug") != "3.1.9", reason="the double copies Werkzeug 3.1.9"
)
def test_double_matches_the_installed_werkzeug_319():
    """If this fails, the copy above no longer describes the real function."""
    real = inspect.unwrap(werkzeug_utils.host_is_trusted)
    cases = [
        ("localhost:8080", ["localhost"]),
        ("[::1]:8080", ["[::1]"]),
        ("[::1]", ["[::1]", "localhost"]),
        ("evil.example", ["localhost"]),
        ("a.local", [".local"]),
        ("[::1]:99999", ["[::1]"]),
        ("", ["localhost"]),
        ("localhost", []),
        ("localhost", "localhost"),
    ]
    for host, trusted in cases:
        assert real(host, trusted) == werkzeug_319(host, trusted), (host, trusted)


def test_doubles_describe_the_three_behaviours():
    assert werkzeug_319("[::1]:80", ["[::1]"]) is False
    assert werkzeug_main("[::1]:80", ["[::1]"]) is True
    assert werkzeug_318("[::1]:80", ["[::1]"]) is True
    # up to 3.1.8 every bracketed host matched every bracketed entry
    assert werkzeug_318("[::2]:80", ["[::1]"]) is True
    assert werkzeug_main("[::2]:80", ["[::1]"]) is False


# --- the wrapper -----------------------------------------------------------

WRAPPED = _host_is_trusted_with_ipv6(werkzeug_319)


@pytest.mark.parametrize(
    "host",
    ["[::1]", "[::1]:8080", "[::1]:80", "[::1]:65535", "[::1]:1"],
)
def test_the_loopback_literal_is_trusted_with_and_without_a_port(host):
    assert WRAPPED(host, ["localhost", "127.0.0.1", "[::1]"]) is True


@pytest.mark.parametrize(
    ("host", "entry"),
    [
        ("[0:0:0:0:0:0:0:1]:8080", "[::1]"),
        ("[::1]", "[0:0:0:0:0:0:0:1]"),
        ("[2001:DB8::10]:8080", "[2001:db8::10]"),
        ("[2001:db8::10]", "[2001:DB8:0:0:0:0:0:10]"),
        ("[::ffff:1.2.3.4]:80", "[::ffff:102:304]"),
        ("[2001:db8::10]:8080", "[2001:db8::10]:9999"),
    ],
)
def test_other_spellings_of_the_same_address_match(host, entry):
    assert WRAPPED(host, [entry]) is True


@pytest.mark.parametrize(
    ("host", "entries"),
    [
        ("[::2]:8080", ["[::1]"]),
        ("[2001:db8::11]", ["[2001:db8::10]"]),
        ("[::1]:8080", ["[::2]", "localhost"]),
        ("[::1]:8080", ["::1"]),  # no brackets: not an IPv6 entry
        ("[::1]:8080", ["[::1", "[]", "[zz]", "["]),
        ("[::1]:8080", ["[1.2.3.4]"]),  # brackets around IPv4 are not IPv6
    ],
)
def test_a_different_address_is_never_trusted(host, entries):
    assert WRAPPED(host, entries) is False


@pytest.mark.parametrize(
    "host",
    [
        "[::1]x",
        "[::1]:0",
        "[::1]:65536",
        "[::1]:99999",
        "[::1]:08080",
        "[::1",
        "::1",
        "[::1]]",
        "[::1]:80:80",
        "[::1%25eth0]",
        "[::1]/",
        " [::1]",
        "",
        None,
    ],
)
def test_a_value_werkzeug_rejects_stays_rejected_even_when_the_address_matches(host):
    assert WRAPPED(host, ["[::1]"]) is False


def test_an_empty_or_missing_list_defers_to_werkzeug():
    for trusted in (None, [], ()):
        for host in ("[::1]:8080", "[::1]:99999", "", "localhost"):
            assert WRAPPED(host, trusted) is werkzeug_319(host, trusted), (
                host,
                trusted,
            )


def test_the_list_may_be_a_single_string():
    assert WRAPPED("[::1]:8080", "[::1]") is True
    assert WRAPPED("[::2]:8080", "[::1]") is False


def test_domains_and_ipv4_are_decided_by_werkzeug_alone():
    hosts = [
        "localhost",
        "localhost:8080",
        "LOCALHOST",
        "127.0.0.1:8080",
        "evil.example",
        "a.local",
        "ai.local:8080",
        "192.168.1.10:8080",
        "bad host",
        "a_b.example",
        "xn--nxasmq6b.example",
    ]
    lists = [
        ["localhost"],
        ["localhost", "127.0.0.1", "[::1]"],
        [".local"],
        ["ai.local", "192.168.1.10"],
        [],
        None,
        "localhost",
    ]
    for host in hosts:
        for trusted in lists:
            assert WRAPPED(host, trusted) is werkzeug_319(host, trusted), (
                host,
                trusted,
            )


def test_the_wrapper_only_turns_a_refusal_into_a_trust_and_only_for_the_same_address():
    rng = random.Random(729)
    addresses = [
        "::1",
        "0:0:0:0:0:0:0:1",
        "::2",
        "2001:db8::10",
        "2001:DB8:0:0:0:0:0:10",
        "2001:db8::11",
        "fe80::1",
        "::ffff:1.2.3.4",
        "::ffff:102:304",
    ]
    ports = ["", ":80", ":8080", ":0", ":65536"]
    hosts = [f"[{a}]{p}" for a in addresses for p in ports] + ["localhost", "x.y"]
    entry_pool = [f"[{a}]" for a in addresses] + ["localhost", ".local", "::1", "[::1"]
    widened = 0
    for _ in range(400):
        trusted = rng.sample(entry_pool, rng.randint(0, 4))
        host = rng.choice(hosts)
        base = werkzeug_319(host, trusted)
        got = WRAPPED(host, trusted)
        if got == base:
            continue
        widened += 1
        assert got is True and base is False, (host, trusted)
        literal = ip_address(host[1 : host.index("]")])
        assert werkzeug_319(host, None) is True, (host, trusted)
        assert any(
            entry.startswith("[")
            and "]" in entry
            and ip_address(entry[1 : entry.index("]")]) == literal
            for entry in trusted
        ), (host, trusted)
    assert widened > 20, "the sample never exercised the wrapper"


# --- the installer ---------------------------------------------------------


def test_a_refusing_werkzeug_is_wrapped_once(monkeypatch):
    install(monkeypatch, werkzeug_319)
    assert ensure_ipv6_trusted_hosts_support() is True
    patched = werkzeug_utils.host_is_trusted
    assert patched is not werkzeug_319
    assert getattr(patched, "__wrapped__", None) is werkzeug_319
    assert patched("[::1]:8080", ["[::1]"]) is True
    assert patched("[::2]:8080", ["[::1]"]) is False
    assert patched("evil.example", ["localhost"]) is False
    assert ensure_ipv6_trusted_hosts_support() is False
    assert werkzeug_utils.host_is_trusted is patched


def test_get_host_uses_the_wrapper(monkeypatch):
    install(monkeypatch, werkzeug_319)
    ensure_ipv6_trusted_hosts_support()
    assert (
        werkzeug_utils.get_host("http", "[::1]:8080", None, ["[::1]"]) == "[::1]:8080"
    )
    with pytest.raises(Exception, match="not trusted"):
        werkzeug_utils.get_host("http", "[::2]:8080", None, ["[::1]"])


@pytest.mark.parametrize("double", [werkzeug_main, werkzeug_318])
def test_a_werkzeug_that_already_matches_is_left_alone(monkeypatch, double):
    install(monkeypatch, double)
    assert ensure_ipv6_trusted_hosts_support() is False
    assert werkzeug_utils.host_is_trusted is double


def test_a_missing_or_unusable_function_is_left_alone(monkeypatch):
    monkeypatch.delattr(werkzeug_utils, "host_is_trusted")
    assert ensure_ipv6_trusted_hosts_support() is False

    def explodes(*_args: Any) -> bool:
        raise RuntimeError("boom")

    install(monkeypatch, explodes)
    assert ensure_ipv6_trusted_hosts_support() is False
    assert werkzeug_utils.host_is_trusted is explodes

    install(monkeypatch, "not callable")
    assert ensure_ipv6_trusted_hosts_support() is False


@pytest.mark.parametrize("base", [werkzeug_main, werkzeug_319])
def test_probing_a_deprecated_helper_stays_silent(monkeypatch, base):
    def deprecated(hostname, trusted_list=None):
        warnings.warn("host_is_trusted is deprecated", DeprecationWarning, stacklevel=2)
        return base(hostname, trusted_list)

    install(monkeypatch, deprecated)
    with warnings.catch_warnings(record=True) as seen:
        warnings.simplefilter("always")
        patched = ensure_ipv6_trusted_hosts_support()
    assert patched is (base is werkzeug_319)
    assert [str(item.message) for item in seen] == []


# --- the real application --------------------------------------------------


def _status(ui: WebFeedbackUI, host: str) -> int:
    ui.app.config["TESTING"] = True
    response = ui.app.test_client().get(
        "/", headers={"Host": host}, environ_base={"REMOTE_ADDR": "127.0.0.1"}
    )
    return response.status_code


def _ui(host: str) -> WebFeedbackUI:
    return WebFeedbackUI(
        prompt="test",
        predefined_options=[],
        task_id="test-ipv6-hosts-r729",
        host=host,
        port=8080,
    )


def test_the_real_app_serves_the_ipv6_loopback_host():
    ui = _ui("0.0.0.0")
    for host in ("[::1]:8080", "[::1]"):
        assert _status(ui, host) == 200, host
    assert _status(ui, "evil.example") == 400


def test_the_real_app_serves_the_bound_ipv6_address_and_only_that_one():
    ui = _ui("2001:db8::10")
    assert _status(ui, "[2001:db8::10]:8080") == 200
    # Werkzeug up to 3.1.8 trusts every bracketed host once one entry exists;
    # the assertion needs a Werkzeug that tells addresses apart.
    if werkzeug_utils.host_is_trusted("[2001:db8::11]:8080", ["[2001:db8::10]"]):
        pytest.skip("this Werkzeug trusts every bracketed host (3.1.8 or older)")
    assert _status(ui, "[2001:db8::11]:8080") == 400


# --- the wiring ------------------------------------------------------------


def test_the_app_installs_the_compat_before_it_sets_trusted_hosts():
    source = (SRC / "web_ui.py").read_text(encoding="utf-8")
    call = source.index("ensure_ipv6_trusted_hosts_support()")
    assignment = source.index('self.app.config["TRUSTED_HOSTS"]')
    assert call < assignment
    assert source.count("ensure_ipv6_trusted_hosts_support()") == 1
