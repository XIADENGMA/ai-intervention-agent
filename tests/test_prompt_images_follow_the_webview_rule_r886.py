r"""R886: the images in the agent's message follow the same rule in the browser Web UI and in the VS Code webview.

The VS Code webview sanitises the rendered message (``sanitizePromptHtml``): for an ``<img>`` its
``normalizeUrl(url, 'img')`` keeps an in-page ``#`` reference, ``data:image/*``, a same-origin path
and whatever the URL parser reads as http(s), and removes the image otherwise.  The browser Web UI
had a policy for the *links* of the message (R801, ``classifyPromptLink`` / ``processLinks``, whose
comment says "same policy as the VS Code webview") and none for the images: ``marked`` hands every
``![alt](src)`` destination to the DOM unchanged, so ``![img](javascript:...)`` stayed in the page
as ``<img src="javascript:...">`` (seen in a real Chromium: the CSP refused it and logged a
violation, and nothing ran; the same page holds that no script-bearing payload of a 28-payload run
executed).  Nothing here was exploitable; what was missing is that the two clients, which render the
same message, did not agree on what an image may point to, and the comment said they did.

``processPromptImages`` (next to ``processLinks``, called at the same two places) now gives the page
the webview's decision for every image.  A dropped image leaves its alt text where it was, as a dropped
link leaves its label.

The tests:

* run the *real* ``classifyPromptImage`` from ``app.js`` and the *real* ``normalizeUrl`` cut out of
  ``packages/vscode/webview-ui.js`` over the same 200-odd destinations (every scheme the policy has an
  opinion about, each with the spellings a browser reads as the same thing: upper case, a tab or a
  newline inside the scheme, a leading control character or no-break space, backslashes), and require
  the same keep / drop decision for each, so the two cannot drift apart;
* hold the hand-written decisions on their own, so that both being wrong in the same way would show;
* run the page function over a small DOM: what stays, what leaves, what is left behind (as a text
  node, never as markup), and that a second pass changes nothing;
* push the audit's payloads, and more, through the vendored ``marked`` the page uses and check the
  ``<img>`` that comes out: it has the attributes ``marked`` writes and no others, and ends up kept
  or dropped as expected;
* check that both places that paint the message call it, before the maths is typeset.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from functools import lru_cache
from pathlib import Path
from typing import Any

import pytest

from tests.test_prompt_links_stay_out_of_the_page_r801 import _extract_function

REPO_ROOT = Path(__file__).resolve().parent.parent
STATIC_JS = REPO_ROOT / "src" / "ai_intervention_agent" / "static" / "js"
APP_JS = STATIC_JS / "app.js"
MULTI_TASK_JS = STATIC_JS / "multi_task.js"
MARKED_JS = STATIC_JS / "marked.js"
WEBVIEW_JS = REPO_ROOT / "packages" / "vscode" / "webview-ui.js"

needs_node = pytest.mark.skipif(
    shutil.which("node") is None, reason="node runtime unavailable"
)

KEEP = [
    "https://example.com/a.png",
    "http://example.com/a.png?x=1&y=2#frag",
    "HTTPS://EXAMPLE.COM/A.PNG",
    "//cdn.example.com/a.png",
    "  https://example.com/padded.png  ",
    "https://example.com/with space.png",
    "https://user:pw@example.com/a.png",
    # the page's own origin: an uploaded or generated image the server hands out
    "/api/local-image?path=a.png",
    "/static/a.png",
    "a.png",
    "./a.png",
    "../a.png",
    # an inline image
    "data:image/png;base64,iVBORw0KGgo=",
    "DATA:IMAGE/PNG;base64,AAAA",
    "  data:image/gif;base64,R0lGODlh",
    "data:image/svg+xml;base64,PHN2ZyBvbmxvYWQ9IndpbmRvdy5fX3hzcz0yMDAiIHhtbG5zPSJodHRwOi8vd3d3LnczLm9yZy8yMDAwL3N2ZyI+PC9zdmc+",
    "#top",
]
DROP = [
    "",
    "   ",
    "\t\n",
    "javascript:alert(1)",
    "javascript:window.__xss=9",
    "JaVaScRiPt:alert(1)",
    "  javascript:alert(1)",
    "java\tscript:alert(1)",
    "java\nscript:alert(1)",
    "\x01javascript:alert(1)",
    "\u00a0javascript:alert(1)",
    "vbscript:msgbox(1)",
    "VBSCRIPT:msgbox(1)",
    "data:text/html,<b>x</b>",
    "data:text/html;base64,PHNjcmlwdD5hbGVydCgxKTwvc2NyaXB0Pg==",
    "data:application/javascript,alert(1)",
    "data:,hello",
    "file:///etc/passwd",
    "blob:https://example.com/00000000-0000-0000-0000-000000000000",
    "about:blank",
    "ftp://example.com/a.png",
    "ws://example.com/a.png",
    "vscode://file/Users/me/x.py:1",
    "chrome-extension://abcdef/a.png",
    "view-source:https://example.com/",
    "mailto:dev@example.com",
    "tel:+8613800000000",
    "x:y",
    # the URL parser refuses these outright (no host, a space in the host, a bracket never closed)
    "http://",
    "https://[::1",
    "http://exa mple.com/a.png",
]

# every scheme the policy has an opinion about, in the spellings a browser reads the same way
_BASES = [
    "javascript:alert(1)",
    "vbscript:msgbox(1)",
    "data:image/png;base64,AAAA",
    "data:image/svg+xml,%3Csvg/%3E",
    "data:text/html,x",
    "file:///etc/passwd",
    "blob:https://example.com/x",
    "ftp://example.com/a.png",
    "https://example.com/a.png",
    "http://example.com/a.png",
    "//example.com/a.png",
    "/local/a.png",
    "a.png",
    "#top",
    "mailto:a@b.c",
    "about:blank",
    "x:y",
]
_SPELLINGS = [
    lambda s: s,
    lambda s: s.upper(),
    lambda s: " " + s,
    lambda s: s + " ",
    lambda s: "\t" + s,
    lambda s: "\n" + s,
    lambda s: "\x01" + s,
    lambda s: "\u00a0" + s,
    lambda s: "\ufeff" + s,
    lambda s: s.replace(":", "\t:", 1),
    lambda s: s[:2] + "\n" + s[2:],
    lambda s: s.replace("/", "\\"),
]
CORPUS = sorted(
    {*KEEP, *DROP, *(spell(base) for base in _BASES for spell in _SPELLINGS)}
    # a leading "/" is taken as a path before the URL parser sees it, whatever follows
    | {"/\\:", "/\\", "/\t/evil.example/a.png"}
)

DOM_CASES = {
    "keeps a web image": ("https://example.com/a.png", "the diagram"),
    "keeps a data image": ("data:image/png;base64,AAAA", "pixel"),
    "keeps a relative image": ("a.png", "local"),
    "drops javascript": ("javascript:alert(1)", "the diagram"),
    "drops an obfuscated javascript": ("java\tscript:alert(1)", "the diagram"),
    "drops a file url": ("file:///etc/passwd", "secret"),
    "drops a blob url": ("blob:https://example.com/x", "blob"),
    "drops an empty source": ("", "nothing"),
    "drops with no alt text": ("javascript:alert(1)", None),
    "drops with an empty alt text": ("javascript:alert(1)", ""),
    "turns markup in the alt text into text": (
        "javascript:alert(1)",
        "<img src=x onerror=alert(1)>",
    ),
}

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
  getAttribute(name) {
    return this.attrs.has(name) ? this.attrs.get(name) : null;
  }
  setAttribute(name, value) {
    this.attrs.set(name, String(value));
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
    if (selector !== 'img[src]') {
      throw new Error('fake DOM: unsupported selector ' + selector);
    }
    const found = [];
    const walk = (node) => {
      for (const child of node.childNodes) {
        if (child.nodeType !== 1) continue;
        if (child.tagName === 'IMG' && child.attrs.has('src')) found.push(child);
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

function kinds(container) {
  return container.childNodes.map((n) => (n.nodeType === 3 ? 'text' : n.tagName.toLowerCase()));
}

const ORIGIN = 'http://127.0.0.1:8081';
const page = vm.createContext({
  Number, String, Array, RegExp, Object, URL,
  window: { location: { href: ORIGIN + '/' } },
  document: { createTextNode: (text) => new TextNode(text) },
});
vm.runInContext(
  process.env.R886_PAGE + '\nthis.classifyPromptImage = classifyPromptImage;' +
  '\nthis.processPromptImages = processPromptImages;',
  page,
);
const webview = vm.createContext({ String, URL, SERVER_URL: ORIGIN });
vm.runInContext(process.env.R886_WEBVIEW + '\nthis.normalizeUrl = normalizeUrl;', webview);

const cases = JSON.parse(process.env.R886_CASES);
const payload = {};

payload.decisions = cases.corpus.map((src) => ({
  src,
  page: page.classifyPromptImage(src),
  webview: webview.normalizeUrl(src, 'img') ? 'keep' : 'drop',
}));

payload.nonStrings = [null, undefined, 42, {}, []].map((value) => ({
  page: page.classifyPromptImage(value),
  webview: webview.normalizeUrl(value, 'img') ? 'keep' : 'drop',
}));

payload.dom = Object.entries(cases.dom).map(([name, [src, alt]]) => {
  const attrs = { src };
  if (alt !== null) attrs.alt = alt;
  const img = new Element('img', attrs, []);
  const container = new Element('p', {}, ['before ', img, ' after']);
  page.processPromptImages(container);
  const once = serialize(container);
  const kindsOnce = kinds(container);
  page.processPromptImages(container);
  return {
    name,
    html: once,
    kinds: kindsOnce,
    texts: container.childNodes.filter((n) => n.nodeType === 3).map((n) => n.textContent),
    idempotent: serialize(container) === once,
  };
});

{
  // an image inside a link (a badge), a kept one next to a dropped one, an image with no src,
  // and an image whose source was dropped inside nested markup
  const badge = new Element('img', { src: 'javascript:x', alt: 'badge' }, []);
  const link = new Element('a', { href: 'https://example.com/x' }, [badge]);
  const kept = new Element('img', { src: 'https://example.com/ok.png', alt: 'ok' }, []);
  const bad = new Element('img', { src: 'file:///etc/passwd', alt: 'bad' }, []);
  const noSrc = new Element('img', { alt: 'no source at all' }, []);
  const nested = new Element('em', {}, [
    new Element('img', { src: 'vbscript:x', alt: 'deep' }, []),
  ]);
  const container = new Element('div', {}, [
    'a ', link, ' b ', kept, ' c ', bad, ' d ', noSrc, ' e ', nested, ' f',
  ]);
  page.processPromptImages(container);
  payload.mixed = serialize(container);
}

{
  const threw = [];
  for (const value of [null, undefined, {}, 42]) {
    try {
      page.processPromptImages(value);
      threw.push(false);
    } catch (e) {
      threw.push(String(e && e.message));
    }
  }
  payload.nonContainers = threw;
}

if (process.env.R886_MARKED) {
  const msandbox = vm.createContext({});
  vm.runInContext(fs.readFileSync(process.env.R886_MARKED, 'utf8'), msandbox);
  const marked = msandbox.marked;
  marked.use({ renderer: { html() { return ''; } } });
  marked.setOptions({ mangle: false, headerIds: false });
  const decode = (s) =>
    s.replace(/&quot;/g, '"').replace(/&#39;/g, "'").replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&amp;/g, '&');
  payload.marked = Object.keys(cases.markdown).map((md) => {
    const html = marked.parse(md);
    const tags = Array.from(html.matchAll(/<img\b[^>]*>/g)).map((m) => m[0]);
    const elements = tags.map((tag) => {
      const attrs = {};
      for (const m of tag.matchAll(/\s([a-z-]+)="([^"]*)"/g)) attrs[m[1]] = decode(m[2]);
      return new Element('img', attrs, []);
    });
    const container = new Element('p', {}, elements.flatMap((el) => [el, ' ']));
    page.processPromptImages(container);
    return {
      md,
      tags,
      attrNames: elements.map((el) => Array.from(el.attrs.keys())),
      left: container.querySelectorAll('img[src]').map((img) => img.getAttribute('src')),
      text: container.childNodes.filter((n) => n.nodeType === 3).map((n) => n.textContent).join(''),
    };
  });
}
process.stdout.write(JSON.stringify(payload));
"""

MARKDOWN = {
    # the payloads the audit pushed through the page, and the ordinary cases
    "![img](javascript:window.__xss=9)": "drop",
    # a quote in the destination does not open an attribute: marked does not even read it as an image
    '![onerr](x" onerror="window.__xss=10)': "none",
    "![svg](data:image/svg+xml;base64,PHN2ZyBvbmxvYWQ9IndpbmRvdy5fX3hzcz0yMDAiIHhtbG5zPSJodHRwOi8vd3d3LnczLm9yZy8yMDAwL3N2ZyI+PC9zdmc+)": "keep",
    "![img](JaVaScRiPt:alert(1))": "drop",
    "![img](vbscript:msgbox(1))": "drop",
    "![img](data:text/html,x)": "drop",
    "![img](file:///etc/passwd)": "drop",
    "![img](blob:https://example.com/abc)": "drop",
    "![img](ftp://example.com/a.png)": "drop",
    "![](javascript:alert(1))": "drop",
    "![ref][1]\n\n[1]: javascript:alert(1)": "drop",
    "[![badge](javascript:alert(1))](https://example.com)": "drop",
    "![img](https://example.com/a.png)": "keep",
    "![img](https://example.com/a.png 'a title')": "keep",
    "![img](/api/local-image?path=a.png)": "keep",
    "![img](a.png)": "keep",
    "![img](data:image/png;base64,AAAA)": "keep",
    "[![badge](https://example.com/b.svg)](https://example.com)": "keep",
}


@lru_cache(maxsize=1)
def _run() -> dict[str, Any]:
    page_source = "\n".join(
        _extract_function(APP_JS.read_text(encoding="utf-8"), marker)
        for marker in ("function classifyPromptImage(", "function processPromptImages(")
    )
    webview_source = _extract_function(
        WEBVIEW_JS.read_text(encoding="utf-8"), "function normalizeUrl("
    )
    cases = {"corpus": CORPUS, "dom": DOM_CASES, "markdown": MARKDOWN}
    env = {
        **os.environ,
        "R886_PAGE": page_source,
        "R886_WEBVIEW": webview_source,
        "R886_CASES": json.dumps(cases),
        "R886_MARKED": str(MARKED_JS),
    }
    proc = subprocess.run(
        ["node", "-e", HARNESS],
        env=env,
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 0, f"stdout={proc.stdout!r}\nstderr={proc.stderr!r}"
    parsed: dict[str, Any] = json.loads(proc.stdout)
    return parsed


def _decision(src: str) -> dict[str, str]:
    for entry in _run()["decisions"]:
        if entry["src"] == src:
            return entry  # type: ignore[no-any-return]
    raise AssertionError(f"no result for {src!r}")


# ---------------------------------------------------------------------------
# the rule, on hand-written destinations
# ---------------------------------------------------------------------------


@needs_node
@pytest.mark.parametrize("src", KEEP)
def test_these_destinations_stay_in_the_page(src: str) -> None:
    entry = _decision(src)
    assert entry["page"] == "keep", entry
    assert entry["webview"] == "keep", entry


@needs_node
@pytest.mark.parametrize("src", DROP)
def test_these_destinations_never_stay_in_the_page(src: str) -> None:
    entry = _decision(src)
    assert entry["page"] == "drop", entry
    assert entry["webview"] == "drop", entry


@needs_node
def test_a_source_that_is_not_text_is_dropped() -> None:
    assert _run()["nonStrings"] == [{"page": "drop", "webview": "drop"}] * 5


# ---------------------------------------------------------------------------
# the two clients, decision for decision
# ---------------------------------------------------------------------------


@needs_node
def test_the_corpus_is_big_enough_to_mean_something() -> None:
    assert len(CORPUS) > 200
    decisions = {entry["page"] for entry in _run()["decisions"]}
    assert decisions == {"keep", "drop"}


@needs_node
def test_the_page_and_the_webview_decide_the_same_for_every_destination() -> None:
    different = [
        (entry["src"], entry["page"], entry["webview"])
        for entry in _run()["decisions"]
        if entry["page"] != entry["webview"]
    ]
    assert different == [], (
        f"the two clients disagree on {len(different)} sources: {different[:5]}"
    )


# ---------------------------------------------------------------------------
# what the page does to an image
# ---------------------------------------------------------------------------


def _dom(name: str) -> dict[str, Any]:
    return next(e for e in _run()["dom"] if e["name"] == name)  # type: ignore[no-any-return]


@needs_node
@pytest.mark.parametrize("name", [n for n in DOM_CASES if n.startswith("keeps")])
def test_a_kept_image_is_left_exactly_as_marked_wrote_it(name: str) -> None:
    src, alt = DOM_CASES[name]
    entry = _dom(name)
    assert entry["kinds"] == ["text", "img", "text"], entry
    assert f"src={json.dumps(src)}" in entry["html"], entry
    assert entry["html"].count("<img") == 1, entry
    assert entry["idempotent"], entry


@needs_node
@pytest.mark.parametrize(
    "name",
    [n for n in DOM_CASES if n.startswith("drops") and "alt" not in n],
)
def test_a_dropped_image_leaves_its_alt_text_in_place(name: str) -> None:
    _, alt = DOM_CASES[name]
    entry = _dom(name)
    assert "<img" not in entry["html"], entry
    # before / alt / after are three text nodes in that order: the sentence still reads
    assert entry["html"] == f"<p>before {alt} after</p>", entry
    assert entry["idempotent"], entry


@needs_node
@pytest.mark.parametrize(
    "name", ["drops with no alt text", "drops with an empty alt text"]
)
def test_a_dropped_image_without_alt_text_leaves_nothing(name: str) -> None:
    entry = _dom(name)
    assert entry["html"] == "<p>before  after</p>", entry
    assert entry["kinds"] == ["text", "text"], entry
    assert entry["idempotent"], entry


@needs_node
def test_markup_in_the_alt_text_is_text_and_never_an_element() -> None:
    entry = _dom("turns markup in the alt text into text")
    assert entry["kinds"] == ["text", "text", "text"], entry
    assert "<img src=x onerror=alert(1)>" in entry["texts"], entry
    assert "<img" not in entry["html"].replace("<img src=x onerror=alert(1)>", ""), (
        entry
    )


@needs_node
def test_mixed_content_keeps_order_and_only_loses_the_dropped_images() -> None:
    assert _run()["mixed"] == (
        '<div>a <a href="https://example.com/x">badge</a> b '
        '<img src="https://example.com/ok.png" alt="ok"></img> c bad d '
        '<img alt="no source at all"></img> e <em>deep</em> f</div>'
    )


@needs_node
def test_a_missing_or_odd_container_is_not_an_error() -> None:
    # same contract as processLinks: render helpers never take the page down
    assert _run()["nonContainers"] == [False, False, False, False]


# ---------------------------------------------------------------------------
# what marked really emits, through the same rule
# ---------------------------------------------------------------------------


@needs_node
@pytest.mark.parametrize("markdown", sorted(MARKDOWN))
def test_vendored_marked_output_ends_up_with_the_expected_decision(
    markdown: str,
) -> None:
    entry = next(e for e in _run()["marked"] if e["md"] == markdown)
    expected = MARKDOWN[markdown]
    if expected == "none":
        assert entry["tags"] == [], entry
        return
    assert entry["tags"], f"marked produced no image for {markdown!r}"
    if expected == "keep":
        assert len(entry["left"]) == len(entry["tags"]), entry
    else:
        assert entry["left"] == [], entry


@needs_node
@pytest.mark.parametrize("markdown", sorted(MARKDOWN))
def test_marked_writes_no_attribute_the_page_did_not_expect(markdown: str) -> None:
    # a quote in the destination must not open a new attribute (``onerror=``): the image
    # carries ``src``, ``alt`` and at most ``title``
    entry = next(e for e in _run()["marked"] if e["md"] == markdown)
    for names in entry["attrNames"]:
        assert set(names) <= {"src", "alt", "title"}, entry
    for tag in entry["tags"]:
        assert re.fullmatch(r'<img src="[^"]*" alt="[^"]*"(?: title="[^"]*")?>', tag), (
            tag
        )


@needs_node
def test_marked_itself_does_not_filter_these_destinations() -> None:
    # documents why the page has to: marked hands every one of these to the DOM
    by_md = {e["md"]: e for e in _run()["marked"]}
    assert (
        'src="javascript:window.__xss=9"'
        in by_md["![img](javascript:window.__xss=9)"]["tags"][0]
    )
    assert 'src="file:///etc/passwd"' in by_md["![img](file:///etc/passwd)"]["tags"][0]
    assert 'src="javascript:alert(1)"' in by_md["![](javascript:alert(1))"]["tags"][0]


@needs_node
def test_a_dropped_markdown_image_leaves_its_alt_text() -> None:
    by_md = {e["md"]: e for e in _run()["marked"]}
    assert by_md["![img](javascript:window.__xss=9)"]["text"].strip() == "img"
    assert (
        by_md["[![badge](javascript:alert(1))](https://example.com)"]["text"].strip()
        == "badge"
    )
    assert by_md["![](javascript:alert(1))"]["text"].strip() == ""


# ---------------------------------------------------------------------------
# wiring: both places that paint the message
# ---------------------------------------------------------------------------


def test_the_first_paint_runs_the_image_rule_after_the_link_rule_and_before_math() -> (
    None
):
    body = _extract_function(
        APP_JS.read_text(encoding="utf-8"), "function renderMarkdownContent("
    )
    assert "processPromptImages(element)" in body
    assert body.index("processLinks(element)") < body.index(
        "processPromptImages(element)"
    )
    assert body.index("processPromptImages(element)") < body.index(
        "loadMathJaxIfNeeded"
    )


def test_the_multi_task_paint_runs_the_image_rule_after_the_link_rule_and_before_math() -> (
    None
):
    body = _extract_function(
        MULTI_TASK_JS.read_text(encoding="utf-8"),
        "async function updateDescriptionDisplay(",
    )
    assert "processPromptImages(descriptionElement)" in body
    assert body.index("processLinks(descriptionElement)") < body.index(
        "processPromptImages(descriptionElement)"
    )
    assert body.index("processPromptImages(descriptionElement)") < body.index(
        "loadMathJaxIfNeeded"
    )


def test_the_multi_task_paint_guards_the_call_like_the_other_helpers() -> None:
    body = _extract_function(
        MULTI_TASK_JS.read_text(encoding="utf-8"),
        "async function updateDescriptionDisplay(",
    )
    assert 'typeof processPromptImages === "function"' in body


def test_the_web_function_does_not_share_a_name_with_the_webview_upload_helper() -> (
    None
):
    # ``processImages`` in webview-ui.js reads files the user picked; same word, other job
    assert "function processImages(" not in APP_JS.read_text(encoding="utf-8")
    assert "async function processImages(" in WEBVIEW_JS.read_text(encoding="utf-8")
