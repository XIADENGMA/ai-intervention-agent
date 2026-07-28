#!/usr/bin/env python3
"""生成 / 校验 pseudo locale JSON，用于 i18n QA。

Pseudo-localization 是业界标准 QA 技术：把源串变成视觉上明显但 ASCII
兼容的变体，不等翻译就能发现：
  * 硬编码串（没走 ``t()`` / ``data-i18n`` 的仍渲成英文）；
  * 拼接 bug（``t('a') + ' ' + t('b')`` 拼出来会断开）；
  * 布局溢出（pseudo 比英文长约 35%，裁剪 / 截断立现）；
  * Unicode 路径问题（重音字符遍历渲染/编码层）。

产物落在 ``<locales>/_pseudo/pseudo.json``（子目录，既有 ``glob('*.json')``
loader 不会误加载）。启用 pseudo（dev URL 参数 / 调试开关）不在本脚本范围。

用法：
    python scripts/gen_pseudo_locale.py           # 两侧各再生
    python scripts/gen_pseudo_locale.py --check   # CI 用：stale 则 exit 1

Exit：``0`` 成功 / 全部最新；``1`` ``--check`` 时有文件缺失或过期。
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent

LOCALE_DIRS: tuple[tuple[Path, str], ...] = (
    (ROOT / "src" / "ai_intervention_agent" / "static" / "locales", "Web UI"),
    (ROOT / "packages" / "vscode" / "locales", "VSCode"),
)


PLACEHOLDER_RE = re.compile(r"\{\{\s*\w+\s*\}\}")


ICU_HEAD_RE = re.compile(r"(\w+)\s*,\s*(plural|select)\s*,\s*", re.DOTALL)
ICU_OPTION_KEY_RE = re.compile(r"\s*(=\d+|[A-Za-z_][\w-]*)\s*\{", re.DOTALL)


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


EXPANSION_EVERY = 2
EXPANSION_CHAR = "·"

PREFIX = "[!! "
SUFFIX = " !!]"


def _transform_segment(text: str) -> str:
    """Transform a plain (no-placeholder) text segment into pseudo."""
    out_chars: list[str] = []
    content_counter = 0
    for ch in text:
        out_chars.append(_CHAR_MAP.get(ch, ch))
        if ch in " \t\n":
            continue
        content_counter += 1
        if content_counter % EXPANSION_EVERY == 0:
            out_chars.append(EXPANSION_CHAR)
    return "".join(out_chars)


def _transform_preserving_mustache(text: str) -> str:
    """pseudo-化一段文本，保留 ``{{name}}`` 占位符不变。"""
    if not text:
        return text
    pieces: list[str] = []
    cursor = 0
    for m in PLACEHOLDER_RE.finditer(text):
        pieces.append(_transform_segment(text[cursor : m.start()]))
        pieces.append(m.group(0))
        cursor = m.end()
    pieces.append(_transform_segment(text[cursor:]))
    return "".join(pieces)


def _pseudoize_inner(text: str) -> str:
    """Recursively pseudo-ize ``text``, preserving mustache + ICU structure."""
    out: list[str] = []
    cursor = 0
    n = len(text)
    while cursor < n:
        open_idx = text.find("{", cursor)
        if open_idx == -1:
            out.append(_transform_preserving_mustache(text[cursor:]))
            break

        if open_idx + 1 < n and text[open_idx + 1] == "{":
            out.append(_transform_preserving_mustache(text[cursor:open_idx]))
            close = text.find("}}", open_idx + 2)
            if close == -1:
                out.append(text[open_idx:])
                cursor = n
                break
            out.append(text[open_idx : close + 2])
            cursor = close + 2
            continue

        head_match = ICU_HEAD_RE.match(text, open_idx + 1)
        if not head_match:
            out.append(_transform_preserving_mustache(text[cursor : open_idx + 1]))
            cursor = open_idx + 1
            continue

        out.append(_transform_preserving_mustache(text[cursor:open_idx]))
        out.append(text[open_idx : head_match.end()])
        scan = head_match.end()

        while scan < n:
            ws_start = scan
            while scan < n and text[scan] in " \t\n":
                scan += 1
            out.append(text[ws_start:scan])
            if scan < n and text[scan] == "}":
                out.append("}")
                scan += 1
                break
            opt_match = ICU_OPTION_KEY_RE.match(text, scan)
            if not opt_match:
                out.append(text[scan:])
                scan = n
                break
            out.append(opt_match.group(0))
            body_start = opt_match.end()
            depth = 1
            body_end = body_start
            while body_end < n and depth > 0:
                ch = text[body_end]
                if ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0:
                        break
                body_end += 1

            out.append(_pseudoize_inner(text[body_start:body_end]))
            if body_end < n and text[body_end] == "}":
                out.append("}")
                scan = body_end + 1
            else:
                scan = body_end
        cursor = scan
    return "".join(out)


def pseudoize(value: str) -> str:
    """Apply pseudo transformation to a single string, preserving ``{{name}}``
    AND ICU plural/select structural tokens."""
    if not value:
        return value
    return PREFIX + _pseudoize_inner(value) + SUFFIX


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
