"""P9·L9·G2 — pseudo-locale length-inflation assertions.

The industry-standard target (Microsoft MSDN, Google Material, Apple
HIG) for pseudo-localized strings is **≥30%** longer than the source.
This reliably surfaces layout issues in:

- Buttons / chips that were sized for short English copy
- Tooltips with fixed ``max-width``
- Modal titles with ``text-overflow: ellipsis``
- Sidebar labels that wrap to two lines

Our ``scripts/gen_pseudo_locale.py`` claims "~35% longer" in its
docstring but nothing pinned that claim. This file adds the pin:

1. **Per-file** average inflation must hit the ≥30% target.
2. Every leaf value must be wrapped in ``[!! ... !!]`` brackets so
   QA can distinguish pseudo-translated strings from hardcoded
   English (un-bracketed strings are i18n coverage gaps).
3. Mustache placeholders (``{{name}}``) must round-trip unchanged —
   any expansion added inside them would break runtime substitution.
4. ICU plural/select structural tokens must round-trip unchanged —
   same reason, the runtime parser would fail to recognize the form.

Together these guard the three failure modes that make a pseudo
locale useless: too short (no overflow pressure), broken structure
(app crashes instead of just looking weird), or incomplete bracket
wrapping (can't tell hardcoded from translated)."""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

WEB_EN = ROOT / "static" / "locales" / "en.json"
WEB_PSEUDO = ROOT / "static" / "locales" / "_pseudo" / "pseudo.json"
VSCODE_EN = ROOT / "packages" / "vscode" / "locales" / "en.json"
VSCODE_PSEUDO = ROOT / "packages" / "vscode" / "locales" / "_pseudo" / "pseudo.json"

# Industry-standard target. We allow a small relaxation on short
# strings because the ``·`` expansion char is inserted every 3 chars,
# which means very short strings round-down to less than 30%. The
# *average* across a corpus, however, must exceed the target.
INFLATION_TARGET = 0.30

MUSTACHE_RE = re.compile(r"\{\{\s*\w+\s*\}\}")
ICU_HEAD_RE = re.compile(r"(?<!\{)\{\s*(\w+)\s*,\s*(plural|select|selectordinal)\s*,")
# Per-option key: e.g., ``one {``, ``=0 {``, ``male {``.
ICU_OPTION_KEY_RE = re.compile(r"\b(one|other|=\d+|male|female|zero|few|many|two)\s*\{")

PREFIX = "[!! "
SUFFIX = " !!]"


def _flatten(data, prefix: str = ""):
    """Yield ``(dotted_key, leaf_string)`` for every string leaf."""
    if isinstance(data, dict):
        for k, v in data.items():
            p = f"{prefix}.{k}" if prefix else k
            yield from _flatten(v, p)
    elif isinstance(data, str):
        yield prefix, data


def _load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _strip_brackets(s: str) -> str:
    if s.startswith(PREFIX) and s.endswith(SUFFIX):
        return s[len(PREFIX) : -len(SUFFIX)]
    return s


def _inflation_ratio(src: str, dst: str) -> float:
    """Ratio of the pseudo-content length over source.

    Excludes bracket markers and mustache/ICU structural tokens on
    both sides so the measurement reflects ACTUAL character expansion
    of natural-language content — not the fixed 8-char bracket
    overhead that would skew short strings.
    """
    src_stripped = _strip_tokens(src)
    dst_stripped = _strip_tokens(_strip_brackets(dst))
    if not src_stripped:
        return 0.0
    return (len(dst_stripped) - len(src_stripped)) / len(src_stripped)


def _strip_tokens(s: str) -> str:
    """Remove mustache placeholders + ICU heads + option keys so only
    the free-form content contributes to the length calculation."""
    out = MUSTACHE_RE.sub("", s)
    out = ICU_HEAD_RE.sub("", out)
    out = ICU_OPTION_KEY_RE.sub("", out)
    return out


class _PseudoInflationMixin:
    en_path: Path
    pseudo_path: Path
    label: str

    def _pairs(self):
        en = dict(_flatten(_load(self.en_path)))
        pseudo = dict(_flatten(_load(self.pseudo_path)))
        assert set(en) == set(pseudo), (
            f"{self.label}: pseudo/en key mismatch\n"
            f"  only in en: {sorted(set(en) - set(pseudo))[:5]}\n"
            f"  only in pseudo: {sorted(set(pseudo) - set(en))[:5]}"
        )
        return en, pseudo

    def test_files_exist(self):
        assert self.en_path.is_file(), f"{self.label}: {self.en_path} missing"
        assert self.pseudo_path.is_file(), f"{self.label}: {self.pseudo_path} missing"

    def test_average_inflation_hits_target(self):
        en, pseudo = self._pairs()
        ratios = []
        for k, src in en.items():
            dst = pseudo[k]
            if not _strip_tokens(src).strip():
                continue
            ratios.append(_inflation_ratio(src, dst))
        assert ratios, f"{self.label}: no non-empty strings to measure"
        avg = sum(ratios) / len(ratios)
        assert avg >= INFLATION_TARGET, (
            f"{self.label}: pseudo-locale inflation {avg:.1%} below "
            f"{INFLATION_TARGET:.0%} target. Expand EXPANSION_EVERY / "
            f"EXPANSION_CHAR in scripts/gen_pseudo_locale.py."
        )

    def test_every_value_wrapped_in_brackets(self):
        _, pseudo = self._pairs()
        unwrapped = [
            k
            for k, v in pseudo.items()
            if not (v.startswith(PREFIX) and v.endswith(SUFFIX))
        ]
        assert not unwrapped, (
            f"{self.label}: {len(unwrapped)} pseudo value(s) missing "
            f"bracket markers — first few: {unwrapped[:5]}"
        )

    def test_mustache_placeholders_roundtrip(self):
        en, pseudo = self._pairs()
        mismatches = []
        for k, src in en.items():
            src_tokens = MUSTACHE_RE.findall(src)
            dst_tokens = MUSTACHE_RE.findall(pseudo[k])
            if src_tokens != dst_tokens:
                mismatches.append((k, src_tokens, dst_tokens))
        assert not mismatches, (
            f"{self.label}: mustache placeholder drift in "
            f"{len(mismatches)} key(s); first few:\n  "
            + "\n  ".join(f"{k}: {s} -> {d}" for k, s, d in mismatches[:5])
        )

    def test_icu_heads_roundtrip(self):
        en, pseudo = self._pairs()
        mismatches = []
        for k, src in en.items():
            src_heads = ICU_HEAD_RE.findall(src)
            dst_heads = ICU_HEAD_RE.findall(pseudo[k])
            if src_heads != dst_heads:
                mismatches.append((k, src_heads, dst_heads))
        assert not mismatches, (
            f"{self.label}: ICU plural/select head drift in "
            f"{len(mismatches)} key(s); first few: {mismatches[:3]}"
        )

    def test_icu_option_keys_preserved(self):
        """If en.json has ``one {…} other {…}`` the pseudo must too."""
        en, pseudo = self._pairs()
        mismatches = []
        for k, src in en.items():
            src_keys = ICU_OPTION_KEY_RE.findall(src)
            dst_keys = ICU_OPTION_KEY_RE.findall(pseudo[k])
            if src_keys != dst_keys:
                mismatches.append((k, src_keys, dst_keys))
        assert not mismatches, (
            f"{self.label}: ICU option key drift in "
            f"{len(mismatches)} key(s); first few: {mismatches[:3]}"
        )


class TestPseudoInflationWebUI(_PseudoInflationMixin, unittest.TestCase):
    en_path = WEB_EN
    pseudo_path = WEB_PSEUDO
    label = "web"


class TestPseudoInflationVSCode(_PseudoInflationMixin, unittest.TestCase):
    en_path = VSCODE_EN
    pseudo_path = VSCODE_PSEUDO
    label = "vscode"


if __name__ == "__main__":
    unittest.main()
