"""双向文本隔离 helper 合约（Batch-3 H14，UAX #9 §3.1）。

公开 ``AIIA_I18N.wrapBidi(str)`` 给 plain-text sink（日志/Output
Channel/HTML title）提前就位，未来上阿拉伯/希伯来 locale 不会炸。

合约：
  * ``wrapBidi(str)`` → ``FSI + str + PDI``（U+2068 / U+2069）
  * null / undefined / missing → 空串（绝不抛）
  * 非字符串先 String() 再包
  * 已包过的（首 FSI 末 PDI）原样返回（幂等，避免嵌套膨胀成 FSI·FSI·…）
  * 公开 API，Web UI 与 VSCode 必须 byte-parity
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

FSI = "\u2068"
PDI = "\u2069"


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


class _WrapBidiMixin(unittest.TestCase):
    __test__ = False
    I18N_PATH: Path

    def test_wraps_plain_string_with_fsi_pdi(self) -> None:
        body = "process.stdout.write(api.wrapBidi('Ada Lovelace'));"
        code, out, err = _run_node(self.I18N_PATH, body)
        self.assertEqual(code, 0, err)
        self.assertEqual(out, FSI + "Ada Lovelace" + PDI)

    def test_empty_string_round_trips_to_empty(self) -> None:
        """空输入直接返回 ``''``，避免给 UI 塞两个不可见控制字符。"""
        body = "process.stdout.write(JSON.stringify(api.wrapBidi('')));"
        code, out, err = _run_node(self.I18N_PATH, body)
        self.assertEqual(code, 0, err)
        self.assertEqual(json.loads(out), "")

    def test_null_undefined_return_empty_string(self) -> None:
        body = (
            "process.stdout.write("
            "JSON.stringify([api.wrapBidi(null), api.wrapBidi(undefined), api.wrapBidi()])"
            ");"
        )
        code, out, err = _run_node(self.I18N_PATH, body)
        self.assertEqual(code, 0, err)
        self.assertEqual(json.loads(out), ["", "", ""])

    def test_coerces_number_to_string_then_wraps(self) -> None:
        body = "process.stdout.write(api.wrapBidi(42));"
        code, out, err = _run_node(self.I18N_PATH, body)
        self.assertEqual(code, 0, err)
        self.assertEqual(out, FSI + "42" + PDI)

    def test_idempotent_on_already_wrapped_input(self) -> None:
        payload = FSI + "abc" + PDI
        body = f"process.stdout.write(api.wrapBidi({json.dumps(payload)}));"
        code, out, err = _run_node(self.I18N_PATH, body)
        self.assertEqual(code, 0, err)
        self.assertEqual(out, payload)

    def test_isolates_rtl_segment_between_ltr_text(self) -> None:
        """希伯来片段夹在英文里的经典 bug：UBA 会把方向跨边界溢出，必须严格得到 ``FSIעבריתPDI``。"""
        hebrew = "עברית"
        body = f"process.stdout.write(api.wrapBidi({json.dumps(hebrew)}));"
        code, out, err = _run_node(self.I18N_PATH, body)
        self.assertEqual(code, 0, err)
        self.assertEqual(out, FSI + hebrew + PDI)

    def test_exposed_on_public_api_surface(self) -> None:
        body = "process.stdout.write(typeof api.wrapBidi);"
        code, out, err = _run_node(self.I18N_PATH, body)
        self.assertEqual(code, 0, err)
        self.assertEqual(out, "function")


@unittest.skipUnless(_node_available(), "node runtime unavailable")
class TestWrapBidiWebUI(_WrapBidiMixin):
    __test__ = True
    I18N_PATH = WEBUI_I18N


@unittest.skipUnless(_node_available(), "node runtime unavailable")
class TestWrapBidiVSCode(_WrapBidiMixin):
    __test__ = True
    I18N_PATH = VSCODE_I18N


@unittest.skipUnless(_node_available(), "node runtime unavailable")
class TestWrapBidiByteParity(unittest.TestCase):
    """两份 i18n.js 对同一输入必须 byte-parity，与其余公共 API 合约一致。"""

    def test_parity_over_mixed_latin_cyrillic_hebrew_cjk_samples(self) -> None:
        samples = [
            "Ada",
            "Иван",
            "עברית",
            "abc مرحبا 123",
            "",
            "45.6",
            FSI + "already" + PDI,
        ]
        body = (
            "process.stdout.write(JSON.stringify(["
            + ",".join(f"api.wrapBidi({json.dumps(s)})" for s in samples)
            + "]));"
        )
        outputs: list[list[str]] = []
        for path in (WEBUI_I18N, VSCODE_I18N):
            code, out, err = _run_node(path, body)
            self.assertEqual(code, 0, err)
            outputs.append(json.loads(out))
        self.assertEqual(outputs[0], outputs[1])


if __name__ == "__main__":
    unittest.main()
