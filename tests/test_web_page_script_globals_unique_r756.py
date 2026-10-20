"""R756: the classic scripts of one page share a global scope, so each top-level name belongs to one file.

The Web UI template and the VS Code webview load several plain ``<script>``
files into the same page. A ``function`` or ``var`` declared at the top level
of two of them silently replaces the earlier one with whichever loads last,
and a ``const``, ``let`` or ``class`` declared twice is a ``SyntaxError`` that
stops the later script from running at all. Every other test loads one file at
a time in a ``vm`` context, so none of them sees the clash.

``notification-manager.js`` carried an ``isMobileDevice`` that ``app.js`` (which
loads later) replaced with a better one, and that nothing in its own file
called; the copy was dead and would have changed the behaviour if the load
order ever flipped. The lock reads the real script lists out of the template
and out of ``webview.ts`` and fails on any new clash.
"""

from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC = REPO_ROOT / "src" / "ai_intervention_agent"
WEB_TEMPLATE = SRC / "templates" / "web_ui.html"
WEB_JS_DIR = SRC / "static" / "js"
VSCODE_DIR = REPO_ROOT / "packages" / "vscode"
WEBVIEW_TS = VSCODE_DIR / "webview.ts"

VENDORED = frozenset(
    {
        "lottie.min.js",
        "marked.js",
        "marked.min.js",
        "prism.js",
        "prism.min.js",
        "tex-mml-chtml.js",
    }
)

# The same two-line helper lives in both files so that each works when a test
# loads it alone; the later copy does the same thing as the earlier one.
KNOWN_IDENTICAL_COPIES = {
    "t": frozenset({"app.js", "notification-manager.js"}),
}

_SCRIPT_TAG = re.compile(r"<script\b(?P<attrs>[^>]*)>", re.IGNORECASE | re.DOTALL)
_HTML_SRC = re.compile(r'(?<![\w-])src="/static/js/(?P<name>[\w.\-]+\.js)(?:\?[^"]*)?"')
_TS_SRC = re.compile(r'(?<![\w-])src="\$\{(?P<var>\w+)\}"')
_TS_URI = re.compile(
    r"const\s+(?P<var>\w+)\s*=\s*webview\.asWebviewUri\(\s*"
    r'vscode\.Uri\.joinPath\(this\._extensionUri,\s*"(?P<name>[\w.\-]+\.js)"\s*\)',
)
_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)
_LINE_COMMENT = re.compile(r"^[ \t]*//.*$", re.MULTILINE)
_TOP_LEVEL = re.compile(
    r"^(?:async[ \t]+function[ \t]*\*?|function[ \t]*\*?|class|const|let|var)"
    r"[ \t]+(?P<name>[A-Za-z_$][\w$]*)",
    re.MULTILINE,
)


def _is_module(attrs: str) -> bool:
    return re.search(r"""\btype\s*=\s*["']module["']""", attrs) is not None


def web_ui_scripts() -> list[str]:
    html = WEB_TEMPLATE.read_text(encoding="utf-8")
    names: list[str] = []
    for tag in _SCRIPT_TAG.finditer(html):
        attrs = tag.group("attrs")
        src = _HTML_SRC.search(attrs)
        if src and not _is_module(attrs):
            names.append(src.group("name"))
    return names


def vscode_scripts() -> list[str]:
    source = WEBVIEW_TS.read_text(encoding="utf-8")
    files = {m.group("var"): m.group("name") for m in _TS_URI.finditer(source)}
    names: list[str] = []
    for tag in _SCRIPT_TAG.finditer(source):
        attrs = tag.group("attrs")
        src = _TS_SRC.search(attrs)
        if src and not _is_module(attrs) and src.group("var") in files:
            names.append(files[src.group("var")])
    lazy = files.get("webviewSettingsUiUri")
    if lazy:
        names.append(lazy)
    return names


def top_level_names(text: str) -> list[str]:
    text = _BLOCK_COMMENT.sub("", text)
    text = _LINE_COMMENT.sub("", text)
    return [m.group("name") for m in _TOP_LEVEL.finditer(text)]


def declarations(directory: Path, scripts: list[str]) -> dict[str, set[str]]:
    owners: dict[str, set[str]] = defaultdict(set)
    for script in dict.fromkeys(scripts):
        if script in VENDORED or script.endswith(".min.js"):
            continue
        path = directory / script
        assert path.is_file(), (
            f"{script} is loaded by the page but missing in {directory}"
        )
        for name in top_level_names(path.read_text(encoding="utf-8")):
            owners[name].add(script)
    return owners


def clashes(owners: dict[str, set[str]]) -> dict[str, set[str]]:
    found: dict[str, set[str]] = {}
    for name, files in owners.items():
        if len(files) < 2:
            continue
        if KNOWN_IDENTICAL_COPIES.get(name) == files:
            continue
        found[name] = files
    return found


def _format(found: dict[str, set[str]]) -> str:
    return "; ".join(
        f"{name}: {sorted(files)}" for name, files in sorted(found.items())
    )


class TestScriptListsAreRead:
    def test_web_ui_list_has_the_main_scripts(self) -> None:
        scripts = web_ui_scripts()
        for expected in (
            "app.js",
            "multi_task.js",
            "notification-manager.js",
            "settings-manager.js",
            "image-upload.js",
            "i18n.js",
        ):
            assert expected in scripts, f"{expected} not found in {scripts}"

    def test_web_ui_list_skips_module_scripts(self) -> None:
        scripts = web_ui_scripts()
        assert "tri-state-panel-loader.js" not in scripts
        assert "tri-state-panel-bootstrap.js" in scripts

    def test_vscode_list_has_the_main_scripts(self) -> None:
        scripts = vscode_scripts()
        for expected in (
            "webview-ui.js",
            "webview-state.js",
            "webview-helpers.js",
            "i18n.js",
            "slash-commands.js",
            "webview-notify-core.js",
            "webview-settings-ui.js",
        ):
            assert expected in scripts, f"{expected} not found in {scripts}"

    def test_vscode_list_skips_module_scripts(self) -> None:
        scripts = vscode_scripts()
        assert "tri-state-panel-loader.js" not in scripts
        assert "tri-state-panel-bootstrap.js" in scripts


class TestDeclarationScanner:
    def test_reads_every_declaration_keyword(self) -> None:
        text = (
            "function a() {}\n"
            "async function b() {}\n"
            "function* c() {}\n"
            "class D {}\n"
            "const e = 1\n"
            "let f\n"
            "var g = 2\n"
        )
        assert top_level_names(text) == ["a", "b", "c", "D", "e", "f", "g"]

    def test_ignores_nested_and_commented_declarations(self) -> None:
        text = (
            "function outer() {\n"
            "  function inner() {}\n"
            "  const local = 1\n"
            "}\n"
            "/*\nfunction commented() {}\n*/\n"
            "// function lineComment() {}\n"
            "const kept = 1\n"
        )
        assert top_level_names(text) == ["outer", "kept"]

    def test_a_name_in_two_files_is_a_clash(self) -> None:
        owners = {"x": {"a.js", "b.js"}, "y": {"a.js"}}
        assert clashes(owners) == {"x": {"a.js", "b.js"}}

    def test_a_known_copy_is_not_a_clash_until_a_third_file_joins(self) -> None:
        pair = {"t": {"app.js", "notification-manager.js"}}
        assert clashes(pair) == {}
        assert clashes({"t": {"app.js", "notification-manager.js", "x.js"}})


class TestWebUiPage:
    def test_no_top_level_name_is_declared_by_two_scripts(self) -> None:
        found = clashes(declarations(WEB_JS_DIR, web_ui_scripts()))
        assert not found, (
            "Top-level names declared by more than one script of the Web UI page "
            f"(the later script replaces or breaks the earlier one): {_format(found)}"
        )

    def test_known_identical_copies_are_still_copies(self) -> None:
        owners = declarations(WEB_JS_DIR, web_ui_scripts())
        for name, files in KNOWN_IDENTICAL_COPIES.items():
            assert owners.get(name) == files, (
                f"{name!r} is no longer declared by exactly {sorted(files)}; "
                "drop it from KNOWN_IDENTICAL_COPIES"
            )

    def test_the_dead_mobile_check_is_gone(self) -> None:
        owners = declarations(WEB_JS_DIR, web_ui_scripts())
        assert owners["isMobileDevice"] == {"app.js"}


class TestVsCodeWebview:
    def test_no_top_level_name_is_declared_by_two_scripts(self) -> None:
        found = clashes(declarations(VSCODE_DIR, vscode_scripts()))
        assert not found, (
            "Top-level names declared by more than one script of the VS Code webview "
            f"(the later script replaces or breaks the earlier one): {_format(found)}"
        )
