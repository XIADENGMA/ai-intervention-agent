"""R743 invariant: a stylesheet only styles classes that some code can put on an element.

Dead selectors pile up quietly. When a button, hint or tab is dropped from the
markup its rules stay behind, and the stylesheet keeps describing UI that no
longer exists (a floating shortcut hint with its tooltip, a "+" tab, the
``btn-enabled`` state classes, light-theme rules written for ``lang-label`` and
``copy-btn`` while the toolbar uses ``language-label`` and ``copy-button``).

The check is textual. A class counts as produced when its name appears as a whole
token (the hyphen belongs to the token) in a template, script, Python module or
locale file of the same product, or when some string ends in the name up to its
last hyphen and is followed by a quote, a backtick or ``$`` (``status-${type}``,
``"toast " + kind`` style composition). It cannot see every generator, and a
generic word such as ``hint`` is found anywhere, so it is a floor and not a
proof; it exists to stop the usual case, a class removed from the markup whose
rules were left in the stylesheet.
"""

from __future__ import annotations

import re
import unittest
from functools import lru_cache
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
PACKAGE = REPO_ROOT / "src" / "ai_intervention_agent"
STATIC = PACKAGE / "static"
VSCODE = REPO_ROOT / "packages" / "vscode"

CLASS_TOKEN = re.compile(r"\.(-?[_a-zA-Z][_a-zA-Z0-9-]*)")


def selector_classes(css: str) -> set[str]:
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    names: set[str] = set()
    for prelude in re.findall(r"([^{}]+)\{", css):
        if prelude.lstrip().startswith("@"):
            continue
        names.update(CLASS_TOKEN.findall(re.sub(r"\[[^\]]*\]", "", prelude)))
    return names


def is_produced(name: str, haystack: str) -> bool:
    if re.search(r"(?<![\w-])" + re.escape(name) + r"(?![\w-])", haystack):
        return True
    if "-" not in name:
        return False
    prefix = name.rsplit("-", 1)[0] + "-"
    return re.search(re.escape(prefix) + r"[\"'`$]", haystack) is not None


def orphan_classes(css: str, haystack: str) -> list[str]:
    return sorted(
        name for name in selector_classes(css) if not is_produced(name, haystack)
    )


def _read_all(paths: list[Path]) -> str:
    return "\n".join(p.read_text(encoding="utf-8", errors="ignore") for p in paths)


@lru_cache(maxsize=1)
def web_haystack() -> str:
    return _read_all(
        [
            *sorted((STATIC / "js").rglob("*.js")),
            PACKAGE / "templates" / "web_ui.html",
            *sorted(PACKAGE.rglob("*.py")),
            *sorted((STATIC / "locales").glob("*.json")),
        ]
    )


@lru_cache(maxsize=1)
def vscode_haystack() -> str:
    return _read_all(
        [
            *sorted(p for p in VSCODE.glob("*.ts") if not p.name.endswith(".d.ts")),
            *sorted(VSCODE.glob("*.js")),
            *sorted((VSCODE / "locales").glob("*.json")),
        ]
    )


def _hint(names: list[str], stylesheet: str) -> str:
    return (
        f"R743 invariant: {stylesheet} styles classes that no template, script or "
        f"module can produce: {names}. Remove the rules (or restore the markup that "
        "uses them); a class built from parts needs its prefix written as a string "
        "ending in '-' next to the code that composes it."
    )


class TestStylesheetsHaveNoOrphanClassSelectors(unittest.TestCase):
    def test_web_ui_stylesheet(self) -> None:
        css = (STATIC / "css" / "main.css").read_text(encoding="utf-8")
        names = orphan_classes(css, web_haystack())
        self.assertEqual(names, [], _hint(names, "static/css/main.css"))

    def test_vscode_webview_stylesheet(self) -> None:
        css = (VSCODE / "webview.css").read_text(encoding="utf-8")
        names = orphan_classes(css, vscode_haystack())
        self.assertEqual(names, [], _hint(names, "packages/vscode/webview.css"))

    def test_the_scan_reads_the_files_that_produce_classes(self) -> None:
        self.assertIn("task-tab-text", web_haystack())
        self.assertIn("code-block-container", web_haystack())
        self.assertIn('"css_class": "highlight"', web_haystack())
        self.assertIn("submit-btn-embedded", vscode_haystack())
        self.assertIn("aiia-slash-popup", vscode_haystack())


class TestOrphanScan(unittest.TestCase):
    def test_a_class_nothing_produces_is_reported(self) -> None:
        css = ".gone { color: red; }\n.here { color: blue; }\n"
        self.assertEqual(orphan_classes(css, '<div class="here">'), ["gone"])

    def test_only_whole_tokens_count(self) -> None:
        css = ".task-tab-new { color: red; }\n"
        self.assertEqual(
            orphan_classes(css, 'class="task-tab-newer"'), ["task-tab-new"]
        )
        self.assertEqual(
            orphan_classes(css, 'class="x-task-tab-new"'), ["task-tab-new"]
        )
        self.assertEqual(orphan_classes(css, 'class="task-tab-new active"'), [])

    def test_a_class_composed_from_a_prefix_counts(self) -> None:
        css = ".status-error { color: red; }\n.toast-warn { color: blue; }\n"
        self.assertEqual(
            orphan_classes(css, "el.className = `status-${type}`"), ["toast-warn"]
        )
        self.assertEqual(
            orphan_classes(css, 'el.className = "toast-" + kind'), ["status-error"]
        )
        self.assertEqual(
            orphan_classes(css, "el.className = 'status-' + type"), ["toast-warn"]
        )

    def test_compound_and_list_selectors_are_each_checked(self) -> None:
        css = '[data-theme="light"] .a,\n[data-theme="light"] .b.c { color: red; }\n'
        self.assertEqual(orphan_classes(css, 'class="a c"'), ["b"])

    def test_attribute_selectors_comments_and_at_rules_are_not_class_names(
        self,
    ) -> None:
        css = (
            '/* .commented { } */\n[data-x=".fake"] { color: red; }\n'
            "@layer framework.base { .real { color: blue; } }\n"
            "@keyframes spin { from { opacity: 0; } to { opacity: 1; } }\n"
        )
        self.assertEqual(selector_classes(css), {"real"})


if __name__ == "__main__":
    unittest.main()
