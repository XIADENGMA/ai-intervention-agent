"""R747 invariant: every top-level function, class and class member of the page scripts has a user.

Code that nothing calls is still read, tested and shipped with every page load.
It also misleads: a close-task path that no tab could trigger, a submit-button
helper whose only call had gone, a tooltip builder for a tooltip that was removed,
and in ``validation-utils.js`` a lazy loader, a virtual scroller and two
``debounce`` copies that no script used, kept alive by exports and tests only.

A symbol counts as used when its name appears as a whole word somewhere in the
product's scripts or templates other than:

* its own body, or the body of another symbol with the same name;
* the bodies of symbols that turn out to be unused themselves (so a helper that
  only a dead function calls is reported together with it);
* export lists: ``window.x = x;``, ``module.exports = x;``, and the ``x,`` /
  ``x: x,`` entries of a ``module.exports = {`` / ``window.X = {`` block.

The symbols are the top-level ``function``, ``class`` and ``const x = (...) =>``
declarations that start in column 0, and the methods, accessors and static fields
of the classes among them (``Class.member``).

It is a floor, not a proof. Mentions in comments and strings count, a method name
that another object also has looks used, indented code (inside an IIFE) is not
looked at, and a cluster whose members are all called at load time looks used.
"""

from __future__ import annotations

import re
import unittest
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
PACKAGE = REPO_ROOT / "src" / "ai_intervention_agent"
WEB_JS = PACKAGE / "static" / "js"
VSCODE = REPO_ROOT / "packages" / "vscode"

VENDORED = frozenset({"marked.js", "prism.js", "tex-mml-chtml.js"})

KEPT_ON_PURPOSE = frozenset(
    {
        # The documented surface of the global notification manager; the custom
        # sound contract test calls hasCustomSound.
        "notification-manager.js:NotificationManager.getStatus",
        "notification-manager.js:NotificationManager.hasCustomSound",
    }
)

DECLARATION = re.compile(
    r"^(?:async\s+)?function\s*\*?\s*(?P<function>[A-Za-z_$][\w$]*)\s*\("
    r"|^class\s+(?P<klass>[A-Za-z_$][\w$]*)\b"
    r"|^(?:const|let|var)\s+(?P<arrow>[A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?"
    r"(?:\([^)]*\)|[A-Za-z_$][\w$]*)\s*=>"
    r"|^(?:const|let|var)\s+(?P<anonymous>[A-Za-z_$][\w$]*)\s*=\s*(?:async\s+)?function\b"
)
MEMBER = re.compile(
    r"^  (?:static\s+)?(?:async\s+)?(?:get\s+|set\s+)?(?P<method>[A-Za-z_$][\w$]*)\s*\("
    r"|^  static\s+(?P<field>[A-Za-z_$][\w$]*)\s*="
)
NOT_MEMBERS = frozenset(
    {"constructor", "if", "for", "while", "switch", "catch", "function", "return"}
)
EXPORT_BLOCK_OPEN = re.compile(
    r"^\s*(?:module\.exports|exports|(?:window|globalThis)\.[\w$]+)\s*=\s*\{\s*$"
)
CLOSING_LINE = re.compile(r"^[})\]]")
CLOSING_MEMBER_LINE = re.compile(r"^  [})\]]")
BLOCK_END = re.compile(r"^\s*\};?\s*$")
WORD = re.compile(r"[A-Za-z_$][\w$]*")


@dataclass(frozen=True)
class Symbol:
    name: str
    path: str
    start: int
    end: int
    klass: str = ""
    is_class: bool = False

    @property
    def qualified(self) -> str:
        return f"{self.klass}.{self.name}" if self.klass else self.name


def _ends_on_first_line(line: str) -> bool:
    stripped = line.rstrip()
    return stripped.endswith(";") or (
        stripped.endswith("}") and stripped.count("{") == stripped.count("}")
    )


def _declarations(path: str, lines: list[str]) -> list[Symbol]:
    symbols: list[Symbol] = []
    for index, line in enumerate(lines):
        match = DECLARATION.match(line)
        if match is None:
            continue
        name = next(group for group in match.groups() if group)
        if _ends_on_first_line(line):
            end = index
        else:
            end = next(
                (
                    later
                    for later in range(index + 1, len(lines))
                    if CLOSING_LINE.match(lines[later])
                ),
                len(lines) - 1,
            )
        symbols.append(
            Symbol(name, path, index, end, is_class=match.group("klass") is not None)
        )
    return symbols


def _members(path: str, lines: list[str], klass: Symbol) -> list[Symbol]:
    members: list[Symbol] = []
    for index in range(klass.start + 1, klass.end):
        match = MEMBER.match(lines[index])
        if match is None:
            continue
        name = match.group("method") or match.group("field")
        if name in NOT_MEMBERS:
            continue
        if _ends_on_first_line(lines[index]):
            end = index
        else:
            end = next(
                (
                    later
                    for later in range(index + 1, klass.end + 1)
                    if CLOSING_MEMBER_LINE.match(lines[later])
                ),
                index,
            )
        members.append(Symbol(name, path, index, end, klass=klass.name))
    return members


def _export_block_lines(lines: list[str]) -> set[int]:
    inside: set[int] = set()
    open_block = False
    for index, line in enumerate(lines):
        if open_block:
            if BLOCK_END.match(line):
                open_block = False
            else:
                inside.add(index)
        elif EXPORT_BLOCK_OPEN.match(line):
            open_block = True
    return inside


def _is_export_only(name: str, line: str, in_export_block: bool) -> bool:
    stripped = line.strip()
    escaped = re.escape(name)
    if re.fullmatch(
        rf"(?:window|globalThis)\.{escaped}\s*=\s*{escaped}\s*;?", stripped
    ):
        return True
    if re.fullmatch(
        rf"(?:module\.exports|exports\.[\w$]+)\s*=\s*{escaped}\s*;?", stripped
    ):
        return True
    return (
        in_export_block
        and re.fullmatch(rf"{escaped}\s*(?::\s*{escaped})?\s*,?", stripped) is not None
    )


def _all_symbols(scripts: dict[str, str]) -> list[Symbol]:
    symbols: list[Symbol] = []
    for path, text in scripts.items():
        lines = text.splitlines()
        for symbol in _declarations(path, lines):
            symbols.append(symbol)
            if symbol.is_class:
                symbols.extend(_members(path, lines, symbol))
    return symbols


def find_unused(scripts: dict[str, str], others: dict[str, str]) -> list[str]:
    files = {path: text.splitlines() for path, text in {**scripts, **others}.items()}
    symbols = _all_symbols(scripts)
    owner: dict[tuple[str, int], Symbol] = {}
    for symbol in sorted(symbols, key=lambda s: bool(s.klass)):
        for index in range(symbol.start, symbol.end + 1):
            owner[(symbol.path, index)] = symbol
    export_lines = {path: _export_block_lines(lines) for path, lines in files.items()}
    mentions: dict[str, list[tuple[str, int]]] = {}
    for path, lines in files.items():
        for index, line in enumerate(lines):
            for word in set(WORD.findall(line)):
                mentions.setdefault(word, []).append((path, index))

    dead: set[Symbol] = set()

    def is_used(symbol: Symbol) -> bool:
        for path, index in mentions.get(symbol.name, ()):
            holder = owner.get((path, index))
            if holder is not None and (holder.name == symbol.name or holder in dead):
                continue
            if _is_export_only(
                symbol.name, files[path][index], index in export_lines[path]
            ):
                continue
            return True
        return False

    changed = True
    while changed:
        changed = False
        for symbol in symbols:
            if symbol in dead or is_used(symbol):
                continue
            dead.add(symbol)
            changed = True
            if symbol.is_class:
                dead.update(
                    member
                    for member in symbols
                    if member.klass == symbol.name and member.path == symbol.path
                )
    return sorted(
        f"{s.path}:{s.qualified}"
        for s in dead
        if not any(c.is_class and c.name == s.klass and c.path == s.path for c in dead)
    )


def _read(paths: list[Path]) -> dict[str, str]:
    return {p.name: p.read_text(encoding="utf-8", errors="ignore") for p in paths}


def web_ui_sources() -> tuple[dict[str, str], dict[str, str]]:
    scripts = [
        p
        for p in sorted(WEB_JS.glob("*.js"))
        if not p.name.endswith(".min.js") and p.name not in VENDORED
    ]
    templates = sorted((PACKAGE / "templates").glob("*.html"))
    return _read(scripts), _read(templates)


def vscode_sources() -> tuple[dict[str, str], dict[str, str]]:
    scripts = [p for p in sorted(VSCODE.glob("*.js")) if not p.name.endswith(".min.js")]
    typescript = [
        p for p in sorted(VSCODE.glob("*.ts")) if not p.name.endswith(".d.ts")
    ]
    return _read(scripts), _read(typescript)


def _hint(unused: list[str], where: str) -> str:
    return (
        f"R747 invariant: {where} declares functions, classes or class members that "
        f"nothing uses: {unused}. Delete them (with the tests that only pin them), "
        "or call them; an export list or a test does not make code live."
    )


class TestScriptsHaveNoUnusedSymbols(unittest.TestCase):
    def test_web_ui_scripts(self) -> None:
        unused = [u for u in find_unused(*web_ui_sources()) if u not in KEPT_ON_PURPOSE]
        self.assertEqual(unused, [], _hint(unused, "static/js"))

    def test_vscode_webview_scripts(self) -> None:
        unused = find_unused(*vscode_sources())
        self.assertEqual(unused, [], _hint(unused, "packages/vscode"))

    def test_what_is_kept_on_purpose_is_still_unused(self) -> None:
        unused = set(find_unused(*web_ui_sources()))
        self.assertEqual(
            sorted(KEPT_ON_PURPOSE - unused),
            [],
            "these are used now: take them off KEPT_ON_PURPOSE",
        )

    def test_the_scan_reads_the_scripts_it_should(self) -> None:
        scripts, others = web_ui_sources()
        self.assertIn("app.js", scripts)
        self.assertIn("multi_task.js", scripts)
        self.assertNotIn("prism.js", scripts)
        self.assertNotIn("app.min.js", scripts)
        self.assertIn("web_ui.html", others)
        symbols = _all_symbols(scripts)
        self.assertGreater(len([s for s in symbols if not s.klass]), 200)
        self.assertGreater(len([s for s in symbols if s.klass]), 50)
        names = {s.qualified for s in symbols}
        self.assertIn("submitFeedback", names)
        self.assertIn("DOMSecurity.createCopyButton", names)
        self.assertIn("NotificationManager.getStatus", names)
        vscode_scripts, vscode_others = vscode_sources()
        self.assertIn("webview-ui.js", vscode_scripts)
        self.assertIn("webview.ts", vscode_others)


class TestUnusedSymbolScan(unittest.TestCase):
    def unused(
        self, scripts: dict[str, str], others: dict[str, str] | None = None
    ) -> list[str]:
        return find_unused(scripts, others or {})

    def test_a_function_nothing_mentions_is_reported(self) -> None:
        scripts = {
            "a.js": "function gone() {\n  return 1;\n}\n\nfunction here() {}\nhere();\n"
        }
        self.assertEqual(self.unused(scripts), ["a.js:gone"])

    def test_a_call_from_another_script_or_a_template_counts(self) -> None:
        scripts = {"a.js": "function f() {}\nfunction g() {}\n", "b.js": "f();\n"}
        self.assertEqual(self.unused(scripts, {"p.html": '<a onclick="g()">'}), [])

    def test_recursion_does_not_make_a_function_used(self) -> None:
        scripts = {"a.js": "function again(n) {\n  return n ? again(n - 1) : 0;\n}\n"}
        self.assertEqual(self.unused(scripts), ["a.js:again"])

    def test_export_lists_do_not_make_code_used(self) -> None:
        scripts = {
            "a.js": (
                "function one() {}\nfunction two() {}\nfunction three() {}\n"
                "window.one = one;\n"
                "module.exports = three;\n"
                "window.api = {\n  two,\n  two: two,\n};\n"
            )
        }
        self.assertEqual(self.unused(scripts), ["a.js:one", "a.js:three", "a.js:two"])

    def test_a_consumer_of_an_exported_member_counts(self) -> None:
        scripts = {
            "a.js": "function two() {}\nwindow.api = {\n  two,\n};\n",
            "b.js": "window.api.two();\n",
        }
        self.assertEqual(self.unused(scripts), [])

    def test_a_name_alone_on_a_line_of_a_call_is_a_use(self) -> None:
        scripts = {
            "a.js": (
                "function onTick() {}\n"
                "document.addEventListener(\n  'click',\n  onTick,\n);\n"
            )
        }
        self.assertEqual(self.unused(scripts), [])

    def test_a_helper_used_only_by_an_unused_function_is_reported_with_it(self) -> None:
        scripts = {
            "a.js": (
                "function helper() {}\n"
                "function shared() {}\n"
                "function dead() {\n  helper();\n  shared();\n}\n"
                "function live() {\n  shared();\n}\n"
                "live();\n"
            )
        }
        self.assertEqual(self.unused(scripts), ["a.js:dead", "a.js:helper"])

    def test_top_level_statements_are_roots(self) -> None:
        scripts = {"a.js": "function boot() {}\nconst cache = new Thing();\nboot();\n"}
        self.assertEqual(self.unused(scripts), [])

    def test_classes_and_arrow_functions_are_symbols(self) -> None:
        scripts = {
            "a.js": (
                "class Gone {\n  run() {}\n}\n"
                "const gone = (x) => {\n  return x;\n};\n"
                "const quick = async x => x;\n"
                "class Kept {}\nnew Kept();\n"
            )
        }
        self.assertEqual(self.unused(scripts), ["a.js:Gone", "a.js:gone", "a.js:quick"])

    def test_same_name_in_two_scripts_is_one_name(self) -> None:
        both = {"a.js": "function twin() {}\n", "b.js": "function twin() {}\n"}
        self.assertEqual(self.unused(both), ["a.js:twin", "b.js:twin"])
        used = {**both, "c.js": "twin();\n"}
        self.assertEqual(self.unused(used), [])

    def test_a_longer_name_is_not_a_use_of_a_shorter_one(self) -> None:
        scripts = {"a.js": "function run() {}\nfunction runs() {}\nruns();\n"}
        self.assertEqual(self.unused(scripts), ["a.js:run"])

    def test_indented_declarations_are_not_top_level(self) -> None:
        scripts = {"a.js": "(function () {\n  function inner() {}\n})();\n"}
        self.assertEqual(self.unused(scripts), [])


class TestUnusedMemberScan(unittest.TestCase):
    CLASS = (
        "class Box {\n"
        "  constructor() {\n    this.n = 0;\n  }\n"
        "  static make() {\n    return new Box();\n  }\n"
        "  static async load() {}\n"
        "  static count = 0;\n"
        "  get size() {\n    return 1;\n  }\n"
        "  set size(value) {}\n"
        "  open() {\n    return this.n;\n  }\n"
        "  close() {}\n"
        "}\n"
        "window.Box = Box;\n"
    )

    def unused(
        self, extra: str = "", others: dict[str, str] | None = None
    ) -> list[str]:
        return find_unused({"a.js": self.CLASS, "b.js": extra}, others or {})

    def test_members_nothing_mentions_are_reported(self) -> None:
        self.assertEqual(
            self.unused("Box.make().open();\n"),
            [
                "a.js:Box.close",
                "a.js:Box.count",
                "a.js:Box.load",
                "a.js:Box.size",
                "a.js:Box.size",
            ],
        )

    def test_a_call_from_another_script_or_a_template_counts(self) -> None:
        unused = self.unused(
            "Box.make().open();\nBox.load();\nBox.count += 1;\n",
            {"p.html": '<a onclick="box.close()">'},
        )
        self.assertEqual(unused, ["a.js:Box.size", "a.js:Box.size"])

    def test_a_property_read_uses_getter_and_setter(self) -> None:
        unused = self.unused("Box.make().open();\nconsole.log(box.size);\n")
        self.assertNotIn("a.js:Box.size", unused)

    def test_the_constructor_is_never_reported(self) -> None:
        self.assertNotIn("a.js:Box.constructor", self.unused("new Box();\n"))

    def test_a_member_used_only_by_an_unused_member_is_reported_with_it(self) -> None:
        scripts = {
            "a.js": (
                "class Box {\n"
                "  helper() {}\n"
                "  shared() {}\n"
                "  gone() {\n    this.helper();\n    this.shared();\n  }\n"
                "  here() {\n    this.shared();\n  }\n"
                "}\n"
                "new Box().here();\n"
            )
        }
        self.assertEqual(find_unused(scripts, {}), ["a.js:Box.gone", "a.js:Box.helper"])

    def test_calling_itself_does_not_make_a_member_used(self) -> None:
        scripts = {
            "a.js": "class Box {\n  loop() {\n    this.loop();\n  }\n}\nnew Box();\n"
        }
        self.assertEqual(find_unused(scripts, {}), ["a.js:Box.loop"])

    def test_the_members_of_an_unused_class_are_not_listed_one_by_one(self) -> None:
        scripts = {"a.js": "class Gone {\n  run() {}\n  stop() {}\n}\n"}
        self.assertEqual(find_unused(scripts, {}), ["a.js:Gone"])

    def test_what_only_an_unused_class_uses_is_reported_with_it(self) -> None:
        scripts = {
            "a.js": "class Gone {\n  run() {\n    util();\n  }\n}\nfunction util() {}\n",
            "b.js": "x.run();\n",
        }
        self.assertEqual(find_unused(scripts, {}), ["a.js:Gone", "a.js:util"])

    def test_a_member_of_another_class_with_the_same_name_is_one_name(self) -> None:
        scripts = {
            "a.js": "class A {\n  init() {}\n}\nclass B {\n  init() {}\n}\nnew A();\nnew B();\n",
            "b.js": "a.init();\n",
        }
        self.assertEqual(find_unused(scripts, {}), [])


if __name__ == "__main__":
    unittest.main()
