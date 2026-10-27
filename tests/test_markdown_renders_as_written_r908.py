"""R908: Markdown shows what it says: every table is a table, no row loses cells, and no page is swallowed by a fenced block that never closes.

A renderer that follows GitHub Flavored Markdown (GitHub itself, the Markdown preview of VS Code,
markdown-it, marked) shows a table only when the header row and the delimiter row under it have the
same number of cells, and it throws away every cell of a body row beyond the width of the header. Both
failures are silent: the file reads fine as text, and the page shows either the raw pipes of a table
that was never recognised or a row with its tail missing.

Both had happened. The delimiter row of the catalogue in ``docs/contributor-guide-invariant-tests.md``
and in its zh-CN twin ended in a fifth ``| --- |`` cell that the four-cell header does not have (since
commit fe86cba3 of 2026-07-26), so on GitHub and in a preview neither of the two catalogues, some 280
rows each, was a table at all: markdown-it rendered no table from either file. Behind it were 19 rows
that would have lost their tails once the delimiter was right: 11 that ended in a stray empty cell (10
in the zh-CN guide, 1 in the EN one) and 8 (4 in each guide) with a ``|`` in a code span
(``curl ... | jq``, ``<<key|params>>``), which is a cell boundary in a table unless it is written
``\\|``. The review ``docs/code-reviews/cr21.md`` had one such row (``Exception | None``). Two rows
glued into one by a missing newline (the R906 row, repaired just before this guard was written) are the
same defect with eight cells.

A fenced block that is opened and never closed is silent in the same way. The module docstring of
``text_safety.py`` (R845) underlined a heading with a row of tildes, the way reStructuredText does; in
Markdown a line of three or more tildes opens a fenced block, nothing closed it, and the generated page
``docs/api.zh-CN/text_safety.md`` showed everything after it, the explanation and the list of
functions, as one block of code (markdown-it: no heading, one code block). It was the only page of the
repository that ended inside a fence.

The checker below is the CommonMark / GFM rule for those two things, which cannot be seen in the
source, applied to every Markdown file of the repository outside the build and dependency directories.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
GUIDES = (
    ROOT / "docs" / "contributor-guide-invariant-tests.md",
    ROOT / "docs" / "contributor-guide-invariant-tests.zh-CN.md",
)
GENERATED_PAGE_WITH_THE_TILDE_HEADING = ROOT / "docs" / "api.zh-CN" / "text_safety.md"

SKIPPED_DIRS = frozenset(
    {
        ".git",
        ".venv",
        "venv",
        "node_modules",
        "site-packages",
        "dist",
        "build",
        "out",
        ".tox",
        ".mypy_cache",
        ".ruff_cache",
        ".pytest_cache",
        "__pycache__",
        ".coverage_data",
    }
)
FENCE = re.compile(r"^\s*(`{3,}|~{3,})(.*)$")
DELIMITER_CELL = re.compile(r"^\s*:?-+:?\s*$")
UNESCAPED_PIPE = re.compile(r"(?<!\\)\|")


def fence_scan(lines: list[str]) -> tuple[list[bool], int | None]:
    """Which lines are inside a fenced block (the fences included), and where one is left open.

    A block opens at three or more backticks or tildes (the info string after backticks may not hold a
    backtick) and closes at a fence of the same character, at least as long, with nothing after it.
    The second value is the 1-based line of the fence that is still open at the end, or ``None``.
    """
    inside = [False] * len(lines)
    opener = ""
    opened_at = 0
    for index, line in enumerate(lines):
        match = FENCE.match(line)
        if opener:
            inside[index] = True
            if (
                match
                and match.group(1)[0] == opener[0]
                and len(match.group(1)) >= len(opener)
                and not match.group(2).strip()
            ):
                opener = ""
        elif match and not (match.group(1)[0] == "`" and "`" in match.group(2)):
            opener = match.group(1)
            opened_at = index + 1
            inside[index] = True
    return inside, (opened_at if opener else None)


def unclosed_fence(text: str) -> int | None:
    """The 1-based line of a fenced block that ``text`` opens and never closes, or ``None``."""
    return fence_scan(text.split("\n"))[1]


def split_row(line: str) -> list[str]:
    """The cells of a table row: split at every ``|`` that is not written ``\\|``, outer pipes dropped.

    A pipe inside a code span splits the row as well; GFM has no other way to put one in a cell.
    """
    stripped = line.strip()
    cells = UNESCAPED_PIPE.split(stripped)
    if stripped.startswith("|"):
        cells = cells[1:]
    if stripped.endswith("|") and not stripped.endswith("\\|"):
        cells = cells[:-1]
    return cells


def is_delimiter_row(line: str) -> bool:
    """A row of cells that are only dashes with optional colons (and at least one pipe)."""
    if "|" not in line:
        return False
    cells = split_row(line)
    return bool(cells) and all(DELIMITER_CELL.match(cell) for cell in cells)


def tables(text: str) -> list[tuple[int, int, list[tuple[int, int]]]]:
    """Every table of ``text`` outside fenced code: ``(line of the header, cells in the header, rows)``.

    ``rows`` holds ``(line, cells)`` for the delimiter row first and then each body row; a table ends at
    the first line that has no pipe (a blank line has none) or that is inside a fenced block.
    """
    lines = text.split("\n")
    inside, _ = fence_scan(lines)
    found: list[tuple[int, int, list[tuple[int, int]]]] = []
    for index, line in enumerate(lines):
        if inside[index] or index == 0 or not is_delimiter_row(line):
            continue
        header = lines[index - 1]
        if "|" not in header or is_delimiter_row(header):
            continue
        rows = [(index + 1, len(split_row(line)))]
        for offset in range(index + 1, len(lines)):
            row = lines[offset]
            if inside[offset] or "|" not in row:
                break
            rows.append((offset + 1, len(split_row(row))))
        found.append((index, len(split_row(header)), rows))
    return found


def table_problems(text: str) -> list[tuple[int, str]]:
    """The tables of ``text`` that a GFM renderer does not show, or shows with cells missing."""
    problems: list[tuple[int, str]] = []
    for _header_line, width, rows in tables(text):
        delimiter_line, delimiter_cells = rows[0]
        if delimiter_cells != width:
            problems.append(
                (
                    delimiter_line,
                    f"the delimiter row has {delimiter_cells} cells and the header {width}: "
                    "the renderer does not show a table",
                )
            )
        problems.extend(
            (
                line,
                f"the row has {cells} cells and the header {width}: the extra cells are dropped",
            )
            for line, cells in rows[1:]
            if cells > width
        )
    return problems


def tracked_or_new_markdown_files(root: Path = ROOT) -> list[Path] | None:
    """The Markdown files git knows of or would add (not the ignored ones), or ``None`` without git."""
    try:
        done = subprocess.run(
            [
                "git",
                "-C",
                str(root),
                "ls-files",
                "--cached",
                "--others",
                "--exclude-standard",
                "-z",
                "--",
                "*.md",
            ],
            capture_output=True,
            check=True,
            timeout=60,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    names = [name for name in done.stdout.decode("utf-8").split("\0") if name]
    return sorted(path for name in names if (path := root / name).is_file())


def walked_markdown_files(root: Path = ROOT) -> list[Path]:
    found: list[Path] = []
    for current, directories, names in os.walk(root):
        directories[:] = sorted(d for d in directories if d not in SKIPPED_DIRS)
        found.extend(
            Path(current, name) for name in sorted(names) if name.endswith(".md")
        )
    return found


def markdown_files(root: Path = ROOT) -> list[Path]:
    from_git = tracked_or_new_markdown_files(root)
    return from_git if from_git else walked_markdown_files(root)


class TestEveryMarkdownFileOfTheRepositoryRendersAsWritten:
    def test_no_table_is_unrecognised_or_cut_short(self) -> None:
        damaged: dict[str, list[tuple[int, str]]] = {}
        for path in markdown_files():
            problems = table_problems(path.read_text(encoding="utf-8"))
            if problems:
                damaged[str(path.relative_to(ROOT))] = problems
        assert damaged == {}, (
            "a Markdown table that GitHub and a preview would not show as written: "
            "make the delimiter row as wide as the header, drop a stray empty cell, "
            "and write a pipe inside a cell as \\|"
        )

    def test_no_page_ends_inside_a_fenced_block(self) -> None:
        left_open: dict[str, int] = {}
        for path in markdown_files():
            line = unclosed_fence(path.read_text(encoding="utf-8"))
            if line is not None:
                left_open[str(path.relative_to(ROOT))] = line
        assert left_open == {}, (
            "a fenced block that is never closed shows the rest of the page as code: "
            "close it; a line of tildes or backticks under a heading is a fence, "
            "so underline a heading with dashes or equals signs"
        )

    def test_the_scan_is_not_empty(self) -> None:
        found = [
            table
            for path in markdown_files()
            for table in tables(path.read_text(encoding="utf-8"))
        ]
        assert len(found) >= 300
        assert sum(len(rows) - 1 for _, _, rows in found) >= 2000

    def test_the_two_catalogues_are_in_the_scan(self) -> None:
        scanned = set(markdown_files())
        assert set(GUIDES) <= scanned
        assert GENERATED_PAGE_WITH_THE_TILDE_HEADING in scanned


class TestAgainstARealRenderer:
    @pytest.mark.parametrize("guide", GUIDES, ids=lambda path: path.name)
    def test_a_catalogue_renders_as_one_table_of_four_cells_a_row(
        self, guide: Path
    ) -> None:
        markdown_it = pytest.importorskip("markdown_it")
        text = guide.read_text(encoding="utf-8")
        html = markdown_it.MarkdownIt("commonmark").enable("table").render(text)
        rows = re.findall(r"<tr>.*?</tr>", html, flags=re.DOTALL)
        found = tables(text)
        assert len(found) == 1
        assert html.count("<table>") == 1
        # the header and every body row; the delimiter row is not a row of the rendered table
        assert len(rows) == len(found[0][2])
        assert {len(re.findall(r"<t[dh][ >]", row)) for row in rows} == {4}

    def test_the_generated_page_with_a_tilde_heading_shows_its_sections(self) -> None:
        markdown_it = pytest.importorskip("markdown_it")
        text = GENERATED_PAGE_WITH_THE_TILDE_HEADING.read_text(encoding="utf-8")
        html = markdown_it.MarkdownIt("commonmark").enable("table").render(text)
        assert "<pre>" not in html
        assert "<h2>函数</h2>" in html
        assert html.count("<h3>") >= 4
        assert unclosed_fence(text) is None


def _git(tree: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(tree), *args],
        check=True,
        capture_output=True,
        env={
            **os.environ,
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_SYSTEM": os.devnull,
        },
    )


class TestWhichFilesAreRead:
    def test_the_walk_skips_dependency_and_build_directories(
        self, tmp_path: Path
    ) -> None:
        for name in (
            "README.md",
            "docs/a.md",
            "docs/deep/b.md",
            "node_modules/pkg/README.md",
            ".venv/lib/c.md",
            "dist/d.md",
            "packages/x/node_modules/e.md",
            ".git/notes.md",
        ):
            target = tmp_path / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("x\n", encoding="utf-8")
        (tmp_path / "docs" / "not-markdown.txt").write_text("x\n", encoding="utf-8")
        found = [
            p.relative_to(tmp_path).as_posix() for p in walked_markdown_files(tmp_path)
        ]
        assert sorted(found) == ["README.md", "docs/a.md", "docs/deep/b.md"]

    def test_without_git_the_walk_is_what_is_read(self, tmp_path: Path) -> None:
        (tmp_path / "a.md").write_text("x\n", encoding="utf-8")
        assert tracked_or_new_markdown_files(tmp_path) is None
        assert markdown_files(tmp_path) == [tmp_path / "a.md"]

    def test_git_lists_tracked_and_new_files_but_not_ignored_ones(
        self, tmp_path: Path
    ) -> None:
        if shutil.which("git") is None:
            pytest.skip("git is not installed")
        _git(tmp_path, "init", "-q")
        (tmp_path / ".gitignore").write_text(
            "scratch.md\nnode_modules/\n", encoding="utf-8"
        )
        for name in (
            "tracked.md",
            "new.md",
            "scratch.md",
            "docs/deep.md",
            "node_modules/x.md",
        ):
            target = tmp_path / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("x\n", encoding="utf-8")
        _git(tmp_path, "add", "tracked.md", ".gitignore")
        found = tracked_or_new_markdown_files(tmp_path)
        assert found is not None
        assert [p.relative_to(tmp_path).as_posix() for p in found] == [
            "docs/deep.md",
            "new.md",
            "tracked.md",
        ]
        assert markdown_files(tmp_path) == found

    def test_a_file_that_git_still_lists_but_that_is_gone_is_left_out(
        self, tmp_path: Path
    ) -> None:
        if shutil.which("git") is None:
            pytest.skip("git is not installed")
        _git(tmp_path, "init", "-q")
        (tmp_path / "gone.md").write_text("x\n", encoding="utf-8")
        (tmp_path / "here.md").write_text("x\n", encoding="utf-8")
        _git(tmp_path, "add", "gone.md", "here.md")
        (tmp_path / "gone.md").unlink()
        found = tracked_or_new_markdown_files(tmp_path)
        assert found is not None
        assert [p.name for p in found] == ["here.md"]


GOOD = "| a | b |\n| --- | --- |\n| 1 | 2 |\n| 3 | 4 |\n"


class TestTheCheckerForTables:
    def test_a_table_that_is_right_has_no_problem(self) -> None:
        assert table_problems(GOOD) == []
        assert [(width, len(rows)) for _, width, rows in tables(GOOD)] == [(2, 3)]

    def test_a_delimiter_row_wider_than_the_header_is_found(self) -> None:
        text = "| a | b |\n| --- | --- | --- |\n| 1 | 2 |\n"
        assert [line for line, _ in table_problems(text)] == [2]
        assert "does not show a table" in table_problems(text)[0][1]

    def test_a_delimiter_row_narrower_than_the_header_is_found(self) -> None:
        text = "| a | b | c |\n| --- | --- |\n| 1 | 2 | 3 |\n"
        assert [line for line, _ in table_problems(text)] == [2]

    def test_the_rows_are_still_looked_at_when_the_delimiter_is_wrong(self) -> None:
        text = "| a | b |\n| --- | --- | --- |\n| 1 | 2 | 3 |\n| 4 | 5 |\n"
        assert [line for line, _ in table_problems(text)] == [2, 3]

    def test_a_row_with_more_cells_than_the_header_is_found(self) -> None:
        text = GOOD + "| 5 | 6 | 7 |\n"
        assert [line for line, _ in table_problems(text)] == [5]
        assert "extra cells are dropped" in table_problems(text)[0][1]

    def test_two_rows_that_ran_together_are_found(self) -> None:
        text = "| a | b |\n| --- | --- |\n| 1 | 2 | 3 | 4 |\n"
        assert [line for line, _ in table_problems(text)] == [3]

    def test_a_stray_empty_cell_at_the_end_is_found(self) -> None:
        text = "| a | b |\n| --- | --- |\n| 1 | 2 |     |\n"
        assert [line for line, _ in table_problems(text)] == [3]

    def test_a_row_with_fewer_cells_is_left_alone(self) -> None:
        # a renderer pads it with empty cells; nothing is lost
        assert table_problems("| a | b |\n| --- | --- |\n| 1 |\n") == []

    def test_a_pipe_in_a_code_span_splits_the_row_unless_it_is_escaped(self) -> None:
        loose = "| a | b |\n| --- | --- |\n| `x | y` | 2 |\n"
        assert [line for line, _ in table_problems(loose)] == [3]
        escaped = "| a | b |\n| --- | --- |\n| `x \\| y` | 2 |\n"
        assert table_problems(escaped) == []

    def test_an_escaped_pipe_is_not_a_boundary(self) -> None:
        assert split_row("| a \\| b | c |") == [" a \\| b ", " c "]

    def test_an_escaped_pipe_at_the_end_does_not_close_the_row(self) -> None:
        assert split_row("| a | b \\|") == [" a ", " b \\|"]

    def test_outer_pipes_are_optional_and_spaces_do_not_count(self) -> None:
        assert split_row("  a | b  ") == ["a ", " b"]
        assert split_row("| a | b |  ") == [" a ", " b "]
        assert split_row("|a|b|") == ["a", "b"]
        assert split_row("| a |") == [" a "]

    def test_an_empty_cell_is_a_cell(self) -> None:
        assert split_row("| a |  | c |") == [" a ", "  ", " c "]
        assert split_row("| a | b |     |") == [" a ", " b ", "     "]

    def test_lines_are_counted_from_one(self) -> None:
        text = "intro\n\n| a | b |\n| --- | --- |\n| 1 | 2 |\n| 3 | 4 |\n"
        assert tables(text) == [(3, 2, [(4, 2), (5, 2), (6, 2)])]

    def test_a_table_inside_a_fenced_block_is_not_looked_at(self) -> None:
        text = "```\n| a | b |\n| --- | --- | --- |\n```\n"
        assert table_problems(text) == []
        assert tables(text) == []

    def test_a_table_after_a_fenced_block_is_looked_at(self) -> None:
        text = "```\n| a |\n```\n\n| a | b |\n| --- | --- | --- |\n"
        assert [line for line, _ in table_problems(text)] == [6]

    def test_a_table_below_a_fence_that_never_closes_is_not_a_table_either(
        self,
    ) -> None:
        # the renderer sees code there; so does the checker
        text = "Title\n~~~~~\n| a | b |\n| --- | --- | --- |\n| 1 | 2 | 3 | 4 |\n"
        assert tables(text) == []

    def test_a_table_is_cut_where_a_fence_opens_without_a_blank_line(self) -> None:
        # the opening fence has pipes in its info string, so only the fence can end the table
        text = GOOD + "```a|b|c|d\n| 1 | 2 | 3 | 4 | 5 |\n```\n"
        assert table_problems(text) == []
        assert [len(rows) for _, _, rows in tables(text)] == [3]

    @pytest.mark.parametrize("delimiter", ["|:--|--:|", "| :---: | ---: |", "|-|-|"])
    def test_alignment_colons_and_short_dashes_make_a_delimiter_row(
        self, delimiter: str
    ) -> None:
        assert is_delimiter_row(delimiter)
        assert table_problems(f"| a | b |\n{delimiter}\n| 1 | 2 |\n") == []

    @pytest.mark.parametrize(
        "line",
        ["---", "***", "| a | b |", "| -- x | -- |", "", "|", "|   |   |", "| | |"],
    )
    def test_what_is_not_a_delimiter_row(self, line: str) -> None:
        assert not is_delimiter_row(line)

    def test_text_with_a_pipe_but_no_delimiter_row_is_not_a_table(self) -> None:
        assert tables("a | b | c\nd | e | f | g\n") == []

    def test_a_delimiter_row_on_the_first_line_has_no_header(self) -> None:
        # nothing is above it: the line before index 0 must not be the last line of the text
        assert tables("| - | - |\n| 1 | 2 |") == []
        assert table_problems("| - | - |\n| 1 | 2 |\n| 3 | 4 | 5 |") == []

    def test_a_header_without_a_pipe_is_not_a_header(self) -> None:
        assert tables("text\n| --- | --- |\n") == []

    def test_a_delimiter_row_under_a_delimiter_row_is_not_a_table(self) -> None:
        assert tables("| - | - |\n| - | - |\n") == []

    def test_a_rule_under_a_heading_is_not_a_table(self) -> None:
        assert tables("Heading\n---\n\ntext | more\n") == []

    def test_a_table_ends_at_a_blank_line(self) -> None:
        text = GOOD + "\n| 1 | 2 | 3 | 4 | 5 |\n"
        assert table_problems(text) == []

    def test_a_table_ends_at_a_line_without_a_pipe(self) -> None:
        text = GOOD + "text\n| 1 | 2 | 3 | 4 | 5 |\n"
        assert table_problems(text) == []

    def test_a_table_without_outer_pipes_is_read(self) -> None:
        text = "a | b\n--- | ---\n1 | 2 | 3\n"
        assert [line for line, _ in table_problems(text)] == [3]

    def test_two_tables_are_both_read(self) -> None:
        text = GOOD + "\n" + "| a | b | c |\n| - | - | - |\n| 1 | 2 | 3 |\n"
        assert [(width, len(rows)) for _, width, rows in tables(text)] == [
            (2, 3),
            (3, 2),
        ]
        assert table_problems(text) == []


class TestTheCheckerForFences:
    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("a\n```\ncode\n```\n", None),
            ("a\n```python\ncode\n```\n", None),
            ("a\n~~~\ncode\n~~~\n", None),
            ("a\n```\ncode\n", 2),
            ("a\n~~~\ncode\n", 2),
            # a row of tildes under a heading: the case that swallowed a generated page
            ("Why\n~~~~~~~~~~~~~~~~~~\ntext\n\n## Functions\n", 2),
            # reStructuredText underlines that Markdown reads as headings, not as fences
            ("Why\n------------------\ntext\n", None),
            ("Why\n==================\ntext\n", None),
            # a longer opening fence is closed only by one at least as long
            ("````\n```\ninner\n```\n````\n", None),
            ("````\n```\ninner\n```\n", 1),
            ("```\ncode\n````\n", None),
            # a fence of the other character does not close it
            ("```\ncode\n~~~\n", 1),
            ("~~~\n```\ninner\n~~~\n", None),
            ("~~~\ncode\n```\n", 1),
            # nothing may follow a closing fence
            ("```\ncode\n``` text\n", 1),
            # a backtick in the info string means it is inline code, not a fence
            ("``` not a fence ``` really\n", None),
            ("```a`b\ntext\n", None),
            # a tilde fence may have backticks in its info string
            ("~~~ a`b\ntext\n", 1),
            # indentation (a fence inside a list item) does not matter
            ("10. item\n\n    ```bash\n    x\n    ```\n", None),
            ("10. item\n\n    ```bash\n    x\n", 3),
            # the first fence that stays open is the one reported
            ("```\na\n```\n\n```\nb\n", 5),
            ("", None),
            ("plain text\n", None),
        ],
    )
    def test_the_line_of_the_fence_left_open(
        self, text: str, expected: int | None
    ) -> None:
        assert unclosed_fence(text) == expected

    def test_every_line_between_the_fences_is_code_and_the_fences_too(self) -> None:
        lines = ["a", "```", "b", "```", "c", "~~~", "d", "~~~", "e"]
        inside, left_open = fence_scan(lines)
        assert inside == [False, True, True, True, False, True, True, True, False]
        assert left_open is None

    def test_an_open_fence_runs_to_the_last_line(self) -> None:
        inside, left_open = fence_scan(["a", "~~~", "b", "c"])
        assert inside == [False, True, True, True]
        assert left_open == 2

    def test_a_closed_block_does_not_report_an_earlier_open_line(self) -> None:
        _, left_open = fence_scan(["```", "a", "```", "b"])
        assert left_open is None
