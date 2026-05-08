"""P9·L9·G1 — ``t()`` call site 与 locale 的 param 签名一致性 pytest 镜像。

对应 ``scripts/check_i18n_param_signatures.py``：脚本以 warn 模式挂在
CI gate（exit 0，允许 WIP 漂移），本文件以 strict 模式挂在 pytest，
让合并前回归。

双轨拆分意图：脚本是 dev-facing 工具（本地跑、彩色报告），pytest
锁合约防 CI 回归。另外合成输入直接喂 parser，给扫描器自身兜底。
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "check_i18n_param_signatures.py"


def _load_script_module():
    """按模块加载脚本（脚本里全是纯函数，直接 importlib 即可）。"""
    spec = importlib.util.spec_from_file_location("_chk_param", SCRIPT)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_chk_param"] = mod
    spec.loader.exec_module(mod)
    return mod


CHK = _load_script_module()


class TestPlaceholderExtraction:
    """锁占位符正则行为，防止改动缩放识别集合。"""

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
    """对真实源码里见过的对象字面量形状跑 parser。"""

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
    """对已提交 tree 跑 live 扫描——回归即挂 CI。"""

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
        web_locales = root / "src" / "ai_intervention_agent" / "static" / "locales"
        web_js = root / "src" / "ai_intervention_agent" / "static" / "js"
        vscode_locales = root / "packages" / "vscode" / "locales"
        web_locales.mkdir(parents=True)
        web_js.mkdir(parents=True)
        # R110：``_scan_web`` / ``_scan_vscode`` 不再 silent skip 缺源
        # locale；测试 monkeypatch 改 root 时必须给两端都建空 en.json
        # （否则 ``_load_json`` 直接抛 FileNotFoundError，与 main 顶部
        # layer-0 的 fail-loud 行为一致）。
        vscode_locales.mkdir(parents=True)
        (web_locales / "en.json").write_text(
            '{ "hello": "Hi {{user}}!" }', encoding="utf-8"
        )
        (vscode_locales / "en.json").write_text("{}", encoding="utf-8")
        (web_js / "app.js").write_text(
            "var x = t('hello');\nvar y = t('hello', { wrong: 1 });\n",
            encoding="utf-8",
        )
        monkeypatch.setattr(CHK, "ROOT", root)
        monkeypatch.setattr(CHK, "WEB_LOCALES_DIR", web_locales)
        monkeypatch.setattr(CHK, "WEB_JS_DIR", web_js)
        monkeypatch.setattr(
            CHK, "TEMPLATES_DIR", root / "src" / "ai_intervention_agent" / "templates"
        )
        monkeypatch.setattr(CHK, "VSCODE_LOCALES_DIR", vscode_locales)
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
        web_locales = root / "src" / "ai_intervention_agent" / "static" / "locales"
        web_js = root / "src" / "ai_intervention_agent" / "static" / "js"
        vscode_locales = root / "packages" / "vscode" / "locales"
        web_locales.mkdir(parents=True)
        web_js.mkdir(parents=True)
        vscode_locales.mkdir(parents=True)  # R110 同款补齐
        (web_locales / "en.json").write_text(
            '{ "hello": "Hi {{user}}!" }', encoding="utf-8"
        )
        (vscode_locales / "en.json").write_text("{}", encoding="utf-8")
        # Key is a variable — scanner should ignore.
        (web_js / "app.js").write_text(
            "var x = t(someKey, { user });\n", encoding="utf-8"
        )
        monkeypatch.setattr(CHK, "ROOT", root)
        monkeypatch.setattr(CHK, "WEB_LOCALES_DIR", web_locales)
        monkeypatch.setattr(CHK, "WEB_JS_DIR", web_js)
        monkeypatch.setattr(CHK, "VSCODE_LOCALES_DIR", vscode_locales)
        monkeypatch.setattr(CHK, "VSCODE_PKG_DIR", root / "packages" / "vscode")
        report = CHK.scan()
        assert report["web"] == []


class TestMainPathDriftR110:
    """R110：``main()`` 顶部的 layer-0 path-drift sanity check。

    Web 与 VS Code 的源 ``en.json`` 必须真实存在；缺失即 fail-loud
    (exit 2) 而非 silent ``return []`` → ``total = 0`` → ``--strict``
    走 exit 0 路径（zero-coverage CI 仍绿）。与 R88/R100/R101/R102
    在 brand-color guard / HTML coverage / ts/js no-cjk / locale
    shape 几个扫描器修过的 silent-skip-on-missing-source 同款修复。

    反向注入只验证 "main() 在 layer-0 抓到 missing 源 locale 后立刻
    fail 2" 的契约；真实 happy path 由 ``TestEndToEndScan`` 兜底。
    """

    def _run_main(
        self,
        argv: list[str],
        web_locales: Path,
        vscode_locales: Path,
        capsys: pytest.CaptureFixture[str],
        web_js: Path | None = None,
        vscode_pkg: Path | None = None,
    ) -> tuple[int, str, str]:
        """Helper：run main() with locale & JS source directories
        monkey-patched on a fresh module load (避免污染 module-level
        ``CHK`` 给同 process 其他测试)。capture stdout/stderr, return
        (rc, out, err)."""
        import importlib.util as _ilu

        spec = _ilu.spec_from_file_location("_chk_param_isolated", SCRIPT)
        assert spec is not None and spec.loader is not None
        mod = _ilu.module_from_spec(spec)
        sys.modules["_chk_param_isolated"] = mod
        spec.loader.exec_module(mod)
        # ty 看不到动态加载模块的 module-level 常量，用 ignore 注释抑制
        # unresolved-attribute false-positive；运行时直接属性赋值等价。
        mod.WEB_LOCALES_DIR = web_locales  # ty: ignore[unresolved-attribute]
        mod.VSCODE_LOCALES_DIR = vscode_locales  # ty: ignore[unresolved-attribute]
        if web_js is not None:
            mod.WEB_JS_DIR = web_js  # ty: ignore[unresolved-attribute]
        if vscode_pkg is not None:
            mod.VSCODE_PKG_DIR = vscode_pkg  # ty: ignore[unresolved-attribute]
        rc = mod.main(argv)
        captured = capsys.readouterr()
        return rc, captured.out, captured.err

    def test_missing_web_en_returns_2_with_r110_tag(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Web ``en.json`` 缺失 → main 返回 2 + 含 R110 tag + 含相对路径。"""
        web_locales = tmp_path / "web_locales_no_en"
        vscode_locales = tmp_path / "vscode_locales"
        web_locales.mkdir()
        vscode_locales.mkdir()
        (vscode_locales / "en.json").write_text("{}", encoding="utf-8")

        rc, _out, err = self._run_main(
            ["--strict"], web_locales, vscode_locales, capsys
        )
        assert rc == 2, (
            f"missing web en.json must yield exit 2 (got {rc}); stderr:\n{err}"
        )
        assert "R110" in err, f"diagnostic must mention R110; stderr:\n{err}"
        assert "Web UI 源 locale" in err, f"label missing; stderr:\n{err}"

    def test_missing_vscode_en_returns_2_with_r110_tag(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """VS Code ``en.json`` 缺失 → 同款 fail 2."""
        web_locales = tmp_path / "web_locales"
        vscode_locales = tmp_path / "vscode_locales_no_en"
        web_locales.mkdir()
        vscode_locales.mkdir()
        (web_locales / "en.json").write_text("{}", encoding="utf-8")

        rc, _out, err = self._run_main(
            ["--strict"], web_locales, vscode_locales, capsys
        )
        assert rc == 2, (
            f"missing vscode en.json must yield exit 2 (got {rc}); stderr:\n{err}"
        )
        assert "R110" in err
        assert "VS Code 源 locale" in err

    def test_both_missing_lists_both_paths(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """两个 ``en.json`` 都缺时 stderr 必须列出**两条** missing 信息。"""
        web_locales = tmp_path / "web_locales_no_en"
        vscode_locales = tmp_path / "vscode_locales_no_en"
        web_locales.mkdir()
        vscode_locales.mkdir()

        rc, _out, err = self._run_main(
            ["--strict"], web_locales, vscode_locales, capsys
        )
        assert rc == 2
        assert "Web UI 源 locale" in err
        assert "VS Code 源 locale" in err
        assert err.count("Resolved absolute path") == 2

    def test_happy_path_returns_0(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """两个 ``en.json`` 都存在且无 mismatch → exit 0。

        端到端验证：layer-0 不误伤 happy path。注意必须也 patch
        ``WEB_JS_DIR`` / ``VSCODE_PKG_DIR`` 到空目录，否则 ``_scan_*``
        会扫真实仓库代码、找到 t() call site 的 keys，但 monkey-patched
        locale 是 ``{}`` 空 → 所有 keys 报 unknown-key。"""
        web_locales = tmp_path / "web_locales"
        vscode_locales = tmp_path / "vscode_locales"
        web_js = tmp_path / "web_js"
        vscode_pkg = tmp_path / "vscode_pkg"
        web_locales.mkdir()
        vscode_locales.mkdir()
        web_js.mkdir()
        vscode_pkg.mkdir()
        (web_locales / "en.json").write_text("{}", encoding="utf-8")
        (vscode_locales / "en.json").write_text("{}", encoding="utf-8")

        rc, out, _err = self._run_main(
            ["--strict"],
            web_locales,
            vscode_locales,
            capsys,
            web_js=web_js,
            vscode_pkg=vscode_pkg,
        )
        assert rc == 0, f"happy path must exit 0 (got {rc}); stdout:\n{out}"

    def test_diagnostic_includes_remediation_hint(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """缺 source 时 stderr 必须包含修复指引（更新 WEB_LOCALES_DIR /
        VSCODE_LOCALES_DIR 常量），与 R102 ``check_locales.py`` 同款
        "tell me how to fix it" 模式。"""
        web_locales = tmp_path / "web_locales_no_en"
        vscode_locales = tmp_path / "vscode_locales_no_en"
        web_locales.mkdir()
        vscode_locales.mkdir()

        rc, _out, err = self._run_main(
            ["--strict"], web_locales, vscode_locales, capsys
        )
        assert rc == 2
        assert "WEB_LOCALES_DIR" in err
        assert "VSCODE_LOCALES_DIR" in err


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
