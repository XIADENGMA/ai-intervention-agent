"""Lexer-level scan of JavaScript / TypeScript source for string literals and comments.

The i18n gates (``check_i18n_js_no_cjk.py``, ``check_i18n_ts_no_cjk.py``) need to
know which text is a string literal and which is a comment. Regexes cannot
tell: ``//`` inside a string looks like a comment, a quote or a backtick inside
a regular expression looks like the start of a string, and every wrong guess
shifts the pairing of all the quotes that follow. This module walks the source
once, the way a tokenizer does:

- ``'...'`` and ``"..."`` strings, with their escapes decoded;
- template literals, one literal per template, ``${...}`` substitutions lexed as
  code (so strings and templates nested inside them are found too);
- regular expression literals (skipped), told apart from division by the token
  before the slash, with the fallback that a regex never spans a line;
- ``//`` and ``/* */`` comments (skipped, or blanked by :func:`blank_comments`).

Decoding the escapes matters: ``"\\u65b0\\u4efb\\u52a1"`` is Chinese text that no
reader and no regex over the source sees.
"""

from __future__ import annotations

import re
from bisect import bisect_right
from dataclasses import dataclass

_TOKEN_RE = re.compile(
    r"""
      (?P<ws>\s+)
    | (?P<line>//[^\n\r\u2028\u2029]*)
    | (?P<block>/\*.*?(?:\*/|\Z))
    | (?P<number>\d[\w.]*)
    | (?P<word>[\w$]+)
    | (?P<quote>['"])
    | (?P<tick>`)
    | (?P<slash>/)
    | (?P<punct>.)
    """,
    re.VERBOSE | re.DOTALL,
)

_EXPRESSION_KEYWORDS = frozenset(
    {
        "await",
        "case",
        "delete",
        "do",
        "else",
        "in",
        "instanceof",
        "new",
        "of",
        "return",
        "throw",
        "typeof",
        "void",
        "yield",
    }
)

_SIMPLE_ESCAPES = {
    "n": "\n",
    "r": "\r",
    "t": "\t",
    "b": "\b",
    "f": "\f",
    "v": "\v",
    "0": "\0",
}
_HEX_DIGITS = frozenset("0123456789abcdefABCDEF")
_LINE_BREAKS = "\n\r\u2028\u2029"


@dataclass(frozen=True)
class Literal:
    """A string or template literal: the 1-based line of its opening quote and its value.

    A template's value shows each substitution as ``${…}``.
    """

    line: int
    text: str
    kind: str


def _hex_run(raw: str, start: int, count: int) -> int | None:
    digits = raw[start : start + count]
    if len(digits) == count and set(digits) <= _HEX_DIGITS:
        return int(digits, 16)
    return None


def _cook(raw: str) -> str:
    """Decode the escape sequences of a string or template body."""
    if "\\" not in raw:
        return raw
    out: list[str] = []
    i = 0
    n = len(raw)
    while i < n:
        ch = raw[i]
        if ch != "\\" or i + 1 >= n:
            out.append(ch)
            i += 1
            continue
        nxt = raw[i + 1]
        if nxt in _SIMPLE_ESCAPES:
            out.append(_SIMPLE_ESCAPES[nxt])
            i += 2
        elif nxt == "x" and (code := _hex_run(raw, i + 2, 2)) is not None:
            out.append(chr(code))
            i += 4
        elif nxt == "u" and raw[i + 2 : i + 3] == "{":
            close = raw.find("}", i + 3)
            code = _hex_run(raw, i + 3, close - i - 3) if close != -1 else None
            if code is not None and code <= 0x10FFFF:
                out.append(chr(code))
                i = close + 1
            else:
                out.append("u")
                i += 2
        elif nxt == "u" and (code := _hex_run(raw, i + 2, 4)) is not None:
            out.append(chr(code))
            i += 6
        elif raw[i + 1 : i + 3] == "\r\n":
            i += 3
        elif nxt in _LINE_BREAKS:
            i += 2
        else:
            out.append(nxt)
            i += 2
    text = "".join(out)
    try:
        return text.encode("utf-16", "surrogatepass").decode("utf-16")
    except UnicodeDecodeError:
        return text


def _end_of_quoted(src: str, start: int) -> tuple[int, int]:
    """Scan a ``'...'`` or ``"..."`` string; return (index after it, index where its body ends).

    A string never spans lines, so an unterminated one ends at its line break.
    """
    quote = src[start]
    n = len(src)
    i = start + 1
    while i < n:
        ch = src[i]
        if ch == "\\":
            i += 3 if src[i + 1 : i + 3] == "\r\n" else 2
            continue
        if ch == quote:
            return i + 1, i
        if ch in "\n\r":
            return i, i
        i += 1
    return n, n


def _end_of_template_text(src: str, start: int) -> tuple[int, int, bool]:
    """Scan template text; return (resume index, body end, a ``${`` substitution follows)."""
    n = len(src)
    i = start
    while i < n:
        ch = src[i]
        if ch == "\\":
            i += 2
            continue
        if ch == "`":
            return i + 1, i, False
        if ch == "$" and src[i + 1 : i + 2] == "{":
            return i + 2, i, True
        i += 1
    return n, n, False


def _end_of_regex(src: str, start: int) -> int | None:
    """Return the index after a regex literal that starts at ``start``, or None."""
    n = len(src)
    i = start + 1
    in_class = False
    while i < n:
        ch = src[i]
        if ch in _LINE_BREAKS:
            return None
        if ch == "\\":
            if src[i + 1 : i + 2] in ("", *_LINE_BREAKS):
                return None
            i += 2
            continue
        if in_class:
            in_class = ch != "]"
        elif ch == "[":
            in_class = True
        elif ch == "/":
            i += 1
            while i < n and src[i].isalpha():
                i += 1
            return i
        i += 1
    return None


def _walk(src: str) -> tuple[list[tuple[int, str, str]], list[tuple[int, int]]]:
    """Return (literals, comment spans).

    A literal is ``(start, kind, text)`` with kind ``"string"`` or ``"template"``;
    a template's text shows each substitution as ``${…}``. A comment span is
    ``(start, end)``.
    """
    literals: list[tuple[int, str, str]] = []
    comments: list[tuple[int, int]] = []
    open_templates: list[list] = []
    n = len(src)
    pos = 0
    ends_operand = False
    after_dot = False

    def read_template_text(start: int) -> int:
        nonlocal ends_operand
        resume, body_end, substitution = _end_of_template_text(src, start)
        template = open_templates[-1]
        template[1].append(_cook(src[start:body_end]))
        if substitution:
            template[2] = 0
            ends_operand = False
        else:
            open_templates.pop()
            literals.append((template[0], "template", "${…}".join(template[1])))
            ends_operand = True
        return resume

    if src.startswith("#!"):
        newline = src.find("\n")
        pos = n if newline == -1 else newline
        comments.append((0, pos))

    while pos < n:
        match = _TOKEN_RE.match(src, pos)
        if match is None:
            break
        kind = match.lastgroup
        start, end = match.span()
        pos = end
        if kind == "ws":
            continue
        if kind in ("line", "block"):
            comments.append((start, end))
            continue
        property_name, after_dot = after_dot, False
        if kind == "word":
            ends_operand = property_name or match.group() not in _EXPRESSION_KEYWORDS
        elif kind == "number":
            ends_operand = True
        elif kind == "quote":
            pos, body_end = _end_of_quoted(src, start)
            literals.append((start, "string", _cook(src[start + 1 : body_end])))
            ends_operand = True
        elif kind == "tick":
            open_templates.append([start, [], 0])
            pos = read_template_text(start + 1)
        elif kind == "slash":
            regex_end = None if ends_operand else _end_of_regex(src, start)
            if regex_end is None:
                ends_operand = False
            else:
                pos = regex_end
                ends_operand = True
        else:
            char = match.group()
            if char == ".":
                after_dot = True
                ends_operand = False
            elif char in "+-" and src[end : end + 1] == char:
                pos = end + 1
            elif char == "{":
                if open_templates:
                    open_templates[-1][2] += 1
                ends_operand = False
            elif char == "}":
                if open_templates and open_templates[-1][2] == 0:
                    pos = read_template_text(end)
                else:
                    if open_templates:
                        open_templates[-1][2] -= 1
                    ends_operand = False
            else:
                ends_operand = char in ")]"
    while open_templates:
        template = open_templates.pop()
        literals.append((template[0], "template", "${…}".join(template[1])))
    literals.sort(key=lambda item: item[0])
    return literals, comments


def string_literals(src: str) -> list[Literal]:
    """Return every string and template literal of ``src`` in source order."""
    found, _comments = _walk(src)
    newlines = [i for i, ch in enumerate(src) if ch == "\n"]
    return [
        Literal(bisect_right(newlines, start - 1) + 1, text, kind)
        for start, kind, text in found
    ]


def blank_comments(src: str) -> str:
    """Replace every comment with spaces, keeping line breaks and all offsets."""
    _found, comments = _walk(src)
    out: list[str] = []
    cursor = 0
    for start, end in comments:
        out.append(src[cursor:start])
        out.append("".join(ch if ch in "\n\r" else " " for ch in src[start:end]))
        cursor = end
    out.append(src[cursor:])
    return "".join(out)
