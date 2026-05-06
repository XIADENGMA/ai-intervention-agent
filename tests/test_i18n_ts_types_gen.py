"""P9·L8 — 守护生成的 ``packages/vscode/i18n-keys.d.ts``。

TypeScript ``I18nKey`` literal union 给 ``extension.ts`` 里 ``hostT(...)``
提供 compile-time 护甲；一旦生成器与 ``.d.ts`` / ``en.json`` 漂移，
tsc 就不再捕捉 typo。合约：
  1. 已提交 ``.d.ts`` 与当下生成结果一致（相当于 ``--check``）；
  2. 生成的每个 key 都在 ``packages/vscode/locales/en.json`` 里
     （无 stale / duplicate）；
  3. ``extension.ts`` 里用到的 ``hostT(...)`` key 全在 union 中；
  4. 生成结果幂等——同输入跑两次 byte-identical。

不在 pytest 里起 ``tsc`` 子进程（代价 + 跨平台），静态串检查即可。
"""

from __future__ import annotations

import importlib.util
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "gen_i18n_types.py"
EN_JSON = ROOT / "packages" / "vscode" / "locales" / "en.json"
DTS = ROOT / "packages" / "vscode" / "i18n-keys.d.ts"
EXTENSION_TS = ROOT / "packages" / "vscode" / "extension.ts"


def _load_gen_module():
    """Import ``scripts/gen_i18n_types.py`` without running ``main``.

    We use ``importlib.util`` so pytest can call the helpers directly
    — reusing them instead of reimplementing flatten/render keeps the
    script and its tests in lockstep."""
    spec = importlib.util.spec_from_file_location("gen_i18n_types", SCRIPT)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["gen_i18n_types"] = mod
    spec.loader.exec_module(mod)
    return mod


GEN = _load_gen_module()


class TestGeneratorDeterminism:
    def test_render_is_deterministic(self) -> None:
        keys = ["b.key", "a.key", "c.key"]
        first = GEN.render_dts(keys)
        second = GEN.render_dts(keys)
        assert first == second

    def test_render_sorts_keys(self) -> None:
        # Input order doesn't matter — output always sorted.
        unordered = GEN.render_dts(["zebra.key", "alpha.key"])
        ordered = GEN.render_dts(["alpha.key", "zebra.key"])
        assert unordered == ordered
        alpha_idx = unordered.index('"alpha.key"')
        zebra_idx = unordered.index('"zebra.key"')
        assert alpha_idx < zebra_idx

    def test_render_deduplicates(self) -> None:
        out = GEN.render_dts(["dup.key", "dup.key", "uniq.key"])
        assert out.count('"dup.key"') == 2  # once in union, once in array
        assert out.count('"uniq.key"') == 2


class TestGeneratorFlatten:
    def test_flatten_preserves_leaves(self) -> None:
        data = {"a": {"b": "leaf1", "c": "leaf2"}, "d": "leaf3"}
        flat = GEN._flatten(data)
        assert set(flat) == {"a.b", "a.c", "d"}

    def test_flatten_skips_non_string_leaves(self) -> None:
        # JSON allows arrays / numbers / bool as leaves — those can't
        # be ICU templates so the generator must skip them.
        data = {"a": "str", "b": 42, "c": [1, 2, 3], "d": True}
        flat = GEN._flatten(data)
        assert set(flat) == {"a"}


class TestCommittedDtsIsUpToDate:
    """This is the CI-gate check reified as a pytest so local
    developers get the same signal from ``pytest -k i18n`` as CI."""

    def test_dts_matches_generator_output(self) -> None:
        keys = GEN.load_keys(EN_JSON)
        generated = GEN.render_dts(keys)
        actual = DTS.read_text(encoding="utf-8") if DTS.exists() else ""
        assert actual == generated, (
            "packages/vscode/i18n-keys.d.ts is out of date. "
            "Run `uv run python scripts/gen_i18n_types.py`."
        )


class TestDtsContainsAllLocaleKeys:
    def test_every_locale_key_is_in_the_union(self) -> None:
        locale_keys = set(GEN.load_keys(EN_JSON))
        # The .d.ts keys are the JSON-quoted literals inside the
        # `export type I18nKey = | "..."` union.
        text = DTS.read_text(encoding="utf-8")
        dts_keys = set(re.findall(r'\|\s+"([^"]+)"', text))
        assert dts_keys == locale_keys, (
            f"dts ↔ locale mismatch:\n"
            f"  only in dts: {sorted(dts_keys - locale_keys)}\n"
            f"  only in locale: {sorted(locale_keys - dts_keys)}"
        )


class TestHostTCallsAreTypeable:
    """Every ``hostT('...')`` literal in ``extension.ts`` must resolve
    to a key the generated union knows about — otherwise the TS
    compiler would reject them and the extension wouldn't build."""

    _HOST_T_RE = re.compile(r"""hostT\(\s*['"]([^'"]+)['"]""")

    @staticmethod
    def _strip_comments(source: str) -> str:
        """Remove ``// ...`` line comments and ``/* ... */`` block
        comments so the regex scan doesn't see example snippets that
        we include in banner docstrings."""
        block = re.sub(r"/\*.*?\*/", "", source, flags=re.DOTALL)
        lines = []
        for raw in block.splitlines():
            idx = raw.find("//")
            lines.append(raw if idx == -1 else raw[:idx])
        return "\n".join(lines)

    def test_all_hostt_keys_present_in_dts(self) -> None:
        if not EXTENSION_TS.is_file():
            pytest.skip("extension.ts not present in this tree")  # ty: ignore[too-many-positional-arguments]
        text = self._strip_comments(EXTENSION_TS.read_text(encoding="utf-8"))
        used = set(self._HOST_T_RE.findall(text))
        assert used, "expected at least one hostT('key') call"
        locale_keys = set(GEN.load_keys(EN_JSON))
        missing = used - locale_keys
        assert not missing, (
            f"extension.ts calls hostT(...) with keys not in en.json: {sorted(missing)}"
        )


class TestCliEntrypoints:
    """Exercise the real subprocess surface so the argparse wiring
    doesn't regress."""

    def test_check_mode_exits_zero_when_up_to_date(self) -> None:
        proc = subprocess.run(
            [sys.executable, str(SCRIPT), "--check"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        assert proc.returncode == 0, (
            f"gen_i18n_types.py --check failed:\nstdout={proc.stdout!r}\nstderr={proc.stderr!r}"
        )
        assert "up to date" in proc.stdout

    def test_stdout_mode_prints_dts(self) -> None:
        proc = subprocess.run(
            [sys.executable, str(SCRIPT), "--stdout"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        assert proc.returncode == 0
        assert "export type I18nKey" in proc.stdout
        # Verify each union line is valid by checking round-trip.
        keys_in_stdout = set(re.findall(r'\|\s+"([^"]+)"', proc.stdout))
        keys_on_disk = set(GEN.load_keys(EN_JSON))
        assert keys_in_stdout == keys_on_disk


class TestReadableBanner:
    """Guard the ``do not edit`` banner so contributors get the hint
    before they spend an hour hand-editing the .d.ts."""

    def test_banner_mentions_regenerate_script(self) -> None:
        text = DTS.read_text(encoding="utf-8")
        assert text.startswith("//"), "first line should be a comment banner"
        assert "do not edit" in text.lower()
        assert "gen_i18n_types.py" in text


if __name__ == "__main__":
    import pytest as _pytest

    _pytest.main([__file__, "-v"])
