"""R874: ``CITATION.cff`` says the version was released on the day the CHANGELOG says it was.

``CITATION.cff`` carries two release facts, ``version`` and ``date-released``.  Only the first was
ever kept in step.  ``scripts/bump_version.py`` rewrote ``version``, the version-sync invariant
(R416) holds the five version sources equal, and ``date-released`` was left to "the publisher, by
hand" (a comment in a unit test, and one line of the ``--dry-run`` output that nobody reads; the
release checklist and ``docs/workflow.md`` never mention it).  It was set once, at v1.8.0, and not
touched by the twelve releases since: the file said "version 1.8.12, released 2026-07-19" for a
version that was tagged on 2026-09-07, and GitHub's "Cite this repository" box is built from it.

The fix has three parts, all pinned here:

* the script takes the date from the one place that already holds it, the
  ``## [X.Y.Z] - YYYY-MM-DD`` heading of the version it is bumping to, and writes it to
  ``date-released``; with no such heading it leaves the date alone and says so on stderr, because
  it cannot know the day;
* the data is right, and stays right: for the version ``CITATION.cff`` names, the date it gives is
  the date that version's CHANGELOG heading gives;
* the parsing is tested on small inputs of its own, on a copy of the real release files taken
  through a whole bump, and against every heading the real CHANGELOG has, so a change of heading
  style cannot blind both the script and the guard.
"""

from __future__ import annotations

import datetime
import importlib.util
import re
import shutil
from pathlib import Path
from types import ModuleType

import pytest

REPO = Path(__file__).resolve().parents[1]
CITATION = REPO / "CITATION.cff"
CHANGELOG = REPO / "CHANGELOG.md"


def _load_bump_version() -> ModuleType:
    path = REPO / "scripts" / "bump_version.py"
    spec = importlib.util.spec_from_file_location("bump_version_r874", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


bump = _load_bump_version()

#: The files ``bump_version.py`` reads and writes, plus the changelog it reads.
RELEASE_FILES = (
    "pyproject.toml",
    "uv.lock",
    "package.json",
    "package-lock.json",
    "packages/vscode/package.json",
    ".github/ISSUE_TEMPLATE/bug_report.yml",
    "CITATION.cff",
    "CHANGELOG.md",
)

SAMPLE_CFF = """\
cff-version: 1.2.0
title: "Demo"
version: "1.8.12"
date-released: "2026-09-07"
"""


# ---------------------------------------------------------------------------------------------
# The data, and the guard that keeps it right
# ---------------------------------------------------------------------------------------------


def _dated_headings(text: str) -> list[tuple[str, str]]:
    """``(version, date)`` of every ``## [X] <dash> YYYY-MM-DD`` line, found without the script."""
    return re.findall(
        r"^## \[([^\]]+)\] [-\u2013\u2014] (\d{4}-\d{2}-\d{2})", text, re.MULTILINE
    )


def citation_problem(cff: str, changelog: str) -> str | None:
    """Why ``cff`` and ``changelog`` disagree on when the cited version was released, or ``None``."""
    version = bump._extract_citation_version(cff)
    if version is None:
        return "CITATION.cff has no readable top-level version"
    cited = bump._extract_citation_date(cff)
    if cited is None:
        return (
            "CITATION.cff has no readable date-released (a bare or quoted YYYY-MM-DD, "
            "alone on a line that starts with the key)"
        )
    try:
        datetime.date.fromisoformat(cited)
    except ValueError:
        return f"CITATION.cff date-released {cited} is not a day that exists"
    released = bump._changelog_release_date(changelog, version)
    if released is None:
        return (
            f"CHANGELOG.md has no '## [{version}] - YYYY-MM-DD' heading for the version "
            "CITATION.cff names; promote [Unreleased] to it (release checklist A.1) before bumping"
        )
    if cited != released:
        return (
            f"CITATION.cff says {version} was released on {cited}; CHANGELOG.md says {released}. "
            f"Run scripts/bump_version.py {version} again, or edit date-released."
        )
    return None


class TestTheDataIsRight:
    def test_the_citation_gives_the_date_the_changelog_gives_for_the_version_it_names(
        self,
    ) -> None:
        problem = citation_problem(
            CITATION.read_text(encoding="utf-8"), CHANGELOG.read_text(encoding="utf-8")
        )
        assert problem is None, problem

    def test_the_guard_reads_every_dated_heading_the_changelog_has(self) -> None:
        text = CHANGELOG.read_text(encoding="utf-8")
        headings = _dated_headings(text)
        assert len(headings) > 20, (
            "the independent heading scan found too few headings to mean much"
        )
        seen: set[str] = set()
        for version, date in headings:
            if version in seen:
                continue
            seen.add(version)
            assert bump._changelog_release_date(text, version) == date, version

    def test_the_real_changelog_uses_both_separators_the_script_accepts(self) -> None:
        text = CHANGELOG.read_text(encoding="utf-8")
        assert re.search(r"^## \[[^\]]+\] - \d{4}", text, re.MULTILINE)
        assert re.search(r"^## \[[^\]]+\] \u2014 \d{4}", text, re.MULTILINE)


class TestTheGuardOnSmallInputs:
    CHANGELOG_OK = "## [Unreleased]\n\n- x\n\n## [1.8.12] - 2026-09-07\n\n- y\n"

    def test_agreeing_files_have_no_problem(self) -> None:
        assert citation_problem(SAMPLE_CFF, self.CHANGELOG_OK) is None

    def test_the_stale_date_the_repository_carried_for_twelve_releases(self) -> None:
        stale = SAMPLE_CFF.replace("2026-09-07", "2026-07-19")
        problem = citation_problem(stale, self.CHANGELOG_OK)
        assert problem is not None
        assert "1.8.12" in problem
        assert "2026-07-19" in problem
        assert "2026-09-07" in problem

    def test_a_date_one_day_off_is_a_problem(self) -> None:
        assert citation_problem(SAMPLE_CFF.replace("09-07", "09-08"), self.CHANGELOG_OK)

    def test_only_the_date_of_the_cited_version_counts(self) -> None:
        changelog = "## [1.8.13] - 2026-10-24\n\n## [1.8.12] - 2026-09-07\n"
        assert citation_problem(SAMPLE_CFF, changelog) is None
        newer = SAMPLE_CFF.replace("1.8.12", "1.8.13")
        assert citation_problem(newer, changelog) is not None
        assert (
            citation_problem(newer.replace("2026-09-07", "2026-10-24"), changelog)
            is None
        )

    def test_a_version_without_a_heading_is_a_problem(self) -> None:
        problem = citation_problem(SAMPLE_CFF, "## [Unreleased]\n\n- x\n")
        assert problem is not None
        assert "promote" in problem

    def test_a_heading_without_a_date_is_a_problem(self) -> None:
        assert citation_problem(SAMPLE_CFF, "## [1.8.12]\n\n- y\n")

    def test_a_citation_without_a_date_or_a_version_is_a_problem(self) -> None:
        assert citation_problem('version: "1.8.12"\n', self.CHANGELOG_OK)
        assert citation_problem('date-released: "2026-09-07"\n', self.CHANGELOG_OK)
        assert citation_problem("", self.CHANGELOG_OK)

    def test_a_citation_date_that_is_not_a_day_is_a_problem(self) -> None:
        impossible = SAMPLE_CFF.replace("2026-09-07", "2026-02-30")
        changelog = self.CHANGELOG_OK.replace("2026-09-07", "2026-02-30")
        problem = citation_problem(impossible, changelog)
        assert problem is not None
        assert "not a day" in problem


# ---------------------------------------------------------------------------------------------
# _changelog_release_date
# ---------------------------------------------------------------------------------------------


class TestChangelogReleaseDate:
    @pytest.mark.parametrize(
        "separator", ["-", "\u2013", "\u2014"], ids=["hyphen", "en-dash", "em-dash"]
    )
    def test_each_dash_a_heading_may_use(self, separator: str) -> None:
        text = f"# Changelog\n\n## [1.8.13] {separator} 2026-10-24\n\n- x\n"
        assert bump._changelog_release_date(text, "1.8.13") == "2026-10-24"

    def test_a_note_after_the_date_is_allowed(self) -> None:
        text = "## [1.8.13] - 2026-10-24 [YANKED]\n"
        assert bump._changelog_release_date(text, "1.8.13") == "2026-10-24"

    def test_trailing_spaces_and_a_windows_line_ending(self) -> None:
        assert bump._changelog_release_date("## [1.8.13] - 2026-10-24  \n", "1.8.13")
        crlf = "## [1.8.13] - 2026-10-24\r\n\r\n- x\r\n"
        assert bump._changelog_release_date(crlf, "1.8.13") == "2026-10-24"

    @pytest.mark.parametrize(
        "text",
        [
            "",
            "# Changelog\n",
            "## [Unreleased]\n\n- x\n",
            "## [1.8.13]\n\n- x\n",
            "## [1.8.12] - 2026-09-07\n",
        ],
        ids=["empty", "no-heading", "unreleased", "no-date", "other-version"],
    )
    def test_no_dated_heading_for_the_version_is_none(self, text: str) -> None:
        assert bump._changelog_release_date(text, "1.8.13") is None

    @pytest.mark.parametrize(
        "date", ["2026-02-30", "2026-13-01", "2026-00-10", "0000-01-01", "2026-04-31"]
    )
    def test_a_date_that_does_not_exist_is_none(self, date: str) -> None:
        assert bump._changelog_release_date(f"## [1.8.13] - {date}\n", "1.8.13") is None

    @pytest.mark.parametrize(
        "line",
        [
            "## [1.8.13] - 2026-10-24x",
            "## [1.8.13] - 2026-10-245",
            "## [1.8.13] - 02026-10-24",
            "## [1.8.13] - 2026-1-24",
            "## [1.8.13] 2026-10-24",
            "## [1.8.13] -2026-10-24",
            "## [1.8.13]- 2026-10-24",
            "## [1.8.13] -- 2026-10-24",
            "## [1.8.13] : 2026-10-24",
        ],
    )
    def test_a_heading_that_is_not_in_the_documented_shape_is_none(
        self, line: str
    ) -> None:
        assert bump._changelog_release_date(line + "\n", "1.8.13") is None

    @pytest.mark.parametrize(
        "line",
        [
            "### [1.8.13] - 2026-10-24",
            "# [1.8.13] - 2026-10-24",
            " ## [1.8.13] - 2026-10-24",
            "    ## [1.8.13] - 2026-10-24",
            "- ## [1.8.13] - 2026-10-24",
            "text ## [1.8.13] - 2026-10-24",
            "## 1.8.13 - 2026-10-24",
            "## [v1.8.13] - 2026-10-24",
        ],
    )
    def test_only_a_level_two_heading_at_the_start_of_a_line_counts(
        self, line: str
    ) -> None:
        assert bump._changelog_release_date(line + "\n", "1.8.13") is None

    def test_a_version_is_matched_whole(self) -> None:
        text = "## [1.8.12] - 2026-09-07\n## [11.8.12] - 2027-01-01\n## [1.8.1] - 2026-01-01\n"
        assert bump._changelog_release_date(text, "1.8.1") == "2026-01-01"
        assert bump._changelog_release_date(text, "1.8.12") == "2026-09-07"
        assert bump._changelog_release_date(text, "11.8.12") == "2027-01-01"
        assert bump._changelog_release_date(text, "1.8") is None
        assert bump._changelog_release_date(text, "1.8.123") is None

    def test_a_version_with_a_prerelease_or_build_part_is_matched_literally(
        self,
    ) -> None:
        text = "## [1.8.13-rc.1] - 2026-10-20\n## [1.8.13+build.5] - 2026-10-21\n"
        assert bump._changelog_release_date(text, "1.8.13-rc.1") == "2026-10-20"
        assert bump._changelog_release_date(text, "1.8.13+build.5") == "2026-10-21"
        assert bump._changelog_release_date(text, "1.8.13") is None
        assert (
            bump._changelog_release_date("## [1x8x13] - 2026-10-20\n", "1.8.13") is None
        )

    def test_the_first_valid_heading_wins(self) -> None:
        text = "## [1.8.13] - 2026-10-24\n\n## [1.8.13] - 2026-10-25\n"
        assert bump._changelog_release_date(text, "1.8.13") == "2026-10-24"

    def test_an_invalid_date_does_not_hide_a_later_valid_one(self) -> None:
        text = "## [1.8.13] - 2026-02-30\n\n## [1.8.13] - 2026-10-25\n"
        assert bump._changelog_release_date(text, "1.8.13") == "2026-10-25"

    def test_the_heading_is_found_in_the_middle_of_a_long_file(self) -> None:
        body = "\n".join(f"- entry {i}" for i in range(2000))
        text = f"## [Unreleased]\n\n{body}\n\n## [1.8.13] - 2026-10-24\n\n{body}\n"
        assert bump._changelog_release_date(text, "1.8.13") == "2026-10-24"


# ---------------------------------------------------------------------------------------------
# _extract_citation_date / _update_citation_date / _update_citation
# ---------------------------------------------------------------------------------------------


class TestCitationDate:
    @pytest.mark.parametrize(
        ("line", "expected"),
        [
            ('date-released: "2026-09-07"', "2026-09-07"),
            ("date-released: '2026-09-07'", "2026-09-07"),
            ("date-released: 2026-09-07", "2026-09-07"),
            ('date-released:   "2026-09-07"   ', "2026-09-07"),
            ('date-released:"2026-09-07"', "2026-09-07"),
        ],
        ids=["double", "single", "bare", "spaces", "tight"],
    )
    def test_extract_reads_each_quoting_style(self, line: str, expected: str) -> None:
        assert bump._extract_citation_date(f'version: "1"\n{line}\n') == expected

    @pytest.mark.parametrize(
        "text",
        [
            "",
            'version: "1.8.12"\n',
            '  date-released: "2026-09-07"\n',
            'preferred-citation:\n  date-released: "2026-09-07"\n',
            '# date-released: "2026-09-07"\n',
            'date-released: "2026-09-07\n',
            "date-released: 'x'\n",
            "date-released: \"2026-09-07'\n",
            'date-released: "2026-9-7"\n',
            'date-released: ""\n',
            'xdate-released: "2026-09-07"\n',
            'date-released: "2026-09-07" # released\n',
        ],
        ids=[
            "empty",
            "no-field",
            "indented",
            "nested",
            "comment",
            "unclosed",
            "not-a-date",
            "mixed-quotes",
            "short-date",
            "empty-value",
            "other-key",
            "trailing-comment",
        ],
    )
    def test_extract_is_none_unless_it_is_the_top_level_field(self, text: str) -> None:
        assert bump._extract_citation_date(text) is None

    @pytest.mark.parametrize(
        ("old_line", "new_line"),
        [
            ('date-released: "2026-09-07"', 'date-released: "2026-10-24"'),
            ("date-released: '2026-09-07'", "date-released: '2026-10-24'"),
            ("date-released: 2026-09-07", "date-released: 2026-10-24"),
            ('date-released:   "2026-09-07"', 'date-released:   "2026-10-24"'),
        ],
        ids=["double", "single", "bare", "spaces"],
    )
    def test_update_keeps_the_quoting_and_changes_one_line(
        self, old_line: str, new_line: str
    ) -> None:
        text = SAMPLE_CFF.replace('date-released: "2026-09-07"', old_line)
        updated = bump._update_citation_date(text, "2026-10-24")
        before, after = text.splitlines(), updated.splitlines()
        assert len(before) == len(after)
        changed = [(a, b) for a, b in zip(before, after, strict=True) if a != b]
        assert changed == [(old_line, new_line)]
        assert updated.endswith("\n") == text.endswith("\n")

    def test_update_is_idempotent_and_leaves_other_fields_alone(self) -> None:
        once = bump._update_citation_date(SAMPLE_CFF, "2026-10-24")
        assert bump._update_citation_date(once, "2026-10-24") == once
        assert bump._update_citation_date(SAMPLE_CFF, "2026-09-07") == SAMPLE_CFF
        assert 'version: "1.8.12"' in once
        assert "cff-version: 1.2.0" in once

    def test_update_changes_only_the_first_of_two_fields(self) -> None:
        text = SAMPLE_CFF + 'date-released: "2020-01-01"\n'
        updated = bump._update_citation_date(text, "2026-10-24")
        assert updated.count('date-released: "2026-10-24"') == 1
        assert updated.count('date-released: "2020-01-01"') == 1

    def test_update_without_the_field_raises(self) -> None:
        with pytest.raises(ValueError, match="date-released"):
            bump._update_citation_date('version: "1"\n', "2026-10-24")

    @pytest.mark.parametrize(
        "bad",
        [
            "",
            "2026-9-7",
            "20260907",
            "2026-W43-6",
            "2026-02-30",
            "2026-10-24\n",
            " 2026-10-24",
            "2026-10-24 ",
            "tomorrow",
            '2026-10-24"',
            "2026-10-24\\1",
        ],
    )
    def test_update_refuses_a_date_that_is_not_yyyy_mm_dd(self, bad: str) -> None:
        with pytest.raises(ValueError):
            bump._update_citation_date(SAMPLE_CFF, bad)

    def test_update_citation_sets_version_and_date_together(self) -> None:
        out = bump._update_citation(SAMPLE_CFF, "1.8.13", "2026-10-24")
        assert bump._extract_citation_version(out) == "1.8.13"
        assert bump._extract_citation_date(out) == "2026-10-24"

    def test_update_citation_without_a_date_leaves_the_date(self) -> None:
        out = bump._update_citation(SAMPLE_CFF, "1.8.13", None)
        assert bump._extract_citation_version(out) == "1.8.13"
        assert bump._extract_citation_date(out) == "2026-09-07"

    def test_update_citation_does_not_add_a_field_the_file_does_not_have(self) -> None:
        text = 'cff-version: 1.2.0\nversion: "1.8.12"\n'
        out = bump._update_citation(text, "1.8.13", "2026-10-24")
        assert out == 'cff-version: 1.2.0\nversion: "1.8.13"\n'


# ---------------------------------------------------------------------------------------------
# The warning
# ---------------------------------------------------------------------------------------------


class TestCitationDateWarning:
    def _tree(
        self, tmp_path: Path, *, changelog: str | None, citation: str | None
    ) -> Path:
        tmp_path.mkdir(parents=True, exist_ok=True)
        if changelog is not None:
            (tmp_path / "CHANGELOG.md").write_text(changelog, encoding="utf-8")
        if citation is not None:
            (tmp_path / "CITATION.cff").write_text(citation, encoding="utf-8")
        return tmp_path

    def test_it_names_the_version_and_the_date_that_stays(self, tmp_path: Path) -> None:
        root = self._tree(
            tmp_path, changelog="## [Unreleased]\n- x\n", citation=SAMPLE_CFF
        )
        message = bump._citation_date_warning(root, "1.8.13")
        assert message is not None
        assert message.startswith("WARNING (R874)")
        assert "## [1.8.13] - YYYY-MM-DD" in message
        assert "2026-09-07" in message

    def test_no_warning_when_the_changelog_has_the_dated_heading(
        self, tmp_path: Path
    ) -> None:
        root = self._tree(
            tmp_path, changelog="## [1.8.13] - 2026-10-24\n- x\n", citation=SAMPLE_CFF
        )
        assert bump._citation_date_warning(root, "1.8.13") is None

    def test_no_warning_when_there_is_no_date_to_keep_in_step(
        self, tmp_path: Path
    ) -> None:
        root = self._tree(
            tmp_path, changelog="## [Unreleased]\n", citation='version: "1.8.12"\n'
        )
        assert bump._citation_date_warning(root, "1.8.13") is None

    def test_no_warning_when_there_is_no_changelog_or_no_citation(
        self, tmp_path: Path
    ) -> None:
        only_cff = self._tree(tmp_path / "a", changelog=None, citation=SAMPLE_CFF)
        only_log = self._tree(
            tmp_path / "b", changelog="## [Unreleased]\n", citation=None
        )
        for root in (only_cff, only_log):
            assert bump._citation_date_warning(root, "1.8.13") is None

    def test_a_heading_with_an_impossible_date_still_warns(
        self, tmp_path: Path
    ) -> None:
        root = self._tree(
            tmp_path, changelog="## [1.8.13] - 2026-02-30\n- x\n", citation=SAMPLE_CFF
        )
        assert bump._citation_date_warning(root, "1.8.13") is not None


# ---------------------------------------------------------------------------------------------
# A whole bump
# ---------------------------------------------------------------------------------------------


def _copy_real_release_files(destination: Path) -> None:
    for relative in RELEASE_FILES:
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(REPO / relative, target)


def _promote(changelog: Path, version: str, date: str) -> None:
    """What the release checklist's A.1 does: the next release gets its own dated heading."""
    text = changelog.read_text(encoding="utf-8")
    first_release = re.search(r"^## \[", text, re.MULTILINE)
    assert first_release is not None
    heading = f"## [{version}] - {date}\n\n- Everything above the previous release.\n\n"
    changelog.write_text(
        text[: first_release.start()] + heading + text[first_release.start() :],
        encoding="utf-8",
    )


@pytest.fixture
def release_tree(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    _copy_real_release_files(tmp_path)
    monkeypatch.setattr(bump, "_repo_root", lambda: tmp_path)
    return tmp_path


class TestAWholeBump:
    def test_a_promoted_changelog_carries_its_date_into_the_citation(
        self, release_tree: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        original = (release_tree / "CITATION.cff").read_text(encoding="utf-8")
        _promote(release_tree / "CHANGELOG.md", "99.0.0", "2031-01-02")
        assert bump.main(["99.0.0"]) == 0
        captured = capsys.readouterr()
        assert "R874" not in captured.err
        updated = (release_tree / "CITATION.cff").read_text(encoding="utf-8")
        assert bump._extract_citation_version(updated) == "99.0.0"
        assert bump._extract_citation_date(updated) == "2031-01-02"
        before, after = original.splitlines(), updated.splitlines()
        assert len(before) == len(after)
        assert sum(a != b for a, b in zip(before, after, strict=True)) == 2

    def test_every_version_source_agrees_afterwards(
        self, release_tree: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _promote(release_tree / "CHANGELOG.md", "99.0.0", "2031-01-02")
        assert bump.main(["99.0.0"]) == 0
        assert bump.main(["--check"]) == 0
        assert "99.0.0" in capsys.readouterr().out

    def test_a_second_run_changes_nothing(self, release_tree: Path) -> None:
        _promote(release_tree / "CHANGELOG.md", "99.0.0", "2031-01-02")
        assert bump.main(["99.0.0"]) == 0
        first = {name: (release_tree / name).read_bytes() for name in RELEASE_FILES}
        assert bump.main(["99.0.0"]) == 0
        assert {
            name: (release_tree / name).read_bytes() for name in RELEASE_FILES
        } == first

    def test_a_bump_before_the_promotion_warns_and_keeps_the_date(
        self, release_tree: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        before = bump._extract_citation_date(
            (release_tree / "CITATION.cff").read_text("utf-8")
        )
        assert bump.main(["99.0.0"]) == 0
        err = capsys.readouterr().err
        assert "WARNING (R874)" in err
        assert "## [99.0.0] - YYYY-MM-DD" in err
        assert before is not None and before in err
        after = (release_tree / "CITATION.cff").read_text(encoding="utf-8")
        assert bump._extract_citation_version(after) == "99.0.0"
        assert bump._extract_citation_date(after) == before

    def test_promoting_afterwards_and_running_again_brings_the_date_along(
        self, release_tree: Path
    ) -> None:
        assert bump.main(["99.0.0"]) == 0
        _promote(release_tree / "CHANGELOG.md", "99.0.0", "2031-01-02")
        assert bump.main(["99.0.0"]) == 0
        text = (release_tree / "CITATION.cff").read_text(encoding="utf-8")
        assert bump._extract_citation_date(text) == "2031-01-02"

    def test_the_date_comes_from_the_version_being_bumped_to(
        self, release_tree: Path
    ) -> None:
        _promote(release_tree / "CHANGELOG.md", "99.0.0", "2031-01-02")
        _promote(release_tree / "CHANGELOG.md", "99.0.1", "2031-02-03")
        assert bump.main(["99.0.0"]) == 0
        text = (release_tree / "CITATION.cff").read_text(encoding="utf-8")
        assert bump._extract_citation_date(text) == "2031-01-02"

    def test_a_missing_changelog_does_not_stop_the_bump_or_print_the_warning(
        self, release_tree: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        (release_tree / "CHANGELOG.md").unlink()
        assert bump.main(["99.0.0"]) == 0
        assert "R874" not in capsys.readouterr().err

    def test_a_citation_without_a_date_does_not_stop_the_bump(
        self, release_tree: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        cff = release_tree / "CITATION.cff"
        cff.write_text(
            re.sub(
                r"^date-released:.*\n", "", cff.read_text("utf-8"), flags=re.MULTILINE
            ),
            encoding="utf-8",
        )
        _promote(release_tree / "CHANGELOG.md", "99.0.0", "2031-01-02")
        assert bump.main(["99.0.0"]) == 0
        assert "R874" not in capsys.readouterr().err
        assert "date-released" not in cff.read_text(encoding="utf-8")

    def test_check_does_not_look_at_the_date(self, release_tree: Path) -> None:
        cff = release_tree / "CITATION.cff"
        cff.write_text(
            bump._update_citation_date(cff.read_text("utf-8"), "1999-01-01"),
            encoding="utf-8",
        )
        assert bump.main(["--check"]) == 0

    def test_dry_run_writes_nothing_and_describes_the_date(
        self, release_tree: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        before = {name: (release_tree / name).read_bytes() for name in RELEASE_FILES}
        assert bump.main(["99.0.0", "--dry-run"]) == 0
        out = capsys.readouterr().out
        assert "date-released" in out
        assert "CHANGELOG.md" in out
        assert "手动维护" not in out
        assert {n: (release_tree / n).read_bytes() for n in RELEASE_FILES} == before


# ---------------------------------------------------------------------------------------------
# What the people who release are told
# ---------------------------------------------------------------------------------------------


class TestTheReleaseDocsSayIt:
    @pytest.mark.parametrize(
        "relative",
        ["docs/workflow.md", "docs/workflow.zh-CN.md", "docs/release-checklist.md"],
    )
    def test_the_release_instructions_name_date_released(self, relative: str) -> None:
        text = (REPO / relative).read_text(encoding="utf-8")
        assert "date-released" in text, (
            f"{relative} never mentions CITATION.cff date-released"
        )

    def test_nothing_still_says_the_date_is_kept_by_hand(self) -> None:
        for relative in (
            "scripts/bump_version.py",
            "docs/workflow.md",
            "docs/workflow.zh-CN.md",
            "docs/release-checklist.md",
        ):
            text = (REPO / relative).read_text(encoding="utf-8")
            assert "仍需手动维护" not in text, relative
