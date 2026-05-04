r"""防回归：``server_config.py`` 的 ``*_DEFAULT`` 常量 = ``shared_types.SECTION_MODELS::feedback`` 各字段的 Pydantic ``default`` 值。

历史背景
---------
``tests/test_server_config_shared_types_parity.py`` 已经锁住「MIN/MAX
钳位边界」的两层一致性（``server_config`` ↔ ``SECTION_MODELS``）。
但**默认值**这条平行 invariant 之前没有测试守住：

    server_config.FEEDBACK_TIMEOUT_DEFAULT  ←→  SECTION_MODELS::feedback.backend_max_wait    (default)
    server_config.AUTO_RESUBMIT_TIMEOUT_DEFAULT ←→ SECTION_MODELS::feedback.frontend_countdown (default)
    server_config.RESUBMIT_PROMPT_DEFAULT   ←→  SECTION_MODELS::feedback.resubmit_prompt    (default)
    server_config.PROMPT_SUFFIX_DEFAULT     ←→  SECTION_MODELS::feedback.prompt_suffix      (default)

如果任何一边改了默认值另一边没跟上：

  - 用户首次 load config 时拿到 SECTION_MODELS 默认（A）；
  - ``POST /api/reset-feedback-config`` 把它写回 server_config DEFAULT（B）。
  - A ≠ B 时 reset 按钮的语义就和「首次 load」不一致 —— 用户点 reset
    后看到一个不是「初始默认」的值。这是 silent 行为漂移。

设计原则
--------
- **Introspection 而非硬编码**：通过 ``model_fields[name].default`` 直接
  从 Pydantic 字段反推默认值，避免和「重新写一遍预期数字」造成新的
  漂移面。
- 与 ``test_server_config_shared_types_parity.py`` 形成互补：那一份
  锁 (min, max) 钳位边界，本份锁默认值；两层加起来把
  ``server_config`` 顶部的 6 个 feedback 常量全部锁定到
  ``SECTION_MODELS::feedback``。
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from server_config import (
    AUTO_RESUBMIT_TIMEOUT_DEFAULT,
    FEEDBACK_TIMEOUT_DEFAULT,
    PROMPT_SUFFIX_DEFAULT,
    RESUBMIT_PROMPT_DEFAULT,
)
from shared_types import SECTION_MODELS


class TestServerConfigDefaultsParity(unittest.TestCase):
    """``server_config`` 的 4 个 ``*_DEFAULT`` 常量必须 = ``SECTION_MODELS::feedback`` 各字段的 ``default`` 值。"""

    def setUp(self) -> None:
        feedback_model = SECTION_MODELS["feedback"]
        self.field_defaults: dict[str, object] = {
            name: info.default for name, info in feedback_model.model_fields.items()
        }
        # Sanity check：4 个字段的 default 都不是 PydanticUndefined（Pydantic
        # 用这个特殊哨兵值表示「无默认值」）；不存在则说明字段的声明方式变了
        for key in (
            "backend_max_wait",
            "frontend_countdown",
            "resubmit_prompt",
            "prompt_suffix",
        ):
            self.assertIn(
                key,
                self.field_defaults,
                f"SECTION_MODELS::feedback.{key} 字段不存在 —— 模型重构了，"
                "测试需要先随之更新",
            )

    def test_backend_max_wait_default(self) -> None:
        """``FEEDBACK_TIMEOUT_DEFAULT`` ↔ ``SECTION_MODELS::feedback.backend_max_wait``"""
        self.assertEqual(
            FEEDBACK_TIMEOUT_DEFAULT,
            self.field_defaults["backend_max_wait"],
            f"server_config.FEEDBACK_TIMEOUT_DEFAULT={FEEDBACK_TIMEOUT_DEFAULT} "
            f"but SECTION_MODELS::feedback.backend_max_wait default="
            f"{self.field_defaults['backend_max_wait']}. "
            "POST /api/reset-feedback-config writes the former; first-time "
            "config load returns the latter — they MUST agree.",
        )

    def test_frontend_countdown_default(self) -> None:
        """``AUTO_RESUBMIT_TIMEOUT_DEFAULT`` ↔ ``SECTION_MODELS::feedback.frontend_countdown``"""
        self.assertEqual(
            AUTO_RESUBMIT_TIMEOUT_DEFAULT,
            self.field_defaults["frontend_countdown"],
            f"server_config.AUTO_RESUBMIT_TIMEOUT_DEFAULT="
            f"{AUTO_RESUBMIT_TIMEOUT_DEFAULT} but "
            f"SECTION_MODELS::feedback.frontend_countdown default="
            f"{self.field_defaults['frontend_countdown']}.",
        )

    def test_resubmit_prompt_default(self) -> None:
        """``RESUBMIT_PROMPT_DEFAULT`` ↔ ``SECTION_MODELS::feedback.resubmit_prompt``"""
        self.assertEqual(
            RESUBMIT_PROMPT_DEFAULT,
            self.field_defaults["resubmit_prompt"],
            f"server_config.RESUBMIT_PROMPT_DEFAULT={RESUBMIT_PROMPT_DEFAULT!r} "
            f"but SECTION_MODELS::feedback.resubmit_prompt default="
            f"{self.field_defaults['resubmit_prompt']!r}.",
        )

    def test_prompt_suffix_default(self) -> None:
        """``PROMPT_SUFFIX_DEFAULT`` ↔ ``SECTION_MODELS::feedback.prompt_suffix``"""
        self.assertEqual(
            PROMPT_SUFFIX_DEFAULT,
            self.field_defaults["prompt_suffix"],
            f"server_config.PROMPT_SUFFIX_DEFAULT={PROMPT_SUFFIX_DEFAULT!r} "
            f"but SECTION_MODELS::feedback.prompt_suffix default="
            f"{self.field_defaults['prompt_suffix']!r}.",
        )


if __name__ == "__main__":
    unittest.main()
