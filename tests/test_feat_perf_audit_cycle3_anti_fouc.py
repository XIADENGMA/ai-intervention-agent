"""perf-audit-cycle-3 §2.2 / R250 — Anti-FOUC theme bootstrap regression.

防止后续重构破坏 anti-FOUC inline ``<script>``：
  1. 该 inline script **必须存在** 于 ``<head>``;
  2. 必须出现在所有 ``<link rel="preload" as="script">`` 之前
     （否则 preload 调度的 script 可能比 inline script 更早开始 paint）；
  3. 必须读取与 ``theme.js`` 相同的 ``theme-preference`` localStorage 键;
  4. 必须处理 ``"auto"`` 与 ``null`` 走 ``matchMedia('(prefers-color-scheme:
     light)')`` fallback;
  5. 必须用 try/catch 兜底（隐私模式 / iframe sandbox 下 localStorage 抛错）;
  6. 必须保留 CSP nonce 占位符 ``nonce="{{ csp_nonce }}"``。
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_TEMPLATE = _REPO_ROOT / "src" / "ai_intervention_agent" / "templates" / "web_ui.html"
_THEME_JS = _REPO_ROOT / "src" / "ai_intervention_agent" / "static" / "js" / "theme.js"


class TestAntiFoucBootstrap(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.html = _TEMPLATE.read_text(encoding="utf-8")
        cls.theme_js = _THEME_JS.read_text(encoding="utf-8")

    # ------------------------------------------------------------------
    # 1. 存在性
    # ------------------------------------------------------------------
    def test_inline_script_present(self) -> None:
        self.assertIn(
            "antiFoucThemeBootstrap",
            self.html,
            "anti-FOUC IIFE 函数名缺失",
        )

    def test_inline_script_inside_head(self) -> None:
        head_end = self.html.find("</head>")
        idx = self.html.find("antiFoucThemeBootstrap")
        self.assertGreater(idx, -1)
        self.assertLess(idx, head_end, "anti-FOUC 必须在 </head> 之前")

    # ------------------------------------------------------------------
    # 2. 顺序
    # ------------------------------------------------------------------
    def test_runs_before_preload_scripts(self) -> None:
        fouc_idx = self.html.find("antiFoucThemeBootstrap")
        first_preload = self.html.find('rel="preload"')
        self.assertGreater(fouc_idx, -1)
        self.assertGreater(first_preload, -1)
        self.assertLess(
            fouc_idx,
            first_preload,
            "anti-FOUC inline script 必须出现在第一个 preload link 之前",
        )

    def test_runs_after_redirect_zero_host(self) -> None:
        # 0.0.0.0 redirect 优先级最高（可能直接 location.replace 跳走），
        # 不需要给 anti-FOUC 让位（redirect 触发时整页都不会渲染）。
        redirect_idx = self.html.find("redirectZeroHostToLoopback")
        fouc_idx = self.html.find("antiFoucThemeBootstrap")
        self.assertGreater(redirect_idx, -1)
        self.assertGreater(fouc_idx, redirect_idx)

    # ------------------------------------------------------------------
    # 3. storage key 同步
    # ------------------------------------------------------------------
    def test_uses_same_storage_key_as_theme_js(self) -> None:
        # theme.js 用 STORAGE_KEY = 'theme-preference'
        self.assertIn("'theme-preference'", self.theme_js)
        # anti-FOUC inline 必须用同名（双引号或单引号都允许）
        m = re.search(
            r'localStorage\.getItem\(["\']theme-preference["\']\)',
            self.html,
        )
        self.assertIsNotNone(
            m,
            "anti-FOUC 必须 getItem('theme-preference') 与 theme.js 一致",
        )

    # ------------------------------------------------------------------
    # 4. auto fallback to matchMedia
    # ------------------------------------------------------------------
    def test_handles_auto_with_match_media(self) -> None:
        # IIFE 必须含 matchMedia 调用
        iife = self._iife_block()
        self.assertIn("matchMedia", iife)
        self.assertIn("(prefers-color-scheme: light)", iife)
        self.assertIn('"auto"', iife)

    def test_handles_unset_storage(self) -> None:
        iife = self._iife_block()
        self.assertIn("!stored", iife, "必须处理 null/undefined")

    # ------------------------------------------------------------------
    # 5. try/catch 兜底
    # ------------------------------------------------------------------
    def test_try_catch_present(self) -> None:
        iife = self._iife_block()
        self.assertIn("try {", iife)
        self.assertIn("catch", iife)

    # ------------------------------------------------------------------
    # 6. CSP nonce
    # ------------------------------------------------------------------
    def test_csp_nonce_present(self) -> None:
        m = re.search(
            r'<script nonce="\{\{ csp_nonce \}\}">\s*\n?\s*'
            r"\(function antiFoucThemeBootstrap",
            self.html,
        )
        self.assertIsNotNone(
            m,
            'anti-FOUC <script> 必须携带 nonce="{{ csp_nonce }}"',
        )

    # ------------------------------------------------------------------
    # 7. 写入 data-theme attribute
    # ------------------------------------------------------------------
    def test_writes_data_theme_attribute(self) -> None:
        iife = self._iife_block()
        self.assertIn(
            "document.documentElement.setAttribute",
            iife,
        )
        self.assertIn('"data-theme"', iife)

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------
    def _iife_block(self) -> str:
        m = re.search(
            r"\(function antiFoucThemeBootstrap\(\) \{.*?\}\)\(\);",
            self.html,
            re.DOTALL,
        )
        assert m is not None, "anti-FOUC IIFE block 缺失"
        return m.group(0)


if __name__ == "__main__":
    unittest.main()
