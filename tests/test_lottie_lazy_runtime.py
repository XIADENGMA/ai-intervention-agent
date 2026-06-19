"""Lottie runtime is non-critical and must stay lazily loaded."""

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
TEMPLATE = REPO_ROOT / "src" / "ai_intervention_agent" / "templates" / "web_ui.html"


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


def test_app_js_does_not_eagerly_load_lottie_runtime() -> None:
    source = APP_JS.read_text(encoding="utf-8")
    ensure_end = source.index("function _createLottieAnimation")
    top_level_slice = source[:ensure_end]

    assert "_ensureLottieLoaded();" not in top_level_slice, (
        "app.js must not eagerly request lottie.min.js during initial parse; "
        "initHourglassAnimation should load it only after visibility + idle gates"
    )


def test_lottie_runtime_load_is_visibility_idle_and_motion_gated() -> None:
    body = _function_body(APP_JS.read_text(encoding="utf-8"), "initHourglassAnimation")

    assert "renderSproutFallback(container)" in body
    assert "prefers-reduced-motion: reduce" in body
    assert "IntersectionObserver" in body
    assert "requestIdleCallback" in body
    assert "_ensureLottieLoaded().then" in body


def test_lottie_lifecycle_uses_pagehide_not_beforeunload() -> None:
    source = APP_JS.read_text(encoding="utf-8")
    assert 'window.addEventListener("pagehide"' in source
    assert 'window.addEventListener("pageshow"' in source
    assert 'document.addEventListener("visibilitychange"' in source
    assert 'window.addEventListener("beforeunload"' not in source
    assert "disposeHourglassAnimationLifecycle" in source
    assert "_disconnectHourglassObserver()" in source
    assert "destroyHourglassAnimation()" in source


def test_lottie_dynamic_script_url_is_versioned_from_template() -> None:
    app = APP_JS.read_text(encoding="utf-8")
    template = TEMPLATE.read_text(encoding="utf-8")

    assert "window.AIIA_LOTTIE_JS_URL" in app
    assert (
        'window.AIIA_LOTTIE_JS_URL = "/static/js/lottie.min.js?v={{ lottie_min_version }}";'
        in template
    )


def _lottie_lifecycle_harness(case_js: str) -> str:
    return textwrap.dedent(
        f"""
        const fs = require('fs');
        const vm = require('vm');
        const code = fs.readFileSync({str(APP_JS)!r}, 'utf8');

        const windowListeners = {{}};
        const documentListeners = {{}};
        const timers = [];
        const idleCallbacks = [];
        const observers = [];
        let loadAnimationCalls = 0;
        let destroyCalls = 0;

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
            return selector === 'svg' && this.innerHTML.includes('<svg')
              ? [{{ removed: false, remove() {{ this.removed = true; }} }}]
              : [];
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
              return {{
                addEventListener() {{}},
                destroy() {{ destroyCalls += 1; }},
              }};
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
          __timers: timers,
          __windowListeners: windowListeners,
          __getStats() {{
            return {{
              destroyCalls,
              loadAnimationCalls,
              observers: observers.map(observer => observer.disconnected),
              timers: timers.map(timer => timer.cleared),
              idleCallbacks: idleCallbacks.map(idle => idle.cancelled),
            }};
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


@pytest.mark.skipif(not _node_available(), reason="node runtime unavailable")
def test_pagehide_cancels_pending_lottie_lazy_load_before_promise_continues() -> None:
    script = _lottie_lifecycle_harness(
        """
        vm.runInContext('initHourglassAnimation()', sandbox);
        sandbox.__observers[0].fire([{ isIntersecting: true, intersectionRatio: 1 }]);
        const delayTimer = sandbox.__timers.find(timer => timer.delay === 500);
        delayTimer.fn();
        sandbox.__idleCallbacks[0].fn();
        sandbox.__windowListeners.pagehide[0]({ persisted: true });
        await Promise.resolve();
        process.stdout.write(JSON.stringify(sandbox.__getStats()));
        """
    )

    assert json.loads(_run_node(script)) == {
        "destroyCalls": 0,
        "loadAnimationCalls": 0,
        "observers": [True],
        "timers": [False],
        "idleCallbacks": [False],
    }


@pytest.mark.skipif(not _node_available(), reason="node runtime unavailable")
def test_pageshow_restores_lottie_lazy_load_after_bfcache_return() -> None:
    script = _lottie_lifecycle_harness(
        """
        vm.runInContext('initHourglassAnimation()', sandbox);
        sandbox.__windowListeners.pagehide[0]({ persisted: true });
        sandbox.__windowListeners.pageshow[0]({ persisted: true });
        sandbox.__observers[sandbox.__observers.length - 1]
          .fire([{ isIntersecting: true, intersectionRatio: 1 }]);
        const delayTimer = sandbox.__timers.find(timer => timer.delay === 500 && !timer.cleared);
        delayTimer.fn();
        sandbox.__idleCallbacks.find(idle => !idle.cancelled).fn();
        await Promise.resolve();
        process.stdout.write(JSON.stringify(sandbox.__getStats()));
        """
    )

    assert json.loads(_run_node(script))["loadAnimationCalls"] == 1
