"""R551 regression coverage for allocation-light new-task notifications."""

from __future__ import annotations

import json
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
NOTIFICATION_MANAGER_JS = (
    REPO_ROOT
    / "src"
    / "ai_intervention_agent"
    / "static"
    / "js"
    / "notification-manager.js"
)


def _source() -> str:
    return NOTIFICATION_MANAGER_JS.read_text(encoding="utf-8")


def _extract_function(source: str, marker: str) -> str:
    start = source.find(marker)
    assert start != -1, f"Cannot find function marker: {marker}"
    if marker.endswith("{"):
        open_brace = start + len(marker) - 1
    else:
        open_brace = source.find("{", start + len(marker))
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


def _notification_harness(case_js: str) -> str:
    return textwrap.dedent(
        f"""
        const fs = require('fs');
        const vm = require('vm');
        const code = fs.readFileSync({str(NOTIFICATION_MANAGER_JS)!r}, 'utf8')
          + '\\nglobalThis.__notificationManager = notificationManager;';

        const visualHintCounts = [];
        let playSoundCalls = 0;

        const sandbox = {{
          Audio: function Audio() {{}},
          Blob: function Blob(parts) {{
            this.size = String(parts && parts[0] ? parts[0] : '').length;
          }},
          CustomEvent: function CustomEvent(type, init) {{
            this.type = type;
            this.detail = init && init.detail;
          }},
          Date,
          Error,
          JSON,
          Map,
          Math,
          Notification: {{ permission: 'granted' }},
          Number,
          Object,
          Promise,
          RegExp,
          String,
          console: {{
            debug() {{}},
            error() {{}},
            info() {{}},
            log() {{}},
            warn() {{}},
          }},
          document: {{
            title: 'AI Intervention Agent',
          }},
          localStorage: {{
            getItem() {{ return null; }},
            setItem() {{}},
            removeItem() {{}},
          }},
          navigator: {{ userAgent: 'node' }},
          setInterval() {{ return 1; }},
          clearInterval() {{}},
          setTimeout(fn) {{ fn(); return 1; }},
          clearTimeout() {{}},
          dispatchEvent() {{}},
          isSecureContext: true,
          showNewTaskVisualHint(count) {{
            visualHintCounts.push(count);
          }},
          __visualHintCounts: visualHintCounts,
          __playSoundCalls() {{
            return playSoundCalls;
          }},
          __incrementPlaySoundCalls() {{
            playSoundCalls += 1;
          }},
        }};
        sandbox.window = sandbox;

        vm.createContext(sandbox);
        vm.runInContext(code, sandbox);

        (async () => {{
        {textwrap.indent(case_js, "  ")}
        }})().catch((err) => {{
          console.error(err && err.stack ? err.stack : err);
          process.exit(1);
        }});
        """
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


def test_notify_new_tasks_uses_lazy_task_id_collection() -> None:
    body = _extract_function(_source(), "async notifyNewTasks(event = {}) {")

    assert ".filter(Boolean)" not in body
    assert "let taskIds = null" in body
    assert "let taskIdCount = 0" in body
    assert "if (!(i in taskIdsRaw)) continue" in body
    assert "if (taskIds === null) taskIds = []" in body


@pytest.mark.skipif(shutil.which("node") is None, reason="node runtime unavailable")
def test_notify_new_tasks_counts_truthy_ids_without_filter_array() -> None:
    script = _notification_harness(
        """
        const manager = sandbox.__notificationManager;
        manager.playSound = async () => {
          sandbox.__incrementPlaySoundCalls();
        };

        const result = await manager.notifyNewTasks({
          taskIds: [null, 'task-a', 0, '', 'task-b', false],
        });

        process.stdout.write(JSON.stringify({
          result,
          visualHintCounts: sandbox.__visualHintCounts,
          playSoundCalls: sandbox.__playSoundCalls(),
        }));
        """
    )

    assert json.loads(_run_node(script)) == {
        "result": {
            "title": "AI Intervention Agent",
            "message": "Received 2 new task(s)",
            "count": 2,
            "taskIds": ["task-a", "task-b"],
        },
        "visualHintCounts": [2],
        "playSoundCalls": 1,
    }


@pytest.mark.skipif(shutil.which("node") is None, reason="node runtime unavailable")
def test_notify_new_tasks_preserves_sparse_array_filter_semantics() -> None:
    script = _notification_harness(
        """
        const manager = sandbox.__notificationManager;
        manager.playSound = async () => {
          sandbox.__incrementPlaySoundCalls();
        };
        const taskIds = [];
        taskIds[2] = 'task-sparse';

        const result = await manager.notifyNewTasks({ taskIds });

        process.stdout.write(JSON.stringify({
          result,
          visualHintCounts: sandbox.__visualHintCounts,
          playSoundCalls: sandbox.__playSoundCalls(),
        }));
        """
    )

    assert json.loads(_run_node(script)) == {
        "result": {
            "title": "AI Intervention Agent",
            "message": "New task added: task-sparse",
            "count": 1,
            "taskIds": ["task-sparse"],
        },
        "visualHintCounts": [1],
        "playSoundCalls": 1,
    }


@pytest.mark.skipif(shutil.which("node") is None, reason="node runtime unavailable")
def test_notify_new_tasks_keeps_count_override_with_empty_task_ids() -> None:
    script = _notification_harness(
        """
        const manager = sandbox.__notificationManager;
        manager.playSound = async () => {
          sandbox.__incrementPlaySoundCalls();
        };

        const result = await manager.notifyNewTasks({
          count: 2.8,
          taskIds: [0, '', false, null],
          title: 'Custom',
        });

        process.stdout.write(JSON.stringify({
          result,
          visualHintCounts: sandbox.__visualHintCounts,
          playSoundCalls: sandbox.__playSoundCalls(),
        }));
        """
    )

    assert json.loads(_run_node(script)) == {
        "result": {
            "title": "Custom",
            "message": "Received 2 new task(s)",
            "count": 2,
            "taskIds": [],
        },
        "visualHintCounts": [2],
        "playSoundCalls": 1,
    }
