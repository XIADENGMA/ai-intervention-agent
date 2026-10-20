r"""R802 regression coverage: a formula cannot link, restyle or re-id the approval page.

R771 shipped every TeX extension MathJax can autoload, and that made two things work
for the first time (before, the download was a 404 and the formula stayed raw TeX):

* the ``html`` extension: ``\href``, ``\class``, ``\style`` and ``\cssId``;
* the CSS option of ``\bbox[...]``.

Measured in headless Chrome 153 against the real page, a message could then

* take over an element id of the page: ``$\cssId{submit-btn}{x}$`` made
  ``document.getElementById('submit-btn')`` return the math element instead of the
  button, and ``\cssId{feedback-text}`` did the same for the textarea (DOM clobbering
  of a page whose scripts look elements up by id);
* cover the whole page, Submit button included, with text of the sender's choosing:
  ``$\style{position:fixed;inset:0;width:100vw;height:100vh;background:#fff;
  z-index:99999}{\text{Session expired}}$`` and the same CSS through ``\bbox[...]``;
* put a live link into the page after the Markdown link policy (R801) had run:
  ``$\href{https://...}{Approve all}$`` replaced the page in its own tab,
  ``$\href{javascript:...}{x}$`` was a live ``javascript:`` anchor (only the CSP kept it
  from running);
* put any class of the page's stylesheet on a math element (``\class{...}``).

No agent message needs any of it: Markdown has links, and the colour, cancel and
chemistry macros stay. So the loader's MathJax configuration

* registers none of those macros for autoload (they are undefined control sequences and
  show as text), and
* makes ``\require`` refuse both extensions (``Extension "[tex]/html" is not allowed to
  be loaded``),

and the two files are not shipped, so a configuration regression ends as a 404 for the
one formula (R771 retries a failed message formula by formula) instead of as control
over the page.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from functools import lru_cache
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
STATIC_JS = REPO_ROOT / "src" / "ai_intervention_agent" / "static" / "js"
BUNDLE_JS = STATIC_JS / "tex-mml-chtml.js"
EXTENSIONS_DIR = STATIC_JS / "input" / "tex" / "extensions"
LOADERS = [STATIC_JS / "mathjax-loader.js", STATIC_JS / "mathjax-loader.min.js"]

HELD_BACK = {"html", "bbox"}
# Every extension the page ships, each reviewed against one question: can the sender
# make it set an attribute of his choosing (href, id, class, style, data-*), or load code?
REVIEWED = {
    "action",  # \toggle, \mathtip, \texttip: tooltips and toggling, no attributes
    "amscd",  # CD environment
    "boldsymbol",
    "braket",
    "bussproofs",
    "cancel",
    "color",  # colour names / hex only
    "enclose",  # notation names, mathcolor / mathbackground colours
    "extpfeil",
    "mhchem",
    "unicode",  # a code point; the font option is not reachable from the macro
    "verb",
}

needs_node = pytest.mark.skipif(
    shutil.which("node") is None, reason="node runtime unavailable"
)

HARNESS = r"""
const fs = require('fs');
const vm = require('vm');

const out = {};
for (const path of JSON.parse(process.env.R802_LOADERS)) {
  const sandbox = {
    Promise,
    console: { debug() {}, log() {}, error() {}, info() {}, warn() {} },
    document: { createElement(tag) { return { tagName: String(tag) }; }, head: { appendChild() {} } },
  };
  sandbox.window = sandbox;
  sandbox.globalThis = sandbox;
  vm.createContext(sandbox);
  vm.runInContext(fs.readFileSync(path, 'utf8'), sandbox);
  out[path] = JSON.parse(JSON.stringify(sandbox.MathJax.tex));
}
process.stdout.write(JSON.stringify(out));
"""


@lru_cache(maxsize=1)
def _loader_tex_configs() -> dict[str, dict]:
    proc = subprocess.run(
        ["node", "-e", HARNESS],
        env={**os.environ, "R802_LOADERS": json.dumps([str(p) for p in LOADERS])},
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.returncode == 0, f"stdout={proc.stdout!r}\nstderr={proc.stderr!r}"
    return json.loads(proc.stdout)


def _macros_and_environments(entry: list) -> tuple[list, list]:
    # How the bundle reads an autoload entry: [macros] or [[macros], [environments]]
    if len(entry) == 2 and isinstance(entry[0], list):
        return entry[0], entry[1]
    return entry, []


def _bundle_autoload_table() -> dict[str, list[str]]:
    source = BUNDLE_JS.read_text(encoding="utf-8")
    match = re.search(r"autoload:\(0,[\w$]+\.expandable\)\(\{([^{}]*)\}\)", source)
    assert match, "cannot find the autoload table in tex-mml-chtml.js"
    table: dict[str, list[str]] = {}
    for name, body in re.findall(
        r"([A-Za-z]+):\[(.*?)\](?=,[A-Za-z]+:|$)", match.group(1)
    ):
        table[name] = re.findall(r'"([^"]+)"', body)
    return table


@needs_node
@pytest.mark.parametrize("loader", LOADERS, ids=lambda p: p.name)
def test_autoload_registers_no_macro_of_the_page_controlling_extensions(
    loader: Path,
) -> None:
    autoload = _loader_tex_configs()[str(loader)].get("autoload", {})

    assert set(autoload) == HELD_BACK, autoload
    for name in HELD_BACK:
        macros, environments = _macros_and_environments(autoload[name])
        assert macros == [] and environments == [], (name, autoload[name])


@needs_node
@pytest.mark.parametrize("loader", LOADERS, ids=lambda p: p.name)
def test_require_refuses_the_page_controlling_extensions(loader: Path) -> None:
    require = _loader_tex_configs()[str(loader)].get("require", {})
    allow = require.get("allow", {})

    for name in HELD_BACK:
        assert allow.get(name) is False, (name, allow)
    # the rest of \require keeps working as before (the default allows)
    assert require.get("defaultAllow", True) is True, require


def test_the_bundle_still_names_what_the_configuration_switches_off() -> None:
    # The configuration overrides entries of the bundle's own autoload table. If a MathJax
    # upgrade renames or splits them, the override silently stops covering the macros.
    table = _bundle_autoload_table()

    assert set(table) >= HELD_BACK | REVIEWED, sorted(table)
    assert set(table["html"]) == {"href", "class", "style", "cssId"}, table["html"]
    assert table["bbox"] == ["bbox"], table["bbox"]


def test_the_page_controlling_extensions_are_not_shipped() -> None:
    leftovers = sorted(
        path.name for name in HELD_BACK for path in EXTENSIONS_DIR.glob(f"{name}.js*")
    )

    assert leftovers == [], (
        f"{leftovers}: with these files present, a configuration slip is control "
        "over the page; without them it is a 404 for one formula"
    )


def test_shipped_extensions_are_exactly_the_reviewed_ones() -> None:
    shipped = {
        path.name.removesuffix(".br").removesuffix(".gz").removesuffix(".js")
        for path in EXTENSIONS_DIR.iterdir()
    }

    assert shipped == REVIEWED, (
        f"new: {sorted(shipped - REVIEWED)}, gone: {sorted(REVIEWED - shipped)}. "
        "Before adding an extension to REVIEWED, read it for a macro that lets the "
        "sender choose an href, id, class, style or data attribute, or load code; if "
        "it has one, switch the macro off in mathjax-loader.js instead of shipping it."
    )
