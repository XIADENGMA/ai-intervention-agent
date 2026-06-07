"""cycle-10 bonus / R253 — cross-tab theme sync regression tests.

Tab A 用户点切换主题 → ``localStorage.setItem('theme-preference',
...)`` → 其他 tab 收到 ``storage`` event → 自动 applyTheme，
**无需 reload**。

确保 ``theme.js`` ``init`` 注册了 storage listener 且：
  1. 只响应 ``theme-preference`` key 的事件;
  2. 验证 newValue 合法（dark / light / auto）;
  3. 同主题 short-circuit 避免重复 apply（idempotency）;
  4. try/catch 兜底（极旧浏览器不支持 storage event）;
  5. 不污染 anti-FOUC inline script（仍走 ``theme-preference`` 同名 key）;
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_THEME_JS = _REPO_ROOT / "src" / "ai_intervention_agent" / "static" / "js" / "theme.js"
_WEB_UI_HTML = (
    _REPO_ROOT / "src" / "ai_intervention_agent" / "templates" / "web_ui.html"
)


class TestCrossTabSync(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.theme_js = _THEME_JS.read_text(encoding="utf-8")
        cls.web_ui = _WEB_UI_HTML.read_text(encoding="utf-8")

    # ---------------------------------------------------------------
    # 1. storage listener present in init
    # ---------------------------------------------------------------
    def test_storage_listener_registered(self) -> None:
        m = re.search(
            r"init:\s*function\s*\([^\)]*\)\s*\{(.*?)^\s*\},",
            self.theme_js,
            re.DOTALL | re.MULTILINE,
        )
        assert m is not None
        init_body = m.group(1)
        self.assertIn(
            "addEventListener('storage'",
            init_body,
            "init 必须为 cross-tab sync 注册 'storage' event listener",
        )

    # ---------------------------------------------------------------
    # 2. key gate — 只响应 STORAGE_KEY
    # ---------------------------------------------------------------
    def test_handler_filters_by_storage_key(self) -> None:
        m = self._storage_handler_block()
        # 过滤其他 key，只处理 STORAGE_KEY
        self.assertIn("event.key !== STORAGE_KEY", m)

    # ---------------------------------------------------------------
    # 3. 验证 newValue 合法性
    # ---------------------------------------------------------------
    def test_handler_validates_new_value(self) -> None:
        m = self._storage_handler_block()
        self.assertIn("Object.values(THEMES).includes(newTheme)", m)

    # ---------------------------------------------------------------
    # 4. idempotency short-circuit
    # ---------------------------------------------------------------
    def test_handler_skips_same_theme(self) -> None:
        m = self._storage_handler_block()
        self.assertIn("newTheme === currentTheme", m)

    # ---------------------------------------------------------------
    # 5. try/catch 兜底
    # ---------------------------------------------------------------
    def test_handler_wrapped_in_try_catch(self) -> None:
        # 整个 storage listener 注册必须包在 try/catch 里
        m = re.search(
            r"try\s*\{\s*window\.addEventListener\('storage'.*?\}\s*catch\s*\(",
            self.theme_js,
            re.DOTALL,
        )
        self.assertIsNotNone(
            m,
            "storage listener 注册必须包在 try/catch 兜底极旧浏览器",
        )

    # ---------------------------------------------------------------
    # 6. 与 anti-FOUC inline script 共用 storage key
    # ---------------------------------------------------------------
    def test_uses_same_storage_key_as_anti_fouc(self) -> None:
        # anti-FOUC inline 用 "theme-preference" (双引号；inline script
        # 中)；theme.js STORAGE_KEY 用 'theme-preference'（单引号；常量）。
        # 都是同字面量 → cross-tab sync 与 anti-FOUC 共用同 key 是关键。
        self.assertIn('"theme-preference"', self.web_ui)
        self.assertIn("'theme-preference'", self.theme_js)

    # ---------------------------------------------------------------
    # 7. handler 调用 applyTheme + updateToggleButton
    # ---------------------------------------------------------------
    def test_handler_applies_theme_and_updates_button(self) -> None:
        m = self._storage_handler_block()
        self.assertIn("applyTheme(newTheme)", m)
        self.assertIn("updateToggleButton()", m)

    # ---------------------------------------------------------------
    # helpers
    # ---------------------------------------------------------------
    def _storage_handler_block(self) -> str:
        m = re.search(
            r"window\.addEventListener\('storage',\s*function\s*\([^)]*\)\s*\{.*?\}\s*\)\s*;",
            self.theme_js,
            re.DOTALL,
        )
        assert m is not None, "storage event handler 块缺失"
        return m.group(0)


if __name__ == "__main__":
    unittest.main()
