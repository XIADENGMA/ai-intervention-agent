"""Runtime VM checks for ``notification-service-worker.js`` fetch behavior.

The existing SW tests intentionally lock many source-level invariants. This file
adds a thin runtime layer for the behavior that is easiest to regress while
refactoring: navigation requests must be network-first with an offline fallback,
SSE must fall through untouched, and static assets must stay cache-first without
turning network failures into rejected ``respondWith`` promises.
"""

from __future__ import annotations

import shutil
import subprocess
import textwrap
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SW_JS = (
    REPO_ROOT
    / "src"
    / "ai_intervention_agent"
    / "static"
    / "js"
    / "notification-service-worker.js"
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


def _service_worker_harness(case_js: str) -> str:
    return textwrap.dedent(
        f"""
        const fs = require('fs');
        const vm = require('vm');
        const code = fs.readFileSync({str(SW_JS)!r}, 'utf8');

        class MiniResponse {{
          constructor(body = '', init = {{}}) {{
            this.body = body;
            this.status = init.status ?? 200;
            this.statusText = init.statusText || '';
            this.ok = this.status >= 200 && this.status < 300;
            this.type = init.type || 'basic';
            this._headers = Object.assign({{}}, init.headers || {{}});
            this.headers = {{
              get: (name) => {{
                const wanted = String(name).toLowerCase();
                for (const [key, value] of Object.entries(this._headers)) {{
                  if (key.toLowerCase() === wanted) return value;
                }}
                return null;
              }},
            }};
          }}

          clone() {{
            return new MiniResponse(this.body, {{
              status: this.status,
              statusText: this.statusText,
              type: this.type,
              headers: this._headers,
            }});
          }}
        }}

        function makeHeaders(rawHeaders = {{}}) {{
          return {{
            get(name) {{
              const wanted = String(name).toLowerCase();
              for (const [key, value] of Object.entries(rawHeaders)) {{
                if (key.toLowerCase() === wanted) return value;
              }}
              return null;
            }},
          }};
        }}

        function makeRequest(path, init = {{}}) {{
          const url = path.startsWith('http') ? path : `http://aiia.test${{path}}`;
          return {{
            url,
            method: init.method || 'GET',
            mode: init.mode || 'no-cors',
            headers: makeHeaders(init.headers || {{}}),
          }};
        }}

        function createSandbox() {{
          const listeners = {{}};
          const stores = {{}};
          const openedCaches = [];
          const putCalls = [];
          const deletedEntries = [];
          const deletedCaches = [];

          function ensureStore(name) {{
            if (!stores[name]) stores[name] = new Map();
            return stores[name];
          }}

          const caches = {{
            async open(name) {{
              openedCaches.push(name);
              const store = ensureStore(name);
              return {{
                async match(requestOrUrl) {{
                  const key =
                    typeof requestOrUrl === 'string' ? requestOrUrl : requestOrUrl.url;
                  return store.get(key) || null;
                }},
                async put(requestOrUrl, response) {{
                  const key =
                    typeof requestOrUrl === 'string' ? requestOrUrl : requestOrUrl.url;
                  putCalls.push({{ cache: name, key, status: response.status }});
                  store.set(key, response);
                }},
                async keys() {{
                  return Array.from(store.keys()).map((url) => ({{ url }}));
                }},
                async delete(requestOrUrl) {{
                  const key =
                    typeof requestOrUrl === 'string' ? requestOrUrl : requestOrUrl.url;
                  deletedEntries.push({{ cache: name, key }});
                  return store.delete(key);
                }},
              }};
            }},
            async keys() {{
              return Object.keys(stores);
            }},
            async delete(name) {{
              deletedCaches.push(name);
              delete stores[name];
              return true;
            }},
          }};

          const sandbox = {{
            Array,
            Boolean,
            Date,
            JSON,
            Map,
            Math,
            Number,
            Object,
            Promise,
            Response: MiniResponse,
            Set,
            String,
            URL,
            caches,
            clients: {{
              claim: async () => undefined,
              matchAll: async () => [],
              openWindow: async () => undefined,
            }},
            console: {{
              debug() {{}},
              error() {{}},
              info() {{}},
              log() {{}},
              warn() {{}},
            }},
            fetch: async () => {{
              throw new Error('fetch stub not configured');
            }},
            location: {{ origin: 'http://aiia.test' }},
            skipWaiting: async () => undefined,
            addEventListener(type, handler) {{
              if (!listeners[type]) listeners[type] = [];
              listeners[type].push(handler);
            }},
            __deletedCaches: deletedCaches,
            __deletedEntries: deletedEntries,
            __listeners: listeners,
            __openedCaches: openedCaches,
            __putCalls: putCalls,
            __stores: stores,
          }};
          sandbox.self = sandbox;
          return sandbox;
        }}

        const sandbox = createSandbox();
        vm.createContext(sandbox);
        vm.runInContext(code, sandbox);

        async function dispatchFetch(request) {{
          const handlers = sandbox.__listeners.fetch || [];
          if (handlers.length !== 1) {{
            throw new Error('expected one fetch handler, got ' + handlers.length);
          }}
          let respondPromise = null;
          handlers[0]({{
            request,
            respondWith(promise) {{
              respondPromise = Promise.resolve(promise);
            }},
          }});
          if (!respondPromise) return null;
          return await respondPromise;
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
def test_navigation_fetch_event_uses_offline_fallback_after_network_failure() -> None:
    script = _service_worker_harness(
        """
        sandbox.__stores['aiia-offline-v1'] = new Map([
          ['/offline.html', new MiniResponse('offline shell', { status: 200 })],
        ]);
        let networkCalls = 0;
        sandbox.fetch = async () => {
          networkCalls += 1;
          throw new Error('offline');
        };

        const response = await dispatchFetch(
          makeRequest('/tasks', { mode: 'navigate' })
        );
        if (!response) throw new Error('navigation request was not handled');
        if (response.body !== 'offline shell') {
          throw new Error('expected cached offline shell, got ' + response.body);
        }
        process.stdout.write(
          JSON.stringify({
            body: response.body,
            networkCalls,
            openedCaches: sandbox.__openedCaches,
          })
        );
        """
    )

    assert _run_node(script) == (
        '{"body":"offline shell","networkCalls":1,"openedCaches":["aiia-offline-v1"]}'
    )


@unittest.skipUnless(_node_available(), "node runtime unavailable")
def test_sse_fetch_event_falls_through_without_cache_or_network() -> None:
    script = _service_worker_harness(
        """
        let networkCalls = 0;
        sandbox.fetch = async () => {
          networkCalls += 1;
          return new MiniResponse('event stream', { status: 200 });
        };

        const response = await dispatchFetch(
          makeRequest('/api/events', {
            headers: { Accept: 'text/event-stream' },
          })
        );
        process.stdout.write(
          JSON.stringify({
            responded: response !== null,
            networkCalls,
            openedCaches: sandbox.__openedCaches,
          })
        );
        """
    )

    assert _run_node(script) == (
        '{"responded":false,"networkCalls":0,"openedCaches":[]}'
    )


@unittest.skipUnless(_node_available(), "node runtime unavailable")
def test_static_cache_first_hit_returns_cached_response_without_network() -> None:
    script = _service_worker_harness(
        """
        const request = makeRequest('/static/js/app.js?v=cached');
        sandbox.__stores['aiia-static-v1'] = new Map([
          [request.url, new MiniResponse('cached app js', { status: 200 })],
        ]);
        let networkCalls = 0;
        sandbox.fetch = async () => {
          networkCalls += 1;
          return new MiniResponse('network app js', { status: 200 });
        };

        const response = await dispatchFetch(request);
        if (!response) throw new Error('static request was not handled');
        process.stdout.write(
          JSON.stringify({
            body: response.body,
            networkCalls,
            openedCaches: sandbox.__openedCaches,
          })
        );
        """
    )

    assert _run_node(script) == (
        '{"body":"cached app js","networkCalls":0,"openedCaches":["aiia-static-v1"]}'
    )


@unittest.skipUnless(_node_available(), "node runtime unavailable")
def test_static_cache_first_miss_writes_successful_network_response() -> None:
    script = _service_worker_harness(
        """
        const request = makeRequest('/static/js/app.js?v=network');
        sandbox.fetch = async () =>
          new MiniResponse('network app js', { status: 200, type: 'basic' });

        const response = await dispatchFetch(request);
        if (!response) throw new Error('static request was not handled');
        if (response.body !== 'network app js') {
          throw new Error('expected network response, got ' + response.body);
        }
        await Promise.resolve();
        process.stdout.write(
          JSON.stringify({
            body: response.body,
            putCalls: sandbox.__putCalls,
          })
        );
        """
    )

    assert _run_node(script) == (
        '{"body":"network app js","putCalls":[{"cache":"aiia-static-v1",'
        '"key":"http://aiia.test/static/js/app.js?v=network","status":200}]}'
    )


@unittest.skipUnless(_node_available(), "node runtime unavailable")
def test_static_cache_first_network_failure_returns_503_response() -> None:
    script = _service_worker_harness(
        """
        sandbox.fetch = async () => {
          throw new Error('offline');
        };

        const response = await dispatchFetch(
          makeRequest('/static/js/app.js?v=missing')
        );
        if (!response) throw new Error('static request was not handled');
        process.stdout.write(
          JSON.stringify({
            status: response.status,
            offlineHeader: response.headers.get('X-AIIA-SW-Offline'),
          })
        );
        """
    )

    assert _run_node(script) == '{"status":503,"offlineHeader":"1"}'
