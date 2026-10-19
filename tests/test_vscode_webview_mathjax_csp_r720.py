"""R720 · MathJax must work under the VS Code webview CSP.

The webview CSP has no ``'unsafe-inline'`` for styles, and MathJax 3.2.2 builds
four ``<style>`` elements when it starts and typesets its first formula (three
for its context menu through a plain ``document.createElement`` while
``defaultReady()`` runs, one SVG output sheet through the DOM adaptor's
``node()`` at the first render). With the policy refusing all four, the sheet
that hides the screen-reader MathML (``mjx-assistive-mml``) and the one that
makes display equations a centred block never applied: every formula appeared
twice, display math sat inline, and each MathJax load logged four
``style-src-elem`` violations (reproduced in real Chromium with the real
generated webview HTML).

The fix has three parts that must stay together:

* ``style-src`` trusts the page nonce (never ``'unsafe-inline'``; a nonce is
  never honoured for ``style`` *attributes*, so R719 stays valid);
* ``runWithStyleNonce`` tags the menu's raw ``createElement('style')`` calls
  while MathJax's ``defaultReady()`` runs, and ``addNonceToMathJaxStyleNodes``
  tags the SVG sheet created later through ``adaptor.node('style', ...)``;
* ``enableMenu: false``: the menu positions itself with ``style`` attributes
  that no nonce can unlock, so it opened at the bottom of the page and scrolled
  the panel. Without it the native webview context menu works as everywhere
  else.
"""

from __future__ import annotations

import functools
import json
import re
import subprocess
import textwrap
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
VSCODE_DIR = REPO_ROOT / "packages" / "vscode"
WEBVIEW_UI_JS = VSCODE_DIR / "webview-ui.js"
WEBVIEW_TS = VSCODE_DIR / "webview.ts"
MATHJAX_BUNDLE = VSCODE_DIR / "mathjax" / "tex-mml-svg.js"


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


def _webview_ui() -> str:
    return WEBVIEW_UI_JS.read_text(encoding="utf-8")


def _math_config_block() -> str:
    source = _webview_ui()
    start = source.index("window.MathJax = window.MathJax || {")
    end = source.index("window._mathJaxLoading = ", start)
    return source[start:end]


def _csp_policy() -> str:
    source = WEBVIEW_TS.read_text(encoding="utf-8")
    match = re.search(
        r'<meta http-equiv="Content-Security-Policy" content="([^"]*)"', source
    )
    assert match, "webview.ts must emit a Content-Security-Policy meta tag"
    return match.group(1)


def _csp_directives() -> dict[str, list[str]]:
    directives: dict[str, list[str]] = {}
    for part in _csp_policy().split(";"):
        tokens = part.split()
        if tokens:
            directives[tokens[0]] = tokens[1:]
    return directives


@functools.cache
def _run_style_nonce_scenarios() -> dict:
    source = _webview_ui()
    run_src = _extract_function(source, "function runWithStyleNonce(")
    add_src = _extract_function(source, "function addNonceToMathJaxStyleNodes(")
    script = textwrap.dedent(
        """
        const [runSrc, addSrc] = JSON.parse(process.argv[1])
        const NONCE = 'N0NCE'
        function load(nonce, document, window) {
          return new Function(
            'document', 'window', 'CSP_NONCE',
            runSrc + '\\n' + addSrc +
              '\\nreturn { runWithStyleNonce, addNonceToMathJaxStyleNodes }'
          )(document, window, nonce)
        }
        function makeDocument(ownProperty) {
          const proto = {
            createElement(tag) {
              return {
                tag: String(tag),
                attrs: {},
                argc: arguments.length,
                self: this,
                setAttribute(name, value) { this.attrs[name] = value }
              }
            }
          }
          const doc = Object.create(proto)
          if (ownProperty) doc.createElement = proto.createElement
          return { doc, proto }
        }
        const hasOwn = (o, k) => Object.prototype.hasOwnProperty.call(o, k)
        const out = {}

        {
          const { doc, proto } = makeDocument(false)
          const api = load(NONCE, doc, {})
          const inside = {}
          const ret = api.runWithStyleNonce(() => {
            inside.style = doc.createElement('style').attrs
            inside.upper = doc.createElement('STYLE').attrs
            inside.div = doc.createElement('div').attrs
            inside.argc = doc.createElement('style', { is: 'x' }).argc
            inside.self = doc.createElement('style').self === doc
            const other = {}
            inside.otherSelf = doc.createElement.call(other, 'style').self === other
            return 'value'
          })
          out.inherited = {
            ret, inside,
            ownAfter: hasOwn(doc, 'createElement'),
            sameAsProto: doc.createElement === proto.createElement,
            after: doc.createElement('style').attrs
          }
        }
        {
          const { doc } = makeDocument(true)
          const original = doc.createElement
          const api = load(NONCE, doc, {})
          let inside = null
          api.runWithStyleNonce(() => { inside = doc.createElement('style').attrs })
          out.own = {
            inside,
            ownAfter: hasOwn(doc, 'createElement'),
            same: doc.createElement === original
          }
        }
        {
          const { doc, proto } = makeDocument(false)
          const api = load(NONCE, doc, {})
          let caught = null
          try {
            api.runWithStyleNonce(() => { throw new Error('boom') })
          } catch (e) { caught = e.message }
          out.throws = {
            caught,
            ownAfter: hasOwn(doc, 'createElement'),
            sameAsProto: doc.createElement === proto.createElement
          }
        }
        {
          const { doc, proto } = makeDocument(false)
          const api = load('', doc, {})
          let wrapped = null
          const ret = api.runWithStyleNonce(() => {
            wrapped = doc.createElement !== proto.createElement
            return 7
          })
          out.noNonce = { ret, wrapped, style: doc.createElement('style').attrs }
        }
        {
          const adaptor = {
            node(kind, def, children, ns) {
              return {
                kind, def, children, ns,
                self: this,
                attrs: {},
                setAttribute(name, value) { this.attrs[name] = value }
              }
            }
          }
          const api = load(NONCE, {}, { MathJax: { startup: { adaptor } } })
          api.addNonceToMathJaxStyleNodes()
          const style = adaptor.node('style', { id: 'MJX' }, ['css'], 'ns')
          const svg = adaptor.node('svg', { id: 'x' })
          const other = {}
          out.adaptor = {
            style: style.attrs,
            svg: svg.attrs,
            forwarded: [style.def.id, style.children[0], style.ns],
            self: style.self === adaptor,
            otherSelf: adaptor.node.call(other, 'style').self === other
          }
        }
        {
          const adaptor = {
            node() { return { attrs: {}, setAttribute(k, v) { this.attrs[k] = v } } }
          }
          const original = adaptor.node
          load('', {}, { MathJax: { startup: { adaptor } } }).addNonceToMathJaxStyleNodes()
          out.adaptorNoNonce = { untouched: adaptor.node === original }
        }
        {
          const results = []
          for (const win of [
            {},
            { MathJax: {} },
            { MathJax: { startup: {} } },
            { MathJax: { startup: { adaptor: {} } } },
            { MathJax: { startup: { adaptor: { node: 1 } } } }
          ]) {
            try {
              load(NONCE, {}, win).addNonceToMathJaxStyleNodes()
              results.push('ok')
            } catch (e) { results.push('threw:' + e.message) }
          }
          out.missing = results
        }
        process.stdout.write(JSON.stringify(out))
        """
    )
    result = subprocess.run(
        ["node", "-e", script, json.dumps([run_src, add_src])],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


def test_csp_style_src_trusts_the_page_nonce_but_never_unsafe_inline() -> None:
    directives = _csp_directives()

    assert directives["style-src"] == ["${cspSource}", "'nonce-${nonce}'"]
    assert directives["script-src"] == ["'nonce-${nonce}'"]
    assert directives["default-src"] == ["'none'"]
    assert "unsafe-inline" not in _csp_policy()
    assert "unsafe-eval" not in _csp_policy()


def test_mathjax_ready_hook_installs_both_nonce_hooks_in_order() -> None:
    block = _math_config_block()

    call = "runWithStyleNonce(() => MathJax.startup.defaultReady())"
    assert call in block
    assert block.count("defaultReady()") == 1
    assert (
        block.index(call)
        < block.index("addNonceToMathJaxStyleNodes()")
        < block.index("_mathJaxPendingElements")
    )


def test_mathjax_context_menu_is_off_in_the_webview() -> None:
    block = _math_config_block()

    options = block[block.index("options: {") :]
    assert "enableMenu: false" in options[: options.index("}")]


def test_style_nonce_hooks_tag_style_elements_only() -> None:
    out = _run_style_nonce_scenarios()

    inherited = out["inherited"]
    assert inherited["ret"] == "value"
    assert inherited["inside"]["style"] == {"nonce": "N0NCE"}
    assert inherited["inside"]["upper"] == {"nonce": "N0NCE"}
    assert inherited["inside"]["div"] == {}
    assert inherited["inside"]["argc"] == 2
    assert inherited["inside"]["self"] is True
    assert inherited["inside"]["otherSelf"] is True

    adaptor = out["adaptor"]
    assert adaptor["style"] == {"nonce": "N0NCE"}
    assert adaptor["svg"] == {}
    assert adaptor["forwarded"] == ["MJX", "css", "ns"]
    assert adaptor["self"] is True
    assert adaptor["otherSelf"] is True


def test_create_element_is_restored_exactly_after_the_callback() -> None:
    out = _run_style_nonce_scenarios()

    inherited = out["inherited"]
    assert inherited["ownAfter"] is False
    assert inherited["sameAsProto"] is True
    assert inherited["after"] == {}

    own = out["own"]
    assert own["inside"] == {"nonce": "N0NCE"}
    assert own["ownAfter"] is True
    assert own["same"] is True

    throws = out["throws"]
    assert throws["caught"] == "boom"
    assert throws["ownAfter"] is False
    assert throws["sameAsProto"] is True


def test_hooks_are_inert_without_a_nonce_or_an_adaptor() -> None:
    out = _run_style_nonce_scenarios()

    assert out["noNonce"] == {"ret": 7, "wrapped": False, "style": {}}
    assert out["adaptorNoNonce"] == {"untouched": True}
    assert out["missing"] == ["ok"] * 5


def test_vendored_mathjax_bundle_is_the_audited_build() -> None:
    bundle = MATHJAX_BUNDLE.read_text(encoding="utf-8")

    assert 'e.VERSION="3.2.2"' in bundle, (
        "MathJax was upgraded: re-audit which <style> elements it creates "
        "(R720) in a real browser with the webview CSP before trusting the hooks"
    )
    assert bundle.count('createElement("style")') == 1, (
        "MathJax creates style elements through a new raw createElement path"
    )
    assert 'STYLESHEETID="MJX-SVG-styles"' in bundle
    assert "enableMenu:!0" in bundle
