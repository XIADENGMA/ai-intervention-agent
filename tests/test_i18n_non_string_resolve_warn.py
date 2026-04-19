"""``resolve`` 命中非字符串值时的 warn-once 观测（Batch-2 H11）。

H3 加固让 ``resolve`` 对非字符串叶子返回 undefined，但这样就把两类
不同的开发者错误（key 真缺 vs. key 指到 namespace 而不是叶子）合并成
一条 missing-key 警告，导致后者被错误地「补一条重复叶子」掩盖。

对齐 i18next #1594 的做法：额外发一条 warn-once 诊断，指出命中的值
是对象/数字/null 等非字符串。两份 i18n.js 都要做，保持与 missing-key
handler 同等契约。

合约：
  * 末段非字符串 → 按 (lang,key) 记入 once-set；
  * 首次触发 ``console.warn('[i18n] resolved non-string: …')``，含嵌套子键提示；
  * 同 (lang,key) 再次触发不打 warn；
  * 调试钩子 ``dbg.getNonStringHits()`` / ``dbg.resetNonStringHits()``（``AIIA_I18N__test``，非公共 API）；
  * strict 模式 ``setStrict(true)`` 对非字符串直接抛异常，与 missing-key strict 语义对齐。
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
        const dbg = globalThis.AIIA_I18N__test;
        if (!dbg) {
          process.stderr.write('missing AIIA_I18N__test hook');
          process.exit(2);
        }
        api.registerLocale('en', { aiia: { foo: { bar: 'deep' } }, plain: 'ok' });
        api.setLang('en');
        dbg.resetNonStringHits && dbg.resetNonStringHits();
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


class _NonStringResolveMixin(unittest.TestCase):
    __test__ = False
    I18N_PATH: Path

    def test_first_hit_emits_console_warn_with_actionable_hint(self) -> None:
        body = textwrap.dedent(
            """
            var warnings = [];
            console.warn = function () {
              warnings.push(Array.from(arguments).join(' '));
            };
            var out = api.t('aiia.foo');
            process.stdout.write(JSON.stringify({ out: out, warnings: warnings }));
            """
        ).strip()
        code, out, err = _run_node(self.I18N_PATH, body)
        self.assertEqual(code, 0, err)
        payload = json.loads(out)
        self.assertEqual(
            payload["out"],
            "aiia.foo",
            "t() 必须降级到原始 key（与 missing-key 合约一致），避免 UI 出现 'undefined'",
        )
        self.assertEqual(
            len(payload["warnings"]),
            1,
            "non-string resolve 首次触发必须恰好 warn 一次",
        )
        warning = payload["warnings"][0]
        self.assertIn("[i18n]", warning)
        self.assertIn("aiia.foo", warning)
        self.assertIn("non-string", warning.lower())

    def test_repeated_hits_do_not_spam_console(self) -> None:
        body = textwrap.dedent(
            """
            var warnings = [];
            console.warn = function () {
              warnings.push(Array.from(arguments).join(' '));
            };
            for (var i = 0; i < 5; i++) api.t('aiia.foo');
            process.stdout.write(String(warnings.length));
            """
        ).strip()
        code, out, err = _run_node(self.I18N_PATH, body)
        self.assertEqual(code, 0, err)
        self.assertEqual(int(out.strip()), 1)

    def test_distinct_keys_each_warn_once(self) -> None:
        body = textwrap.dedent(
            """
            api.registerLocale('en', {
              aiia: { foo: { bar: 'deep' }, baz: { qux: 'deeper' } }
            });
            dbg.resetNonStringHits();
            var warnings = [];
            console.warn = function () {
              warnings.push(Array.from(arguments).join(' '));
            };
            api.t('aiia.foo'); api.t('aiia.foo');
            api.t('aiia.baz'); api.t('aiia.baz');
            process.stdout.write(String(warnings.length));
            """
        ).strip()
        code, out, err = _run_node(self.I18N_PATH, body)
        self.assertEqual(code, 0, err)
        self.assertEqual(int(out.strip()), 2)

    def test_plain_missing_key_path_untouched(self) -> None:
        """missing-key 原有 warning 不得被 non-string 分支污染，保留独立签名。"""
        body = textwrap.dedent(
            """
            var warnings = [];
            console.warn = function () {
              warnings.push(Array.from(arguments).join(' '));
            };
            api.t('aiia.never-defined');
            process.stdout.write(JSON.stringify(warnings));
            """
        ).strip()
        code, out, err = _run_node(self.I18N_PATH, body)
        self.assertEqual(code, 0, err)
        warnings = json.loads(out)
        joined = "\n".join(warnings).lower()
        self.assertNotIn("non-string", joined)

    def test_hits_are_introspectable_for_tests(self) -> None:
        body = textwrap.dedent(
            """
            api.t('aiia.foo');
            api.t('aiia.foo');
            process.stdout.write(JSON.stringify(dbg.getNonStringHits()));
            """
        ).strip()
        code, out, err = _run_node(self.I18N_PATH, body)
        self.assertEqual(code, 0, err)
        hits = json.loads(out)
        self.assertEqual(len(hits), 1)
        entry = hits[0]
        self.assertEqual(entry["lang"], "en")
        self.assertEqual(entry["key"], "aiia.foo")
        self.assertEqual(entry["type"], "object")

    def test_strict_mode_throws_on_non_string_resolve(self) -> None:
        body = textwrap.dedent(
            """
            api.setStrict(true);
            var threw = false;
            try { api.t('aiia.foo'); }
            catch (e) { threw = (e && e.message || String(e)); }
            process.stdout.write(String(threw));
            """
        ).strip()
        code, out, err = _run_node(self.I18N_PATH, body)
        self.assertEqual(code, 0, err)
        self.assertNotEqual(out.strip(), "false")
        self.assertIn("aiia.foo", out)

    def test_reset_clears_the_once_set(self) -> None:
        body = textwrap.dedent(
            """
            var warnings = [];
            console.warn = function () {
              warnings.push(Array.from(arguments).join(' '));
            };
            api.t('aiia.foo');
            dbg.resetNonStringHits();
            api.t('aiia.foo');
            process.stdout.write(String(warnings.length));
            """
        ).strip()
        code, out, err = _run_node(self.I18N_PATH, body)
        self.assertEqual(code, 0, err)
        self.assertEqual(int(out.strip()), 2)


@unittest.skipUnless(_node_available(), "node runtime unavailable")
class TestNonStringResolveWebUI(_NonStringResolveMixin):
    __test__ = True
    I18N_PATH = WEBUI_I18N


@unittest.skipUnless(_node_available(), "node runtime unavailable")
class TestNonStringResolveVSCode(_NonStringResolveMixin):
    __test__ = True
    I18N_PATH = VSCODE_I18N


if __name__ == "__main__":
    unittest.main()
