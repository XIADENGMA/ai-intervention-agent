"""a11y/perf-audit-cycle-22 · Track G (R265) · `_wireCustomSoundControls`
listener leak fix（cr51 follow-up #4 spillover）.

背景
----

cr51 §5 follow-up #4 列出 "通用 lint：扫所有 ``function open\\w+Modal``
看是否 leak addEventListener" 作为 cycle-9 candidate（medium / M）。
cycle-22 把扫描扩展到所有「在多个调用点被复用的 wire/init 函数」，
发现 ``settings-manager.js::_wireCustomSoundControls`` 是真 bug：

调用点 1: ``init()`` 内首次绑 fileInput.change / testBtn.click /
clearBtn.click。
调用点 2: ``resetSettings()`` line 261 // 刷新 status / disabled 状态
— 注释只提"刷新"，实际把整个 ``_wireCustomSoundControls`` 重新执行
一遍，listener 第 2 次绑定，永不解绑。

真 bug 影响
-----------

| reset 次数 N | testBtn.click 触发 playSound() 次数 |
|-------------|--------------------------------------|
| 0           | 1                                    |
| 1           | 2                                    |
| 2           | 3                                    |
| N           | N+1                                  |

同理 filePicker change → ``saveCustomSoundFromFile`` 也线性叠加调用
（虽然第一次成功后会 ``e.target.value = ""``，但 N 个 listener 都进
``async`` 里跑 → API 被并行 N 次调用 + statusEl.textContent 被 N 次
覆盖 → race condition）。

clearBtn.click → ``clearCustomSound + refresh`` 同样线性叠加（虽然
clearCustomSound 第 2 次是 no-op，但 ``refresh`` 写 statusEl 文本 N 次
是浪费）。

audio playback 重复 N 次 = 用户听到 N 次"重叠"播放，明显 perf/UX bug。

修复
----

Pattern 对齐 R263a image-modal 的 ``modal.dataset.aiiaInited`` guard：
``fileInput.dataset.aiiaWired`` 第一次设 "1"，之后 skip listener 绑定，
只跑 ``refresh()``（refresh 纯 DOM read/write 无副作用，重复跑安全
且必要：reset 后要刷新 disabled / status 文本）。

回归契约
--------

5 invariants 防 leak 回归：
- listener 绑定段必须被 ``if (!fileInput.dataset.aiiaWired)`` 包裹
- guard 必须正确 set ``dataset.aiiaWired = "1"`` 标记
- ``refresh()`` 必须在 guard 外（每次调用都要刷新 UI）
- 3 个 listener (fileInput change / testBtn click / clearBtn click) 都
  必须在 guard 内

Without these invariants, a routine "let me extract this wiring to a
hook" refactor would silently drop the guard and re-introduce the N+1
audio playback bug — and **no existing test would catch it** because
all settings-manager tests stub ``notificationManager`` and don't
exercise the resetSettings → _wireCustomSoundControls re-entry path.
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
    / "settings-manager.js"
)


class TestWireCustomSoundControlsLeakFix(unittest.TestCase):
    """R265 · 防 ``_wireCustomSoundControls`` listener 累积"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.js = JS_PATH.read_text(encoding="utf-8")
        # 抓 _wireCustomSoundControls 函数体（到下一个顶级方法 ``  _``
        # 或 ``  ====`` 注释区分）
        body_match = re.search(
            r"_wireCustomSoundControls\s*\(\s*\)\s*\{[\s\S]*?(?=\n  // ====|\n  [a-zA-Z_]+\s*\()",
            cls.js,
        )
        cls.body = body_match.group(0) if body_match else ""
        assert cls.body, "找不到 _wireCustomSoundControls 函数体"

    def test_function_uses_dataset_aiia_wired_guard(self) -> None:
        """3 个 listener 绑定必须被 ``if (!fileInput.dataset.aiiaWired)`` 包裹."""
        self.assertRegex(
            self.body,
            r"if\s*\(\s*!\s*fileInput\.dataset\.aiiaWired\s*\)",
            "R265 leak 修复缺失：listener 绑定必须用 dataset.aiiaWired guard"
            "（init + resetSettings 双调用点会导致 listener 第 2 次绑定 → "
            "testBtn 点击播 N+1 次 audio）",
        )

    def test_guard_marks_aiia_wired_with_1(self) -> None:
        """guard 开头必须 ``dataset.aiiaWired = "1"`` 写标记，否则 guard 永远
        true → listener 仍然每次 reset 都绑."""
        self.assertRegex(
            self.body,
            r'fileInput\.dataset\.aiiaWired\s*=\s*"1"',
            "R265 guard 缺标记写入：必须 fileInput.dataset.aiiaWired = '1'",
        )

    def test_all_three_listeners_inside_guard(self) -> None:
        """fileInput.change / testBtn.click / clearBtn.click 三个 listener
        必须都在 guard 内。"""
        # 切出 guard 块（从 ``if (!fileInput.dataset.aiiaWired) {`` 到对应 ``}``）
        guard_match = re.search(
            r"if\s*\(\s*!\s*fileInput\.dataset\.aiiaWired\s*\)\s*\{([\s\S]*?)\n    \}",
            self.body,
        )
        self.assertIsNotNone(guard_match, "找不到 guard 块匹配")
        assert guard_match is not None
        guard_body = guard_match.group(1)
        self.assertIn(
            'fileInput.addEventListener("change"',
            guard_body,
            "R265 fileInput.change listener 必须在 guard 内",
        )
        self.assertIn(
            'testBtn.addEventListener("click"',
            guard_body,
            "R265 testBtn.click listener 必须在 guard 内",
        )
        self.assertIn(
            'clearBtn.addEventListener("click"',
            guard_body,
            "R265 clearBtn.click listener 必须在 guard 内",
        )

    def test_refresh_call_outside_guard(self) -> None:
        """``refresh()`` 必须在 guard 外（最后无条件调一次），不然 reset 后
        UI 状态不刷新就是死的（reset 的整个目的是更新 status / disabled）."""
        # 抓 guard 结束后到函数结束的尾段
        tail_match = re.search(
            r"\n    \}\n\n(    refresh\(\);)",
            self.body,
        )
        self.assertIsNotNone(
            tail_match,
            "R265 refresh() 必须在 guard 块结束后无条件调用 —— "
            "否则 reset 不更新 status / disabled 状态",
        )

    def test_dataset_guard_pattern_aligned_with_r263a(self) -> None:
        """meta-test：dataset guard 命名应与 R263a image-modal 的 ``aiiaInited``
        / R265 的 ``aiiaWired`` 处于同一 namespace（``aiia*``），保持 project-
        wide pattern 一致性。defense-in-depth 也防 typo 类的回归。"""
        self.assertRegex(
            self.body,
            r"\.dataset\.aiia[A-Z]\w+",
            "R265 dataset guard 命名应在 aiia* namespace（与 R263a 对齐）",
        )


if __name__ == "__main__":
    unittest.main()
