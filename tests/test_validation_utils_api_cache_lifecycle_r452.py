"""Runtime checks for ``validation-utils.js`` APICache cleanup lifecycle.

The Web UI already treats long-lived timers as lifecycle-owned resources. This
suite applies the same contract to ``APICache``: the cleanup timer should exist
only while there are entries to clean, should be idempotent, and should stop on
hidden/pagehide lifecycle edges.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import textwrap
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
VALIDATION_UTILS_JS = (
    REPO_ROOT
    / "src"
    / "ai_intervention_agent"
    / "static"
    / "js"
    / "validation-utils.js"
)


def _read_source() -> str:
    return VALIDATION_UTILS_JS.read_text(encoding="utf-8")


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


def _validation_utils_harness(case_js: str) -> str:
    return textwrap.dedent(
        f"""
        const fs = require('fs');
        const vm = require('vm');
        const code = fs.readFileSync({str(VALIDATION_UTILS_JS)!r}, 'utf8');

        const intervals = [];
        const clearedIntervals = [];
        const documentListeners = {{}};
        const windowListeners = {{}};
        let now = 1700000000000;

        function pushListener(bucket, type, handler) {{
          if (!bucket[type]) bucket[type] = [];
          bucket[type].push(handler);
        }}

        const sandbox = {{
          Date: {{ now: () => now }},
          JSON,
          Map,
          Math,
          Number,
          Object,
          Promise,
          RegExp,
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
            addEventListener(type, handler) {{
              pushListener(documentListeners, type, handler);
            }},
            createElement() {{
              return {{ style: {{}}, appendChild() {{}}, addEventListener() {{}} }};
            }},
            querySelector() {{
              return null;
            }},
            querySelectorAll() {{
              return [];
            }},
          }},
          setInterval(fn, delay) {{
            const id = `interval-${{intervals.length + 1}}`;
            intervals.push({{ id, fn, delay }});
            return id;
          }},
          clearInterval(id) {{
            clearedIntervals.push(id);
          }},
          addEventListener(type, handler) {{
            pushListener(windowListeners, type, handler);
          }},
          module: {{ exports: {{}} }},
          exports: {{}},
          __clearedIntervals: clearedIntervals,
          __documentListeners: documentListeners,
          __intervals: intervals,
          __windowListeners: windowListeners,
          __setNow(value) {{
            now = value;
          }},
        }};
        sandbox.window = sandbox;
        sandbox.globalThis = sandbox;

        vm.createContext(sandbox);
        vm.runInContext(code, sandbox);
        const exported = sandbox.module.exports;

        (async () => {{
        {textwrap.indent(case_js, "  ")}
        }})().catch((err) => {{
          console.error(err && err.stack ? err.stack : err);
          process.exit(1);
        }});
        """
    )


class TestApiCacheCleanupSourceContract(unittest.TestCase):
    def setUp(self) -> None:
        self.src = _read_source()

    def test_no_module_load_bare_cleanup_interval(self) -> None:
        stripped = re.sub(r"/\*[\s\S]*?\*/", "", self.src)
        self.assertNotRegex(
            stripped,
            r"setInterval\(\s*\(\s*\)\s*=>\s*\{?\s*apiCache\.cleanup\(",
            "APICache cleanup 不应在模块加载时创建裸 interval",
        )

    def test_cleanup_timer_id_is_saved_and_clearable(self) -> None:
        self.assertIn("_cleanupTimerId", self.src)
        self.assertRegex(
            self.src,
            r"stopCleanupTimer[\s\S]*?clearInterval\(this\._cleanupTimerId\)"
            r"[\s\S]*?this\._cleanupTimerId\s*=\s*null",
        )

    def test_visibility_and_pagehide_lifecycle_hooks_present(self) -> None:
        self.assertIn(
            'document.addEventListener("visibilitychange", syncTimerWithVisibility)',
            self.src,
        )
        self.assertIn('window.addEventListener("pagehide"', self.src)
        self.assertIn(
            'window.addEventListener("pageshow", syncTimerWithVisibility)',
            self.src,
        )
        self.assertIn("setupApiCacheLifecycle(apiCache)", self.src)


@unittest.skipUnless(_node_available(), "node runtime unavailable")
def test_module_load_installs_lifecycle_but_does_not_start_interval() -> None:
    script = _validation_utils_harness(
        """
        process.stdout.write(
          JSON.stringify({
            intervals: sandbox.__intervals.length,
            visibilityListeners:
              (sandbox.__documentListeners.visibilitychange || []).length,
            pagehideListeners: (sandbox.__windowListeners.pagehide || []).length,
            pageshowListeners: (sandbox.__windowListeners.pageshow || []).length,
          })
        );
        """
    )

    assert _run_node(script) == (
        '{"intervals":0,"visibilityListeners":1,'
        '"pagehideListeners":1,"pageshowListeners":1}'
    )


@unittest.skipUnless(_node_available(), "node runtime unavailable")
def test_cache_set_starts_one_cleanup_timer_and_clear_stops_it() -> None:
    script = _validation_utils_harness(
        """
        const cache = new exported.APICache(30, 5000);
        cache.set('a', 1);
        cache.set('b', 2);
        cache.clear();
        process.stdout.write(
          JSON.stringify({
            intervals: sandbox.__intervals.map((entry) => entry.id),
            delays: sandbox.__intervals.map((entry) => entry.delay),
            clearedIntervals: sandbox.__clearedIntervals,
            timerId: cache._cleanupTimerId,
          })
        );
        """
    )

    assert _run_node(script) == (
        '{"intervals":["interval-1"],"delays":[5000],'
        '"clearedIntervals":["interval-1"],"timerId":null}'
    )


@unittest.skipUnless(_node_available(), "node runtime unavailable")
def test_expired_last_entry_stops_cleanup_timer_on_get() -> None:
    script = _validation_utils_harness(
        """
        const cache = new exported.APICache(10, 5000);
        cache.set('a', 1);
        sandbox.__setNow(1700000000020);
        const value = cache.get('a');
        process.stdout.write(
          JSON.stringify({
            value,
            size: cache.size,
            clearedIntervals: sandbox.__clearedIntervals,
            timerId: cache._cleanupTimerId,
          })
        );
        """
    )

    assert _run_node(script) == (
        '{"value":null,"size":0,"clearedIntervals":["interval-1"],"timerId":null}'
    )


@unittest.skipUnless(_node_available(), "node runtime unavailable")
def test_fetch_with_cache_reuses_json_null_response() -> None:
    script = _validation_utils_harness(
        """
        let fetchCalls = 0;
        sandbox.fetch = async () => {
          fetchCalls += 1;
          return {
            ok: true,
            headers: {
              get(name) {
                return name.toLowerCase() === 'content-type'
                  ? 'application/json'
                  : '';
              },
            },
            async json() {
              return null;
            },
          };
        };

        const cache = new exported.APICache(1000, 5000);
        const first = await cache.fetchWithCache('/api/maybe-empty');
        const second = await cache.fetchWithCache('/api/maybe-empty');
        process.stdout.write(
          JSON.stringify({
            first,
            second,
            fetchCalls,
            size: cache.size,
            storedValue: cache.cache.get('GET:/api/maybe-empty').value,
          })
        );
        """
    )

    assert _run_node(script) == (
        '{"first":null,"second":null,"fetchCalls":1,"size":1,"storedValue":null}'
    )


@unittest.skipUnless(_node_available(), "node runtime unavailable")
def test_hidden_document_defers_timer_until_visible_again() -> None:
    script = _validation_utils_harness(
        """
        const cache = new exported.APICache(30, 5000);
        exported.setupApiCacheLifecycle(cache);
        sandbox.document.hidden = true;
        cache.set('a', 1);
        sandbox.document.hidden = false;
        sandbox.__documentListeners.visibilitychange[1]();
        process.stdout.write(
          JSON.stringify({
            intervals: sandbox.__intervals.map((entry) => entry.id),
            clearedIntervals: sandbox.__clearedIntervals,
            size: cache.size,
          })
        );
        """
    )

    assert _run_node(script) == (
        '{"intervals":["interval-1"],"clearedIntervals":[],"size":1}'
    )


@unittest.skipUnless(_node_available(), "node runtime unavailable")
def test_pagehide_stops_global_api_cache_cleanup_timer() -> None:
    script = _validation_utils_harness(
        """
        exported.apiCache.set('GET:/api/tasks', { tasks: [] });
        sandbox.__windowListeners.pagehide[0]();
        process.stdout.write(
          JSON.stringify({
            intervals: sandbox.__intervals.map((entry) => entry.id),
            clearedIntervals: sandbox.__clearedIntervals,
            timerId: exported.apiCache._cleanupTimerId,
          })
        );
        """
    )

    assert _run_node(script) == (
        '{"intervals":["interval-1"],"clearedIntervals":["interval-1"],"timerId":null}'
    )


@unittest.skipUnless(_node_available(), "node runtime unavailable")
def test_pageshow_resumes_cleanup_timer_after_pagehide_when_visible() -> None:
    script = _validation_utils_harness(
        """
        exported.apiCache.set('GET:/api/tasks', { tasks: [] });
        sandbox.__windowListeners.pagehide[0]({ persisted: true });
        sandbox.__windowListeners.pageshow[0]({ persisted: true });
        process.stdout.write(
          JSON.stringify({
            intervals: sandbox.__intervals.map((entry) => entry.id),
            clearedIntervals: sandbox.__clearedIntervals,
            timerId: exported.apiCache._cleanupTimerId,
            size: exported.apiCache.size,
          })
        );
        """
    )

    assert _run_node(script) == (
        '{"intervals":["interval-1","interval-2"],'
        '"clearedIntervals":["interval-1"],"timerId":"interval-2","size":1}'
    )


@unittest.skipUnless(_node_available(), "node runtime unavailable")
def test_pageshow_keeps_cleanup_timer_stopped_when_document_remains_hidden() -> None:
    script = _validation_utils_harness(
        """
        exported.apiCache.set('GET:/api/tasks', { tasks: [] });
        sandbox.__windowListeners.pagehide[0]({ persisted: true });
        sandbox.document.hidden = true;
        sandbox.__windowListeners.pageshow[0]({ persisted: true });
        process.stdout.write(
          JSON.stringify({
            intervals: sandbox.__intervals.map((entry) => entry.id),
            clearedIntervals: sandbox.__clearedIntervals,
            timerId: exported.apiCache._cleanupTimerId,
            size: exported.apiCache.size,
          })
        );
        """
    )

    assert _run_node(script) == (
        '{"intervals":["interval-1"],'
        '"clearedIntervals":["interval-1"],"timerId":null,"size":1}'
    )
