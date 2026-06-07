"""perf-audit-cycle-22 · Track H (R266) · countdown SVG DOM ref cache.

背景
----

`multi_task.js::startTaskCountdown` 内的 `setInterval` body 与
`forceUpdateAllTaskCountdowns` 都是 1Hz × N 并发 task 的高频 DOM 路径。
原实现每次 tick 都为每个 task 触发 3 次 DOM 查找：

```js
const countdownRing = document.getElementById(`countdown-${tid}`);
const circle = countdownRing.querySelector("circle");
const numberSpan = countdownRing.querySelector(".countdown-number");
```

= 3N 次 DOM 查找 / 秒。N=10 task 时 = 30/s = 1800/min。每次查找虽然
O(1)，但 querySelector 的 cache miss + setAttribute 触发的 layout
invalidation 累加会吃 frame budget。Browser 在 background tab throttle
setInterval 到 1Hz 但 layout pipeline 仍要 work，长会话场景明显有 perf
浪费。

修复
----

把 DOM refs cache 在 `taskCountdowns[tid]._domCache` 上，`document.contains
(cache.ring)` 兜底 stale invalidation（SSE 重渲染 / incremental rebuild
会替换 .task-tab 节点，旧 cache 就脱离 DOM tree）。命中 cache 直接复用，
未命中重查并写回。

回归契约
--------

5 invariants 防 cache 模式被无意 revert：
- helper 函数 `_getOrCacheCountdownDom` 必须存在
- 必须用 `document.contains` 检测 stale
- 必须挂在 `entry._domCache` 上
- `forceUpdateAllTaskCountdowns` 与 `setInterval` 内部都必须经由 helper
- helper 必须 cache 三个 refs（ring / circle / numberSpan）

Without these invariants, a routine "let me simplify this back to
inline querySelector" refactor would silently revert to the 3N/s DOM
lookups and the perf regression would be invisible to users until
they hit a 50+ task session.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

JS_PATH = (
    Path(__file__).resolve().parent.parent
    / "src"
    / "ai_intervention_agent"
    / "static"
    / "js"
    / "multi_task.js"
)


class TestCountdownDomCacheR266(unittest.TestCase):
    """R266 · 高频 1Hz countdown 路径 DOM ref cache"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.js = JS_PATH.read_text(encoding="utf-8")

    def test_helper_function_exists(self) -> None:
        """`_getOrCacheCountdownDom` helper 必须存在."""
        self.assertRegex(
            self.js,
            r"function\s+_getOrCacheCountdownDom\s*\(\s*tid\s*,\s*entry\s*\)",
            "R266 perf cache helper 缺失：必须有 _getOrCacheCountdownDom(tid, entry)",
        )

    def test_helper_uses_document_contains_to_detect_stale(self) -> None:
        """helper 必须用 `document.contains(cache.ring)` 检测脱离 DOM 的
        旧 cache —— SSE 重渲染 / incremental tab rebuild 会替换 .task-tab
        节点，盲 reuse stale ref 会 silent fail（setAttribute 不报错但用户
        看不到效果）。"""
        helper_match = re.search(
            r"function\s+_getOrCacheCountdownDom[\s\S]*?(?=\nfunction\s+)",
            self.js,
        )
        self.assertIsNotNone(helper_match, "找不到 _getOrCacheCountdownDom 函数体")
        assert helper_match is not None
        body = helper_match.group(0)
        self.assertRegex(
            body,
            r"document\.contains\(\s*cache\.ring\s*\)",
            "R266 helper 缺 document.contains(cache.ring) stale detection",
        )

    def test_helper_caches_three_refs(self) -> None:
        """helper 必须 cache 三个 DOM refs：ring / circle / numberSpan."""
        helper_match = re.search(
            r"function\s+_getOrCacheCountdownDom[\s\S]*?(?=\nfunction\s+)",
            self.js,
        )
        self.assertIsNotNone(helper_match, "找不到 _getOrCacheCountdownDom 函数体")
        assert helper_match is not None
        body = helper_match.group(0)
        self.assertIn(
            "ring:",
            body,
            "R266 helper 必须 cache `ring` ref",
        )
        self.assertIn(
            "circle:",
            body,
            "R266 helper 必须 cache `circle` ref（querySelector('circle')）",
        )
        self.assertIn(
            "numberSpan:",
            body,
            "R266 helper 必须 cache `numberSpan` ref（querySelector('.countdown-number')）",
        )

    def test_helper_stores_cache_on_entry(self) -> None:
        """cache 必须挂在 `entry._domCache` 上（每个 task 的 countdown entry
        持有自己的 cache，task 退场时 cache 跟着 GC 不需要额外清理）。"""
        helper_match = re.search(
            r"function\s+_getOrCacheCountdownDom[\s\S]*?(?=\nfunction\s+)",
            self.js,
        )
        self.assertIsNotNone(helper_match, "找不到 _getOrCacheCountdownDom 函数体")
        assert helper_match is not None
        body = helper_match.group(0)
        self.assertRegex(
            body,
            r"entry\._domCache\s*=\s*cache",
            "R266 helper 必须把 cache 挂在 entry._domCache 上",
        )

    def test_force_update_all_uses_cache_helper(self) -> None:
        """`forceUpdateAllTaskCountdowns` 必须经由 helper —— 不能 inline 写
        getElementById/querySelector（否则又退化到 1Hz × N 反复查找）。"""
        body_match = re.search(
            r"function\s+forceUpdateAllTaskCountdowns[\s\S]*?(?=\nif\s*\(typeof|\nfunction\s+)",
            self.js,
        )
        self.assertIsNotNone(body_match, "找不到 forceUpdateAllTaskCountdowns 函数体")
        assert body_match is not None
        body = body_match.group(0)
        self.assertIn(
            "_getOrCacheCountdownDom(tid, entry)",
            body,
            "R266 forceUpdateAllTaskCountdowns 必须 _getOrCacheCountdownDom(tid, entry)",
        )
        # 反向锁：不能再 inline 写 getElementById(`countdown-${tid}`)
        self.assertNotRegex(
            body,
            r"document\.getElementById\(`countdown-\$\{tid\}`\)",
            "R266 forceUpdateAllTaskCountdowns 不应再 inline getElementById"
            "（应走 _getOrCacheCountdownDom 缓存路径）",
        )

    def test_start_task_countdown_setInterval_uses_cache(self) -> None:
        """`startTaskCountdown` 内 setInterval body 必须经由 helper（每秒
        N 次的最热路径，不走 cache = 直接 perf regression）。"""
        # 抓 startTaskCountdown 整段
        body_match = re.search(
            r"function\s+startTaskCountdown[\s\S]*?(?=\n/\*\*|\nfunction\s+)",
            self.js,
        )
        self.assertIsNotNone(body_match, "找不到 startTaskCountdown 函数体")
        assert body_match is not None
        body = body_match.group(0)
        self.assertIn(
            "_getOrCacheCountdownDom(taskId, taskCountdowns[taskId])",
            body,
            "R266 startTaskCountdown setInterval body 必须 "
            "_getOrCacheCountdownDom(taskId, taskCountdowns[taskId])",
        )
        # 反向锁：不能再 inline getElementById(`countdown-${taskId}`)
        self.assertNotRegex(
            body,
            r"document\.getElementById\(`countdown-\$\{taskId\}`\)",
            "R266 startTaskCountdown setInterval 不应再 inline getElementById"
            "（应走 _getOrCacheCountdownDom 缓存路径）",
        )


if __name__ == "__main__":
    unittest.main()
