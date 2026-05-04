"""``scripts/generate_docs.py`` 中所有项目根 ``*.py`` 必须被分类。

每个项目根的 ``*.py`` 模块要么 (a) 列在 ``MODULES_TO_DOCUMENT`` —— 实际生成
``docs/api(.zh-CN)/<name>.md``，要么 (b) 列在 ``IGNORED_MODULES`` —— 显式打
TODO 标记说明为什么暂不文档化。两个集合必须互斥且并集等于项目根 ``*.py``。

本测试同时锁住:

1. ``_assert_top_level_modules_classified`` 仍然在 ``generate_index`` 入口
   被调用——通过对函数源码做 substring 检查。如果未来有人 inadvertently
   把这道 invariant call 删掉，本测试立即 fail。
2. 当前不变量在真实仓库上 PASS（即 9 个未文档化模块都已显式登记到
   IGNORED_MODULES）。
3. ``IGNORED_MODULES`` 中每个条目都带 ``TODO`` 注释（防止未来悄悄塞个
   "出于政治原因不文档化"的模块进 IGNORED 集合）。

边界情况：
- 子目录中的 ``*.py`` 不算（``web_ui_routes/``、``tests/``、``scripts/`` 都有自己的
  分类机制；本测试只看项目根）。
- ``__init__.py`` 不算（命名空间标记，不是文档化目标）。
"""

from __future__ import annotations

import inspect
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts import generate_docs as gd


class TestTopLevelModuleClassification(unittest.TestCase):
    def test_invariant_passes_today(self) -> None:
        """生产仓库当前必须满足分类不变量；否则 generate_docs.py 会 SystemExit。"""
        gd._assert_top_level_modules_classified()

    def test_classification_sets_disjoint(self) -> None:
        """``MODULES_TO_DOCUMENT`` 与 ``IGNORED_MODULES`` 必须互斥——
        一个模块同时被宣告"文档化"和"忽略"是矛盾。"""
        declared = set(gd.MODULES_TO_DOCUMENT)
        ignored = set(gd.IGNORED_MODULES)
        overlap = declared & ignored
        self.assertEqual(
            overlap,
            set(),
            f"MODULES_TO_DOCUMENT 与 IGNORED_MODULES 重叠：{sorted(overlap)}",
        )

    def test_classification_covers_all_top_level_modules(self) -> None:
        """两个集合的并必须等于项目根 ``*.py``——没有未分类、没有过期条目。"""
        actual = gd._enumerate_top_level_python_modules()
        classified = set(gd.MODULES_TO_DOCUMENT) | set(gd.IGNORED_MODULES)
        unclassified = actual - classified
        stale = classified - actual
        self.assertEqual(
            unclassified,
            set(),
            "项目根存在未分类的 .py 模块（应在 MODULES_TO_DOCUMENT 或 "
            f"IGNORED_MODULES 显式登记）：{sorted(unclassified)}",
        )
        self.assertEqual(
            stale,
            set(),
            "MODULES_TO_DOCUMENT / IGNORED_MODULES 列了不存在的文件（"
            f"过期条目，应从 scripts/generate_docs.py 删除）：{sorted(stale)}",
        )

    def test_invariant_is_called_from_generate_index(self) -> None:
        """``_assert_top_level_modules_classified`` 必须在 ``generate_index`` 入口被调用。

        反向锁：如果未来有人删除这条调用（或重命名函数后忘了调），本测试
        会 fail。比单纯检测两个集合是否对齐多覆盖一道防线——后者只在
        函数被调用时才生效。
        """
        source = inspect.getsource(gd.generate_index)
        self.assertIn(
            "_assert_top_level_modules_classified()",
            source,
            "generate_index() 必须调用 _assert_top_level_modules_classified()；"
            "否则新加未分类模块时不变量不会触发。",
        )

    def test_ignored_modules_have_todo_marker(self) -> None:
        """``IGNORED_MODULES`` 集合是 frozenset，无法在源里附注释——
        改为对脚本源码做 substring 检查：每个 ignored 模块名上方
        必须出现一个 ``TODO`` 标记，避免悄悄添加无说明的"永久 ignored"条目。
        """
        gd_file = gd.__file__
        assert gd_file is not None, "scripts/generate_docs 模块缺少 __file__"
        source = Path(gd_file).read_text(encoding="utf-8")
        # 找到 IGNORED_MODULES 块的范围
        start_marker = "IGNORED_MODULES = frozenset("
        end_marker = "\n)\n"
        start = source.find(start_marker)
        self.assertNotEqual(start, -1, "未找到 IGNORED_MODULES 定义")
        end = source.find(end_marker, start)
        self.assertNotEqual(end, -1, "未找到 IGNORED_MODULES 结束标记")
        block = source[start:end]
        for module in gd.IGNORED_MODULES:
            quoted = f'"{module}"'
            module_pos = block.find(quoted)
            self.assertNotEqual(
                module_pos,
                -1,
                f"IGNORED_MODULES 块中找不到 {quoted}",
            )
            preceding = block[:module_pos]
            last_newline = preceding.rfind("\n")
            line_after_last_newline = preceding[last_newline + 1 :]
            self.assertEqual(
                line_after_last_newline.strip(),
                "",
                f"{quoted} 不在自己的一行（破坏 TODO 注释定位规则）",
            )
            preceding_lines = preceding.rstrip().split("\n")
            comment_line = preceding_lines[-1] if preceding_lines else ""
            self.assertIn(
                "TODO",
                comment_line,
                f"IGNORED_MODULES 中的 {quoted} 上方缺少 TODO 注释。"
                "请添加 ``# TODO(...)`` 说明为什么暂不文档化，避免悄悄"
                "积累永久 ignored 条目。",
            )


if __name__ == "__main__":
    unittest.main()
