#!/usr/bin/env python3
"""P9·L9·G1 – param-signature parity between call sites and locale values.

What it catches
---------------
Runtime i18n already falls back gracefully when a placeholder has no
matching parameter (the raw ``{name}`` literal stays in the rendered
string). But that graceful fallback means bugs hide: nobody notices
``t('greet', { usre: 'Alice' })`` is wrong until a user eyeballs the
UI and says "why does it say 'Hello {user}'?"

This scanner parses every simple ``t('key', { a, b })`` call site
across the web UI + VSCode extension and diffs its keyword set against
the ICU placeholder set declared in the **source** locale
(``static/locales/en.json`` and ``packages/vscode/locales/en.json``).

Three failure modes are reported:

- **Missing params** – the locale value uses ``{name}`` but the call
  site doesn't pass ``name``. This is the most severe: the UI will
  literally render the placeholder text.
- **Extra params** – the call site passes ``{name}`` but the locale
  value never uses it. Usually a rename left behind dead code; the
  runtime silently discards it but it's confusing.
- **Unknown key** – ``t(...)`` references a key that doesn't exist in
  the source locale. This is a strict subset of the dead-key check
  in ``tests/test_runtime_behavior.py`` but we replicate it here so
  you see everything in one report.

What it *doesn't* catch
-----------------------
We only look at **simple** call sites where both arguments are
literals that static analysis can parse:

- ``t('literal.key', { a, b })`` – shorthand object
- ``t('literal.key', { a: x, b: y })`` – explicit values
- ``t('literal.key', { a: fn(), b: 'lit' })`` – expressions OK
- ``t('literal.key')`` – no params (still catches missing params)

Dynamic keys and dynamic param objects are skipped:

- ``t(someVar, { a })`` – skipped
- ``t('key', paramsVar)`` – skipped
- ``t('key', { ...rest })`` – skipped (we don't resolve the spread)

A warn-level summary is printed either way. Strict mode (``--strict``)
exits 1 on any mismatch, which is how the CI gate wires it once the
codebase is clean.

Exit codes
----------
- ``0`` – clean (or warn mode) — ci_gate continues.
- ``1`` – ``--strict`` and at least one mismatch.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent

WEB_LOCALES_DIR = ROOT / "static" / "locales"
VSCODE_LOCALES_DIR = ROOT / "packages" / "vscode" / "locales"
WEB_JS_DIR = ROOT / "static" / "js"
VSCODE_PKG_DIR = ROOT / "packages" / "vscode"
TEMPLATES_DIR = ROOT / "templates"

# Vendor/min bundles — not ours, not scannable.
VENDOR_JS = {
    "mathjax-loader.js",
    "tex-mml-chtml.js",
    "lottie.min.js",
}

# Match ``t('key', { ... })`` or ``t('key')``.
# Captures (1: quote, 2: key, 3: optional object body).
# The object body allows simple nesting of braces (e.g. `{ id: {foo} }`
# shouldn't occur in our code, but pattern handles one level to avoid
# chopping off the true close brace).
_T_CALL_RE = re.compile(
    r"""
    (?<![.\w])
    (?:_?tl?|hostT|__vuT|__domSecT|__ncT)
    \(
      \s*
      (['"])([a-zA-Z][a-zA-Z0-9_.]+)\1        # literal key
      \s*
      (?:,\s*(\{(?:[^{}]|\{[^{}]*\})*\}))?    # optional object literal arg
      \s*\)
    """,
    re.VERBOSE,
)

# Extract top-level keys from an inline object literal. Handles:
#   { a, b }              → ['a', 'b']
#   { a: x, b: 1 }        → ['a', 'b']
#   { 'a': 1, "b": 2 }    → ['a', 'b']
#   { a: fn(x, y), b: z } → ['a', 'b']
# We walk character-by-character tracking bracket depth so that nested
# commas inside function calls / nested object values don't fool us.
_SHORTHAND_KEY_RE = re.compile(r"^['\"]?([A-Za-z_][A-Za-z0-9_]*)['\"]?$")


def _extract_param_names(obj_body: str) -> set[str]:
    """Parse the object literal body between ``{`` and ``}`` and
    return the set of top-level key names.

    Returns ``set()`` if we hit a spread (``...x``) or any syntax we
    can't confidently parse — callers then treat it as "unknown,
    skip check" rather than falsely flagging it."""
    inner = obj_body.strip()
    if inner.startswith("{"):
        inner = inner[1:]
    if inner.endswith("}"):
        inner = inner[:-1]
    inner = inner.strip()
    if not inner:
        return set()
    if "..." in inner:
        # Spread syntax — we can't statically resolve what names it
        # brings in, so refuse to check this call (returning sentinel
        # None-like behaviour via empty set + caller flag below).
        return {"__aiia_param_spread__"}

    out: set[str] = set()
    depth = 0
    paren_depth = 0
    buf: list[str] = []
    # We split on top-level commas then take the part before ':' as the key.
    parts: list[str] = []
    for ch in inner:
        if ch in "{[":
            depth += 1
        elif ch in "}]":
            depth -= 1
        elif ch == "(":
            paren_depth += 1
        elif ch == ")":
            paren_depth -= 1
        if ch == "," and depth == 0 and paren_depth == 0:
            parts.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    if buf:
        parts.append("".join(buf))

    for part in parts:
        part = part.strip()
        if not part:
            continue
        # Split on first top-level ':' to get the key. If no ':',
        # treat whole part as the shorthand key.
        colon_idx = -1
        d = 0
        pd = 0
        for i, ch in enumerate(part):
            if ch in "{[":
                d += 1
            elif ch in "}]":
                d -= 1
            elif ch == "(":
                pd += 1
            elif ch == ")":
                pd -= 1
            elif ch == ":" and d == 0 and pd == 0:
                colon_idx = i
                break
        key_expr = part[:colon_idx] if colon_idx >= 0 else part
        m = _SHORTHAND_KEY_RE.match(key_expr.strip())
        if m:
            out.add(m.group(1))
        else:
            # Something we can't parse (e.g. computed key `[x]:...`).
            # Mark as indeterminate so the caller skips the key.
            return {"__aiia_param_dynamic__"}
    return out


# Extract placeholder names from a locale value. The runtime
# (``packages/vscode/i18n.js`` / ``static/js/i18n.js``) runs a
# two-stage pipeline:
#
#   1. ICU: `{arg, plural|select|selectordinal, ...}`
#   2. Mustache: `{{name}}`
#
# So a locale value like ``{count, plural, one {1 {{item}}} other {# {{item}}s}}``
# has two params: ``count`` (ICU plural arg) and ``item`` (Mustache).
# The scanner therefore extracts both.
#
# Deliberately NOT extracted:
#   - ``{#}`` — ICU hash is substituted by the plural count, not a named param.
#   - bare ``{name}`` single-braces — the runtime does NOT interpolate these;
#     only ``{{name}}`` and the ICU head forms are recognized, so any bare
#     ``{x}`` would render literally. Our linter flags those separately in
#     ``test_runtime_behavior.py::_check_quality`` (brace balance).
_MUSTACHE_RE = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}")
# ICU head: first word inside `{name, plural|select|selectordinal|number|date|time`.
_ICU_HEAD_RE = re.compile(
    r"(?<!\{)\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*,\s*"
    r"(?:plural|select|selectordinal|number|date|time|ordinal)\b",
)


def _placeholders_in(text: str) -> set[str]:
    return set(_MUSTACHE_RE.findall(text)) | set(_ICU_HEAD_RE.findall(text))


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _flatten(data: Any, prefix: str = "") -> dict[str, str]:
    """Flatten nested dicts into dotted keys → leaf string."""
    out: dict[str, str] = {}
    if isinstance(data, dict):
        for k, v in data.items():
            p = f"{prefix}.{k}" if prefix else k
            if isinstance(v, dict):
                out.update(_flatten(v, p))
            elif isinstance(v, str):
                out[p] = v
    return out


_BLOCK_COMMENT_RE = re.compile(r"/\*.*?\*/", re.DOTALL)


def _strip_source_comments(text: str) -> str:
    """Zero out ``//`` line comments and ``/* ... */`` block comments
    while preserving line offsets, so regex line-number math stays
    accurate and we don't false-positive on example snippets inside
    docstrings / contributor comments.

    We replace with space so byte offsets are preserved exactly."""

    def _blank_block(m: re.Match[str]) -> str:
        s = m.group(0)
        return "".join("\n" if ch == "\n" else " " for ch in s)

    without_block = _BLOCK_COMMENT_RE.sub(_blank_block, text)
    out_lines: list[str] = []
    for line in without_block.split("\n"):
        # Naive `//` line-comment strip. It's imperfect for `//` that
        # appears inside strings, but none of our source files have
        # that in a `t(...)` call site — and the few that do (e.g.
        # URL literals in config) never hit the t() regex anyway.
        idx = line.find("//")
        out_lines.append(line if idx == -1 else line[:idx] + " " * (len(line) - idx))
    return "\n".join(out_lines)


def _iter_call_sites(path: Path) -> list[tuple[int, str, str | None]]:
    """Yield ``(lineno, key, obj_body_or_None)`` for every t() call.

    Comments are blanked beforehand so docstring examples with
    intentional typos (see ``extension.ts`` banner referring to
    ``statusBar.unkown``) don't trip the scanner."""
    raw = path.read_text(encoding="utf-8", errors="ignore")
    text = _strip_source_comments(raw)
    results: list[tuple[int, str, str | None]] = []
    for m in _T_CALL_RE.finditer(text):
        lineno = text.count("\n", 0, m.start()) + 1
        results.append((lineno, m.group(2), m.group(3)))
    return results


def _collect_surface(
    label: str,
    files: list[Path],
    placeholders: dict[str, set[str]],
    locale_known_keys: set[str],
) -> list[dict[str, Any]]:
    """Return list of mismatch dicts for a surface (web or vscode)."""
    issues: list[dict[str, Any]] = []
    for path in files:
        if not path.is_file():
            continue
        if path.name in VENDOR_JS:
            continue
        rel = path.relative_to(ROOT)
        for lineno, key, obj_body in _iter_call_sites(path):
            if key not in locale_known_keys:
                # Unknown key — report once; no point diffing params
                # against a value we don't have.
                issues.append(
                    {
                        "file": str(rel),
                        "line": lineno,
                        "key": key,
                        "kind": "unknown-key",
                        "missing": [],
                        "extra": [],
                    }
                )
                continue
            expected = placeholders.get(key, set())
            if obj_body is None:
                provided: set[str] = set()
            else:
                provided = _extract_param_names(obj_body)

            if (
                "__aiia_param_spread__" in provided
                or "__aiia_param_dynamic__" in provided
            ):
                # Call site has spread or computed keys — the static
                # scanner can't tell; skip.
                continue

            missing = sorted(expected - provided)
            extra = sorted(provided - expected)
            if not missing and not extra:
                continue
            kind = (
                "missing-params"
                if missing and not extra
                else ("extra-params" if extra and not missing else "both")
            )
            issues.append(
                {
                    "file": str(rel),
                    "line": lineno,
                    "key": key,
                    "kind": kind,
                    "missing": missing,
                    "extra": extra,
                }
            )
    return issues


def _scan_web() -> list[dict[str, Any]]:
    en = WEB_LOCALES_DIR / "en.json"
    if not en.is_file():
        return []
    flat = _flatten(_load_json(en))
    placeholders = {k: _placeholders_in(v) for k, v in flat.items()}
    files: list[Path] = []
    if WEB_JS_DIR.is_dir():
        files.extend(
            p for p in sorted(WEB_JS_DIR.glob("*.js")) if ".min." not in p.name
        )
    return _collect_surface("web", files, placeholders, set(flat.keys()))


def _scan_vscode() -> list[dict[str, Any]]:
    en = VSCODE_LOCALES_DIR / "en.json"
    if not en.is_file():
        return []
    flat = _flatten(_load_json(en))
    placeholders = {k: _placeholders_in(v) for k, v in flat.items()}
    targets = (
        "webview-ui.js",
        "webview-settings-ui.js",
        "webview-notify-core.js",
        "webview.ts",
        "extension.ts",
        "notification-providers.ts",
        "applescript-executor.ts",
        "i18n.js",
    )
    files = [VSCODE_PKG_DIR / name for name in targets]
    return _collect_surface("vscode", files, placeholders, set(flat.keys()))


def scan() -> dict[str, list[dict[str, Any]]]:
    return {
        "web": _scan_web(),
        "vscode": _scan_vscode(),
    }


def _format_human(report: dict[str, list[dict[str, Any]]]) -> str:
    lines: list[str] = []
    for label, issues in report.items():
        lines.append(f"[{label}] {len(issues)} param-signature issue(s)")
        for it in issues[:50]:
            parts = []
            if it["missing"]:
                parts.append("missing=" + ",".join(it["missing"]))
            if it["extra"]:
                parts.append("extra=" + ",".join(it["extra"]))
            if not parts:
                parts.append(it["kind"])
            lines.append(
                f"  • {it['file']}:{it['line']}  key={it['key']}  {' '.join(parts)}"
            )
        if len(issues) > 50:
            lines.append(f"  ...({len(issues) - 50} more)")
    return "\n".join(lines) if lines else "No issues."


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit 1 if any mismatch is found (default: warn-only, exit 0).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON instead of a human report.",
    )
    args = parser.parse_args(argv)

    try:
        report = scan()
    except Exception as exc:
        print(f"check_i18n_param_signatures: scan failed: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(_format_human(report))

    total = sum(len(v) for v in report.values())
    if total > 0 and args.strict:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
