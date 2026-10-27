"""R910: a Markdown link that points at ``#anchor`` lands on a heading that exists.

``tests/test_docs_links_no_rot.py`` checks that the file a link names is there, and stops at the ``#``.
A link to a section of a page is a promise of a second kind: the heading is there, and it gives that
anchor. Break it and nothing complains; the browser opens the page at its top and the reader is left
to find the section alone.

One had been broken. ``docs/troubleshooting.zh-CN.md`` sends the reader of the "the client gave up on a
silent call" entry to ``configuration.zh-CN.md#feedback``, the English page's anchor. The Chinese
heading is ``### `feedback`（反馈/超时）``, whose anchor is ``feedback反馈超时``: the full-width
parentheses and the slash are dropped, the Chinese words stay. ``#feedback`` matched nothing and the
link opened the top of a 440-line page. The twin ``troubleshooting.md`` links the same section with
the right anchor, so the two languages disagreed. It was the only one of the 41 anchor links of the
repository that was dead, and no test could have told.

The rule that makes an anchor out of a heading is the one GitHub uses (the ``github-slugger`` package):

- the text of the heading as a reader sees it (the words and the code, none of the markup around them,
  no image) is lower-cased;
- every space becomes a hyphen; everything that is not a letter, a mark, a number or a hyphen or an
  underscore is dropped, which includes all punctuation (the Chinese full-width kind too), emoji, and
  any other white space;
- a slug that is already taken gets ``-1``, ``-2``, ... until one is free, and the numbered slug is
  taken, too.

The expected values of the table below were produced by ``github-slugger`` 2.0.0, not by the code of
this file. The same code was also compared with it over all 4,443 headings of the 233 Markdown files of
the repository (no difference), over every Unicode code point (770 differences out of 1.1 million:
circled capital letters, and scripts added to Unicode after that package was built), and over 200,000
random strings made of the punctuation, Chinese, emoji, accents and combining marks that headings
contain (no difference).

A heading is found the way a renderer finds it, by parsing the page (``markdown-it``), so that a line
that starts with ``#`` inside a fenced block (a shell comment) is not taken for a heading, and a
heading written with an underline is. An ``id`` or ``name`` written in raw HTML (``<a id="x"></a>``)
is an anchor too. Links are collected the same way, so reference-style links count and a link written
inside a code span does not. A link is checked when it has a fragment and points into a Markdown file
that exists; other targets are left to ``test_docs_links_no_rot.py`` or to nobody (``file.py#L10``).
"""

from __future__ import annotations

import difflib
import os
import re
import unicodedata
from collections.abc import Iterable
from pathlib import Path
from typing import Any, NamedTuple
from urllib.parse import unquote, urlsplit

import pytest

from tests.test_markdown_renders_as_written_r908 import ROOT, markdown_files

markdown_it = pytest.importorskip("markdown_it")

PARSER = markdown_it.MarkdownIt("commonmark").enable("table")

EXTERNAL = re.compile(r"^(?:[a-zA-Z][a-zA-Z0-9+.-]*:|//)")
HTML_ANCHOR = re.compile(
    r"""<[a-zA-Z][^<>]*?\s(?:id|name)\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s"'<>=`]+))"""
)


def slug_of(text: str) -> str:
    """The anchor GitHub makes of the text of a heading, before the numbering of repeated ones."""
    kept: list[str] = []
    for char in text.lower():
        category = unicodedata.category(char)
        if char == " ":
            kept.append("-")
        elif char == "-" or category[0] in "LM" or category in ("Nd", "Nl", "Pc"):
            kept.append(char)
    return "".join(kept)


class Slugger:
    """Numbers the repeated headings of one page the way ``github-slugger`` does.

    A slug that is taken gets ``-1``, ``-2``, ... until one is free, and the slug it ends up with is
    taken too, so a heading that is really called ``Same 1`` does not collide with the ``-1`` of
    ``Same``.
    """

    def __init__(self) -> None:
        self.occurrences: dict[str, int] = {}

    def slug(self, text: str) -> str:
        base = slug_of(text)
        result = base
        while result in self.occurrences:
            self.occurrences[base] += 1
            result = f"{base}-{self.occurrences[base]}"
        self.occurrences[result] = 0
        return result


def text_of(inline: Any) -> str:
    """The text of a heading as a reader sees it: words and code, no markup, no image.

    A line break inside a heading (an underlined heading may take several lines) adds nothing: it is
    a newline character in the rendered text, which the slug drops, so the two words around it run
    together.
    """
    return "".join(
        child.content
        for child in inline.children or []
        if child.type in ("text", "code_inline")
    )


def explicit_ids(html: str) -> list[str]:
    """The ``id`` and ``name`` attributes of the tags in a piece of raw HTML."""
    found = (
        next((group for group in groups if group), "")
        for groups in HTML_ANCHOR.findall(html)
    )
    return [name for name in found if name]


class Page(NamedTuple):
    anchors: set[str]
    links: list[tuple[int, str]]  # (line, destination) of every link of the page


def line_of(lines: list[str], block: list[int], destination: str) -> int:
    """The line of the link: the first line of its block that shows its fragment, else the block's."""
    start, end = block
    fragment = urlsplit(destination).fragment
    for needle in (unquote(fragment), fragment):
        for number in range(start, end):
            if needle and f"#{needle}" in lines[number]:
                return number + 1
    return start + 1


def parse(text: str) -> Page:
    tokens = PARSER.parse(text)
    lines = re.split(r"\r\n?|\n", text)  # the breaks markdown-it counts lines by
    slugger = Slugger()
    anchors: set[str] = set()
    links: list[tuple[int, str]] = []
    for index, token in enumerate(tokens):
        if token.type == "heading_open":
            anchors.add(slugger.slug(text_of(tokens[index + 1])))
        elif token.type == "html_block":
            anchors.update(explicit_ids(token.content))
        elif token.type == "inline":
            for child in token.children or []:
                if child.type == "html_inline":
                    anchors.update(explicit_ids(child.content))
                elif child.type == "link_open":
                    destination = child.attrGet("href")
                    if destination:
                        links.append(
                            (
                                line_of(lines, token.map or [0, 1], str(destination)),
                                str(destination),
                            )
                        )
    return Page(anchors, links)


def target_of(source: Path, destination: str, root: Path) -> Path | None:
    """The Markdown file a link with a fragment points into, or ``None`` when it is not checked."""
    if EXTERNAL.match(destination):
        return None
    path = unquote(urlsplit(destination).path)
    if not path:
        return source
    base = root if path.startswith("/") else source.parent
    target = Path(os.path.normpath(base / path.lstrip("/")))
    return target if target.suffix == ".md" else None


class Scan(NamedTuple):
    problems: list[str]
    links: int  # anchor links into Markdown files that exist
    cross_file_links: int  # of those, the ones that point into another file
    anchors: int  # anchors found in the files the links were collected from


def relative(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def scan(files: Iterable[Path], root: Path) -> Scan:
    """Every ``...#fragment`` link of ``files`` into a Markdown file, and whether the fragment exists."""
    pages: dict[Path, Page] = {}

    def page_of(path: Path) -> Page | None:
        if path not in pages:
            if not path.is_file():
                return None
            pages[path] = parse(path.read_text(encoding="utf-8"))
        return pages[path]

    problems: list[str] = []
    checked = cross_file = 0
    sources = list(files)
    for source in sources:
        page = page_of(source)
        assert page is not None
        for line, destination in page.links:
            fragment = unquote(urlsplit(destination).fragment)
            if not fragment or fragment.lower() == "top":
                continue  # the top of the page needs no heading (HTML: "" and "top")
            target = target_of(source, destination, root)
            target_page = page_of(target) if target is not None else None
            if target is None or target_page is None:
                continue  # not Markdown, external, or a file that is missing (another guard's)
            checked += 1
            cross_file += target != source
            if fragment not in target_page.anchors:
                close = difflib.get_close_matches(
                    fragment, sorted(target_page.anchors), n=3, cutoff=0.5
                )
                hint = f" (closest: #{', #'.join(close)})" if close else ""
                problems.append(
                    f"{relative(source, root)}:{line}: {unquote(destination)} - "
                    f"{relative(target, root)} has no heading or id that gives "
                    f"#{fragment}{hint}"
                )
    return Scan(
        problems,
        checked,
        cross_file,
        sum(len(pages[source].anchors) for source in sources),
    )


@pytest.fixture(scope="module")
def repository_scan() -> Scan:
    return scan(markdown_files(), ROOT)


class TestEveryAnchorLinkOfTheRepositoryLandsOnSomething:
    def test_no_link_points_at_an_anchor_that_does_not_exist(
        self, repository_scan: Scan
    ) -> None:
        assert repository_scan.problems == [], (
            "a link that names a section that is not there opens the page at its top; "
            "write the anchor the heading really gives (a heading with Chinese words "
            "keeps them and loses its punctuation: `feedback`（反馈/超时） is "
            "#feedback反馈超时)"
        )

    def test_the_scan_is_not_empty(self, repository_scan: Scan) -> None:
        assert repository_scan.links >= 30
        assert repository_scan.cross_file_links >= 20
        assert repository_scan.anchors >= 4000


# (the Markdown of a heading, the anchor github-slugger 2.0.0 makes of its text)
HEADINGS = [
    ("## Plain heading", "plain-heading"),
    ("### `feedback`（反馈/超时）", "feedback反馈超时"),
    (
        "## 1. Web UI does not start (port already in use)",
        "1-web-ui-does-not-start-port-already-in-use",
    ),
    ("## [1.6.2] — 2026-05-10", "162--2026-05-10"),
    ("### iPhone 推荐用法：快捷指令 + Bark", "iphone-推荐用法快捷指令--bark"),
    ("## What's new in `v2`? (R&D)", "whats-new-in-v2-rd"),
    ("## snake_case and kebab-case", "snake_case-and-kebab-case"),
    ("## Rocket 🚀 launch", "rocket--launch"),
    ("## A  B   C", "a--b---c"),
    ("## Link [the docs](https://example.com/x) here", "link-the-docs-here"),
    ("## *Emphasis* and **strong** text", "emphasis-and-strong-text"),
    (
        "## Escaped \\_underscore\\_ and &amp; entity",
        "escaped-_underscore_-and--entity",
    ),
    ("## Closed with hashes ##", "closed-with-hashes"),
    ("## ÀÉÎ Straße", "àéî-straße"),
    ("## Σίσυφος ΑΣ", "σίσυφος-ας"),
    ("## ![logo](logo.png) Title", "-title"),
    ("## <kbd>Ctrl</kbd>+<kbd>C</kbd>", "ctrlc"),
    ("## A\u00a0B", "ab"),
    ("## 中\u3000文", "中文"),
    ("## Version 1.2.3 (stable)", "version-123-stable"),
    ("## C++ & C# notes", "c--c-notes"),
    ("## Q&A: why? how?", "qa-why-how"),
    ("## `async def f(x: int) -> str`", "async-def-fx-int---str"),
    # the double underscores are strong emphasis, so the text is "dunder"; escaped, they stay
    ("## Under_score_ and __dunder__", "under_score_-and-dunder"),
    # a combining mark, a letter number, a titlecase letter, decimal digits of another script
    ("## Cafe\u0301 au lait", "cafe\u0301-au-lait"),
    ("## Chapter \u2167", "chapter-\u2177"),
    ("## \u01c5 titlecase", "\u01c6-titlecase"),
    ("## \u0967\u0968\u0969 digits", "\u0967\u0968\u0969-digits"),
    ("## Cost \u00bd and \u00b2 and \u2460", "cost--and--and-"),
    ("## \\_\\_init\\_\\_ method", "__init__-method"),
]


class TestWhichAnchorAHeadingGives:
    @pytest.mark.parametrize(
        ("source", "anchor"), HEADINGS, ids=[source for source, _ in HEADINGS]
    )
    def test_the_anchor_is_the_one_github_gives(self, source: str, anchor: str) -> None:
        assert parse(source + "\n").anchors == {anchor}

    @pytest.mark.parametrize(
        ("titles", "expected"),
        [
            (
                ["Same", "Same", "Same", "Same 1", "Other", "Same-1", "Same 1"],
                [
                    "same",
                    "same-1",
                    "same-2",
                    "same-1-1",
                    "other",
                    "same-1-2",
                    "same-1-3",
                ],
            ),
            (["Same", "Same 1", "Same"], ["same", "same-1", "same-2"]),
            (["A", "A", "A 1", "A", "A 1"], ["a", "a-1", "a-1-1", "a-2", "a-1-2"]),
        ],
    )
    def test_repeated_headings_are_numbered_and_never_collide(
        self, titles: list[str], expected: list[str]
    ) -> None:
        slugger = Slugger()
        assert [slugger.slug(title) for title in titles] == expected
        page = parse("".join(f"## {title}\n\n" for title in titles))
        assert page.anchors == set(expected)

    def test_the_numbering_starts_again_on_every_page(self) -> None:
        assert parse("## Same\n").anchors == parse("## Same\n").anchors == {"same"}

    def test_an_underlined_heading_is_a_heading(self) -> None:
        page = parse("First title\n===========\n\nSecond title\n------------\n")
        assert page.anchors == {"first-title", "second-title"}

    def test_a_heading_of_two_lines_runs_its_words_together(self) -> None:
        # the line break is a newline character in the rendered heading, which the slug drops
        assert parse("two\nlines\n=====\n").anchors == {"twolines"}

    def test_a_heading_inside_a_quote_or_a_list_is_a_heading(self) -> None:
        page = parse("> ## Quoted\n\n- item\n\n  ### Nested\n")
        assert page.anchors == {"quoted", "nested"}

    @pytest.mark.parametrize(
        "text",
        [
            "```bash\n# a shell comment\n```\n",
            "~~~\n## inside a tilde fence\n~~~\n",
            "    # an indented code block\n",
            "<!--\n## inside a comment\n-->\n",
            "#hashtag without a space\n",
            "text with ## in the middle\n",
            "\\# escaped\n",
        ],
    )
    def test_what_only_looks_like_a_heading_is_not_one(self, text: str) -> None:
        assert parse(text).anchors == set()

    def test_ids_and_names_written_in_html_are_anchors(self) -> None:
        page = parse(
            "<a id=\"here\"></a> and <a name='there'></a> and <a id=bare></a>\n\n"
            '<div id="block">\n\ntext\n\n</div>\n\n'
            '<span data-id="no" class="id">x</span> <input name="">\n'
        )
        assert page.anchors == {"here", "there", "bare", "block"}


def scan_of(tmp_path: Path, pages: dict[str, str]) -> Scan:
    """Write ``pages`` (name -> text) under ``tmp_path`` and scan all of them."""
    paths = []
    for name, text in pages.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        paths.append(path)
    return scan(paths, tmp_path)


def where(result: Scan) -> list[str]:
    """``file:line: destination`` of every problem, without the explanation."""
    return [problem.split(" - ")[0] for problem in result.problems]


class TestWhichLinksAreChecked:
    def test_a_link_to_a_heading_of_the_same_page(self, tmp_path: Path) -> None:
        result = scan_of(tmp_path, {"a.md": "## Here\n\n[ok](#here) [dead](#there)\n"})
        assert where(result) == ["a.md:3: #there"]
        assert (result.links, result.cross_file_links) == (2, 0)

    def test_a_link_to_a_heading_of_another_page(self, tmp_path: Path) -> None:
        result = scan_of(
            tmp_path,
            {
                "a.md": "[ok](b.md#target) [dead](b.md#nothing) [down](sub/c.md#deep)\n",
                "b.md": "# Target\n",
                "sub/c.md": "[back](../a.md#missing) [fine](../b.md#target)\n\n## Deep\n",
            },
        )
        assert where(result) == ["a.md:1: b.md#nothing", "sub/c.md:1: ../a.md#missing"]
        # the page a link points at is named by its path from the root, not as it was written
        assert result.problems[1].endswith(
            "- a.md has no heading or id that gives #missing"
        )
        assert (result.links, result.cross_file_links) == (5, 5)

    def test_the_english_anchor_of_a_chinese_heading_is_dead(
        self, tmp_path: Path
    ) -> None:
        # the defect this guard was written for
        result = scan_of(
            tmp_path,
            {
                "configuration.zh-CN.md": "### `feedback`（反馈/超时）\n",
                "troubleshooting.zh-CN.md": "[配置](configuration.zh-CN.md#feedback)\n",
            },
        )
        (problem,) = result.problems
        assert problem.startswith(
            "troubleshooting.zh-CN.md:1: configuration.zh-CN.md#feedback - "
            "configuration.zh-CN.md has no heading or id that gives #feedback"
        )
        assert "closest: #feedback反馈超时" in problem
        fixed = scan_of(
            tmp_path,
            {
                "troubleshooting.zh-CN.md": "[配置](configuration.zh-CN.md#feedback反馈超时)\n"
            },
        )
        assert fixed.problems == []

    def test_what_is_not_a_link_into_markdown_is_left_alone(
        self, tmp_path: Path
    ) -> None:
        result = scan_of(
            tmp_path,
            {
                "a.md": (
                    "[external](https://example.com/page.md#nope) "
                    "[mail](mailto:a@example.com#nope) "
                    "[no scheme](//example.com/x.md#nope)\n\n"
                    "[source](script.py#L10) [directory](docs/#nope) "
                    "[image](pic.png#nope)\n\n"
                    "[missing file](gone.md#nope) [no fragment](b.md) [empty](b.md#) "
                    "[top](#top) [also top](b.md#TOP)\n"
                ),
                "b.md": "# B\n",
                # files that a careless reading of the links above would find and then judge
                "page.md": "# Page\n",
                "x.md": "# X\n",
                "script.py": "# a comment, not a heading\n",
                "pic.png": "not a Markdown file\n",
            },
        )
        assert result.problems == []
        assert result.links == 0

    def test_a_link_written_as_code_is_not_a_link(self, tmp_path: Path) -> None:
        result = scan_of(
            tmp_path,
            {"a.md": "`[x](#nope)` and\n\n```\n[y](#nope)\n```\n\n    [z](#nope)\n"},
        )
        assert result.problems == []
        assert result.links == 0

    def test_a_reference_style_link_counts_when_it_is_used(
        self, tmp_path: Path
    ) -> None:
        result = scan_of(
            tmp_path,
            {
                "a.md": "[used][ref]\n\n[ref]: b.md#nope\n[unused]: b.md#also-nope\n",
                "b.md": "# B\n",
            },
        )
        assert where(result) == ["a.md:1: b.md#nope"]

    def test_a_fragment_may_be_written_encoded_or_as_it_is(
        self, tmp_path: Path
    ) -> None:
        result = scan_of(
            tmp_path,
            {
                "a.md": (
                    "[raw](b.md#反馈-超时) "
                    "[encoded](b.md#%E5%8F%8D%E9%A6%88-%E8%B6%85%E6%97%B6) "
                    "[same page](#反馈)\n\n## 反馈\n"
                ),
                "b.md": "## 反馈 超时\n",
            },
        )
        assert result.problems == []
        assert result.links == 3

    def test_a_path_may_have_spaces_or_start_at_the_root(self, tmp_path: Path) -> None:
        result = scan_of(
            tmp_path,
            {
                "a.md": "[angle](<my page.md#here>) [encoded](my%20page.md#here)\n",
                "my page.md": "## Here\n",
                "sub/b.md": "[root](/my%20page.md#here) [dead](/my%20page.md#gone)\n",
            },
        )
        assert where(result) == ["sub/b.md:1: /my page.md#gone"]
        assert result.links == 4

    def test_an_anchor_is_case_sensitive(self, tmp_path: Path) -> None:
        result = scan_of(tmp_path, {"a.md": "## Feedback\n\n[x](#Feedback)\n"})
        assert where(result) == ["a.md:3: #Feedback"]
        assert "closest: #feedback" in result.problems[0]

    def test_a_link_in_a_table_cell_or_a_heading_is_found(self, tmp_path: Path) -> None:
        result = scan_of(
            tmp_path,
            {
                "a.md": (
                    "## Title with [a link](#nowhere)\n\n"
                    "| a | b |\n| - | - |\n| x | [cell](#missing) |\n"
                )
            },
        )
        assert where(result) == ["a.md:1: #nowhere", "a.md:5: #missing"]

    def test_the_line_of_a_link_is_the_line_it_is_on(self, tmp_path: Path) -> None:
        result = scan_of(
            tmp_path,
            {
                "a.md": "first line\nsecond line\nthird [dead](#gone) line\nfourth line\n"
            },
        )
        assert where(result) == ["a.md:3: #gone"]

    def test_the_line_is_found_whether_the_fragment_is_written_raw_or_encoded(
        self, tmp_path: Path
    ) -> None:
        # each link is on the second line of its paragraph, so the line has to be searched for
        result = scan_of(
            tmp_path,
            {
                "a.md": (
                    "intro line\nwith the [raw](b.md#反馈) link\n\n"
                    "another line\nand the [encoded](b.md#%E8%B6%85%E6%97%B6) one\n"
                ),
                "b.md": "# B\n",
            },
        )
        assert where(result) == ["a.md:2: b.md#反馈", "a.md:5: b.md#超时"]

    def test_lines_are_counted_by_the_breaks_markdown_it_counts_by(
        self, tmp_path: Path
    ) -> None:
        # U+2028 and the form feed end a line for str.splitlines() but not for a Markdown parser
        result = scan_of(
            tmp_path,
            {"a.md": "a\u2028b\x0cc\n\npara one\nand [dead](#gone)\n"},
        )
        assert where(result) == ["a.md:4: #gone"]

    def test_a_table_cell_ends_at_its_pipe_even_inside_a_code_span(
        self, tmp_path: Path
    ) -> None:
        # a row is split at its pipes before the cells are read, so the backtick that opens in the
        # first cell does not reach the link in the second
        result = scan_of(
            tmp_path,
            {"a.md": "| a | b | c |\n| - | - | - |\n| `x | [dead](#nowhere) | y` |\n"},
        )
        assert where(result) == ["a.md:3: #nowhere"]

    def test_a_dead_link_names_what_it_probably_meant(self, tmp_path: Path) -> None:
        result = scan_of(
            tmp_path,
            {
                "a.md": "[x](b.md#installation)\n",
                "b.md": "## Installation guide\n\n## Installing\n\n## Unrelated\n",
            },
        )
        (problem,) = result.problems
        assert "#installation-guide" in problem
        assert "#installing" in problem
        assert "#unrelated" not in problem
