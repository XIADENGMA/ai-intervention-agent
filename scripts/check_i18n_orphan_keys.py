#!/usr/bin/env python3
"""L4·G1 – orphan (dead) i18n key scanner (warn-level CI gate).

Definition: an "orphan" key is one present in a locale JSON file but
not referenced from any of the scanned surfaces:

- ``templates/web_ui.html`` ``data-i18n="..."`` / ``data-i18n-html="..."`` /
  ``data-i18n-*="..."`` attributes
- ``static/js/**/*.js`` ``t('key')`` / ``__…T('key')`` calls (vendor/min
  files skipped)
- ``packages/vscode/{webview-ui.js, webview-settings-ui.js,
  webview-notify-core.js, webview.ts, extension.ts}`` same patterns

Intentionally NOT failing CI
----------------------------
Dead-key failures in ``tests/test_runtime_behavior.py`` are the strict
line in the sand. This script duplicates the scan but reports as a
soft warning: it exits ``0`` so ``ci_gate`` keeps flowing through
downstream gates even if someone lands a locale change that temporarily
unlinks a key. Contributors can run the script locally before/after a
rename to see the diff immediately without having to run the full
pytest suite.

When an orphan set DOES appear in CI, the script still prints a report
so reviewers can triage it on the PR — but it will never block the merge.
If you want hard enforcement, set ``--strict`` (dev-only).

Usage
-----
    python scripts/check_i18n_orphan_keys.py           # warn-level
    python scripts/check_i18n_orphan_keys.py --strict  # exit 1 if any orphan
    python scripts/check_i18n_orphan_keys.py --json    # machine-readable

Exit codes
----------
- ``0`` – scan complete (warn mode) OR no orphans (strict mode)
- ``1`` – ``--strict`` and at least one orphan found (or scan error)
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
WEB_TEMPLATES_DIR = ROOT / "templates"
WEB_JS_DIR = ROOT / "static" / "js"
VSCODE_PKG_DIR = ROOT / "packages" / "vscode"

# Extraction regexes. Must stay in lockstep with
# ``tests/test_runtime_behavior.py`` — if that file expands the set of
# wrapper function names (e.g. a new ``__fooT``), add it here too.
DATA_I18N_RE = re.compile(
    r"""data-i18n(?:-(?:html|title|placeholder|alt|aria-label|value))?\s*=\s*"([^"]+)\"""",
)
# Match ``t('key')``, ``_t('key')``, ``tl('key')``, ``hostT('key')``,
# ``__vuT('key')``, ``__domSecT('key')``, ``__ncT('key')``. The negative
# lookbehind ``(?<![.\w])`` suppresses property-access false positives
# like ``obj.t('x')``. Must stay in sync with
# ``tests/test_runtime_behavior.py::_JS_T_CALL_RE``.
JS_T_CALL_RE = re.compile(
    r"""(?<![.\w])(?:_?tl?|hostT|__vuT|__domSecT|__ncT)\(['"]([a-zA-Z][a-zA-Z0-9_.]+)['"]\s*[,)]""",
)

# Vendor / min'd JS that we don't own and don't want to treat as call sites.
VENDOR_JS = {
    "mathjax-loader.js",
    "tex-mml-chtml.js",
    "lottie.min.js",
}


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _flatten_keys(data: Any, prefix: str = "") -> set[str]:
    out: set[str] = set()
    if isinstance(data, dict):
        for k, v in data.items():
            p = f"{prefix}.{k}" if prefix else k
            if isinstance(v, dict):
                out |= _flatten_keys(v, p)
            else:
                out.add(p)
    return out


def _collect_web_used() -> set[str]:
    """Scan HTML templates + static JS for every referenced i18n key."""
    used: set[str] = set()
    template = WEB_TEMPLATES_DIR / "web_ui.html"
    if template.is_file():
        html = template.read_text(encoding="utf-8", errors="ignore")
        used.update(DATA_I18N_RE.findall(html))
    if WEB_JS_DIR.is_dir():
        for js in sorted(WEB_JS_DIR.glob("*.js")):
            if ".min." in js.name or js.name in VENDOR_JS:
                continue
            src = js.read_text(encoding="utf-8", errors="ignore")
            used.update(JS_T_CALL_RE.findall(src))
    return used


def _collect_vscode_used() -> set[str]:
    """Scan packages/vscode/{ui,core,ts} for every referenced i18n key.

    Only the specific surface files are scanned — avoid walking the
    whole directory, because it would false-positive on e.g. locale
    JSON or build output and make the gate noisy."""
    used: set[str] = set()
    targets = (
        "webview-ui.js",
        "webview-settings-ui.js",
        "webview-notify-core.js",
        "webview.ts",
        "extension.ts",
        "notification-providers.ts",
        "applescript-executor.ts",
    )
    for name in targets:
        path = VSCODE_PKG_DIR / name
        if path.is_file():
            text = path.read_text(encoding="utf-8", errors="ignore")
            used.update(JS_T_CALL_RE.findall(text))
    return used


def scan() -> dict[str, dict]:
    """Return a structured report for both surfaces.

    Shape::

        {
          'web':    { 'orphans': [...], 'total_keys': N, 'used_keys': M },
          'vscode': { 'orphans': [...], 'total_keys': N, 'used_keys': M },
        }
    """
    report: dict[str, dict] = {}

    web_used = _collect_web_used()
    web_en = WEB_LOCALES_DIR / "en.json"
    if web_en.is_file():
        web_total = _flatten_keys(_load_json(web_en))
        report["web"] = {
            "orphans": sorted(web_total - web_used),
            "total_keys": len(web_total),
            "used_keys": len(web_used),
        }

    vscode_used = _collect_vscode_used()
    vscode_en = VSCODE_LOCALES_DIR / "en.json"
    if vscode_en.is_file():
        vscode_total = _flatten_keys(_load_json(vscode_en))
        report["vscode"] = {
            "orphans": sorted(vscode_total - vscode_used),
            "total_keys": len(vscode_total),
            "used_keys": len(vscode_used),
        }

    return report


def _format_human(report: dict[str, dict]) -> str:
    lines: list[str] = []
    for label, data in report.items():
        orphans = data["orphans"]
        header = (
            f"[{label}] {len(orphans)} orphan key(s) "
            f"({data['used_keys']} used / {data['total_keys']} total)"
        )
        lines.append(header)
        for k in orphans[:30]:
            lines.append(f"  • {k}")
        if len(orphans) > 30:
            lines.append(f"  ...({len(orphans) - 30} more)")
    return "\n".join(lines) if lines else "No locales scanned."


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit 1 if any orphan is found (default: warn-only, exit 0).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON instead of a human-readable report.",
    )
    args = parser.parse_args(argv)

    try:
        report = scan()
    except Exception as exc:
        print(f"check_i18n_orphan_keys: scan failed: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(_format_human(report))

    total_orphans = sum(len(d["orphans"]) for d in report.values())
    if total_orphans > 0 and args.strict:
        return 1
    # Warn-level default: always 0 so ci_gate keeps flowing.
    return 0


if __name__ == "__main__":
    sys.exit(main())
