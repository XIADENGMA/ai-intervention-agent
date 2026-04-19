"""ICU AST 编译缓存（Batch-3 H12）。

合约：
  * 同模板重复 parse → cache size 保持 1
  * 不同模板 → 不同 cache entry
  * LRU 上限 256（与 FormatJS ``maxCacheSize`` 默认一致），淘汰后下次命中重新 parse
  * 命中与冷 parse 必须产出一致结果
  * ``_testingClearIntlCaches()`` 清空 ICU 桶
  * 调试钩子 ``dbg.getIcuCompileCacheSize()`` 可读
  * Web UI 与 VSCode 对上述行为 byte-parity
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
        """
    ) % {"path": json.dumps(str(i18n_path))}
    proc = subprocess.run(
        ["node", "-e", harness + "\n" + body],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    return proc.returncode, proc.stdout, proc.stderr


class _IcuCompileCacheMixin(unittest.TestCase):
    __test__ = False
    I18N_PATH: Path

    # ------------------------------------------------------------------
    # introspection hook exists
    # ------------------------------------------------------------------
    def test_debug_hooks_expose_getter_and_clear(self) -> None:
        body = textwrap.dedent(
            """
            process.stdout.write(JSON.stringify({
              getter: typeof dbg.getIcuCompileCacheSize,
              clear: typeof dbg.clearIntlCaches,
              peek: typeof dbg.peekIcuCompileKeys,
            }));
            """
        ).strip()
        code, out, err = _run_node(self.I18N_PATH, body)
        self.assertEqual(code, 0, err)
        shape = json.loads(out)
        self.assertEqual(shape["getter"], "function")
        self.assertEqual(shape["clear"], "function")
        self.assertEqual(shape["peek"], "function")

    # 1 模板 N 次调用 → 1 条缓存
    def test_same_template_parses_once_then_hits_cache(self) -> None:
        body = textwrap.dedent(
            """
            api.registerLocale('en', {
              msg: '{n, plural, one {# item} other {# items}}'
            });
            api.setLang('en');
            dbg.clearIntlCaches();
            for (var i = 0; i < 8; i++) api.t('msg', { n: i });
            process.stdout.write(String(dbg.getIcuCompileCacheSize()));
            """
        ).strip()
        code, out, err = _run_node(self.I18N_PATH, body)
        self.assertEqual(code, 0, err)
        self.assertEqual(int(out), 1)

    # trivial 模板（无 ICU 块）也进缓存，避免每次 t() 重跑 _findIcuBlock
    def test_trivial_template_is_marked_and_cached(self) -> None:
        body = textwrap.dedent(
            """
            api.registerLocale('en', {
              hello: 'Hello {{name}}',
            });
            api.setLang('en');
            dbg.clearIntlCaches();
            for (var i = 0; i < 4; i++) api.t('hello', { name: 'Ada' });
            process.stdout.write(String(dbg.getIcuCompileCacheSize()));
            """
        ).strip()
        code, out, err = _run_node(self.I18N_PATH, body)
        self.assertEqual(code, 0, err)
        self.assertEqual(int(out), 1)

    # 不同模板 → 各自一条缓存
    def test_distinct_templates_land_in_distinct_entries(self) -> None:
        body = textwrap.dedent(
            """
            api.registerLocale('en', {
              a: '{n, plural, one {# apple} other {# apples}}',
              b: '{n, plural, one {# banana} other {# bananas}}',
              c: '{n, plural, one {# cherry} other {# cherries}}',
            });
            api.setLang('en');
            dbg.clearIntlCaches();
            api.t('a', { n: 1 }); api.t('b', { n: 1 }); api.t('c', { n: 1 });
            process.stdout.write(String(dbg.getIcuCompileCacheSize()));
            """
        ).strip()
        code, out, err = _run_node(self.I18N_PATH, body)
        self.assertEqual(code, 0, err)
        self.assertEqual(int(out), 3)

    # LRU 硬上限
    def test_lru_hard_cap_at_256_entries(self) -> None:
        """灌 400 条不同模板，size 必须 ≤ 256，证明 LRU 真的在淘汰。"""
        body = textwrap.dedent(
            """
            dbg.clearIntlCaches();
            var bundle = {};
            for (var i = 0; i < 400; i++) {
              bundle['k' + i] = 'row ' + i + ' — {n, plural, one {# one-' + i
                + '} other {# many-' + i + '}}';
            }
            api.registerLocale('en', bundle);
            api.setLang('en');
            for (var j = 0; j < 400; j++) api.t('k' + j, { n: 1 });
            var size = dbg.getIcuCompileCacheSize();
            process.stdout.write(JSON.stringify({ size: size }));
            """
        ).strip()
        code, out, err = _run_node(self.I18N_PATH, body)
        self.assertEqual(code, 0, err)
        payload = json.loads(out)
        self.assertLessEqual(payload["size"], 256)
        self.assertGreaterEqual(payload["size"], 200)

    # 命中与冷 parse 输出一致
    def test_cache_hit_produces_correct_output(self) -> None:
        body = textwrap.dedent(
            """
            api.registerLocale('en', {
              msg: '{n, plural, one {# item} other {# items}}'
            });
            api.setLang('en');
            dbg.clearIntlCaches();
            var cold = api.t('msg', { n: 1 });
            var hot  = api.t('msg', { n: 5 });
            var warm = api.t('msg', { n: 1 });
            process.stdout.write(JSON.stringify({ cold: cold, hot: hot, warm: warm }));
            """
        ).strip()
        code, out, err = _run_node(self.I18N_PATH, body)
        self.assertEqual(code, 0, err)
        payload = json.loads(out)
        self.assertEqual(payload["cold"], "1 item")
        self.assertEqual(payload["hot"], "5 items")
        self.assertEqual(payload["warm"], "1 item")

    def test_cache_hit_preserves_apostrophe_escape_semantics(self) -> None:
        """命中缓存必须沿用冷 parse 的撇号转义结果，否则两次命中会发散。"""
        body = textwrap.dedent(
            """
            api.registerLocale('en', {
              msg: "{n, plural, one {# it''s one} other {# it''s # items}}"
            });
            api.setLang('en');
            dbg.clearIntlCaches();
            var a = api.t('msg', { n: 1 });
            var b = api.t('msg', { n: 2 });
            var c = api.t('msg', { n: 1 });
            process.stdout.write(JSON.stringify({ a: a, b: b, c: c }));
            """
        ).strip()
        code, out, err = _run_node(self.I18N_PATH, body)
        self.assertEqual(code, 0, err)
        payload = json.loads(out)
        self.assertEqual(payload["a"], "1 it's one")
        self.assertEqual(payload["b"], "2 it's 2 items")
        self.assertEqual(payload["c"], "1 it's one")

    # clearIntlCaches() 同步清空 ICU 编译桶
    def test_clear_intl_caches_also_empties_icu_compile(self) -> None:
        body = textwrap.dedent(
            """
            api.registerLocale('en', {
              msg: '{n, plural, one {# item} other {# items}}',
              hello: 'Hello {{name}}',
            });
            api.setLang('en');
            api.t('msg', { n: 1 });
            api.t('hello', { name: 'Ada' });
            var before = dbg.getIcuCompileCacheSize();
            dbg.clearIntlCaches();
            var after = dbg.getIcuCompileCacheSize();
            process.stdout.write(JSON.stringify({ before: before, after: after }));
            """
        ).strip()
        code, out, err = _run_node(self.I18N_PATH, body)
        self.assertEqual(code, 0, err)
        payload = json.loads(out)
        self.assertGreaterEqual(payload["before"], 1)
        self.assertEqual(payload["after"], 0)


@unittest.skipUnless(_node_available(), "node runtime unavailable")
class TestIcuCompileCacheWebUI(_IcuCompileCacheMixin):
    __test__ = True
    I18N_PATH = WEBUI_I18N


@unittest.skipUnless(_node_available(), "node runtime unavailable")
class TestIcuCompileCacheVSCode(_IcuCompileCacheMixin):
    __test__ = True
    I18N_PATH = VSCODE_I18N


@unittest.skipUnless(_node_available(), "node runtime unavailable")
class TestIcuCompileCacheByteParity(unittest.TestCase):
    """两份 i18n.js 对同输入必须给出同样的缓存 geometry（byte-parity 基准）。"""

    TEMPLATES: tuple[tuple[str, str], ...] = (
        ("t0", "Hello {{name}}"),
        ("t1", "{n, plural, one {# item} other {# items}}"),
        ("t2", "{x, select, a {A} b {B} other {O}}"),
        ("t3", "{n, selectordinal, one {#st} two {#nd} few {#rd} other {#th}}"),
        ("t4", "trivial literal without placeholders"),
    )

    def test_size_and_keys_match_across_halves(self) -> None:
        reg = ",".join(f"{k!r}: {v!r}" for k, v in self.TEMPLATES)
        body = textwrap.dedent(
            f"""
            api.registerLocale('en', {{{reg}}});
            api.setLang('en');
            dbg.clearIntlCaches();
            for (var i = 0; i < 3; i++) {{
              api.t('t0', {{ name: 'Ada' }});
              api.t('t1', {{ n: 1 }});
              api.t('t2', {{ x: 'a' }});
              api.t('t3', {{ n: 1 }});
              api.t('t4');
            }}
            process.stdout.write(JSON.stringify({{
              size: dbg.getIcuCompileCacheSize(),
              keys: dbg.peekIcuCompileKeys().slice().sort(),
            }}));
            """
        ).strip()
        outputs: list[dict] = []
        for path in (WEBUI_I18N, VSCODE_I18N):
            code, out, err = _run_node(path, body)
            self.assertEqual(code, 0, err)
            outputs.append(json.loads(out))
        self.assertEqual(outputs[0], outputs[1])


if __name__ == "__main__":
    unittest.main()
