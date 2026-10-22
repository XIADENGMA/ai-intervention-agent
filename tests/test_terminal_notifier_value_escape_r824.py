"""R824: a request whose first words start with ``-``, ``[``, ``(`` ... no longer reaches the desktop 2.5 s late.

The VS Code extension raises its macOS banner with the ``terminal-notifier`` 2.0.0 binary
it bundles (``packages/vscode/vendor``), passing the text as ``-title`` and ``-message``
arguments. The banner for a new request carries a summary of the request: the first 120
characters of what the AI asked. The binary does not take those values as they are: it
hands them to ``NSUserDefaults``' command-line argument parser. Measured on the bundled
binary, with every printable ASCII character as the first character of the value (four
shapes each, 404 texts):

* a value that starts with ``[``, ``(``, ``{``, ``<``, ``"`` or ``-`` is read as "no
  value". For ``-message`` the binary then waits for one on its standard input, and
  ``execFile`` gives it a pipe that never closes: the process hangs until the provider's
  2.5 s timeout kills it, and the AppleScript fallback shows the banner 2.5 s late, by
  another notification path and with another sound. With the pipe closed or ``/dev/null``
  the same text arrives at once as a banner with an empty body, which is what a quick probe
  from a shell shows. ``- item one``, ``[x] done``, ``(1) first``, ``"quoted" ...`` are all
  ordinary ways for a question to start;
* a ``-title`` read as "no title" becomes the binary's default, ``Terminal``;
* a value that is nothing but a property list (``()``, ``{}``, ``(x)``, ``{a = b;}``)
  hangs the process whatever its stdin is;
* a value that starts with a backslash loses it (``\\path`` arrives as ``path``): the
  binary treats the first backslash as an escape character and removes it.

The other 380 texts arrive intact, and so does every one when a backslash is put in front
of the value: the parser sees a backslash first and stops treating the value as a property
list, and the binary removes exactly that backslash. ``escapeTerminalNotifierValue`` does
that for the title and the message; nothing else (``-sound``, ``-activate``,
``-execute``) is passed through it.

Two kinds of test below:

* the source of the provider is read and checked for the one rule that matters (every
  ``-title`` / ``-message`` value goes through the helper, the helper is exported, no raw
  value is left anywhere);
* the TypeScript of the provider is transpiled and run in Node with a fake ``vscode``, a
  fake ``child_process.execFile`` and ``process.platform`` set to ``darwin``, so the
  arguments the provider really builds can be read on any machine. These skip when
  ``node`` or the ``typescript`` package is not installed. The host tests in
  ``packages/vscode/test/notification-providers.test.js`` check the same on a real macOS
  host and, when asked to (``AIIA_REAL_TERMINAL_NOTIFIER=1``), against the real binary run
  the way the provider runs it.
"""

from __future__ import annotations

import functools
import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
HOST_DIR = REPO_ROOT / "packages" / "vscode"
PROVIDERS_TS = HOST_DIR / "notification-providers.ts"
TYPESCRIPT_MODULE = REPO_ROOT / "node_modules" / "typescript" / "lib" / "typescript.js"

# What the bundled binary misreads when the value is passed as it is (see the module
# docstring). One text for each way of misreading, then the shapes a real summary has.
MISREAD = [
    "[Plan] next steps",
    "[x] done",
    "(1) first",
    "(R823) fixed",
    "{x} y",
    "<think> abc",
    '"quoted" start',
    "- item one",
    "- [ ] todo",
    "-flag",
    "--",
    "\\path\\n",
    '\\"quote',
    "[",
    "(",
    "{",
    "<",
    '"',
    "-",
    "\\",
    "()",
    "{}",
    "(x)",
    "[]",
    "<abc>",
    "(a, b) tail",
    "{a = b;}",
]
READ_RIGHT = [
    "plain text",
    "Done: 3 files changed",
    "中文开头，继续",
    "\U0001f642 emoji first",
    "【计划】 full-width bracket",
    'say "hi"',
    "a = b;",
    "# heading",
    "> quote",
    "**bold** text",
    "$HOME `x`",
    "/path/to/file",
    "'single' quoted",
    "1. first item",
    "...and more",
    ")",
    "]",
    "}",
    ">",
]
# The first characters the binary was seen to misread.
MISREAD_FIRST_CHARACTERS = ["[", "(", "{", "<", '"', "-", "\\"]


@functools.cache
def _source() -> str:
    return PROVIDERS_TS.read_text(encoding="utf-8")


def _class_body(source: str, name: str) -> str:
    start = source.index(f"export class {name}")
    nxt = source.find("\nexport class ", start + 1)
    end = nxt if nxt != -1 else source.index("\nmodule.exports", start)
    return source[start:end]


class TestEveryValueGoesThroughTheHelper:
    """Source-level guard: the rule cannot be bypassed by adding another argument."""

    def test_helper_is_defined_and_exported(self) -> None:
        source = _source()
        assert "export function escapeTerminalNotifierValue(" in source
        exports = source[source.index("module.exports") :]
        assert "escapeTerminalNotifierValue" in exports

    def test_helper_puts_exactly_one_backslash_in_front(self) -> None:
        source = _source()
        body = source[source.index("export function escapeTerminalNotifierValue(") :]
        body = body[: body.index("\n}") + 2]
        assert re.search(r"return '\\\\' \+ value\b", body), body

    def test_title_and_message_values_are_escaped(self) -> None:
        macos = _class_body(_source(), "MacOSNativeNotificationProvider")
        assert re.search(
            r"'-title',\s*escapeTerminalNotifierValue\(title\),\s*"
            r"'-message',\s*escapeTerminalNotifierValue\(message\)",
            macos,
        ), "the -title / -message pair must be built from the escaped values"

    def test_no_raw_title_or_message_value_is_left_anywhere(self) -> None:
        source = _source()
        for flag in ("-title", "-message"):
            for match in re.finditer(rf"'{flag}'\s*,\s*([^,\n]+)", source):
                value = match.group(1).strip()
                assert value.startswith("escapeTerminalNotifierValue("), (
                    f"{flag} is passed {value!r} without the helper"
                )

    def test_the_other_arguments_are_left_alone(self) -> None:
        # -activate takes a bundle id and -execute a command line; both start with a letter
        # and must not get a backslash (the id would no longer name an application).
        macos = _class_body(_source(), "MacOSNativeNotificationProvider")
        assert "args.push('-activate', bundleId)" in macos
        assert "args.push('-execute', executeCmd)" in macos
        assert "'-sound'," in macos


def test_corpus_has_every_first_character_the_binary_misreads() -> None:
    firsts = {text[0] for text in MISREAD}
    assert set(MISREAD_FIRST_CHARACTERS) <= firsts
    assert not {text for text in MISREAD if text[0] not in MISREAD_FIRST_CHARACTERS}
    # nothing in the "reads right" list may start with one of the misread characters
    assert not {text for text in READ_RIGHT if text[0] in MISREAD_FIRST_CHARACTERS}


# --- running the real TypeScript --------------------------------------------------------

HARNESS = r"""
const fs = require('fs')
const path = require('path')
const [tsPath, srcDir, scenarioJson] = process.argv.slice(1)
const ts = require(tsPath)
const scenarios = JSON.parse(scenarioJson)
const realPlatform = process.platform
const realChildProcess = require('child_process')
const vscodeStub = {
  l10n: { t: (m, ...a) => String(m).replace(/\{(\d+)\}/g, (_, i) => String(a[Number(i)])) },
  window: {}, env: {}, workspace: {}, commands: {}
}
let current = null
const fakeChildProcess = Object.assign({}, realChildProcess, {
  execFile(file, args, options, callback) {
    current.calls.push({ file, args: Array.from(args) })
    setImmediate(() => {
      if (current.fail) callback(Object.assign(new Error('terminal-notifier failed'), { code: 1 }), '', 'failed')
      else callback(null, '', '')
    })
    return { kill() {}, on() {} }
  }
})
const cache = {}
function load(name) {
  if (cache[name]) return cache[name].exports
  const file = path.join(srcDir, name + '.ts')
  const js = ts.transpileModule(fs.readFileSync(file, 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, esModuleInterop: true }
  }).outputText
  const mod = { exports: {} }
  cache[name] = mod
  const req = id =>
    id === 'vscode' ? vscodeStub
    : id === 'child_process' ? fakeChildProcess
    : id.startsWith('./') ? load(id.slice(2))
    : require(id)
  new Function('module', 'exports', 'require', '__dirname', '__filename', js)(
    mod, mod.exports, req, srcDir, path.join(srcDir, name + '.js'))
  return mod.exports
}
;(async () => {
  const { MacOSNativeNotificationProvider, escapeTerminalNotifierValue } = load('notification-providers')
  const out = []
  for (const sc of scenarios) {
    current = { calls: [], appleScripts: [], fail: !!sc.fail }
    const provider = new MacOSNativeNotificationProvider({
      executor: { runAppleScript: async script => { current.appleScripts.push(String(script)); return '' } },
      vscodeApi: { env: {} }
    })
    Object.defineProperty(process, 'platform', { value: 'darwin', configurable: true })
    provider._terminalNotifierBin = '/fake/terminal-notifier'
    if (sc.bundleId) provider._appleScriptProvider._resolveHostBundleId = async () => sc.bundleId
    let ok
    try {
      ok = await provider.send(sc.event)
    } finally {
      Object.defineProperty(process, 'platform', { value: realPlatform, configurable: true })
    }
    out.push({
      ok,
      calls: current.calls,
      appleScripts: current.appleScripts,
      escaped: typeof escapeTerminalNotifierValue === 'function' ? escapeTerminalNotifierValue(String(sc.event.message || '')) : null
    })
  }
  process.stdout.write(JSON.stringify(out))
})().catch(e => { process.stderr.write(String((e && e.stack) || e)); process.exit(1) })
"""


def _can_run_typescript() -> bool:
    return shutil.which("node") is not None and TYPESCRIPT_MODULE.exists()


needs_typescript = pytest.mark.skipif(
    not _can_run_typescript(),
    reason="needs node and the typescript package (npm ci at the repository root)",
)


def run_provider(scenarios: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Send each scenario's event through the real MacOSNativeNotificationProvider."""
    proc = subprocess.run(
        [
            shutil.which("node") or "node",
            "-e",
            HARNESS,
            str(TYPESCRIPT_MODULE),
            str(HOST_DIR),
            json.dumps(scenarios),
        ],
        capture_output=True,
        text=True,
        timeout=120,
        # no HOME: the provider's start-up copy of the bundled app into the user's library
        # is skipped, nothing is written outside the process
        env={"PATH": "/usr/bin:/bin:/usr/local/bin", "HOME": ""},
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def _pair(text: str) -> dict[str, Any]:
    return {"event": {"title": "[Plan] " + text, "message": text, "metadata": {}}}


FALLBACK_TEXTS = ["[Plan] next steps", '"quoted" start', "- item"]


@pytest.fixture(scope="module")
def ran() -> dict[str, dict[str, Any]]:
    """Every scenario of this file, run through the provider in one Node process."""
    named: dict[str, dict[str, Any]] = {}
    for text in MISREAD + READ_RIGHT:
        named[f"pair:{text}"] = _pair(text)
    for text in MISREAD:
        named[f"bare:{text}"] = {"event": {"message": text, "metadata": {}}}
    named["default-title"] = {"event": {"message": "(1) first", "metadata": {}}}
    named["trimmed"] = {
        "event": {"title": "  T  ", "message": "  - item  ", "metadata": {}}
    }
    named["empty"] = {"event": {"message": "   ", "metadata": {}}}
    named["bundle"] = {
        "event": {"title": "T", "message": "- item", "metadata": {}},
        "bundleId": "com.example.host",
    }
    for text in FALLBACK_TEXTS:
        named[f"fallback:{text}"] = {
            "event": {"title": "(T) title", "message": text, "metadata": {}},
            "fail": True,
        }
    results = run_provider(list(named.values()))
    return dict(zip(named, results, strict=True))


@needs_typescript
class TestTheArgumentsTheProviderReallyBuilds:
    @pytest.mark.parametrize("text", MISREAD + READ_RIGHT)
    def test_title_and_message_arrive_with_one_backslash_in_front(
        self, ran: dict[str, dict[str, Any]], text: str
    ) -> None:
        result = ran[f"pair:{text}"]
        assert result["ok"] is True
        assert len(result["calls"]) == 1
        call = result["calls"][0]
        assert call["file"] == "/fake/terminal-notifier"
        assert call["args"] == [
            "-title",
            "\\[Plan] " + text,
            "-message",
            "\\" + text,
            "-sound",
            "default",
        ]

    @pytest.mark.parametrize("text", MISREAD)
    def test_helper_agrees_with_what_the_provider_passes(
        self, ran: dict[str, dict[str, Any]], text: str
    ) -> None:
        result = ran[f"bare:{text}"]
        assert result["escaped"] == "\\" + text
        assert result["calls"][0]["args"][3] == result["escaped"]

    def test_default_title_is_escaped_too(self, ran: dict[str, dict[str, Any]]) -> None:
        assert ran["default-title"]["calls"][0]["args"][:4] == [
            "-title",
            "\\AI Intervention Agent",
            "-message",
            "\\(1) first",
        ]

    def test_title_and_message_are_trimmed_before_they_are_escaped(
        self, ran: dict[str, dict[str, Any]]
    ) -> None:
        # the backslash must be the first character of the value, never in front of blanks
        assert ran["trimmed"]["calls"][0]["args"][:4] == [
            "-title",
            "\\T",
            "-message",
            "\\- item",
        ]

    def test_sound_activate_and_execute_are_left_alone(
        self, ran: dict[str, dict[str, Any]]
    ) -> None:
        # the bundle id names an application and the command line starts with `osascript`:
        # a backslash in front of either would break the click-to-activate
        assert ran["bundle"]["calls"][0]["args"] == [
            "-title",
            "\\T",
            "-message",
            "\\- item",
            "-sound",
            "default",
            "-activate",
            "com.example.host",
            "-execute",
            'osascript -e "tell application id \\"com.example.host\\"" '
            '-e "reopen" -e "activate" -e "end tell"',
        ]

    def test_an_empty_message_sends_nothing(
        self, ran: dict[str, dict[str, Any]]
    ) -> None:
        assert ran["empty"]["ok"] is False
        assert ran["empty"]["calls"] == []
        assert ran["empty"]["appleScripts"] == []

    @pytest.mark.parametrize("text", FALLBACK_TEXTS)
    def test_the_applescript_fallback_gets_the_text_as_it_was(
        self, ran: dict[str, dict[str, Any]], text: str
    ) -> None:
        result = ran[f"fallback:{text}"]
        assert result["ok"] is True
        assert len(result["calls"]) == 1
        assert len(result["appleScripts"]) == 1
        # AppleScript string literals escape \ and " the way JSON does for these texts
        assert (
            f'display notification {json.dumps(text)} with title "(T) title"'
            in result["appleScripts"][0]
        )
