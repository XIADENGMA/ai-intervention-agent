"""R773: a code block's copy button never keeps an untranslated i18n key.

``DOMSecurity.createCopyButton`` builds the button while the agent's message is
rendered. On a page whose language is detected (the default) the locale file is
fetched by ``AIIA_I18N.init()``, and the message can be on screen before it has
arrived. ``t()`` then answers with the key itself, and the old button wrote it into
its own markup for good: the label read ``page.copyCode``, the accessible name was the
key too, and neither the translation pass that runs when ``init()`` finishes nor a
later language switch could repair it, because nothing on the button said which key it
stood for. The same snapshot of the idle look was also what the button went back to
after a click, so a button built too early brought the key back two seconds after
"Copied".

The label is now a ``<span data-i18n="page.copyCode">`` and the accessible name is
bound with ``data-i18n-aria-label``, the way the VS Code panel's copy button already
binds its title. Until a translation exists the span stays empty rather than showing
the key. The idle look is rebuilt whenever it is needed, and the feedback labels are
read when the button is clicked, so they follow the language of that moment.

The tests run the real ``i18n.js`` and ``dom-security.js`` in Node with a fake button
and a fake root for ``translateDOM`` that finds the button's span and attributes, so
what is checked is the contract between the two files, not a copy of it.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import textwrap
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
STATIC = REPO_ROOT / "src" / "ai_intervention_agent" / "static"
DOM_SECURITY_JS = STATIC / "js" / "dom-security.js"
I18N_JS = STATIC / "js" / "i18n.js"
LOCALES = STATIC / "locales"

NODE_AVAILABLE = shutil.which("node") is not None

HARNESS = textwrap.dedent(
    """
    const fs = require('fs');
    const timers = [];
    let nextTimerId = 1;
    globalThis.setTimeout = (fn, delay) => {
      const id = nextTimerId++;
      timers.push({ id, fn, delay, cleared: false, ran: false });
      return id;
    };
    globalThis.clearTimeout = (id) => {
      const timer = timers.find((t) => t.id === id);
      if (timer) timer.cleared = true;
    };
    function runTimer(timer) { timer.ran = true; timer.fn(); }

    const escapeHtml = (value) =>
      String(value).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');

    function makeButton() {
      const classes = new Set();
      const listeners = {};
      return {
        innerHTML: '',
        attrs: {},
        set className(value) {
          classes.clear();
          String(value).split(/\\s+/).filter(Boolean).forEach((c) => classes.add(c));
        },
        get className() { return [...classes].join(' '); },
        classList: {
          add: (...names) => names.forEach((n) => classes.add(n)),
          remove: (...names) => names.forEach((n) => classes.delete(n)),
          contains: (name) => classes.has(name),
        },
        setAttribute(name, value) { this.attrs[name] = String(value); },
        getAttribute(name) { return name in this.attrs ? this.attrs[name] : null; },
        addEventListener(type, handler) { listeners[type] = handler; },
        async click() { await listeners.click(); },
      };
    }

    const SPAN = /<span data-i18n="([^"]*)">([^<]*)<\\/span>/;
    function rootFor(button) {
      return {
        querySelectorAll(selector) {
          const attr = selector.slice(1, -1);
          const found = [];
          if (attr === 'data-i18n') {
            const match = SPAN.exec(button.innerHTML);
            if (match) {
              found.push({
                getAttribute: (name) => (name === 'data-i18n' ? match[1] : null),
                set textContent(value) {
                  button.innerHTML = button.innerHTML.replace(
                    SPAN, () => '<span data-i18n="' + match[1] + '">' + escapeHtml(value) + '</span>'
                  );
                },
              });
            }
          } else if (attr in button.attrs) {
            found.push({
              getAttribute: (name) => (name === attr ? button.attrs[attr] : null),
              setAttribute: (name, value) => { button.attrs[name] = String(value); },
            });
          }
          return found;
        },
      };
    }

    let clipboardFails = false;
    globalThis.window = globalThis;
    globalThis.document = { createElement: () => makeButton() };
    Object.defineProperty(globalThis, 'navigator', {
      value: {
        language: 'en',
        clipboard: {
          async writeText() { if (clipboardFails) throw new Error('denied'); },
        },
      },
      writable: true, configurable: true, enumerable: true,
    });
    require(%(i18n)s);
    require(%(dom_security)s);
    const api = globalThis.AIIA_I18N;
    const EN = JSON.parse(fs.readFileSync(%(en)s, 'utf8'));
    const ZH = JSON.parse(fs.readFileSync(%(zh)s, 'utf8'));
    const create = (text) => globalThis.DOMSecurity.createCopyButton(text);
    const visibleLabel = (button) => {
      const match = SPAN.exec(button.innerHTML);
      return match ? match[2] : null;
    };
    """
) % {
    "i18n": json.dumps(str(I18N_JS)),
    "dom_security": json.dumps(str(DOM_SECURITY_JS)),
    "en": json.dumps(str(LOCALES / "en.json")),
    "zh": json.dumps(str(LOCALES / "zh-CN.json")),
}


def _run(case_js: str) -> dict:
    script = HARNESS + "\n(async () => {\n" + case_js + "\n})();\n"
    proc = subprocess.run(
        ["node", "-e", script],
        capture_output=True,
        check=False,
        text=True,
        timeout=20,
    )
    if proc.returncode != 0:
        raise AssertionError(
            f"node exited {proc.returncode}\nstdout={proc.stdout!r}\nstderr={proc.stderr!r}"
        )
    return json.loads(proc.stdout)


@unittest.skipUnless(NODE_AVAILABLE, "node runtime unavailable")
class TestButtonBuiltBeforeTheLocaleArrives(unittest.TestCase):
    def test_the_label_is_empty_not_the_raw_key_and_is_marked_for_translation(
        self,
    ) -> None:
        result = _run(
            """
            const button = create('code');
            console.log(JSON.stringify({
              html: button.innerHTML,
              label: visibleLabel(button),
              bound: button.attrs['data-i18n-aria-label'],
            }));
            """
        )
        self.assertEqual(result["label"], "")
        self.assertIn('data-i18n="page.copyCode"', result["html"])
        self.assertNotIn(">page.copyCode<", result["html"])
        self.assertEqual(result["bound"], "page.copyCode")

    def test_the_translation_pass_after_init_fills_label_and_name_in(self) -> None:
        result = _run(
            """
            const button = create('code');
            const before = { label: visibleLabel(button), name: button.attrs['aria-label'] };
            api.registerLocale('en', EN);
            api.setLang('en');
            api.translateDOM(rootFor(button));
            console.log(JSON.stringify({
              before,
              after: { label: visibleLabel(button), name: button.attrs['aria-label'] },
            }));
            """
        )
        self.assertEqual(result["before"]["label"], "")
        self.assertEqual(result["after"], {"label": "Copy code", "name": "Copy code"})

    def test_clicking_a_button_built_too_early_never_brings_the_key_back(self) -> None:
        result = _run(
            """
            const button = create('code');
            api.registerLocale('en', EN);
            api.setLang('en');
            await button.click();
            const copied = visibleLabel(button);
            const copiedHtml = button.innerHTML;
            runTimer(timers[0]);
            console.log(JSON.stringify({
              copiedHtml, copied, restored: visibleLabel(button), html: button.innerHTML,
            }));
            """
        )
        self.assertIn("Copied", result["copiedHtml"])
        self.assertNotIn("page.copied", result["copiedHtml"])
        self.assertEqual(result["restored"], "Copy code")
        self.assertNotIn("page.copyCode<", result["html"])

    def test_a_failed_copy_names_the_failure_in_words(self) -> None:
        result = _run(
            """
            const button = create('code');
            api.registerLocale('en', EN);
            api.setLang('en');
            clipboardFails = true;
            await button.click();
            console.log(JSON.stringify({ html: button.innerHTML }));
            """
        )
        self.assertIn("Copy failed", result["html"])
        self.assertNotIn("page.copyFailed", result["html"])


@unittest.skipUnless(NODE_AVAILABLE, "node runtime unavailable")
class TestButtonFollowsTheLanguage(unittest.TestCase):
    def test_a_language_switch_translates_buttons_that_already_exist(self) -> None:
        result = _run(
            """
            api.registerLocale('en', EN);
            api.registerLocale('zh-CN', ZH);
            api.setLang('en');
            const button = create('code');
            const english = { label: visibleLabel(button), name: button.attrs['aria-label'] };
            api.setLang('zh-CN');
            api.translateDOM(rootFor(button));
            console.log(JSON.stringify({
              english,
              chinese: { label: visibleLabel(button), name: button.attrs['aria-label'] },
            }));
            """
        )
        self.assertEqual(result["english"], {"label": "Copy code", "name": "Copy code"})
        self.assertEqual(result["chinese"], {"label": "复制代码", "name": "复制代码"})

    def test_feedback_labels_are_read_when_the_button_is_clicked(self) -> None:
        result = _run(
            """
            api.registerLocale('en', EN);
            api.registerLocale('zh-CN', ZH);
            api.setLang('en');
            const button = create('code');
            api.setLang('zh-CN');
            await button.click();
            const copiedHtml = button.innerHTML;
            runTimer(timers[0]);
            console.log(JSON.stringify({ copiedHtml, restored: visibleLabel(button) }));
            """
        )
        self.assertIn("已复制", result["copiedHtml"])
        self.assertNotIn("Copied", result["copiedHtml"])
        self.assertEqual(result["restored"], "复制代码")

    def test_feedback_during_a_switch_is_not_overwritten_by_the_translation_pass(
        self,
    ) -> None:
        result = _run(
            """
            api.registerLocale('en', EN);
            api.registerLocale('zh-CN', ZH);
            api.setLang('en');
            const button = create('code');
            await button.click();
            const duringFeedback = button.innerHTML;
            api.setLang('zh-CN');
            api.translateDOM(rootFor(button));
            console.log(JSON.stringify({ duringFeedback, afterPass: button.innerHTML }));
            """
        )
        self.assertEqual(result["afterPass"], result["duringFeedback"])
        self.assertIn("Copied", result["afterPass"])


@unittest.skipUnless(NODE_AVAILABLE, "node runtime unavailable")
class TestLabelsAreTextNotMarkup(unittest.TestCase):
    def test_a_label_with_markup_is_escaped_in_every_state(self) -> None:
        result = _run(
            """
            const hostile = '<img src=x onerror=alert(1)>';
            api.registerLocale('en', {
              page: { copyCode: hostile, copied: hostile, copyFailed: hostile },
            });
            api.setLang('en');
            const button = create('code');
            const idle = button.innerHTML;
            await button.click();
            const copied = button.innerHTML;
            clipboardFails = true;
            await button.click();
            const failed = button.innerHTML;
            console.log(JSON.stringify({ idle, copied, failed }));
            """
        )
        for state in ("idle", "copied", "failed"):
            with self.subTest(state=state):
                self.assertNotIn("<img", result[state])
                self.assertIn("&lt;img", result[state])


class TestTheKeysTheButtonUsesExist(unittest.TestCase):
    def test_every_locale_has_the_three_labels(self) -> None:
        for path in sorted(LOCALES.glob("*.json")):
            if path.name.startswith("_"):
                continue
            data = json.loads(path.read_text(encoding="utf-8"))
            for key in ("copyCode", "copied", "copyFailed"):
                with self.subTest(locale=path.name, key=key):
                    self.assertIsInstance(data["page"][key], str)
                    self.assertTrue(data["page"][key])


if __name__ == "__main__":
    unittest.main()
