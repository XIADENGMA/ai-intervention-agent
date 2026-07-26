"""R712 回归护栏：空态动画豁免「减弱动态效果」，照常播放。

演进史（本文件取代 test_lottie_reduced_motion_rest_frame_r704.py）：

* R696 之前：prefers-reduced-motion 被当成降级 SVG 的触发条件——
  iOS「减弱动态效果」用户永远看不到 Lottie 画面。
* R704：改为「仍加载 Lottie 但静止在完整长成帧」——画面回来了，
  但真机观感是「动画坏了/页面死了」（进度条同时被全局 reduce 规则
  压成 0.01ms 一次性结束）。
* R712（维护者真机验证后的产品决策）：空态页的两个「等待中」提示
  动画（Lottie 嫩芽 + loading 进度条）**豁免**系统偏好、照常循环——
  两者均为小幅面积装饰动画、无大幅位移/视差/闪烁，前庭风险低；
  页面其余动画（入场/过渡/骨架屏等）继续尊重 prefers-reduced-motion。

本文件锁定 R712 契约，防止未来重构把空态动画重新挂回系统偏好：

1. ``_createLottieAnimation`` 必须 ``autoplay: true``（不含偏好条件）；
2. app.js 不再残留 R704 的偏好机制（watcher / rest-frame 函数）；
3. ``error`` 处理仍须先 ``destroyHourglassAnimation()`` 再渲染降级
   SVG（残留实例会让下一次 init 提前 return，卡死在降级画面——
   该顺序契约与偏好无关，从 R704 原样继承）；
4. main.css 的全局 reduce 块必须保留 ``.no-content-progress-bar``
   豁免（animation-iteration-count: infinite）。
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
APP_JS = REPO_ROOT / "src" / "ai_intervention_agent" / "static" / "js" / "app.js"
MAIN_CSS = REPO_ROOT / "src" / "ai_intervention_agent" / "static" / "css" / "main.css"


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


class TestLottieAlwaysAutoplays(unittest.TestCase):
    """_createLottieAnimation：autoplay 恒真，不受系统偏好牵制。"""

    def setUp(self) -> None:
        self.app = APP_JS.read_text(encoding="utf-8")
        self.body = _function_body(self.app, "_createLottieAnimation")

    def test_autoplay_is_unconditionally_true(self) -> None:
        self.assertIn(
            "autoplay: true",
            self.body,
            "R712: 空态 Lottie 必须无条件 autoplay（豁免 reduced-motion）",
        )

    def test_no_preference_gate_in_autoplay(self) -> None:
        self.assertNotIn(
            "_prefersReducedMotion",
            self.body,
            "R712: autoplay 不得再挂 prefers-reduced-motion 条件",
        )

    def test_error_destroys_before_fallback(self) -> None:
        # destroy 必须发生在 renderSproutFallback 之前：残留实例会让
        # 下一次 initHourglassAnimation 直接 return；且 lottie destroy
        # 会清空容器，顺序颠倒会把刚渲染的 fallback 抹掉。
        # （从 error 监听器开始截取，跳过函数开头重建前的常规 destroy）
        error_idx = self.body.find('addEventListener("error"')
        self.assertGreater(error_idx, 0)
        error_block = self.body[error_idx:]
        destroy_idx = error_block.find("destroyHourglassAnimation()")
        fallback_idx = error_block.find("renderSproutFallback(container)")
        self.assertGreater(destroy_idx, 0, "error 分支缺少 destroy")
        self.assertGreater(fallback_idx, 0, "error 分支缺少 fallback")
        self.assertLess(destroy_idx, fallback_idx)


class TestR704MachineryRemoved(unittest.TestCase):
    """R704 的偏好机制必须整体移除（半拆状态 = 行为漂移温床）。"""

    def setUp(self) -> None:
        self.app = APP_JS.read_text(encoding="utf-8")

    def test_no_reduced_motion_watcher(self) -> None:
        self.assertNotIn("_installReducedMotionWatcher", self.app)

    def test_no_rest_frame_helper(self) -> None:
        self.assertNotIn("_applySproutRestFrame", self.app)
        self.assertNotIn("SPROUT_REST_FRAME", self.app)


class TestProgressBarCssExemption(unittest.TestCase):
    """main.css：全局 reduce 块必须保留空态进度条豁免。"""

    def setUp(self) -> None:
        self.css = MAIN_CSS.read_text(encoding="utf-8")

    def test_exemption_rule_present(self) -> None:
        # 提取全局 reduce 块（含 * 选择器 0.01ms 规则的那个）之后的
        # 豁免规则：进度条 animation-iteration-count 必须回到 infinite。
        match = re.search(
            r"\.no-content-progress-bar\s*\{[^}]*animation-iteration-count:\s*"
            r"infinite\s*!important[^}]*\}",
            self.css,
        )
        self.assertIsNotNone(
            match,
            "R712: main.css 必须保留 .no-content-progress-bar 的 "
            "reduced-motion 豁免（animation-iteration-count: infinite "
            "!important），否则减弱动态设备上进度条 0.01ms 跑完一次后"
            "永久静止",
        )

    def test_exemption_lives_inside_reduce_block(self) -> None:
        reduce_blocks = re.findall(
            r"@media\s*\(prefers-reduced-motion:\s*reduce\)\s*\{",
            self.css,
        )
        self.assertGreater(len(reduce_blocks), 0)
        # 豁免必须出现在某个 reduce 块内部（!important 才有对象可覆盖）
        idx = self.css.find("animation-iteration-count: infinite !important")
        self.assertGreater(idx, 0)
        prefix = self.css[:idx]
        last_open = prefix.rfind("@media (prefers-reduced-motion: reduce)")
        self.assertGreater(
            last_open,
            0,
            "R712: 进度条豁免规则必须写在 prefers-reduced-motion 媒体查询内",
        )


if __name__ == "__main__":
    unittest.main()
