"""R808: the copy button of a code block also works where there is no Clipboard API.

``navigator.clipboard`` only exists in a secure context.  The README documents the
Web UI as reachable from other machines (``web_ui.host = "0.0.0.0"``, an mDNS
``<host>.local`` URL, the iPhone Shortcuts setup), and ``http://192.168.x.x:8081`` or
``http://ai.local:8081`` is *not* a secure context: there ``navigator.clipboard`` is
``undefined``.  The copy button of a fenced code block
(``DOMSecurity.createCopyButton``) called ``navigator.clipboard.writeText`` straight
away, so on such an origin every click ended in the "Copy failed" look and nothing
else was tried (real Chrome on ``http://<LAN IP>:port``: ``window.isSecureContext ===
false``, ``typeof navigator.clipboard === "undefined"``, class ``copy-button error``,
no ``execCommand`` call).  The two other copy buttons of the page - the task id
(``multi_task.js``) and the LAN URL (``settings-manager.js``) - already fall back to
a selection copy, which made the failure look random from the reviewer's chair.

The contract: the Clipboard API is tried when there is one; when it is missing or
refuses (permission, document not focused) the code is copied through a selection
(``execCommand('copy')``); only when both fail does the button show the error look.
The fallback has to keep a page working: the helper textarea is read-only (no
on-screen keyboard), fixed and off screen (no scrolling), removed again on every path
including a throwing ``execCommand``, and keyboard focus and the page's selection are
put back where they were.  With no Clipboard API it must run synchronously inside the
click handler - Safari only honours ``execCommand('copy')`` while the user gesture is
still on the stack.

The Node tests load the real ``dom-security.js`` with a fake DOM.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import textwrap
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DOM_SECURITY_JS = (
    REPO_ROOT / "src" / "ai_intervention_agent" / "static" / "js" / "dom-security.js"
)

NODE_AVAILABLE = shutil.which("node") is not None

CODE = "const total = items.reduce((a, b) => a + b, 0);\nif (total > 10) {\n\tlog('大', '🙂');\n}\n"

FAKE_DOM = textwrap.dedent(
    """
    const calls = [];
    const execCalls = [];
    const written = [];
    let execResult = true;
    let execThrows = false;

    function makeElement(tag) {
      const classes = new Set();
      const listeners = {};
      return {
        tagName: String(tag).toUpperCase(),
        innerHTML: '',
        value: '',
        style: {},
        attrs: {},
        parentNode: null,
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
        click() { return listeners.click(); },
        select() { calls.push('select'); document_.activeElement = this; fakeSelection.ranges = ['helper-selection']; },
        focus() { calls.push('focus:' + this.tagName + ':' + (this.attrs.id || '')); document_.activeElement = this; },
        states() { return { copied: classes.has('copied'), error: classes.has('error') }; },
      };
    }

    const body = {
      children: [],
      appendChild(el) { el.parentNode = this; this.children.push(el); calls.push('append:' + el.tagName); return el; },
      removeChild(el) {
        const index = this.children.indexOf(el);
        if (index >= 0) this.children.splice(index, 1);
        el.parentNode = null;
        calls.push('remove:' + el.tagName);
        return el;
      },
    };

    const fakeSelection = {
      ranges: ['range-1', 'range-2'],
      get rangeCount() { return this.ranges.length; },
      getRangeAt(index) { return this.ranges[index]; },
      removeAllRanges() { this.ranges = []; calls.push('selection:clear'); },
      addRange(range) { this.ranges.push(range); calls.push('selection:add:' + range); },
    };

    const timers = [];
    const sandboxTimers = {
      setTimeout(fn, delay) { timers.push({ fn, delay }); return timers.length; },
      clearTimeout() {},
    };

    const previous = makeElement('button');
    previous.attrs.id = 'previously-focused';
    const document_ = {
      activeElement: previous,
      body,
      createElement: (tag) => makeElement(tag),
      getSelection: () => fakeSelection,
      execCommand(command) {
        const helper = document_.activeElement;
        execCalls.push({
          command,
          value: helper && helper.tagName === 'TEXTAREA' ? helper.value : null,
          helperInBody: body.children.length,
          readonly: helper && helper.attrs ? helper.attrs.readonly : undefined,
          position: helper && helper.style ? helper.style.position : undefined,
          offscreen: helper && helper.style ? [helper.style.top, helper.style.left] : undefined,
        });
        if (execThrows) throw new Error('execCommand blew up');
        return execResult;
      },
    };
    """
)


def _script(case_js: str, *, navigator_js: str) -> str:
    return FAKE_DOM + textwrap.dedent(
        f"""
            const fs = require('fs');
            const vm = require('vm');
            const source = fs.readFileSync({str(DOM_SECURITY_JS)!r}, 'utf8');
            const CODE = {json.dumps(CODE)};
            const navigator_ = {navigator_js};
            const sandbox = {{
              console,
              window: {{}},
              navigator: navigator_,
              document: document_,
              setTimeout: sandboxTimers.setTimeout,
              clearTimeout: sandboxTimers.clearTimeout,
            }};
            vm.createContext(sandbox);
            vm.runInContext(source + '\\n;this.DOMSecurity = DOMSecurity;', sandbox);
            const create = (text) => sandbox.DOMSecurity.createCopyButton(text);
            const report = (extra) => process.stdout.write(JSON.stringify(Object.assign({{
              calls, execCalls, written, helpers: body.children.length,
              activeId: document_.activeElement && document_.activeElement.attrs
                ? document_.activeElement.attrs.id : null,
              selection: fakeSelection.ranges,
            }}, extra || {{}})));
            (async () => {{
            {case_js}
            }})().catch((error) => {{ console.error(error && error.stack || error); process.exit(1); }});
            """
    )


NO_CLIPBOARD = "{}"
WORKING_CLIPBOARD = "{ clipboard: { async writeText(value) { written.push(value); } } }"
REFUSING_CLIPBOARD = (
    "{ clipboard: { async writeText(value) { written.push('refused:' + value);"
    " throw new Error('NotAllowedError'); } } }"
)


def _run(case_js: str, *, navigator_js: str) -> dict:
    proc = subprocess.run(
        ["node", "-e", _script(case_js, navigator_js=navigator_js)],
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


@unittest.skipUnless(NODE_AVAILABLE, "node runtime unavailable")
class TestCopyWithoutTheClipboardApi(unittest.TestCase):
    def test_the_code_is_copied_through_a_selection(self) -> None:
        result = _run(
            """
            const button = create(CODE);
            await button.click();
            report({ states: button.states() });
            """,
            navigator_js=NO_CLIPBOARD,
        )

        self.assertEqual(result["states"], {"copied": True, "error": False})
        self.assertEqual(len(result["execCalls"]), 1)
        call = result["execCalls"][0]
        self.assertEqual(call["command"], "copy")
        self.assertEqual(call["value"], CODE)
        self.assertEqual(call["helperInBody"], 1)
        self.assertEqual(result["written"], [])

    def test_the_selection_is_made_before_the_copy_command_runs(self) -> None:
        result = _run(
            """
            await create(CODE).click();
            report();
            """,
            navigator_js=NO_CLIPBOARD,
        )

        calls = result["calls"]
        self.assertLess(calls.index("append:TEXTAREA"), calls.index("select"))

    def test_it_runs_inside_the_click_handler_before_anything_is_awaited(
        self,
    ) -> None:
        # Safari only honours execCommand('copy') while the user gesture is on
        # the stack; an `await` before it would lose it.
        result = _run(
            """
            const button = create(CODE);
            const pending = button.click();
            const syncCalls = execCalls.length;
            await pending;
            report({ syncCalls });
            """,
            navigator_js=NO_CLIPBOARD,
        )

        self.assertEqual(result["syncCalls"], 1)

    def test_the_helper_textarea_is_read_only_fixed_and_off_screen(self) -> None:
        result = _run(
            """
            await create(CODE).click();
            report();
            """,
            navigator_js=NO_CLIPBOARD,
        )

        call = result["execCalls"][0]
        self.assertEqual(call["readonly"], "")
        self.assertEqual(call["position"], "fixed")
        self.assertEqual(call["offscreen"], ["-1000px", "-1000px"])

    def test_the_helper_textarea_never_stays_in_the_page(self) -> None:
        for exec_result, exec_throws in (
            ("true", "false"),
            ("false", "false"),
            ("true", "true"),
        ):
            with self.subTest(exec_result=exec_result, exec_throws=exec_throws):
                result = _run(
                    f"""
                    execResult = {exec_result};
                    execThrows = {exec_throws};
                    await create(CODE).click();
                    report();
                    """,
                    navigator_js=NO_CLIPBOARD,
                )

                self.assertEqual(result["helpers"], 0)

    def test_focus_and_the_page_selection_are_put_back(self) -> None:
        result = _run(
            """
            await create(CODE).click();
            report();
            """,
            navigator_js=NO_CLIPBOARD,
        )

        self.assertEqual(result["activeId"], "previously-focused")
        self.assertEqual(result["selection"], ["range-1", "range-2"])

    def test_focus_and_selection_are_put_back_after_a_failure_too(self) -> None:
        result = _run(
            """
            execThrows = true;
            await create(CODE).click();
            report();
            """,
            navigator_js=NO_CLIPBOARD,
        )

        self.assertEqual(result["activeId"], "previously-focused")
        self.assertEqual(result["selection"], ["range-1", "range-2"])

    def test_a_refusing_selection_copy_shows_the_error_look(self) -> None:
        result = _run(
            """
            execResult = false;
            const button = create(CODE);
            await button.click();
            report({ states: button.states() });
            """,
            navigator_js=NO_CLIPBOARD,
        )

        self.assertEqual(result["states"], {"copied": False, "error": True})

    def test_a_throwing_selection_copy_is_an_error_look_not_an_exception(self) -> None:
        result = _run(
            """
            execThrows = true;
            const button = create(CODE);
            await button.click();
            report({ states: button.states() });
            """,
            navigator_js=NO_CLIPBOARD,
        )

        self.assertEqual(result["states"], {"copied": False, "error": True})


@unittest.skipUnless(NODE_AVAILABLE, "node runtime unavailable")
class TestTheClipboardApiStillComesFirst(unittest.TestCase):
    def test_a_working_api_is_used_alone(self) -> None:
        result = _run(
            """
            const button = create(CODE);
            await button.click();
            report({ states: button.states() });
            """,
            navigator_js=WORKING_CLIPBOARD,
        )

        self.assertEqual(result["written"], [CODE])
        self.assertEqual(result["execCalls"], [])
        self.assertEqual(result["states"], {"copied": True, "error": False})
        self.assertEqual(result["helpers"], 0)

    def test_a_refused_api_write_falls_back_to_the_selection(self) -> None:
        result = _run(
            """
            const button = create(CODE);
            await button.click();
            report({ states: button.states() });
            """,
            navigator_js=REFUSING_CLIPBOARD,
        )

        self.assertEqual(result["written"], ["refused:" + CODE])
        self.assertEqual(len(result["execCalls"]), 1)
        self.assertEqual(result["execCalls"][0]["value"], CODE)
        self.assertEqual(result["states"], {"copied": True, "error": False})
        self.assertEqual(result["helpers"], 0)

    def test_when_both_refuse_the_button_shows_the_error_look(self) -> None:
        result = _run(
            """
            execResult = false;
            const button = create(CODE);
            await button.click();
            report({ states: button.states() });
            """,
            navigator_js=REFUSING_CLIPBOARD,
        )

        self.assertEqual(result["states"], {"copied": False, "error": True})
        self.assertEqual(result["helpers"], 0)

    def test_a_clipboard_object_without_write_text_counts_as_missing(self) -> None:
        result = _run(
            """
            const button = create(CODE);
            await button.click();
            report({ states: button.states() });
            """,
            navigator_js="{ clipboard: {} }",
        )

        self.assertEqual(len(result["execCalls"]), 1)
        self.assertEqual(result["states"], {"copied": True, "error": False})


if __name__ == "__main__":
    unittest.main()
