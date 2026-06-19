"""Locale JSON fetches should use the shared versioned URL builder."""

from __future__ import annotations

import json
import shutil
import subprocess
import textwrap
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
WEBUI_I18N = REPO_ROOT / "src" / "ai_intervention_agent" / "static" / "js" / "i18n.js"
SETTINGS_MANAGER = (
    REPO_ROOT
    / "src"
    / "ai_intervention_agent"
    / "static"
    / "js"
    / "settings-manager.js"
)


def _node_available() -> bool:
    return shutil.which("node") is not None


def _run(script: str) -> str:
    proc = subprocess.run(
        ["node", "-e", script],
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"node exited {proc.returncode}\nstdout={proc.stdout!r}\nstderr={proc.stderr!r}"
        )
    return proc.stdout


@unittest.skipUnless(_node_available(), "node runtime unavailable")
class TestLocaleJsonVersionedUrls(unittest.TestCase):
    def test_current_default_and_pseudo_locale_fetches_use_versions(self) -> None:
        script = textwrap.dedent(
            """
            globalThis.window = globalThis;
            globalThis.document = undefined;
            Object.defineProperty(globalThis, 'navigator', { value: { language: 'zh-CN' }, writable: true, configurable: true, enumerable: true });
            globalThis.AIIA_LOCALE_VERSIONS = {
              en: 'en123',
              'zh-CN': 'zh123',
              pseudo: 'ps123'
            };
            const seen = [];
            globalThis.fetch = async (url) => {
              seen.push(String(url));
              return { ok: true, async json() { return { hello: 'ok' }; } };
            };
            require(%(path_literal)s);
            const api = globalThis.AIIA_I18N;
            (async () => {
              await api.init({ lang: 'zh-CN', localeBaseUrl: '/static/locales' });
              await globalThis.AIIA_I18N__test.flushPendingLoads();
              await api.loadLocale('pseudo');
              process.stdout.write(JSON.stringify(seen));
            })().catch(e => { console.error(e); process.exit(1); });
            """
        ) % {"path_literal": json.dumps(str(WEBUI_I18N))}
        urls = json.loads(_run(script))

        self.assertIn("/static/locales/zh-CN.json?v=zh123", urls)
        self.assertIn("/static/locales/en.json?v=en123", urls)
        self.assertIn("/static/locales/_pseudo/pseudo.json?v=ps123", urls)

    def test_without_version_map_keeps_legacy_urls(self) -> None:
        script = textwrap.dedent(
            """
            globalThis.window = globalThis;
            globalThis.document = undefined;
            Object.defineProperty(globalThis, 'navigator', { value: { language: 'zh-CN' }, writable: true, configurable: true, enumerable: true });
            const seen = [];
            globalThis.fetch = async (url) => {
              seen.push(String(url));
              return { ok: true, async json() { return { hello: 'ok' }; } };
            };
            require(%(path_literal)s);
            const api = globalThis.AIIA_I18N;
            (async () => {
              await api.init({ lang: 'zh-CN', localeBaseUrl: '/static/locales' });
              await globalThis.AIIA_I18N__test.flushPendingLoads();
              process.stdout.write(JSON.stringify(seen));
            })().catch(e => { console.error(e); process.exit(1); });
            """
        ) % {"path_literal": json.dumps(str(WEBUI_I18N))}
        urls = json.loads(_run(script))

        self.assertIn("/static/locales/zh-CN.json", urls)
        self.assertIn("/static/locales/en.json", urls)


def test_settings_manager_delegates_locale_url_building_to_i18n() -> None:
    source = SETTINGS_MANAGER.read_text(encoding="utf-8")

    assert '"/static/locales/" + targetLang + ".json"' not in source
    assert '"/static/locales/en.json"' not in source
    assert "loadLocale(targetLang)" in source
    assert 'loadLocale("en")' in source
