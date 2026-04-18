"""P7·L4·step-3: every locale JSON under ``static/locales/`` MUST expose
the same set of keys (recursively), with the same value type, so the
client's ``t()`` fallback-to-DEFAULT_LANG path is uniform across locales.

Background:
    ``static/js/i18n.js::t`` implements ``currentLang → DEFAULT_LANG``
    fallback. That mechanism exists so a newly added English key doesn't
    render raw ``foo.bar.baz`` in Chinese until translators catch up.
    But the fallback is single-hop: if a Chinese-only key (for whatever
    reason the English file forgot) is missing on English, Chinese users
    see the translation while English users see the raw key. The project
    has historically kept a strict parity invariant — every key in one
    locale must appear in every other locale — but without a test, the
    invariant drifts every time a contributor adds a key on only one
    side.

Scope & rationale:
    * **Structural parity**: key SET (recursively flattened via dot
      notation) must be equal across all locales.
    * **Type parity**: if ``foo.bar`` is an object in one locale, it
      must be an object in every locale (never a leaf string). This
      catches the subtle bug where one side was refactored from
      ``{"foo": "flat"}`` to ``{"foo": {"short": "flat"}}`` but the
      other side was not.
    * **Placeholder parity**: if the English says ``"Hello {{name}}"``,
      every other locale MUST also include ``{{name}}`` — otherwise
      interpolation silently drops the parameter. This is critical for
      messages like ``env.secureOrigin`` which injects the page origin,
      or ``status.barkTestFailed`` which injects the failure reason.

Why this file and not a runtime ``scripts/check_locales.py`` only:
    ``scripts/check_locales.py`` already exists and is the CI gate. But
    CI gates can be disabled or bypassed; a pytest assertion is invoked
    by the default test runner and fails fast during local development
    *before* a contributor pushes. Duplicating the logic here is cheap
    (both implementations stay small) and raises the floor.
"""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
LOCALES_DIR = REPO_ROOT / "static" / "locales"


def _load_locales() -> dict[str, dict[str, Any]]:
    """Load every ``*.json`` under ``static/locales/`` as a parsed dict."""
    result: dict[str, dict[str, Any]] = {}
    for path in sorted(LOCALES_DIR.glob("*.json")):
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


if __name__ == "__main__":
    unittest.main()
