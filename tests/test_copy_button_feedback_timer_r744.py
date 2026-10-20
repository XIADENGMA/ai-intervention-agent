"""R744: a second click on a code block's copy button keeps its own feedback.

The copy button of the Web UI (``DOMSecurity.createCopyButton``) and of the VS Code
panel (``createCopyButton`` in ``webview-ui.js``) switched to its "copied" or
"error" look and scheduled the way back two seconds later, without cancelling the
way back scheduled by the click before. Two clicks within two seconds therefore let
the first click's timer reset the button while the second click's feedback was still
due, and a failure followed by a success carried both state classes until the stale
timer ran.

The tests load the real sources into Node with a fake DOM and fake timers: every click
cancels the pending timer, the newest timer restores the idle look, a state replaces
the other one.
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
DOM_SECURITY_JS = (
    REPO_ROOT / "src" / "ai_intervention_agent" / "static" / "js" / "dom-security.js"
)
WEBVIEW_UI_JS = REPO_ROOT / "packages" / "vscode" / "webview-ui.js"

NODE_AVAILABLE = shutil.which("node") is not None

FAKE_DOM = textwrap.dedent(
    """
    const timers = [];
    let nextTimerId = 1;
    const written = [];
    let clipboardFails = false;

    function makeButton() {
      const classes = new Set();
      const listeners = {};
      return {
        innerHTML: '',
        title: '',
        attrs: {},
        set className(value) {
          classes.clear();
          String(value).split(/\\s+/).filter(Boolean).forEach((c) => classes.add(c));
        },
        get className() { return [...classes].join(' '); },
        classList: {
          add: (...names) => names.forEach((n) => classes.add(n)),
          remove: (...names) => names.forEach((n) => classes.delete(n)),
          contains: (name) => classes.has(name),
        },
        setAttribute(name, value) { this.attrs[name] = value; },
        addEventListener(type, handler) { listeners[type] = handler; },
        async click() { await listeners.click(); },
        states() {
          return { copied: classes.has('copied'), error: classes.has('error') };
        },
      };
    }

    const fakeTimers = {
      setTimeout(fn, delay) {
        const id = nextTimerId++;
        timers.push({ id, fn, delay, cleared: false, ran: false });
        return id;
      },
      clearTimeout(id) {
        const timer = timers.find((t) => t.id === id);
        if (timer) timer.cleared = true;
      },
    };
    const fakeNavigator = {
      clipboard: {
        async writeText(value) {
          if (clipboardFails) throw new Error('denied');
          written.push(value);
        },
      },
    };
    function runTimer(timer) {
      timer.ran = true;
      timer.fn();
    }
    function pending() {
      return timers.filter((t) => !t.cleared && !t.ran).length;
    }
    """
)


def _run_node(script: str) -> dict:
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
    return json.loads(proc.stdout)


def _extract_function(source: str, signature: str) -> str:
    start = source.index(signature)
    end = source.index("\n  }\n", start) + len("\n  }\n")
    return source[start:end]


def _web_ui_script(case_js: str) -> str:
    return FAKE_DOM + textwrap.dedent(
        f"""
            const fs = require('fs');
            const vm = require('vm');
            const source = fs.readFileSync({str(DOM_SECURITY_JS)!r}, 'utf8');
            const sandbox = {{
              console,
              window: {{}},
              navigator: fakeNavigator,
              document: {{ createElement: () => makeButton() }},
              setTimeout: fakeTimers.setTimeout,
              clearTimeout: fakeTimers.clearTimeout,
            }};
            vm.createContext(sandbox);
            vm.runInContext(source + '\\n;this.DOMSecurity = DOMSecurity;', sandbox);
            const create = (text) => sandbox.DOMSecurity.createCopyButton(text);
            (async () => {{
            {case_js}
            }})();
            """
    )


def _vscode_script(case_js: str) -> str:
    function_source = _extract_function(
        WEBVIEW_UI_JS.read_text(encoding="utf-8"), "function createCopyButton("
    )
    return FAKE_DOM + textwrap.dedent(
        f"""
            let clock = 1000;
            const fakeDate = {{ now: () => clock }};
            const create = new Function(
              'document', 'navigator', 't', 'Date', 'setTimeout', 'clearTimeout',
              {json.dumps(function_source)} + '; return createCopyButton;'
            )(
              {{ createElement: () => makeButton() }},
              fakeNavigator,
              (key) => key,
              fakeDate,
              fakeTimers.setTimeout,
              fakeTimers.clearTimeout,
            );
            (async () => {{
            {case_js}
            }})();
            """
    )


@unittest.skipUnless(NODE_AVAILABLE, "node runtime unavailable")
class TestWebUiCopyButton(unittest.TestCase):
    def test_second_click_cancels_the_first_timer_and_keeps_its_feedback(self) -> None:
        result = _run_node(
            _web_ui_script(
                """
                const button = create('code');
                const idle = button.innerHTML;
                await button.click();
                const afterFirst = {
                  ...button.states(), idle: button.innerHTML === idle, pending: pending(),
                };
                await button.click();
                const afterSecond = {
                  ...button.states(), idle: button.innerHTML === idle,
                  firstCleared: timers[0].cleared, pending: pending(),
                };
                runTimer(timers[1]);
                const afterRestore = {
                  ...button.states(), idle: button.innerHTML === idle, pending: pending(),
                };
                console.log(JSON.stringify({
                  afterFirst, afterSecond, afterRestore, delays: timers.map((t) => t.delay),
                  written,
                }));
                """
            )
        )
        self.assertEqual(
            result["afterFirst"],
            {"copied": True, "error": False, "idle": False, "pending": 1},
        )
        self.assertEqual(
            result["afterSecond"],
            {
                "copied": True,
                "error": False,
                "idle": False,
                "firstCleared": True,
                "pending": 1,
            },
        )
        self.assertEqual(
            result["afterRestore"],
            {"copied": False, "error": False, "idle": True, "pending": 0},
        )
        self.assertEqual(result["delays"], [2000, 2000])
        self.assertEqual(result["written"], ["code", "code"])

    def test_a_failed_copy_shows_the_error_and_goes_back_to_idle(self) -> None:
        result = _run_node(
            _web_ui_script(
                """
                const button = create('code');
                const idle = button.innerHTML;
                clipboardFails = true;
                await button.click();
                const failed = {
                  ...button.states(), idle: button.innerHTML === idle,
                  labelChanged: button.innerHTML !== idle,
                };
                runTimer(timers[0]);
                const restored = { ...button.states(), idle: button.innerHTML === idle };
                console.log(JSON.stringify({ failed, restored }));
                """
            )
        )
        self.assertEqual(
            result["failed"],
            {"copied": False, "error": True, "idle": False, "labelChanged": True},
        )
        self.assertEqual(
            result["restored"], {"copied": False, "error": False, "idle": True}
        )

    def test_a_success_right_after_a_failure_replaces_the_error_state(self) -> None:
        result = _run_node(
            _web_ui_script(
                """
                const button = create('code');
                clipboardFails = true;
                await button.click();
                clipboardFails = false;
                await button.click();
                const afterSuccess = {
                  ...button.states(), failedTimerCleared: timers[0].cleared, pending: pending(),
                };
                runTimer(timers[1]);
                console.log(JSON.stringify({ afterSuccess, restored: button.states() }));
                """
            )
        )
        self.assertEqual(
            result["afterSuccess"],
            {
                "copied": True,
                "error": False,
                "failedTimerCleared": True,
                "pending": 1,
            },
        )
        self.assertEqual(result["restored"], {"copied": False, "error": False})


@unittest.skipUnless(NODE_AVAILABLE, "node runtime unavailable")
class TestVsCodeCopyButton(unittest.TestCase):
    def test_second_click_cancels_the_first_timer_and_keeps_its_feedback(self) -> None:
        result = _run_node(
            _vscode_script(
                """
                const button = create('code');
                await button.click();
                const afterFirst = { ...button.states(), title: button.title, pending: pending() };
                clock += 1000;
                await button.click();
                const afterSecond = {
                  ...button.states(), title: button.title,
                  firstCleared: timers[0].cleared, pending: pending(),
                };
                runTimer(timers[1]);
                const afterRestore = {
                  ...button.states(), title: button.title, pending: pending(),
                };
                console.log(JSON.stringify({
                  afterFirst, afterSecond, afterRestore, delays: timers.map((t) => t.delay),
                  written,
                }));
                """
            )
        )
        self.assertEqual(
            result["afterFirst"],
            {"copied": True, "error": False, "title": "ui.copy.success", "pending": 1},
        )
        self.assertEqual(
            result["afterSecond"],
            {
                "copied": True,
                "error": False,
                "title": "ui.copy.success",
                "firstCleared": True,
                "pending": 1,
            },
        )
        self.assertEqual(
            result["afterRestore"],
            {"copied": False, "error": False, "title": "ui.copy.label", "pending": 0},
        )
        self.assertEqual(result["delays"], [2000, 2000])
        self.assertEqual(result["written"], ["code", "code"])

    def test_clicks_within_250ms_are_ignored(self) -> None:
        result = _run_node(
            _vscode_script(
                """
                const button = create('code');
                await button.click();
                clock += 100;
                await button.click();
                console.log(JSON.stringify({ timers: timers.length, written }));
                """
            )
        )
        self.assertEqual(result, {"timers": 1, "written": ["code"]})

    def test_a_failed_copy_shows_the_error_and_a_later_success_replaces_it(
        self,
    ) -> None:
        result = _run_node(
            _vscode_script(
                """
                const button = create('code');
                clipboardFails = true;
                await button.click();
                const failed = { ...button.states(), title: button.title };
                clock += 1000;
                clipboardFails = false;
                await button.click();
                const afterSuccess = {
                  ...button.states(), title: button.title,
                  failedTimerCleared: timers[0].cleared, pending: pending(),
                };
                runTimer(timers[1]);
                console.log(JSON.stringify({
                  failed, afterSuccess, restored: { ...button.states(), title: button.title },
                }));
                """
            )
        )
        self.assertEqual(
            result["failed"],
            {"copied": False, "error": True, "title": "ui.copy.failed"},
        )
        self.assertEqual(
            result["afterSuccess"],
            {
                "copied": True,
                "error": False,
                "title": "ui.copy.success",
                "failedTimerCleared": True,
                "pending": 1,
            },
        )
        self.assertEqual(
            result["restored"],
            {"copied": False, "error": False, "title": "ui.copy.label"},
        )


class TestSourcesStillHaveTheFunctionsUnderTest(unittest.TestCase):
    def test_both_copy_buttons_exist_where_the_harness_looks(self) -> None:
        self.assertRegex(
            DOM_SECURITY_JS.read_text(encoding="utf-8"),
            r"static createCopyButton\(targetText\)",
        )
        source = WEBVIEW_UI_JS.read_text(encoding="utf-8")
        function_source = _extract_function(source, "function createCopyButton(")
        self.assertTrue(function_source.rstrip().endswith("}"))
        self.assertEqual(
            len(re.findall(r"addEventListener\('click'", function_source)), 1
        )


if __name__ == "__main__":
    unittest.main()
