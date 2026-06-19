"""R452 · VS Code Webview retainContextWhenHidden benchmark contract."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
WEBVIEW_TS = REPO_ROOT / "packages" / "vscode" / "webview.ts"
WEBVIEW_UI = REPO_ROOT / "packages" / "vscode" / "webview-ui.js"
EXTENSION_TS = REPO_ROOT / "packages" / "vscode" / "extension.ts"
VSCODE_PACKAGE_JSON = REPO_ROOT / "packages" / "vscode" / "package.json"
SCRIPT = REPO_ROOT / "scripts" / "bench_vscode_webview_retain.mjs"
ROOT_PACKAGE_JSON = REPO_ROOT / "package.json"


def test_host_sends_visibility_benchmark_probe_on_restore() -> None:
    text = WEBVIEW_TS.read_text(encoding="utf-8")
    assert "_sendVisibilityBenchmarkProbe()" in text
    assert 'type: "visibility-benchmark-probe"' in text
    assert "this._retainContextWhenHidden" in text
    assert "AIIA_WEBVIEW_BENCH_OUTPUT" in text
    assert "webview.visibility_benchmark" in text


def test_retain_context_is_explicit_opt_in_not_default() -> None:
    pkg = json.loads(VSCODE_PACKAGE_JSON.read_text(encoding="utf-8"))
    props = pkg["contributes"]["configuration"]["properties"]
    retain = props["ai-intervention-agent.webview.retainContextWhenHidden"]
    assert retain["type"] == "boolean"
    assert retain["default"] is False

    extension = EXTENSION_TS.read_text(encoding="utf-8")
    assert "webview.retainContextWhenHidden" in extension
    assert "retainContextWhenHidden: retainWebviewContextWhenHidden" in extension
    assert "getState/setState" in extension


def test_webview_reports_probe_after_two_animation_frames() -> None:
    text = WEBVIEW_UI.read_text(encoding="utf-8")
    assert "function handleVisibilityBenchmarkProbe" in text
    assert "visibilityBenchmarkResult" in text
    assert "requestAnimationFrame(function ()" in text
    assert "performance.memory" in text
    assert "paintLatencyMs" in text


def test_root_package_exposes_benchmark_script() -> None:
    pkg = json.loads(ROOT_PACKAGE_JSON.read_text(encoding="utf-8"))
    scripts = pkg.get("scripts", {})
    assert scripts.get("vscode:webview-bench") == (
        "node scripts/bench_vscode_webview_retain.mjs"
    )


def test_benchmark_script_summarizes_ndjson_fixture(tmp_path: Path) -> None:
    sample = tmp_path / "retain.ndjson"
    rows = [
        {
            "seq": 1,
            "retainContextWhenHidden": True,
            "roundTripMs": 12,
            "paintLatencyMs": 18,
            "usedJSHeapSize": 2 * 1024 * 1024,
            "totalJSHeapSize": 4 * 1024 * 1024,
        },
        {
            "seq": 2,
            "retainContextWhenHidden": True,
            "roundTripMs": 20,
            "paintLatencyMs": 30,
            "usedJSHeapSize": 3 * 1024 * 1024,
            "totalJSHeapSize": 5 * 1024 * 1024,
        },
    ]
    sample.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")

    result = subprocess.run(
        ["node", str(SCRIPT), "--input", str(sample), "--json"],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    data = json.loads(result.stdout)
    assert data["samples"] == 2
    assert data["retainContextWhenHidden"] is True
    assert data["roundTripMs"]["p50"] == 12
    assert data["roundTripMs"]["p95"] == 20
    assert data["paintLatencyMs"]["max"] == 30
    assert data["usedJSHeapDelta"] == 1024 * 1024
