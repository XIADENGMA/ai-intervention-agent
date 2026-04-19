"""P9·L7 — backend (Python) i18n hardening.

``i18n.py`` is the backend counterpart of ``static/js/i18n.js`` — it
ships error messages and notification copy surfaced from the
Flask/FastMCP layer back to the web UI. Historically this dictionary
lived in Python with zero test coverage, so it was trivial to:

- Add an ``en`` key without a matching ``zh-CN`` translation (the
  site would silently fall back to English even when the user had
  explicitly picked Chinese).
- Rename a key in one locale but not the other (dead key on one
  side, missing key on the other).
- Add ``{param}`` placeholders that only exist in one locale
  (call sites would silently drop the context).
- Call ``get_locale_message("does.not.exist")`` from a route and
  never notice until the user opened DevTools.

These tests pin the contract so the whole chain stays coherent.
Each test has a justification in its docstring.
"""

from __future__ import annotations

import ast
import importlib
import re
from pathlib import Path

import pytest

i18n = importlib.import_module("i18n")

ROOT = Path(__file__).resolve().parent.parent
SERVER_PY_GLOB = [
    ROOT / "web_ui.py",
    ROOT / "web_ui_routes" / "feedback.py",
    ROOT / "web_ui_routes" / "notification.py",
    ROOT / "web_ui_routes" / "task.py",
]

# Matches ``msg("x.y")`` and ``get_locale_message("x.y")`` across the
# codebase. Use a conservative non-greedy regex so we don't match
# across newlines or interpolate variable keys.
_CALL_RE = re.compile(
    r"""(?x)
    \b(?:get_locale_message|msg)\s*\(
        \s*
        (['\"])([a-zA-Z][a-zA-Z0-9_.-]*)\1
    """,
)
# ``{param}`` placeholder extractor (Python ``str.format`` style —
# distinct from the frontend's ``{{param}}`` Mustache syntax).
_PLACEHOLDER_RE = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")


def _collect_backend_used_keys() -> set[str]:
    """Grep every server-side module for ``get_locale_message(...)``
    and ``msg(...)`` calls with a literal string first argument. We
    use a regex rather than AST to stay robust against f-strings and
    multi-line call formatting that can confuse ``ast.walk``."""
    used: set[str] = set()
    for path in SERVER_PY_GLOB:
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        for _, key in _CALL_RE.findall(text):
            used.add(key)
    return used


def _placeholders(s: str) -> set[str]:
    return set(_PLACEHOLDER_RE.findall(s))


class TestBackendLocaleParity:
    """Every key on one side must exist on the other."""

    def test_zh_cn_matches_en_key_set(self) -> None:
        # Rationale: if ``en`` ships a key the user's active locale
        # can't resolve, ``get_locale_message`` silently falls back to
        # English. That breaks the i18n contract for zh-CN users.
        en = set(i18n._MESSAGES["en"].keys())
        zh = set(i18n._MESSAGES["zh-CN"].keys())
        missing_in_zh = en - zh
        missing_in_en = zh - en
        assert not missing_in_zh, (
            f"zh-CN missing keys that exist in en: {sorted(missing_in_zh)}"
        )
        assert not missing_in_en, (
            f"en missing keys that exist in zh-CN: {sorted(missing_in_en)}"
        )

    def test_placeholder_parity(self) -> None:
        # Rationale: a call site like
        # ``msg("x.y", detail=err)`` depends on ``{detail}`` being in
        # BOTH locales. If one side drops the placeholder, the context
        # vanishes and users get e.g. "发送失败" without the ``err``
        # payload they'd see in English.
        for key, en_val in i18n._MESSAGES["en"].items():
            zh_val = i18n._MESSAGES["zh-CN"][key]
            en_ph = _placeholders(en_val)
            zh_ph = _placeholders(zh_val)
            assert en_ph == zh_ph, f"{key}: placeholder mismatch en={en_ph} zh={zh_ph}"


class TestBackendKeyCoverage:
    """Every call site must reach a real key; every defined key
    must be reached from somewhere."""

    def test_no_missing_keys_in_call_sites(self) -> None:
        used = _collect_backend_used_keys()
        defined = set(i18n._MESSAGES["en"].keys())
        missing = used - defined
        assert not missing, (
            f"{len(missing)} key(s) referenced in code but not declared "
            f"in i18n._MESSAGES: {sorted(missing)}"
        )

    def test_no_orphan_keys(self) -> None:
        # Rationale: dead keys signal either a missed deletion (noise
        # for translators) or a typo at the call site (user-visible
        # regression hiding in plain sight). We keep this strict —
        # unlike the JS side which is still ramping — because the
        # backend dict is tiny (<50 entries).
        used = _collect_backend_used_keys()
        defined = set(i18n._MESSAGES["en"].keys())
        orphan = defined - used
        assert not orphan, (
            f"{len(orphan)} orphan key(s) defined in i18n._MESSAGES but "
            f"never referenced: {sorted(orphan)}"
        )


class TestBackendLookup:
    """End-to-end sanity over the public API."""

    def test_missing_key_returns_key_like_js(self) -> None:
        # Behavior parity with static/js/i18n.js::t() — missing keys
        # echo back rather than crashing.
        out = i18n.get_locale_message("totally.not.real", lang="en")
        assert out == "totally.not.real"

    def test_en_fallback_for_zh_missing(self) -> None:
        # Simulate a half-translated key by temporarily poking the
        # module dict. We restore in teardown to keep other tests
        # isolated.
        key = "_test_only.fallback_probe"
        i18n._MESSAGES["en"][key] = "hello en"
        try:
            # No zh-CN entry → must fall through to en.
            out = i18n.get_locale_message(key, lang="zh-CN")
            assert out == "hello en"
        finally:
            del i18n._MESSAGES["en"][key]

    def test_placeholder_substitution(self) -> None:
        # Rationale: guard against a future refactor that swaps
        # ``.format`` for ``.format_map`` or ICU — ``{detail}`` must
        # continue to interpolate.
        out = i18n.get_locale_message(
            "notify.sendFailedDetail", lang="en", detail="timeout"
        )
        assert "timeout" in out

    def test_normalize_lang_collapses_variants(self) -> None:
        assert i18n.normalize_lang("zh-HK") == "zh-CN"
        assert i18n.normalize_lang("en-GB") == "en"
        assert i18n.normalize_lang("fr") == i18n.DEFAULT_LANG
        assert i18n.normalize_lang("") == i18n.DEFAULT_LANG


class TestBackendStaticStructure:
    """Guard the shape of ``i18n.py`` itself so a future refactor
    can't silently drop ``_MESSAGES`` or change the public surface."""

    def test_supported_langs_includes_default(self) -> None:
        assert i18n.DEFAULT_LANG in i18n.SUPPORTED_LANGS

    def test_msg_alias_matches_get_locale_message(self) -> None:
        # ``msg`` is documented as an alias; treating it as such in
        # call sites MUST continue to work.
        assert i18n.msg is i18n.get_locale_message

    def test_i18n_module_has_no_syntax_drift(self) -> None:
        # A small AST probe to catch accidental top-level statements
        # (e.g. a stray ``print(...)`` landing in the dict block)
        # without running the module.
        src = (ROOT / "i18n.py").read_text(encoding="utf-8")
        tree = ast.parse(src)
        offenders = [
            ast.dump(node)
            for node in tree.body
            if isinstance(node, ast.Expr) and not isinstance(node.value, ast.Constant)
        ]
        assert not offenders, (
            f"Unexpected top-level expression(s) in i18n.py: {offenders}"
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
