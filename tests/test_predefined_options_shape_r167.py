"""R167 — ``predefined_options`` 形态收敛锁：移除并行数组形态，保留 dict / list[str] 两种。

为什么需要这层锁
================

R63b（v1.5.20）一度引入了三种形态：``list[str]`` / ``list[dict]`` /
``list[str] + predefined_options_defaults``。其中第三种"平行数组"形态
和 ``list[dict]`` 功能完全重复，但带来若干隐患：

1. **平行数组反模式** —— 长度对齐 / 索引错位是经典 bug 面；
2. **API 表面冗余** —— LLM 需要记忆两个相关字段；
3. **JSON Schema 无法 enforce 位置约束** —— "第 i 项 default 对应第 i 项 label"
   这种"位置依赖语义"只能靠 prose docs 强调；
4. **LLM-unfriendly** —— 在 sample 时容易少填一个数组或位置错位；
5. **与业界主流不一致** —— HTML ``<option selected>``、React ``[{value, label,
   defaultChecked}]``、JSON Schema ``enum`` + ``default`` 都倾向"对象式"
   表达单一形态。

R167（v1.6.0+）做的事情：

- **移除** ``predefined_options_defaults`` 顶层参数。
- **移除** ``server_feedback.interactive_feedback`` 中的 parallel array
  合并逻辑（"detect list + zip into dict form"）。
- **保留** 两种 canonical 形态：
  - ``list[dict]`` —— RECOMMENDED 写法（带 ``default: true`` 表达推荐项）；
  - ``list[str]`` —— 简单 fallback（所有项默认未勾选）。
- **保留** ``validate_input_with_defaults`` 的 dict 形态解析能力——这是
  内部公共 helper，前端仍可通过 ``POST /api/tasks`` 的 HTTP 接口传
  ``predefined_options_defaults`` 字段（VS Code 插件 / 外部脚本路径），
  但 LLM 的 MCP 调用必须用 dict 形态。

锁住设计意图
============

1. **签名锁** —— ``predefined_options_defaults`` 不在 ``interactive_feedback``
   函数签名里，避免后续 PR 又恢复并行数组的诱惑。
2. **description 锁** —— ``predefined_options`` description 里必须有
   "RECOMMENDED" 字眼引导 LLM 用 dict 形态。
3. **dict 形态正向 fuzz 锁** —— ``validate_input_with_defaults`` 接受
   dict 形态 + truthy 别名归一化，保证 LLM 写 ``{"label": "X",
   "default": true}`` 时不会因为类型杂乱被 silently dropped。
"""

from __future__ import annotations

import inspect
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import ai_intervention_agent.server_config as server_config
import ai_intervention_agent.server_feedback as server_feedback


class TestPredefinedOptionsDefaultsParamRemoved(unittest.TestCase):
    """R167：``interactive_feedback`` 函数签名中不再有 ``predefined_options_defaults`` 参数。"""

    def setUp(self) -> None:
        self.sig = inspect.signature(server_feedback.interactive_feedback)

    def test_param_no_longer_in_signature(self) -> None:
        self.assertNotIn(
            "predefined_options_defaults",
            self.sig.parameters,
            "R167 已移除 predefined_options_defaults 顶层参数；如再次出现"
            "意味着『功能去重』被 revert，请改用 list[dict] 形态",
        )

    def test_predefined_options_still_in_signature(self) -> None:
        self.assertIn(
            "predefined_options",
            self.sig.parameters,
            "predefined_options 主参数必须保留（list[str] / list[dict] 两形态）",
        )


class TestDescriptionRecommendsDictForm(unittest.TestCase):
    """``predefined_options`` description 必须主动推荐 list[dict] 形态。"""

    def setUp(self) -> None:
        from pydantic.fields import FieldInfo

        self.sig = inspect.signature(server_feedback.interactive_feedback)
        param = self.sig.parameters["predefined_options"]
        self.desc = (
            param.default.description if isinstance(param.default, FieldInfo) else ""
        )
        self.assertTrue(self.desc, "predefined_options 必须有非空 description")

    def test_mentions_list_str_form(self) -> None:
        """list[str] 形态是简洁回退路径，必须保留在 description 里。"""
        self.assertIn(
            "list[str]",
            self.desc,
            "description 必须告诉 LLM 还有 list[str] 这种简洁形态可用",
        )

    def test_mentions_dict_label_default_form(self) -> None:
        """list[dict] 形态是 RECOMMENDED 写法；label/default 字段必须出现。"""
        self.assertIn(
            "label",
            self.desc,
            "description 必须告诉 LLM dict 形态里有 label 字段",
        )
        self.assertIn(
            "default",
            self.desc,
            "description 必须告诉 LLM dict 形态里有 default 字段（推荐项标记）",
        )

    def test_actively_recommends_dict_form(self) -> None:
        """description 必须主动告诉 LLM dict 形态是 RECOMMENDED——不能两形态平等。"""
        # 强调"RECOMMENDED"或类似积极引导词；锁住"积极推荐 dict 形态"的契约
        recommend_markers = ("RECOMMENDED", "PREFER", "recommend")
        hit = any(marker in self.desc for marker in recommend_markers)
        self.assertTrue(
            hit,
            "description 应当主动推荐 list[dict] 形态（出现 RECOMMENDED/PREFER 等关键词），"
            f"实际 description: {self.desc[:200]}",
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

    def test_mentions_removal_of_parallel_array_shape(self) -> None:
        """description 应明确告诉 LLM R167 已移除并行数组形态，避免它继续 sample 旧形态。"""
        self.assertIn(
            "removed",
            self.desc,
            "description 应该明确告诉 LLM R167 已移除 predefined_options_defaults 并行数组形态",
        )


class TestDictFormSemantics(unittest.TestCase):
    """``validate_input_with_defaults`` 对 dict 形态的解析必须保持稳定。

    这部分继承自 R63b 的 fuzz 测试，保证移除 parallel array 形态后
    dict 形态的所有正向能力都被锁住——避免日后误改 helper 把 dict 形态
    也一并打掉。
    """

    def test_dict_form_canonical_three_items(self) -> None:
        """完整 dict 形态：(label, default) pair 正确提取。"""
        items = [
            {"label": "Rebase", "default": True},
            {"label": "Merge", "default": False},
            {"label": "Defer", "default": False},
        ]
        _, options, defaults = server_config.validate_input_with_defaults(
            "Choose strategy", items
        )
        self.assertEqual(options, ["Rebase", "Merge", "Defer"])
        self.assertEqual(defaults, [True, False, False])

    def test_dict_form_field_aliases_label(self) -> None:
        """label 字段的 alias（text / value）必须被识别——避免 LLM 改写 key 时被 drop。"""
        # 用 text alias
        _, options, _ = server_config.validate_input_with_defaults(
            "x", [{"text": "Alpha", "default": True}]
        )
        self.assertEqual(options, ["Alpha"])
        # 用 value alias
        _, options2, _ = server_config.validate_input_with_defaults(
            "x", [{"value": "Beta"}]
        )
        self.assertEqual(options2, ["Beta"])

    def test_dict_form_field_aliases_default(self) -> None:
        """default 字段的 alias（selected / checked）必须被识别。"""
        items = [
            {"label": "A", "selected": True},
            {"label": "B", "checked": True},
            {"label": "C", "default": True},
        ]
        _, _, defaults = server_config.validate_input_with_defaults("x", items)
        self.assertEqual(defaults, [True, True, True])

    def test_mixed_string_and_dict_items(self) -> None:
        """混合形态（list 里同时有 str 和 dict）应当被正确归一化。"""
        items = [
            {"label": "Rebase", "default": True},
            "Merge",
            "Defer",
        ]
        _, options, defaults = server_config.validate_input_with_defaults("x", items)
        self.assertEqual(options, ["Rebase", "Merge", "Defer"])
        self.assertEqual(
            defaults,
            [True, False, False],
            "纯 string 项默认 False，dict 项保留显式 default",
        )

    def test_truthy_aliases_for_default_field(self) -> None:
        """default 字段接受 truthy/falsy 字符串别名（case-insensitive, trimmed）。"""
        items = [
            {"label": "A", "default": "yes"},
            {"label": "B", "default": "true"},
            {"label": "C", "default": 1},
            {"label": "D", "default": "selected"},
            {"label": "E", "default": "no"},
            {"label": "F", "default": 0},
            {"label": "G", "default": None},
        ]
        _, _, defaults = server_config.validate_input_with_defaults("x", items)
        self.assertEqual(
            defaults,
            [True, True, True, True, False, False, False],
            "_normalize_option_default 必须把 truthy 别名都归一化到 True，"
            "其它（含 None/0/'no'）归到 False",
        )


class TestListStrFormSemantics(unittest.TestCase):
    """list[str] 形态（简洁形态）的解析必须保持稳定。"""

    def test_list_str_form_all_defaults_false(self) -> None:
        """纯 list[str]：所有 option 的 default 必须是 False。"""
        _, options, defaults = server_config.validate_input_with_defaults(
            "x", ["Rebase", "Merge", "Defer"]
        )
        self.assertEqual(options, ["Rebase", "Merge", "Defer"])
        self.assertEqual(defaults, [False, False, False])

    def test_empty_list_returns_empty(self) -> None:
        _, options, defaults = server_config.validate_input_with_defaults("x", [])
        self.assertEqual(options, [])
        self.assertEqual(defaults, [])

    def test_none_returns_empty(self) -> None:
        _, options, defaults = server_config.validate_input_with_defaults("x", None)
        self.assertEqual(options, [])
        self.assertEqual(defaults, [])


if __name__ == "__main__":
    unittest.main()
