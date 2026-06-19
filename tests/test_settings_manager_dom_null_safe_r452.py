"""Runtime checks for settings-manager.js DOM write null safety."""

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

        const documentListeners = [];
        const elements = new Map();
        const fetchCalls = [];
        const notificationConfigs = [];

        function makeElement(id) {{
          return {{
            id,
            checked: false,
            classList: {{ add() {{}}, remove() {{}} }},
            dataset: {{}},
            disabled: false,
            files: [],
            innerHTML: '',
            style: {{}},
            textContent: '',
            value: '',
            addEventListener() {{}},
            appendChild() {{}},
            blur() {{}},
            focus() {{}},
            hasAttribute() {{ return false; }},
            querySelector() {{ return null; }},
            querySelectorAll() {{ return []; }},
            removeAttribute() {{}},
            setAttribute() {{}},
          }};
        }}

        const sandbox = {{
          Array,
          Error,
          JSON,
          Map,
          Math,
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
            addEventListener(type, handler) {{
              documentListeners.push({{ type, handler }});
            }},
            body: {{
              appendChild() {{}},
              removeChild() {{}},
            }},
            contains() {{ return false; }},
            createElement() {{ return makeElement('created'); }},
            execCommand() {{ return true; }},
            getElementById(id) {{
              return elements.get(id) || null;
            }},
            querySelector(selector) {{
              return elements.get(selector) || null;
            }},
            querySelectorAll() {{ return []; }},
            removeEventListener() {{}},
          }},
          fetch(url, init) {{
            fetchCalls.push({{ url, init }});
            return Promise.resolve({{
              ok: true,
              json: () => Promise.resolve({{ status: 'success', config: {{}} }}),
            }});
          }},
          localStorage: {{
            getItem() {{ return null; }},
            setItem() {{}},
          }},
          location: {{ origin: 'http://127.0.0.1:8080' }},
          module: {{ exports: {{}} }},
          exports: {{}},
          notificationManager: {{
            audioContext: null,
            isSupported: true,
            permission: 'default',
            clearCustomSound() {{ return Promise.resolve({{ success: true }}); }},
            getCustomSoundMeta() {{ return null; }},
            playSound() {{ return Promise.resolve(); }},
            saveCustomSoundFromFile() {{
              return Promise.resolve({{ success: true }});
            }},
            updateConfig(config) {{
              notificationConfigs.push(config);
            }},
          }},
          setTimeout(fn) {{ return {{ fn }}; }},
          clearTimeout() {{}},
          showStatus() {{}},
          t(key, params) {{
            return params && params.origin ? `${{key}}:${{params.origin}}` : key;
          }},
          window: null,
          __documentListeners: documentListeners,
          __elements: elements,
          __fetchCalls: fetchCalls,
          __makeElement: makeElement,
          __notificationConfigs: notificationConfigs,
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


@unittest.skipUnless(_node_available(), "node runtime unavailable")
def test_update_ui_skips_missing_settings_controls() -> None:
    script = _settings_manager_harness(
        """
        const manager = new exported.SettingsManager();
        manager.settings = { ...manager.defaultSettings, soundVolume: 42 };
        let threw = false;
        try {
          manager.updateUI();
        } catch (_err) {
          threw = true;
        }
        process.stdout.write(JSON.stringify({
          threw,
          elementCount: sandbox.__elements.size,
        }));
        """
    )

    assert json.loads(_run_node(script)) == {
        "threw": False,
        "elementCount": 0,
    }


@unittest.skipUnless(_node_available(), "node runtime unavailable")
def test_update_ui_still_writes_present_volume_controls() -> None:
    script = _settings_manager_harness(
        """
        const manager = new exported.SettingsManager();
        manager.settings = { ...manager.defaultSettings, soundVolume: 55 };
        const soundVolume = sandbox.__makeElement('sound-volume');
        const volumeValue = sandbox.__makeElement('.volume-value');
        sandbox.__elements.set('sound-volume', soundVolume);
        sandbox.__elements.set('.volume-value', volumeValue);
        manager.updateUI();
        process.stdout.write(JSON.stringify({
          soundVolumeValue: soundVolume.value,
          volumeText: volumeValue.textContent,
        }));
        """
    )

    assert json.loads(_run_node(script)) == {
        "soundVolumeValue": 55,
        "volumeText": "55%",
    }


@unittest.skipUnless(_node_available(), "node runtime unavailable")
def test_volume_change_does_not_throw_when_value_label_is_missing() -> None:
    script = _settings_manager_harness(
        """
        const manager = new exported.SettingsManager();
        manager.settings = { ...manager.defaultSettings };
        manager.initEventListeners();
        const changeHandler = sandbox.__documentListeners.find(
          (entry) => entry.type === 'change',
        ).handler;
        let threw = false;
        try {
          changeHandler({
            target: { id: 'sound-volume', value: '37' },
          });
        } catch (_err) {
          threw = true;
        }
        process.stdout.write(JSON.stringify({
          threw,
          soundVolume: manager.settings.soundVolume,
          updateConfigCalls: sandbox.__notificationConfigs.length,
        }));
        """
    )

    assert json.loads(_run_node(script)) == {
        "threw": False,
        "soundVolume": 37,
        "updateConfigCalls": 1,
    }
