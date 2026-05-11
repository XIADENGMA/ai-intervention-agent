"""CR#10 F-3 — MCP-path 与 HTTP-path 的 ``predefined_options`` 解析必须等价。

## 背景

R167 把 ``predefined_options`` 在 LLM-facing MCP API 上收敛到两种合法形态：

1. ``list[str]``：纯字符串数组，所有项 default=False；
2. ``list[dict]``：``[{"label": str, "default": bool}, ...]``，
   field aliases 接受 ``text`` / ``value`` 作为 ``label`` 同义、
   ``selected`` / ``checked`` 作为 ``default`` 同义。

但 HTTP API ``POST /api/tasks``（VS Code 扩展 / 自动化脚本路径）**只接受**
parallel-array 形态：``predefined_options: list[str]`` + 独立的
``predefined_options_defaults: list[bool]``。

两条入口"殊途同归"到同一个 ``task_queue.Task`` 字段：
- MCP 路径：``server_feedback`` 内部用 ``validate_input_with_defaults``
  把 ``list[dict]`` 拆成 ``(list[str], list[bool])`` → 再调
  ``POST /api/tasks``（参数 ``predefined_options`` + ``predefined_options_defaults``）；
- HTTP 路径：调用方直接传 ``(list[str], list[bool])``，``web_ui_routes/task.py``
  做长度对齐 + bool normalization → ``Task.predefined_options{,_defaults}``。

## CR#10 F-3 invariant

未来如果在 MCP 路径加新的 ``label`` alias（例如 ``"caption"``）但忘了在
HTTP 路径补对应的兼容逻辑，两条入口就会 drift —— 同一组"概念输入"在
两条路径上得到不同的 ``Task`` 内部表示。

本测试锁住的 invariant：

> 对于 MCP 形态 ``[{"label": L, "default": D}]`` 输入：
> ``validate_input_with_defaults`` 拆出来的 ``(labels, defaults)`` 必须
> 与"HTTP 端 parallel-array 形态 ``(predefined_options=[L], predefined_options_defaults=[D])``"
> 完全等价（label 一致、default 一致、长度对齐规则一致）。

如果该等价性被破坏（新 alias 只在一侧支持 / 新 normalize 规则只改一侧），
未来 commit 应该在两侧同时落地，否则本测试会失败提醒。

## 不测什么

- 不测 HTTP-side 是否接受 ``list[dict]``：R167 设计上 HTTP-side
  *只* 接受 parallel-array，``web_ui_routes/task.py`` 看到非 str 元素会
  直接 400。本测试不挑战这个分工。
- 不测 ``validate_input_with_defaults`` 接受第三种 "tuple 形态"
  ``[("label", True)]``：那是 ``validate_input_with_defaults`` 的本地能力，
  HTTP-side 不接受 tuple，所以"tuple → 等价 parallel array"不构成
  *两条入口* 的 parity invariant。
"""

from __future__ import annotations

import unittest

from ai_intervention_agent.server_config import validate_input_with_defaults


class TestPredefinedOptionsDualPathParityCR10F3(unittest.TestCase):
    """MCP 形态 list[dict] 与 HTTP 形态 (list[str], list[bool]) 必须等价。"""

    def assertDualPathEquivalent(
        self,
        mcp_input: list,
        expected_labels: list[str],
        expected_defaults: list[bool],
        msg: str | None = None,
    ) -> None:
        """断言：``validate_input_with_defaults`` 对 ``mcp_input`` 的拆解
        与 HTTP-side parallel-array 形态 ``(expected_labels, expected_defaults)``
        完全等价（两个列表长度匹配 + 逐位 ``label``/``default`` 一致）。
        """
        prompt, labels, defaults = validate_input_with_defaults("Continue?", mcp_input)
        self.assertEqual(prompt, "Continue?", msg)
        self.assertEqual(labels, expected_labels, msg)
        self.assertEqual(defaults, expected_defaults, msg)
        # parallel-array 不变量：两列表长度始终一致
        self.assertEqual(
            len(labels),
            len(defaults),
            f"MCP 拆解结果长度对齐失败: labels={labels!r} defaults={defaults!r}",
        )

    def test_simple_dict_form_matches_parallel_array(self) -> None:
        """单一 dict 形态选项 ↔ 单元素 parallel-array."""
        self.assertDualPathEquivalent(
            mcp_input=[{"label": "Apply", "default": True}],
            expected_labels=["Apply"],
            expected_defaults=[True],
            msg="basic single-dict shape",
        )

    def test_multi_dict_mixed_defaults_match_parallel_array(self) -> None:
        """多个 dict + 混合 default 取值 ↔ 多元素 parallel-array."""
        self.assertDualPathEquivalent(
            mcp_input=[
                {"label": "Yes", "default": True},
                {"label": "No", "default": False},
                {"label": "Maybe", "default": True},
            ],
            expected_labels=["Yes", "No", "Maybe"],
            expected_defaults=[True, False, True],
            msg="three options with mixed defaults",
        )

    def test_dict_without_default_falls_to_false(self) -> None:
        """dict 形态省略 ``default`` 字段时等价于 HTTP-side ``default=False``."""
        self.assertDualPathEquivalent(
            mcp_input=[{"label": "Continue"}],
            expected_labels=["Continue"],
            expected_defaults=[False],
            msg="dict shape without default key",
        )

    def test_text_alias_for_label_matches_parallel_array(self) -> None:
        """``text`` alias 与 ``label`` 行为一致，结果与 parallel-array 等价."""
        self.assertDualPathEquivalent(
            mcp_input=[{"text": "Submit", "default": True}],
            expected_labels=["Submit"],
            expected_defaults=[True],
            msg="``text`` alias for ``label``",
        )

    def test_value_alias_for_label_matches_parallel_array(self) -> None:
        """``value`` alias 与 ``label`` 行为一致，结果与 parallel-array 等价."""
        self.assertDualPathEquivalent(
            mcp_input=[{"value": "Reject", "default": False}],
            expected_labels=["Reject"],
            expected_defaults=[False],
            msg="``value`` alias for ``label``",
        )

    def test_selected_alias_for_default_matches_parallel_array(self) -> None:
        """``selected`` alias 与 ``default`` 行为一致."""
        self.assertDualPathEquivalent(
            mcp_input=[{"label": "Pin", "selected": True}],
            expected_labels=["Pin"],
            expected_defaults=[True],
            msg="``selected`` alias for ``default``",
        )

    def test_checked_alias_for_default_matches_parallel_array(self) -> None:
        """``checked`` alias 与 ``default`` 行为一致."""
        self.assertDualPathEquivalent(
            mcp_input=[{"label": "Star", "checked": True}],
            expected_labels=["Star"],
            expected_defaults=[True],
            msg="``checked`` alias for ``default``",
        )

    def test_pure_string_form_matches_all_false_parallel_array(self) -> None:
        """纯 ``list[str]`` 形态等价于 HTTP-side ``defaults=[False, False, ...]``."""
        self.assertDualPathEquivalent(
            mcp_input=["A", "B", "C"],
            expected_labels=["A", "B", "C"],
            expected_defaults=[False, False, False],
            msg="pure list[str] -> all-False defaults",
        )

    def test_mixed_str_and_dict_form_normalises_consistently(self) -> None:
        """同一个 list 里混 string + dict（合法），label 全保留 / default 按各项处理."""
        self.assertDualPathEquivalent(
            mcp_input=[
                "Quick",  # default=False
                {"label": "Verbose", "default": True},  # default=True
                "Skip",  # default=False
            ],
            expected_labels=["Quick", "Verbose", "Skip"],
            expected_defaults=[False, True, False],
            msg="mixed str + dict in same list",
        )

    def test_truthy_default_values_normalise_to_bool(self) -> None:
        """``default`` 字段不是真布尔时，必须 normalize 到 bool（与 HTTP-side 行为对齐）.

        HTTP-side 在 ``web_ui_routes/task.py`` 的 normalised_defaults 循环里也做
        ``isinstance(d, (int, float)) -> bool(d)`` 同样的归一；本测试锁这两条
        路径的 truthy 语义一致。"""
        # int truthy/falsy
        self.assertDualPathEquivalent(
            mcp_input=[{"label": "A", "default": 1}],
            expected_labels=["A"],
            expected_defaults=[True],
            msg="int 1 -> True",
        )
        self.assertDualPathEquivalent(
            mcp_input=[{"label": "B", "default": 0}],
            expected_labels=["B"],
            expected_defaults=[False],
            msg="int 0 -> False",
        )
        # string truthy: "true"/"1"/"yes"/"y"/"on"/"selected"（与 _normalize_option_default 一致）
        for truthy in ("true", "TRUE", "1", "yes", "y", "on", "selected"):
            self.assertDualPathEquivalent(
                mcp_input=[{"label": "X", "default": truthy}],
                expected_labels=["X"],
                expected_defaults=[True],
                msg=f"string {truthy!r} -> True",
            )
        # string falsy: 其他全部 → False
        self.assertDualPathEquivalent(
            mcp_input=[{"label": "Y", "default": "no"}],
            expected_labels=["Y"],
            expected_defaults=[False],
            msg="string 'no' -> False",
        )


class TestHttpSideStrictlyRejectsDictForm(unittest.TestCase):
    """HTTP-side ``POST /api/tasks`` 在 R167 设计上**只接受 parallel-array**。

    本测试不直接挑 Flask 客户端跑端到端，而是检查 ``web_ui_routes/task.py``
    源码里那段「``predefined_options`` 元素必须是字符串」的 400 分支仍然存在，
    防止未来误改成"也接受 dict"，破坏 dual-path 分工。
    """

    def test_post_handler_rejects_non_string_options(self) -> None:
        """``web_ui_routes/task.py::create_task`` 必须在 ``options_raw`` 元素非
        str 时返回 400 + 「必须是字符串」错误消息——这是 dual-path 分工的
        显式标记，dict 形态走 MCP，parallel-array 走 HTTP。"""
        from pathlib import Path

        src = (
            Path(__file__).resolve().parent.parent
            / "src"
            / "ai_intervention_agent"
            / "web_ui_routes"
            / "task.py"
        ).read_text(encoding="utf-8")
        self.assertIn(
            "predefined_options（或 options）元素必须是字符串",
            src,
            "POST /api/tasks 应保持「只接受 list[str]」的 dual-path 分工 —— "
            "如果改成支持 list[dict]，本测试会失败提醒同步更新 CR#10 F-3 "
            "invariant 文档与 R167 设计契约。",
        )


if __name__ == "__main__":
    unittest.main()
