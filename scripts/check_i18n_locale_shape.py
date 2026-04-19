#!/usr/bin/env python3
"""Locale JSON shape validator (Batch-3 H13).

Why this gate exists
--------------------
Our runtime (``static/js/i18n.js`` + ``packages/vscode/i18n.js``)
treats locale bundles as a **tree of objects with string leaves**.
When a leaf is anything else — a number, a boolean, ``null``, an
array — ``t()`` either returns ``[object Object]``, the literal
``"null"``, or silently empties the slot. Batch-2 H11 added a
runtime warn-once for non-string resolves so the bug shows up in
the console, but by the time it reaches ``t()`` the bad JSON has
already merged.

This script is the lint-time backstop: it refuses to leave exit 0
when any locale file under the scanned roots violates the shape,
printing a structured diagnostic to stderr so reviewers can fix it
in the PR instead of chasing a runtime warning in production.

The contract mirrors i18next's ``i18next-parser`` validator, Airbnb
``polyglot.js`` ``Polyglot.validate``, and FormatJS's ``extract``
shape check — all three refuse to emit a bundle where a leaf isn't
a string. The script also catches interior nodes that are arrays
(``{"page": ["a", "b"]}``) which is a common mistake when migrating
copy from a YAML list.

Usage
-----
::

    python scripts/check_i18n_locale_shape.py
    python scripts/check_i18n_locale_shape.py --locales-dir path/to/locales
    python scripts/check_i18n_locale_shape.py --json

Exit codes
----------
- ``0`` – all scanned bundles conform.
- ``1`` – at least one violation (bad leaf type / bad interior type
  / invalid JSON) OR no locale files were found in the scan roots
  (which itself signals a configuration regression worth catching).
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

# Structured violation record:
#   (bundle path relative to CWD, dotted key path or '<root>',
#    short reason label, offending value's JS/Python type name).
Violation = tuple[Path, str, str, str]


def _type_label(value: Any) -> str:
    """Human-readable label matching how the diagnostic reads aloud.

    We spell out ``None → null`` and ``bool → boolean`` because the
    error messages should match what a reader sees in the JSON source,
    not the Python type name.
    """
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
    """Recursively validate shape of *node*.

    ``node`` may be an object (dict) or a leaf (anything else). The
    caller is responsible for passing the root object in first; this
    function then descends into keys.
    """
    if isinstance(node, dict):
        # empty dict is fine — it's a namespace placeholder.
        for key, value in node.items():
            child_path = [*path, str(key)]
            if isinstance(value, dict):
                _walk(value, child_path, file_path, out)
            elif isinstance(value, str):
                continue  # valid leaf
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
    # Root-level non-dict: the entire file is shaped wrong.
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
        # No JSONs under any configured root — this is a configuration
        # regression (or a brand-new repo). Fail so reviewers see it.
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
