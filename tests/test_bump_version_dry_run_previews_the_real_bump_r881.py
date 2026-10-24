"""R881: ``bump_version.py --dry-run`` previews the real bump; it does not print a list from memory.

``docs/release-checklist.md`` tells whoever releases to run ``bump_version.py X.Y.Z --dry-run``
first ("preview"), then the same command without the flag.  The flag returned before the script
read the version, a file or the changelog, and printed the same seven names whatever it was given:

* ``--dry-run``, ``--dry-run not-a-version`` and ``--dry-run v1.8.13`` answered 0, where the real
  run says "missing version" or "invalid version" and answers 2;
* a file that is missing, or one the script cannot rewrite (no ``placeholder: e.g.`` line in the
  bug template, no package entry in ``uv.lock``), did not show up: the preview said 0 and the real
  run stopped with 1 in the middle of a release;
* the warnings the real run prints (a changelog without the version's dated heading, an empty
  ``[Unreleased]``) never appeared, although that is what the person who previews wants to know;
* the list named every file even when the tree was already at the version, and the line for
  ``CITATION.cff`` was a general sentence about ``date-released``, not what this bump does to it;
* ``--check --dry-run`` ran the preview and silently dropped ``--check``.

The fix is to run the real path up to the point where it would write, then print what it would
write.  Everything the real run decides (version, files, rewrites, warnings, exit codes) is decided
once, in the same code; the pieces pinned here are the ones the flag adds: the list is exactly the
files a real run changes, the CITATION line says what happens to ``version`` and ``date-released``,
nothing is written and no gate is run, and ``--check`` and ``--dry-run`` exclude each other.
"""

from __future__ import annotations

import importlib.util
import re
import shutil
from pathlib import Path
from types import ModuleType

import pytest

REPO = Path(__file__).resolve().parents[1]
CHECKLIST = REPO / "docs" / "release-checklist.md"


def _load_bump_version() -> ModuleType:
    path = REPO / "scripts" / "bump_version.py"
    spec = importlib.util.spec_from_file_location("bump_version_r881", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


bump = _load_bump_version()

#: The files a bump may write, in the order the script lists them.
SYNCED = (
    "pyproject.toml",
    "uv.lock",
    "package.json",
    "package-lock.json",
    "packages/vscode/package.json",
    ".github/ISSUE_TEMPLATE/bug_report.yml",
    "CITATION.cff",
)
RELEASE_FILES = (*SYNCED, "CHANGELOG.md")

NEXT = "99.0.0"
NEXT_HEADING = f'"## [{NEXT}] - YYYY-MM-DD"'

#: What a file holds when the script cannot rewrite it, and the words of the real run's refusal.
BROKEN = {
    "pyproject.toml": "[project]\nname = 'x'\n",
    "uv.lock": "version = 1\n",
    "package.json": "{not json",
    "package-lock.json": "{not json",
    "packages/vscode/package.json": "[]",
    ".github/ISSUE_TEMPLATE/bug_report.yml": "name: Bug\n",
    "CITATION.cff": "title: x\n",
}

MINIMAL_CHANGELOG_WITHOUT_ENTRIES = (
    "# Changelog\n\n## [Unreleased]\n\n## [1.0.0] - 2026-01-01\n\n- Something.\n"
)


# ---------------------------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------------------------


def _make_tree(root: Path, name: str) -> Path:
    """A copy of the real release files, in a directory of its own."""
    tree = root / name
    for relative in RELEASE_FILES:
        target = tree / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPO / relative, target)
    return tree


def _snapshot(tree: Path) -> dict[str, bytes]:
    return {
        relative: (tree / relative).read_bytes()
        for relative in RELEASE_FILES
        if (tree / relative).exists()
    }


def _changed(before: dict[str, bytes], after: dict[str, bytes]) -> list[str]:
    return [name for name in SYNCED if before.get(name) != after.get(name)]


def _current_version(tree: Path) -> str:
    version = bump._extract_pyproject_version(
        (tree / "pyproject.toml").read_text(encoding="utf-8")
    )
    assert version is not None
    return version


def _promote(tree: Path, version: str, date: str) -> None:
    """What the release checklist's A.1 does: the next release gets its own dated heading."""
    changelog = tree / "CHANGELOG.md"
    text = changelog.read_text(encoding="utf-8")
    first_release = re.search(r"^## \[(?!Unreleased)", text, re.MULTILINE)
    assert first_release is not None
    heading = f"## [{version}] - {date}\n\n- Everything above the previous release.\n\n"
    changelog.write_text(
        text[: first_release.start()] + heading + text[first_release.start() :],
        encoding="utf-8",
    )


def _listed(stdout: str) -> list[str]:
    """The file names a ``--dry-run`` printed, in order."""
    return re.findall(r"^- (\S+)", stdout, re.MULTILINE)


def _citation_line(stdout: str) -> str:
    lines = [line for line in stdout.splitlines() if line.startswith("- CITATION.cff")]
    assert len(lines) == 1, stdout
    return lines[0]


class Runner:
    """Runs ``bump_version.main`` in a tree and hands back ``(exit code, stdout, stderr)``."""

    def __init__(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        self._monkeypatch = monkeypatch
        self._capsys = capsys

    def __call__(self, tree: Path, argv: list[str]) -> tuple[int, str, str]:
        self._monkeypatch.setattr(bump, "_repo_root", lambda: tree)
        self._capsys.readouterr()
        try:
            code = bump.main(argv)
        except SystemExit as stop:
            assert isinstance(stop.code, int)
            code = stop.code
        out, err = self._capsys.readouterr()
        return code, out, err


@pytest.fixture
def run(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> Runner:
    return Runner(monkeypatch, capsys)


@pytest.fixture
def pair(tmp_path: Path) -> tuple[Path, Path]:
    """Two identical copies of the release files: one to preview in, one to bump for real."""
    return _make_tree(tmp_path, "preview"), _make_tree(tmp_path, "real")


def _both(
    run: Runner, pair: tuple[Path, Path], argv: list[str]
) -> tuple[tuple[int, str, str], tuple[int, str, str]]:
    preview, real = pair
    return run(preview, [*argv, "--dry-run"]), run(real, argv)


# ---------------------------------------------------------------------------------------------
# It stops where the real bump stops
# ---------------------------------------------------------------------------------------------


class TestItStopsWhereTheRealBumpStops:
    def test_without_a_version_it_asks_for_one(
        self, run: Runner, pair: tuple[Path, Path]
    ) -> None:
        dry, real = _both(run, pair, [])
        assert dry == real
        assert dry[0] == 2
        assert dry[1] == ""
        assert "缺少版本号" in dry[2]

    @pytest.mark.parametrize(
        "version", ["1.8", "v1.8.13", "1.8.13.1", "not-a-version", "1.8.x"]
    )
    def test_a_version_that_is_not_semver_is_refused(
        self, run: Runner, pair: tuple[Path, Path], version: str
    ) -> None:
        dry, real = _both(run, pair, [version])
        assert dry == real
        assert dry[0] == 2
        assert dry[1] == ""
        assert f"版本号格式不合法：{version}" in dry[2]

    def test_from_pyproject_is_for_check_only_here_too(
        self, run: Runner, pair: tuple[Path, Path]
    ) -> None:
        dry, real = _both(run, pair, ["--from-pyproject"])
        assert dry == real
        assert dry[0] == 2
        assert "--from-pyproject 仅用于 --check" in dry[2]

    @pytest.mark.parametrize("relative", SYNCED)
    def test_a_missing_file_stops_it(
        self, run: Runner, pair: tuple[Path, Path], relative: str
    ) -> None:
        for tree in pair:
            (tree / relative).unlink()
        before = _snapshot(pair[0])
        dry, real = _both(run, pair, [NEXT])
        assert dry == real
        assert dry[0] == 1
        assert dry[1] == ""
        assert f"文件不存在：{relative}" in dry[2].replace("\\", "/")
        assert _snapshot(pair[0]) == before

    @pytest.mark.parametrize("relative", SYNCED)
    def test_a_file_it_cannot_rewrite_stops_it(
        self, run: Runner, pair: tuple[Path, Path], relative: str
    ) -> None:
        for tree in pair:
            (tree / relative).write_text(BROKEN[relative], encoding="utf-8")
        before = _snapshot(pair[0])
        dry, real = _both(run, pair, [NEXT])
        assert dry == real
        assert dry[0] == 1
        assert dry[1] == ""
        assert f"更新失败：{relative}" in dry[2].replace("\\", "/")
        assert _snapshot(pair[0]) == before

    def test_a_missing_changelog_is_not_an_error_for_either(
        self, run: Runner, pair: tuple[Path, Path]
    ) -> None:
        for tree in pair:
            (tree / "CHANGELOG.md").unlink()
        dry, real = _both(run, pair, [NEXT])
        assert dry[0] == real[0] == 0
        assert dry[2] == real[2]
        assert _listed(dry[1]) == list(SYNCED)

    def test_check_and_dry_run_exclude_each_other(
        self, run: Runner, tmp_path: Path
    ) -> None:
        tree = _make_tree(tmp_path, "tree")
        before = _snapshot(tree)
        code, out, err = run(tree, ["--check", "--dry-run"])
        assert code == 2
        assert out == ""
        assert "--check" in err and "--dry-run" in err
        assert _snapshot(tree) == before


# ---------------------------------------------------------------------------------------------
# The list is what the real bump changes
# ---------------------------------------------------------------------------------------------


class TestTheListIsWhatTheRealBumpChanges:
    @pytest.mark.parametrize("version", [NEXT, f"{NEXT}-rc.1", f"{NEXT}+build.5"])
    def test_a_new_version_lists_every_file_the_real_bump_rewrites(
        self, run: Runner, pair: tuple[Path, Path], version: str
    ) -> None:
        preview, real = pair
        before = _snapshot(real)
        (code, out, _), (real_code, _, _) = _both(run, pair, [version])
        assert code == real_code == 0
        changed = _changed(before, _snapshot(real))
        assert changed == list(SYNCED)
        assert _listed(out) == changed
        assert (
            out.splitlines()[0]
            == f"将同步版本号到 {version}（dry-run：未写文件），会修改："
        )

    @pytest.mark.parametrize("relative", SYNCED)
    def test_when_one_file_is_behind_only_that_file_is_listed(
        self, run: Runner, pair: tuple[Path, Path], relative: str
    ) -> None:
        for tree in pair:
            assert run(tree, [NEXT])[0] == 0
            shutil.copy2(REPO / relative, tree / relative)
        before = _snapshot(pair[1])
        (code, out, _), (real_code, _, _) = _both(run, pair, [NEXT])
        assert code == real_code == 0
        changed = _changed(before, _snapshot(pair[1]))
        assert changed == [relative]
        assert _listed(out) == [relative]

    def test_when_the_tree_is_at_the_version_it_says_so(
        self, run: Runner, pair: tuple[Path, Path]
    ) -> None:
        for tree in pair:
            assert run(tree, [NEXT])[0] == 0
        before = _snapshot(pair[1])
        (code, out, _), (real_code, real_out, _) = _both(run, pair, [NEXT])
        assert code == real_code == 0
        assert _changed(before, _snapshot(pair[1])) == []
        assert (
            out
            == f"所有目标文件已是 {NEXT}，没有需要修改的文件（dry-run：未写文件）。\n"
        )
        assert _listed(out) == []
        assert real_out == f"已同步版本号到：{NEXT}\n"

    def test_the_version_it_is_already_at_lists_nothing_for_the_real_files(
        self, run: Runner, tmp_path: Path
    ) -> None:
        tree = _make_tree(tmp_path, "tree")
        current = _current_version(tree)
        code, out, _ = run(tree, [current, "--dry-run"])
        assert code == 0
        assert _listed(out) == []
        assert "没有需要修改的文件" in out

    def test_a_date_that_differs_lists_only_the_citation(
        self, run: Runner, pair: tuple[Path, Path]
    ) -> None:
        for tree in pair:
            _promote(tree, NEXT, "2031-01-02")
            assert run(tree, [NEXT])[0] == 0
            changelog = tree / "CHANGELOG.md"
            changelog.write_text(
                changelog.read_text(encoding="utf-8").replace(
                    f"## [{NEXT}] - 2031-01-02", f"## [{NEXT}] - 2031-01-05"
                ),
                encoding="utf-8",
            )
        before = _snapshot(pair[1])
        (code, out, _), (real_code, _, _) = _both(run, pair, [NEXT])
        assert code == real_code == 0
        assert _changed(before, _snapshot(pair[1])) == ["CITATION.cff"]
        assert _listed(out) == ["CITATION.cff"]
        line = _citation_line(out)
        assert "date-released 2031-01-02 → 2031-01-05" in line
        assert "version" not in line

    def test_it_does_not_print_the_old_fixed_list(
        self, run: Runner, tmp_path: Path
    ) -> None:
        tree = _make_tree(tmp_path, "tree")
        for argv in ([NEXT, "--dry-run"], [_current_version(tree), "--dry-run"]):
            out = run(tree, argv)[1]
            assert "将同步版本号的文件" not in out
            assert "手动维护" not in out


# ---------------------------------------------------------------------------------------------
# The line for CITATION.cff says what happens to it
# ---------------------------------------------------------------------------------------------


class TestTheCitationLine:
    def test_with_a_dated_heading_it_names_the_old_and_the_new_date(
        self, run: Runner, tmp_path: Path
    ) -> None:
        tree = _make_tree(tmp_path, "tree")
        old_date = bump._extract_citation_date(
            (tree / "CITATION.cff").read_text(encoding="utf-8")
        )
        assert old_date is not None
        _promote(tree, NEXT, "2031-01-02")
        out = run(tree, [NEXT, "--dry-run"])[1]
        assert _citation_line(out) == (
            f"- CITATION.cff  (version；date-released {old_date} → 2031-01-02)"
        )

    def test_a_heading_with_the_date_it_already_has_says_nothing_about_the_date(
        self, run: Runner, tmp_path: Path
    ) -> None:
        tree = _make_tree(tmp_path, "tree")
        old_date = bump._extract_citation_date(
            (tree / "CITATION.cff").read_text(encoding="utf-8")
        )
        assert old_date is not None
        _promote(tree, NEXT, old_date)
        out = run(tree, [NEXT, "--dry-run"])[1]
        assert _citation_line(out) == "- CITATION.cff  (version)"

    def test_without_a_heading_it_says_the_date_stays_and_which_heading_it_looked_for(
        self, run: Runner, tmp_path: Path
    ) -> None:
        tree = _make_tree(tmp_path, "tree")
        old_date = bump._extract_citation_date(
            (tree / "CITATION.cff").read_text(encoding="utf-8")
        )
        out = run(tree, [NEXT, "--dry-run"])[1]
        assert _citation_line(out) == (
            f"- CITATION.cff  (version；date-released 保持 {old_date} 不变，"
            f"CHANGELOG.md 里没有 {NEXT_HEADING} 标题)"
        )
        assert "→" not in _citation_line(out)

    def test_a_citation_without_a_date_field_says_nothing_about_a_date(
        self, run: Runner, tmp_path: Path
    ) -> None:
        tree = _make_tree(tmp_path, "tree")
        cff = tree / "CITATION.cff"
        cff.write_text(
            re.sub(
                r"^date-released:.*\n", "", cff.read_text("utf-8"), flags=re.MULTILINE
            ),
            encoding="utf-8",
        )
        _promote(tree, NEXT, "2031-01-02")
        out = run(tree, [NEXT, "--dry-run"])[1]
        assert _citation_line(out) == "- CITATION.cff  (version)"

    def test_the_other_lines_carry_no_note(self, run: Runner, tmp_path: Path) -> None:
        tree = _make_tree(tmp_path, "tree")
        out = run(tree, [NEXT, "--dry-run"])[1]
        others = [
            line
            for line in out.splitlines()[1:]
            if not line.startswith("- CITATION.cff")
        ]
        assert others == [f"- {name}" for name in SYNCED[:-1]]


class TestTheHelpersOnSmallInputs:
    def test_nothing_pending_is_one_sentence(self, tmp_path: Path) -> None:
        assert bump._dry_run_lines(tmp_path, "1.2.3", None, []) == [
            "所有目标文件已是 1.2.3，没有需要修改的文件（dry-run：未写文件）。"
        ]

    def test_paths_are_written_relative_to_the_root_with_forward_slashes(
        self, tmp_path: Path
    ) -> None:
        pending = [
            (tmp_path / "pyproject.toml", "x"),
            (tmp_path / "packages" / "vscode" / "package.json", "x"),
            (tmp_path / ".github" / "ISSUE_TEMPLATE" / "bug_report.yml", "x"),
        ]
        assert bump._dry_run_lines(tmp_path, "1.2.3", None, pending) == [
            "将同步版本号到 1.2.3（dry-run：未写文件），会修改：",
            "- pyproject.toml",
            "- packages/vscode/package.json",
            "- .github/ISSUE_TEMPLATE/bug_report.yml",
        ]

    def test_the_order_of_the_pending_writes_is_kept(self, tmp_path: Path) -> None:
        pending = [(tmp_path / name, "x") for name in ("b.txt", "a.txt", "c.txt")]
        assert bump._dry_run_lines(tmp_path, "1.2.3", None, pending)[1:] == [
            "- b.txt",
            "- a.txt",
            "- c.txt",
        ]

    @pytest.mark.parametrize(
        ("old", "new", "release_date", "note"),
        [
            (
                'version: "1.0.0"\ndate-released: "2026-01-01"\n',
                'version: "2.0.0"\ndate-released: "2026-02-02"\n',
                "2026-02-02",
                "  (version；date-released 2026-01-01 → 2026-02-02)",
            ),
            (
                'version: "1.0.0"\ndate-released: "2026-01-01"\n',
                'version: "2.0.0"\ndate-released: "2026-01-01"\n',
                None,
                '  (version；date-released 保持 2026-01-01 不变，CHANGELOG.md 里没有 "## [2.0.0] - YYYY-MM-DD" 标题)',
            ),
            (
                'version: "1.0.0"\ndate-released: "2026-01-01"\n',
                'version: "2.0.0"\ndate-released: "2026-01-01"\n',
                "2026-01-01",
                "  (version)",
            ),
            (
                'version: "2.0.0"\ndate-released: "2026-01-01"\n',
                'version: "2.0.0"\ndate-released: "2026-03-03"\n',
                "2026-03-03",
                "  (date-released 2026-01-01 → 2026-03-03)",
            ),
            (
                'version: "1.0.0"\n',
                'version: "2.0.0"\n',
                "2026-03-03",
                "  (version)",
            ),
            (
                'version: "1.0.0"\n',
                'version: "2.0.0"\n',
                None,
                "  (version)",
            ),
        ],
    )
    def test_the_citation_note(
        self,
        tmp_path: Path,
        old: str,
        new: str,
        release_date: str | None,
        note: str,
    ) -> None:
        (tmp_path / "CITATION.cff").write_text(old, encoding="utf-8")
        assert bump._citation_dry_run_note(tmp_path, new, "2.0.0", release_date) == note

    def test_a_citation_that_cannot_be_read_has_no_note(self, tmp_path: Path) -> None:
        assert bump._citation_dry_run_note(tmp_path, "x", "2.0.0", None) == ""


# ---------------------------------------------------------------------------------------------
# The warnings are the real run's warnings
# ---------------------------------------------------------------------------------------------


class TestTheWarningsAreTheRealRunsWarnings:
    def test_a_changelog_without_the_heading_warns_in_the_preview(
        self, run: Runner, pair: tuple[Path, Path]
    ) -> None:
        dry, real = _both(run, pair, [NEXT])
        assert "WARNING (R874)" in dry[2]
        assert NEXT_HEADING in dry[2]
        assert dry[2] == real[2]

    def test_a_changelog_with_the_heading_does_not_warn(
        self, run: Runner, pair: tuple[Path, Path]
    ) -> None:
        for tree in pair:
            _promote(tree, NEXT, "2031-01-02")
        dry, real = _both(run, pair, [NEXT])
        assert "R874" not in dry[2]
        assert dry[2] == real[2]

    @pytest.mark.parametrize("flag", [[], ["--no-warn-empty-unreleased"]])
    def test_an_empty_unreleased_section_warns_unless_told_not_to(
        self, run: Runner, pair: tuple[Path, Path], flag: list[str]
    ) -> None:
        for tree in pair:
            (tree / "CHANGELOG.md").write_text(
                MINIMAL_CHANGELOG_WITHOUT_ENTRIES, encoding="utf-8"
            )
        dry, real = _both(run, pair, [NEXT, *flag])
        assert dry[2] == real[2]
        assert ("WARNING (R183)" in dry[2]) is (not flag)
        assert "WARNING (R874)" in dry[2]


# ---------------------------------------------------------------------------------------------
# It writes nothing and runs nothing
# ---------------------------------------------------------------------------------------------


class TestItWritesNothingAndRunsNothing:
    @pytest.mark.parametrize(
        "argv",
        [
            [NEXT],
            [f"{NEXT}-rc.1"],
            [NEXT, "--no-warn-empty-unreleased"],
            [NEXT, "--ci-gate"],
            [NEXT, "--ci-gate", "--with-vscode"],
        ],
    )
    def test_no_file_changes(
        self, run: Runner, tmp_path: Path, argv: list[str]
    ) -> None:
        tree = _make_tree(tmp_path, "tree")
        before = _snapshot(tree)
        code, _, _ = run(tree, [*argv, "--dry-run"])
        assert code == 0
        assert _snapshot(tree) == before

    def test_the_writer_is_never_called(
        self,
        run: Runner,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        def refuse(path: Path, content: str) -> None:
            raise AssertionError(f"wrote {path}")

        monkeypatch.setattr(bump, "_write_text_atomic", refuse)
        tree = _make_tree(tmp_path, "tree")
        assert run(tree, [NEXT, "--dry-run"])[0] == 0
        with pytest.raises(AssertionError, match="wrote"):
            run(tree, [NEXT])

    def test_the_gate_is_not_run(
        self,
        run: Runner,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        calls: list[bool] = []
        monkeypatch.setattr(
            bump,
            "_maybe_run_ci_gate",
            lambda *, include_vscode: calls.append(include_vscode),
        )
        tree = _make_tree(tmp_path, "tree")
        assert run(tree, [NEXT, "--dry-run", "--ci-gate", "--with-vscode"])[0] == 0
        assert calls == []
        other = _make_tree(tmp_path, "other")
        assert run(other, [NEXT, "--ci-gate", "--with-vscode"])[0] == 0
        assert calls == [True]


# ---------------------------------------------------------------------------------------------
# What the people who release are told
# ---------------------------------------------------------------------------------------------


class TestTheChecklistDescribesThePreview:
    def test_the_checklist_says_what_the_preview_does(self) -> None:
        lines = [
            line
            for line in CHECKLIST.read_text(encoding="utf-8").splitlines()
            if "bump_version.py X.Y.Z --dry-run" in line
        ]
        assert len(lines) == 1, lines
        assert "preview" in lines[0]
        assert "same checks" in lines[0]
        assert "writes nothing" in lines[0]
