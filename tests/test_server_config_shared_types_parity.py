r"""防回归：``server_config.py`` 顶部的运行时钳位常量 = ``shared_types.SECTION_MODELS::feedback`` Pydantic 边界。

历史背景
---------
``shared_types.SECTION_MODELS::feedback`` 中的 ``backend_max_wait`` /
``frontend_countdown`` 用 ``BeforeValidator(_clamp_int(...))`` 各自定义了
``[10, 7200]`` 和 ``[10, 3600]`` 的合法范围；但 ``server_config.py`` 顶部
另外维护着一份运行时常量（``FEEDBACK_TIMEOUT_MIN/MAX`` 与
``AUTO_RESUBMIT_TIMEOUT_MIN/MAX``）—— ``task_queue.py`` 和
``web_ui_validators.py`` 在二次 clamp 时使用的就是这套常量。

历史漂移：v1.5.x 早期 ``server_config`` 的范围比 ``shared_types`` 严格
（``FEEDBACK_TIMEOUT_MAX=3600`` vs Pydantic ``7200``；``AUTO_RESUBMIT_TIMEOUT_MAX
=250`` vs Pydantic ``3600``），导致用户在 ``config.toml`` 写
``frontend_countdown = 1000``，Pydantic 接受 ``1000``，但 web_ui 二次 clamp
回 ``250``——表面通过校验，运行时被静默截断。

修复后加这个回归位，把"runtime clamp 常量 = SECTION_MODELS Pydantic 范围"
的契约锁住——以后任何一边动了，CI 都必须在另一边同步。

设计原则
--------
- 复用 ``test_config_docs_range_parity.py`` 已有的 ``_introspect_field_bounds``
  introspection（避免硬编码 ``(10, 7200)``）。Pydantic 字段边界变了，本测试
  会自动反映新数字，无需手动同步。
- ``test_introspect_recovers_known_bounds`` 在另一份测试里已经守住了
  introspection 算法本身，本测试只验证「常量值 = 反推值」的等价性。
- 错误消息里给出可立刻复制的修复 hint，节省排查时间。
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from server_config import (
    AUTO_RESUBMIT_TIMEOUT_MAX,
    AUTO_RESUBMIT_TIMEOUT_MIN,
    FEEDBACK_TIMEOUT_MAX,
    FEEDBACK_TIMEOUT_MIN,
)
from shared_types import SECTION_MODELS
from tests.test_config_docs_range_parity import (
    _introspect_field_bounds,
)


class TestServerConfigSharedTypesParity(unittest.TestCase):
    """``server_config`` 顶部的 4 个 runtime clamp 常量必须 = ``SECTION_MODELS::feedback`` Pydantic 边界。"""

    def setUp(self) -> None:
        self.feedback_bounds = _introspect_field_bounds(SECTION_MODELS["feedback"])
        # Sanity check：introspect 至少要拿到我们关心的两个字段，否则
        # 说明 _clamp_int 实现细节变了，本测试自身逻辑需要先随之更新
        for key in ("backend_max_wait", "frontend_countdown"):
            self.assertIn(
                key,
                self.feedback_bounds,
                "introspect_field_bounds 没找到 SECTION_MODELS::feedback 中的 "
                f"`{key}`——说明 shared_types._clamp_int 工厂签名变了，"
                "本测试需要先更新 introspection 逻辑",
            )

    def test_feedback_timeout_matches_backend_max_wait(self) -> None:
        """``FEEDBACK_TIMEOUT_MIN/MAX`` ↔ ``SECTION_MODELS::feedback.backend_max_wait``"""
        py_min, py_max = self.feedback_bounds["backend_max_wait"]
        self.assertEqual(
            (FEEDBACK_TIMEOUT_MIN, FEEDBACK_TIMEOUT_MAX),
            (py_min, py_max),
            f"server_config.FEEDBACK_TIMEOUT_MIN/MAX = "
            f"({FEEDBACK_TIMEOUT_MIN}, {FEEDBACK_TIMEOUT_MAX}) "
            f"but shared_types.SECTION_MODELS::feedback.backend_max_wait clamps to "
            f"({py_min}, {py_max}). "
            f"Update server_config.py top-level constants OR shared_types.py "
            f"_clamp_int(...) bounds so they stay in lockstep.",
        )

    def test_auto_resubmit_timeout_matches_frontend_countdown(self) -> None:
        """``AUTO_RESUBMIT_TIMEOUT_MIN/MAX`` ↔ ``SECTION_MODELS::feedback.frontend_countdown``"""
        py_min, py_max = self.feedback_bounds["frontend_countdown"]
        self.assertEqual(
            (AUTO_RESUBMIT_TIMEOUT_MIN, AUTO_RESUBMIT_TIMEOUT_MAX),
            (py_min, py_max),
            f"server_config.AUTO_RESUBMIT_TIMEOUT_MIN/MAX = "
            f"({AUTO_RESUBMIT_TIMEOUT_MIN}, {AUTO_RESUBMIT_TIMEOUT_MAX}) "
            f"but shared_types.SECTION_MODELS::feedback.frontend_countdown clamps to "
            f"({py_min}, {py_max}). "
            f"Update server_config.py top-level constants OR shared_types.py "
            f"_clamp_int_allow_zero(...) bounds so they stay in lockstep.",
        )


if __name__ == "__main__":
    unittest.main()
