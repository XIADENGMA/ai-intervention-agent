"""R753: the i18n gates read JavaScript/TypeScript with a lexer, not with regexes.

``check_i18n_js_no_cjk.py`` and ``check_i18n_ts_no_cjk.py`` used to blank
everything after the first ``//`` of a line and then pair quotes with a regex.
A string such as ``"http://localhost/"`` lost its closing quote that way, and
from there on the quotes of the file were paired the wrong way round: in
``multi_task.js`` the scan lost 25 of 885 literals and missed
`` _debugLog(`显示新任务视觉提示: ${count} 个新任务`) ``. Text written as
``\\u65b0\\u4efb\\u52a1`` was invisible to it by construction, which is how the
host-side new-task notification kept a Chinese title and body in ``webview.ts``.

``scripts/js_source_scan.py`` now walks the source once: strings, template
literals (substitutions lexed as code), regex literals and comments. These
tests pin its behaviour on the cases that broke the regexes and compare it with
the TypeScript scanner on fixtures and on the repository's own sources.
"""

from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCANNER_PATH = REPO_ROOT / "scripts" / "js_source_scan.py"
TS_CHECKER_PATH = REPO_ROOT / "scripts" / "check_i18n_ts_no_cjk.py"
JS_CHECKER_PATH = REPO_ROOT / "scripts" / "check_i18n_js_no_cjk.py"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


scan = _load("_aiia_js_source_scan_r753", SCANNER_PATH)


def literals(src: str) -> list[tuple[int, str]]:
    return [(lit.line, lit.text) for lit in scan.string_literals(src)]


def texts(src: str) -> list[str]:
    return [text for _line, text in literals(src)]


class TestStringsAndComments(unittest.TestCase):
    def test_slashes_inside_a_string_are_not_a_comment(self) -> None:
        src = 'const base = "http://localhost/"; const label = "新任务";\n'
        self.assertEqual(texts(src), ["http://localhost/", "新任务"])

    def test_a_url_does_not_shift_the_pairing_of_the_following_lines(self) -> None:
        src = (
            'const url = cond ? base : "http://localhost/";\n'
            'u.searchParams.set("task_id", id);\n'
            "const label = '中文';\n"
        )
        self.assertEqual(
            literals(src),
            [(1, "http://localhost/"), (2, "task_id"), (3, "中文")],
        )

    def test_quotes_inside_comments_are_not_literals(self) -> None:
        src = "// say \"中\"\n/* it's '中' */\nconst a = 'x' /* \"中\" */ + 'y';\n"
        self.assertEqual(literals(src), [(3, "x"), (3, "y")])

    def test_an_unterminated_string_ends_at_its_line_break(self) -> None:
        src = 'const a = "oops;\nconst b = "中";\n'
        self.assertEqual(literals(src), [(1, "oops;"), (2, "中")])

    def test_a_line_continuation_keeps_the_string_going(self) -> None:
        src = 'const a = "ab\\\ncd"; const b = "中";\n'
        self.assertEqual(literals(src), [(1, "abcd"), (2, "中")])
        windows = 'const a = "ab\\\r\ncd"; const b = "中";\r\n'
        self.assertEqual(literals(windows), [(1, "abcd"), (2, "中")])

    def test_a_shebang_is_a_comment(self) -> None:
        src = "#!/usr/bin/env node\nconst a = '中';\n"
        self.assertEqual(literals(src), [(2, "中")])
        self.assertTrue(scan.blank_comments(src).startswith(" " * 19 + "\n"))


class TestEscapes(unittest.TestCase):
    def test_unicode_escapes_are_decoded(self) -> None:
        self.assertEqual(texts('"\\u65b0\\u4efb\\u52a1"'), ["新任务"])
        self.assertEqual(texts("'\\u{65b0}\\u{1F600}'"), ["新😀"])
        self.assertEqual(texts('"\\ud83d\\ude00"'), ["😀"])

    def test_hex_and_simple_escapes_are_decoded(self) -> None:
        self.assertEqual(texts('"\\x41\\x7a"'), ["Az"])
        self.assertEqual(texts('"a\\nb\\tc\\\\d\\"e"'), ['a\nb\tc\\d"e'])
        self.assertEqual(texts("'it\\'s'"), ["it's"])
        self.assertEqual(texts('"\\q"'), ["q"])

    def test_the_escaped_text_of_the_notification_that_slipped_through(self) -> None:
        src = 'const title = "AI \\u4ea4\\u4e92\\u53cd\\u9988";\n'
        self.assertEqual(texts(src), ["AI 交互反馈"])


class TestRegexVersusDivision(unittest.TestCase):
    def test_quotes_and_backticks_inside_a_regex_do_not_open_strings(self) -> None:
        src = "const a = /['\"]/g;\nconst b = /`/;\nconst c = '中';\n"
        self.assertEqual(literals(src), [(3, "中")])

    def test_a_slash_inside_a_character_class_does_not_end_the_regex(self) -> None:
        src = "const r = /[/]'\\/\"/g; const s = '中';\n"
        self.assertEqual(texts(src), ["中"])

    def test_division_is_not_a_regex(self) -> None:
        src = (
            "const h = total / 2; const q = '中'; const r = a / b / c; const s = 'x';\n"
        )
        self.assertEqual(texts(src), ["中", "x"])

    def test_division_after_a_closing_bracket_or_an_increment(self) -> None:
        src = "i++ / '中' / 2;\nx = (a) / '文' / 3;\ny = arr[0] / '字' / 4;\n"
        self.assertEqual(texts(src), ["中", "文", "字"])

    def test_regex_after_operators_keywords_and_punctuation(self) -> None:
        src = (
            "const a = [/\"/, /'/]; const m = x && /`/.test(y); const k = '中';\n"
            "function f(s) { return /\"/.test(s) ? '文' : 'x'; }\n"
            "const g = (s) => /'/.test(s) || !/\"/.test(s);\n"
            "const h = typeof /'/ === 'object' ? '字' : '';\n"
        )
        self.assertEqual(texts(src), ["中", "文", "x", "object", "字", ""])

    def test_a_keyword_used_as_a_property_name_ends_an_operand(self) -> None:
        src = "const a = it.return / '中' / 2; const b = map.delete / '文' / 3;\n"
        self.assertEqual(texts(src), ["中", "文"])

    def test_a_regex_after_a_closing_brace(self) -> None:
        src = "function f() {}\n/\"/.test(s); const t = '中';\n"
        self.assertEqual(texts(src), ["中"])

    def test_regex_flags_end_the_regex(self) -> None:
        src = "const r = /a'b/gi; const s = '中';\n"
        self.assertEqual(texts(src), ["中"])

    def test_a_slash_that_cannot_start_a_regex_is_a_division(self) -> None:
        src = "const v = {a: 1} / 2; const q = '中';\nconst w = '文' / 3;\n"
        self.assertEqual(literals(src), [(1, "中"), (2, "文")])
        self.assertEqual(texts("const v = {a: 1} / 2; const q = '中';"), ["中"])


class TestTemplates(unittest.TestCase):
    def test_a_template_is_one_literal_with_placeholders(self) -> None:
        src = "const m = `a ${x} b ${y}`;\n"
        self.assertEqual(literals(src), [(1, "a ${…} b ${…}")])

    def test_strings_and_templates_inside_a_substitution_are_found(self) -> None:
        src = 'const m = `a ${ "中" } b ${ x ? `c ${y} d` : "e" }`;\n'
        self.assertEqual(
            texts(src),
            ["a ${…} b ${…}", "中", "c ${…} d", "e"],
        )

    def test_braces_inside_a_substitution_do_not_end_it(self) -> None:
        src = 'const m = `x ${ {a: "}"}.a } y ${ "文" }`;\n'
        self.assertEqual(texts(src), ["x ${…} y ${…}", "}", "文"])

    def test_a_multiline_template_reports_the_line_it_starts_on(self) -> None:
        src = "const a = `line1\nline2 ${x}\nline3`;\nconst b = '中';\n"
        self.assertEqual(
            literals(src),
            [(1, "line1\nline2 ${…}\nline3"), (4, "中")],
        )

    def test_a_template_escape_and_a_dollar_sign(self) -> None:
        src = "const a = `\\u4e2d $5 \\${x} \\`q\\``;\n"
        self.assertEqual(texts(src), ["中 $5 ${x} `q`"])

    def test_a_regex_or_a_comment_inside_a_substitution(self) -> None:
        src = "const a = `${ /`/.test(s) /* ` */ ? '中' : 'x' }`;\n"
        self.assertEqual(texts(src), ["${…}", "中", "x"])

    def test_line_numbers_with_windows_line_endings(self) -> None:
        src = "const a = 'x';\r\nconst b = `p\r\nq`;\r\nconst c = '中';\r\n"
        self.assertEqual(
            [line for line, _text in literals(src)],
            [1, 2, 4],
        )


class TestBlankComments(unittest.TestCase):
    def test_comments_become_spaces_and_nothing_moves(self) -> None:
        src = "a // b /* c\nd /* e */ f\n"
        blanked = scan.blank_comments(src)
        self.assertEqual(len(blanked), len(src))
        self.assertEqual(blanked.count("\n"), src.count("\n"))
        self.assertEqual(blanked.split(), ["a", "d", "f"])

    def test_slashes_inside_strings_and_regexes_stay(self) -> None:
        src = 'x = "// not a comment"; y = /\\/\\//; // real\n'
        self.assertEqual(
            scan.blank_comments(src),
            'x = "// not a comment"; y = /\\/\\//;        \n',
        )

    def test_a_line_comment_with_a_block_opener_does_not_swallow_code(self) -> None:
        src = "// see packages/* layout\nconst a = '中';\n/* closes */\n"
        blanked = scan.blank_comments(src)
        self.assertIn("'中'", blanked)
        self.assertNotIn("closes", blanked)


class TestCheckers(unittest.TestCase):
    def setUp(self) -> None:
        self.ts = _load("_aiia_check_ts_r753", TS_CHECKER_PATH)
        self.js = _load("_aiia_check_js_r753", JS_CHECKER_PATH)

    def _scan(self, module, suffix: str, source: str) -> list[tuple[int, str]]:
        with tempfile.NamedTemporaryFile(
            "w", suffix=suffix, encoding="utf-8", delete=False
        ) as handle:
            handle.write(source)
            path = Path(handle.name)
        try:
            return module.scan_file(path)
        finally:
            path.unlink(missing_ok=True)

    def test_escaped_chinese_is_reported_as_the_text_it_spells(self) -> None:
        source = 'const title = "\\u4ea4\\u4e92\\u53cd\\u9988";\nconst ok = "plain";\n'
        self.assertEqual(self._scan(self.ts, ".ts", source), [(1, "交互反馈")])
        self.assertEqual(self._scan(self.js, ".js", source), [(1, "交互反馈")])

    def test_a_url_before_a_chinese_literal_does_not_hide_it(self) -> None:
        source = 'const u = "http://x/"; const t = "新任务";\nconst ok = "plain";\n'
        self.assertEqual(self._scan(self.ts, ".ts", source), [(1, "新任务")])
        self.assertEqual(self._scan(self.js, ".js", source), [(1, "新任务")])

    def test_a_regex_with_a_backtick_does_not_hide_what_follows(self) -> None:
        source = "const r = /`/;\nconst t = '新任务';\n"
        self.assertEqual(self._scan(self.ts, ".ts", source), [(2, "新任务")])
        self.assertEqual(self._scan(self.js, ".js", source), [(2, "新任务")])

    def test_a_template_with_chinese_text_is_reported_once(self) -> None:
        source = "_debugLog(`显示 ${count} 个任务`);\n"
        self.assertEqual(self._scan(self.js, ".js", source), [(1, "显示 ${…} 个任务")])

    def test_the_allow_marker_and_comments_still_work(self) -> None:
        source = (
            'const a = "中"; // aiia:i18n-allow-cjk\n'
            '// const b = "中";\n'
            '/* const c = "中"; */\n'
            'const d = "文";\n'
        )
        self.assertEqual(self._scan(self.ts, ".ts", source), [(4, "文")])
        self.assertEqual(self._scan(self.js, ".js", source), [(4, "文")])


def _node_with_typescript() -> str | None:
    node = shutil.which("node")
    if node is None:
        return None
    probe = subprocess.run(
        [
            node,
            "-e",
            "require('module').createRequire(process.argv[1])('typescript')",
            str(REPO_ROOT / "packages" / "vscode" / "package.json"),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    return node if probe.returncode == 0 else None


_ORACLE_JS = r"""
const { createRequire } = require('module')
const ts = createRequire(process.argv[1])('typescript')
const files = JSON.parse(require('fs').readFileSync(0, 'utf8'))
const out = {}
for (const file of files) {
  const kind = file.name.endsWith('.ts') ? ts.ScriptKind.TS : ts.ScriptKind.JS
  const sf = ts.createSourceFile(file.name, file.text, ts.ScriptTarget.Latest, true, kind)
  const found = []
  const visit = node => {
    if (node.kind === ts.SyntaxKind.StringLiteral || node.kind === ts.SyntaxKind.NoSubstitutionTemplateLiteral) {
      found.push([node.getStart(sf), node.text])
    } else if (node.kind === ts.SyntaxKind.TemplateExpression) {
      found.push([node.getStart(sf), [node.head.text, ...node.templateSpans.map(s => s.literal.text)].join('${…}')])
    }
    ts.forEachChild(node, visit)
  }
  visit(sf)
  found.sort((a, b) => a[0] - b[0])
  out[file.name] = found.map(item => [sf.getLineAndCharacterOfPosition(item[0]).line + 1, item[1]])
}
process.stdout.write(JSON.stringify(out))
"""

_TRICKY_FIXTURE = r"""
const a = "http://localhost/"; const b = '中';
const r1 = /['"]/g, r2 = /`/, r3 = /[/]'\/"/g;
const d = total / 2 + x / y / z; const e = '文';
i++ / '字' / 2; j-- / "q" / 3;
const t = `a ${ "x" } b ${ y ? `c ${z} d` : "e" } f`;
const u = `x ${ {k: "}"}.k } y`;
const v = `${ /`/.test(s) /* ` */ ? 'p' : 'q' }`;
function f(s) { return /"/.test(s) ? "yes" : 'no'; }
const g = (s) => /'/.test(s) || !/"/.test(s);
const h = typeof /'/ === 'object' ? "o" : '';
if (ok) { } /"/.test(s);
const esc = "\u65b0\u4efb\x41\u{1F600}\ud83d\ude00\n\t\\\"\q";
const cont = "ab\
cd";
const tpl = `\u4e2d $5 \${x} \`q\``;
const multi = `line1
line2 ${x}
line3`;
// "comment" 'comment' `comment`
/* "block" 'block' */ const after = "z";
label: for (const k of "abc") { break label }
const re2 = a ? /x'/ : /y"/;
x = a /* c */ / 2 / "w";
const pr = it.return / '键' / map.delete / "值";
"""


@unittest.skipUnless(
    _node_with_typescript(), "node with the TypeScript package is not installed"
)
class TestAgainstTheTypeScriptScanner(unittest.TestCase):
    """Literal for literal (line and decoded value) the same as ``typescript``."""

    @staticmethod
    def _oracle(files: list[dict[str, str]]) -> dict[str, list[list]]:
        node = _node_with_typescript()
        assert node is not None
        result = subprocess.run(
            [
                node,
                "-e",
                _ORACLE_JS,
                str(REPO_ROOT / "packages" / "vscode" / "package.json"),
            ],
            input=json.dumps(files),
            capture_output=True,
            text=True,
            check=True,
            timeout=120,
        )
        return json.loads(result.stdout)

    def test_the_tricky_fixture(self) -> None:
        expected = self._oracle(
            [
                {"name": "fixture.js", "text": _TRICKY_FIXTURE},
                {"name": "fixture.ts", "text": _TRICKY_FIXTURE},
            ]
        )
        mine = [[lit.line, lit.text] for lit in scan.string_literals(_TRICKY_FIXTURE)]
        self.assertGreater(len(mine), 20)
        self.assertEqual(mine, expected["fixture.js"])
        self.assertEqual(mine, expected["fixture.ts"])

    def test_every_source_file_of_the_repository(self) -> None:
        roots = [
            REPO_ROOT / "src" / "ai_intervention_agent" / "static" / "js",
            REPO_ROOT / "packages" / "vscode",
        ]
        skip = ("node_modules", "dist", ".vscode-test", "mathjax", "vendor")
        paths = sorted(
            path
            for root in roots
            for pattern in ("*.js", "*.ts", "*.mjs")
            for path in root.rglob(pattern)
            if not path.name.endswith((".min.js", ".d.ts"))
            and not any(part in skip for part in path.relative_to(REPO_ROOT).parts)
        )
        self.assertGreater(len(paths), 40)
        files = []
        for path in paths:
            try:
                text = path.read_text(encoding="utf-8")
            except FileNotFoundError:
                # 另一个 worker 里的测试放进这个目录的临时文件：列出来之后、读之前
                # 就被它删了。它不是仓库的源码，不在这个测试要比对的范围里。
                continue
            files.append({"name": str(path), "text": text})
        self.assertGreater(len(files), 40)
        expected = self._oracle(files)
        mismatched = []
        for file in files:
            mine = [[lit.line, lit.text] for lit in scan.string_literals(file["text"])]
            if mine != expected[file["name"]]:
                mismatched.append(Path(file["name"]).relative_to(REPO_ROOT).as_posix())
        self.assertEqual(mismatched, [])


if __name__ == "__main__":
    unittest.main()
