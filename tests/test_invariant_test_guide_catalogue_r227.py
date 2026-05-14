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


if __name__ == "__main__":
    unittest.main()
