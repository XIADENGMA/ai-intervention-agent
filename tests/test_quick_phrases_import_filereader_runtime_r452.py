"""Runtime checks for Quick Phrases import FileReader failure handling."""

from __future__ import annotations

import json
import shutil
import subprocess
import textwrap
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
QUICK_PHRASES_JS = (
    REPO_ROOT / "src" / "ai_intervention_agent" / "static" / "js" / "quick_phrases.js"
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


def _quick_phrases_import_harness(case_js: str) -> str:
    return textwrap.dedent(
        f"""
        const fs = require('fs');
        const vm = require('vm');
        const code = fs.readFileSync({str(QUICK_PHRASES_JS)!r}, 'utf8');

        const alerts = [];
        const documentListeners = {{}};
        const elements = {{}};
        const storage = new Map();

        function pushListener(bucket, type, handler) {{
          if (!bucket[type]) bucket[type] = [];
          bucket[type].push(handler);
        }}

        function createElement(tagName, id) {{
          const listeners = {{}};
          const el = {{
            id: id || '',
            tagName: String(tagName || 'div').toUpperCase(),
            children: [],
            className: '',
            dataset: {{}},
            disabled: false,
            files: [],
            parentNode: null,
            textContent: '',
            type: '',
            value: '',
            classList: {{
              values: [],
              add(name) {{
                this.values.push(name);
              }},
            }},
            get firstChild() {{
              return this.children.length > 0 ? this.children[0] : null;
            }},
            appendChild(child) {{
              child.parentNode = this;
              this.children.push(child);
              return child;
            }},
            removeChild(child) {{
              const idx = this.children.indexOf(child);
              if (idx !== -1) this.children.splice(idx, 1);
              child.parentNode = null;
              return child;
            }},
            setAttribute() {{}},
            addEventListener(type, handler) {{
              pushListener(listeners, type, handler);
            }},
            click() {{}},
            dispatch(type, eventInit) {{
              const event = Object.assign({{ type, target: this }}, eventInit || {{}});
              for (const handler of [...(listeners[type] || [])]) {{
                handler(event);
              }}
              return event;
            }},
            querySelector(selector) {{
              if (selector === '.quick-phrases-form') {{
                return this.children.find((child) => child.className === 'quick-phrases-form') || null;
              }}
              if (selector === 'input, textarea') {{
                return this.children.find((child) => child.tagName === 'INPUT' || child.tagName === 'TEXTAREA') || null;
              }}
              return null;
            }},
            __listeners: listeners,
          }};
          return el;
        }}

        [
          ['div', 'quick-phrases-container'],
          ['div', 'quick-phrases-list'],
          ['div', 'quick-phrases-form-host'],
          ['button', 'quick-phrases-add-btn'],
          ['button', 'quick-phrases-export-btn'],
          ['button', 'quick-phrases-import-btn'],
          ['input', 'quick-phrases-import-file'],
          ['textarea', 'feedback-text'],
        ].forEach(([tag, id]) => {{
          elements[id] = createElement(tag, id);
        }});

        const sandbox = {{
          Array,
          Date: {{ now: () => 1700000000000 }},
          JSON,
          Math,
          Number,
          Object,
          String,
          isFinite,
          alert(message) {{
            alerts.push(String(message));
          }},
          console: {{
            debug() {{}},
            error() {{}},
            info() {{}},
            log() {{}},
            warn() {{}},
          }},
          document: {{
            body: createElement('body', 'body'),
            readyState: 'loading',
            addEventListener(type, handler) {{
              pushListener(documentListeners, type, handler);
            }},
            createElement(tagName) {{
              return createElement(tagName);
            }},
            getElementById(id) {{
              return elements[id] || null;
            }},
          }},
          localStorage: {{
            getItem(key) {{
              return storage.has(key) ? storage.get(key) : null;
            }},
            setItem(key, value) {{
              storage.set(key, String(value));
            }},
            removeItem(key) {{
              storage.delete(key);
            }},
          }},
          setTimeout(fn) {{
            fn();
            return 1;
          }},
          __alerts: alerts,
          __documentListeners: documentListeners,
          __elements: elements,
          __storage: storage,
        }};
        sandbox.window = sandbox;
        sandbox.globalThis = sandbox;

        vm.createContext(sandbox);
        vm.runInContext(code, sandbox);

        (async () => {{
        {textwrap.indent(case_js, "  ")}
        }})().catch((err) => {{
          console.error(err && err.stack ? err.stack : err);
          process.exit(1);
        }});
        """
    )


@unittest.skipUnless(_node_available(), "node runtime unavailable")
def test_import_resets_file_input_when_filereader_is_unavailable() -> None:
    script = _quick_phrases_import_harness(
        """
        const api = sandbox.AIIA_QUICK_PHRASES;
        const input = sandbox.__elements['quick-phrases-import-file'];
        input.value = '/fake/quick-replies.json';
        input.files = [{ name: 'quick-replies.json' }];
        sandbox.FileReader = undefined;

        api.init();
        input.dispatch('change');

        process.stdout.write(JSON.stringify({
          value: input.value,
          alerts: sandbox.__alerts,
        }));
        """
    )

    assert json.loads(_run_node(script)) == {
        "value": "",
        "alerts": ["Could not read selected file. Please try again."],
    }


@unittest.skipUnless(_node_available(), "node runtime unavailable")
def test_import_resets_file_input_when_read_as_text_throws() -> None:
    script = _quick_phrases_import_harness(
        """
        const api = sandbox.AIIA_QUICK_PHRASES;
        const input = sandbox.__elements['quick-phrases-import-file'];
        input.value = '/fake/quick-replies.json';
        input.files = [{ name: 'quick-replies.json' }];
        sandbox.FileReader = function FileReader() {
          this.readAsText = function readAsText() {
            throw new Error('read failed');
          };
        };

        api.init();
        let errorMessage = null;
        try {
          input.dispatch('change');
        } catch (err) {
          errorMessage = err && err.message;
        }

        process.stdout.write(JSON.stringify({
          errorMessage,
          value: input.value,
          alerts: sandbox.__alerts,
        }));
        """
    )

    assert json.loads(_run_node(script)) == {
        "errorMessage": None,
        "value": "",
        "alerts": ["Could not read selected file. Please try again."],
    }
