"""R299: Web Observer (Intersection/Resize/Mutation) 内存泄漏审计 + invariant 测试。

cycle-29 #D (cr58 §5) 续作 R298: `fetchWithTimeout` AbortController
cleanup 之后, 继续审计 Web Observer API:
- IntersectionObserver (LazyImageLoader in validation-utils.js)
- ResizeObserver (feedback_textarea_height.js)
- MutationObserver (当前未使用, 但需要锁 invariant 防 future 引入)

Observer API 的 lifecycle 规范:
- `new XObserver(callback)` 创建实例 → callback 引用 entries/closure 变量
- `.observe(target)` 注册观察 target
- `.unobserve(target)` 取消单个 target 观察 (可选)
- `.disconnect()` 取消所有观察 (必须在 cleanup 时调用)

**leak 风险**:
1. observe 后忘 disconnect → callback closure 长期持有 target / 外部状态
2. disconnect 后没有置 = null → 实例本身 GC 不掉, callback 闭包驻留
3. 单图加载完没有 unobserve → 观察者一直 fire callback 但已无意义

R299 锁定:

================================================================
| 维度                                                  | tests |
|-----------------------------------------------------|-------|
| 1. IntersectionObserver LazyImageLoader disconnect 路径完备 | 4   |
| 2. IntersectionObserver entry 加载完必须 unobserve     | 2     |
| 3. ResizeObserver setupResizeObserver 必须返回 observer 引用 | 2 |
| 4. ResizeObserver 必须 feature-detect (旧浏览器降级 fallback) | 2 |
| 5. meta-lint: 全 source 不应出现 MutationObserver (未来如引入应有 cleanup) | 2 |
================================================================
| 合计                                                  | 12    |
================================================================

**pattern lineage**: R298 lifecycle-cleanup invariant 的延伸扩展到
Observer API。methodology v3.6 推荐 pattern #3 (lifecycle-cleanup) 的
进一步推广 - 凡是 *long-lived registration API* (AbortController /
Observer / addEventListener) 都应有 cleanup invariant 锁定。
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC = PROJECT_ROOT / "src" / "ai_intervention_agent"
JS_DIR = SRC / "static" / "js"
VALIDATION_UTILS_JS = JS_DIR / "validation-utils.js"
FEEDBACK_HEIGHT_JS = JS_DIR / "feedback_textarea_height.js"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def _strip_js_comments(src: str) -> str:
    out = re.sub(r"/\*[\s\S]*?\*/", "", src)
    cleaned: list[str] = []
    for line in out.split("\n"):
        in_str: str | None = None
        i = 0
        n = len(line)
        cut = n
        while i < n:
            c = line[i]
            if in_str:
                if c == "\\" and i + 1 < n:
                    i += 2
                    continue
                if c == in_str:
                    in_str = None
            else:
                if c in ('"', "'", "`"):
                    in_str = c
                elif c == "/" and i + 1 < n and line[i + 1] == "/":
                    cut = i
                    break
            i += 1
        cleaned.append(line[:cut])
    return "\n".join(cleaned)


# ============================================================
# #1: IntersectionObserver LazyImageLoader disconnect 路径完备
# ============================================================
class TestIntersectionObserverCleanup(unittest.TestCase):
    """validation-utils.js LazyImageLoader 必须有完整的 disconnect 路径"""

    def setUp(self) -> None:
        self.js = _strip_js_comments(_read(VALIDATION_UTILS_JS))

    def test_intersection_observer_created(self) -> None:
        """必须 new IntersectionObserver。"""
        self.assertRegex(
            self.js,
            r"new\s+IntersectionObserver\(",
            "validation-utils.js 必须 new IntersectionObserver",
        )

    def test_observer_assigned_to_class_field(self) -> None:
        """observer 必须存到 this._observer (或 ClassName._observer) 便于 disconnect。"""
        m = re.search(r"this\._observer\s*=\s*observer", self.js)
        self.assertIsNotNone(
            m,
            "IntersectionObserver 创建后必须 this._observer = observer 保存引用",
        )

    def test_disconnect_method_exists(self) -> None:
        """LazyImageLoader 必须有 static disconnect() 方法。"""
        m = re.search(
            r"static\s+disconnect\(\)\s*\{[\s\S]{0,300}?this\._observer\.disconnect\(\)",
            self.js,
        )
        self.assertIsNotNone(
            m,
            "LazyImageLoader 必须有 static disconnect() 方法 + 调用 this._observer.disconnect()",
        )

    def test_disconnect_nulls_observer(self) -> None:
        """disconnect() 必须置 this._observer = null (避免长期持有)。"""
        m = re.search(
            r"this\._observer\.disconnect\(\)\s*;?\s*this\._observer\s*=\s*null",
            self.js,
        )
        self.assertIsNotNone(
            m,
            "LazyImageLoader disconnect() 必须 this._observer.disconnect(); "
            "this._observer = null — observer 实例 GC 不掉则 callback 闭包驻留",
        )


# ============================================================
# #2: IntersectionObserver entry 加载完必须 unobserve
# ============================================================
class TestIntersectionObserverUnobserve(unittest.TestCase):
    """单图懒加载完成后必须 obs.unobserve(entry.target) 避免重复 fire callback"""

    def setUp(self) -> None:
        self.js = _strip_js_comments(_read(VALIDATION_UTILS_JS))

    def test_unobserve_called_after_load(self) -> None:
        """observe callback 内 isIntersecting 分支必须 obs.unobserve(entry.target)。"""
        m = re.search(
            r"if\s*\(\s*entry\.isIntersecting\s*\)[\s\S]{0,300}?obs\.unobserve\(\s*entry\.target\s*\)",
            self.js,
        )
        self.assertIsNotNone(
            m,
            "IntersectionObserver isIntersecting 分支必须 obs.unobserve(entry.target) "
            "— 否则 observer 持续 fire callback 但已无意义, 形成 zombie 观察",
        )

    def test_callback_second_arg_is_obs(self) -> None:
        """IntersectionObserver callback 必须 (entries, obs) 接收第二参数, 才能 unobserve。"""
        m = re.search(
            r"new\s+IntersectionObserver\(\s*\(?entries\s*,\s*obs\)?\s*=>", self.js
        )
        self.assertIsNotNone(
            m,
            "IntersectionObserver callback 必须 (entries, obs) => 接受第二参数 obs",
        )


# ============================================================
# #3: ResizeObserver setupResizeObserver 必须返回 observer 引用
# ============================================================
class TestResizeObserverReturnsHandle(unittest.TestCase):
    """feedback_textarea_height.js setupResizeObserver 必须返回 { observer, mode } 便于 cleanup"""

    def setUp(self) -> None:
        self.js = _strip_js_comments(_read(FEEDBACK_HEIGHT_JS))

    def test_resize_observer_created(self) -> None:
        """必须 new ResizeObserver。"""
        self.assertRegex(
            self.js,
            r"new\s+ResizeObserver\(",
            "feedback_textarea_height.js 必须 new ResizeObserver",
        )

    def test_returns_object_with_observer_field(self) -> None:
        """setupResizeObserver 必须 return { observer: ro, mode: ... } 让 caller 可控。"""
        m = re.search(
            r"new\s+ResizeObserver\([\s\S]{0,200}?return\s*\{\s*observer\s*:\s*\w+",
            self.js,
        )
        self.assertIsNotNone(
            m,
            "setupResizeObserver 必须 return { observer: ro, mode: ... } "
            "— caller 可凭 observer 引用调用 .disconnect() 做 cleanup",
        )


# ============================================================
# #4: ResizeObserver 必须 feature-detect (旧浏览器降级)
# ============================================================
class TestResizeObserverFeatureDetect(unittest.TestCase):
    """ResizeObserver 必须 feature-detect, 旧浏览器走 mouseup fallback"""

    def setUp(self) -> None:
        self.js = _strip_js_comments(_read(FEEDBACK_HEIGHT_JS))

    def test_feature_detect_present(self) -> None:
        """必须 if (typeof ResizeObserver !== "undefined") 守护。"""
        m = re.search(
            r"typeof\s+ResizeObserver\s*!==?\s*['\"]undefined['\"]",
            self.js,
        )
        self.assertIsNotNone(
            m,
            "feedback_textarea_height.js 必须 typeof ResizeObserver !== 'undefined' "
            "做 feature detect — 否则旧浏览器抛 ReferenceError 中断 textarea 持久化",
        )

    def test_fallback_path_exists(self) -> None:
        """fallback 必须用 addEventListener mouseup/touchend (非 ResizeObserver 路径)。"""
        m = re.search(
            r"addEventListener\(\s*['\"]mouseup['\"]",
            self.js,
        )
        self.assertIsNotNone(
            m,
            "ResizeObserver 不支持时必须有 mouseup fallback path",
        )
        m2 = re.search(
            r"addEventListener\(\s*['\"]touchend['\"]",
            self.js,
        )
        self.assertIsNotNone(
            m2,
            "ResizeObserver 不支持时必须有 touchend fallback path (移动端 UX 必备)",
        )


# ============================================================
# #5: meta-lint: 全 source 不应出现 MutationObserver
#    (未来如引入须有 cleanup invariant)
# ============================================================
class TestNoMutationObserverYet(unittest.TestCase):
    """整 source tree 当前不应出现 MutationObserver 使用 — 一旦引入必须配 cleanup invariant"""

    def test_no_mutation_observer_in_static_js(self) -> None:
        """扫描 static/js/ 全部 .js 文件不应有 new MutationObserver。"""
        violators: list[str] = []
        for js_file in JS_DIR.glob("*.js"):
            if not js_file.is_file():
                continue
            content = _strip_js_comments(_read(js_file))
            if re.search(r"new\s+MutationObserver\(", content):
                violators.append(js_file.name)
        self.assertEqual(
            violators,
            [],
            f"R299: {violators} 引入了 MutationObserver 但本测试还没补对应 "
            f"disconnect cleanup invariant — 请扩展 R299 或新 R30x 锁定其 lifecycle",
        )

    def test_no_performance_observer_in_static_js(self) -> None:
        """扫描 static/js/ 不应有 new PerformanceObserver (同样未审计)。"""
        violators: list[str] = []
        for js_file in JS_DIR.glob("*.js"):
            if not js_file.is_file():
                continue
            content = _strip_js_comments(_read(js_file))
            if re.search(r"new\s+PerformanceObserver\(", content):
                violators.append(js_file.name)
        self.assertEqual(
            violators,
            [],
            f"R299: {violators} 引入了 PerformanceObserver 但本测试还没补对应 "
            f"disconnect cleanup invariant — 请扩展 R299 或新 R30x 锁定其 lifecycle",
        )


if __name__ == "__main__":
    unittest.main()
