"""R560 regression coverage for one-pass Lottie fallback SVG removal."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
APP_JS = REPO_ROOT / "src" / "ai_intervention_agent" / "static" / "js" / "app.js"


def _source() -> str:
    return APP_JS.read_text(encoding="utf-8")


def _function_body(source: str, name: str) -> str:
    match = re.search(rf"function\s+{name}\s*\([^)]*\)\s*\{{", source)
    assert match is not None, f"Missing function {name}"
    depth = 0
    for idx in range(match.end() - 1, len(source)):
        char = source[idx]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return source[match.end() : idx]
    raise AssertionError(f"Could not parse body for {name}")


def _run_node(case_js: str) -> str:
    script = textwrap.dedent(
        f"""
        const fs = require('fs');
        const vm = require('vm');
        const code = fs.readFileSync({str(APP_JS)!r}, 'utf8');

        const documentListeners = {{}};
        const idleCallbacks = [];
        const observers = [];
        const timers = [];
        const windowListeners = {{}};
        const svgNodes = [
          {{ removed: false, remove() {{ this.removed = true; }} }},
          {{ removed: false, remove() {{ this.removed = true; }} }},
        ];
        let loadAnimationCalls = 0;
        let querySelectorAllCalls = 0;
        let lastAnimation = null;

        function addListener(store, type, handler) {{
          if (!store[type]) store[type] = [];
          store[type].push(handler);
        }}

        function removeListener(store, type, handler) {{
          if (!store[type]) return;
          store[type] = store[type].filter(item => item !== handler);
        }}

        const container = {{
          id: 'hourglass-lottie',
          isConnected: true,
          innerHTML: '',
          textContent: '',
          style: {{}},
          querySelectorAll(selector) {{
            querySelectorAllCalls += 1;
            if (selector !== 'svg' || !this.innerHTML.includes('<svg')) {{
              return {{ length: 0 }};
            }}
            return {{
              0: svgNodes[0],
              1: svgNodes[1],
              length: svgNodes.length,
            }};
          }},
        }};

        class FakeIntersectionObserver {{
          constructor(callback) {{
            this.callback = callback;
            this.disconnected = false;
            this.observed = [];
            observers.push(this);
          }}
          observe(target) {{ this.observed.push(target); }}
          disconnect() {{ this.disconnected = true; }}
          fire(entries) {{ this.callback(entries); }}
        }}

        const sandbox = {{
          AbortController: function AbortController() {{
            this.signal = {{
              addEventListener() {{}},
              removeEventListener() {{}},
            }};
            this.abort = function abort() {{}};
          }},
          AbortSignal: {{}},
          Array,
          Boolean,
          Date,
          JSON,
          Math,
          Number,
          Object,
          Promise,
          Set,
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
            hidden: false,
            readyState: 'loading',
            documentElement: {{
              getAttribute() {{ return 'light'; }},
            }},
            body: {{
              contains(node) {{ return node === container; }},
            }},
            head: {{
              appendChild(script) {{
                if (typeof script.onload === 'function') script.onload();
              }},
            }},
            createElement(tag) {{ return {{ tagName: tag, style: {{}} }}; }},
            getElementById(id) {{ return id === 'hourglass-lottie' ? container : null; }},
            addEventListener(type, handler) {{ addListener(documentListeners, type, handler); }},
            removeEventListener(type, handler) {{ removeListener(documentListeners, type, handler); }},
          }},
          location: {{
            href: 'http://127.0.0.1:8080/',
            replace(value) {{ this.href = String(value); }},
          }},
          addEventListener(type, handler) {{ addListener(windowListeners, type, handler); }},
          removeEventListener(type, handler) {{ removeListener(windowListeners, type, handler); }},
          matchMedia() {{ return {{ matches: false }}; }},
          setTimeout(fn, delay) {{
            const timer = {{ fn, delay, cleared: false }};
            timers.push(timer);
            return timer;
          }},
          clearTimeout(timer) {{
            if (timer) timer.cleared = true;
          }},
          requestIdleCallback(fn) {{
            const idle = {{ fn, cancelled: false }};
            idleCallbacks.push(idle);
            return idle;
          }},
          cancelIdleCallback(idle) {{
            if (idle) idle.cancelled = true;
          }},
          requestAnimationFrame(fn) {{ fn(); }},
          IntersectionObserver: FakeIntersectionObserver,
          lottie: {{
            loadAnimation() {{
              loadAnimationCalls += 1;
              const handlers = {{}};
              lastAnimation = {{
                addEventListener(type, handler) {{
                  if (!handlers[type]) handlers[type] = [];
                  handlers[type].push(handler);
                }},
                destroy() {{}},
                fire(type) {{
                  for (const handler of handlers[type] || []) handler();
                }},
              }};
              return lastAnimation;
            }},
          }},
          fetch() {{
            return Promise.resolve({{ ok: true, json: async () => ({{}}) }});
          }},
          selectedImages: [],
          clearAllImages() {{}},
          initializeImageFeatures() {{}},
          startPeriodicCleanup() {{}},
          initMultiTaskSupport() {{}},
          settingsManager: {{ init: async () => undefined, applySettings() {{}} }},
          notificationManager: {{ init: async () => undefined, sendNotification: async () => undefined }},
          __container: container,
          __documentListeners: documentListeners,
          __idleCallbacks: idleCallbacks,
          __observers: observers,
          __svgNodes: svgNodes,
          __timers: timers,
          __windowListeners: windowListeners,
          __stats() {{
            return {{
              loadAnimationCalls,
              querySelectorAllCalls,
              removed: svgNodes.map(node => node.removed),
              opacity: container.style.opacity || '',
              transition: container.style.transition || '',
            }};
          }},
          __fireLottie(type) {{
            if (!lastAnimation) throw new Error('missing animation');
            lastAnimation.fire(type);
          }},
        }};
        sandbox.window = sandbox;
        sandbox.globalThis = sandbox;

        vm.createContext(sandbox);
        vm.runInContext(code, sandbox);
        sandbox.document.readyState = 'complete';

        (async () => {{
        {textwrap.indent(case_js, "  ")}
        }})().catch((err) => {{
          console.error(err && err.stack ? err.stack : err);
          process.exit(1);
        }});
        """
    )
    proc = subprocess.run(
        ["node", "-e", script],
        check=False,
        capture_output=True,
        text=True,
        timeout=20,
    )
    if proc.returncode != 0:
        raise AssertionError(
            f"node exited {proc.returncode}\nstdout={proc.stdout!r}\nstderr={proc.stderr!r}"
        )
    return proc.stdout


def test_lottie_fallback_svg_handoff_uses_nodelist_without_array_copy() -> None:
    body = _function_body(_source(), "initHourglassAnimation")

    assert 'Array.from(container.querySelectorAll("svg"))' not in body
    assert 'const fallbackSvgs = container.querySelectorAll("svg")' in body
    assert "const fallbackSvgCount = fallbackSvgs.length" in body
    assert "for (let i = 0; i < fallbackSvgCount; i += 1)" in body
    assert "_removeElement(fallbackSvgs[i])" in body
    assert ".forEach((s)" not in body


@pytest.mark.skipif(shutil.which("node") is None, reason="node runtime unavailable")
def test_lottie_fallback_removal_handles_indexed_nodelist_like_collection() -> None:
    script = """
        vm.runInContext('initHourglassAnimation()', sandbox);
        sandbox.__observers[0].fire([{ isIntersecting: true, intersectionRatio: 1 }]);
        const delayTimer = sandbox.__timers.find(timer => timer.delay === 500);
        delayTimer.fn();
        sandbox.__idleCallbacks[0].fn();
        await Promise.resolve();
        const beforeDomLoaded = sandbox.__stats();
        sandbox.__fireLottie('DOMLoaded');
        const afterDomLoaded = sandbox.__stats();
        process.stdout.write(JSON.stringify({ beforeDomLoaded, afterDomLoaded }));
    """

    assert json.loads(_run_node(script)) == {
        "beforeDomLoaded": {
            "loadAnimationCalls": 1,
            "querySelectorAllCalls": 1,
            "removed": [False, False],
            "opacity": "0",
            "transition": "opacity .25s ease",
        },
        "afterDomLoaded": {
            "loadAnimationCalls": 1,
            "querySelectorAllCalls": 1,
            "removed": [True, True],
            "opacity": "1",
            "transition": "opacity .25s ease",
        },
    }
