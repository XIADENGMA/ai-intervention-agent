"""R726 · local images in a prompt (``ai_intervention_agent.local_images``).

An agent shows a screenshot or a chart by writing a Markdown image whose
destination is a path on its own machine. The MCP process reads the file and
ships the bytes with the task, so what may be read is the security-relevant
part: only inside the allowed folders, never through ``..`` or a symlink that
leads out, only real image files (extension *and* leading bytes, no SVG), only
within the size and count limits, and never by a UNC / remote ``file:`` host.
The text scanner must find exactly the images a Markdown renderer would draw
(not those in code), and must stay linear on hostile input.
"""

from __future__ import annotations

import base64
import os
import random
import stat
import tempfile
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from ai_intervention_agent import local_images as li

POSIX_ONLY = pytest.mark.skipif(os.name == "nt", reason="POSIX file semantics")

PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000d4944415478da63f8cfc0f01f0005000201a1b0d1d40000000049454e44ae426082"
)
JPEG = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
GIF = b"GIF89a\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00\xff\xff\xff!\xf9\x04\x01"
WEBP = b"RIFF\x1a\x00\x00\x00WEBPVP8 \x0e\x00\x00\x000\x01\x00\x9d\x01*\x01\x00\x01\x00"
BMP = (
    b"BM"
    + (58).to_bytes(4, "little")
    + b"\x00" * 4
    + (54).to_bytes(4, "little")
    + (40).to_bytes(4, "little")
    + b"\x00" * 40
)
AVIF = b"\x00\x00\x00\x1cftypavif\x00\x00\x00\x00avifmif1miaf"

TASK = "proj-1234"


def make_root(base: Path, name: str = "root") -> Path:
    root = base / name
    root.mkdir()
    return root.resolve()


def only(root: Path) -> list[Path]:
    """Allowed folders consisting of ``root`` alone (no temp dir, no cwd)."""
    return li.resolve_allowed_dirs([str(root)])


def run(prompt: str, roots: list[Path]) -> li.PreparedPrompt:
    return li.prepare_prompt_images(prompt, TASK, roots)


def url(index: int) -> str:
    return li.image_url(TASK, index)


# --------------------------------------------------------------------------
# content sniffing
# --------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("data", "mime"),
    [
        (PNG, "image/png"),
        (JPEG, "image/jpeg"),
        (GIF, "image/gif"),
        (b"GIF87a" + b"\x00" * 10, "image/gif"),
        (WEBP, "image/webp"),
        (BMP, "image/bmp"),
        (AVIF, "image/avif"),
        (b"\x00\x00\x00\x1cftypavis" + b"\x00" * 8, "image/avif"),
    ],
)
def test_sniff_recognises_the_supported_formats(data: bytes, mime: str):
    assert li.sniff_image_mime(data[:32]) == mime


@pytest.mark.parametrize(
    "data",
    [
        b"",
        b"<svg xmlns='http://www.w3.org/2000/svg'></svg>",
        b"<!doctype html><html></html>",
        b"#!/bin/sh\necho hi\n",
        b"BM is the start of a sentence, not a bitmap file at all.",
        b"RIFF\x00\x00\x00\x00WAVEfmt ",
        b"\x00\x00\x00\x1cftypheic" + b"\x00" * 8,
        b"\x89PNG",
        b"GIF9",
        b"%PDF-1.7",
    ],
)
def test_sniff_rejects_everything_else(data: bytes):
    assert li.sniff_image_mime(data) is None


def test_image_url_quotes_the_task_id():
    assert li.image_url("a b/c?d#e", 3) == "/api/tasks/a%20b%2Fc%3Fd%23e/images/3"
    assert li.image_url("项目-1", 0) == "/api/tasks/%E9%A1%B9%E7%9B%AE-1/images/0"


# --------------------------------------------------------------------------
# the setting
# --------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, ["auto"]),
        ([], []),
        ("~/pics", ["~/pics"]),
        (["auto", " ~/a ", ""], ["auto", "~/a"]),
        ([1, None], ["auto"]),
        (7, ["auto"]),
    ],
)
def test_normalize_image_dirs(value, expected):
    assert li.normalize_image_dirs(value) == expected


def test_empty_setting_allows_nothing(tmp_path: Path):
    assert li.resolve_allowed_dirs([], [tmp_path]) == []


def test_auto_means_client_roots_plus_the_temp_dir(tmp_path: Path):
    workspace = make_root(tmp_path, "workspace")
    roots = li.resolve_allowed_dirs(["auto"], [workspace])
    assert workspace in roots
    import tempfile

    assert Path(os.path.realpath(tempfile.gettempdir())) in roots


def test_auto_expands_only_once(tmp_path: Path):
    workspace = make_root(tmp_path, "workspace")
    once = li.resolve_allowed_dirs(["auto"], [workspace])
    twice = li.resolve_allowed_dirs(["auto", "AUTO"], [workspace])
    assert once == twice


def test_auto_falls_back_to_the_working_directory_without_client_roots(
    tmp_path: Path,
):
    workspace = make_root(tmp_path, "workspace")
    assert workspace in li.resolve_allowed_dirs(["auto"], [], cwd=workspace)


def test_the_working_directory_is_not_trusted_when_it_is_the_home_or_a_root(
    tmp_path: Path,
):
    home = make_root(tmp_path, "home")
    assert home not in li.resolve_allowed_dirs(["auto"], [], cwd=home, home=home)
    assert Path(Path.cwd().anchor) not in li.resolve_allowed_dirs(
        ["auto"], [], cwd=Path(Path.cwd().anchor)
    )


def test_client_roots_win_over_the_working_directory(tmp_path: Path):
    workspace = make_root(tmp_path, "workspace")
    elsewhere = make_root(tmp_path, "elsewhere")
    roots = li.resolve_allowed_dirs(["auto"], [workspace], cwd=elsewhere)
    assert workspace in roots
    assert elsewhere not in roots


def test_a_filesystem_root_is_never_allowed(tmp_path: Path):
    anchor = Path(tmp_path.anchor)
    assert li.resolve_allowed_dirs([str(anchor)], [anchor]) == []
    assert anchor not in li.resolve_allowed_dirs(["auto"], [anchor])


def test_explicit_entries_expand_home_and_relative_paths(tmp_path: Path):
    home = make_root(tmp_path, "home")
    (home / "pics").mkdir()
    work = make_root(tmp_path, "work")
    (work / "shots").mkdir()
    roots = li.resolve_allowed_dirs(
        ["~/pics", "shots", "~", "missing"], cwd=work, home=home
    )
    assert roots == [(home / "pics").resolve(), (work / "shots").resolve(), home]


def test_missing_and_duplicate_entries_are_dropped(tmp_path: Path):
    workspace = make_root(tmp_path, "workspace")
    roots = li.resolve_allowed_dirs(
        [str(workspace), str(workspace / "."), str(tmp_path / "nope")]
    )
    assert roots == [workspace]


@POSIX_ONLY
def test_a_symlinked_root_is_resolved_to_its_real_directory(tmp_path: Path):
    real = make_root(tmp_path, "real")
    link = tmp_path / "link"
    link.symlink_to(real)
    assert li.resolve_allowed_dirs([str(link)]) == [real]


def test_a_file_is_not_a_folder(tmp_path: Path):
    file = tmp_path / "f"
    file.write_bytes(b"x")
    assert li.resolve_allowed_dirs([str(file)]) == []


# --------------------------------------------------------------------------
# file:// URIs (MCP roots)
# --------------------------------------------------------------------------
@POSIX_ONLY
@pytest.mark.parametrize(
    ("uri", "expected"),
    [
        ("file:///tmp/a%20b", Path("/tmp/a b")),
        ("file://localhost/tmp/x", Path("/tmp/x")),
        ("FILE:///tmp/x", Path("/tmp/x")),
        ("file:///tmp/%E9%A1%B9", Path("/tmp/项")),
        ("file://server/share/x", None),
        ("http://example.test/x", None),
        ("file:///tmp/a%00b", None),
        ("file://", None),
        ("not a uri", None),
        ("file://[::1/x", None),
    ],
)
def test_file_uri_to_path(uri: str, expected: Path | None):
    assert li.file_uri_to_path(uri) == expected


# --------------------------------------------------------------------------
# finding and rewriting references
# --------------------------------------------------------------------------
@pytest.fixture
def shots(tmp_path: Path) -> Path:
    root = make_root(tmp_path, "shots")
    (root / "a.png").write_bytes(PNG)
    (root / "b.JPG").write_bytes(JPEG)
    (root / "sub").mkdir()
    (root / "sub" / "c d.gif").write_bytes(GIF)
    return root


def test_a_prompt_without_images_is_returned_untouched(shots: Path):
    prompt = "Plain *text* with `code` and a [link](a.png)."
    result = run(prompt, only(shots))
    assert result.prompt == prompt
    assert result.images == ()
    assert result.skipped == ()


def test_a_markdown_image_is_read_and_rewritten(shots: Path):
    result = run(f"before ![shot]({shots}/a.png) after", only(shots))
    assert result.prompt == f"before ![shot]({url(0)}) after"
    assert result.images == (li.PromptImage("image/png", PNG),)
    assert result.skipped == ()


def test_relative_paths_resolve_against_the_allowed_folders(shots: Path):
    result = run("![x](sub/c%20d.gif) ![y](./a.png) ![z](<sub/c d.gif>)", only(shots))
    assert result.prompt == f"![x]({url(0)}) ![y]({url(1)}) ![z]({url(0)})"
    assert [image.mime_type for image in result.images] == ["image/gif", "image/png"]


def test_extension_case_does_not_matter_but_the_bytes_decide(shots: Path):
    result = run("![x](b.JPG)", only(shots))
    assert result.images == (li.PromptImage("image/jpeg", JPEG),)


def test_titles_alt_brackets_and_escapes_are_understood(shots: Path):
    prompt = (
        '![a "quoted" [nested] alt](a.png "a title") '
        "![b](a.png 'single') "
        "![c](a.png (paren title)) "
        "![d](  a.png  )"
    )
    result = run(prompt, only(shots))
    assert result.prompt == (
        f'![a "quoted" [nested] alt]({url(0)} "a title") '
        f"![b]({url(0)} 'single') "
        f"![c]({url(0)} (paren title)) "
        f"![d](  {url(0)}  )"
    )
    assert len(result.images) == 1


def test_an_escaped_bang_is_not_an_image(shots: Path):
    prompt = r"\![x](a.png) and \\![y](a.png)"
    result = run(prompt, only(shots))
    assert result.prompt == rf"\![x](a.png) and \\![y]({url(0)})"


def test_a_query_or_fragment_does_not_hide_the_file(shots: Path):
    result = run("![x](a.png?raw=true) ![y](a.png#frag)", only(shots))
    assert result.prompt == f"![x]({url(0)}) ![y]({url(0)})"


def test_file_urls_and_home_paths_are_local(tmp_path: Path):
    home = make_root(tmp_path, "home")
    (home / "pic.png").write_bytes(PNG)
    roots = li.resolve_allowed_dirs([str(home)], home=home)
    uri = (home / "pic.png").as_uri()
    result = run(
        f"![a]({uri}) ![b]({uri.replace('file://', 'file://localhost')})", roots
    )
    assert result.prompt == f"![a]({url(0)}) ![b]({url(0)})"


@pytest.mark.parametrize(
    "dest",
    [
        "https://example.test/a.png",
        "http://example.test/a.png",
        "data:image/png;base64,AAAA",
        "blob:https://example.test/1-2-3",
        "//cdn.example.test/a.png",
        "#anchor",
        "mailto:someone@example.test",
        "ftp://example.test/a.png",
        "",
    ],
)
def test_references_that_are_not_local_are_left_alone(shots: Path, dest: str):
    prompt = f'![x]({dest}) <img src="{dest}">'
    result = run(prompt, only(shots))
    assert result.prompt == prompt
    assert result.skipped == ()


def test_reference_style_images_are_not_recognised(shots: Path):
    prompt = "![x][ref]\n\n[ref]: a.png\n"
    assert run(prompt, only(shots)).prompt == prompt


@pytest.mark.parametrize(
    "prompt",
    [
        "```\n![x](a.png)\n```\n",
        "~~~\n![x](a.png)\n~~~\n",
        "````\n![x](a.png)\n```\n![y](a.png)\n````\n",
        "```python\n![x](a.png)\n",
        "   ```\n![x](a.png)\n   ```\n",
        "`![x](a.png)`",
        "``![x](a.png)``",
        "text `` ` ![x](a.png) ` `` text",
        '```\n<img src="a.png">\n```\n',
        '`<img src="a.png">`',
    ],
)
def test_images_inside_code_are_left_alone(shots: Path, prompt: str):
    result = run(prompt, only(shots))
    assert result.prompt == prompt
    assert result.images == ()


def test_code_blocks_do_not_hide_the_images_around_them(shots: Path):
    prompt = "![a](a.png)\n```\n![b](a.png)\n```\n![c](a.png)\n`x` ![d](a.png)"
    result = run(prompt, only(shots))
    assert result.prompt == (
        f"![a]({url(0)})\n```\n![b](a.png)\n```\n![c]({url(0)})\n`x` ![d]({url(0)})"
    )


def test_an_unbalanced_backtick_does_not_swallow_the_next_paragraph(shots: Path):
    prompt = "stray ` backtick\n\n![x](a.png)\n\nanother ` one"
    result = run(prompt, only(shots))
    assert f"![x]({url(0)})" in result.prompt


def test_a_four_space_indent_is_not_a_fence(shots: Path):
    prompt = "    ```\n![x](a.png)\n"
    assert f"![x]({url(0)})" in run(prompt, only(shots)).prompt


@pytest.mark.parametrize(
    ("tag", "expected"),
    [
        ('<img src="a.png">', f'<img src="{url(0)}">'),
        ("<img src='a.png' alt='x'>", f"<img src='{url(0)}' alt='x'>"),
        ("<img alt=x src=a.png>", f"<img alt=x src={url(0)}>"),
        ('<IMG SRC = "a.png" />', f'<IMG SRC = "{url(0)}" />'),
        (
            '<img\n  src="a.png"\n  width="10">',
            f'<img\n  src="{url(0)}"\n  width="10">',
        ),
    ],
)
def test_html_images_are_rewritten_in_place(shots: Path, tag: str, expected: str):
    result = run(tag, only(shots))
    assert result.prompt == expected
    assert len(result.images) == 1


def test_html_attributes_that_merely_contain_src_are_ignored(shots: Path):
    prompt = '<img data-src="a.png" srcset="a.png 2x" alt="a.png">'
    result = run(prompt, only(shots))
    assert result.prompt == prompt


def test_html_entities_in_the_path_are_decoded(shots: Path):
    (shots / "a&b.png").write_bytes(PNG)
    result = run('<img src="a&amp;b.png">', only(shots))
    assert result.prompt == f'<img src="{url(0)}">'


def test_markdown_and_html_to_the_same_file_share_one_image(shots: Path):
    result = run('![x](a.png) <img src="./a.png">', only(shots))
    assert result.prompt == f'![x]({url(0)}) <img src="{url(0)}">'
    assert len(result.images) == 1


def test_images_are_numbered_in_order_of_appearance(shots: Path):
    result = run("![1](sub/c%20d.gif) ![2](a.png) ![3](b.JPG) ![4](a.png)", only(shots))
    assert (
        result.prompt == f"![1]({url(0)}) ![2]({url(1)}) ![3]({url(2)}) ![4]({url(1)})"
    )
    assert [image.mime_type for image in result.images] == [
        "image/gif",
        "image/png",
        "image/jpeg",
    ]


# --------------------------------------------------------------------------
# what is refused, and the placeholder that says so
# --------------------------------------------------------------------------
def test_a_missing_file_becomes_a_placeholder(shots: Path):
    result = run("see ![x](nope.png) here", only(shots))
    assert result.prompt == (
        "see 🖼️ *(image not shown: file not found) `nope.png`* here"
    )
    assert result.skipped == (li.SkippedImage("nope.png", li.Reason.NOT_FOUND),)
    assert result.images == ()


def test_the_placeholder_for_an_html_tag_is_plain_escaped_text(shots: Path):
    result = run('<p><img src="a&lt;b&gt;&quot;.png"></p>', only(shots))
    assert result.prompt == (
        "<p>🖼️ (image not shown: file not found) a&lt;b&gt;&quot;.png</p>"
    )


def test_the_placeholder_keeps_the_reference_readable_but_harmless(shots: Path):
    result = run("![x](<a`b|c_d*e.png>)", only(shots))
    assert "`a b c_d*e.png`" in result.prompt


def test_a_long_reference_is_shortened_in_the_placeholder(shots: Path):
    result = run(f"![x]({'d/' * 400}z.png)", only(shots))
    assert "…" in result.prompt
    assert len(result.prompt) < 300


@pytest.mark.parametrize(
    ("name", "content"),
    [
        ("note.txt", PNG),
        ("fake.png", b"<html><script>alert(1)</script></html>"),
        ("vector.svg", b"<svg xmlns='http://www.w3.org/2000/svg'><script/></svg>"),
        ("empty.png", b""),
        ("pdf.png", b"%PDF-1.7 ..."),
    ],
)
def test_only_real_images_with_an_image_extension_are_read(
    shots: Path, name: str, content: bytes
):
    (shots / name).write_bytes(content)
    result = run(f"![x]({name})", only(shots))
    assert result.images == ()
    assert result.skipped == (li.SkippedImage(name, li.Reason.NOT_IMAGE),)


def test_a_directory_named_like_an_image_is_not_found(shots: Path):
    (shots / "folder.png").mkdir()
    result = run("![x](folder.png)", only(shots))
    assert result.skipped[0].reason is li.Reason.NOT_FOUND


def test_oversize_files_are_refused_without_being_read(
    shots: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(li, "MAX_IMAGE_BYTES", 100)
    (shots / "big.png").write_bytes(PNG + b"\x00" * 200)
    result = run("![x](big.png) ![y](a.png)", only(shots))
    assert result.skipped == (li.SkippedImage("big.png", li.Reason.TOO_LARGE),)
    assert result.images == (li.PromptImage("image/png", PNG),)


def test_the_total_budget_applies_across_images(
    shots: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(li, "MAX_TOTAL_BYTES", len(PNG) + len(JPEG) + 1)
    result = run("![1](a.png) ![2](b.JPG) ![3](sub/c%20d.gif)", only(shots))
    assert [image.mime_type for image in result.images] == ["image/png", "image/jpeg"]
    assert result.skipped == (li.SkippedImage("sub/c%20d.gif", li.Reason.TOO_LARGE),)


def test_a_repeated_image_does_not_count_twice(
    shots: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(li, "MAX_TOTAL_BYTES", len(PNG))
    result = run("![1](a.png) ![2](./a.png) ![3](a.png)", only(shots))
    assert len(result.images) == 1
    assert result.skipped == ()


def test_no_more_than_the_maximum_number_of_images(shots: Path):
    for number in range(li.MAX_IMAGES + 2):
        (shots / f"n{number}.png").write_bytes(PNG + bytes([number]))
    prompt = " ".join(f"![{n}](n{n}.png)" for n in range(li.MAX_IMAGES + 2))
    result = run(prompt, only(shots))
    assert len(result.images) == li.MAX_IMAGES
    assert [item.reason for item in result.skipped] == [li.Reason.TOO_MANY] * 2
    assert result.prompt.count("/images/") == li.MAX_IMAGES
    assert result.prompt.count("image not shown") == 2


def test_nothing_is_readable_without_allowed_folders(shots: Path):
    result = run(f"![x]({shots}/a.png)", [])
    assert result.images == ()
    assert result.skipped[0].reason is li.Reason.OUTSIDE


# --------------------------------------------------------------------------
# containment
# --------------------------------------------------------------------------
@pytest.fixture
def fence(tmp_path: Path) -> tuple[Path, Path]:
    """``(inside, outside)``: an allowed folder and a sibling with a secret."""
    inside = make_root(tmp_path, "inside")
    outside = make_root(tmp_path, "outside")
    (inside / "ok.png").write_bytes(PNG)
    (outside / "secret.png").write_bytes(PNG + b"secret")
    return inside, outside


def test_an_absolute_path_outside_the_folders_is_refused(fence):
    inside, outside = fence
    result = run(f"![x]({outside}/secret.png)", only(inside))
    assert result.images == ()
    assert result.skipped[0].reason is li.Reason.OUTSIDE


def test_dot_dot_cannot_climb_out(fence):
    inside, outside = fence
    result = run(
        f"![x](../outside/secret.png) ![y]({inside}/../outside/secret.png)",
        only(inside),
    )
    assert result.images == ()
    assert [item.reason for item in result.skipped] == [li.Reason.OUTSIDE] * 2


def test_dot_dot_that_stays_inside_is_fine(fence):
    inside, _ = fence
    (inside / "deep").mkdir()
    result = run("![x](deep/../ok.png)", only(inside))
    assert len(result.images) == 1


def test_a_sibling_with_the_same_prefix_is_not_inside(tmp_path: Path):
    inside = make_root(tmp_path, "proj")
    sibling = make_root(tmp_path, "proj-evil")
    (sibling / "x.png").write_bytes(PNG)
    result = run(f"![x]({sibling}/x.png)", only(inside))
    assert result.skipped[0].reason is li.Reason.OUTSIDE


def test_percent_encoded_dot_dot_cannot_climb_out(fence):
    inside, _ = fence
    result = run("![x](%2e%2e/outside/secret.png)", only(inside))
    assert result.images == ()


@POSIX_ONLY
def test_a_symlink_to_a_file_outside_is_refused(fence):
    inside, outside = fence
    (inside / "link.png").symlink_to(outside / "secret.png")
    result = run("![x](link.png)", only(inside))
    assert result.images == ()
    assert result.skipped[0].reason is li.Reason.OUTSIDE


@POSIX_ONLY
def test_a_symlinked_folder_that_leads_out_is_refused(fence):
    inside, outside = fence
    (inside / "gallery").symlink_to(outside)
    result = run("![x](gallery/secret.png)", only(inside))
    assert result.images == ()
    assert result.skipped[0].reason is li.Reason.OUTSIDE


@POSIX_ONLY
def test_a_symlink_that_stays_inside_is_followed(fence):
    inside, _ = fence
    (inside / "alias.png").symlink_to(inside / "ok.png")
    result = run("![x](alias.png)", only(inside))
    assert result.images == (li.PromptImage("image/png", PNG),)


@POSIX_ONLY
def test_a_symlink_to_a_non_image_inside_is_refused(fence):
    inside, _ = fence
    (inside / "notes.txt").write_bytes(b"hello")
    (inside / "alias.png").symlink_to(inside / "notes.txt")
    result = run("![x](alias.png)", only(inside))
    assert result.skipped[0].reason is li.Reason.NOT_IMAGE


@POSIX_ONLY
def test_a_dangling_symlink_is_not_found(fence):
    inside, _ = fence
    (inside / "dangling.png").symlink_to(inside / "gone.png")
    result = run("![x](dangling.png)", only(inside))
    assert result.skipped[0].reason is li.Reason.NOT_FOUND


@POSIX_ONLY
def test_a_fifo_is_never_opened(fence):
    inside, _ = fence
    os.mkfifo(inside / "pipe.png")
    outcome: list[li.PreparedPrompt] = []
    worker = threading.Thread(
        target=lambda: outcome.append(run("![x](pipe.png)", only(inside))), daemon=True
    )
    worker.start()
    worker.join(5)
    assert not worker.is_alive(), "reading a FIFO blocked the scan"
    assert outcome[0].images == ()
    assert outcome[0].skipped[0].reason is li.Reason.NOT_FOUND


@POSIX_ONLY
@pytest.mark.skipif(
    hasattr(os, "geteuid") and os.geteuid() == 0, reason="root ignores file modes"
)
def test_an_unreadable_file_is_reported(fence):
    inside, _ = fence
    locked = inside / "locked.png"
    locked.write_bytes(PNG)
    locked.chmod(0)
    try:
        result = run("![x](locked.png)", only(inside))
    finally:
        locked.chmod(0o600)
    assert result.skipped[0].reason is li.Reason.UNREADABLE


@pytest.mark.parametrize(
    "dest",
    [
        "\\\\\\\\attacker\\\\share\\\\x.png",
        "<\\\\\\\\attacker\\\\share\\\\x.png>",
        "\\\\attacker\\share\\x.png",
        "<\\\\attacker\\share\\x.png>",
        "%5C%5Cattacker%5Cshare%5Cx.png",
        "file://attacker/share/x.png",
        "file:////attacker/share/x.png",
    ],
)
def test_unc_and_remote_hosts_are_never_touched(
    fence, monkeypatch: pytest.MonkeyPatch, dest: str
):
    """Resolving a UNC path makes Windows contact the server (and offer credentials)."""
    inside, _ = fence
    touched: list[str] = []
    real = li._realpath

    def spy(path: Path) -> Path | None:
        touched.append(str(path))
        return real(path)

    monkeypatch.setattr(li, "_realpath", spy)
    result = run(f"![x]({dest})", only(inside))
    assert result.images == ()
    assert result.skipped
    assert not [item for item in touched if item.startswith(("\\\\", "//"))], touched


@pytest.mark.parametrize(
    "dest",
    [
        "\\\\\\\\attacker\\\\share\\\\x.png",
        "file://attacker/share/x.png",
        "file:////attacker/share/x.png",
    ],
)
def test_a_unc_destination_is_reported_as_outside(fence, dest: str):
    inside, _ = fence
    result = run(f"![x]({dest})", only(inside))
    assert [item.reason for item in result.skipped] == [li.Reason.OUTSIDE]


@pytest.mark.parametrize("dest", ["a%00.png", "a\x00.png", "~someone/x.png", "~"])
def test_odd_destinations_do_not_raise(fence, dest: str):
    inside, _ = fence
    result = run(f"![x](<{dest}>)", only(inside))
    assert result.images == ()


def test_a_reference_that_changes_under_the_reader_is_refused(
    fence, monkeypatch: pytest.MonkeyPatch
):
    inside, outside = fence
    real = li._realpath
    calls = {"count": 0}

    def swapped(path: Path) -> Path | None:
        calls["count"] += 1
        if path.name == "ok.png" and calls["count"] > 2:
            return outside / "secret.png"
        return real(path)

    monkeypatch.setattr(li, "_realpath", swapped)
    result = run("![x](ok.png)", only(inside))
    assert result.images == ()
    assert result.skipped[0].reason is li.Reason.UNREADABLE


# --------------------------------------------------------------------------
# the reader's own checks: what it verifies after it holds the file open
# --------------------------------------------------------------------------
class OsProxy:
    """Stands in for ``os`` inside ``local_images`` only, with some members replaced."""

    def __init__(self, **replaced: object) -> None:
        self._replaced = replaced

    def __getattr__(self, name: str) -> object:
        if name in self._replaced:
            return self._replaced[name]
        return getattr(os, name)


def read(path: Path, budget: int = li.MAX_TOTAL_BYTES) -> li.PromptImage:
    return li._read_image(path, budget)


def refusal(path: Path, budget: int = li.MAX_TOTAL_BYTES) -> li.Reason:
    with pytest.raises(li._Skip) as caught:
        read(path, budget)
    return caught.value.reason


def test_the_reader_returns_what_the_file_holds(fence):
    inside, _ = fence

    assert read(inside / "ok.png") == li.PromptImage("image/png", PNG)


@POSIX_ONLY
def test_a_path_that_now_resolves_elsewhere_is_refused_even_for_the_same_file(
    fence, monkeypatch: pytest.MonkeyPatch
):
    """The inode check cannot see this: both paths lead to one file."""
    inside, outside = fence
    twin = outside / "twin.png"
    os.link(inside / "ok.png", twin)
    monkeypatch.setattr(li, "_realpath", lambda path: twin)

    assert refusal(inside / "ok.png") is li.Reason.UNREADABLE


@POSIX_ONLY
def test_a_path_that_cannot_be_resolved_again_is_refused(
    fence, monkeypatch: pytest.MonkeyPatch
):
    inside, _ = fence
    monkeypatch.setattr(li, "_realpath", lambda path: None)

    assert refusal(inside / "ok.png") is li.Reason.UNREADABLE


@POSIX_ONLY
def test_a_file_replaced_while_it_is_open_is_refused(
    fence, monkeypatch: pytest.MonkeyPatch
):
    """Same path before and after, a different file behind it: only the inode shows."""
    inside, _ = fence
    target = inside / "ok.png"
    resolve = li._realpath

    def swap_then_resolve(path: Path) -> Path | None:
        replacement = inside / "replacement.png"
        replacement.write_bytes(PNG + b"other")
        os.replace(replacement, target)
        return resolve(path)

    monkeypatch.setattr(li, "_realpath", swap_then_resolve)

    assert refusal(target) is li.Reason.UNREADABLE


@POSIX_ONLY
def test_the_file_is_opened_without_following_a_symlink_or_waiting(
    fence, monkeypatch: pytest.MonkeyPatch
):
    inside, _ = fence
    flags: list[int] = []

    def spy(path, open_flags, *args, **kwargs):
        flags.append(open_flags)
        return os.open(path, open_flags, *args, **kwargs)

    monkeypatch.setattr(li, "os", OsProxy(open=spy))

    read(inside / "ok.png")

    (used,) = flags
    for name in ("O_NOFOLLOW", "O_NONBLOCK"):
        assert used & getattr(os, name) == getattr(os, name), name


@POSIX_ONLY
def test_a_fifo_handed_to_the_reader_is_refused_without_blocking(fence):
    inside, _ = fence
    pipe = inside / "pipe.png"
    os.mkfifo(pipe)
    outcome: list[li.Reason] = []

    def attempt() -> None:
        try:
            read(pipe)
        except li._Skip as skip:
            outcome.append(skip.reason)

    worker = threading.Thread(target=attempt, daemon=True)
    worker.start()
    worker.join(5)
    if worker.is_alive():
        try:
            os.close(os.open(pipe, os.O_WRONLY | os.O_NONBLOCK))
        except OSError:
            pass
        worker.join(5)
        pytest.fail("opening a FIFO blocked the reader")

    assert outcome == [li.Reason.NOT_IMAGE]


@POSIX_ONLY
def test_a_special_file_is_refused_before_anything_is_read(
    fence, monkeypatch: pytest.MonkeyPatch
):
    """Reading a device can have side effects, so the file type is checked first."""
    inside, _ = fence
    reads: list[int] = []

    def as_a_device(descriptor: int) -> SimpleNamespace:
        info = os.fstat(descriptor)
        return SimpleNamespace(
            st_mode=stat.S_IFCHR | 0o600,
            st_size=0,
            st_dev=info.st_dev,
            st_ino=info.st_ino,
        )

    def spy(descriptor: int, count: int) -> bytes:
        reads.append(count)
        return os.read(descriptor, count)

    monkeypatch.setattr(li, "os", OsProxy(fstat=as_a_device, read=spy))

    assert refusal(inside / "ok.png") is li.Reason.NOT_IMAGE
    assert reads == []


@POSIX_ONLY
def test_a_file_that_grows_after_it_was_measured_is_refused(
    fence, monkeypatch: pytest.MonkeyPatch
):
    inside, _ = fence
    growing = inside / "growing.png"
    growing.write_bytes(PNG + b"\x00" * 4096)

    def understated(descriptor: int) -> SimpleNamespace:
        info = os.fstat(descriptor)
        return SimpleNamespace(
            st_mode=info.st_mode,
            st_size=len(PNG),
            st_dev=info.st_dev,
            st_ino=info.st_ino,
        )

    monkeypatch.setattr(li, "os", OsProxy(fstat=understated))

    assert refusal(growing, len(PNG) + 16) is li.Reason.TOO_LARGE


# --------------------------------------------------------------------------
# which folder a path is "inside", and why a reference is refused
# --------------------------------------------------------------------------
def test_the_file_system_decides_what_counts_as_the_same_folder(
    monkeypatch: pytest.MonkeyPatch,
):
    """On a case-insensitive file system ``/srv/pictures`` is ``/srv/Pictures``."""
    root = Path("/srv/Pictures")
    probe = Path("/srv/pictures/albums/a.png")
    assert li._is_inside(probe, root) is False

    monkeypatch.setattr(
        Path, "samefile", lambda self, other: str(self).lower() == str(other).lower()
    )

    assert li._is_inside(probe, root) is True


def test_a_folder_and_its_ancestors_are_told_apart():
    root = Path("/srv/pictures")

    assert li._is_inside(Path("/srv/pictures"), root) is True
    assert li._is_inside(Path("/srv/pictures/a/b/c.png"), root) is True
    assert li._is_inside(Path("/srv"), root) is False
    assert li._is_inside(Path("/srv/pictures2/a.png"), root) is False


@POSIX_ONLY
def test_auto_always_includes_slash_tmp(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """On macOS the temp dir is under ``/var/folders``, yet agents write to ``/tmp``."""
    if not Path("/tmp").is_dir():
        pytest.skip("no /tmp on this machine")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.setattr(tempfile, "gettempdir", lambda: str(elsewhere))

    roots = li.resolve_allowed_dirs(["auto"], [], cwd=Path("/"), home=tmp_path)

    assert Path("/tmp").resolve() in roots
    assert elsewhere.resolve() in roots


@POSIX_ONLY
def test_a_symlink_out_reads_as_not_found_when_another_folder_could_hold_the_name(
    tmp_path: Path,
):
    """Saying "outside" would confirm that the file behind the link exists."""
    first = make_root(tmp_path, "first")
    second = make_root(tmp_path, "second")
    outside = make_root(tmp_path, "outside")
    (outside / "secret.png").write_bytes(PNG)
    (first / "gallery").symlink_to(outside)
    roots = li.resolve_allowed_dirs([str(first), str(second)])

    through_the_link = run("![x](gallery/secret.png)", roots)
    spelled_out = run(f"![y]({outside}/secret.png)", roots)

    assert through_the_link.skipped[0].reason is li.Reason.NOT_FOUND
    assert spelled_out.skipped[0].reason is li.Reason.OUTSIDE


@POSIX_ONLY
def test_a_tilde_name_is_never_read_as_a_folder_called_that(shots: Path):
    (shots / "~someone").mkdir()
    (shots / "~someone" / "x.png").write_bytes(PNG)

    result = run("![x](~someone/x.png)", only(shots))

    assert result.images == ()
    assert result.skipped[0].reason is li.Reason.NOT_FOUND


@pytest.mark.parametrize(
    "prompt",
    [
        """![a](a.png "<img src='b.JPG'>")""",
        """![<img src="b.JPG">](a.png)""",
    ],
)
def test_a_reference_inside_another_one_is_not_edited_twice(shots: Path, prompt: str):
    result = run(prompt, only(shots))

    assert result.prompt == prompt.replace("a.png", url(0))
    assert len(result.images) == 1


# --------------------------------------------------------------------------
# the Web UI side of the payload
# --------------------------------------------------------------------------
def encode(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def test_encode_and_parse_round_trip():
    images = (li.PromptImage("image/png", PNG), li.PromptImage("image/jpeg", JPEG))
    assert li.parse_prompt_images(li.encode_prompt_images(images)) == images


def test_parse_ignores_the_claimed_mime_type():
    parsed = li.parse_prompt_images([{"mime_type": "text/html", "data": encode(PNG)}])
    assert parsed == (li.PromptImage("image/png", PNG),)


def test_parse_keeps_positions_when_an_entry_is_invalid():
    raw = [
        {"data": encode(PNG)},
        {"data": "!!not base64!!"},
        "not a dict",
        {"data": encode(b"<html>")},
        {"data": ""},
        {"data": 5},
        {"mime_type": "image/png"},
        {"data": encode(JPEG)},
    ]
    parsed = li.parse_prompt_images(raw)
    assert [None if image is None else image.mime_type for image in parsed] == [
        "image/png",
        None,
        None,
        None,
        None,
        None,
        None,
        "image/jpeg",
    ]


@pytest.mark.parametrize("raw", [None, {}, "x", 5, [], ()])
def test_parse_of_a_missing_or_malformed_field_is_empty(raw):
    assert li.parse_prompt_images(raw) == ()


def test_parse_refuses_base64_with_stray_characters():
    good = encode(PNG)
    for bad in (good[:8] + "\n" + good[8:], good[:8] + "!" + good[8:], " " + good):
        assert li.parse_prompt_images([{"data": bad}]) == (None,)


def test_parse_enforces_the_count_and_size_limits(monkeypatch: pytest.MonkeyPatch):
    many = [{"data": encode(PNG)}] * (li.MAX_IMAGES + 3)
    assert len(li.parse_prompt_images(many)) == li.MAX_IMAGES

    monkeypatch.setattr(li, "MAX_IMAGE_BYTES", len(PNG))
    monkeypatch.setattr(li, "MAX_TOTAL_BYTES", len(PNG) * 2)
    raw = [
        {"data": encode(PNG)},
        {"data": encode(PNG + b"\x00")},
        {"data": encode(PNG)},
        {"data": encode(PNG)},
    ]
    parsed = li.parse_prompt_images(raw)
    assert [image is not None for image in parsed] == [True, False, True, False]


def test_parse_does_not_decode_an_absurdly_long_string(monkeypatch: pytest.MonkeyPatch):
    calls: list[int] = []
    real = base64.b64decode

    def spy(value, *args, **kwargs):
        calls.append(len(value))
        return real(value, *args, **kwargs)

    monkeypatch.setattr(li.base64, "b64decode", spy)
    monkeypatch.setattr(li, "MAX_IMAGE_BYTES", 10)
    assert li.parse_prompt_images([{"data": "A" * 10_000}]) == (None,)
    assert calls == []


# --------------------------------------------------------------------------
# hostile and random input
# --------------------------------------------------------------------------
def test_scanning_is_linear_on_hostile_input(shots: Path):
    roots = only(shots)
    started = time.perf_counter()
    hostile = [
        "![" * 400_000,
        "![a](" * 150_000,
        "![" + "[" * 300_000,
        "<img " * 150_000,
        "`" * 400_000,
        "".join("`" * (n % 40 + 1) + "x" for n in range(40_000)),
        "![a](" + "(" * 300_000,
        "![a](<" + "\\" * 300_000,
        "```\n" * 200_000,
        "\\![" * 200_000,
    ]
    for text in hostile:
        assert li.prepare_prompt_images(text, TASK, roots).prompt is not None
    assert time.perf_counter() - started < 20


def test_random_input_never_raises_and_unresolved_text_is_unchanged(shots: Path):
    rng = random.Random(726)
    alphabet = [
        *"![]()<>\"'\\ \n\t`~#?%&;:/.-_=*",
        "a.png",
        "img",
        "src",
        "file:",
        "~/",
        "http://",
        "<img ",
    ]
    roots = only(shots)
    for _ in range(3000):
        text = "".join(rng.choice(alphabet) for _ in range(rng.randint(0, 80)))
        result = li.prepare_prompt_images(text, TASK, roots)
        if not result.images and not result.skipped:
            assert result.prompt == text


def test_only_the_first_references_are_examined(shots: Path):
    prompt = "![x](a.png) " * (li._MAX_REFS_SCANNED + 20)
    result = run(prompt, only(shots))
    assert result.prompt.count("/images/0") == li._MAX_REFS_SCANNED
    assert result.prompt.count("](a.png)") == 20


def test_images_in_code_do_not_use_up_the_scan_budget(shots: Path):
    prompt = (
        "```\n" + "![c](a.png)\n" * (li._MAX_REFS_SCANNED + 50) + "```\n![real](a.png)"
    )
    result = run(prompt, only(shots))
    assert result.prompt.endswith(f"![real]({url(0)})")
