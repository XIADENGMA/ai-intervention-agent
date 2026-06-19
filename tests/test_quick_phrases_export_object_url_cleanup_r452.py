"""Runtime checks for Quick Phrases export object URL cleanup.

Export uses a Blob URL and a temporary anchor. If the synthetic download click
throws, the Blob URL must still be revoked and the temporary DOM node must be
removed; otherwise a failed export leaks browser-owned resources.
"""

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


def _quick_phrases_export_harness(case_js: str) -> str:
    return textwrap.dedent(
        f"""
        const fs = require('fs');
        const vm = require('vm');
        const code = fs.readFileSync({str(QUICK_PHRASES_JS)!r}, 'utf8');
        const HostDate = Date;

        class FixedDate extends HostDate {{
          constructor(...args) {{
            super(...(args.length ? args : ['2026-06-18T12:00:00.000Z']));
          }}

          static now() {{
            return 1781784000000;
          }}
        }}

        const createdUrls = [];
        const revokedUrls = [];
        const storage = new Map();
        const timeouts = [];
        function URLCtor() {{}}
        URLCtor.createObjectURL = function createObjectURL() {{
          const url = `blob:quick-phrases-${{createdUrls.length + 1}}`;
          createdUrls.push(url);
          return url;
        }};
        URLCtor.revokeObjectURL = function revokeObjectURL(url) {{
          revokedUrls.push(url);
        }};

        function createElement(tagName) {{
          const el = {{
            tagName: String(tagName || 'div').toUpperCase(),
            children: [],
            dataset: {{}},
            href: '',
            download: '',
            parentNode: null,
            setAttribute() {{}},
            addEventListener() {{}},
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
            click() {{
              if (this.__throwOnClick) throw new Error('download click failed');
            }},
          }};
          if (el.tagName === 'A') el.__throwOnClick = true;
          return el;
        }}

        const body = createElement('body');
        const documentListeners = {{}};

        const sandbox = {{
          Date: FixedDate,
          JSON,
          Math,
          Number,
          Object,
          String,
          console: {{
            debug() {{}},
            error() {{}},
            info() {{}},
            log() {{}},
            warn() {{}},
          }},
          document: {{
            body,
            readyState: 'loading',
            addEventListener(type, handler) {{
              documentListeners[type] = documentListeners[type] || [];
              documentListeners[type].push(handler);
            }},
            createElement,
            getElementById() {{
              return null;
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
          Blob: function Blob(parts, options) {{
            this.parts = parts;
            this.options = options;
          }},
          URL: URLCtor,
          setTimeout(fn, delay) {{
            timeouts.push({{ fn, delay }});
            fn();
            return `timeout-${{timeouts.length}}`;
          }},
          __body: body,
          __createdUrls: createdUrls,
          __documentListeners: documentListeners,
          __revokedUrls: revokedUrls,
          __storage: storage,
          __timeouts: timeouts,
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
def test_export_releases_blob_url_and_anchor_when_download_click_throws() -> None:
    script = _quick_phrases_export_harness(
        """
        const api = sandbox.AIIA_QUICK_PHRASES;
        let errorMessage = null;
        try {
          api.downloadPhrasesAsFile();
        } catch (err) {
          errorMessage = err && err.message;
        }

        process.stdout.write(JSON.stringify({
          errorMessage,
          bodyChildren: sandbox.__body.children.length,
          createdUrls: sandbox.__createdUrls,
          revokedUrls: sandbox.__revokedUrls,
          revokeDelay: sandbox.__timeouts[0] && sandbox.__timeouts[0].delay,
        }));
        """
    )

    assert json.loads(_run_node(script)) == {
        "errorMessage": "download click failed",
        "bodyChildren": 0,
        "createdUrls": ["blob:quick-phrases-1"],
        "revokedUrls": ["blob:quick-phrases-1"],
        "revokeDelay": 100,
    }


@unittest.skipUnless(_node_available(), "node runtime unavailable")
def test_export_fallback_removes_anchor_when_download_click_throws() -> None:
    script = _quick_phrases_export_harness(
        """
        sandbox.Blob = undefined;
        const api = sandbox.AIIA_QUICK_PHRASES;
        let errorMessage = null;
        try {
          api.downloadPhrasesAsFile();
        } catch (err) {
          errorMessage = err && err.message;
        }

        process.stdout.write(JSON.stringify({
          errorMessage,
          bodyChildren: sandbox.__body.children.length,
          createdUrls: sandbox.__createdUrls,
          revokedUrls: sandbox.__revokedUrls,
          scheduledRevokeTimers: sandbox.__timeouts.length,
        }));
        """
    )

    assert json.loads(_run_node(script)) == {
        "errorMessage": "download click failed",
        "bodyChildren": 0,
        "createdUrls": [],
        "revokedUrls": [],
        "scheduledRevokeTimers": 0,
    }
