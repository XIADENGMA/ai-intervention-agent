"""``shared_types`` Pydantic BeforeValidator 助手单元覆盖 (R38)

R38 之前 ``shared_types.py`` 整体覆盖率 75.66%，所有未覆盖行都集中在
``_coerce_bool`` / ``_coerce_int`` / ``_coerce_float`` / ``_coerce_str`` /
``_clamp_int`` / ``_clamp_int_allow_zero`` / ``_clamp_float`` 这一组
``BeforeValidator`` 助手函数——它们承担 TOML / JSON 配置值 *入口* 的强转
+ 钳位职责，是 ``SECTION_MODELS`` 的"防御性外壳"，但仅通过 Pydantic 段模
型间接调用，正常配置文件根本走不到它们的异常分支。

为什么直接测函数而不是只测 Pydantic 模型：

- ``test_config_manager.py`` / ``test_server_config_shared_types_parity.py``
  覆盖的是"模型在合法配置上的行为"，无法系统性触达这一组 helper 的
  异常分支（例如 ``_coerce_int("not-a-number")`` / ``_clamp_float(None)``）。
- 这些 helper 是 *公开行为* —— 任何用户写出的诡异 TOML 值（``port = "8080"``、
  ``retry_delay = "1.0"``、``enabled = "yes"``）都会走到它们；如果有人未来
  把 ``except (TypeError, ValueError)`` 写成 ``except ValueError`` 漏掉
  ``int(None)`` 抛 ``TypeError`` 的路径，配置加载就会在生产 server 启动
  期 hard-fail，而本来 ``_clamp_int`` 应当 fall back 到 default。
- pytest+coverage 跑下来这一文件落到 96%+，把实际"防御逻辑"完整锁死。

测试矩阵：
==========
``_coerce_bool``  : True/False, 0/1 (int), 0.0/1.0 (float), "true"/"TRUE"/
                    "1"/"yes"/"y"/"on", "false"/"FALSE"/"0"/"no"/"n"/"off",
                    带前后空白, 不可识别字符串, None, dict, list 这种 fall
                    through 路径。
``_coerce_int``   : True/False (bool 子类提前返回), int, float (走 int(float)),
                    数字字符串, 浮点字符串, 非数字字符串, None。
``_coerce_float`` : 同上 + isinstance bool 排除。
``_coerce_str``   : None passthrough, 数字 / list 转 str。
``_clamp_int``    : 在范围内 / 上越界 / 下越界 / 无法转换 (TypeError, ValueError)
                    → 走 default。
``_clamp_int_allow_zero``: 0 / 负值 → 0 ; 1+ 钳位常规路径 ; 异常路径 → default。
``_clamp_float``  : 同 ``_clamp_int`` 但 float 域。
"""

from __future__ import annotations

import unittest

from shared_types import (
    _clamp_float,
    _clamp_int,
    _clamp_int_allow_zero,
    _coerce_bool,
    _coerce_float,
    _coerce_int,
    _coerce_str,
)


class TestCoerceBool(unittest.TestCase):
    def test_native_true_passthrough(self) -> None:
        self.assertIs(_coerce_bool(True), True)

    def test_native_false_passthrough(self) -> None:
        self.assertIs(_coerce_bool(False), False)

    def test_int_one_to_true(self) -> None:
        self.assertIs(_coerce_bool(1), True)

    def test_int_zero_to_false(self) -> None:
        self.assertIs(_coerce_bool(0), False)

    def test_negative_int_truthy(self) -> None:
        self.assertIs(_coerce_bool(-7), True)

    def test_float_one_to_true(self) -> None:
        self.assertIs(_coerce_bool(1.0), True)

    def test_float_zero_to_false(self) -> None:
        self.assertIs(_coerce_bool(0.0), False)

    def test_string_true_variants_case_insensitive(self) -> None:
        for raw in ("true", "TRUE", "True", "  TrUe  ", "1", "yes", "y", "ON"):
            with self.subTest(raw=raw):
                self.assertIs(
                    _coerce_bool(raw),
                    True,
                    f"_coerce_bool({raw!r}) 应当返回 True",
                )

    def test_string_false_variants_case_insensitive(self) -> None:
        for raw in ("false", "FALSE", "False", "  FaLsE  ", "0", "no", "n", "OFF"):
            with self.subTest(raw=raw):
                self.assertIs(
                    _coerce_bool(raw),
                    False,
                    f"_coerce_bool({raw!r}) 应当返回 False",
                )

    def test_unrecognized_string_passthrough(self) -> None:
        """未识别字符串不能擅自转换；保留原值让 Pydantic 自己抛 ValidationError，
        以便 client / 用户能看到精确诊断信息。"""
        self.assertEqual(_coerce_bool("maybe"), "maybe")
        self.assertEqual(_coerce_bool(""), "")
        self.assertEqual(_coerce_bool("on?"), "on?")

    def test_none_passthrough(self) -> None:
        self.assertIsNone(_coerce_bool(None))

    def test_unknown_type_passthrough(self) -> None:
        sentinel = object()
        self.assertIs(_coerce_bool(sentinel), sentinel)
        self.assertEqual(_coerce_bool([1, 2]), [1, 2])
        self.assertEqual(_coerce_bool({"k": "v"}), {"k": "v"})


class TestCoerceInt(unittest.TestCase):
    def test_bool_short_circuits_int(self) -> None:
        """bool 是 int 的子类；isinstance(True, int) 是 True，所以 _coerce_int
        必须在 *之前* 单独处理布尔，否则 ``_coerce_int(True)`` 会无意义地走到
        try/int 分支。这里锁住"bool 走第一个分支"的行为不被悄悄回退。"""
        self.assertEqual(_coerce_int(True), 1)
        self.assertEqual(_coerce_int(False), 0)

    def test_native_int_passthrough(self) -> None:
        self.assertEqual(_coerce_int(42), 42)
        self.assertEqual(_coerce_int(-7), -7)
        self.assertEqual(_coerce_int(0), 0)

    def test_float_truncates_toward_zero(self) -> None:
        self.assertEqual(_coerce_int(3.9), 3)
        self.assertEqual(_coerce_int(-3.9), -3)
        self.assertEqual(_coerce_int(0.0), 0)

    def test_numeric_string(self) -> None:
        self.assertEqual(_coerce_int("123"), 123)
        self.assertEqual(_coerce_int("-7"), -7)

    def test_float_string(self) -> None:
        self.assertEqual(_coerce_int("1.9"), 1)

    def test_invalid_string_passthrough(self) -> None:
        self.assertEqual(_coerce_int("abc"), "abc")
        self.assertEqual(_coerce_int(""), "")

    def test_none_passthrough(self) -> None:
        self.assertIsNone(_coerce_int(None))

    def test_list_passthrough(self) -> None:
        self.assertEqual(_coerce_int([1]), [1])


class TestCoerceFloat(unittest.TestCase):
    def test_native_float_passthrough(self) -> None:
        self.assertEqual(_coerce_float(3.14), 3.14)
        self.assertEqual(_coerce_float(0.0), 0.0)

    def test_int_to_float(self) -> None:
        result = _coerce_float(7)
        self.assertEqual(result, 7.0)
        self.assertIsInstance(result, float)

    def test_bool_excluded_from_int_branch(self) -> None:
        """``not isinstance(v, bool)`` guard 必须把 True/False 排除掉，让
        ``float(True)`` 走 try/float 路径。运行时表现等价（``float(True) == 1.0``），
        但保留这条 invariant 让代码意图清晰。"""
        result = _coerce_float(True)
        self.assertEqual(result, 1.0)
        self.assertIsInstance(result, float)

    def test_numeric_string(self) -> None:
        self.assertAlmostEqual(_coerce_float("2.5"), 2.5)
        self.assertEqual(_coerce_float("7"), 7.0)

    def test_invalid_string_passthrough(self) -> None:
        self.assertEqual(_coerce_float("abc"), "abc")

    def test_none_passthrough(self) -> None:
        self.assertIsNone(_coerce_float(None))


class TestCoerceStr(unittest.TestCase):
    def test_none_passthrough(self) -> None:
        """None 应当原样传递，让 Pydantic 自己处理（落到字段 default 或抛错）。
        这条比起 ``str(None) == 'None'`` 更安全：用户从 TOML 漏配 key 时不会
        拿到字符串 ``"None"`` 这种诡异默认值。"""
        self.assertIsNone(_coerce_str(None))

    def test_int_to_str(self) -> None:
        self.assertEqual(_coerce_str(42), "42")

    def test_float_to_str(self) -> None:
        self.assertEqual(_coerce_str(3.14), "3.14")

    def test_bool_to_str(self) -> None:
        self.assertEqual(_coerce_str(True), "True")
        self.assertEqual(_coerce_str(False), "False")

    def test_str_passthrough(self) -> None:
        self.assertEqual(_coerce_str("ai.local"), "ai.local")

    def test_list_to_str(self) -> None:
        self.assertEqual(_coerce_str([1, 2]), "[1, 2]")


class TestClampInt(unittest.TestCase):
    def setUp(self) -> None:
        self.validator = _clamp_int(min_val=10, max_val=100, default=50)

    def test_in_range_passthrough(self) -> None:
        self.assertEqual(self.validator(42), 42)
        self.assertEqual(self.validator(10), 10)
        self.assertEqual(self.validator(100), 100)

    def test_below_min_clamps_to_min(self) -> None:
        self.assertEqual(self.validator(0), 10)
        self.assertEqual(self.validator(-99), 10)

    def test_above_max_clamps_to_max(self) -> None:
        self.assertEqual(self.validator(101), 100)
        self.assertEqual(self.validator(99999), 100)

    def test_float_truncated_then_clamped(self) -> None:
        self.assertEqual(self.validator(42.9), 42)
        self.assertEqual(self.validator(150.0), 100)

    def test_numeric_string_accepted(self) -> None:
        self.assertEqual(self.validator("75"), 75)

    def test_invalid_string_returns_default(self) -> None:
        """ValueError 路径——确保 fall-through 到 default 而不是冒泡到上层。"""
        self.assertEqual(self.validator("abc"), 50)

    def test_none_returns_default(self) -> None:
        """TypeError 路径——``int(float(None))`` 会抛 TypeError，必须捕获。"""
        self.assertEqual(self.validator(None), 50)

    def test_bool_handled_explicitly(self) -> None:
        """``int(True) == 1``，``int(float(True)) == 1``，两条路径下 result
        相同；但代码里有 ``not isinstance(v, bool)`` guard 是为了
        future-proof（万一上游 ``BeforeValidator`` 链改成不允许 bool）。"""
        self.assertEqual(self.validator(True), 10)
        self.assertEqual(self.validator(False), 10)


class TestClampIntAllowZero(unittest.TestCase):
    def setUp(self) -> None:
        self.validator = _clamp_int_allow_zero(min_val=10, max_val=100, default=50)

    def test_zero_returns_zero(self) -> None:
        """0 表示"显式禁用"（例如 ``frontend_countdown = 0`` = 永不超时）。
        必须原样保留，不能被 min_val 钳位拉高。"""
        self.assertEqual(self.validator(0), 0)

    def test_negative_returns_zero(self) -> None:
        """负值视作"禁用意图"——降级到 0，而不是 default。"""
        self.assertEqual(self.validator(-5), 0)
        self.assertEqual(self.validator(-99999), 0)

    def test_positive_in_range(self) -> None:
        self.assertEqual(self.validator(50), 50)

    def test_positive_below_min_clamps_up(self) -> None:
        """1 ≤ v < min_val 必须被钳位到 min_val（不像负数那样落到 0）。"""
        self.assertEqual(self.validator(1), 10)

    def test_positive_above_max_clamps_down(self) -> None:
        self.assertEqual(self.validator(500), 100)

    def test_invalid_string_returns_default(self) -> None:
        self.assertEqual(self.validator("not-a-number"), 50)

    def test_none_returns_default(self) -> None:
        self.assertEqual(self.validator(None), 50)


class TestClampFloat(unittest.TestCase):
    def setUp(self) -> None:
        self.validator = _clamp_float(min_val=0.5, max_val=10.0, default=1.0)

    def test_in_range_passthrough(self) -> None:
        self.assertAlmostEqual(self.validator(2.5), 2.5)
        self.assertAlmostEqual(self.validator(0.5), 0.5)
        self.assertAlmostEqual(self.validator(10.0), 10.0)

    def test_below_min_clamps_to_min(self) -> None:
        self.assertAlmostEqual(self.validator(0.0), 0.5)
        self.assertAlmostEqual(self.validator(-99.0), 0.5)

    def test_above_max_clamps_to_max(self) -> None:
        self.assertAlmostEqual(self.validator(11.0), 10.0)

    def test_int_promoted_to_float(self) -> None:
        result = self.validator(3)
        self.assertAlmostEqual(result, 3.0)
        self.assertIsInstance(result, float)

    def test_numeric_string_accepted(self) -> None:
        self.assertAlmostEqual(self.validator("2.5"), 2.5)

    def test_invalid_string_returns_default(self) -> None:
        self.assertAlmostEqual(self.validator("abc"), 1.0)

    def test_none_returns_default(self) -> None:
        """None 触发 TypeError；helper 必须落到 default 而不是冒泡。"""
        self.assertAlmostEqual(self.validator(None), 1.0)


class TestSectionModelsIntegration(unittest.TestCase):
    """末端集成 sanity check：通过实际段模型走一遍 helper 路径。

    主要捕获"helper 改了签名但 Annotated 没同步"这种远距离回归——单独跑
    helper 单测能锁住 helper 行为，但模型层面 Annotated 配置可能漂移。
    """

    def test_web_ui_section_clamps_port(self) -> None:
        from shared_types import WebUISectionConfig

        cfg = WebUISectionConfig.model_validate({"port": "99999"})
        self.assertEqual(cfg.port, 65535, "字符串端口应被强转 + 钳位到 65535")

        cfg2 = WebUISectionConfig.model_validate({"port": "abc"})
        self.assertEqual(cfg2.port, 8080, "无法解析的端口应回退到 default 8080")

    def test_feedback_section_allow_zero_for_countdown(self) -> None:
        from shared_types import FeedbackSectionConfig

        cfg = FeedbackSectionConfig.model_validate({"frontend_countdown": 0})
        self.assertEqual(cfg.frontend_countdown, 0, "0 = 显式禁用，不能被钳位")

        cfg_neg = FeedbackSectionConfig.model_validate({"frontend_countdown": -5})
        self.assertEqual(cfg_neg.frontend_countdown, 0, "负值降级到 0（disable）")

    def test_notification_section_coerces_bool_strings(self) -> None:
        from shared_types import NotificationSectionConfig

        cfg = NotificationSectionConfig.model_validate({"enabled": "yes"})
        self.assertTrue(cfg.enabled)

        cfg_off = NotificationSectionConfig.model_validate({"enabled": "off"})
        self.assertFalse(cfg_off.enabled)

    def test_web_ui_section_coerces_retry_delay_string(self) -> None:
        from shared_types import WebUISectionConfig

        cfg = WebUISectionConfig.model_validate({"http_retry_delay": "2.5"})
        self.assertAlmostEqual(cfg.http_retry_delay, 2.5)

        cfg_invalid = WebUISectionConfig.model_validate({"http_retry_delay": "garbage"})
        self.assertAlmostEqual(
            cfg_invalid.http_retry_delay,
            1.0,
            msg="无法解析的浮点数应回退到 default=1.0",
        )


if __name__ == "__main__":
    unittest.main()
