"""R227 / Cycle 13 · F-cycle12-4: invariant-test-guide catalogue is real.

Background
----------
CR#25 §7 follow-up F-cycle12-4 requested a contributor-facing guide
documenting the recurring invariant-test patterns (12+ invariants
have accumulated across cycles 9–13). R227 ships
`docs/contributor-guide-invariant-tests{,.zh-CN}.md` with a §6
"Repository-wide invariant test catalogue" table.

The catalogue is only useful as long as it actually references real
test files. This invariant locks that contract:

1. Both bilingual guide files exist.
2. The EN guide's §6 table references each test by relative path
   (`tests/test_*.py`); each referenced file actually exists on
   disk. Without this, a future test rename would silently leave
   the guide pointing at a ghost test.
3. The zh-CN guide's catalogue references the same set of test
   files as the EN guide. Bilingual parity for the catalogue
   specifically (the prose can differ idiomatically; the catalogue
   is data).
4. Each referenced test file is parseable Python (cheap sanity
   that the catalogue did not accidentally cite a deleted file
   that left a stale path string).
5. The guide files cross-link each other (EN → zh-CN and vice
   versa) so a reader landing on one always finds the other.
6. Each guide's §6 table is non-empty (catches accidental
   wholesale deletion of the catalogue section).
"""

from __future__ import annotations

import ast
import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
GUIDE_EN = REPO_ROOT / "docs" / "contributor-guide-invariant-tests.md"
GUIDE_ZH = REPO_ROOT / "docs" / "contributor-guide-invariant-tests.zh-CN.md"

# Markdown table-cell regex for matching a backtick-wrapped relative
# test path like ``tests/test_foo_invariant_rNNN.py``.
_TEST_PATH_RE = re.compile(r"`(tests/test_[A-Za-z0-9_]+\.py)`")


def _extract_test_paths(markdown: str) -> set[str]:
    return set(_TEST_PATH_RE.findall(markdown))


class TestGuideFilesExist(unittest.TestCase):
    def test_en_guide_exists(self) -> None:
        self.assertTrue(
            GUIDE_EN.is_file(),
            f"R227 guide file missing: {GUIDE_EN}",
        )

    def test_zh_guide_exists(self) -> None:
        self.assertTrue(
            GUIDE_ZH.is_file(),
            f"R227 zh-CN guide file missing: {GUIDE_ZH}",
        )


class TestCataloguesAreNonEmpty(unittest.TestCase):
    def test_en_catalogue_lists_at_least_eight_tests(self) -> None:
        paths = _extract_test_paths(GUIDE_EN.read_text(encoding="utf-8"))
        self.assertGreaterEqual(
            len(paths),
            8,
            (
                "EN guide §6 catalogue references "
                f"{len(paths)} test files; expected at least 8 "
                "(the catalogue had 12 entries when R227 landed; "
                "dropping to <8 likely means the catalogue section "
                "was accidentally truncated)."
            ),
        )

    def test_zh_catalogue_lists_at_least_eight_tests(self) -> None:
        paths = _extract_test_paths(GUIDE_ZH.read_text(encoding="utf-8"))
        self.assertGreaterEqual(len(paths), 8)


class TestCatalogueEntriesPointAtRealFiles(unittest.TestCase):
    def test_every_en_referenced_test_file_exists(self) -> None:
        paths = _extract_test_paths(GUIDE_EN.read_text(encoding="utf-8"))
        missing = sorted(p for p in paths if not (REPO_ROOT / p).is_file())
        self.assertEqual(
            missing,
            [],
            (
                "EN guide §6 catalogue references test files that "
                f"don't exist on disk: {missing}. Either a test was "
                "renamed/deleted without updating the guide, or the "
                "guide has a typo'd path."
            ),
        )

    def test_every_zh_referenced_test_file_exists(self) -> None:
        paths = _extract_test_paths(GUIDE_ZH.read_text(encoding="utf-8"))
        missing = sorted(p for p in paths if not (REPO_ROOT / p).is_file())
        self.assertEqual(missing, [])

    def test_every_referenced_test_file_is_valid_python(self) -> None:
        # Combine both guides' references — if either guide passes
        # but the file is unparseable, fail loudly.
        en_paths = _extract_test_paths(GUIDE_EN.read_text(encoding="utf-8"))
        zh_paths = _extract_test_paths(GUIDE_ZH.read_text(encoding="utf-8"))
        all_paths = sorted(en_paths | zh_paths)
        for path in all_paths:
            full = REPO_ROOT / path
            if not full.is_file():
                continue  # caught by the file-existence tests above
            with self.subTest(path=path):
                try:
                    ast.parse(full.read_text(encoding="utf-8"))
                except SyntaxError as exc:
                    self.fail(
                        f"{path} referenced by the invariant-test "
                        f"guide catalogue but contains a SyntaxError: {exc}"
                    )


class TestBilingualCatalogueParity(unittest.TestCase):
    def test_en_and_zh_catalogues_reference_the_same_files(self) -> None:
        en_paths = _extract_test_paths(GUIDE_EN.read_text(encoding="utf-8"))
        zh_paths = _extract_test_paths(GUIDE_ZH.read_text(encoding="utf-8"))
        only_in_en = sorted(en_paths - zh_paths)
        only_in_zh = sorted(zh_paths - en_paths)
        self.assertEqual(
            (only_in_en, only_in_zh),
            ([], []),
            (
                "Bilingual catalogue desync. Files only referenced "
                f"in EN: {only_in_en}. Files only referenced in "
                f"zh-CN: {only_in_zh}. Catalogue rows are *data* "
                "(unlike prose); when adding a row, add it to BOTH "
                "guides simultaneously."
            ),
        )


class TestGuidesCrossLink(unittest.TestCase):
    def test_en_guide_links_to_zh_guide(self) -> None:
        self.assertIn(
            "contributor-guide-invariant-tests.zh-CN.md",
            GUIDE_EN.read_text(encoding="utf-8"),
            "EN guide does not link to its zh-CN sibling.",
        )

    def test_zh_guide_links_to_en_guide(self) -> None:
        self.assertIn(
            "contributor-guide-invariant-tests.md",
            GUIDE_ZH.read_text(encoding="utf-8"),
            "zh-CN guide does not link to its EN sibling.",
        )


# R231 / Cycle 14 · F-cycle13-1: catalogue staleness guard.
#
# R227 (the original catalogue) only enforced "entries point to real
# files"; missing entries did NOT fail the test. CR#26 §3 flagged this
# as a mild risk because R229 + R230 landed without auto-refreshing the
# catalogue (R230 commit silently skipped it). R231 adds a *missing-
# entry* check: if the catalogue is more than ``MAX_R_LAG`` R-numbers
# behind the latest invariant test in the repo, fail.
#
# Tuning ``MAX_R_LAG``:
# - Too low (1-2) → noisy, fires within a single cycle
# - Too high (15+) → invariant guide effectively never refreshed
# - 10 is a working middle: roughly two cycles of R-work; forces
#   refresh at code-review time at the latest.
#
# R420 (cycle-48 #A1) / Cycle 47 cr77 §5 风险 A 修复: regex 放宽。
# 原 regex ``_invariant_r(\d+)\.py$`` 只匹配带 ``_invariant_`` 前缀的文件,
# 但 cycle-43+ 累积 ~15 个 invariant test 用 ``test_feat_<topic>_rNNN.py``
# 简化命名 (省略 ``_invariant_``), 这些文件被 R231 静默忽略, 导致 catalogue
# staleness guard 形成局部盲点。
# 新 regex ``_r(\d+)\.py$`` 匹配任何 ``_rNNN.py`` 后缀, 与项目 cycle-43+
# convention 一致。
_TEST_FILE_R_RE = re.compile(r"_r(\d+)\.py$")

MAX_R_LAG = 10


def _r_number_from_path(path: str) -> int | None:
    match = _TEST_FILE_R_RE.search(path)
    return int(match.group(1)) if match else None


def _scan_repo_invariant_r_numbers() -> set[int]:
    """Find all invariant-test R-numbers in tests/ (filename pattern)."""
    tests_dir = REPO_ROOT / "tests"
    if not tests_dir.is_dir():
        return set()
    numbers: set[int] = set()
    for entry in tests_dir.iterdir():
        if not entry.is_file() or not entry.name.endswith(".py"):
            continue
        n = _r_number_from_path(entry.name)
        if n is not None:
            numbers.add(n)
    return numbers


class TestRecentInvariantsCataloged(unittest.TestCase):
    """R231: catalogue must include every invariant-test R-number within the most-recent MAX_R_LAG slice."""

    def test_no_recent_invariant_lacks_a_catalogue_entry(self) -> None:
        repo_r_numbers = _scan_repo_invariant_r_numbers()
        if not repo_r_numbers:
            self.skipTest(
                "No invariant test files found in tests/; nothing to catalogue."
            )

        latest_r = max(repo_r_numbers)
        recent_threshold = latest_r - MAX_R_LAG
        recent_r_numbers = {n for n in repo_r_numbers if n > recent_threshold}

        en_paths = _extract_test_paths(GUIDE_EN.read_text(encoding="utf-8"))
        cataloged_r_numbers = {
            _r_number_from_path(p) for p in en_paths if _r_number_from_path(p)
        }

        missing = sorted(recent_r_numbers - cataloged_r_numbers)
        self.assertEqual(
            missing,
            [],
            (
                f"R231 invariant: 最新 {MAX_R_LAG} 个 R-cycle 内的 invariant "
                "test 必须在 docs/contributor-guide-invariant-tests*.md 的 §6 "
                f"catalogue 中有条目。当前最新 R-number = {latest_r}, 阈值 = "
                f"R{recent_threshold} 之后。缺失：{[f'R{n}' for n in missing]}。"
                "修复：在 EN + zh-CN 两份 guide 的 §6 catalogue 表格分别加上对应行，"
                "标注 Pattern + 一句话主题。若某个 R-number 不该在 catalogue 中 "
                "(e.g. R-cycle 已废弃的 invariant 文件)，请删除对应的 "
                "tests/test_*_invariant_rNNN.py 文件而不是把它从 catalogue 漏掉。"
            ),
        )


if __name__ == "__main__":
    unittest.main()
