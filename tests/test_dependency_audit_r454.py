"""R454 · dependency audit command-shape and edge-case tests."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest import mock

import scripts.dependency_audit as dependency_audit


def test_python_export_command_audits_all_nonlocal_locked_requirements() -> None:
    cmd = dependency_audit._python_requirements_export_cmd()

    assert cmd[:3] == ["uv", "export", "--format"]
    assert "--all-groups" in cmd
    assert "--all-extras" in cmd
    assert "--no-emit-project" in cmd
    assert "--no-hashes" in cmd


def test_pip_audit_command_uses_pinned_requirements_without_resolver(
    tmp_path: Path,
) -> None:
    requirements = tmp_path / "requirements.txt"
    cmd = dependency_audit._pip_audit_cmd(requirements)

    assert cmd[:2] == ["uvx", "pip-audit"]
    assert ["-r", str(requirements)] == cmd[2:4]
    assert "--format" in cmd
    assert "json" in cmd
    assert "--no-deps" in cmd
    assert "--disable-pip" in cmd


def test_python_audit_writes_exported_requirements_to_pip_audit_input() -> None:
    calls: list[list[str]] = []

    def fake_run_capture(cmd: list[str]) -> subprocess.CompletedProcess[str]:
        calls.append(cmd)
        if cmd == dependency_audit._python_requirements_export_cmd():
            return subprocess.CompletedProcess(cmd, 0, stdout="attrs==25.3.0\n")
        assert cmd[:2] == ["uvx", "pip-audit"]
        requirements = Path(cmd[3])
        assert requirements.read_text(encoding="utf-8") == "attrs==25.3.0\n"
        return subprocess.CompletedProcess(
            cmd,
            0,
            stdout='{"dependencies": [], "fixes": []}',
        )

    with mock.patch.object(
        dependency_audit, "_run_capture", side_effect=fake_run_capture
    ):
        ok, message = dependency_audit._run_python_audit()

    assert ok is True
    assert message == "pip-audit: no known vulnerabilities"
    assert calls[0] == dependency_audit._python_requirements_export_cmd()
    assert calls[1][0:2] == ["uvx", "pip-audit"]
    assert "--no-deps" in calls[1]
    assert "--disable-pip" in calls[1]


def test_python_audit_fails_when_pip_audit_reports_vulnerability() -> None:
    def fake_run_capture(cmd: list[str]) -> subprocess.CompletedProcess[str]:
        if cmd == dependency_audit._python_requirements_export_cmd():
            return subprocess.CompletedProcess(cmd, 0, stdout="flask==0.5\n")
        return subprocess.CompletedProcess(
            cmd,
            1,
            stdout='{"dependencies": [{"name": "flask", "vulns": [{"id": "x"}]}]}',
        )

    with mock.patch.object(
        dependency_audit, "_run_capture", side_effect=fake_run_capture
    ):
        ok, message = dependency_audit._run_python_audit()

    assert ok is False
    assert '"flask"' in message


def test_accepted_npm_exception_still_requires_package_dry_run() -> None:
    finding = {
        "via": [{"name": "mocha"}],
        "nodes": ["node_modules/@vscode/test-cli"],
    }

    with mock.patch.object(
        dependency_audit,
        "_packaged_paths",
        return_value=["node_modules/@vscode/test-cli/out/index.js"],
    ):
        assert dependency_audit._is_accepted_npm_finding("@vscode/test-cli", finding)
        try:
            dependency_audit._assert_accepted_npm_not_packaged()
        except RuntimeError as exc:
            assert "no longer dev-only" in str(exc)
        else:
            raise AssertionError("packaged accepted npm exception must fail")
