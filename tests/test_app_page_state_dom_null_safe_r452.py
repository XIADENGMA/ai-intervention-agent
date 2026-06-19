"""Runtime checks for app.js page-state DOM safety."""

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
        timeout=20,
    )
    if proc.returncode != 0:
        raise AssertionError(
            f"node exited {proc.returncode}\nstdout={proc.stdout!r}\nstderr={proc.stderr!r}"
        )
    return proc.stdout


def _app_page_state_harness(case_js: str) -> str:
    return textwrap.dedent(
        f"""
        const fs = require('fs');
        const vm = require('vm');
        const code = fs.readFileSync({str(APP_JS)!r}, 'utf8');

        const elements = new Map();
        const warningMessages = [];

        function makeClassList() {{
          const values = new Set();
          return {{
            add(name) {{ values.add(name); }},
            remove(name) {{ values.delete(name); }},
            contains(name) {{ return values.has(name); }},
            toArray() {{ return Array.from(values).sort(); }},
          }};
        }}

        function createElement(id) {{
          return {{
            id,
            classList: makeClassList(),
            disabled: false,
            innerHTML: '',
            style: {{}},
            value: '',
            addEventListener() {{}},
            click() {{}},
          }};
        }}

        const bodyClassList = makeClassList();
        const sandbox = {{
          AbortController: function AbortController() {{
            this.signal = {{
              addEventListener() {{}},
              removeEventListener() {{}},
            }};
            this.abort = function abort() {{}};
          }},
          AbortSignal: {{}},
          JSON,
          Object,
          Promise,
          String,
          URL,
          console: {{
            debug() {{}},
            error() {{}},
            info() {{}},
            log() {{}},
            warn(...args) {{ warningMessages.push(args.join(' ')); }},
          }},
          document: {{
            readyState: 'loading',
            addEventListener() {{}},
            removeEventListener() {{}},
            body: {{
              classList: bodyClassList,
            }},
            getElementById(id) {{
              return elements.get(id) || null;
            }},
          }},
          location: {{
            href: 'http://127.0.0.1:8080/',
            replace(value) {{ this.href = String(value); }},
          }},
          addEventListener() {{}},
          fetch() {{
            return Promise.resolve({{
              ok: true,
              json: async () => ({{}}),
            }});
          }},
          setTimeout() {{ return 'timer'; }},
          clearTimeout() {{}},
          selectedImages: [],
          clearAllImages() {{}},
          initializeImageFeatures() {{}},
          startPeriodicCleanup() {{}},
          initMultiTaskSupport() {{}},
          settingsManager: {{
            init: async () => undefined,
            applySettings() {{}},
          }},
          notificationManager: {{
            init: async () => undefined,
            sendNotification: async () => undefined,
            audioContext: null,
          }},
          __bodyClassList: bodyClassList,
          __createElement: createElement,
          __elements: elements,
          __warningMessages: warningMessages,
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
def test_no_content_page_does_not_throw_when_state_containers_are_missing() -> None:
    script = _app_page_state_harness(
        """
        let threw = false;
        try {
          vm.runInContext('config = {}; showNoContentPage();', sandbox);
        } catch (_err) {
          threw = true;
        }
        process.stdout.write(JSON.stringify({
          threw,
          bodyClasses: sandbox.__bodyClassList.toArray(),
          warnings: sandbox.__warningMessages,
        }));
        """
    )

    assert json.loads(_run_node(script)) == {
        "threw": False,
        "bodyClasses": ["no-content-mode"],
        "warnings": [
            "Page state update skipped: #content-container not in DOM",
            "Page state update skipped: #no-content-container not in DOM",
            "Page state update skipped: #no-content-buttons not in DOM",
        ],
    }


@unittest.skipUnless(_node_available(), "node runtime unavailable")
def test_content_page_does_not_throw_when_state_containers_are_missing() -> None:
    script = _app_page_state_harness(
        """
        sandbox.__bodyClassList.add('no-content-mode');
        let threw = false;
        try {
          vm.runInContext('showContentPage();', sandbox);
        } catch (_err) {
          threw = true;
        }
        process.stdout.write(JSON.stringify({
          threw,
          bodyClasses: sandbox.__bodyClassList.toArray(),
          warnings: sandbox.__warningMessages,
        }));
        """
    )

    assert json.loads(_run_node(script)) == {
        "threw": False,
        "bodyClasses": [],
        "warnings": [
            "Page state update skipped: #content-container not in DOM",
            "Page state update skipped: #no-content-container not in DOM",
        ],
    }


@unittest.skipUnless(_node_available(), "node runtime unavailable")
def test_page_state_helpers_still_update_present_elements() -> None:
    script = _app_page_state_harness(
        """
        for (const id of [
          'content-container',
          'no-content-container',
          'no-content-buttons',
        ]) {
          sandbox.__elements.set(id, sandbox.__createElement(id));
        }
        vm.runInContext('config = {}; showNoContentPage();', sandbox);
        const noContentState = {
          content: sandbox.__elements.get('content-container').style.display,
          noContent: sandbox.__elements.get('no-content-container').style.display,
          buttons: sandbox.__elements.get('no-content-buttons').style.display,
          classes: sandbox.__bodyClassList.toArray(),
        };
        vm.runInContext('showContentPage();', sandbox);
        process.stdout.write(JSON.stringify({
          noContentState,
          contentState: {
            content: sandbox.__elements.get('content-container').style.display,
            noContent: sandbox.__elements.get('no-content-container').style.display,
            classes: sandbox.__bodyClassList.toArray(),
          },
          warnings: sandbox.__warningMessages,
        }));
        """
    )

    assert json.loads(_run_node(script)) == {
        "noContentState": {
            "content": "none",
            "noContent": "flex",
            "buttons": "block",
            "classes": ["no-content-mode"],
        },
        "contentState": {
            "content": "block",
            "noContent": "none",
            "classes": [],
        },
        "warnings": [],
    }
