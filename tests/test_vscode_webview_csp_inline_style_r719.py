"""R719 · the VS Code webview must not depend on CSP-blocked inline styles.

The webview CSP is ``style-src ${cspSource}`` (no ``'unsafe-inline'``), so every
``style="..."`` attribute that reaches the DOM is refused *and reported*. Two
concrete costs were measured in real VS Code 1.110 / Cursor 3.26:

* ``sanitizePromptHtml`` parsed server HTML whose Pygments markup carries
  ``style`` attributes (``noclasses=True``: one ``<span style>`` per token, one
  ``<div class="highlight" style>`` and one ``<pre style>`` per block). A 52 KB
  prompt raised 12 050 CSP violation events during that parse (first render
  259 ms, 110 ms once the attributes are removed from the string first) - the
  sanitizer deleted them right afterwards anyway.
* ``webview.ts`` shipped two inline ``style`` attributes in the settings panel
  (``#feedbackCountdown`` width, Bark action-row flex layout). Computed styles
  in the live webview showed ``max-width: none`` / ``display: block``: the
  intended layout never applied and every load logged two violations.
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
WEBVIEW_CSS = VSCODE_DIR / "webview.css"

PRE_STRIP_STATEMENT = (
    "container.innerHTML = rawHtml.replace("
    '/(<(?:span|pre|div class="highlight")) style="[^"]*">/g, \'$1>\')'
)
FIRST_PARTY_WEBVIEW_JS = (
    "webview-ui.js",
    "webview-state.js",
    "webview-helpers.js",
    "webview-notify-core.js",
    "webview-settings-ui.js",
    "tri-state-panel.js",
    "tri-state-panel-loader.js",
    "tri-state-panel-bootstrap.js",
    "prism-bootstrap.js",
    "i18n.js",
)


def _extract_function(source: str, marker: str) -> str:
    start = source.find(marker)
    assert start != -1, f"Cannot find function marker: {marker}"
    open_brace = source.find("{", start)
    assert open_brace != -1, f"Cannot find opening brace for: {marker}"
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


def _sanitize_body() -> str:
    return _extract_function(
        WEBVIEW_UI_JS.read_text(encoding="utf-8"), "function sanitizePromptHtml("
    )


def _html_template() -> str:
    source = WEBVIEW_TS.read_text(encoding="utf-8")
    start = source.index("return `<!DOCTYPE html>")
    end = source.index("</html>`", start)
    return source[start:end]


def _pre_strip_call() -> tuple[str, str]:
    match = re.search(r"rawHtml\.replace\((/.+?/g), '(.*?)'\)", _sanitize_body())
    assert match, "sanitizePromptHtml must pre-strip style attributes with a regex"
    return match.group(1), match.group(2)


def _pre_strip_in_node(samples: list[str]) -> list[str]:
    regex, replacement = _pre_strip_call()
    script = textwrap.dedent(
        f"""
        const samples = JSON.parse(process.argv[1])
        const re = {regex}
        process.stdout.write(
          JSON.stringify(samples.map(s => s.replace(re, {json.dumps(replacement)})))
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


def test_sanitizer_strips_style_attributes_before_the_html_parse() -> None:
    body = _sanitize_body()

    assert PRE_STRIP_STATEMENT in body
    assert "container.innerHTML = rawHtml\n" not in body
    assert body.index(PRE_STRIP_STATEMENT) < body.index("const DROP_TAGS")
    assert body.index(PRE_STRIP_STATEMENT) < body.index(
        "const all = container.querySelectorAll('*')"
    )


def test_pre_strip_only_rewrites_the_exact_pygments_openers() -> None:
    cases = {
        '<span style="color: #66d9ef">def</span>': "<span>def</span>",
        '<span style="color: #f8f8f2; background-color: #272822">x</span>': (
            "<span>x</span>"
        ),
        '<span style=""></span>': "<span></span>",
        (
            '<span style="color: #a">a</span><span style="color: #b">b</span>'
        ): "<span>a</span><span>b</span>",
        '<pre style="line-height: 125%;"><span></span><code>': (
            "<pre><span></span><code>"
        ),
        '<div class="highlight" style="background: #272822"><pre style="line-height: 125%;">': (
            '<div class="highlight"><pre>'
        ),
        '<span class="k" style="color: #a">a</span>': (
            '<span class="k" style="color: #a">a</span>'
        ),
        '<pre class="x" style="color: #a">': '<pre class="x" style="color: #a">',
        '<div class="other" style="background: #fff">': (
            '<div class="other" style="background: #fff">'
        ),
        '<div style="background: #fff">': '<div style="background: #fff">',
        '<code style="color: #a">': '<code style="color: #a">',
        "<span style='color: #a'>a</span>": "<span style='color: #a'>a</span>",
        "&lt;span style=&quot;color: #a&quot;&gt;": (
            "&lt;span style=&quot;color: #a&quot;&gt;"
        ),
        'literal text: span style="color: #a"': 'literal text: span style="color: #a"',
        'prose: <b>set style="color: red" here</b>': (
            'prose: <b>set style="color: red" here</b>'
        ),
        '<span style="never closed': '<span style="never closed',
        "": "",
    }

    assert _pre_strip_in_node(list(cases)) == list(cases.values())


def test_pre_strip_is_linear_on_hostile_input() -> None:
    regex, replacement = _pre_strip_call()
    script = textwrap.dedent(
        f"""
        const re = {regex}
        const inputs = [
          '<span style="' + 'a'.repeat(2000000),
          '<span style="'.repeat(100000),
          '<span style="x">'.repeat(200000),
          '<pre style="'.repeat(100000),
          '<div class="highlight" style="'.repeat(100000),
          '<div class="highlight" '.repeat(100000)
        ]
        const t0 = process.hrtime.bigint()
        for (const s of inputs) s.replace(re, {json.dumps(replacement)})
        process.stdout.write(String(Number(process.hrtime.bigint() - t0) / 1e6))
        """
    )
    result = subprocess.run(
        ["node", "-e", script], check=True, capture_output=True, text=True
    )

    assert float(result.stdout) < 1500, (
        f"style pre-strip took {result.stdout} ms on hostile input"
    )


def test_pre_strip_leaves_no_inline_style_in_the_servers_markdown() -> None:
    import markdown

    from ai_intervention_agent.web_ui import _MD_EXTENSION_CONFIGS, _MD_EXTENSIONS

    source = (
        "```python\ndef f(x):\n    return x * 2\n```\n\n"
        "```\nunlabelled <b>block</b>\n```\n\n`inline`\n"
    )
    html = markdown.Markdown(
        extensions=_MD_EXTENSIONS, extension_configs=_MD_EXTENSION_CONFIGS
    ).convert(source)

    assert '<span style="' in html, (
        "server markup no longer uses Pygments inline-style tokens; "
        "re-evaluate the R719 sanitizer pre-strip"
    )
    assert '<div class="highlight" style="' in html
    assert '<pre style="' in html
    stripped = _pre_strip_in_node([html])[0]

    assert re.findall(r"<[a-zA-Z][^<>]*?\sstyle\s*=", stripped) == []


def test_webview_html_template_has_no_inline_style_attributes() -> None:
    template = _html_template()
    template = re.sub(r"<script\b.*?</script>", "", template, flags=re.DOTALL)
    template = re.sub(r"<!--.*?-->", "", template, flags=re.DOTALL)

    offenders = re.findall(r"<[a-zA-Z][^<>]*?\sstyle\s*=[^<>]*>", template)

    assert offenders == []


def test_first_party_webview_scripts_do_not_emit_inline_style_attributes() -> None:
    offenders: list[str] = []
    for name in FIRST_PARTY_WEBVIEW_JS:
        path = VSCODE_DIR / name
        assert path.exists(), f"first-party webview script renamed or removed: {name}"
        text = path.read_text(encoding="utf-8")
        if name == "webview-ui.js":
            text = text.replace(PRE_STRIP_STATEMENT, "")
        for match in re.finditer(r"""\sstyle\s*=\s*[\\'"`]""", text):
            line = text.count("\n", 0, match.start()) + 1
            offenders.append(f"{name}:{line}")

    assert offenders == []


def test_intended_layout_lives_in_css_instead_of_inline_styles() -> None:
    css = WEBVIEW_CSS.read_text(encoding="utf-8")

    actions = re.search(
        r"\.settings-bark-base-url-actions\s*\{([^}]*)\}", css, flags=re.DOTALL
    )
    assert actions, "webview.css must define .settings-bark-base-url-actions"
    for declaration in (
        "display: flex",
        "flex-wrap: wrap",
        "gap: 8px",
        "margin-top: 4px",
    ):
        assert declaration in actions.group(1)

    countdown = re.search(
        r"\.settings-field input#feedbackCountdown\s*\{([^}]*)\}",
        css,
        flags=re.DOTALL,
    )
    assert countdown, "webview.css must size #feedbackCountdown"
    assert "max-width: 100px" in countdown.group(1)

    template = _html_template()
    assert 'class="settings-bark-base-url-actions">' in template
    assert re.search(r'<input type="number" id="feedbackCountdown"[^>]*>', template)
