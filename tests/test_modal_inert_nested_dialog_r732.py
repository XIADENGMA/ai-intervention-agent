"""R732: an open dialog is never inside the inert subtree, wherever it sits.

``inert`` is inherited: an element is inert when it, or any ancestor, carries
the attribute. While a dialog is open the page behind it is made inert, and the
helper that does so (``_setContainerSiblingsInert`` in ``app.js`` and
``settings-manager.js``) used to mark only the direct children of
``.container`` except the dialog. ``#settings-panel`` is a direct child, so it
worked; ``#code-paste-panel`` sits two levels deeper
(``.container > #content-container > .feedback-group``), so its ancestor
``#content-container`` was made inert and, with it, the dialog itself: focus
stayed on ``<body>``, typing did nothing, and the Insert button could not be
clicked. The earlier invariants (R240, R244, R245) read the source text and so
could not see it.

This test runs the shipped helpers against the real template: the template is
parsed into an element tree, a minimal DOM is built from it in Node, and for
every ``role="dialog"`` it checks that

* the dialog and everything above it stay interactive,
* everything else under ``.container`` is inert (nothing behind the dialog can
  be reached), and
* closing the dialog leaves nothing inert.

A synthetic, deeply nested dialog keeps the property covered even if the
template changes shape.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import textwrap
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
STATIC_JS = REPO_ROOT / "src" / "ai_intervention_agent" / "static" / "js"
WEB_UI_HTML = REPO_ROOT / "src" / "ai_intervention_agent" / "templates" / "web_ui.html"
APP_JS = STATIC_JS / "app.js"
SETTINGS_JS = STATIC_JS / "settings-manager.js"

_VOID_TAGS = frozenset(
    {
        "area",
        "base",
        "br",
        "col",
        "embed",
        "hr",
        "img",
        "input",
        "link",
        "meta",
        "param",
        "source",
        "track",
        "wbr",
    }
)

pytestmark = pytest.mark.skipif(
    shutil.which("node") is None, reason="node runtime unavailable"
)


def _new_node(tag: str, attrs: dict[str, str | None]) -> dict[str, Any]:
    return {
        "tag": tag,
        "id": attrs.get("id"),
        "cls": attrs.get("class") or "",
        "role": attrs.get("role"),
        "children": [],
    }


class _TreeBuilder(HTMLParser):
    """Builds a nested element tree (elements only, no text)."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = _new_node("#root", {})
        self._stack: list[dict[str, Any]] = [self.root]

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        node = _new_node(tag, dict(attrs))
        self._stack[-1]["children"].append(node)
        if tag not in _VOID_TAGS:
            self._stack.append(node)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._stack[-1]["children"].append(_new_node(tag, dict(attrs)))

    def handle_endtag(self, tag: str) -> None:
        for index in range(len(self._stack) - 1, 0, -1):
            if self._stack[index]["tag"] == tag:
                del self._stack[index:]
                return


def _template_tree() -> dict[str, Any]:
    html = WEB_UI_HTML.read_text(encoding="utf-8")
    html = re.sub(r"\{\{.*?\}\}", "PH", html, flags=re.DOTALL)
    html = re.sub(r"\{%.*?%\}", "", html, flags=re.DOTALL)
    builder = _TreeBuilder()
    builder.feed(html)
    return builder.root


def _block_from(source: str, marker: str) -> str:
    start = source.find(marker)
    assert start != -1, f"cannot find {marker!r}"
    depth = 0
    index = source.find("{", start)
    assert index != -1
    while index < len(source):
        char = source[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return source[start : index + 1]
        index += 1
    raise AssertionError(f"unbalanced braces after {marker!r}")


def _app_helper_source() -> str:
    source = APP_JS.read_text(encoding="utf-8")
    return "\n".join(
        [
            _block_from(source, "function _safelySetInert("),
            _block_from(source, "function _setContainerSiblingsInert("),
        ]
    )


def _settings_helper_source() -> str:
    source = SETTINGS_JS.read_text(encoding="utf-8")
    methods = "\n".join(
        [
            _block_from(source, "_safelySetInert(el, value) {"),
            _block_from(source, "_setContainerSiblingsInert(openModalEl, value) {"),
        ]
    )
    return f"class Holder {{\n{methods}\n}}"


_NODE_HARNESS = r"""
const vm = require('vm');
const template = __TEMPLATE__;
const appHelpers = __APP_HELPERS__;
const settingsHelpers = __SETTINGS_HELPERS__;

function build(spec, parent) {
  const node = {
    tagName: String(spec.tag).toUpperCase(),
    id: spec.id || '',
    className: spec.cls || '',
    role: spec.role || null,
    parentElement: parent,
    children: [],
    _inert: false,
    get inert() { return this._inert; },
    set inert(value) { this._inert = Boolean(value); },
    setAttribute(name) { if (name === 'inert') this._inert = true; },
    removeAttribute(name) { if (name === 'inert') this._inert = false; },
    contains(other) {
      for (let n = other; n; n = n.parentElement) if (n === this) return true;
      return false;
    },
  };
  node.children = spec.children.map((child) => build(child, node));
  return node;
}

function walk(node, visit) {
  visit(node);
  for (const child of node.children) walk(child, visit);
}

function label(node) {
  const names = [];
  for (let n = node; n && n.tagName !== '#ROOT'; n = n.parentElement) {
    names.unshift(n.id ? '#' + n.id : n.tagName.toLowerCase() + (n.className ? '.' + String(n.className).split(' ')[0] : ''));
  }
  return names.join(' > ');
}

function effectivelyInert(node) {
  for (let n = node; n; n = n.parentElement) if (n._inert) return true;
  return false;
}

function hasClass(node, name) {
  return String(node.className).split(/\s+/).includes(name);
}

function run(kind, rootSpec) {
  const root = build(rootSpec, null);
  const all = [];
  walk(root, (n) => all.push(n));
  const container = all.find((n) => hasClass(n, 'container'));
  if (!container) throw new Error('no .container element in the tree');
  const dialogs = all.filter((n) => n.role === 'dialog');
  const sandbox = { document: { querySelector: (sel) => (sel === '.container' ? container : null) } };
  vm.createContext(sandbox);
  let call;
  if (kind === 'app') {
    vm.runInContext(appHelpers, sandbox);
    call = (dialog, value) => sandbox._setContainerSiblingsInert(dialog, value);
  } else {
    vm.runInContext(settingsHelpers + '\nthis.__holder = new Holder();', sandbox);
    call = (dialog, value) => sandbox.__holder._setContainerSiblingsInert(dialog, value);
  }
  const report = [];
  for (const dialog of dialogs) {
    call(dialog, true);
    const inside = [];
    walk(container, (n) => inside.push(n));
    const reachable = inside.filter(
      (n) => n !== container && !n.contains(dialog) && !dialog.contains(n) && !effectivelyInert(n),
    ).map(label);
    const blockedPath = [];
    for (let n = dialog; n && n !== container; n = n.parentElement) {
      if (n._inert) blockedPath.push(label(n));
    }
    const dialogInert = effectivelyInert(dialog);
    const insideDialogInert = [];
    walk(dialog, (n) => { if (effectivelyInert(n)) insideDialogInert.push(label(n)); });
    call(dialog, false);
    const leftover = [];
    walk(root, (n) => { if (n._inert) leftover.push(label(n)); });
    report.push({
      dialog: dialog.id || label(dialog),
      depth: (() => { let d = 0; for (let n = dialog; n && n !== container; n = n.parentElement) d += 1; return d; })(),
      dialogInert,
      blockedPath,
      insideDialogInert,
      reachable,
      leftover,
    });
  }
  return report;
}

function synthetic() {
  const el = (tag, cls, children, extra) => Object.assign({ tag, id: null, cls: cls || '', role: null, children: children || [] }, extra || {});
  return el('#root', '', [
    el('body', '', [
      el('div', 'container', [
        el('header', '', [el('button', '')]),
        el('div', 'content', [
          el('div', 'group-a', [el('textarea', ''), el('button', '')]),
          el('div', 'group-b', [
            el('div', 'group-c', [
              el('div', '', [el('p', '')]),
              el('div', 'deep-dialog', [el('button', ''), el('textarea', '')], { id: 'deep-dialog', role: 'dialog' }),
              el('div', '', [el('button', '')]),
            ]),
            el('div', '', [el('button', '')]),
          ]),
        ]),
        el('footer', '', [el('a', '')]),
        el('div', 'direct-dialog', [el('button', '')], { id: 'direct-dialog', role: 'dialog' }),
      ]),
      el('div', 'toast-host', []),
    ]),
  ]);
}

const outsideDialog = (() => {
  const spec = synthetic();
  const body = spec.children[0];
  body.children.push({ tag: 'div', id: 'outside-dialog', cls: 'outside', role: 'dialog', children: [{ tag: 'button', id: null, cls: '', role: null, children: [] }] });
  return spec;
})();

process.stdout.write(JSON.stringify({
  appTemplate: run('app', template),
  settingsTemplate: run('settings', template),
  appSynthetic: run('app', synthetic()),
  settingsSynthetic: run('settings', synthetic()),
  appOutside: run('app', outsideDialog),
  settingsOutside: run('settings', outsideDialog),
}));
"""


def _run_harness() -> dict[str, list[dict[str, Any]]]:
    script = (
        textwrap.dedent(_NODE_HARNESS)
        .replace("__TEMPLATE__", json.dumps(_template_tree()))
        .replace("__APP_HELPERS__", json.dumps(_app_helper_source()))
        .replace("__SETTINGS_HELPERS__", json.dumps(_settings_helper_source()))
    )
    proc = subprocess.run(
        ["node", "-e", script],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if proc.returncode != 0:
        raise AssertionError(
            f"node exited {proc.returncode}\nstdout={proc.stdout!r}\nstderr={proc.stderr!r}"
        )
    return json.loads(proc.stdout)


@pytest.fixture(scope="module")
def reports() -> dict[str, list[dict[str, Any]]]:
    return _run_harness()


def _describe(entry: dict[str, Any]) -> str:
    return json.dumps(entry, ensure_ascii=False, indent=1)


def test_template_still_has_the_dialogs_this_test_is_about(
    reports: dict[str, list[dict[str, Any]]],
) -> None:
    ids = {entry["dialog"] for entry in reports["appTemplate"]}
    assert {"code-paste-panel", "settings-panel"} <= ids, ids


@pytest.mark.parametrize("helper", ["app", "settings"])
@pytest.mark.parametrize("shape", ["Template", "Synthetic", "Outside"])
def test_open_dialog_stays_interactive_and_the_page_behind_it_does_not(
    reports: dict[str, list[dict[str, Any]]], helper: str, shape: str
) -> None:
    entries = reports[f"{helper}{shape}"]
    assert entries, f"no dialog found in the {shape.lower()} tree"
    for entry in entries:
        assert entry["dialogInert"] is False, (
            f"the open dialog is inert ({helper}, {shape}):\n{_describe(entry)}"
        )
        assert entry["blockedPath"] == [], (
            f"an ancestor of the open dialog is inert ({helper}, {shape}):\n"
            f"{_describe(entry)}"
        )
        assert entry["insideDialogInert"] == [], (
            f"something inside the open dialog is inert ({helper}, {shape}):\n"
            f"{_describe(entry)}"
        )
        assert entry["reachable"] == [], (
            f"something behind the open dialog is still reachable ({helper}, "
            f"{shape}):\n{_describe(entry)}"
        )


@pytest.mark.parametrize("helper", ["app", "settings"])
@pytest.mark.parametrize("shape", ["Template", "Synthetic", "Outside"])
def test_closing_the_dialog_leaves_nothing_inert(
    reports: dict[str, list[dict[str, Any]]], helper: str, shape: str
) -> None:
    for entry in reports[f"{helper}{shape}"]:
        assert entry["leftover"] == [], (
            f"inert is left behind after closing ({helper}, {shape}):\n"
            f"{_describe(entry)}"
        )


def test_the_synthetic_tree_really_exercises_nesting(
    reports: dict[str, list[dict[str, Any]]],
) -> None:
    depths = {entry["dialog"]: entry["depth"] for entry in reports["appSynthetic"]}
    assert depths["direct-dialog"] == 1
    assert depths["deep-dialog"] >= 4, depths
