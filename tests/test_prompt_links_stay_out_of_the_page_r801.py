r"""R801 regression coverage: a link in the agent's message never takes the approval page away.

The Web UI renders the agent's message with marked and put every ``<a>`` it
produced into the page exactly as marked wrote it, so clicking one

* navigated the *approval page itself* to the link: ``[docs](https://...)``, a bare
  URL (GFM autolink) and the very common ``[app.py](src/app.py)`` all replaced the
  page in the same tab (the last one with the server's 404, because a relative
  reference can only ever resolve to the Web UI's own origin), and ``[x]()``, which
  marked renders as ``<a href="">``, reloaded the page. The task keeps waiting on the
  server but the typed-in feedback and the live view are gone, and in an installed
  PWA window there is no back button at all;
* left ``javascript:`` / ``data:`` destinations in the DOM as live links. The CSP
  stops them from running, but only by logging a violation per click, and only as
  long as the header reaches the page.

The VS Code webview already treats prompt links the way the page now does
(``sanitizePromptHtml``: ``target="_blank"`` and ``rel="noopener noreferrer"`` for web
links, no ``href`` for script schemes); the browser Web UI had none of it.

The policy, per ``href``:

* ``http:`` / ``https:`` (and protocol-relative ``//host``) open in a new tab with
  ``rel="noopener noreferrer"`` (the referrer would otherwise carry the Web UI's URL);
* ``#fragment``, ``mailto:`` and ``tel:`` are left alone: none of them replaces the page;
* everything else (a relative path, an empty ``href``, ``javascript:``, ``data:``,
  ``file:``, custom schemes, anything that only becomes a scheme after the browser
  strips tabs and spaces) is not a link at all: the anchor is replaced by its
  children, so the text stays, nothing is clickable, and nothing carries the link
  colour that would promise a click.
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
APP_JS = STATIC_JS / "app.js"
MULTI_TASK_JS = STATIC_JS / "multi_task.js"
MARKED_JS = STATIC_JS / "marked.js"
WEBVIEW_JS = REPO_ROOT / "packages" / "vscode" / "webview-ui.js"

needs_node = pytest.mark.skipif(
    shutil.which("node") is None, reason="node runtime unavailable"
)


def _extract_function(source: str, marker: str) -> str:
    start = source.find(marker)
    assert start != -1, f"Cannot find function marker: {marker}"
    open_brace = source.find("{", start)
    assert open_brace != -1, f"Cannot find opening brace for: {marker}"
    depth = 1
    index = open_brace + 1
    while index < len(source):
        char = source[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return source[start : index + 1]
        index += 1
    raise AssertionError(f"Unbalanced function body for: {marker}")


NEW_TAB = [
    "https://example.com/docs",
    "http://example.com/a?b=1&c=2#frag",
    "HTTPS://EXAMPLE.COM/UPPER",
    "//example.com/protocol-relative",
    "  https://example.com/padded  ",
    "https://example.com/with space",
]
LEFT_ALONE = [
    "#top",
    "#",
    "#a-b-c",
    "mailto:dev@example.com",
    "MAILTO:DEV@EXAMPLE.COM",
    "tel:+8613800000000",
]
NOT_A_LINK = [
    # a relative reference can only resolve to the Web UI's own origin
    "src/app.py",
    "./notes.md",
    "../notes.md",
    "/Users/me/project/src/app.py",
    "docs/",
    "?q=1",
    # an empty href is "this document": a click reloads the page
    "",
    "   ",
    # script and data destinations
    "javascript:alert(1)",
    "JaVaScRiPt:alert(1)",
    "  javascript:alert(1)",
    "java\tscript:alert(1)",
    "java\nscript:alert(1)",
    "\x01javascript:alert(1)",
    "data:text/html,<b>x</b>",
    "data:text/html;base64,PHNjcmlwdD5hbGVydCgxKTwvc2NyaXB0Pg==",
    "vbscript:msgbox(1)",
    # schemes the page cannot (or must not) open for the user
    "file:///etc/passwd",
    "blob:https://example.com/00000000-0000-0000-0000-000000000000",
    "about:blank",
    "vscode://file/Users/me/x.py:1",
    "ftp://example.com/x",
    "ws://example.com/socket",
    # a leading backslash pair is read as "//host" by browsers
    "\\\\evil.example\\share",
    "\\evil.example/path",
]

HARNESS = r"""
const vm = require('vm');
const fs = require('fs');

class TextNode {
  constructor(text) {
    this.nodeType = 3;
    this.textContent = text;
    this.parentNode = null;
  }
}

class Element {
  constructor(tag, attrs, children) {
    this.nodeType = 1;
    this.tagName = tag.toUpperCase();
    this.attrs = new Map(Object.entries(attrs || {}));
    this.childNodes = [];
    this.parentNode = null;
    for (const child of children || []) {
      this.appendChild(typeof child === 'string' ? new TextNode(child) : child);
    }
  }
  get firstChild() {
    return this.childNodes.length ? this.childNodes[0] : null;
  }
  getAttribute(name) {
    return this.attrs.has(name) ? this.attrs.get(name) : null;
  }
  setAttribute(name, value) {
    this.attrs.set(name, String(value));
  }
  removeAttribute(name) {
    this.attrs.delete(name);
  }
  appendChild(child) {
    if (child.parentNode) child.parentNode.removeChild(child);
    child.parentNode = this;
    this.childNodes.push(child);
    return child;
  }
  insertBefore(child, ref) {
    if (child.parentNode) child.parentNode.removeChild(child);
    const index = this.childNodes.indexOf(ref);
    if (index < 0) throw new Error('NotFoundError: reference node');
    child.parentNode = this;
    this.childNodes.splice(index, 0, child);
    return child;
  }
  removeChild(child) {
    const index = this.childNodes.indexOf(child);
    if (index < 0) throw new Error('NotFoundError: child');
    this.childNodes.splice(index, 1);
    child.parentNode = null;
    return child;
  }
  querySelectorAll(selector) {
    if (selector !== 'a[href]' && selector !== 'a') {
      throw new Error('fake DOM: unsupported selector ' + selector);
    }
    const found = [];
    const walk = (node) => {
      for (const child of node.childNodes) {
        if (child.nodeType !== 1) continue;
        if (
          child.tagName === 'A' &&
          (selector === 'a' || child.attrs.has('href'))
        ) {
          found.push(child);
        }
        walk(child);
      }
    };
    walk(this);
    return found;
  }
}

function serialize(node) {
  if (node.nodeType === 3) return node.textContent;
  const attrs = Array.from(node.attrs.entries())
    .map(([k, v]) => ' ' + k + '=' + JSON.stringify(v))
    .join('');
  return (
    '<' + node.tagName.toLowerCase() + attrs + '>' +
    node.childNodes.map(serialize).join('') +
    '</' + node.tagName.toLowerCase() + '>'
  );
}

function anchorsOf(container) {
  return container.querySelectorAll('a').map((a) => ({
    href: a.getAttribute('href'),
    target: a.getAttribute('target'),
    rel: a.getAttribute('rel'),
    text: a.childNodes.map(serialize).join(''),
  }));
}

const sandbox = vm.createContext({ Number, String, Array, RegExp, Object });
vm.runInContext(
  process.env.R801_SOURCE + '\nthis.processLinks = processLinks;',
  sandbox,
);

function run(hrefs, markup) {
  const results = [];
  for (const href of hrefs) {
    const anchor = new Element('a', { href }, [
      'label ',
      new Element('em', {}, ['inner']),
    ]);
    const container = new Element('p', {}, [
      'before ',
      anchor,
      ' after',
    ]);
    sandbox.processLinks(container);
    const once = serialize(container);
    sandbox.processLinks(container);
    results.push({
      href,
      anchors: anchorsOf(container),
      html: once,
      idempotent: serialize(container) === once,
    });
  }
  return results;
}

const out = JSON.parse(process.env.R801_CASES);
const payload = { plain: run(out.hrefs) };

// shape checks that need more than one anchor / unusual containers
{
  const a1 = new Element('a', { href: 'src/a.py' }, ['one']);
  const a2 = new Element('a', { href: 'https://example.com/b' }, ['two']);
  const a3 = new Element('a', { href: 'javascript:x' }, [
    new Element('img', { src: 'p.png' }, []),
  ]);
  const a4 = new Element('a', {}, ['no href at all']);
  const container = new Element('div', {}, [
    'x ', a1, ' y ', a2, ' z ', a3, ' w ', a4,
  ]);
  sandbox.processLinks(container);
  payload.mixed = serialize(container);
}
{
  const threw = [];
  for (const value of [null, undefined, {}, 42]) {
    try {
      sandbox.processLinks(value);
      threw.push(false);
    } catch (e) {
      threw.push(String(e && e.message));
    }
  }
  payload.nonContainers = threw;
}

if (process.env.R801_MARKED) {
  const msandbox = vm.createContext({});
  vm.runInContext(fs.readFileSync(process.env.R801_MARKED, 'utf8'), msandbox);
  const marked = msandbox.marked;
  marked.use({ renderer: { html() { return ''; } } });
  marked.setOptions({ mangle: false, headerIds: false });
  const decode = (s) => s.replace(/&amp;/g, '&').replace(/&quot;/g, '"');
  payload.marked = Object.entries(out.markdown).map(([md]) => {
    const html = marked.parse(md);
    const hrefs = Array.from(html.matchAll(/<a href="([^"]*)"/g)).map((m) =>
      decode(m[1]),
    );
    const container = new Element(
      'p',
      {},
      hrefs.flatMap((href, i) => [
        new Element('a', { href }, ['link' + i]),
        ' ',
      ]),
    );
    sandbox.processLinks(container);
    return { md, hrefs, anchors: anchorsOf(container), html: serialize(container) };
  });
}
process.stdout.write(JSON.stringify(payload));
"""

MARKDOWN = {
    "[docs](https://example.com/docs)": "new-tab",
    "see https://example.com/page now": "new-tab",
    "<https://example.com/x>": "new-tab",
    "www.example.com": "new-tab",
    "[amp](https://example.com/?a=1&b=2)": "new-tab",
    "[ref][1]\n\n[1]: https://example.com/ref": "new-tab",
    "[![img](https://example.com/i.png)](https://example.com/x)": "new-tab",
    "[u](//example.com/x)": "new-tab",
    "[m](mailto:dev@example.com)": "left-alone",
    "dev@example.com": "left-alone",
    "[t](#top)": "left-alone",
    "[f](src/app.py)": "not-a-link",
    "[f](/abs/app.py)": "not-a-link",
    "[q](?q=1)": "not-a-link",
    "[x]()": "not-a-link",
    "[x](<>)": "not-a-link",
    "[j](javascript:alert(1))": "not-a-link",
    "[j](JaVaScRiPt:alert(1))": "not-a-link",
    "[d](data:text/html,x)": "not-a-link",
    "[v](vscode://file/x.py:1)": "not-a-link",
}


@lru_cache(maxsize=1)
def _run() -> dict:
    source = APP_JS.read_text(encoding="utf-8")
    function_source = "\n".join(
        _extract_function(source, marker)
        for marker in ("function classifyPromptLink(", "function processLinks(")
    )
    cases = {
        "hrefs": [*NEW_TAB, *LEFT_ALONE, *NOT_A_LINK],
        "markdown": MARKDOWN,
    }
    env = {
        **os.environ,
        "R801_SOURCE": function_source,
        "R801_CASES": json.dumps(cases),
        "R801_MARKED": str(MARKED_JS),
    }
    proc = subprocess.run(
        ["node", "-e", HARNESS],
        env=env,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.returncode == 0, f"stdout={proc.stdout!r}\nstderr={proc.stderr!r}"
    return json.loads(proc.stdout)


def _by_href(href: str) -> dict:
    for entry in _run()["plain"]:
        if entry["href"] == href:
            return entry
    raise AssertionError(f"no result for {href!r}")


# ---------------------------------------------------------------------------
# the policy, on hand-written hrefs
# ---------------------------------------------------------------------------


@needs_node
@pytest.mark.parametrize("href", NEW_TAB)
def test_web_links_open_in_a_new_tab_without_opener_or_referrer(href: str) -> None:
    entry = _by_href(href)

    assert len(entry["anchors"]) == 1, entry
    anchor = entry["anchors"][0]
    assert anchor["href"] == href, "the destination itself is never rewritten"
    assert anchor["target"] == "_blank", entry
    assert anchor["rel"] == "noopener noreferrer", entry
    assert "label <em>inner</em>" in anchor["text"], entry


@needs_node
@pytest.mark.parametrize("href", LEFT_ALONE)
def test_links_that_do_not_replace_the_page_are_left_alone(href: str) -> None:
    entry = _by_href(href)

    assert len(entry["anchors"]) == 1, entry
    anchor = entry["anchors"][0]
    assert anchor["href"] == href
    assert anchor["target"] is None, "an in-page jump must not open a tab"
    assert anchor["rel"] is None
    assert "label <em>inner</em>" in anchor["text"]


@needs_node
@pytest.mark.parametrize("href", NOT_A_LINK)
def test_everything_else_is_text_not_a_link(href: str) -> None:
    entry = _by_href(href)

    assert entry["anchors"] == [], f"{href!r} must not stay clickable: {entry['html']}"
    # the text survives, in place, with the nested element intact
    assert entry["html"] == "<p>before label <em>inner</em> after</p>", entry["html"]


@needs_node
def test_every_outcome_is_stable_when_applied_twice() -> None:
    # the description element is re-rendered and re-processed; a second pass must be a no-op
    unstable = [e["href"] for e in _run()["plain"] if not e["idempotent"]]
    assert unstable == []


@needs_node
def test_mixed_content_keeps_order_images_and_untouched_anchors() -> None:
    html = _run()["mixed"]

    assert html == (
        '<div>x one y <a href="https://example.com/b" target="_blank" '
        'rel="noopener noreferrer">two</a> z <img src="p.png"></img> w '
        "<a>no href at all</a></div>"
    ), html


@needs_node
def test_a_missing_or_odd_container_is_not_an_error() -> None:
    # same contract as processStrikethrough({}): render helpers never take the page down
    assert _run()["nonContainers"] == [False, False, False, False]


# ---------------------------------------------------------------------------
# what marked really emits, through the same policy
# ---------------------------------------------------------------------------


@needs_node
@pytest.mark.parametrize("markdown", sorted(MARKDOWN))
def test_vendored_marked_output_ends_up_with_the_expected_policy(
    markdown: str,
) -> None:
    entry = next(e for e in _run()["marked"] if e["md"] == markdown)
    expected = MARKDOWN[markdown]

    assert entry["hrefs"], f"marked produced no link for {markdown!r}"
    anchors = entry["anchors"]
    if expected == "new-tab":
        assert len(anchors) == len(entry["hrefs"]), entry
        assert all(
            a["target"] == "_blank" and a["rel"] == "noopener noreferrer"
            for a in anchors
        ), entry
    elif expected == "left-alone":
        assert len(anchors) == len(entry["hrefs"]), entry
        assert all(a["target"] is None for a in anchors), entry
    else:
        assert anchors == [], entry


@needs_node
def test_marked_itself_does_not_filter_these_destinations() -> None:
    # documents why the page has to: marked hands every one of these to the DOM
    by_md = {e["md"]: e["hrefs"] for e in _run()["marked"]}

    assert by_md["[j](javascript:alert(1))"] == ["javascript:alert(1)"]
    assert by_md["[d](data:text/html,x)"] == ["data:text/html,x"]
    assert by_md["[x]()"] == [""]
    assert by_md["[f](src/app.py)"] == ["src/app.py"]


# ---------------------------------------------------------------------------
# wiring: both places that paint the message, and the other client
# ---------------------------------------------------------------------------


def test_the_first_paint_runs_the_link_policy_before_math_typesetting() -> None:
    body = _extract_function(
        APP_JS.read_text(encoding="utf-8"), "function renderMarkdownContent("
    )

    assert "processLinks(element)" in body
    assert body.index("processLinks(element)") < body.index("loadMathJaxIfNeeded")


def test_the_multi_task_paint_runs_the_link_policy_before_math_typesetting() -> None:
    body = _extract_function(
        MULTI_TASK_JS.read_text(encoding="utf-8"),
        "async function updateDescriptionDisplay(",
    )

    assert "processLinks(descriptionElement)" in body
    assert body.index("processLinks(descriptionElement)") < body.index(
        "loadMathJaxIfNeeded"
    )


def test_no_other_script_turns_markdown_into_dom() -> None:
    # a third renderer would need the policy too; fail loudly so it gets one
    offenders = sorted(
        path.name
        for path in STATIC_JS.glob("*.js")
        if not path.name.endswith(".min.js")
        and path.name not in {"marked.js", "tex-mml-chtml.js", "lottie.min.js"}
        and "marked.parse(" in path.read_text(encoding="utf-8")
    )

    assert offenders == ["app.js", "multi_task.js"]


def test_both_clients_open_prompt_links_the_same_way() -> None:
    web = _extract_function(
        APP_JS.read_text(encoding="utf-8"), "function processLinks("
    )
    webview = _extract_function(
        WEBVIEW_JS.read_text(encoding="utf-8"), "function sanitizePromptHtml("
    )

    for body in (web, webview):
        assert re.search(r"""['"]target['"],\s*['"]_blank['"]""", body)
        assert re.search(r"""['"]rel['"],\s*['"]noopener noreferrer['"]""", body)
