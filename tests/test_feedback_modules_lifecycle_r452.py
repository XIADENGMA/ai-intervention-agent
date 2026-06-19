"""Lifecycle checks for the small feedback UI modules.

Both modules auto-initialize on load and also expose public ``init()`` helpers
for tests and future partial UI refreshes. Repeated calls should refresh cheap
state, not accumulate anonymous listeners or orphaned observers.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import textwrap
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
JS_DIR = REPO_ROOT / "src" / "ai_intervention_agent" / "static" / "js"
CHAR_COUNTER_JS = JS_DIR / "feedback_char_counter.js"
TEXTAREA_HEIGHT_JS = JS_DIR / "feedback_textarea_height.js"


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


def _char_harness(case_js: str) -> str:
    return textwrap.dedent(
        f"""
        const fs = require('fs');
        const vm = require('vm');
        const code = fs.readFileSync({str(CHAR_COUNTER_JS)!r}, 'utf8');

        function createClassList() {{
          const values = new Set();
          return {{
            values,
            add(name) {{ values.add(name); }},
            remove(...names) {{ for (const name of names) values.delete(name); }},
          }};
        }}

        function createTextarea(name) {{
          const listeners = {{ input: [] }};
          return {{
            name,
            value: '',
            addCalls: [],
            removeCalls: [],
            addEventListener(type, handler) {{
              this.addCalls.push({{ type, handler }});
              listeners[type] = listeners[type] || [];
              listeners[type].push(handler);
            }},
            removeEventListener(type, handler) {{
              this.removeCalls.push({{ type, handler }});
              listeners[type] = (listeners[type] || []).filter((h) => h !== handler);
            }},
            dispatch(type) {{
              for (const handler of [...(listeners[type] || [])]) handler({{ type }});
            }},
            listenerCount(type) {{
              return (listeners[type] || []).length;
            }},
          }};
        }}

        function createCounter(name) {{
          return {{
            name,
            hidden: true,
            textContent: '',
            classList: createClassList(),
          }};
        }}

        let currentTextarea = createTextarea('one');
        let currentCounter = createCounter('one');

        const sandbox = {{
          Intl,
          JSON,
          Object,
          Set,
          String,
          console: {{ debug() {{}}, error() {{}}, log() {{}}, warn() {{}} }},
          document: {{
            readyState: 'complete',
            addEventListener() {{}},
            getElementById(id) {{
              if (id === 'feedback-text') return currentTextarea;
              if (id === 'feedback-char-counter') return currentCounter;
              return null;
            }},
          }},
          window: null,
          __getElements() {{
            return {{ textarea: currentTextarea, counter: currentCounter }};
          }},
          __setElements(textarea, counter) {{
            currentTextarea = textarea;
            currentCounter = counter;
          }},
          __createCounter: createCounter,
          __createTextarea: createTextarea,
        }};
        sandbox.window = sandbox;
        sandbox.globalThis = sandbox;

        vm.createContext(sandbox);
        vm.runInContext(code, sandbox);
        const api = sandbox.window.AIIA_FEEDBACK_CHAR_COUNTER;

        {textwrap.indent(case_js, "        ")}
        """
    )


def _height_harness(case_js: str, *, with_resize_observer: bool) -> str:
    resize_observer_setup = (
        """
        function MockResizeObserver(handler) {
          this.handler = handler;
          this.observeCalls = [];
          this.disconnectCalls = 0;
          resizeObservers.push(this);
        }
        MockResizeObserver.prototype.observe = function (target) {
          this.observeCalls.push(target.name);
        };
        MockResizeObserver.prototype.disconnect = function () {
          this.disconnectCalls += 1;
        };
        sandbox.ResizeObserver = MockResizeObserver;
        """
        if with_resize_observer
        else ""
    )
    return textwrap.dedent(
        f"""
        const fs = require('fs');
        const vm = require('vm');
        const code = fs.readFileSync({str(TEXTAREA_HEIGHT_JS)!r}, 'utf8');

        function createTextarea(name) {{
          const listeners = {{ mouseup: [], touchend: [] }};
          return {{
            name,
            offsetHeight: 180,
            style: {{}},
            addCalls: [],
            removeCalls: [],
            addEventListener(type, handler) {{
              this.addCalls.push({{ type, handler }});
              listeners[type] = listeners[type] || [];
              listeners[type].push(handler);
            }},
            removeEventListener(type, handler) {{
              this.removeCalls.push({{ type, handler }});
              listeners[type] = (listeners[type] || []).filter((h) => h !== handler);
            }},
            listenerCount(type) {{
              return (listeners[type] || []).length;
            }},
          }};
        }}

        let currentTextarea = createTextarea('one');
        let storedHeight = null;
        const resizeObservers = [];
        const timeouts = [];

        const sandbox = {{
          Date,
          JSON,
          Math,
          Number,
          String,
          clearTimeout(id) {{
            const timer = timeouts.find((entry) => entry.id === id);
            if (timer) timer.cleared = true;
          }},
          console: {{ debug() {{}}, error() {{}}, log() {{}}, warn() {{}} }},
          document: {{
            readyState: 'complete',
            addEventListener() {{}},
            getElementById(id) {{
              return id === 'feedback-text' ? currentTextarea : null;
            }},
          }},
          localStorage: {{
            getItem(key) {{
              return key === 'aiia.feedbackTextareaHeight.v1' ? storedHeight : null;
            }},
            setItem(key, value) {{
              if (key === 'aiia.feedbackTextareaHeight.v1') storedHeight = String(value);
            }},
          }},
          setTimeout(fn, ms) {{
            const id = timeouts.length + 1;
            timeouts.push({{ id, fn, ms, cleared: false }});
            return id;
          }},
          window: null,
          __createTextarea: createTextarea,
          __getTextarea() {{ return currentTextarea; }},
          __resizeObservers: resizeObservers,
          __setTextarea(textarea) {{ currentTextarea = textarea; }},
          __timeouts: timeouts,
        }};
        {textwrap.indent(resize_observer_setup, "        ")}
        sandbox.window = sandbox;
        sandbox.globalThis = sandbox;

        vm.createContext(sandbox);
        vm.runInContext(code, sandbox);
        const api = sandbox.window.AIIA_FEEDBACK_TEXTAREA_HEIGHT;

        {textwrap.indent(case_js, "        ")}
        """
    )


class TestFeedbackModuleLifecycleSourceContracts(unittest.TestCase):
    def test_char_counter_uses_one_active_named_input_handler(self) -> None:
        src = CHAR_COUNTER_JS.read_text(encoding="utf-8")
        self.assertIn("let activeBinding = null", src)
        self.assertIn("function handleInput()", src)
        self.assertIn('textarea.addEventListener("input", handleInput)', src)
        self.assertIn(
            'activeBinding.textarea.removeEventListener("input", handleInput)',
            src,
        )

    def test_textarea_height_disconnects_old_resize_binding(self) -> None:
        src = TEXTAREA_HEIGHT_JS.read_text(encoding="utf-8")
        self.assertIn("let activeResizeBinding = null", src)
        self.assertIn("function disconnectActiveResizeBinding()", src)
        self.assertIn("activeResizeBinding.observer.disconnect()", src)
        self.assertIn('typeof textarea.removeEventListener === "function"', src)
        self.assertIn('textarea.removeEventListener("mouseup"', src)
        self.assertIn('textarea.removeEventListener("touchend"', src)
        self.assertIn("clearTimeout(activeResizeBinding.timeoutId)", src)


@unittest.skipUnless(_node_available(), "node runtime unavailable")
def test_char_counter_repeated_init_keeps_one_input_listener() -> None:
    script = _char_harness(
        """
        const first = api.init();
        const second = api.init();
        const { textarea, counter } = sandbox.__getElements();
        textarea.value = 'hello';
        textarea.dispatch('input');

        process.stdout.write(JSON.stringify({
          sameBinding: first === second,
          addInputCalls: textarea.addCalls.filter((entry) => entry.type === 'input').length,
          inputListeners: textarea.listenerCount('input'),
          removeInputCalls: textarea.removeCalls.filter((entry) => entry.type === 'input').length,
          counterText: counter.textContent,
          counterHidden: counter.hidden,
        }));
        """
    )

    assert json.loads(_run_node(script)) == {
        "sameBinding": True,
        "addInputCalls": 1,
        "inputListeners": 1,
        "removeInputCalls": 0,
        "counterText": "5 chars",
        "counterHidden": False,
    }


@unittest.skipUnless(_node_available(), "node runtime unavailable")
def test_char_counter_dom_replacement_removes_old_input_listener() -> None:
    script = _char_harness(
        """
        const oldElements = sandbox.__getElements();
        const nextTextarea = sandbox.__createTextarea('two');
        const nextCounter = sandbox.__createCounter('two');
        sandbox.__setElements(nextTextarea, nextCounter);

        api.init();
        oldElements.textarea.value = 'stale';
        oldElements.textarea.dispatch('input');
        nextTextarea.value = 'fresh';
        nextTextarea.dispatch('input');

        process.stdout.write(JSON.stringify({
          oldInputListeners: oldElements.textarea.listenerCount('input'),
          oldRemoveInputCalls: oldElements.textarea.removeCalls
            .filter((entry) => entry.type === 'input').length,
          nextAddInputCalls: nextTextarea.addCalls
            .filter((entry) => entry.type === 'input').length,
          nextInputListeners: nextTextarea.listenerCount('input'),
          nextCounterText: nextCounter.textContent,
        }));
        """
    )

    assert json.loads(_run_node(script)) == {
        "oldInputListeners": 0,
        "oldRemoveInputCalls": 1,
        "nextAddInputCalls": 1,
        "nextInputListeners": 1,
        "nextCounterText": "5 chars",
    }


@unittest.skipUnless(_node_available(), "node runtime unavailable")
def test_textarea_height_repeated_init_reuses_resize_observer() -> None:
    script = _height_harness(
        """
        const first = api.init();
        const second = api.init();
        process.stdout.write(JSON.stringify({
          sameBinding: first === second,
          observerInstances: sandbox.__resizeObservers.length,
          observeCalls: sandbox.__resizeObservers[0].observeCalls,
          disconnectCalls: sandbox.__resizeObservers[0].disconnectCalls,
          mode: first.mode,
        }));
        """,
        with_resize_observer=True,
    )

    assert json.loads(_run_node(script)) == {
        "sameBinding": True,
        "observerInstances": 1,
        "observeCalls": ["one"],
        "disconnectCalls": 0,
        "mode": "resize_observer",
    }


@unittest.skipUnless(_node_available(), "node runtime unavailable")
def test_textarea_height_dom_replacement_disconnects_previous_observer() -> None:
    script = _height_harness(
        """
        const oldObserver = sandbox.__resizeObservers[0];
        const nextTextarea = sandbox.__createTextarea('two');
        sandbox.__setTextarea(nextTextarea);
        const nextBinding = api.init();

        process.stdout.write(JSON.stringify({
          observerInstances: sandbox.__resizeObservers.length,
          oldDisconnectCalls: oldObserver.disconnectCalls,
          nextObserveCalls: nextBinding.observer.observeCalls,
          nextMode: nextBinding.mode,
        }));
        """,
        with_resize_observer=True,
    )

    assert json.loads(_run_node(script)) == {
        "observerInstances": 2,
        "oldDisconnectCalls": 1,
        "nextObserveCalls": ["two"],
        "nextMode": "resize_observer",
    }


@unittest.skipUnless(_node_available(), "node runtime unavailable")
def test_textarea_height_fallback_listener_lifecycle_is_single_binding() -> None:
    script = _height_harness(
        """
        const first = api.init();
        const second = api.init();
        const oldTextarea = sandbox.__getTextarea();
        const nextTextarea = sandbox.__createTextarea('two');
        sandbox.__setTextarea(nextTextarea);
        api.init();

        process.stdout.write(JSON.stringify({
          sameBinding: first === second,
          oldMode: first.mode,
          oldMouseupListeners: oldTextarea.listenerCount('mouseup'),
          oldTouchendListeners: oldTextarea.listenerCount('touchend'),
          oldMouseupRemoveCalls: oldTextarea.removeCalls
            .filter((entry) => entry.type === 'mouseup').length,
          oldTouchendRemoveCalls: oldTextarea.removeCalls
            .filter((entry) => entry.type === 'touchend').length,
          nextMouseupListeners: nextTextarea.listenerCount('mouseup'),
          nextTouchendListeners: nextTextarea.listenerCount('touchend'),
        }));
        """,
        with_resize_observer=False,
    )

    assert json.loads(_run_node(script)) == {
        "sameBinding": True,
        "oldMode": "mouseup_fallback",
        "oldMouseupListeners": 0,
        "oldTouchendListeners": 0,
        "oldMouseupRemoveCalls": 1,
        "oldTouchendRemoveCalls": 1,
        "nextMouseupListeners": 1,
        "nextTouchendListeners": 1,
    }


@unittest.skipUnless(_node_available(), "node runtime unavailable")
def test_textarea_height_fallback_rebind_tolerates_missing_remove_event_listener() -> (
    None
):
    script = _height_harness(
        """
        const oldTextarea = sandbox.__getTextarea();
        delete oldTextarea.removeEventListener;

        const nextTextarea = sandbox.__createTextarea('two');
        sandbox.__setTextarea(nextTextarea);
        const nextBinding = api.init();

        process.stdout.write(JSON.stringify({
          oldHasRemoveEventListener: typeof oldTextarea.removeEventListener === 'function',
          oldMouseupListeners: oldTextarea.listenerCount('mouseup'),
          oldTouchendListeners: oldTextarea.listenerCount('touchend'),
          nextMode: nextBinding.mode,
          nextMouseupListeners: nextTextarea.listenerCount('mouseup'),
          nextTouchendListeners: nextTextarea.listenerCount('touchend'),
        }));
        """,
        with_resize_observer=False,
    )

    assert json.loads(_run_node(script)) == {
        "oldHasRemoveEventListener": False,
        "oldMouseupListeners": 1,
        "oldTouchendListeners": 1,
        "nextMode": "mouseup_fallback",
        "nextMouseupListeners": 1,
        "nextTouchendListeners": 1,
    }
