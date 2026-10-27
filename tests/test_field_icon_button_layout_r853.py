"""R853: an icon button beside a text field keeps its size - the generic ``.btn`` no longer overrules it.

The settings panel of the Web UI has two rows made of a text field and a small square button
beside it: the config file path with its "open in IDE" button, and (since R852) the Device Key
with its show/hide eye.  Both buttons are ``.btn`` - that is what gives them the button
colours, the focus ring and the press feedback - and the config path one was sized by a rule
with a single class, ``.config-path-open-btn``.  The generic ``.btn`` block further down
``main.css`` has a single class as well: same specificity, later in the file, so it won.  On a
desktop the "icon button" came out as the 130 x 52 px pill every other ``.btn`` is, and in a
window 768 px wide or narrower - where ``.btn`` is ``width: 100%`` - it took the whole row and
squeezed the path field to 34 px (measured in Chrome 156 at 1000, 768 and 390 px).  The Device
Key's eye had been written against that cascade, with three classes, and was fine.

Now both rows share one set of rules, and the button rules carry three classes.

A browser is the judge of a layout, and this was checked in one.  What a test can do is keep
the cascade that decided it from drifting back, and for that it reads ``main.css`` and
``main.min.css`` the way the cascade does, for the real elements of ``web_ui.html``: selectors
with their specificity and their place in the file, ``!important``, media queries at several
widths with and without a touch pointer, and ``margin`` / ``padding`` / ``flex`` / ``gap``
beside their longhands.  The model was compared with ``getComputedStyle`` in Chrome on the old
and on the new stylesheet and agreed on every value.  It is strict on purpose: a selector, a
media query or a property it cannot judge - on a rule that could apply to these elements -
raises ``Unsupported`` instead of being guessed at, so an edit that outgrows the model fails
here and the model gets taught, rather than the test going quietly blind.

The model's own behaviour is tested first, because everything after it leans on it.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass
from functools import cache, cached_property
from html.parser import HTMLParser
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "src" / "ai_intervention_agent"
WEB_HTML = WEB / "templates" / "web_ui.html"
STYLESHEETS = {
    "main.css": WEB / "static" / "css" / "main.css",
    "main.min.css": WEB / "static" / "css" / "main.min.css",
}

# --------------------------------------------------------------------------- the cascade model


class Unsupported(Exception):
    """A selector, media query or property the model cannot judge, on a rule that could apply."""


@dataclass(frozen=True)
class Element:
    tag: str
    classes: frozenset[str]
    attrs: tuple[tuple[str, str | None], ...] = ()
    ancestors: tuple[Element, ...] = ()  # nearest first

    def attr(self, name: str) -> str | None:
        return dict(self.attrs).get(name)

    def has(self, name: str) -> bool:
        return name in dict(self.attrs)


def el(spec: str) -> Element:
    """``el("button.go#x[disabled] < div.row < section")``: an element, then what it sits in, nearest first."""
    chain: list[Element] = []
    for text in reversed(spec.split(" < ")):
        m = re.fullmatch(r"([a-z0-9]*)((?:[.#][\w-]+|\[[\w-]+(?:=[^\]]*)?\])*)", text)
        assert m, f"bad element spec {text!r}"
        classes = frozenset(re.findall(r"\.([\w-]+)", m.group(2)))
        attrs = [("id", i) for i in re.findall(r"#([\w-]+)", m.group(2))]
        for name, _, value in re.findall(r"\[([\w-]+)(=([^\]]*))?\]", m.group(2)):
            attrs.append((name, value or None))
        chain.append(
            Element(m.group(1) or "div", classes, tuple(attrs), tuple(reversed(chain)))
        )
    return chain[-1]


Compound = tuple[str | None, tuple[str, ...]]
Cascade = tuple[int, tuple[int, int, int], int]  # important, specificity, source order

PART = r"[.#][\w-]+|\[[^\]]+\]|::?[\w-]+(?:\([^)]*\))?"
COMPOUND = re.compile(rf"(?P<tag>[a-zA-Z][\w-]*|\*)?(?P<rest>(?:{PART})*)")
ATTR = re.compile(
    r"""\[\s*([\w-]+)\s*(?:(=)\s*(?:"([^"]*)"|'([^']*)'|([^\]\s]+)))?\s*\]"""
)
AT_REST = frozenset(
    {"hover", "active", "focus", "focus-visible", "focus-within", "visited"}
)

SIDES = ("top", "right", "bottom", "left")
# longhand -> (shorthand, position in the shorthand's expansion)
LONGHANDS = {
    **{f"margin-{side}": ("margin", i) for i, side in enumerate(SIDES)},
    **{f"padding-{side}": ("padding", i) for i, side in enumerate(SIDES)},
    "flex-grow": ("flex", 0),
    "flex-shrink": ("flex", 1),
    "flex-basis": ("flex", 2),
    "row-gap": ("gap", 0),
    "column-gap": ("gap", 1),
}
# Other spellings of the same things (logical properties, single corners) are not modelled, so a
# rule that sets one of them on an element under test is refused rather than ignored.
NOT_MODELLED = frozenset(
    {"all", "inline-size", "min-inline-size", "max-inline-size"}
    | {f"{b}-{a}{p}" for b in ("margin", "padding") for a in ("inline", "block") for p in ("", "-start", "-end")}
    | {f"border-{y}-{x}-radius" for y in ("top", "bottom", "start", "end") for x in ("left", "right", "start", "end")}
)  # fmt: skip


@dataclass
class Rule:
    order: int
    media: str | None
    selector: str
    decls: dict[str, tuple[str, bool]]  # property -> (value, !important)
    compounds: list[Compound]
    joins: list[str]  # joins[i] sits between compounds[i] and compounds[i + 1]
    specificity: tuple[int, int, int]


class Rules(list[Rule]):
    @cached_property
    def declaring(self) -> dict[str, list[Rule]]:
        """The rules that declare each property: resolving one property looks at these only."""
        index: dict[str, list[Rule]] = {}
        for rule in self:
            for name in rule.decls:
                index.setdefault(name, []).append(rule)
        return index


def _split_top(text: str, sep: str) -> list[str]:
    parts: list[str] = []
    depth = 0
    cur = ""
    for ch in text:
        if ch in "([":
            depth += 1
        elif ch in ")]":
            depth -= 1
        if ch == sep and depth == 0:
            parts.append(cur)
            cur = ""
        else:
            cur += ch
    return [*parts, cur]


def _blocks(text: str) -> Iterator[tuple[str, str]]:
    """Top-level ``prelude { body }`` pairs; a ``@layer a, b;`` statement is not part of a prelude."""
    depth = 0
    start = 0
    prelude = ""
    body_start = 0
    for i, ch in enumerate(text):
        if ch == "{":
            if depth == 0:
                before = text[start:i]
                prelude = re.sub(r"^(?:\s*@[\w-]+[^;{}]*;)+", "", before).strip()
                body_start = i + 1
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                yield prelude, text[body_start:i]
                start = i + 1


def _declarations(body: str) -> dict[str, tuple[str, bool]]:
    out: dict[str, tuple[str, bool]] = {}
    for part in body.split(";"):
        if ":" not in part:
            continue
        name, value = part.split(":", 1)
        value = value.strip()
        important = re.search(r"!\s*important\s*$", value) is not None
        value = re.sub(r"\s*!\s*important\s*$", "", value)
        out[name.strip().lower()] = (re.sub(r"\s+", " ", value), important)
    return out


def _tokenize(selector: str) -> tuple[list[Compound], list[str]]:
    """The compounds of ``selector`` and the combinators between them (space, ``>``, ``+``, ``~``)."""
    compounds: list[Compound] = []
    joins: list[str] = []
    depth = 0
    cur = ""
    pending: str | None = None

    def flush() -> None:
        nonlocal cur, pending
        if cur:
            m = COMPOUND.fullmatch(cur)
            if not m:
                raise Unsupported(f"selector part {cur!r}")
            if compounds:
                joins.append(pending or " ")
            tag = m.group("tag")
            compounds.append(
                (
                    None if tag in (None, "*") else tag,
                    tuple(re.findall(PART, m.group("rest"))),
                )
            )
            cur = ""
            pending = None

    for ch in selector.strip():
        if ch in "([":
            depth += 1
        elif ch in ")]":
            depth -= 1
        if depth == 0 and ch in " \t\n>+~":
            flush()
            pending = ch if ch in ">+~" else pending
            continue
        cur += ch
    flush()
    if not compounds:
        raise Unsupported(f"selector {selector!r}")
    return compounds, joins


def _specificity(compounds: list[Compound]) -> tuple[int, int, int]:
    ids = classes = tags = 0
    for tag, parts in compounds:
        tags += 1 if tag else 0
        for part in parts:
            if part.startswith("#"):
                ids += 1
            elif part.startswith("::") or part in (":before", ":after"):
                tags += 1
            else:
                classes += 1
    return ids, classes, tags


def parse(css: str) -> tuple[Rules, list[str]]:
    """The style rules in source order, media blocks flattened, and the other at-rule blocks skipped."""
    rules = Rules()
    skipped: list[str] = []

    def walk(text: str, media: str | None) -> None:
        for prelude, body in _blocks(text):
            if prelude.startswith("@media"):
                walk(body, prelude[len("@media") :].strip())
            elif prelude.startswith("@"):
                skipped.append(f"{prelude}{{{body}}}")
            else:
                decls = _declarations(body)
                for selector in _split_top(prelude, ","):
                    compounds, joins = _tokenize(selector)
                    spec = _specificity(compounds)
                    rule = Rule(
                        len(rules) + 1,
                        media,
                        selector.strip(),
                        decls,
                        compounds,
                        joins,
                        spec,
                    )
                    rules.append(rule)

    walk(re.sub(r"/\*.*?\*/", "", css, flags=re.S), None)
    return rules, skipped


def _compound_matches(
    tag: str | None, parts: tuple[str, ...], node: Element
) -> bool | None:
    """False if a part rules the element out, None if only parts the model cannot judge are left."""
    if tag is not None and tag != node.tag:
        return False
    unsure = False
    for part in parts:
        if part.startswith("."):
            if part[1:] not in node.classes:
                return False
        elif part.startswith("#"):
            if node.attr("id") != part[1:]:
                return False
        elif part.startswith("["):
            m = ATTR.fullmatch(part)
            if not m:
                unsure = True
                continue
            name, op, *quoted = m.groups()
            value = next((v for v in quoted if v is not None), None)
            if (op is None and not node.has(name)) or (op and node.attr(name) != value):
                return False
        elif part.startswith("::") or part in (":before", ":after"):
            return False  # styles a pseudo-element, not the element itself
        else:
            name = part[1:].split("(")[0]
            if name == "disabled":
                if not node.has("disabled"):
                    return False
            elif name == "root":
                if node.tag != "html":
                    return False
            elif name in AT_REST:
                return False  # the layout under test is the one at rest
            else:
                unsure = True
    return None if unsure else True


def _both(x: bool | None, y: bool | None) -> bool | None:
    if x is False or y is False:
        return False
    return None if (x is None or y is None) else True


def matches(rule: Rule, target: Element) -> bool:
    """Whether the rule's selector matches ``target``; ``Unsupported`` if that cannot be decided."""

    def ok(index: int, node: Element, chain: tuple[Element, ...]) -> bool | None:
        tag, parts = rule.compounds[index]
        here = _compound_matches(tag, parts, node)
        if here is False or index == 0:
            return here
        join = rule.joins[index - 1]
        if join in "+~":
            return _both(here, None)  # siblings are not modelled
        if join == ">":
            return _both(here, ok(index - 1, chain[0], chain[1:]) if chain else False)
        found = [ok(index - 1, chain[i], chain[i + 1 :]) for i in range(len(chain))]
        return _both(
            here, True if True in found else (None if None in found else False)
        )

    state = ok(len(rule.compounds) - 1, target, target.ancestors)
    if state is None:
        raise Unsupported(
            f"{rule.selector!r} on <{target.tag}>: part of it is outside the model"
        )
    return state


def media_applies(cond: str, width: int, touch: bool) -> bool:
    """Whether the media query holds for a window ``width`` px wide (``touch``: no hover, coarse pointer)."""
    for alternative in _split_top(cond, ","):
        holds = True
        for term in re.findall(r"\([^)]*\)|[A-Za-z-]+", alternative):
            term = re.sub(r"\s+", "", term)
            m = re.fullmatch(r"\((max|min)-width:([\d.]+)px\)", term)
            if term in ("screen", "all", "and"):
                continue
            if term == "print":
                holds = False
            elif m:
                limit = float(m.group(2))
                holds = holds and (
                    width <= limit if m.group(1) == "max" else width >= limit
                )
            elif term in ("(hover:none)", "(pointer:coarse)"):
                holds = holds and touch
            elif term in ("(hover:hover)", "(pointer:fine)"):
                holds = holds and not touch
            else:
                raise Unsupported(f"media query {cond!r}")
        if holds:
            return True
    return False


def _expand(shorthand: str, value: str) -> list[str] | None:
    """The longhand values of a ``margin`` / ``padding`` / ``gap`` / ``flex`` shorthand (None: not understood)."""
    tokens = value.split(" ")
    if shorthand in ("margin", "padding"):
        order = {1: (0, 0, 0, 0), 2: (0, 1, 0, 1), 3: (0, 1, 2, 1), 4: (0, 1, 2, 3)}
        return [tokens[i] for i in order[len(tokens)]] if len(tokens) in order else None
    if shorthand == "gap":
        return (
            tokens * 2 if len(tokens) == 1 else (tokens if len(tokens) == 2 else None)
        )
    number = re.compile(r"[\d.]+")
    words = {
        "none": ["0", "0", "auto"],
        "auto": ["1", "1", "auto"],
        "initial": ["0", "1", "auto"],
    }
    if len(tokens) == 1:
        if tokens[0] in words:
            return words[tokens[0]]
        return (
            [tokens[0], "1", "0%"]
            if number.fullmatch(tokens[0])
            else ["1", "1", tokens[0]]
        )
    if len(tokens) == 2:
        return (
            [*tokens, "0%"]
            if number.fullmatch(tokens[1])
            else [tokens[0], "1", tokens[1]]
        )
    return tokens if len(tokens) == 3 else None


def declared(
    rules: Rules, target: Element, prop: str, width: int, touch: bool
) -> list[tuple[Cascade, str]]:
    """Every declaration that applies to ``target`` and sets ``prop`` (a shorthand counts for its longhands)."""
    shorthand, index = LONGHANDS.get(prop, ("", 0))
    names = {prop, shorthand, *NOT_MODELLED} - {""}
    candidates = {
        rule.order: rule for name in names for rule in rules.declaring.get(name, [])
    }
    found: list[tuple[Cascade, str]] = []
    for _, rule in sorted(candidates.items()):
        if not matches(rule, target):
            continue
        if rule.media is not None and not media_applies(rule.media, width, touch):
            continue
        if risky := NOT_MODELLED & rule.decls.keys():
            raise Unsupported(
                f"{rule.selector!r} sets {sorted(risky)}, which the model does not read"
            )
        for name in (prop, shorthand):
            if name and name in rule.decls:
                value, important = rule.decls[name]
                if name != prop:
                    parts = _expand(shorthand, value)
                    if parts is None:
                        raise Unsupported(f"{rule.selector!r}: {name}: {value}")
                    value = parts[index]
                found.append(
                    ((1 if important else 0, rule.specificity, rule.order), value)
                )
    return found


def resolve(
    rules: Rules, target: Element, prop: str, width: int, touch: bool = False
) -> str | None:
    """The value ``prop`` ends up with on ``target`` in a window ``width`` px wide (None: no rule sets it)."""
    found = declared(rules, target, prop, width, touch)
    return max(found, key=lambda pair: pair[0])[1] if found else None


# --------------------------------------------------------------------------- the markup

VOID_TAGS = frozenset(
    {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta"}
    | {"source", "track", "wbr"}
)


class Node:
    def __init__(
        self, tag: str, attrs: list[tuple[str, str | None]], parent: Node | None
    ) -> None:
        self.tag = tag
        self.attrs = tuple(attrs)
        self.parent = parent
        self.children: list[Node] = []

    def get(self, name: str) -> str | None:
        return dict(self.attrs).get(name)

    @property
    def classes(self) -> frozenset[str]:
        return frozenset((self.get("class") or "").split())

    def descendants(self) -> Iterator[Node]:
        for child in self.children:
            yield child
            yield from child.descendants()

    def element(self) -> Element:
        chain: list[Element] = []
        node = self.parent
        while node is not None and node.tag != "#root":
            chain.append(Element(node.tag, node.classes, node.attrs))
            node = node.parent
        return Element(self.tag, self.classes, self.attrs, tuple(chain))


class Page(HTMLParser):
    def __init__(self, markup: str) -> None:
        super().__init__(convert_charrefs=True)
        self.root = Node("#root", [], None)
        self.by_id: dict[str, Node] = {}
        self._open = self.root
        self.feed(markup)
        self.close()

    def _add(self, tag: str, attrs: list[tuple[str, str | None]]) -> Node:
        node = Node(tag, attrs, self._open)
        self._open.children.append(node)
        if node_id := node.get("id"):
            self.by_id[node_id] = node
        return node

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        node = self._add(tag, attrs)
        if tag not in VOID_TAGS:
            self._open = node

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._add(tag, attrs)

    def handle_endtag(self, tag: str) -> None:
        node: Node | None = self._open
        while node is not None and node is not self.root and node.tag != tag:
            node = node.parent
        if node is not None and node is not self.root and node.parent is not None:
            self._open = node.parent

    def get(self, element_id: str) -> Node:
        assert element_id in self.by_id, f"#{element_id} is not in the markup"
        return self.by_id[element_id]


@cache
def page() -> Page:
    return Page(WEB_HTML.read_text(encoding="utf-8"))


@cache
def stylesheet(name: str) -> tuple[Rules, list[str]]:
    return parse(STYLESHEETS[name].read_text(encoding="utf-8"))


# --------------------------------------------------------------------------- the rows


@dataclass(frozen=True)
class Row:
    name: str
    field: str  # id of the text field
    button: str  # id of the icon button beside it
    row_class: str


ROWS = (
    Row(
        "config file path",
        "config-file-path",
        "open-config-file-btn",
        "config-path-row",
    ),
    Row("Device Key", "bark-device-key", "bark-device-key-toggle", "secret-field-row"),
)
ROW_IDS = [row.name for row in ROWS]

# wide to narrow, either side of both breakpoints (768 and 480), with and without a touch pointer
PROFILES = [
    (w, t) for w in (1280, 1000, 769, 768, 481, 480, 390, 320) for t in (False, True)
]
CHECKED = (
    "width", "min-width", "min-height", "height", "display", "align-items", "justify-content",
    "border-radius", "flex-grow", "flex-shrink", "flex-basis", "column-gap",
    *(f"{box}-{side}" for box in ("padding", "margin") for side in SIDES),
)  # fmt: skip


@dataclass(frozen=True)
class Parts:
    """The elements of one row, as the cascade sees them."""

    row: Element
    field: Element
    button: Element
    icons: tuple[Element, ...]
    alone: Element  # the same field if it stood in the setting item by itself

    @property
    def all(self) -> tuple[Element, ...]:
        return (self.row, self.field, self.button, self.alone, *self.icons)


def parts_of(row: Row) -> Parts:
    field, button = page().get(row.field), page().get(row.button)
    holder = field.element().ancestors[0]
    assert row.row_class in holder.classes, (
        f"#{row.field} is not inside .{row.row_class}"
    )
    svgs = [
        n for n in button.descendants() if n.tag == "svg" and "btn-icon" in n.classes
    ]
    alone = Element(
        "input", frozenset({"setting-input"}), field.element().attrs, holder.ancestors
    )
    return Parts(
        holder,
        field.element(),
        button.element(),
        tuple(n.element() for n in svgs),
        alone,
    )


def number(value: str | None) -> float | None:
    """A bare number (``0``, ``1``, ``0.5``); None for anything else."""
    return float(value) if value and re.fullmatch(r"\d*\.?\d+", value) else None


def px(value: str | None) -> float | None:
    """A length in pixels (16 to the rem and the em); None for auto, a percentage, calc()..."""
    m = re.fullmatch(r"(-?\d*\.?\d+)(px|rem|em)?", (value or "").strip())
    if not m or (m.group(2) is None and float(m.group(1)) != 0):
        return None
    return float(m.group(1)) * (16 if m.group(2) in ("rem", "em") else 1)


@dataclass(frozen=True)
class Window:
    """A browser window of a given width and pointer, over a stylesheet."""

    rules: Rules
    width: int
    touch: bool

    def __str__(self) -> str:
        return f"{self.width}px{' touch' if self.touch else ''}"

    def get(self, target: Element, prop: str) -> str | None:
        return resolve(self.rules, target, prop, self.width, self.touch)

    def faults(self, parts: Parts) -> list[str]:
        """What is wrong with the text field and its icon button in this window."""
        g, row, field, button = self.get, parts.row, parts.field, parts.button
        out: list[str] = []
        if g(button, "width") not in (None, "auto"):
            out.append(
                f"the button is width {g(button, 'width')}: it takes the row, the field gets what is left"
            )
        for prop, limit in (
            ("min-width", 48),
            ("padding-left", 16),
            ("padding-right", 16),
        ):
            if (length := px(g(button, prop))) is None or length > limit:
                out.append(
                    f"the button's {prop} is {g(button, prop)}; an icon button needs at most {limit}px"
                )
        flex = [g(button, f"flex-{part}") for part in ("grow", "shrink", "basis")]
        if flex != ["0", "0", "auto"]:
            out.append(
                f"the button's flex is {' '.join(map(str, flex))}; it must keep its own size (0 0 auto)"
            )
        centred = all(
            g(button, p) == "center" for p in ("align-items", "justify-content")
        )
        if g(button, "display") not in ("flex", "inline-flex") or not centred:
            out.append(
                f"the button does not centre its icon (display {g(button, 'display')})"
            )
        if g(button, "border-radius") != g(field, "border-radius"):
            out.append(
                f"the button's corners ({g(button, 'border-radius')}) differ from the field's ({g(field, 'border-radius')})"
            )
        if (number(g(field, "flex-grow")) or 0) < 1 or px(g(field, "min-width")) != 0:
            out.append(
                f"the field must grow and may shrink (flex-grow {g(field, 'flex-grow')}, min-width {g(field, 'min-width')})"
            )
        if px(g(field, "margin-top")) != 0:
            out.append(
                f"the field has its own top margin ({g(field, 'margin-top')}); the row carries it, or the stretched button starts above the field"
            )
        if g(row, "margin-top") is None or g(row, "margin-top") != g(
            parts.alone, "margin-top"
        ):
            out.append(
                f"the row's top margin ({g(row, 'margin-top')}) is not what a lone field gets ({g(parts.alone, 'margin-top')})"
            )
        gap = px(g(row, "column-gap"))
        stretched = g(row, "align-items") in (None, "normal", "stretch")
        if (
            g(row, "display") != "flex"
            or not stretched
            or gap is None
            or not 4 <= gap <= 16
        ):
            out.append(
                f"the row must be a flex row that stretches its items with a 4-16px gap (display {g(row, 'display')}, align-items {g(row, 'align-items')}, gap {g(row, 'column-gap')})"
            )
        for icon in parts.icons:
            if px(g(icon, "margin-right")) != 0:
                out.append(
                    f"the icon keeps a margin-right of {g(icon, 'margin-right')} and sits off the button's centre"
                )
            if g(icon, "width") is None or g(icon, "width") != g(icon, "height"):
                out.append(
                    f"the icon is {g(icon, 'width')} x {g(icon, 'height')}, not square"
                )
        return out


def layout_problems(
    rules: Rules, parts: Parts, profiles: list[tuple[int, bool]] = PROFILES
) -> list[str]:
    """One line per fault and window of a text field with an icon button beside it."""
    problems = [] if parts.icons else ["the button has no .btn-icon svg"]
    for width, touch in profiles:
        window = Window(rules, width, touch)
        problems += [f"{window}: {line}" for line in window.faults(parts)]
    return problems


SKIPPED_ON_PURPOSE = ("@keyframes", "@supports", "@layer a11y")
RESOLVED = set(CHECKED) | set(LONGHANDS) | {"margin", "padding", "flex", "gap"}


def unread_problems(skipped: list[str]) -> list[str]:
    """What the model skips that it should not: an at-rule it does not know, or one that sets what it resolves."""
    problems: list[str] = []
    for block in skipped:
        if not block.startswith(SKIPPED_ON_PURPOSE):
            problems.append(
                f"the model does not read {block[:60]!r}; teach it or allow it on purpose"
            )
        elif not block.startswith("@keyframes"):
            sets = set(re.findall(r"(?<![\w-])([a-z-]+)\s*:", block)) & RESOLVED
            if sets:
                problems.append(
                    f"{block[:40]!r} is skipped and sets {sorted(sets)}, which the model resolves"
                )
    return problems


# ===================================================================== the model, on its own

# id, css, element (then what it sits in, nearest first), property, window width, touch, expected
RESOLUTIONS = [
    ("class beats tag", "div{width:1px} .a{width:2px}", "div.a", "width", 1000, False, "2px"),
    ("two classes beat one", ".a.b{width:1px} .a{width:2px}", "div.a.b", "width", 1000, False, "1px"),
    ("id beats classes", "#x{width:1px} .a.b.c{width:2px}", "div#x.a.b.c", "width", 1000, False, "1px"),
    ("tag matches", "input{width:1px} div{width:2px}", "input", "width", 1000, False, "1px"),
    ("nothing sets it", ".a{width:1px}", "div.b", "width", 1000, False, None),
    ("equal: the later wins", ".a{width:1px} .b{width:2px}", "div.a.b", "width", 1000, False, "2px"),
    ("equal: the later wins, other order", ".b{width:2px} .a{width:1px}", "div.a.b", "width", 1000, False, "1px"),
    ("an attribute counts as a class", '.a{width:1px} [data-k="v"]{width:2px}', "div.a[data-k=v]", "width", 1000, False, "2px"),
    ("another attribute value", '.a{width:1px} [data-k="v"]{width:2px}', "div.a[data-k=w]", "width", 1000, False, "1px"),
    ("a present attribute", "[disabled]{width:1px}", "button[disabled]", "width", 1000, False, "1px"),
    ("an absent attribute", "[disabled]{width:1px}", "button", "width", 1000, False, None),
    (":disabled", ".a:disabled{width:1px}", "button.a[disabled]", "width", 1000, False, "1px"),
    (":disabled, not disabled", ".a:disabled{width:1px}", "button.a", "width", 1000, False, None),
    ("!important beats specificity", ".a{width:1px!important} #x.a{width:2px}", "div#x.a", "width", 1000, False, "1px"),
    ("media: wide", ".a{width:1px} @media (max-width: 768px){.a{width:2px}}", "div.a", "width", 1000, False, "1px"),
    ("media: 769", ".a{width:1px} @media (max-width: 768px){.a{width:2px}}", "div.a", "width", 769, False, "1px"),
    ("media: 768", ".a{width:1px} @media (max-width: 768px){.a{width:2px}}", "div.a", "width", 768, False, "2px"),
    ("media: nested breakpoints", ".a{width:1px} @media (max-width:768px){.a{width:2px}} @media (max-width:480px){.a{width:3px}}", "div.a", "width", 480, False, "3px"),
    ("media: min-width, below", ".a{width:1px} @media (min-width: 600px){.a{width:2px}}", "div.a", "width", 599, False, "1px"),
    ("media: min-width, at", ".a{width:1px} @media (min-width: 600px){.a{width:2px}}", "div.a", "width", 600, False, "2px"),
    ("media: print never applies", ".a{width:1px} @media print{.a{width:2px}}", "div.a", "width", 320, False, "1px"),
    ("media: touch alternative, mouse", ".a{width:1px} @media (max-width: 768px), (hover: none) and (pointer: coarse){.a{width:2px}}", "div.a", "width", 1000, False, "1px"),
    ("media: touch alternative, touch", ".a{width:1px} @media (max-width: 768px), (hover: none) and (pointer: coarse){.a{width:2px}}", "div.a", "width", 1000, True, "2px"),
    ("media: touch alternative, narrow", ".a{width:1px} @media (max-width: 768px), (hover: none) and (pointer: coarse){.a{width:2px}}", "div.a", "width", 700, False, "2px"),
    ("media: minified spacing", ".a{width:1px} @media (max-width:768px),(hover:none) and (pointer:coarse){.a{width:2px}}", "div.a", "width", 1000, True, "2px"),
    ("descendant skips levels", ".wrap .go{width:1px}", "button.go < section.mid < div.wrap", "width", 1000, False, "1px"),
    ("descendant needs the ancestor", ".nope .go{width:1px}", "button.go < section.mid < div.wrap", "width", 1000, False, None),
    ("child needs the parent", ".wrap > .go{width:1px}", "button.go < section.mid < div.wrap", "width", 1000, False, None),
    ("child, the parent", ".mid > .go{width:1px}", "button.go < section.mid < div.wrap", "width", 1000, False, "1px"),
    ("a state at rest never matches", ".a:hover{width:1px} .a:focus-visible{width:2px} .a{width:3px}", "div.a", "width", 1000, False, "3px"),
    ("a pseudo-element is not the element", ".a::before{width:1px} .a{width:2px}", "div.a", "width", 1000, False, "2px"),
    ("an unknown part that cannot matter", ".other:nth-child(2){width:1px} .a{width:3px} :root{width:2px}", "div.a", "width", 1000, False, "3px"),
    ("an id that is not the element's", ".a{width:2px} #x{width:1px}", "div.a", "width", 1000, False, "2px"),
    ("another tag", ".a{width:2px} input{width:1px}", "div.a", "width", 1000, False, "2px"),
    ("a rule for another property", ".a:nth-child(2){height:1px}", "div.a", "width", 1000, False, None),
    ("a later longhand beats a shorthand", ".a{margin:0} .a{margin-top:5px}", "div.a", "margin-top", 1000, False, "5px"),
    ("a later shorthand beats a longhand", ".a{margin-top:5px} .a{margin:0}", "div.a", "margin-top", 1000, False, "0"),
    ("specificity decides between them", ".a.b{margin:7px} div.a{margin-top:5px}", "div.a.b", "margin-top", 1000, False, "7px"),
    ("a reset loses to a class", "*{margin:0} .a{margin-top:5px}", "div.a", "margin-top", 1000, False, "5px"),
    ("padding: one value", ".a{padding:1px}", "div.a", "padding-right", 1000, False, "1px"),
    ("padding: two values", ".a{padding:1px 2px}", "div.a", "padding-left", 1000, False, "2px"),
    ("padding: three values", ".a{padding:1px 2px 3px}", "div.a", "padding-bottom", 1000, False, "3px"),
    ("padding: four values", ".a{padding:1px 2px 3px 4px}", "div.a", "padding-left", 1000, False, "4px"),
    ("gap: one value", ".a{gap:.5rem}", "div.a", "column-gap", 1000, False, ".5rem"),
    ("gap: two values", ".a{gap:1px 2px}", "div.a", "column-gap", 1000, False, "2px"),
    ("gap: a longhand after", ".a{gap:1px 2px} .a{column-gap:9px}", "div.a", "column-gap", 1000, False, "9px"),
    ("flex: three values", ".a{flex:2 3 10px}", "div.a", "flex-shrink", 1000, False, "3"),
    ("flex: none, the basis", ".a{flex:none}", "div.a", "flex-basis", 1000, False, "auto"),
    ("flex: none, it does not shrink", ".a{flex:none}", "div.a", "flex-shrink", 1000, False, "0"),
    ("flex: auto, it grows", ".a{flex:auto}", "div.a", "flex-grow", 1000, False, "1"),
    ("flex: initial, it shrinks", ".a{flex:initial}", "div.a", "flex-shrink", 1000, False, "1"),
    ("flex: one number", ".a{flex:1}", "div.a", "flex-basis", 1000, False, "0%"),
    ("flex: a number and a length", ".a{flex:1 10px}", "div.a", "flex-basis", 1000, False, "10px"),
    ("flex: two numbers", ".a{flex:1 2}", "div.a", "flex-shrink", 1000, False, "2"),
    ("flex: a longhand after", ".a{flex:1 1 auto} .a{flex-shrink:0}", "div.a", "flex-shrink", 1000, False, "0"),
    ("a rule for a logical property elsewhere", ".b{margin-inline:0} .a{width:1px}", "div.a", "width", 1000, False, "1px"),
]  # fmt: skip

# id, css, the property being resolved: rules the model must refuse, because they could apply
# to ``button.a`` and it cannot tell
REFUSALS = [
    ("nth-child", ".a:nth-child(2){width:1px}", "width"),
    ("not()", ".a:not(.b){width:1px}", "width"),
    ("is()", ".a:is(.b, .c){width:1px}", "width"),
    ("adjacent sibling", ".z + .a{width:1px}", "width"),
    ("general sibling", ".z ~ .a{width:1px}", "width"),
    ("a media feature", "@media (prefers-contrast: more){.a{width:1px}}", "width"),
    ("a logical margin", ".a{margin-inline:0}", "width"),
    ("a logical padding", ".a{padding-block-start:1px}", "width"),
    ("a logical size", ".a{inline-size:5px}", "width"),
    ("a single corner", ".a{border-start-start-radius:3px}", "width"),
    ("all", ".a{all:unset}", "width"),
    ("a shorthand it cannot expand", ".a{margin:1px 2px 3px 4px 5px}", "margin-top"),
]  # fmt: skip


def rules_of(css: str) -> Rules:
    return parse(css)[0]


class TestCascadeModel:
    @pytest.mark.parametrize(
        ("css", "spec", "prop", "width", "touch", "expected"),
        [case[1:] for case in RESOLUTIONS],
        ids=[case[0] for case in RESOLUTIONS],
    )
    def test_the_model_resolves(
        self,
        css: str,
        spec: str,
        prop: str,
        width: int,
        touch: bool,
        expected: str | None,
    ) -> None:
        assert resolve(rules_of(css), el(spec), prop, width, touch) == expected

    @pytest.mark.parametrize(
        ("css", "prop"),
        [case[1:] for case in REFUSALS],
        ids=[case[0] for case in REFUSALS],
    )
    def test_what_could_matter_and_cannot_be_judged_is_refused(
        self, css: str, prop: str
    ) -> None:
        with pytest.raises(Unsupported):
            resolve(rules_of(css), el("button.a"), prop, 1000)

    @pytest.mark.parametrize(
        ("blocks", "expected"),
        [
            ([], 0),
            (["@keyframes k{from{width:0}to{width:9px}}"], 0),
            (["@layer a11y{:focus-visible{outline:2px solid red}}"], 0),
            (["@supports (background:color-mix(in srgb,red 50%,blue)){.s{background:red}}"], 0),
            (["@container (min-width:1px){.btn{width:100%}}"], 1),
            (["@layer a11y{.go{min-width:130px}}"], 1),
            (["@supports (display:grid){.btn{padding:1rem}}"], 1),
            (["@layer base{.go{color:red}}"], 1),
            (["@keyframes k{from{width:0}}", "@container (x){.b{width:1px}}"], 1),
        ],
        ids=["none", "keyframes", "a11y outline", "supports colour", "unknown at-rule",
             "layer sets min-width", "supports sets padding", "unknown layer", "one of two"],
    )  # fmt: skip
    def test_the_blocks_the_model_skips_are_judged(
        self, blocks: list[str], expected: int
    ) -> None:
        assert len(unread_problems(blocks)) == expected, unread_problems(blocks)

    def test_the_layer_statement_does_not_swallow_the_next_rule(self) -> None:
        css = "@layer reset, base; .a{width:1px} @keyframes k{from{width:0}to{width:9px}} @layer base{.a{width:2px}} .b{width:3px}"
        rules, skipped = parse(css)
        assert [rule.selector for rule in rules] == [".a", ".b"]
        assert [block.split("{")[0] for block in skipped] == [
            "@keyframes k",
            "@layer base",
        ]

    def test_the_cascade_that_bit_r853_is_reproduced_and_the_fix_is_seen(self) -> None:
        """A one-class component rule above the generic ``.btn``: the icon button became a pill."""
        row_parts = Parts(
            el("div.row < div.setting-item"),
            el("input.setting-input < div.row < div.setting-item"),
            el("button.btn.btn-icon-only.go < div.row < div.setting-item"),
            (
                el(
                    "svg.btn-icon < button.btn.btn-icon-only.go < div.row < div.setting-item"
                ),
            ),
            el("input.setting-input < div.setting-item"),
        )
        button, icon = row_parts.button, row_parts.icons[0]
        common = (
            ".setting-input{width:100%;margin-top:.5rem;border-radius:8px}"
            ".btn-icon{width:1.1em;height:1.1em;margin-right:.4em}"
            ".row{display:flex;align-items:stretch;gap:.5rem;width:100%;margin-top:.5rem}"
            ".row .setting-input{flex:1 1 auto;min-width:0;margin-top:0}"
            ".go .btn-icon{width:1.05rem;height:1.05rem;margin-right:0}"
        )
        generic = (
            ".btn{min-width:130px;padding:1rem 1.75rem;border-radius:20px;display:flex;"
            "align-items:center;justify-content:center}"
            "@media (max-width: 768px){.btn{width:100%}}"
        )
        compact = "flex:0 0 auto;min-width:2.75rem;padding:0 .85rem;border-radius:8px"
        before = rules_of(f"{common} .go{{{compact}}} {generic}")
        after = rules_of(f"{common} {generic} .row .go.btn{{{compact};width:auto}}")
        assert resolve(before, button, "min-width", 1000) == "130px"
        assert resolve(before, button, "padding-left", 1000) == "1.75rem"
        assert resolve(before, button, "width", 768) == "100%"
        assert resolve(before, button, "width", 769) is None
        assert resolve(after, button, "min-width", 1000) == "2.75rem"
        assert resolve(after, button, "padding-left", 1000) == ".85rem"
        assert resolve(after, button, "width", 768) == "auto"
        assert resolve(after, icon, "margin-right", 768) == "0"
        # and the row check tells the two apart
        assert layout_problems(after, row_parts) == []
        found = layout_problems(before, row_parts)
        assert any(
            line.startswith("768px:") and "width 100%" in line for line in found
        ), found
        assert any("min-width is 130px" in line for line in found), found
        assert any("padding-left is 1.75rem" in line for line in found), found
        assert any("corners (20px)" in line for line in found), found
        assert not any(
            line.startswith("1000px:") and "takes the row" in line for line in found
        )


# ===================================================================== the real thing


@pytest.mark.parametrize("name", list(STYLESHEETS))
class TestStylesheets:
    def test_the_whole_stylesheet_is_read(self, name: str) -> None:
        rules, skipped = stylesheet(name)
        # A floor, not an exact count: it only has to notice a read that stops halfway.
        # (839 rules when this was written; deleting a feature's CSS lowers it, 793 after R896.)
        assert len(rules) > 750, f"{name}: only {len(rules)} rules were read"
        assert not unread_problems(skipped), f"{name}: {unread_problems(skipped)}"

    @pytest.mark.parametrize("row", ROWS, ids=ROW_IDS)
    def test_an_icon_button_beside_a_field_keeps_its_size(
        self, name: str, row: Row
    ) -> None:
        problems = layout_problems(stylesheet(name)[0], parts_of(row))
        assert not problems, "\n".join(problems)

    def test_both_rows_are_laid_out_alike(self, name: str) -> None:
        rules = stylesheet(name)[0]
        first, second = (parts_of(row) for row in ROWS)
        for width, touch in PROFILES:
            for what in ("row", "field", "button", "alone"):
                for prop in CHECKED:
                    a = resolve(rules, getattr(first, what), prop, width, touch)
                    b = resolve(rules, getattr(second, what), prop, width, touch)
                    where = f"{width}px{' touch' if touch else ''}: the {what} {prop}"
                    assert a == b, (
                        f"{where} is {a} in the {ROWS[0].name} row and {b} in the {ROWS[1].name} row"
                    )


def test_the_minified_stylesheet_resolves_like_the_source() -> None:
    source, minified = stylesheet("main.css")[0], stylesheet("main.min.css")[0]

    def canon(value: str | None) -> str | None:
        return re.sub(r"(?<![\w.])0\.", ".", value) if value else value

    for row in ROWS:
        for target in parts_of(row).all:
            for width, touch in PROFILES:
                for prop in CHECKED:
                    a = canon(resolve(source, target, prop, width, touch))
                    b = canon(resolve(minified, target, prop, width, touch))
                    assert a == b, (
                        f"{row.name} <{target.tag}> {prop} at {width}px: source {a}, minified {b}"
                    )


@pytest.mark.parametrize("row", ROWS, ids=ROW_IDS)
def test_the_markup_of_a_row(row: Row) -> None:
    field, button = page().get(row.field), page().get(row.button)
    assert field.tag == "input"
    assert button.tag == "button" and button.get("type") == "button"
    assert field.parent is button.parent and field.parent is not None
    assert row.row_class in field.parent.classes
    assert [child.tag for child in field.parent.children] == ["input", "button"]
    # both stay .btn, which is what gives them the button look - the cascade has to cope with it
    assert {"btn", "btn-icon-only"} <= button.classes
    assert "setting-input" in field.classes
