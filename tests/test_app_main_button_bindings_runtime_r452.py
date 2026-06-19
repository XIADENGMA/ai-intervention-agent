"""Runtime checks for app.js main button binding DOM safety."""

from __future__ import annotations

import json
import shutil
import subprocess
import textwrap
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
APP_JS = REPO_ROOT / "src" / "ai_intervention_agent" / "static" / "js" / "app.js"


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


def _app_button_harness(case_js: str) -> str:
    return textwrap.dedent(
        f"""
        const fs = require('fs');
        const vm = require('vm');
        const code = fs.readFileSync({str(APP_JS)!r}, 'utf8');

        const elements = new Map();
        const documentListeners = {{}};
        const documentRemoveCalls = [];
        const windowListeners = {{}};
        const debugMessages = [];
        const focusedIds = [];
        const warningMessages = [];
        const calls = [];
        const clearedTimeouts = [];
        const timeoutCallbacks = [];
        let nextTimeoutId = 0;

        function pushListener(bucket, type, handler) {{
          bucket[type] = bucket[type] || [];
          bucket[type].push(handler);
        }}

        function removeListener(bucket, type, handler) {{
          const listeners = bucket[type] || [];
          const index = listeners.indexOf(handler);
          if (index >= 0) {{
            listeners.splice(index, 1);
          }}
        }}

        function createElement(id) {{
          const classNames = new Set();
          return {{
            id,
            addCalls: [],
            handlers: {{}},
            listeners: {{}},
            dataset: {{}},
            classList: {{
              add(...names) {{
                for (const name of names) classNames.add(name);
              }},
              remove(...names) {{
                for (const name of names) classNames.delete(name);
              }},
              contains(name) {{
                return classNames.has(name);
              }},
            }},
            disabled: false,
            innerHTML: '',
            style: {{}},
            textContent: '',
            value: '',
            addEventListener(type, handler) {{
              this.addCalls.push({{ type, handlerName: handler.name || '' }});
              pushListener(this.listeners, type, handler);
              this.handlers[type] = handler;
            }},
            removeEventListener(type, handler) {{
              removeListener(this.listeners, type, handler);
            }},
            click() {{
              for (const handler of this.listeners.click || []) {{
                handler({{ target: this }});
              }}
            }},
            focus() {{
              focusedIds.push(id);
              sandbox.document.activeElement = this;
            }},
          }};
        }}

        const sandbox = {{
          AbortController: function AbortController() {{
            this.signal = {{
              addEventListener() {{}},
              removeEventListener() {{}},
            }};
            this.abort = function abort() {{}};
          }},
          AbortSignal: {{}},
          JSON,
          Object,
          Promise,
          String,
          URL,
          console: {{
            debug(...args) {{ debugMessages.push(args.join(' ')); }},
            error() {{}},
            info() {{}},
            log() {{}},
            warn(...args) {{ warningMessages.push(args.join(' ')); }},
          }},
          document: {{
            activeElement: null,
            readyState: 'loading',
            addEventListener(type, handler) {{
              pushListener(documentListeners, type, handler);
            }},
            removeEventListener(type, handler) {{
              documentRemoveCalls.push({{
                type,
                handlerName: handler.name || '',
              }});
              removeListener(documentListeners, type, handler);
            }},
            getElementById(id) {{
              return elements.get(id) || null;
            }},
            contains(element) {{
              return Array.from(elements.values()).includes(element);
            }},
            querySelector() {{
              return null;
            }},
          }},
          location: {{
            href: 'http://127.0.0.1:8080/',
            replace(value) {{ this.href = String(value); }},
          }},
          isSecureContext: true,
          navigator: {{
            maxTouchPoints: 0,
            platform: 'Win32',
            userAgent: 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
          }},
          addEventListener(type, handler) {{
            pushListener(windowListeners, type, handler);
          }},
          fetch() {{
            return Promise.resolve({{
              ok: true,
              json: async () => ({{}}),
            }});
          }},
          setTimeout(fn, delay) {{
            const id = `timer-${{++nextTimeoutId}}`;
            timeoutCallbacks.push({{ id, fn, delay }});
            return id;
          }},
          clearTimeout(id) {{
            clearedTimeouts.push(id);
          }},
          selectedImages: [],
          clearAllImages() {{}},
          initializeImageFeatures() {{}},
          startPeriodicCleanup() {{}},
          initMultiTaskSupport() {{}},
          settingsManager: {{
            init: () => new Promise(() => {{}}),
            applySettings() {{}},
          }},
          notificationManager: {{
            audioContext: null,
            init: () => new Promise(() => {{}}),
            sendNotification: async () => undefined,
          }},
          __calls: calls,
          __createElement: createElement,
          __clearedTimeouts: clearedTimeouts,
          __debugMessages: debugMessages,
          __documentListeners: documentListeners,
          __documentRemoveCalls: documentRemoveCalls,
          __elements: elements,
          __focusedIds: focusedIds,
          __timeoutCallbacks: timeoutCallbacks,
          __warningMessages: warningMessages,
          __windowListeners: windowListeners,
        }};
        sandbox.window = sandbox;
        sandbox.globalThis = sandbox;

        vm.createContext(sandbox);
        vm.runInContext(code, sandbox);
        sandbox.loadConfig = () => new Promise(() => {{}});
        sandbox.initHourglassAnimation = () => undefined;
        sandbox.initializeShortcutTooltip = () => undefined;
        sandbox.insertCodeFromClipboard = function insertCodeFromClipboard() {{
          calls.push('insert');
        }};
        sandbox.submitFeedback = function submitFeedback() {{
          calls.push('submit');
        }};
        sandbox.closeInterface = function closeInterface() {{
          calls.push('close');
        }};

        (async () => {{
        {textwrap.indent(case_js, "  ")}
        }})().catch((err) => {{
          console.error(err && err.stack ? err.stack : err);
          process.exit(1);
        }});
        """
    )


@unittest.skipUnless(_node_available(), "node runtime unavailable")
def test_initialize_app_continues_when_main_buttons_are_missing() -> None:
    script = _app_button_harness(
        """
        let threw = false;
        try {
          vm.runInContext('initializeApp()', sandbox);
        } catch (_err) {
          threw = true;
        }

        process.stdout.write(JSON.stringify({
          threw,
          knownElements: Array.from(sandbox.__elements.keys()),
          keydownListenerNames: (sandbox.__documentListeners.keydown || [])
            .map((handler) => handler.name),
          audioUnlockListenerCounts: {
            click: (sandbox.__documentListeners.click || []).length,
            keydown: (sandbox.__documentListeners.keydown || []).length,
            touchstart: (sandbox.__documentListeners.touchstart || []).length,
          },
          debugMessages: sandbox.__debugMessages,
          warnings: sandbox.__warningMessages,
        }));
        """
    )

    assert json.loads(_run_node(script)) == {
        "threw": False,
        "knownElements": [],
        "keydownListenerNames": [
            "handleGlobalKeydown",
            "enableAudioOnFirstInteraction",
        ],
        "audioUnlockListenerCounts": {
            "click": 1,
            "keydown": 2,
            "touchstart": 1,
        },
        "debugMessages": [
            "App button binding skipped: #insert-code-btn unavailable",
            "App button binding skipped: #submit-btn unavailable",
            "App button binding skipped: #close-btn unavailable",
        ],
        "warnings": [],
    }


@unittest.skipUnless(_node_available(), "node runtime unavailable")
def test_initialize_app_binds_main_buttons_when_present() -> None:
    script = _app_button_harness(
        """
        for (const id of ['insert-code-btn', 'submit-btn', 'close-btn']) {
          sandbox.__elements.set(id, sandbox.__createElement(id));
        }

        vm.runInContext('initializeApp()', sandbox);
        for (const id of ['insert-code-btn', 'submit-btn', 'close-btn']) {
          sandbox.__elements.get(id).click();
        }

        process.stdout.write(JSON.stringify({
          addCalls: Object.fromEntries(
            Array.from(sandbox.__elements.entries()).map(([id, element]) => [
              id,
              element.addCalls,
            ]),
          ),
          calls: sandbox.__calls,
          debugMessages: sandbox.__debugMessages,
          warnings: sandbox.__warningMessages,
        }));
        """
    )

    assert json.loads(_run_node(script)) == {
        "addCalls": {
            "insert-code-btn": [
                {"type": "click", "handlerName": "insertCodeFromClipboard"},
            ],
            "submit-btn": [{"type": "click", "handlerName": "submitFeedback"}],
            "close-btn": [{"type": "click", "handlerName": "closeInterface"}],
        },
        "calls": ["insert", "submit", "close"],
        "debugMessages": [],
        "warnings": [],
    }


@unittest.skipUnless(_node_available(), "node runtime unavailable")
def test_initialize_app_does_not_duplicate_page_level_bindings() -> None:
    script = _app_button_harness(
        """
        const watchedIds = [
          'insert-code-btn',
          'submit-btn',
          'close-btn',
          'code-paste-close-btn',
          'code-paste-cancel-btn',
          'code-paste-insert-btn',
          'code-paste-panel',
          'code-paste-textarea',
        ];
        for (const id of watchedIds) {
          sandbox.__elements.set(id, sandbox.__createElement(id));
        }

        vm.runInContext('initializeApp()', sandbox);
        vm.runInContext('initializeApp()', sandbox);

        for (const id of ['insert-code-btn', 'submit-btn', 'close-btn']) {
          sandbox.__elements.get(id).click();
        }

        process.stdout.write(JSON.stringify({
          addCalls: Object.fromEntries(
            watchedIds.map((id) => [
              id,
              sandbox.__elements.get(id).addCalls,
            ]),
          ),
          calls: sandbox.__calls,
          documentListeners: {
            click: (sandbox.__documentListeners.click || [])
              .map((handler) => handler.name),
            keydown: (sandbox.__documentListeners.keydown || [])
              .map((handler) => handler.name),
            touchstart: (sandbox.__documentListeners.touchstart || [])
              .map((handler) => handler.name),
          },
          warnings: sandbox.__warningMessages,
        }));
        """
    )

    assert json.loads(_run_node(script)) == {
        "addCalls": {
            "insert-code-btn": [
                {"type": "click", "handlerName": "insertCodeFromClipboard"},
            ],
            "submit-btn": [{"type": "click", "handlerName": "submitFeedback"}],
            "close-btn": [{"type": "click", "handlerName": "closeInterface"}],
            "code-paste-close-btn": [
                {"type": "click", "handlerName": "closeCodePasteModal"},
            ],
            "code-paste-cancel-btn": [
                {"type": "click", "handlerName": "closeCodePasteModal"},
            ],
            "code-paste-insert-btn": [
                {"type": "click", "handlerName": "handleCodePasteInsertClick"},
            ],
            "code-paste-panel": [
                {"type": "click", "handlerName": "handleCodePasteBackdropClick"},
            ],
            "code-paste-textarea": [],
        },
        "calls": ["insert", "submit", "close"],
        "documentListeners": {
            "click": ["enableAudioOnFirstInteraction"],
            "keydown": ["handleGlobalKeydown", "enableAudioOnFirstInteraction"],
            "touchstart": ["enableAudioOnFirstInteraction"],
        },
        "warnings": [],
    }


@unittest.skipUnless(_node_available(), "node runtime unavailable")
def test_audio_unlock_listener_set_is_single_and_self_removing() -> None:
    script = _app_button_harness(
        """
        for (const id of ['insert-code-btn', 'submit-btn', 'close-btn']) {
          sandbox.__elements.set(id, sandbox.__createElement(id));
        }
        let resumeCalls = 0;
        sandbox.notificationManager.audioContext = {
          state: 'suspended',
          resume() {
            resumeCalls += 1;
            return Promise.resolve();
          },
        };

        vm.runInContext('initializeApp()', sandbox);
        vm.runInContext('initializeApp()', sandbox);

        const unlock = sandbox.__documentListeners.click.find(
          (candidate) => candidate.name === 'enableAudioOnFirstInteraction',
        );
        unlock();
        await Promise.resolve();

        process.stdout.write(JSON.stringify({
          resumeCalls,
          listenerCounts: {
            click: (sandbox.__documentListeners.click || []).length,
            keydown: (sandbox.__documentListeners.keydown || []).length,
            touchstart: (sandbox.__documentListeners.touchstart || []).length,
          },
          removeCalls: sandbox.__documentRemoveCalls,
          debugMessages: sandbox.__debugMessages,
          warnings: sandbox.__warningMessages,
        }));
        """
    )

    assert json.loads(_run_node(script)) == {
        "resumeCalls": 1,
        "listenerCounts": {
            "click": 0,
            "keydown": 1,
            "touchstart": 0,
        },
        "removeCalls": [
            {"type": "click", "handlerName": "enableAudioOnFirstInteraction"},
            {"type": "keydown", "handlerName": "enableAudioOnFirstInteraction"},
            {"type": "touchstart", "handlerName": "enableAudioOnFirstInteraction"},
        ],
        "debugMessages": ["Audio context enabled"],
        "warnings": [],
    }


@unittest.skipUnless(_node_available(), "node runtime unavailable")
def test_reopening_code_paste_modal_preserves_original_focus_origin() -> None:
    script = _app_button_harness(
        """
        for (const id of [
          'opener',
          'feedback-text',
          'code-paste-panel',
          'code-paste-textarea',
          'code-paste-hint',
        ]) {
          sandbox.__elements.set(id, sandbox.__createElement(id));
        }

        const opener = sandbox.__elements.get('opener');
        const textarea = sandbox.__elements.get('code-paste-textarea');
        sandbox.document.activeElement = opener;

        vm.runInContext(
          'openCodePasteModal({ name: "NotAllowedError" })',
          sandbox,
        );
        sandbox.document.activeElement = textarea;
        textarea.value = 'stale draft';
        vm.runInContext(
          'openCodePasteModal({ name: "Error", message: "ClipboardEmpty" })',
          sandbox,
        );

        const beforeClose = {
          keydownListeners: (sandbox.__documentListeners.keydown || [])
            .map((handler) => handler.name),
          hintText: sandbox.__elements.get('code-paste-hint').textContent,
          modalOpen: sandbox.__elements.get('code-paste-panel')
            .classList.contains('show'),
          textareaValue: textarea.value,
        };

        vm.runInContext('closeCodePasteModal()', sandbox);

        process.stdout.write(JSON.stringify({
          beforeClose,
          focusedIds: sandbox.__focusedIds,
          keydownListenersAfterClose: (sandbox.__documentListeners.keydown || [])
            .map((handler) => handler.name),
          keydownRemoveCalls: sandbox.__documentRemoveCalls
            .filter((entry) => entry.type === 'keydown')
            .map((entry) => entry.handlerName),
          modalHidden: sandbox.__elements.get('code-paste-panel')
            .classList.contains('hidden'),
          warnings: sandbox.__warningMessages,
        }));
        """
    )

    assert json.loads(_run_node(script)) == {
        "beforeClose": {
            "keydownListeners": ["handleCodePasteModalKeydown"],
            "hintText": "status.clipboardNoText",
            "modalOpen": True,
            "textareaValue": "",
        },
        "focusedIds": ["opener"],
        "keydownListenersAfterClose": [],
        "keydownRemoveCalls": ["handleCodePasteModalKeydown"],
        "modalHidden": True,
        "warnings": [],
    }


@unittest.skipUnless(_node_available(), "node runtime unavailable")
def test_close_code_paste_modal_restores_opener_without_scroll_with_plain_fallback() -> (
    None
):
    script = _app_button_harness(
        """
        for (const id of [
          'opener',
          'code-paste-panel',
          'code-paste-textarea',
        ]) {
          sandbox.__elements.set(id, sandbox.__createElement(id));
        }

        const opener = sandbox.__elements.get('opener');
        const focusCalls = [];
        opener.focus = (options) => {
          focusCalls.push(options && options.preventScroll ? 'options' : 'plain');
          if (options && options.preventScroll) {
            throw new Error('focus options unsupported');
          }
          sandbox.document.activeElement = opener;
        };
        sandbox.document.activeElement = opener;

        vm.runInContext('openCodePasteModal()', sandbox);
        let threw = false;
        try {
          vm.runInContext('closeCodePasteModal()', sandbox);
        } catch (_err) {
          threw = true;
        }

        process.stdout.write(JSON.stringify({
          activeElementId: sandbox.document.activeElement
            ? sandbox.document.activeElement.id
            : null,
          clearedTimeouts: sandbox.__clearedTimeouts,
          focusCalls,
          threw,
          warnings: sandbox.__warningMessages,
        }));
        """
    )

    assert json.loads(_run_node(script)) == {
        "activeElementId": "opener",
        "clearedTimeouts": ["timer-1"],
        "focusCalls": ["options", "plain"],
        "threw": False,
        "warnings": [],
    }


@unittest.skipUnless(_node_available(), "node runtime unavailable")
def test_close_code_paste_modal_feedback_fallback_focuses_without_scroll() -> None:
    script = _app_button_harness(
        """
        for (const id of [
          'opener',
          'feedback-text',
          'code-paste-panel',
          'code-paste-textarea',
        ]) {
          sandbox.__elements.set(id, sandbox.__createElement(id));
        }

        const opener = sandbox.__elements.get('opener');
        const feedback = sandbox.__elements.get('feedback-text');
        const focusCalls = [];
        feedback.focus = (options) => {
          focusCalls.push(options && options.preventScroll ? 'options' : 'plain');
          sandbox.document.activeElement = feedback;
        };
        sandbox.document.activeElement = opener;

        vm.runInContext('openCodePasteModal()', sandbox);
        sandbox.__elements.delete('opener');
        let threw = false;
        try {
          vm.runInContext('closeCodePasteModal()', sandbox);
        } catch (_err) {
          threw = true;
        }

        process.stdout.write(JSON.stringify({
          activeElementId: sandbox.document.activeElement
            ? sandbox.document.activeElement.id
            : null,
          clearedTimeouts: sandbox.__clearedTimeouts,
          focusCalls,
          threw,
          warnings: sandbox.__warningMessages,
        }));
        """
    )

    assert json.loads(_run_node(script)) == {
        "activeElementId": "feedback-text",
        "clearedTimeouts": ["timer-1"],
        "focusCalls": ["options"],
        "threw": False,
        "warnings": [],
    }


@unittest.skipUnless(_node_available(), "node runtime unavailable")
def test_close_code_paste_modal_cancels_deferred_textarea_focus_after_quick_close() -> (
    None
):
    script = _app_button_harness(
        """
        for (const id of [
          'opener',
          'code-paste-panel',
          'code-paste-textarea',
        ]) {
          sandbox.__elements.set(id, sandbox.__createElement(id));
        }

        const opener = sandbox.__elements.get('opener');
        const panel = sandbox.__elements.get('code-paste-panel');
        sandbox.document.activeElement = opener;

        vm.runInContext('openCodePasteModal()', sandbox);
        const pending = sandbox.__timeoutCallbacks[0];

        vm.runInContext('closeCodePasteModal()', sandbox);
        let threw = false;
        try {
          pending.fn();
        } catch (_err) {
          threw = true;
        }

        process.stdout.write(JSON.stringify({
          activeElementId: sandbox.document.activeElement
            ? sandbox.document.activeElement.id
            : null,
          clearedTimeouts: sandbox.__clearedTimeouts,
          focusedIds: sandbox.__focusedIds,
          modalHidden: panel.classList.contains('hidden'),
          modalOpen: panel.classList.contains('show'),
          threw,
          timeoutCount: sandbox.__timeoutCallbacks.length,
          warnings: sandbox.__warningMessages,
        }));
        """
    )

    assert json.loads(_run_node(script)) == {
        "activeElementId": "opener",
        "clearedTimeouts": ["timer-1"],
        "focusedIds": ["opener"],
        "modalHidden": True,
        "modalOpen": False,
        "threw": False,
        "timeoutCount": 1,
        "warnings": [],
    }


@unittest.skipUnless(_node_available(), "node runtime unavailable")
def test_code_paste_modal_deferred_focus_uses_prevent_scroll_with_plain_fallback() -> (
    None
):
    script = _app_button_harness(
        """
        for (const id of [
          'code-paste-panel',
          'code-paste-textarea',
        ]) {
          sandbox.__elements.set(id, sandbox.__createElement(id));
        }

        const textarea = sandbox.__elements.get('code-paste-textarea');
        const focusCalls = [];
        textarea.focus = (options) => {
          focusCalls.push(options && options.preventScroll ? 'options' : 'plain');
          if (options && options.preventScroll) {
            throw new Error('focus options unsupported');
          }
          sandbox.document.activeElement = textarea;
        };

        vm.runInContext('openCodePasteModal()', sandbox);
        let threw = false;
        try {
          sandbox.__timeoutCallbacks[0].fn();
        } catch (_err) {
          threw = true;
        }

        process.stdout.write(JSON.stringify({
          activeElementId: sandbox.document.activeElement
            ? sandbox.document.activeElement.id
            : null,
          clearedTimeouts: sandbox.__clearedTimeouts,
          focusCalls,
          threw,
          timeoutCount: sandbox.__timeoutCallbacks.length,
          warnings: sandbox.__warningMessages,
        }));
        """
    )

    assert json.loads(_run_node(script)) == {
        "activeElementId": "code-paste-textarea",
        "clearedTimeouts": [],
        "focusCalls": ["options", "plain"],
        "threw": False,
        "timeoutCount": 1,
        "warnings": [],
    }


@unittest.skipUnless(_node_available(), "node runtime unavailable")
def test_code_paste_modal_deferred_focus_skips_detached_textarea() -> None:
    script = _app_button_harness(
        """
        for (const id of [
          'code-paste-panel',
          'code-paste-textarea',
        ]) {
          sandbox.__elements.set(id, sandbox.__createElement(id));
        }

        const textarea = sandbox.__elements.get('code-paste-textarea');
        let focusCalls = 0;
        textarea.focus = () => {
          focusCalls += 1;
          throw new Error('detached textarea focus should not be attempted');
        };

        vm.runInContext('openCodePasteModal()', sandbox);
        const pending = sandbox.__timeoutCallbacks[0];
        sandbox.__elements.delete('code-paste-textarea');

        let threw = false;
        try {
          pending.fn();
        } catch (_err) {
          threw = true;
        }

        process.stdout.write(JSON.stringify({
          focusCalls,
          threw,
          timeoutCount: sandbox.__timeoutCallbacks.length,
          warnings: sandbox.__warningMessages,
        }));
        """
    )

    assert json.loads(_run_node(script)) == {
        "focusCalls": 0,
        "threw": False,
        "timeoutCount": 1,
        "warnings": [],
    }


@unittest.skipUnless(_node_available(), "node runtime unavailable")
def test_reopening_code_paste_modal_ignores_stale_deferred_focus_timer() -> None:
    script = _app_button_harness(
        """
        for (const id of [
          'opener',
          'code-paste-panel',
          'code-paste-textarea',
          'code-paste-hint',
        ]) {
          sandbox.__elements.set(id, sandbox.__createElement(id));
        }

        const opener = sandbox.__elements.get('opener');
        const textarea = sandbox.__elements.get('code-paste-textarea');
        const focusCalls = [];
        textarea.focus = (options) => {
          focusCalls.push(options && options.preventScroll ? 'options' : 'plain');
          sandbox.document.activeElement = textarea;
        };
        sandbox.document.activeElement = opener;

        vm.runInContext(
          'openCodePasteModal({ name: "NotAllowedError" })',
          sandbox,
        );
        const stale = sandbox.__timeoutCallbacks[0];
        textarea.value = 'stale draft';
        vm.runInContext(
          'openCodePasteModal({ name: "Error", message: "ClipboardEmpty" })',
          sandbox,
        );
        const current = sandbox.__timeoutCallbacks[1];

        let staleThrew = false;
        try {
          stale.fn();
        } catch (_err) {
          staleThrew = true;
        }
        const focusCallsAfterStale = focusCalls.slice();

        let currentThrew = false;
        try {
          current.fn();
        } catch (_err) {
          currentThrew = true;
        }

        process.stdout.write(JSON.stringify({
          activeElementId: sandbox.document.activeElement
            ? sandbox.document.activeElement.id
            : null,
          clearedTimeouts: sandbox.__clearedTimeouts,
          currentThrew,
          focusCalls,
          focusCallsAfterStale,
          hintText: sandbox.__elements.get('code-paste-hint').textContent,
          staleThrew,
          textareaValue: textarea.value,
          timeoutCount: sandbox.__timeoutCallbacks.length,
          warnings: sandbox.__warningMessages,
        }));
        """
    )

    assert json.loads(_run_node(script)) == {
        "activeElementId": "code-paste-textarea",
        "clearedTimeouts": ["timer-1"],
        "currentThrew": False,
        "focusCalls": ["options"],
        "focusCallsAfterStale": [],
        "hintText": "status.clipboardNoText",
        "staleThrew": False,
        "textareaValue": "",
        "timeoutCount": 2,
        "warnings": [],
    }


@unittest.skipUnless(_node_available(), "node runtime unavailable")
def test_close_code_paste_modal_removes_keydown_when_panel_was_detached() -> None:
    script = _app_button_harness(
        """
        for (const id of [
          'opener',
          'code-paste-panel',
          'code-paste-textarea',
        ]) {
          sandbox.__elements.set(id, sandbox.__createElement(id));
        }

        sandbox.document.activeElement = sandbox.__elements.get('opener');
        vm.runInContext('openCodePasteModal()', sandbox);
        const pending = sandbox.__timeoutCallbacks[0];
        const keydownAfterOpen = (sandbox.__documentListeners.keydown || [])
          .map((handler) => handler.name);

        sandbox.__elements.delete('code-paste-panel');
        let threw = false;
        try {
          vm.runInContext('closeCodePasteModal()', sandbox);
          pending.fn();
        } catch (_err) {
          threw = true;
        }

        process.stdout.write(JSON.stringify({
          clearedTimeouts: sandbox.__clearedTimeouts,
          threw,
          keydownAfterOpen,
          keydownAfterDetachedClose: (sandbox.__documentListeners.keydown || [])
            .map((handler) => handler.name),
          keydownRemoveCalls: sandbox.__documentRemoveCalls
            .filter((entry) => entry.type === 'keydown')
            .map((entry) => entry.handlerName),
          focusedIds: sandbox.__focusedIds,
          timeoutCount: sandbox.__timeoutCallbacks.length,
          warnings: sandbox.__warningMessages,
        }));
        """
    )

    assert json.loads(_run_node(script)) == {
        "clearedTimeouts": ["timer-1"],
        "threw": False,
        "keydownAfterOpen": ["handleCodePasteModalKeydown"],
        "keydownAfterDetachedClose": [],
        "keydownRemoveCalls": ["handleCodePasteModalKeydown"],
        "focusedIds": [],
        "timeoutCount": 1,
        "warnings": [],
    }
