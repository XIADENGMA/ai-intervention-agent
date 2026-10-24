"""R869: the upload scan no longer drops an image because three of its bytes spell ``<?=``.

``FileValidator`` looks for text that would be dangerous if an upload were ever executed or served
as a page (``<script``, ``<?php``, ``eval(``, ...) in up to three 64 KiB windows of every upload
(its start, its end and, for a file of more than 128 KiB, its middle: 192 KiB).  Seventeen patterns
did that; one of them, ``<?=`` (PHP's short echo tag), is three bytes long.

Compressed pixels look like random bytes, and the chance that three given bytes turn up somewhere in
196,608 random positions is 196,608 / 256**3, 1.17%.  Measured, not computed: of 6,002 PNG / JPEG /
GIF / WebP / BMP files from macOS system folders (20 KiB to 10 MiB), 69 (1.15%) were refused with
``检测到可疑内容模式: <\\?=`` (the 700 KB ``Folder_512x512@2x.png`` of the system icon set, the images
of the Ventura settings extension, ...), and random buffers of 100 KiB to 2 MiB were refused at the
rate the calculation gives.  A refused file is not reported to the user: ``extract_uploaded_images``
logs a warning and goes on, so ``POST /api/tasks/<id>/submit`` answered ``{"success": true}`` while
the screenshot the user attached never reached the agent.  About one image in a hundred.

The other sixteen patterns are long enough that random data almost never matches them (the likeliest,
``curl\\s+`` and ``wget\\s+``, once in 58,000 uploads each).  ``<?=`` now counts only where PHP needs
it to be a tag: followed by a variable (``<?=$_GET[0]?>``, ``<?= $cmd ?>``) or by a back-quoted
command (``<?=`id`?>``), which random data reaches once in 100,000 uploads each.  What PHP could do
after ``<?=`` that is neither (``<?=phpinfo()?>``, ``<?='a'?>``) is not told from chance by three
bytes and is no longer refused; the patterns for ``system(``, ``exec(``, ``eval(`` and the rest
still see the calls that matter.

What the tests pin:

* the chance that a clean upload is refused, computed from the patterns themselves: a pattern is cut
  into the pieces the list uses (a character, an escape, a class, each with its repeat), the pieces
  become a small automaton over the 256 byte values (letters in both cases, as the scan compiles
  them), and the automaton says how likely random bytes are to match starting at one position, every
  way the pattern can match counted (``[^>]*>`` waits for its ``>``).  Times the bytes the scan reads
  (measured on a large file, not assumed) and summed over the patterns, it must stay below 1 in
  10,000.  The old ``<?=`` alone was 1 in 85, the list now is 1 in 16,000.  A pattern the model cannot
  read (a group, an alternation) fails the test instead of being skipped;
* the model is right: closed forms for small patterns, a measurement of the old pattern over 3,000
  seeded random buffers, and a measurement of a variable-length pattern against the regex engine;
* a high-entropy image that contains ``<?=`` in its head, its middle or its tail is accepted, and
  so is one that contains the first bytes of each of the new forms without the rest;
* what the scan is for is still refused, in each window: ``<?=$x``, ``<?= $cmd``, ``<?=`id`?>``,
  ``<?php``, ``<script>``, ``javascript:``, ``system(``;
* end to end, the route keeps an image that contains ``<?=`` and still drops one that carries a tag;
* the checker's own cases (the pieces, the chances, the refusal of constructs it cannot read).
"""

from __future__ import annotations

import functools
import io
import random
import re
from collections.abc import Iterable, Iterator

import pytest
from flask.testing import FlaskClient

from ai_intervention_agent.file_validator import MALICIOUS_PATTERNS, FileValidator
from ai_intervention_agent.task_queue_singleton import get_task_queue
from ai_intervention_agent.web_ui import WebFeedbackUI

PNG = b"\x89PNG\r\n\x1a\n"
LOOPBACK = {"REMOTE_ADDR": "127.0.0.1"}
LIMIT = 1e-4  # a clean upload refused by chance: fewer than one in ten thousand
BODY_BYTES = 300 * 1024  # more than the three windows
OLD_PATTERN = rb"<\?="  # what the list had until R869


# --------------------------------------------------------------------------- the model


class UnreadablePattern(ValueError):
    """The pattern uses something the chance model does not read."""


def pieces(source: str) -> list[tuple[str, int, int | None]]:
    """``[(piece, at least, at most or None)]`` for a pattern made of characters, escapes
    (``\\s``, ``\\(``, ``\\x41``), classes (``[^>]``, ``[A-Za-z_]``) and the repeats
    ``* + ? {m} {m,} {m,n}``."""
    found: list[tuple[str, int, int | None]] = []
    index = 0
    while index < len(source):
        char = source[index]
        if char == "\\":
            width = 4 if source[index + 1 : index + 2] == "x" else 2
            piece = source[index : index + width]
        elif char == "[":
            end = index + 1
            if source[end : end + 1] == "^":
                end += 1
            if source[end : end + 1] == "]":
                end += 1
            while end < len(source) and source[end] != "]":
                end += 2 if source[end] == "\\" else 1
            if end >= len(source):
                raise UnreadablePattern(f"unterminated class in {source!r}")
            piece = source[index : end + 1]
        elif char in "()|^$":
            raise UnreadablePattern(f"{char!r} in {source!r}")
        elif char in "*+?{":
            raise UnreadablePattern(f"a repeat with nothing to repeat in {source!r}")
        else:
            piece = char
        index += len(piece)
        minimum: int = 1
        maximum: int | None = 1
        repeat = re.match(r"[*+?]|\{(\d+)(?:(,)(\d*))?\}", source[index:])
        if repeat:
            text = repeat.group(0)
            if text == "*":
                minimum, maximum = 0, None
            elif text == "+":
                minimum, maximum = 1, None
            elif text == "?":
                minimum, maximum = 0, 1
            else:
                minimum = int(repeat.group(1))
                if repeat.group(2) is None:
                    maximum = minimum
                else:
                    maximum = int(repeat.group(3)) if repeat.group(3) else None
            index += len(text)
            if source[index : index + 1] in ("?", "+"):
                raise UnreadablePattern(f"a lazy or possessive repeat in {source!r}")
        found.append((piece, minimum, maximum))
    return found


@functools.cache
def chance_at_a_position(pattern: bytes) -> float:
    """The chance that random bytes match ``pattern`` starting at one given position, counting
    every way it can match (a repeat may keep going until what follows it fits).

    The pieces become a chain of atoms (a set of byte values; optional or not; looping or not),
    the chain is run as a nondeterministic automaton, and the probability mass is pushed through
    its subset states one random byte at a time (grouped into the classes of bytes that no atom
    tells apart) until the mass that has not matched or died is negligible.
    """
    atoms: list[tuple[frozenset[int], bool, bool]] = []
    for piece, minimum, maximum in pieces(pattern.decode("latin-1")):
        compiled = re.compile(piece.encode("latin-1"), re.IGNORECASE)
        members = frozenset(v for v in range(256) if compiled.fullmatch(bytes([v])))
        atoms += [(members, False, False)] * minimum
        if maximum is None:
            atoms.append((members, True, True))
        else:
            atoms += [(members, True, False)] * (maximum - minimum)
    accept = len(atoms)

    def closure(states: Iterable[int]) -> frozenset[int]:
        reached: set[int] = set()
        for state in states:
            reached.add(state)
            while state < accept and atoms[state][1]:
                state += 1
                reached.add(state)
        return frozenset(reached)

    groups: dict[frozenset[int], list[int]] = {}
    for value in range(256):
        signature = frozenset(i for i, atom in enumerate(atoms) if value in atom[0])
        groups.setdefault(signature, []).append(value)
    classes = [(values[0], len(values)) for values in groups.values()]

    start = closure({0})
    if accept in start:
        return 1.0
    live: dict[frozenset[int], float] = {start: 1.0}
    matched = 0.0
    steps: dict[tuple[frozenset[int], int], frozenset[int]] = {}
    for _ in range(20_000):
        following: dict[frozenset[int], float] = {}
        for state, mass in live.items():
            for representative, count in classes:
                key = (state, representative)
                if key not in steps:
                    targets: set[int] = set()
                    for j in state:
                        if j < accept and representative in atoms[j][0]:
                            targets.add(j + 1)
                            if atoms[j][2]:
                                targets.add(j)
                    steps[key] = closure(targets)
                target = steps[key]
                if not target:
                    continue
                weight = mass * count / 256
                if accept in target:
                    matched += weight
                else:
                    following[target] = following.get(target, 0.0) + weight
        live = following
        if not live or (matched and sum(live.values()) < matched * 1e-9):
            break
    return matched


class _Recorder:
    def __init__(self, lengths: list[int]) -> None:
        self.lengths = lengths

    def search(self, chunk: bytes) -> None:
        self.lengths.append(len(chunk))


def scanned_bytes(monkeypatch: pytest.MonkeyPatch, size: int = 2 * 1024 * 1024) -> int:
    """How many bytes one pattern reads of an upload of ``size`` bytes (summed over its windows)."""
    lengths: list[int] = []
    validator = FileValidator()
    monkeypatch.setattr(
        validator, "compiled_patterns", [(_Recorder(lengths), "recorder")]
    )
    result = {"errors": []}
    validator._scan_malicious_content(bytes(size), result)  # ty: ignore[invalid-argument-type]
    return sum(lengths)


def refused_by_chance(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[float, list[tuple[float, str]]]:
    """``(expected refusals per clean upload, [(share, pattern)] biggest first)``: the chance at
    one position times the positions the scan reads, summed over the patterns (a union bound)."""
    positions = scanned_bytes(monkeypatch)
    shares = sorted(
        (
            (chance_at_a_position(pattern) * positions, pattern.decode("latin-1"))
            for pattern in MALICIOUS_PATTERNS
        ),
        reverse=True,
    )
    return sum(share for share, _ in shares), shares


# --------------------------------------------------------------------------- the data


def image(marker: bytes = b"", where: str = "middle", seed: int = 869) -> bytes:
    """A PNG header and ``BODY_BYTES`` of seeded random bytes, with ``marker`` written over the
    bytes at the head, the middle or the tail (each is inside a scanned window)."""
    body = bytearray(random.Random(seed).randbytes(BODY_BYTES))
    offset = {"head": 1000, "middle": BODY_BYTES // 2, "tail": BODY_BYTES - 1000}[where]
    body[offset : offset + len(marker)] = marker
    return PNG + bytes(body)


def verdict(data: bytes) -> tuple[bool, list[str]]:
    result = FileValidator().validate_file(data, "picture.png")
    return result["valid"], result["errors"]


# --------------------------------------------------------------------------- tests


class TestChanceOfRefusingACleanUpload:
    def test_the_scan_reads_three_windows_of_a_large_upload(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        assert scanned_bytes(monkeypatch) == 3 * 64 * 1024

    def test_it_reads_one_window_of_a_small_one(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        assert scanned_bytes(monkeypatch, 40 * 1024) == 40 * 1024

    def test_every_pattern_can_be_read_by_the_model(self) -> None:
        for pattern in MALICIOUS_PATTERNS:
            assert 0 < chance_at_a_position(pattern) < 1, pattern

    def test_a_clean_upload_is_refused_by_chance_less_than_once_in_ten_thousand(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        total, shares = refused_by_chance(monkeypatch)
        worst = ", ".join(f"{pattern} {share:.2g}" for share, pattern in shares[:4])
        assert total < LIMIT, f"{total:.3g} per upload; the biggest shares: {worst}"

    def test_the_shares_are_listed_biggest_first(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _, shares = refused_by_chance(monkeypatch)
        assert len(shares) == len(MALICIOUS_PATTERNS)
        assert [share for share, _ in shares] == sorted(
            (share for share, _ in shares), reverse=True
        )

    def test_no_single_pattern_takes_half_of_the_budget(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _, shares = refused_by_chance(monkeypatch)
        assert shares[0][0] < LIMIT / 2, shares[0]

    def test_the_old_pattern_was_one_refusal_in_eighty_five(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        expected = chance_at_a_position(OLD_PATTERN) * scanned_bytes(monkeypatch)
        assert 1 / 100 < expected < 1 / 80

    def test_the_old_pattern_is_not_in_the_list(self) -> None:
        assert OLD_PATTERN not in MALICIOUS_PATTERNS


class TestTheModelAgreesWithTheRegexEngine:
    def test_for_the_old_three_byte_pattern(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        size = scanned_bytes(monkeypatch)
        chance = chance_at_a_position(OLD_PATTERN)
        expected_per_buffer = 1 - (1 - chance) ** size
        runs = 3000
        search = re.compile(OLD_PATTERN).search
        rng = random.Random(869)
        hits = sum(1 for _ in range(runs) if search(rng.randbytes(size)))
        assert (
            runs * expected_per_buffer * 0.5 < hits < runs * expected_per_buffer * 1.6
        )

    def test_for_a_pattern_whose_length_varies(self) -> None:
        pattern = rb"\x00[^\x01]{1,3}\x01"
        data = random.Random(869).randbytes(16 * 1024 * 1024)
        measured = sum(1 for _ in re.finditer(pattern, data))
        expected = chance_at_a_position(pattern) * len(data)
        assert expected * 0.85 < measured < expected * 1.15, (measured, expected)

    def test_for_a_pattern_that_waits_for_its_end(self) -> None:
        source = rb"\x00[^\x01]*\x01"
        compiled = re.compile(source, re.IGNORECASE)
        data = random.Random(869).randbytes(1024 * 1024)
        rng = random.Random(869)
        samples = 200_000
        # from the first half, so a "\x01" is certain to follow: a start matches when it is "\x00"
        hits = sum(
            1
            for _ in range(samples)
            if compiled.match(data, rng.randrange(len(data) // 2))
        )
        expected = samples * chance_at_a_position(source)
        assert chance_at_a_position(source) == pytest.approx(1 / 256)
        assert expected * 0.85 < hits < expected * 1.15, (hits, expected)


class TestTheFixtureImage:
    def test_each_marker_lies_in_exactly_one_scan_window(self) -> None:
        window = 64 * 1024
        size = len(image())
        windows = {
            "head": range(window),
            "middle": range(size // 2 - window // 2, size // 2 + window // 2),
            "tail": range(size - window, size),
        }
        for where in windows:
            marker = b"<script>"
            offset = image(marker, where).index(marker)
            covering = [
                name
                for name, span in windows.items()
                if offset in span and offset + len(marker) - 1 in span
            ]
            assert covering == [where]


class TestAnImageThatContainsTheBytesIsKept:
    def test_the_baseline_image_is_clean(self) -> None:
        assert verdict(image()) == (True, [])

    @pytest.mark.parametrize("where", ["head", "middle", "tail"])
    def test_three_bytes_that_spell_a_short_echo_tag_are_not_a_reason(
        self, where: str
    ) -> None:
        data = image(b"<?=", where)
        assert b"<?=" in data
        assert re.search(
            OLD_PATTERN, data
        )  # the premise: the old pattern would have matched
        assert verdict(data) == (True, [])

    @pytest.mark.parametrize(
        "marker",
        [b"<?=1", b"<?='a'", b"<?=(", b"<?= ", b"<?=\n\n", b"<?=`", b"<?=$", b"<?=$1"],
    )
    def test_the_start_of_the_new_forms_without_the_rest_is_not_a_reason(
        self, marker: bytes
    ) -> None:
        assert verdict(image(marker + b"\x00\x00", "middle")) == (True, [])


class TestWhatTheScanIsForIsStillRefused:
    PAYLOADS = [
        b"<?=$x",
        b"<?= $cmd ?>",
        b"<?=\n$_GET[0]",
        b"<?=`id`?>",
        b"<?= `ls -la` ?>",
        b"<?php echo 1;",
        b"<script>alert(1)</script>",
        b"javascript:alert(1)",
        b"system('id')",
    ]

    @pytest.mark.parametrize("where", ["head", "middle", "tail"])
    @pytest.mark.parametrize("payload", PAYLOADS)
    def test_it_is_refused_in_each_window(self, payload: bytes, where: str) -> None:
        valid, errors = verdict(image(payload, where))
        assert valid is False
        assert any("可疑内容模式" in error for error in errors)

    def test_the_variable_form_names_its_own_pattern(self) -> None:
        _, errors = verdict(image(b"<?=$x", "middle"))
        assert errors == ["检测到可疑内容模式: <\\?=\\s*\\$[A-Za-z_]"]

    def test_the_command_form_names_its_own_pattern(self) -> None:
        _, errors = verdict(image(b"<?=`id`?>", "middle"))
        assert errors == ["检测到可疑内容模式: <\\?=\\s*`[^`\\r\\n]{1,100}`"]


@pytest.fixture
def ui() -> WebFeedbackUI:
    instance = WebFeedbackUI(prompt="", auto_resubmit_timeout=0, port=19869)
    instance.app.config["TESTING"] = True
    instance.limiter.enabled = False
    object.__setattr__(instance, "shutdown_server", lambda: None)
    return instance


@pytest.fixture
def client(ui: WebFeedbackUI) -> Iterator[FlaskClient]:
    queue = get_task_queue()
    queue.clear_all_tasks()
    try:
        yield ui.app.test_client()
    finally:
        queue.clear_all_tasks()


class TestTheSubmitRoute:
    def submit(self, client: FlaskClient, task_id: str, data: bytes) -> list[object]:
        assert get_task_queue().add_task(
            task_id=task_id, prompt="p", auto_resubmit_timeout=240
        )
        response = client.post(
            f"/api/tasks/{task_id}/submit",
            data={
                "feedback_text": "see the picture",
                "image_0": (io.BytesIO(data), "shot.png"),
            },
            environ_base=LOOPBACK,
            content_type="multipart/form-data",
        )
        assert response.status_code == 200
        task = client.get(f"/api/tasks/{task_id}", environ_base=LOOPBACK).get_json()[
            "task"
        ]
        return task["result"].get("images", [])

    def test_an_image_that_contains_the_bytes_reaches_the_agent(
        self, client: FlaskClient
    ) -> None:
        assert len(self.submit(client, "r869-kept", image(b"<?=", "middle"))) == 1

    def test_an_image_that_carries_a_tag_does_not(self, client: FlaskClient) -> None:
        assert self.submit(client, "r869-dropped", image(b"<?=$x", "middle")) == []


# --------------------------------------------------------------------------- the checker's own cases


class TestTheModelItself:
    @pytest.mark.parametrize(
        ("source", "expected"),
        [
            ("ab", [("a", 1, 1), ("b", 1, 1)]),
            ("a*b+c?", [("a", 0, None), ("b", 1, None), ("c", 0, 1)]),
            (
                "a{3}b{2,5}c{1,}",
                [("a", 3, 3), ("b", 2, 5), ("c", 1, None)],
            ),
            (r"\s+\(\.", [(r"\s", 1, None), (r"\(", 1, 1), (r"\.", 1, 1)]),
            (r"\x41z", [(r"\x41", 1, 1), ("z", 1, 1)]),
            ("[^>]*>", [("[^>]", 0, None), (">", 1, 1)]),
            ("[A-Za-z_]x", [("[A-Za-z_]", 1, 1), ("x", 1, 1)]),
            (r"[^`\r\n]{1,100}`", [(r"[^`\r\n]", 1, 100), ("`", 1, 1)]),
            ("[]a]b", [("[]a]", 1, 1), ("b", 1, 1)]),
            ("[^]a]b", [("[^]a]", 1, 1), ("b", 1, 1)]),
        ],
    )
    def test_pieces(
        self, source: str, expected: list[tuple[str, int, int | None]]
    ) -> None:
        assert pieces(source) == expected

    @pytest.mark.parametrize(
        ("source", "reason"),
        [
            ("(a)", "'('"),
            ("a|b", "'|'"),
            ("^a", "'^'"),
            ("a$", "'$'"),
            ("*a", "nothing to repeat"),
            ("[ab", "unterminated class"),
            ("a*?", "lazy or possessive"),
            ("a++", "lazy or possessive"),
            ("a{2}?", "lazy or possessive"),
        ],
    )
    def test_what_it_cannot_read_is_an_error_not_a_guess(
        self, source: str, reason: str
    ) -> None:
        with pytest.raises(UnreadablePattern, match=re.escape(reason)):
            pieces(source)

    @pytest.mark.parametrize(
        ("pattern", "expected"),
        [
            (rb"<", 1 / 256),
            (rb"12", 1 / 256**2),  # digits have no other case
            (rb"ab", (2 / 256) ** 2),  # letters match in both cases
            (rb"a", 2 / 256),
            (rb"a?b", 2 / 256 + (2 / 256) ** 2),  # "b" or "ab"
            (rb"x\s+", 2 / 256 * 6 / 256),  # more spaces do not make a match likelier
            (rb"\s*a", (2 / 256) / (1 - 6 / 256)),  # but they may come first
            (rb"[^>]*>", 1.0),  # it waits for its ">"
            (rb"[^>]{3}", (255 / 256) ** 3),
            (rb"a{2,3}b", (2 / 256) ** 2 * (2 / 256 + (2 / 256) ** 2)),
            (rb"\(", 1 / 256),
            (rb"<\?=", 1 / 256**3),
            (
                rb"<\?=\s*\$[A-Za-z_]",
                (1 / 256) ** 3 / (1 - 6 / 256) * (1 / 256) * (53 / 256),
            ),
            (
                # the closing back-quote may come after 1 to 100 characters that are none of
                # back-quote, CR, LF: the sum over k of (253/256)**k * (1/256)
                rb"<\?=\s*`[^`\r\n]{1,100}`",
                (1 / 256) ** 3
                / (1 - 6 / 256)
                * (1 / 256)
                * (1 / 256)
                * (253 / 256)
                * (1 - (253 / 256) ** 100)
                / (1 - 253 / 256),
            ),
        ],
    )
    def test_chance_at_a_position(self, pattern: bytes, expected: float) -> None:
        assert chance_at_a_position(pattern) == pytest.approx(expected, rel=1e-6)

    def test_a_pattern_that_matches_nothing_longer_than_nothing_is_certain(
        self,
    ) -> None:
        assert chance_at_a_position(rb"a*") == 1.0
