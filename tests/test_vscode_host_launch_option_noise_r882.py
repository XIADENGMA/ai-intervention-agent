"""R882: the VS Code host tests do not print VS Code's complaint about ``--no-cached-data``.

``@vscode/test-electron`` 3 starts the VS Code of the extension host tests with a fixed
``--no-cached-data`` among its arguments (2.5.2 did not). The command line parser inside VS
Code turns every ``--no-<name>`` into ``<name>=false``, finds no option called ``cached-data``
(it knows ``no-cached-data``) and prints one line on every start::

    Warning: 'cached-data' is not in the list of known options, but still passed to Electron/Chromium.

The run is green and the tests are untouched, but that line is in the output of every run, on
Linux and on macOS, and the output of the host tests is meant to hold nothing but results.
Our own ``launchArgs`` cannot remove it: ``test-electron`` puts them in front of its fixed
arguments, and there is no switch to drop one.

``scripts/run_vscode_host_tests.mjs`` (R745) already leaves VS Code's failed network lookups out
of the output and says how many. It now also leaves out exactly this line, counts it
apart from the network lines and says so in a note of its own, which names the flag. Any other
"is not in the list of known options" line stays: a misspelt option of ours must still show.

The tests load the real script in Node: the line filter on samples, and the whole wrapper
around a stand-in command.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import textwrap
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
WRAPPER = REPO_ROOT / "scripts" / "run_vscode_host_tests.mjs"

NODE_AVAILABLE = shutil.which("node") is not None

# Printed by VS Code 1.110.0 when @vscode/test-electron 3.1.0 starts it (taken from a real run).
LAUNCH_LINE = (
    "Warning: 'cached-data' is not in the list of known options, "
    "but still passed to Electron/Chromium."
)

NETWORK_LINE = "Failed to fetch"

STACK = (
    "    at cYe.queryRawGalleryExtensions (vscode-file://vscode-app/Users/me/repo/packages/"
    "vscode/.vscode-test/vscode-darwin-arm64-1.110.0/Visual%20Studio%20Code.app/Contents/"
    "Resources/app/out/vs/workbench/workbench.desktop.main.js:4850:49483)"
)

LAUNCH_NOTE = (
    "VS Code printed about --no-cached-data, a flag @vscode/test-electron passes to it)"
)
NETWORK_NOTE = (
    "VS Code printed about its own marketplace, chat and alert lookups; "
    "the test instance has no reliable network)"
)

# Lines that look like the one we leave out, and must stay.
KEPT = [
    # another option, the same sentence
    "Warning: 'disable-gpu' is not in the list of known options, "
    "but still passed to Electron/Chromium.",
    "Warning: 'no-cached-data' is not in the list of known options, "
    "but still passed to Electron/Chromium.",
    "Warning: 'cached-data-x' is not in the list of known options, "
    "but still passed to Electron/Chromium.",
    "Warning: '' is not in the list of known options, but still passed to Electron/Chromium.",
    # the same option, another sentence
    "Warning: 'cached-data' is not in the list of known options.",
    "Warning: 'cached-data' is deprecated.",
    "Warning: 'cached-data' is not in the list of known options, but still passed on.",
    # the same sentence, but not the whole line
    "[main] " + LAUNCH_LINE,
    " " + LAUNCH_LINE,
    LAUNCH_LINE + " ",
    LAUNCH_LINE + " Check your launch arguments.",
    LAUNCH_LINE + LAUNCH_LINE,
    # another spelling of the start
    LAUNCH_LINE.replace("Warning:", "warning:"),
    LAUNCH_LINE.replace("Warning:", "WARNING:"),
    LAUNCH_LINE.replace("Warning:", "Error:"),
    LAUNCH_LINE.replace("'cached-data'", '"cached-data"'),
    # one character off inside the sentence
    LAUNCH_LINE[:-1] + "!",
    LAUNCH_LINE.replace("Electron/Chromium", "Electron-Chromium"),
    LAUNCH_LINE.replace("known options", "known option"),
    # nothing to do with it
    "",
    "  99 passing (21s)",
    "  1 failing",
    "Warning: something else entirely",
    "[ERROR] [ext] event=sse.connect_failed reason=boom",
    "cached-data",
    "--no-cached-data",
]


def _run_node(source: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["node", "--input-type=module", "-e", source],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


@unittest.skipUnless(NODE_AVAILABLE, "node runtime unavailable")
class TestLaunchOptionFilter(unittest.TestCase):
    def _classify(self, lines: list[str]) -> list[bool]:
        script = textwrap.dedent(
            f"""
            import {{ isLaunchOptionNoise }} from {json.dumps(WRAPPER.as_uri())};
            const lines = {json.dumps(lines)};
            console.log(JSON.stringify(lines.map((line) => isLaunchOptionNoise(line))));
            """
        )
        result = _run_node(script)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_the_line_test_electron_provokes_is_left_out(self) -> None:
        self.assertEqual(self._classify([LAUNCH_LINE]), [True])

    def test_colour_codes_do_not_hide_the_line_from_the_filter(self) -> None:
        coloured = "\u001b[33m" + LAUNCH_LINE + "\u001b[0m"
        self.assertEqual(self._classify([coloured]), [True])

    def test_a_line_that_merely_looks_similar_stays(self) -> None:
        for line in KEPT:
            with self.subTest(line=line[:70]):
                self.assertEqual(self._classify([line]), [False])

    def test_every_line_is_judged_on_its_own(self) -> None:
        lines = [LAUNCH_LINE, "  99 passing (21s)", LAUNCH_LINE, LAUNCH_LINE]
        self.assertEqual(self._classify(lines), [True, False, True, True])

    def test_the_source_has_one_pattern_and_it_is_anchored_at_both_ends(self) -> None:
        source = WRAPPER.read_text(encoding="utf-8")
        block = source.split("const LAUNCH_OPTION_LINES = [", 1)[1].split("];", 1)[0]
        patterns = [line.strip() for line in block.splitlines() if line.strip()]
        self.assertEqual(len(patterns), 1, "one exact line, not a family of lines")
        pattern = patterns[0]
        self.assertTrue(
            pattern.startswith("/^"),
            "a pattern that can match in the middle of a line could hide ours",
        )
        self.assertTrue(
            pattern.endswith("$/,"),
            "a pattern that can stop before the end of a line could hide ours",
        )
        self.assertIn(
            "'cached-data'", pattern, "the pattern names the one option it hides"
        )


@unittest.skipUnless(NODE_AVAILABLE, "node runtime unavailable")
class TestWrapperAroundACommand(unittest.TestCase):
    def _run(self, child_source: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["node", str(WRAPPER), "--", "node", "-e", child_source],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )

    def test_the_line_is_left_out_and_the_note_names_the_flag(self) -> None:
        result = self._run(
            textwrap.dedent(
                f"""
                console.log("- Resolving version...");
                console.log({json.dumps(LAUNCH_LINE)});
                console.log("  2 passing (1s)");
                """
            )
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            result.stdout,
            "- Resolving version...\n  2 passing (1s)\n(left out 1 line "
            + LAUNCH_NOTE
            + "\n",
        )
        self.assertEqual(result.stderr, "")

    def test_the_line_is_left_out_on_the_error_stream_too(self) -> None:
        result = self._run(
            textwrap.dedent(
                f"""
                console.log("  2 passing (1s)");
                console.error({json.dumps(LAUNCH_LINE)});
                """
            )
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, "")
        self.assertEqual(
            result.stdout,
            "  2 passing (1s)\n(left out 1 line " + LAUNCH_NOTE + "\n",
        )

    def test_the_count_is_in_the_plural_for_more_than_one_line(self) -> None:
        result = self._run(
            textwrap.dedent(
                f"""
                console.log({json.dumps(LAUNCH_LINE)});
                console.error({json.dumps(LAUNCH_LINE)});
                console.log({json.dumps(LAUNCH_LINE)});
                console.log("  2 passing (1s)");
                """
            )
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            result.stdout,
            "  2 passing (1s)\n(left out 3 lines " + LAUNCH_NOTE + "\n",
        )

    def test_the_wrapper_says_nothing_that_trips_a_search_for_error_or_warning(
        self,
    ) -> None:
        result = self._run(
            textwrap.dedent(
                f"""
                console.log({json.dumps(LAUNCH_LINE)});
                console.log({json.dumps(NETWORK_LINE)});
                console.log("  2 passing (1s)");
                """
            )
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("(left out 1 line " + LAUNCH_NOTE, result.stdout)
        self.assertIn("(left out 1 line " + NETWORK_NOTE, result.stdout)
        self.assertNotRegex(
            result.stdout + result.stderr, re.compile(r"\berror\b|\bwarning\b", re.I)
        )

    def test_the_two_kinds_are_counted_apart_and_each_has_its_own_note(self) -> None:
        result = self._run(
            textwrap.dedent(
                f"""
                console.log({json.dumps(NETWORK_LINE)});
                console.log({json.dumps(LAUNCH_LINE)});
                console.error({json.dumps(NETWORK_LINE)});
                console.log("  2 passing (1s)");
                console.error({json.dumps(NETWORK_LINE)});
                """
            )
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            result.stdout,
            "  2 passing (1s)\n"
            "(left out 3 lines " + NETWORK_NOTE + "\n"
            "(left out 1 line " + LAUNCH_NOTE + "\n",
        )

    def test_a_run_with_one_kind_has_the_note_of_that_kind_only(self) -> None:
        launch_only = self._run(f"console.log({json.dumps(LAUNCH_LINE)});")
        self.assertEqual(launch_only.returncode, 0, launch_only.stderr)
        self.assertEqual(launch_only.stdout, "(left out 1 line " + LAUNCH_NOTE + "\n")
        network_only = self._run(f"console.log({json.dumps(NETWORK_LINE)});")
        self.assertEqual(network_only.returncode, 0, network_only.stderr)
        self.assertEqual(network_only.stdout, "(left out 1 line " + NETWORK_NOTE + "\n")

    def test_a_run_without_the_line_prints_no_note_about_it(self) -> None:
        result = self._run('console.log("  1 passing");')
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "  1 passing\n")
        self.assertEqual(result.stderr, "")

    def test_a_complaint_about_any_other_option_still_shows(self) -> None:
        other = (
            "Warning: 'disable-gpu' is not in the list of known options, "
            "but still passed to Electron/Chromium."
        )
        result = self._run(
            textwrap.dedent(
                f"""
                console.log({json.dumps(other)});
                console.error({json.dumps(LAUNCH_LINE)});
                console.log("  1 passing");
                """
            )
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            result.stdout,
            other + "\n  1 passing\n(left out 1 line " + LAUNCH_NOTE + "\n",
        )

    def test_a_failing_run_keeps_its_exit_code_and_its_failure_output(self) -> None:
        result = self._run(
            textwrap.dedent(
                f"""
                console.log({json.dumps(LAUNCH_LINE)});
                console.log("  1 failing");
                console.error("AssertionError [ERR_ASSERTION]: expected 3 to be above 5");
                process.exit(3);
                """
            )
        )
        self.assertEqual(result.returncode, 3)
        self.assertIn("1 failing", result.stdout)
        self.assertIn("AssertionError [ERR_ASSERTION]", result.stderr)
        self.assertIn("(left out 1 line " + LAUNCH_NOTE, result.stdout)
        self.assertNotIn(
            "cached-data' is not in the list", result.stdout + result.stderr
        )

    def test_a_line_between_a_left_out_line_and_its_stack_ends_the_stack_pass(
        self,
    ) -> None:
        # R745: the stack of a left-out line goes with it, up to the first other line.
        # The launch line is such a line, so what follows it is not hidden by accident.
        result = self._run(
            textwrap.dedent(
                f"""
                console.log({json.dumps(NETWORK_LINE)});
                console.log({json.dumps(STACK)});
                console.log({json.dumps(LAUNCH_LINE)});
                console.log({json.dumps(STACK)});
                console.log("  1 passing");
                """
            )
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            result.stdout,
            STACK + "\n  1 passing\n"
            "(left out 2 lines " + NETWORK_NOTE + "\n"
            "(left out 1 line " + LAUNCH_NOTE + "\n",
        )

    def test_the_launch_line_does_not_start_a_stack_pass(self) -> None:
        result = self._run(
            textwrap.dedent(
                f"""
                console.log({json.dumps(LAUNCH_LINE)});
                console.log({json.dumps(STACK)});
                console.log("  1 passing");
                """
            )
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            result.stdout,
            STACK + "\n  1 passing\n(left out 1 line " + LAUNCH_NOTE + "\n",
        )

    def test_the_two_streams_are_filtered_independently(self) -> None:
        result = self._run(
            textwrap.dedent(
                f"""
                const write = (stream, text) =>
                  new Promise((resolve) => stream.write(text, resolve));
                const pause = () => new Promise((resolve) => setTimeout(resolve, 300));
                (async () => {{
                  await write(process.stdout, {json.dumps(NETWORK_LINE)} + "\\n");
                  await pause();
                  await write(process.stderr, {json.dumps(LAUNCH_LINE)} + "\\n");
                  await pause();
                  await write(process.stdout, {json.dumps(STACK)} + "\\n");
                  await write(process.stdout, "  1 passing\\n");
                }})();
                """
            )
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, "")
        # the launch line on the other stream did not end the stack pass of this one
        self.assertNotIn("queryRawGalleryExtensions", result.stdout)
        self.assertIn("1 passing", result.stdout)
        self.assertIn("(left out 1 line " + LAUNCH_NOTE, result.stdout)
        self.assertIn("(left out 2 lines " + NETWORK_NOTE, result.stdout)

    def test_the_line_is_left_out_when_a_colour_code_wraps_it(self) -> None:
        coloured = "\u001b[33m" + LAUNCH_LINE + "\u001b[0m"
        result = self._run(f"console.log({json.dumps(coloured)});")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "(left out 1 line " + LAUNCH_NOTE + "\n")

    def test_the_lines_of_a_look_alike_stay_and_are_not_counted(self) -> None:
        result = self._run(f"for (const line of {json.dumps(KEPT)}) console.log(line);")
        self.assertEqual(result.returncode, 0, result.stderr)
        # every look-alike comes through unchanged and in order, with no note after it
        self.assertEqual(result.stdout, "".join(line + "\n" for line in KEPT))
        self.assertEqual(result.stderr, "")


if __name__ == "__main__":
    unittest.main()
