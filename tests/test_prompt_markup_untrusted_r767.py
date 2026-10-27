"""R767 regression coverage: the Web UI never inserts the prompt as raw HTML.

The page used to paint ``config.prompt_html`` (HTML the server produced with
Python-Markdown, which passes raw HTML through) with ``innerHTML`` and only
about 100 ms later replaced it with the client render, which drops raw HTML.
In that window a prompt such as ``<meta http-equiv="refresh" ...>`` navigated
the approval page to another site. The first paint now goes through the same
client-side Markdown renderer as the multi-task view, both renderers fall back
to plain text instead of raw HTML when Markdown cannot be rendered, and the
first paint yields to a render that already owns the element so it cannot paint
a stale prompt over a newer one.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
STATIC_JS = REPO_ROOT / "src" / "ai_intervention_agent" / "static" / "js"
APP_JS = STATIC_JS / "app.js"
MULTI_TASK_JS = STATIC_JS / "multi_task.js"

HOSTILE = '<meta http-equiv="refresh" content="0;url=http://evil.test/"> approve?'

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


def _run_node(script: str) -> str:
    proc = subprocess.run(
        ["node", "-e", script],
        check=False,
        capture_output=True,
        text=True,
        timeout=20,
    )
    if proc.returncode != 0:
        raise AssertionError(
            f"node exited {proc.returncode}\nstdout={proc.stdout!r}\nstderr={proc.stderr!r}"
        )
    return proc.stdout


_HARNESS = r"""
const vm = require('vm');
const writes = [];
const tempHtml = [];
const warnings = [];
const frames = [];

function makeFragment() {
  return {
    isFragment: true,
    kids: [],
    appendChild(node) {
      if (node.parent) node.parent.kids.splice(node.parent.kids.indexOf(node), 1);
      node.parent = this;
      this.kids.push(node);
      return node;
    },
  };
}

function makeScratchDiv() {
  const div = { kids: [] };
  Object.defineProperty(div, 'innerHTML', {
    set(value) {
      tempHtml.push(value);
      this.kids = [{ html: value, parent: div }];
    },
  });
  Object.defineProperty(div, 'firstChild', {
    get() {
      return this.kids.length ? this.kids[0] : null;
    },
  });
  return div;
}

function makeElement() {
  const element = {
    dataset: {},
    childNodes: [],
    removeAttribute() {},
    appendChild(child) {
      if (child && child.isFragment) {
        for (const kid of child.kids.splice(0)) this.childNodes.push(kid);
        writes.push(['append-fragment']);
      } else {
        this.childNodes.push(child);
      }
      return child;
    },
  };
  Object.defineProperty(element, 'textContent', {
    get() {
      return this._text === undefined ? '' : this._text;
    },
    set(value) {
      this._text = value;
      this.childNodes = value ? [{ text: value }] : [];
      writes.push(['text', value]);
    },
  });
  Object.defineProperty(element, 'innerHTML', {
    get() {
      return '';
    },
    set(value) {
      writes.push(['html', value]);
      this.childNodes = [];
    },
  });
  return element;
}

const target = makeElement();
const sandbox = {
  console: {
    warn(...args) { warnings.push(args.map(String).join(' ')); },
    error() {},
    debug() {},
    log() {},
    info() {},
  },
  document: {
    createDocumentFragment: () => makeFragment(),
    createElement: () => makeScratchDiv(),
    getElementById: (id) => (id === 'description' ? target : null),
  },
  window: {},
  t: (key) => key,
  processCodeBlocks() {},
  processStrikethrough() {},
  processLinks() {},
  processPromptImages() {},
  enablePromptImageZoom() {},
  _debugLog() {},
  _scheduleNextFrame(callback) { frames.push(callback); },
};
vm.createContext(sandbox);
vm.runInContext(FUNCTION_SOURCE, sandbox);
const HOSTILE = HOSTILE_JSON;

function runFrames() {
  while (frames.length) frames.shift()();
}

function report(extra) {
  process.stdout.write(JSON.stringify(Object.assign({
    writes, tempHtml, warnings, dataset: target.dataset,
  }, extra || {})));
}
"""


def _case(function_source: str, body: str) -> dict:
    script = _HARNESS.replace("FUNCTION_SOURCE", json.dumps(function_source)).replace(
        "HOSTILE_JSON", json.dumps(HOSTILE)
    )
    script += "\n(async () => {\n" + textwrap.indent(textwrap.dedent(body), "  ")
    script += (
        "\n})().catch((e) => { console.error(e && e.stack || e); process.exit(1); });\n"
    )
    return json.loads(_run_node(script))


def _render_markdown_source() -> str:
    return _extract_function(
        APP_JS.read_text(encoding="utf-8"), "function renderMarkdownContent("
    )


def _update_description_source() -> str:
    return _extract_function(
        MULTI_TASK_JS.read_text(encoding="utf-8"),
        "async function updateDescriptionDisplay(",
    )


def test_app_js_no_longer_reads_the_server_rendered_prompt_html() -> None:
    source = APP_JS.read_text(encoding="utf-8")

    assert "prompt_html" not in source
    load_config = _extract_function(source, "async function loadConfig(")
    assert (
        "renderMarkdownContent(descriptionElement, config.prompt, true)" in load_config
    )


@needs_node
def test_markdown_mode_falls_back_to_text_when_marked_is_missing() -> None:
    result = _case(
        _render_markdown_source(),
        """
        sandbox.renderMarkdownContent(target, HOSTILE, true);
        runFrames();
        report();
        """,
    )

    assert result["writes"] == [["text", HOSTILE]]
    assert result["tempHtml"] == []
    assert result["dataset"] == {"renderedContent": HOSTILE, "renderedPrompt": HOSTILE}


@needs_node
def test_markdown_mode_falls_back_to_text_when_marked_throws() -> None:
    result = _case(
        _render_markdown_source(),
        """
        sandbox.marked = { parse() { throw new Error('boom'); } };
        sandbox.renderMarkdownContent(target, HOSTILE, true);
        runFrames();
        report();
        """,
    )

    assert result["writes"] == [["text", HOSTILE]]
    assert result["tempHtml"] == []
    assert result["warnings"] == ["marked.js parse failed: Error: boom"]


@needs_node
def test_markdown_mode_falls_back_to_text_when_restoring_math_throws() -> None:
    result = _case(
        _render_markdown_source(),
        """
        sandbox.marked = { parse: (text) => '<p>' + text + '</p>' };
        sandbox.window.protectMathDelimiters = (text) => ({ text, segments: ['S'] });
        sandbox.window.restoreMathDelimiters = () => { throw new Error('restore'); };
        sandbox.renderMarkdownContent(target, 'x', true);
        runFrames();
        report();
        """,
    )

    assert result["writes"] == [["text", "x"]]
    assert result["tempHtml"] == []


@needs_node
def test_markdown_mode_renders_the_parsed_html_and_records_the_prompt() -> None:
    result = _case(
        _render_markdown_source(),
        """
        sandbox.marked = { parse: (text) => '<p>' + text + '</p>' };
        sandbox.window.protectMathDelimiters = (text) => ({ text: text + '!', segments: ['S'] });
        sandbox.window.restoreMathDelimiters = (html, segments) => html + '|' + segments.join(',');
        sandbox.renderMarkdownContent(target, 'hello', true);
        runFrames();
        report();
        """,
    )

    assert result["tempHtml"] == ["<p>hello!</p>|S"]
    assert result["writes"] == [["html", ""], ["append-fragment"]]
    assert result["dataset"] == {"renderedContent": "hello", "renderedPrompt": "hello"}


@needs_node
@pytest.mark.parametrize("owner", ["hello", "a newer prompt"])
def test_first_paint_yields_to_a_render_that_already_owns_the_element(
    owner: str,
) -> None:
    result = _case(
        _render_markdown_source(),
        f"""
        sandbox.marked = {{ parse: (text) => '<p>' + text + '</p>' }};
        target.dataset.renderedPrompt = {json.dumps(owner)};
        target.childNodes = [{{ html: 'live' }}];
        sandbox.renderMarkdownContent(target, 'hello', true);
        runFrames();
        report();
        """,
    )

    assert result["writes"] == []
    assert result["tempHtml"] == []
    assert result["dataset"] == {"renderedPrompt": owner}


@needs_node
def test_first_paint_renders_into_an_element_that_was_emptied() -> None:
    result = _case(
        _render_markdown_source(),
        """
        sandbox.marked = { parse: (text) => '<p>' + text + '</p>' };
        target.dataset.renderedPrompt = 'older';
        sandbox.renderMarkdownContent(target, 'hello', true);
        runFrames();
        report();
        """,
    )

    assert result["tempHtml"] == ["<p>hello</p>"]
    assert result["dataset"] == {"renderedPrompt": "hello", "renderedContent": "hello"}


@needs_node
def test_html_mode_keeps_its_contract_for_trusted_callers() -> None:
    result = _case(
        _render_markdown_source(),
        """
        target.dataset.renderedPrompt = 'owned by the multi-task view';
        target.childNodes = [{ html: 'live' }];
        sandbox.renderMarkdownContent(target, '<b>x</b>', false);
        runFrames();
        report();
        """,
    )

    assert result["tempHtml"] == ["<b>x</b>"]
    assert result["dataset"] == {
        "renderedContent": "<b>x</b>",
        "renderedPrompt": "owned by the multi-task view",
    }


@needs_node
def test_multi_task_render_falls_back_to_text_when_marked_is_missing() -> None:
    result = _case(
        _update_description_source(),
        """
        await sandbox.updateDescriptionDisplay(HOSTILE);
        report();
        """,
    )

    assert result["writes"] == [["text", HOSTILE]]
    assert result["dataset"] == {"renderedPrompt": HOSTILE}


@needs_node
def test_multi_task_render_falls_back_to_text_when_marked_throws() -> None:
    result = _case(
        _update_description_source(),
        """
        sandbox.marked = { parse() { throw new Error('boom'); } };
        await sandbox.updateDescriptionDisplay(HOSTILE);
        report();
        """,
    )

    assert result["writes"] == [["text", HOSTILE]]
    assert result["warnings"] == ["marked.js parse failed: Error: boom"]


@needs_node
def test_multi_task_render_falls_back_to_text_when_restoring_math_throws() -> None:
    result = _case(
        _update_description_source(),
        """
        sandbox.marked = { parse: (text) => '<p>' + text + '</p>' };
        sandbox.window.protectMathDelimiters = (text) => ({ text, segments: ['S'] });
        sandbox.window.restoreMathDelimiters = () => { throw new Error('restore'); };
        await sandbox.updateDescriptionDisplay('x');
        report();
        """,
    )

    assert result["writes"] == [["text", "x"]]


@needs_node
def test_multi_task_render_inserts_parsed_markdown_as_html() -> None:
    result = _case(
        _update_description_source(),
        """
        sandbox.marked = { parse: (text) => '<p>' + text + '</p>' };
        await sandbox.updateDescriptionDisplay('hello');
        report();
        """,
    )

    assert result["writes"] == [["html", "<p>hello</p>"]]
    assert result["dataset"] == {"renderedPrompt": "hello"}
