#!/usr/bin/env python3
"""Reproducible Python + npm dependency security audit gate.

The command is intentionally small and boring:

* export locked third-party Python requirements with ``uv export``;
* audit the pinned requirements with ``uvx pip-audit`` without resolver work;
* run ``npm audit --audit-level=moderate --json`` against the root lockfile;
* allow only the documented brace-expansion dev-toolchain exception.

Anything else is a hard failure. The exception is tied to
``docs/security/npm-audit-2026-07-26.md`` and a package dry-run check so it
does not silently become a runtime/package exposure.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, cast

ROOT = Path(__file__).resolve().parents[1]


NPM_TRIAGE_DOC_BRACE_EXPANSION = ROOT / "docs" / "security" / "npm-audit-2026-07-26.md"


BRACE_EXPANSION_REDOS_GHSAS = {
    "GHSA-3jxr-9vmj-r5cp",
    "GHSA-mh99-v99m-4gvg",
    "GHSA-rgw5-rvv9-x895",
}


BRACE_EXPANSION_DEV_CHAIN = {
    "brace-expansion",
    "minimatch",
    "glob",
    "mocha",
    "eslint",
    "@eslint/config-array",
    "@eslint/eslintrc",
}
FORBIDDEN_PACKAGED_TOKENS = (
    "node_modules/",
    "mocha",
    "brace-expansion",
)


def _python_requirements_export_cmd() -> list[str]:
    return [
        "uv",
        "export",
        "--format",
        "requirements-txt",
        "--all-groups",
        "--all-extras",
        "--no-emit-project",
        "--no-hashes",
    ]


def _pip_audit_cmd(requirements: Path) -> list[str]:
    return [
        "uvx",
        "pip-audit",
        "-r",
        str(requirements),
        "--format",
        "json",
        "--no-deps",
        "--disable-pip",
    ]


def _run_capture(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def _load_json_stdout(cmd: list[str], *, allowed_returncodes: set[int]) -> Any:
    completed = _run_capture(cmd)
    if completed.returncode not in allowed_returncodes:
        if completed.stdout:
            print(completed.stdout, file=sys.stderr)
        if completed.stderr:
            print(completed.stderr, file=sys.stderr)
        raise RuntimeError(
            f"{' '.join(cmd)} failed with exit code {completed.returncode}"
        )
    try:
        return json.loads(completed.stdout or "{}")
    except json.JSONDecodeError as exc:
        if completed.stdout:
            print(completed.stdout, file=sys.stderr)
        if completed.stderr:
            print(completed.stderr, file=sys.stderr)
        raise RuntimeError(
            f"{' '.join(cmd)} did not produce valid JSON: {exc}"
        ) from exc


def _via_names(finding: dict[str, Any]) -> set[str]:
    names: set[str] = set()
    for item in finding.get("via", []):
        if isinstance(item, str):
            names.add(item)
        elif isinstance(item, dict) and isinstance(item.get("name"), str):
            names.add(item["name"])
    return names


def _via_ghsa_ids(finding: dict[str, Any]) -> set[str]:
    """提取 finding.via 中 advisory 对象的 GHSA id（url 末段）。"""
    ghsas: set[str] = set()
    for item in finding.get("via", []):
        if isinstance(item, dict):
            url = item.get("url")
            if isinstance(url, str) and "/GHSA-" in url:
                ghsas.add(url.rsplit("/", 1)[-1])
    return ghsas


def _is_accepted_brace_expansion_family(name: str, finding: dict[str, Any]) -> bool:
    """R711：brace-expansion 2026-07 advisory 家族的 dev-only 豁免。"""
    if name not in BRACE_EXPANSION_DEV_CHAIN:
        return False
    if not NPM_TRIAGE_DOC_BRACE_EXPANSION.exists():
        return False

    via_ghsas = _via_ghsa_ids(finding)
    if via_ghsas and not via_ghsas <= BRACE_EXPANSION_REDOS_GHSAS:
        return False

    via_names = _via_names(finding)
    if not via_names and not via_ghsas:
        return False
    return via_names <= BRACE_EXPANSION_DEV_CHAIN


def _is_accepted_npm_finding(name: str, finding: dict[str, Any]) -> bool:
    return _is_accepted_brace_expansion_family(name, finding)


def _packaged_paths() -> list[str]:
    data = _load_json_stdout(
        ["npm", "pack", "--workspace", "ai-intervention-agent", "--dry-run", "--json"],
        allowed_returncodes={0},
    )
    if not isinstance(data, list):
        raise RuntimeError("npm pack --dry-run --json returned non-list JSON")
    paths: list[str] = []
    for package in data:
        if not isinstance(package, dict):
            continue
        for file_entry in package.get("files", []):
            if isinstance(file_entry, dict) and isinstance(file_entry.get("path"), str):
                paths.append(file_entry["path"])
    return paths


def _assert_accepted_npm_not_packaged() -> None:
    paths = _packaged_paths()
    leaked = [
        path for path in paths for token in FORBIDDEN_PACKAGED_TOKENS if token in path
    ]
    if leaked:
        sample = "\n  ".join(sorted(set(leaked))[:20])
        raise RuntimeError(
            "accepted npm audit exception is no longer dev-only; package dry-run "
            f"contains forbidden paths:\n  {sample}"
        )


def _run_python_audit() -> tuple[bool, str]:
    with tempfile.TemporaryDirectory(prefix="aiia-pip-audit-") as tmp:
        requirements = Path(tmp) / "requirements.txt"
        export = _run_capture(_python_requirements_export_cmd())
        if export.returncode != 0:
            return False, export.stderr or export.stdout
        requirements.write_text(export.stdout, encoding="utf-8")

        audit = _run_capture(_pip_audit_cmd(requirements))
        if audit.returncode == 0:
            return True, "pip-audit: no known vulnerabilities"
        return False, audit.stdout or audit.stderr


def _run_npm_audit() -> tuple[bool, list[str], list[str]]:
    data = _load_json_stdout(
        ["npm", "audit", "--audit-level=moderate", "--json"],
        allowed_returncodes={0, 1},
    )
    if not isinstance(data, dict):
        raise RuntimeError("npm audit JSON root must be an object")
    vulnerabilities_obj = data.get("vulnerabilities", {})
    if not isinstance(vulnerabilities_obj, dict):
        raise RuntimeError("npm audit JSON missing vulnerabilities object")
    vulnerabilities = cast("dict[str, Any]", vulnerabilities_obj)

    accepted: list[str] = []
    unaccepted: list[str] = []
    for raw_name, raw_finding in sorted(vulnerabilities.items()):
        name = str(raw_name)
        if not isinstance(raw_finding, dict):
            unaccepted.append(f"{name}: malformed finding")
            continue
        finding = cast("dict[str, Any]", raw_finding)
        severity = str(finding.get("severity", "unknown"))
        if _is_accepted_npm_finding(name, finding):
            accepted.append(f"{name} ({severity})")
        else:
            unaccepted.append(f"{name} ({severity})")

    if accepted:
        _assert_accepted_npm_not_packaged()

    return not unaccepted, accepted, unaccepted


def _main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description="Run reproducible Python and npm dependency security audits."
    )
    parser.add_argument(
        "--gate",
        choices=("local", "pr", "release"),
        default="local",
        help=(
            "Gate label for reporting. All modes fail on Python vulnerabilities "
            "and unaccepted npm findings; accepted npm dev-tool findings remain "
            "visible warnings."
        ),
    )
    args = parser.parse_args(argv)

    ok = True
    print(f"[dependency-audit] gate={args.gate}")

    python_ok, python_message = _run_python_audit()
    if python_ok:
        print(f"[dependency-audit] PASS: {python_message}")
    else:
        ok = False
        print("[dependency-audit] FAIL: pip-audit reported unresolved findings")
        print(python_message)

    npm_ok, accepted, unaccepted = _run_npm_audit()
    if accepted:
        print(
            "[dependency-audit] WARN: accepted npm dev-tool findings "
            f"({', '.join(accepted)})"
        )
        print(
            "[dependency-audit] WARN: exception document: "
            f"{NPM_TRIAGE_DOC_BRACE_EXPANSION}"
        )
    if npm_ok:
        print("[dependency-audit] PASS: npm audit has no unaccepted findings")
    else:
        ok = False
        print(
            "[dependency-audit] FAIL: npm audit has unaccepted findings "
            f"({', '.join(unaccepted)})"
        )

    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))
