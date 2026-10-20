r"""R769 regression coverage: only TeX the page recognised is typeset, and Markdown leaves it alone.

Two things were wrong with math in the Web UI.

1. protectMathDelimiters hid only \(...\) and \[...\] from Markdown, so the TeX inside
   $...$ and $$...$$ was rewritten by marked: \\ lost a backslash (a matrix collapsed
   into one row), \, became a comma, \{ and \} lost their backslashes and _ / *
   turned into emphasis.
2. MathJax read every $...$ it found in the page, so ordinary prose such as
   "The total is $5 and the deposit is $10" came out as one italic formula
   (5anddthedepositis10), and so did option labels and anything else on the page,
   because MathJax also typeset the whole body once after it loaded.

The page now finds the TeX itself (Pandoc / GitHub rules for $), hides it from marked,
puts the original text back inside a tex2jax_process span and has MathJax look only
inside those spans (the container gets tex2jax_ignore and MathJax no longer typesets the
whole page on load).
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
STATIC_JS = REPO_ROOT / "src" / "ai_intervention_agent" / "static" / "js"
LOADER_JS = STATIC_JS / "mathjax-loader.js"
MARKED_JS = STATIC_JS / "marked.js"
APP_JS = STATIC_JS / "app.js"

pytestmark = pytest.mark.skipif(
    shutil.which("node") is None, reason="node runtime unavailable"
)

SPAN = '<span class="tex2jax_process">'

# name -> (markdown, expected segments)
CASES: dict[str, tuple[str, list[str]]] = {
    "inline": ("Let $x^2+y^2=z^2$ hold.", ["$x^2+y^2=z^2$"]),
    "display_rows": (
        "Text\n\n$$\n\\begin{aligned}\na &= b \\\\\nc &= d\n\\end{aligned}\n$$\n\nAfter",
        ["$$\n\\begin{aligned}\na &= b \\\\\nc &= d\n\\end{aligned}\n$$"],
    ),
    "matrix_one_line": (
        "M $$\\begin{pmatrix} a & b \\\\ c & d \\end{pmatrix}$$ end",
        ["$$\\begin{pmatrix} a & b \\\\ c & d \\end{pmatrix}$$"],
    ),
    "thin_space_and_braces": (
        "$\\int_0^1 f(x)\\,dx$ and $\\{x \\mid x>0\\}$",
        ["$\\int_0^1 f(x)\\,dx$", "$\\{x \\mid x>0\\}$"],
    ),
    "emphasis_characters": (
        "See $a_b*c_d*$ and $**z**$",
        ["$a_b*c_d*$", "$**z**$"],
    ),
    "paren_with_parens": ("Call \\(f(x) + g(y)\\) now", ["\\(f(x) + g(y)\\)"]),
    "bracket_with_brackets": ("Index \\[ a_{[i]} + b \\] now", ["\\[ a_{[i]} + b \\]"]),
    "escaped_dollar_inside": ("so $a \\$ b$ holds", ["$a \\$ b$"]),
    "escaped_closer_is_not_a_closer": ("Open \\(a\\\\) text", []),
    "escaped_closer_then_real": (
        "x \\(a\\\\) y \\(b\\) z",
        ["\\(a\\\\) y \\(b\\)"],
    ),
    "even_backslashes_then_closer": ("x \\(a\\\\\\) z", ["\\(a\\\\\\)"]),
    "escaped_environment_end": ("\\begin{align}a\\\\end{align} no", []),
    "currency": ("The total is $5 and the deposit is $10 each, so $15 today.", []),
    "currency_and_shell": (
        "A price of $20,000 versus $30,000, and $HOME or $PATH and $USER.",
        [],
    ),
    "currency_range": ("Prices: $5-$10 and US$5 to US$10", []),
    "currency_then_math": ("Costs $5 and $10, but $x$ is a variable", ["$x$"]),
    "escaped_dollars": ("Pay \\$5 and \\$10 and $x$", ["$x$"]),
    "space_after_opener": ("cost $ a$ done", []),
    "closer_after_space": ("owe $5 and $x ok", []),
    "empty_paren": ("a \\(  \\) b", []),
    "display_too_long": ("a $$" + "x" * 30100 + "$$ b", []),
    "code_span_across_blank_line": ("`a $x$\n\nb` end", ["$x$"]),
    "code_span_exact_run": ("`a ``b $x$ c` d $y$", ["$y$"]),
    "dollar_spaces": ("cost is $ 5 and $ 10 so $ x $ is not math", []),
    "digit_after_closer": ("we have $a$1 but $b$ and $c$2", ["$b$"]),
    "dollar_runs": ("a $$$ b $$$$ c $x$", ["$x$"]),
    "empty_display": ("a $$   $$ b", []),
    "unmatched": ("only $ here and $$ there and \\( and \\[ end", []),
    "inline_code": ("Use `$x$` and `echo $HOME` and $y$", ["$y$"]),
    "double_backtick_code": ("Use ``a ` $b$ ` c`` then $z$", ["$z$"]),
    "fenced_code": (
        'Before $a$\n\n```bash\necho "$x$" $HOME\n```\n\nAfter $b$',
        ["$a$", "$b$"],
    ),
    "tilde_fence": ("~~~\n$x$ \\(y\\) \\[z\\]\n~~~\n$w$", ["$w$"]),
    "unclosed_fence": ("Intro $a$\n```\n$b$ and $$c$$ never closed", ["$a$"]),
    "indented_fence_in_list": (
        '1. step\n\n    ```sh\n    echo "$a" "$b"\n    ```\n\n2. next $c$',
        ["$c$"],
    ),
    "link_destination": ("See [docs](https://example.com/a$b$c) now", []),
    "relative_link_destination": ("See [docs](docs/a$b$c.md) now", []),
    "bare_url": ("Go to https://example.com/a$b$c now and $d$", ["$d$"]),
    "www_url": ("see www.example.com/a$b$c and $d$", ["$d$"]),
    "ftp_url": ("get ftp://host/a$b$c and $d$", ["$d$"]),
    "image_alt": ("![$x$](pic.png)", []),
    "html_characters": (
        "Compare $a<b>c$ and $a&b$ and $$x<y$$",
        ["$a<b>c$", "$a&b$", "$$x<y$$"],
    ),
    "blank_line_inside_inline": ("Open $a\n\nb$ close", []),
    "blank_line_inside_display": ("Open $$a\n\nb$$ close", ["$$a\n\nb$$"]),
    "inline_too_long": ("x $" + "a" * 2100 + "$ y", []),
    "table": (
        "| a | b |\n|---|---|\n| $a|b$ | $c$ |",
        ["$a|b$", "$c$"],
    ),
    "bare_environment": (
        "Text\n\\begin{align}\na &= b \\\\\nc &= d\n\\end{align}\nafter",
        ["\\begin{align}\na &= b \\\\\nc &= d\n\\end{align}"],
    ),
    "unknown_environment": ("\\begin{itemize}\n\\item one\n\\end{itemize}", []),
    "around_emphasis": ("**$x$** and _$y$_ and ~~$z$~~", ["$x$", "$y$", "$z$"]),
    "heading": ("# Title with $E=mc^2$\n\nBody", ["$E=mc^2$"]),
    "list_and_quote": (
        "- item $a$\n- item \\(b\\)\n\n> quote $c$ and\n> $$d$$",
        ["$a$", "\\(b\\)", "$c$", "$$d$$"],
    ),
    "quote_display_rows": (
        "> Given:\n> $$\n> q = r\n> $$\n> done",
        ["$$\nq = r\n$$"],
    ),
    "quote_display_aligned": (
        "> $$\n> \\begin{aligned}\n> a &= b \\\\\n> c &= d\n> \\end{aligned}\n> $$",
        ["$$\n\\begin{aligned}\na &= b \\\\\nc &= d\n\\end{aligned}\n$$"],
    ),
    "quote_nested_display": (
        "> > $$\n> > a\n> > $$\n> back",
        ["$$\na\n$$"],
    ),
    "quote_inline_over_two_lines": (
        "> text $a\n> + b$ end",
        ["$a\n+ b$"],
    ),
    "quote_lazy_continuation": ("> $$\na\n> $$", ["$$\na\n$$"]),
    "quote_indented_markers": ("> a $$\n   > b\n> $$", ["$$\nb\n$$"]),
    "quote_environment": (
        "> \\begin{align}\n> a &= b\n> \\end{align}",
        ["\\begin{align}\na &= b\n\\end{align}"],
    ),
    "quote_extra_marker_is_tex": ("> $$\n> > x\n> $$", ["$$\n> x\n$$"]),
    "greater_than_outside_a_quote_is_tex": ("$$\n> a\n$$", ["$$\n> a\n$$"]),
    "list_continuation_keeps_its_text": (
        "- item $$\n  a\n  $$",
        ["$$\n  a\n  $$"],
    ),
    "nested_dollar_in_display": (
        "$$ \\text{if } $x$ > 0 $$",
        ["$$ \\text{if } $x$ > 0 $$"],
    ),
    "unknown_slot_left_alone": ("literal %%AIIA_MATH_SLOT_7%% and $x$", ["$x$"]),
    "no_math": ("just text with `code` and **bold**", []),
}

HARNESS = r"""
const fs = require('fs');
const vm = require('vm');
const marked = require(__MARKED_PATH__);
marked.use({ renderer: { html() { return ''; } } });
const loaderSource = fs.readFileSync(__LOADER_PATH__, 'utf8');

function makeSandbox() {
  const appended = [];
  const sandbox = {
    console: { debug() {}, warn() {}, error() {}, log() {}, info() {} },
    document: {
      createElement(tag) { return { tagName: String(tag).toUpperCase() }; },
      head: { appendChild(node) { appended.push(node); } },
    },
    __appended: appended,
  };
  sandbox.window = sandbox;
  sandbox.globalThis = sandbox;
  vm.createContext(sandbox);
  vm.runInContext(loaderSource, sandbox);
  return sandbox;
}

const sandbox = makeSandbox();
const win = sandbox.window;
const out = { cases: {}, loader: {}, restore: {} };

for (const [name, markdown] of Object.entries(__CASES__)) {
  const guard = win.protectMathDelimiters(markdown);
  const html = win.restoreMathDelimiters(marked.parse(guard.text), guard.segments);
  out.cases[name] = { segments: Array.from(guard.segments), html, unchanged: guard.text === markdown };
}

for (const [name, markdown] of Object.entries(__ATTACKS__)) {
  const guard = win.protectMathDelimiters(markdown);
  out.cases[name] = {
    segments: Array.from(guard.segments),
    html: win.restoreMathDelimiters(marked.parse(guard.text), guard.segments),
  };
}

out.restore.attribute = win.restoreMathDelimiters(
  '<a href="%%AIIA_MATH_SLOT_0%%" title="%%AIIA_MATH_SLOT_0%%">%%AIIA_MATH_SLOT_0%%</a>',
  ['$a"b$'],
);
out.restore.attributeEscapes = win.restoreMathDelimiters(
  '<a title="%%AIIA_MATH_SLOT_0%%"></a>',
  ['&<>"\''],
);
out.restore.unknownInTag = win.restoreMathDelimiters(
  '<a title="%%AIIA_MATH_SLOT_3%% %%AIIA_MATH_SLOT_0%%"></a>',
  ['$a$'],
);
out.restore.unknown = win.restoreMathDelimiters('<p>%%AIIA_MATH_SLOT_3%%</p>', ['$a$']);
out.restore.noSegments = win.restoreMathDelimiters('<p>%%AIIA_MATH_SLOT_0%%</p>', []);
out.restore.notString = win.restoreMathDelimiters(null, ['$a$']);
out.restore.protectNotString = JSON.stringify(win.protectMathDelimiters(null));

function reassemble(guard) {
  return guard.text.replace(/%%AIIA_MATH_SLOT_(\d+)%%/g, (m, k) => guard.segments[Number(k)]);
}

// A formula inside a blockquote loses the quote's markers on its later lines, so
// the round trip is exact only up to those markers.
function withoutQuoteMarkers(value) {
  return value.split('\n').map((line) => line.replace(/^ {0,3}(?:> ?)+/, '')).join('\n');
}

function wellFormed(segment) {
  if (segment.startsWith('$$')) return segment.length >= 5 && segment.endsWith('$$') && segment.slice(2, -2).trim() !== '';
  if (segment.startsWith('$')) {
    const body = segment.slice(1, -1);
    return segment.length >= 3 && segment.endsWith('$') && !/^\s/.test(body) && !/\s$/.test(body);
  }
  if (segment.startsWith('\\(')) return segment.endsWith('\\)') && segment.length > 4;
  if (segment.startsWith('\\[')) return segment.endsWith('\\]') && segment.length > 4;
  if (segment.startsWith('\\begin{')) return /\\end\{[a-z]+\*?\}$/.test(segment);
  return false;
}

const ALPHABET = ['$', '$', '$', '\\', '(', ')', '[', ']', '`', '`', '~', 'a', 'b', ' ', ' ', '\n', '\n', '1', 'x', '_', '*', '{', '}', '<', '>', '&', 'h', 't', 'p', ':', '/', '\\begin{align}', '\\end{align}', '\\(', '\\)', '\\[', '\\]', '```', '$$', '%'];
let seed = 20261021;
function rnd() { seed = (seed * 1664525 + 1013904223) >>> 0; return seed / 4294967296; }
const fuzz = { iterations: 0, broken: [], malformed: [], thrown: [], withSegments: 0 };
for (let n = 0; n < 30000; n += 1) {
  let text = '';
  const length = Math.floor(rnd() * 70);
  for (let k = 0; k < length; k += 1) text += ALPHABET[Math.floor(rnd() * ALPHABET.length)];
  if (text.indexOf('%%AIIA_MATH_SLOT_') !== -1) continue;
  fuzz.iterations += 1;
  try {
    const guard = win.protectMathDelimiters(text);
    if (guard.segments.length) fuzz.withSegments += 1;
    const back = reassemble(guard);
    const exact = text.indexOf('>') === -1 ? back === text : true;
    if ((!exact || withoutQuoteMarkers(back) !== withoutQuoteMarkers(text)) && fuzz.broken.length < 3) {
      fuzz.broken.push(text);
    }
    for (const segment of guard.segments) {
      if (!wellFormed(segment) && fuzz.malformed.length < 3) fuzz.malformed.push([segment, text]);
    }
    if (n % 25 === 0) win.restoreMathDelimiters(marked.parse(guard.text), guard.segments);
  } catch (error) {
    if (fuzz.thrown.length < 3) fuzz.thrown.push([text, String(error)]);
  }
}
out.fuzz = fuzz;

const SIZE = 200000;
const repeat = (unit) => unit.repeat(Math.ceil(SIZE / unit.length)).slice(0, SIZE);
const adversarial = {
  dollarOpeners: repeat('$a '),
  parenOpeners: repeat('\\( '),
  bracketOpeners: repeat('\\[ '),
  beginOpeners: repeat('\\begin{align} '),
  displayOpeners: repeat('$$ a '),
  manyPairs: repeat('$x$ '),
  backtickRuns: (() => { let s = ''; let k = 1; while (s.length < SIZE) { s += '`'.repeat(k) + 'a '; k = (k % 40) + 1; } return s; })(),
  dollarLines: repeat('$a\n'),
  quotedDisplays: repeat('> $$\n> a\n> $$\n'),
  quotedInlineOverLines: repeat('> > > > > $a\n> > b$ '),
  longQuotePrefix: '> '.repeat(SIZE / 4) + '$$\n' + repeat('> a\n') + '\n> $$',
  escaped: '$a' + repeat('\\$'),
};
out.perf = {};
for (const [name, text] of Object.entries(adversarial)) {
  const started = process.hrtime.bigint();
  const guard = win.protectMathDelimiters('$x$ ' + text);
  win.restoreMathDelimiters(guard.text, guard.segments);
  out.perf[name] = Number(process.hrtime.bigint() - started) / 1e6;
}

const config = win.MathJax;
out.loader.config = {
  typeset: config.startup.typeset,
  ignore: config.options.ignoreHtmlClass,
  process: config.options.processHtmlClass,
  skip: config.options.skipHtmlTags,
};

function element(hasSpan) {
  const added = [];
  return {
    added,
    querySelector(selector) { return hasSpan && selector === '.tex2jax_process' ? {} : null; },
    classList: { add(name) { added.push(name); } },
  };
}

{
  const s = makeSandbox();
  const plain = element(false);
  s.window.loadMathJaxIfNeeded(plain, 'The total is $5 and $10');
  out.loader.noSpan = { added: plain.added, appended: s.__appended.length, pending: s.window._mathJaxPendingElements.length, loading: s.window._mathJaxLoading };
}
{
  const s = makeSandbox();
  const first = element(true);
  const second = element(true);
  s.window.loadMathJaxIfNeeded(first, '$x$');
  s.window.loadMathJaxIfNeeded(second, '$y$');
  out.loader.withSpan = {
    added: first.added,
    appended: s.__appended.map((node) => node.src),
    pending: s.window._mathJaxPendingElements.length,
    loading: s.window._mathJaxLoading,
  };
}
{
  const s = makeSandbox();
  const typeset = [];
  s.window._mathJaxLoaded = true;
  s.window.MathJax.typesetPromise = (elements) => { typeset.push(elements.length); return Promise.resolve(); };
  const el = element(true);
  s.window.loadMathJaxIfNeeded(el, '$x$');
  out.loader.loaded = { added: el.added, typeset, appended: s.__appended.length };
}
{
  const s = makeSandbox();
  const el = element(true);
  s.window.loadMathJaxIfNeeded(el, 'no math marker here');
  out.loader.noMarker = { added: el.added, appended: s.__appended.length };
}
out.loader.hasMath = ['', 'plain', '$5', '\\(x\\)', '\\[x\\]', '\\begin{align}'].map((text) => win.hasMathContent(text));

process.stdout.write(JSON.stringify(out));
"""

ATTACKS = {
    "attack_destination_paren": '[x](http://e/\\(" onmouseover=alert(1) x="\\))',
    "attack_destination_dollar": '[x](http://e/$" onmouseover=alert(1) x="$)',
    "attack_link_text": '[$" onmouseover=alert(1) x="$](http://e/)',
    "attack_image_alt": '![$" onerror=alert(1) x="$](http://e/p.png)',
    "attack_link_title": '[x](http://e/ (t $a" onmouseover="alert(1)$ b))',
    "attack_reference_title": "[r]: http://e/ 't $a\" onmouseover=\"alert(1)$ b'\n\n[x][r]",
    "attack_image_reference_title": '![i][r]\n\n[r]: http://e/p.png (t $a" onerror="alert(1)$ b)',
}

# Places the scan cannot see through (a title, a definition, an indented code
# block): the placeholder is replaced by plain text there, never by a span.
CONTEXTS = {
    "link_title": '[docs](http://e/a "price $a$ b")',
    "reference_title": '[r]: http://e/p.png "t $c$"\n\n![i][r] and [x][r]',
    "indented_code_block": "text\n\n    $x$ and \\(y\\)\n\nafter $z$",
    "indented_fence_in_list_with_math": (
        "1. step\n\n    ```tex\n    $a+b$ here\n    ```\n\n2. next $c$"
    ),
}


@pytest.fixture(scope="module")
def result() -> dict:
    script = (
        HARNESS.replace("__MARKED_PATH__", json.dumps(str(MARKED_JS)))
        .replace("__LOADER_PATH__", json.dumps(str(LOADER_JS)))
        .replace("__CASES__", json.dumps({k: v[0] for k, v in CASES.items()}))
        .replace("__ATTACKS__", json.dumps({**ATTACKS, **CONTEXTS}))
    )
    proc = subprocess.run(
        ["node", "-e", script],
        check=False,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0, f"stdout={proc.stdout!r} stderr={proc.stderr!r}"
    return json.loads(proc.stdout)


@pytest.mark.parametrize("name", sorted(CASES))
def test_only_real_math_is_protected(result: dict, name: str) -> None:
    markdown, expected = CASES[name]
    case = result["cases"][name]

    assert case["segments"] == expected, markdown
    assert case["unchanged"] is (not expected), markdown
    for segment in expected:
        escaped = (
            segment.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        )
        assert f"{SPAN}{escaped}</span>" in case["html"], (markdown, case["html"])
    assert case["html"].count(SPAN) == len(expected), case["html"]
    assert "AIIA_MATH_SLOT_0" not in case["html"]


def test_math_text_survives_markdown_untouched(result: dict) -> None:
    html = result["cases"]["display_rows"]["html"]
    assert "a &amp;= b \\\\\nc &amp;= d" in html

    thin = result["cases"]["thin_space_and_braces"]["html"]
    assert "\\int_0^1 f(x)\\,dx" in thin
    assert "\\{x \\mid x&gt;0\\}" in thin

    assert "<em>" not in result["cases"]["emphasis_characters"]["html"]
    assert "<strong>" not in result["cases"]["emphasis_characters"]["html"]


def test_prose_dollars_stay_plain_text(result: dict) -> None:
    html = result["cases"]["currency"]["html"]
    assert html == "<p>The total is $5 and the deposit is $10 each, so $15 today.</p>\n"
    assert SPAN not in result["cases"]["currency_and_shell"]["html"]


def test_code_and_urls_are_never_read_as_math(result: dict) -> None:
    assert "<code>$x$</code>" in result["cases"]["inline_code"]["html"]
    assert (
        'href="https://example.com/a$b$c"'
        in result["cases"]["link_destination"]["html"]
    )
    assert (
        'href="docs/a$b$c.md"' in result["cases"]["relative_link_destination"]["html"]
    )
    assert 'href="https://example.com/a$b$c"' in result["cases"]["bare_url"]["html"]
    assert 'href="http://www.example.com/a$b$c"' in result["cases"]["www_url"]["html"]
    assert 'href="ftp://host/a$b$c"' in result["cases"]["ftp_url"]["html"]
    assert 'alt="$x$"' in result["cases"]["image_alt"]["html"]
    assert "echo &quot;$x$&quot; $HOME" in result["cases"]["fenced_code"]["html"]


def _attribute_names(tag: str) -> list[str]:
    without_values = re.sub(r'"[^"]*"', '""', tag)
    return re.findall(r"\s([A-Za-z-]+)(?==)", without_values)


@pytest.mark.parametrize("name", sorted(ATTACKS))
def test_tex_never_reaches_an_attribute(result: dict, name: str) -> None:
    html = result["cases"][name]["html"]

    names = {n for tag in re.findall(r"<[^>]*>", html) for n in _attribute_names(tag)}
    assert names <= {"href", "src", "alt", "class", "title"}, html


def test_a_title_keeps_its_text_and_never_a_placeholder(result: dict) -> None:
    # A placeholder in a link title or a reference definition used to be left
    # as "%%AIIA_MATH_SLOT_n%%" in the page (the title tooltip showed it).
    html = result["cases"]["link_title"]["html"]
    assert 'title="price $a$ b"' in html

    html = result["cases"]["reference_title"]["html"]
    assert html.count('title="t $c$"') == 2, html

    attack = result["cases"]["attack_link_title"]["html"]
    assert 'title="t $a&quot; onmouseover=&quot;alert(1)$ b"' in attack, attack

    for name in (
        "link_title",
        "reference_title",
        "attack_link_title",
        "attack_reference_title",
        "attack_image_reference_title",
    ):
        html = result["cases"][name]["html"]
        assert "AIIA_MATH_SLOT" not in html, html
        assert SPAN not in html, html


def test_math_inside_code_comes_back_as_plain_text(result: dict) -> None:
    # An indented code block (and a fence indented four or more columns, e.g.
    # inside a list) is not recognised by the scan, so its TeX is protected like
    # any other. It must come back as the code it is, not as a span of markup.
    block = result["cases"]["indented_code_block"]["html"]
    assert "<pre><code>$x$ and \\(y\\)\n</code></pre>" in block, block
    assert block.count(SPAN) == 1
    assert f"{SPAN}$z$</span>" in block

    fence = result["cases"]["indented_fence_in_list_with_math"]["html"]
    assert re.search(r'<code class="language-tex">\$a\+b\$ here\n</code>', fence), fence
    assert fence.count(SPAN) == 1
    assert f"{SPAN}$c$</span>" in fence
    for name in ("indented_code_block", "indented_fence_in_list_with_math"):
        assert "AIIA_MATH_SLOT" not in result["cases"][name]["html"]


def test_restore_gives_attributes_plain_escaped_text(result: dict) -> None:
    # Inside a tag the original text is escaped for an attribute value (it must
    # not be able to close the attribute) and never wrapped in a span; in running
    # text it goes into the span MathJax is allowed to read.
    assert result["restore"]["attribute"] == (
        f'<a href="$a&quot;b$" title="$a&quot;b$">{SPAN}$a"b$</span></a>'
    )
    assert result["restore"]["attributeEscapes"] == (
        '<a title="&amp;&lt;&gt;&quot;&#39;"></a>'
    )
    assert result["restore"]["unknown"] == "<p>%%AIIA_MATH_SLOT_3%%</p>"
    assert (
        result["restore"]["unknownInTag"] == '<a title="%%AIIA_MATH_SLOT_3%% $a$"></a>'
    )
    assert result["restore"]["noSegments"] == "<p>%%AIIA_MATH_SLOT_0%%</p>"
    assert result["restore"]["notString"] is None
    assert json.loads(result["restore"]["protectNotString"]) == {
        "text": None,
        "segments": [],
    }


def test_random_text_round_trips_and_segments_are_well_formed(result: dict) -> None:
    fuzz = result["fuzz"]

    assert fuzz["iterations"] > 25000
    assert fuzz["withSegments"] > 5000
    assert fuzz["broken"] == []
    assert fuzz["malformed"] == []
    assert fuzz["thrown"] == []


def test_scan_time_is_linear_on_adversarial_text(result: dict) -> None:
    slow = {name: ms for name, ms in result["perf"].items() if ms > 1500}

    assert slow == {}, result["perf"]


def test_mathjax_is_told_to_typeset_only_marked_spans(result: dict) -> None:
    config = result["loader"]["config"]

    assert config["typeset"] is False
    assert config["ignore"] == "tex2jax_ignore"
    assert config["process"] == "tex2jax_process"
    assert "pre" in config["skip"]
    assert "code" in config["skip"]


def test_loader_ignores_elements_without_marked_math(result: dict) -> None:
    assert result["loader"]["noSpan"] == {
        "added": [],
        "appended": 0,
        "pending": 0,
        "loading": False,
    }
    assert result["loader"]["noMarker"] == {"added": [], "appended": 0}


def test_loader_gates_the_container_and_loads_mathjax_once(result: dict) -> None:
    assert result["loader"]["withSpan"] == {
        "added": ["tex2jax_ignore"],
        "appended": ["/static/js/tex-mml-chtml.js"],
        "pending": 2,
        "loading": True,
    }
    assert result["loader"]["loaded"] == {
        "added": ["tex2jax_ignore"],
        "typeset": [1],
        "appended": 0,
    }


def test_has_math_content_is_a_cheap_prefilter(result: dict) -> None:
    assert result["loader"]["hasMath"] == [False, False, True, True, True, True]


def test_strikethrough_pass_skips_math_spans() -> None:
    source = APP_JS.read_text(encoding="utf-8")
    start = source.index("function processStrikethrough(")
    body = source[start : source.index("async function loadConfig(")]

    assert 'parent.closest("pre, code, script, style, .tex2jax_process")' in body
