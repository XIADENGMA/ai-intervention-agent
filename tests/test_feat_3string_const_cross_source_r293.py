"""R293 invariant: 3 个 string const 第三轮 cross-source audit (R292 配套 lock)。

背景
----
cycle-28 R292 锁了 3 个 numeric const，R293 把同轮的 string const 一并 lock。
**string const drift 比 numeric 更隐蔽** —— 因为：

- 没有 ``ValueError`` 让 Python startup crash
- ``"default"`` 多一个字符 ``"defaullt"`` (typo) 可能让 fallback 静默失败
- URL template 多一个 ``/`` 影响所有 Bark 通知点击行为

R293 锁定 3 个 string const，覆盖 **12 source sites** (3+5+4):

1. **``web_icon = "default"``** (3 source):
   - ``shared_types.NotificationSectionConfig.web_icon`` Pydantic
   - ``notification_manager.NotificationConfig.web_icon`` class default
   - ``config.toml.default``

2. **``bark_action = "none"``** (5 source):
   - ``shared_types.NotificationSectionConfig.bark_action`` Pydantic
   - ``notification_manager.NotificationConfig.bark_action`` class default
   - ``validate_bark_action`` validator: ``validate_enum_value(..., "none")``
   - ``web_ui_routes/notification.py``: ``data.get("bark_action", "none")``
   - ``config.toml.default``: ``bark_action = "none"``

3. **``bark_url_template = "{base_url}/?task_id={task_id}"``** (4 source):
   - ``shared_types.NotificationSectionConfig.bark_url_template`` Pydantic
   - ``notification_manager.NotificationConfig.bark_url_template`` class default
   - ``web_ui_routes/notification.py``: ``data.get("bark_url_template", ...)``
   - ``config.toml.default``: ``bark_url_template = "{base_url}/?task_id={task_id}"``

R290 (4 numeric) + R292 (3 numeric) + R293 (3 string) = 10 const total
locked, 37 + 12 = 49 source sites cumulative。
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC = REPO_ROOT / "src" / "ai_intervention_agent"
SHARED_TYPES = SRC / "shared_types.py"
NOTIFICATION_MANAGER = SRC / "notification_manager.py"
NOTIFICATION_ROUTES = SRC / "web_ui_routes" / "notification.py"
CONFIG_TOML_DEFAULT = REPO_ROOT / "config.toml.default"

DEFAULT_BARK_URL_TEMPLATE = '"{base_url}/?task_id={task_id}"'


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


class TestWebIcon3Source(unittest.TestCase):
    """``web_icon = "default"`` 必须在 3 个 source 保持一致。"""

    EXPECTED = '"default"'

    def test_shared_types_pydantic_default(self) -> None:
        src = _read(SHARED_TYPES)
        self.assertRegex(
            src,
            r'web_icon\s*:\s*SafeStr\s*=\s*"default"',
            "shared_types.NotificationSectionConfig.web_icon Pydantic = 'default'",
        )

    def test_notification_manager_class_default(self) -> None:
        src = _read(NOTIFICATION_MANAGER)
        self.assertRegex(
            src,
            r'web_icon\s*:\s*str\s*=\s*"default"',
            "NotificationConfig.web_icon class default must = 'default'",
        )

    def test_config_toml_default(self) -> None:
        src = _read(CONFIG_TOML_DEFAULT)
        match = re.search(r'^web_icon\s*=\s*"default"', src, re.MULTILINE)
        self.assertIsNotNone(match, "config.toml.default web_icon must = 'default'")


class TestBarkAction5Source(unittest.TestCase):
    """``bark_action = "none"`` 必须在 5 个 source 保持一致。"""

    EXPECTED = '"none"'

    def test_shared_types_pydantic_default(self) -> None:
        src = _read(SHARED_TYPES)
        self.assertRegex(
            src,
            r'bark_action\s*:\s*SafeStr\s*=\s*"none"',
            "shared_types.NotificationSectionConfig.bark_action Pydantic = 'none'",
        )

    def test_notification_manager_class_default(self) -> None:
        src = _read(NOTIFICATION_MANAGER)
        self.assertRegex(
            src,
            r'bark_action\s*:\s*str\s*=\s*"none"',
            "NotificationConfig.bark_action class default must = 'none'",
        )

    def test_validate_bark_action_fallback_none(self) -> None:
        """``validate_bark_action`` 必须用 ``validate_enum_value(..., 'none')`` 兜底。"""
        src = _read(NOTIFICATION_MANAGER)
        self.assertRegex(
            src,
            r'validate_enum_value\([^,]+,\s*cls\.BARK_ACTIONS_VALID\s*,\s*"bark_action"\s*,\s*"none"\s*\)',
            "validate_bark_action 必须以 'none' fallback (validate_enum_value 第 4 参数)",
        )

    def test_routes_data_get_bark_action_fallback(self) -> None:
        """``web_ui_routes/notification.py::data.get('bark_action', 'none')`` 兜底。"""
        src = _read(NOTIFICATION_ROUTES)
        match = re.search(
            r'data\.get\(\s*"bark_action"\s*,\s*"([^"]+)"\s*\)',
            src,
        )
        self.assertIsNotNone(match, "找不到 data.get('bark_action', ...) fallback")
        assert match is not None
        self.assertEqual(
            match.group(1),
            "none",
            f"data.get fallback = {match.group(1)!r}, 应该 = 'none'",
        )

    def test_config_toml_default(self) -> None:
        src = _read(CONFIG_TOML_DEFAULT)
        match = re.search(r'^bark_action\s*=\s*"none"', src, re.MULTILINE)
        self.assertIsNotNone(match, "config.toml.default bark_action must = 'none'")


class TestBarkUrlTemplate4Source(unittest.TestCase):
    """``bark_url_template = "{base_url}/?task_id={task_id}"`` 4 source 一致。"""

    EXPECTED_TEMPLATE = "{base_url}/?task_id={task_id}"

    def test_shared_types_pydantic_default(self) -> None:
        src = _read(SHARED_TYPES)
        self.assertRegex(
            src,
            r'bark_url_template\s*:\s*SafeStr\s*=\s*"\{base_url\}/\?task_id=\{task_id\}"',
            "shared_types Pydantic bark_url_template must = '{base_url}/?task_id={task_id}'",
        )

    def test_notification_manager_class_default(self) -> None:
        src = _read(NOTIFICATION_MANAGER)
        self.assertRegex(
            src,
            r'bark_url_template\s*:\s*str\s*=\s*"\{base_url\}/\?task_id=\{task_id\}"',
            "NotificationConfig.bark_url_template class default must match template",
        )

    def test_routes_data_get_fallback_template(self) -> None:
        """``web_ui_routes/notification.py::data.get('bark_url_template', ...)`` fallback。"""
        src = _read(NOTIFICATION_ROUTES)
        match = re.search(
            r'data\.get\(\s*"bark_url_template"\s*,\s*"([^"]+)"\s*\)',
            src,
        )
        self.assertIsNotNone(match)
        assert match is not None
        self.assertEqual(
            match.group(1),
            self.EXPECTED_TEMPLATE,
            f"data.get fallback template drift: {match.group(1)!r}",
        )

    def test_config_toml_default(self) -> None:
        src = _read(CONFIG_TOML_DEFAULT)
        # config.toml.default 的 ``bark_url_template = "..."`` 必须包含 placeholder
        match = re.search(
            r'^bark_url_template\s*=\s*"\{base_url\}/\?task_id=\{task_id\}"',
            src,
            re.MULTILINE,
        )
        self.assertIsNotNone(
            match,
            "config.toml.default bark_url_template 必须 = '{base_url}/?task_id={task_id}'",
        )


class TestR292R293LineageDocumented(unittest.TestCase):
    """meta-doc: R293 docstring 必须 reference R290 + R292 lineage，并显式列
    cumulative const count (10) 和 source count (49)。"""

    def test_docstring_mentions_3_consts(self) -> None:
        src = _read(Path(__file__))
        for const in ["web_icon", "bark_action", "bark_url_template"]:
            self.assertIn(const, src, f"R293 docstring must list `{const}`")

    def test_docstring_mentions_r290_r292(self) -> None:
        src = _read(Path(__file__))
        for anchor in ["R290", "R292"]:
            self.assertIn(anchor, src, f"R293 docstring must reference {anchor}")

    def test_docstring_lists_cumulative_metric(self) -> None:
        """必须显式列出 cumulative const count (10) 和 source count (49)。"""
        src = _read(Path(__file__))
        # 含 "10 const" 或 "10 const total"
        self.assertRegex(
            src,
            r"10\s+const",
            "R293 docstring 必须列 cumulative const count = 10",
        )
        self.assertRegex(
            src,
            r"49\s+source",
            "R293 docstring 必须列 cumulative source count = 49",
        )


if __name__ == "__main__":
    unittest.main()
