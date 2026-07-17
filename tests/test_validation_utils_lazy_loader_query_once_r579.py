"""R579 regression coverage for LazyLoader one-pass image collection."""

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


def test_lazy_loader_caches_queryselectorall_result_for_observe_and_debug() -> None:
    source = _source()
    init_body = _extract_method_body(
        source,
        'static init(selector = ".lazy-image", options = {}) {',
    )
    load_all_body = _extract_method_body(source, "static loadAllImages(")

    assert "document.querySelectorAll(selector).forEach" not in init_body
    assert "document.querySelectorAll(selector).forEach" not in load_all_body
    assert "const images = document.querySelectorAll(selector)" in init_body
    assert "const imageCount =" in init_body
    assert "observer.observe(img)" in init_body
    assert "watching ${imageCount} images" in init_body
    assert "const images = document.querySelectorAll(selector)" in load_all_body
    assert "this.loadImage(img)" in load_all_body


@pytest.mark.skipif(shutil.which("node") is None, reason="node runtime unavailable")
def test_lazy_loader_init_observes_nodelist_like_once_without_foreach() -> None:
    script = textwrap.dedent(
        f"""
        const path = {json.dumps(str(VALIDATION_UTILS_JS))};
        const observed = [];
        const debugMessages = [];
        const queryLog = [];

        class FakeIntersectionObserver {{
          constructor(callback, options) {{
            this.callback = callback;
            this.options = options;
          }}
          observe(img) {{
            observed.push(img.id);
          }}
          disconnect() {{}}
        }}

        const images = {{
          0: {{ id: 'first' }},
          1: {{ id: 'second' }},
          length: 2,
          forEach() {{
            throw new Error('NodeList.forEach must not be used by LazyLoader.init');
          }},
        }};

        global.window = {{ IntersectionObserver: FakeIntersectionObserver }};
        global.IntersectionObserver = FakeIntersectionObserver;
        global.document = {{
          querySelectorAll(selector) {{
            queryLog.push(selector);
            return images;
          }},
        }};
        global.console = {{
          debug(message) {{ debugMessages.push(message); }},
          warn() {{}},
        }};

        const {{ LazyLoader }} = require(path);
        LazyLoader.init('.lazy-image');
        LazyLoader.disconnect();

        process.stdout.write(JSON.stringify({{
          observed,
          queryLog,
          debugMessages,
          activeObserverCleared: LazyLoader._observer === null,
        }}));
        """
    )

    assert json.loads(_run_node(script)) == {
        "observed": ["first", "second"],
        "queryLog": [".lazy-image"],
        "debugMessages": ["Lazy loader initialized, watching 2 images"],
        "activeObserverCleared": True,
    }


@pytest.mark.skipif(shutil.which("node") is None, reason="node runtime unavailable")
def test_lazy_loader_fallback_loads_nodelist_like_without_foreach() -> None:
    script = textwrap.dedent(
        f"""
        const path = {json.dumps(str(VALIDATION_UTILS_JS))};
        const loaded = [];
        const queryLog = [];
        const images = {{
          0: {{ id: 'first' }},
          1: {{ id: 'second' }},
          length: 2,
          forEach() {{
            throw new Error('NodeList.forEach must not be used by LazyLoader.loadAllImages');
          }},
        }};

        global.window = {{}};
        global.document = {{
          querySelectorAll(selector) {{
            queryLog.push(selector);
            return images;
          }},
        }};
        global.console = {{ debug() {{}}, warn() {{}} }};

        const {{ LazyLoader }} = require(path);
        LazyLoader.loadImage = function loadImage(img) {{
          loaded.push(img.id);
        }};
        LazyLoader.loadAllImages('.lazy-image');

        process.stdout.write(JSON.stringify({{ loaded, queryLog }}));
        """
    )

    assert json.loads(_run_node(script)) == {
        "loaded": ["first", "second"],
        "queryLog": [".lazy-image"],
    }
