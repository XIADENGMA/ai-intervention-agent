"""R724: nothing the product shows or declares may suggest a sign-in.

The MCP server is a local stdio process and the Web UI has no login screen, yet
the toast for an HTTP 401/403 answer read "Authentication required, please sign
in again" (zh-CN: "需要重新登录，请刷新页面或检查访问令牌"). The only things that
can answer 401/403 are the network access control (a blocked address) or a
reverse proxy in front of the page, so the copy now says access was denied and
points at the network access settings. This file keeps that wording honest and
keeps authentication from creeping back into the surfaces that never had it:
the FastMCP constructor, the page templates and the first-party front-end code.

A masked input is not a sign-in: the one password-type field the page templates
may carry is a pasted credential for a third-party push service (the Bark device
key), listed in ``PASTED_CREDENTIAL_FIELD_IDS`` below.
"""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
PACKAGE = REPO / "src" / "ai_intervention_agent"
LOCALES = PACKAGE / "static" / "locales"
WEB_JS = PACKAGE / "static" / "js"
VSCODE = REPO / "packages" / "vscode"

SIGN_IN_WORDS = {
    "en": re.compile(
        r"sign[ -]?in|log[ -]?in|authenticat|credential|password|token", re.I
    ),
    "zh-CN": re.compile("登录|认证|鉴权|令牌|密码"),
    "zh-TW": re.compile("登入|認證|鑑權|權杖|令牌|密碼"),
}
SETTINGS_HINT = {
    "en": "network access settings",
    "zh-CN": "网络访问控制设置",
    "zh-TW": "網路存取控制設定",
}
VENDORED_WEB_JS = {"marked.js", "prism.js", "tex-mml-chtml.js"}
AUTH_HEADER = re.compile(r"""['"]authorization['"]|\bbearer\s""", re.I)
PASSWORD_FIELD = re.compile(r"""type\s*=\s*['"]?password""", re.I)
INPUT_TAG = re.compile(r"<input\b[^>]*>", re.I | re.S)
FIELD_ID = re.compile(r"""\bid\s*=\s*['"]([^'"]+)['"]""", re.I)
PASTED_CREDENTIAL_FIELD_IDS = {"bark-device-key"}


def _status_text(locale: str) -> str:
    data = json.loads((LOCALES / f"{locale}.json").read_text(encoding="utf-8"))
    return str(data["status"]["unauthorized"])


@pytest.mark.parametrize("locale", sorted(SIGN_IN_WORDS))
class TestAccessDeniedCopy:
    def test_names_both_status_codes(self, locale: str) -> None:
        text = _status_text(locale)
        assert "401" in text
        assert "403" in text

    def test_never_promises_a_sign_in(self, locale: str) -> None:
        text = _status_text(locale)
        assert SIGN_IN_WORDS[locale].search(text) is None, text

    def test_points_at_the_network_access_settings(self, locale: str) -> None:
        assert SETTINGS_HINT[locale] in _status_text(locale)


class TestNoAuthenticationSurface:
    def test_fastmcp_is_built_without_an_auth_provider(self) -> None:
        tree = ast.parse((PACKAGE / "server.py").read_text(encoding="utf-8"))
        constructors = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "FastMCP"
        ]
        assert constructors, "server.py no longer builds a FastMCP instance"
        for call in constructors:
            assert "auth" not in {kw.arg for kw in call.keywords}

    def test_page_templates_have_no_password_field(self) -> None:
        templates = sorted((PACKAGE / "templates").glob("*.html"))
        assert templates
        for path in templates:
            for tag in INPUT_TAG.findall(path.read_text(encoding="utf-8")):
                if PASSWORD_FIELD.search(tag) is None:
                    continue
                field_id = FIELD_ID.search(tag)
                assert field_id is not None, (path, tag)
                assert field_id.group(1) in PASTED_CREDENTIAL_FIELD_IDS, (path, tag)

    def test_first_party_front_end_code_sets_no_authorization_header(self) -> None:
        sources = [
            path
            for path in WEB_JS.glob("*.js")
            if not path.name.endswith(".min.js") and path.name not in VENDORED_WEB_JS
        ]
        sources += [
            path
            for pattern in ("*.js", "*.ts")
            for path in VSCODE.glob(pattern)
            if not path.name.endswith(".min.js")
        ]
        assert len(sources) > 20
        for path in sources:
            assert AUTH_HEADER.search(path.read_text(encoding="utf-8")) is None, path
