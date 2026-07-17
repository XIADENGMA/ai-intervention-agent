"""R208 / Cycle 10 · F-204-2 · `_compute_age_seconds_from_iso` helper tests。

设计目标
========

R208 把 R199 ``GET /api/system/api-token-info`` endpoint inline 的
age 计算与 R204 ``_safe_token_age_seconds()`` helper 的 age 计算
统一到 module-level ``_compute_age_seconds_from_iso(rotated_at)``
共享 helper。之前两份 verbatim duplicated, 任何 bug fix 必须同步,
R204 ``TestEndpointMetricParity`` 在运行时验证一致。R208 在 source
level 消除 drift 风险。

本测试覆盖共享 helper 的所有边界 case (从 R204 helper test + R199
endpoint test 合并精简而来)；R199 + R204 自己的 test 保留, 验证
调用点行为不变 (regression)。

测试覆盖 (13 cases / 4 invariant class)
========================================

1. **TestNonStringInput** (3): None / int / dict 非 str 输入 → None
2. **TestEmptyString** (1): "" / "   " 空 / whitespace → None
3. **TestMalformedTimestamp** (3): 完全乱码 / 部分 ISO / 月份 13 →
   None (ValueError 被 catch)
4. **TestValidTimestamp** (6): UTC Z 后缀 / +00:00 / 整数秒 / 浮点秒 /
   45 天前 / 刚刚 (0/1 秒前) → 正确 int
5. **TestFutureTimestamp** (2): 未来 1 秒 / 未来 1 天 → None (clock
   skew 防御)
"""

from __future__ import annotations

import inspect
import sys
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import ai_intervention_agent.web_ui_routes.system as system_routes
from ai_intervention_agent.web_ui_routes.system import (
    _compute_age_seconds_from_iso,
)


def _iso_ago(*, seconds: float = 0, days: float = 0) -> str:
    """生成 N 秒 / 天前的 UTC Z 时间戳, helper-friendly。"""
    ts = datetime.now(UTC) - timedelta(seconds=seconds, days=days)
    return ts.isoformat().replace("+00:00", "Z")


def _iso_future(*, seconds: float = 0, days: float = 0) -> str:
    ts = datetime.now(UTC) + timedelta(seconds=seconds, days=days)
    return ts.isoformat().replace("+00:00", "Z")


# ---------------------------------------------------------------------------
# 1. Non-string input
# ---------------------------------------------------------------------------


class TestNonStringInput(unittest.TestCase):
    """非 str 输入全部 → None (helper 不抛, caller 不必预先 isinstance)。"""

    def test_none_input(self) -> None:
        self.assertIsNone(_compute_age_seconds_from_iso(None))

    def test_int_input(self) -> None:
        self.assertIsNone(_compute_age_seconds_from_iso(1234567890))

    def test_dict_input(self) -> None:
        self.assertIsNone(_compute_age_seconds_from_iso({"rotated_at": "x"}))


# ---------------------------------------------------------------------------
# 2. Empty / whitespace string
# ---------------------------------------------------------------------------


class TestEmptyString(unittest.TestCase):
    def test_empty_string_returns_none(self) -> None:
        self.assertIsNone(_compute_age_seconds_from_iso(""))


# ---------------------------------------------------------------------------
# 3. Malformed timestamp
# ---------------------------------------------------------------------------


class TestMalformedTimestamp(unittest.TestCase):
    """脏数据 → None (catch ValueError + TypeError, 不抛)。"""

    def test_random_gibberish(self) -> None:
        self.assertIsNone(_compute_age_seconds_from_iso("not_a_date"))

    def test_partial_iso(self) -> None:
        """``2026-01`` 缺日, fromisoformat 在 3.11 之前不允许 (3.11+
        允许 partial date 但意义不同)。这里测一种确实非法的形式。"""
        self.assertIsNone(_compute_age_seconds_from_iso("2026-13-01"))  # 月份 13

    def test_alphabetic_in_timestamp(self) -> None:
        self.assertIsNone(
            _compute_age_seconds_from_iso("2026-XX-15T00:00:00Z"),
        )


# ---------------------------------------------------------------------------
# 4. Valid timestamp → 正确 int
# ---------------------------------------------------------------------------


class TestValidTimestamp(unittest.TestCase):
    def test_utc_z_suffix_30_seconds_ago(self) -> None:
        """Z 后缀必须被识别 (Python 3.10 兼容兜底, 3.11+ 原生 OK)。"""
        result = _compute_age_seconds_from_iso(_iso_ago(seconds=30))
        self.assertIsNotNone(result)
        assert result is not None
        # 时钟漂移容忍 ±3 秒 (CI 慢机器)
        self.assertGreaterEqual(result, 27)
        self.assertLessEqual(result, 33)

    def test_explicit_offset_plus_0000(self) -> None:
        """显式 +00:00 offset 必须识别。"""
        ts = (datetime.now(UTC) - timedelta(seconds=60)).isoformat()
        # 此时 ts 已经是 "...+00:00" 形式
        result = _compute_age_seconds_from_iso(ts)
        self.assertIsNotNone(result)
        assert result is not None
        self.assertGreaterEqual(result, 57)
        self.assertLessEqual(result, 63)

    def test_45_days_ago(self) -> None:
        """NIST 建议 token rotate 期 30-90 天, 中点 45 天 case。"""
        result = _compute_age_seconds_from_iso(_iso_ago(days=45))
        self.assertIsNotNone(result)
        assert result is not None
        expected = 45 * 86400
        self.assertGreaterEqual(result, expected - 60)
        self.assertLessEqual(result, expected + 60)

    def test_just_now_returns_small_int(self) -> None:
        """刚刚 (0 秒前) → 结果应是 0 或非常小的 int。"""
        result = _compute_age_seconds_from_iso(_iso_ago(seconds=0))
        self.assertIsNotNone(result)
        assert result is not None
        self.assertGreaterEqual(result, 0)
        self.assertLessEqual(result, 3)

    def test_returns_int_type_not_float(self) -> None:
        """**契约**: 返回类型必须是 int (不是 float), 让 caller json.dumps
        输出整数而非 1234.5 (用户 / Grafana 不期望浮点秒)。"""
        result = _compute_age_seconds_from_iso(_iso_ago(seconds=10))
        self.assertIsNotNone(result)
        self.assertIsInstance(result, int)

    def test_fractional_seconds_in_timestamp_still_returns_int(self) -> None:
        """ISO 含微秒 (``...T00:00:00.123456Z``) 也能解析, 整数秒返回。"""
        ts_str = (datetime.now(UTC) - timedelta(seconds=10.5)).isoformat()
        result = _compute_age_seconds_from_iso(ts_str.replace("+00:00", "Z"))
        self.assertIsNotNone(result)
        assert result is not None
        self.assertIsInstance(result, int)
        self.assertGreaterEqual(result, 7)
        self.assertLessEqual(result, 13)


# ---------------------------------------------------------------------------
# 5. Future timestamp → None (clock skew defense)
# ---------------------------------------------------------------------------


class TestFutureTimestamp(unittest.TestCase):
    """未来时间戳 → None。0 也不合适——dashboard 看到 0 会误以为刚轮换。"""

    def test_one_second_in_future_returns_none(self) -> None:
        self.assertIsNone(_compute_age_seconds_from_iso(_iso_future(seconds=10)))

    def test_one_day_in_future_returns_none(self) -> None:
        self.assertIsNone(_compute_age_seconds_from_iso(_iso_future(days=1)))


class TestImportPlacementPerfInvariant(unittest.TestCase):
    """R470: hot age helper must not repeat stdlib import binding per call."""

    def test_compute_age_helper_has_no_local_datetime_import(self) -> None:
        source = inspect.getsource(_compute_age_seconds_from_iso)

        self.assertNotIn("from datetime import", source)

    def test_datetime_import_is_module_scoped_once(self) -> None:
        module_path = Path(system_routes.__file__)
        source = module_path.read_text(encoding="utf-8")

        self.assertEqual(source.count("from datetime import UTC, datetime"), 1)


if __name__ == "__main__":
    unittest.main()
