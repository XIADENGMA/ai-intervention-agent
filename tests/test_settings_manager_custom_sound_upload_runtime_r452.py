"""Runtime checks for custom sound upload file-input cleanup."""

from __future__ import annotations

import json
import shutil
import subprocess
import textwrap
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SETTINGS_MANAGER_JS = (
    REPO_ROOT
    / "src"
    / "ai_intervention_agent"
    / "static"
    / "js"
    / "settings-manager.js"
)


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


def _settings_manager_harness(case_js: str) -> str:
    return textwrap.dedent(
        f"""
        const fs = require('fs');
        const vm = require('vm');
        const code = fs.readFileSync({str(SETTINGS_MANAGER_JS)!r}, 'utf8');

        const elementListeners = [];
        const elements = new Map();
        const saveCalls = [];

        function makeElement(id) {{
          return {{
            id,
            attributes: {{}},
            checked: false,
            classList: {{ add() {{}}, remove() {{}} }},
            dataset: {{}},
            disabled: false,
            files: [],
            innerHTML: '',
            style: {{}},
            textContent: '',
            value: '',
            addEventListener(type, handler) {{
              elementListeners.push({{ id, type, handler }});
            }},
            appendChild() {{}},
            blur() {{}},
            focus() {{}},
            hasAttribute() {{ return false; }},
            querySelector() {{ return null; }},
            querySelectorAll() {{ return []; }},
            removeAttribute(name) {{
              delete this.attributes[name];
            }},
            setAttribute(name, value) {{
              this.attributes[name] = String(value);
            }},
          }};
        }}

        function getElement(id) {{
          if (!elements.has(id)) {{
            elements.set(id, makeElement(id));
          }}
          return elements.get(id);
        }}

        const sandbox = {{
          Array,
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
          console: {{
            debug() {{}},
            error() {{}},
            info() {{}},
            log() {{}},
            warn() {{}},
          }},
          document: {{
            activeElement: null,
            addEventListener() {{}},
            body: {{
              appendChild() {{}},
              removeChild() {{}},
            }},
            contains() {{ return false; }},
            createElement() {{ return makeElement('created'); }},
            execCommand() {{ return true; }},
            getElementById(id) {{ return getElement(id); }},
            querySelector(selector) {{ return getElement(selector); }},
            querySelectorAll() {{ return []; }},
            removeEventListener() {{}},
          }},
          fetch() {{
            return Promise.resolve({{
              ok: true,
              json: () => Promise.resolve({{ status: 'success', config: {{}} }}),
            }});
          }},
          localStorage: {{
            getItem() {{ return null; }},
            setItem() {{}},
          }},
          module: {{ exports: {{}} }},
          exports: {{}},
          notificationManager: {{
            clearCustomSound() {{ return Promise.resolve({{ success: true }}); }},
            getCustomSoundMeta() {{ return null; }},
            playSound() {{ return Promise.resolve(); }},
            saveCustomSoundFromFile(file) {{
              saveCalls.push(file);
              return Promise.resolve({{ success: true }});
            }},
          }},
          setTimeout(fn) {{ return {{ fn }}; }},
          clearTimeout() {{}},
          showStatus() {{}},
          t(key) {{ return key; }},
          window: null,
          __elementListeners: elementListeners,
          __getElement: getElement,
          __saveCalls: saveCalls,
        }};
        sandbox.window = sandbox;
        sandbox.globalThis = sandbox;
        sandbox.addEventListener = () => {{}};

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


def _run_upload_failure_case(save_impl_js: str) -> dict[str, object]:
    script = _settings_manager_harness(
        f"""
        const manager = new exported.SettingsManager();
        const fileInput = sandbox.__getElement('custom-sound-input');
        const statusEl = sandbox.__getElement('custom-sound-status');
        sandbox.__getElement('custom-sound-test');
        sandbox.__getElement('custom-sound-clear');
        sandbox.notificationManager.saveCustomSoundFromFile = function (file) {{
          sandbox.__saveCalls.push(file);
          {save_impl_js}
        }};

        manager._wireCustomSoundControls();
        const changeHandler = sandbox.__elementListeners.find(
          (entry) => entry.id === 'custom-sound-input' && entry.type === 'change',
        ).handler;

        const selectedFile = {{ name: 'bad.wav', type: 'audio/wav', size: 128 }};
        fileInput.files = [selectedFile];
        fileInput.value = '/fake/path/bad.wav';

        let bubbled = null;
        try {{
          await changeHandler({{ target: fileInput }});
        }} catch (err) {{
          bubbled = err && err.message ? err.message : String(err);
        }}

        process.stdout.write(JSON.stringify({{
          bubbled,
          inputValue: fileInput.value,
          saveCalls: sandbox.__saveCalls.length,
          statusText: statusEl.textContent,
          status: statusEl.attributes['data-status'],
        }}));
        """
    )
    return json.loads(_run_node(script))


@unittest.skipUnless(_node_available(), "node runtime unavailable")
def test_custom_sound_upload_resets_file_input_when_save_rejects() -> None:
    assert _run_upload_failure_case("return Promise.reject(new Error('boom'));") == {
        "bubbled": None,
        "inputValue": "",
        "saveCalls": 1,
        "statusText": "settings.customSound.errors.generic",
        "status": "error",
    }


@unittest.skipUnless(_node_available(), "node runtime unavailable")
def test_custom_sound_upload_resets_file_input_when_save_throws() -> None:
    assert _run_upload_failure_case("throw new Error('boom');") == {
        "bubbled": None,
        "inputValue": "",
        "saveCalls": 1,
        "statusText": "settings.customSound.errors.generic",
        "status": "error",
    }
