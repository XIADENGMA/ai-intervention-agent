"""Runtime checks for ``image-upload.js`` object URL cleanup ownership.

Blob URLs pin browser-side resources until revoked. This suite locks the image
upload module to the same lifecycle pattern used by other frontend resources:
start cleanup work only when URLs exist, keep the timer id clearable, pause in
hidden documents, pause across bfcache restores, and release everything on
discarded page exits.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import textwrap
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
IMAGE_UPLOAD_JS = (
    REPO_ROOT / "src" / "ai_intervention_agent" / "static" / "js" / "image-upload.js"
)


def _read_source() -> str:
    return IMAGE_UPLOAD_JS.read_text(encoding="utf-8")


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


def _image_upload_harness(case_js: str) -> str:
    return textwrap.dedent(
        f"""
        const fs = require('fs');
        const vm = require('vm');
        const code = fs.readFileSync({str(IMAGE_UPLOAD_JS)!r}, 'utf8');

        const intervals = [];
        const clearedIntervals = [];
        const timeouts = [];
        const clearedTimeouts = [];
        const documentListeners = {{}};
        const windowListeners = {{}};
        const revokedUrls = [];
        let now = 1700000000000;
        let urlSeq = 0;

        function pushListener(bucket, type, handler) {{
          if (!bucket[type]) bucket[type] = [];
          bucket[type].push(handler);
        }}

        const sandbox = {{
          Array,
          Date: {{ now: () => now }},
          Error,
          JSON,
          Map,
          Math,
          Number,
          Object,
          Promise,
          RegExp,
          Set,
          String,
          WeakMap,
          console: {{
            debug() {{}},
            error() {{}},
            info() {{}},
            log() {{}},
            warn() {{}},
          }},
          document: {{
            activeElement: null,
            hidden: false,
            readyState: 'loading',
            addEventListener(type, handler) {{
              pushListener(documentListeners, type, handler);
            }},
            contains() {{
              return false;
            }},
            createDocumentFragment() {{
              return {{ appendChild() {{}} }};
            }},
            createElement() {{
              return {{
                classList: {{ add() {{}}, remove() {{}} }},
                dataset: {{}},
                getContext() {{ return {{}}; }},
                querySelector() {{ return null; }},
                setAttribute() {{}},
                removeAttribute() {{}},
                style: {{}},
              }};
            }},
            getElementById() {{
              return null;
            }},
            querySelector() {{
              return null;
            }},
          }},
          DOMSecurity: {{
            clearContent() {{}},
            createImagePreview() {{
              return {{ firstChild: null }};
            }},
            replaceContent() {{}},
          }},
          navigator: {{ clipboard: {{ read() {{}} }} }},
          performance: {{ now: () => now }},
          URL: {{
            createObjectURL() {{
              urlSeq += 1;
              return `blob:test-${{urlSeq}}`;
            }},
            revokeObjectURL(url) {{
              revokedUrls.push(url);
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
          requestAnimationFrame(fn) {{
            return fn();
          }},
          showStatus() {{}},
          t(key) {{
            return key;
          }},
          module: {{ exports: {{}} }},
          exports: {{}},
          __clearedIntervals: clearedIntervals,
          __clearedTimeouts: clearedTimeouts,
          __documentListeners: documentListeners,
          __intervals: intervals,
          __revokedUrls: revokedUrls,
          __timeouts: timeouts,
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


class TestImageUploadObjectURLSourceContract(unittest.TestCase):
    def setUp(self) -> None:
        self.src = _read_source()

    def test_periodic_cleanup_timer_id_is_saved_and_clearable(self) -> None:
        self.assertIn("objectURLCleanupIntervalId", self.src)
        self.assertRegex(
            self.src,
            r"objectURLCleanupIntervalId\s*=\s*setInterval\("
            r"[\s\S]*?OBJECT_URL_CLEANUP_INTERVAL_MS",
        )
        self.assertRegex(
            self.src,
            r"function stopPeriodicCleanup\(\) \{"
            r"[\s\S]*?clearInterval\(objectURLCleanupIntervalId\)"
            r"[\s\S]*?objectURLCleanupIntervalId\s*=\s*null",
        )

    def test_create_object_url_no_longer_creates_per_url_timeout(self) -> None:
        match = re.search(
            r"function createObjectURL\(file\) \{(?P<body>[\s\S]*?)\n\}",
            self.src,
        )
        self.assertIsNotNone(match)
        assert match is not None
        self.assertNotIn(
            "setTimeout(",
            match.group("body"),
            "createObjectURL 不应为每个 URL 创建无法取消的 timeout",
        )
        self.assertIn("startPeriodicCleanup();", match.group("body"))

    def test_visibility_lifecycle_hook_present(self) -> None:
        self.assertIn('"visibilitychange"', self.src)
        self.assertIn("syncObjectURLCleanupWithVisibility", self.src)
        self.assertIn(
            'window.addEventListener("pageshow", syncObjectURLCleanupWithVisibility)',
            self.src,
        )
        self.assertNotIn(
            'window.addEventListener("beforeunload"',
            self.src,
            "Object URL cleanup should not install a permanent beforeunload listener",
        )
        self.assertIn("setupObjectURLCleanupLifecycle();", self.src)


@unittest.skipUnless(_node_available(), "node runtime unavailable")
def test_module_load_installs_lifecycle_but_starts_no_interval() -> None:
    script = _image_upload_harness(
        """
        process.stdout.write(
          JSON.stringify({
            intervals: sandbox.__intervals.length,
            visibilityListeners:
              (sandbox.__documentListeners.visibilitychange || []).length,
            pagehideListeners: (sandbox.__windowListeners.pagehide || []).length,
            pageshowListeners: (sandbox.__windowListeners.pageshow || []).length,
            beforeunloadListeners:
              (sandbox.__windowListeners.beforeunload || []).length,
          })
        );
        """
    )

    assert _run_node(script) == (
        '{"intervals":0,"visibilityListeners":1,'
        '"pagehideListeners":1,"pageshowListeners":1,"beforeunloadListeners":0}'
    )


@unittest.skipUnless(_node_available(), "node runtime unavailable")
def test_create_object_url_starts_one_periodic_cleanup_timer() -> None:
    script = _image_upload_harness(
        """
        const first = exported.createObjectURL({ name: 'a.png' });
        const second = exported.createObjectURL({ name: 'b.png' });
        process.stdout.write(
          JSON.stringify({
            urls: [first, second],
            intervals: sandbox.__intervals.map((entry) => entry.id),
            delays: sandbox.__intervals.map((entry) => entry.delay),
            timeouts: sandbox.__timeouts.length,
            state: exported._getObjectURLLifecycleState(),
          })
        );
        """
    )

    assert _run_node(script) == (
        '{"urls":["blob:test-1","blob:test-2"],'
        '"intervals":["interval-1"],"delays":[300000],"timeouts":0,'
        '"state":{"size":2,"cleanupIntervalId":"interval-1",'
        '"lifecycleListenersInstalled":true,'
        '"trackedUrls":["blob:test-1","blob:test-2"],'
        '"creationTimes":[["blob:test-1",1700000000000],'
        '["blob:test-2",1700000000000]]}}'
    )


@unittest.skipUnless(_node_available(), "node runtime unavailable")
def test_revoke_last_object_url_stops_periodic_cleanup_timer() -> None:
    script = _image_upload_harness(
        """
        const url = exported.createObjectURL({ name: 'a.png' });
        exported.revokeObjectURL(url);
        process.stdout.write(
          JSON.stringify({
            revokedUrls: sandbox.__revokedUrls,
            clearedIntervals: sandbox.__clearedIntervals,
            state: exported._getObjectURLLifecycleState(),
          })
        );
        """
    )

    assert _run_node(script) == (
        '{"revokedUrls":["blob:test-1"],"clearedIntervals":["interval-1"],'
        '"state":{"size":0,"cleanupIntervalId":null,'
        '"lifecycleListenersInstalled":true,"trackedUrls":[],"creationTimes":[]}}'
    )


@unittest.skipUnless(_node_available(), "node runtime unavailable")
def test_expired_object_urls_are_revoked_and_stop_timer_when_empty() -> None:
    script = _image_upload_harness(
        """
        exported.createObjectURL({ name: 'a.png' });
        sandbox.__setNow(1700000000000 + exported.OBJECT_URL_MAX_AGE_MS + 1);
        const removed = exported.cleanupExpiredObjectURLs();
        process.stdout.write(
          JSON.stringify({
            removed,
            revokedUrls: sandbox.__revokedUrls,
            clearedIntervals: sandbox.__clearedIntervals,
            state: exported._getObjectURLLifecycleState(),
          })
        );
        """
    )

    assert _run_node(script) == (
        '{"removed":1,"revokedUrls":["blob:test-1"],'
        '"clearedIntervals":["interval-1"],'
        '"state":{"size":0,"cleanupIntervalId":null,'
        '"lifecycleListenersInstalled":true,"trackedUrls":[],"creationTimes":[]}}'
    )


@unittest.skipUnless(_node_available(), "node runtime unavailable")
def test_hidden_document_defers_cleanup_timer_until_visible() -> None:
    script = _image_upload_harness(
        """
        sandbox.document.hidden = true;
        exported.createObjectURL({ name: 'a.png' });
        sandbox.document.hidden = false;
        sandbox.__documentListeners.visibilitychange[0]();
        process.stdout.write(
          JSON.stringify({
            intervals: sandbox.__intervals.map((entry) => entry.id),
            clearedIntervals: sandbox.__clearedIntervals,
            state: exported._getObjectURLLifecycleState(),
          })
        );
        """
    )

    assert _run_node(script) == (
        '{"intervals":["interval-1"],"clearedIntervals":[],'
        '"state":{"size":1,"cleanupIntervalId":"interval-1",'
        '"lifecycleListenersInstalled":true,"trackedUrls":["blob:test-1"],'
        '"creationTimes":[["blob:test-1",1700000000000]]}}'
    )


@unittest.skipUnless(_node_available(), "node runtime unavailable")
def test_pagehide_cleans_all_urls_and_stops_timer() -> None:
    script = _image_upload_harness(
        """
        exported.createObjectURL({ name: 'a.png' });
        exported.createObjectURL({ name: 'b.png' });
        sandbox.__windowListeners.pagehide[0]();
        process.stdout.write(
          JSON.stringify({
            revokedUrls: sandbox.__revokedUrls,
            clearedIntervals: sandbox.__clearedIntervals,
            state: exported._getObjectURLLifecycleState(),
          })
        );
        """
    )

    assert _run_node(script) == (
        '{"revokedUrls":["blob:test-1","blob:test-2"],'
        '"clearedIntervals":["interval-1"],'
        '"state":{"size":0,"cleanupIntervalId":null,'
        '"lifecycleListenersInstalled":true,"trackedUrls":[],"creationTimes":[]}}'
    )


@unittest.skipUnless(_node_available(), "node runtime unavailable")
def test_pagehide_persisted_pauses_timer_without_revoking_urls() -> None:
    script = _image_upload_harness(
        """
        exported.createObjectURL({ name: 'a.png' });
        exported.createObjectURL({ name: 'b.png' });
        sandbox.__windowListeners.pagehide[0]({ persisted: true });
        process.stdout.write(
          JSON.stringify({
            revokedUrls: sandbox.__revokedUrls,
            clearedIntervals: sandbox.__clearedIntervals,
            state: exported._getObjectURLLifecycleState(),
          })
        );
        """
    )

    assert _run_node(script) == (
        '{"revokedUrls":[],"clearedIntervals":["interval-1"],'
        '"state":{"size":2,"cleanupIntervalId":null,'
        '"lifecycleListenersInstalled":true,'
        '"trackedUrls":["blob:test-1","blob:test-2"],'
        '"creationTimes":[["blob:test-1",1700000000000],'
        '["blob:test-2",1700000000000]]}}'
    )


@unittest.skipUnless(_node_available(), "node runtime unavailable")
def test_pageshow_resumes_timer_after_bfcache_restore_when_visible() -> None:
    script = _image_upload_harness(
        """
        exported.createObjectURL({ name: 'a.png' });
        sandbox.__windowListeners.pagehide[0]({ persisted: true });
        sandbox.__windowListeners.pageshow[0]({ persisted: true });
        process.stdout.write(
          JSON.stringify({
            intervals: sandbox.__intervals.map((entry) => entry.id),
            revokedUrls: sandbox.__revokedUrls,
            clearedIntervals: sandbox.__clearedIntervals,
            state: exported._getObjectURLLifecycleState(),
          })
        );
        """
    )

    assert _run_node(script) == (
        '{"intervals":["interval-1","interval-2"],'
        '"revokedUrls":[],"clearedIntervals":["interval-1"],'
        '"state":{"size":1,"cleanupIntervalId":"interval-2",'
        '"lifecycleListenersInstalled":true,"trackedUrls":["blob:test-1"],'
        '"creationTimes":[["blob:test-1",1700000000000]]}}'
    )


@unittest.skipUnless(_node_available(), "node runtime unavailable")
def test_pageshow_keeps_timer_stopped_when_document_is_still_hidden() -> None:
    script = _image_upload_harness(
        """
        exported.createObjectURL({ name: 'a.png' });
        sandbox.__windowListeners.pagehide[0]({ persisted: true });
        sandbox.document.hidden = true;
        sandbox.__windowListeners.pageshow[0]({ persisted: true });
        process.stdout.write(
          JSON.stringify({
            intervals: sandbox.__intervals.map((entry) => entry.id),
            revokedUrls: sandbox.__revokedUrls,
            clearedIntervals: sandbox.__clearedIntervals,
            state: exported._getObjectURLLifecycleState(),
          })
        );
        """
    )

    assert _run_node(script) == (
        '{"intervals":["interval-1"],'
        '"revokedUrls":[],"clearedIntervals":["interval-1"],'
        '"state":{"size":1,"cleanupIntervalId":null,'
        '"lifecycleListenersInstalled":true,"trackedUrls":["blob:test-1"],'
        '"creationTimes":[["blob:test-1",1700000000000]]}}'
    )
