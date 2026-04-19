"""P9·L5·G1 — runtime pseudo-locale switch regression.

We generate pseudo JSON as part of the build (``gen_pseudo_locale.py``)
but without a way to activate it at runtime, developers never see its
output. These tests guard the four activation paths we want to support:

1. ``normalizeLang('pseudo')`` returns ``'pseudo'`` (rather than
   collapsing to ``en`` / ``zh-CN``).
2. ``loadLocale('pseudo')`` on the Web UI maps to
   ``locales/_pseudo/pseudo.json`` via the special-case in
   ``i18n.js``.
3. The Web UI ``detectLang`` picks up ``?lang=pseudo`` / the
   ``localStorage['aiia_i18n_lang']`` sticky opt-in.
4. The VSCode extension setting
   ``ai-intervention-agent.i18n.pseudoLocale`` is declared correctly
   (schema-only; runtime wiring is smoke-tested by the mocha harness).

Why pytest instead of the existing mocha suite? The mocha harness is
VSCode-only (extension-host side); these switches live in the shared
``i18n.js`` and must be verified against *both* copies. Pytest is the
cross-cutting layer. Tests SKIP when ``node`` isn't available so
non-CI developer laptops without Node can still run the suite."""

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
VSCODE_PACKAGE_JSON = ROOT / "packages" / "vscode" / "package.json"


def _node_available() -> bool:
    return shutil.which("node") is not None


_NODE_MESSAGE = "node runtime unavailable"


def _eval(js: str) -> str:
    proc = subprocess.run(
        ["node", "-e", js],
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


def _harness(i18n_path: Path, body: str, *, with_location: str | None = None) -> str:
    """Load ``i18n.js`` under a simulated browser globals object and
    execute ``body``. Optionally inject a ``window.location`` stub so we
    can test the URL-based pseudo toggle."""
    header = textwrap.dedent(
        """
        globalThis.window = globalThis;
        globalThis.document = undefined;
        globalThis.navigator = { language: 'en' };
        globalThis.localStorage = {
          _m: Object.create(null),
          getItem(k) { return this._m[k] || null; },
          setItem(k, v) { this._m[k] = String(v); },
          removeItem(k) { delete this._m[k]; },
        };
        %(location_stub)s
        require(%(path_literal)s);
        const api = globalThis.AIIA_I18N;
        """
    ) % {
        "path_literal": json.dumps(str(i18n_path)),
        "location_stub": (
            (
                "globalThis.window.location = { search: "
                + json.dumps(with_location)
                + " };"
            )
            if with_location is not None
            else ""
        ),
    }
    return _eval(header + "\n" + body)


@unittest.skipUnless(_node_available(), _NODE_MESSAGE)
class TestPseudoNormalizeLang(unittest.TestCase):
    """``normalizeLang`` must preserve the pseudo tag exactly."""

    def _assert_roundtrip(self, i18n_path: Path) -> None:
        for raw in ("pseudo", "PSEUDO", "xx-AC", "xx", "  pseudo  "):
            out = _harness(
                i18n_path,
                f"process.stdout.write(api.normalizeLang({json.dumps(raw)}));",
            )
            self.assertEqual(out, "pseudo", f"{i18n_path.name}: {raw!r} → {out!r}")

    def test_web_ui_preserves_pseudo(self) -> None:
        self._assert_roundtrip(WEBUI_I18N)

    def test_vscode_preserves_pseudo(self) -> None:
        self._assert_roundtrip(VSCODE_I18N)


@unittest.skipUnless(_node_available(), _NODE_MESSAGE)
class TestPseudoDetectLang(unittest.TestCase):
    """Web UI detectLang priority chain — URL param beats
    localStorage beats ``navigator.language``."""

    def test_url_query_param_wins(self) -> None:
        out = _harness(
            WEBUI_I18N,
            "process.stdout.write(api.detectLang());",
            with_location="?lang=pseudo",
        )
        self.assertEqual(out, "pseudo")

    def test_localstorage_fallback(self) -> None:
        out = _harness(
            WEBUI_I18N,
            textwrap.dedent(
                """
                globalThis.localStorage.setItem('aiia_i18n_lang', 'pseudo');
                process.stdout.write(api.detectLang());
                """
            ).strip(),
        )
        self.assertEqual(out, "pseudo")

    def test_navigator_language_still_works(self) -> None:
        # Without ?lang= or localStorage, navigator.language wins.
        out = _harness(
            WEBUI_I18N,
            textwrap.dedent(
                """
                // Force navigator.language to something zh-shaped; should
                // collapse to 'zh-CN'.
                globalThis.navigator = { language: 'zh-HK' };
                process.stdout.write(api.detectLang());
                """
            ).strip(),
        )
        self.assertEqual(out, "zh-CN")


@unittest.skipUnless(_node_available(), _NODE_MESSAGE)
class TestPseudoLoadLocaleRouting(unittest.TestCase):
    """``loadLocale('pseudo')`` on the Web UI must route to the
    ``_pseudo/pseudo.json`` sub-path instead of ``pseudo.json`` at
    locale base root."""

    def test_web_ui_maps_pseudo_to_subdir(self) -> None:
        body = textwrap.dedent(
            """
            const seen = [];
            globalThis.fetch = async (url) => {
              seen.push(url);
              // Return a minimal locale body so registerLocale succeeds
              // and the test doesn't hang on retry logic.
              return {
                ok: true,
                async json() { return { greeting: 'hi' }; }
              };
            };
            (async () => {
              await api.init({ localeBaseUrl: '/locales', lang: 'pseudo' });
              process.stdout.write(JSON.stringify(seen));
            })();
            """
        ).strip()
        out = _harness(WEBUI_I18N, body)
        urls = json.loads(out)
        # The lang=pseudo load MUST go to the _pseudo subdirectory.
        self.assertIn("/locales/_pseudo/pseudo.json", urls)


class TestPseudoVscodeSetting(unittest.TestCase):
    """VSCode package.json must declare the pseudo-locale setting so
    ``settings.json`` discovery works in the Command Palette."""

    def test_setting_declared(self) -> None:
        pkg = json.loads(VSCODE_PACKAGE_JSON.read_text(encoding="utf-8"))
        props = (
            pkg.get("contributes", {}).get("configuration", {}).get("properties", {})
        )
        self.assertIn("ai-intervention-agent.i18n.pseudoLocale", props)
        spec = props["ai-intervention-agent.i18n.pseudoLocale"]
        self.assertEqual(spec.get("type"), "boolean")
        self.assertEqual(spec.get("default"), False)
        # Experimental tag keeps VSCode from surfacing it as a
        # "suggested" setting in the default Settings view.
        self.assertIn("experimental", spec.get("tags", []))


if __name__ == "__main__":
    unittest.main()
