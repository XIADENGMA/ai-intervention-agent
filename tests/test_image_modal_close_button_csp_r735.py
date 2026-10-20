"""R735 — the image preview's × button closes it without an inline event handler.

Why this exists
---------------
The Web UI ships ``script-src 'self' 'nonce-…'`` (no ``'unsafe-inline'``), so
an inline ``onclick="…"`` attribute is never executed: Chromium logs
"Executing inline event handler violates the following Content Security
Policy directive" when the page loads, and the control does nothing.  The
image preview's × button (``<button class="image-modal-close"
onclick="closeImageModal()">``) was the only such attribute in the project:
clicking it, or pressing Enter / Space on the focused button, left the
preview open, so only ``Esc`` and a click on the backdrop closed it.

The fix wires the button from ``_initImageModalOnce`` (once, behind the same
``data-aiia-inited`` guard as the backdrop handler) and removes the attribute.

Pattern: C (runtime) — the real ``image-upload.js`` in a Node ``vm`` with a DOM
that really dispatches (and bubbles) events, plus a template lint.
"""

from __future__ import annotations

import json
import re
import unittest
from html.parser import HTMLParser
from pathlib import Path

from tests.test_image_upload_modal_lifecycle_r452 import (
    IMAGE_UPLOAD_JS,
    _node_available,
    _run_node,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = REPO_ROOT / "src" / "ai_intervention_agent" / "templates" / "web_ui.html"


def _template_start_tags() -> list[tuple[str, dict[str, str | None]]]:
    """Every start tag of the real template as ``(tag, {attribute: value})``."""
    text = TEMPLATE.read_text(encoding="utf-8")
    text = re.sub(r"\{\{.*?\}\}", "PH", text, flags=re.DOTALL)
    text = re.sub(r"\{%.*?%\}", "", text, flags=re.DOTALL)

    class Collector(HTMLParser):
        def __init__(self) -> None:
            super().__init__(convert_charrefs=True)
            self.tags: list[tuple[str, dict[str, str | None]]] = []

        def handle_starttag(
            self, tag: str, attrs: list[tuple[str, str | None]]
        ) -> None:
            self.tags.append((tag, dict(attrs)))

        def handle_startendtag(
            self, tag: str, attrs: list[tuple[str, str | None]]
        ) -> None:
            self.tags.append((tag, dict(attrs)))

    collector = Collector()
    collector.feed(text)
    return collector.tags


def test_template_has_no_inline_event_handler_attributes() -> None:
    offenders = [
        f"<{tag} {name}=...>"
        for tag, attrs in _template_start_tags()
        for name in attrs
        if re.fullmatch(r"on[a-z]+", name)
    ]
    # ``script-src`` has no ``'unsafe-inline'``: such an attribute is dead code
    # that also logs a CSP violation on every page load.
    assert offenders == [], offenders


def test_template_close_button_is_a_labelled_button_inside_the_dialog() -> None:
    tags = _template_start_tags()
    dialog_index = next(
        index
        for index, (_tag, attrs) in enumerate(tags)
        if attrs.get("id") == "image-modal"
    )
    buttons = [
        attrs
        for _tag, attrs in tags[dialog_index + 1 :]
        if "image-modal-close" in (attrs.get("class") or "").split()
    ]
    assert len(buttons) == 1
    assert buttons[0].get("type") == "button"
    assert buttons[0].get("aria-label")


_HARNESS = r"""
const fs = require('fs');
const vm = require('vm');
const code = fs.readFileSync(__IMAGE_UPLOAD_JS__, 'utf8')
  + '\nglobalThis.__openImageModal = openImageModal;'
  + '\nglobalThis.__closeImageModal = closeImageModal;'
  + '\nglobalThis.__init = _initImageModalOnce;';

const documentListeners = [];
const documentRemoved = [];
const focusLog = [];
const showRemovals = { count: 0 };

function makeNode(id, parent) {
  const listeners = {};
  const classes = new Set();
  const node = {
    id,
    parent,
    dataset: {},
    hidden: false,
    src: '',
    alt: '',
    textContent: '',
    style: {},
    classList: {
      add(name) { classes.add(name); },
      contains(name) { return classes.has(name); },
      remove(name) {
        if (name === 'show' && id === 'image-modal') showRemovals.count += 1;
        classes.delete(name);
      },
    },
    addEventListener(type, handler) {
      (listeners[type] = listeners[type] || []).push(handler);
    },
    removeEventListener() {},
    listenerCount(type) { return (listeners[type] || []).length; },
    // Dispatches like a browser: target first, then every ancestor.
    click(target) {
      const event = { type: 'click', target: target || node, preventDefault() {}, stopPropagation() {} };
      for (let current = event.target; current; current = current.parent) {
        event.currentTarget = current;
        for (const handler of (current.__listeners().click || []).slice()) handler(event);
      }
    },
    __listeners() { return listeners; },
    focus() {
      focusLog.push(id);
      sandbox.document.activeElement = node;
    },
    querySelector(selector) {
      if (selector === '.image-modal-close') return closeBtn;
      return null;
    },
    removeAttribute(name) { if (name === 'hidden') node.hidden = false; },
    setAttribute(name) { if (name === 'hidden') node.hidden = true; },
  };
  return node;
}

const body = makeNode('body', null);
const opener = makeNode('opener', body);
const modal = makeNode('image-modal', body);
modal.hidden = true;
const content = makeNode('image-modal-content', modal);
const picture = makeNode('modal-image', content);
const closeBtn = makeNode('image-modal-close', content);
const info = makeNode('modal-info', content);
const byId = { 'image-modal': modal, 'modal-image': picture, 'modal-info': info, opener };

const sandbox = {
  Array, Date, Error, JSON, Map, Math, Number, Object, Promise, RegExp, Set, String,
  Blob: function Blob() {},
  File: function File() {},
  FileList: function FileList() {},
  FileReader: function FileReader() {},
  URL: { createObjectURL() { return 'blob:test'; }, revokeObjectURL() {} },
  console: { debug() {}, error() {}, info() {}, log() {}, warn() {} },
  document: {
    activeElement: null,
    readyState: 'loading',
    addEventListener(type, handler) { documentListeners.push({ type, handler }); },
    removeEventListener(type, handler) { documentRemoved.push({ type, handler }); },
    contains(el) { return el === opener || el === closeBtn; },
    createElement(tag) { return makeNode(tag, null); },
    getElementById(id) { return Object.prototype.hasOwnProperty.call(byId, id) ? byId[id] : null; },
    querySelector(selector) { return selector === '.image-modal-close' ? closeBtn : null; },
  },
  module: { exports: {} },
  exports: {},
  navigator: {},
  requestAnimationFrame(fn) { return fn(); },
  setInterval() { return 1; },
  clearInterval() {},
  setTimeout(fn) { return { fn }; },
  clearTimeout() {},
  showStatus() {},
  t(key, params) { return params && params.name ? params.name + ':' + params.size : key; },
  window: null,
};
sandbox.window = sandbox;
sandbox.globalThis = sandbox;
sandbox.addEventListener = () => {};
vm.createContext(sandbox);
vm.runInContext(code, sandbox);

const state = () => ({
  open: modal.classList.contains('show') && !modal.hidden,
  closed: !modal.classList.contains('show') && modal.hidden,
  focusLog: focusLog.slice(),
  showRemovals: showRemovals.count,
  keydownRemoved: documentRemoved.filter((entry) => entry.type === 'keydown').length,
});

(async () => {
/*CASE*/
})().catch((err) => { console.error(err && err.stack ? err.stack : err); process.exit(1); });
"""


def _run_case(case_js: str) -> dict:
    script = _HARNESS.replace(
        "__IMAGE_UPLOAD_JS__", json.dumps(str(IMAGE_UPLOAD_JS))
    ).replace("/*CASE*/", case_js)
    return json.loads(_run_node(script))


_OPEN = """
  sandbox.document.activeElement = opener;
  sandbox.__init();
  sandbox.__openImageModal('data:image/png;base64,AAAA', 'p.png', 2048);
"""


@unittest.skipUnless(_node_available(), "node runtime unavailable")
def test_close_button_click_closes_the_dialog_and_hands_focus_back() -> None:
    outcome = _run_case(
        _OPEN
        + """
        const opened = state();
        closeBtn.click();
        process.stdout.write(JSON.stringify({ opened, closed: state() }));
        """
    )
    assert outcome["opened"]["open"] is True
    # Probe validity: focus moved to the button on open.
    assert outcome["opened"]["focusLog"] == ["image-modal-close"]
    closed = outcome["closed"]
    assert closed["closed"] is True
    # Full cleanup, not just hiding: keyboard handlers detached and focus
    # returned to the element that opened the preview.
    assert closed["keydownRemoved"] == 2
    assert closed["focusLog"] == ["image-modal-close", "opener"]


@unittest.skipUnless(_node_available(), "node runtime unavailable")
def test_each_close_path_runs_the_close_logic_exactly_once() -> None:
    outcome = _run_case(
        _OPEN
        + """
        const results = {};
        // The click on the button bubbles up to the dialog (target = button):
        // the backdrop handler must ignore it, so the logic runs once.
        closeBtn.click();
        results.button = state().showRemovals;
        sandbox.__openImageModal('data:image/png;base64,AAAA', 'p.png', 2048);
        modal.click(modal);
        results.backdrop = state().showRemovals - results.button;
        sandbox.__openImageModal('data:image/png;base64,AAAA', 'p.png', 2048);
        const before = state().showRemovals;
        picture.click();
        results.picture = state().showRemovals - before;
        results.stillOpen = state().open;
        content.click(content);
        results.content = state().showRemovals - before;
        results.stillOpenAfterContent = state().open;
        process.stdout.write(JSON.stringify(results));
        """
    )
    assert outcome == {
        "button": 1,
        "backdrop": 1,
        "picture": 0,
        "stillOpen": True,
        "content": 0,
        "stillOpenAfterContent": True,
    }


@unittest.skipUnless(_node_available(), "node runtime unavailable")
def test_repeated_init_wires_each_listener_once() -> None:
    outcome = _run_case(
        """
        sandbox.__init();
        sandbox.__init();
        sandbox.__init();
        process.stdout.write(JSON.stringify({
          button: closeBtn.listenerCount('click'),
          dialog: modal.listenerCount('click'),
          content: content.listenerCount('click'),
          picture: picture.listenerCount('click'),
        }));
        """
    )
    assert outcome == {"button": 1, "dialog": 1, "content": 0, "picture": 0}


@unittest.skipUnless(_node_available(), "node runtime unavailable")
def test_init_without_a_close_button_still_wires_the_backdrop() -> None:
    outcome = _run_case(
        """
        // A template without the button must not break the backdrop wiring.
        modal.querySelector = () => null;
        sandbox.document.querySelector = () => null;
        sandbox.__init();
        process.stdout.write(JSON.stringify({
          button: closeBtn.listenerCount('click'),
          dialog: modal.listenerCount('click'),
          inited: modal.dataset.aiiaInited,
        }));
        """
    )
    assert outcome == {"button": 0, "dialog": 1, "inited": "1"}
