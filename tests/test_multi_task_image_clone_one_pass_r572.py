"""R572: multi_task image state clones avoid Array.map callbacks."""

from __future__ import annotations

import json
import shutil
import subprocess
import textwrap
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
MULTI_TASK_JS = (
    REPO_ROOT / "src" / "ai_intervention_agent" / "static" / "js" / "multi_task.js"
)


def _node_available() -> bool:
    return shutil.which("node") is not None


def _run_node(script: str) -> dict[str, object]:
    if not _node_available():
        raise AssertionError("node runtime unavailable")
    completed = subprocess.run(
        ["node", "-e", script],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


def _extract_function(source: str, name: str) -> str:
    marker = f"function {name}("
    start = source.index(marker)
    body_start = source.index("{", start)
    depth = 0
    for index in range(body_start, len(source)):
        char = source[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return source[body_start + 1 : index]
    raise AssertionError(f"function body not found for {name}")


def test_multi_task_image_clone_call_sites_use_shared_one_pass_helper() -> None:
    source = MULTI_TASK_JS.read_text(encoding="utf-8")
    helper = _extract_function(source, "cloneTaskImagesForState")
    switch_task = _extract_function(source, "switchTask")
    load_details = _extract_function(source, "loadTaskDetails")

    assert "selectedImages.map" not in source
    assert "taskImages[taskId].map" not in source
    assert ".map((img) => ({ ...img }))" not in source
    assert "new Array(imageCount)" in helper
    assert "for (let imageIndex = 0; imageIndex < imageCount;" in helper
    assert "if (!(imageIndex in images)) continue;" in helper
    assert "clonedImages[imageIndex] = { ...images[imageIndex] };" in helper
    assert (
        "taskImages[activeTaskId] = cloneTaskImagesForState(selectedImages)"
        in switch_task
    )
    assert (
        "selectedImages = cloneTaskImagesForState(taskImages[taskId])" in load_details
    )


def test_clone_task_images_for_state_preserves_map_clone_boundaries() -> None:
    script = textwrap.dedent(
        f"""
        const fs = require('fs');
        const vm = require('vm');
        const path = {json.dumps(str(MULTI_TASK_JS))};
        const source = fs.readFileSync(path, 'utf8');
        const context = {{
          Array,
          CustomEvent: function CustomEvent(type, init) {{
            this.type = type;
            this.detail = init && init.detail;
          }},
          Date,
          Error,
          JSON,
          Math,
          Number,
          Object,
          Promise,
          Set,
          String,
          Symbol,
          URL,
          URLSearchParams,
          console: {{ log() {{}}, warn() {{}}, error() {{}}, debug() {{}} }},
          fetch: async () => ({{ ok: true, json: async () => ({{ success: true }}) }}),
          fetchWithTimeout: () => new Promise(() => {{}}),
          setTimeout() {{ return 1; }},
          clearTimeout() {{}},
          setInterval() {{ return 1; }},
          clearInterval() {{}},
          location: {{
            href: 'http://127.0.0.1/',
            origin: 'http://127.0.0.1',
            pathname: '/',
            search: '',
          }},
          addEventListener() {{}},
          removeEventListener() {{}},
          dispatchEvent() {{}},
          document: {{
            addEventListener() {{}},
            getElementById() {{ return null; }},
            querySelectorAll() {{ return []; }},
            hidden: false,
            readyState: 'complete',
          }},
          navigator: {{}},
          currentTasks: [],
          activeTaskId: null,
          taskCountdowns: {{}},
          tasksPollingTimer: null,
          taskTextareaContents: {{}},
          taskOptionsStates: {{}},
          taskImages: {{}},
          pendingNewTaskCount: 0,
          newTaskHintTimer: null,
          tasksHealthCheckTimer: null,
          hasLoadedTaskSnapshot: true,
          serverTimeOffset: 0,
          taskDeadlines: {{}},
          feedbackPrompts: {{}},
          autoSubmitAttempted: {{}},
          selectedImages: [],
          AIIA_DEBUG: false,
          AIIA_I18N: {{ t: (key) => key }},
        }};
        context.window = context;
        context.globalThis = context;
        vm.createContext(context);
        vm.runInContext(source, context, {{ filename: 'multi_task.js' }});

        const originalMap = Array.prototype.map;
        try {{
          Array.prototype.map = function () {{ throw new Error('map must not be called'); }};
          const symbolKey = Symbol('blob');
          const sourceImages = [];
          sourceImages[0] = Object.create({{ inherited: 'skip' }});
          sourceImages[0].id = 'a';
          sourceImages[0].url = 'blob:a';
          Object.defineProperty(sourceImages[0], 'hidden', {{
            value: 'skip',
            enumerable: false,
          }});
          sourceImages[2] = undefined;
          sourceImages[3] = null;
          sourceImages[4] = {{ id: 'b', nested: {{ keep: true }} }};
          sourceImages[4][symbolKey] = 'symbol-copy';

          const cloned = vm.runInContext(
            'cloneTaskImagesForState(globalThis.__sourceImages)',
            Object.assign(context, {{ __sourceImages: sourceImages }}),
          );

          process.stdout.write(JSON.stringify({{
            length: cloned.length,
            hasHole: !Object.prototype.hasOwnProperty.call(cloned, 1),
            zero: cloned[0],
            zeroNotSame: cloned[0] !== sourceImages[0],
            zeroHasInherited: Object.prototype.hasOwnProperty.call(cloned[0], 'inherited'),
            zeroHasHidden: Object.prototype.hasOwnProperty.call(cloned[0], 'hidden'),
            two: cloned[2],
            three: cloned[3],
            fourNotSame: cloned[4] !== sourceImages[4],
            nestedSame: cloned[4].nested === sourceImages[4].nested,
            symbolCopied: cloned[4][symbolKey],
          }}));
        }} finally {{
          Array.prototype.map = originalMap;
        }}
        """
    )

    assert _run_node(script) == {
        "length": 5,
        "hasHole": True,
        "zero": {"id": "a", "url": "blob:a"},
        "zeroNotSame": True,
        "zeroHasInherited": False,
        "zeroHasHidden": False,
        "two": {},
        "three": {},
        "fourNotSame": True,
        "nestedSame": True,
        "symbolCopied": "symbol-copy",
    }
