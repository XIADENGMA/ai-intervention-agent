"""R580 regression coverage for LazyLoader IntersectionObserver entries loop."""

from __future__ import annotations

import json
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
VALIDATION_UTILS_JS = (
    REPO_ROOT
    / "src"
    / "ai_intervention_agent"
    / "static"
    / "js"
    / "validation-utils.js"
)


def _source() -> str:
    return VALIDATION_UTILS_JS.read_text(encoding="utf-8")


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


def _extract_method_body(source: str, marker: str) -> str:
    start = source.find(marker)
    assert start != -1, f"Cannot find method marker: {marker}"
    open_brace = (
        start + len(marker) - 1 if marker.endswith("{") else source.find("{", start)
    )
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
    raise AssertionError(f"Unbalanced method body for: {marker}")


def test_lazy_loader_observer_callback_uses_indexed_entries_loop() -> None:
    init_body = _extract_method_body(
        _source(),
        'static init(selector = ".lazy-image", options = {}) {',
    )

    assert "entries.forEach((entry)" not in init_body
    assert "const entryCount =" in init_body
    assert "entryIndex < entryCount" in init_body
    assert "const entry = entries[entryIndex]" in init_body
    assert "if (!entry) continue" in init_body
    assert "this.loadImage(entry.target, config)" in init_body
    assert "obs.unobserve(entry.target)" in init_body


@pytest.mark.skipif(shutil.which("node") is None, reason="node runtime unavailable")
def test_lazy_loader_observer_callback_handles_entries_without_foreach() -> None:
    script = textwrap.dedent(
        f"""
        const path = {json.dumps(str(VALIDATION_UTILS_JS))};
        const loaded = [];
        const unobserved = [];
        const observed = [];
        const images = {{
          0: {{ id: 'first' }},
          1: {{ id: 'second' }},
          length: 2,
        }};
        let activeObserver = null;

        class FakeIntersectionObserver {{
          constructor(callback, options) {{
            this.callback = callback;
            this.options = options;
            activeObserver = this;
          }}
          observe(img) {{
            observed.push(img.id);
          }}
          unobserve(img) {{
            unobserved.push(img.id);
          }}
          disconnect() {{}}
        }}

        global.window = {{ IntersectionObserver: FakeIntersectionObserver }};
        global.IntersectionObserver = FakeIntersectionObserver;
        global.document = {{
          querySelectorAll() {{
            return images;
          }},
        }};
        global.console = {{ debug() {{}}, warn() {{}} }};

        const {{ LazyLoader }} = require(path);
        LazyLoader.loadImage = function loadImage(img, config) {{
          loaded.push([img.id, config.loadingClass]);
        }};
        LazyLoader.init('.lazy-image', {{ loadingClass: 'custom-loading' }});

        const entries = {{
          0: {{ isIntersecting: true, target: images[0] }},
          1: {{ isIntersecting: false, target: images[1] }},
          2: {{ isIntersecting: true, target: images[1] }},
          length: 3,
          forEach() {{
            throw new Error('entries.forEach must not be used by LazyLoader callback');
          }},
        }};
        activeObserver.callback(entries, activeObserver);
        LazyLoader.disconnect();

        process.stdout.write(JSON.stringify({{
          observed,
          loaded,
          unobserved,
          activeObserverCleared: LazyLoader._observer === null,
        }}));
        """
    )

    assert json.loads(_run_node(script)) == {
        "observed": ["first", "second"],
        "loaded": [["first", "custom-loading"], ["second", "custom-loading"]],
        "unobserved": ["first", "second"],
        "activeObserverCleared": True,
    }
