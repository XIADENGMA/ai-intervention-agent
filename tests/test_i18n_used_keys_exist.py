"""P7·L1·step-13：Web UI JS 里引用的每个 i18n key 必须在所有 Web UI
locale JSON 中存在。

``t()`` 的 forgive 默认值（miss → 回 default → 回 raw key）对在翻的
新 key 是 feature，对 typo / 漏翻是 regression——UI 静默印 ``foo.bar.baz``
而不是响报。

覆盖范围：
  * ``static/js/**`` 非 min JS + ``templates/web_ui.html``（其
    ``data-i18n*`` 属性由 ``translateDOM`` 处理）；
  * 识别的 call site（codebase 稳定）：``t('key')`` / ``__vuT('key')``
    （validation-utils）/ ``__domSecT('key')``（dom-security）/
    ``_t('key')``（multi_task）/ ``data-i18n*="key"``；
  * 动态 key（``t(variable)`` / ``t('prefix.' + suffix)``）无法静态解析，
    刻意跳过——接受这个 trade-off，不禁模板 key 构造。

「存在」判定：``a.b.c`` 按点段走 JSON，最终落在字符串叶子。中途缺段 /
中途命到非叶子字符串都算 missing。
"""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
LOCALES_DIR = REPO_ROOT / "static" / "locales"
STATIC_JS_DIR = REPO_ROOT / "static" / "js"
TEMPLATE_PATH = REPO_ROOT / "templates" / "web_ui.html"

# Strip comments to avoid matching example keys inside /* ... */ or // docs.
BLOCK_COMMENT_RE = re.compile(r"/\*.*?\*/", re.DOTALL)
LINE_COMMENT_RE = re.compile(r"//[^\n]*")

# Supported call sites. ``(?<![.\w])`` avoids matching ``.t('...')`` on
# chained APIs like ``window.AIIA_I18N.t('…')`` (those are internal
# helpers already covered via the lightweight wrappers, and matching
# chained access would also hit e.g. ``fetch.t(...)`` noise).
_CALLSITE_RES: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?<![.\w])t\(\s*(['\"])([\w.-]+)\1"),
    re.compile(r"__vuT\(\s*(['\"])([\w.-]+)\1"),
    re.compile(r"__domSecT\(\s*(['\"])([\w.-]+)\1"),
    re.compile(r"(?<![.\w])_t\(\s*(['\"])([\w.-]+)\1"),
)

# HTML data-i18n* attributes (single-segment or multi-segment suffix).
_DATA_I18N_RE = re.compile(r'data-i18n(?:-[a-z][\w-]*)?="([^"]+)"')

# Files that use ``t('…')`` for non-i18n semantics (e.g. vendored MathJax
# / lottie bundles using ``t`` as a loop variable). They are not part of
# the Web UI i18n boundary and must be ignored wholesale.
_JS_SKIPLIST: frozenset[str] = frozenset(
    {
        "tex-mml-chtml.js",
        "lottie.min.js",
        "marked.js",
        "prism.js",
        "mathjax-loader.js",  # pure loader: just console logs
    }
)


def _strip_comments(src: str) -> str:
    def _blank(match: re.Match[str]) -> str:
        return re.sub(r"[^\n]", " ", match.group(0))

    src = BLOCK_COMMENT_RE.sub(_blank, src)
    return LINE_COMMENT_RE.sub(_blank, src)


def _iter_js_files() -> list[Path]:
    if not STATIC_JS_DIR.is_dir():
        return []
    return sorted(
        p
        for p in STATIC_JS_DIR.glob("*.js")
        if not p.name.endswith(".min.js") and p.name not in _JS_SKIPLIST
    )


def _collect_js_keys() -> dict[str, list[tuple[Path, int]]]:
    """Return ``{key: [(path, line), ...]}`` for every t('…') call site."""
    hits: dict[str, list[tuple[Path, int]]] = {}
    for path in _iter_js_files():
        src = path.read_text(encoding="utf-8")
        stripped = _strip_comments(src)
        for pattern in _CALLSITE_RES:
            for match in pattern.finditer(stripped):
                key = (
                    match.group(2)
                    if match.lastindex and match.lastindex >= 2
                    else match.group(1)
                )
                line = stripped[: match.start()].count("\n") + 1
                hits.setdefault(key, []).append((path, line))
    return hits


def _collect_html_keys() -> dict[str, list[tuple[Path, int]]]:
    """Return HTML ``data-i18n*`` keys with their line numbers."""
    hits: dict[str, list[tuple[Path, int]]] = {}
    if not TEMPLATE_PATH.is_file():
        return hits
    src = TEMPLATE_PATH.read_text(encoding="utf-8")
    for match in _DATA_I18N_RE.finditer(src):
        key = match.group(1)
        line = src[: match.start()].count("\n") + 1
        hits.setdefault(key, []).append((TEMPLATE_PATH, line))
    return hits


def _key_exists(data: dict[str, Any], key: str) -> bool:
    # ``static/js/i18n.js::resolve`` splits the key on ``.`` and walks
    # the locale tree by each segment, so a key ``page.skipToContent``
    # is resolvable *only* if the JSON is ``{"page": {"skipToContent":
    # "..."}}``. A flat top-level ``"page.skipToContent"`` entry would
    # never be reached at runtime — we rejected that shape by pytest
    # on purpose (it was a silent invisible regression when we missed
    # it before).
    cur: Any = data
    for part in key.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return False
        cur = cur[part]
    return isinstance(cur, str)


def _load_web_locales() -> dict[str, dict[str, Any]]:
    return {
        path.stem: json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(LOCALES_DIR.glob("*.json"))
    }


class TestI18nUsedKeysExist(unittest.TestCase):
    """Every key used by JS or HTML MUST exist in every Web UI locale."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.locales = _load_web_locales()
        cls.used_keys: dict[str, list[tuple[Path, int]]] = {}
        for key, refs in _collect_js_keys().items():
            cls.used_keys.setdefault(key, []).extend(refs)
        for key, refs in _collect_html_keys().items():
            cls.used_keys.setdefault(key, []).extend(refs)

    def test_all_used_keys_resolve_in_every_locale(self) -> None:
        self.assertTrue(self.locales, msg="No locale JSON files discovered")
        missing: list[str] = []
        for key, refs in sorted(self.used_keys.items()):
            for locale_name, data in self.locales.items():
                if not _key_exists(data, key):
                    first_ref = refs[0]
                    rel = first_ref[0].relative_to(REPO_ROOT).as_posix()
                    missing.append(
                        f"  [{locale_name}] key {key!r} missing "
                        f"(first used at {rel}:{first_ref[1]})"
                    )
        if missing:
            self.fail(
                f"Found {len(missing)} unresolved i18n key reference(s):\n"
                + "\n".join(missing)
                + "\nFix: add the missing key to static/locales/*.json "
                "(keep en.json and zh-CN.json in structural parity)."
            )


if __name__ == "__main__":
    unittest.main()
