"""R726 · the VS Code webview can show a local image.

A prompt that links to a local image reaches the webview as
``<img src="/api/tasks/<id>/images/<n>">``: a path on the Web UI server, which the
webview's own origin does not serve. Three existing pieces carry it to the screen and
nothing else in the suite pins them for images, so they are pinned here:

* ``sanitizePromptHtml`` keeps ``<img>`` with ``src``/``alt``/``title``;
* its ``normalizeUrl`` puts the server in front of a root-relative image URL
  (and refuses script URLs);
* the panel's CSP ``img-src`` names the server.
"""

from __future__ import annotations

import json
import re
import subprocess
import textwrap
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
VSCODE_DIR = REPO_ROOT / "packages" / "vscode"
WEBVIEW_UI_JS = VSCODE_DIR / "webview-ui.js"
WEBVIEW_TS = VSCODE_DIR / "webview.ts"

SERVER = "http://127.0.0.1:8080"


def _source() -> str:
    return WEBVIEW_UI_JS.read_text(encoding="utf-8")


def _extract_function(source: str, marker: str) -> str:
    start = source.find(marker)
    assert start != -1, f"Cannot find function marker: {marker}"
    open_brace = source.find("{", start)
    depth = 1
    i = open_brace + 1
    while i < len(source):
        char = source[i]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return source[start : i + 1]
        i += 1
    raise AssertionError(f"Unbalanced function body for: {marker}")


def _normalize_in_node(samples: list[tuple[str, str]]) -> list[str]:
    helper = _extract_function(_source(), "function normalizeUrl(")
    script = textwrap.dedent(
        f"""
        const SERVER_URL = {json.dumps(SERVER)}
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


def test_the_sanitiser_keeps_images_with_their_source_and_text() -> None:
    body = _extract_function(_source(), "function sanitizePromptHtml(")

    tags = body[body.index("const ALLOWED_TAGS") : body.index("const ALLOWED_ATTR")]
    assert "'img'" in tags
    assert "img: new Set(['src', 'alt', 'title'])" in body


def test_an_image_source_goes_through_normalize_url() -> None:
    body = _extract_function(_source(), "function sanitizePromptHtml(")

    assert re.search(
        r"tag === 'img' && name === 'src'\)\s*\{\s*"
        r"const safe = normalizeUrl\(value, 'img'\)\s*"
        r"if \(!safe\) \{\s*el\.remove\(\)\s*\} else \{\s*"
        r"el\.setAttribute\('src', safe\)",
        body,
    )


def test_a_root_relative_image_url_is_given_the_server() -> None:
    cases = [
        ("/api/tasks/t-1/images/0", "img"),
        ("/api/tasks/t-1/images/12?v=1", "img"),
        ("/api/tasks/%E4%B8%AD-1/images/0", "img"),
        ("/a.png", "img"),
    ]

    assert _normalize_in_node(cases) == [f"{SERVER}{url}" for url, _ in cases]


def test_other_image_urls_are_resolved_or_refused() -> None:
    cases = [
        ("https://example.com/a.png", "img"),
        ("data:image/png;base64,AAAA", "img"),
        ("javascript:alert(1)", "img"),
        ("  JavaScript:alert(1)", "img"),
        ("vbscript:x", "img"),
        ("data:text/html;base64,AAAA", "img"),
        ("", "img"),
    ]

    assert _normalize_in_node(cases) == [
        "https://example.com/a.png",
        "data:image/png;base64,AAAA",
        "",
        "",
        "",
        "",
        "",
    ]


def test_the_csp_lets_the_webview_load_images_from_the_server() -> None:
    template = WEBVIEW_TS.read_text(encoding="utf-8")

    assert re.search(r"img-src [^;]*\$\{serverUrl\}", template)
