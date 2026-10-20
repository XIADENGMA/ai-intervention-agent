"""R741 — a protocol-relative URL in a prompt keeps its own host in the VS Code webview.

The panel's sanitiser rewrites every link and image URL with ``normalizeUrl``.  A URL
that starts with ``/`` is a path on the Web UI server and gets the server in front of
it (R726).  The test was ``startsWith('/')``, which also matched ``//host/path``: the
link ``[docs](//example.com/docs)`` became ``http://127.0.0.1:8080//example.com/docs``,
a 404 on the local server, instead of ``http://example.com/docs``.  Only a single
leading slash is a local path now; ``//host/path`` is resolved against the server's
scheme like any other URL, and an unusable one (``//``, no server) is dropped.

The tests run the real function from ``webview-ui.js`` in Node.

Pattern: C + Node runtime.
"""

from __future__ import annotations

import json
import subprocess
import textwrap

import pytest

from tests.test_vscode_webview_local_images_r726 import _extract_function, _source

HTTP_SERVER = "http://127.0.0.1:8080"
HTTPS_SERVER = "https://aiia.example.com"


def _normalize(server: str, samples: list[tuple[str, str]]) -> list[str]:
    helper = _extract_function(_source(), "function normalizeUrl(")
    script = textwrap.dedent(
        f"""
        const SERVER_URL = {json.dumps(server)}
        {helper}
        const samples = JSON.parse(process.argv[1])
        process.stdout.write(
          JSON.stringify(samples.map(([url, kind]) => normalizeUrl(url, kind)))
        )
        """
    )
    result = subprocess.run(
        ["node", "-e", script, json.dumps(samples)],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


@pytest.mark.parametrize(
    ("server", "scheme"), [(HTTP_SERVER, "http"), (HTTPS_SERVER, "https")]
)
def test_a_protocol_relative_url_keeps_its_own_host(server: str, scheme: str) -> None:
    samples = [
        ("//cdn.example.com/a.png", "img"),
        ("//example.com/docs?x=1#top", "a"),
        ("//localhost:9999/x", "img"),
    ]

    assert _normalize(server, samples) == [
        f"{scheme}://cdn.example.com/a.png",
        f"{scheme}://example.com/docs?x=1#top",
        f"{scheme}://localhost:9999/x",
    ]


@pytest.mark.parametrize("server", [HTTP_SERVER, HTTPS_SERVER])
def test_a_path_with_one_leading_slash_still_goes_to_the_server(server: str) -> None:
    samples = [
        ("/a.png", "img"),
        ("/api/tasks/t-1/images/0", "img"),
        ("/x//y", "a"),
        ("/", "a"),
    ]

    assert _normalize(server, samples) == [server + url for url, _ in samples]


def test_a_protocol_relative_url_that_cannot_be_resolved_is_dropped() -> None:
    samples = [
        ("//", "a"),
        ("///", "a"),
        ("//javascript:alert(1)", "a"),
    ]

    assert _normalize(HTTP_SERVER, samples) == ["", "", ""]


def test_without_a_server_a_protocol_relative_url_is_dropped() -> None:
    samples = [("//cdn.example.com/a.png", "img"), ("/a.png", "img")]

    assert _normalize("", samples) == ["", "/a.png"]
