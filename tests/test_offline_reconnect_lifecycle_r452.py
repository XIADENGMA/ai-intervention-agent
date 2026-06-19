"""Runtime checks for the offline fallback reconnect loop.

The offline page is intentionally self-contained, so these tests execute its
inline script in a small VM instead of relying only on source-level invariants.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import textwrap
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
OFFLINE_HTML = (
    REPO_ROOT / "src" / "ai_intervention_agent" / "templates" / "offline.html"
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


def _offline_script() -> str:
    html = OFFLINE_HTML.read_text(encoding="utf-8")
    match = re.search(
        r'<script\s+nonce="\{\{\s*csp_nonce\s*\}\}">\s*(.*?)\s*</script>',
        html,
        re.DOTALL,
    )
    assert match is not None, "offline.html inline script with CSP nonce not found"
    return match.group(1)


def _offline_harness(case_js: str) -> str:
    return textwrap.dedent(
        f"""
        const vm = require('vm');
        const code = {json.dumps(_offline_script())};

        function createSandbox() {{
          let nextTimerId = 1;
          const timers = new Map();
          const clearedTimers = [];
          const documentListeners = {{}};
          const windowListeners = {{}};
          const buttonListeners = {{}};

          function pushListener(bucket, type, handler) {{
            if (!bucket[type]) bucket[type] = [];
            bucket[type].push(handler);
          }}

          function activeTimers() {{
            return Array.from(timers.values())
              .filter((timer) => !timer.cleared)
              .map((timer) => ({{ id: timer.id, delay: timer.delay }}));
          }}

          function setTimeoutFake(handler, delay) {{
            const id = nextTimerId++;
            timers.set(id, {{
              id,
              handler,
              delay,
              cleared: false,
            }});
            return id;
          }}

          function clearTimeoutFake(id) {{
            const timer = timers.get(id);
            if (timer && !timer.cleared) {{
              timer.cleared = true;
              clearedTimers.push(id);
            }}
          }}

          function fireTimer(id) {{
            const timer = timers.get(id);
            if (!timer || timer.cleared) return false;
            timers.delete(id);
            timer.handler();
            return true;
          }}

          function fireNextTimerByDelay(delay) {{
            const timer = activeTimers().find((candidate) => candidate.delay === delay);
            if (!timer) return false;
            return fireTimer(timer.id);
          }}

          async function flushMicrotasks() {{
            for (let i = 0; i < 8; i += 1) {{
              await Promise.resolve();
            }}
          }}

          const status = {{
            textContent: '',
            classes: new Set(),
            classList: {{
              toggle(name, enabled) {{
                if (enabled) {{
                  status.classes.add(name);
                }} else {{
                  status.classes.delete(name);
                }}
              }},
            }},
          }};

          const button = {{
            addEventListener(type, handler) {{
              pushListener(buttonListeners, type, handler);
            }},
          }};

          const document = {{
            hidden: false,
            visibilityState: 'visible',
            addEventListener(type, handler) {{
              pushListener(documentListeners, type, handler);
            }},
            getElementById(id) {{
              if (id === 'retry-btn') return button;
              if (id === 'status') return status;
              return null;
            }},
          }};

          const state = {{
            aborts: 0,
            fetchMode: 'fail',
            fetchCalls: 0,
            reloads: 0,
          }};

          function fetchStub(_url, options = {{}}) {{
            state.fetchCalls += 1;
            if (state.fetchMode === 'success') {{
              return Promise.resolve({{ ok: true }});
            }}
            if (state.fetchMode === 'pending') {{
              return new Promise((_resolve, reject) => {{
                if (options.signal) {{
                  options.signal.addEventListener(
                    'abort',
                    () => {{
                      state.aborts += 1;
                      reject(new Error('aborted'));
                    }},
                    {{ once: true }},
                  );
                }}
              }});
            }}
            return Promise.reject(new Error('offline'));
          }}

          const windowObject = {{
            addEventListener(type, handler) {{
              pushListener(windowListeners, type, handler);
            }},
            location: {{
              reload() {{
                state.reloads += 1;
              }},
            }},
          }};

          const sandbox = {{
            AbortController,
            Error,
            Map,
            Promise,
            Set,
            console: {{
              debug() {{}},
              error() {{}},
              info() {{}},
              log() {{}},
              warn() {{}},
            }},
            document,
            fetch: fetchStub,
            setTimeout: setTimeoutFake,
            clearTimeout: clearTimeoutFake,
            window: windowObject,
            __activeTimers: activeTimers,
            __buttonListeners: buttonListeners,
            __clearedTimers: clearedTimers,
            __document: document,
            __documentListeners: documentListeners,
            __fireNextTimerByDelay: fireNextTimerByDelay,
            __fireTimer: fireTimer,
            __flushMicrotasks: flushMicrotasks,
            __state: state,
            __status: status,
            __windowListeners: windowListeners,
          }};
          return sandbox;
        }}

        (async () => {{
          const sandbox = createSandbox();
          vm.createContext(sandbox);
          vm.runInContext(code, sandbox);
          {case_js}
        }})().catch((error) => {{
          console.error(error && error.stack ? error.stack : error);
          process.exit(1);
        }});
        """
    )


@unittest.skipUnless(_node_available(), "node runtime unavailable")
def test_hidden_tabs_pause_and_visible_tabs_resume_offline_reconnect_polling() -> None:
    script = _offline_harness(
        """
        const initial = sandbox.__activeTimers();
        sandbox.__document.hidden = true;
        sandbox.__document.visibilityState = 'hidden';
        sandbox.__documentListeners.visibilitychange[0]();
        const hidden = sandbox.__activeTimers();

        sandbox.__document.hidden = false;
        sandbox.__document.visibilityState = 'visible';
        sandbox.__documentListeners.visibilitychange[0]();
        const visible = sandbox.__activeTimers();

        process.stdout.write(JSON.stringify({
          initial,
          hidden,
          clearedCount: sandbox.__clearedTimers.length,
          visible,
          listenerCounts: {
            visibilitychange: sandbox.__documentListeners.visibilitychange.length,
            pagehide: sandbox.__windowListeners.pagehide.length,
            pageshow: sandbox.__windowListeners.pageshow.length,
            beforeunload: (sandbox.__windowListeners.beforeunload || []).length,
            unload: (sandbox.__windowListeners.unload || []).length,
          },
        }));
        """
    )

    assert json.loads(_run_node(script)) == {
        "initial": [{"id": 1, "delay": 5000}],
        "hidden": [],
        "clearedCount": 1,
        "visible": [{"id": 2, "delay": 0}],
        "listenerCounts": {
            "visibilitychange": 1,
            "pagehide": 1,
            "pageshow": 1,
            "beforeunload": 0,
            "unload": 0,
        },
    }


@unittest.skipUnless(_node_available(), "node runtime unavailable")
def test_pagehide_aborts_in_flight_ping_and_prevents_stale_reschedule() -> None:
    script = _offline_harness(
        """
        sandbox.__state.fetchMode = 'pending';
        sandbox.__fireNextTimerByDelay(5000);
        await sandbox.__flushMicrotasks();

        sandbox.__document.hidden = true;
        sandbox.__document.visibilityState = 'hidden';
        sandbox.__windowListeners.pagehide[0]({ persisted: true });
        await sandbox.__flushMicrotasks();

        process.stdout.write(JSON.stringify({
          fetchCalls: sandbox.__state.fetchCalls,
          aborts: sandbox.__state.aborts,
          activeTimers: sandbox.__activeTimers(),
          reloads: sandbox.__state.reloads,
        }));
        """
    )

    assert json.loads(_run_node(script)) == {
        "fetchCalls": 1,
        "aborts": 1,
        "activeTimers": [],
        "reloads": 0,
    }


@unittest.skipUnless(_node_available(), "node runtime unavailable")
def test_online_event_pings_before_reload_and_pagehide_clears_reload_timer() -> None:
    script = _offline_harness(
        """
        sandbox.__state.fetchMode = 'success';
        sandbox.__windowListeners.online[0]();
        const afterOnline = {
          timers: sandbox.__activeTimers(),
          reloads: sandbox.__state.reloads,
          status: sandbox.__status.textContent,
        };

        sandbox.__fireNextTimerByDelay(0);
        await sandbox.__flushMicrotasks();
        const afterPing = {
          timers: sandbox.__activeTimers(),
          fetchCalls: sandbox.__state.fetchCalls,
          reloads: sandbox.__state.reloads,
          status: sandbox.__status.textContent,
        };

        sandbox.__windowListeners.pagehide[0]({ persisted: true });
        const afterPagehide = {
          timers: sandbox.__activeTimers(),
          reloads: sandbox.__state.reloads,
        };
        sandbox.__fireNextTimerByDelay(600);
        await sandbox.__flushMicrotasks();

        process.stdout.write(JSON.stringify({
          afterOnline,
          afterPing,
          afterPagehide,
          finalReloads: sandbox.__state.reloads,
        }));
        """
    )

    assert json.loads(_run_node(script)) == {
        "afterOnline": {
            "timers": [{"id": 2, "delay": 0}],
            "reloads": 0,
            "status": "网络已连接，重试中… / Online, retrying…",
        },
        "afterPing": {
            "timers": [{"id": 4, "delay": 600}],
            "fetchCalls": 1,
            "reloads": 0,
            "status": "服务已恢复，正在重新加载… / Service back, reloading…",
        },
        "afterPagehide": {
            "timers": [],
            "reloads": 0,
        },
        "finalReloads": 0,
    }
