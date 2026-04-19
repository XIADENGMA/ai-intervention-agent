#!/usr/bin/env python3
"""Locale JSON 形状校验（Batch-3 H13）：runtime 合约要求 locale bundle
是「对象树 + 字符串叶子」，非字符串叶子会让 ``t()`` 退化为
``[object Object]`` / ``"null"``。Batch-2 H11 在运行时加了 warn-once，
本脚本是 lint-time 兜底：发现坏叶子/坏 interior/JSON 解析失败即非零退出，
把问题挡在 PR 而不是 prod。

i18next、polyglot.js、FormatJS extract 也是同款形状合约。

用法：
    uv run python scripts/check_i18n_locale_shape.py
    uv run python scripts/check_i18n_locale_shape.py --locales-dir path/to/locales
    uv run python scripts/check_i18n_locale_shape.py --json

退出码：``0`` 全部合规；``1`` 违规或 scan 根目录下无 ``*.json``（视为配置回归）。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_LOCALE_DIRS: tuple[Path, ...] = (
    ROOT / "static" / "locales",
    ROOT / "packages" / "vscode" / "locales",
)

# 违规记录：(bundle 相对路径, 点号 key 路径/``<root>``, 原因, 实际类型)
Violation = tuple[Path, str, str, str]


def _type_label(value: Any) -> str:
    """返回 JSON 源里读出来的类型名（``None→null``、``bool→boolean``）。"""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "number"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return type(value).__name__


def _walk(
    node: Any,
    path: list[str],
    file_path: Path,
    out: list[Violation],
) -> None:
    """递归校验节点形状：dict 往下走，字符串叶子合规，其余记违规。"""
    if isinstance(node, dict):
        for key, value in node.items():
            child_path = [*path, str(key)]
            if isinstance(value, dict):
                _walk(value, child_path, file_path, out)
            elif isinstance(value, str):
                continue
            else:
                out.append(
                    (
                        file_path,
                        ".".join(child_path),
                        "leaf must be a string",
                        _type_label(value),
                    )
                )
        return
    out.append(
        (
            file_path,
            ".".join(path) or "<root>",
            "interior node must be an object",
            _type_label(node),
        )
    )


def _scan_file(path: Path, violations: list[Violation]) -> None:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        violations.append(
            (path, "<file>", f"cannot read: {exc}", "io-error"),
        )
        return
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        violations.append(
            (
                path,
                "<file>",
                f"invalid JSON: {exc.msg} (line {exc.lineno}, col {exc.colno})",
                "json-error",
            ),
        )
        return
    _walk(data, [], path, violations)


def _discover_locale_files(roots: list[Path]) -> list[Path]:
    files: list[Path] = []
    for root in roots:
        if not root.exists():
            continue
        files.extend(sorted(root.rglob("*.json")))
    return files


def _format_diagnostic(v: Violation, *, project_root: Path) -> str:
    path, key_path, reason, type_label = v
    try:
        rel = path.relative_to(project_root)
    except ValueError:
        rel = path
    return f"{rel} \u203a {key_path} :: {reason} (got {type_label})"


def _format_json(violations: list[Violation], *, project_root: Path) -> str:
    payload = []
    for path, key_path, reason, type_label in violations:
        try:
            rel = str(path.relative_to(project_root))
        except ValueError:
            rel = str(path)
        payload.append(
            {
                "file": rel,
                "key_path": key_path,
                "reason": reason,
                "actual_type": type_label,
            }
        )
    return json.dumps(payload, indent=2, ensure_ascii=False)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="check_i18n_locale_shape",
        description=(
            "Validate that every locale JSON under the scan roots is a "
            "tree-of-objects with string leaves. Fails CI on any "
            "non-string leaf, non-object interior, or parse error."
        ),
    )
    parser.add_argument(
        "--locales-dir",
        dest="locales_dir",
        action="append",
        default=None,
        help=(
            "Directory to scan for ``*.json`` locale bundles. "
            "May be passed multiple times; if omitted, scans the "
            "project's ``static/locales`` and "
            "``packages/vscode/locales`` trees."
        ),
    )
    parser.add_argument(
        "--json",
        dest="as_json",
        action="store_true",
        help="Emit a JSON array of violations to stdout instead of "
        "human-readable lines on stderr.",
    )
    args = parser.parse_args(argv)

    roots: list[Path]
    if args.locales_dir:
        roots = [Path(p).resolve() for p in args.locales_dir]
    else:
        roots = [p for p in DEFAULT_LOCALE_DIRS if p.exists()]

    if not roots:
        print(
            "check_i18n_locale_shape: no existing locale roots to scan "
            f"(looked under {', '.join(str(p) for p in DEFAULT_LOCALE_DIRS)})",
            file=sys.stderr,
        )
        return 1

    files = _discover_locale_files(roots)
    if not files:
        # scan 根目录下无 JSON，视为配置回归——直接失败让 reviewer 看见
        print(
            "check_i18n_locale_shape: no *.json files found under "
            f"{', '.join(str(r) for r in roots)}",
            file=sys.stderr,
        )
        return 1

    violations: list[Violation] = []
    for path in files:
        _scan_file(path, violations)

    if not violations:
        return 0

    project_root = Path.cwd().resolve()
    if args.as_json:
        sys.stdout.write(_format_json(violations, project_root=project_root))
        sys.stdout.write("\n")
    for v in violations:
        print(
            _format_diagnostic(v, project_root=project_root),
            file=sys.stderr,
        )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
