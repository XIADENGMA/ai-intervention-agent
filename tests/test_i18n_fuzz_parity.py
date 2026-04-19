"""Pinned random-fuzz parity test (Batch-3 H16).

Why this matters
----------------
Hand-written unit tests have caught the specific edge cases we
thought to write. They cannot, by construction, find the ones we
haven't thought of: a random ICU template that happens to exercise
a corner where ``_renderIcu`` leaks PUA markers, where the
apostrophe tokenizer double-unescapes a literal, where nested
plurals drop their ``#`` scope, etc.

FormatJS's own test suite ships snapshot fixtures but no fuzz
driver. Their maintainers have spoken openly on the Unicode mailing
list about "bugs we only found after users shipped"; Airbnb's
polyglot.js and lingui.js have each taken at least one regression
through the same class of gap.

Batch-3 H16 closes this gap with a **deterministic** random fuzz:

* A single Python RNG seed (``SEED = 0xA11ABADE``) drives a grammar
  that produces ~200 random templates + params.
* Those templates are rendered through ``static/js/i18n.js`` and
  ``packages/vscode/i18n.js`` in a single Node invocation each
  (so runtime stays in the sub-second range).
* Assertions:
  - every call returns without throwing (``out`` field present);
  - output is a ``string``;
  - Web ↔ VSCode outputs are byte-identical;
  - no U+F0000–U+F0FFF PUA character leaks (the apostrophe marker
    must be stripped before return).

Because the RNG is seeded, CI reproduces the exact matrix every
run. A failing template is printed alongside its seed index so the
regression can be pinned into the permanent suite.
"""

from __future__ import annotations

import json
import random
import shutil
import string
import subprocess
import textwrap
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEBUI_I18N = ROOT / "static" / "js" / "i18n.js"
VSCODE_I18N = ROOT / "packages" / "vscode" / "i18n.js"

SEED = 0xA11ABADE
ITERATIONS = 200
MAX_DEPTH = 2
PUA_RANGE = (0xF0000, 0xF1000)

_ALPHABET = string.ascii_letters + string.digits + " ,.-!?"


def _node_available() -> bool:
    return shutil.which("node") is not None


def _literal(rng: random.Random) -> str:
    """A short text fragment. Occasionally includes apostrophes
    and hash marks so the tokenizer is exercised."""
    length = rng.randint(0, 12)
    pieces = rng.choices(_ALPHABET, k=length)
    # sprinkle in syntax-sensitive chars
    if rng.random() < 0.15:
        pieces.append("'")
    if rng.random() < 0.10:
        pieces.append("''")
    if rng.random() < 0.05:
        pieces.append("'{not-a-brace}'")
    if rng.random() < 0.15:
        pieces.append("#")
    return "".join(pieces)


def _mustache(rng: random.Random, args: list[str]) -> str:
    args.append(f"p{len(args)}")
    return "{{" + args[-1] + "}}"


def _plural(rng: random.Random, depth: int, args: list[str]) -> str:
    name = f"n{len(args)}"
    args.append(name)
    kinds = ["plural", "selectordinal"]
    kind = rng.choice(kinds)
    one_body = _body(rng, depth + 1, args)
    other_body = _body(rng, depth + 1, args)
    few_body = _body(rng, depth + 1, args) if rng.random() < 0.4 else None
    parts = [f"one {{{one_body}}}"]
    if few_body is not None:
        parts.append(f"few {{{few_body}}}")
    parts.append(f"other {{{other_body}}}")
    return "{" + name + ", " + kind + ", " + " ".join(parts) + "}"


def _select(rng: random.Random, depth: int, args: list[str]) -> str:
    name = f"s{len(args)}"
    args.append(name)
    opt_a = _body(rng, depth + 1, args)
    opt_b = _body(rng, depth + 1, args)
    other = _body(rng, depth + 1, args)
    return (
        "{"
        + name
        + ", select, a {"
        + opt_a
        + "} b {"
        + opt_b
        + "} other {"
        + other
        + "}}"
    )


def _body(rng: random.Random, depth: int, args: list[str]) -> str:
    """Randomly mix literal / mustache / nested blocks up to MAX_DEPTH."""
    pieces: list[str] = []
    segments = rng.randint(1, 3)
    for _ in range(segments):
        roll = rng.random()
        if roll < 0.5 or depth >= MAX_DEPTH:
            pieces.append(_literal(rng))
        elif roll < 0.7:
            pieces.append(_mustache(rng, args))
        elif roll < 0.85:
            pieces.append(_plural(rng, depth, args))
        else:
            pieces.append(_select(rng, depth, args))
    return "".join(pieces)


def _template(rng: random.Random) -> tuple[str, dict]:
    args: list[str] = []
    tpl = _body(rng, 0, args)
    params: dict[str, object] = {}
    for arg in args:
        if arg.startswith(("n", "N")):
            params[arg] = rng.randint(0, 5)
        elif arg.startswith(("s", "S")):
            params[arg] = rng.choice(["a", "b", "c", "d"])
        else:
            params[arg] = rng.choice(["Ada", "42", "", "ünıçödé", "'x'"])
    return tpl, params


def _build_corpus() -> list[dict]:
    rng = random.Random(SEED)
    corpus: list[dict] = []
    for idx in range(ITERATIONS):
        tpl, params = _template(rng)
        corpus.append({"id": idx, "tpl": tpl, "params": params})
    return corpus


def _run_node_batch(i18n_path: Path, corpus: list[dict]) -> list[dict]:
    """Render each corpus entry inside a single node process; write
    the results as a JSON array on stdout."""
    harness = textwrap.dedent(
        """
        globalThis.window = globalThis;
        globalThis.document = undefined;
        globalThis.navigator = { language: 'en' };
        require(%(path)s);
        const api = globalThis.AIIA_I18N;

        const corpus = JSON.parse(process.argv[1]);
        const results = [];
        for (let i = 0; i < corpus.length; i++) {
          const { id, tpl, params } = corpus[i];
          api.registerLocale('en', { k: tpl });
          api.setLang('en');
          try {
            const out = api.t('k', params);
            results.push({ id: id, out: out });
          } catch (err) {
            results.push({ id: id, err: String(err && err.message || err) });
          }
        }
        process.stdout.write(JSON.stringify(results));
        """
    ) % {"path": json.dumps(str(i18n_path))}
    proc = subprocess.run(
        ["node", "-e", harness, "--", json.dumps(corpus)],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    if proc.returncode != 0:
        raise AssertionError(
            f"node batch failed (rc={proc.returncode}): "
            f"stdout={proc.stdout!r} stderr={proc.stderr!r}"
        )
    return json.loads(proc.stdout)


def _has_pua_leak(s: str) -> bool:
    lo, hi = PUA_RANGE
    for ch in s:
        c = ord(ch)
        if lo <= c < hi:
            return True
    return False


@unittest.skipUnless(_node_available(), "node runtime unavailable")
class TestFuzzParity(unittest.TestCase):
    def test_deterministic_fuzz_preserves_byte_parity(self) -> None:
        corpus = _build_corpus()
        web = _run_node_batch(WEBUI_I18N, corpus)
        vsc = _run_node_batch(VSCODE_I18N, corpus)
        self.assertEqual(len(web), ITERATIONS)
        self.assertEqual(len(vsc), ITERATIONS)

        for entry, w, v in zip(corpus, web, vsc, strict=True):
            with self.subTest(id=entry["id"], tpl=entry["tpl"]):
                # neither side throws
                self.assertNotIn(
                    "err",
                    w,
                    f"Web UI threw on seed#{entry['id']}: tpl={entry['tpl']!r}",
                )
                self.assertNotIn(
                    "err",
                    v,
                    f"VSCode threw on seed#{entry['id']}: tpl={entry['tpl']!r}",
                )
                # both return strings
                self.assertIsInstance(w["out"], str)
                self.assertIsInstance(v["out"], str)
                # byte-parity across halves
                self.assertEqual(
                    w["out"],
                    v["out"],
                    f"parity diverged on seed#{entry['id']}:\n  tpl={entry['tpl']!r}\n"
                    f"  web={w['out']!r}\n  vsc={v['out']!r}",
                )
                # no PUA marker leak
                self.assertFalse(
                    _has_pua_leak(w["out"]),
                    f"PUA marker leaked on seed#{entry['id']}: {w['out']!r}",
                )


if __name__ == "__main__":
    unittest.main()
