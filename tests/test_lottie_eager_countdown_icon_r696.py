"""R696 回归护栏：空态 Lottie 直出 + 倒计时条主题化图标。

背景（用户反馈驱动的两处 UI 修正）：

1. **Lottie 直出**：旧流程首屏先渲染零依赖 SVG 降级动画，等
   「视口可见 + load 事件 + 500ms + idle」四道门后才加载 lottie 运行时
   再热切换——两套动画风格不同，切换过程肉眼可见且不流畅。R696 改为
   lottie.min.js 随首屏 ``<script defer>`` 预加载（排在 app.js 之前，
   defer 按文档顺序执行），``initHourglassAnimation`` 直接创建 Lottie
   动画；SVG 降级仅保留 lottie 运行时加载失败一个场景（R704 起
   prefers-reduced-motion 不再降级，改为加载 Lottie 后静止到完整帧，
   详见 test_lottie_reduced_motion_rest_frame_r704.py）。
2. **倒计时条图标**：``.countdown-label`` 从 ⏰ emoji 改为
   stroke:currentColor 的内联 SVG 时钟，颜色随主题（暗色琥珀 /
   浅色深陶土橙），与页面风格一致。

本文件锁定上述契约，防止未来重构倒退回「降级动画热切换」或 emoji。
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
APP_JS = REPO_ROOT / "src" / "ai_intervention_agent" / "static" / "js" / "app.js"
TEMPLATE = REPO_ROOT / "src" / "ai_intervention_agent" / "templates" / "web_ui.html"
CSS_PATH = REPO_ROOT / "src" / "ai_intervention_agent" / "static" / "css" / "main.css"


def _function_body(source: str, name: str) -> str:
    match = re.search(rf"function\s+{name}\s*\([^)]*\)\s*\{{", source)
    assert match is not None, f"missing function {name}"
    depth = 0
    for idx in range(match.end() - 1, len(source)):
        char = source[idx]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return source[match.end() : idx]
    raise AssertionError(f"could not parse body for {name}")


class TestLottieRuntimeEagerlyLoaded(unittest.TestCase):
    """lottie.min.js 必须随首屏 defer 预加载，且排在 app.js 之前。"""

    def setUp(self) -> None:
        self.template = TEMPLATE.read_text(encoding="utf-8")

    def test_template_has_defer_lottie_script(self) -> None:
        self.assertIn(
            'src="/static/js/lottie.min.js?v={{ lottie_min_version }}"',
            self.template,
        )

    def test_lottie_script_precedes_app_js(self) -> None:
        lottie_idx = self.template.find(
            'src="/static/js/lottie.min.js?v={{ lottie_min_version }}"'
        )
        app_idx = self.template.find('src="/static/js/app.js?v={{ app_version }}"')
        self.assertGreater(lottie_idx, 0)
        self.assertGreater(app_idx, 0)
        self.assertLess(
            lottie_idx,
            app_idx,
            "defer 按文档顺序执行：lottie 运行时必须排在 app.js 之前，"
            "否则 initHourglassAnimation 首跑时 lottie 全局不存在",
        )

    def test_dynamic_loader_fallback_url_kept(self) -> None:
        """AIIA_LOTTIE_JS_URL 动态加载兜底（defer 标签失败时）保留。"""
        app = APP_JS.read_text(encoding="utf-8")
        self.assertIn("window.AIIA_LOTTIE_JS_URL", app)
        self.assertIn(
            'window.AIIA_LOTTIE_JS_URL = "/static/js/lottie.min.js?v={{ lottie_min_version }}";',
            self.template,
        )


class TestInitCreatesLottieDirectly(unittest.TestCase):
    """initHourglassAnimation 不得先渲染降级动画再热切换。"""

    def setUp(self) -> None:
        self.body = _function_body(
            APP_JS.read_text(encoding="utf-8"), "initHourglassAnimation"
        )

    def test_no_visibility_idle_gates(self) -> None:
        self.assertNotIn("IntersectionObserver", self.body)
        self.assertNotIn("requestIdleCallback", self.body)

    def test_fallback_only_for_load_failure(self) -> None:
        # 降级渲染仅出现在 !ok（运行时加载失败）分支——不允许回到
        # 「先降级后切换」的旧流程，也不允许恢复 R704 移除的
        # prefers-reduced-motion 提前降级分支。
        occurrences = self.body.count("renderSproutFallback(container)")
        self.assertEqual(
            occurrences,
            1,
            "renderSproutFallback 应恰好出现 1 次（仅运行时加载失败）",
        )
        self.assertNotIn(
            "prefers-reduced-motion: reduce",
            self.body,
            "R704：reduced-motion 不再提前降级，偏好判断移入 "
            "_createLottieAnimation（autoplay）与 DOMLoaded（静止帧）",
        )
        self.assertIn("_installReducedMotionWatcher()", self.body)
        self.assertIn("_ensureLottieLoaded().then", self.body)
        self.assertIn("_createLottieAnimation(container, token)", self.body)

    def test_lifecycle_handlers_kept(self) -> None:
        source = APP_JS.read_text(encoding="utf-8")
        self.assertIn('window.addEventListener("pagehide"', source)
        self.assertIn('window.addEventListener("pageshow"', source)
        self.assertIn('document.addEventListener("visibilitychange"', source)
        self.assertIn("disposeHourglassAnimationLifecycle", source)


class TestCountdownLabelIsThemedSvg(unittest.TestCase):
    """倒计时条图标：内联 SVG（currentColor），禁止 emoji。"""

    def setUp(self) -> None:
        self.template = TEMPLATE.read_text(encoding="utf-8")
        self.css = CSS_PATH.read_text(encoding="utf-8")

    def test_no_alarm_clock_emoji(self) -> None:
        self.assertNotIn("⏰", self.template)

    def test_label_contains_current_color_svg(self) -> None:
        idx = self.template.find('class="countdown-label"')
        self.assertGreater(idx, 0)
        snippet = self.template[idx : idx + 900]
        self.assertIn("<svg", snippet)
        self.assertIn('stroke="currentColor"', snippet)
        self.assertIn('aria-hidden="true"', snippet)

    def test_label_color_follows_theme_tokens(self) -> None:
        """R698：倒计时行降级为 quiet 元信息，图标随次要文字色令牌。"""
        match = re.search(r"\.countdown-label\s*\{([^}]*)\}", self.css)
        self.assertIsNotNone(match)
        assert match is not None
        self.assertIn("--text-secondary", match.group(1))
        self.assertIn(
            '[data-theme="light"] .countdown-label',
            self.css,
            "浅色主题必须有 countdown-label 覆盖（quiet 次要文字色）",
        )


if __name__ == "__main__":
    unittest.main()
