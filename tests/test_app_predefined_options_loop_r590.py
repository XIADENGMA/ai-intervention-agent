"""R590 regression coverage for app predefined-options rendering."""

from __future__ import annotations

import json
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
APP_JS = REPO_ROOT / "src" / "ai_intervention_agent" / "static" / "js" / "app.js"


def _source() -> str:
    return APP_JS.read_text(encoding="utf-8")


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


def test_load_config_renders_predefined_options_without_array_foreach() -> None:
    body = _extract_function(_source(), "async function loadConfig(")

    assert "config.predefined_options.forEach" not in body
    assert "const predefinedOptionCount = config.predefined_options.length" in body
    assert "for (let index = 0; index < predefinedOptionCount; index += 1)" in body
    assert "if (!(index in config.predefined_options)) continue" in body
    assert "const option = config.predefined_options[index]" in body
    assert "checkbox.id = `option-${index}`" in body
    assert "checkbox.checked = optionDefaults[index] === true" in body


@pytest.mark.skipif(shutil.which("node") is None, reason="node runtime unavailable")
def test_load_config_preserves_option_dom_order_defaults_and_sparse_skip() -> None:
    function_source = _extract_function(_source(), "async function loadConfig(")
    script = textwrap.dedent(
        f"""
        const vm = require('vm');
        (async () => {{

        function makeClassList() {{
          const values = [];
          return {{
            values,
            add(name) {{
              values.push(name);
            }},
          }};
        }}

        function makeElement(tagName, id) {{
          return {{
            tagName: String(tagName).toUpperCase(),
            id: id || '',
            className: '',
            value: '',
            checked: false,
            htmlFor: '',
            textContent: '',
            style: {{}},
            children: [],
            classList: makeClassList(),
            appendChild(child) {{
              this.children.push(child);
              child.parentNode = this;
              return child;
            }},
          }};
        }}

        const elements = {{
          description: makeElement('div', 'description'),
          'options-container': makeElement('div', 'options-container'),
          separator: makeElement('div', 'separator'),
        }};
        const options = ['Approve', 'unused-hole', 'Escalate'];
        delete options[1];
        options.forEach = function disabledForEach() {{
          throw new Error('predefined_options.forEach must not be used');
        }};

        const calls = [];
        const sandbox = {{
          Array,
          console: {{ error() {{}}, warn() {{}} }},
          document: {{
            createElement(tagName) {{
              return makeElement(tagName);
            }},
            getElementById(id) {{
              return elements[id] || null;
            }},
          }},
          fetchWithTimeout: async () => ({{
            json: async () => ({{
              has_content: true,
              prompt: 'Prompt',
              prompt_html: '<p>Prompt</p>',
              predefined_options: options,
              predefined_options_defaults: [true, true, false],
            }}),
          }}),
          renderMarkdownContent(element, content) {{
            calls.push(['renderMarkdownContent', element.id, content]);
          }},
          showContentPage() {{
            calls.push(['showContentPage']);
          }},
          showNoContentPage() {{
            calls.push(['showNoContentPage']);
          }},
          showStatus(message, level) {{
            calls.push(['showStatus', message, level]);
          }},
          t(key) {{
            return key;
          }},
        }};
        vm.createContext(sandbox);
        vm.runInContext({json.dumps(function_source)} + '; this.loadConfig = loadConfig;', sandbox);
        await sandbox.loadConfig();

        const rendered = elements['options-container'].children.map((optionDiv) => {{
          const checkbox = optionDiv.children[0];
          const label = optionDiv.children[1];
          return {{
            className: optionDiv.className,
            selectedClasses: optionDiv.classList.values,
            checkboxId: checkbox.id,
            checkboxValue: checkbox.value,
            checkboxChecked: checkbox.checked,
            labelFor: label.htmlFor,
            labelText: label.textContent,
          }};
        }});

        process.stdout.write(JSON.stringify({{
          calls,
          optionsDisplay: elements['options-container'].style.display,
          separatorDisplay: elements.separator.style.display,
          rendered,
        }}));
        }})().catch((error) => {{
          console.error(error && error.stack ? error.stack : String(error));
          process.exit(1);
        }});
        """
    )

    result = json.loads(_run_node(script))

    assert result == {
        "calls": [
            ["showContentPage"],
            ["renderMarkdownContent", "description", "<p>Prompt</p>"],
        ],
        "optionsDisplay": "block",
        "separatorDisplay": "block",
        "rendered": [
            {
                "className": "option-item",
                "selectedClasses": ["selected"],
                "checkboxId": "option-0",
                "checkboxValue": "Approve",
                "checkboxChecked": True,
                "labelFor": "option-0",
                "labelText": "Approve",
            },
            {
                "className": "option-item",
                "selectedClasses": [],
                "checkboxId": "option-2",
                "checkboxValue": "Escalate",
                "checkboxChecked": False,
                "labelFor": "option-2",
                "labelText": "Escalate",
            },
        ],
    }
