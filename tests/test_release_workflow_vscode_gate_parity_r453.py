"""R453 · release workflow must validate VSCode before publishing VSIX.

The dedicated VSCode workflow runs lint, tests, and packaging. The release
workflow builds the VSIX that is later published to Marketplace/Open VSX, so it
must not regress to a package-only path that skips extension tests.
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RELEASE_WORKFLOW = ROOT / ".github" / "workflows" / "release.yml"
ROOT_PACKAGE_JSON = ROOT / "package.json"
VSCODE_PACKAGE_JSON = ROOT / "packages" / "vscode" / "package.json"


def _workflow_text() -> str:
    assert RELEASE_WORKFLOW.exists(), "release workflow is missing"
    return RELEASE_WORKFLOW.read_text(encoding="utf-8")


def _build_job_text() -> str:
    text = _workflow_text()
    marker = "\n  publish:\n"
    assert marker in text, "release.yml should keep publish job after build job"
    return text[: text.index(marker)]


def test_release_build_job_runs_vscode_check_before_upload() -> None:
    build = _build_job_text()
    npm_ci = build.index("npm ci")
    check = build.index("npm run vscode:check")
    upload = build.index("path: packages/vscode/*.vsix")

    assert npm_ci < check < upload, (
        "release build job must install Node deps, run the VSCode "
        "test+package gate, then upload the produced VSIX"
    )


def test_release_build_job_uses_single_headless_vscode_check_not_package_only() -> None:
    build = _build_job_text()

    assert "sudo apt-get update && sudo apt-get install -y xvfb" in build
    assert "xvfb-run -a npm run vscode:check" in build
    assert "run: npm run vscode:lint" not in build, (
        "release.yml should not run an explicit lint step before vscode:check; "
        "the workspace npm test lifecycle already runs pretest"
    )
    assert "run: npm run vscode:package" not in build, (
        "release.yml must not build the marketplace VSIX through the "
        "package-only command; vscode:check runs tests and then packages"
    )


def test_vscode_check_covers_compile_lint_test_and_package() -> None:
    root_scripts = json.loads(ROOT_PACKAGE_JSON.read_text(encoding="utf-8"))["scripts"]
    vscode_scripts = json.loads(VSCODE_PACKAGE_JSON.read_text(encoding="utf-8"))[
        "scripts"
    ]

    assert (
        root_scripts["vscode:check"] == "npm run vscode:test && npm run vscode:package"
    )
    assert root_scripts["vscode:test"] == "npm -w ai-intervention-agent test"
    assert vscode_scripts["pretest"] == "npm run compile && npm run lint"
    assert vscode_scripts["test"] == "vscode-test --config .vscode-test.mjs"
    assert vscode_scripts["package"] == "node ../../scripts/package_vscode_vsix.mjs"


def test_publish_jobs_still_consume_build_vsix_artifact() -> None:
    text = _workflow_text()
    assert "name: vsix" in text
    assert "path: packages/vscode/*.vsix" in text
    assert "needs: build" in text
    assert "npx --yes @vscode/vsce publish" in text
    assert "npx --yes ovsx@0.10.9 publish" in text
