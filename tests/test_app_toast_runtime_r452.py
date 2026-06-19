"""Runtime checks for Web UI frame fallbacks and toast lifecycle."""

from __future__ import annotations

import json
import shutil
import subprocess
import textwrap
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
APP_JS = REPO_ROOT / "src" / "ai_intervention_agent" / "static" / "js" / "app.js"


def _node_available() -> bool:
    return shutil.which("node") is not None


def _run_node(script: str) -> str:
    proc = subprocess.run(
        ["node", "-e", script],
        capture_output=True,
        check=False,
        text=True,
        timeout=15,
    )
    if proc.returncode != 0:
        raise AssertionError(
            f"node exited {proc.returncode}\nstdout={proc.stdout!r}\nstderr={proc.stderr!r}"
        )
    return proc.stdout


def _app_harness(case_js: str) -> str:
    return textwrap.dedent(
        f"""
        const fs = require('fs');
        const vm = require('vm');
        const code = fs.readFileSync({str(APP_JS)!r}, 'utf8');

        const timers = [];
        const clearedTimers = [];
        const documentListeners = {{}};
        const windowListeners = {{}};

        function pushListener(bucket, type, handler) {{
          if (!bucket[type]) bucket[type] = [];
          bucket[type].push(handler);
        }}

        function walk(root, predicate) {{
          if (!root) return null;
          if (predicate(root)) return root;
          for (const child of root.children || []) {{
            const found = walk(child, predicate);
            if (found) return found;
          }}
          return null;
        }}

        function createElement(tagName) {{
          const upperTagName = String(tagName || 'div').toUpperCase();
          const el = {{
            tagName: upperTagName,
            children: [],
            parentNode: null,
            attrs: {{}},
            className: '',
            id: '',
            _innerHTML: '',
            style: {{}},
            textContent: '',
            appendChild(child) {{
              if (child.parentNode && child.parentNode !== this) {{
                child.parentNode.removeChild(child);
              }}
              child.parentNode = this;
              this.children.push(child);
              return child;
            }},
            contains(node) {{
              return walk(this, (candidate) => candidate === node) !== null;
            }},
            getAttribute(name) {{
              return Object.prototype.hasOwnProperty.call(this.attrs, name)
                ? this.attrs[name]
                : null;
            }},
            querySelector(selector) {{
              return this.querySelectorAll(selector)[0] || null;
            }},
            querySelectorAll(selector) {{
              const wanted = String(selector || '').toUpperCase();
              const matches = [];
              function visit(node) {{
                for (const child of node.children || []) {{
                  if (child.tagName === wanted) matches.push(child);
                  visit(child);
                }}
              }}
              visit(this);
              return matches;
            }},
            removeChild(child) {{
              const index = this.children.indexOf(child);
              if (index >= 0) {{
                this.children.splice(index, 1);
                child.parentNode = null;
              }}
              return child;
            }},
            setAttribute(name, value) {{
              this.attrs[name] = String(value);
              if (name === 'id') this.id = String(value);
            }},
          }};
          el.classList = {{
            add(...names) {{
              const classes = new Set(
                String(el.className || '').split(/\\s+/).filter(Boolean),
              );
              names.forEach((name) => classes.add(String(name)));
              el.className = Array.from(classes).join(' ');
            }},
            contains(name) {{
              return String(el.className || '')
                .split(/\\s+/)
                .filter(Boolean)
                .includes(String(name));
            }},
            remove(...names) {{
              const removeSet = new Set(names.map((name) => String(name)));
              el.className = String(el.className || '')
                .split(/\\s+/)
                .filter(Boolean)
                .filter((name) => !removeSet.has(name))
                .join(' ');
            }},
          }};
          Object.defineProperty(el, 'innerHTML', {{
            get() {{
              return this._innerHTML;
            }},
            set(value) {{
              this._innerHTML = String(value);
              this.children.forEach((child) => {{
                child.parentNode = null;
              }});
              this.children = [];
              if (this._innerHTML.includes('<svg')) {{
                this.appendChild(createElement('svg'));
              }}
            }},
          }});
          Object.defineProperty(el, 'isConnected', {{
            get() {{
              return (
                this === body ||
                this === head ||
                this === documentElement ||
                walk(body, (candidate) => candidate === this) !== null
              );
            }},
          }});
          return el;
        }}

        const body = createElement('body');
        const head = createElement('head');
        const documentElement = createElement('html');

        function setTimeoutStub(fn, delay) {{
          const id = `timer-${{timers.length + 1}}`;
          timers.push({{ id, fn, delay, cleared: false }});
          return id;
        }}

        function clearTimeoutStub(id) {{
          clearedTimers.push(id);
          const timer = timers.find((entry) => entry.id === id);
          if (timer) timer.cleared = true;
        }}

        function runTimer(id, force) {{
          const timer = timers.find((entry) => entry.id === id);
          if (!timer || (timer.cleared && !force)) return false;
          timer.fn();
          return true;
        }}

        const sandbox = {{
          AbortController: function AbortController() {{
            this.signal = {{}};
            this.abort = function abort() {{}};
          }},
          AbortSignal: {{}},
          Array,
          Object,
          Promise,
          String,
          URL,
          console: {{
            debug() {{}},
            error() {{}},
            info() {{}},
            log() {{}},
            warn() {{}},
          }},
          document: {{
            body,
            head,
            documentElement,
            readyState: 'loading',
            addEventListener(type, handler) {{
              pushListener(documentListeners, type, handler);
            }},
            createElement(tagName) {{
              return createElement(tagName);
            }},
            createDocumentFragment() {{
              return createElement('#fragment');
            }},
            getElementById(id) {{
              return walk(body, (node) => node.id === id);
            }},
          }},
          fetch() {{
            return Promise.resolve();
          }},
          addEventListener(type, handler) {{
            pushListener(windowListeners, type, handler);
          }},
          location: {{
            href: 'http://127.0.0.1:8080/',
            replace(value) {{
              this.href = String(value);
            }},
          }},
          setTimeout: setTimeoutStub,
          clearTimeout: clearTimeoutStub,
          __clearedTimers: clearedTimers,
          __documentListeners: documentListeners,
          __runTimer: runTimer,
          __timers: timers,
          __windowListeners: windowListeners,
        }};
        sandbox.window = sandbox;
        sandbox.globalThis = sandbox;

        vm.createContext(sandbox);
        vm.runInContext(code, sandbox);

        function callToast(message) {{
          vm.runInContext(`_showToast(${{JSON.stringify(message)}})`, sandbox);
        }}

        function callStatus(message, type) {{
          vm.runInContext(
            `showStatus(${{JSON.stringify(message)}}, ${{JSON.stringify(type)}})`,
            sandbox,
          );
        }}

        (async () => {{
        {textwrap.indent(case_js, "  ")}
        }})().catch((err) => {{
          console.error(err && err.stack ? err.stack : err);
          process.exit(1);
        }});
        """
    )


@unittest.skipUnless(_node_available(), "node runtime unavailable")
def test_markdown_loading_state_uses_timeout_when_animation_frame_is_missing() -> None:
    script = _app_harness(
        """
        const target = sandbox.document.createElement('div');
        sandbox.__target = target;

        vm.runInContext('renderMarkdownContent(__target, "", false)', sandbox);
        const beforeTimer = {
          text: target.textContent,
          timers: sandbox.__timers.map(({ delay, cleared }) => ({ delay, cleared })),
        };

        sandbox.__runTimer('timer-1', false);
        process.stdout.write(
          JSON.stringify({
            beforeTimer,
            afterTimer: {
              text: target.textContent,
              timers: sandbox.__timers.map(({ delay, cleared }) => ({ delay, cleared })),
            },
          })
        );
        """
    )

    assert json.loads(_run_node(script)) == {
        "beforeTimer": {
            "text": "",
            "timers": [{"delay": 16, "cleared": False}],
        },
        "afterTimer": {
            "text": "page.loading",
            "timers": [{"delay": 16, "cleared": False}],
        },
    }


@unittest.skipUnless(_node_available(), "node runtime unavailable")
def test_lottie_fallback_cleanup_uses_timeout_and_parent_remove_fallback() -> None:
    script = _app_harness(
        """
        const listeners = {};
        const container = sandbox.document.createElement('div');
        container.id = 'hourglass-lottie';
        sandbox.document.body.appendChild(container);
        sandbox.document.readyState = 'complete';
        sandbox.lottie = {
          loadAnimation() {
            return {
              addEventListener(type, handler) {
                if (!listeners[type]) listeners[type] = [];
                listeners[type].push(handler);
              },
              destroy() {},
            };
          },
        };

        vm.runInContext('initHourglassAnimation()', sandbox);
        sandbox.__runTimer('timer-1', false);
        sandbox.__runTimer('timer-2', false);
        await Promise.resolve();

        const afterLoad = {
          childTags: container.children.map((child) => child.tagName),
          opacity: container.style.opacity,
          timers: sandbox.__timers.map(({ delay, cleared }) => ({ delay, cleared })),
          domLoadedListeners: (listeners.DOMLoaded || []).length,
        };

        for (const handler of listeners.DOMLoaded || []) handler();
        const afterDomLoaded = {
          childTags: container.children.map((child) => child.tagName),
          opacity: container.style.opacity,
          timers: sandbox.__timers.map(({ delay, cleared }) => ({ delay, cleared })),
        };

        sandbox.__runTimer('timer-4', false);
        process.stdout.write(
          JSON.stringify({
            afterLoad,
            afterDomLoaded,
            afterFrame: {
              childTags: container.children.map((child) => child.tagName),
              opacity: container.style.opacity,
            },
          })
        );
        """
    )

    assert json.loads(_run_node(script)) == {
        "afterLoad": {
            "childTags": ["SVG"],
            "opacity": "0",
            "timers": [
                {"delay": 500, "cleared": False},
                {"delay": 0, "cleared": False},
                {"delay": 2000, "cleared": False},
            ],
            "domLoadedListeners": 2,
        },
        "afterDomLoaded": {
            "childTags": [],
            "opacity": "0",
            "timers": [
                {"delay": 500, "cleared": False},
                {"delay": 0, "cleared": False},
                {"delay": 2000, "cleared": False},
                {"delay": 16, "cleared": False},
            ],
        },
        "afterFrame": {"childTags": [], "opacity": "1"},
    }


@unittest.skipUnless(_node_available(), "node runtime unavailable")
def test_copy_code_button_clears_stale_restore_timer_and_restores_baseline() -> None:
    script = _app_harness(
        """
        const writes = [];
        sandbox.navigator = {
          clipboard: {
            async writeText(value) {
              writes.push(value);
            },
          },
        };

        const pre = sandbox.document.createElement('pre');
        const code = sandbox.document.createElement('code');
        code.textContent = 'hello world';
        pre.appendChild(code);
        sandbox.document.body.appendChild(pre);

        const button = sandbox.document.createElement('button');
        button.className = 'copy-button';
        button.innerHTML = '<span>Copy</span>';
        sandbox.document.body.appendChild(button);

        async function callCopy() {
          sandbox.__copyPre = pre;
          sandbox.__copyButton = button;
          await vm.runInContext(
            'copyCodeToClipboard(__copyPre, __copyButton)',
            sandbox,
          );
        }

        await callCopy();
        const afterFirst = {
          copiedText: button.innerHTML.includes('status.copied'),
          defaultHtml: button.innerHTML === '<span>Copy</span>',
          className: button.className,
          timers: sandbox.__timers.map(({ id, delay, cleared }) => ({
            id,
            delay,
            cleared,
          })),
          clearedTimers: [...sandbox.__clearedTimers],
          writes: [...writes],
        };

        await callCopy();
        const afterSecond = {
          copiedText: button.innerHTML.includes('status.copied'),
          defaultHtml: button.innerHTML === '<span>Copy</span>',
          className: button.className,
          timers: sandbox.__timers.map(({ id, delay, cleared }) => ({
            id,
            delay,
            cleared,
          })),
          clearedTimers: [...sandbox.__clearedTimers],
          writes: [...writes],
        };

        sandbox.__runTimer('timer-1', true);
        const afterStaleRestore = {
          copiedText: button.innerHTML.includes('status.copied'),
          defaultHtml: button.innerHTML === '<span>Copy</span>',
          className: button.className,
        };

        sandbox.__runTimer('timer-2', false);
        const afterCurrentRestore = {
          copiedText: button.innerHTML.includes('status.copied'),
          defaultHtml: button.innerHTML === '<span>Copy</span>',
          className: button.className,
        };

        process.stdout.write(
          JSON.stringify({
            afterFirst,
            afterSecond,
            afterStaleRestore,
            afterCurrentRestore,
          })
        );
        """
    )

    assert json.loads(_run_node(script)) == {
        "afterFirst": {
            "copiedText": True,
            "defaultHtml": False,
            "className": "copy-button copied",
            "timers": [{"id": "timer-1", "delay": 2000, "cleared": False}],
            "clearedTimers": [],
            "writes": ["hello world"],
        },
        "afterSecond": {
            "copiedText": True,
            "defaultHtml": False,
            "className": "copy-button copied",
            "timers": [
                {"id": "timer-1", "delay": 2000, "cleared": True},
                {"id": "timer-2", "delay": 2000, "cleared": False},
            ],
            "clearedTimers": ["timer-1"],
            "writes": ["hello world", "hello world"],
        },
        "afterStaleRestore": {
            "copiedText": True,
            "defaultHtml": False,
            "className": "copy-button copied",
        },
        "afterCurrentRestore": {
            "copiedText": False,
            "defaultHtml": True,
            "className": "copy-button",
        },
    }


@unittest.skipUnless(_node_available(), "node runtime unavailable")
def test_toast_clears_stale_hide_timer_and_ignores_stale_callbacks() -> None:
    script = _app_harness(
        """
        callToast('first');
        callToast('second');

        const toast = sandbox.document.getElementById('_aiia-toast');
        const afterCalls = {
          text: toast.textContent,
          opacity: toast.style.opacity,
          transform: toast.style.transform,
          timers: sandbox.__timers.map(({ id, delay, cleared }) => ({
            id,
            delay,
            cleared,
          })),
          clearedTimers: [...sandbox.__clearedTimers],
        };

        sandbox.__runTimer('timer-1', true);
        const afterStaleShow = {
          opacity: toast.style.opacity,
          transform: toast.style.transform,
        };

        sandbox.__runTimer('timer-3', false);
        const afterCurrentShow = {
          opacity: toast.style.opacity,
          transform: toast.style.transform,
        };

        sandbox.__runTimer('timer-2', true);
        const afterStaleHide = {
          opacity: toast.style.opacity,
          transform: toast.style.transform,
        };

        sandbox.__runTimer('timer-4', false);
        const afterCurrentHide = {
          opacity: toast.style.opacity,
          transform: toast.style.transform,
        };

        process.stdout.write(
          JSON.stringify({
            afterCalls,
            afterStaleShow,
            afterCurrentShow,
            afterStaleHide,
            afterCurrentHide,
          })
        );
        """
    )

    assert json.loads(_run_node(script)) == {
        "afterCalls": {
            "text": "second",
            "opacity": "0",
            "transform": "translateX(-50%) translateY(-120%)",
            "timers": [
                {"id": "timer-1", "delay": 16, "cleared": False},
                {"id": "timer-2", "delay": 1800, "cleared": True},
                {"id": "timer-3", "delay": 16, "cleared": False},
                {"id": "timer-4", "delay": 1800, "cleared": False},
            ],
            "clearedTimers": ["timer-2"],
        },
        "afterStaleShow": {
            "opacity": "0",
            "transform": "translateX(-50%) translateY(-120%)",
        },
        "afterCurrentShow": {
            "opacity": "1",
            "transform": "translateX(-50%) translateY(0)",
        },
        "afterStaleHide": {
            "opacity": "1",
            "transform": "translateX(-50%) translateY(0)",
        },
        "afterCurrentHide": {
            "opacity": "0",
            "transform": "translateX(-50%) translateY(-120%)",
        },
    }


@unittest.skipUnless(_node_available(), "node runtime unavailable")
def test_status_message_clears_stale_dismiss_timer_and_ignores_stale_callbacks() -> (
    None
):
    script = _app_harness(
        """
        const noContentContainer = sandbox.document.createElement('div');
        noContentContainer.id = 'no-content-container';
        noContentContainer.style.display = 'flex';
        sandbox.document.body.appendChild(noContentContainer);

        const status = sandbox.document.createElement('div');
        status.id = 'no-content-status-message';
        sandbox.document.body.appendChild(status);

        callStatus('Saved', 'success');
        const afterSuccess = {
          text: status.textContent,
          className: status.className,
          display: status.style.display,
          timers: sandbox.__timers.map(({ id, delay, cleared }) => ({
            id,
            delay,
            cleared,
          })),
          clearedTimers: [...sandbox.__clearedTimers],
        };

        callStatus('Working', 'info');
        const afterInfo = {
          text: status.textContent,
          className: status.className,
          display: status.style.display,
          timers: sandbox.__timers.map(({ id, delay, cleared }) => ({
            id,
            delay,
            cleared,
          })),
          clearedTimers: [...sandbox.__clearedTimers],
        };

        sandbox.__runTimer('timer-1', true);
        const afterStaleSuccessDismiss = {
          text: status.textContent,
          display: status.style.display,
        };

        callStatus('Careful', 'warning');
        callStatus('Failed', 'error');
        sandbox.__runTimer('timer-2', true);
        const afterStaleWarningDismiss = {
          text: status.textContent,
          className: status.className,
          display: status.style.display,
          timers: sandbox.__timers.map(({ id, delay, cleared }) => ({
            id,
            delay,
            cleared,
          })),
          clearedTimers: [...sandbox.__clearedTimers],
        };

        sandbox.__runTimer('timer-3', false);
        const afterCurrentErrorDismiss = {
          text: status.textContent,
          className: status.className,
          display: status.style.display,
        };

        process.stdout.write(
          JSON.stringify({
            afterSuccess,
            afterInfo,
            afterStaleSuccessDismiss,
            afterStaleWarningDismiss,
            afterCurrentErrorDismiss,
          })
        );
        """
    )

    assert json.loads(_run_node(script)) == {
        "afterSuccess": {
            "text": "Saved",
            "className": "status-message status-success",
            "display": "block",
            "timers": [{"id": "timer-1", "delay": 3000, "cleared": False}],
            "clearedTimers": [],
        },
        "afterInfo": {
            "text": "Working",
            "className": "status-message status-info",
            "display": "block",
            "timers": [{"id": "timer-1", "delay": 3000, "cleared": True}],
            "clearedTimers": ["timer-1"],
        },
        "afterStaleSuccessDismiss": {
            "text": "Working",
            "display": "block",
        },
        "afterStaleWarningDismiss": {
            "text": "Failed",
            "className": "status-message status-error",
            "display": "block",
            "timers": [
                {"id": "timer-1", "delay": 3000, "cleared": True},
                {"id": "timer-2", "delay": 5000, "cleared": True},
                {"id": "timer-3", "delay": 10000, "cleared": False},
            ],
            "clearedTimers": ["timer-1", "timer-2"],
        },
        "afterCurrentErrorDismiss": {
            "text": "Failed",
            "className": "status-message status-error",
            "display": "none",
        },
    }
