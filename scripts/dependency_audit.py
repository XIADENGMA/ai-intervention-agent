#!/usr/bin/env python3
"""Reproducible Python + npm dependency security audit gate.

The command is intentionally small and boring:

* export locked third-party Python requirements with ``uv export``;
* audit the pinned requirements with ``uvx pip-audit`` without resolver work;
* run ``npm audit --audit-level=moderate --json`` against the root lockfile;
* allow only the documented VS Code test-runner npm exception.

Anything else is a hard failure. The exception is tied to
``docs/security/npm-audit-2026-06-21.md`` and a package dry-run check so it
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
NPM_TRIAGE_DOC = ROOT / "docs" / "security" / "npm-audit-2026-06-21.md"
# R711：2026-07-20..24 披露的 brace-expansion DoS/ReDoS 家族 triage 文档。
# 上游只为 5.x 发了 5.0.8 修复（GHSA-mh99 宣告 <= 5.0.7 全部受影响且无
# 1.x/2.x backport），eslint/minimatch 3.x 的 CJS 消费端与 5.x 的 named
# export 不兼容（overrides 强钉会让 dev 工具链直接崩），只能豁免等上游。
NPM_TRIAGE_DOC_BRACE_EXPANSION = ROOT / "docs" / "security" / "npm-audit-2026-07-26.md"
# brace-expansion advisory 家族的根因 GHSA（豁免锚点：finding 的 via 链
# 必须直接命中这些 advisory，或经由下方 dev 工具链家族包传递）。
BRACE_EXPANSION_REDOS_GHSAS = {
    "GHSA-3jxr-9vmj-r5cp",  # CVE-2026-13149 连续非展开 {} 组的指数展开
    "GHSA-mh99-v99m-4gvg",  # <= 5.0.7 无界展开长度 OOM
}
# 该家族 advisory 在本仓 lockfile 里的完整传递链（全部是 packages/vscode
# 的 devDependencies 工具链；不进 VSIX / wheel，由
# ``_assert_accepted_npm_not_packaged`` 的 dry-run 验证兜底）。
BRACE_EXPANSION_DEV_CHAIN = {
    "brace-expansion",
    "minimatch",
    "glob",
    "mocha",
    "eslint",
    "@eslint/config-array",
    "@eslint/eslintrc",
}
ACCEPTED_NPM_FINDINGS = {
    "@vscode/test-cli",
    "mocha",
    "diff",
    "serialize-javascript",
} | BRACE_EXPANSION_DEV_CHAIN
FORBIDDEN_PACKAGED_TOKENS = (
    "node_modules/",
    "@vscode/test-cli",
    "mocha",
    "diff",
    "serialize-javascript",
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


def _effects(finding: dict[str, Any]) -> set[str]:
    return {str(item) for item in finding.get("effects", [])}


def _nodes(finding: dict[str, Any]) -> set[str]:
    return {str(item) for item in finding.get("nodes", [])}


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
    """R711：brace-expansion 2026-07 advisory 家族的 dev-only 豁免。

    接受条件（两者满足其一）：
    1. finding 的 via 直接命中 ``BRACE_EXPANSION_REDOS_GHSAS`` 之一
       （链条根部：brace-expansion 自身，或 npm audit 把 advisory 挂到
       family 内更高层包时）；
    2. via 的包名全部落在 ``BRACE_EXPANSION_DEV_CHAIN`` 内（纯传递
       finding：minimatch → eslint → … 的中间层，via 只会是家族内包）。

    锚点设计：不放行任何 via 里出现家族外包名 / 家族外 advisory 的
    finding——未来同名包出现**新的**无关漏洞时，条件 2 因 via 里出现
    新 advisory 对象（dict 非 str，且 GHSA 不在锚点集合）而 fail-close。
    """
    if name not in BRACE_EXPANSION_DEV_CHAIN:
        return False
    if not NPM_TRIAGE_DOC_BRACE_EXPANSION.exists():
        return False

    via_ghsas = _via_ghsa_ids(finding)
    if via_ghsas and not via_ghsas <= BRACE_EXPANSION_REDOS_GHSAS:
        # via 里出现未 triage 的 advisory —— fail-close
        return False

    # 传递部分（via 中的包名 str，advisory dict 的 name 也会出现在
    # _via_names 里）必须全部落在家族内；advisory dict 的 name 即
    # brace-expansion 自身，天然属于家族。
    via_names = _via_names(finding)
    if not via_names and not via_ghsas:
        return False
    return via_names <= BRACE_EXPANSION_DEV_CHAIN


def _is_accepted_npm_finding(name: str, finding: dict[str, Any]) -> bool:
    if not NPM_TRIAGE_DOC.exists() or name not in ACCEPTED_NPM_FINDINGS:
        return False

    via = _via_names(finding)
    effects = _effects(finding)
    nodes = _nodes(finding)

    if name == "@vscode/test-cli":
        return "mocha" in via and "node_modules/@vscode/test-cli" in nodes
    if name == "mocha":
        if (
            "@vscode/test-cli" in effects
            and {
                "diff",
                "serialize-javascript",
            }
            <= via
        ):
            return True
        # R711：mocha 也在 brace-expansion 家族传递链上（mocha →
        # glob/minimatch → brace-expansion），旧专属条件不命中时落到
        # 家族豁免判定。
        return _is_accepted_brace_expansion_family(name, finding)
    if name == "diff":
        return "mocha" in effects and "node_modules/mocha/node_modules/diff" in nodes
    if name == "serialize-javascript":
        return (
            "mocha" in effects
            and "node_modules/mocha/node_modules/serialize-javascript" in nodes
        )
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
        print(f"[dependency-audit] WARN: exception document: {NPM_TRIAGE_DOC}")
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
