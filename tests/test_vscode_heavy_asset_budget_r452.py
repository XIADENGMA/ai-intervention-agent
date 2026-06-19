"""R452 · Heavy asset budget / optionalization guard.

Packed VSIX size is already guarded by ``tests/test_vscode_vsix_size_budget.py``.
This test catches a different failure earlier: a known heavy asset silently
doubling while the total package still happens to fit under the packed limit.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _size_kib(path: Path) -> int:
    if path.is_file():
        return (path.stat().st_size + 1023) // 1024
    total = 0
    for child in path.rglob("*"):
        if child.is_file():
            total += child.stat().st_size
    return (total + 1023) // 1024


HEAVY_ASSET_BUDGETS_KIB = {
    "packages/vscode/mathjax": 2500,
    "packages/vscode/vendor/terminal-notifier": 2200,
    "packages/vscode/lottie": 600,
    "packages/vscode/lottie.min.js": 350,
    "src/ai_intervention_agent/static/js/lottie.min.js": 350,
    "src/ai_intervention_agent/static/lottie/sprout.json": 500,
    "src/ai_intervention_agent/static/js/tex-mml-chtml.js": 1300,
}


def test_known_heavy_assets_stay_inside_review_budgets() -> None:
    failures: list[str] = []
    for rel, budget_kib in HEAVY_ASSET_BUDGETS_KIB.items():
        path = REPO_ROOT / rel
        assert path.exists(), f"heavy asset budget target missing: {rel}"
        actual_kib = _size_kib(path)
        if actual_kib > budget_kib:
            failures.append(f"{rel}: {actual_kib} KiB > {budget_kib} KiB")
    assert not failures, (
        "Known heavy asset budget exceeded. Either optionalize/split the asset "
        "or update this test with a measured rationale:\n" + "\n".join(failures)
    )


def test_asset_strategy_docs_record_offline_first_tradeoff() -> None:
    en = (REPO_ROOT / "docs" / "perf-web-asset-pipeline.md").read_text(encoding="utf-8")
    zh = (REPO_ROOT / "docs" / "perf-web-asset-pipeline.zh-CN.md").read_text(
        encoding="utf-8"
    )
    for text in (en, zh):
        assert "R452" in text
        assert "terminal-notifier" in text
        assert "MathJax" in text
        assert "offline" in text.lower() or "离线" in text
        assert "tests/test_vscode_heavy_asset_budget_r452.py" in text
