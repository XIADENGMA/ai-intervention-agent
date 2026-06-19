"""Template static JS/CSS URLs must be cache-busted.

The server already gives ``/static/js`` and ``/static/css`` responses with a
``?v=`` query a one-year immutable cache policy. This source-level invariant
keeps the template wired to that policy, including import-map URLs.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = REPO_ROOT / "src" / "ai_intervention_agent" / "templates" / "web_ui.html"


def _template_without_comments() -> str:
    text = TEMPLATE.read_text(encoding="utf-8")
    return re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL)


def test_all_static_js_css_template_urls_have_jinja_version_query() -> None:
    text = _template_without_comments()
    urls = re.findall(r'["\'](/static/(?:js|css)/[^"\']+)["\']', text)

    assert urls, "Expected web_ui.html to reference static JS/CSS assets"

    missing = [url for url in urls if "?v={{" not in url or "}}" not in url]
    assert missing == [], (
        "All /static/js and /static/css template URLs must carry a Jinja "
        f"cache-busting query so they hit one-year immutable caching: {missing}"
    )


def test_prism_preload_and_stylesheet_urls_match_exactly() -> None:
    text = _template_without_comments()
    preload = re.search(
        r'<link\b[^>]*\brel="preload"[^>]*\bhref="([^"]*?/static/css/prism\.css[^"]*)"',
        text,
    )
    stylesheet = re.search(
        r'<link\b[^>]*\brel="stylesheet"[^>]*\bhref="([^"]*?/static/css/prism\.css[^"]*)"',
        text,
    )

    assert preload is not None, "Prism CSS preload link missing"
    assert stylesheet is not None, "Prism CSS stylesheet link missing"
    assert preload.group(1) == stylesheet.group(1), (
        "Prism CSS preload and stylesheet href must be byte-identical, "
        "including the version query, or browsers treat them as separate fetches"
    )


def test_template_context_provides_every_static_asset_version_variable() -> None:
    from ai_intervention_agent.web_ui import WebFeedbackUI

    text = _template_without_comments()
    variables = sorted(set(re.findall(r"\?v=\{\{\s*(\w+)\s*\}\}", text)))
    ctx = WebFeedbackUI(
        prompt="static version invariant", port=19002
    )._get_template_context()

    missing = [name for name in variables if name not in ctx]
    empty = [name for name in variables if name in ctx and not str(ctx[name])]
    assert missing == [], f"_get_template_context missing version variables: {missing}"
    assert empty == [], f"_get_template_context returned empty versions: {empty}"


def test_template_context_provides_locale_version_map() -> None:
    from ai_intervention_agent.web_ui import WebFeedbackUI

    ctx = WebFeedbackUI(
        prompt="locale version invariant", port=19003
    )._get_template_context()
    versions = ctx.get("locale_versions")

    assert isinstance(versions, dict), "locale_versions must be a JSON-serializable map"
    assert set(versions) == {"en", "zh-CN", "zh-TW", "pseudo"}
    assert all(str(value) for value in versions.values())
