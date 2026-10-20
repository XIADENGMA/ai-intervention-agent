"""R733: the Tab shortcut must not take the Tab key away from the browser.

``Tab`` / ``Shift+Tab`` switch the task tab on the Web UI page. They were
registered with the registry's default ``preventDefault: true``, so the key
was swallowed before the handler even looked at the tabs:

* with one task (or none) nothing was switched, yet focus could not move from
  ``<body>``, a button or a link, so the page could not be driven from the
  keyboard at all;
* while a dialog (paste code, settings, image preview, shortcut help) was open
  the key still did that, so the dialog's focus trap could never move focus
  (it stuck on the Cancel button) and, with several tasks, every Tab press
  switched the task behind the dialog.

The shortcut now prevents the default only when it really switches a task, and
does nothing while a modal dialog is open. These tests run the shipped
``keyboard-shortcuts.js`` in a Node ``vm`` and check the one structural
fact the runtime check relies on: every ``aria-modal`` element of the template
starts out closed in a way the open-dialog selector excludes (otherwise the
shortcut would be disabled from the first paint).
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import textwrap
from html.parser import HTMLParser
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
KEYBOARD_SHORTCUTS_JS = (
    REPO_ROOT
    / "src"
    / "ai_intervention_agent"
    / "static"
    / "js"
    / "keyboard-shortcuts.js"
)
WEB_UI_HTML = REPO_ROOT / "src" / "ai_intervention_agent" / "templates" / "web_ui.html"

needs_node = pytest.mark.skipif(
    shutil.which("node") is None, reason="node runtime unavailable"
)


def _run_node(script: str) -> str:
    proc = subprocess.run(
        ["node", "-e", script],
        check=False,
        capture_output=True,
        text=True,
        timeout=15,
    )
    if proc.returncode != 0:
        raise AssertionError(
            f"node exited {proc.returncode}\nstdout={proc.stdout!r}\nstderr={proc.stderr!r}"
        )
    return proc.stdout


def _harness(case_js: str) -> str:
    return textwrap.dedent(
        f"""
        const fs = require('fs');
        const vm = require('vm');
        const code = fs.readFileSync({str(KEYBOARD_SHORTCUTS_JS)!r}, 'utf8');
        const documentListeners = {{}};
        let currentTabs = [];
        let openDialog = null;
        const dialogSelectors = [];
        function el(tagName) {{
          return {{
            tagName,
            isContentEditable: false,
            classList: {{ contains() {{ return false; }} }},
          }};
        }}
        const body = el('BODY');
        const sandbox = {{
          Array, JSON, Map, Object, Set, String,
          console: {{ debug() {{}}, error(...a) {{ process.stderr.write(a.join(' ') + '\\n'); }}, info() {{}}, log() {{}}, warn() {{}} }},
          document: {{
            body,
            addEventListener(type, handler) {{
              if (!documentListeners[type]) documentListeners[type] = [];
              documentListeners[type].push(handler);
            }},
            removeEventListener() {{}},
            getElementById() {{ return null; }},
            querySelector(selector) {{
              dialogSelectors.push(selector);
              return selector.includes('aria-modal') ? openDialog : null;
            }},
            querySelectorAll(selector) {{
              return selector === '.task-tab:not(.hidden)' ? currentTabs : [];
            }},
          }},
          module: {{ exports: {{}} }},
          navigator: {{ platform: 'MacIntel' }},
          __press(init) {{
            const event = Object.assign({{
              type: 'keydown', key: 'Tab', ctrlKey: false, altKey: false,
              shiftKey: false, metaKey: false, target: body, defaultPrevented: false,
              preventDefault() {{ this.defaultPrevented = true; }},
              stopPropagation() {{}},
            }}, init || {{}});
            for (const handler of [...(documentListeners.keydown || [])]) handler(event);
            return event;
          }},
          __setTabs(count, activeIndex, clicks) {{
            currentTabs = Array.from({{ length: count }}, (_, index) => ({{
              classList: {{ contains(name) {{ return name === 'active' && index === activeIndex; }} }},
              click() {{ clicks.push(index); }},
            }}));
          }},
          __setDialog(value) {{ openDialog = value; }},
          __dialogSelectors: dialogSelectors,
        }};
        sandbox.window = sandbox;
        sandbox.globalThis = sandbox;
        vm.createContext(sandbox);
        vm.runInContext(code, sandbox);
        const KeyboardShortcuts = sandbox.module.exports;
        KeyboardShortcuts.init();
        {case_js}
        """
    )


def _run_case(case_js: str) -> dict:
    return json.loads(_run_node(_harness(case_js)))


@needs_node
def test_tab_is_left_to_the_browser_when_there_is_nothing_to_switch() -> None:
    result = _run_case(
        """
        const clicks = [];
        const out = {};
        for (const [name, count] of [['none', 0], ['one', 1]]) {
          sandbox.__setTabs(count, 0, clicks);
          for (const target of [el('BUTTON'), el('BODY'), el('A')]) {
            for (const shiftKey of [false, true]) {
              const event = sandbox.__press({ shiftKey, target });
              out[`${name}/${target.tagName}/${shiftKey ? 'shift' : 'plain'}`] = event.defaultPrevented;
            }
          }
        }
        process.stdout.write(JSON.stringify({ out, clicks }));
        """
    )
    assert result["clicks"] == []
    assert set(result["out"].values()) == {False}, result["out"]
    assert len(result["out"]) == 12


@needs_node
def test_tab_still_switches_tasks_on_the_page() -> None:
    result = _run_case(
        """
        const clicks = [];
        const seen = [];
        sandbox.__setTabs(3, 0, clicks);
        seen.push(sandbox.__press({ target: body }).defaultPrevented);
        seen.push(sandbox.__press({ target: el('BUTTON') }).defaultPrevented);
        seen.push(sandbox.__press({ shiftKey: true, target: body }).defaultPrevented);
        process.stdout.write(JSON.stringify({ clicks, seen }));
        """
    )
    assert result == {"clicks": [1, 1, 2], "seen": [True, True, True]}


@needs_node
def test_tab_does_nothing_while_a_dialog_is_open() -> None:
    result = _run_case(
        """
        const clicks = [];
        const out = [];
        sandbox.__setTabs(3, 0, clicks);
        sandbox.__setDialog({ id: 'some-dialog' });
        for (const target of [el('BUTTON'), el('BODY'), el('DIV')]) {
          for (const shiftKey of [false, true]) {
            out.push(sandbox.__press({ shiftKey, target }).defaultPrevented);
          }
        }
        sandbox.__setDialog(null);
        const after = sandbox.__press({ target: body }).defaultPrevented;
        process.stdout.write(JSON.stringify({ clicks, out, after }));
        """
    )
    assert result["clicks"] == [1]
    assert result["out"] == [False] * 6
    assert result["after"] is True


@needs_node
def test_inputs_and_modified_tab_keys_are_not_touched() -> None:
    result = _run_case(
        """
        const clicks = [];
        sandbox.__setTabs(3, 0, clicks);
        const out = [];
        for (const tag of ['INPUT', 'TEXTAREA', 'SELECT']) {
          out.push(sandbox.__press({ target: el(tag) }).defaultPrevented);
        }
        out.push(sandbox.__press({ ctrlKey: true, target: body }).defaultPrevented);
        out.push(sandbox.__press({ metaKey: true, target: body }).defaultPrevented);
        out.push(sandbox.__press({ altKey: true, target: body }).defaultPrevented);
        process.stdout.write(JSON.stringify({ clicks, out }));
        """
    )
    assert result == {"clicks": [], "out": [False] * 6}


@needs_node
def test_the_open_dialog_query_excludes_closed_dialogs_of_both_kinds() -> None:
    result = _run_case(
        """
        sandbox.__setTabs(3, 0, []);
        sandbox.__press({ target: body });
        process.stdout.write(JSON.stringify(sandbox.__dialogSelectors));
        """
    )
    assert result, "the Tab shortcut never asked whether a dialog is open"
    for selector in result:
        assert '[aria-modal="true"]' in selector
        assert ":not([hidden])" in selector
        assert ":not(.hidden)" in selector


class _ModalCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.modals: list[dict[str, object]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if attributes.get("aria-modal") == "true":
            self.modals.append(
                {
                    "id": attributes.get("id") or "?",
                    "hidden_attr": "hidden" in attributes,
                    "hidden_class": "hidden" in (attributes.get("class") or "").split(),
                }
            )


def test_every_modal_dialog_of_the_template_starts_closed_in_a_way_the_query_excludes() -> (
    None
):
    html = WEB_UI_HTML.read_text(encoding="utf-8")
    html = re.sub(r"\{\{.*?\}\}", "PH", html, flags=re.DOTALL)
    html = re.sub(r"\{%.*?%\}", "", html, flags=re.DOTALL)
    collector = _ModalCollector()
    collector.feed(html)
    ids = {str(modal["id"]) for modal in collector.modals}
    assert {"code-paste-panel", "settings-panel", "image-modal"} <= ids, ids
    open_at_load = [
        modal["id"]
        for modal in collector.modals
        if not (modal["hidden_attr"] or modal["hidden_class"])
    ]
    assert open_at_load == [], (
        f"modal dialogs that count as open on first paint: {open_at_load}; "
        "the Tab shortcut would be disabled until they are closed"
    )
