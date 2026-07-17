"""R593 regression coverage for theme toggle button NodeList loops."""

from __future__ import annotations

import json
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
THEME_JS = REPO_ROOT / "src" / "ai_intervention_agent" / "static" / "js" / "theme.js"


def _source() -> str:
    return THEME_JS.read_text(encoding="utf-8")


def _extract_function(source: str, marker: str) -> str:
    start = source.find(marker)
    assert start != -1, f"Cannot find function marker: {marker}"
    open_brace = source.find("{", start)
    assert open_brace != -1, f"Cannot find opening brace for: {marker}"
    depth = 1
    i = open_brace + 1
    while i < len(source):
        char = source[i]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return source[start : i + 1]
        i += 1
    raise AssertionError(f"Unbalanced function body for: {marker}")


def _run_node(script: str) -> str:
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


def test_theme_toggle_button_paths_use_indexed_loops_without_nodelist_foreach() -> None:
    source = _source()
    update_body = _extract_function(source, "function updateToggleButton(")
    bind_body = _extract_function(source, "function bindExistingButtons(")

    assert "buttons.forEach" not in update_body
    assert "buttons.forEach" not in bind_body
    assert "const buttonCount = buttons.length" in update_body
    assert "const buttonCount = buttons.length" in bind_body
    assert "for (let index = 0; index < buttonCount; index += 1)" in update_body
    assert "for (let index = 0; index < buttonCount; index += 1)" in bind_body
    assert "const button = buttons[index]" in update_body
    assert "const button = buttons[index]" in bind_body
    assert "if (!button) continue" in update_body
    assert "if (!button) continue" in bind_body


@pytest.mark.skipif(shutil.which("node") is None, reason="node runtime unavailable")
def test_theme_toggle_buttons_update_and_bind_without_nodelist_foreach() -> None:
    script = textwrap.dedent(
        f"""
        const fs = require('fs');
        const vm = require('vm');
        const code = fs.readFileSync({str(THEME_JS)!r}, 'utf8');

        function makeButton(name) {{
          const attrs = {{}};
          const classes = new Set();
          const listeners = [];
          return {{
            name,
            attrs,
            classes,
            listeners,
            classList: {{
              toggle(className, force) {{
                if (force) classes.add(className);
                else classes.delete(className);
              }},
            }},
            addEventListener(type, handler) {{
              listeners.push({{ type, handlerName: handler && handler.name }});
            }},
            hasAttribute(attr) {{
              return Object.prototype.hasOwnProperty.call(attrs, attr);
            }},
            setAttribute(attr, value) {{
              attrs[attr] = String(value);
            }},
          }};
        }}

        const buttonA = makeButton('a');
        const buttonB = makeButton('b');
        const buttons = {{
          0: buttonA,
          1: buttonB,
          length: 2,
          forEach() {{
            throw new Error('NodeList.forEach must not be used');
          }},
        }};
        const documentListeners = [];
        const windowListeners = [];
        const mediaListeners = [];
        const headChildren = [];
        const htmlAttrs = {{}};
        const dispatchedEvents = [];
        let storedTheme = null;

        const sandbox = {{
          CustomEvent: function CustomEvent(type, init) {{
            return {{ type, detail: init && init.detail }};
          }},
          JSON,
          Object,
          Promise,
          Set,
          String,
          console: {{
            debug() {{}},
            error() {{}},
            info() {{}},
            log() {{}},
            warn() {{}},
          }},
          document: {{
            addEventListener(type, handler) {{
              documentListeners.push({{ type, handler }});
            }},
            createElement(tag) {{
              return {{ tagName: String(tag).toUpperCase(), content: '', name: '' }};
            }},
            documentElement: {{
              removeAttribute(name) {{
                delete htmlAttrs[name];
              }},
              setAttribute(name, value) {{
                htmlAttrs[name] = String(value);
              }},
            }},
            head: {{
              appendChild(node) {{
                headChildren.push(node);
              }},
            }},
            querySelector(selector) {{
              if (selector === 'meta[name="theme-color"]') return headChildren[0] || null;
              return null;
            }},
            querySelectorAll(selector) {{
              return selector === '.theme-toggle-btn'
                ? buttons
                : {{ length: 0, forEach() {{ throw new Error('unexpected forEach'); }} }};
            }},
          }},
          localStorage: {{
            getItem(key) {{
              return key === 'theme-preference' ? storedTheme : null;
            }},
            setItem(key, value) {{
              if (key === 'theme-preference') storedTheme = String(value);
            }},
          }},
          module: {{ exports: {{}} }},
          exports: {{}},
          window: null,
          __buttons: [buttonA, buttonB],
          __dispatchedEvents: dispatchedEvents,
          __documentListeners: documentListeners,
          __htmlAttrs: htmlAttrs,
          __windowListeners: windowListeners,
        }};
        sandbox.window = sandbox;
        sandbox.globalThis = sandbox;
        sandbox.addEventListener = (type, handler) => {{
          windowListeners.push({{ type, handler }});
        }};
        sandbox.dispatchEvent = (event) => {{
          dispatchedEvents.push(event);
          return true;
        }};
        sandbox.matchMedia = () => ({{
          matches: false,
          addEventListener(type, handler) {{
            mediaListeners.push({{ type, handler }});
          }},
        }});

        vm.createContext(sandbox);
        vm.runInContext(code, sandbox);
        const ThemeManager = sandbox.module.exports;

        ThemeManager.init();
        ThemeManager.init();
        const afterInit = sandbox.__buttons.map((button) => ({{
          attrs: {{ ...button.attrs }},
          classes: Array.from(button.classes).sort(),
          listenerCount: button.listeners.length,
        }}));

        ThemeManager.setTheme('light');
        const afterLight = sandbox.__buttons.map((button) => ({{
          attrs: {{ ...button.attrs }},
          classes: Array.from(button.classes).sort(),
          listenerCount: button.listeners.length,
        }}));

        process.stdout.write(JSON.stringify({{
          afterInit,
          afterLight,
          currentTheme: ThemeManager.getTheme(),
          effectiveTheme: ThemeManager.getEffectiveTheme(),
          htmlTheme: sandbox.__htmlAttrs['data-theme'],
          storageListeners: sandbox.__windowListeners
            .filter((entry) => entry.type === 'storage').length,
        }}));
        """
    )

    result = json.loads(_run_node(script))

    assert result == {
        "afterInit": [
            {
                "attrs": {
                    "aria-label": "theme.auto",
                    "data-theme-bound": "true",
                    "title": "theme.auto",
                },
                "classes": ["is-auto"],
                "listenerCount": 1,
            },
            {
                "attrs": {
                    "aria-label": "theme.auto",
                    "data-theme-bound": "true",
                    "title": "theme.auto",
                },
                "classes": ["is-auto"],
                "listenerCount": 1,
            },
        ],
        "afterLight": [
            {
                "attrs": {
                    "aria-label": "theme.light",
                    "data-theme-bound": "true",
                    "title": "theme.light",
                },
                "classes": ["is-light"],
                "listenerCount": 1,
            },
            {
                "attrs": {
                    "aria-label": "theme.light",
                    "data-theme-bound": "true",
                    "title": "theme.light",
                },
                "classes": ["is-light"],
                "listenerCount": 1,
            },
        ],
        "currentTheme": "light",
        "effectiveTheme": "light",
        "htmlTheme": "light",
        "storageListeners": 1,
    }
