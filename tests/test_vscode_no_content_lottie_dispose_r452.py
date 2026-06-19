"""R452: VS Code no-content Lottie resources must be explicitly disposed."""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
WEBVIEW_UI_JS = REPO_ROOT / "packages" / "vscode" / "webview-ui.js"


def _source() -> str:
    return WEBVIEW_UI_JS.read_text(encoding="utf-8")


def _extract_function(source: str, name: str) -> str:
    marker = f"function {name}("
    start = source.index(marker)
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


def _extract_beforeunload_handler(source: str) -> str:
    match = re.search(
        r"window\.addEventListener\('beforeunload',\s*\(\)\s*=>\s*\{", source
    )
    assert match, "beforeunload handler not found"
    start = match.start()
    brace = source.index("{", match.end() - 1)
    depth = 0
    for index in range(brace, len(source)):
        char = source[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return source[start : index + 1]
    raise AssertionError("Could not extract beforeunload handler")


def test_no_content_lottie_recovery_handlers_are_disposable() -> None:
    source = _source()
    install = _extract_function(source, "installNoContentLottieRecoveryHandlers")
    dispose = _extract_function(source, "disposeNoContentLottieRecoveryHandlers")

    assert "let noContentOnlineHandler = null" in source
    assert "let noContentVisibilityHandler = null" in source
    assert "window.addEventListener('online', noContentOnlineHandler)" in install
    assert (
        "document.addEventListener('visibilitychange', noContentVisibilityHandler)"
        in install
    )

    assert "noContentLottieDisposed = true" in dispose
    assert "clearNoContentLottieTimers()" in dispose
    assert "window.removeEventListener('online', noContentOnlineHandler)" in dispose
    assert (
        "document.removeEventListener('visibilitychange', noContentVisibilityHandler)"
        in dispose
    )
    assert "noContentStateObserver.disconnect()" in dispose
    assert "destroyNoContentHourglassAnimation()" in dispose


def test_no_content_lottie_async_paths_stop_after_dispose() -> None:
    source = _source()
    schedule = _extract_function(source, "scheduleNoContentLottieRetry")
    init = _extract_function(source, "initNoContentHourglassAnimation")
    beforeunload = _extract_beforeunload_handler(source)

    assert schedule.index("if (noContentLottieDisposed) return") < schedule.index(
        "if (!isNoContentVisible()) return"
    )
    assert init.index("if (noContentLottieDisposed) return") < init.index(
        "const container = document.getElementById('hourglass-lottie')"
    )
    assert (
        ".then(([okLib, data]) => {\n        if (noContentLottieDisposed) return"
        in init
    )
    assert ".catch(() => {\n        if (noContentLottieDisposed) return" in init
    assert "disposeNoContentLottieRecoveryHandlers()" in beforeunload
