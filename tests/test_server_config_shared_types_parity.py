r"""防回归：``server_config.py`` 的运行时钳位常量 = ``shared_types.SECTION_MODELS`` Pydantic 边界。

覆盖范围
--------
1. ``feedback`` section（顶层模块常量）：
   - ``FEEDBACK_TIMEOUT_MIN/MAX`` ↔ ``SECTION_MODELS::feedback.backend_max_wait``
   - ``AUTO_RESUBMIT_TIMEOUT_MIN/MAX`` ↔ ``SECTION_MODELS::feedback.frontend_countdown``
2. ``web_ui`` section（``WebUIConfig.ClassVar``）：
   - ``WebUIConfig.TIMEOUT_MIN/MAX`` ↔ ``SECTION_MODELS::web_ui.http_request_timeout``
   - ``WebUIConfig.MAX_RETRIES_MIN/MAX`` ↔ ``SECTION_MODELS::web_ui.http_max_retries``
   - ``WebUIConfig.RETRY_DELAY_MIN/MAX`` ↔ ``SECTION_MODELS::web_ui.http_retry_delay``

历史背景
--------
``shared_types.SECTION_MODELS`` 中的字段用 ``BeforeValidator(_clamp_int/
_clamp_float(...))`` 定义合法范围；但 ``server_config.py`` 另外维护一份运行
时常量（``FEEDBACK_TIMEOUT_MIN/MAX``、``AUTO_RESUBMIT_TIMEOUT_MIN/MAX``、
``WebUIConfig.TIMEOUT/MAX_RETRIES/RETRY_DELAY_MIN/MAX``），``task_queue.py``、
``web_ui_validators.py`` 与 ``service_manager._load_web_ui_config_from_disk``
做"二次 clamp"时使用的就是这套常量。

历史漂移（v1.5.x 早期）：

- ``FEEDBACK_TIMEOUT_MAX=3600`` vs Pydantic ``7200``
- ``AUTO_RESUBMIT_TIMEOUT_MAX=250`` vs Pydantic ``3600``
- ``WebUIConfig.TIMEOUT_MAX=300`` vs Pydantic ``600``
- ``WebUIConfig.MAX_RETRIES_MAX=10`` vs Pydantic ``20``
- ``WebUIConfig.RETRY_DELAY_MIN=0.1`` vs Pydantic ``0.0``

后果：用户写 ``config.toml`` 中 ``http_request_timeout = 500``，Pydantic 接
受 500，但 ``service_manager`` 在构造 ``WebUIConfig`` 时被二次 clamp 到 300
——表面通过校验，运行时被静默截断（虽然有 warning log）。修复后加这个回
归位，把"runtime clamp 常量 = SECTION_MODELS Pydantic 范围"的契约锁住——
以后任何一边动了，CI 必须在另一边同步。

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
    WebUIConfig,
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


class TestWebUIConfigSharedTypesParity(unittest.TestCase):
    """``WebUIConfig`` 的 6 个 ClassVar 钳位常量必须 = ``SECTION_MODELS::web_ui`` Pydantic 边界。

    历史漂移（在 v1.5.x 中段被发现并修复）：``service_manager`` 把已经被
    Pydantic 校验过的 dict 再传给 ``WebUIConfig(...)`` 构造器，``WebUIConfig``
    内部的 ``@field_validator`` 会做"二次 clamp"。如果 ``ClassVar`` 边界比
    Pydantic 严格，用户在 config 里写 ``http_request_timeout=500`` 会被
    悄悄降到 300——通过 Pydantic 又被运行时截断，最为隐蔽。
    """

    def setUp(self) -> None:
        self.web_ui_bounds = _introspect_field_bounds(SECTION_MODELS["web_ui"])
        for key in ("http_request_timeout", "http_max_retries", "http_retry_delay"):
            self.assertIn(
                key,
                self.web_ui_bounds,
                "introspect_field_bounds 没找到 SECTION_MODELS::web_ui 中的 "
                f"`{key}`——说明 shared_types._clamp_int / _clamp_float 工厂"
                "签名变了，本测试需要先更新 introspection 逻辑",
            )

    def test_http_timeout_matches_pydantic(self) -> None:
        """``WebUIConfig.TIMEOUT_MIN/MAX`` ↔ ``SECTION_MODELS::web_ui.http_request_timeout``"""
        py_min, py_max = self.web_ui_bounds["http_request_timeout"]
        self.assertEqual(
            (WebUIConfig.TIMEOUT_MIN, WebUIConfig.TIMEOUT_MAX),
            (py_min, py_max),
            f"WebUIConfig.TIMEOUT_MIN/MAX = "
            f"({WebUIConfig.TIMEOUT_MIN}, {WebUIConfig.TIMEOUT_MAX}) "
            f"but shared_types.SECTION_MODELS::web_ui.http_request_timeout "
            f"clamps to ({py_min}, {py_max}). "
            f"Update server_config.py WebUIConfig.ClassVar OR shared_types.py "
            f"_clamp_int(...) bounds so they stay in lockstep.",
        )

    def test_http_max_retries_matches_pydantic(self) -> None:
        """``WebUIConfig.MAX_RETRIES_MIN/MAX`` ↔ ``SECTION_MODELS::web_ui.http_max_retries``"""
        py_min, py_max = self.web_ui_bounds["http_max_retries"]
        self.assertEqual(
            (WebUIConfig.MAX_RETRIES_MIN, WebUIConfig.MAX_RETRIES_MAX),
            (py_min, py_max),
            f"WebUIConfig.MAX_RETRIES_MIN/MAX = "
            f"({WebUIConfig.MAX_RETRIES_MIN}, {WebUIConfig.MAX_RETRIES_MAX}) "
            f"but shared_types.SECTION_MODELS::web_ui.http_max_retries "
            f"clamps to ({py_min}, {py_max}). "
            f"Update server_config.py WebUIConfig.ClassVar OR shared_types.py "
            f"_clamp_int(...) bounds so they stay in lockstep.",
        )

    def test_http_retry_delay_matches_pydantic(self) -> None:
        """``WebUIConfig.RETRY_DELAY_MIN/MAX`` ↔ ``SECTION_MODELS::web_ui.http_retry_delay``"""
        py_min, py_max = self.web_ui_bounds["http_retry_delay"]
        self.assertEqual(
            (WebUIConfig.RETRY_DELAY_MIN, WebUIConfig.RETRY_DELAY_MAX),
            (py_min, py_max),
            f"WebUIConfig.RETRY_DELAY_MIN/MAX = "
            f"({WebUIConfig.RETRY_DELAY_MIN}, {WebUIConfig.RETRY_DELAY_MAX}) "
            f"but shared_types.SECTION_MODELS::web_ui.http_retry_delay "
            f"clamps to ({py_min}, {py_max}). "
            f"Update server_config.py WebUIConfig.ClassVar OR shared_types.py "
            f"_clamp_float(...) bounds so they stay in lockstep.",
        )


if __name__ == "__main__":
    unittest.main()
