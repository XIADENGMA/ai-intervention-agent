"""R129 · ``app.js`` 已停用代码注释墓碑清理护栏。

背景
----
``static/js/app.js`` 在历史演进中累积了若干"已删除/已停用"的 30+ 行
banner 注释（典型样本："内容轮询 - 已停用"、"updatePageContent() 已删除"），
以及在两处 ``loadConfig().then() / .catch()`` 路径中重复出现的：

    // 【优化】停用 app.js 内容轮询，使用 multi_task.js 的任务轮询统一管理
    // 原因：两个轮询系统会导致 textarea 内容被意外清空
    // startContentPolling() // 已停用

这种"墓碑注释"对未来阅读者价值很低（``git log --follow`` 已经能取
回任何被删代码的上下文），却持续占据屏幕空间。R129 把它们清理掉，
但保留 ``stopContentPolling()`` no-op 函数本体——因为 ``closeInterface()``
仍在调用，删除会引入 ``ReferenceError``。

本测试覆盖三个反向不变量（reverse-lock）：

1. **死引用注释剥光**：``startContentPolling`` 这个函数名只能出现在
   合规说明里（即 R129 自己写的解释段落），不能再以
   "// startContentPolling() // 已停用" 这种墓碑形式出现。
2. **超长 banner 已合并**：单文件中的 ``// ===…(5个等号以上)`` 风格
   分隔符行不应连续出现 ≥3 次（这是历史 banner 注释的特征——
   形如 ``// ====== 内容轮询 - 已停用 ======``）。
3. **关键安全合约不变**：``stopContentPolling`` 函数本体仍然存在
   且仍可被 ``closeInterface()`` 调用，否则会引入 ReferenceError
   并破坏关闭流程。
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
APP_JS = REPO_ROOT / "src" / "ai_intervention_agent" / "static" / "js" / "app.js"


def _read_source() -> str:
    assert APP_JS.is_file(), f"app.js 缺失: {APP_JS}"
    return APP_JS.read_text(encoding="utf-8")


class TestNoStartContentPollingDeadCommentMarkers(unittest.TestCase):
    """``startContentPolling`` 不应再以 ``// xxx // 已停用`` 的墓碑注释形式出现。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.source = _read_source()

    def test_no_disabled_comment_form(self) -> None:
        """禁止再次出现 ``// startContentPolling() // 已停用`` 这类死引用。"""
        # 只允许在 R129 自身的解释段落里以 ``startContentPolling`` 字面量出现。
        # 死注释形态要 fail：``//`` + 函数名 + ``// 已停用`` 在同一行。
        pattern = re.compile(
            r"//\s*startContentPolling\s*\(\s*\)\s*//\s*已停用",
        )
        match = pattern.search(self.source)
        self.assertIsNone(
            match,
            "禁止再出现 ``// startContentPolling() // 已停用`` 形式的墓碑注释——"
            "把它清理掉，靠 ``git log -S startContentPolling`` 取回历史；"
            "已停用语义由不调用本身就足够表达。",
        )

    def test_function_name_only_appears_in_explanatory_form(self) -> None:
        """``startContentPolling`` 全文只能出现在 R129 注释解释段落（最多 1 处）。

        如果将来代码中再出现 ``startContentPolling`` 调用或定义，
        说明 R129 的"已停用→已迁移"决策被偷偷推翻——本测试要求显式
        revisit 这个不变量并更新本文件以反映新的语义合约。
        """
        occurrences = re.findall(r"startContentPolling", self.source)
        # R129 注释最多提及 0 次 (此前的 R129 注释提到了一次, 后来删了)
        # 但允许 ≤ 1 次以容忍未来注释里再次提到名字
        self.assertLessEqual(
            len(occurrences),
            1,
            f"``startContentPolling`` 在 app.js 中出现 {len(occurrences)} 次"
            "——R129 之后应只在解释段落保留 ≤ 1 处提及；"
            f"如需新增，请同步更新本测试文档 (occurrences={occurrences[:5]})",
        )


class TestNoUpdatePageContentTombstone(unittest.TestCase):
    """``updatePageContent`` 同样禁止以墓碑注释形态留存。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.source = _read_source()

    def test_no_deleted_marker_comment(self) -> None:
        """禁止再出现 ``// updatePageContent() 已删除`` 这种墓碑形态。"""
        pattern = re.compile(
            r"//\s*updatePageContent\s*\(\s*\)\s*已删除",
        )
        self.assertIsNone(
            pattern.search(self.source),
            "禁止再出现 ``// updatePageContent() 已删除`` 形式的墓碑注释——"
            "已删除语义不需要在每次阅读时反复提醒读者；"
            "``git log -S updatePageContent`` 自带历史。",
        )

    def test_function_only_in_explanatory_form(self) -> None:
        """``updatePageContent`` 在 app.js 中至多出现 1 次（仅本 R129 注释）。"""
        occurrences = re.findall(r"updatePageContent", self.source)
        self.assertLessEqual(
            len(occurrences),
            1,
            f"``updatePageContent`` 在 app.js 中出现 {len(occurrences)} 次；"
            "R129 之后应只在解释段落保留 ≤ 1 处",
        )


class TestNoLongBannerCommentRuns(unittest.TestCase):
    """``// =====...`` 分隔符行不能连续出现 ≥3 次（历史 banner 特征）。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.source = _read_source()

    def test_no_3plus_consecutive_banner_lines(self) -> None:
        """不允许连续 3 行以上的 ``// =====...`` 分隔符。

        pre-R129 的 ``// === 内容轮询 - 已停用 === \n // === \n // ...``
        风格 banner 会触发本断言，提醒清理掉。
        """
        lines = self.source.splitlines()
        run = 0
        max_run = 0
        run_start_line = -1
        max_run_start = -1
        banner_re = re.compile(r"^\s*//\s*=+\s*$")
        for idx, line in enumerate(lines):
            if banner_re.match(line):
                if run == 0:
                    run_start_line = idx
                run += 1
                if run > max_run:
                    max_run = run
                    max_run_start = run_start_line
            else:
                run = 0
        self.assertLess(
            max_run,
            3,
            f"app.js 出现连续 {max_run} 行 ``// ====`` 分隔符 "
            f"(从第 {max_run_start + 1} 行开始) ——"
            "这是 pre-R129 banner 墓碑注释的特征，应清理后压缩成 ≤ 5 行说明",
        )


class TestStopContentPollingStillExists(unittest.TestCase):
    """关键安全合约：``stopContentPolling`` no-op 函数仍然必须存在。

    ``closeInterface()`` 在 line 1151 附近还会调用它；如果 R129 误删了
    函数本体，会引入 ``ReferenceError: stopContentPolling is not defined``，
    破坏关闭流程。本测试守护这条不变量。
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.source = _read_source()

    def test_function_definition_present(self) -> None:
        self.assertIn(
            "function stopContentPolling()",
            self.source,
            "``stopContentPolling`` 函数本体必须保留（即使是 no-op）——"
            "``closeInterface()`` 还在调用它；删除会引入 ReferenceError。",
        )

    def test_close_interface_still_calls_it(self) -> None:
        self.assertRegex(
            self.source,
            r"closeInterface[\s\S]*?stopContentPolling\s*\(\s*\)",
            "``closeInterface()`` 必须仍然调用 ``stopContentPolling()``；"
            "如果删除调用，请先确认没有任何用户路径还需要"
            "shut-down 信号，并同步更新本测试文档说明",
        )


if __name__ == "__main__":
    unittest.main()
