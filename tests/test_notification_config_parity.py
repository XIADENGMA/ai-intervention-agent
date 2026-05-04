r"""防回归：``notification_manager.NotificationConfig`` 的二次 clamp 范围 = ``shared_types.SECTION_MODELS::notification`` Pydantic 范围。

历史背景
--------
``NotificationConfig`` 中的四个 ``coerce_*`` ``field_validator`` 用硬编码
``max(min, min(max, int(v)))`` 做"二次 clamp"：

- ``coerce_retry_count``: ``max(0, min(10, ...))``
- ``coerce_retry_delay``: ``max(0, min(60, ...))``
- ``coerce_bark_timeout``: ``max(1, min(300, ...))``
- ``clamp_sound_volume``:  ClassVar ``[0.0, 1.0]``（``sound_volume`` 在
  ``from_config_file`` 中经 ``/100.0`` 转换；Pydantic 端是 ``[0, 100]``）

而 ``shared_types.SECTION_MODELS::notification`` Pydantic 端通过
``BeforeValidator(_clamp_int(...))`` 维护**另一**份范围。今天（v1.5.x）
两边数字一致，但没有 CI 回归位锁住这个契约——一旦未来有人把 Pydantic
端的 ``retry_count`` 上限从 10 抬到 20，``NotificationConfig`` 的硬编码
``min(10, ...)`` 不会自动跟进，于是用户在 ``config.toml`` 写
``retry_count = 15``，Pydantic 接受 15，``NotificationConfig`` 二次
clamp 回 10——和 ``frontend_countdown`` / ``http_request_timeout``
完全相同的 silent-truncation 反模式。

本测试用**黑盒行为断言**（传越界值，看 clamp 后的结果 = Pydantic
introspected max）锁住这个契约——不依赖 ``coerce_*`` 是 hardcoded 还是
``ClassVar``-based，只要"二次 clamp 上界 = Pydantic 上界"就 OK。

设计原则
--------
- **黑盒优先**：``NotificationConfig`` 中的 4 个 clamp 函数实现各异
  （3 个 hardcoded inline、1 个 ClassVar-driven），用 introspection
  会要求每个分支特殊处理。直接传越界值看输出更鲁棒。
- 复用 ``test_config_docs_range_parity.py::_introspect_field_bounds``，
  保持与其他四份 parity gate 同一套 introspection 入口（避免硬编码
  ``(0, 10)`` 这类 anchor）。
- **`sound_volume` 的尺度差异**显式处理：Pydantic 用百分比 `[0, 100]`，
  ``NotificationConfig`` 用小数 `[0.0, 1.0]`，``from_config_file`` 走
  ``/100.0``。本测试在断言时手动除以 100，确保契约语义对齐而不会
  错把 100 当 1 比。
- ``test_introspect_recovers_known_bounds`` 在 ``test_config_docs_range_parity.py``
  里已经守住了 introspection 算法本身，本测试只验证「越界输入→
  clamp 后等于 Pydantic 上界」的等价性。
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from notification_manager import NotificationConfig
from shared_types import SECTION_MODELS
from tests.test_config_docs_range_parity import _introspect_field_bounds


class TestNotificationConfigParity(unittest.TestCase):
    """``NotificationConfig`` 二次 clamp 上界必须 = ``SECTION_MODELS::notification`` Pydantic 上界。"""

    def setUp(self) -> None:
        self.notif_bounds = _introspect_field_bounds(SECTION_MODELS["notification"])
        for key in ("retry_count", "retry_delay", "bark_timeout", "sound_volume"):
            self.assertIn(
                key,
                self.notif_bounds,
                f"introspect_field_bounds 没找到 SECTION_MODELS::notification 中的 `{key}`"
                "——说明 shared_types._clamp_int 工厂签名变了，本测试需要先更新",
            )

    def _assert_max_matches(self, field: str, oversized_input: int) -> None:
        """构造 ``NotificationConfig`` 传越界整数，看 clamp 后是否 = Pydantic 上界。

        用 ``model_validate(dict)`` 而非 ``**dict`` 解包，是为了让静态类型检查
        （``ty check``）不去尝试匹配每个 BaseModel 字段的精确类型——动态字段名
        本来就走 dict 验证更合适。
        """
        cfg = NotificationConfig.model_validate({field: oversized_input})
        actual = getattr(cfg, field)
        py_max = self.notif_bounds[field][1]
        self.assertEqual(
            actual,
            py_max,
            f"NotificationConfig.{field}({oversized_input}) clamped to {actual}, "
            f"but shared_types.SECTION_MODELS::notification.{field} max is {py_max}. "
            f"Update notification_manager.py coerce_{field} OR shared_types.py "
            f"_clamp_int(...) bounds so they stay in lockstep.",
        )

    def _assert_min_matches(self, field: str, undersized_input: int) -> None:
        """构造 ``NotificationConfig`` 传越界负数，看 clamp 后是否 = Pydantic 下界。"""
        cfg = NotificationConfig.model_validate({field: undersized_input})
        actual = getattr(cfg, field)
        py_min = self.notif_bounds[field][0]
        self.assertEqual(
            actual,
            py_min,
            f"NotificationConfig.{field}({undersized_input}) clamped to {actual}, "
            f"but shared_types.SECTION_MODELS::notification.{field} min is {py_min}. "
            f"Update notification_manager.py coerce_{field} OR shared_types.py "
            f"_clamp_int(...) bounds so they stay in lockstep.",
        )

    def test_retry_count_max_matches_pydantic(self) -> None:
        self._assert_max_matches("retry_count", 99999)

    def test_retry_count_min_matches_pydantic(self) -> None:
        self._assert_min_matches("retry_count", -100)

    def test_retry_delay_max_matches_pydantic(self) -> None:
        self._assert_max_matches("retry_delay", 99999)

    def test_retry_delay_min_matches_pydantic(self) -> None:
        self._assert_min_matches("retry_delay", -100)

    def test_bark_timeout_max_matches_pydantic(self) -> None:
        self._assert_max_matches("bark_timeout", 99999)

    def test_bark_timeout_min_matches_pydantic(self) -> None:
        self._assert_min_matches("bark_timeout", -100)

    def test_sound_volume_max_matches_pydantic_normalised(self) -> None:
        """``sound_volume``：Pydantic ``[0, 100]`` ÷ 100 = ``NotificationConfig`` ``[0.0, 1.0]``"""
        cfg_overshoot = NotificationConfig.model_validate({"sound_volume": 10.0})
        self.assertEqual(
            cfg_overshoot.sound_volume,
            NotificationConfig.SOUND_VOLUME_MAX,
            f"NotificationConfig.sound_volume(10.0) clamped to "
            f"{cfg_overshoot.sound_volume}, expected SOUND_VOLUME_MAX="
            f"{NotificationConfig.SOUND_VOLUME_MAX}",
        )
        # Pydantic 上界 100 ÷ 100 = ClassVar 1.0
        py_max_pct = self.notif_bounds["sound_volume"][1]
        self.assertEqual(
            NotificationConfig.SOUND_VOLUME_MAX,
            py_max_pct / 100.0,
            f"NotificationConfig.SOUND_VOLUME_MAX={NotificationConfig.SOUND_VOLUME_MAX} "
            f"vs shared_types Pydantic max={py_max_pct} ÷ 100 = {py_max_pct / 100.0}. "
            "NotificationConfig works in [0.0, 1.0] (decimals) while Pydantic works in "
            "[0, 100] (percentages); from_config_file divides by 100. If either side "
            "moves, also update the other.",
        )

    def test_sound_volume_min_matches_pydantic_normalised(self) -> None:
        cfg = NotificationConfig.model_validate({"sound_volume": -5.0})
        self.assertEqual(
            cfg.sound_volume,
            NotificationConfig.SOUND_VOLUME_MIN,
            f"NotificationConfig.sound_volume(-5.0) clamped to {cfg.sound_volume}, "
            f"expected SOUND_VOLUME_MIN={NotificationConfig.SOUND_VOLUME_MIN}",
        )
        py_min_pct = self.notif_bounds["sound_volume"][0]
        self.assertEqual(
            NotificationConfig.SOUND_VOLUME_MIN,
            py_min_pct / 100.0,
            f"NotificationConfig.SOUND_VOLUME_MIN={NotificationConfig.SOUND_VOLUME_MIN} "
            f"vs shared_types Pydantic min={py_min_pct} ÷ 100 = {py_min_pct / 100.0}. "
            "Same percentage/decimal scale invariant as the max test.",
        )


if __name__ == "__main__":
    unittest.main()
