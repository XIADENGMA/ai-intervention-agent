"""R456 · CI gate must verify generated static assets without rewriting them."""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
CI_GATE = REPO_ROOT / "scripts" / "ci_gate.py"
WORKFLOW_DOCS = (
    REPO_ROOT / "docs" / "workflow.md",
    REPO_ROOT / "docs" / "workflow.zh-CN.md",
)


def test_ci_mode_uses_check_only_static_asset_commands() -> None:
    src = CI_GATE.read_text(encoding="utf-8")

    assert 'minify_cmd = ["uv", "run", "python", "scripts/minify_assets.py"]' in src
    assert (
        'precompress_cmd = ["uv", "run", "python", "scripts/precompress_static.py"]'
        in src
    )
    assert re.search(
        r"if args\.ci:\s+minify_cmd\.append\(\"--check\"\)\s+"
        r"precompress_cmd\.append\(\"--check\"\)",
        src,
    ), "ci_gate.py --ci must validate minify/precompress freshness without writes"


def test_workflow_docs_do_not_claim_ci_mode_writes_static_artifacts() -> None:
    forbidden = (".min`, `.gz`, `.br", ".min`、`.gz`、`.br")
    for path in WORKFLOW_DOCS:
        text = path.read_text(encoding="utf-8")
        for phrase in forbidden:
            assert phrase not in text, (
                f"{path.name} still says CI mode may write static artifacts; "
                "R456 made ci_gate.py --ci check-only for minify/precompress"
            )
