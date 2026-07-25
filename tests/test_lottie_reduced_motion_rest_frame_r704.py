"""R704 回归护栏：prefers-reduced-motion 下 Lottie 静止帧（不再降级 SVG）。

背景（TODO「移动端 lottie 动画一直是 fallback SVG」的根因修复）：

R696 之前的契约把 prefers-reduced-motion 与「lottie 运行时加载失败」
一起列为降级 SVG 的触发场景。但 iPhone「设置 > 辅助功能 > 动态效果 >
减弱动态效果」是设备级常开设置——开启它的用户每次访问都命中降级
分支，永远看不到 Lottie 画面，观感等同「动画坏了」。

R704 的新契约（WCAG 无障碍最佳实践：reduced motion ≠ no imagery）：

1. **偏好开启时仍加载 Lottie**：``autoplay: !_prefersReducedMotion()``，
   DOMLoaded 后 ``_applySproutRestFrame()`` 静止到「完整长成」帧
   （``SPROUT_REST_FRAME``）——零运动、视觉与动画版一致。
2. **静止帧必须落在稳定段**：sprout.json 共 72 帧（0-36 生长、36-48
   长成后摆动、之后回缩到土丘），静止帧取稳定段中部而非首尾帧。
3. **偏好实时切换**：``_installReducedMotionWatcher`` 监听
   MediaQueryList change（旧 WebKit 走 addListener 兼容分支），
   开启 → 静止帧、关闭 → 恢复播放。
4. **降级 SVG 仅剩一个场景**：lottie 运行时加载失败；且 error 处理
   必须先 ``destroyHourglassAnimation()`` 再渲染 fallback（残留实例
   会让下一次 init 误判「动画健在」直接 return，卡死在降级画面）。

本文件锁定上述契约，防止未来重构把 reduced-motion 用户打回简笔 SVG。
"""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
APP_JS = REPO_ROOT / "src" / "ai_intervention_agent" / "static" / "js" / "app.js"
SPROUT_JSON = (
    REPO_ROOT / "src" / "ai_intervention_agent" / "static" / "lottie" / "sprout.json"
)


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


class TestRestFrameConstant(unittest.TestCase):
    """SPROUT_REST_FRAME 必须存在且落在动画的「完整长成」稳定段。"""

    def setUp(self) -> None:
        self.app = APP_JS.read_text(encoding="utf-8")

    def _rest_frame(self) -> int:
        match = re.search(r"const\s+SPROUT_REST_FRAME\s*=\s*(\d+)", self.app)
        self.assertIsNotNone(match, "missing SPROUT_REST_FRAME constant")
        assert match is not None
        return int(match.group(1))

    def test_rest_frame_in_grown_stable_range(self) -> None:
        # 稳定段 36-48（运行时逐帧截图核实：36/48 均为完整嫩芽，
        # 71 是循环回起点的空土丘）。
        frame = self._rest_frame()
        self.assertGreaterEqual(frame, 36)
        self.assertLessEqual(frame, 48)

    def test_rest_frame_within_animation_bounds(self) -> None:
        data = json.loads(SPROUT_JSON.read_text(encoding="utf-8"))
        op = int(data["op"])  # 结束帧（排他）
        self.assertLess(self._rest_frame(), op)


class TestCreateAnimationHonorsPreference(unittest.TestCase):
    """_createLottieAnimation：偏好决定 autoplay，DOMLoaded 静止帧。"""

    def setUp(self) -> None:
        self.body = _function_body(
            APP_JS.read_text(encoding="utf-8"), "_createLottieAnimation"
        )

    def test_autoplay_respects_preference(self) -> None:
        self.assertIn("autoplay: !_prefersReducedMotion()", self.body)

    def test_domloaded_applies_rest_frame(self) -> None:
        self.assertIn("_applySproutRestFrame()", self.body)

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


class TestRestFrameHelper(unittest.TestCase):
    """_applySproutRestFrame：goToAndStop + totalFrames 越界保护。"""

    def setUp(self) -> None:
        self.body = _function_body(
            APP_JS.read_text(encoding="utf-8"), "_applySproutRestFrame"
        )

    def test_uses_go_to_and_stop(self) -> None:
        self.assertIn("goToAndStop", self.body)

    def test_clamps_to_total_frames(self) -> None:
        self.assertIn("totalFrames", self.body)
        self.assertIn("Math.min(SPROUT_REST_FRAME", self.body)


class TestReducedMotionWatcher(unittest.TestCase):
    """_installReducedMotionWatcher：偏好变化实时 播放 / 静止。"""

    def setUp(self) -> None:
        self.body = _function_body(
            APP_JS.read_text(encoding="utf-8"), "_installReducedMotionWatcher"
        )

    def test_watches_change_event(self) -> None:
        self.assertIn('addEventListener("change"', self.body)

    def test_legacy_webkit_add_listener_branch(self) -> None:
        self.assertIn("addListener", self.body)

    def test_toggles_between_rest_and_play(self) -> None:
        self.assertIn("_applySproutRestFrame()", self.body)
        self.assertIn("hourglassAnimation.play()", self.body)


if __name__ == "__main__":
    unittest.main()
