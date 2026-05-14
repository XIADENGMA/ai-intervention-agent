"""G4 / R107：校验 ``scripts/gen_pseudo_locale.py`` 对 Web UI / VSCode webview
两侧生成的 pseudo locale 形状正确且保持最新。

合约：
  1. ``<locales>/_pseudo/pseudo.json`` 存在；
  2. ``--check`` 绿——committed pseudo 与各自 en.json 同步；
  3. key 集合 / 嵌套结构与 en.json 镜像；
  4. 每个叶子串都被 ``[!! !!]`` 包裹且 ``{{placeholder}}`` 原样保留；
  5. 变换幂等——同输入两次 pseudoize 结果一致，``--check`` 才稳。

合约 3 防 key drift；合约 4 是 pseudo-localization 全部意义所在（未括
起来的串等于漏了 ``t()``，QA 渲染时能直观发现）；合约 5 防有人往
generator 里塞随机字符让 ``--check`` flaky。

R107：原实现对「``en.json`` / ``pseudo.json`` 不存在」用 ``pytest.skip``
silent skip。这 4 个 locale 文件都是项目 i18n 单一源，缺失即配置漂移
（与 R104 ``main.css/webview.css`` / R105 ``packages/vscode/i18n.js``
/ R102 ``check_locales.py`` 的 6 个核心资源同款）。改成 ``pytest.fail``
让 reviewer 立刻看到漂移，与 R88/R100/R101/R102/R104/R105/R106 silent-
skip 修复家族对齐。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.gen_pseudo_locale import (
    PLACEHOLDER_RE,
    PREFIX,
    SUFFIX,
    main,
    pseudoize,
)

WEB_PSEUDO = (
    ROOT
    / "src"
    / "ai_intervention_agent"
    / "static"
    / "locales"
    / "_pseudo"
    / "pseudo.json"
)
VSCODE_PSEUDO = ROOT / "packages" / "vscode" / "locales" / "_pseudo" / "pseudo.json"
WEB_EN = ROOT / "src" / "ai_intervention_agent" / "static" / "locales" / "en.json"
VSCODE_EN = ROOT / "packages" / "vscode" / "locales" / "en.json"


def _flatten(data, prefix=""):
    out = {}
    if isinstance(data, dict):
        for k, v in data.items():
            p = f"{prefix}.{k}" if prefix else k
            if isinstance(v, dict):
                out.update(_flatten(v, p))
            elif isinstance(v, str):
                out[p] = v
    return out


class TestPseudoizeFn:
    """Unit tests for the core ``pseudoize`` transform."""

    def test_empty_passes_through(self):
        assert pseudoize("") == ""

    def test_wraps_with_bracket_markers(self):
        out = pseudoize("Hello")
        assert out.startswith(PREFIX), out
        assert out.endswith(SUFFIX), out

    def test_preserves_placeholder_names_and_syntax(self):
        src = "Hello {{name}}, you have {{count}} tasks"
        out = pseudoize(src)
        # placeholder 名称必须完全保留（内容、大小写、空白）
        # 顺序也必须保留
        names_in = PLACEHOLDER_RE.findall(src)
        names_out = PLACEHOLDER_RE.findall(out)
        assert names_in == names_out

    def test_transforms_letters_outside_placeholders(self):
        out = pseudoize("Hello {{name}}")
        # 剥掉 prefix/suffix/placeholder 后应该已被变换（至少 1 字符 非 ASCII）
        inner = out[len(PREFIX) : -len(SUFFIX)]
        # placeholder 完整段作为一整块保留，取它之外的部分
        non_placeholder = PLACEHOLDER_RE.sub("", inner)
        assert any(ord(c) > 127 for c in non_placeholder), (
            f"expected at least one non-ASCII char, got {non_placeholder!r}"
        )

    def test_idempotent_for_check_mode(self):
        """Running pseudoize twice on the same input gives the same output.

        关键：--check 模式依赖此不变量。若 generator 对同一输入产生两种
        输出（例如加入随机插入位置），--check 将成为 flaky test。"""
        src = "The quick brown fox jumps"
        assert pseudoize(src) == pseudoize(src)

    def test_preserves_icu_plural_keywords(self):
        """ICU 关键字 (plural/select/one/other/=N/argName) 必须原样保留。

        否则 runtime 端 i18n.js::_renderIcu 无法识别 kind/category，
        整条消息会退化为模板字符串，pseudo locale 将彻底丧失 QA 价值。"""
        src = "Have {count, plural, one {# task} other {# tasks}} left"
        out = pseudoize(src)
        # 结构关键字必须逐字节出现在 pseudo 输出中
        for token in ("{count,", "plural,", "one {", "other {"):
            assert token in out, f"ICU keyword {token!r} lost in pseudo: {out!r}"

    def test_preserves_icu_select_keywords(self):
        src = "{gender, select, male {he} female {she} other {they}}"
        out = pseudoize(src)
        for token in ("{gender,", "select,", "male {", "female {", "other {"):
            assert token in out, f"ICU keyword {token!r} lost in pseudo: {out!r}"

    def test_icu_option_body_is_pseudoized(self):
        """ICU 外壳保留，但 option body 里的 `task`/`tasks` 文本必须 pseudo 化。"""
        src = "{count, plural, one {# task} other {# tasks}}"
        out = pseudoize(src)
        # 纯 ASCII 的 body 字符应已被替换为重音变体 (至少 1 个 non-ASCII)
        # 剥掉 prefix/suffix + ICU 关键字后仍应含非 ASCII
        stripped = out[len(PREFIX) : -len(SUFFIX)]
        for kw in ("{count,", "plural,", "one {", "other {", "}"):
            stripped = stripped.replace(kw, "")
        assert any(ord(c) > 127 for c in stripped), (
            f"option body not pseudoized: {out!r}"
        )


class TestPseudoFilesInSyncWithEn:
    """committed pseudo files must match what the generator would produce
    right now (i.e. ``--check`` is green)."""

    def test_check_mode_is_green(self, capsys):
        # 不重新生成，只校验；若失败代表有人改了 en.json 但忘记跑 gen 脚本
        rc = main(["--check"])
        out = capsys.readouterr().out
        assert rc == 0, f"--check failed:\n{out}"


class TestPseudoStructuralParity:
    """Pseudo 文件结构必须与 en.json 键集/嵌套完全一致。"""

    @pytest.mark.parametrize(
        ("en_path", "pseudo_path"),
        [
            (WEB_EN, WEB_PSEUDO),
            (VSCODE_EN, VSCODE_PSEUDO),
        ],
    )
    def test_key_sets_match(self, en_path: Path, pseudo_path: Path):
        if not en_path.is_file():
            # 预先求值并赋给单变量避开 ty 对 pytest.fail 多 positional args
            # 的 false-positive（多行 f-string 隐式拼接 / call expr 会被 ty
            # 解析成多参传递）。
            reason: str = (
                f"R107: en locale missing: {en_path}\n"
                f"  This is configuration drift (i18n single-source missing),\n"
                f"  not 'OK' — failing loud per R107 (matches R102/R104/R105\n"
                f"  silent-skip purge family). Either restore the file or\n"
                f"  update WEB_EN/VSCODE_EN at top of "
                f"tests/test_i18n_pseudo_locale.py."
            )
            pytest.fail(reason)
        assert pseudo_path.is_file(), (
            f"Missing {pseudo_path}. Run gen_pseudo_locale.py."
        )
        en = _flatten(json.loads(en_path.read_text(encoding="utf-8")))
        pseudo = _flatten(json.loads(pseudo_path.read_text(encoding="utf-8")))
        en_keys = set(en)
        pseudo_keys = set(pseudo)
        missing = sorted(en_keys - pseudo_keys)
        extra = sorted(pseudo_keys - en_keys)
        assert not missing, f"pseudo missing keys from en.json: {missing[:5]}..."
        assert not extra, f"pseudo has extra keys not in en.json: {extra[:5]}..."


class TestEveryLeafTransformed:
    """Every non-empty leaf of pseudo.json MUST be wrapped with ``[!! !!]``.
    This is the core *purpose* of pseudo-loc: a string that slipped through
    without wrapping is a hardcoded English leak (or a bug in the generator)."""

    @pytest.mark.parametrize("pseudo_path", [WEB_PSEUDO, VSCODE_PSEUDO])
    def test_all_leaves_are_bracketed(self, pseudo_path: Path):
        if not pseudo_path.is_file():
            reason: str = (
                f"R107: pseudo locale missing: {pseudo_path}\n"
                f"  Run ``uv run python scripts/gen_pseudo_locale.py`` to (re)generate.\n"
                f"  silent skip would mask the case where someone deletes "
                f"_pseudo/pseudo.json\n"
                f"  while leaving en.json fresh — this whole test class would no-op."
            )
            pytest.fail(reason)
        leaves = _flatten(json.loads(pseudo_path.read_text(encoding="utf-8")))
        broken: list[tuple[str, str]] = []
        for k, v in leaves.items():
            if not v:
                continue  # 空串允许
            if not (v.startswith(PREFIX) and v.endswith(SUFFIX)):
                broken.append((k, v[:40]))
        assert not broken, f"unbracketed pseudo leaves: {broken[:5]}"

    @pytest.mark.parametrize(
        ("en_path", "pseudo_path"), [(WEB_EN, WEB_PSEUDO), (VSCODE_EN, VSCODE_PSEUDO)]
    )
    def test_placeholders_preserved(self, en_path: Path, pseudo_path: Path):
        """en.json 中的每个 {{name}} 必须在对应 pseudo 字符串里**原样**出现。"""
        if not en_path.is_file() or not pseudo_path.is_file():
            missing_paths: list[str] = []
            if not en_path.is_file():
                missing_paths.append(f"en={en_path}")
            if not pseudo_path.is_file():
                missing_paths.append(f"pseudo={pseudo_path}")
            reason: str = (
                f"R107: locale file(s) missing: {', '.join(missing_paths)}\n"
                f"  This is configuration drift; failing loud per R107.\n"
                f"  Restore the missing files or fix the path constants in "
                f"tests/test_i18n_pseudo_locale.py."
            )
            pytest.fail(reason)
        en_leaves = _flatten(json.loads(en_path.read_text(encoding="utf-8")))
        ps_leaves = _flatten(json.loads(pseudo_path.read_text(encoding="utf-8")))
        missing: list[str] = []
        for k, en_val in en_leaves.items():
            wanted = PLACEHOLDER_RE.findall(en_val)
            if not wanted:
                continue
            got = PLACEHOLDER_RE.findall(ps_leaves.get(k, ""))
            if sorted(wanted) != sorted(got):
                missing.append(f"{k}: en={wanted} pseudo={got}")
        assert not missing, f"placeholder drift: {missing[:5]}"
