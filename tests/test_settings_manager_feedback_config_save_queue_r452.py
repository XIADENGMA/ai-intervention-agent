"""Runtime checks for settings-manager.js feedback-config save ordering."""

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
        const statusCalls = [];
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
                  status: ok ? 200 : 500,
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
          showStatus(message, kind) {{
            statusCalls.push({{ message, kind }});
          }},
          t(key) {{ return key; }},
          window: null,
          __fetchCalls: fetchCalls,
          __flushMicrotasks: flushMicrotasks,
          __statusCalls: statusCalls,
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
def test_feedback_config_save_sends_latest_queued_payload_and_one_success() -> None:
    script = _settings_manager_harness(
        """
        const manager = new exported.SettingsManager();
        manager.feedbackConfig = {
          frontend_countdown: 240,
          resubmit_prompt: '',
          prompt_suffix: '',
        };

        const savePromise = manager.saveFeedbackConfig({
          frontend_countdown: 60,
          prompt_suffix: 'old suffix',
        });
        manager.saveFeedbackConfig({
          frontend_countdown: 61,
          resubmit_prompt: 'new prompt',
        });

        const beforeResolve = {
          fetchCount: sandbox.__fetchCalls.length,
          firstBody: sandbox.__fetchCalls[0].body,
          statusCount: sandbox.__statusCalls.length,
        };

        sandbox.__fetchCalls[0].resolve();
        await sandbox.__flushMicrotasks(6);

        const afterFirstResolve = {
          fetchCount: sandbox.__fetchCalls.length,
          secondBody: sandbox.__fetchCalls[1].body,
          statusCount: sandbox.__statusCalls.length,
        };

        sandbox.__fetchCalls[1].resolve();
        await savePromise;

        process.stdout.write(JSON.stringify({
          beforeResolve,
          afterFirstResolve,
          finalConfig: manager.feedbackConfig,
          statusCalls: sandbox.__statusCalls,
          suppressCalls: sandbox.__suppressCalls.length,
          pending: manager._pendingFeedbackConfigUpdates,
          saving: Boolean(manager._feedbackConfigSavePromise),
        }));
        """
    )

    assert json.loads(_run_node(script)) == {
        "beforeResolve": {
            "fetchCount": 1,
            "firstBody": {
                "frontend_countdown": 60,
                "prompt_suffix": "old suffix",
            },
            "statusCount": 0,
        },
        "afterFirstResolve": {
            "fetchCount": 2,
            "secondBody": {
                "frontend_countdown": 61,
                "resubmit_prompt": "new prompt",
            },
            "statusCount": 0,
        },
        "finalConfig": {
            "frontend_countdown": 61,
            "resubmit_prompt": "new prompt",
            "prompt_suffix": "old suffix",
        },
        "statusCalls": [
            {
                "message": "settings.feedbackConfigSaved",
                "kind": "success",
            }
        ],
        "suppressCalls": 2,
        "pending": None,
        "saving": False,
    }


@unittest.skipUnless(_node_available(), "node runtime unavailable")
def test_feedback_config_save_suppresses_stale_error_when_queued_retry_succeeds() -> (
    None
):
    script = _settings_manager_harness(
        """
        const manager = new exported.SettingsManager();
        manager.feedbackConfig = {
          frontend_countdown: 240,
          resubmit_prompt: '',
          prompt_suffix: '',
        };

        const savePromise = manager.saveFeedbackConfig({
          prompt_suffix: 'first',
        });
        manager.saveFeedbackConfig({
          prompt_suffix: 'latest',
        });

        sandbox.__fetchCalls[0].reject(new Error('network down'));
        await sandbox.__flushMicrotasks(6);

        const afterFailure = {
          fetchCount: sandbox.__fetchCalls.length,
          statusCount: sandbox.__statusCalls.length,
          secondBody: sandbox.__fetchCalls[1].body,
        };

        sandbox.__fetchCalls[1].resolve();
        await savePromise;

        process.stdout.write(JSON.stringify({
          afterFailure,
          finalConfig: manager.feedbackConfig,
          statusCalls: sandbox.__statusCalls,
          suppressCalls: sandbox.__suppressCalls.length,
          pending: manager._pendingFeedbackConfigUpdates,
          saving: Boolean(manager._feedbackConfigSavePromise),
        }));
        """
    )

    assert json.loads(_run_node(script)) == {
        "afterFailure": {
            "fetchCount": 2,
            "statusCount": 0,
            "secondBody": {
                "prompt_suffix": "latest",
            },
        },
        "finalConfig": {
            "frontend_countdown": 240,
            "resubmit_prompt": "",
            "prompt_suffix": "latest",
        },
        "statusCalls": [
            {
                "message": "settings.feedbackConfigSaved",
                "kind": "success",
            }
        ],
        "suppressCalls": 2,
        "pending": None,
        "saving": False,
    }


@unittest.skipUnless(_node_available(), "node runtime unavailable")
def test_feedback_config_reset_cancels_unsent_debounced_save() -> None:
    script = _settings_manager_harness(
        """
        const manager = new exported.SettingsManager();
        manager.feedbackConfig = {
          frontend_countdown: 240,
          resubmit_prompt: '',
          prompt_suffix: '',
        };

        manager._queueFeedbackConfigSaveFromUi({ prompt_suffix: 'stale' });

        const resetPromise = manager.resetFeedbackConfig();
        await sandbox.__flushMicrotasks(2);

        const beforeResolve = {
          fetchCount: sandbox.__fetchCalls.length,
          firstUrl: sandbox.__fetchCalls[0].url,
          firstBody: sandbox.__fetchCalls[0].body,
          debounceTimer: Boolean(manager._feedbackConfigDebounceTimer),
          debouncePending: manager._pendingDebouncedFeedbackConfigUpdates,
          savePending: manager._pendingFeedbackConfigUpdates,
        };

        sandbox.__fetchCalls[0].resolve({
          status: 'success',
          defaults: {
            frontend_countdown: 240,
            resubmit_prompt: '',
            prompt_suffix: '',
          },
        });
        await resetPromise;

        process.stdout.write(JSON.stringify({
          beforeResolve,
          finalConfig: manager.feedbackConfig,
          statusCalls: sandbox.__statusCalls,
          suppressCalls: sandbox.__suppressCalls.length,
          fetchCalls: sandbox.__fetchCalls.map((call) => ({
            url: call.url,
            body: call.body,
          })),
        }));
        """
    )

    assert json.loads(_run_node(script)) == {
        "beforeResolve": {
            "fetchCount": 1,
            "firstUrl": "/api/reset-feedback-config",
            "firstBody": None,
            "debounceTimer": False,
            "debouncePending": None,
            "savePending": None,
        },
        "finalConfig": {
            "frontend_countdown": 240,
            "resubmit_prompt": "",
            "prompt_suffix": "",
        },
        "statusCalls": [
            {
                "message": "settings.feedbackConfigReset",
                "kind": "success",
            }
        ],
        "suppressCalls": 1,
        "fetchCalls": [
            {
                "url": "/api/reset-feedback-config",
                "body": None,
            }
        ],
    }


@unittest.skipUnless(_node_available(), "node runtime unavailable")
def test_feedback_config_reset_waits_for_inflight_save_without_stale_hint() -> None:
    script = _settings_manager_harness(
        """
        const manager = new exported.SettingsManager();
        manager.feedbackConfig = {
          frontend_countdown: 240,
          resubmit_prompt: '',
          prompt_suffix: '',
        };

        const savePromise = manager.saveFeedbackConfig({
          prompt_suffix: 'stale first',
        });
        manager.saveFeedbackConfig({
          prompt_suffix: 'stale queued',
        });

        const resetPromise = manager.resetFeedbackConfig();
        await sandbox.__flushMicrotasks(2);

        const beforeSaveResolve = {
          fetchCount: sandbox.__fetchCalls.length,
          firstUrl: sandbox.__fetchCalls[0].url,
          firstBody: sandbox.__fetchCalls[0].body,
          statusCount: sandbox.__statusCalls.length,
          savePending: manager._pendingFeedbackConfigUpdates,
        };

        sandbox.__fetchCalls[0].resolve();
        await sandbox.__flushMicrotasks(8);

        const afterSaveResolve = {
          fetchCount: sandbox.__fetchCalls.length,
          secondUrl: sandbox.__fetchCalls[1].url,
          secondBody: sandbox.__fetchCalls[1].body,
          statusCount: sandbox.__statusCalls.length,
          savePending: manager._pendingFeedbackConfigUpdates,
          saving: Boolean(manager._feedbackConfigSavePromise),
        };

        sandbox.__fetchCalls[1].resolve({
          status: 'success',
          defaults: {
            frontend_countdown: 240,
            resubmit_prompt: '',
            prompt_suffix: '',
          },
        });
        await resetPromise;
        await savePromise;

        process.stdout.write(JSON.stringify({
          beforeSaveResolve,
          afterSaveResolve,
          finalConfig: manager.feedbackConfig,
          statusCalls: sandbox.__statusCalls,
          suppressCalls: sandbox.__suppressCalls.length,
          fetchCalls: sandbox.__fetchCalls.map((call) => ({
            url: call.url,
            body: call.body,
          })),
        }));
        """
    )

    assert json.loads(_run_node(script)) == {
        "beforeSaveResolve": {
            "fetchCount": 1,
            "firstUrl": "/api/update-feedback-config",
            "firstBody": {
                "prompt_suffix": "stale first",
            },
            "statusCount": 0,
            "savePending": None,
        },
        "afterSaveResolve": {
            "fetchCount": 2,
            "secondUrl": "/api/reset-feedback-config",
            "secondBody": None,
            "statusCount": 0,
            "savePending": None,
            "saving": False,
        },
        "finalConfig": {
            "frontend_countdown": 240,
            "resubmit_prompt": "",
            "prompt_suffix": "",
        },
        "statusCalls": [
            {
                "message": "settings.feedbackConfigReset",
                "kind": "success",
            }
        ],
        "suppressCalls": 2,
        "fetchCalls": [
            {
                "url": "/api/update-feedback-config",
                "body": {
                    "prompt_suffix": "stale first",
                },
            },
            {
                "url": "/api/reset-feedback-config",
                "body": None,
            },
        ],
    }


@unittest.skipUnless(_node_available(), "node runtime unavailable")
def test_feedback_config_open_refresh_preserves_edit_made_during_load() -> None:
    script = _settings_manager_harness(
        """
        const manager = new exported.SettingsManager();
        manager.feedbackConfig = {
          frontend_countdown: 240,
          resubmit_prompt: '',
          prompt_suffix: 'visible local',
        };

        let resolveLoad = null;
        manager.loadFeedbackConfig = () =>
          new Promise((resolve) => {
            resolveLoad = resolve;
          });

        const refreshPromise = manager._refreshFeedbackConfigForOpen();
        manager._queueFeedbackConfigSaveFromUi({ prompt_suffix: 'typed' });
        resolveLoad({
          frontend_countdown: 10,
          resubmit_prompt: 'server prompt',
          prompt_suffix: 'server suffix',
        });

        const applied = await refreshPromise;

        process.stdout.write(JSON.stringify({
          applied,
          finalConfig: manager.feedbackConfig,
          editEpoch: manager._feedbackConfigEditEpoch,
          debounceTimer: Boolean(manager._feedbackConfigDebounceTimer),
          debouncePending: manager._pendingDebouncedFeedbackConfigUpdates,
          statusCalls: sandbox.__statusCalls,
        }));
        """
    )

    assert json.loads(_run_node(script)) == {
        "applied": False,
        "finalConfig": {
            "frontend_countdown": 240,
            "resubmit_prompt": "",
            "prompt_suffix": "visible local",
        },
        "editEpoch": 1,
        "debounceTimer": True,
        "debouncePending": {"prompt_suffix": "typed"},
        "statusCalls": [],
    }
