"""Runtime checks for settings-manager.js backend sync ordering."""

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

        const fetchCalls = [];
        const localStorageWrites = [];
        const notificationConfigs = [];
        const suppressCalls = [];

        function flushMicrotasks(count) {{
          let promise = Promise.resolve();
          for (let i = 0; i < count; i += 1) {{
            promise = promise.then(() => {{}});
          }}
          return promise;
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
            createElement() {{
              return {{
                addEventListener() {{}},
                classList: {{ add() {{}}, remove() {{}} }},
                dataset: {{}},
                querySelector() {{ return null; }},
                querySelectorAll() {{ return []; }},
                setAttribute() {{}},
                style: {{}},
              }};
            }},
            execCommand() {{ return true; }},
            getElementById() {{ return null; }},
            querySelector() {{ return null; }},
            querySelectorAll() {{ return []; }},
            removeEventListener() {{}},
          }},
          fetch(url, init) {{
            let resolveFetch;
            let rejectFetch;
            const promise = new Promise((resolve, reject) => {{
              resolveFetch = resolve;
              rejectFetch = reject;
            }});
            fetchCalls.push({{
              url,
              body: init && init.body ? JSON.parse(init.body) : null,
              resolve(data = {{ status: 'success' }}, ok = true) {{
                resolveFetch({{
                  ok,
                  json: () => Promise.resolve(data),
                }});
              }},
              reject(error) {{
                rejectFetch(error);
              }},
            }});
            return promise;
          }},
          localStorage: {{
            getItem() {{ return null; }},
            setItem(key, value) {{
              localStorageWrites.push({{ key, value }});
            }},
          }},
          module: {{ exports: {{}} }},
          exports: {{}},
          notificationManager: {{
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
          t(key) {{ return key; }},
          window: null,
          __fetchCalls: fetchCalls,
          __flushMicrotasks: flushMicrotasks,
          __localStorageWrites: localStorageWrites,
          __notificationConfigs: notificationConfigs,
          __suppressCalls: suppressCalls,
        }};
        sandbox.window = sandbox;
        sandbox.globalThis = sandbox;
        sandbox.addEventListener = () => {{}};
        sandbox.suppressLocalConfigChangedEcho = () => {{
          suppressCalls.push(true);
        }};

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
def test_backend_sync_coalesces_rapid_changes_to_latest_snapshot() -> None:
    script = _settings_manager_harness(
        """
        const manager = new exported.SettingsManager();
        manager.settings = { ...manager.defaultSettings };

        manager.updateSetting('soundVolume', 10);
        const queuePromise = manager._backendSyncPromise;
        manager.updateSetting('soundVolume', 20);
        manager.updateSetting('barkEnabled', true);

        const beforeResolve = {
          fetchCount: sandbox.__fetchCalls.length,
          firstVolume: sandbox.__fetchCalls[0].body.soundVolume,
          firstBarkEnabled: sandbox.__fetchCalls[0].body.barkEnabled,
          storageWrites: sandbox.__localStorageWrites.length,
          notificationUpdates: sandbox.__notificationConfigs.length,
        };

        sandbox.__fetchCalls[0].resolve();
        await sandbox.__flushMicrotasks(6);

        const afterFirstResolve = {
          fetchCount: sandbox.__fetchCalls.length,
          secondVolume: sandbox.__fetchCalls[1].body.soundVolume,
          secondBarkEnabled: sandbox.__fetchCalls[1].body.barkEnabled,
        };

        sandbox.__fetchCalls[1].resolve();
        await queuePromise;

        process.stdout.write(JSON.stringify({
          beforeResolve,
          afterFirstResolve,
          drained: {
            fetchCount: sandbox.__fetchCalls.length,
            pending: manager._pendingBackendSyncSettings,
            syncing: Boolean(manager._backendSyncPromise),
            suppressCalls: sandbox.__suppressCalls.length,
          },
        }));
        """
    )

    assert json.loads(_run_node(script)) == {
        "beforeResolve": {
            "fetchCount": 1,
            "firstVolume": 10,
            "firstBarkEnabled": False,
            "storageWrites": 3,
            "notificationUpdates": 3,
        },
        "afterFirstResolve": {
            "fetchCount": 2,
            "secondVolume": 20,
            "secondBarkEnabled": True,
        },
        "drained": {
            "fetchCount": 2,
            "pending": None,
            "syncing": False,
            "suppressCalls": 2,
        },
    }


@unittest.skipUnless(_node_available(), "node runtime unavailable")
def test_backend_sync_sends_queued_latest_snapshot_after_failed_request() -> None:
    script = _settings_manager_harness(
        """
        const manager = new exported.SettingsManager();
        manager.settings = { ...manager.defaultSettings };

        manager.updateSetting('soundVolume', 31);
        const queuePromise = manager._backendSyncPromise;
        manager.updateSetting('soundVolume', 32);

        sandbox.__fetchCalls[0].reject(new Error('network down'));
        await sandbox.__flushMicrotasks(6);

        const afterFailure = {
          fetchCount: sandbox.__fetchCalls.length,
          secondVolume: sandbox.__fetchCalls[1].body.soundVolume,
        };

        sandbox.__fetchCalls[1].resolve();
        await queuePromise;

        process.stdout.write(JSON.stringify({
          afterFailure,
          drained: {
            pending: manager._pendingBackendSyncSettings,
            syncing: Boolean(manager._backendSyncPromise),
            suppressCalls: sandbox.__suppressCalls.length,
          },
        }));
        """
    )

    assert json.loads(_run_node(script)) == {
        "afterFailure": {
            "fetchCount": 2,
            "secondVolume": 32,
        },
        "drained": {
            "pending": None,
            "syncing": False,
            "suppressCalls": 2,
        },
    }


@unittest.skipUnless(_node_available(), "node runtime unavailable")
def test_open_settings_refresh_does_not_overwrite_edit_made_during_load() -> None:
    script = _settings_manager_harness(
        """
        class ClassList {
          constructor(values) {
            this.values = new Set(values || []);
          }
          add(value) {
            this.values.add(value);
          }
          remove(value) {
            this.values.delete(value);
          }
          contains(value) {
            return this.values.has(value);
          }
        }

        class TestElement {
          constructor(id) {
            this.id = id;
            this.checked = false;
            this.value = '';
            this.textContent = '';
            this.innerHTML = '';
            this.classList = new ClassList();
            this.style = {};
          }
          addEventListener() {}
          querySelector() { return null; }
          querySelectorAll() { return []; }
        }

        const elements = {};
        function element(id) {
          if (!elements[id]) elements[id] = new TestElement(id);
          return elements[id];
        }

        element('notification-enabled').checked = false;
        element('volume-value').textContent = '40%';

        sandbox.document.getElementById = (id) => {
          return Object.prototype.hasOwnProperty.call(elements, id)
            ? elements[id]
            : null;
        };
        sandbox.document.querySelector = (selector) => {
          if (selector === '.volume-value') return element('volume-value');
          return null;
        };
        sandbox.document.contains = () => true;

        const manager = new exported.SettingsManager();
        manager.initialized = true;
        manager.settings = { ...manager.defaultSettings, enabled: false, soundVolume: 40 };

        const openPromise = manager.showSettings();
        await sandbox.__flushMicrotasks(2);

        element('notification-enabled').checked = true;
        manager.updateSetting('enabled', true);

        const loadCall = sandbox.__fetchCalls.find(
          (call) => call.url === '/api/get-notification-config',
        );
        loadCall.resolve({
          status: 'success',
          config: {
            enabled: false,
            web_enabled: false,
            sound_volume: 40,
          },
        });
        await sandbox.__flushMicrotasks(6);

        const feedbackLoadCall = sandbox.__fetchCalls.find(
          (call) => call.url === '/api/get-feedback-prompts',
        );
        feedbackLoadCall.resolve({
          status: 'success',
          config: {
            frontend_countdown: 240,
            resubmit_prompt: '',
            prompt_suffix: '',
          },
        });
        await openPromise;

        const saveCall = sandbox.__fetchCalls.find(
          (call) => call.url === '/api/update-notification-config',
        );
        saveCall.resolve();
        await manager._backendSyncPromise;

        process.stdout.write(JSON.stringify({
          settingsEnabled: manager.settings.enabled,
          checkboxChecked: element('notification-enabled').checked,
          saveBody: saveCall.body,
        }));
        """
    )

    assert json.loads(_run_node(script)) == {
        "settingsEnabled": True,
        "checkboxChecked": True,
        "saveBody": {
            "enabled": True,
            "webEnabled": True,
            "autoRequestPermission": True,
            "soundEnabled": True,
            "soundMute": False,
            "soundVolume": 40,
            "mobileOptimized": True,
            "mobileVibrate": True,
            "barkEnabled": False,
            "barkUrl": "https://api.day.app/push",
            "barkDeviceKey": "",
            "barkIcon": "",
            "barkAction": "none",
            "barkUrlTemplate": "{base_url}/?task_id={task_id}",
        },
    }
