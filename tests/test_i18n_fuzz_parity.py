"""受控随机 fuzz 的 Web↔VSCode parity 测试（Batch-3 H16 + Round-11 扩展）。

覆盖人工单测容易漏掉的组合（随机 ICU 模板让 ``_renderIcu`` 泄漏 PUA、
撇号 tokenizer 双重 unescape、嵌套 plural 丢 ``#`` 作用域等）。

固定 ``SEED = 0xA11ABADE`` 驱动语法生成 ~200 条模板+参数，分别跑两份
``i18n.js``；断言：返回不抛、输出是字符串、Web/VSCode byte-identical、
U+F0000–U+F0FFF PUA 字符零漏出。

seed 固定 → CI 可复现；失败时 seed 下标同时打印，便于拉到永久样本集。

Round-11 扩展（``EXT_SEED = 0xFACECAFE``）：在原始 corpus 之外追加针对
ICU 标准 corner case 的 100 条样本：
  * ``=N`` 字面值匹配（``i18n.js::_selectPluralOption`` line 410 实现）
  * emoji / 非-BMP 字符（surrogate pair 处理）
  * 组合字符（grapheme cluster，e.g. ``a\u0301`` = á 但占两个 code unit）
  * 极短输入（空 plural arm body、零字符 mustache 参数）
覆盖目的：让 ``=N`` 分支不再是「只在生产 locale 没有用就永远不知道是否
work」的盲点；同时用 surrogate pair 防止未来引入「按 length 切片」的
正则误改 silently 砍掉一个 emoji 的低位 surrogate。
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

EXT_SEED = 0xFACECAFE
EXT_ITERATIONS = 100

_ALPHABET = string.ascii_letters + string.digits + " ,.-!?"
_EMOJI_POOL = ["🚀", "🌍", "👨‍👩‍👧", "🇨🇳", "🏳️‍🌈"]
_COMBINING_POOL = ["a\u0301", "e\u0301", "n\u0303", "o\u0308"]
_BIDI_POOL = ["\u200e", "\u200f", "\u202a", "\u202c"]


def _node_available() -> bool:
    return shutil.which("node") is not None


def _literal(rng: random.Random) -> str:
    """生成短文本片段，偶尔塞入撇号/``#`` 以触发 tokenizer 边界。"""
    length = rng.randint(0, 12)
    pieces = rng.choices(_ALPHABET, k=length)
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


def _plural_with_exact(rng: random.Random, depth: int, args: list[str]) -> str:
    """``=N`` 字面值匹配优先于 CLDR 类别（i18n.js 第 410 行实现）。"""
    name = f"n{len(args)}"
    args.append(name)
    zero_body = _body(rng, depth + 1, args)
    one_body = _body(rng, depth + 1, args)
    other_body = _body(rng, depth + 1, args)
    parts = [
        f"=0 {{{zero_body}}}",
        f"=1 {{{one_body}}}",
        f"other {{{other_body}}}",
    ]
    return "{" + name + ", plural, " + " ".join(parts) + "}"


def _empty_arm_plural(rng: random.Random, depth: int, args: list[str]) -> str:
    """空 ``one {}`` arm — 0 个字符的合法 ICU body。

    历史上 ``_parseIcuOptions`` 用 ``while depth > 0`` 扫描花括号，空 body 是
    「打开 ``{`` 立即关闭 ``}``」，对深度计数器是个边界条件。
    """
    name = f"n{len(args)}"
    args.append(name)
    other_body = _body(rng, depth + 1, args)
    return "{" + name + ", plural, one {} other {" + other_body + "}}"


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


def _ext_template(rng: random.Random) -> tuple[str, dict]:
    """Round-11 扩展 corpus 的模板生成器。

    从 ``[=N plural | empty-arm plural | emoji-heavy mustache | bidi mustache]``
    四档随机选一种结构性 corner case，再用 ``_plural_with_exact``/
    ``_empty_arm_plural``/常规 ``_template`` 组合，强制每条样本都至少触发
    一个新的代码路径（不退化成与原 corpus 重复的纯文本）。
    """
    args: list[str] = []
    pieces: list[str] = []
    flavor = rng.choice(["exact", "empty_arm", "emoji", "bidi"])
    if flavor == "exact":
        pieces.append(_plural_with_exact(rng, 0, args))
        pieces.append(_literal(rng))
    elif flavor == "empty_arm":
        pieces.append(_empty_arm_plural(rng, 0, args))
    elif flavor == "emoji":
        emoji = rng.choice(_EMOJI_POOL)
        combine = rng.choice(_COMBINING_POOL)
        pieces.append(f"{emoji} ")
        pieces.append(_mustache(rng, args))
        pieces.append(f" {combine}")
    else:  # bidi
        bidi = rng.choice(_BIDI_POOL)
        pieces.append(_literal(rng))
        pieces.append(bidi)
        pieces.append(_mustache(rng, args))

    tpl = "".join(pieces)
    params: dict[str, object] = {}
    for arg in args:
        if arg.startswith(("n", "N")):
            # 让 ``=0``/``=1`` 字面分支真有命中机会（70% 概率落在 0/1）
            if rng.random() < 0.7:
                params[arg] = rng.randint(0, 1)
            else:
                params[arg] = rng.randint(2, 5)
        elif arg.startswith(("s", "S")):
            params[arg] = rng.choice(["a", "b", "c", "d"])
        else:
            # mustache 参数偶尔塞 emoji / 组合字符 / 空串：覆盖 ``_interpolateMustache``
            # 在拼接非 ASCII 时是否原样保留 byte sequence
            choices = [
                "Ada",
                "",
                rng.choice(_EMOJI_POOL),
                rng.choice(_COMBINING_POOL),
                "ünıçödé",
                "'x'",
            ]
            params[arg] = rng.choice(choices)
    return tpl, params


def _build_ext_corpus() -> list[dict]:
    rng = random.Random(EXT_SEED)
    corpus: list[dict] = []
    for idx in range(EXT_ITERATIONS):
        tpl, params = _ext_template(rng)
        corpus.append({"id": ITERATIONS + idx, "tpl": tpl, "params": params})
    return corpus


def _run_node_batch(i18n_path: Path, corpus: list[dict]) -> list[dict]:
    """单次 node 调用渲染整个 corpus，结果作为 JSON 数组经 stdout 回传。"""
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
    def _assert_parity(
        self, corpus: list[dict], web: list[dict], vsc: list[dict]
    ) -> None:
        for entry, w, v in zip(corpus, web, vsc, strict=True):
            with self.subTest(id=entry["id"], tpl=entry["tpl"]):
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
                self.assertIsInstance(w["out"], str)
                self.assertIsInstance(v["out"], str)
                self.assertEqual(
                    w["out"],
                    v["out"],
                    f"parity diverged on seed#{entry['id']}:\n  tpl={entry['tpl']!r}\n"
                    f"  web={w['out']!r}\n  vsc={v['out']!r}",
                )
                self.assertFalse(
                    _has_pua_leak(w["out"]),
                    f"PUA marker leaked on seed#{entry['id']}: {w['out']!r}",
                )

    def test_deterministic_fuzz_preserves_byte_parity(self) -> None:
        corpus = _build_corpus()
        web = _run_node_batch(WEBUI_I18N, corpus)
        vsc = _run_node_batch(VSCODE_I18N, corpus)
        self.assertEqual(len(web), ITERATIONS)
        self.assertEqual(len(vsc), ITERATIONS)
        self._assert_parity(corpus, web, vsc)

    def test_extended_fuzz_covers_icu_corner_cases(self) -> None:
        """``=N`` 字面值 / 空 plural arm / emoji surrogate / bidi 控制字符。

        和主 fuzz 用不同 seed，保证扩展失败时不污染原 corpus 的诊断信息。
        """
        corpus = _build_ext_corpus()
        web = _run_node_batch(WEBUI_I18N, corpus)
        vsc = _run_node_batch(VSCODE_I18N, corpus)
        self.assertEqual(len(web), EXT_ITERATIONS)
        self.assertEqual(len(vsc), EXT_ITERATIONS)
        self._assert_parity(corpus, web, vsc)


if __name__ == "__main__":
    unittest.main()
