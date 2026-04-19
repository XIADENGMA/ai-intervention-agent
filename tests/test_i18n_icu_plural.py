"""L3·G1: verify the ICU MessageFormat subset baked into ``t()`` works as
expected for plural/select + ``{{param}}`` mustache interpolation.

Why a pytest and not a JS runner
--------------------------------
The ICU parser is implemented twice — once in ``static/js/i18n.js`` and
once in ``packages/vscode/i18n.js`` (byte-for-byte mirror of the parse
logic, per the T1 contract that static/js is the real source and the
VSCode copy is a packaging mirror). Rather than spin up jsdom or a full
node mocha environment for 20 micro-tests, we exercise the parser by
evaluating the JS module inside Python via a minimal Node subprocess.
That keeps the test suite hermetic (no browser dependency) and every
contributor's ``uv run pytest`` still exercises the plural logic against
the *real* source file.

Fallback: when Node isn't available on the contributor's machine, the
test is SKIPPED rather than failed — the CLI gate (``npm run
vscode:check``) still runs it on every CI run via the mocha test below
in ``packages/vscode/test/extension.test.js``.

Scope of this test
------------------
    * Mustache-only messages still work (no ICU in source).
    * ``{n, plural, =0 {…} one {…} other {…}}`` picks the right branch
      for English (one/other) and Chinese (always other).
    * ``#`` inside plural body is replaced with ``Intl.NumberFormat``-
      rendered numeric value.
    * ``=N`` exact match beats CLDR category.
    * ``{g, select, male {…} female {…} other {…}}`` picks by string
      key with ``other`` fallback.
    * Mixed ICU + mustache in the same template.
    * Non-existent key → returns key (runtime forgiveness contract).
"""

from __future__ import annotations

import json
import shutil
import subprocess
import textwrap
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
WEBUI_I18N = REPO_ROOT / "static" / "js" / "i18n.js"
VSCODE_I18N = REPO_ROOT / "packages" / "vscode" / "i18n.js"


def _node_available() -> bool:
    return shutil.which("node") is not None


def _render_with_node(
    i18n_path: Path,
    locale: dict,
    lang: str,
    key: str,
    params: dict | None,
) -> str:
    """Evaluate i18n.js inside node and call ``t(key, params)``.

    The i18n module attaches itself to ``globalThis.AIIA_I18N`` (Web UI
    uses ``window.AIIA_I18N``; we polyfill ``window === globalThis``
    inside the harness so both shapes work). We then call ``init`` with
    the locale-as-object, ``setLang``, and ``t``.
    """
    harness = textwrap.dedent(
        """
        globalThis.window = globalThis;
        globalThis.document = undefined;
        globalThis.navigator = { language: %(lang_literal)s };
        // Load the module (it IIFEs itself into globalThis.AIIA_I18N).
        require(%(path_literal)s);
        const api = globalThis.AIIA_I18N;
        api.registerLocale(%(lang_literal)s, %(locale_literal)s);
        api.setLang(%(lang_literal)s);
        const out = api.t(%(key_literal)s, %(params_literal)s);
        process.stdout.write(String(out));
        """
    ) % {
        "path_literal": json.dumps(str(i18n_path)),
        "lang_literal": json.dumps(lang),
        "locale_literal": json.dumps(locale),
        "key_literal": json.dumps(key),
        "params_literal": json.dumps(params) if params is not None else "undefined",
    }
    proc = subprocess.run(
        ["node", "-e", harness],
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"node exited {proc.returncode}:\nstdout={proc.stdout!r}\nstderr={proc.stderr!r}"
        )
    return proc.stdout


@unittest.skipUnless(
    _node_available(),
    "node runtime unavailable; ICU plural is still covered by mocha under npm run vscode:check",
)
class TestIcuPluralWebUI(unittest.TestCase):
    """Exercise ``static/js/i18n.js`` via a node subprocess."""

    I18N_PATH = WEBUI_I18N

    @classmethod
    def _render(
        cls,
        lang: str,
        key: str,
        params: dict | None,
        locale: dict | None = None,
    ) -> str:
        merged = locale if locale is not None else {"test": {}}
        return _render_with_node(cls.I18N_PATH, merged, lang, key, params)

    def test_mustache_only_still_works(self) -> None:
        out = self._render(
            "en",
            "greet",
            {"name": "Ada"},
            {"greet": "Hello, {{name}}!"},
        )
        self.assertEqual(out, "Hello, Ada!")

    def test_plural_english_one_vs_other(self) -> None:
        locale = {"items": "{count, plural, one {# item} other {# items}}"}
        self.assertEqual(self._render("en", "items", {"count": 1}, locale), "1 item")
        self.assertEqual(self._render("en", "items", {"count": 2}, locale), "2 items")
        self.assertEqual(self._render("en", "items", {"count": 0}, locale), "0 items")

    def test_plural_exact_match_beats_category(self) -> None:
        locale = {
            "items": "{count, plural, =0 {no items} one {# item} other {# items}}"
        }
        self.assertEqual(self._render("en", "items", {"count": 0}, locale), "no items")
        self.assertEqual(self._render("en", "items", {"count": 1}, locale), "1 item")

    def test_plural_chinese_always_other(self) -> None:
        locale = {"items": "{count, plural, one {一个物品} other {# 个物品}}"}
        self.assertEqual(
            self._render("zh-CN", "items", {"count": 1}, locale), "1 个物品"
        )
        self.assertEqual(
            self._render("zh-CN", "items", {"count": 5}, locale), "5 个物品"
        )

    def test_select_gender(self) -> None:
        locale = {"liked": "{g, select, male {He} female {She} other {They}} liked it."}
        self.assertEqual(
            self._render("en", "liked", {"g": "male"}, locale), "He liked it."
        )
        self.assertEqual(
            self._render("en", "liked", {"g": "female"}, locale), "She liked it."
        )
        self.assertEqual(
            self._render("en", "liked", {"g": "unknown"}, locale), "They liked it."
        )

    def test_mixed_icu_and_mustache(self) -> None:
        locale = {
            "greet_items": "Hi {{name}}, you have {count, plural, one {# task} other {# tasks}} today."
        }
        self.assertEqual(
            self._render("en", "greet_items", {"name": "Ada", "count": 1}, locale),
            "Hi Ada, you have 1 task today.",
        )
        self.assertEqual(
            self._render("en", "greet_items", {"name": "Ada", "count": 3}, locale),
            "Hi Ada, you have 3 tasks today.",
        )

    def test_missing_key_returns_key(self) -> None:
        self.assertEqual(self._render("en", "missing.key", {}, {}), "missing.key")

    def test_plural_with_null_params_returns_template(self) -> None:
        # Contract: ``t(key)`` (no params) / ``t(key, null)`` returns the
        # raw template — no ICU expansion, no mustache. This lets callers
        # probe the existence of a key without triggering formatter work.
        locale = {"items": "{count, plural, one {# item} other {# items}}"}
        out = self._render("en", "items", None, locale)
        self.assertIn("{count, plural", out)

    def test_plural_missing_count_arg_falls_back_to_other(self) -> None:
        # Passing an object that is missing the plural arg is a program
        # bug, but the runtime must not crash. We coerce missing → 0 so
        # English plural picks the `other` branch (CLDR category for 0).
        locale = {"items": "{count, plural, one {# item} other {# items}}"}
        out = self._render("en", "items", {"unrelated": True}, locale)
        self.assertEqual(out, "0 items")

    # --- ICU MessagePattern apostrophe-escape (L3·G1 follow-up) ---
    #
    # ICU rule recap (from the MessagePattern.ApostropheMode spec and
    # the messageformat/messageformat issue tracker):
    #   * ``''`` anywhere → literal ``'``.
    #   * A single ``'`` immediately followed by ``{``, ``}``, ``|``,
    #     or ``#`` starts a quoted span that lasts until the next
    #     un-paired ``'``. Inside the span, special chars are literal.
    #   * A single ``'`` NOT followed by a special char is literal.
    #
    # Before the fix, our parser had no apostrophe state so:
    #   * ``'{literal}'`` printed with the quotes AND got ``{literal}``
    #     eaten as a malformed ICU attempt.
    #   * ``''`` printed as two characters instead of one.
    # These tests pin the exact ICU semantics.

    def test_apostrophe_double_becomes_single(self) -> None:
        out = self._render(
            "en",
            "msg",
            {},
            {"msg": "it''s fine"},
        )
        self.assertEqual(out, "it's fine")

    def test_apostrophe_escapes_literal_braces(self) -> None:
        out = self._render(
            "en",
            "msg",
            {"x": 1},
            {"msg": "render '{literal}' verbatim"},
        )
        self.assertEqual(out, "render {literal} verbatim")

    def test_apostrophe_escapes_plural_hash(self) -> None:
        # ``'#'`` inside a plural body must print literal '#' rather
        # than the argument's localised number.
        locale = {
            "msg": "{n, plural, one {# item (tag '#')} other {# items (tag '#')}}"
        }
        self.assertEqual(self._render("en", "msg", {"n": 1}, locale), "1 item (tag #)")
        self.assertEqual(self._render("en", "msg", {"n": 3}, locale), "3 items (tag #)")

    def test_apostrophe_lone_remains_literal_without_special_char(self) -> None:
        # ICU spec: an unpaired ' that is NOT followed by {, }, |, # is
        # kept as a literal character. The word "don't" must survive.
        out = self._render(
            "en",
            "msg",
            {},
            {"msg": "I don't know"},
        )
        self.assertEqual(out, "I don't know")

    def test_apostrophe_mixed_double_and_quoted(self) -> None:
        # Canonical ICU example (from the messageformat tracker):
        #   "I said '{''Wow!''}'" → "I said {'Wow!'}"
        # The ``'{`` opens the quoted span, ``''`` inside renders as
        # literal ``'``, and the trailing ``'`` after ``}`` closes it.
        out = self._render(
            "en",
            "msg",
            {},
            {"msg": "I said '{''Wow!''}'"},
        )
        self.assertEqual(out, "I said {'Wow!'}")

    # --- Nested ICU (L3·G1 follow-up) ---
    #
    # Despite the ``YAGNI`` comment in the source, ``_renderIcu`` calls
    # itself recursively on option bodies, so in practice we support
    # arbitrary-depth nesting. These tests pin the actual behaviour so
    # future refactors can't regress it.

    def test_nested_plural_inside_select(self) -> None:
        locale = {
            "msg": (
                "{status, select, "
                "ok {{count, plural, one {# task ready} other {# tasks ready}}} "
                "other {unknown}}"
            )
        }
        self.assertEqual(
            self._render("en", "msg", {"status": "ok", "count": 1}, locale),
            "1 task ready",
        )
        self.assertEqual(
            self._render("en", "msg", {"status": "ok", "count": 5}, locale),
            "5 tasks ready",
        )
        self.assertEqual(
            self._render("en", "msg", {"status": "error"}, locale),
            "unknown",
        )

    def test_three_level_nesting_plural_select_plural(self) -> None:
        # plural → select → plural. Exercises recursion beyond a single
        # level so the implementation can't be simplified to a shallow
        # one-level hack without breaking this case.
        locale = {
            "msg": (
                "{items, plural, "
                "one {{status, select, "
                "new {just added} "
                "done {finished} "
                "other {{count, plural, one {1 step} other {# steps}}}"
                "}} "
                "other {# items}}"
            )
        }
        self.assertEqual(
            self._render(
                "en",
                "msg",
                {"items": 1, "status": "new"},
                locale,
            ),
            "just added",
        )
        self.assertEqual(
            self._render(
                "en",
                "msg",
                {"items": 1, "status": "other", "count": 3},
                locale,
            ),
            "3 steps",
        )
        self.assertEqual(
            self._render("en", "msg", {"items": 5}, locale),
            "5 items",
        )


@unittest.skipUnless(_node_available(), "node runtime unavailable")
class TestIcuPluralVSCode(TestIcuPluralWebUI):
    """Re-run the same suite against ``packages/vscode/i18n.js`` to enforce
    semantic parity between the two mirrored parser implementations."""

    I18N_PATH = VSCODE_I18N


if __name__ == "__main__":
    unittest.main()
