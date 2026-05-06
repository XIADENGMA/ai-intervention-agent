"""GitHub Actions 中 setup-uv 必须固定 uv 版本。

不固定 `version` 时，astral-sh/setup-uv 会先尝试从 uv.toml / pyproject.toml
读取 required-version；本项目没有该字段，于是远端日志会出现
`Could not determine uv version ... Falling back to latest.`。固定版本能同时减少
warning 噪声并提高 CI 可复现性。
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
