"""CR#16 F-4 护栏：``check_changelog_diff_scope.py`` 单元测试。

被测的 invariant
================

CHANGELOG.md 在一次 commit 中如果 ``[Unreleased]`` 区段外的 +/- 行数
超过阈值（默认 100），hook 必须 fail-fast，避免格式化 / 历史段落整
理悄悄混入 feature commit。

测试边界
========

* ``_release_sections_in_staged_file``：能正确切分 ``## [Unreleased]``
  与 ``## [vX.Y.Z]`` 区段；
* ``_classify_line_section``：把 new-file 行号映射到对应区段标签；
* ``_count_non_unreleased_lines``：能跳过 ``unreleased`` 区段、累加其它
  区段的 ``+``/``-`` 行；
* ``main()`` CLI：``--threshold`` 默认 100；超过 → exit 1；
  ``--allow-massive-changelog-rewrite`` → exit 0 with WARNING；非负
  ``--threshold`` 校验；CHANGELOG.md 未 staged 时 short-circuit exit 0。

测试用 ``mock.patch`` 桩掉 ``_run_git`` 调用，避免对真实 git 状态依赖。
"""

from __future__ import annotations

import io
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
SCRIPTS = REPO_ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import check_changelog_diff_scope as M

# ---------------------------------------------------------------------------
# 1. _release_sections_in_staged_file: 区段切分
# ---------------------------------------------------------------------------


_SAMPLE_CHANGELOG = """# Changelog

## [Unreleased]

### Added

- feature foo

## [1.6.5]

### Added

- feature bar

## [1.6.4]

### Fixed

- bug xyz
""".strip()


class TestReleaseSections(unittest.TestCase):
    def test_three_sections_recognized(self) -> None:
        with mock.patch.object(M, "_run_git", return_value=_SAMPLE_CHANGELOG):
            ranges = M._release_sections_in_staged_file()
        labels = [label for _, _, label in ranges]
        self.assertEqual(labels, ["unreleased", "1.6.5", "1.6.4"])

    def test_unreleased_range_covers_until_next_section(self) -> None:
        with mock.patch.object(M, "_run_git", return_value=_SAMPLE_CHANGELOG):
            ranges = M._release_sections_in_staged_file()
        # unreleased 段应从其标题行到 1.6.5 标题前
        unreleased = next((r for r in ranges if r[2] == "unreleased"), None)
        self.assertIsNotNone(unreleased)
        assert unreleased is not None
        start, end, _ = unreleased
        text = _SAMPLE_CHANGELOG.splitlines()
        self.assertIn("[Unreleased]", text[start - 1])
        self.assertNotIn("[1.6.5]", text[end - 1])


class TestClassifyLineSection(unittest.TestCase):
    def test_line_inside_unreleased(self) -> None:
        ranges = [(3, 8, "unreleased"), (9, 15, "1.6.5")]
        self.assertEqual(M._classify_line_section(5, ranges), "unreleased")

    def test_line_inside_release(self) -> None:
        ranges = [(3, 8, "unreleased"), (9, 15, "1.6.5")]
        self.assertEqual(M._classify_line_section(12, ranges), "1.6.5")

    def test_line_outside_any_range_returns_none(self) -> None:
        ranges = [(3, 8, "unreleased")]
        self.assertIsNone(M._classify_line_section(100, ranges))


# ---------------------------------------------------------------------------
# 2. _count_non_unreleased_lines: 统计语义
# ---------------------------------------------------------------------------


class TestCountNonUnreleasedLines(unittest.TestCase):
    def test_lines_in_unreleased_not_counted(self) -> None:
        ranges = [(1, 10, "unreleased"), (11, 20, "1.6.5")]
        diff_lines = [
            (5, "+", "added unreleased"),
            (7, "-", "removed unreleased"),
        ]
        self.assertEqual(M._count_non_unreleased_lines(diff_lines, ranges), 0)

    def test_lines_in_release_counted(self) -> None:
        ranges = [(1, 10, "unreleased"), (11, 20, "1.6.5")]
        diff_lines = [
            (12, "+", "lint change in 1.6.5"),
            (15, "-", "removed in 1.6.5"),
        ]
        self.assertEqual(M._count_non_unreleased_lines(diff_lines, ranges), 2)

    def test_mixed_lines_only_non_unreleased_counted(self) -> None:
        ranges = [(1, 10, "unreleased"), (11, 20, "1.6.5"), (21, 30, "1.6.4")]
        diff_lines = [
            (5, "+", "unreleased add"),
            (12, "+", "1.6.5 change 1"),
            (15, "-", "1.6.5 change 2"),
            (25, "+", "1.6.4 change"),
        ]
        # 1.6.5 (2) + 1.6.4 (1) = 3
        self.assertEqual(M._count_non_unreleased_lines(diff_lines, ranges), 3)


# ---------------------------------------------------------------------------
# 3. main() CLI flow
# ---------------------------------------------------------------------------


class TestMainShortCircuitWhenChangelogNotStaged(unittest.TestCase):
    """没改 CHANGELOG.md 时立即 exit 0——pre-commit 几乎零开销。"""

    def test_returns_zero_when_changelog_not_staged(self) -> None:
        with mock.patch.object(M, "_is_changelog_staged", return_value=False):
            self.assertEqual(M.main([]), 0)


class TestMainPassesUnderThreshold(unittest.TestCase):
    """改动行数 ≤ 阈值时通过。"""

    def test_small_diff_passes(self) -> None:
        with (
            mock.patch.object(M, "_is_changelog_staged", return_value=True),
            mock.patch.object(
                M,
                "_staged_changelog_diff_lines",
                return_value=[(12, "+", "x"), (15, "-", "y")],
            ),
            mock.patch.object(
                M,
                "_release_sections_in_staged_file",
                return_value=[(1, 10, "unreleased"), (11, 30, "1.6.5")],
            ),
        ):
            self.assertEqual(M.main(["--threshold", "100"]), 0)


class TestMainFailsAboveThreshold(unittest.TestCase):
    """非-Unreleased 改动超过阈值时 exit 1 + 友好 stderr。"""

    def test_large_diff_fails(self) -> None:
        # 模拟 150 行非-unreleased 改动
        diff = [(20 + i, "+", f"line {i}") for i in range(150)]
        with (
            mock.patch.object(M, "_is_changelog_staged", return_value=True),
            mock.patch.object(M, "_staged_changelog_diff_lines", return_value=diff),
            mock.patch.object(
                M,
                "_release_sections_in_staged_file",
                return_value=[(1, 10, "unreleased"), (11, 500, "1.6.5")],
            ),
        ):
            stderr = io.StringIO()
            with redirect_stderr(stderr), redirect_stdout(io.StringIO()):
                rc = M.main(["--threshold", "100"])
        self.assertEqual(rc, 1)
        out = stderr.getvalue()
        self.assertIn("FAIL", out)
        self.assertIn("150", out, "stderr 必须打印实际超出的行数")

    def test_emergency_override_passes_with_warning(self) -> None:
        """``--allow-massive-changelog-rewrite`` 显式绕过——
        但 stderr 必须留 WARNING 让 reviewer 看见。"""
        diff = [(20 + i, "+", f"line {i}") for i in range(150)]
        with (
            mock.patch.object(M, "_is_changelog_staged", return_value=True),
            mock.patch.object(M, "_staged_changelog_diff_lines", return_value=diff),
            mock.patch.object(
                M,
                "_release_sections_in_staged_file",
                return_value=[(1, 10, "unreleased"), (11, 500, "1.6.5")],
            ),
        ):
            stderr = io.StringIO()
            with redirect_stderr(stderr), redirect_stdout(io.StringIO()):
                rc = M.main(["--threshold", "100", "--allow-massive-changelog-rewrite"])
        self.assertEqual(rc, 0)
        self.assertIn("WARNING", stderr.getvalue())


class TestMainValidatesThreshold(unittest.TestCase):
    def test_negative_threshold_rejected(self) -> None:
        with redirect_stderr(io.StringIO()), redirect_stdout(io.StringIO()):
            rc = M.main(["--threshold", "-1"])
        self.assertEqual(rc, 2)


if __name__ == "__main__":
    unittest.main()
