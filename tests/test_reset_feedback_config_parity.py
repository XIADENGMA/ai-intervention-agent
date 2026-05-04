r"""防回归：``POST /api/reset-feedback-config`` 返回的 ``defaults`` dict 字段集 = ``shared_types.SECTION_MODELS::feedback`` 字段集。

历史背景
--------
``web_ui_routes/notification.py::reset_feedback_config`` 是 Web UI 上"重置
反馈配置为默认值"按钮调用的端点。它的契约是**重置整个 ``feedback``
section** 为 ``server_config.py`` 中定义的默认值。

历史漂移（v1.5.x 中段被发现并修复）：endpoint 的 ``defaults`` dict 只含
3 个字段——``frontend_countdown`` / ``resubmit_prompt`` / ``prompt_suffix``
——但 ``SECTION_MODELS::feedback`` 实际有 **4 个**字段（``backend_max_wait``
被漏了）。结果：用户改了 ``config.toml`` 中的 ``backend_max_wait``（或者
被以前的 bug 留下了非默认值），按下"重置"按钮后只有 3 个字段回到默认，
``backend_max_wait`` 静默保留——**partial reset**。

修复后加这个 introspection-based 回归位，把 endpoint defaults dict 字段
集与 Pydantic section model 字段集锁住——以后任何人在 ``SECTION_MODELS::
feedback`` 加字段，必须同步更新 endpoint，否则 CI 失败。

设计原则
--------
- **静态扫源码 + AST 解析**比启动 Flask app 更轻量、更稳定（不需要
  mock ``config_mgr`` / 启动 web 服务），并且 contract 本身就是 endpoint
  源码里的字面量——比从运行时响应反推更直接。
- 解析 ``reset_feedback_config`` 函数的 ``defaults = {...}`` 字面量字典，
  用 ``ast`` 模块抽出 dict 的所有 key。
- 字段集**等价**而非"包含"：endpoint 不应该有 SECTION_MODELS 没有的字段
  （那会被 Pydantic 当 ``extra="allow"`` 接住，但语义上属于隐藏字段，
  应当报错）。
"""

from __future__ import annotations

import ast
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from shared_types import SECTION_MODELS

ROUTE_FILE = REPO_ROOT / "web_ui_routes" / "notification.py"


def _extract_reset_defaults_keys() -> set[str]:
    """静态解析 ``notification.py`` 中 ``reset_feedback_config`` 的 ``defaults`` dict key。

    用 ``ast`` 而非正则——dict 字面量的 key 可以是 ``"a"`` / ``'a'`` /
    multiline 拼接，正则会有边界 case；AST 直接给出 ``Constant.value``。
    """
    tree = ast.parse(ROUTE_FILE.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "reset_feedback_config":
            for sub in ast.walk(node):
                if (
                    isinstance(sub, ast.Assign)
                    and len(sub.targets) == 1
                    and isinstance(sub.targets[0], ast.Name)
                    and sub.targets[0].id == "defaults"
                    and isinstance(sub.value, ast.Dict)
                ):
                    keys: set[str] = set()
                    for k in sub.value.keys:
                        if isinstance(k, ast.Constant) and isinstance(k.value, str):
                            keys.add(k.value)
                    return keys
    return set()


class TestResetFeedbackConfigParity(unittest.TestCase):
    """endpoint defaults dict 字段集必须 = ``SECTION_MODELS::feedback`` 字段集。"""

    def test_defaults_dict_keys_match_section_model_fields(self) -> None:
        endpoint_keys = _extract_reset_defaults_keys()
        # Sanity check：解析至少要拿到 1 个 key，否则说明 reset_feedback_config
        # 函数的 defaults 字面量赋值结构变了（比如改成 dict comprehension
        # 或拆成多个 .update(...) 调用），本测试需要先更新 AST 提取逻辑。
        self.assertGreater(
            len(endpoint_keys),
            0,
            "未能从 web_ui_routes/notification.py::reset_feedback_config "
            "中找到 `defaults = {...}` 的字面量 dict——可能函数结构被重构，"
            "本测试需要更新 _extract_reset_defaults_keys 逻辑",
        )

        feedback_model = SECTION_MODELS["feedback"]
        section_keys = set(feedback_model.model_fields.keys())

        self.assertEqual(
            endpoint_keys,
            section_keys,
            f"reset_feedback_config defaults dict keys = {sorted(endpoint_keys)} "
            f"but SECTION_MODELS::feedback fields = {sorted(section_keys)}. "
            f"\n\nMissing in endpoint (will be silently NOT reset): "
            f"{sorted(section_keys - endpoint_keys)}"
            f"\nExtra in endpoint (will pass through Pydantic extra='allow' "
            f"but is semantically a hidden field): "
            f"{sorted(endpoint_keys - section_keys)}"
            f"\n\nFix: update web_ui_routes/notification.py::reset_feedback_config "
            f"`defaults = {{...}}` to cover every field in SECTION_MODELS::feedback "
            f"(import the corresponding *_DEFAULT constant from server_config.py).",
        )


if __name__ == "__main__":
    unittest.main()
