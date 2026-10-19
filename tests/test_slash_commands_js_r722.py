"""R722: runtime and wiring invariants for the ``/`` skill picker (slash-commands.js).

``slash-commands.js`` is a shared module: the very same file is served by the
Web UI (``static/js``) and shipped inside the VS Code extension, so every
behaviour below has to hold for both hosts.

The runtime tests run the real file in a Node ``vm`` context against a small
hand-written DOM (there is no jsdom in this repo).  The fake DOM implements
capture / target / bubble dispatch, ``stopImmediatePropagation`` and the
``execCommand`` quirks the module has to survive, because the interesting bugs
of a picker live exactly there: who sees ``Enter`` first, what happens when the
catalogue request fails, and whether listeners leak after a reload.

The wiring tests pin the places where forgetting one file silently ships a
half-working feature (template tag, webview tag, packaging lists, locale keys,
CSS for both hosts).
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import textwrap
import unittest
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
STATIC_DIR = REPO_ROOT / "src" / "ai_intervention_agent" / "static"
WEB_JS = STATIC_DIR / "js" / "slash-commands.js"
PLUGIN_DIR = REPO_ROOT / "packages" / "vscode"
PLUGIN_JS = PLUGIN_DIR / "slash-commands.js"
TEMPLATE = REPO_ROOT / "src" / "ai_intervention_agent" / "templates" / "web_ui.html"
WEB_UI_PY = REPO_ROOT / "src" / "ai_intervention_agent" / "web_ui.py"
WEB_CSS = STATIC_DIR / "css" / "main.css"
PLUGIN_CSS = PLUGIN_DIR / "webview.css"
WEBVIEW_TS = PLUGIN_DIR / "webview.ts"

LOCALE_FILES = (
    STATIC_DIR / "locales" / "en.json",
    STATIC_DIR / "locales" / "zh-CN.json",
    STATIC_DIR / "locales" / "zh-TW.json",
    PLUGIN_DIR / "locales" / "en.json",
    PLUGIN_DIR / "locales" / "zh-CN.json",
    PLUGIN_DIR / "locales" / "zh-TW.json",
)

pytestmark = pytest.mark.skipif(
    shutil.which("node") is None, reason="node is required for the picker runtime tests"
)


# --------------------------------------------------------------------------
# Node harness
# --------------------------------------------------------------------------

_HARNESS = r"""
const fs = require('fs');
const vm = require('vm');
const CODE_PATH = __CODE_PATH__;
const CODE = fs.readFileSync(CODE_PATH, 'utf8');

class FakeEvent {
  constructor(type, init) {
    this.type = type;
    this.bubbles = false;
    this.cancelable = true;
    Object.assign(this, init || {});
    this.target = null;
    this.defaultPrevented = false;
    this._stopped = false;
    this._immediate = false;
  }
  preventDefault() { this.defaultPrevented = true; }
  stopPropagation() { this._stopped = true; }
  stopImmediatePropagation() { this._stopped = true; this._immediate = true; }
}

function captureFlag(opts) {
  return opts === true || !!(opts && opts.capture);
}

class FakeNode {
  constructor(tag, env) {
    this.env = env;
    this.nodeType = tag === '#fragment' ? 11 : tag === '#document' ? 9 : 1;
    this.tagName = String(tag).toUpperCase();
    this.children = [];
    this.parentNode = null;
    this.attrs = {};
    this.listeners = [];
    this.style = {};
    this.hidden = false;
    this.className = '';
    this.id = '';
    this.title = '';
    this._text = '';
    this.scrollTop = 0;
    this.offsetTop = 0;
    this.offsetHeight = 20;
    this.clientHeight = 100;
  }
  get isConnected() {
    let node = this;
    while (node.parentNode) node = node.parentNode;
    return node === this.env.document;
  }
  get textContent() {
    return this.children.length ? this.children.map((c) => c.textContent).join('') : this._text;
  }
  set textContent(value) {
    for (const child of this.children) child.parentNode = null;
    this.children = [];
    this._text = String(value);
  }
  setAttribute(name, value) { this.attrs[name] = String(value); }
  getAttribute(name) { return Object.prototype.hasOwnProperty.call(this.attrs, name) ? this.attrs[name] : null; }
  hasAttribute(name) { return Object.prototype.hasOwnProperty.call(this.attrs, name); }
  removeAttribute(name) { delete this.attrs[name]; }
  appendChild(child) {
    if (child.nodeType === 11) {
      for (const inner of [...child.children]) this.appendChild(inner);
      child.children = [];
      return child;
    }
    if (child.parentNode) child.parentNode.removeChild(child);
    child.parentNode = this;
    this.children.push(child);
    return child;
  }
  removeChild(child) {
    const index = this.children.indexOf(child);
    if (index >= 0) this.children.splice(index, 1);
    child.parentNode = null;
    return child;
  }
  contains(node) {
    for (let n = node; n; n = n.parentNode) if (n === this) return true;
    return false;
  }
  closest(selector) {
    const wanted = selector.replace(/^\./, '');
    for (let n = this; n && n.nodeType === 1; n = n.parentNode) {
      if (String(n.className).split(/\s+/).includes(wanted)) return n;
    }
    return null;
  }
  addEventListener(type, fn, options) {
    this.listeners.push({ type, fn, capture: captureFlag(options) });
  }
  removeEventListener(type, fn, options) {
    const capture = captureFlag(options);
    this.listeners = this.listeners.filter((l) => !(l.type === type && l.fn === fn && l.capture === capture));
  }
  dispatchEvent(event) {
    event.target = this;
    const path = [];
    for (let n = this; n; n = n.parentNode) path.unshift(n);
    const run = (node, capture, atTarget) => {
      for (const l of [...node.listeners]) {
        if (l.type !== event.type) continue;
        if (!atTarget && l.capture !== capture) continue;
        event.currentTarget = node;
        l.fn.call(node, event);
        if (event._immediate) return true;
      }
      return false;
    };
    for (let i = 0; i < path.length - 1; i += 1) {
      if (run(path[i], true, false) || event._stopped) return !event.defaultPrevented;
    }
    if (run(this, false, true) || event._stopped || !event.bubbles) return !event.defaultPrevented;
    for (let i = path.length - 2; i >= 0; i -= 1) {
      if (run(path[i], false, false) || event._stopped) break;
    }
    return !event.defaultPrevented;
  }
}

class FakeTextarea extends FakeNode {
  constructor(env) {
    super('textarea', env);
    this.value = '';
    this.selectionStart = 0;
    this.selectionEnd = 0;
    this.disabled = false;
    this.readOnly = false;
    this.rect = { left: 100, top: 500, right: 700, bottom: 600, width: 600, height: 100 };
    this.attrs['data-aiia-slash-commands'] = '';
    this.setRangeTextCalls = 0;
  }
  focus() { this.env.document.activeElement = this; }
  blur() {
    if (this.env.document.activeElement !== this) return;
    this.dispatchEvent(new FakeEvent('focusout', { bubbles: true }));
    this.env.document.activeElement = this.env.document.body;
  }
  setSelectionRange(start, end) { this.selectionStart = start; this.selectionEnd = end; }
  setRangeText(text, start, end, mode) {
    this.setRangeTextCalls += 1;
    const from = start === undefined ? this.selectionStart : start;
    const to = end === undefined ? this.selectionEnd : end;
    this.value = this.value.slice(0, from) + text + this.value.slice(to);
    const caret = from + text.length;
    if (mode === 'end') { this.selectionStart = caret; this.selectionEnd = caret; }
  }
  getBoundingClientRect() {
    const r = this.rect;
    return { left: r.left, top: r.top, right: r.right, bottom: r.bottom, width: r.width, height: r.height, x: r.left, y: r.top };
  }
}

function createEnvironment(options) {
  const opts = options || {};
  const env = {
    now: 1000000,
    execMode: opts.execMode || 'native',
    fetchCalls: [],
    consoleCalls: [],
    inputEvents: 0,
    timers: [],
    nextTimerId: 1,
    payload: { status: 'success', skills: opts.skills === undefined ? DEFAULT_SKILLS : opts.skills },
  };
  const document = new FakeNode('#document', env);
  env.document = document;
  const html = new FakeNode('html', env);
  html.clientHeight = opts.clientHeight || 800;
  const body = new FakeNode('body', env);
  document.appendChild(html);
  html.appendChild(body);
  document.documentElement = html;
  document.body = body;
  document.activeElement = body;
  document.visibilityState = 'visible';
  document.readyState = 'complete';
  document.createElement = (tag) => new FakeNode(tag, env);
  document.createDocumentFragment = () => new FakeNode('#fragment', env);
  document.getElementById = (id) => {
    const walk = (node) => {
      if (node.id === id) return node;
      for (const child of node.children) {
        const hit = walk(child);
        if (hit) return hit;
      }
      return null;
    };
    return walk(document);
  };
  document.execCommand = (command, _ui, text) => {
    if (command !== 'insertText') return false;
    if (env.execMode === 'throw') throw new Error('execCommand blocked');
    if (env.execMode === 'noop') return false;
    if (env.execMode === 'lies') return true;
    const target = document.activeElement;
    if (!target || target.tagName !== 'TEXTAREA') return false;
    target.value = target.value.slice(0, target.selectionStart) + text + target.value.slice(target.selectionEnd);
    const caret = target.selectionStart + text.length;
    target.selectionStart = caret;
    target.selectionEnd = caret;
    env.inputEvents += 1;
    target.dispatchEvent(new FakeEvent('input', { bubbles: true }));
    return true;
  };

  const win = {
    innerWidth: opts.width || 1000,
    innerHeight: opts.height || 800,
    visualViewport: opts.visualViewport || null,
    listeners: [],
    document,
    Event: FakeEvent,
    Date: { now: () => env.now },
    console: {
      log: (...a) => env.consoleCalls.push(['log', a.join(' ')]),
      info: (...a) => env.consoleCalls.push(['info', a.join(' ')]),
      debug: (...a) => env.consoleCalls.push(['debug', a.join(' ')]),
      warn: (...a) => env.consoleCalls.push(['warn', a.join(' ')]),
      error: (...a) => env.consoleCalls.push(['error', a.join(' ')]),
    },
    addEventListener(type, fn, options2) { this.listeners.push({ type, fn, capture: captureFlag(options2) }); },
    removeEventListener(type, fn, options2) {
      const capture = captureFlag(options2);
      this.listeners = this.listeners.filter((l) => !(l.type === type && l.fn === fn && l.capture === capture));
    },
    setTimeout(fn, ms) {
      const id = env.nextTimerId++;
      env.timers.push({ id, fn, ms });
      return id;
    },
    clearTimeout(id) { env.timers = env.timers.filter((t) => t.id !== id); },
    AbortController: class {
      constructor() {
        this.signal = { aborted: false, listeners: [], addEventListener(_t, fn) { this.listeners.push(fn); } };
      }
      abort() {
        this.signal.aborted = true;
        for (const fn of this.signal.listeners) fn();
      }
    },
    fetch(url, init) {
      env.fetchCalls.push({ url, init });
      return env.fetchImpl(url, init);
    },
  };
  if (opts.i18n !== undefined) win.AIIA_I18N = opts.i18n;
  env.window = win;
  env.fetchImpl = () => Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(env.payload) });

  env.dispatchWindow = (type, event) => {
    for (const l of [...win.listeners]) if (l.type === type) l.fn.call(win, event || new FakeEvent(type));
  };
  env.makeTextarea = () => {
    const ta = new FakeTextarea(env);
    body.appendChild(ta);
    return ta;
  };
  env.addConfig = (serverUrl) => {
    const meta = new FakeNode('meta', env);
    meta.id = 'aiia-config';
    meta.setAttribute('data-server-url', serverUrl);
    body.appendChild(meta);
    return meta;
  };
  env.load = () => {
    const context = win;
    win.window = win;
    win.globalThis = win;
    if (!vm.isContext(win)) vm.createContext(win);
    vm.runInContext(CODE, win);
    env.api = win.AIIASlashCommands;
    return env.api;
  };
  env.popup = () => body.children.find((c) => String(c.className).split(/\s+/).includes('aiia-slash-popup')) || null;
  env.rows = () => {
    const popup = env.popup();
    return popup ? popup.children.slice() : [];
  };
  env.tokens = () => env.rows().map((row) => row.children[0].children[0].textContent);
  env.isOpen = () => {
    const popup = env.popup();
    return !!popup && !popup.hidden && popup.children.length > 0;
  };
  env.activeIndex = () => env.rows().findIndex((row) => row.getAttribute('aria-selected') === 'true');
  env.flush = async () => {
    for (let i = 0; i < 6; i += 1) await new Promise((resolve) => setImmediate(resolve));
  };
  env.type = async (textarea, text) => {
    textarea.focus();
    for (const ch of text) {
      textarea.value = textarea.value.slice(0, textarea.selectionStart) + ch + textarea.value.slice(textarea.selectionEnd);
      const caret = textarea.selectionStart + 1;
      textarea.selectionStart = caret;
      textarea.selectionEnd = caret;
      textarea.dispatchEvent(new FakeEvent('input', { bubbles: true }));
      await env.flush();
    }
  };
  env.key = (textarea, key, init) => {
    const event = new FakeEvent('keydown', Object.assign({ key, bubbles: true, shiftKey: false, altKey: false, ctrlKey: false, metaKey: false, keyCode: 0 }, init || {}));
    textarea.dispatchEvent(event);
    return event;
  };
  env.keyup = (textarea, key) => {
    textarea.dispatchEvent(new FakeEvent('keyup', { key, bubbles: true }));
  };
  env.docListenerCount = () => document.listeners.length;
  return env;
}

const DEFAULT_SKILLS = [
  { name: 'alpha-skill', insert: 'alpha-skill', description: 'First skill about reviewing code', kind: 'skill', source: '~/.cursor/skills' },
  { name: 'CTF·Web 漏洞', insert: 'ctf-web', description: 'Web exploitation helper', kind: 'skill', source: '~/.codex/skills' },
  { name: 'review', insert: 'review', description: 'Review the staged changes', kind: 'command', source: '~/.cursor/commands' },
  { name: 'release-notes', insert: 'release-notes', description: 'Summarise the changelog', kind: 'command', source: '~/.claude/commands' },
  { name: 'reverse-engineering', insert: 'reverse-engineering', description: 'Reverse engineer binaries', kind: 'skill', source: '~/.cursor/skills' },
];

async function main(fn) {
  try {
    const result = await fn();
    process.stdout.write('\n__RESULT__' + JSON.stringify(result === undefined ? null : result) + '\n');
  } catch (error) {
    process.stderr.write(String(error && error.stack ? error.stack : error) + '\n');
    process.exit(1);
  }
}
"""


def _run_node(case_js: str, code_path: Path = WEB_JS) -> Any:
    script = (
        _HARNESS.replace("__CODE_PATH__", json.dumps(str(code_path))) + "\n" + case_js
    )
    proc = subprocess.run(
        ["node", "-e", script],
        capture_output=True,
        check=False,
        text=True,
        timeout=30,
    )
    if proc.returncode != 0:
        raise AssertionError(
            f"node exited {proc.returncode}\nstdout={proc.stdout!r}\nstderr={proc.stderr!r}"
        )
    marker = "__RESULT__"
    for line in reversed(proc.stdout.splitlines()):
        if line.startswith(marker):
            return json.loads(line[len(marker) :])
    raise AssertionError(f"no result marker in stdout={proc.stdout!r}")


def _case(body: str) -> str:
    return (
        "main(async () => {\n" + textwrap.indent(textwrap.dedent(body), "  ") + "\n});"
    )


# --------------------------------------------------------------------------
# Pure helpers
# --------------------------------------------------------------------------


class TestPureHelpers(unittest.TestCase):
    def test_find_trigger_table(self) -> None:
        result = _run_node(
            _case(
                """
                const env = createEnvironment();
                const api = env.load();
                const long = '/' + 'x'.repeat(65);
                const cases = [
                  ['/', 1], ['/rev', 4], ['hello /rev', 10], ['hello/rev', 9], ['a/b', 3],
                  ['http://x', 8], ['/a/b', 4], ['/rev ', 5], ['/rev x', 4], ['line1\\n/rev', 10],
                  ['/review', 3], [long, long.length], ['/取证', 3], ['', 0], ['/a', -1], ['/a', 9],
                  ['/a', 1.5], [null, 0], [undefined, 0], ['  /x', 4], ['\\t/x', 3],
                  ['/rev', 0], ['hello /rev', 6], ['/rev', 1],
                ];
                return cases.map(([value, caret]) => [value == null ? null : String(value).slice(0, 12), caret, api.findTrigger(value, caret)]);
                """
            )
        )
        expected = [
            ["/", 1, {"start": 0, "end": 1, "query": ""}],
            ["/rev", 4, {"start": 0, "end": 4, "query": "rev"}],
            ["hello /rev", 10, {"start": 6, "end": 10, "query": "rev"}],
            ["hello/rev", 9, None],
            ["a/b", 3, None],
            ["http://x", 8, None],
            ["/a/b", 4, None],
            ["/rev ", 5, None],
            ["/rev x", 4, {"start": 0, "end": 4, "query": "rev"}],
            ["line1\n/rev", 10, {"start": 6, "end": 10, "query": "rev"}],
            ["/review", 3, {"start": 0, "end": 7, "query": "re"}],
            [("/" + "x" * 65)[:12], 66, None],
            ["/取证", 3, {"start": 0, "end": 3, "query": "取证"}],
            ["", 0, None],
            ["/a", -1, None],
            ["/a", 9, None],
            ["/a", 1.5, None],
            [None, 0, None],
            [None, 0, None],
            ["  /x", 4, {"start": 2, "end": 4, "query": "x"}],
            ["\t/x", 3, {"start": 1, "end": 3, "query": "x"}],
            # the caret has to sit *after* the slash, never in front of it
            ["/rev", 0, None],
            ["hello /rev", 6, None],
            ["/rev", 1, {"start": 0, "end": 4, "query": ""}],
        ]
        self.assertEqual(result, expected)

    def test_normalize_items_filters_unsafe_entries(self) -> None:
        result = _run_node(
            _case(
                """
                const env = createEnvironment();
                const api = env.load();
                const raw = [
                  null, 'text', 7, [], {},
                  { insert: '' }, { insert: '   ' }, { insert: 'has space' }, { insert: 'a/b' },
                  { insert: 'ok' },
                  { insert: ' trimmed ', name: 'Pretty', description: 'd', kind: 'command', source: 's' },
                  { insert: 'odd-kind', kind: 'plugin', name: 5, description: 5, source: 5 },
                ];
                const items = api.normalizeItems(raw);
                const many = api.normalizeItems(Array.from({ length: 2500 }, (_, i) => ({ insert: 'n' + i })));
                return {
                  items: items.map((i) => [i.insert, i.name, i.description, i.kind, i.source]),
                  notArray: [api.normalizeItems(null), api.normalizeItems({}), api.normalizeItems('x')],
                  capped: many.length,
                };
                """
            )
        )
        assert isinstance(result, dict)
        self.assertEqual(
            result["items"],
            [
                ["ok", "ok", "", "skill", ""],
                ["trimmed", "Pretty", "d", "command", "s"],
                ["odd-kind", "odd-kind", "", "skill", ""],
            ],
        )
        self.assertEqual(result["notArray"], [[], [], []])
        self.assertEqual(result["capped"], 2000)

    def test_rank_items_priority_and_stability(self) -> None:
        result = _run_node(
            _case(
                """
                const env = createEnvironment();
                const api = env.load();
                const mk = (insert, name, description) => ({ insert, name: name || insert, description: description || '', kind: 'skill', source: '' });
                const items = api.normalizeItems([
                  mk('zz-review-tool'),                 // word-boundary match
                  mk('xxreviewxx'),                     // plain substring
                  mk('review'),                         // exact
                  mk('reviewer'),                       // prefix, short remainder
                  mk('review-code'),                    // prefix, longer remainder
                  mk('rvw-helper', 'Review Helper'),    // name prefix only
                  mk('abc', 'My Review Tool'),          // name substring only
                  mk('r-e-v-i-e-w'),                    // subsequence of the insert token
                  mk('other', 'Other', 'will review things'),  // description only
                  mk('unrelated', 'Unrelated', 'nothing here'),
                ]);
                const inserts = (list) => list.map((i) => i.insert);
                return {
                  ranked: inserts(api.rankItems(items, 'Review')),
                  singleChar: inserts(api.rankItems(items, 'w')),
                  twoChars: inserts(api.rankItems(items, 'wi')),
                  empty: inserts(api.rankItems(items, '')),
                  limited: inserts(api.rankItems(items, '', 3)),
                  whitespaceOnly: inserts(api.rankItems(items, '')).length,
                  nullQuery: inserts(api.rankItems(items, null)).length,
                  stableTies: inserts(api.rankItems(api.normalizeItems([mk('aa-x'), mk('bb-x'), mk('cc-x')]), 'x')),
                };
                """
            )
        )
        assert isinstance(result, dict)
        self.assertEqual(
            result["ranked"],
            [
                "review",
                "reviewer",
                "review-code",
                "zz-review-tool",
                "xxreviewxx",
                "rvw-helper",
                "abc",
                "r-e-v-i-e-w",
                "other",
            ],
        )
        # One character is far too common to be matched against free-form
        # descriptions, so "other" (whose only 'w' lives in its description)
        # must not show up, while two characters may use the description.
        self.assertNotIn("other", result["singleChar"])
        self.assertNotIn("unrelated", result["singleChar"])
        self.assertEqual(result["twoChars"], ["other"])
        self.assertEqual(
            result["empty"][:3], ["zz-review-tool", "xxreviewxx", "review"]
        )
        self.assertEqual(result["limited"], ["zz-review-tool", "xxreviewxx", "review"])
        self.assertEqual(result["whitespaceOnly"], 10)
        self.assertEqual(result["nullQuery"], 10)
        self.assertEqual(result["stableTies"], ["aa-x", "bb-x", "cc-x"])


# --------------------------------------------------------------------------
# Opening, filtering and accepting
# --------------------------------------------------------------------------


class TestOpenFilterAccept(unittest.TestCase):
    def test_slash_opens_popup_and_fetches_catalogue_once(self) -> None:
        result = _run_node(
            _case(
                """
                const env = createEnvironment();
                env.load();
                const ta = env.makeTextarea();
                await env.type(ta, '/');
                const afterOpen = {
                  open: env.isOpen(), rows: env.rows().length, active: env.activeIndex(),
                  listAttrs: [ta.getAttribute('aria-autocomplete'), ta.getAttribute('aria-controls'), ta.getAttribute('aria-activedescendant')],
                  popupRole: env.popup().getAttribute('role'), popupLabel: env.popup().getAttribute('aria-label'),
                  rowRoles: env.rows().map((r) => r.getAttribute('role')),
                  fetchCount: env.fetchCalls.length, fetchUrl: env.fetchCalls[0].url, fetchInit: {
                    cache: env.fetchCalls[0].init.cache, credentials: env.fetchCalls[0].init.credentials,
                    hasSignal: !!env.fetchCalls[0].init.signal,
                  },
                  timers: env.timers.map((t) => t.ms),
                };
                await env.type(ta, 're');
                const afterFilter = { tokens: env.tokens(), fetchCount: env.fetchCalls.length };
                return { afterOpen, afterFilter, console: env.consoleCalls };
                """
            )
        )
        assert isinstance(result, dict)
        opened = result["afterOpen"]
        self.assertTrue(opened["open"])
        self.assertEqual(opened["rows"], 5)
        self.assertEqual(opened["active"], 0)
        self.assertEqual(opened["listAttrs"][0], "list")
        self.assertEqual(opened["listAttrs"][1], "aiia-slash-listbox")
        self.assertEqual(opened["listAttrs"][2], "aiia-slash-option-0")
        self.assertEqual(opened["popupRole"], "listbox")
        self.assertEqual(opened["popupLabel"], "Skills and commands")
        self.assertEqual(opened["rowRoles"], ["option"] * 5)
        self.assertEqual(opened["fetchCount"], 1)
        self.assertEqual(opened["fetchUrl"], "/api/skills")
        self.assertEqual(
            opened["fetchInit"],
            {"cache": "no-store", "credentials": "same-origin", "hasSignal": True},
        )
        # the request timeout was armed and then cleared once the response landed
        self.assertEqual(opened["timers"], [])
        self.assertEqual(
            result["afterFilter"]["tokens"][:3],
            ["/review", "/release-notes", "/reverse-engineering"],
        )
        self.assertEqual(result["afterFilter"]["fetchCount"], 1)
        self.assertEqual(result["console"], [])

    def test_endpoint_follows_the_embedding_host_config(self) -> None:
        result = _run_node(
            _case(
                """
                const env = createEnvironment();
                env.addConfig('http://127.0.0.1:8081///');
                env.load();
                const ta = env.makeTextarea();
                await env.type(ta, '/');
                return env.fetchCalls.map((c) => c.url);
                """
            )
        )
        self.assertEqual(result, ["http://127.0.0.1:8081/api/skills"])

    def test_rows_show_label_kind_description_and_source(self) -> None:
        result = _run_node(
            _case(
                """
                const env = createEnvironment({ i18n: { t: (k) => k === 'aiia.slash.kindCommand' ? '命令' : k } });
                env.load();
                const ta = env.makeTextarea();
                await env.type(ta, '/');
                const describe = (row) => ({
                  classes: row.children.map((c) => c.className),
                  headClasses: row.children[0].children.map((c) => c.className),
                  texts: row.children[0].children.map((c) => c.textContent),
                  desc: row.children[1] ? row.children[1].textContent : null,
                  title: row.title,
                });
                return env.rows().map(describe);
                """
            )
        )
        assert isinstance(result, list)
        by_token = {row["texts"][0]: row for row in result}
        plain = by_token["/alpha-skill"]
        self.assertEqual(plain["headClasses"], ["aiia-slash-token"])
        self.assertEqual(plain["desc"], "First skill about reviewing code")
        self.assertEqual(plain["title"], "~/.cursor/skills")
        labelled = by_token["/ctf-web"]
        self.assertEqual(
            labelled["headClasses"], ["aiia-slash-token", "aiia-slash-label"]
        )
        self.assertEqual(labelled["texts"], ["/ctf-web", "CTF·Web 漏洞"])
        command = by_token["/review"]
        self.assertEqual(
            command["headClasses"], ["aiia-slash-token", "aiia-slash-kind"]
        )
        self.assertEqual(command["texts"], ["/review", "命令"])

    def test_keyboard_navigation_wraps_and_enter_accepts(self) -> None:
        result = _run_node(
            _case(
                """
                const env = createEnvironment();
                env.load();
                const ta = env.makeTextarea();
                await env.type(ta, 'see /rev');
                const trace = [env.activeIndex()];
                env.key(ta, 'ArrowDown'); trace.push(env.activeIndex());
                env.key(ta, 'ArrowDown'); trace.push(env.activeIndex());
                env.key(ta, 'ArrowDown'); trace.push(env.activeIndex());
                env.key(ta, 'ArrowUp'); trace.push(env.activeIndex());
                env.key(ta, 'ArrowUp'); trace.push(env.activeIndex());
                env.key(ta, 'ArrowUp'); trace.push(env.activeIndex());
                const rowCount = env.rows().length;
                env.key(ta, 'ArrowDown');
                const enter = env.key(ta, 'Enter');
                return {
                  trace, rowCount, value: ta.value, caret: [ta.selectionStart, ta.selectionEnd],
                  open: env.isOpen(), enterPrevented: enter.defaultPrevented, inputEvents: env.inputEvents,
                  attrs: [ta.getAttribute('aria-controls'), ta.getAttribute('aria-activedescendant'), ta.getAttribute('aria-autocomplete')],
                  setRangeTextCalls: ta.setRangeTextCalls,
                };
                """
            )
        )
        assert isinstance(result, dict)
        # "rev" matches review, reverse-engineering and (through its description)
        # alpha-skill: three rows, so the cursor wraps in both directions.
        self.assertEqual(result["rowCount"], 3)
        self.assertEqual(result["trace"], [0, 1, 2, 0, 2, 1, 0])
        self.assertEqual(result["value"], "see /reverse-engineering ")
        self.assertEqual(result["caret"], [25, 25])
        self.assertFalse(result["open"])
        self.assertTrue(result["enterPrevented"])
        self.assertEqual(result["inputEvents"], 1)
        self.assertEqual(result["attrs"], [None, None, None])
        self.assertEqual(result["setRangeTextCalls"], 0)

    def test_tab_accepts_and_swallows_one_trailing_space(self) -> None:
        result = _run_node(
            _case(
                """
                const env = createEnvironment();
                env.load();
                const ta = env.makeTextarea();
                ta.focus();
                ta.value = 'x /rev tail';
                ta.setSelectionRange(6, 6);
                ta.dispatchEvent(new FakeEvent('input', { bubbles: true }));
                await env.flush();
                const opened = env.isOpen();
                const tab = env.key(ta, 'Tab');
                return { opened, value: ta.value, caret: ta.selectionStart, prevented: tab.defaultPrevented };
                """
            )
        )
        self.assertEqual(
            result,
            {"opened": True, "value": "x /review tail", "caret": 10, "prevented": True},
        )

    def test_accept_falls_back_when_exec_command_cannot_insert(self) -> None:
        for mode in ("noop", "throw", "lies"):
            with self.subTest(mode=mode):
                result = _run_node(
                    _case(
                        """
                        const env = createEnvironment({ execMode: __EXEC_MODE__ });
                        env.load();
                        const ta = env.makeTextarea();
                        await env.type(ta, '/rel');
                        let inputs = 0;
                        ta.addEventListener('input', () => { inputs += 1; });
                        const enter = env.key(ta, 'Enter');
                        return {
                          value: ta.value, caret: ta.selectionStart, open: env.isOpen(),
                          setRangeTextCalls: ta.setRangeTextCalls, inputs, prevented: enter.defaultPrevented,
                        };
                        """.replace("__EXEC_MODE__", json.dumps(mode))
                    )
                )
                self.assertEqual(
                    result,
                    {
                        "value": "/release-notes ",
                        "caret": 15,
                        "open": False,
                        "setRangeTextCalls": 1,
                        "inputs": 1,
                        "prevented": True,
                    },
                )

    def test_trigger_must_stay_a_single_token(self) -> None:
        result = _run_node(
            _case(
                """
                const env = createEnvironment();
                env.load();
                const ta = env.makeTextarea();
                const seen = [];
                for (const text of ['see http://x/re', 'a/re', 'one two']) {
                  ta.value = ''; ta.selectionStart = ta.selectionEnd = 0;
                  await env.type(ta, text);
                  seen.push(env.isOpen());
                }
                ta.value = ''; ta.selectionStart = ta.selectionEnd = 0;
                await env.type(ta, '/re');
                const open = env.isOpen();
                await env.type(ta, ' ');
                return { seen, open, closedAfterSpace: !env.isOpen() };
                """
            )
        )
        self.assertEqual(
            result,
            {"seen": [False, False, False], "open": True, "closedAfterSpace": True},
        )

    def test_no_match_closes_popup(self) -> None:
        result = _run_node(
            _case(
                """
                const env = createEnvironment();
                env.load();
                const ta = env.makeTextarea();
                await env.type(ta, '/rev');
                const open = env.isOpen();
                await env.type(ta, 'zzzzq');
                const closed = !env.isOpen();
                ta.value = '/rev'; ta.selectionStart = ta.selectionEnd = 4;
                ta.dispatchEvent(new FakeEvent('input', { bubbles: true }));
                await env.flush();
                return { open, closed, reopened: env.isOpen(), hiddenAttr: env.popup().hidden };
                """
            )
        )
        self.assertEqual(
            result,
            {"open": True, "closed": True, "reopened": True, "hiddenAttr": False},
        )

    def test_non_collapsed_selection_does_not_open_and_closes_an_open_popup(
        self,
    ) -> None:
        result = _run_node(
            _case(
                """
                const env = createEnvironment();
                env.load();
                const ta = env.makeTextarea();
                ta.focus();
                ta.value = '/review';
                // the selection starts *inside* the token, so only the explicit guard keeps it closed
                ta.setSelectionRange(3, 5);
                ta.dispatchEvent(new FakeEvent('input', { bubbles: true }));
                await env.flush();
                const notOpened = env.popup() ? !env.isOpen() : true;
                ta.setSelectionRange(3, 3);
                ta.dispatchEvent(new FakeEvent('input', { bubbles: true }));
                await env.flush();
                const opened = env.isOpen();
                ta.setSelectionRange(3, 5);
                env.keyup(ta, 'ArrowRight');
                return { notOpened, opened, closedBySelection: !env.isOpen() };
                """
            )
        )
        self.assertEqual(
            result, {"notOpened": True, "opened": True, "closedBySelection": True}
        )

    def test_textareas_without_marker_or_disabled_are_ignored(self) -> None:
        result = _run_node(
            _case(
                """
                const env = createEnvironment();
                env.load();
                const plain = env.makeTextarea();
                delete plain.attrs['data-aiia-slash-commands'];
                await env.type(plain, '/rev');
                const disabled = env.makeTextarea();
                disabled.disabled = true;
                await env.type(disabled, '/rev');
                const readonly = env.makeTextarea();
                readonly.readOnly = true;
                await env.type(readonly, '/rev');
                return { fetches: env.fetchCalls.length, popup: env.popup() ? env.isOpen() : false };
                """
            )
        )
        self.assertEqual(result, {"fetches": 0, "popup": False})


# --------------------------------------------------------------------------
# Keyboard ownership (who sees Enter first)
# --------------------------------------------------------------------------


class TestKeyboardOwnership(unittest.TestCase):
    def test_open_picker_consumes_enter_before_submit_handlers(self) -> None:
        result = _run_node(
            _case(
                """
                const env = createEnvironment();
                env.load();
                const ta = env.makeTextarea();
                const seen = [];
                // registered after the picker, so only stopImmediatePropagation can hide the key from it
                env.document.addEventListener('keydown', (e) => seen.push('doc-capture:' + e.key), true);
                ta.addEventListener('keydown', (e) => seen.push('capture:' + e.key), true);
                ta.addEventListener('keydown', (e) => seen.push('bubble:' + e.key), false);
                env.document.addEventListener('keydown', (e) => seen.push('doc-bubble:' + e.key), false);
                await env.type(ta, '/rev');
                const consumed = env.key(ta, 'Enter');
                const afterPick = seen.slice();
                seen.length = 0;
                const later = env.key(ta, 'Enter');
                return { afterPick, later: seen.slice(), consumed: consumed.defaultPrevented, laterPrevented: later.defaultPrevented };
                """
            )
        )
        self.assertEqual(
            result,
            {
                "afterPick": [],
                "later": [
                    "doc-capture:Enter",
                    "capture:Enter",
                    "bubble:Enter",
                    "doc-bubble:Enter",
                ],
                "consumed": True,
                "laterPrevented": False,
            },
        )

    def test_modified_enter_is_never_consumed(self) -> None:
        result = _run_node(
            _case(
                """
                const env = createEnvironment();
                env.load();
                const ta = env.makeTextarea();
                await env.type(ta, '/rev');
                const out = {};
                const shift = env.key(ta, 'Enter', { shiftKey: true });
                out.shift = { prevented: shift.defaultPrevented, open: env.isOpen() };
                const alt = env.key(ta, 'Enter', { altKey: true });
                out.alt = { prevented: alt.defaultPrevented, open: env.isOpen() };
                const ctrl = env.key(ta, 'Enter', { ctrlKey: true });
                out.ctrl = { prevented: ctrl.defaultPrevented, open: env.isOpen() };
                await env.type(ta, '');
                ta.value = '/rev'; ta.selectionStart = ta.selectionEnd = 4;
                ta.dispatchEvent(new FakeEvent('input', { bubbles: true }));
                await env.flush();
                const meta = env.key(ta, 'Enter', { metaKey: true });
                out.meta = { prevented: meta.defaultPrevented, open: env.isOpen() };
                out.value = ta.value;
                return out;
                """
            )
        )
        self.assertEqual(
            result,
            {
                "shift": {"prevented": False, "open": True},
                "alt": {"prevented": False, "open": True},
                "ctrl": {"prevented": False, "open": False},
                "meta": {"prevented": False, "open": False},
                "value": "/rev",
            },
        )

    def test_composition_keystrokes_are_ignored(self) -> None:
        result = _run_node(
            _case(
                """
                const env = createEnvironment();
                env.load();
                const ta = env.makeTextarea();
                await env.type(ta, '/rev');
                const composing = env.key(ta, 'Enter', { isComposing: true });
                const legacy = env.key(ta, 'Enter', { keyCode: 229 });
                const arrow = env.key(ta, 'ArrowDown', { isComposing: true });
                return {
                  prevented: [composing.defaultPrevented, legacy.defaultPrevented, arrow.defaultPrevented],
                  open: env.isOpen(), active: env.activeIndex(), value: ta.value,
                };
                """
            )
        )
        self.assertEqual(
            result,
            {
                "prevented": [False, False, False],
                "open": True,
                "active": 0,
                "value": "/rev",
            },
        )

    def test_events_from_other_elements_are_ignored(self) -> None:
        result = _run_node(
            _case(
                """
                const env = createEnvironment();
                env.load();
                const ta = env.makeTextarea();
                const other = env.makeTextarea();
                await env.type(ta, '/rev');
                const event = env.key(other, 'Enter');
                return { prevented: event.defaultPrevented, open: env.isOpen(), value: ta.value, otherValue: other.value };
                """
            )
        )
        self.assertEqual(
            result,
            {"prevented": False, "open": True, "value": "/rev", "otherValue": ""},
        )

    def test_escape_dismisses_until_the_trigger_changes(self) -> None:
        result = _run_node(
            _case(
                """
                const env = createEnvironment();
                env.load();
                const ta = env.makeTextarea();
                await env.type(ta, '/rev');
                const esc = env.key(ta, 'Escape');
                const out = { prevented: esc.defaultPrevented, closed: !env.isOpen() };
                env.keyup(ta, 'Escape');
                env.keyup(ta, 'Shift');
                env.keyup(ta, 'Control');
                ta.dispatchEvent(new FakeEvent('click', { bubbles: true }));
                await env.flush();
                out.stillClosedAfterKeyupsAndClick = !env.isOpen();
                await env.type(ta, 'i');
                out.reopenedWhenTokenChanges = env.isOpen();
                env.key(ta, 'Escape');
                out.closedAgain = !env.isOpen();
                ta.value = 'plain'; ta.selectionStart = ta.selectionEnd = 5;
                ta.dispatchEvent(new FakeEvent('input', { bubbles: true }));
                await env.flush();
                await env.type(ta, ' /rev');
                out.reopenedAfterTriggerDisappeared = env.isOpen();
                return out;
                """
            )
        )
        self.assertEqual(
            result,
            {
                "prevented": True,
                "closed": True,
                "stillClosedAfterKeyupsAndClick": True,
                "reopenedWhenTokenChanges": True,
                "closedAgain": True,
                "reopenedAfterTriggerDisappeared": True,
            },
        )

    def test_escape_without_open_popup_is_not_consumed(self) -> None:
        result = _run_node(
            _case(
                """
                const env = createEnvironment();
                env.load();
                const ta = env.makeTextarea();
                await env.type(ta, 'plain text');
                const esc = env.key(ta, 'Escape');
                const enter = env.key(ta, 'Enter');
                const arrow = env.key(ta, 'ArrowDown');
                return [esc.defaultPrevented, enter.defaultPrevented, arrow.defaultPrevented];
                """
            )
        )
        self.assertEqual(result, [False, False, False])

    def test_refreshing_an_open_popup_keeps_the_highlighted_row(self) -> None:
        result = _run_node(
            _case(
                """
                const env = createEnvironment();
                env.load();
                const ta = env.makeTextarea();
                await env.type(ta, '/');
                env.key(ta, 'ArrowDown');
                env.key(ta, 'ArrowDown');
                const before = env.activeIndex();
                const rowsBefore = env.rows();
                env.keyup(ta, 'Shift');
                env.keyup(ta, 'ArrowDown');
                ta.dispatchEvent(new FakeEvent('click', { bubbles: true }));
                await env.flush();
                return {
                  before,
                  after: env.activeIndex(),
                  sameRows: env.rows().every((row, i) => row === rowsBefore[i]),
                };
                """
            )
        )
        self.assertEqual(result, {"before": 2, "after": 2, "sameRows": True})

    def test_keyup_and_click_never_open_but_keep_an_open_popup_in_sync(self) -> None:
        result = _run_node(
            _case(
                """
                const env = createEnvironment();
                env.load();
                const ta = env.makeTextarea();
                ta.focus();
                ta.value = 'hello /rev';
                ta.setSelectionRange(10, 10);
                env.keyup(ta, 'ArrowRight');
                ta.dispatchEvent(new FakeEvent('click', { bubbles: true }));
                await env.flush();
                const out = { neverOpened: [env.popup() ? env.isOpen() : false, env.fetchCalls.length] };

                ta.dispatchEvent(new FakeEvent('input', { bubbles: true }));
                await env.flush();
                out.opened = env.isOpen();

                // caret moves inside the token: the query follows it (keyup)
                ta.setSelectionRange(8, 8);
                env.keyup(ta, 'ArrowLeft');
                out.queryAfterArrow = env.tokens().length > 0 && env.isOpen();
                out.rowsAfterArrow = env.rows().length;

                // caret leaves the token (keyup)
                ta.setSelectionRange(2, 2);
                env.keyup(ta, 'ArrowLeft');
                out.closedByKeyup = !env.isOpen();

                // reopen, then leave with a click instead
                ta.setSelectionRange(10, 10);
                ta.dispatchEvent(new FakeEvent('input', { bubbles: true }));
                await env.flush();
                out.reopened = env.isOpen();
                ta.setSelectionRange(0, 0);
                ta.dispatchEvent(new FakeEvent('click', { bubbles: true }));
                out.closedByClick = !env.isOpen();

                // caret directly in front of the slash does not count as typing a command
                ta.setSelectionRange(10, 10);
                ta.dispatchEvent(new FakeEvent('input', { bubbles: true }));
                await env.flush();
                ta.setSelectionRange(6, 6);
                env.keyup(ta, 'ArrowLeft');
                out.closedInFrontOfSlash = !env.isOpen();
                return out;
                """
            )
        )
        assert isinstance(result, dict)
        self.assertEqual(result["neverOpened"], [False, 0])
        self.assertTrue(result["opened"])
        self.assertTrue(result["queryAfterArrow"])
        self.assertGreaterEqual(result["rowsAfterArrow"], 3)
        self.assertTrue(result["closedByKeyup"])
        self.assertTrue(result["reopened"])
        self.assertTrue(result["closedByClick"])
        self.assertTrue(result["closedInFrontOfSlash"])

    def test_dismissal_survives_edits_that_keep_the_same_query(self) -> None:
        result = _run_node(
            _case(
                """
                const env = createEnvironment();
                env.load();
                const ta = env.makeTextarea();
                ta.focus();
                ta.value = '/review';
                ta.setSelectionRange(3, 3);
                ta.dispatchEvent(new FakeEvent('input', { bubbles: true }));
                await env.flush();
                const opened = env.isOpen();
                env.key(ta, 'Escape');
                // "Delete" removes the character *after* the caret: same start, same query
                ta.value = '/reiew';
                ta.setSelectionRange(3, 3);
                ta.dispatchEvent(new FakeEvent('input', { bubbles: true }));
                await env.flush();
                const stillClosed = !env.isOpen();
                // typing changes the query again, which lifts the dismissal
                ta.value = '/reviiew';
                ta.setSelectionRange(5, 5);
                ta.dispatchEvent(new FakeEvent('input', { bubbles: true }));
                await env.flush();
                return { opened, stillClosed, reopened: env.isOpen() };
                """
            )
        )
        self.assertEqual(
            result, {"opened": True, "stillClosed": True, "reopened": True}
        )

    def test_composition_end_refreshes_the_popup(self) -> None:
        result = _run_node(
            _case(
                """
                const env = createEnvironment();
                env.load();
                const ta = env.makeTextarea();
                ta.focus();
                // some engines commit the text without a trailing input event
                ta.value = '/rev';
                ta.setSelectionRange(4, 4);
                ta.dispatchEvent(new FakeEvent('compositionend', { bubbles: true }));
                await env.flush();
                const opened = env.isOpen();
                const other = env.makeTextarea();
                delete other.attrs['data-aiia-slash-commands'];
                other.focus();
                other.value = '/rev';
                other.setSelectionRange(4, 4);
                ta.blur();
                const fetchesBefore = env.fetchCalls.length;
                other.dispatchEvent(new FakeEvent('compositionend', { bubbles: true }));
                await env.flush();
                return { opened, unmarkedIgnored: env.fetchCalls.length === fetchesBefore };
                """
            )
        )
        self.assertEqual(result, {"opened": True, "unmarkedIgnored": True})


# --------------------------------------------------------------------------
# Catalogue loading and failure injection
# --------------------------------------------------------------------------


class TestCatalogueLoading(unittest.TestCase):
    def test_failures_back_off_instead_of_hammering_the_server(self) -> None:
        result = _run_node(
            _case(
                """
                const env = createEnvironment();
                env.load();
                const ta = env.makeTextarea();
                env.fetchImpl = () => Promise.reject(new Error('offline'));
                await env.type(ta, '/');
                const out = { first: [env.fetchCalls.length, env.popup() ? env.isOpen() : false] };
                await env.type(ta, 'r');
                await env.type(ta, 'e');
                out.withinBackoff = env.fetchCalls.length;
                env.now += 14000;
                await env.type(ta, 'v');
                out.stillBackedOff = env.fetchCalls.length;
                env.now += 2000;
                await env.type(ta, 'i');
                out.afterBackoff = env.fetchCalls.length;
                env.fetchImpl = () => Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(env.payload) });
                env.now += 16000;
                await env.type(ta, 'e');
                out.recovered = [env.fetchCalls.length, env.isOpen(), env.tokens()];
                out.console = env.consoleCalls;
                return out;
                """
            )
        )
        assert isinstance(result, dict)
        self.assertEqual(result["first"], [1, False])
        self.assertEqual(result["withinBackoff"], 1)
        self.assertEqual(result["stillBackedOff"], 1)
        self.assertEqual(result["afterBackoff"], 2)
        self.assertEqual(
            result["recovered"],
            [3, True, ["/review", "/reverse-engineering", "/alpha-skill"]],
        )
        self.assertEqual(result["console"], [])

    def test_http_errors_and_malformed_payloads_do_not_open_or_throw(self) -> None:
        result = _run_node(
            _case(
                """
                const out = [];
                const variants = {
                  http500: () => Promise.resolve({ ok: false, status: 500, json: () => Promise.resolve({}) }),
                  badJson: () => Promise.resolve({ ok: true, status: 200, json: () => Promise.reject(new SyntaxError('bad')) }),
                  notArray: () => Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({ status: 'success', skills: 'nope' }) }),
                  nullPayload: () => Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(null) }),
                  empty: () => Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({ status: 'success', skills: [] }) }),
                  throwsSync: () => { throw new Error('boom'); },
                };
                for (const [name, impl] of Object.entries(variants)) {
                  const env = createEnvironment();
                  env.load();
                  env.fetchImpl = impl;
                  const ta = env.makeTextarea();
                  await env.type(ta, '/re');
                  out.push([name, env.popup() ? env.isOpen() : false, env.consoleCalls.length]);
                }
                return out;
                """
            )
        )
        # ``throwsSync`` escapes ``fetch`` synchronously; the module must still not crash the host page.
        assert isinstance(result, list)
        for name, opened, console_calls in result:
            with self.subTest(variant=name):
                self.assertFalse(opened)
                self.assertEqual(console_calls, 0)

    def test_hanging_request_is_aborted_by_the_timeout(self) -> None:
        result = _run_node(
            _case(
                """
                const env = createEnvironment();
                env.load();
                const ta = env.makeTextarea();
                env.fetchImpl = (_url, init) => new Promise((_resolve, reject) => {
                  init.signal.addEventListener('abort', () => reject(new Error('aborted')));
                });
                ta.focus();
                ta.value = '/re';
                ta.setSelectionRange(3, 3);
                ta.dispatchEvent(new FakeEvent('input', { bubbles: true }));
                await env.flush();
                const armed = env.timers.map((t) => t.ms);
                env.timers[0].fn();
                await env.flush();
                const out = { armed, aborted: env.fetchCalls[0].init.signal.aborted, timersLeft: env.timers.length, popup: env.popup() ? env.isOpen() : false };
                env.fetchImpl = () => Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(env.payload) });
                env.now += 16000;
                ta.dispatchEvent(new FakeEvent('input', { bubbles: true }));
                await env.flush();
                out.recovered = env.isOpen();
                return out;
                """
            )
        )
        self.assertEqual(
            result,
            {
                "armed": [5000],
                "aborted": True,
                "timersLeft": 0,
                "popup": False,
                "recovered": True,
            },
        )

    def test_concurrent_inputs_share_one_request(self) -> None:
        result = _run_node(
            _case(
                """
                const env = createEnvironment();
                env.load();
                const ta = env.makeTextarea();
                let release;
                env.fetchImpl = () => new Promise((resolve) => {
                  release = () => resolve({ ok: true, status: 200, json: () => Promise.resolve(env.payload) });
                });
                ta.focus();
                ta.value = '/r';
                ta.setSelectionRange(2, 2);
                ta.dispatchEvent(new FakeEvent('input', { bubbles: true }));
                ta.value = '/re';
                ta.setSelectionRange(3, 3);
                ta.dispatchEvent(new FakeEvent('input', { bubbles: true }));
                ta.value = '/rev';
                ta.setSelectionRange(4, 4);
                ta.dispatchEvent(new FakeEvent('input', { bubbles: true }));
                await env.flush();
                const whilePending = [env.fetchCalls.length, env.popup() ? env.isOpen() : false];
                release();
                await env.flush();
                return { whilePending, fetches: env.fetchCalls.length, open: env.isOpen(), tokens: env.tokens() };
                """
            )
        )
        assert isinstance(result, dict)
        self.assertEqual(result["whilePending"], [1, False])
        self.assertEqual(result["fetches"], 1)
        self.assertTrue(result["open"])
        self.assertEqual(result["tokens"][0], "/review")

    def test_late_response_does_not_pop_up_after_focus_left(self) -> None:
        result = _run_node(
            _case(
                """
                const env = createEnvironment();
                env.load();
                const ta = env.makeTextarea();
                let release;
                env.fetchImpl = () => new Promise((resolve) => {
                  release = () => resolve({ ok: true, status: 200, json: () => Promise.resolve(env.payload) });
                });
                ta.focus();
                ta.value = '/rev';
                ta.setSelectionRange(4, 4);
                ta.dispatchEvent(new FakeEvent('input', { bubbles: true }));
                await env.flush();
                ta.blur();
                release();
                await env.flush();
                return { open: env.popup() ? env.isOpen() : false, fetches: env.fetchCalls.length };
                """
            )
        )
        self.assertEqual(result, {"open": False, "fetches": 1})

    def test_stale_catalogue_refreshes_in_background_and_keeps_rows_on_failure(
        self,
    ) -> None:
        result = _run_node(
            _case(
                """
                const env = createEnvironment();
                env.load();
                const ta = env.makeTextarea();
                await env.type(ta, '/rev');
                const out = { first: [env.fetchCalls.length, env.tokens()] };
                env.now += 61000;
                env.payload = { status: 'success', skills: [
                  { name: 'fresh-review', insert: 'fresh-review', description: '', kind: 'skill', source: '' },
                ] };
                await env.type(ta, 'i');
                out.refreshed = [env.fetchCalls.length, env.tokens()];
                env.now += 61000;
                env.fetchImpl = () => Promise.reject(new Error('offline'));
                await env.type(ta, 'e');
                out.afterFailedRefresh = [env.fetchCalls.length, env.tokens()];
                out.console = env.consoleCalls;
                return out;
                """
            )
        )
        assert isinstance(result, dict)
        self.assertEqual(result["first"][0], 1)
        self.assertEqual(result["first"][1][0], "/review")
        self.assertEqual(result["refreshed"], [2, ["/fresh-review"]])
        self.assertEqual(result["afterFailedRefresh"], [3, ["/fresh-review"]])
        self.assertEqual(result["console"], [])


# --------------------------------------------------------------------------
# Positioning
# --------------------------------------------------------------------------


class TestPositioning(unittest.TestCase):
    def test_places_above_when_there_is_room_below_otherwise(self) -> None:
        result = _run_node(
            _case(
                """
                const env = createEnvironment({ width: 1000, height: 800, clientHeight: 800 });
                env.load();
                const ta = env.makeTextarea();
                ta.rect = { left: 100, top: 600, right: 700, bottom: 700, width: 600, height: 100 };
                await env.type(ta, '/');
                const popup = env.popup();
                const above = { top: popup.style.top, bottom: popup.style.bottom, left: popup.style.left, width: popup.style.width, maxHeight: popup.style.maxHeight };
                ta.rect = { left: 100, top: 40, right: 700, bottom: 140, width: 600, height: 100 };
                env.dispatchWindow('resize');
                const below = { top: popup.style.top, bottom: popup.style.bottom, maxHeight: popup.style.maxHeight };
                return { above, below };
                """
            )
        )
        self.assertEqual(
            result,
            {
                "above": {
                    "top": "auto",
                    "bottom": "206px",
                    "left": "100px",
                    "width": "560px",
                    "maxHeight": "320px",
                },
                "below": {"top": "146px", "bottom": "auto", "maxHeight": "320px"},
            },
        )

    def test_clamps_to_narrow_viewports_and_honours_visual_viewport(self) -> None:
        result = _run_node(
            _case(
                """
                const viewportListeners = [];
                const visualViewport = {
                  offsetLeft: 0, offsetTop: 0, width: 320, height: 300,
                  addEventListener(type, fn) { viewportListeners.push(type); },
                  removeEventListener(type) { const i = viewportListeners.indexOf(type); if (i >= 0) viewportListeners.splice(i, 1); },
                };
                const env = createEnvironment({ width: 320, height: 640, clientHeight: 640, visualViewport });
                env.load();
                const ta = env.makeTextarea();
                ta.rect = { left: 16, top: 180, right: 304, bottom: 260, width: 288, height: 80 };
                await env.type(ta, '/');
                const popup = env.popup();
                const out = {
                  left: popup.style.left, width: popup.style.width, maxHeight: popup.style.maxHeight,
                  top: popup.style.top, bottom: popup.style.bottom, tracking: viewportListeners.slice().sort(),
                };
                ta.blur();
                out.trackingAfterClose = viewportListeners.length;
                return out;
                """
            )
        )
        assert isinstance(result, dict)
        self.assertEqual(result["left"], "16px")
        self.assertEqual(result["width"], "288px")
        self.assertEqual(result["tracking"], ["resize", "scroll"])
        self.assertEqual(result["trackingAfterClose"], 0)
        # 300px visual viewport: 180 above leaves 166px, 40 below leaves less -> above
        self.assertEqual(result["top"], "auto")
        self.assertEqual(result["maxHeight"], "166px")

    def test_closes_when_the_textarea_scrolls_out_of_view(self) -> None:
        result = _run_node(
            _case(
                """
                const env = createEnvironment({ width: 1000, height: 800, clientHeight: 800 });
                env.load();
                const ta = env.makeTextarea();
                ta.rect = { left: 100, top: 600, right: 700, bottom: 700, width: 600, height: 100 };
                await env.type(ta, '/');
                const open = env.isOpen();
                ta.rect = { left: 100, top: 900, right: 700, bottom: 1000, width: 600, height: 100 };
                env.dispatchWindow('scroll');
                const closedBelow = !env.isOpen();
                ta.rect = { left: 100, top: 600, right: 700, bottom: 700, width: 600, height: 100 };
                await env.type(ta, 'r');
                const reopened = env.isOpen();
                ta.rect = { left: 100, top: -200, right: 700, bottom: -100, width: 600, height: 100 };
                env.dispatchWindow('scroll');
                const closedAbove = !env.isOpen();
                ta.rect = { left: 100, top: 0, right: 100, bottom: 0, width: 0, height: 0 };
                await env.type(ta, 'e');
                return { open, closedBelow, reopened, closedAbove, hiddenTextarea: !env.isOpen() };
                """
            )
        )
        self.assertEqual(
            result,
            {
                "open": True,
                "closedBelow": True,
                "reopened": True,
                "closedAbove": True,
                "hiddenTextarea": True,
            },
        )

    def test_scrolling_the_list_itself_does_not_reposition(self) -> None:
        result = _run_node(
            _case(
                """
                const env = createEnvironment();
                env.load();
                const ta = env.makeTextarea();
                await env.type(ta, '/');
                const popup = env.popup();
                let reads = 0;
                const original = ta.getBoundingClientRect.bind(ta);
                ta.getBoundingClientRect = () => { reads += 1; return original(); };
                env.dispatchWindow('scroll', Object.assign(new FakeEvent('scroll'), { target: popup }));
                const fromPopup = reads;
                env.dispatchWindow('scroll', Object.assign(new FakeEvent('scroll'), { target: env.document.body }));
                return { fromPopup, fromPage: reads };
                """
            )
        )
        self.assertEqual(result, {"fromPopup": 0, "fromPage": 1})


# --------------------------------------------------------------------------
# Pointer, focus and lifecycle
# --------------------------------------------------------------------------


class TestPointerFocusLifecycle(unittest.TestCase):
    def test_pointer_interaction(self) -> None:
        result = _run_node(
            _case(
                """
                const env = createEnvironment();
                env.load();
                const ta = env.makeTextarea();
                await env.type(ta, '/');
                const popup = env.popup();
                const rows = env.rows();
                const out = {};
                const mousedown = new FakeEvent('mousedown', { bubbles: true });
                popup.dispatchEvent(mousedown);
                const pointerdown = new FakeEvent('pointerdown', { bubbles: true });
                rows[2].dispatchEvent(pointerdown);
                out.defaultsPrevented = [mousedown.defaultPrevented, pointerdown.defaultPrevented];
                // focus loss caused by the press itself must not close the popup
                ta.dispatchEvent(new FakeEvent('focusout', { bubbles: true }));
                out.survivesFocusoutDuringPress = env.isOpen();
                rows[2].dispatchEvent(new FakeEvent('pointerup', { bubbles: true }));
                // hover moves the active row, a repeated event at the same spot does not
                rows[3].dispatchEvent(new FakeEvent('mousemove', { bubbles: true, clientX: 10, clientY: 20 }));
                out.hover = env.activeIndex();
                env.key(ta, 'ArrowUp');
                rows[3].dispatchEvent(new FakeEvent('mousemove', { bubbles: true, clientX: 10, clientY: 20 }));
                out.sameSpotIgnored = env.activeIndex();
                rows[4].dispatchEvent(new FakeEvent('mousemove', { bubbles: true, clientX: 11, clientY: 20 }));
                out.moved = env.activeIndex();
                rows[1].dispatchEvent(new FakeEvent('click', { bubbles: true }));
                out.afterClick = { value: ta.value, open: env.isOpen() };
                return out;
                """
            )
        )
        self.assertEqual(
            result,
            {
                "defaultsPrevented": [True, True],
                "survivesFocusoutDuringPress": True,
                "hover": 3,
                "sameSpotIgnored": 2,
                "moved": 4,
                "afterClick": {"value": "/ctf-web ", "open": False},
            },
        )

    def test_focus_loss_outside_click_and_hidden_page_close_the_popup(self) -> None:
        result = _run_node(
            _case(
                """
                const env = createEnvironment();
                env.load();
                const ta = env.makeTextarea();
                const out = {};
                await env.type(ta, '/');
                ta.blur();
                out.blur = !env.isOpen();
                await env.type(ta, 'r');
                const outside = env.makeTextarea();
                outside.dispatchEvent(new FakeEvent('pointerdown', { bubbles: true }));
                out.outsidePointer = !env.isOpen();
                await env.type(ta, 'e');
                ta.dispatchEvent(new FakeEvent('pointerdown', { bubbles: true }));
                out.pointerOnTextareaKeepsIt = env.isOpen();
                env.popup().dispatchEvent(new FakeEvent('pointerdown', { bubbles: true }));
                out.pointerOnPopupKeepsIt = env.isOpen();
                env.popup().dispatchEvent(new FakeEvent('pointercancel', { bubbles: true }));
                env.document.visibilityState = 'hidden';
                env.document.dispatchEvent(new FakeEvent('visibilitychange'));
                out.hiddenPage = !env.isOpen();
                return out;
                """
            )
        )
        self.assertEqual(
            result,
            {
                "blur": True,
                "outsidePointer": True,
                "pointerOnTextareaKeepsIt": True,
                "pointerOnPopupKeepsIt": True,
                "hiddenPage": True,
            },
        )

    def test_popup_is_rebuilt_not_duplicated_and_old_rows_are_released(self) -> None:
        result = _run_node(
            _case(
                """
                const env = createEnvironment();
                env.load();
                const ta = env.makeTextarea();
                await env.type(ta, '/');
                const first = env.popup();
                const firstRows = env.rows();
                await env.type(ta, 're');
                ta.blur();
                ta.value = '';
                ta.selectionStart = ta.selectionEnd = 0;
                await env.type(ta, '/');
                return {
                  popups: env.document.body.children.filter((c) => String(c.className).includes('aiia-slash-popup')).length,
                  samePopup: env.popup() === first,
                  oldRowsDetached: firstRows.every((row) => row.parentNode === null),
                  childCount: env.rows().length,
                };
                """
            )
        )
        self.assertEqual(
            result,
            {"popups": 1, "samePopup": True, "oldRowsDetached": True, "childCount": 5},
        )

    def test_destroy_releases_every_listener_and_the_popup(self) -> None:
        result = _run_node(
            _case(
                """
                const env = createEnvironment({ visualViewport: {
                  offsetLeft: 0, offsetTop: 0, width: 1000, height: 800,
                  addEventListener() {}, removeEventListener() {},
                } });
                const api = env.load();
                const initial = env.docListenerCount();
                const ta = env.makeTextarea();
                await env.type(ta, '/');
                const windowWhileOpen = env.window.listeners.length;
                api.destroy();
                return {
                  hadListeners: initial > 0,
                  documentAfter: env.docListenerCount(),
                  windowWhileOpen,
                  windowAfter: env.window.listeners.length,
                  popupGone: env.popup() === null,
                  apiGone: env.window.AIIASlashCommands === undefined,
                  attrs: [ta.getAttribute('aria-controls'), ta.getAttribute('aria-activedescendant')],
                };
                """
            )
        )
        self.assertEqual(
            result,
            {
                "hadListeners": True,
                "documentAfter": 0,
                "windowWhileOpen": 2,
                "windowAfter": 0,
                "popupGone": True,
                "apiGone": True,
                "attrs": [None, None],
            },
        )

    def test_loading_twice_replaces_the_previous_instance(self) -> None:
        result = _run_node(
            _case(
                """
                const env = createEnvironment();
                const first = env.load();
                const ta = env.makeTextarea();
                await env.type(ta, '/rev');
                const before = env.docListenerCount();
                const secondApi = env.load();
                const out = {
                  replaced: first !== secondApi,
                  sameListenerCount: env.docListenerCount() === before,
                  hasListeners: before > 0,
                  oldPopupRemoved: env.popup() === null,
                  oldTextareaCleaned: ta.getAttribute('aria-controls'),
                };
                env.fetchCalls.length = 0;
                await env.type(ta, 'i');
                out.fetchesAfterReload = env.fetchCalls.length;
                out.open = env.isOpen();
                return out;
                """
            )
        )
        self.assertEqual(
            result,
            {
                "replaced": True,
                "sameListenerCount": True,
                "hasListeners": True,
                "oldPopupRemoved": True,
                "oldTextareaCleaned": None,
                "fetchesAfterReload": 1,
                "open": True,
            },
        )

    def test_reset_forgets_the_catalogue_and_closes(self) -> None:
        result = _run_node(
            _case(
                """
                const env = createEnvironment();
                const api = env.load();
                const ta = env.makeTextarea();
                await env.type(ta, '/rev');
                api.reset();
                const closed = !env.isOpen();
                await env.type(ta, 'i');
                return { closed, fetches: env.fetchCalls.length, open: env.isOpen() };
                """
            )
        )
        self.assertEqual(result, {"closed": True, "fetches": 2, "open": True})


# --------------------------------------------------------------------------
# i18n
# --------------------------------------------------------------------------


class TestI18n(unittest.TestCase):
    def test_translator_is_used_and_failures_fall_back_to_english(self) -> None:
        result = _run_node(
            _case(
                """
                const out = [];
                const variants = [
                  ['translated', { t: (k) => ({ 'aiia.slash.listLabel': '技能与命令', 'aiia.slash.kindCommand': '命令' }[k] || k) }],
                  ['echoes key', { t: (k) => k }],
                  ['throws', { t: () => { throw new Error('i18n broke'); } }],
                  ['empty string', { t: () => '' }],
                  ['not a function', { t: 'nope' }],
                  ['missing', undefined],
                ];
                for (const [name, i18n] of variants) {
                  const env = createEnvironment({ i18n });
                  env.load();
                  const ta = env.makeTextarea();
                  await env.type(ta, '/rev');
                  const commandRow = env.rows().find((row) => row.children[0].children[0].textContent === '/review');
                  out.push([name, env.popup().getAttribute('aria-label'), commandRow.children[0].children[1].textContent, env.consoleCalls.length]);
                }
                return out;
                """
            )
        )
        self.assertEqual(
            result,
            [
                ["translated", "技能与命令", "命令", 0],
                ["echoes key", "Skills and commands", "command", 0],
                ["throws", "Skills and commands", "command", 0],
                ["empty string", "Skills and commands", "command", 0],
                ["not a function", "Skills and commands", "command", 0],
                ["missing", "Skills and commands", "command", 0],
            ],
        )


# --------------------------------------------------------------------------
# Static wiring
# --------------------------------------------------------------------------


class TestSharedFileParity(unittest.TestCase):
    def test_web_and_plugin_copies_are_byte_identical(self) -> None:
        self.assertTrue(WEB_JS.is_file(), WEB_JS)
        self.assertTrue(PLUGIN_JS.is_file(), PLUGIN_JS)
        self.assertEqual(
            WEB_JS.read_bytes(),
            PLUGIN_JS.read_bytes(),
            "slash-commands.js drifted between the Web UI and the VS Code plugin; "
            "edit the Web UI copy and `cp` it to packages/vscode/",
        )

    def test_source_never_writes_inline_style_attributes(self) -> None:
        source = WEB_JS.read_text(encoding="utf-8")
        self.assertNotRegex(source, r"setAttribute\(\s*['\"]style['\"]")
        self.assertNotRegex(source, r"style\s*=\s*['\"]")
        self.assertNotIn("cssText", source)
        self.assertNotIn("innerHTML", source)
        self.assertNotIn("insertAdjacentHTML", source)

    def test_source_has_no_console_output(self) -> None:
        source = WEB_JS.read_text(encoding="utf-8")
        self.assertNotRegex(source, r"\bconsole\.")


class TestWebUiWiring(unittest.TestCase):
    def test_template_marks_the_textarea_and_loads_the_script_with_a_nonce(
        self,
    ) -> None:
        html = TEMPLATE.read_text(encoding="utf-8")
        textarea = re.search(r"<textarea[^>]*id=\"feedback-text\"[^>]*>", html, re.S)
        self.assertIsNotNone(textarea)
        assert textarea is not None
        self.assertIn("data-aiia-slash-commands", textarea.group(0))
        script = re.search(
            r"<script\s[^>]*src=\"/static/js/slash-commands\.js\?v=\{\{ slash_commands_version \}\}\"[^>]*>",
            html,
            re.S,
        )
        self.assertIsNotNone(script, "slash-commands.js script tag missing")
        assert script is not None
        self.assertIn("defer", script.group(0))
        self.assertIn('nonce="{{ csp_nonce }}"', script.group(0))

    def test_template_context_exposes_the_cache_busting_version(self) -> None:
        source = WEB_UI_PY.read_text(encoding="utf-8")
        self.assertRegex(
            source,
            r'"slash_commands_version":\s*_compute_file_version\(\s*str\(static_dir / "js" / "slash-commands\.js"\)\s*\)',
        )

    def test_stylesheet_defines_the_popup_and_wins_over_light_theme_span_rule(
        self,
    ) -> None:
        css = WEB_CSS.read_text(encoding="utf-8")
        for selector in (
            ".aiia-slash-popup {",
            ".aiia-slash-popup[hidden] {",
            '.aiia-slash-popup .aiia-slash-item[aria-selected="true"] {',
            ".aiia-slash-popup .aiia-slash-token {",
            ".aiia-slash-popup .aiia-slash-desc {",
            ".aiia-slash-popup .aiia-slash-kind {",
        ):
            self.assertIn(selector, css)
        # ``[data-theme="light"] span`` forces ``color: var(--text-primary)``; the
        # child rules need the extra class in front to out-rank it (0,2,0 > 0,1,1).
        self.assertNotRegex(css, r"(?m)^\.aiia-slash-(token|label|desc|kind)\b")


class TestPluginWiring(unittest.TestCase):
    def test_webview_loads_the_script_and_marks_the_textarea(self) -> None:
        ts = WEBVIEW_TS.read_text(encoding="utf-8")
        self.assertRegex(
            ts,
            r'const slashCommandsUri = webview\.asWebviewUri\(\s*vscode\.Uri\.joinPath\(this\._extensionUri, "slash-commands\.js"\),?\s*\);',
        )
        self.assertIn(
            '<script nonce="${nonce}" src="${slashCommandsUri}"></script>', ts
        )
        textarea = re.search(r"<textarea[^>]*id=\"feedbackText\"[^>]*>", ts, re.S)
        self.assertIsNotNone(textarea)
        assert textarea is not None
        self.assertIn("data-aiia-slash-commands", textarea.group(0))

    def test_script_is_loaded_before_the_first_user_interaction_can_happen(
        self,
    ) -> None:
        ts = WEBVIEW_TS.read_text(encoding="utf-8")
        ui = ts.index('src="${webviewUiUri}"')
        slash = ts.index('src="${slashCommandsUri}"')
        self.assertLess(ui, slash, "slash-commands.js must come after webview-ui.js")

    def test_packaging_lists_ship_the_script(self) -> None:
        package = json.loads((PLUGIN_DIR / "package.json").read_text(encoding="utf-8"))
        self.assertIn("slash-commands.js", package["files"])
        packaging = (REPO_ROOT / "scripts" / "package_vscode_vsix.mjs").read_text(
            encoding="utf-8"
        )
        self.assertIn('"slash-commands.js"', packaging)
        eslint = (PLUGIN_DIR / "eslint.config.mjs").read_text(encoding="utf-8")
        self.assertIn("'slash-commands.js'", eslint)

    def test_stylesheet_uses_theme_tokens_only(self) -> None:
        css = PLUGIN_CSS.read_text(encoding="utf-8")
        start = css.index(".aiia-slash-popup {")
        end = css.index(".input-buttons {", start)
        block = css[start:end]
        self.assertIn(".aiia-slash-popup[hidden] {", block)
        self.assertIn('.aiia-slash-item[aria-selected="true"] {', block)
        self.assertIn("--vscode-list-activeSelectionBackground", block)
        self.assertNotRegex(block, r"#[0-9a-fA-F]{3,8}\b")
        self.assertNotIn("!important", block)

    def test_stylesheet_gives_the_selected_row_a_forced_colours_proof_indicator(
        self,
    ) -> None:
        css = PLUGIN_CSS.read_text(encoding="utf-8")
        block = css[css.index(".aiia-slash-popup {") : css.index(".input-buttons {")]
        selected = _rule_declarations(block, ['.aiia-slash-item[aria-selected="true"]'])
        # A background alone disappears in high-contrast themes; VS Code lists
        # draw ``contrastActiveBorder`` there, so the picker has to do the same.
        self.assertIn("--vscode-contrastActiveBorder", selected["outline"])
        self.assertEqual(
            selected["color"], "var(--vscode-list-activeSelectionForeground)"
        )
        # Description / kind text follows the selection foreground instead of
        # keeping a colour that was only checked against the plain background.
        secondary = _rule_declarations(
            block,
            [
                '.aiia-slash-item[aria-selected="true"] .aiia-slash-label',
                '.aiia-slash-item[aria-selected="true"] .aiia-slash-desc',
                '.aiia-slash-item[aria-selected="true"] .aiia-slash-kind',
            ],
        )
        self.assertEqual(secondary["color"], "inherit")


_AA_NORMAL = 4.5
_NON_TEXT_MIN = 3.0
_COLOR_RE = re.compile(
    r"^(?:#(?P<hex>[0-9a-fA-F]{6}|[0-9a-fA-F]{3})"
    r"|rgba?\(\s*(?P<r>\d+)\s*,\s*(?P<g>\d+)\s*,\s*(?P<b>\d+)\s*(?:,\s*(?P<a>[\d.]+)\s*)?\))$"
)


def _parse_color(value: str) -> tuple[float, float, float, float]:
    match = _COLOR_RE.match(value.strip())
    if match is None:
        raise AssertionError(f"unsupported colour in a token: {value!r}")
    if match.group("hex"):
        digits = match.group("hex")
        if len(digits) == 3:
            digits = "".join(ch * 2 for ch in digits)
        return (
            float(int(digits[0:2], 16)),
            float(int(digits[2:4], 16)),
            float(int(digits[4:6], 16)),
            1.0,
        )
    alpha = match.group("a")
    return (
        float(match.group("r")),
        float(match.group("g")),
        float(match.group("b")),
        float(alpha) if alpha is not None else 1.0,
    )


def _composite(
    top: tuple[float, float, float, float], below: tuple[float, float, float, float]
) -> tuple[float, float, float, float]:
    alpha = top[3]
    return (
        top[0] * alpha + below[0] * (1 - alpha),
        top[1] * alpha + below[1] * (1 - alpha),
        top[2] * alpha + below[2] * (1 - alpha),
        1.0,
    )


def _contrast(
    first: tuple[float, float, float, float], second: tuple[float, float, float, float]
) -> float:
    def luminance(color: tuple[float, float, float, float]) -> float:
        def channel(value: float) -> float:
            scaled = value / 255
            return (
                scaled / 12.92
                if scaled <= 0.03928
                else ((scaled + 0.055) / 1.055) ** 2.4
            )

        return (
            0.2126 * channel(color[0])
            + 0.7152 * channel(color[1])
            + 0.0722 * channel(color[2])
        )

    lighter, darker = sorted((luminance(first), luminance(second)), reverse=True)
    return (lighter + 0.05) / (darker + 0.05)


def _scope_block(css: str, signature: str) -> str:
    start = css.index(signature)
    open_at = css.index("{", start)
    depth = 0
    for index in range(open_at, len(css)):
        if css[index] == "{":
            depth += 1
        elif css[index] == "}":
            depth -= 1
            if depth == 0:
                return css[open_at + 1 : index]
    raise AssertionError(f"unbalanced block for {signature!r}")


def _scope_tokens(css: str, signature: str) -> dict[str, str]:
    body = _scope_block(css, signature)
    return {
        name: value.strip()
        for name, value in re.findall(r"(--[\w-]+)\s*:\s*([^;]+);", body)
    }


def _normalise_selector(selector: str) -> str:
    return re.sub(r"\s+", " ", selector).strip()


def _rule_declarations(css: str, selectors: list[str]) -> dict[str, str]:
    """Declarations of the flat rule whose selector list is exactly ``selectors``."""
    wanted = [_normalise_selector(item) for item in selectors]
    for match in re.finditer(r"([^{}]+)\{([^{}]*)\}", css):
        found = [
            _normalise_selector(item)
            for item in match.group(1).split(",")
            if item.strip()
        ]
        if found == wanted:
            return {
                name.strip(): value.strip()
                for name, value in re.findall(
                    r"([\w-]+)\s*:\s*([^;]+);", match.group(2)
                )
            }
    raise AssertionError(f"no rule with selector list {wanted!r}")


def _resolve_token(
    value: str, tokens: dict[str, str]
) -> tuple[float, float, float, float]:
    match = re.fullmatch(r"var\((--[\w-]+)(?:\s*,\s*[^)]*)?\)", value.strip())
    if match is None:
        return _parse_color(value)
    return _parse_color(tokens[match.group(1)])


class TestPickerContrast(unittest.TestCase):
    """The picker is text on a popup: every colour pair has to pass WCAG AA.

    The first version coloured the command token with the brand orange (2.6:1 on
    the selected row in the light theme) and the kind pill with
    ``--text-tertiary`` (reserved for strikethrough by the cycle-2 contrast
    audit); both were invisible to a test that only looked at class names.
    """

    THEMES = {
        "dark": ":root {",
        "light": '[data-theme="light"] {',
    }

    @classmethod
    def setUpClass(cls) -> None:
        cls.css = WEB_CSS.read_text(encoding="utf-8")
        cls.block = cls.css[
            cls.css.index(".aiia-slash-popup {") : cls.css.index(".button-container {")
        ]

    def _colours(
        self, theme: str
    ) -> tuple[
        dict[str, tuple[float, float, float, float]],
        dict[str, tuple[float, float, float, float]],
    ]:
        tokens = _scope_tokens(self.css, self.THEMES[theme])
        popup = _rule_declarations(self.block, [".aiia-slash-popup"])
        item_selected = _rule_declarations(
            self.block, ['.aiia-slash-popup .aiia-slash-item[aria-selected="true"]']
        )
        page = _resolve_token("var(--bg-primary)", tokens)
        popup_bg = _composite(_resolve_token(popup["background"], tokens), page)
        selected_bg = _composite(
            _resolve_token(item_selected["background"], tokens), popup_bg
        )
        token = _rule_declarations(self.block, [".aiia-slash-popup .aiia-slash-token"])
        secondary = _rule_declarations(
            self.block,
            [
                ".aiia-slash-popup .aiia-slash-label",
                ".aiia-slash-popup .aiia-slash-desc",
            ],
        )
        kind = _rule_declarations(self.block, [".aiia-slash-popup .aiia-slash-kind"])
        selected_text = _rule_declarations(
            self.block,
            [
                '.aiia-slash-popup .aiia-slash-item[aria-selected="true"] .aiia-slash-label',
                '.aiia-slash-popup .aiia-slash-item[aria-selected="true"] .aiia-slash-desc',
                '.aiia-slash-popup .aiia-slash-item[aria-selected="true"] .aiia-slash-kind',
            ],
        )
        text = {
            "token": _resolve_token(token["color"], tokens),
            "label and description": _resolve_token(secondary["color"], tokens),
            "kind pill": _resolve_token(kind["color"], tokens),
            "selected label, description and kind": _resolve_token(
                selected_text["color"], tokens
            ),
        }
        surfaces = {"popup": popup_bg, "selected row": selected_bg}
        return text, surfaces

    def test_every_text_colour_reaches_aa_on_the_surface_it_is_drawn_on(self) -> None:
        for theme in self.THEMES:
            text, surfaces = self._colours(theme)
            drawn_on = {
                "token": ("popup", "selected row"),
                "label and description": ("popup",),
                "kind pill": ("popup",),
                "selected label, description and kind": ("selected row",),
            }
            for name, color in text.items():
                for surface in drawn_on[name]:
                    with self.subTest(theme=theme, text=name, surface=surface):
                        ratio = _contrast(color, surfaces[surface])
                        self.assertGreaterEqual(
                            ratio,
                            _AA_NORMAL,
                            f"{theme}: {name} on {surface} is {ratio:.2f}:1",
                        )

    def test_selection_indicator_reaches_non_text_contrast(self) -> None:
        for theme in self.THEMES:
            with self.subTest(theme=theme):
                tokens = _scope_tokens(self.css, self.THEMES[theme])
                selected = _rule_declarations(
                    self.block,
                    ['.aiia-slash-popup .aiia-slash-item[aria-selected="true"]'],
                )
                self.assertRegex(
                    selected["outline"], r"^2px solid var\(--focus-ring-color"
                )
                ring = _resolve_token("var(--focus-ring-color)", tokens)
                _, surfaces = self._colours(theme)
                self.assertGreaterEqual(
                    _contrast(ring, surfaces["popup"]),
                    _NON_TEXT_MIN,
                    f"{theme}: the selection outline fades into the popup",
                )

    def test_text_colours_come_from_the_audited_text_tokens_only(self) -> None:
        used = set(re.findall(r"(?<![\w-])color:\s*var\((--[\w-]+)", self.block))
        self.assertTrue(used, "the picker block declares no text colour at all")
        self.assertLessEqual(
            used,
            {"--text-primary", "--text-secondary"},
            "tertiary / muted / brand colours are not AA text colours (cycle-2 audit)",
        )

    def test_high_contrast_preference_strengthens_the_selection_outline(self) -> None:
        match = re.search(
            r"@media \(prefers-contrast: more\) \{\s*"
            r'\.aiia-slash-popup \.aiia-slash-item\[aria-selected="true"\] \{([^}]*)\}',
            self.css,
        )
        self.assertIsNotNone(match)
        assert match is not None
        declarations = match.group(1)
        # ``Highlight`` is a pale translucent blue outside forced-colours mode (1.5:1
        # on white), the text token is the one colour that is always readable.
        self.assertIn("outline-color: var(--text-primary)", declarations)
        self.assertIn("outline-width: 3px", declarations)
        self.assertNotIn("Highlight", declarations)


class TestLocaleKeys(unittest.TestCase):
    def test_every_locale_carries_both_keys(self) -> None:
        for path in LOCALE_FILES:
            with self.subTest(locale=str(path.relative_to(REPO_ROOT))):
                data = json.loads(path.read_text(encoding="utf-8"))
                slash = data["aiia"]["slash"]
                self.assertEqual(sorted(slash), ["kindCommand", "listLabel"])
                for value in slash.values():
                    self.assertIsInstance(value, str)
                    self.assertTrue(value.strip())

    def test_js_fallbacks_match_the_english_locale(self) -> None:
        source = WEB_JS.read_text(encoding="utf-8")
        english = json.loads(LOCALE_FILES[0].read_text(encoding="utf-8"))["aiia"][
            "slash"
        ]
        for key, value in english.items():
            self.assertIn(f"'aiia.slash.{key}': '{value}'", source)

    def test_both_hosts_share_identical_slash_translations(self) -> None:
        for name in ("en", "zh-CN", "zh-TW"):
            web = json.loads(
                (STATIC_DIR / "locales" / f"{name}.json").read_text(encoding="utf-8")
            )["aiia"]["slash"]
            plugin = json.loads(
                (PLUGIN_DIR / "locales" / f"{name}.json").read_text(encoding="utf-8")
            )["aiia"]["slash"]
            self.assertEqual(web, plugin, name)


if __name__ == "__main__":
    unittest.main()
