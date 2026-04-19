"""受控随机 fuzz 的 Web↔VSCode parity 测试（Batch-3 H16）。

覆盖人工单测容易漏掉的组合（随机 ICU 模板让 ``_renderIcu`` 泄漏 PUA、
撇号 tokenizer 双重 unescape、嵌套 plural 丢 ``#`` 作用域等）。

固定 ``SEED = 0xA11ABADE`` 驱动语法生成 ~200 条模板+参数，分别跑两份
``i18n.js``；断言：返回不抛、输出是字符串、Web/VSCode byte-identical、
U+F0000–U+F0FFF PUA 字符零漏出。

seed 固定 → CI 可复现；失败时 seed 下标同时打印，便于拉到永久样本集。
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
    def test_deterministic_fuzz_preserves_byte_parity(self) -> None:
        corpus = _build_corpus()
        web = _run_node_batch(WEBUI_I18N, corpus)
        vsc = _run_node_batch(VSCODE_I18N, corpus)
        self.assertEqual(len(web), ITERATIONS)
        self.assertEqual(len(vsc), ITERATIONS)

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


if __name__ == "__main__":
    unittest.main()
