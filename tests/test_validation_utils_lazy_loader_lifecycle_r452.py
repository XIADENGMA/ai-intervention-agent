"""R452: LazyLoader repeated init must not leak stale observers."""

from __future__ import annotations

import json
import shutil
import subprocess
import textwrap
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
VALIDATION_UTILS_JS = (
    REPO_ROOT
    / "src"
    / "ai_intervention_agent"
    / "static"
    / "js"
    / "validation-utils.js"
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


def test_lazy_loader_init_disconnects_previous_observer() -> None:
    script = textwrap.dedent(
        f"""
        const path = {json.dumps(str(VALIDATION_UTILS_JS))};
        const observers = [];

        class FakeIntersectionObserver {{
          constructor(callback, options) {{
            this.callback = callback;
            this.options = options;
            this.observed = [];
            this.disconnected = false;
            observers.push(this);
          }}
          observe(img) {{
            this.observed.push(img);
          }}
          unobserve(img) {{
            this.unobserved = img;
          }}
          disconnect() {{
            this.disconnected = true;
          }}
        }}

        const imageA = {{ dataset: {{ src: 'a.png' }}, classList: {{ add() {{}}, remove() {{}} }} }};
        const imageB = {{ dataset: {{ src: 'b.png' }}, classList: {{ add() {{}}, remove() {{}} }} }};
        const queryLog = [];

        global.window = {{ IntersectionObserver: FakeIntersectionObserver }};
        global.IntersectionObserver = FakeIntersectionObserver;
        global.document = {{
          querySelectorAll(selector) {{
            queryLog.push(selector);
            return selector === '.first' ? [imageA] : [imageB];
          }},
        }};
        global.console = {{ debug() {{}}, warn() {{}} }};

        const {{ LazyLoader }} = require(path);

        LazyLoader.init('.first');
        const first = observers[0];
        LazyLoader.init('.second');
        const second = observers[1];
        LazyLoader.disconnect();

        process.stdout.write(JSON.stringify({{
          observerCount: observers.length,
          firstDisconnectedBeforeReplace: first.disconnected,
          secondDisconnectedOnDisconnect: second.disconnected,
          firstObserved: first.observed.length,
          secondObserved: second.observed.length,
          queryLog,
          activeObserverCleared: LazyLoader._observer === null,
        }}));
        """
    )

    assert _run_node(script) == {
        "observerCount": 2,
        "firstDisconnectedBeforeReplace": True,
        "secondDisconnectedOnDisconnect": True,
        "firstObserved": 1,
        "secondObserved": 1,
        "queryLog": [".first", ".first", ".second", ".second"],
        "activeObserverCleared": True,
    }


def test_virtual_scroller_destroy_removes_scroll_listener() -> None:
    script = textwrap.dedent(
        f"""
        const path = {json.dumps(str(VALIDATION_UTILS_JS))};
        const events = [];

        function makeElement(tag) {{
          const el = {{
            tag,
            className: '',
            style: {{}},
            children: [],
            parentNode: null,
            scrollTop: 0,
            clientHeight: 100,
            innerHTML: '',
            appendChild(child) {{
              child.parentNode = this;
              this.children.push(child);
            }},
            removeChild(child) {{
              const index = this.children.indexOf(child);
              if (index >= 0) this.children.splice(index, 1);
              child.parentNode = null;
            }},
            addEventListener(type, handler) {{
              events.push({{ action: 'add', type, handler }});
            }},
            removeEventListener(type, handler) {{
              events.push({{ action: 'remove', type, handler }});
            }},
          }};
          return el;
        }}

        global.window = {{}};
        global.document = {{
          createElement(tag) {{
            return makeElement(tag);
          }},
        }};
        global.console = {{ debug() {{}}, warn() {{}} }};

        const {{ VirtualScroller }} = require(path);
        const container = makeElement('container');
        const scroller = new VirtualScroller(container, {{
          itemHeight: 20,
          renderItem(item) {{ return '<div>' + item + '</div>'; }},
        }});
        const wrapperAfterInit = container.children.length;
        scroller.destroy();
        scroller.destroy();

        const add = events.find((event) => event.action === 'add');
        const removes = events.filter((event) => event.action === 'remove');

        process.stdout.write(JSON.stringify({{
          addType: add && add.type,
          removeCount: removes.length,
          removedSameHandler: !!(add && removes[0] && add.handler === removes[0].handler),
          wrapperAfterInit,
          wrapperAfterDestroy: container.children.length,
          handlerCleared: scroller._scrollHandler === null,
          destroyed: scroller._destroyed === true,
        }}));
        """
    )

    assert _run_node(script) == {
        "addType": "scroll",
        "removeCount": 1,
        "removedSameHandler": True,
        "wrapperAfterInit": 1,
        "wrapperAfterDestroy": 0,
        "handlerCleared": True,
        "destroyed": True,
    }
