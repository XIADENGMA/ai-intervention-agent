"""R310: asyncio task lifecycle invariant (cycle-31 t31-5, v3.7 新 pattern #B2)。

cycle-30 cr60 §5 #B2 提议 — async task lifecycle invariant。R298+R299
锁了 JS DOM/Observer 的 cleanup, R310 把 lifecycle-cleanup pattern 扩展
到 **Python asyncio task** 维度, 防 ``asyncio.create_task`` 后没 cancel
+ await 导致的 "fire-and-forget task" 泄漏。

================================================================
| 当前 asyncio.create_task 使用点 (R310 commit 时):                  |
|---------------------------------------------------------------|
| server_feedback.py:438  sse_task = asyncio.create_task(_sse_listener()) |
| server_feedback.py:439  poll_task = asyncio.create_task(_poll_fallback()) |
================================================================

================================================================
| Cleanup pattern (R310 锁定):                                      |
================================================================
```python
sse_task = asyncio.create_task(_sse_listener())
poll_task = asyncio.create_task(_poll_fallback())
try:
    ...
finally:
    sse_task.cancel()
    poll_task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await sse_task
    with contextlib.suppress(asyncio.CancelledError):
        await poll_task
```

================================================================
| Invariant 锁定 (5 条)                                              |
================================================================
1. ``server_feedback.py`` 中的 sse_task 必须有 ``.cancel()`` + ``await``
2. ``server_feedback.py`` 中的 poll_task 必须有 ``.cancel()`` + ``await``
3. cancel 之后的 await 必须包在 ``contextlib.suppress(asyncio.CancelledError)``
4. R310 marker 必须出现在 server_feedback.py (防 lineage 丢失)
5. **future-guard meta-lint**: 全仓 ``src/`` 中 ``asyncio.create_task``
   总数必须 == 2 (R310 commit 时点的 baseline) — 未来新增必须 review
   cleanup pattern 后才能更新此数字

================================================================
| Tests | 维度                                                    |
|-------|------------------------------------------------------|
| 3     | sse_task / poll_task lifecycle (cancel + await + suppress) |
| 1     | R310 marker / contextlib.suppress 用法                  |
| 1     | future-guard: create_task 总数 baseline                 |
================================================================
| 5 总计                                                            |
================================================================

**pattern lineage**: v3.6 lifecycle-cleanup (R298 AbortController +
R299 Web Observer + R301 HTTP status) → **R310 (asyncio.create_task)**
— lifecycle pattern 域跨度从 "Browser 端 DOM API" 扩展到 "Python 端
async 任务"。
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC = PROJECT_ROOT / "src" / "ai_intervention_agent"
SERVER_FEEDBACK = SRC / "server_feedback.py"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


# ============================================================
# sse_task / poll_task lifecycle
# ============================================================
class TestAsyncioTaskLifecycle(unittest.TestCase):
    """server_feedback.py 中 2 个 asyncio.create_task 的 cleanup 必须存在"""

    def setUp(self) -> None:
        self.src = _read(SERVER_FEEDBACK)

    def test_sse_task_has_create_cancel_await(self) -> None:
        """``sse_task`` 必须有 create + cancel + await 三段。"""
        # create
        self.assertRegex(
            self.src,
            r"sse_task\s*=\s*asyncio\.create_task\(",
            "R310: sse_task 必须由 asyncio.create_task() 创建",
        )
        # cancel
        self.assertRegex(
            self.src,
            r"sse_task\.cancel\(\)",
            "R310: sse_task 必须有 .cancel() 调用 (finally 中)",
        )
        # await
        self.assertRegex(
            self.src,
            r"await sse_task",
            "R310: sse_task 必须有 await (cancel 后等待真正结束, 防 task 泄漏)",
        )

    def test_poll_task_has_create_cancel_await(self) -> None:
        """``poll_task`` 必须有 create + cancel + await 三段。"""
        self.assertRegex(
            self.src,
            r"poll_task\s*=\s*asyncio\.create_task\(",
            "R310: poll_task 必须由 asyncio.create_task() 创建",
        )
        self.assertRegex(
            self.src,
            r"poll_task\.cancel\(\)",
            "R310: poll_task 必须有 .cancel() 调用",
        )
        self.assertRegex(
            self.src,
            r"await poll_task",
            "R310: poll_task 必须有 await",
        )

    def test_cancel_and_await_in_same_finally_block(self) -> None:
        """``cancel()`` 和 ``await`` 必须在同一 ``finally:`` block 中 (close
        in time, 不能 cancel 后散步)。"""
        # 找到 finally 块包含两个 cancel + 两个 await
        m = re.search(
            r"finally:[\s\S]{0,500}?sse_task\.cancel\(\)"
            r"[\s\S]{0,200}?poll_task\.cancel\(\)"
            r"[\s\S]{0,400}?await sse_task[\s\S]{0,200}?await poll_task",
            self.src,
        )
        self.assertIsNotNone(
            m,
            "R310: cancel + await 必须在同一 finally 块中, 按 sse → poll 顺序",
        )


# ============================================================
# suppress(CancelledError) 用法
# ============================================================
class TestSuppressCancelledError(unittest.TestCase):
    """cancel 之后的 await 必须用 contextlib.suppress 隔离 CancelledError"""

    def setUp(self) -> None:
        self.src = _read(SERVER_FEEDBACK)

    def test_await_wrapped_in_suppress_cancelled_error(self) -> None:
        """每个 ``await sse_task`` / ``await poll_task`` 前必须有
        ``with contextlib.suppress(asyncio.CancelledError):``。"""
        m = re.search(
            r"with contextlib\.suppress\(asyncio\.CancelledError\):\s*\n\s+"
            r"await sse_task",
            self.src,
        )
        self.assertIsNotNone(
            m,
            "R310: await sse_task 必须包在 with contextlib.suppress("
            "asyncio.CancelledError) 中 (cancel 后 CancelledError 是预期, "
            "不应向上传播)",
        )
        m = re.search(
            r"with contextlib\.suppress\(asyncio\.CancelledError\):\s*\n\s+"
            r"await poll_task",
            self.src,
        )
        self.assertIsNotNone(
            m,
            "R310: await poll_task 必须包在 with contextlib.suppress("
            "asyncio.CancelledError) 中",
        )

    def test_contextlib_imported(self) -> None:
        """``contextlib`` 必须 import (使用 suppress)。"""
        # multiline flag 让 ^ 匹配每行行首, 而不仅是 string 起始
        m = re.search(
            r"^import contextlib\b|^from contextlib import",
            self.src,
            re.MULTILINE,
        )
        self.assertIsNotNone(
            m,
            "R310: server_feedback.py 必须 import contextlib (used by suppress)",
        )


# ============================================================
# future-guard: create_task 总数 baseline
# ============================================================
class TestCreateTaskBaselineCount(unittest.TestCase):
    """全仓 src/ 内 asyncio.create_task 总数必须 = R310 commit 时 baseline"""

    def test_total_create_task_count_baseline(self) -> None:
        """全 ``src/`` 中 ``asyncio.create_task`` 总数 = 2 (R310 baseline)。

        未来新增 asyncio.create_task 必须:
        1. 同步实现 cancel + await + suppress cleanup pattern
        2. 在 R310 测试中显式列入并锁 lifecycle
        3. 更新本 baseline 数字
        """
        all_matches: list[tuple[str, int]] = []
        for py_file in SRC.rglob("*.py"):
            content = py_file.read_text(encoding="utf-8")
            count = len(re.findall(r"asyncio\.create_task\(", content))
            if count:
                all_matches.append((str(py_file.relative_to(PROJECT_ROOT)), count))

        total = sum(c for _, c in all_matches)
        self.assertEqual(
            total,
            2,
            f"R310: 全 src/ 中 asyncio.create_task 总数必须 = 2 "
            f"(R310 commit 时 baseline)。当前找到 {total}: {all_matches}\n"
            f"如果新增了 create_task: ① 实现 cancel + await + suppress cleanup "
            f"② R310 测试列入新 task ③ 更新此 baseline 数字。",
        )


# ============================================================
# R310 marker
# ============================================================
class TestR310MarkerPresent(unittest.TestCase):
    """server_feedback.py 必须保留 R310 marker (或在测试中保留 lineage)"""

    def test_test_file_contains_lineage_explanation(self) -> None:
        """本测试文件 docstring 必须解释 R310 lineage (R298 → R299 → R301 → R310)。"""
        content = _read(Path(__file__))
        self.assertIn("R298", content)
        self.assertIn("R299", content)
        self.assertIn("R310", content)


if __name__ == "__main__":
    unittest.main()
