r"""R771 regression coverage: the files MathJax asks for while typesetting are shipped, served and survivable.

``tex-mml-chtml.js`` is the whole MathJax program, but while typesetting it still
downloads two kinds of files next to itself:

* TeX extensions (``input/tex/extensions/<name>.js``). A formula that uses
  ``\boldsymbol``, ``\color``, ``\textcolor``, ``\cancel``, ``\bra`` / ``\ket``,
  ``\ce`` ... makes MathJax autoload one of them. None was shipped, so the
  download was a 404 and MathJax rejected the whole message: every formula in it, also
  the plain ones, stayed as raw TeX. (R802 keeps two of them, ``html`` and ``bbox``,
  out of the package on purpose: they let a formula link, restyle or re-id the page.)
* The CHTML web fonts (``output/chtml/fonts/woff-v2/``). Only 4 of the 22 the bundle
  names were shipped, so ``\mathbb``, ``\mathbf``, ``\mathcal``, big brackets ... fell
  back to a system font.

Two more things stood in the way once those files exist:

* They are nested paths, answered by Flask's own ``/static/<path:filename>`` endpoint,
  which was not exempt from the default limits ("10 per second"). A formula needing a dozen
  fonts asks for them all at once, so everything past the tenth got a 429 and the font
  never loaded.
* A message in which one formula still cannot be typeset (a ``\require`` of a package
  that does not exist) lost all of its formulas, so a failed typeset is retried one
  formula at a time.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import textwrap
import unittest
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
STATIC_JS = REPO_ROOT / "src" / "ai_intervention_agent" / "static" / "js"
BUNDLE_JS = STATIC_JS / "tex-mml-chtml.js"
LOADER_JS = STATIC_JS / "mathjax-loader.js"
EXTENSIONS_DIR = STATIC_JS / "input" / "tex" / "extensions"
FONTS_DIR = STATIC_JS / "output" / "chtml" / "fonts" / "woff-v2"

MATHJAX_VERSION = "3.2.2"
# ``autoload`` lists it, but it is compiled into the bundle: nothing to download.
BUILT_IN_EXTENSIONS = {"newcommand"}
# The bundle names these too, but the page switches them off and does not ship them
# (R802, test_mathjax_no_page_control_r802.py).
HELD_BACK_EXTENSIONS = {"html", "bbox"}
FONT_FILE_PATTERN = (
    r"MathJax_(?:AMS|Calligraphic|Fraktur|Main|Math|SansSerif|Script|Size[1-4]"
    r"|Typewriter|Vector|Zero)(?:-[A-Za-z]+)?"
)


def _bundle() -> str:
    return BUNDLE_JS.read_text(encoding="utf-8")


def _autoload_extensions() -> set[str]:
    """The extension names MathJax can ask for on its own, read from the real bundle."""
    match = re.search(r"autoload:\(0,[\w$]+\.expandable\)\(\{([^{}]*)\}\)", _bundle())
    assert match, "cannot find the autoload table in tex-mml-chtml.js"
    return set(re.findall(r"(?:^|,)([A-Za-z]+):\[", match.group(1)))


def _font_names() -> set[str]:
    return set(re.findall(FONT_FILE_PATTERN, _bundle()))


def test_autoload_table_is_read_from_the_bundle() -> None:
    # Guards the parser above: an empty or truncated table would make the shipped-file
    # tests below vacuous.
    names = _autoload_extensions()
    assert {"boldsymbol", "color", "cancel", "enclose", "mhchem", "html"} <= names
    assert len(names) >= 14, names


def test_every_extension_autoload_can_request_is_shipped() -> None:
    missing = sorted(
        name
        for name in _autoload_extensions() - BUILT_IN_EXTENSIONS - HELD_BACK_EXTENSIONS
        if not (EXTENSIONS_DIR / f"{name}.js").is_file()
    )
    assert missing == [], (
        f"MathJax autoloads these but {EXTENSIONS_DIR} has no such file, so a "
        f"formula using them is a 404 and the whole message stays raw TeX: {missing}"
    )


def test_shipped_extensions_belong_to_the_bundled_mathjax_version() -> None:
    assert f'"{MATHJAX_VERSION}"' in _bundle()
    stale = sorted(
        path.name
        for path in EXTENSIONS_DIR.glob("*.js")
        if f'"{MATHJAX_VERSION}"' not in path.read_text(encoding="utf-8")
    )
    assert stale == [], f"not MathJax {MATHJAX_VERSION}: {stale}"


def test_extensions_are_single_files_with_a_final_newline() -> None:
    # end-of-file-fixer rewrites a file without the newline, which would make the
    # vendored copy differ from what is committed.
    for path in EXTENSIONS_DIR.glob("*.js"):
        data = path.read_bytes()
        assert data.endswith(b"\n") and not data.endswith(b"\n\n"), path.name
        assert b"\r" not in data, path.name


def test_every_font_the_bundle_names_is_shipped_and_nothing_else() -> None:
    names = _font_names()
    assert len(names) == 22, sorted(names)

    shipped = {path.stem for path in FONTS_DIR.glob("*.woff")}
    assert sorted(names - shipped) == [], (
        "font files the CHTML output asks for are missing"
    )
    assert sorted(shipped - names) == [], "font files nothing asks for"

    for name in names:
        head = (FONTS_DIR / f"{name}.woff").read_bytes()[:4]
        assert head == b"wOFF", f"{name}.woff is not a WOFF file"


class TestNestedAssetsAreServedAndNotRateLimited(unittest.TestCase):
    _ui: Any = None
    _client: Any = None

    @classmethod
    def setUpClass(cls) -> None:
        from ai_intervention_agent.web_ui import WebFeedbackUI

        cls._ui = WebFeedbackUI(prompt="r771", task_id="r771-base", port=19771)
        cls._ui.app.config["TESTING"] = True
        # The limiter stays on: the point is that these URLs do not count against it.
        assert cls._ui.limiter.enabled
        # A plain route, under the default limits like any API endpoint (it has to
        # exist before the app serves its first request).
        cls._ui.app.add_url_rule("/r771-limited", "r771_limited", lambda: "ok")
        cls._client = cls._ui.app.test_client()

    def _urls(self) -> list[str]:
        urls = [
            f"/static/js/input/tex/extensions/{path.name}"
            for path in sorted(EXTENSIONS_DIR.glob("*.js"))
        ]
        urls += [
            f"/static/js/output/chtml/fonts/woff-v2/{name}.woff"
            for name in sorted(_font_names())
        ]
        return urls

    def test_every_shipped_asset_is_served(self) -> None:
        for url in self._urls():
            response = self._client.get(url)
            try:
                self.assertEqual(response.status_code, 200, url)
                self.assertGreater(len(response.get_data()), 500, url)
                if url.endswith(".js"):
                    self.assertIn("javascript", response.headers["Content-Type"], url)
                else:
                    self.assertIn("woff", response.headers["Content-Type"], url)
            finally:
                response.close()

    def test_a_burst_of_nested_asset_requests_is_never_rate_limited(self) -> None:
        # One formula can need a dozen fonts and extensions within a second. Three
        # rounds are far beyond both default limits (10 per second, 60 per minute).
        urls = self._urls() * 3
        self.assertGreater(len(urls), 60)

        statuses = []
        for url in urls:
            response = self._client.get(url)
            statuses.append(response.status_code)
            response.close()

        self.assertEqual(set(statuses), {200}, statuses)

    def test_the_limiter_still_guards_other_endpoints(self) -> None:
        # Exempting static files must not have switched the limiter off.
        statuses = set()
        for _ in range(80):
            response = self._client.get("/r771-limited")
            statuses.add(response.status_code)
            response.close()
        self.assertEqual(statuses, {200, 429})


LOADER_HARNESS = r"""
const fs = require('fs');
const vm = require('vm');
const source = fs.readFileSync(__LOADER_PATH__, 'utf8');

function makeWindow() {
  const warns = [];
  const sandbox = {
    Promise,
    console: {
      debug() {}, log() {}, error() {}, info() {},
      warn(message, error) { warns.push(String(error && error.message ? error.message : error)); },
    },
    document: { createElement(tag) { return { tagName: String(tag) }; }, head: { appendChild() {} } },
  };
  sandbox.window = sandbox;
  sandbox.globalThis = sandbox;
  vm.createContext(sandbox);
  vm.runInContext(source, sandbox);
  return { win: sandbox, warns };
}

const idOf = (item) => item.id;

// Stands in for MathJax: rejects every call that includes an item named in `failing`.
function install(win, failing, withClear) {
  const calls = [];
  win.MathJax.typesetPromise = (items) => {
    calls.push(items.map(idOf));
    return items.some((item) => failing.includes(item.id))
      ? Promise.reject(new Error('cannot typeset ' + items.map(idOf).join(',')))
      : Promise.resolve();
  };
  if (withClear) win.MathJax.typesetClear = (items) => { calls.push(['clear'].concat(items.map(idOf))); };
  return calls;
}

const container = (id, spans) => ({
  id,
  querySelectorAll: (selector) => (selector === '.tex2jax_process' ? spans : []),
});

async function scenario(name, build) {
  const { win, warns } = makeWindow();
  const { calls, element, failing, withClear } = build(win);
  const installed = install(win, failing, withClear !== false);
  let outcome = 'resolved';
  try {
    await win._mathJaxTypeset(element);
  } catch (error) {
    outcome = 'rejected: ' + error.message;
  }
  return [name, { calls: installed, warns, outcome }];
}

(async () => {
  const s1 = { id: 's1' }, s2 = { id: 's2' }, s3 = { id: 's3' };
  const results = Object.fromEntries(await Promise.all([
    scenario('allGood', () => ({ element: container('ok', [s1, s2]), failing: [] })),
    scenario('oneBad', () => ({ element: container('msg', [s1, s2, s3]), failing: ['msg', 's2'] })),
    scenario('wholeFailsPartsFine', () => ({ element: container('msg', [s1, s2]), failing: ['msg'] })),
    scenario('singleSpan', () => ({ element: container('only', [s1]), failing: ['only'] })),
    scenario('noSpans', () => ({ element: container('none', []), failing: ['none'] })),
    scenario('noQuerySelector', () => ({ element: { id: 'plain' }, failing: ['plain'] })),
    scenario('noTypesetClear', () => ({ element: container('msg', [s1, s2]), failing: ['msg'], withClear: false })),
  ]));
  process.stdout.write(JSON.stringify(results));
})().catch((error) => { console.error(error); process.exit(1); });
"""


@pytest.fixture(scope="module")
def loader_results() -> dict:
    if shutil.which("node") is None:
        pytest.skip("node runtime unavailable")
    script = LOADER_HARNESS.replace("__LOADER_PATH__", json.dumps(str(LOADER_JS)))
    proc = subprocess.run(
        ["node", "-e", textwrap.dedent(script)],
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 0, f"stdout={proc.stdout!r} stderr={proc.stderr!r}"
    return json.loads(proc.stdout)


def test_a_clean_message_is_typeset_in_one_call(loader_results: dict) -> None:
    assert loader_results["allGood"] == {
        "calls": [["ok"]],
        "warns": [],
        "outcome": "resolved",
    }


def test_a_failed_message_is_retried_one_formula_at_a_time(
    loader_results: dict,
) -> None:
    # The whole message fails, MathJax's half-built state for it is cleared, then
    # each formula gets its own attempt; only the one that still fails stays TeX.
    assert loader_results["oneBad"] == {
        "calls": [
            ["msg"],
            ["clear", "msg"],
            ["s1"],
            ["s2"],
            ["clear", "s2"],
            ["s3"],
        ],
        "warns": ["cannot typeset msg", "cannot typeset s2"],
        "outcome": "resolved",
    }
    assert loader_results["wholeFailsPartsFine"] == {
        "calls": [["msg"], ["clear", "msg"], ["s1"], ["s2"]],
        "warns": ["cannot typeset msg"],
        "outcome": "resolved",
    }


def test_retry_is_skipped_when_it_cannot_help_and_never_throws(
    loader_results: dict,
) -> None:
    for name, calls in (
        ("singleSpan", [["only"]]),
        ("noSpans", [["none"]]),
        ("noQuerySelector", [["plain"]]),
    ):
        assert loader_results[name]["calls"] == calls, name
        assert len(loader_results[name]["warns"]) == 1, name
        assert loader_results[name]["outcome"] == "resolved", name

    # Without typesetClear (a MathJax build that lacks it) the retries still run.
    assert loader_results["noTypesetClear"]["calls"] == [["msg"], ["s1"], ["s2"]]
    assert loader_results["noTypesetClear"]["outcome"] == "resolved"
