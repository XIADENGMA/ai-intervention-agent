"""R454 · dependency audit command-shape and edge-case tests."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest import mock

import pytest

import scripts.dependency_audit as dependency_audit

TRIAGED_GHSA = "GHSA-rgw5-rvv9-x895"
UNRELATED_GHSA = "GHSA-aaaa-bbbb-cccc"


def advisory(name: str, ghsa: str) -> dict[str, str]:
    return {"name": name, "url": f"https://github.com/advisories/{ghsa}"}


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
        "via": [advisory("brace-expansion", TRIAGED_GHSA)],
        "nodes": ["node_modules/brace-expansion"],
    }

    with mock.patch.object(
        dependency_audit,
        "_packaged_paths",
        return_value=["node_modules/brace-expansion/index.js"],
    ):
        assert dependency_audit._is_accepted_npm_finding("brace-expansion", finding)
        try:
            dependency_audit._assert_accepted_npm_not_packaged()
        except RuntimeError as exc:
            assert "no longer dev-only" in str(exc)
        else:
            raise AssertionError("packaged accepted npm exception must fail")


@pytest.mark.parametrize(
    ("name", "finding"),
    [
        (
            "@vscode/test-cli",
            {"via": ["mocha"], "nodes": ["node_modules/@vscode/test-cli"]},
        ),
        (
            "mocha",
            {
                "via": ["diff", "serialize-javascript"],
                "effects": ["@vscode/test-cli"],
                "nodes": ["node_modules/mocha"],
            },
        ),
        (
            "diff",
            {
                "effects": ["mocha"],
                "nodes": ["node_modules/mocha/node_modules/diff"],
            },
        ),
        (
            "serialize-javascript",
            {
                "effects": ["mocha"],
                "nodes": ["node_modules/mocha/node_modules/serialize-javascript"],
            },
        ),
    ],
)
def test_the_spent_test_runner_exceptions_no_longer_apply(
    name: str, finding: dict[str, object]
) -> None:
    assert not dependency_audit._is_accepted_npm_finding(name, finding)


@pytest.mark.parametrize(
    ("name", "finding", "accepted"),
    [
        (
            "brace-expansion",
            {"via": [advisory("brace-expansion", TRIAGED_GHSA)]},
            True,
        ),
        ("minimatch", {"via": ["brace-expansion"]}, True),
        (
            "brace-expansion",
            {"via": [advisory("brace-expansion", UNRELATED_GHSA)]},
            False,
        ),
        (
            "brace-expansion",
            {
                "via": [
                    advisory("brace-expansion", TRIAGED_GHSA),
                    advisory("brace-expansion", UNRELATED_GHSA),
                ]
            },
            False,
        ),
        ("minimatch", {"via": ["left-pad"]}, False),
        ("left-pad", {"via": ["brace-expansion"]}, False),
        ("minimatch", {"via": []}, False),
        (
            "left-pad",
            {"via": [advisory("left-pad", TRIAGED_GHSA)]},
            False,
        ),
    ],
)
def test_the_brace_expansion_exception_fails_closed(
    name: str, finding: dict[str, object], accepted: bool
) -> None:
    assert dependency_audit._is_accepted_npm_finding(name, finding) is accepted


def test_the_brace_expansion_exception_needs_its_triage_document(
    tmp_path: Path,
) -> None:
    finding = {"via": [advisory("brace-expansion", TRIAGED_GHSA)]}

    with mock.patch.object(
        dependency_audit,
        "NPM_TRIAGE_DOC_BRACE_EXPANSION",
        tmp_path / "missing.md",
    ):
        assert not dependency_audit._is_accepted_npm_finding("brace-expansion", finding)


def test_a_clean_npm_audit_passes_without_an_exception_or_a_dry_run() -> None:
    with (
        mock.patch.object(
            dependency_audit,
            "_load_json_stdout",
            return_value={"vulnerabilities": {}},
        ),
        mock.patch.object(
            dependency_audit,
            "_packaged_paths",
            side_effect=AssertionError("nothing is accepted, so no dry run"),
        ),
    ):
        assert dependency_audit._run_npm_audit() == (True, [], [])


ACCEPTED_AUDIT = {
    "vulnerabilities": {
        "brace-expansion": {
            "severity": "high",
            "via": [advisory("brace-expansion", TRIAGED_GHSA)],
            "nodes": ["node_modules/brace-expansion"],
        }
    }
}


def test_a_dev_dependency_in_the_package_is_caught_wherever_it_lives() -> None:
    with mock.patch.object(
        dependency_audit,
        "_packaged_paths",
        return_value=["node_modules/left-pad/index.js"],
    ):
        with pytest.raises(RuntimeError, match="no longer dev-only"):
            dependency_audit._assert_accepted_npm_not_packaged()


def test_a_package_without_dev_dependencies_passes_the_dry_run() -> None:
    with mock.patch.object(
        dependency_audit,
        "_packaged_paths",
        return_value=["package.json", "out/extension.js"],
    ):
        dependency_audit._assert_accepted_npm_not_packaged()


def test_an_accepted_npm_finding_is_reported_when_the_package_is_clean() -> None:
    with (
        mock.patch.object(
            dependency_audit, "_load_json_stdout", return_value=ACCEPTED_AUDIT
        ),
        mock.patch.object(
            dependency_audit, "_packaged_paths", return_value=["package.json"]
        ),
    ):
        assert dependency_audit._run_npm_audit() == (
            True,
            ["brace-expansion (high)"],
            [],
        )


def test_an_accepted_npm_finding_fails_when_the_package_ships_it() -> None:
    with (
        mock.patch.object(
            dependency_audit, "_load_json_stdout", return_value=ACCEPTED_AUDIT
        ),
        mock.patch.object(
            dependency_audit,
            "_packaged_paths",
            return_value=["node_modules/brace-expansion/index.js"],
        ),
    ):
        with pytest.raises(RuntimeError, match="no longer dev-only"):
            dependency_audit._run_npm_audit()
