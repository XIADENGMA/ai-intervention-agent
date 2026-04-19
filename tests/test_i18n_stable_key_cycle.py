"""``_stableStringify`` 的环安全 + JSON.stringify 对齐（Batch-1.5 H1 加固）。

H1 给 Intl options 做了按值合并的 LRU，但当时没带 ``WeakSet`` seen 守卫，
也没尊重 ``toJSON``。边界：
  1. 循环 options（``Intl.*`` 会静默忽略未知字段，caller 把 debug 字段
     ``opts.context = opts`` 合法回塞）→ 递归爆栈；``_intlKey`` try/catch
     兜底但所有循环 caller 都塌陷到 ``lang|?`` 单桶，**不同循环 options
     共享同一个 Intl 实例**，是正确性 bug。
  2. Date 字段：``JSON.stringify(new Date(0))`` 走 ``toJSON`` 得 ISO 串；
     ``Object.keys(date)`` 为空，当前 walk 会把所有 Date 折叠成 ``{}``。
  3. fallback 路径：即便 stringify 合法失败（循环/BigInt/Symbol），不同
     形状的 opts 也必须产出不同 key，否则跨 caller 复用实例。

合约（两份 i18n.js）：
  * ``_stableStringify`` 带 WeakSet seen，环触发 sentinel 由 ``_intlKey`` 捕获；
  * ``_stableStringify`` 像 JSON.stringify 一样尊重 ``toJSON``；
  * stringify 失败时 ``_intlKey`` 退到 shape signature（顶层 own keys 排序）
    作为 fallback，避免塌陷到 ``|?``；
  * 两份对同输入产同 canonical key（byte-parity 在末尾测）。
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
        api.registerLocale('en', {});
        api.setLang('en');
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


class _CycleMixin(unittest.TestCase):
    __test__ = False
    I18N_PATH: Path

    def test_cyclic_options_do_not_crash_and_produce_a_cache_entry(self) -> None:
        """``a.self = a`` 不得整个 runtime 崩溃。"""
        body = textwrap.dedent(
            """
            dbg.clearIntlCaches();
            var a = { style: 'decimal', context: null };
            a.context = a;
            var out = api.formatNumber(1, a);
            process.stdout.write(JSON.stringify({
              out: out,
              size: dbg.getIntlCacheSize('NumberFormat'),
            }));
            """
        ).strip()
        code, out, err = _run_node(self.I18N_PATH, body)
        self.assertEqual(code, 0, err)
        payload = json.loads(out)
        self.assertEqual(payload["out"], "1")
        self.assertEqual(payload["size"], 1)

    def test_distinct_cyclic_shapes_do_not_collide_on_question_mark(self) -> None:
        """不同顶层 key 的循环 opts 必须分桶，否则会跨 caller 复用 formatter。"""
        body = textwrap.dedent(
            """
            dbg.clearIntlCaches();
            var a = { style: 'decimal', aSide: null };
            a.aSide = a;
            var b = { style: 'decimal', bSide: null };
            b.bSide = b;
            api.formatNumber(1, a);
            api.formatNumber(1, b);
            process.stdout.write(String(dbg.getIntlCacheSize('NumberFormat')));
            """
        ).strip()
        code, out, err = _run_node(self.I18N_PATH, body)
        self.assertEqual(code, 0, err)
        self.assertEqual(int(out.strip()), 2)

    def test_date_options_align_with_json_stringify_semantics(self) -> None:
        """``JSON.stringify`` 对 Date 走 ``toJSON``；_stableStringify 必须对齐，
        否则不同 Date 值会折叠到同一个 ``{}`` key。
        """
        body = textwrap.dedent(
            """
            dbg.clearIntlCaches();
            api.formatDate(new Date(0), { dateStyle: 'short' });
            api.formatDate(new Date(0), { dateStyle: 'short' });
            api.formatNumber(1, { style: 'decimal', pinned: new Date(0) });
            api.formatNumber(1, { style: 'decimal', pinned: new Date(86400000) });
            var dateSize = dbg.getIntlCacheSize('DateTimeFormat');
            var numSize = dbg.getIntlCacheSize('NumberFormat');
            process.stdout.write(JSON.stringify([dateSize, numSize]));
            """
        ).strip()
        code, out, err = _run_node(self.I18N_PATH, body)
        self.assertEqual(code, 0, err)
        self.assertEqual(
            json.loads(out),
            [1, 2],
            "Date opts 同值必须去重、异值必须分桶",
        )

    def test_custom_tojson_is_honoured(self) -> None:
        """任何带 ``toJSON`` 方法的对象都要被 round-trip，对齐 ``JSON.stringify``。"""
        body = textwrap.dedent(
            """
            dbg.clearIntlCaches();
            var tag = function (label) {
              return { toJSON: function () { return 'tag:' + label; } };
            };
            api.formatNumber(1, { style: 'decimal', tag: tag('A') });
            api.formatNumber(2, { style: 'decimal', tag: tag('A') });
            api.formatNumber(3, { style: 'decimal', tag: tag('B') });
            process.stdout.write(String(dbg.getIntlCacheSize('NumberFormat')));
            """
        ).strip()
        code, out, err = _run_node(self.I18N_PATH, body)
        self.assertEqual(code, 0, err)
        self.assertEqual(int(out.strip()), 2)


@unittest.skipUnless(_node_available(), "node runtime unavailable")
class TestCycleWebUI(_CycleMixin):
    __test__ = True
    I18N_PATH = WEBUI_I18N


@unittest.skipUnless(_node_available(), "node runtime unavailable")
class TestCycleVSCode(_CycleMixin):
    __test__ = True
    I18N_PATH = VSCODE_I18N


@unittest.skipUnless(_node_available(), "node runtime unavailable")
class TestCycleByteParity(unittest.TestCase):
    """即便走环降级分支，两份也必须产出相同 canonical key；否则贡献者在
    Web UI / VSCode 里分别 ``peekIntlCacheKeys('NumberFormat')`` 会看到莫名漂移。
    """

    def test_cycle_fallback_key_bytes_match(self) -> None:
        body = textwrap.dedent(
            """
            dbg.clearIntlCaches();
            var a = { style: 'decimal', probeA: null };
            a.probeA = a;
            var b = { style: 'decimal', probeB: null };
            b.probeB = b;
            api.formatNumber(1, a);
            api.formatNumber(1, b);
            process.stdout.write(JSON.stringify(dbg.peekIntlCacheKeys('NumberFormat')));
            """
        ).strip()
        code_w, out_w, err_w = _run_node(WEBUI_I18N, body)
        code_v, out_v, err_v = _run_node(VSCODE_I18N, body)
        self.assertEqual(code_w, 0, err_w)
        self.assertEqual(code_v, 0, err_v)
        self.assertEqual(
            json.loads(out_w),
            json.loads(out_v),
            "环降级分支的 cache key 在 Web UI 与 VSCode i18n.js 之间漂移",
        )


if __name__ == "__main__":
    unittest.main()
