"""R97 回归：锁住 ``check_i18n_ts_no_cjk.py::_strip_comments`` 的剥序契约。

历史 silent breakage
--------------------
旧实现先 ``BLOCK_COMMENT_RE.sub`` 再 ``LINE_COMMENT_RE.sub``：``packages/
vscode/extension.ts:59`` 的 ``// 命中 repo root...packages/* 多走一`` 中那个
裸 ``/*`` 被 block-comment 正则当成开头，吞掉到下一处真实 ``*/`` 为止——
实测连续吃掉 ~50 行真代码（变成等长空白）。这 50 行恰好都是真注释所以
表面零误报，但属于「lurking silent breakage」：一旦未来有人在
``// foo /* bar`` 类型注释附近塞入硬编码 CJK 字符串，扫描器就会漏报。

这套 fixture-based 单元测试独立于 ``extension.ts`` 当前内容，直接锁住
``_strip_comments`` 的契约：line comment 内裸 ``/*`` 不能升级为 block-
comment 起点。这与 ``check_i18n_orphan_keys.py`` 在 R92 修复后采用的同款
折中一致（line-first via ``find('//')`` + block-via-regex）。
"""

from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = REPO_ROOT / "scripts" / "check_i18n_ts_no_cjk.py"


def _load_gate_module():
    spec = importlib.util.spec_from_file_location(
        "_aiia_check_i18n_ts_no_cjk_r97", SCRIPT_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class TestStripCommentsLineFirstR97(unittest.TestCase):
    """``_strip_comments`` 必须先剥 ``//`` 再剥 ``/* */``，否则 line comment
    内的裸 ``/*`` 会触发 block-comment 跨吞数百行真代码。"""

    def test_line_comment_with_bare_block_opener_does_not_swallow_code(
        self,
    ) -> None:
        """复刻 ``extension.ts:59`` 的最小 silent breakage：line comment
        里裸 ``/*``，下一行真代码必须保留。

        关键：fixture **必须**在后面包含一个真实的 ``*/``（配在合法 block
        comment 里），否则 buggy block-first 实现的 ``/\\*.*?\\*/`` 找不到
        配对会 0 命中，导致测试侥幸通过——这正是反向注入验证逮过的设计陷阱。
        """
        gate = _load_gate_module()
        src = (
            "// see packages/* for layout\n"
            "const realCode = 'should-survive';\n"
            "const realCjk = '中文真字符串';\n"
            "/* a legitimate block-comment to provide the closing */\n"
        )
        stripped = gate._strip_comments(src)
        self.assertIn(
            "should-survive",
            stripped,
            msg="line-comment 后的真代码字符串被剥注释逻辑误吞 —— "
            "强烈提示 strip 顺序回归到了 R97 之前的 block-first 实现。",
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
            "// see packages/* multi-line trap\n"
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
                msg=f"strip 后丢失 {needle!r}，提示 line-comment 内的 ``/*`` "
                f"和后续真实 block-comment 的 ``*/`` 误配对，吞掉了中间真代码。",
            )
        self.assertNotIn(
            "legitimate block",
            stripped,
            msg="真实 block comment 没被剥 —— 注释里 'legitimate block' "
            "字面量泄漏到 strip 输出，会让 STRING_RE 把注释内容误认作字符串。",
        )

    def test_strip_preserves_byte_length_for_line_number_mapping(self) -> None:
        """``scan_file()`` 用 ``stripped[:start].count('\\n') + 1`` 算行号，
        要求 ``_strip_comments`` 输出长度与输入逐字节相等（``\\n`` 保留，
        其他字符替成空格）。否则报告里行号会偏移。"""
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
        """更精细的 byte-offset 契约：``// /*`` 触发陷阱时，``_strip_comments``
        输出**仍然**和输入逐字节同长度，且关键的真代码字符串字面量在 strip
        后**位置不变**（开始/结束 byte offset 与原文一致）。这条契约直接
        喂给 ``scan_file::stripped[:start].count('\\n') + 1`` 行号映射。"""
        gate = _load_gate_module()
        src = (
            "// see packages/* layout note\n"
            "const greeting = '中文硬编码';\n"
            "/* legit block */\n"
        )
        stripped = gate._strip_comments(src)
        self.assertEqual(len(stripped), len(src))
        # strip 后真代码 substring 起点/终点 byte offset 必须和原文一致
        # (line-comment 起在第 1 行 → 该行被替成空白，但下一行 const 整行保留)
        original_start = src.index("'中文硬编码'")
        stripped_start = stripped.index("'中文硬编码'")
        self.assertEqual(
            original_start,
            stripped_start,
            msg=f"R97 之前 buggy block-first 实现把 ``//`` 后裸 ``/*`` 当 block "
            f"opener，吞掉到下一处 ``*/``，会让 ``'中文硬编码'`` 在 strip "
            f"输出里位置偏移甚至丢失。原 byte offset {original_start}, "
            f"strip 后 {stripped_start}。",
        )


class TestScanFileEndToEndR97(unittest.TestCase):
    """端到端：把 fixture 写成临时 ``.ts`` 文件，调用 ``scan_file()``，
    验证 R97 回归不会让 line-comment 后的硬编码 CJK 静默漏报。"""

    def test_scan_file_catches_cjk_after_line_comment_with_block_opener(
        self,
    ) -> None:
        """端到端 fixture **必须**含有真实尾部 ``*/`` 才能让 buggy block-
        first 实现真正 swallow 中间真代码——否则 buggy 正则找不到配对
        ``*/``，0 命中，结果跟正确实现等价，反向注入验证不了。"""
        gate = _load_gate_module()
        with tempfile.NamedTemporaryFile(
            "w",
            suffix=".ts",
            encoding="utf-8",
            delete=False,
        ) as fh:
            fh.write(
                "// see packages/* layout note\n"
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
                "—— 高度提示 ``_strip_comments`` 的剥序回归到了 R97 之前的"
                " block-first 实现，line-comment 内裸 ``/*`` 与后续真实 ``*/``"
                "误配对吞掉了中间真代码。",
            )
        finally:
            tmp_path.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
