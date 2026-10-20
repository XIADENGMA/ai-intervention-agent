"""R745: the VS Code host tests do not print VS Code's own failed network lookups.

The extension host tests start a real VS Code. While they run, the workbench of that
VS Code looks things up on the Internet (the marketplace entry of the extension under
test, chat entitlement data, alerts) and prints an error line, sometimes with a stack,
whenever one of those requests fails. On a machine behind a proxy that happens now and
then, so the output of an otherwise green run carried lines such as ``Failed to fetch``
or ``ERROR:net/socket/ssl_client_socket_impl.cc ... handshake failed`` that have nothing
to do with the extension.

``scripts/run_vscode_host_tests.mjs`` runs ``vscode-test`` and leaves exactly those
lines out, then says how many it left out. Everything else, test results, failures,
our own log lines, other Chromium errors, passes through, and the exit code is the
exit code of ``vscode-test``.

The tests load the real script in Node: the filter on samples taken from real runs, and
the whole wrapper around a stand-in command.
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
VSCODE_PACKAGE_JSON = REPO_ROOT / "packages" / "vscode" / "package.json"
VSCODE_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "vscode.yml"

NODE_AVAILABLE = shutil.which("node") is not None

STACK = (
    "    at cYe.queryRawGalleryExtensions (vscode-file://vscode-app/Users/me/repo/packages/"
    "vscode/.vscode-test/vscode-darwin-arm64-1.110.0/Visual%20Studio%20Code.app/Contents/"
    "Resources/app/out/vs/workbench/workbench.desktop.main.js:4850:49483)"
)

NOISE = [
    "[LM] Failed to request chat control data Failed to fetch",
    "Error while getting the latest version for the extension xiadengma.ai-intervention-agent"
    " from https://marketplace.visualstudio.com/_apis/public/gallery/vscode/{publisher}/"
    "{name}/latest. Trying the fallback https://www.vscode-unpkg.net",
    "Error while getting the latest version for the extension xiadengma.ai-intervention-agent."
    " TypeError: Failed to fetch",
    "Failed to fetch: Failed: Failed to fetch",
    "Failed to fetch: TypeError: Failed to fetch",
    "Failed to fetch",
    "[76455:1020/191513.070284:ERROR:net/socket/ssl_client_socket_impl.cc:916] handshake"
    " failed; returned -1, SSL error code 1, net_error -100",
]

KEPT = [
    "    ✔ reconnect backoff keeps growing while the stream flaps (12054ms)",
    "  65 passing (14s)",
    "  1 failing",
    "  1) Extension host SSE / HTTP hardening (real extension host)",
    "     reconnect backoff keeps growing:",
    "AssertionError [ERR_ASSERTION]: expected 3 to be above 5",
    "Error: Timeout of 10000ms exceeded.",
    "Error: connect ECONNREFUSED 127.0.0.1:8080",
    "Failed to fetch /api/tasks: HTTP 500",
    "Failed to fetch tasks",
    "TypeError: Failed to fetch",
    "[ERROR] [ext] event=sse.connect_failed reason=boom",
    "Error while getting the latest version of something else",
    "[1234:1020/191513.070284:ERROR:gpu/command_buffer/service/gles2_cmd_decoder.cc:1]"
    " GL error",
    "[1234:1020/191513.070284:ERROR:net/socket/ssl_client_socket_impl.cc:916] other",
    "[1234:1020/191513.070284:ERROR:net/socket/ssl_server_socket_impl.cc:100] handshake"
    " failed; returned -1, SSL error code 1, net_error -100",
    "    at Context.<anonymous> (/repo/packages/vscode/test/extension.test.js:12:3)",
    "    at async cYe.getExtensions (vscode-file://vscode-app/x/workbench.desktop.main.js:1:1)",
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
class TestWorkbenchNetworkFilter(unittest.TestCase):
    def _classify(self, lines: list[str]) -> list[bool]:
        script = textwrap.dedent(
            f"""
            import {{ createWorkbenchNetworkFilter }} from {json.dumps(WRAPPER.as_uri())};
            const isNoise = createWorkbenchNetworkFilter();
            const lines = {json.dumps(lines)};
            console.log(JSON.stringify(lines.map((line) => isNoise(line))));
            """
        )
        result = _run_node(script)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_each_failed_lookup_line_is_left_out(self) -> None:
        for line in NOISE:
            with self.subTest(line=line[:60]):
                self.assertEqual(self._classify([line]), [True])

    def test_the_stack_of_a_left_out_line_goes_with_it(self) -> None:
        lines = [
            "Failed to fetch: Failed: Failed to fetch",
            STACK,
            STACK,
            "  65 passing",
        ]
        self.assertEqual(self._classify(lines), [True, True, True, False])

    def test_a_line_that_merely_looks_similar_stays(self) -> None:
        for line in KEPT:
            with self.subTest(line=line[:60]):
                self.assertEqual(self._classify([line]), [False])

    def test_workbench_stack_lines_without_a_left_out_line_before_them_stay(
        self,
    ) -> None:
        lines = ["AssertionError: boom", STACK]
        self.assertEqual(self._classify(lines), [False, False])

    def test_a_stack_from_other_code_after_a_left_out_line_stays(self) -> None:
        lines = [
            "Failed to fetch",
            "    at Context.<anonymous> (/repo/packages/vscode/test/extension.test.js:12:3)",
        ]
        self.assertEqual(self._classify(lines), [True, False])

    def test_the_stack_pass_ends_with_the_first_other_line(self) -> None:
        lines = ["Failed to fetch", STACK, "  ✔ next test", STACK]
        self.assertEqual(self._classify(lines), [True, True, False, False])

    def test_colour_codes_do_not_hide_a_line_from_the_filter(self) -> None:
        coloured = "\u001b[31mFailed to fetch\u001b[0m"
        self.assertEqual(self._classify([coloured]), [True])


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

    def test_results_pass_through_and_the_noise_is_counted(self) -> None:
        result = self._run(
            textwrap.dedent(
                f"""
                console.log("  ✔ first test");
                console.log("Failed to fetch");
                console.error("[LM] Failed to request chat control data Failed to fetch");
                console.log({json.dumps(STACK)});
                console.log("  2 passing (1s)");
                """
            )
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("✔ first test", result.stdout)
        self.assertIn("2 passing (1s)", result.stdout)
        self.assertNotIn("Failed to fetch", result.stdout.split("(left out")[0])
        self.assertNotIn("chat control", result.stderr)
        self.assertIn("(left out 3 lines", result.stdout)
        self.assertNotRegex(
            result.stdout + result.stderr, re.compile(r"\berror\b|\bwarning\b", re.I)
        )

    def test_a_run_without_noise_prints_nothing_extra(self) -> None:
        result = self._run('console.log("  1 passing");')
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "  1 passing\n")
        self.assertEqual(result.stderr, "")

    def test_a_failing_run_keeps_its_exit_code_and_its_failure_output(self) -> None:
        result = self._run(
            textwrap.dedent(
                """
                console.log("  1 failing");
                console.error("AssertionError [ERR_ASSERTION]: expected 3 to be above 5");
                console.log("Failed to fetch");
                process.exit(3);
                """
            )
        )
        self.assertEqual(result.returncode, 3)
        self.assertIn("1 failing", result.stdout)
        self.assertIn("AssertionError [ERR_ASSERTION]", result.stderr)
        self.assertIn("(left out 1 line ", result.stdout)

    def test_a_command_that_cannot_start_fails_the_run(self) -> None:
        result = subprocess.run(
            ["node", str(WRAPPER), "--", "definitely-not-a-command-r745"],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("definitely-not-a-command-r745", result.stderr)
        self.assertEqual(
            len(result.stderr.strip().splitlines()),
            1,
            "one message, not an uncaught exception with a stack",
        )

    def test_a_command_killed_by_a_signal_fails_the_run(self) -> None:
        result = self._run('process.kill(process.pid, "SIGKILL");')
        self.assertNotEqual(result.returncode, 0)

    def test_the_two_streams_are_filtered_independently(self) -> None:
        result = self._run(
            textwrap.dedent(
                f"""
                const write = (stream, text) =>
                  new Promise((resolve) => stream.write(text, resolve));
                const pause = () => new Promise((resolve) => setTimeout(resolve, 300));
                (async () => {{
                  await write(process.stdout, "Failed to fetch\\n");
                  await pause();
                  await write(process.stderr, "  a plain line on the other stream\\n");
                  await pause();
                  await write(process.stdout, {json.dumps(STACK)} + "\\n");
                  await write(process.stdout, "  1 passing\\n");
                }})();
                """
            )
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("queryRawGalleryExtensions", result.stdout)
        self.assertIn("a plain line on the other stream", result.stderr)
        self.assertIn("1 passing", result.stdout)

    def test_output_that_ends_without_a_newline_is_not_lost(self) -> None:
        result = self._run('process.stdout.write("  last line without newline");')
        self.assertEqual(result.returncode, 0)
        self.assertIn("last line without newline", result.stdout)


class TestWiring(unittest.TestCase):
    def test_npm_test_goes_through_the_wrapper(self) -> None:
        scripts = json.loads(VSCODE_PACKAGE_JSON.read_text(encoding="utf-8"))["scripts"]
        self.assertEqual(
            scripts["test"], "node ../../scripts/run_vscode_host_tests.mjs"
        )

    def test_the_wrapper_still_runs_vscode_test_with_the_project_config(self) -> None:
        source = WRAPPER.read_text(encoding="utf-8")
        self.assertIn('require.resolve("@vscode/test-cli")', source)
        self.assertIn('"bin.mjs"', source)
        self.assertIn('"--config", ".vscode-test.mjs"', source)
        self.assertIn('"packages",', source)
        self.assertIn('"vscode",', source)

    def test_a_change_to_the_wrapper_triggers_the_extension_workflow(self) -> None:
        workflow = VSCODE_WORKFLOW.read_text(encoding="utf-8")
        self.assertEqual(
            workflow.count('- "scripts/run_vscode_host_tests.mjs"'),
            2,
            "both the push and the pull_request filter must list the wrapper",
        )

    def test_every_filter_pattern_is_anchored_to_the_start_of_the_line(self) -> None:
        source = WRAPPER.read_text(encoding="utf-8")
        block = source.split("const WORKBENCH_NETWORK_LINES = [", 1)[1].split("];", 1)[
            0
        ]
        patterns = [line.strip() for line in block.splitlines() if line.strip()]
        self.assertGreaterEqual(len(patterns), 4)
        for pattern in patterns:
            with self.subTest(pattern=pattern):
                self.assertTrue(
                    pattern.startswith("/^"),
                    "a pattern that can match in the middle of a line could hide ours",
                )


if __name__ == "__main__":
    unittest.main()
