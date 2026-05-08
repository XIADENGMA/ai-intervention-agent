"""R98 回归：锁住 ``check_i18n_js_no_cjk.py::_strip_comments`` 的剥序契约。

历史 silent breakage（与 R97 同源）
--------------------
``check_i18n_js_no_cjk.py`` 是 R92 修复族里**最后一个**仍带 buggy block-first
strip 实现的扫描器。R92 在 ``check_i18n_orphan_keys.py`` /
``check_i18n_param_signatures.py`` 修了同源 bug 时，docstring 里点名提到
``static/js/app.js:538`` 的 ``// 走 locales/*.json 静态 key`` 是真实触发
案例：line comment 内裸写的 ``/*`` 被 block-comment 正则误识为开头，
吞 509 行真代码（直到下一处 JSDoc ``*/``）。R92 提交时漏 back-port
到 ``js_no_cjk``，导致它沿用 buggy 实现至 R98 修复。

修复时的实测影响：``static/js/app.js`` 吞 509 行（lines 539-1201），
``static/js/i18n.js`` 吞 58 行（lines 1015-1089）；两个被吞区域当前均
无未豁免硬编码 CJK 字面量，所以表面零误报，但属 latent silent
breakage——未来在被吞区域加 CJK 字面量都会逃过扫描。

这套 fixture-based 测试独立于真实 JS 文件内容，直接锁住 line-first
契约——R97 同款，复用经过 reverse-injection 验证的测试模式。
"""

from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = REPO_ROOT / "scripts" / "check_i18n_js_no_cjk.py"


def _load_gate_module():
    spec = importlib.util.spec_from_file_location(
        "_aiia_check_i18n_js_no_cjk_r98", SCRIPT_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class TestStripCommentsLineFirstR98(unittest.TestCase):
    """``_strip_comments`` 必须先剥 ``//`` 再剥 ``/* */``，否则 line comment
    内的裸 ``/*`` 会触发 block-comment 跨吞数百行真代码（R92 docstring
    点名的 ``static/js/app.js:538`` 案例）。"""

    def test_line_comment_with_bare_block_opener_does_not_swallow_code(
        self,
    ) -> None:
        """复刻 ``app.js:538`` 的最小 silent breakage：line comment 里
        裸 ``/*``，下一行真代码必须保留。

        关键：fixture **必须**在后面包含一个真实的 ``*/``（配在合法 block
        comment 里）才能让 buggy block-first 实现真正 swallow——否则 buggy
        正则找不到配对 ``*/`` 0 命中，跟正确实现等价，反向注入验证不了。
        """
        gate = _load_gate_module()
        src = (
            "// 走 locales/*.json 静态 key 且无参数\n"
            "const realCode = 'should-survive';\n"
            "const realCjk = '中文真字符串';\n"
            "/* a legitimate block-comment to provide the closing */\n"
        )
        stripped = gate._strip_comments(src)
        self.assertIn(
            "should-survive",
            stripped,
            msg="line-comment 后的真代码字符串被剥注释逻辑误吞 —— "
            "强烈提示 strip 顺序回归到了 R98 之前的 block-first 实现。",
        )
        self.assertIn(
            "中文真字符串",
            stripped,
            msg="line-comment 后的 CJK 真字符串被剥注释逻辑误吞 —— "
            "扫描器会漏报硬编码 CJK，silent breakage。",
        )

    def test_line_comment_with_block_opener_then_closer_far_below(
        self,
    ) -> None:
        """更恶劣 fixture：line comment 含 ``/*``，文件尾部真有一个 ``*/``，
        修复前会让两者配对，吞掉中间所有真代码。"""
        gate = _load_gate_module()
        src = (
            "// 引用 locales/*.json 多行陷阱\n"
            "const realCjk1 = '中文一';\n"
            "const realCjk2 = '中文二';\n"
            "/* legitimate block\n"
            "   comment */\n"
            "const realCjk3 = '中文三';\n"
        )
        stripped = gate._strip_comments(src)
        for needle in ("中文一", "中文二", "中文三"):
            self.assertIn(
                needle,
                stripped,
                msg=f"strip 后丢失 {needle!r}，提示 line-comment 内 ``/*`` "
                f"和后续真实 block-comment 的 ``*/`` 误配对吞掉了中间真代码。",
            )
        self.assertNotIn(
            "legitimate block",
            stripped,
            msg="真实 block comment 没被剥 —— 注释里 'legitimate block' "
            "字面量泄漏到 strip 输出，会让 STRING_RE 把注释内容误认作字符串。",
        )

    def test_strip_preserves_byte_length_for_line_number_mapping(self) -> None:
        """``scan_file()`` 用 ``stripped[:start].count('\\n') + 1`` 算行号，
        要求 ``_strip_comments`` 输出长度与输入逐字节相等。"""
        gate = _load_gate_module()
        src = "// header line\n/* block\n   comment */\nconst x = 1;\n"
        stripped = gate._strip_comments(src)
        self.assertEqual(
            len(stripped),
            len(src),
            msg="strip 输出与输入字节长度不一致，会破坏 scan_file() 的行号映射。",
        )
        self.assertEqual(
            stripped.count("\n"),
            src.count("\n"),
            msg="strip 输出 ``\\n`` 数量与输入不一致，行号会全错位。",
        )

    def test_strip_preserves_string_byte_offset_around_line_comment_block_opener(
        self,
    ) -> None:
        """更精细的 byte-offset 契约：``// /*`` 触发陷阱时，关键真代码字
        符串字面量在 strip 后位置不变，喂给 ``scan_file()`` 行号映射。"""
        gate = _load_gate_module()
        src = (
            "// 引用 locales/*.json 中的 layout note\n"
            "const greeting = '中文硬编码';\n"
            "/* legit block */\n"
        )
        stripped = gate._strip_comments(src)
        self.assertEqual(len(stripped), len(src))
        original_start = src.index("'中文硬编码'")
        stripped_start = stripped.index("'中文硬编码'")
        self.assertEqual(
            original_start,
            stripped_start,
            msg=f"R98 之前 buggy block-first 实现把 line-comment 后的 ``/*``"
            f" 当 block opener，吞掉到下一处 ``*/``，会让 ``'中文硬编码'``"
            f" 在 strip 输出里位置偏移甚至丢失。原 byte offset"
            f" {original_start}, strip 后 {stripped_start}。",
        )


class TestScanFileEndToEndR98(unittest.TestCase):
    """端到端：fixture 写成临时 ``.js`` 文件，调用 ``scan_file()``，验证
    R98 回归不会让 line-comment 后的硬编码 CJK 静默漏报。"""

    def test_scan_file_catches_cjk_after_line_comment_with_block_opener(
        self,
    ) -> None:
        """fixture 必须含尾部 ``*/`` 才能让 buggy block-first 实现真正
        swallow 中间真代码——否则反向注入验证不了。"""
        gate = _load_gate_module()
        with tempfile.NamedTemporaryFile(
            "w",
            suffix=".js",
            encoding="utf-8",
            delete=False,
        ) as fh:
            fh.write(
                "// 走 locales/*.json 静态 key\n"
                "const greeting = '中文硬编码';\n"
                "/* legitimate block-comment to close the trap */\n"
            )
            tmp_path = Path(fh.name)
        try:
            offenders = gate.scan_file(tmp_path)
            literals = [literal for _line, literal in offenders]
            self.assertIn(
                "中文硬编码",
                literals,
                msg="scan_file() 没扫到 line-comment 之后的硬编码 CJK 字面量"
                "—— 高度提示 ``_strip_comments`` 的剥序回归到了 R98 之前的"
                " block-first 实现，line-comment 内裸 ``/*`` 与后续真实"
                " ``*/`` 误配对吞掉了中间真代码。",
            )
        finally:
            tmp_path.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
