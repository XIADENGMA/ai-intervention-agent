"""G4 pytest: verify ``scripts/gen_pseudo_locale.py`` produces a
well-formed, up-to-date pseudo locale for both Web UI and VSCode webview.

What this test asserts:
1. Pseudo locale files exist at the expected path
   (``<locales>/_pseudo/pseudo.json``).
2. ``--check`` mode is green — i.e. committed pseudo files are in sync
   with the current ``en.json`` on each side.
3. Key set / nesting structure of ``pseudo.json`` mirrors ``en.json``.
4. Every leaf string has been transformed (wrapped in ``[!! !!]``)
   and preserves all ``{{placeholder}}`` tokens verbatim.
5. The transformation is deterministic (running pseudoize twice on the
   same input gives the same output), so ``--check`` is reliable.

Why these checks (and not just "did the generator run"):
- Invariant 3 protects against key drift (en.json adds a key but the
  committed pseudo.json wasn't regenerated).
- Invariant 4 is the **whole point** of pseudo-localization: a string
  that isn't bracketed never went through ``t()`` — it's a hardcoded
  leak that QA would catch at render time.
- Invariant 5 guards against non-determinism creeping into the
  generator (e.g. someone adds a random character insertion) which
  would make ``--check`` flaky.
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

WEB_PSEUDO = ROOT / "static" / "locales" / "_pseudo" / "pseudo.json"
VSCODE_PSEUDO = ROOT / "packages" / "vscode" / "locales" / "_pseudo" / "pseudo.json"
WEB_EN = ROOT / "static" / "locales" / "en.json"
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
            pytest.skip(f"{en_path} not present")
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
            pytest.skip(f"{pseudo_path} not present")
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
        if not (en_path.is_file() and pseudo_path.is_file()):
            pytest.skip("locale file missing")
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
