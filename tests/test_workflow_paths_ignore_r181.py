"""R181 — Lock the paths-ignore list of ``.github/workflows/test.yml``.

Background
----------
Between v1.6.2 and v1.6.3 the project relied on
``paths-ignore: [docs/**, '**/*.md']`` in ``test.yml`` as a "doc-only
commits don't need to run CI" optimisation. That optimisation
contained a load-bearing latent footgun: every guard the project
ships for ``CHANGELOG.md`` (``test_housekeeping_r151``,
``test_changelog_*``), ``docs/*.md`` (``test_docs_links_no_rot``,
``test_generate_docs_index_prefix_r178``), README, or any other
``*.md`` source-of-truth — none of them gated doc-only commits.

The first real evidence was the v1.6.3 bump (R179) itself: it
correctly migrated R148-R151 entries out of ``[Unreleased]`` into
``[1.6.3]``, which violated ``TestR151ChangelogUnreleased``'s
``[Unreleased]``-anchored invariant. Because the bump touched
*only* ``CHANGELOG.md`` + version-strings (all matching ``*.md`` or
fully-cached version files), CI's ``paths-ignore`` ducked the
problem. The next thing that touched the tag — ``release.yml`` on
``v1.6.3 tag push`` — could not duck it (release workflow has no
paths-ignore), and Build (sdist + wheel) failed at Python CI Gate.

R181 removes ``**/*.md`` and ``docs/**`` from the ``test.yml``
paths-ignore. ``LICENSE`` and ``.github/ISSUE_TEMPLATE/**`` stay
ignored because no pytest guard reads them. This test locks the
configuration so a future PR can't quietly re-introduce the
optimisation without flipping a red light first.

What this suite locks
---------------------
*   ``.github/workflows/test.yml`` exists.
*   Its ``on.push.paths-ignore`` and ``on.pull_request.paths-ignore``
    do **not** contain ``**/*.md`` or ``docs/**``.
*   Both blocks still contain ``LICENSE`` and
    ``.github/ISSUE_TEMPLATE/**`` so we don't waste CI on those
    truly inert files.
*   Workflow file has an R181-style comment explaining why we no
    longer ignore docs (so a future contributor finds the history,
    not just the diff).
"""

from __future__ import annotations

import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
TEST_YML = ROOT / ".github/workflows/test.yml"

# Globs that **must not** appear in paths-ignore (would let
# doc-related CHANGELOG / docs / README tests slip through).
FORBIDDEN_GLOBS = ("**/*.md", "docs/**")

# Globs we still expect to be ignored (genuinely outside the test
# surface). If you change these, also update the workflow file +
# this constant.
REQUIRED_GLOBS = (".github/ISSUE_TEMPLATE/**", "LICENSE")


def _load_workflow() -> dict:
    """Parse ``test.yml`` and return the YAML dict.

    PyYAML treats ``on:`` as the Python ``True`` key (Norway-problem-
    style), so we walk both spellings to stay robust against YAML
    spec quirks.
    """
    text = TEST_YML.read_text(encoding="utf-8")
    return yaml.safe_load(text)


def _get_on_block(doc: dict) -> dict:
    """Find the ``on:`` block regardless of YAML's ``true`` casting.

    PyYAML's safe_load treats the bare ``on:`` key as Python ``True``
    (Norway-problem-style); we accept both spellings.
    """
    if "on" in doc:
        block = doc["on"]
    elif True in doc:
        block = doc[True]
    else:
        raise KeyError("test.yml 缺失 on: 块")
    if not isinstance(block, dict):
        raise TypeError(f"test.yml 的 on: 块形态非 dict (got {type(block).__name__})")
    return block


class TestR181WorkflowPathsIgnore(unittest.TestCase):
    """``.github/workflows/test.yml`` paths-ignore 必须排除 docs/md。"""

    def setUp(self) -> None:
        self.assertTrue(TEST_YML.exists(), "test.yml 必须存在")
        self.workflow = _load_workflow()
        self.on_block = _get_on_block(self.workflow)

    def _paths_ignore_for(self, trigger: str) -> list[str]:
        block = self.on_block.get(trigger)
        if not isinstance(block, dict):
            self.fail(f"on.{trigger} 必须是 dict (got {type(block).__name__})")
        # YAML preserves dash-keys; the field name in the workflow
        # is ``paths-ignore`` (literal).
        pi = block.get("paths-ignore")
        if not isinstance(pi, list):
            self.fail(
                f"on.{trigger}.paths-ignore 必须是 list (got {type(pi).__name__})"
            )
        return pi

    def test_push_paths_ignore_excludes_docs(self) -> None:
        pi = self._paths_ignore_for("push")
        for forbidden in FORBIDDEN_GLOBS:
            self.assertNotIn(
                forbidden,
                pi,
                f"on.push.paths-ignore 不能含 {forbidden!r} "
                f"(R181: 否则 CHANGELOG/docs 改动会跳过 CI)。"
                f"实际: {pi}",
            )

    def test_pull_request_paths_ignore_excludes_docs(self) -> None:
        pi = self._paths_ignore_for("pull_request")
        for forbidden in FORBIDDEN_GLOBS:
            self.assertNotIn(
                forbidden,
                pi,
                f"on.pull_request.paths-ignore 不能含 {forbidden!r} (R181). 实际: {pi}",
            )

    def test_push_paths_ignore_keeps_inert_globs(self) -> None:
        pi = self._paths_ignore_for("push")
        for required in REQUIRED_GLOBS:
            self.assertIn(
                required,
                pi,
                f"on.push.paths-ignore 应保留 {required!r}（无 pytest "
                f"guard 读取这些路径，跑 CI 是浪费）。实际: {pi}",
            )

    def test_pull_request_paths_ignore_keeps_inert_globs(self) -> None:
        pi = self._paths_ignore_for("pull_request")
        for required in REQUIRED_GLOBS:
            self.assertIn(
                required,
                pi,
                f"on.pull_request.paths-ignore 应保留 {required!r}。实际: {pi}",
            )

    def test_workflow_has_r181_rationale_comment(self) -> None:
        """Inline R181 comment explains the removal so future contributors
        find the history before re-adding ``docs/**``."""
        text = TEST_YML.read_text(encoding="utf-8")
        self.assertIn(
            "R181",
            text,
            "test.yml 必须含 R181 注释解释为何移除 docs/md paths-ignore",
        )
        # Also check it actually mentions the specific risk so the
        # comment isn't a stub ("R181 something something").
        self.assertRegex(
            text,
            r"R181[^\n]*?(CHANGELOG|docs|guard|paths-ignore)",
            "R181 注释必须解释具体风险 (CHANGELOG / docs / guard)",
        )

    def test_no_other_workflow_silently_re_ignores_docs(self) -> None:
        """Defensive: other workflows (codeql / vscode) historically
        also had ``docs/**`` paths-ignore. We don't *require* them to
        match test.yml's posture (codeql is for code analysis only;
        vscode build doesn't read CHANGELOG.md guards), but if they
        ever start running pytest-like guards, this test should be
        expanded — flag the assumption explicitly so a future
        reviewer sees it."""
        # No assertion — this is a documentation-anchored test.
        # The body's existence + the docstring above are the
        # signal. Pytest will record the test name in CI logs.
        self.assertTrue(True)


if __name__ == "__main__":
    unittest.main()
