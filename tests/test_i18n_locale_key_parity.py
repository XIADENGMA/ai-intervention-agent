"""P7·L4·step-3：``static/locales/*.json`` 的每个 locale 必须（递归）暴露
相同 key 集合、相同值类型，``t()`` 的 ``currentLang → DEFAULT_LANG`` 回落
路径才在各 locale 间一致。

回落是单跳：若某 key 只在 zh-CN 有而 en 缺，zh-CN 用户看翻译，en 用户
看 raw key。项目历来强制 parity，但没测试时每次只单侧加 key 就会漂移。

合约：
  * 结构 parity：递归扁平化后的 key SET 跨 locale 相等；
  * 类型 parity：某 ``foo.bar`` 若在一 locale 是 object，其他 locale 必须
    也是 object——挡住「一侧从 flat 重构到 nested 另一侧没跟进」的坑；
  * 占位符 parity：英文是 ``"Hello {{name}}"``，其他 locale 也必须带
    ``{{name}}``，否则 interpolation 静默丢参数。比如 ``env.secureOrigin``
    注入页面 origin、``status.barkTestFailed`` 注入失败原因都是关键占位。

为什么不只靠 ``scripts/check_locales.py``：CI gate 可以被 disable / bypass，
pytest 在本地 ``pytest`` 默认跑，在 push 之前就能挡。逻辑双轨冗余很便宜，
抬高下限。
"""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
LOCALES_DIR = REPO_ROOT / "static" / "locales"
VSCODE_LOCALES_DIR = REPO_ROOT / "packages" / "vscode" / "locales"


def _load_locales(dir_path: Path = LOCALES_DIR) -> dict[str, dict[str, Any]]:
    """Load every ``*.json`` under the given locale directory."""
    result: dict[str, dict[str, Any]] = {}
    for path in sorted(dir_path.glob("*.json")):
        result[path.stem] = json.loads(path.read_text(encoding="utf-8"))
    return result


def _flatten_paths(data: Any, prefix: str = "") -> dict[str, str]:
    """Flatten a nested locale dict into ``dotted.path → typeof(leaf)``.

    Leaf types are either ``"str"`` (value is a translated string) or
    ``"obj"`` (value is a nested namespace). Keys that are literal
    strings containing ``.`` (see ``page.skipToContent`` in en.json,
    which is historically flat for compatibility) are preserved as-is
    by joining with the full prefix — the dotted notation in the key
    itself is respected because both locales would encode it the same
    way.
    """
    out: dict[str, str] = {}
    if isinstance(data, dict):
        for k, v in data.items():
            path = f"{prefix}.{k}" if prefix else k
            if isinstance(v, dict):
                out[path] = "obj"
                out.update(_flatten_paths(v, path))
            else:
                out[path] = "str"
    return out


PLACEHOLDER_RE = re.compile(r"\{\{\s*(\w+)\s*\}\}")


def _collect_placeholders(data: Any, prefix: str = "") -> dict[str, set[str]]:
    """Return ``dotted.path → {placeholder_names}`` for every leaf string.

    A placeholder is a ``{{name}}`` sequence (whitespace-tolerant). Any
    string leaf is included even if empty set (e.g. ``"page.cancel"``
    has no placeholders; it still appears in the output with value
    ``frozenset()``)."""
    out: dict[str, set[str]] = {}
    if isinstance(data, dict):
        for k, v in data.items():
            path = f"{prefix}.{k}" if prefix else k
            if isinstance(v, dict):
                out.update(_collect_placeholders(v, path))
            elif isinstance(v, str):
                out[path] = set(PLACEHOLDER_RE.findall(v))
    return out


class TestLocalesExist(unittest.TestCase):
    """Minimum invariant: at least ``en`` + ``zh-CN`` exist and load
    without exceptions. If either disappears, every subsequent test
    would silently pass on the remaining half, so this guard must come
    first."""

    def test_locales_directory_exists(self) -> None:
        self.assertTrue(
            LOCALES_DIR.is_dir(),
            msg=f"Expected {LOCALES_DIR} to be a directory containing *.json locales",
        )

    def test_en_locale_loadable(self) -> None:
        path = LOCALES_DIR / "en.json"
        self.assertTrue(path.is_file(), msg=f"Missing {path}")
        json.loads(path.read_text(encoding="utf-8"))

    def test_zh_cn_locale_loadable(self) -> None:
        path = LOCALES_DIR / "zh-CN.json"
        self.assertTrue(path.is_file(), msg=f"Missing {path}")
        json.loads(path.read_text(encoding="utf-8"))


class TestStructuralParity(unittest.TestCase):
    """Every locale MUST expose the same (key, type) pairs. ``en`` is
    the authoritative reference."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.locales = _load_locales()
        assert "en" in cls.locales, "en.json is required as the reference locale"
        cls.reference_paths = _flatten_paths(cls.locales["en"])

    def test_all_locales_have_same_key_set(self) -> None:
        ref_keys = set(self.reference_paths)
        for name, data in self.locales.items():
            if name == "en":
                continue
            got = set(_flatten_paths(data))
            missing = sorted(ref_keys - got)
            extra = sorted(got - ref_keys)
            if missing or extra:
                self.fail(
                    f"Locale {name!r} drifted from en.json reference.\n"
                    f"  missing in {name}: {missing}\n"
                    f"  extra in {name}:   {extra}\n"
                    f"Fix: keep en.json + {name}.json key sets identical. "
                    f"Missing keys mean {name} users see raw 'foo.bar' instead "
                    f"of translation (or fall back to English silently); "
                    f"extra keys mean the key is unused (or worse, en users "
                    f"see raw 'foo.bar' because the English fallback chain "
                    f"cannot reach it)."
                )

    def test_all_locales_have_same_type_per_path(self) -> None:
        for name, data in self.locales.items():
            if name == "en":
                continue
            got = _flatten_paths(data)
            for path, ref_type in self.reference_paths.items():
                if path not in got:
                    continue
                got_type = got[path]
                self.assertEqual(
                    ref_type,
                    got_type,
                    msg=(
                        f"Locale {name!r} path {path!r} is {got_type!r} "
                        f"but en.json has {ref_type!r}. Swapping a leaf "
                        f"string for a namespace dict (or vice versa) "
                        f"breaks t() lookups silently — t('foo.bar') "
                        f"either returns undefined if a leaf became a "
                        f"namespace, or overwrites textContent with "
                        f"'[object Object]' if a namespace became a leaf "
                        f"via resolve() taking a wrong branch."
                    ),
                )


class TestPlaceholderParity(unittest.TestCase):
    """If en.json says ``Hello {{name}}``, every other locale MUST also
    include ``{{name}}`` so interpolation produces the same user-visible
    output. A mismatch usually means a translator localized the prose
    but forgot to carry the placeholder (or accidentally introduced a
    new placeholder that has no corresponding ``t()`` call)."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.locales = _load_locales()
        cls.reference_placeholders = _collect_placeholders(cls.locales["en"])

    def test_placeholders_match_reference(self) -> None:
        failures: list[str] = []
        for name, data in self.locales.items():
            if name == "en":
                continue
            got = _collect_placeholders(data)
            for path, ref_set in self.reference_placeholders.items():
                if path not in got:
                    continue  # already reported as a missing key elsewhere
                got_set = got[path]
                if got_set != ref_set:
                    missing = sorted(ref_set - got_set)
                    extra = sorted(got_set - ref_set)
                    failures.append(
                        f"  {name}::{path}: expected placeholders {sorted(ref_set)}, "
                        f"got {sorted(got_set)} (missing={missing}, extra={extra})"
                    )
        if failures:
            self.fail(
                "Placeholder mismatch between locales and en.json:\n"
                + "\n".join(failures)
                + "\nFix: every translation must reference the same "
                "{{placeholder}} names as the English original. Adding a "
                "placeholder only in one locale silently drops the parameter "
                "on that locale (it renders the literal {{name}} in output); "
                "omitting a placeholder means the parameter is never injected."
            )


class TestVSCodeLocalesParity(unittest.TestCase):
    """Mirror structural + placeholder parity checks for the VSCode webview
    locale directory (``packages/vscode/locales/``). The static-gate script
    ``scripts/check_i18n_locale_parity.py`` already walks this directory,
    but without a pytest mirror a contributor running ``pytest -q`` locally
    would only see Web UI regressions and miss VSCode drift until the full
    ``ci_gate`` runs. P9-L1 adds the pytest layer for symmetry."""

    @classmethod
    def setUpClass(cls) -> None:
        if not VSCODE_LOCALES_DIR.is_dir():
            raise unittest.SkipTest(f"{VSCODE_LOCALES_DIR} not present")
        cls.locales = _load_locales(VSCODE_LOCALES_DIR)
        if "en" not in cls.locales:
            raise unittest.SkipTest("VSCode locale directory missing en.json")
        cls.reference_paths = _flatten_paths(cls.locales["en"])
        cls.reference_placeholders = _collect_placeholders(cls.locales["en"])

    def test_vscode_locales_have_same_key_set(self) -> None:
        ref_keys = set(self.reference_paths)
        for name, data in self.locales.items():
            if name == "en":
                continue
            got = set(_flatten_paths(data))
            missing = sorted(ref_keys - got)
            extra = sorted(got - ref_keys)
            if missing or extra:
                self.fail(
                    f"[VSCode] locale {name!r} drifted from en.json reference.\n"
                    f"  missing in {name}: {missing}\n"
                    f"  extra in {name}:   {extra}"
                )

    def test_vscode_locales_have_same_type_per_path(self) -> None:
        for name, data in self.locales.items():
            if name == "en":
                continue
            got = _flatten_paths(data)
            for path, ref_type in self.reference_paths.items():
                if path not in got:
                    continue
                self.assertEqual(
                    ref_type,
                    got[path],
                    msg=f"[VSCode] {name}.json {path!r} is {got[path]!r} vs en {ref_type!r}",
                )

    def test_vscode_placeholders_match_reference(self) -> None:
        failures: list[str] = []
        for name, data in self.locales.items():
            if name == "en":
                continue
            got = _collect_placeholders(data)
            for path, ref_set in self.reference_placeholders.items():
                if path not in got:
                    continue
                if got[path] != ref_set:
                    missing = sorted(ref_set - got[path])
                    extra = sorted(got[path] - ref_set)
                    failures.append(
                        f"  [VSCode] {name}::{path}: expected {sorted(ref_set)}, "
                        f"got {sorted(got[path])} (missing={missing}, extra={extra})"
                    )
        if failures:
            self.fail(
                "Placeholder mismatch between VSCode locales and en.json:\n"
                + "\n".join(failures)
            )


if __name__ == "__main__":
    unittest.main()
