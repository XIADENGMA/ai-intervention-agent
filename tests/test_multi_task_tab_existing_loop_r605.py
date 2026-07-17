"""R605 regression coverage for task-tab existing NodeList scans."""

from __future__ import annotations

import json
import re
import unittest

from tests.test_multi_task_poll_controller_lifecycle_r452 import (
    MULTI_TASK_JS,
    _node_available,
    _run_node,
)


def _source() -> str:
    return MULTI_TASK_JS.read_text(encoding="utf-8")


def _extract_function_body(source: str, name: str) -> str:
    marker = f"function {name}("
    start = source.find(marker)
    assert start >= 0, f"missing function {name}"
    brace_open = source.find("{", start)
    assert brace_open >= 0, f"missing opening brace for {name}"

    depth = 0
    in_str: str | None = None
    in_template = False
    in_line_comment = False
    in_block_comment = False
    i = brace_open
    while i < len(source):
        ch = source[i]
        nxt = source[i + 1] if i + 1 < len(source) else ""

        if in_line_comment:
            if ch == "\n":
                in_line_comment = False
            i += 1
            continue
        if in_block_comment:
            if ch == "*" and nxt == "/":
                in_block_comment = False
                i += 2
                continue
            i += 1
            continue
        if in_str is not None:
            if ch == "\\":
                i += 2
                continue
            if ch == in_str:
                in_str = None
            i += 1
            continue
        if in_template:
            if ch == "\\":
                i += 2
                continue
            if ch == "`":
                in_template = False
            i += 1
            continue

        if ch == "/" and nxt == "/":
            in_line_comment = True
            i += 2
            continue
        if ch == "/" and nxt == "*":
            in_block_comment = True
            i += 2
            continue
        if ch in ('"', "'"):
            in_str = ch
            i += 1
            continue
        if ch == "`":
            in_template = True
            i += 1
            continue

        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return source[brace_open : i + 1]
        i += 1

    raise AssertionError(f"unterminated function {name}")


def test_tab_render_state_existing_tabs_uses_indexed_scan() -> None:
    body = _extract_function_body(_source(), "_buildTaskTabRenderState")

    assert "existingTabs.forEach" not in body
    assert "const existingTabCount = existingTabs.length;" in body
    assert "for (let index = 0; index < existingTabCount; index += 1)" in body
    assert "if (!(index in existingTabs)) continue;" in body
    assert "const tab = existingTabs[index];" in body
    assert re.search(
        r"const taskId = tab && tab\.dataset \? tab\.dataset\.taskId : undefined;"
        r"\s+existingTaskIds\.push\(taskId\);"
        r"\s+existingTaskIdSet\.add\(taskId\);",
        body,
    )


@unittest.skipUnless(_node_available(), "node runtime unavailable")
def test_tab_render_state_scans_existing_tabs_without_nodelist_foreach() -> None:
    script = f"""
    const fs = require('fs');
    const vm = require('vm');
    const source = fs.readFileSync({json.dumps(str(MULTI_TASK_JS))}, 'utf8');
    const context = {{
      console: {{ log() {{}}, warn() {{}}, error() {{}}, debug() {{}} }},
      setTimeout() {{ return 1; }},
      clearTimeout() {{}},
      setInterval() {{ return 1; }},
      clearInterval() {{}},
      URL,
      URLSearchParams,
      Math,
      Date,
      window: {{
        location: {{ href: 'http://localhost/', search: '' }},
        addEventListener() {{}},
      }},
      document: {{
        addEventListener() {{}},
        getElementById() {{ return null; }},
        querySelectorAll() {{ return []; }},
        hidden: false,
        readyState: 'complete',
      }},
      navigator: {{}},
    }};
    context.window.window = context.window;
    context.window.document = context.document;
    vm.createContext(context);
    vm.runInContext(source, context, {{ filename: 'multi_task.js' }});

    let queryCount = 0;
    const existingTabs = {{
      0: {{ dataset: {{ taskId: 'old' }} }},
      2: {{ dataset: {{ taskId: 'keep' }} }},
      length: 3,
      forEach() {{
        throw new Error('existingTabs.forEach must not be used');
      }},
    }};
    const tabsContainer = {{
      querySelectorAll(selector) {{
        queryCount += 1;
        if (selector !== '.task-tab:not(.task-tab-exit)') {{
          throw new Error('unexpected selector: ' + selector);
        }}
        return existingTabs;
      }},
    }};
    const state = context._buildTaskTabRenderState(
      [
        {{ task_id: 'new', status: 'pending' }},
        {{ task_id: 'done', status: 'completed' }},
        {{ task_id: 'keep', status: 'active' }},
      ],
      tabsContainer,
    );

    process.stdout.write(JSON.stringify({{
      queryCount,
      incompleteTaskIds: state.incompleteTaskIds,
      existingTaskIds: state.existingTaskIds,
      needsRebuild: state.needsRebuild,
      removedIds: state.removedIds,
      addedTaskIds: state.addedTasks.map((task) => task.task_id),
      existingTabsIdentity: state.existingTabs === existingTabs,
      hasSparseSlot: Object.prototype.hasOwnProperty.call(existingTabs, '1'),
    }}));
    """

    assert json.loads(_run_node(script)) == {
        "queryCount": 1,
        "incompleteTaskIds": ["new", "keep"],
        "existingTaskIds": ["old", "keep"],
        "needsRebuild": True,
        "removedIds": ["old"],
        "addedTaskIds": ["new"],
        "existingTabsIdentity": True,
        "hasSparseSlot": False,
    }
