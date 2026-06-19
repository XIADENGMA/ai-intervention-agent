"""Runtime checks for feedback draft autosave lifecycle behavior.

The R139 source invariants lock the shape of ``feedback_drafts.js``. These
tests execute the module in a small Node VM browser harness so regressions in
timer idempotency and page-exit flushing are caught as behavior, not just text.
"""

from __future__ import annotations

import shutil
import subprocess
import textwrap
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
FEEDBACK_DRAFTS_JS = (
    REPO_ROOT / "src" / "ai_intervention_agent" / "static" / "js" / "feedback_drafts.js"
)


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


def _drafts_harness(case_js: str) -> str:
    return textwrap.dedent(
        f"""
        const fs = require('fs');
        const vm = require('vm');
        const code = fs.readFileSync({str(FEEDBACK_DRAFTS_JS)!r}, 'utf8');

        const storage = new Map();
        const documentListeners = {{}};
        const windowListeners = {{}};
        const intervals = [];
        const clearedIntervals = [];
        const timeouts = [];
        const clearedTimeouts = [];
        let now = 1700000000000;

        function pushListener(bucket, type, handler) {{
          if (!bucket[type]) bucket[type] = [];
          bucket[type].push(handler);
        }}

        function createTextarea(name) {{
          const listeners = {{}};
          return {{
            name,
            value: '',
            addCalls: [],
            removeCalls: [],
            addEventListener(type, handler) {{
              this.addCalls.push({{ type, handler }});
              pushListener(listeners, type, handler);
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
            listeners,
          }};
        }}

        let textarea = createTextarea('one');

        const localStorage = {{
          getItem(key) {{
            return storage.has(key) ? storage.get(key) : null;
          }},
          setItem(key, value) {{
            storage.set(key, String(value));
          }},
          removeItem(key) {{
            storage.delete(key);
          }},
        }};

        const sandbox = {{
          Date: {{ now: () => now }},
          JSON,
          Number,
          Object,
          console: {{
            debug() {{}},
            error() {{}},
            info() {{}},
            log() {{}},
            warn() {{}},
          }},
          document: {{
            hidden: false,
            readyState: 'complete',
            addEventListener(type, handler) {{
              pushListener(documentListeners, type, handler);
            }},
            getElementById(id) {{
              return id === 'feedback-text' ? textarea : null;
            }},
          }},
          localStorage,
          setInterval(fn, delay) {{
            const id = `interval-${{intervals.length + 1}}`;
            intervals.push({{ id, fn, delay }});
            return id;
          }},
          clearInterval(id) {{
            clearedIntervals.push(id);
          }},
          setTimeout(fn, delay) {{
            const id = `timeout-${{timeouts.length + 1}}`;
            timeouts.push({{ id, fn, delay }});
            return id;
          }},
          clearTimeout(id) {{
            clearedTimeouts.push(id);
          }},
          addEventListener(type, handler) {{
            pushListener(windowListeners, type, handler);
          }},
          activeTaskId: 'task-1',
          taskTextareaContents: {{}},
          __clearedIntervals: clearedIntervals,
          __clearedTimeouts: clearedTimeouts,
          __documentListeners: documentListeners,
          __intervals: intervals,
          __storage: storage,
          __textarea: textarea,
          __createTextarea: createTextarea,
          __getTextarea() {{ return textarea; }},
          __setTextarea(nextTextarea) {{
            textarea = nextTextarea;
            sandbox.__textarea = nextTextarea;
            sandbox.__textareaListeners = nextTextarea.listeners;
          }},
          __textareaListeners: textarea.listeners,
          __timeouts: timeouts,
          __windowListeners: windowListeners,
        }};
        sandbox.window = sandbox;

        vm.createContext(sandbox);
        vm.runInContext(code, sandbox);

        function readEnvelope() {{
          const raw = sandbox.localStorage.getItem('aiia.feedbackDrafts.v1');
          return raw ? JSON.parse(raw) : null;
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
def test_init_is_idempotent_for_listeners_and_periodic_sync() -> None:
    script = _drafts_harness(
        """
        const api = sandbox.AIIA_FEEDBACK_DRAFTS;
        api.init();
        api.init();

        process.stdout.write(
          JSON.stringify({
            intervals: sandbox.__intervals.length,
            inputListeners: (sandbox.__textareaListeners.input || []).length,
            visibilityListeners:
              (sandbox.__documentListeners.visibilitychange || []).length,
            pagehideListeners: (sandbox.__windowListeners.pagehide || []).length,
            beforeunloadListeners:
              (sandbox.__windowListeners.beforeunload || []).length,
          })
        );
        """
    )

    assert _run_node(script) == (
        '{"intervals":1,"inputListeners":1,"visibilityListeners":1,'
        '"pagehideListeners":1,"beforeunloadListeners":0}'
    )


@unittest.skipUnless(_node_available(), "node runtime unavailable")
def test_init_rebinds_input_listener_when_textarea_dom_is_replaced() -> None:
    script = _drafts_harness(
        """
        const api = sandbox.AIIA_FEEDBACK_DRAFTS;
        const oldTextarea = sandbox.__getTextarea();

        oldTextarea.value = 'stale draft';
        oldTextarea.dispatch('input');
        const nextTextarea = sandbox.__createTextarea('two');
        sandbox.__setTextarea(nextTextarea);
        const rebound = api.init();

        nextTextarea.value = 'replacement draft';
        nextTextarea.dispatch('input');
        sandbox.__timeouts[sandbox.__timeouts.length - 1].fn();
        const envelope = readEnvelope();

        process.stdout.write(
          JSON.stringify({
            reboundName: rebound.input.textarea.name,
            oldInputListeners: oldTextarea.listenerCount('input'),
            oldRemoveCalls: oldTextarea.removeCalls
              .filter((entry) => entry.type === 'input').length,
            nextInputListeners: nextTextarea.listenerCount('input'),
            clearedTimeouts: sandbox.__clearedTimeouts,
            draft: envelope.drafts['task-1'].text,
          })
        );
        """
    )

    assert _run_node(script) == (
        '{"reboundName":"two","oldInputListeners":0,"oldRemoveCalls":1,'
        '"nextInputListeners":1,"clearedTimeouts":["timeout-1"],'
        '"draft":"replacement draft"}'
    )


@unittest.skipUnless(_node_available(), "node runtime unavailable")
def test_pagehide_prefers_current_textarea_after_dom_replacement_before_reinit() -> (
    None
):
    script = _drafts_harness(
        """
        const nextTextarea = sandbox.__createTextarea('two');
        nextTextarea.value = 'current dom draft';
        sandbox.__setTextarea(nextTextarea);

        sandbox.__windowListeners.pagehide[0]({ persisted: false });
        const envelope = readEnvelope();

        process.stdout.write(
          JSON.stringify({
            currentName: sandbox.__getTextarea().name,
            draft: envelope.drafts['task-1'].text,
            memoryDraft: sandbox.taskTextareaContents['task-1'],
          })
        );
        """
    )

    assert _run_node(script) == (
        '{"currentName":"two","draft":"current dom draft",'
        '"memoryDraft":"current dom draft"}'
    )


@unittest.skipUnless(_node_available(), "node runtime unavailable")
def test_pagehide_flushes_pending_debounced_textarea_value() -> None:
    script = _drafts_harness(
        """
        sandbox.__textarea.value = 'draft before close';
        sandbox.__textarea.dispatch('input');
        if (sandbox.__timeouts.length !== 1) {
          throw new Error('expected one pending input debounce');
        }
        sandbox.__windowListeners.pagehide[0]({ persisted: false });
        const envelope = readEnvelope();

        process.stdout.write(
          JSON.stringify({
            clearedTimeouts: sandbox.__clearedTimeouts,
            draft: envelope.drafts['task-1'].text,
            memoryDraft: sandbox.taskTextareaContents['task-1'],
          })
        );
        """
    )

    assert _run_node(script) == (
        '{"clearedTimeouts":["timeout-1"],"draft":"draft before close",'
        '"memoryDraft":"draft before close"}'
    )


@unittest.skipUnless(_node_available(), "node runtime unavailable")
def test_visibility_hidden_stops_periodic_sync_and_visible_restarts_it() -> None:
    script = _drafts_harness(
        """
        sandbox.document.hidden = true;
        sandbox.__documentListeners.visibilitychange[0]();
        sandbox.document.hidden = false;
        sandbox.__documentListeners.visibilitychange[0]();
        sandbox.AIIA_FEEDBACK_DRAFTS.init();

        process.stdout.write(
          JSON.stringify({
            intervals: sandbox.__intervals.map((entry) => entry.id),
            clearedIntervals: sandbox.__clearedIntervals,
          })
        );
        """
    )

    assert _run_node(script) == (
        '{"intervals":["interval-1","interval-2"],"clearedIntervals":["interval-1"]}'
    )
