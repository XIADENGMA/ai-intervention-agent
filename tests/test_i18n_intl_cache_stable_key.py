"""``_intlCache`` / ``_pluralRulesCache`` 的稳定排序 cache key（Batch-1.5 H1）。

FormatJS ``intl-format-cache`` 在 JSON-stringify 前强制排序 options key，
否则同义但 key 顺序不同的 options（``Object.assign`` / spread 产物）会产
生不同缓存项，悄悄让 LRU 体积翻倍。

合约（两份 i18n.js 必须一致）：
  * 递归排序所有嵌套对象 key；
  * 数组保序（Intl options 里数组都是位置语义）；
  * 任何 key 排列的序列化结果一致，两份 i18n.js 需 byte-parity。

测试走 ``dbg.getIntlCacheSize`` / ``dbg.peekIntlCacheKeys`` 的可观察效
果，而非私有 ``_intlKey``，与调用方真正依赖的契约对齐。
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


class _StableKeyMixin(unittest.TestCase):
    __test__ = False
    I18N_PATH: Path

    def test_key_order_permutation_hits_same_bucket_entry(self) -> None:
        body = textwrap.dedent(
            """
            dbg.clearIntlCaches();
            api.formatNumber(1, { style: 'currency', currency: 'USD', maximumFractionDigits: 2 });
            api.formatNumber(2, { maximumFractionDigits: 2, style: 'currency', currency: 'USD' });
            api.formatNumber(3, { currency: 'USD', maximumFractionDigits: 2, style: 'currency' });
            process.stdout.write(String(dbg.getIntlCacheSize('NumberFormat')));
            """
        ).strip()
        code, out, err = _run_node(self.I18N_PATH, body)
        self.assertEqual(code, 0, err)
        self.assertEqual(
            int(out.strip()),
            1,
            "three semantically-identical option permutations should reuse the "
            "single cached NumberFormat; otherwise LRU starves for dupes.",
        )

    def test_nested_option_keys_are_order_agnostic(self) -> None:
        # DateTimeFormat 的嵌套 options 常由 Object.assign 拼出，key 顺序不定，必须等价命中
        body = textwrap.dedent(
            """
            dbg.clearIntlCaches();
            api.formatDate(new Date(0), { dateStyle: 'short', timeStyle: 'short' });
            api.formatDate(new Date(0), { timeStyle: 'short', dateStyle: 'short' });
            process.stdout.write(String(dbg.getIntlCacheSize('DateTimeFormat')));
            """
        ).strip()
        code, out, err = _run_node(self.I18N_PATH, body)
        self.assertEqual(code, 0, err)
        self.assertEqual(int(out.strip()), 1)

    def test_distinct_option_values_still_occupy_distinct_entries(self) -> None:
        # 稳定排序只做去重，不能让真正不同的 options 撞 key
        body = textwrap.dedent(
            """
            dbg.clearIntlCaches();
            api.formatNumber(1, { style: 'currency', currency: 'USD' });
            api.formatNumber(1, { style: 'currency', currency: 'EUR' });
            api.formatNumber(1, { style: 'decimal' });
            process.stdout.write(String(dbg.getIntlCacheSize('NumberFormat')));
            """
        ).strip()
        code, out, err = _run_node(self.I18N_PATH, body)
        self.assertEqual(code, 0, err)
        self.assertEqual(int(out.strip()), 3)


@unittest.skipUnless(_node_available(), "node runtime unavailable")
class TestStableKeyWebUI(_StableKeyMixin):
    __test__ = True
    I18N_PATH = WEBUI_I18N


@unittest.skipUnless(_node_available(), "node runtime unavailable")
class TestStableKeyVSCode(_StableKeyMixin):
    __test__ = True
    I18N_PATH = VSCODE_I18N


@unittest.skipUnless(_node_available(), "node runtime unavailable")
class TestStableKeyByteParity(unittest.TestCase):
    """两份 i18n.js 输出同一 canonical key 序列（dashboard/CI snapshot 可 diff）。"""

    def test_canonical_cache_key_bytes_match(self) -> None:
        body = textwrap.dedent(
            """
            dbg.clearIntlCaches();
            api.formatNumber(1, { style: 'currency', currency: 'USD', maximumFractionDigits: 2 });
            api.formatNumber(2, { maximumFractionDigits: 4, minimumIntegerDigits: 1 });
            api.formatNumber(3, { useGrouping: false, notation: 'compact' });
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
            "stable-sorted cache key bytes drifted between Web UI and VSCode i18n.js",
        )


if __name__ == "__main__":
    unittest.main()
