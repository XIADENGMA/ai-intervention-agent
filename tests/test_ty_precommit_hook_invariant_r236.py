"""R236 / Cycle 15 · F-cycle14-1: ``ty`` must stay in .pre-commit-config.yaml.

Why this invariant
------------------

v1.7.5 release (Cycle 13) was abandoned because ``ty`` (the astral-sh
type checker, mypy-spirit) caught an `unresolved-attribute` error in
the release CI step (``Release.yml`` line 53,
``ci_gate.py --ci``), too late to fix before the tag was pushed. The
specific error was unfixable type-narrowing on ``re.Match | None``
using ``self.assertIsNotNone(match)`` instead of the PEP 484 standard
``assert match is not None``. v1.7.6 supersession was needed.

Root cause: ``ty`` was only in CI, not in the local pre-commit loop.
The fix (R236, this cycle) promotes ``ty`` to ``.pre-commit-config.yaml``,
mirroring R226's promotion of the precompress-freshness check.

This invariant prevents R236 from being silently removed (e.g. someone
"cleaning up slow hooks" without realizing the cost). The hook is
~1s per commit but saves an entire abandoned release cycle.

What this test guards
---------------------

* The hook id ``ty-check`` exists in ``.pre-commit-config.yaml``.
* The hook entry actually runs ``ty check`` (not a no-op rename).
* The hook filter matches ``.py`` files (would be silly to only run
  ``ty`` on ``.md`` files).
* The hook runs at the default ``[pre-commit]`` stage (not skipped to
  manual/pre-push, which would defeat the local-feedback purpose).
* ``ci_gate.py`` still runs ``ty check`` as the canonical authority
  (CI must stay the source of truth — pre-commit is a fast shadow).
"""

from __future__ import annotations

import unittest
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
PRECOMMIT_PATH = REPO_ROOT / ".pre-commit-config.yaml"
CI_GATE_PATH = REPO_ROOT / "scripts" / "ci_gate.py"


def _load_precommit() -> dict:
    with PRECOMMIT_PATH.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def _find_hook(config: dict, hook_id: str) -> dict | None:
    for repo in config.get("repos", []):
        for hook in repo.get("hooks", []):
            if hook.get("id") == hook_id:
                return hook
    return None


class TestTyCheckHookExists(unittest.TestCase):
    def test_ty_check_hook_present_in_precommit_config(self) -> None:
        config = _load_precommit()
        hook = _find_hook(config, "ty-check")
        self.assertIsNotNone(
            hook,
            msg=(
                "R236 invariant: .pre-commit-config.yaml 必须包含 id='ty-check' "
                "hook。R236 把 ty 从 CI-only 提到 pre-commit, 防止 v1.7.5-style "
                "release 失败 (本地不跑 ty, 推到 CI 才发现, 已经太晚)。如果你"
                "想移除这个 hook, 必须先在 ai-intervention-agent 工具里问业主"
                "理由 (ty check ~1s 不该是 'slow hook')。"
            ),
        )

    def test_ty_check_hook_entry_actually_runs_ty(self) -> None:
        config = _load_precommit()
        hook = _find_hook(config, "ty-check")
        assert hook is not None
        entry = hook.get("entry", "")
        self.assertIn(
            "ty check",
            entry,
            msg=(
                f"R236 invariant: ty-check hook 的 entry 必须真正运行 ``ty check`` "
                f"(当前: {entry!r})。被静默改成 no-op (e.g. 'echo skip') 会让 "
                "v1.7.5-style 失败再次发生且更隐蔽 (CI 通过 + 本地 hook 通过, "
                "但实际什么都没检查)。"
            ),
        )

    def test_ty_check_hook_filters_python_files(self) -> None:
        config = _load_precommit()
        hook = _find_hook(config, "ty-check")
        assert hook is not None
        files = hook.get("files", "")
        self.assertIn(
            ".py",
            files,
            msg=(
                f"R236 invariant: ty-check hook 的 files filter 必须匹配 .py "
                f"(当前: {files!r}). 如果改成 .md 之类, hook 永远不会被任何 "
                "Python 改动触发, 等于失效。"
            ),
        )


class TestTyCheckHookRunsAtPreCommitStage(unittest.TestCase):
    def test_ty_check_hook_runs_at_default_or_pre_commit_stage(self) -> None:
        config = _load_precommit()
        hook = _find_hook(config, "ty-check")
        assert hook is not None
        stages = hook.get("stages")
        if stages is None:
            return
        forbidden_only_stages = {"manual", "pre-push", "post-commit"}
        if set(stages).issubset(forbidden_only_stages):
            self.fail(
                f"R236 invariant: ty-check hook stages = {stages!r}, 但 ty 必须"
                f"在 [pre-commit] 阶段 (default) 跑才能在 commit 前 fail-closed。"
                "只跑在 manual/pre-push/post-commit 等于把 ty 推回到 push 之后, "
                "失去 R236 缩短反馈链的全部意义。"
            )


class TestCiGateStillRunsTy(unittest.TestCase):
    """pre-commit 是 fast shadow, CI 仍是 source of truth。两个都要在。"""

    def test_ci_gate_still_invokes_ty(self) -> None:
        contents = CI_GATE_PATH.read_text(encoding="utf-8")
        self.assertIn(
            '"ty"',
            contents,
            msg=(
                "R236 invariant: scripts/ci_gate.py 仍必须包含 ty check 调用。"
                "把 ty 从 CI 移除 (即使加了 pre-commit) 会让漏装 hook 的开发者"
                "或 ``--no-verify`` push 路径直接绕过类型检查, 回到 R236 之前"
                "的状态。pre-commit 是开发者速度优化, CI 是契约。两者并行。"
            ),
        )


if __name__ == "__main__":
    unittest.main()
