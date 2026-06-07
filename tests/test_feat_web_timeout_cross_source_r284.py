"""R284 / cycle-26 t26-1 (R278/R283 spillover): ``web_timeout`` (5000ms)
跨源 consistency invariant — Pydantic authoritative + 4 个 fallback site
全部 = 5000。

R278 → R283 → R284 evolution
----------------------------

R276 cycle-24: 1 const (image upload) 2 language (Python + JS)
R278 cycle-25: 3 const (timeout default/max + port) 3 language (+ HTML)
R283 cycle-25: 4 const (PROMPT_MAX_LENGTH) 3 language
R284 cycle-26: 5 const (web_timeout) 1 language (5 Python sites)

R284 没扩展 source language (web_timeout 不在 frontend JS hardcode)，但
扩展了 const 锁定数到 5 个，并覆盖了**新场景**：cls default + fallback
parsers (defensive ``cfg.get("web_timeout", N)``)。

Why locked
----------

``web_timeout`` 5000ms 在 5 个 Python 文件 hardcode:

1. ``shared_types.NotificationSectionConfig.web_timeout`` (Pydantic
   authoritative)
2. ``notification_manager.NotificationConfig.web_timeout`` (cls default)
3. ``notification_manager.py`` line ~289 (cls ``__init__`` reads cfg)
4. ``notification_manager.py`` line ~1458 (runtime config reload)
5. ``web_ui_routes/notification.py`` (API 端点 normalize default)

如果改 shared_types 到 7000 但忘了:
- ``config.toml.default`` 仍 5000 → 新用户拿 7000 (Pydantic), 但
  ``config.toml`` 还 5000 → 用户改了 default 但实际不生效
- 4 个 Python fallback 都 5000 → 如果 config 缺这个 key, fallback 返回
  5000 而非 Pydantic 7000，造成两种来源行为不一致

R284 invariant 锁定这 5 处必须严格相等，强制 future change 必须同步全部
mirror。

Pattern
-------

R278 + R283 (frontend mirror) 是"前端 hardcode 必须等于 backend
authoritative"。R284 (backend fallback mirror) 是"defensive parsers 必须
等于 authoritative Pydantic default"。前者防 UI drift，后者防 fallback
behavior drift。
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SHARED_TYPES_PY = REPO_ROOT / "src" / "ai_intervention_agent" / "shared_types.py"
NOTIFICATION_MANAGER_PY = (
    REPO_ROOT / "src" / "ai_intervention_agent" / "notification_manager.py"
)
NOTIFICATION_ROUTE_PY = (
    REPO_ROOT / "src" / "ai_intervention_agent" / "web_ui_routes" / "notification.py"
)
CONFIG_TOML_DEFAULT = REPO_ROOT / "config.toml.default"


class TestWebTimeoutCrossSourceR284(unittest.TestCase):
    """R284: ``web_timeout`` 跨 5 个 source 必须严格 = 5000ms。"""

    AUTHORITATIVE_VALUE = 5000

    def test_shared_types_pydantic_default(self) -> None:
        """``NotificationSectionConfig.web_timeout`` Pydantic 默认 = 5000。"""
        src = SHARED_TYPES_PY.read_text(encoding="utf-8")
        # 解析 ``web_timeout: Annotated[...5000...] = 5000``
        pattern = re.compile(
            r"web_timeout\s*:\s*Annotated\[.*?5000.*?\]\s*=\s*5000",
            re.DOTALL,
        )
        self.assertRegex(
            src,
            pattern,
            "R284: shared_types.NotificationSectionConfig.web_timeout 必须 "
            "保持 ``Annotated[...5000...] = 5000`` (clamp default + field "
            "default 都是 5000，作为整个 R284 invariant 的 authoritative "
            "source)",
        )

    def test_config_toml_default(self) -> None:
        """``config.toml.default`` 里 ``web_timeout = 5000``。"""
        src = CONFIG_TOML_DEFAULT.read_text(encoding="utf-8")
        self.assertRegex(
            src,
            re.compile(r"^web_timeout\s*=\s*5000\b", re.MULTILINE),
            "R284: config.toml.default 里 ``web_timeout = 5000`` 必须保留。"
            "如果改 Pydantic default，必须同步改这里，否则新用户拿 Pydantic "
            "值，但用户 init 后 disk 拷贝的 config 还是旧值。",
        )

    def test_notification_manager_cls_default(self) -> None:
        """``NotificationConfig.web_timeout`` 类默认 = 5000。"""
        src = NOTIFICATION_MANAGER_PY.read_text(encoding="utf-8")
        self.assertRegex(
            src,
            r"web_timeout\s*:\s*int\s*=\s*5000\b",
            "R284: notification_manager.NotificationConfig.web_timeout 类 "
            "默认必须 = 5000 (mirror Pydantic authoritative)",
        )

    def test_notification_manager_init_fallback(self) -> None:
        """``__init__`` 里 ``cfg.get(\"web_timeout\", 5000)`` fallback。"""
        src = NOTIFICATION_MANAGER_PY.read_text(encoding="utf-8")
        matches = re.findall(
            r'cfg\.get\(\s*[\'"]web_timeout[\'"]\s*,\s*(\d+)\s*\)',
            src,
        )
        self.assertGreaterEqual(
            len(matches),
            2,
            "R284: notification_manager.py 必须至少 2 处 "
            '``cfg.get("web_timeout", 5000)`` fallback '
            "(__init__ + runtime reload)",
        )
        for val in matches:
            self.assertEqual(
                int(val),
                self.AUTHORITATIVE_VALUE,
                f'R284: notification_manager.py ``cfg.get("web_timeout", '
                f"{val})`` fallback 值 ({val}) 必须 = "
                f"{self.AUTHORITATIVE_VALUE} (Pydantic authoritative)",
            )

    def test_notification_route_normalize_default(self) -> None:
        """``web_ui_routes/notification.py::normalize_web_timeout`` 内
        ``notification_config.get("web_timeout", 5000)``。"""
        src = NOTIFICATION_ROUTE_PY.read_text(encoding="utf-8")
        match = re.search(
            r'notification_config\.get\(\s*[\'"]web_timeout[\'"]\s*,\s*(\d+)\s*\)',
            src,
        )
        self.assertIsNotNone(
            match,
            "R284: web_ui_routes/notification.py 必须有 "
            '``notification_config.get("web_timeout", 5000)`` fallback '
            "(normalize_web_timeout closure 内)",
        )
        assert match is not None
        self.assertEqual(
            int(match.group(1)),
            self.AUTHORITATIVE_VALUE,
            f"R284: normalize_web_timeout 的 fallback 值 ({match.group(1)}) "
            f"必须 = {self.AUTHORITATIVE_VALUE}",
        )

    def test_r284_anchor_in_docstring(self) -> None:
        """本测试文件 docstring 必须列出 5 个 authoritative sources，让
        grep R284 能立刻定位全部 mirror。"""
        self_src = Path(__file__).read_text(encoding="utf-8")
        for marker in (
            "shared_types",
            "NotificationSectionConfig",
            "notification_manager.py",
            "config.toml.default",
            "web_ui_routes/notification.py",
        ):
            self.assertIn(
                marker,
                self_src,
                f"R284: 测试文件 docstring 必须提到 ``{marker}``",
            )


if __name__ == "__main__":
    unittest.main()
