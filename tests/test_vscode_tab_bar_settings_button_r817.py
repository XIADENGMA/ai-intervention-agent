"""R817: in a narrow VS Code side bar the task tabs neither sit on top of the settings button nor scroll it away.

TODO.md asked whether, in a narrow side bar, the tabs of the panel "may cover the settings
button on the right".  They do, and they do worse.  A real-Chrome pass over the panel's real
template, script and stylesheet (seven tasks, widths 200, 260, 300 and 360 px, the tab strip
scrolled to its start, its middle and its end) found two defects:

* **The gear sits on top of a tab.**  ``.tabs-container`` was the scroller, and the gear a
  ``position: absolute`` child of it.  The 34 px of right padding that was meant to keep the
  tabs clear of the gear only exists at the *end* of the scrollable content, so at the start
  of the strip the tabs run under the gear: it covered most of the third tab (a 22 x 22 px
  overlap, 484 px^2, at every width).
* **The gear scrolls away.**  An absolutely positioned child of a scroll container scrolls
  with its content, so scrolling the strip to the tabs further right moved the gear out of the
  bar (x = -167 px at 300 px with the strip in its middle, -306 px at its end).  The settings
  stayed out of reach until the strip was scrolled back.

The tabs now scroll in an element of their own (``.tabs-scroll``, ``flex: 1 1 auto`` with
``min-width: 0``), the gear is an ordinary flex item after it, and ``.tabs-container`` no longer
scrolls and no longer reserves room for a gear that is not on top of it.  The panel's second
gear (``.no-content-settings-btn``, in the empty state, where there are no tabs) keeps its
absolute position, which it used to inherit from the rule that is now gone.

The tests read the template, the stylesheet and ``renderTaskTabs`` (no browser in CI): the
template puts the scroller in front of the gear and nothing else in between, the stylesheet
makes the bar a non-scrolling row, the scroller the part that takes the remaining room and the
gear a flow item that does not shrink, and a run of ``renderTaskTabs`` against a small DOM
stand-in puts the tabs into the scroller, and into the bar itself when a page has no scroller.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import textwrap
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
WEBVIEW_CSS = REPO_ROOT / "packages" / "vscode" / "webview.css"
WEBVIEW_TS = REPO_ROOT / "packages" / "vscode" / "webview.ts"
WEBVIEW_UI_JS = REPO_ROOT / "packages" / "vscode" / "webview-ui.js"
GEAR_WIDTH_PX = 22

Rule = tuple[str, dict[str, str]]


def _rules() -> list[Rule]:
    css = re.sub(r"/\*.*?\*/", "", WEBVIEW_CSS.read_text(encoding="utf-8"), flags=re.S)
    rules: list[Rule] = []
    for match in re.finditer(r"([^{}]+)\{([^{}]*)\}", css):
        selectors = match.group(1).strip()
        if selectors.startswith("@"):
            continue
        declarations: dict[str, str] = {}
        for declaration in match.group(2).split(";"):
            name, separator, value = declaration.partition(":")
            if separator:
                declarations[name.strip().lower()] = " ".join(value.split())
        for selector in selectors.split(","):
            rules.append((" ".join(selector.split()), declarations))
    return rules


RULES = _rules()


def _merged(selector: str) -> dict[str, str]:
    """Every declaration of the rules whose selector is exactly ``selector``, later wins."""
    merged: dict[str, str] = {}
    for rule_selector, declarations in RULES:
        if rule_selector == selector:
            merged.update(declarations)
    assert merged, f"no rule for {selector}"
    return merged


def _padding_right(value: str) -> float:
    tokens = value.split()
    right = tokens[1] if len(tokens) > 1 else tokens[0]
    match = re.fullmatch(r"(\d+(?:\.\d+)?)(?:px)?", right)
    assert match, value
    return float(match.group(1))


def _extract_function(source: str, name: str) -> str:
    start = source.index(f"function {name}(")
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
    assert shutil.which("node") is not None, "node runtime unavailable"
    completed = subprocess.run(
        ["node", "-e", script], check=True, capture_output=True, text=True
    )
    return completed.stdout


class TestTemplate:
    def test_the_tabs_have_a_scroller_of_their_own_in_front_of_the_gear(self) -> None:
        template = WEBVIEW_TS.read_text(encoding="utf-8")

        assert re.search(
            r'id="tasksTabsContainer">\s*<div class="status-indicator">.*?</div>\s*</div>'
            r'\s*<div class="tabs-scroll" id="tasksTabsScroll"></div>'
            r'\s*<button class="settings-btn" id="settingsBtn"',
            template,
            flags=re.S,
        )

    def test_there_is_one_scroller_and_one_bar(self) -> None:
        template = WEBVIEW_TS.read_text(encoding="utf-8")

        assert template.count('id="tasksTabsScroll"') == 1
        assert template.count('id="tasksTabsContainer"') == 1


class TestStylesheet:
    def test_the_bar_itself_does_not_scroll(self) -> None:
        bar = _merged(".tabs-container")

        for prop in ("overflow", "overflow-x"):
            first = bar.get(prop, "visible").split()[0]
            assert first not in {"auto", "scroll"}, (prop, bar.get(prop))

    def test_the_scroller_takes_the_room_the_gear_leaves(self) -> None:
        scroller = _merged(".tabs-scroll")

        assert scroller.get("display") == "flex"
        assert scroller.get("overflow-x") == "auto"
        assert scroller.get("min-width") == "0"
        assert scroller.get("flex", "").split()[:1] == ["1"], scroller.get("flex")

    def test_the_gear_is_a_flow_item_and_does_not_shrink(self) -> None:
        gear = _merged(".settings-btn")

        assert gear.get("position", "static") not in {"absolute", "fixed"}
        assert gear.get("flex-shrink") == "0" or gear.get("flex", "").startswith("none")
        assert "transform" not in gear
        assert gear.get("width") == f"{GEAR_WIDTH_PX}px"

    def test_the_bar_reserves_no_room_for_a_gear_that_is_in_the_flow(self) -> None:
        right = _padding_right(_merged(".tabs-container")["padding"])

        assert right < GEAR_WIDTH_PX, right

    def test_the_gear_of_the_empty_state_stays_where_it_was(self) -> None:
        gear = _merged(".no-content-settings-btn")

        assert gear.get("position") == "absolute"
        assert gear.get("top") == "8px"
        assert gear.get("right") == "8px"


def _render_script(*, with_scroller: bool) -> str:
    source = WEBVIEW_UI_JS.read_text(encoding="utf-8")
    parts = "\n\n".join(
        _extract_function(source, name)
        for name in (
            "clearAllTabCountdowns",
            "getTaskIdString",
            "getOpenTaskId",
            "pickOpenTaskId",
            "reconcileActiveTaskId",
            "buildTaskTabsRenderState",
            "renderTaskTabs",
        )
    )
    return textwrap.dedent(
        f"""
        function makeElement(id) {{
          const element = {{
            id,
            className: '',
            dataset: {{}},
            children: [],
            parent: null,
            textContent: '',
            innerHTML: '',
            title: '',
            classList: {{
              names: new Set(),
              add(...names) {{ names.forEach(n => this.names.add(n)); }},
              remove(...names) {{ names.forEach(n => this.names.delete(n)); }},
              toggle(name, force) {{ if (force) this.names.add(name); else this.names.delete(name); }},
              contains(name) {{ return this.names.has(name); }},
            }},
            appendChild(child) {{ child.parent = this; this.children.push(child); return child; }},
            addEventListener() {{}},
            setAttribute() {{}},
            querySelector() {{ return null; }},
            querySelectorAll(selector) {{
              const found = [];
              const walk = node => node.children.forEach(child => {{
                if (selector === '.task-tab' && child.className.split(' ').includes('task-tab')) found.push(child);
                walk(child);
              }});
              walk(this);
              return found;
            }},
            remove() {{ if (this.parent) this.parent.children = this.parent.children.filter(c => c !== this); }},
          }};
          return element;
        }}

        const container = makeElement('tasksTabsContainer');
        const indicator = makeElement('indicator');
        const scroller = makeElement('tasksTabsScroll');
        const gear = makeElement('settingsBtn');
        container.children = [indicator, {"scroller, " if with_scroller else ""}gear];
        const document = {{
          createElement() {{ return makeElement(''); }},
          getElementById(id) {{
            if (id === 'tasksTabsContainer') return container;
            if (id === 'tasksTabsScroll') return {"scroller" if with_scroller else "null"};
            throw new Error('unexpected id: ' + id);
          }},
        }};
        const logs = [];
        let allTasks = [
          {{ task_id: 'task-1', status: 'active' }},
          {{ task_id: 'task-2', status: 'pending' }},
        ];
        let activeTaskId = null;
        let lastTasksHash = '';
        let lastTaskIds = new Set();
        let hasInitializedTaskIdTracking = false;
        let tabCountdownTimers = {{}};
        let tabCountdownRemaining = {{}};
        function clearInterval() {{}}
        function log(message) {{ logs.push(String(message)); }}
        function schedulePersistUiState() {{}}
        function notifyNewTasks() {{}}
        function showTabs() {{}}
        function hideTabs() {{}}
        function pruneTaskLocalState() {{ return false; }}
        function updateTabCountdowns() {{}}
        function switchToTask() {{}}

        {parts}

        renderTaskTabs();

        const ids = list => list.map(child => child.dataset.taskId || child.id);
        process.stdout.write(JSON.stringify({{
          container: ids(container.children),
          scroller: ids(scroller.children),
        }}));
        """
    )


class TestRenderTaskTabs:
    def test_the_tabs_go_into_the_scroller_and_the_bar_keeps_its_own_children(
        self,
    ) -> None:
        result = json.loads(_run_node(_render_script(with_scroller=True)))

        assert result == {
            "container": ["indicator", "tasksTabsScroll", "settingsBtn"],
            "scroller": ["task-1", "task-2"],
        }

    def test_a_page_without_a_scroller_still_gets_its_tabs(self) -> None:
        result = json.loads(_run_node(_render_script(with_scroller=False)))

        assert result == {
            "container": ["indicator", "settingsBtn", "task-1", "task-2"],
            "scroller": [],
        }

    def test_the_scroller_is_looked_up_only_once_the_bar_is_known_to_exist(
        self,
    ) -> None:
        source = WEBVIEW_UI_JS.read_text(encoding="utf-8")
        body = _extract_function(source, "renderTaskTabs")

        assert body.index("if (!container)") < body.index("'tasksTabsScroll'")
