"""W3C / UAX #9 bidi-isolation helper contract (Batch-3 H14).

Why this matters
----------------
When a right-to-left locale (Arabic, Hebrew, Farsi) renders a string
interpolating a left-to-right value — e.g. a filename, URL, or a
person's name written in Latin script — the Unicode Bidirectional
Algorithm can reorder glyphs in unexpected ways. The W3C
``qa-bidi-unicode-controls`` guide and Unicode UAX #9 §3.1 recommend
wrapping the embedded fragment with U+2068 FIRST STRONG ISOLATE (FSI)
and U+2069 POP DIRECTIONAL ISOLATE (PDI) — equivalent to
``<bdi dir="auto">`` in HTML but works in plain text, node sinks and
VSCode webview Output Channels alike.

Mozilla's Project Fluent ships this as the default for all
interpolated slots (``fluent.js`` ``@projectfluent/fluent-bundle``),
and ICU4J 74 added the same wrap through its
``MessageFormatter.formatWithBidiIsolate`` helper. The Unicode
Consortium's own recommendation is "enable isolation by default for
all future bidi embeddings where markup is not available".

Our runtime doesn't yet render any RTL locale, but the tooling needs
to be in place **before** we ship Arabic/Hebrew so we never discover
the bug inside a released build. ``AIIA_I18N.wrapBidi(str)`` is the
public helper; callers that stitch strings by hand (log lines, copy
buttons showing verbatim user input next to an i18n'd message) use
it explicitly.

Contract
--------
* ``wrapBidi(str)`` returns ``'\\u2068' + str + '\\u2069'``.
* Null / undefined / missing → empty string (never throws).
* Non-strings → stringified first, then wrapped.
* Already-wrapped strings (first char FSI, last char PDI) pass through
  unchanged — idempotent, so repeated calls at nested layers of the
  stack never balloon into ``FSI·FSI·FSI·…·PDI·PDI·PDI``.
* The helper is a public API (exposed on ``AIIA_I18N``) so both the
  Web UI and the VSCode webview copies must ship it with byte-parity.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import textwrap
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEBUI_I18N = ROOT / "static" / "js" / "i18n.js"
VSCODE_I18N = ROOT / "packages" / "vscode" / "i18n.js"

FSI = "\u2068"
PDI = "\u2069"


def _node_available() -> bool:
    return shutil.which("node") is not None


def _run_node(i18n_path: Path, body: str) -> tuple[int, str, str]:
    harness = textwrap.dedent(
        """
        globalThis.window = globalThis;
        globalThis.document = undefined;
        globalThis.navigator = { language: 'en' };
        require(%(path)s);
        const api = globalThis.AIIA_I18N;
        """
    ) % {"path": json.dumps(str(i18n_path))}
    proc = subprocess.run(
        ["node", "-e", harness + "\n" + body],
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    return proc.returncode, proc.stdout, proc.stderr


class _WrapBidiMixin(unittest.TestCase):
    __test__ = False
    I18N_PATH: Path

    def test_wraps_plain_string_with_fsi_pdi(self) -> None:
        body = "process.stdout.write(api.wrapBidi('Ada Lovelace'));"
        code, out, err = _run_node(self.I18N_PATH, body)
        self.assertEqual(code, 0, err)
        self.assertEqual(out, FSI + "Ada Lovelace" + PDI)

    def test_empty_string_round_trips_to_empty(self) -> None:
        """FSI/PDI of an empty string would still be two invisible
        code points — we treat empty input as "nothing to isolate"
        instead and return ``''`` so UI lengths stay as expected.
        """
        body = "process.stdout.write(JSON.stringify(api.wrapBidi('')));"
        code, out, err = _run_node(self.I18N_PATH, body)
        self.assertEqual(code, 0, err)
        self.assertEqual(json.loads(out), "")

    def test_null_undefined_return_empty_string(self) -> None:
        body = (
            "process.stdout.write("
            "JSON.stringify([api.wrapBidi(null), api.wrapBidi(undefined), api.wrapBidi()])"
            ");"
        )
        code, out, err = _run_node(self.I18N_PATH, body)
        self.assertEqual(code, 0, err)
        self.assertEqual(json.loads(out), ["", "", ""])

    def test_coerces_number_to_string_then_wraps(self) -> None:
        body = "process.stdout.write(api.wrapBidi(42));"
        code, out, err = _run_node(self.I18N_PATH, body)
        self.assertEqual(code, 0, err)
        self.assertEqual(out, FSI + "42" + PDI)

    def test_idempotent_on_already_wrapped_input(self) -> None:
        payload = FSI + "abc" + PDI
        body = f"process.stdout.write(api.wrapBidi({json.dumps(payload)}));"
        code, out, err = _run_node(self.I18N_PATH, body)
        self.assertEqual(code, 0, err)
        self.assertEqual(out, payload)

    def test_isolates_rtl_segment_between_ltr_text(self) -> None:
        """The canonical bug this fixes: a Hebrew placeholder sandwiched
        between English words. Without FSI/PDI, UBA bleeds directional
        runs across the boundary. The wrapper must produce exactly
        ``…FSIעבריתPDI…`` so the Hebrew segment owns its own isolate.
        """
        hebrew = "עברית"
        body = f"process.stdout.write(api.wrapBidi({json.dumps(hebrew)}));"
        code, out, err = _run_node(self.I18N_PATH, body)
        self.assertEqual(code, 0, err)
        self.assertEqual(out, FSI + hebrew + PDI)

    def test_exposed_on_public_api_surface(self) -> None:
        body = "process.stdout.write(typeof api.wrapBidi);"
        code, out, err = _run_node(self.I18N_PATH, body)
        self.assertEqual(code, 0, err)
        self.assertEqual(out, "function")


@unittest.skipUnless(_node_available(), "node runtime unavailable")
class TestWrapBidiWebUI(_WrapBidiMixin):
    __test__ = True
    I18N_PATH = WEBUI_I18N


@unittest.skipUnless(_node_available(), "node runtime unavailable")
class TestWrapBidiVSCode(_WrapBidiMixin):
    __test__ = True
    I18N_PATH = VSCODE_I18N


@unittest.skipUnless(_node_available(), "node runtime unavailable")
class TestWrapBidiByteParity(unittest.TestCase):
    """The helper's behaviour must match byte-for-byte across the two
    ``i18n.js`` copies for every input — this is the same contract we
    enforce for the rest of the public API."""

    def test_parity_over_mixed_latin_cyrillic_hebrew_cjk_samples(self) -> None:
        samples = [
            "Ada",
            "Иван",  # Cyrillic
            "עברית",  # Hebrew
            "abc مرحبا 123",  # mixed Latin + Arabic + digits
            "",
            "45.6",
            FSI + "already" + PDI,
        ]
        body = (
            "process.stdout.write(JSON.stringify(["
            + ",".join(f"api.wrapBidi({json.dumps(s)})" for s in samples)
            + "]));"
        )
        outputs: list[list[str]] = []
        for path in (WEBUI_I18N, VSCODE_I18N):
            code, out, err = _run_node(path, body)
            self.assertEqual(code, 0, err)
            outputs.append(json.loads(out))
        self.assertEqual(outputs[0], outputs[1])


if __name__ == "__main__":
    unittest.main()
