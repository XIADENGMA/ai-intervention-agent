r"""R768 regression coverage: the vendored marked.js is a release that is safe on agent text.

The Web UI renders the agent's message with the copy of marked in
``static/js/marked.js`` and inserts the result with ``innerHTML``. That copy was
17.0.1 while ``package-lock.json`` already resolved 17.0.6, and the releases from
there up to 18.1.1 fix four things that matter here:

1. 17.0.3 escapes the alt text of an image. Before, ``![a" onerror=x y="](p.png)``
   came out as an ``<img>`` carrying attributes of the sender's choosing (the CSP
   stops script handlers, but not ``style="position:fixed;..."`` overlays).
2. 17.0.4 and 17.0.5 fix regular expressions that backtracked without bound: an
   unclosed ``[`` followed by twenty code spans written with two backticks each (200
   bytes) froze the tab for good, and 6 kB of ``a[b](c`` repeated cost two seconds
   (24 kB more than half a minute), all on the main thread of the page the user
   needs to answer the question.
3. 17.0.2 and 17.0.5 stop ``"~3.8k", "~1.4k"`` from striking through the text
   between the two tildes.
4. 18.1.1 fixes the last freeze that is cubic in the input: ``[a](`` followed by
   Unicode whitespace (4,000 em spaces took 12 to 22 seconds on 17.0.6, 8,000 more
   than a minute; 20,000 take 7 ms on 18.1.1).

The copy now has to be a release with those fixes and has to follow the lockfile,
which is what Dependabot bumps and what had silently stopped reaching the page.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
MARKED_JS = REPO_ROOT / "src" / "ai_intervention_agent" / "static" / "js" / "marked.js"
LOCKFILE = REPO_ROOT / "package-lock.json"

pytestmark = pytest.mark.skipif(
    shutil.which("node") is None, reason="node runtime unavailable"
)

HARNESS = r"""
const vm = require('vm');
const fs = require('fs');
const sandbox = vm.createContext({});
vm.runInContext(fs.readFileSync(process.env.R768_MARKED, 'utf8'), sandbox);
const marked = sandbox.marked;
marked.use({ renderer: { html() { return ''; } } });
marked.setOptions({ mangle: false, headerIds: false });
const started = process.hrtime.bigint();
const html = marked.parse(process.env.R768_MARKDOWN);
const ms = Number((process.hrtime.bigint() - started) / 1000000n);
process.stdout.write(JSON.stringify({ html, ms }));
"""

ALT_ATTACKS = {
    "quote_and_handler": '![a" onerror=alert(1) x="](p.png)',
    "quote_and_style": (
        '![a" style="position:fixed;inset:0;width:100vw;height:100vh" x="](p.png)'
    ),
    "angle_brackets": "![a<script>alert(1)</script>](p.png)",
    "ampersand_and_quote": '![a&quot;" onmouseover=alert(1) x="](p.png)',
}


def _render(markdown: str, *, timeout: float = 20.0) -> dict:
    env = {
        **os.environ,
        "R768_MARKED": str(MARKED_JS),
        "R768_MARKDOWN": markdown,
    }
    try:
        proc = subprocess.run(
            ["node", "-e", HARNESS],
            env=env,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        pytest.fail(
            f"marked.parse did not finish within {timeout:g}s on "
            f"{len(markdown)} characters of input"
        )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def _attribute_names(tag: str) -> list[str]:
    without_values = re.sub(r'"[^"]*"', '""', tag)
    return re.findall(r"\s([A-Za-z-]+)(?==)", without_values)


@pytest.mark.parametrize("name", sorted(ALT_ATTACKS))
def test_image_alt_text_cannot_add_attributes(name: str) -> None:
    html = _render(ALT_ATTACKS[name])["html"]

    names = {n for tag in re.findall(r"<[^>]*>", html) for n in _attribute_names(tag)}
    assert names <= {"src", "alt", "title"}, html
    assert "<script" not in html, html


def test_images_with_plain_alt_and_title_render_as_before() -> None:
    html = _render('![a cat](cat.png "Tom\'s \\"best\\"")')["html"]

    assert html.startswith('<p><img src="cat.png" alt="a cat" title="')
    assert "Tom&#39;s" in html


@pytest.mark.parametrize(
    ("name", "markdown"),
    [
        ("link_title", "a[b](c" * 4000),
        ("link_unicode_whitespace", "[a](" + "\u2003" * 4000),
        (
            "backticks_after_bracket",
            "[" + " ".join(f"````code{i}````" for i in range(100)),
        ),
        (
            "rst_code_after_bracket",
            "[" + " ".join(f"``code{i}``" for i in range(20)),
        ),
    ],
)
def test_short_inputs_cannot_hang_the_page(name: str, markdown: str) -> None:
    result = _render(markdown)

    assert result["ms"] < 2000, f"{name}: {result['ms']} ms for {len(markdown)} chars"


def test_approximate_values_are_not_struck_through() -> None:
    html = _render('at v1.7.7 the "~3.8k", "~1.4k" figures')["html"]

    assert "<del>" not in html
    assert "~3.8k" in html
    assert "~1.4k" in html


def test_real_strikethrough_still_works() -> None:
    assert "<del>gone</del>" in _render("this is ~~gone~~ now")["html"]


def test_vendored_copy_matches_the_lockfile() -> None:
    header = MARKED_JS.read_text(encoding="utf-8")[:300]
    match = re.search(r"marked v(\d+\.\d+\.\d+)", header)
    assert match, header
    locked = json.loads(LOCKFILE.read_text(encoding="utf-8"))["packages"][
        "node_modules/marked"
    ]["version"]

    assert match.group(1) == locked, (
        f"static/js/marked.js is marked {match.group(1)} but package-lock.json "
        f"resolves {locked}; copy node_modules/marked/lib/marked.umd.js over it and "
        "run scripts/precompress_static.py"
    )
