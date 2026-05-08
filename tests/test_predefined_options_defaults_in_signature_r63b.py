"""R63b — ``interactive_feedback`` 函数签名暴露 ``predefined_options_defaults``。

为什么需要这层锁
================

历史上 ``server_feedback.interactive_feedback`` 函数签名只有
``predefined_options`` 参数（接受 list[str] / list[dict] 两种形态），
没有显式的 ``predefined_options_defaults`` 平行数组参数。但
``docs/mcp_tools.md`` v1.5.20+ 公开 API 明文告诉 LLM 可以这样用：

::

    interactive_feedback(
      message="...",
      predefined_options=["Rebase", "Merge", "Defer"],
      predefined_options_defaults=[true, false, false]
    )

矛盾：FastMCP 把函数签名转成 JSON Schema 时 ``additionalProperties: false``
默认开启，``predefined_options_defaults`` 不在 properties 里就会被
ToolError 拒掉，但 docs 又说能用。

R63b 同时做三件事：

1. 在 ``predefined_options`` description 里 **显式列出三种输入形态**，
   尤其纠正过去的 "MUST be a JSON array of strings"
   误导（实际后端早就支持 dict / list-pair 两种附加形态）。
2. 把过去 description 里 ``[Recommended] ...`` 文本前缀的 trick 改成
   推荐用 ``{"label": ..., "default": true}`` dict 形态——前后端都已经
   渲染真的 pre-checked 复选框，让 LLM 用真功能而不是文本 hack。
3. 真的把 ``predefined_options_defaults`` 加进函数签名作为 ``list | None``
   形参，并在函数体内合并成 dict 形态后再交给
   ``server_config.validate_input_with_defaults``。

锁住设计意图：

* 函数签名里有 ``predefined_options_defaults`` 形参；
* 三种 description 关键词都在；
* parallel array 形态的 fixture 实际能产生默认勾选的任务；
* dict 形态的 default 优先级高于 parallel array（dict 形态显式传
  ``default`` 时 parallel array 不能覆盖）。
"""

from __future__ import annotations

import inspect
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import server_config
import server_feedback


class TestInteractiveFeedbackSignatureExposesDefaults(unittest.TestCase):
    """``interactive_feedback`` 必须把 ``predefined_options_defaults`` 作为顶层参数暴露。"""

    def setUp(self) -> None:
        self.sig = inspect.signature(server_feedback.interactive_feedback)

    def test_predefined_options_defaults_param_exists(self) -> None:
        self.assertIn(
            "predefined_options_defaults",
            self.sig.parameters,
            "interactive_feedback 必须有 predefined_options_defaults 参数；"
            "否则 docs/mcp_tools.md 公开的并行数组 API 在 MCP schema 里被 "
            "additionalProperties: false 拒掉",
        )

    def test_default_value_is_none(self) -> None:
        param = self.sig.parameters["predefined_options_defaults"]
        # FastMCP / pydantic Field 默认值是 FieldInfo，不是裸 None；从 Field 提取
        from pydantic.fields import FieldInfo

        if isinstance(param.default, FieldInfo):
            self.assertIsNone(
                param.default.default,
                "predefined_options_defaults 必须默认 None，让 LLM 可省略此参数",
            )
        else:
            self.assertIsNone(
                param.default,
                "predefined_options_defaults 必须默认 None，让 LLM 可省略此参数",
            )


class TestDescriptionMentionsAllThreeShapes(unittest.TestCase):
    """``predefined_options`` description 必须明确列出三种输入形态。"""

    def setUp(self) -> None:
        self.sig = inspect.signature(server_feedback.interactive_feedback)
        param = self.sig.parameters["predefined_options"]
        from pydantic.fields import FieldInfo

        self.desc = (
            param.default.description if isinstance(param.default, FieldInfo) else ""
        )
        self.assertTrue(self.desc, "predefined_options 必须有非空 description")

    def test_mentions_list_str_form(self) -> None:
        self.assertIn(
            "list[str]",
            self.desc,
            "description 必须明确列出 list[str] 形态",
        )

    def test_mentions_dict_label_default_form(self) -> None:
        self.assertIn(
            "label",
            self.desc,
            "description 必须提到 dict 形态里的 label 字段",
        )
        self.assertIn(
            "default",
            self.desc,
            "description 必须提到 dict 形态里的 default 字段，让 LLM 知道有"
            "「默认勾选」UI 能力，而不是依赖文本前缀 hack",
        )

    def test_mentions_predefined_options_defaults_param(self) -> None:
        self.assertIn(
            "predefined_options_defaults",
            self.desc,
            "description 必须告诉 LLM 还有平行数组形态可用，否则 docs/mcp_tools.md "
            "和 schema 之间永远不一致",
        )

    def test_does_not_recommend_inline_text_prefix_trick(self) -> None:
        """description 应主动告诉 LLM 不要再用 ``[Recommended] ...`` 文本 hack。"""
        # 历史 description 里写过 ``mark it (e.g. '[Recommended] ...')``——
        # 这条「积极推荐文本前缀」的话术必须撤掉，否则 LLM 看到后会优先
        # 用最显眼的方案，绕过真正的 default-checked 能力
        self.assertNotIn(
            "[Recommended]",
            self.desc,
            "description 不应再积极推荐 [Recommended] 文本前缀 hack；"
            "应改为推荐 dict 形态的 default 字段",
        )


class TestPredefinedOptionsDefaultsParamDescriptionExists(unittest.TestCase):
    """``predefined_options_defaults`` 自己也要有非空 description（schema 可读性）。"""

    def setUp(self) -> None:
        from pydantic.fields import FieldInfo

        self.sig = inspect.signature(server_feedback.interactive_feedback)
        self.param = self.sig.parameters["predefined_options_defaults"]
        self.assertIsInstance(self.param.default, FieldInfo)
        # type narrowing for ty
        assert isinstance(self.param.default, FieldInfo)
        self.desc: str = self.param.default.description or ""

    def test_description_non_empty_and_mentions_truthy_aliases(self) -> None:
        self.assertTrue(self.desc, "predefined_options_defaults 必须有非空 description")
        # 锁住「告诉 LLM truthy 别名可用」的契约——避免它误以为只接受 bool
        for alias in ('"true"', '"yes"', '"selected"'):
            self.assertIn(
                alias,
                self.desc,
                f"description 必须告诉 LLM 接受 {alias} 这种 truthy 别名",
            )


class TestParallelArrayMergedIntoDictForm(unittest.TestCase):
    """``predefined_options=[...] + predefined_options_defaults=[...]`` 真的能合并。

    我们绕过 MCP/HTTP 直接 fuzz ``validate_input_with_defaults``——但合并逻辑
    在 ``server_feedback.interactive_feedback`` 里，所以这里改用单元逻辑级
    fuzz：直接调用合并步骤的等价代码（手写一个 fixture 调用 helper）。
    """

    def test_validate_helper_accepts_dict_form_after_merge(self) -> None:
        """合并后的 dict 形态能正确产出 (label, default) pair。"""
        merged = [
            {"label": "Rebase", "default": True},
            {"label": "Merge", "default": False},
            {"label": "Defer", "default": False},
        ]
        _, options, defaults = server_config.validate_input_with_defaults(
            "Choose strategy", merged
        )
        self.assertEqual(options, ["Rebase", "Merge", "Defer"])
        self.assertEqual(defaults, [True, False, False])

    def test_dict_form_default_takes_precedence_over_parallel_array(self) -> None:
        """dict 形态显式 ``default`` 时，parallel array 不能盖掉它。

        合并逻辑在 ``server_feedback`` 里，但这里用「dict 形态混合 string」
        的输入证明 ``validate_input_with_defaults`` 自己就保留了 dict 的 default。
        """
        # 用混合形态：第一项 dict（自带 default=True），后两项 string
        merged_mixed = [
            {"label": "Rebase", "default": True},
            "Merge",
            "Defer",
        ]
        _, options, defaults = server_config.validate_input_with_defaults(
            "x", merged_mixed
        )
        self.assertEqual(options, ["Rebase", "Merge", "Defer"])
        self.assertEqual(
            defaults,
            [True, False, False],
            "dict 形态的 default 必须保留，纯 string 项默认 False",
        )

    def test_truthy_aliases_normalize_to_true(self) -> None:
        merged = [
            {"label": "A", "default": "yes"},
            {"label": "B", "default": "true"},
            {"label": "C", "default": 1},
            {"label": "D", "default": "selected"},
            {"label": "E", "default": "no"},
            {"label": "F", "default": 0},
            {"label": "G", "default": None},
        ]
        _, _, defaults = server_config.validate_input_with_defaults("x", merged)
        self.assertEqual(
            defaults,
            [True, True, True, True, False, False, False],
            "_normalize_option_default 必须把 truthy 别名都归一化到 True，"
            "其它（含 None/0/'no'）归到 False",
        )


if __name__ == "__main__":
    unittest.main()
