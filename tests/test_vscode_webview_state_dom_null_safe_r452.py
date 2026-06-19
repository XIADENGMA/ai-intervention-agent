"""R452: VS Code webview state toggles should tolerate missing chrome nodes."""

from __future__ import annotations

import json
import shutil
import subprocess
import textwrap
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
WEBVIEW_UI_JS = REPO_ROOT / "packages" / "vscode" / "webview-ui.js"


def _node_available() -> bool:
    return shutil.which("node") is not None


def _read_source() -> str:
    return WEBVIEW_UI_JS.read_text(encoding="utf-8")


def _extract_function(source: str, name: str) -> str:
    marker = f"function {name}("
    start = source.index(marker)
    brace = source.index("{", start)
    depth = 0
    for index in range(brace, len(source)):
        char = source[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return source[start : index + 1]
    raise AssertionError(f"Could not extract {name}()")


def _run_node(script: str) -> str:
    if not _node_available():
        raise AssertionError("node runtime unavailable")
    completed = subprocess.run(
        ["node", "-e", script],
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout


def test_webview_state_toggles_no_longer_chain_getelementbyid_classlist() -> None:
    source = _read_source()

    for fragment in (
        "document.getElementById('tasksTabsContainer').classList.remove('hidden')",
        "document.getElementById('loadingState').classList.add('hidden')",
        "document.getElementById('noContentState').classList.add('hidden')",
        "document.getElementById('feedbackForm').classList.remove('hidden')",
        "document.getElementById('feedbackForm').classList.add('hidden')",
        "document.getElementById('noContentState').classList.remove('hidden')",
    ):
        assert fragment not in source

    helper = _extract_function(source, "setHiddenById")
    assert "const element = document.getElementById(id)" in helper
    assert "if (!element || !element.classList) return null" in helper


def test_set_hidden_by_id_skips_missing_nodes_and_updates_present_nodes() -> None:
    source = _read_source()
    helper = _extract_function(source, "setHiddenById")
    script = textwrap.dedent(
        f"""
        function makeClassList() {{
          const values = new Set();
          return {{
            add(name) {{ values.add(name); }},
            remove(name) {{ values.delete(name); }},
            toArray() {{ return Array.from(values).sort(); }},
          }};
        }}
        const elements = {{
          present: {{ classList: makeClassList() }},
        }};
        const document = {{
          getElementById(id) {{
            return Object.prototype.hasOwnProperty.call(elements, id)
              ? elements[id]
              : null;
          }},
        }};

        {helper}

        const missing = setHiddenById('missing', true);
        const hidden = setHiddenById('present', true);
        const shown = setHiddenById('present', false);

        process.stdout.write(JSON.stringify({{
          missing,
          hiddenIsElement: hidden === elements.present,
          shownIsElement: shown === elements.present,
          classes: elements.present.classList.toArray(),
        }}));
        """
    )

    assert json.loads(_run_node(script)) == {
        "missing": None,
        "hiddenIsElement": True,
        "shownIsElement": True,
        "classes": [],
    }


def test_show_tabs_and_show_no_content_survive_missing_state_nodes() -> None:
    source = _read_source()
    parts = "\n\n".join(
        _extract_function(source, name)
        for name in ("setHiddenById", "hideTabs", "showTabs", "showNoContent")
    )
    script = textwrap.dedent(
        f"""
        const calls = [];
        const document = {{
          getElementById() {{
            return null;
          }},
        }};
        let noContentLottieRetryAttempt = 5;
        let lottieInitWarned = true;
        function clearNoContentLottieTimers() {{ calls.push('clearTimers'); }}
        function installNoContentLottieRecoveryHandlers() {{ calls.push('installRecovery'); }}
        function initNoContentHourglassAnimation() {{ calls.push('initHourglass'); }}
        function stopCountdown() {{ calls.push('stopCountdown'); }}

        {parts}

        let threw = false;
        try {{
          showTabs();
          showNoContent();
        }} catch (_error) {{
          threw = true;
        }}

        process.stdout.write(JSON.stringify({{
          threw,
          noContentLottieRetryAttempt,
          lottieInitWarned,
          calls,
        }}));
        """
    )

    assert json.loads(_run_node(script)) == {
        "threw": False,
        "noContentLottieRetryAttempt": 0,
        "lottieInitWarned": False,
        "calls": [
            "clearTimers",
            "installRecovery",
            "initHourglass",
            "stopCountdown",
        ],
    }


def test_render_task_tabs_missing_container_does_not_block_nonempty_tasks() -> None:
    source = _read_source()
    parts = "\n\n".join(
        _extract_function(source, name)
        for name in (
            "clearAllTabCountdowns",
            "getTaskIdString",
            "getOpenTaskId",
            "pickOpenTaskId",
            "reconcileActiveTaskId",
            "renderTaskTabs",
        )
    )
    script = textwrap.dedent(
        f"""
        const document = {{
          getElementById(id) {{
            if (id === 'tasksTabsContainer') return null;
            throw new Error('unexpected id: ' + id);
          }},
        }};
        const logs = [];
        let allTasks = [{{ task_id: 'task-1', status: 'active' }}];
        let activeTaskId = null;
        let lastTasksHash = 'stale';
        let lastTaskIds = new Set();
        let hasInitializedTaskIdTracking = false;
        let tabCountdownTimers = {{ old: 123 }};
        let tabCountdownRemaining = {{ old: 5 }};
        const cleared = [];
        function clearInterval(id) {{ cleared.push(id); }}
        function log(message) {{ logs.push(String(message)); }}
        function schedulePersistUiState() {{ logs.push('persist'); }}

        {parts}

        let threw = false;
        try {{
          renderTaskTabs();
        }} catch (_error) {{
          threw = true;
        }}

        process.stdout.write(JSON.stringify({{
          threw,
          allTaskCount: allTasks.length,
          activeTaskId,
          lastTasksHash,
          lastTaskIds: Array.from(lastTaskIds),
          hasInitializedTaskIdTracking,
          tabCountdownTimerKeys: Object.keys(tabCountdownTimers),
          tabCountdownRemainingKeys: Object.keys(tabCountdownRemaining),
          cleared,
          logs,
        }}));
        """
    )

    assert json.loads(_run_node(script)) == {
        "threw": False,
        "allTaskCount": 1,
        "activeTaskId": "task-1",
        "lastTasksHash": "",
        "lastTaskIds": ["task-1"],
        "hasInitializedTaskIdTracking": True,
        "tabCountdownTimerKeys": [],
        "tabCountdownRemainingKeys": [],
        "cleared": [123],
        "logs": ["persist", "Skipped task tabs render: tasksTabsContainer not found"],
    }


def test_update_ui_state_chrome_missing_does_not_block_task_render_path() -> None:
    source = _read_source()
    parts = "\n\n".join(
        _extract_function(source, name) for name in ("setHiddenById", "updateUI")
    )
    script = textwrap.dedent(
        f"""
        function makeClassList() {{
          const values = new Set();
          return {{
            add(name) {{ values.add(name); }},
            remove(name) {{ values.delete(name); }},
            toArray() {{ return Array.from(values).sort(); }},
          }};
        }}
        const elements = {{
          markdownContent: {{ innerHTML: '' }},
          optionsSection: {{ classList: makeClassList() }},
          optionsContainer: {{ innerHTML: '' }},
        }};
        const document = {{
          getElementById(id) {{
            return Object.prototype.hasOwnProperty.call(elements, id)
              ? elements[id]
              : null;
          }},
        }};
        let currentConfig = null;
        let lastRenderedPrompt = '';
        let lastRenderedOptions = 'old';
        let markdownRenderSeq = 0;
        let noContentLottieRetryAttempt = 3;
        let countdownStopped = false;
        const logs = [];
        function destroyNoContentHourglassAnimation() {{ logs.push('destroyHourglass'); }}
        function stopCountdown() {{ countdownStopped = true; }}
        function log(message) {{ logs.push(String(message)); }}
        function restoreLocalStateForTask(taskId) {{ logs.push('restore:' + taskId); }}

        {parts}

        let threw = false;
        try {{
          updateUI({{ task_id: 't1', prompt: '', predefined_options: [] }});
        }} catch (_error) {{
          threw = true;
        }}

        process.stdout.write(JSON.stringify({{
          threw,
          currentTaskId: currentConfig && currentConfig.task_id,
          lastRenderedOptions,
          optionsSectionClasses: elements.optionsSection.classList.toArray(),
          noContentLottieRetryAttempt,
          countdownStopped,
          logs,
        }}));
        """
    )

    assert json.loads(_run_node(script)) == {
        "threw": False,
        "currentTaskId": "t1",
        "lastRenderedOptions": "",
        "optionsSectionClasses": ["hidden"],
        "noContentLottieRetryAttempt": 0,
        "countdownStopped": True,
        "logs": ["destroyHourglass", "restore:t1", "UI updated"],
    }


def test_update_ui_missing_options_container_does_not_block_task_render_path() -> None:
    source = _read_source()
    parts = "\n\n".join(
        _extract_function(source, name) for name in ("setHiddenById", "updateUI")
    )
    script = textwrap.dedent(
        f"""
        function makeClassList() {{
          const values = new Set();
          return {{
            add(name) {{ values.add(name); }},
            remove(name) {{ values.delete(name); }},
            toArray() {{ return Array.from(values).sort(); }},
          }};
        }}
        const elements = {{
          markdownContent: {{ innerHTML: '' }},
          optionsSection: {{ classList: makeClassList() }},
        }};
        const document = {{
          getElementById(id) {{
            return Object.prototype.hasOwnProperty.call(elements, id)
              ? elements[id]
              : null;
          }},
        }};
        let currentConfig = null;
        let lastRenderedPrompt = '';
        let lastRenderedOptions = 'stale-options-cache';
        let markdownRenderSeq = 0;
        let noContentLottieRetryAttempt = 3;
        let countdownStopped = false;
        const logs = [];
        function destroyNoContentHourglassAnimation() {{ logs.push('destroyHourglass'); }}
        function stopCountdown() {{ countdownStopped = true; }}
        function log(message) {{ logs.push(String(message)); }}
        function restoreLocalStateForTask(taskId) {{ logs.push('restore:' + taskId); }}

        {parts}

        let threw = false;
        try {{
          updateUI({{
            task_id: 't-options',
            prompt: '',
            predefined_options: ['Approve'],
            predefined_options_defaults: [true],
          }});
        }} catch (_error) {{
          threw = true;
        }}

        process.stdout.write(JSON.stringify({{
          threw,
          currentTaskId: currentConfig && currentConfig.task_id,
          lastRenderedOptions,
          optionsSectionClasses: elements.optionsSection.classList.toArray(),
          noContentLottieRetryAttempt,
          countdownStopped,
          logs,
        }}));
        """
    )

    assert json.loads(_run_node(script)) == {
        "threw": False,
        "currentTaskId": "t-options",
        "lastRenderedOptions": "",
        "optionsSectionClasses": ["hidden"],
        "noContentLottieRetryAttempt": 0,
        "countdownStopped": True,
        "logs": ["destroyHourglass", "restore:t-options", "UI updated"],
    }


def test_update_ui_present_options_container_still_rebuilds_default_checked_options() -> (
    None
):
    source = _read_source()
    parts = "\n\n".join(
        _extract_function(source, name) for name in ("setHiddenById", "updateUI")
    )
    script = textwrap.dedent(
        f"""
        function makeClassList(initial) {{
          const values = new Set(initial || []);
          return {{
            add(name) {{ values.add(name); }},
            remove(name) {{ values.delete(name); }},
            toggle(name, force) {{
              if (force) values.add(name);
              else values.delete(name);
            }},
            toArray() {{ return Array.from(values).sort(); }},
          }};
        }}
        function makeOptionDiv() {{
          const checkbox = {{
            checked: false,
            listeners: [],
            addEventListener(type, handler) {{
              this.listeners.push({{ type, handler }});
            }},
            click() {{ this.checked = !this.checked; }},
          }};
          const label = {{}};
          return {{
            className: '',
            innerHTML: '',
            checkbox,
            label,
            classList: makeClassList(),
            listeners: [],
            addEventListener(type, handler) {{
              this.listeners.push({{ type, handler }});
            }},
            querySelector(selector) {{
              if (selector === 'input') return checkbox;
              if (selector === 'label') return label;
              return null;
            }},
          }};
        }}
        const optionChildren = [];
        const elements = {{
          markdownContent: {{ innerHTML: '' }},
          optionsSection: {{ classList: makeClassList(['hidden']) }},
          optionsContainer: {{
            innerHTML: 'stale',
            appendChild(child) {{ optionChildren.push(child); }},
          }},
        }};
        const document = {{
          getElementById(id) {{
            return Object.prototype.hasOwnProperty.call(elements, id)
              ? elements[id]
              : null;
          }},
          createElement(tag) {{
            if (tag !== 'div') throw new Error('unexpected tag: ' + tag);
            return makeOptionDiv();
          }},
        }};
        let currentConfig = null;
        let lastRenderedPrompt = '';
        let lastRenderedOptions = 'old-options';
        let markdownRenderSeq = 0;
        let noContentLottieRetryAttempt = 3;
        let countdownStopped = false;
        let taskOptionsStates = {{}};
        const logs = [];
        function destroyNoContentHourglassAnimation() {{ logs.push('destroyHourglass'); }}
        function stopCountdown() {{ countdownStopped = true; }}
        function log(message) {{ logs.push(String(message)); }}
        function restoreLocalStateForTask(taskId) {{ logs.push('restore:' + taskId); }}
        function escapeHtml(value) {{ return String(value).replace(/&/g, '&amp;'); }}

        {parts}

        updateUI({{
          task_id: 't-options',
          prompt: '',
          predefined_options: ['Approve', 'Escalate'],
          predefined_options_defaults: [false, true],
        }});

        process.stdout.write(JSON.stringify({{
          lastRenderedOptions,
          optionsSectionClasses: elements.optionsSection.classList.toArray(),
          optionsContainerInnerHTML: elements.optionsContainer.innerHTML,
          childCount: optionChildren.length,
          checked: optionChildren.map(child => child.checkbox.checked),
          selectedClasses: optionChildren.map(child => child.classList.toArray()),
          inputListenerCounts: optionChildren.map(child => child.checkbox.listeners.length),
          optionListenerCounts: optionChildren.map(child => child.listeners.length),
          noContentLottieRetryAttempt,
          countdownStopped,
          logs,
        }}));
        """
    )

    assert json.loads(_run_node(script)) == {
        "lastRenderedOptions": 't-options|["Approve","Escalate"]',
        "optionsSectionClasses": [],
        "optionsContainerInnerHTML": "",
        "childCount": 2,
        "checked": [False, True],
        "selectedClasses": [[], ["selected"]],
        "inputListenerCounts": [1, 1],
        "optionListenerCounts": [1, 1],
        "noContentLottieRetryAttempt": 0,
        "countdownStopped": True,
        "logs": ["destroyHourglass", "restore:t-options", "UI updated"],
    }
