"""R721 · skill / slash-command catalogue behind the feedback box's ``/`` picker.

``ai_intervention_agent.skill_catalog`` turns ``[feedback] skill_dirs`` into the
rows the picker shows. These tests pin the parts that are easy to get subtly
wrong on real machines: the hand-written front-matter reader (no PyYAML
dependency), the choice of the word inserted after ``/`` (63 of 229 skills in
one real library have non-ASCII display names), directory discovery (hidden
``.system`` folders, nested skills, symlink loops, dedupe priority) and the
bounds that keep a hostile directory from stalling the Web UI.
"""

from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Any

import pytest

from ai_intervention_agent import dir_settings as ds
from ai_intervention_agent import skill_catalog as sc
from ai_intervention_agent.shared_types import FeedbackSectionConfig

POSIX_ONLY = pytest.mark.skipif(os.name == "nt", reason="POSIX file semantics")


@pytest.fixture(autouse=True)
def _fresh_cache():
    sc.invalidate_cache()
    yield
    sc.invalidate_cache()


def write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def skill(root: Path, folder: str, front: str, body: str = "Body\n") -> Path:
    return write(root / folder / "SKILL.md", f"---\n{front}\n---\n{body}")


def tokens(catalog: sc.Catalog) -> list[str]:
    return [entry["insert"] for entry in catalog["skills"]]


# --------------------------------------------------------------------------
# front matter
# --------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("document", "expected"),
    [
        ("---\nname: plain\n---\n", {"name": "plain"}),
        ('---\nname: "quoted: yes"\n---\n', {"name": "quoted: yes"}),
        ("---\nname: 'it''s'\n---\n", {"name": "it's"}),
        ('---\nname: "a \\"b\\" \\u00e9 \\x41"\n---\n', {"name": 'a "b" é A'}),
        ("---\nname: x # comment\n---\n", {"name": "x"}),
        ("---\nname: C#\n---\n", {"name": "C#"}),
        ('---\nname: "x # kept"\n---\n', {"name": "x # kept"}),
        ("---\nurl: http://a.b/c\n---\n", {"url": "http://a.b/c"}),
        (
            "---\ndescription: >\n  folded\n  text\n\n  more\n---\n",
            {"description": "folded text more"},
        ),
        (
            "---\ndescription: |-\n  literal\n  text\n---\n",
            {"description": "literal text"},
        ),
        (
            "---\ndescription:\n  indented plain\n  scalar\n---\n",
            {"description": "indented plain scalar"},
        ),
        ("---\ndescription: first\n  second\n---\n", {"description": "first second"}),
        ('---\ndescription: "multi\n  line"\n---\n', {"description": "multi line"}),
        ("---\nname: a\nname: b\n---\n", {"name": "a"}),
        ("\ufeff---\nname: bom\n---\n", {"name": "bom"}),
        ("---\r\nname: crlf\r\n---\r\n", {"name": "crlf"}),
        ("---\nname: dots\n...\nbody\n", {"name": "dots"}),
        (
            "---\nname: unterminated\ndescription: still read",
            {"name": "unterminated", "description": "still read"},
        ),
        ("---  \nname: padded fence\n---\n", {"name": "padded fence"}),
    ],
)
def test_frontmatter_scalars(document: str, expected: dict[str, str]):
    assert sc.parse_frontmatter(document)[0] == expected


def test_frontmatter_nested_structures_never_leak_into_top_level():
    meta, _ = sc.parse_frontmatter(
        "---\n"
        "name: outer\n"
        "metadata:\n"
        '  user-invocable: "false"\n'
        "  name: inner\n"
        "tags:\n"
        "  - a\n"
        "  - b\n"
        "flow: [a, b]\n"
        "map: {a: 1}\n"
        "description: kept\n"
        "---\n"
    )
    assert meta == {"name": "outer", "description": "kept"}


def test_frontmatter_without_fence_is_all_body():
    text = "# Title\n\nname: not front matter\n"
    assert sc.parse_frontmatter(text) == ({}, text)
    assert sc.parse_frontmatter("") == ({}, "")
    assert sc.parse_frontmatter("--- not a fence\nname: x\n---\n")[0] == {}


def test_frontmatter_body_follows_the_closing_fence():
    meta, body = sc.parse_frontmatter("---\nname: x\n---\nline one\n---\nline two\n")
    assert meta == {"name": "x"}
    assert body == "line one\n---\nline two\n"


def test_frontmatter_real_world_localised_skill():
    meta, _ = sc.parse_frontmatter(
        "---\n"
        'name: "CTF•Web 漏洞"\n'
        'description: "用于 XSS、SQL 注入、SSRF 等 Web 类 CTF 题;触发名:ctf-web"\n'
        "metadata:\n"
        '  user-invocable: "false"\n'
        "---\n"
    )
    assert meta["name"] == "CTF•Web 漏洞"
    assert meta["description"].endswith("触发名:ctf-web")
    assert "user-invocable" not in meta


def test_frontmatter_hostile_input_stays_linear():
    hostile = (
        "---\n"
        + "a: "
        + "x" * 200_000
        + "\n"
        + ("  " + "y" * 50 + "\n") * 5_000
        + "---\n"
    )
    meta, _ = sc.parse_frontmatter(hostile)
    assert meta["a"].startswith("xxx")
    assert sc.parse_frontmatter('---\nname: "' + "\\" * 100_001)[0]["name"] != ""


# --------------------------------------------------------------------------
# the word inserted after "/"
# --------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("name", "description", "fallback", "expected"),
    [
        ("ctf-web", "", "folder", "ctf-web"),
        ("CTF•Web 漏洞", "用于 Web 题;触发名:ctf-web", "CTF•Web 漏洞", "ctf-web"),
        ("CTF•Web 漏洞", "用于 Web 题;触发名：ctf-web", "x", "ctf-web"),
        ("Display Name", "Trigger name: `my-skill`", "folder", "my-skill"),
        ("Display Name", "trigger name = Alpha_1.2", "folder", "Alpha_1.2"),
        ("MinerU Document Extractor", "", "mineru", "mineru"),
        ("CTF•AI/ML 攻防", "", "ML 攻防", "CTF•AI-ML-攻防"),
        ("A  B/C\\D", "", "also bad", "A-B-C-D"),
        ("  ", "", "folder", "folder"),
        ("", "", "", ""),
        ("x\u0000y\u0007z w", "", "bad name", "xyz-w"),
        ("short", "Trigger: when the user asks", "folder", "short"),
        ("n", "trigger name:", "folder", "n"),
    ],
)
def test_slash_token(name: str, description: str, fallback: str, expected: str):
    assert sc.slash_token(name, description, fallback) == expected


def test_slash_token_is_bounded():
    token = sc.slash_token("a b " * 100, "", "")
    assert 0 < len(token) <= sc.MAX_NAME_LENGTH
    assert not token.startswith("-") and not token.endswith("-")
    assert sc.slash_token("é" * 200, "", "") == "é" * sc.MAX_NAME_LENGTH


# --------------------------------------------------------------------------
# rows
# --------------------------------------------------------------------------
def test_build_entry_shapes_a_skill():
    entry = sc.build_entry(
        '---\nname: review\ndescription: "Review a diff"\n---\nbody\n',
        "review-dir",
        "skill",
        "~/.cursor/skills",
    )
    assert entry == {
        "name": "review",
        "insert": "review",
        "description": "Review a diff",
        "kind": "skill",
        "source": "~/.cursor/skills",
    }


def test_build_entry_hides_invalid_or_non_invocable_skills():
    assert sc.build_entry("# no front matter\n", "x", "skill", "s") is None
    assert (
        sc.build_entry("---\nuser-invocable: false\nname: x\n---\n", "x", "skill", "s")
        is None
    )
    assert (
        sc.build_entry(
            '---\nuser-invocable: "False"\nname: x\n---\n', "x", "skill", "s"
        )
        is None
    )
    assert sc.build_entry(
        "---\nname: x\nuser-invocable: true\n---\n", "x", "skill", "s"
    )
    assert sc.build_entry(
        "---\nname: x\ndisable-model-invocation: true\n---\n", "x", "skill", "s"
    )
    assert sc.build_entry(
        "---\nname: x\nmetadata:\n  user-invocable: false\n---\n", "x", "skill", "s"
    )


def test_build_entry_description_fallbacks_and_clipping():
    when_to_use = sc.build_entry(
        "---\nname: x\nwhen_to_use: When asked\n---\n", "x", "skill", "s"
    )
    assert when_to_use is not None
    assert when_to_use["description"] == "When asked"
    command = sc.build_entry("# Heading line\n\nMore text\n", "deploy", "command", "s")
    assert command is not None
    assert command["description"] == "Heading line"
    assert command["insert"] == "deploy" and command["kind"] == "command"
    long = sc.build_entry(
        "---\nname: x\ndescription: " + "word " * 200 + "\n---\n", "x", "skill", "s"
    )
    assert long is not None
    assert len(long["description"]) == sc.MAX_DESCRIPTION_LENGTH
    assert long["description"].endswith("…")
    long_name = sc.build_entry("---\nname: " + "n" * 200 + "\n---\n", "x", "skill", "s")
    assert long_name is not None
    assert len(long_name["name"]) == sc.MAX_NAME_LENGTH and long_name["name"].endswith(
        "…"
    )
    assert "…" not in long_name["insert"]


# --------------------------------------------------------------------------
# setting normalisation
# --------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, ["auto"]),
        ("~/skills", ["~/skills"]),
        (["auto", " ~/a ", ""], ["auto", "~/a"]),
        ([], []),
        ([1, None, {}], ["auto"]),
        ([" ", ""], ["auto"]),
        (5, ["auto"]),
        ({"a": 1}, ["auto"]),
        (("a", "b"), ["a", "b"]),
        (["a\x00b", "ok"], ["ok"]),
        (["x" * (ds.MAX_PATH_LENGTH + 1), "ok"], ["ok"]),
    ],
)
def test_normalize_skill_dirs(value: Any, expected: list[str]):
    assert sc.normalize_skill_dirs(value) == expected


def test_normalize_skill_dirs_caps_the_list():
    result = sc.normalize_skill_dirs([f"d{i}" for i in range(100)])
    assert len(result) == ds.MAX_CONFIGURED_DIRS
    assert result[0] == "d0"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ({}, ["auto"]),
        ({"skill_dirs": []}, []),
        ({"skill_dirs": "~/x"}, ["~/x"]),
        ({"skill_dirs": [3]}, ["auto"]),
        ({"skill_dirs": None}, ["auto"]),
        ({"skill_dirs": ["auto", "~/team"]}, ["auto", "~/team"]),
    ],
)
def test_config_model_uses_the_same_normaliser(
    raw: dict[str, Any], expected: list[str]
):
    assert FeedbackSectionConfig.model_validate(raw).skill_dirs == expected


def test_config_model_default_is_not_shared_between_instances():
    first, second = FeedbackSectionConfig(), FeedbackSectionConfig()
    first.skill_dirs.append("mutated")
    assert second.skill_dirs == ["auto"]
    assert FeedbackSectionConfig().skill_dirs == ["auto"]


# --------------------------------------------------------------------------
# directory resolution
# --------------------------------------------------------------------------
def make_world(tmp_path: Path) -> tuple[Path, Path]:
    home = tmp_path / "home"
    project = tmp_path / "project"
    home.mkdir()
    project.mkdir()
    return home, project


def test_auto_expands_project_before_home_in_a_fixed_order(tmp_path: Path):
    home, project = make_world(tmp_path)
    for relative in (
        ".cursor/skills",
        ".agents/skills",
        ".claude/commands",
    ):
        (project / relative).mkdir(parents=True)
    for relative in (
        ".cursor/skills",
        ".cursor/skills-cursor",
        ".claude/skills",
        ".codex/skills",
        ".codex/prompts",
    ):
        (home / relative).mkdir(parents=True)

    roots = sc.resolve_skill_roots(["auto"], home=home, cwd=project)

    assert [(root.label, root.kind) for root in roots] == [
        ("./.cursor/skills", "skill"),
        ("./.agents/skills", "skill"),
        ("./.claude/commands", "command"),
        ("~/.cursor/skills", "skill"),
        ("~/.cursor/skills-cursor", "skill"),
        ("~/.claude/skills", "skill"),
        ("~/.codex/skills", "skill"),
        ("~/.codex/prompts", "command"),
    ]


def test_missing_directories_and_files_are_ignored(tmp_path: Path):
    home, project = make_world(tmp_path)
    (project / "afile").write_text("x", encoding="utf-8")
    roots = sc.resolve_skill_roots(
        ["auto", "afile", "nope", "~/missing"], home=home, cwd=project
    )
    assert roots == []


def test_cwd_equal_to_home_does_not_duplicate_and_prefers_the_home_label(
    tmp_path: Path,
):
    home, _ = make_world(tmp_path)
    (home / ".cursor/skills").mkdir(parents=True)
    roots = sc.resolve_skill_roots(["auto"], home=home, cwd=home)
    assert [root.label for root in roots] == ["~/.cursor/skills"]


def test_explicit_entries_expand_home_and_relative_paths(tmp_path: Path):
    home, project = make_world(tmp_path)
    (home / "mine").mkdir()
    (project / "team" / "skills").mkdir(parents=True)
    (tmp_path / "elsewhere" / "deep" / "skills").mkdir(parents=True)

    roots = sc.resolve_skill_roots(
        ["~/mine", "team/skills", str(tmp_path / "elsewhere" / "deep" / "skills")],
        home=home,
        cwd=project,
    )

    assert [root.label for root in roots] == ["~/mine", "./team/skills", "deep/skills"]


def test_roles_follow_the_directory_name(tmp_path: Path):
    home, project = make_world(tmp_path)
    for name in ("commands", "Prompts", "skills", "anything"):
        (project / name).mkdir()
    roots = sc.resolve_skill_roots(
        ["commands", "Prompts", "skills", "anything"], home=home, cwd=project
    )
    assert [root.kind for root in roots] == ["command", "command", "skill", "skill"]


def test_auto_token_is_case_insensitive_and_expanded_once(tmp_path: Path):
    home, project = make_world(tmp_path)
    (home / ".cursor/skills").mkdir(parents=True)
    roots = sc.resolve_skill_roots(["AUTO", "auto", " Auto "], home=home, cwd=project)
    assert len(roots) == 1


def test_same_directory_through_different_spellings_is_one_root(tmp_path: Path):
    home, project = make_world(tmp_path)
    target = home / ".cursor/skills"
    target.mkdir(parents=True)
    roots = sc.resolve_skill_roots(
        [
            "auto",
            str(target),
            str(target) + "/",
            str(home / ".cursor" / ".." / ".cursor/skills"),
        ],
        home=home,
        cwd=project,
    )
    assert len(roots) == 1


def test_empty_list_disables_everything(tmp_path: Path):
    home, project = make_world(tmp_path)
    (home / ".cursor/skills").mkdir(parents=True)
    assert sc.resolve_skill_roots([], home=home, cwd=project) == []
    assert sc.get_catalog([], home=home, cwd=project) == {
        "skills": [],
        "truncated": False,
    }


# --------------------------------------------------------------------------
# scanning
# --------------------------------------------------------------------------
def test_scan_finds_nested_and_hidden_system_skills_but_not_junk(tmp_path: Path):
    root = tmp_path / "skills"
    skill(root, "alpha", "name: alpha\ndescription: A")
    skill(root, "group/inner", "name: inner\ndescription: I")
    skill(root, ".system/imagegen", "name: imagegen\ndescription: G")
    skill(root, "node_modules/pkg", "name: junk-a\ndescription: x")
    skill(root, ".git/hooks", "name: junk-b\ndescription: x")
    skill(root, "alpha/references/deep", "name: reference-skill\ndescription: R")
    skill(root, "l1/l2/l3/l4/l5/l6", "name: too-deep\ndescription: x")
    write(root / "README.md", "# not a skill")
    write(root / "loose" / "notes.md", "# nothing")

    catalog = sc.scan_roots([sc.SkillRoot(root, "skill", "~/skills")])

    assert tokens(catalog) == ["alpha", "imagegen", "inner", "reference-skill"]
    assert catalog["truncated"] is False


def test_scan_skips_skills_without_front_matter_and_hidden_ones(tmp_path: Path):
    root = tmp_path / "skills"
    write(root / "bare" / "SKILL.md", "# SKILL: no front matter\n")
    skill(root, "hidden", "name: hidden\nuser-invocable: false")
    skill(root, "shown", "name: shown")
    catalog = sc.scan_roots([sc.SkillRoot(root, "skill", "s")])
    assert tokens(catalog) == ["shown"]


def test_scan_command_directory_lists_top_level_markdown_only(tmp_path: Path):
    root = tmp_path / "commands"
    write(root / "deploy.md", "---\ndescription: Ship it\n---\nbody\n")
    write(root / "plain.md", "# Plain command\nbody\n")
    write(root / "UPPER.MD", "# Upper\n")
    write(root / ".hidden.md", "# Hidden\n")
    write(root / "notes.txt", "ignored")
    write(root / "nested" / "inner.md", "# Nested\n")
    (root / "folder.md").mkdir()

    catalog = sc.scan_roots([sc.SkillRoot(root, "command", "./commands")])

    assert tokens(catalog) == ["deploy", "plain", "UPPER"]
    by_token = {entry["insert"]: entry for entry in catalog["skills"]}
    assert by_token["deploy"]["description"] == "Ship it"
    assert by_token["plain"]["description"] == "Plain command"
    assert all(entry["kind"] == "command" for entry in catalog["skills"])


def test_first_root_wins_on_duplicate_tokens_case_insensitively(tmp_path: Path):
    first, second = tmp_path / "a", tmp_path / "b"
    skill(first, "x", "name: Review\ndescription: from first")
    skill(second, "x", "name: review\ndescription: from second")
    skill(second, "y", "name: only-second\ndescription: kept")

    catalog = sc.scan_roots(
        [sc.SkillRoot(first, "skill", "first"), sc.SkillRoot(second, "skill", "second")]
    )

    by_token = {entry["insert"].lower(): entry for entry in catalog["skills"]}
    assert by_token["review"]["description"] == "from first"
    assert by_token["review"]["source"] == "first"
    assert by_token["only-second"]["source"] == "second"
    assert len(catalog["skills"]) == 2


def test_results_are_sorted_case_insensitively_by_token(tmp_path: Path):
    root = tmp_path / "skills"
    for name in ("Zeta", "alpha", "Beta", "gamma"):
        skill(root, name.lower(), f"name: {name}")
    catalog = sc.scan_roots([sc.SkillRoot(root, "skill", "s")])
    assert tokens(catalog) == ["alpha", "Beta", "gamma", "Zeta"]


def test_entry_limit_marks_truncated_only_when_something_was_dropped(tmp_path: Path):
    root = tmp_path / "skills"
    for index in range(5):
        skill(root, f"s{index}", f"name: s{index}")
    roots = [sc.SkillRoot(root, "skill", "s")]
    exact = sc.scan_roots(roots, limit=5)
    assert len(exact["skills"]) == 5 and exact["truncated"] is False
    cut = sc.scan_roots(roots, limit=3)
    assert len(cut["skills"]) == 3 and cut["truncated"] is True


def test_time_budget_stops_the_scan(tmp_path: Path):
    root = tmp_path / "skills"
    for index in range(30):
        skill(root, f"s{index:02d}", f"name: s{index:02d}")
    ticks = iter(range(10_000))
    catalog = sc.scan_roots(
        [sc.SkillRoot(root, "skill", "s")],
        budget=5,
        clock=lambda: float(next(ticks)),
    )
    assert catalog["truncated"] is True
    assert 0 < len(catalog["skills"]) < 30


@POSIX_ONLY
def test_symlink_loops_and_symlinked_skill_folders(tmp_path: Path):
    root = tmp_path / "skills"
    skill(root, "real", "name: real")
    target = tmp_path / "elsewhere" / "linked-skill"
    skill(target.parent, "linked-skill", "name: linked")
    (root / "linked").symlink_to(target, target_is_directory=True)
    (root / "real" / "loop").symlink_to(root, target_is_directory=True)
    (root / "dangling").symlink_to(tmp_path / "does-not-exist")

    catalog = sc.scan_roots([sc.SkillRoot(root, "skill", "s")])

    assert tokens(catalog) == ["linked", "real"]


@POSIX_ONLY
def test_unreadable_and_non_regular_files_are_skipped_without_blocking(tmp_path: Path):
    if os.geteuid() == 0:
        pytest.skip("root can read mode-000 files")
    root = tmp_path / "skills"
    skill(root, "ok", "name: ok")
    locked = skill(root, "locked", "name: locked")
    os.chmod(locked, 0)
    fifo_dir = root / "fifo"
    fifo_dir.mkdir()
    os.mkfifo(fifo_dir / "SKILL.md")
    try:
        catalog = sc.scan_roots([sc.SkillRoot(root, "skill", "s")])
    finally:
        os.chmod(locked, 0o644)
    assert tokens(catalog) == ["ok"]


def test_invalid_utf8_and_oversized_front_matter(tmp_path: Path):
    root = tmp_path / "skills"
    folder = root / "bytes"
    folder.mkdir(parents=True)
    (folder / "SKILL.md").write_bytes(
        b"---\nname: bytes\ndescription: caf\xe9 ok\n---\n" + b"\xff" * 100
    )
    big = root / "big"
    big.mkdir()
    (big / "SKILL.md").write_bytes(
        b"---\nname: big\ndescription: early\n" + b"x: " + b"y" * 100_000 + b"\n---\n"
    )
    catalog = sc.scan_roots([sc.SkillRoot(root, "skill", "s")])
    by_token = {entry["insert"]: entry for entry in catalog["skills"]}
    assert "\ufffd" in by_token["bytes"]["description"]
    assert by_token["big"]["description"] == "early"


def test_scan_never_returns_paths_or_file_bodies(tmp_path: Path):
    root = tmp_path / "skills"
    skill(root, "secret", "name: secret\ndescription: public text", "TOP-SECRET-BODY\n")
    catalog = sc.scan_roots([sc.SkillRoot(root, "skill", "~/skills")])
    blob = repr(catalog)
    assert "TOP-SECRET-BODY" not in blob
    assert str(tmp_path) not in blob
    assert set(catalog["skills"][0]) == {
        "name",
        "insert",
        "description",
        "kind",
        "source",
    }


def test_entry_cap_applies_across_roots_before_sorting(tmp_path: Path):
    first, second = tmp_path / "a", tmp_path / "b"
    for index in range(3):
        skill(first, f"a{index}", f"name: a{index}")
        skill(second, f"b{index}", f"name: b{index}")
    catalog = sc.scan_roots(
        [sc.SkillRoot(first, "skill", "a"), sc.SkillRoot(second, "skill", "b")], limit=4
    )
    assert catalog["truncated"] is True
    assert tokens(catalog) == ["a0", "a1", "a2", "b0"]


# --------------------------------------------------------------------------
# cache
# --------------------------------------------------------------------------
def test_catalog_is_cached_until_ttl_and_rebuilt_when_dirs_change(tmp_path: Path):
    home, project = make_world(tmp_path)
    root = home / ".cursor/skills"
    skill(root, "one", "name: one")
    now = [100.0]

    def clock() -> float:
        return now[0]

    first = sc.get_catalog(["auto"], home=home, cwd=project, clock=clock)
    skill(root, "two", "name: two")
    assert sc.get_catalog(["auto"], home=home, cwd=project, clock=clock) is first
    assert tokens(first) == ["one"]

    now[0] += sc.CACHE_TTL_SECONDS + 1
    refreshed = sc.get_catalog(["auto"], home=home, cwd=project, clock=clock)
    assert tokens(refreshed) == ["one", "two"]

    other = home / "other"
    skill(other, "three", "name: three")
    switched = sc.get_catalog([str(other)], home=home, cwd=project, clock=clock)
    assert tokens(switched) == ["three"]

    sc.invalidate_cache()
    skill(root, "four", "name: four")
    assert "four" in tokens(
        sc.get_catalog(["auto"], home=home, cwd=project, clock=clock)
    )


def test_clock_going_backwards_forces_a_rescan(tmp_path: Path):
    home, project = make_world(tmp_path)
    skill(home / ".cursor/skills", "one", "name: one")
    now = [500.0]
    first = sc.get_catalog(["auto"], home=home, cwd=project, clock=lambda: now[0])
    now[0] = 10.0
    second = sc.get_catalog(["auto"], home=home, cwd=project, clock=lambda: now[0])
    assert first is not second


def test_scan_failure_degrades_to_an_empty_catalog(tmp_path: Path, monkeypatch):
    home, project = make_world(tmp_path)
    skill(home / ".cursor/skills", "one", "name: one")

    def boom(*_args: Any, **_kwargs: Any):
        raise RuntimeError("disk on fire")

    monkeypatch.setattr(sc, "scan_roots", boom)
    assert sc.get_catalog(["auto"], home=home, cwd=project) == {
        "skills": [],
        "truncated": False,
    }


def test_concurrent_requests_scan_once(tmp_path: Path, monkeypatch):
    home, project = make_world(tmp_path)
    skill(home / ".cursor/skills", "one", "name: one")
    calls: list[int] = []
    real = sc.scan_roots

    def counting(*args: Any, **kwargs: Any):
        calls.append(1)
        return real(*args, **kwargs)

    monkeypatch.setattr(sc, "scan_roots", counting)
    results: list[sc.Catalog] = []

    def worker():
        results.append(sc.get_catalog(["auto"], home=home, cwd=project))

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(calls) == 1
    assert len(results) == 8 and all(result is results[0] for result in results)


def test_real_defaults_path_does_not_raise_without_injection():
    catalog = sc.get_catalog(["auto"])
    assert set(catalog) == {"skills", "truncated"}
