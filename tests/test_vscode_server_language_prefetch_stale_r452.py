"""Source contracts for VS Code server language prefetch stale-response handling."""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
WEBVIEW_TS = REPO_ROOT / "packages" / "vscode" / "webview.ts"


def _source() -> str:
    return WEBVIEW_TS.read_text(encoding="utf-8")


def _extract_method_body(source: str, name: str) -> str:
    pattern = r"(?:private\s+)?" + re.escape(name) + r"\s*\([^)]*\)\s*:\s*[^{}]+\{"
    match = re.search(pattern, source)
    assert match, f"Cannot find method body for {name}"
    start = match.end()
    depth = 1
    i = start
    while i < len(source):
        char = source[i]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return source[start:i]
        i += 1
    raise AssertionError(f"Unbalanced method body for {name}")


def test_server_language_prefetch_uses_request_scoped_url() -> None:
    body = _extract_method_body(_source(), "_prefetchServerLanguage")

    assert "const requestServerUrl = this._serverUrl;" in body
    assert "fetch(`${requestServerUrl}/api/config`" in body
    assert "fetch(`${this._serverUrl}/api/config`" not in body


def test_stale_language_prefetch_returns_before_cache_or_callback() -> None:
    body = _extract_method_body(_source(), "_prefetchServerLanguage")

    first_guard = body.index("if (this._serverUrl !== requestServerUrl)")
    cache_idx = body.index("this._cachedServerLang = data.language;")
    callback_idx = body.index("this._onLanguageChanged(data.language as string);")
    assert first_guard < cache_idx
    assert first_guard < callback_idx


def test_server_url_change_clears_language_singleflight_before_reprefetch() -> None:
    body = _extract_method_body(_source(), "updateServerUrl")

    clear_cache_idx = body.index("this._cachedServerLang = null;")
    abort_idx = body.index("this._abortPrefetchServerLanguage();")
    refetch_idx = body.index("this._prefetchServerLanguage().catch(")
    assert clear_cache_idx < abort_idx < refetch_idx


def test_language_prefetch_controller_is_owned_and_disposed() -> None:
    source = _source()
    abort_body = _extract_method_body(source, "_abortPrefetchServerLanguage")

    assert (
        "private _prefetchServerLangAbortController: AbortController | null;" in source
    )
    assert "this._prefetchServerLangAbortController = null;" in abort_body
    assert "controller.abort();" in abort_body
    assert source.count("this._abortPrefetchServerLanguage();") >= 3
