"""R453 · VS Code webview server URL must be remote-safe.

VS Code's Remote/Codespaces guidance warns that `localhost` inside webview
content points at the UI/browser side, not necessarily the remote extension
host. The extension host should keep using the configured direct server URL,
while browser-side webview fetch/SSE URLs should use `vscode.env.asExternalUri`
when VS Code can provide a forwarded URL.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEBVIEW_TS = ROOT / "packages" / "vscode" / "webview.ts"
EXTENSION_TS = ROOT / "packages" / "vscode" / "extension.ts"


def _webview_source() -> str:
    assert WEBVIEW_TS.exists(), "packages/vscode/webview.ts is missing"
    return WEBVIEW_TS.read_text(encoding="utf-8")


def _extension_source() -> str:
    assert EXTENSION_TS.exists(), "packages/vscode/extension.ts is missing"
    return EXTENSION_TS.read_text(encoding="utf-8")


def test_webview_has_separate_browser_facing_server_url_cache() -> None:
    src = _webview_source()

    assert "private _webviewServerUrl: string;" in src
    assert "this._serverUrl = serverUrl;" in src
    assert "this._webviewServerUrl = this._normalizeWebviewServerUrl(serverUrl);" in src
    assert "const serverUrl =\n      this._webviewServerUrl" in src, (
        "_getHtmlContent should inject the browser/webview-facing URL, not "
        "the extension-host direct URL"
    )


def test_webview_uses_as_external_uri_with_direct_url_fallback() -> None:
    src = _webview_source()

    assert "private async _refreshWebviewServerUrl()" in src
    assert "vscode.env.asExternalUri(vscode.Uri.parse(fallback))" in src
    assert "forwarded.toString()" in src
    assert "this._webviewServerUrl = fallback;" in src
    assert "catch {\n      this._webviewServerUrl = fallback;" in src
    assert 'raw.replace(/\\/+$/, "")' in src, (
        "webview SERVER_URL must have no trailing slash because frontend code "
        "builds endpoints with SERVER_URL + '/api/...'"
    )


def test_webview_refreshes_forwarded_url_before_html_render() -> None:
    src = _webview_source()

    assert (
        "Promise.all([this._preloadResources(), this._refreshWebviewServerUrl()])"
        in src
    )
    assert "view.webview.html = this._getHtmlContent(view.webview)" in src
    assert "this._webviewServerUrl = this._normalizeWebviewServerUrl(serverUrl);" in src


def test_extension_host_keeps_direct_server_url_for_polling_and_sse() -> None:
    src = _extension_source()

    assert "const requestServerUrl = serverUrl;" in src
    assert "fetch(`${requestServerUrl}/api/tasks`" in src
    assert "let sseUrl = `${serverUrl}/api/events`" in src
    assert "provider" in src and ".updateServerUrl(serverUrl)" in src
    assert "asExternalUri" not in src, (
        "forwarding belongs at the webview boundary; extension-host polling "
        "must keep direct access to the configured serverUrl"
    )


def test_webview_local_resource_roots_remain_extension_scoped() -> None:
    src = _webview_source()

    assert "localResourceRoots: [this._extensionUri]" in src
    assert "localResourceRoots: undefined" not in src
    assert "localResourceRoots: []" not in src
