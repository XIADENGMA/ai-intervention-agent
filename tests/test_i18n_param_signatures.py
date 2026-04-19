"""P9·L9·G1 — param-signature parity between t() call sites and locales.

Pytest mirror of ``scripts/check_i18n_param_signatures.py``. This is
the strict enforcement layer: the script runs in warn-mode from the
CI gate (exit 0 always) so contributors can land WIP with placeholder
drift, but this test file fails the run so merges stay clean.

The two-file split is intentional:
- Script is the dev-facing tool (run locally, pretty report).
- Test pins the contract so CI refuses to regress.

We also exercise the parser with synthetic inputs so the scanner
itself has regression coverage, independent of real locale data."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "check_i18n_param_signatures.py"


def _load_script_module():
    """Import the script without running ``main``.

    The script has no ``if __name__`` guard shenanigans we need to
    worry about — it just defines pure functions — so a raw
    ``importlib`` load gives us access to the internals for unit
    testing."""
    spec = importlib.util.spec_from_file_location("_chk_param", SCRIPT)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_chk_param"] = mod
    spec.loader.exec_module(mod)
    return mod


CHK = _load_script_module()


class TestPlaceholderExtraction:
    """Pin the placeholder-regex behavior so future edits don't
    accidentally narrow or broaden the set of recognized tokens."""

    def test_mustache_only(self) -> None:
        assert CHK._placeholders_in("Hello {{name}}!") == {"name"}
        assert CHK._placeholders_in("{{a}} and {{b}}") == {"a", "b"}

    def test_icu_plural_head(self) -> None:
        value = "{count, plural, one {1 item} other {# items}}"
        assert CHK._placeholders_in(value) == {"count"}

    def test_icu_select_head(self) -> None:
        value = "{gender, select, male {he} female {she} other {they}}"
        assert CHK._placeholders_in(value) == {"gender"}

    def test_icu_nested_with_mustache(self) -> None:
        # Mixed: ICU head arg + nested Mustache.
        value = "{count, plural, one {1 {{fruit}}} other {# {{fruit}}s}}"
        assert CHK._placeholders_in(value) == {"count", "fruit"}

    def test_bare_single_brace_is_not_a_placeholder(self) -> None:
        # Runtime i18n doesn't substitute `{name}` — only `{{name}}`
        # and ICU heads — so the scanner also ignores bare braces to
        # stay honest.
        assert CHK._placeholders_in("File {foo}") == set()

    def test_icu_hash_is_not_a_placeholder(self) -> None:
        # ICU's `#` is implicit (plural count) — not a named param.
        assert CHK._placeholders_in("{n, plural, one {#} other {# items}}") == {"n"}

    def test_empty_or_plain(self) -> None:
        assert CHK._placeholders_in("") == set()
        assert CHK._placeholders_in("no braces here") == set()

    def test_non_word_start_rejected(self) -> None:
        # `{ 123 }` or `{ !foo }` should not be treated as a named param.
        assert CHK._placeholders_in("{{123}}") == set()
        assert CHK._placeholders_in("{!bad, plural, one {} other {}}") == set()


class TestParamExtraction:
    """Exercise the object-literal parser against the forms we see in
    real source."""

    def test_shorthand_names(self) -> None:
        # `{ a, b, c }`
        assert CHK._extract_param_names("{ a, b, c }") == {"a", "b", "c"}

    def test_explicit_values(self) -> None:
        assert CHK._extract_param_names("{ a: 1, b: 'x' }") == {"a", "b"}

    def test_function_call_values(self) -> None:
        # Nested commas inside the call should not split the top-level
        # property list.
        assert CHK._extract_param_names("{ name: fn(x, y), size: obj.get(a, b) }") == {
            "name",
            "size",
        }

    def test_nested_object_value(self) -> None:
        assert CHK._extract_param_names("{ a: { x: 1, y: 2 }, b: 3 }") == {"a", "b"}

    def test_string_literal_keys(self) -> None:
        assert CHK._extract_param_names("{ 'a': 1, \"b\": 2 }") == {"a", "b"}

    def test_spread_bails_out(self) -> None:
        out = CHK._extract_param_names("{ ...rest, a: 1 }")
        assert "__aiia_param_spread__" in out

    def test_computed_key_bails_out(self) -> None:
        # We can't resolve `[expr]: value` statically.
        out = CHK._extract_param_names("{ [x]: 1, b: 2 }")
        assert "__aiia_param_dynamic__" in out

    def test_empty_object(self) -> None:
        assert CHK._extract_param_names("{ }") == set()
        assert CHK._extract_param_names("{}") == set()


class TestCommentStripping:
    def test_line_comments_erased(self) -> None:
        text = "foo // t('fake.key', { a })\nbar"
        out = CHK._strip_source_comments(text)
        # Line count preserved; the commented call site vanishes.
        assert out.count("\n") == text.count("\n")
        assert "t('fake.key'" not in out

    def test_block_comments_erased(self) -> None:
        text = "x\n/* t('a.b')\n   t('c.d') */\ny"
        out = CHK._strip_source_comments(text)
        assert "t('a.b')" not in out
        assert "t('c.d')" not in out
        # Line breaks inside the block are preserved so line numbers
        # don't shift.
        assert out.count("\n") == text.count("\n")


class TestEndToEndScan:
    """The live scan must pass against the committed tree — this is
    what fails the CI build if someone regresses."""

    def test_no_mismatches_on_real_codebase(self) -> None:
        report = CHK.scan()
        all_issues = report["web"] + report["vscode"]
        assert all_issues == [], (
            "Param-signature drift found. Run "
            "`uv run python scripts/check_i18n_param_signatures.py` "
            "for a full report. Issues:\n"
            + "\n".join(
                f"  - {it['file']}:{it['line']} key={it['key']} "
                f"missing={it['missing']} extra={it['extra']}"
                for it in all_issues
            )
        )


class TestScannerResilience:
    """Feed the scanner dummy files through a tmp_path swap to
    ensure the end-to-end pipeline surfaces known bugs."""

    def test_detects_missing_param(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Build a tiny fake tree with one t() call missing the `user`
        # param declared in the locale value.
        root = tmp_path
        web_locales = root / "static" / "locales"
        web_js = root / "static" / "js"
        web_locales.mkdir(parents=True)
        web_js.mkdir(parents=True)
        (web_locales / "en.json").write_text(
            '{ "hello": "Hi {{user}}!" }', encoding="utf-8"
        )
        (web_js / "app.js").write_text(
            "var x = t('hello');\nvar y = t('hello', { wrong: 1 });\n",
            encoding="utf-8",
        )
        monkeypatch.setattr(CHK, "ROOT", root)
        monkeypatch.setattr(CHK, "WEB_LOCALES_DIR", web_locales)
        monkeypatch.setattr(CHK, "WEB_JS_DIR", web_js)
        monkeypatch.setattr(CHK, "TEMPLATES_DIR", root / "templates")
        monkeypatch.setattr(
            CHK, "VSCODE_LOCALES_DIR", root / "packages" / "vscode" / "locales"
        )
        monkeypatch.setattr(CHK, "VSCODE_PKG_DIR", root / "packages" / "vscode")
        report = CHK.scan()
        web_issues = report["web"]
        kinds = {it["kind"] for it in web_issues}
        keys = {it["key"] for it in web_issues}
        assert keys == {"hello"}
        assert "missing-params" in kinds or "both" in kinds
        # The second call had a stray `wrong` param → extra-params.
        extras = {tuple(it["extra"]) for it in web_issues if it["extra"]}
        assert ("wrong",) in extras

    def test_skips_dynamic_key(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        root = tmp_path
        web_locales = root / "static" / "locales"
        web_js = root / "static" / "js"
        web_locales.mkdir(parents=True)
        web_js.mkdir(parents=True)
        (web_locales / "en.json").write_text(
            '{ "hello": "Hi {{user}}!" }', encoding="utf-8"
        )
        # Key is a variable — scanner should ignore.
        (web_js / "app.js").write_text(
            "var x = t(someKey, { user });\n", encoding="utf-8"
        )
        monkeypatch.setattr(CHK, "ROOT", root)
        monkeypatch.setattr(CHK, "WEB_LOCALES_DIR", web_locales)
        monkeypatch.setattr(CHK, "WEB_JS_DIR", web_js)
        monkeypatch.setattr(
            CHK, "VSCODE_LOCALES_DIR", root / "packages" / "vscode" / "locales"
        )
        monkeypatch.setattr(CHK, "VSCODE_PKG_DIR", root / "packages" / "vscode")
        report = CHK.scan()
        assert report["web"] == []


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
