"""Runtime checks for settings-manager.js language-change ordering."""

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


def _read_source() -> str:
    return SETTINGS_MANAGER_JS.read_text(encoding="utf-8")


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
        const fetchCalls = [];
        const suppressCalls = [];
        const elements = new Map();

        function flushMicrotasks(count) {{
          let promise = Promise.resolve();
          for (let i = 0; i < count; i += 1) {{
            promise = promise.then(() => {{}});
          }}
          return promise;
        }}

        function makeElement(id) {{
          return {{
            id,
            checked: false,
            classList: {{ add() {{}}, remove() {{}} }},
            dataset: {{}},
            disabled: false,
            files: [],
            hidden: false,
            innerHTML: '',
            offsetParent: {{}},
            style: {{}},
            textContent: '',
            title: '',
            value: '',
            addEventListener(type, handler) {{
              elementListeners.push({{ id, type, handler }});
            }},
            appendChild() {{}},
            focus() {{}},
            querySelector() {{
              return {{ textContent: '' }};
            }},
            querySelectorAll() {{
              return [];
            }},
            removeAttribute() {{}},
            setAttribute() {{}},
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
            createElement() {{
              return makeElement('created');
            }},
            execCommand() {{ return true; }},
            getElementById(id) {{
              return getElement(id);
            }},
            querySelector(selector) {{
              return getElement(selector);
            }},
            querySelectorAll() {{
              return [];
            }},
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
              resolve(ok = true) {{
                resolveFetch({{
                  ok,
                  status: ok ? 200 : 500,
                  json: () => Promise.resolve({{ status: 'success' }}),
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
            setItem() {{}},
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
            updateConfig() {{}},
          }},
          setTimeout(fn) {{ return {{ fn }}; }},
          clearTimeout() {{}},
          showStatus() {{}},
          t(key) {{ return key; }},
          window: null,
          __elementListeners: elementListeners,
          __fetchCalls: fetchCalls,
          __flushMicrotasks: flushMicrotasks,
          __getElement: getElement,
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


class TestSettingsManagerLanguageSourceContract(unittest.TestCase):
    def setUp(self) -> None:
        self.source = _read_source()

    def test_language_change_has_epoch_and_save_queue(self) -> None:
        self.assertIn("this._languageChangeEpoch = 0;", self.source)
        self.assertIn("this._languagePersistPromise = null;", self.source)
        self.assertIn("this._pendingLanguagePreference = null;", self.source)
        self.assertIn("async _handleLanguageSelectChange(newLang)", self.source)
        self.assertIn("_queueLanguagePreferenceSave(language)", self.source)
        self.assertIn("_drainLanguagePreferenceSaveQueue()", self.source)
        self.assertIn("changeEpoch !== this._languageChangeEpoch", self.source)


@unittest.skipUnless(_node_available(), "node runtime unavailable")
def test_stale_locale_load_completion_cannot_override_newer_selection() -> None:
    script = _settings_manager_harness(
        """
        const manager = new exported.SettingsManager();
        manager.initEventListeners();

        const languageSelect = sandbox.__getElement('language-select');
        const changeHandler = sandbox.__elementListeners.find(
          (entry) => entry.id === 'language-select' && entry.type === 'change'
        ).handler;

        const available = new Set(['en']);
        const loadCalls = [];
        const loadResolvers = {};
        const setLangCalls = [];
        const translateCalls = [];

        sandbox.AIIA_I18N = {
          detectLang() {
            return 'zh-CN';
          },
          normalizeLang(lang) {
            return String(lang);
          },
          getAvailableLangs() {
            return Array.from(available);
          },
          loadLocale(lang) {
            loadCalls.push(lang);
            return new Promise((resolve) => {
              loadResolvers[lang] = () => {
                available.add(lang);
                resolve();
              };
            });
          },
          setLang(lang) {
            setLangCalls.push(lang);
          },
          translateDOM() {
            translateCalls.push(setLangCalls[setLangCalls.length - 1] || null);
          },
        };

        languageSelect.value = 'zh-CN';
        const firstChange = changeHandler();
        await sandbox.__flushMicrotasks(2);

        languageSelect.value = 'en';
        await changeHandler();

        loadResolvers['zh-CN']();
        await firstChange;
        await sandbox.__flushMicrotasks(4);

        process.stdout.write(JSON.stringify({
          loadCalls,
          setLangCalls,
          translateCalls,
          persistedBodies: sandbox.__fetchCalls.map((call) => call.body),
        }));
        """
    )

    assert json.loads(_run_node(script)) == {
        "loadCalls": ["zh-CN"],
        "setLangCalls": ["en"],
        "translateCalls": ["en"],
        "persistedBodies": [{"language": "en"}],
    }


@unittest.skipUnless(_node_available(), "node runtime unavailable")
def test_language_preference_persistence_serializes_to_latest_queued_value() -> None:
    script = _settings_manager_harness(
        """
        const manager = new exported.SettingsManager();

        const queuePromise = manager._queueLanguagePreferenceSave('zh-CN');
        manager._queueLanguagePreferenceSave('en');
        manager._queueLanguagePreferenceSave('auto');

        const beforeResolve = {
          fetchCount: sandbox.__fetchCalls.length,
          firstBody: sandbox.__fetchCalls[0].body,
        };

        sandbox.__fetchCalls[0].resolve();
        await sandbox.__flushMicrotasks(6);

        const afterFirstResolve = {
          fetchCount: sandbox.__fetchCalls.length,
          secondBody: sandbox.__fetchCalls[1].body,
        };

        sandbox.__fetchCalls[1].resolve();
        await queuePromise;

        process.stdout.write(JSON.stringify({
          beforeResolve,
          afterFirstResolve,
          drained: {
            fetchCount: sandbox.__fetchCalls.length,
            pending: manager._pendingLanguagePreference,
            saving: Boolean(manager._languagePersistPromise),
            suppressCalls: sandbox.__suppressCalls.length,
          },
        }));
        """
    )

    assert json.loads(_run_node(script)) == {
        "beforeResolve": {
            "fetchCount": 1,
            "firstBody": {"language": "zh-CN"},
        },
        "afterFirstResolve": {
            "fetchCount": 2,
            "secondBody": {"language": "auto"},
        },
        "drained": {
            "fetchCount": 2,
            "pending": None,
            "saving": False,
            "suppressCalls": 2,
        },
    }
