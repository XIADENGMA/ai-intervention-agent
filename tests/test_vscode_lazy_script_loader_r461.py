"""R461: VS Code webview lazy script loading should be event-driven.

The optional VS Code webview bundles (Lottie, marked, Prism, notification core,
settings UI) are intentionally lazy. This test locks the loader shape so
concurrent calls share script load/error events instead of spawning 50 ms
readiness polling loops for each duplicate script path.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
WEBVIEW_UI_JS = REPO_ROOT / "packages" / "vscode" / "webview-ui.js"


def _source() -> str:
    return WEBVIEW_UI_JS.read_text(encoding="utf-8")


def _helper_body(source: str) -> str:
    start = source.index("  function loadLazyScriptOnce(")
    end = source.index("  // 无有效内容页面", start)
    return source[start:end]


def test_lazy_script_loader_uses_load_error_events_with_timeout_guard() -> None:
    source = _source()
    helper = _helper_body(source)

    assert "script.addEventListener('load', onLoad, { once: true })" in helper
    assert "script.addEventListener('error', onError, { once: true })" in helper
    assert "script.removeEventListener('load', onLoad)" in helper
    assert "script.removeEventListener('error', onError)" in helper
    assert "timer = setTimeout(checkAndFinish" in helper
    assert "clearTimeout(timer)" in helper
    assert "script.setAttribute('nonce', CSP_NONCE)" in helper
    assert "document.head.appendChild(script)" in helper


def test_lazy_script_loader_replaces_duplicate_script_polling_loops() -> None:
    source = _source()

    assert "setTimeout(tick, 50)" not in source

    expected_calls = {
        "aiia-lottie-script": "LOTTIE_LIB_URL",
        "aiia-marked-script": "MARKED_JS_URL",
        "aiia-prism-script": "PRISM_JS_URL",
        "aiia-notify-core-script": "NOTIFY_CORE_JS_URL",
        "aiia-settings-ui-script": "SETTINGS_UI_JS_URL",
    }
    for script_id, url_const in expected_calls.items():
        pattern = re.compile(
            r"loadLazyScriptOnce\(\s*"
            + re.escape(f"'{script_id}'")
            + r",\s*"
            + re.escape(url_const)
            + r",",
            re.MULTILINE,
        )
        assert pattern.search(source), (
            f"{script_id} should load through loadLazyScriptOnce"
        )


def test_lottie_failure_still_clears_cached_promise_for_recovery() -> None:
    source = _source()

    assert "if (!ok) lottieLoadPromise = null" in source
