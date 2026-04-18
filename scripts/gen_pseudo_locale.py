#!/usr/bin/env python3
"""Generate (or check) pseudo-localized locale JSON files for i18n QA.

Pseudo-localization is a standard i18n testing technique
(https://intlpull.com/blog/pseudo-localization-qa-testing-guide-2026):
transform source strings into visually-distinct but ASCII-compatible
variants so that QA + developers can spot, without waiting for
translators:

- **Hardcoded strings** — any plain English string on-screen that wasn't
  wrapped in ``t()``/``data-i18n=`` will still render in English.
- **Concatenation bugs** — split strings like ``t('a') + ' ' + t('b')``
  produce broken pseudo output.
- **Layout overflow** — pseudo is ~35% longer than English; truncated
  tooltips / clipped buttons surface immediately.
- **Unicode path breaks** — accented characters exercise every
  rendering/encoding layer.

This script does NOT ship pseudo locale to end-users. The generated
file lives in ``<locales>/_pseudo/pseudo.json`` (under a subdirectory
so existing ``glob('*.json')`` locale loaders don't pick it up by
mistake). Developers can manually enable it for QA by e.g. loading
the file via a dev-mode URL query or a debug toggle — that wiring is
intentionally out of scope here.

---

**Usage**:
    python scripts/gen_pseudo_locale.py           # regenerate both sides
    python scripts/gen_pseudo_locale.py --check   # CI-friendly: fail if stale

**Exit codes**:
- ``0``: generation succeeded, OR (--check) all pseudo files up-to-date
- ``1``: (--check) at least one pseudo file is missing or stale
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent

LOCALE_DIRS: tuple[tuple[Path, str], ...] = (
    (ROOT / "static" / "locales", "Web UI"),
    (ROOT / "packages" / "vscode" / "locales", "VSCode"),
)

# 占位符 regex：必须和 static/js/i18n.js::t + tests/test_i18n_locale_key_parity
# 的匹配规则完全一致，否则 placeholder parity 会假通过。
PLACEHOLDER_RE = re.compile(r"\{\{\s*\w+\s*\}\}")

# 字符映射：ASCII 字母 → 带重音的 Unicode 变体。选取原则：
# 1. 保持字形相似（读起来仍像原词）
# 2. 覆盖到 BMP 之外？否——仅用 Latin-1 Supplement 和 Latin Extended-A，
#    避免测试环境字体缺失。
# 3. 与 Mozilla L20n 和 Angular i18n 的 pseudo 表保持接近。
_CHAR_MAP = {
    "a": "á",
    "b": "ƀ",
    "c": "ç",
    "d": "đ",
    "e": "é",
    "f": "ƒ",
    "g": "ğ",
    "h": "ĥ",
    "i": "í",
    "j": "ĵ",
    "k": "ķ",
    "l": "ł",
    "m": "ɱ",
    "n": "ñ",
    "o": "ö",
    "p": "þ",
    "q": "ǫ",
    "r": "ř",
    "s": "š",
    "t": "ŧ",
    "u": "ů",
    "v": "ʋ",
    "w": "ŵ",
    "x": "ẋ",
    "y": "ý",
    "z": "ž",
    "A": "Á",
    "B": "Ɓ",
    "C": "Ç",
    "D": "Đ",
    "E": "É",
    "F": "Ƒ",
    "G": "Ğ",
    "H": "Ĥ",
    "I": "Í",
    "J": "Ĵ",
    "K": "Ķ",
    "L": "Ł",
    "M": "Ɱ",
    "N": "Ñ",
    "O": "Ö",
    "P": "Þ",
    "Q": "Ǫ",
    "R": "Ř",
    "S": "Š",
    "T": "Ŧ",
    "U": "Ů",
    "V": "Ʋ",
    "W": "Ŵ",
    "X": "Ẋ",
    "Y": "Ý",
    "Z": "Ž",
}

# 每 N 个（变换后）字符插入一个膨胀字符，目标 35% 膨胀率。
EXPANSION_EVERY = 3
EXPANSION_CHAR = "·"

PREFIX = "[!! "
SUFFIX = " !!]"


def _transform_segment(text: str) -> str:
    """Transform a plain (no-placeholder) text segment into pseudo."""
    out_chars: list[str] = []
    for i, ch in enumerate(text):
        out_chars.append(_CHAR_MAP.get(ch, ch))
        # 膨胀：每 EXPANSION_EVERY 个字符追加一个标记。不在 ASCII 空白边界
        # 插入，避免破坏单词；也不对空字符串做任何事。
        if ch != " " and ch != "\n" and (i + 1) % EXPANSION_EVERY == 0:
            out_chars.append(EXPANSION_CHAR)
    return "".join(out_chars)


def pseudoize(value: str) -> str:
    """Apply pseudo transformation to a single string, preserving ``{{name}}``.

    Algorithm:
    1. Tokenize by placeholder regex: keep placeholder slices untouched.
    2. For every non-placeholder slice, run ``_transform_segment``.
    3. Wrap the whole result in PREFIX/SUFFIX bracket markers so reviewers
       can tell at a glance which strings **were** translated (i.e. hit
       the pseudo generator) vs which were hardcoded (English → English).
    """
    if not value:
        return value
    pieces: list[str] = []
    cursor = 0
    for m in PLACEHOLDER_RE.finditer(value):
        pieces.append(_transform_segment(value[cursor : m.start()]))
        pieces.append(m.group(0))  # 保留占位符
        cursor = m.end()
    pieces.append(_transform_segment(value[cursor:]))
    return PREFIX + "".join(pieces) + SUFFIX


def _walk_and_transform(node: Any) -> Any:
    """Deep-copy a locale tree, applying ``pseudoize`` to every leaf string."""
    if isinstance(node, dict):
        return {k: _walk_and_transform(v) for k, v in node.items()}
    if isinstance(node, str):
        return pseudoize(node)
    return node


def _pseudo_target(locale_dir: Path) -> Path:
    """子目录 ``_pseudo/pseudo.json``：避免污染 ``glob('*.json')`` 扫描。"""
    return locale_dir / "_pseudo" / "pseudo.json"


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _serialize(data: Any) -> str:
    # 稳定排序 + 2 空格缩进 + 末尾换行，和 en.json 的物理风格一致，便于 diff
    return json.dumps(data, ensure_ascii=False, indent=2, sort_keys=False) + "\n"


def generate_one(
    locale_dir: Path,
    *,
    check_only: bool,
) -> tuple[bool, str]:
    """Return ``(ok, message)``. ``ok=False`` iff generation/check failed."""
    en_path = locale_dir / "en.json"
    if not en_path.is_file():
        return True, f"skipped {locale_dir}: no en.json"
    en_data = _load(en_path)
    pseudo_data = _walk_and_transform(en_data)
    serialized = _serialize(pseudo_data)
    target = _pseudo_target(locale_dir)
    if check_only:
        if not target.is_file():
            return False, f"missing {target}"
        existing = target.read_text(encoding="utf-8")
        if existing != serialized:
            return False, f"stale {target} (run without --check to regenerate)"
        return True, f"OK {target}"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(serialized, encoding="utf-8")
    return True, f"wrote {target}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Fail non-zero if any pseudo file is missing or stale (CI mode).",
    )
    args = parser.parse_args(argv)
    failures: list[str] = []
    for locale_dir, label in LOCALE_DIRS:
        ok, msg = generate_one(locale_dir, check_only=args.check)
        print(f"[{label}] {msg}")
        if not ok:
            failures.append(f"[{label}] {msg}")
    if failures:
        if args.check:
            print("\n--check failed: pseudo locale out of date. Run:")
            print("    uv run python scripts/gen_pseudo_locale.py")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
