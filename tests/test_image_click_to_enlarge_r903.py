"""R903: an image of the agent's message opens large when it is clicked.

TODO "界面优化 10" (the text is dictation noise around one clear request: "需要一个点击后查看大图的功能").  An agent can
put images into its message (``![chart](/abs/chart.png)``; the MCP server reads the file and the page gets
``/api/tasks/<id>/images/<n>``), and the Web UI and the VS Code panel both showed them at the width of the message and
nothing more: there was nothing to click.  The Web page had a viewer for the thumbnails of what the *user* attaches
(``openImageModal``), the panel had none, and the viewer of the page had a bug of its own that this change makes
reachable from every image of every message: an image taller than wide (a phone screenshot) was shown at its own size
and cut off by the window, with no way to see the rest, because ``max-height: 100%`` of a box that has no height of its
own is no limit at all.

Now:

* **Web page** (``app.js``, ``image-upload.js``, ``multi_task.js``, ``main.css``).  ``enablePromptImageZoom`` runs at
  both places that paint the message, after ``processPromptImages`` has decided which images stay and before the maths
  is typeset.  An image that stays becomes a button: ``role``, ``tabindex="0"``, an ``aria-label`` that names it,
  ``cursor: zoom-in``; click, Enter or Space (plain: a Ctrl/Cmd/Alt/Shift chord is somebody else's) opens it in the
  existing modal.  An image inside a link keeps doing what its link does; an image the browser could not load has
  nothing to show, so it is not offered (and loses the offer if the error comes late).  The caption says the pixels the
  browser read (``name (1920 × 1080 px)``) as soon as the image has loaded and, until then, the name alone; an
  attachment keeps its file size.  The modal lets go of the image when it closes, and a viewer opened from the message
  closes when the message is written again (an attachment's does not: it is not the message's).  The image now fits
  the window, tall or wide, and the caption is as wide as its text, not as wide as a narrow strip of an image.
* **VS Code panel** (``webview.ts``, ``webview-ui.js``, ``webview.css``).  The same marking for the images of the
  message and for the thumbnails of attachments, and a viewer of its own (``#imageViewer``, a modal dialog: it takes
  focus, keeps Tab on its two buttons, closes on Escape and on a click outside the image, and hands focus back).  The
  panel is narrow, so "to fit" is hardly larger than the message itself; what the viewer is for is the second state,
  the image at its own size, to scroll through.  A click on the image (the spot clicked ends up in the middle of the
  view) or the 1:1 button goes from one state to the other, and the button is off while there is nothing to enlarge.

The checks run the real source: the page's functions in Node against a small DOM, and the panel's block of
``webview-ui.js`` the same way; then the two stylesheets (what the new rules are, that the minified file the page
loads has them), the places that call the new functions (and in what order), the panel's markup, and the strings in
every locale.  The real Chrome and VS Code runs of this change are the other half.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

from tests.test_app_toast_runtime_r452 import _node_available, _run_node
from tests.test_options_unpin_r901 import PANEL_RULES, WEB_RULES, _merged
from tests.test_prompt_links_stay_out_of_the_page_r801 import _extract_function

REPO_ROOT = Path(__file__).resolve().parent.parent
PACKAGE = REPO_ROOT / "src" / "ai_intervention_agent"
STATIC = PACKAGE / "static"
APP_JS = STATIC / "js" / "app.js"
UPLOAD_JS = STATIC / "js" / "image-upload.js"
MULTI_TASK_JS = STATIC / "js" / "multi_task.js"
WEB_CSS = STATIC / "css" / "main.css"
WEB_MIN_CSS = STATIC / "css" / "main.min.css"
WEB_LOCALES = STATIC / "locales"
WEB_TEMPLATE = PACKAGE / "templates" / "web_ui.html"
VSCODE = REPO_ROOT / "packages" / "vscode"
PANEL_JS = VSCODE / "webview-ui.js"
PANEL_TS = VSCODE / "webview.ts"
PANEL_LOCALES = VSCODE / "locales"
PANEL_KEYS_DTS = VSCODE / "i18n-keys.d.ts"

PHONE = "@media (max-width: 768px)"
LOCALES = ["en", "zh-CN", "zh-TW", "_pseudo/pseudo"]

needs_node = pytest.mark.skipif(
    not _node_available(), reason="node runtime unavailable"
)


# ============================================================================== a small DOM for Node
DOM = r"""
const vm = require('vm');
const ORIGIN = 'http://127.0.0.1:8080';
const logs = { debug: [], warn: [], error: [] };
const docListeners = [];
const byId = new Map();
let activeElement = null;

function matches(el, sel) {
  let m;
  if ((m = /^\.([\w-]+)$/.exec(sel))) return el.classList.contains(m[1]);
  if ((m = /^([a-z]+)\[([\w-]+)\]$/.exec(sel))) return el.tagName === m[1].toUpperCase() && el.attrs.has(m[2]);
  if ((m = /^([a-z]+)$/.exec(sel))) return el.tagName === m[1].toUpperCase();
  throw new Error('fake DOM: unsupported selector ' + sel);
}
function find(root, sel, first) {
  const found = [];
  (function walk(node) {
    for (const child of node.children) {
      if (first && found.length) return;
      if (matches(child, sel)) found.push(child);
      walk(child);
    }
  })(root);
  return found;
}

class El {
  constructor(tag, attrs = {}) {
    this.tagName = tag.toUpperCase();
    this.attrs = new Map(
      Object.entries(attrs).filter(([k]) => k !== 'class').map(([k, v]) => [k, String(v)]),
    );
    this.listeners = [];
    this.children = [];
    this.parentNode = null;
    this.detached = false;
    this.dataset = {};
    this.textContent = '';
    this.disabled = false;
    this.complete = true;
    this.naturalWidth = 0;
    this.naturalHeight = 0;
    this.clientWidth = 0;
    this.clientHeight = 0;
    this.offsetLeft = 0;
    this.offsetTop = 0;
    this.offsetWidth = 0;
    this.offsetHeight = 0;
    this.scrollLeft = 0;
    this.scrollTop = 0;
    this.currentSrc = '';
    this.rect = { left: 0, top: 0, width: 0, height: 0 };
    this.focusCalls = 0;
    const classes = new Set(String(attrs.class || '').split(/\s+/).filter(Boolean));
    this.classList = {
      add: (...n) => n.forEach((x) => classes.add(x)),
      remove: (...n) => n.forEach((x) => classes.delete(x)),
      contains: (n) => classes.has(n),
      toggle: (n, force) => {
        const on = force === undefined ? !classes.has(n) : !!force;
        if (on) classes.add(n); else classes.delete(n);
        return on;
      },
    };
  }
  getAttribute(n) { return this.attrs.has(n) ? this.attrs.get(n) : null; }
  setAttribute(n, v) { this.attrs.set(n, String(v)); }
  removeAttribute(n) { this.attrs.delete(n); if (n === 'src' && this.onSrc) this.onSrc(this); }
  hasAttribute(n) { return this.attrs.has(n); }
  get src() { return this.attrs.has('src') ? this.attrs.get('src') : ''; }
  set src(v) { this.attrs.set('src', String(v)); if (this.onSrc) this.onSrc(this); }
  get alt() { return this.attrs.has('alt') ? this.attrs.get('alt') : ''; }
  set alt(v) { this.attrs.set('alt', String(v)); }
  appendChild(child) { child.parentNode = this; this.children.push(child); return child; }
  closest(sel) {
    if (sel !== 'a[href]') throw new Error('fake DOM: unsupported closest ' + sel);
    for (let n = this; n; n = n.parentNode) if (n.tagName === 'A' && n.attrs.has('href')) return n;
    return null;
  }
  querySelector(sel) { return find(this, sel, true)[0] || null; }
  querySelectorAll(sel) { return find(this, sel, false); }
  getBoundingClientRect() { return this.rect; }
  addEventListener(type, fn, options) {
    this.listeners.push({
      type, fn, once: !!(options && options.once), capture: options === true || !!(options && options.capture),
    });
  }
  removeEventListener(type, fn) {
    const i = this.listeners.findIndex((l) => l.type === type && l.fn === fn);
    if (i >= 0) this.listeners.splice(i, 1);
  }
  count(type) { return this.listeners.filter((l) => l.type === type).length; }
  focus() { activeElement = this; this.focusCalls += 1; }
}

const document = {
  readyState: 'complete',
  get activeElement() { return activeElement; },
  body: new El('body'),
  getElementById: (id) => byId.get(id) || null,
  querySelector: (sel) => find(document.body, sel, true)[0] || null,
  addEventListener(type, fn, options) {
    docListeners.push({ type, fn, capture: options === true || !!(options && options.capture) });
  },
  removeEventListener(type, fn, options) {
    const capture = options === true || !!(options && options.capture);
    const i = docListeners.findIndex((l) => l.type === type && l.fn === fn && l.capture === capture);
    if (i >= 0) docListeners.splice(i, 1);
  },
  contains: (el) => !!el && !el.detached,
};
const docCount = (type) => docListeners.filter((l) => l.type === type).length;

// One event, the way a browser walks it: the capture listeners of the document, the target and the
// elements around it, the document again.  A listener that was removed on the way is not called.
function fire(target, type, props = {}) {
  const event = Object.assign(
    {
      type, target, currentTarget: target, defaultPrevented: false, stopped: false,
      preventDefault() { this.defaultPrevented = true; },
      stopPropagation() { this.stopped = true; },
    },
    props,
  );
  const run = (list, owner, wanted) => {
    for (const l of list.slice()) {
      if (event.stopped) return;
      if (!list.includes(l) || l.type !== type || !wanted(l)) continue;
      if (l.once) list.splice(list.indexOf(l), 1);
      event.currentTarget = owner;
      l.fn.call(owner, event);
    }
  };
  run(docListeners, document, (l) => l.capture);
  for (let node = target; node && !event.stopped; node = node.parentNode) run(node.listeners, node, () => true);
  run(docListeners, document, (l) => !l.capture);
  return event;
}
const press = (target, key, props = {}) => fire(target, 'keydown', Object.assign({ key }, props));

const t = (key, params) => (params ? key + '|' + JSON.stringify(params) : key);
const consoleStub = {
  debug: (...a) => logs.debug.push(a.join(' ')),
  warn: (...a) => logs.warn.push(a.join(' ')),
  error: (...a) => logs.error.push(a.join(' ')),
  log() {}, info() {},
};

// What the browser makes of an image of the message
function mkImg(alt, opts = {}) {
  const img = new El('img', alt === null ? {} : { alt });
  img.attrs.set('src', '/api/tasks/t1/images/' + (opts.n === undefined ? 0 : opts.n));
  img.currentSrc = ORIGIN + img.attrs.get('src');
  img.complete = opts.complete !== false;
  img.naturalWidth = opts.w === undefined ? 1920 : opts.w;
  img.naturalHeight = opts.h === undefined ? 1080 : opts.h;
  return img;
}
function mkMessage(...images) {
  const box = new El('div');
  images.forEach((i) => box.appendChild(i));
  return box;
}
const done = (value) => { process.stdout.write(JSON.stringify(value === undefined ? null : value)); };
"""


def _slice(path: Path, start: str, end: str) -> str:
    source = path.read_text(encoding="utf-8")
    first = source.index(start)
    return source[first : source.index(end, first)]


def _run(code: str, setup: str, case_js: str) -> Any:
    script = (
        f"const CODE = {json.dumps(code)};\n"
        + DOM
        + setup
        + "\n(async () => {\n"
        + case_js
        + "\n})().catch((e) => { console.error((e && e.stack) || e); process.exit(1); });\n"
    )
    return json.loads(_run_node(script))


# ============================================================================== the Web page
WEB_SETUP = r"""
// the modal of web_ui.html
const modal = new El('div', { id: 'image-modal', class: 'image-modal', hidden: '' });
const modalImage = new El('img', { id: 'modal-image', alt: '' });
const modalInfo = new El('div', { id: 'modal-info' });
const closeButton = new El('button', { class: 'image-modal-close' });
modal.appendChild(closeButton);
document.body.appendChild(modal);
for (const el of [modal, modalImage, modalInfo]) byId.set(el.attrs.get('id'), el);

// the browser loads an image later, unless it has it already (``instant``)
const sizes = {};
modalImage.onSrc = (img) => {
  if (!img.hasAttribute('src')) { img.complete = true; img.naturalWidth = 0; img.naturalHeight = 0; return; }
  const entry = sizes[img.getAttribute('src')];
  if (entry && entry.instant) { img.complete = true; img.naturalWidth = entry.w; img.naturalHeight = entry.h; return; }
  img.complete = false; img.naturalWidth = 0; img.naturalHeight = 0;
};
const finishLoad = (src) => {
  const entry = sizes[src];
  modalImage.complete = true; modalImage.naturalWidth = entry.w; modalImage.naturalHeight = entry.h;
  fire(modalImage, 'load');
};

const page = { window: {}, document, console: consoleStub, t };
vm.createContext(page);
vm.runInContext(
  CODE + '\nthis.__state = () => ({ source: typeof _imageModalSource === "undefined" ? null : _imageModalSource, ' +
    'handlers: typeof _imageModalKeydownHandlersAttached === "undefined" ? null : _imageModalKeydownHandlersAttached });',
  page,
);
const modalOpen = () => modal.classList.contains('show');
const snapshot = () => ({
  open: modalOpen(),
  hidden: modal.hasAttribute('hidden'),
  src: modalImage.getAttribute('src'),
  alt: modalImage.getAttribute('alt'),
  info: modalInfo.textContent,
  focus: activeElement === closeButton ? 'close' : activeElement ? activeElement.tagName + ':' + activeElement.getAttribute('alt') : null,
  keydownListeners: docCount('keydown'),
  state: page.__state(),
});
"""


def _web_code(*, modal: bool = True) -> str:
    """The modal of ``image-upload.js`` and the message-image functions of ``app.js``: the real text."""
    app = _slice(APP_JS, "function openPromptImage(", "async function loadConfig(")
    if not modal:
        return app
    upload = _slice(
        UPLOAD_JS,
        "let _imageModalPreviouslyFocusedElement = null;",
        "function checkBrowserCompatibility(",
    )
    return upload + "\n" + app


def _web(case_js: str, *, modal: bool = True) -> Any:
    return _run(_web_code(modal=modal), WEB_SETUP, case_js)


@needs_node
class TestWebMessageImages:
    def test_an_image_of_the_message_becomes_a_button_that_names_itself(self) -> None:
        out = _web(
            """
            const named = mkImg('wide shot'), plain = mkImg(null, { n: 1 }), blank = mkImg('   ', { n: 2 });
            page.enablePromptImageZoom(mkMessage(named, plain, blank));
            const attrs = (img) => ({
              zoom: img.getAttribute('data-aiia-zoom'), tabindex: img.getAttribute('tabindex'),
              role: img.getAttribute('role'), label: img.getAttribute('aria-label'),
              click: img.count('click'), keydown: img.count('keydown'), error: img.count('error'),
            });
            done({ named: attrs(named), plain: attrs(plain), blank: attrs(blank) });
            """
        )
        named = out["named"]
        assert named["zoom"] == "1"
        assert named["tabindex"] == "0"
        assert named["role"] == "button"
        assert named["label"] == 'page.imageEnlargeNamed|{"name":"wide shot"}'
        assert (named["click"], named["keydown"], named["error"]) == (1, 1, 1)
        # no alt text, or only blanks: the label is the plain one, never "View larger image: "
        assert out["plain"]["label"] == "page.imageEnlarge"
        assert out["blank"]["label"] == "page.imageEnlarge"

    def test_a_second_pass_changes_nothing(self) -> None:
        out = _web(
            """
            const img = mkImg('a'), message = mkMessage(img);
            page.enablePromptImageZoom(message);
            const first = JSON.stringify([...img.attrs.entries()]);
            page.enablePromptImageZoom(message);
            done({ same: first === JSON.stringify([...img.attrs.entries()]),
                   click: img.count('click'), keydown: img.count('keydown'), error: img.count('error') });
            """
        )
        assert out == {"same": True, "click": 1, "keydown": 1, "error": 1}

    def test_an_image_inside_a_link_keeps_doing_what_its_link_does(self) -> None:
        out = _web(
            """
            const badge = mkImg('badge'), link = new El('a', { href: 'https://example.com' });
            link.appendChild(badge);
            // an anchor without ``href`` is no link: its image is still offered
            const bare = mkImg('bare', { n: 1 }), anchor = new El('a', { name: 'top' });
            anchor.appendChild(bare);
            page.enablePromptImageZoom(mkMessage(link, anchor));
            done({ badge: badge.getAttribute('data-aiia-zoom'), badgeClick: badge.count('click'),
                   bare: bare.getAttribute('data-aiia-zoom') });
            """
        )
        assert out == {"badge": None, "badgeClick": 0, "bare": "1"}

    def test_an_image_the_browser_could_not_load_is_not_offered(self) -> None:
        out = _web(
            """
            const broken = mkImg('broken', { w: 0, h: 0 });
            const loading = mkImg('loading', { complete: false, w: 0, h: 0, n: 1 });
            page.enablePromptImageZoom(mkMessage(broken, loading));
            done({ broken: broken.getAttribute('data-aiia-zoom'), loading: loading.getAttribute('data-aiia-zoom') });
            """
        )
        assert out["broken"] is None
        # still loading: nobody knows yet, so it is offered (and loses the offer if it fails, below)
        assert out["loading"] == "1"

    def test_an_image_that_fails_late_loses_the_offer(self) -> None:
        out = _web(
            """
            const img = mkImg('late', { complete: false, w: 0, h: 0 });
            page.enablePromptImageZoom(mkMessage(img));
            const before = img.getAttribute('data-aiia-zoom');
            fire(img, 'error');
            done({ before, after: [...img.attrs.keys()].filter((k) => /^(data-aiia-zoom|tabindex|role|aria-label)$/.test(k)) });
            """
        )
        assert out == {"before": "1", "after": []}

    def test_no_container_is_not_an_error(self) -> None:
        out = _web(
            """
            const results = [];
            for (const value of [null, undefined, {}, 42]) {
              try { page.enablePromptImageZoom(value); results.push('ok'); } catch (e) { results.push(String(e.message)); }
            }
            done({ results, errors: logs.error, warnings: logs.warn });
            """
        )
        assert out == {"results": ["ok"] * 4, "errors": [], "warnings": []}

    def test_a_click_opens_the_image_in_the_modal(self) -> None:
        out = _web(
            """
            const img = mkImg('wide shot');
            page.enablePromptImageZoom(mkMessage(img));
            img.focus();
            fire(img, 'click');
            done(snapshot());
            """
        )
        assert out["open"] is True
        assert out["hidden"] is False
        assert out["src"] == "http://127.0.0.1:8080/api/tasks/t1/images/0"
        assert out["alt"] == "wide shot"
        # the keyboard goes to the close button, and the modal listens for Escape and Tab
        assert out["focus"] == "close"
        assert out["keydownListeners"] == 2
        assert out["state"]["source"] == "prompt"

    def test_the_caption_gives_the_pixels_as_soon_as_the_image_has_loaded(self) -> None:
        out = _web(
            """
            const img = mkImg('wide shot');
            page.enablePromptImageZoom(mkMessage(img));
            const src = ORIGIN + '/api/tasks/t1/images/0';
            sizes[src] = { w: 1920, h: 1080 };
            fire(img, 'click');
            const before = modalInfo.textContent;
            const waiting = modalImage.count('load');
            finishLoad(src);
            done({ before, waiting, after: modalInfo.textContent, left: modalImage.count('load') });
            """
        )
        assert out["before"] == "wide shot"
        assert out["after"] == (
            'status.imageDimensionsLabel|{"name":"wide shot","width":"1920","height":"1080"}'
        )
        # one listener per opening, and it goes with the load it waited for: opening many images leaks none
        assert (out["waiting"], out["left"]) == (1, 0)

    def test_an_image_the_browser_has_already_gets_its_pixels_at_once(self) -> None:
        out = _web(
            """
            const img = mkImg('cached');
            page.enablePromptImageZoom(mkMessage(img));
            sizes[ORIGIN + '/api/tasks/t1/images/0'] = { w: 640, h: 480, instant: true };
            fire(img, 'click');
            done(modalInfo.textContent);
            """
        )
        assert out == (
            'status.imageDimensionsLabel|{"name":"cached","width":"640","height":"480"}'
        )

    def test_an_image_without_alt_text_is_called_what_the_dialog_is_called(
        self,
    ) -> None:
        out = _web(
            """
            const img = mkImg(null);
            page.enablePromptImageZoom(mkMessage(img));
            const src = ORIGIN + '/api/tasks/t1/images/0';
            sizes[src] = { w: 800, h: 800 };
            fire(img, 'click');
            const before = modalInfo.textContent;
            finishLoad(src);
            done({ before, after: modalInfo.textContent, alt: modalImage.getAttribute('alt') });
            """
        )
        assert out["before"] == "page.imagePreview"
        assert out["after"] == (
            'status.imageDimensionsLabel|{"name":"page.imagePreview","width":"800","height":"800"}'
        )
        assert out["alt"] == ""

    def test_an_image_whose_alt_text_is_only_blanks_is_opened_without_a_name(
        self,
    ) -> None:
        out = _web(
            """
            const img = mkImg('   ');
            page.enablePromptImageZoom(mkMessage(img));
            fire(img, 'click');
            done({ alt: modalImage.getAttribute('alt'), info: modalInfo.textContent });
            """
        )
        assert out == {"alt": "", "info": "page.imagePreview"}

    def test_an_image_opened_without_any_name_is_not_called_undefined(self) -> None:
        out = _web(
            """
            page.openImageModal('blob:nameless');
            done({ alt: modalImage.getAttribute('alt'), info: modalInfo.textContent });
            """
        )
        assert out == {"alt": "", "info": "page.imagePreview"}

    @pytest.mark.parametrize("size", [(0, 0), (10, 0), (0, 10)])
    def test_an_image_that_did_not_load_has_no_pixels_to_tell(
        self, size: tuple[int, int]
    ) -> None:
        # ``complete`` is true for an image that failed, and its size is 0
        out = _web(
            f"""
            const img = mkImg('broken?');
            page.enablePromptImageZoom(mkMessage(img));
            sizes[ORIGIN + '/api/tasks/t1/images/0'] = {{ w: {size[0]}, h: {size[1]}, instant: true }};
            fire(img, 'click');
            done(modalInfo.textContent);
            """
        )
        assert out == "broken?"

    def test_an_img_without_a_source_is_not_offered(self) -> None:
        out = _web(
            """
            // no source, and a browser that has not yet decided it is broken (a script may still give it one)
            const empty = new El('img', { alt: 'nothing here' });
            empty.complete = false;
            const real = mkImg('real');
            page.enablePromptImageZoom(mkMessage(empty, real));
            done({ empty: empty.getAttribute('data-aiia-zoom'), real: real.getAttribute('data-aiia-zoom') });
            """
        )
        assert out == {"empty": None, "real": "1"}

    def test_the_pixels_of_the_previous_image_are_never_shown_for_the_next_one(
        self,
    ) -> None:
        # while a new ``src`` loads, ``naturalWidth`` can still be the old image's: ``complete`` says whose it is
        out = _web(
            """
            const first = mkImg('first'), second = mkImg('second', { n: 1 });
            page.enablePromptImageZoom(mkMessage(first, second));
            sizes[ORIGIN + '/api/tasks/t1/images/0'] = { w: 100, h: 50, instant: true };
            sizes[ORIGIN + '/api/tasks/t1/images/1'] = { w: 300, h: 200 };
            fire(first, 'click');
            const one = modalInfo.textContent;
            // a stale reading: the element still holds the first image's size while the second one loads
            modalImage.onSrc = (img) => { img.complete = false; };
            fire(second, 'click');
            const during = modalInfo.textContent;
            modalImage.naturalWidth = 300; modalImage.naturalHeight = 200; modalImage.complete = true;
            fire(modalImage, 'load');
            done({ one, during, after: modalInfo.textContent });
            """
        )
        assert '"width":"100","height":"50"' in out["one"]
        assert out["during"] == "second"
        assert '"width":"300","height":"200"' in out["after"]

    def test_a_late_load_cannot_write_into_the_caption_of_another_opening(self) -> None:
        out = _web(
            """
            const a = mkImg('a'), b = mkImg('b', { n: 1 });
            page.enablePromptImageZoom(mkMessage(a, b));
            sizes[ORIGIN + '/api/tasks/t1/images/0'] = { w: 111, h: 11 };
            sizes[ORIGIN + '/api/tasks/t1/images/1'] = { w: 222, h: 22 };
            fire(a, 'click');
            const stale = modalImage.listeners.filter((l) => l.type === 'load').map((l) => l.fn);
            page.closeImageModal();
            fire(b, 'click');
            // the load of the first opening arrives now, with the element holding the second image's size
            modalImage.complete = true; modalImage.naturalWidth = 222; modalImage.naturalHeight = 22;
            stale.forEach((fn) => fn());
            done({ staleCount: stale.length, info: modalInfo.textContent });
            """
        )
        # only the listener of the current opening may write; the stale one does nothing
        assert out == {"staleCount": 1, "info": "b"}

    def test_an_opening_over_another_one_does_not_hear_the_late_load_of_the_first(
        self,
    ) -> None:
        # no closing in between: the second opening must retire the first one's listener by itself
        out = _web(
            """
            const a = mkImg('a'), b = mkImg('b', { n: 1 });
            page.enablePromptImageZoom(mkMessage(a, b));
            sizes[ORIGIN + '/api/tasks/t1/images/0'] = { w: 111, h: 11 };
            sizes[ORIGIN + '/api/tasks/t1/images/1'] = { w: 222, h: 22, instant: true };
            fire(a, 'click');
            const first = modalInfo.textContent;
            fire(b, 'click');
            const second = modalInfo.textContent;
            // the first image finishes loading only now
            finishLoad(ORIGIN + '/api/tasks/t1/images/0');
            done({ first, second, after: modalInfo.textContent });
            """
        )
        assert out["first"] == "a"
        assert '"width":"222","height":"22"' in out["second"]
        assert out["after"] == out["second"]

    def test_a_load_that_arrives_after_the_modal_was_closed_writes_nothing(
        self,
    ) -> None:
        out = _web(
            """
            const img = mkImg('closed early');
            page.enablePromptImageZoom(mkMessage(img));
            sizes[ORIGIN + '/api/tasks/t1/images/0'] = { w: 500, h: 400 };
            fire(img, 'click');
            page.closeImageModal();
            const before = modalInfo.textContent;
            // the browser still finishes what it was loading
            modalImage.complete = true; modalImage.naturalWidth = 500; modalImage.naturalHeight = 400;
            fire(modalImage, 'load');
            done({ before, after: modalInfo.textContent });
            """
        )
        assert out["after"] == out["before"] == "closed early"

    @pytest.mark.parametrize("key", ["Enter", " ", "Spacebar"])
    def test_enter_and_space_open_an_image_that_has_focus(self, key: str) -> None:
        out = _web(
            f"""
            const img = mkImg('keyed');
            page.enablePromptImageZoom(mkMessage(img));
            img.focus();
            const event = press(img, {json.dumps(key)});
            done({{ prevented: event.defaultPrevented, snap: snapshot() }});
            """
        )
        # the key is taken (Space must not scroll the page, Enter must not reach the button that gets focus)
        assert out["prevented"] is True
        assert out["snap"]["open"] is True
        assert out["snap"]["focus"] == "close"

    @pytest.mark.parametrize(
        "props",
        [{"ctrlKey": True}, {"metaKey": True}, {"altKey": True}, {"shiftKey": True}],
    )
    def test_a_chord_is_somebody_elses_and_opens_nothing(
        self, props: dict[str, bool]
    ) -> None:
        out = _web(
            f"""
            const img = mkImg('chord');
            page.enablePromptImageZoom(mkMessage(img));
            const event = press(img, 'Enter', {json.dumps(props)});
            done({{ open: modalOpen(), prevented: event.defaultPrevented }});
            """
        )
        assert out == {"open": False, "prevented": False}

    def test_a_key_somebody_else_already_took_opens_nothing(self) -> None:
        out = _web(
            """
            const img = mkImg('taken');
            page.enablePromptImageZoom(mkMessage(img));
            press(img, 'Enter', { defaultPrevented: true });
            done(modalOpen());
            """
        )
        assert out is False

    def test_other_keys_are_left_alone(self) -> None:
        out = _web(
            """
            const img = mkImg('keys');
            page.enablePromptImageZoom(mkMessage(img));
            done(['a', 'Tab', 'Escape', 'ArrowDown', 'Backspace'].map((k) => {
              const event = press(img, k);
              return { k, open: modalOpen(), prevented: event.defaultPrevented };
            }));
            """
        )
        assert [(r["open"], r["prevented"]) for r in out] == [(False, False)] * 5

    def test_clicking_an_image_that_turns_out_to_be_broken_opens_nothing(self) -> None:
        out = _web(
            """
            const img = mkImg('later', { complete: false, w: 0, h: 0 });
            page.enablePromptImageZoom(mkMessage(img));
            img.complete = true;            // it finished, and failed, before the error event could be handled
            fire(img, 'click');
            done(snapshot());
            """
        )
        assert out["open"] is False

    def test_closing_lets_go_of_the_image_and_gives_focus_back(self) -> None:
        out = _web(
            """
            const img = mkImg('wide shot');
            page.enablePromptImageZoom(mkMessage(img));
            img.focus();
            fire(img, 'click');
            const opened = snapshot();
            const closed = page.closeImageModal();
            done({ opened, closed, snap: snapshot() });
            """
        )
        snap = out["snap"]
        assert out["opened"]["open"] is True
        assert out["closed"] is True
        assert snap["open"] is False and snap["hidden"] is True
        # the element no longer holds up to 8 MB nobody looks at, and the next image cannot inherit its pixels
        assert snap["src"] is None
        assert snap["focus"] == "IMG:wide shot"
        assert snap["keydownListeners"] == 0
        assert snap["state"] == {"source": "", "handlers": False}

    def test_escape_closes_it(self) -> None:
        out = _web(
            """
            const img = mkImg('esc');
            page.enablePromptImageZoom(mkMessage(img));
            fire(img, 'click');
            press(closeButton, 'Escape');
            done(snapshot());
            """
        )
        assert out["open"] is False
        assert out["keydownListeners"] == 0

    def test_tab_stays_on_the_close_button(self) -> None:
        out = _web(
            """
            const img = mkImg('tab');
            page.enablePromptImageZoom(mkMessage(img));
            fire(img, 'click');
            const outside = new El('button');
            outside.focus();
            const event = press(outside, 'Tab');
            done({ prevented: event.defaultPrevented, focus: snapshot().focus, open: modalOpen() });
            """
        )
        assert out == {"prevented": True, "focus": "close", "open": True}

    def test_the_viewer_of_the_old_message_goes_when_the_message_is_written_again(
        self,
    ) -> None:
        out = _web(
            """
            const old = mkImg('old');
            page.enablePromptImageZoom(mkMessage(old));
            old.focus();
            fire(old, 'click');
            const before = modalOpen();
            const fresh = mkImg('fresh', { n: 5 });
            old.detached = true;            // the old message is gone from the page
            page.enablePromptImageZoom(mkMessage(fresh));
            done({ before, snap: snapshot(), freshMarked: fresh.getAttribute('data-aiia-zoom') });
            """
        )
        assert out["before"] is True
        assert out["snap"]["open"] is False
        assert out["snap"]["state"]["source"] == ""
        assert out["freshMarked"] == "1"
        # focus is not given back to a node that is no longer on the page: it stays where it was
        assert out["snap"]["focus"] == "close"

    def test_an_attachment_in_the_viewer_is_not_the_messages_and_stays(self) -> None:
        out = _web(
            """
            page.openImageModal('blob:attached', 'photo.png', 2048);
            const caption = modalInfo.textContent;
            const closedByMessage = page.closeImageModalFromPrompt();
            page.enablePromptImageZoom(mkMessage(mkImg('another')));
            done({ caption, closedByMessage, snap: snapshot() });
            """
        )
        assert out["caption"] == 'status.sizeLabelKB|{"name":"photo.png","size":"2.00"}'
        assert out["closedByMessage"] is False
        assert out["snap"]["open"] is True
        assert out["snap"]["state"]["source"] == ""

    def test_nothing_open_means_nothing_to_close(self) -> None:
        out = _web(
            "done({ closed: page.closeImageModalFromPrompt(), snap: snapshot() });"
        )
        assert out["closed"] is False
        assert out["snap"]["open"] is False

    def test_an_attachment_keeps_its_name_and_file_size_in_the_caption(self) -> None:
        out = _web(
            """
            page.openImageModal('blob:a', 'shot.png', 0);
            const zero = modalInfo.textContent;
            page.openImageModal('blob:b', 'big.png', 10 * 1024 * 1024);
            done({ zero, big: modalInfo.textContent, alt: modalImage.getAttribute('alt'), listeners: modalImage.count('load') });
            """
        )
        assert out["zero"] == 'status.sizeLabelKB|{"name":"shot.png","size":"0.00"}'
        assert out["big"] == 'status.sizeLabelKB|{"name":"big.png","size":"10240.00"}'
        assert out["alt"] == "big.png"
        # it has a file size to tell, so there is no pixel caption to wait for
        assert out["listeners"] == 0

    def test_an_image_opened_over_another_does_not_forget_who_had_focus(self) -> None:
        out = _web(
            """
            const a = mkImg('a');
            page.enablePromptImageZoom(mkMessage(a));
            a.focus();
            fire(a, 'click');
            page.openImageModal(ORIGIN + '/other', 'b', undefined, { source: 'prompt' });
            page.closeImageModal();
            done(snapshot().focus);
            """
        )
        assert out == "IMG:a"

    def test_a_page_without_the_modal_markup_opens_nothing_and_says_so_quietly(
        self,
    ) -> None:
        out = _web(
            """
            byId.delete('modal-info');
            const img = mkImg('no modal');
            page.enablePromptImageZoom(mkMessage(img));
            fire(img, 'click');
            done({ open: modalOpen(), debug: logs.debug, error: logs.error });
            """
        )
        assert out["open"] is False
        assert out["error"] == []
        assert out["debug"] == ["Image modal open skipped: #modal-info unavailable"]

    def test_a_page_without_the_modal_script_still_marks_nothing_it_cannot_open(
        self,
    ) -> None:
        # image-upload.js failed to load: the images are marked (they are the message's), a click does nothing
        out = _web(
            """
            const img = mkImg('no script');
            page.enablePromptImageZoom(mkMessage(img));
            fire(img, 'click');
            press(img, 'Enter');
            done({ marked: img.getAttribute('data-aiia-zoom'), errors: logs.error });
            """,
            modal=False,
        )
        assert out == {"marked": "1", "errors": []}

    def test_nothing_prints_a_warning_or_an_error(self) -> None:
        out = _web(
            """
            const img = mkImg('quiet');
            page.enablePromptImageZoom(mkMessage(img));
            sizes[ORIGIN + '/api/tasks/t1/images/0'] = { w: 10, h: 10 };
            fire(img, 'click');
            finishLoad(ORIGIN + '/api/tasks/t1/images/0');
            press(closeButton, 'Tab');
            press(closeButton, 'Escape');
            done({ warn: logs.warn, error: logs.error, debug: logs.debug });
            """
        )
        assert out == {"warn": [], "error": [], "debug": []}


# ============================================================================== wiring of the Web page
class TestWebWiring:
    def test_the_first_paint_marks_the_images_after_the_rule_and_before_the_maths(
        self,
    ) -> None:
        body = _extract_function(
            APP_JS.read_text(encoding="utf-8"), "function renderMarkdownContent("
        )
        assert "enablePromptImageZoom(element)" in body
        assert body.index("processPromptImages(element)") < body.index(
            "enablePromptImageZoom(element)"
        )
        assert body.index("enablePromptImageZoom(element)") < body.index(
            "loadMathJaxIfNeeded"
        )

    def test_the_multi_task_paint_does_the_same_and_guards_the_call(self) -> None:
        body = _extract_function(
            MULTI_TASK_JS.read_text(encoding="utf-8"),
            "async function updateDescriptionDisplay(",
        )
        assert 'typeof enablePromptImageZoom === "function"' in body
        assert body.index("processPromptImages(descriptionElement)") < body.index(
            "enablePromptImageZoom(descriptionElement)"
        )
        assert body.index("enablePromptImageZoom(descriptionElement)") < body.index(
            "loadMathJaxIfNeeded"
        )

    def test_the_marking_is_not_part_of_the_rule_that_decides_which_images_stay(
        self,
    ) -> None:
        # R886 runs ``processPromptImages`` over a bare DOM and compares the markup: it must stay a pure filter
        body = _extract_function(
            APP_JS.read_text(encoding="utf-8"), "function processPromptImages("
        )
        assert "data-aiia-zoom" not in body
        assert "openImageModal" not in body

    def test_the_page_has_the_modal_the_script_opens_and_loads_the_scripts_in_an_order_that_works(
        self,
    ) -> None:
        html = WEB_TEMPLATE.read_text(encoding="utf-8")
        for ident in ("image-modal", "modal-image", "modal-info"):
            assert f'id="{ident}"' in html
        assert 'class="image-modal-close"' in html
        # ``multi_task.js`` calls the function behind a ``typeof`` guard, ``app.js`` after the page has loaded
        assert html.index("/static/js/image-upload.js") < html.index(
            "/static/js/app.js?v={{ app_version }}",
            html.index("/static/js/image-upload.js"),
        )

    def test_the_minified_scripts_the_page_loads_have_the_change(self) -> None:
        js = STATIC / "js"
        app = (js / "app.min.js").read_text(encoding="utf-8")
        upload = (js / "image-upload.min.js").read_text(encoding="utf-8")
        multi = (js / "multi_task.min.js").read_text(encoding="utf-8")
        assert "function enablePromptImageZoom(" in app and "data-aiia-zoom" in app
        # the same order as the source: filter the images, offer what is left, and only then hand the text to the maths
        assert re.search(
            r"processPromptImages\(element\);\s*enablePromptImageZoom\(element\);\s*const textContent",
            app,
        )
        assert "function closeImageModalFromPrompt(" in upload
        assert "status.imageDimensionsLabel" in upload
        assert re.search(
            r'if\(typeof processPromptImages==="function"\)\{processPromptImages\(descriptionElement\);\}\s*'
            r'if\(typeof enablePromptImageZoom==="function"\)\{enablePromptImageZoom\(descriptionElement\);\}',
            multi,
        )


# ============================================================================== the Web stylesheet
class TestWebStylesheet:
    def test_an_image_that_can_be_opened_shows_it_with_the_cursor(self) -> None:
        rule = _merged(WEB_RULES, '.markdown-content img[data-aiia-zoom="1"]')
        assert rule["cursor"] == "zoom-in"
        # a tap does not wait for a double-tap to zoom the page
        assert rule["touch-action"] == "manipulation"

    def test_the_large_image_fits_the_window_not_the_box_around_it(self) -> None:
        rule = _merged(WEB_RULES, ".image-modal img")
        # ``100%`` of a box with no height of its own is no limit: a tall image kept its own size
        assert rule["max-width"] == "90vw"
        assert rule["max-height"] == "80dvh"
        assert rule["object-fit"] == "contain"
        # browsers that do not know ``dvh`` drop that line and keep the one before it
        text = WEB_CSS.read_text(encoding="utf-8")
        block = text[text.index(".image-modal img {") :]
        block = block[: block.index("}")]
        assert block.index("max-height: 80vh;") < block.index("max-height: 80dvh;")

    def test_the_caption_is_as_wide_as_its_text_and_at_least_as_wide_as_the_image(
        self,
    ) -> None:
        rule = _merged(WEB_RULES, ".image-modal-info")
        assert rule["width"] == "max-content"
        assert rule["min-width"] == "100%"
        assert rule["left"] == "50%"
        assert rule["transform"] == "translateX(-50%)"
        assert rule["box-sizing"] == "border-box"
        assert rule["max-width"] == "90vw"
        assert "right" not in rule

    def test_on_a_phone_the_caption_is_pinned_inside_the_image_again(self) -> None:
        rule = _merged(WEB_RULES, ".image-modal-info", PHONE)
        assert (rule["left"], rule["right"]) == ("10px", "10px")
        assert rule["transform"] == "none"
        assert rule["width"] == "auto"
        assert rule["min-width"] == "0"
        assert rule["max-width"] == "none"

    def test_the_minified_stylesheet_the_page_loads_has_the_rules(self) -> None:
        css = WEB_MIN_CSS.read_text(encoding="utf-8")
        assert re.search(
            r'\.markdown-content img\[data-aiia-zoom="?1"?\]\{[^}]*cursor:zoom-in', css
        )
        assert re.search(
            r"\.image-modal img\{[^}]*max-height:80vh;max-height:80dvh", css
        )
        assert re.search(r"\.image-modal-info\{[^}]*width:max-content", css)
        assert re.search(r"\.image-modal-info\{[^}]*transform:none", css)


# ============================================================================== the panel
PANEL_SETUP = r"""
const viewer = new El('div', { id: 'imageViewer', class: 'image-viewer hidden' });
const stage = new El('div', { id: 'imageViewerStage' });
const image = new El('img', { id: 'imageViewerImg', alt: '' });
const caption = new El('div', { id: 'imageViewerCaption' });
const toolbar = new El('div');
const zoom = new El('button', { id: 'imageViewerZoom' });
const close = new El('button', { id: 'imageViewerClose' });
zoom.disabled = true;
viewer.appendChild(stage);
stage.appendChild(image);
viewer.appendChild(caption);
viewer.appendChild(toolbar);
toolbar.appendChild(zoom);
toolbar.appendChild(close);
document.body.appendChild(viewer);
for (const el of [viewer, stage, image, caption, zoom, close]) byId.set(el.attrs.get('id'), el);
const windowListeners = [];
const win = { addEventListener: (type, fn) => windowListeners.push({ type, fn }) };

// What the browser lays out: the view is 299 x 779 and an image is scaled down to fit it, in the box
// that is left after the buttons (above) and the caption (below).
const STAGE = { w: 299, h: 779 };
stage.clientWidth = STAGE.w;
stage.clientHeight = STAGE.h;
const sizes = {};
const fitOf = (natural) => {
  const k = Math.min(1, (STAGE.w - 24) / natural.w, (STAGE.h - 48) / natural.h);
  return { w: Math.round(natural.w * k), h: Math.round(natural.h * k) };
};
function layout() {
  const actual = viewer.classList.contains('is-actual');
  const natural = { w: image.naturalWidth, h: image.naturalHeight };
  const box = actual ? natural : fitOf(natural);
  image.clientWidth = box.w; image.clientHeight = box.h;
  image.offsetWidth = box.w; image.offsetHeight = box.h;
  image.offsetLeft = Math.max(12, Math.round((STAGE.w - box.w) / 2));
  image.offsetTop = 44;
  image.rect = { left: 12, top: 44, width: box.w, height: box.h };
}
image.onSrc = (img) => {
  if (!img.hasAttribute('src')) { img.complete = true; img.naturalWidth = 0; img.naturalHeight = 0; layout(); return; }
  const entry = sizes[img.getAttribute('src')] || { w: 1920, h: 1080 };
  img.complete = !entry.late;
  img.naturalWidth = entry.late ? 0 : entry.w;
  img.naturalHeight = entry.late ? 0 : entry.h;
  layout();
};
const finishLoad = (src) => {
  const entry = sizes[src];
  image.complete = true; image.naturalWidth = entry.w; image.naturalHeight = entry.h;
  layout();
  fire(image, 'load');
};
// a class changes the layout: look again after every change
for (const name of ['add', 'remove', 'toggle']) {
  const original = viewer.classList[name];
  viewer.classList[name] = (...args) => { const r = original(...args); layout(); return r; };
}

const panel = { window: win, document, console: consoleStub, t };
vm.createContext(panel);
vm.runInContext(
  'let uploadedImages = [];\n' + CODE +
  '\nthis.api = { openImageViewer, closeImageViewer, isImageViewerOpen, initImageViewer, enablePromptImageZoom, ' +
  'makeImageZoomable, closeImageViewerIfAttachmentGone, ' +
  'setUploaded: (list) => { uploadedImages = list; }, ' +
  'state: () => ({ source: imageViewerSource, opener: imageViewerOpener, keys: imageViewerKeydownAttached }) };',
  panel,
);
const api = panel.api;
api.initImageViewer();
const snap = () => ({
  open: !viewer.classList.contains('hidden'),
  actual: viewer.classList.contains('is-actual'),
  canEnlarge: viewer.classList.contains('can-enlarge'),
  src: image.getAttribute('src'),
  alt: image.getAttribute('alt'),
  caption: caption.textContent,
  zoomDisabled: zoom.disabled,
  zoomPressed: zoom.getAttribute('aria-pressed'),
  scroll: { left: stage.scrollLeft, top: stage.scrollTop },
  focus: activeElement === close ? 'close' : activeElement === zoom ? 'zoom'
    : activeElement ? activeElement.tagName + ':' + activeElement.getAttribute('alt') : null,
  keys: docCount('keydown'),
  state: (({ source, keys, opener }) => ({ source, keys, opener: !!opener }))(api.state()),
});
const SRC = ORIGIN + '/api/tasks/t1/images/0';
"""


def _panel_block() -> str:
    """Everything the panel does with an image that is opened large, from its constants to the attachments list."""
    return _slice(
        PANEL_JS,
        "const IMAGE_VIEWER_ACTUAL_CLASS",
        "function renderUploadedImages()",
    )


def _panel(case_js: str) -> Any:
    return _run(_panel_block(), PANEL_SETUP, case_js)


OPEN_WIDE = """
sizes[SRC] = { w: 1920, h: 1080 };
api.openImageViewer(SRC, 'wide shot', 'prompt', null);
"""


@needs_node
class TestPanelViewer:
    def test_opening_shows_the_viewer_on_the_close_button_and_listens_for_keys(
        self,
    ) -> None:
        out = _panel(OPEN_WIDE + "done(snap());")
        assert out["open"] is True
        assert out["src"] == "http://127.0.0.1:8080/api/tasks/t1/images/0"
        assert out["alt"] == "wide shot"
        assert out["focus"] == "close"
        assert out["keys"] == 1
        assert out["state"]["source"] == "prompt"

    def test_every_image_opens_to_fit_from_the_top_left(self) -> None:
        out = _panel(
            OPEN_WIDE
            + """
            fire(image, 'click', { detail: 1, clientX: 100, clientY: 100 });
            const was = snap();
            stage.scrollLeft = 99; stage.scrollTop = 99;
            api.openImageViewer(SRC, 'again', 'prompt', null);
            done({ was, now: snap() });
            """
        )
        assert out["was"]["actual"] is True
        assert out["now"]["actual"] is False
        assert out["now"]["scroll"] == {"left": 0, "top": 0}
        assert out["now"]["zoomPressed"] == "false"

    def test_the_1_1_button_is_on_only_while_there_is_something_to_enlarge(
        self,
    ) -> None:
        out = _panel(
            """
            const results = {};
            const cases = {
              wide: [1920, 1080], tall: [600, 3000], small: [160, 100], exact: [275, 155], within: [276, 156],
              beyond: [277, 157], hairline: [1, 3000], thread: [3000, 1],
            };
            for (const [name, size] of Object.entries(cases)) {
              const src = ORIGIN + '/img/' + name;
              sizes[src] = { w: size[0], h: size[1] };
              api.openImageViewer(src, name, 'prompt', null);
              const s = snap();
              results[name] = { zoomDisabled: s.zoomDisabled, canEnlarge: s.canEnlarge };
              api.closeImageViewer();
            }
            done(results);
            """
        )
        assert out["wide"] == {"zoomDisabled": False, "canEnlarge": True}
        assert out["tall"] == {"zoomDisabled": False, "canEnlarge": True}
        # smaller than the view, or within a pixel of it: the image already is at its own size
        assert out["small"] == {"zoomDisabled": True, "canEnlarge": False}
        assert out["exact"] == {"zoomDisabled": True, "canEnlarge": False}
        # a pixel of rounding is no reason to offer a switch; two pixels are
        assert out["within"] == {"zoomDisabled": True, "canEnlarge": False}
        assert out["beyond"] == {"zoomDisabled": False, "canEnlarge": True}
        # a line one pixel wide is as long as it is: either side being larger than its box is enough
        assert out["hairline"] == {"zoomDisabled": False, "canEnlarge": True}
        assert out["thread"] == {"zoomDisabled": False, "canEnlarge": True}

    @pytest.mark.parametrize("size", [(0, 0), (10, 0), (0, 10)])
    def test_an_image_that_did_not_load_has_no_pixels_to_tell(
        self, size: tuple[int, int]
    ) -> None:
        out = _panel(
            f"""
            const src = ORIGIN + '/broken';
            sizes[src] = {{ w: {size[0]}, h: {size[1]} }};
            api.openImageViewer(src, 'broken?', 'prompt', null);
            done(snap());
            """
        )
        assert out["caption"] == "broken?"
        assert out["zoomDisabled"] is True

    def test_a_load_that_arrives_after_the_viewer_was_closed_writes_nothing(
        self,
    ) -> None:
        out = _panel(
            """
            const src = ORIGIN + '/late';
            sizes[src] = { w: 1920, h: 1080, late: true };
            api.openImageViewer(src, 'late', 'prompt', null);
            api.closeImageViewer();
            finishLoad(src);
            done(snap());
            """
        )
        assert out["caption"] == ""
        assert out["zoomDisabled"] is True

    def test_an_image_that_has_not_loaded_yet_cannot_be_enlarged_until_it_has(
        self,
    ) -> None:
        out = _panel(
            """
            const src = ORIGIN + '/api/late';
            sizes[src] = { w: 1920, h: 1080, late: true };
            api.openImageViewer(src, 'late', 'prompt', null);
            const before = snap();
            finishLoad(src);
            done({ before, after: snap() });
            """
        )
        assert out["before"]["zoomDisabled"] is True
        assert out["before"]["caption"] == "late"
        assert out["after"]["zoomDisabled"] is False
        assert out["after"]["caption"] == (
            'ui.image.dimensions|{"name":"late","width":"1920","height":"1080"}'
        )

    def test_the_pixels_of_the_previous_image_are_never_shown_for_the_next_one(
        self,
    ) -> None:
        # while a new ``src`` loads the element can still report the size of the image it held before
        out = _panel(
            """
            const first = ORIGIN + '/first', second = ORIGIN + '/second';
            sizes[first] = { w: 1920, h: 1080 };
            api.openImageViewer(first, 'first', 'prompt', null);
            const one = snap();
            image.onSrc = (img) => { img.complete = false; layout(); };   // naturalWidth/Height stay the first image's
            api.openImageViewer(second, 'second', 'prompt', null);
            done({ one, during: snap() });
            """
        )
        assert out["one"]["zoomDisabled"] is False
        assert out["during"]["caption"] == "second"
        assert out["during"]["zoomDisabled"] is True

    def test_the_viewer_follows_the_view_when_it_is_resized(self) -> None:
        out = _panel(
            """
            const src = ORIGIN + '/api/mid';
            sizes[src] = { w: 500, h: 300 };
            api.openImageViewer(src, 'mid', 'prompt', null);
            const narrow = snap().zoomDisabled;
            STAGE.w = 700;                         // the sidebar is dragged wider: the image fits as it is
            layout();
            windowListeners.filter((l) => l.type === 'resize').forEach((l) => l.fn());
            done({ narrow, wide: snap().zoomDisabled, listeners: windowListeners.length });
            """
        )
        assert out == {"narrow": False, "wide": True, "listeners": 1}

    def test_a_click_on_the_image_goes_to_its_own_size_around_the_spot_clicked(
        self,
    ) -> None:
        out = _panel(
            OPEN_WIDE
            + """
            // fit: 275 x 155 at (12, 44); click 20 % across and 40 % down
            fire(image, 'click', { detail: 1, clientX: 12 + 275 * 0.2, clientY: 44 + 155 * 0.4 });
            done({ s: snap(), left: image.offsetLeft, top: image.offsetTop, w: image.offsetWidth, h: image.offsetHeight,
                   cw: stage.clientWidth, ch: stage.clientHeight });
            """
        )
        s = out["s"]
        assert s["actual"] is True
        assert s["zoomPressed"] == "true"
        assert s["zoomDisabled"] is False
        # the spot clicked is in the middle of the view
        assert s["scroll"]["left"] == pytest.approx(
            out["left"] + 0.2 * out["w"] - out["cw"] / 2
        )
        assert s["scroll"]["top"] == pytest.approx(
            out["top"] + 0.4 * out["h"] - out["ch"] / 2
        )

    def test_a_second_click_goes_back_to_fit(self) -> None:
        out = _panel(
            OPEN_WIDE
            + """
            fire(image, 'click', { detail: 1, clientX: 100, clientY: 80 });
            fire(image, 'click', { detail: 1, clientX: 100, clientY: 80 });
            done(snap());
            """
        )
        assert out["actual"] is False
        assert out["zoomPressed"] == "false"
        assert out["scroll"] == {"left": 0, "top": 0}
        assert out["open"] is True

    def test_a_click_nobody_pointed_goes_to_the_middle_of_the_image(self) -> None:
        # ``detail`` is 0 for a click that a key made
        out = _panel(
            OPEN_WIDE
            + """
            fire(image, 'click', { detail: 0, clientX: 0, clientY: 0 });
            done({ s: snap(), left: image.offsetLeft, top: image.offsetTop, w: image.offsetWidth, h: image.offsetHeight,
                   cw: stage.clientWidth, ch: stage.clientHeight });
            """
        )
        assert out["s"]["scroll"]["left"] == pytest.approx(
            out["left"] + 0.5 * out["w"] - out["cw"] / 2
        )
        assert out["s"]["scroll"]["top"] == pytest.approx(
            out["top"] + 0.5 * out["h"] - out["ch"] / 2
        )

    @pytest.mark.parametrize("box", [(0, 0), (0, 100), (100, 0)])
    def test_a_click_on_an_image_with_no_size_on_screen_goes_to_the_middle(
        self, box: tuple[int, int]
    ) -> None:
        # a pointer position over a box of no size says nothing: no division by it
        out = _panel(
            OPEN_WIDE
            + f"""
            image.rect = {{ left: 0, top: 0, width: {box[0]}, height: {box[1]} }};
            fire(image, 'click', {{ detail: 1, clientX: 40, clientY: 40 }});
            done({{ s: snap(), left: image.offsetLeft, top: image.offsetTop, w: image.offsetWidth, h: image.offsetHeight,
                   cw: stage.clientWidth, ch: stage.clientHeight }});
            """
        )
        assert out["s"]["actual"] is True
        assert out["s"]["scroll"]["left"] == pytest.approx(
            out["left"] + 0.5 * out["w"] - out["cw"] / 2
        )
        assert out["s"]["scroll"]["top"] == pytest.approx(
            out["top"] + 0.5 * out["h"] - out["ch"] / 2
        )

    @pytest.mark.parametrize(
        ("x", "y", "share_x", "share_y"),
        [(-500, 9000, 0, 1), (9000, -500, 1, 0)],
    )
    def test_a_click_outside_the_image_box_is_clamped_to_its_edge(
        self, x: int, y: int, share_x: int, share_y: int
    ) -> None:
        out = _panel(
            OPEN_WIDE
            + f"""
            fire(image, 'click', {{ detail: 1, clientX: {x}, clientY: {y} }});
            done({{ s: snap(), left: image.offsetLeft, top: image.offsetTop, w: image.offsetWidth, h: image.offsetHeight,
                   cw: stage.clientWidth, ch: stage.clientHeight }});
            """
        )
        assert out["s"]["scroll"]["left"] == pytest.approx(
            out["left"] + share_x * out["w"] - out["cw"] / 2
        )
        assert out["s"]["scroll"]["top"] == pytest.approx(
            out["top"] + share_y * out["h"] - out["ch"] / 2
        )

    def test_the_1_1_button_toggles_and_does_nothing_while_it_is_off(self) -> None:
        out = _panel(
            """
            const big = ORIGIN + '/big', small = ORIGIN + '/small';
            sizes[big] = { w: 1920, h: 1080 }; sizes[small] = { w: 100, h: 60 };
            api.openImageViewer(big, 'big', 'prompt', null);
            fire(zoom, 'click');
            const on = snap();
            fire(zoom, 'click');
            const off = snap();
            api.openImageViewer(small, 'small', 'prompt', null);
            fire(zoom, 'click');
            done({ on, off, small: snap() });
            """
        )
        assert (out["on"]["actual"], out["on"]["zoomPressed"]) == (True, "true")
        assert (out["off"]["actual"], out["off"]["zoomPressed"]) == (False, "false")
        assert out["small"]["actual"] is False

    def test_a_click_on_the_image_when_there_is_nothing_to_enlarge_does_nothing(
        self,
    ) -> None:
        out = _panel(
            """
            const small = ORIGIN + '/small';
            sizes[small] = { w: 100, h: 60 };
            api.openImageViewer(small, 'small', 'prompt', null);
            fire(image, 'click', { detail: 1, clientX: 50, clientY: 60 });
            done(snap());
            """
        )
        assert out["actual"] is False
        assert out["open"] is True

    def test_escape_closes_and_the_page_does_not_see_it(self) -> None:
        out = _panel(
            OPEN_WIDE
            + """
            const event = press(close, 'Escape');
            done({ event: { prevented: event.defaultPrevented, stopped: event.stopped }, snap: snap() });
            """
        )
        assert out["event"] == {"prevented": True, "stopped": True}
        assert out["snap"]["open"] is False
        assert out["snap"]["keys"] == 0
        assert out["snap"]["state"]["keys"] is False

    def test_closing_gives_focus_back_to_what_opened_it(self) -> None:
        out = _panel(
            """
            const opener = mkImg('opener');
            sizes[opener.currentSrc] = { w: 1920, h: 1080 };
            opener.focus();
            api.openImageViewer(opener.currentSrc, 'opener', 'prompt', opener);
            const during = snap().focus;
            api.closeImageViewer();
            done({ during, after: snap().focus });
            """
        )
        assert out == {"during": "close", "after": "IMG:opener"}

    def test_the_opener_that_is_handed_in_wins_over_what_happens_to_have_focus(
        self,
    ) -> None:
        # Safari does not focus an image on a click: the focused element is something else, the opener is the image
        out = _panel(
            """
            const opener = mkImg('opener'), elsewhere = new El('button', { alt: 'elsewhere' });
            sizes[opener.currentSrc] = { w: 1920, h: 1080 };
            elsewhere.focus();
            api.openImageViewer(opener.currentSrc, 'opener', 'prompt', opener);
            api.closeImageViewer();
            done(snap().focus);
            """
        )
        assert out == "IMG:opener"

    def test_a_click_on_an_image_that_has_no_focus_still_gets_it_back_on_close(
        self,
    ) -> None:
        # a click does not focus an image in every browser; what was clicked is still where the person was
        out = _panel(
            """
            const img = mkImg('clicked');
            sizes[img.currentSrc] = { w: 1920, h: 1080 };
            api.enablePromptImageZoom(mkMessage(img));
            const elsewhere = new El('button', { alt: 'elsewhere' });
            elsewhere.focus();
            fire(img, 'click');
            api.closeImageViewer();
            done(snap().focus);
            """
        )
        assert out == "IMG:clicked"

    def test_an_image_without_a_name_does_not_stop_the_viewer(self) -> None:
        out = _panel(
            """
            sizes[SRC] = { w: 10, h: 10 };
            const results = [undefined, null, 42].map((name) => {
              const opened = api.openImageViewer(SRC, name, 'prompt', null);
              const alt = snap().alt;
              api.closeImageViewer();
              return { opened, alt };
            });
            done(results);
            """
        )
        assert out == [{"opened": True, "alt": ""}] * 3

    def test_without_an_opener_focus_goes_back_to_what_had_it(self) -> None:
        out = _panel(
            """
            const before = new El('button', { alt: 'before' });
            sizes[SRC] = { w: 1920, h: 1080 };
            before.focus();
            api.openImageViewer(SRC, 'x', 'prompt', null);
            const during = snap().focus;
            api.closeImageViewer();
            done({ during, after: snap().focus, opener: snap().state.opener });
            """
        )
        assert out == {"during": "close", "after": "BUTTON:before", "opener": False}

    def test_closing_when_the_opener_is_gone_does_not_focus_a_node_that_left(
        self,
    ) -> None:
        out = _panel(
            """
            const opener = mkImg('gone');
            opener.focus();
            api.openImageViewer(opener.currentSrc, 'gone', 'prompt', opener);
            opener.detached = true;
            const calls = opener.focusCalls;
            api.closeImageViewer();
            done({ calls: opener.focusCalls - calls });
            """
        )
        assert out == {"calls": 0}

    def test_closing_lets_go_of_the_image(self) -> None:
        out = _panel(
            OPEN_WIDE
            + """
            fire(zoom, 'click');
            api.closeImageViewer();
            done(snap());
            """
        )
        assert out["open"] is False
        assert out["src"] is None
        assert out["alt"] == ""
        assert out["caption"] == ""
        assert out["actual"] is False and out["canEnlarge"] is False

    def test_closing_twice_is_harmless(self) -> None:
        out = _panel(
            OPEN_WIDE
            + "done({ first: api.closeImageViewer(), second: api.closeImageViewer(), keys: docCount('keydown') });"
        )
        assert out == {"first": True, "second": False, "keys": 0}

    def test_a_click_outside_the_image_closes_it_and_on_the_image_does_not(
        self,
    ) -> None:
        out = _panel(
            OPEN_WIDE
            + """
            const results = {};
            for (const [name, target] of [['button', close], ['backdrop', viewer], ['stage', stage],
                                          ['caption', caption], ['image', image]]) {
              api.openImageViewer(SRC, 'again', 'prompt', null);
              fire(target, 'click', { detail: 1, clientX: 0, clientY: 0 });
              results[name] = snap().open;
              if (snap().open) api.closeImageViewer();
            }
            done(results);
            """
        )
        assert out == {
            "button": False,
            "backdrop": False,
            "stage": False,
            "caption": True,
            "image": True,
        }

    def test_the_caption_says_the_pixels_once_loaded(self) -> None:
        out = _panel(OPEN_WIDE + "done(snap().caption);")
        assert out == (
            'ui.image.dimensions|{"name":"wide shot","width":"1920","height":"1080"}'
        )

    def test_an_image_without_a_name_is_called_what_the_dialog_is_called(self) -> None:
        out = _panel(
            """
            const src = ORIGIN + '/x';
            sizes[src] = { w: 10, h: 10 };
            api.openImageViewer(src, '   ', 'prompt', null);
            done(snap());
            """
        )
        assert out["alt"] == ""
        assert out["caption"] == (
            'ui.image.dimensions|{"name":"ui.image.viewerTitle","width":"10","height":"10"}'
        )

    def test_tab_stays_on_the_two_buttons(self) -> None:
        out = _panel(
            OPEN_WIDE
            + """
            const tab = (shift) => {
              const e = press(activeElement, 'Tab', { shiftKey: !!shift });
              return { prevented: e.defaultPrevented, focus: snap().focus };
            };
            const steps = [snap().focus];               // starts on close
            steps.push(tab(false));                     // close is the last stop: wraps to 1:1
            zoom.focus();
            steps.push(tab(false));                     // 1:1 -> close: the browser does that, not taken
            steps.push(tab(true));                      // the first stop, Shift+Tab: wraps to close
            done(steps);
            """
        )
        assert out[0] == "close"
        assert out[1] == {"prevented": True, "focus": "zoom"}
        assert out[2]["prevented"] is False
        assert out[3] == {"prevented": True, "focus": "close"}

    def test_tab_skips_the_1_1_button_while_it_is_off(self) -> None:
        out = _panel(
            """
            const small = ORIGIN + '/small';
            sizes[small] = { w: 100, h: 60 };
            api.openImageViewer(small, 'small', 'prompt', null);
            const forward = press(close, 'Tab');
            const afterForward = snap().focus;
            const backward = press(close, 'Tab', { shiftKey: true });
            const afterBackward = snap().focus;
            done({ forward: forward.defaultPrevented, backward: backward.defaultPrevented, afterForward, afterBackward });
            """
        )
        # one stop left: each key keeps the focus on it (a stop on the switch that is off would show after the first)
        assert out == {
            "forward": True,
            "backward": True,
            "afterForward": "close",
            "afterBackward": "close",
        }

    def test_tab_from_outside_comes_back_in(self) -> None:
        out = _panel(
            OPEN_WIDE
            + """
            const outside = new El('button');
            outside.focus();
            const event = press(outside, 'Tab');
            done({ prevented: event.defaultPrevented, focus: snap().focus });
            """
        )
        assert out == {"prevented": True, "focus": "zoom"}

    def test_shift_tab_from_outside_comes_back_in_at_the_other_end(self) -> None:
        out = _panel(
            OPEN_WIDE
            + """
            const outside = new El('button');
            outside.focus();
            const event = press(outside, 'Tab', { shiftKey: true });
            done({ prevented: event.defaultPrevented, focus: snap().focus });
            """
        )
        assert out == {"prevented": True, "focus": "close"}

    def test_other_keys_are_left_alone_while_it_is_open(self) -> None:
        out = _panel(
            OPEN_WIDE
            + """
            done(['a', 'ArrowDown', 'Enter', ' ', 'Backspace'].map((k) => {
              const event = press(close, k);
              return { k, prevented: event.defaultPrevented, stopped: event.stopped, focus: snap().focus, open: snap().open };
            }));
            """
        )
        assert out == [
            {
                "k": k,
                "prevented": False,
                "stopped": False,
                "focus": "close",
                "open": True,
            }
            for k in ("a", "ArrowDown", "Enter", " ", "Backspace")
        ]

    def test_the_page_behind_does_not_see_the_escape_that_closes_it(self) -> None:
        # the panel has key shortcuts of its own, and they are registered before the viewer opens
        out = _panel(
            """
            const seen = [];
            document.addEventListener('keydown', (e) => seen.push(e.key));
            sizes[SRC] = { w: 1920, h: 1080 };
            api.openImageViewer(SRC, 'wide', 'prompt', null);
            press(close, 'Escape');
            done({ seen, open: snap().open });
            """
        )
        assert out == {"seen": [], "open": False}

    def test_a_key_that_an_input_method_is_using_is_left_alone(self) -> None:
        out = _panel(
            OPEN_WIDE
            + """
            press(close, 'Escape', { isComposing: true });
            press(close, 'Escape', { keyCode: 229 });
            press(close, 'Escape', { defaultPrevented: true });
            done({ open: snap().open });
            """
        )
        assert out == {"open": True}

    def test_opening_twice_listens_once(self) -> None:
        out = _panel(
            OPEN_WIDE
            + """
            api.openImageViewer(SRC, 'second', 'prompt', null);
            done({ keys: docCount('keydown'), alt: snap().alt });
            """
        )
        assert out == {"keys": 1, "alt": "second"}

    def test_an_image_without_an_address_opens_nothing(self) -> None:
        out = _panel(
            """
            const results = ['', null, undefined].map((src) => api.openImageViewer(src, 'x', 'prompt', null));
            done({ results, snap: snap() });
            """
        )
        assert out["results"] == [False, False, False]
        assert out["snap"]["open"] is False
        assert out["snap"]["keys"] == 0

    def test_a_viewer_without_its_markup_opens_nothing(self) -> None:
        out = _panel(
            """
            byId.delete('imageViewerStage');
            done({ opened: api.openImageViewer(SRC, 'x', 'prompt', null), closed: api.closeImageViewer(),
                   open: api.isImageViewerOpen(), keys: docCount('keydown'), errors: logs.error });
            """
        )
        assert out["opened"] is False
        assert out["closed"] is False
        assert out["keys"] == 0 and out["errors"] == []


@needs_node
class TestPanelImages:
    def test_an_image_of_the_message_becomes_a_button_that_names_itself(self) -> None:
        out = _panel(
            """
            const named = mkImg('wide shot'), plain = mkImg(null, { n: 1 }), blank = mkImg('  ', { n: 2 });
            api.enablePromptImageZoom(mkMessage(named, plain, blank));
            const attrs = (img) => ({
              zoom: img.getAttribute('data-aiia-zoom'), tabindex: img.getAttribute('tabindex'),
              role: img.getAttribute('role'), label: img.getAttribute('aria-label'),
              click: img.count('click'), keydown: img.count('keydown'), error: img.count('error'),
            });
            done({ named: attrs(named), plain: attrs(plain), blank: attrs(blank) });
            """
        )
        named = out["named"]
        assert named["zoom"] == "prompt"
        assert (named["tabindex"], named["role"]) == ("0", "button")
        assert named["label"] == 'ui.image.enlargeNamed|{"name":"wide shot"}'
        assert (named["click"], named["keydown"], named["error"]) == (1, 1, 1)
        assert out["plain"]["label"] == "ui.image.enlarge"
        assert out["blank"]["label"] == "ui.image.enlarge"

    def test_a_second_pass_changes_nothing(self) -> None:
        out = _panel(
            """
            const img = mkImg('a'), message = mkMessage(img);
            api.enablePromptImageZoom(message);
            api.enablePromptImageZoom(message);
            done({ click: img.count('click'), keydown: img.count('keydown'), error: img.count('error') });
            """
        )
        assert out == {"click": 1, "keydown": 1, "error": 1}

    def test_an_image_inside_a_link_or_one_that_did_not_load_is_left_alone(
        self,
    ) -> None:
        out = _panel(
            """
            const badge = mkImg('badge'), link = new El('a', { href: 'https://example.com' });
            link.appendChild(badge);
            const broken = mkImg('broken', { w: 0, h: 0, n: 1 });
            const loading = mkImg('loading', { complete: false, w: 0, h: 0, n: 2 });
            api.enablePromptImageZoom(mkMessage(link, broken, loading));
            done({ badge: badge.getAttribute('data-aiia-zoom'), broken: broken.getAttribute('data-aiia-zoom'),
                   loading: loading.getAttribute('data-aiia-zoom') });
            """
        )
        assert out == {"badge": None, "broken": None, "loading": "prompt"}

    def test_an_image_that_fails_late_loses_the_offer(self) -> None:
        out = _panel(
            """
            const img = mkImg('late', { complete: false, w: 0, h: 0 });
            api.enablePromptImageZoom(mkMessage(img));
            fire(img, 'error');
            done([...img.attrs.keys()].filter((k) => /^(data-aiia-zoom|tabindex|role|aria-label)$/.test(k)));
            """
        )
        assert out == []

    def test_no_container_is_not_an_error(self) -> None:
        out = _panel(
            """
            const results = [];
            for (const value of [null, undefined, {}, 42]) {
              try { api.enablePromptImageZoom(value); results.push('ok'); } catch (e) { results.push(String(e.message)); }
            }
            done(results);
            """
        )
        assert out == ["ok"] * 4

    def test_click_and_plain_enter_or_space_open_it_from_the_message(self) -> None:
        out = _panel(
            """
            const img = mkImg('keyed');
            sizes[img.currentSrc] = { w: 1920, h: 1080 };
            api.enablePromptImageZoom(mkMessage(img));
            const results = [];
            for (const key of ['Enter', ' ', 'Spacebar']) {
              img.focus();
              const e = press(img, key);
              const s = snap();
              results.push({ key, prevented: e.defaultPrevented, open: s.open, source: s.state.source, focus: s.focus, src: s.src });
              api.closeImageViewer();
            }
            img.focus();
            fire(img, 'click');
            results.push({ key: 'click', open: snap().open, src: snap().src, alt: snap().alt });
            api.closeImageViewer();
            // somebody else's chords, a key an input method is using, a key already taken: nothing opens
            for (const props of [{ ctrlKey: true }, { metaKey: true }, { altKey: true }, { shiftKey: true },
                                 { isComposing: true }, { defaultPrevented: true }]) {
              const e = press(img, 'Enter', props);
              results.push({ props, open: snap().open, prevented: props.defaultPrevented ? false : e.defaultPrevented });
            }
            const other = press(img, 'a');
            results.push({ key: 'a', open: snap().open, prevented: other.defaultPrevented });
            done(results);
            """
        )
        for item in out[:3]:
            assert item["prevented"] is True and item["open"] is True
            assert item["source"] == "prompt" and item["focus"] == "close"
            # what the browser picked, in full: the viewer must show the image that was clicked
            assert item["src"] == "http://127.0.0.1:8080/api/tasks/t1/images/0"
        assert out[3] == {
            "key": "click",
            "open": True,
            "src": "http://127.0.0.1:8080/api/tasks/t1/images/0",
            "alt": "keyed",
        }
        assert len(out[4:]) == 7
        for item in out[4:]:
            assert item["open"] is False and item["prevented"] is False

    def test_a_broken_image_opens_nothing(self) -> None:
        out = _panel(
            """
            const img = mkImg('later', { complete: false, w: 0, h: 0 });
            api.enablePromptImageZoom(mkMessage(img));
            img.complete = true;
            fire(img, 'click');
            done(snap().open);
            """
        )
        assert out is False

    def test_an_image_of_the_old_message_goes_when_the_message_is_written_again(
        self,
    ) -> None:
        out = _panel(
            """
            const old = mkImg('old');
            sizes[old.currentSrc] = { w: 1920, h: 1080 };
            api.enablePromptImageZoom(mkMessage(old));
            fire(old, 'click');
            const before = snap().open;
            old.detached = true;
            api.enablePromptImageZoom(mkMessage(mkImg('fresh', { n: 5 })));
            done({ before, after: snap() });
            """
        )
        assert out["before"] is True
        assert out["after"]["open"] is False
        assert out["after"]["state"]["source"] == ""

    def test_a_thumbnail_opens_the_viewer_and_the_message_does_not_take_it_back(
        self,
    ) -> None:
        out = _panel(
            """
            const thumb = mkImg('photo.png', { w: 640, h: 480 });
            thumb.attrs.set('src', 'data:image/png;base64,AAAA');
            thumb.currentSrc = 'data:image/png;base64,AAAA';
            sizes[thumb.currentSrc] = { w: 640, h: 480 };
            api.makeImageZoomable(thumb, 'attachment');
            fire(thumb, 'click');
            const opened = snap();
            api.enablePromptImageZoom(mkMessage(mkImg('another', { n: 3 })));
            done({ opened, label: thumb.getAttribute('aria-label'), after: snap() });
            """
        )
        assert out["opened"]["open"] is True
        assert out["opened"]["state"]["source"] == "attachment"
        assert out["label"] == 'ui.image.enlargeNamed|{"name":"photo.png"}'
        assert out["after"]["open"] is True

    def test_an_attachment_that_was_taken_off_the_list_takes_the_viewer_with_it(
        self,
    ) -> None:
        out = _panel(
            """
            const data = 'data:image/png;base64,BBBB';
            sizes[data] = { w: 640, h: 480 };
            api.setUploaded([{ name: 'a.png', data }, { name: 'b.png', data: 'data:image/png;base64,CCCC' }]);
            api.openImageViewer(data, 'a.png', 'attachment', null);
            api.closeImageViewerIfAttachmentGone();
            const kept = snap().open;
            api.setUploaded([{ name: 'b.png', data: 'data:image/png;base64,CCCC' }]);
            api.closeImageViewerIfAttachmentGone();
            done({ kept, gone: snap().open });
            """
        )
        assert out == {"kept": True, "gone": False}

    def test_a_viewer_of_the_message_is_not_touched_by_the_attachments_list(
        self,
    ) -> None:
        out = _panel(
            OPEN_WIDE
            + """
            api.setUploaded([]);
            api.closeImageViewerIfAttachmentGone();
            done(snap().open);
            """
        )
        assert out is True

    def test_nothing_prints_a_warning_or_an_error(self) -> None:
        out = _panel(
            OPEN_WIDE
            + """
            fire(image, 'click', { detail: 1, clientX: 10, clientY: 60 });
            press(close, 'Tab');
            press(close, 'Escape');
            done({ warn: logs.warn, error: logs.error, debug: logs.debug });
            """
        )
        assert out == {"warn": [], "error": [], "debug": []}


# ============================================================================== the panel's source
class TestPanelWiring:
    def test_the_messages_images_are_marked_at_once_not_at_an_idle_moment(self) -> None:
        body = _extract_function(
            PANEL_JS.read_text(encoding="utf-8"),
            "function schedulePromptEnhancements(",
        )
        assert body.index("enablePromptImageZoom(markdownContent)") < body.index(
            "scheduleLowPriorityWork("
        )

    def test_every_place_that_writes_the_message_goes_through_that_function(
        self,
    ) -> None:
        source = PANEL_JS.read_text(encoding="utf-8")
        writes = [
            m.start() for m in re.finditer(r"markdownContent\.innerHTML = ", source)
        ]
        assert len(writes) == 3
        for position in writes:
            assert (
                "schedulePromptEnhancements(markdownContent, promptKey, renderSeq)"
                in source[position : position + 500]
            )

    def test_the_thumbnails_of_attachments_are_marked_and_the_list_checks_the_viewer(
        self,
    ) -> None:
        source = PANEL_JS.read_text(encoding="utf-8")
        body = _extract_function(source, "function renderUploadedImages(")
        assert "makeImageZoomable(img, 'attachment')" in body
        # the list is built again from the attachments that are left: a viewer open on one that is gone has to hear it
        assert "closeImageViewerIfAttachmentGone()" in body

    def test_the_viewer_is_wired_when_the_page_starts(self) -> None:
        body = _extract_function(
            PANEL_JS.read_text(encoding="utf-8"), "function setupEventListeners("
        )
        assert "initImageViewer()" in body

    def test_the_viewer_is_a_modal_dialog_with_the_controls_the_script_looks_for(
        self,
    ) -> None:
        ts = PANEL_TS.read_text(encoding="utf-8")
        start = ts.index('<div class="image-viewer hidden" id="imageViewer"')
        dialog = ts[start : ts.index('id="imageViewerClose"', start) + 700]
        assert 'role="dialog"' in dialog
        assert 'aria-modal="true"' in dialog
        for ident in (
            "imageViewerStage",
            "imageViewerImg",
            "imageViewerCaption",
            "imageViewerZoom",
            "imageViewerClose",
        ):
            assert f'id="{ident}"' in dialog
        # what a screen reader says, and what the buttons say, follows the language of the panel
        for key in (
            "ui.image.viewerTitle",
            "ui.image.viewerActualSize",
            "ui.image.viewerClose",
        ):
            assert f'data-i18n-aria-label="{key}"' in dialog
        assert 'aria-pressed="false"' in dialog
        assert dialog.count('type="button"') == 2

    def test_the_viewer_sits_after_the_settings_dialog_and_before_the_scripts(
        self,
    ) -> None:
        ts = PANEL_TS.read_text(encoding="utf-8")
        assert (
            ts.index('id="settingsOverlay"')
            < ts.index('id="imageViewer"')
            < ts.index('<script nonce="${nonce}" src="${prismBootstrapUri}"></script>')
        )

    def test_the_content_security_policy_already_lets_the_viewer_show_what_the_message_shows(
        self,
    ) -> None:
        # the viewer shows the same URLs the message does, so no new source is needed
        assert "img-src data: ${serverUrl} ${cspSource};" in PANEL_TS.read_text(
            encoding="utf-8"
        )

    def test_the_script_looks_for_nothing_the_markup_lacks(self) -> None:
        wanted = set(re.findall(r"getElementById\('([A-Za-z]+)'\)", _panel_block()))
        assert wanted == {
            "imageViewer",
            "imageViewerStage",
            "imageViewerImg",
            "imageViewerCaption",
            "imageViewerZoom",
            "imageViewerClose",
        }
        ts = PANEL_TS.read_text(encoding="utf-8")
        for ident in wanted:
            assert f'id="{ident}"' in ts, ident


class TestPanelStylesheet:
    def test_the_images_that_open_show_it_with_the_cursor(self) -> None:
        for selector in (
            ".markdown-content img[data-aiia-zoom]",
            ".image-preview img[data-aiia-zoom]",
        ):
            assert _merged(PANEL_RULES, selector)["cursor"] == "zoom-in"

    def test_the_viewer_covers_the_panel_with_the_settings_dialog_and_below_the_toasts(
        self,
    ) -> None:
        viewer = _merged(PANEL_RULES, ".image-viewer")
        assert viewer["position"] == "fixed"
        assert viewer["inset"] == "0"
        overlay = _merged(PANEL_RULES, ".settings-overlay")
        toasts = _merged(PANEL_RULES, ".toast-host")
        assert int(viewer["z-index"]) == int(overlay["z-index"])
        assert int(viewer["z-index"]) < int(toasts["z-index"])
        # opaque enough that the message behind it does not compete
        alpha = re.search(r"rgba\(0, 0, 0, ([\d.]+)\)", viewer["background"])
        assert alpha is not None and float(alpha.group(1)) >= 0.9

    def test_fit_clips_and_the_image_at_its_own_size_scrolls(self) -> None:
        stage = _merged(PANEL_RULES, ".image-viewer-stage")
        assert stage["overflow"] == "hidden"
        assert (
            stage["position"] == "relative"
        )  # ``offsetLeft`` of the image counts from here
        assert stage["min-height"] == "0"
        assert (
            _merged(PANEL_RULES, ".image-viewer.is-actual .image-viewer-stage")[
                "overflow"
            ]
            == "auto"
        )

    def test_the_image_is_centred_without_losing_its_top_left_when_it_is_larger(
        self,
    ) -> None:
        # ``justify-content: center`` would put the left part of an oversized image out of reach; auto margins do not
        image = _merged(PANEL_RULES, ".image-viewer-img")
        assert image["margin"] == "auto"
        assert image["max-width"] == "100%" and image["max-height"] == "100%"
        stage = _merged(PANEL_RULES, ".image-viewer-stage")
        assert "justify-content" not in stage and "align-items" not in stage

    def test_at_its_own_size_the_image_is_not_limited(self) -> None:
        rule = _merged(PANEL_RULES, ".image-viewer.is-actual .image-viewer-img")
        assert rule["max-width"] == "none" and rule["max-height"] == "none"
        assert rule["cursor"] == "zoom-out"
        enlarge = _merged(PANEL_RULES, ".image-viewer.can-enlarge .image-viewer-img")
        assert enlarge["cursor"] == "zoom-in"

    def test_the_pressed_1_1_button_is_marked_and_the_off_one_is_dimmed(self) -> None:
        pressed = _merged(PANEL_RULES, '.image-viewer-btn[aria-pressed="true"]')
        assert "--vscode-button-background" in pressed["background"]
        assert "--vscode-button-foreground" in pressed["color"]
        off = _merged(PANEL_RULES, ".image-viewer-btn:disabled")
        assert float(off["opacity"]) < 1
        assert off["cursor"] == "default"

    def test_the_caption_never_wraps(self) -> None:
        rule = _merged(PANEL_RULES, ".image-viewer-caption")
        assert rule["white-space"] == "nowrap"
        assert rule["text-overflow"] == "ellipsis"
        assert rule["overflow"] == "hidden"


# ============================================================================== the strings
WEB_KEYS = {
    "page": ["imageEnlarge", "imageEnlargeNamed"],
    "status": ["imageDimensionsLabel"],
}
PANEL_KEYS = [
    "enlarge",
    "enlargeNamed",
    "viewerTitle",
    "viewerClose",
    "viewerActualSize",
    "dimensions",
]


def _placeholders(text: str) -> set[str]:
    return set(re.findall(r"\{\{(\w+)\}\}", text))


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


class TestStrings:
    @pytest.mark.parametrize("lang", LOCALES)
    def test_the_page_has_every_string_with_the_same_placeholders(
        self, lang: str
    ) -> None:
        data = _load(WEB_LOCALES / f"{lang}.json")
        reference = _load(WEB_LOCALES / "en.json")
        for group, keys in WEB_KEYS.items():
            for key in keys:
                text = data[group][key]
                assert text.strip(), f"{lang} {group}.{key} is empty"
                assert _placeholders(text) == _placeholders(reference[group][key])
        assert _placeholders(reference["page"]["imageEnlargeNamed"]) == {"name"}
        assert _placeholders(reference["status"]["imageDimensionsLabel"]) == {
            "name",
            "width",
            "height",
        }

    @pytest.mark.parametrize("lang", LOCALES)
    def test_the_panel_has_every_string_with_the_same_placeholders(
        self, lang: str
    ) -> None:
        data = _load(PANEL_LOCALES / f"{lang}.json")
        reference = _load(PANEL_LOCALES / "en.json")
        for key in PANEL_KEYS:
            text = data["ui"]["image"][key]
            assert text.strip(), f"{lang} ui.image.{key} is empty"
            assert _placeholders(text) == _placeholders(reference["ui"]["image"][key])
        assert _placeholders(reference["ui"]["image"]["enlargeNamed"]) == {"name"}
        assert _placeholders(reference["ui"]["image"]["dimensions"]) == {
            "name",
            "width",
            "height",
        }

    def test_the_typed_keys_of_the_panel_know_them(self) -> None:
        text = PANEL_KEYS_DTS.read_text(encoding="utf-8")
        for key in PANEL_KEYS:
            # the file names every key twice: in the union type and in the list that goes with it
            assert f'  | "ui.image.{key}"\n' in text
            assert f'  "ui.image.{key}",\n' in text

    def test_every_key_the_code_asks_for_exists(self) -> None:
        asked_web = set(
            re.findall(
                r't\("((?:page\.imageEnlarge(?:Named)?)|status\.imageDimensionsLabel)"',
                _web_code(),
            )
        )
        assert asked_web == {
            "page.imageEnlarge",
            "page.imageEnlargeNamed",
            "status.imageDimensionsLabel",
        }
        # the panel asks for four from the script; the other two are the words of the buttons, in the markup
        asked_panel = set(re.findall(r"\bt\('(ui\.image\.[A-Za-z]+)'", _panel_block()))
        assert asked_panel == {
            "ui.image.dimensions",
            "ui.image.enlarge",
            "ui.image.enlargeNamed",
            "ui.image.viewerTitle",
        }
        markup = set(
            re.findall(
                r"data-i18n-[a-z-]+=\"(ui\.image\.[A-Za-z]+)\"",
                PANEL_TS.read_text(encoding="utf-8"),
            )
        )
        assert markup == {
            "ui.image.viewerTitle",
            "ui.image.viewerActualSize",
            "ui.image.viewerClose",
        }
        assert asked_panel | markup == {f"ui.image.{key}" for key in PANEL_KEYS}

    def test_the_wording_says_what_it_does(self) -> None:
        en = _load(WEB_LOCALES / "en.json")
        zh = _load(WEB_LOCALES / "zh-CN.json")
        assert "larger" in en["page"]["imageEnlarge"].lower()
        assert "大图" in zh["page"]["imageEnlarge"]
        assert "px" in en["status"]["imageDimensionsLabel"]
        assert "像素" in zh["status"]["imageDimensionsLabel"]
        panel_zh = _load(PANEL_LOCALES / "zh-CN.json")
        assert panel_zh["ui"]["image"]["viewerActualSize"] == "实际大小"
