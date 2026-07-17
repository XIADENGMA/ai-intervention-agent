"""R570: VirtualScroller render avoids slice/map allocation."""

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


def _extract_method(source: str, method_name: str) -> str:
    signature = f"  {method_name}() {{"
    start = source.index(signature)
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
    raise AssertionError(f"{method_name} body not found")


def test_virtual_scroller_render_uses_indexed_one_pass_html_builder() -> None:
    source = VALIDATION_UTILS_JS.read_text(encoding="utf-8")
    body = _extract_method(source, "render")

    assert "this.items.slice(startIndex, endIndex)" not in body
    assert "visibleItems" not in body
    assert ".map((item, i) => this.renderItem(item, startIndex + i))" not in body
    assert 'let html = "";' in body
    assert "for (let index = startIndex; index < endIndex; index += 1)" in body
    assert "if (!(index in this.items)) continue;" in body
    assert "this.renderItem(this.items[index], index)" in body
    assert "this.content.innerHTML = html;" in body


def test_virtual_scroller_render_preserves_output_without_slice_or_map() -> None:
    script = textwrap.dedent(
        f"""
        const path = {json.dumps(str(VALIDATION_UTILS_JS))};

        function makeElement(tag) {{
          return {{
            tag,
            className: '',
            style: {{}},
            children: [],
            parentNode: null,
            scrollTop: 20,
            clientHeight: 30,
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
            addEventListener() {{}},
            removeEventListener() {{}},
          }};
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
        const renderCalls = [];
        const scroller = new VirtualScroller(container, {{
          itemHeight: 10,
          buffer: 1,
          renderItem(item, index) {{
            renderCalls.push([index, Object.prototype.hasOwnProperty.call(scroller.items, index), item]);
            if (item === undefined || item === null) return item;
            return '<span data-index="' + index + '">' + item + '</span>';
          }},
        }});

        const items = ['zero', 'one', , 'three', undefined, null, 'six', 'seven'];
        items.slice = function () {{ throw new Error('slice must not be called'); }};
        scroller.setItems(items);

        process.stdout.write(JSON.stringify({{
          wrapperHeight: scroller.wrapper.style.height,
          transform: scroller.content.style.transform,
          html: scroller.content.innerHTML,
          renderCalls,
        }}));
        """
    )

    assert _run_node(script) == {
        "wrapperHeight": "80px",
        "transform": "translateY(10px)",
        "html": '<span data-index="1">one</span><span data-index="3">three</span>',
        "renderCalls": [
            [1, True, "one"],
            [3, True, "three"],
            [4, True, None],
            [5, True, None],
        ],
    }
