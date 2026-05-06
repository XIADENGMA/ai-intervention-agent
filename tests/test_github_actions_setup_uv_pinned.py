"""GitHub Actions 中可控 CI 噪声必须被锁住。

不固定 `version` 时，astral-sh/setup-uv 会先尝试从 uv.toml / pyproject.toml
读取 required-version；本项目没有该字段，于是远端日志会出现
`Could not determine uv version ... Falling back to latest.`。固定版本能同时减少
warning 噪声并提高 CI 可复现性。

harden-runner 会查询当前 workflow run 元数据；使用它的 workflow 至少应给
`actions: read`，避免只读 token 权限过窄时第三方审计 Action 退化出 API 噪声。
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WORKFLOWS = (
    ROOT / ".github" / "workflows" / "test.yml",
    ROOT / ".github" / "workflows" / "release.yml",
    ROOT / ".github" / "workflows" / "bump_version.yml",
)
HARDEN_RUNNER_WORKFLOWS = (
    ROOT / ".github" / "workflows" / "actionlint.yml",
    ROOT / ".github" / "workflows" / "bump_version.yml",
    ROOT / ".github" / "workflows" / "codeql.yml",
    ROOT / ".github" / "workflows" / "dependabot-auto-merge.yml",
    ROOT / ".github" / "workflows" / "dependency-review.yml",
    ROOT / ".github" / "workflows" / "release.yml",
    ROOT / ".github" / "workflows" / "scorecard.yml",
    ROOT / ".github" / "workflows" / "test.yml",
    ROOT / ".github" / "workflows" / "vscode.yml",
)


def test_setup_uv_steps_pin_uv_version() -> None:
    for workflow in WORKFLOWS:
        text = workflow.read_text(encoding="utf-8")
        setup_uv_steps = list(
            re.finditer(
                r"uses:\s+astral-sh/setup-uv@[^\n]+\n(?P<body>(?:\s{8,}.*\n)+)", text
            )
        )

        assert setup_uv_steps, f"{workflow} 应包含 setup-uv step"
        for match in setup_uv_steps:
            body = match.group("body")
            assert re.search(r'^\s+version:\s+"0\.11\.9"\s*$', body, re.MULTILINE), (
                f"{workflow} 的 setup-uv step 必须固定 version，避免远端回退 latest"
            )


def test_harden_runner_workflows_grant_actions_read() -> None:
    for workflow in HARDEN_RUNNER_WORKFLOWS:
        text = workflow.read_text(encoding="utf-8")
        assert "step-security/harden-runner@" in text, (
            f"{workflow} 应包含 harden-runner"
        )
        assert re.search(r"^\s+actions:\s+read\s*$", text, re.MULTILINE), (
            f"{workflow} 使用 harden-runner 时应授予 actions: read，"
            "避免 run metadata 查询退化为有噪声的 API 路径"
        )
