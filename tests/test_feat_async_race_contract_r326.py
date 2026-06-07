"""R326 · ``task_queue.py`` async race contract invariant
(v3.9 第 1 个新 pattern 启动)。

背景 — 为什么需要 async race contract
----------------------------------------

cycle-34 完成 v3.7 + v3.8 全 pattern 完全工业化, 但 codebase 中并发 / 锁
相关的 contract 仍然只在**字面量 (R315/R321)** 或 **决策记录** 层 lock。
真正的运行时 contract — "哪些操作必须用 deadlock-aware wrapper / 哪些操
作允许直接 lock" — 还没有 invariant 保护。

R326 启动 v3.9 新 pattern: **async race contract invariant**, 专门锁定并
发原语 (Lock / RLock / ReadWriteLock / asyncio.Lock) 的**使用契约**, 而
不只是数字或决策。

R326 起步选 task_queue.py
---------------------------

``task_queue.py`` 是 codebase 中 contention 最重的 module (R315 锁了相关
prompt size guard + lock watchdog 常量, R321 lock 了 watchdog timeout 决
策)。它有非常清晰的设计:

1. 自定义 ``ReadWriteLock`` (多读单写 + RLock 实现)
2. 写操作必须通过 ``_watched_write_lock(self._lock, label)`` deadlock-aware
   wrapper, **不允许直接** ``self._lock.write_lock()``
3. ``_lock_watchdog_loop`` daemon 监控所有 wrapper, 超 timeout dump 全栈
4. 读操作可以直接 ``self._lock.read_lock()`` (不需要 watchdog 因为多读
   并发)

R326 invariant 锁定:

1. **Layer 1 (Wrapper anchor)**: ``_watched_write_lock`` context manager
   存在 + 注册到 ``_pending_acquisitions`` + 调用 ``_ensure_lock_watchdog_
   started()``
2. **Layer 2 (Write call site)**: ``self._lock.write_lock()`` **只**出现
   在 ``_watched_write_lock`` 函数内 (1 site total), 否则任何直接调用都
   是 contract 违反
3. **Layer 3 (Wrapper usage count)**: ``_watched_write_lock(self._lock,
   label)`` 用法 >= 8 个 (实际 11), 防止意外删除导致 watchdog 失效
4. **Layer 4 (Each write needs label)**: 每个 ``_watched_write_lock`` 调
   用必须传 label string (deadlock dump 时识别哪个 critical section)
5. **Layer 5 (Read & write parity)**: ``read_lock`` 与 ``write_lock`` 都
   通过 with-statement 调用, 不允许 raw acquire/release 模式 (会 leak)

methodology lineage
-------------------

R326 是 v3.9 系列**第 1 个**新 pattern (async race contract), 起步意味着
未来 R-series 可以继续应用此 pattern 到其他并发场景:

- 2nd app 候选: ``notification_manager`` 的 ``_stats_lock`` /
  ``_providers_lock`` / ``_queue_lock`` 互相调用关系 (避免死锁)
- 3rd app 候选: ``service_manager`` 的 ``_http_client_lock`` 配对
- 4th+: HTTP 路由 + asyncio 任务的 race condition contract

**v3.9 pattern 类别**: contract / 静态分析驱动 invariant (与 v3.7
decision-three-layer / v3.8 idempotent endpoint 互补, 后者偏 "决策 +
docstring" 层)。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC = REPO_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

_TASK_QUEUE_PY = SRC / "ai_intervention_agent" / "task_queue.py"


class TestLayer1WrapperAnchor:
    """Layer 1: ``_watched_write_lock`` 必须存在, 且包含 watchdog 注册 +
    daemon 启动。"""

    def test_task_queue_py_exists(self):
        assert _TASK_QUEUE_PY.is_file()

    def test_watched_write_lock_function_defined(self):
        text = _TASK_QUEUE_PY.read_text(encoding="utf-8")
        assert "def _watched_write_lock(" in text, (
            "R326 anchor: _watched_write_lock function must exist"
        )

    def test_watched_write_lock_is_context_manager(self):
        text = _TASK_QUEUE_PY.read_text(encoding="utf-8")
        m = re.search(
            r"(@contextmanager\s*\n\s*)?def\s+_watched_write_lock\s*\(",
            text,
        )
        assert m, "R326-L1: _watched_write_lock function not found"
        # 抓取 30 行 context 之前
        idx = text.index("def _watched_write_lock(")
        before = text[max(0, idx - 100) : idx]
        assert "@contextmanager" in before, (
            "R326-L1: _watched_write_lock must be decorated with "
            "@contextmanager (so callers can use `with ...:` syntax)"
        )

    def test_watched_write_lock_registers_pending_acquisition(self):
        text = _TASK_QUEUE_PY.read_text(encoding="utf-8")
        m = re.search(
            r"def\s+_watched_write_lock\s*\([^)]*\)[^:]*:\s*\n"
            r"(?P<body>.*?)(?=\n(?:def\s+|class\s+|@|\Z))",
            text,
            re.DOTALL,
        )
        assert m, "R326-L1: cannot locate _watched_write_lock body"
        body = m.group("body")

        assert "_pending_acquisitions" in body, (
            "R326-L1: _watched_write_lock must register call into "
            "_pending_acquisitions for watchdog visibility"
        )
        assert "_pending_acquisitions_lock" in body, (
            "R326-L1: _watched_write_lock must hold "
            "_pending_acquisitions_lock when mutating registry"
        )

    def test_watched_write_lock_starts_watchdog_daemon(self):
        text = _TASK_QUEUE_PY.read_text(encoding="utf-8")
        m = re.search(
            r"def\s+_watched_write_lock\s*\([^)]*\)[^:]*:\s*\n"
            r"(?P<body>.*?)(?=\n(?:def\s+|class\s+|@|\Z))",
            text,
            re.DOTALL,
        )
        assert m
        body = m.group("body")
        assert "_ensure_lock_watchdog_started()" in body, (
            "R326-L1: _watched_write_lock must call "
            "_ensure_lock_watchdog_started() to lazy-start the watchdog daemon"
        )

    def test_watched_write_lock_uses_try_finally(self):
        """R326-L1: 必须 try/finally 保证 ``_pending_acquisitions`` 中的
        record 即使 yield 抛异常也能被 pop 掉, 否则 watchdog 会误报。"""
        text = _TASK_QUEUE_PY.read_text(encoding="utf-8")
        m = re.search(
            r"def\s+_watched_write_lock\s*\([^)]*\)[^:]*:\s*\n"
            r"(?P<body>.*?)(?=\n(?:def\s+|class\s+|@|\Z))",
            text,
            re.DOTALL,
        )
        assert m
        body = m.group("body")
        assert "try:" in body and "finally:" in body, (
            "R326-L1: _watched_write_lock must use try/finally to guarantee "
            "_pending_acquisitions cleanup even on exception"
        )


class TestLayer2WriteCallSiteRestriction:
    """Layer 2: ``self._lock.write_lock()`` raw 调用**只**允许出现在
    ``_watched_write_lock`` 函数内 (1 site total), 不允许其他地方直接调用。"""

    def test_write_lock_raw_call_appears_exactly_once(self):
        text = _TASK_QUEUE_PY.read_text(encoding="utf-8")
        # 去掉 triple-quoted docstrings 防止匹配示例代码 / docstring 引用
        text_no_docs = re.sub(
            r'"""[\s\S]*?"""',
            "",
            text,
        )
        # 计数所有 `<obj>.write_lock()` 直接调用 (排除 docstring)
        raw_calls = re.findall(r"\w+\.write_lock\(\s*\)", text_no_docs)
        # 但允许 _watched_write_lock 自身的实现, 其他 site 必须为 0
        assert len(raw_calls) == 1, (
            f"R326-L2: expected exactly 1 raw write_lock() call (inside "
            f"_watched_write_lock implementation), found {len(raw_calls)}: "
            f"{raw_calls}. All write operations must go through "
            f"_watched_write_lock(self._lock, label) wrapper for "
            f"deadlock-aware watchdog coverage."
        )

    def test_only_write_lock_call_is_inside_wrapper(self):
        """验证那唯一的 ``write_lock()`` 调用确实在 ``_watched_write_lock``
        函数内。"""
        text = _TASK_QUEUE_PY.read_text(encoding="utf-8")
        wrapper_m = re.search(
            r"def\s+_watched_write_lock\s*\([^)]*\)[^:]*:\s*\n"
            r"(?P<body>.*?)(?=\n(?:def\s+|class\s+|@|\Z))",
            text,
            re.DOTALL,
        )
        assert wrapper_m
        wrapper_body = wrapper_m.group("body")
        assert re.search(r"\w+\.write_lock\(\s*\)", wrapper_body), (
            "R326-L2: _watched_write_lock body must contain the single "
            "raw write_lock() invocation"
        )


class TestLayer3WrapperUsageCount:
    """Layer 3: ``_watched_write_lock(self._lock, label)`` 必须有足够多
    使用 site (>=8), 防止退化或意外删除。"""

    def test_wrapper_usage_count_meets_minimum(self):
        text = _TASK_QUEUE_PY.read_text(encoding="utf-8")
        usage = re.findall(
            r"with\s+_watched_write_lock\s*\(\s*self\._lock\s*,\s*['\"]([^'\"]+)['\"]\s*\)",
            text,
        )
        assert len(usage) >= 8, (
            f"R326-L3: expected >=8 _watched_write_lock(self._lock, label) "
            f"usage sites, found {len(usage)}. Labels: {usage}. If you "
            f"reduced lock-protected paths, audit which write operations "
            f"now run lockless."
        )

    def test_known_write_operations_use_wrapper(self):
        """关键写操作必须用 wrapper: add_task / complete_task / remove_task /
        set_active_task / extend_task_deadline。"""
        text = _TASK_QUEUE_PY.read_text(encoding="utf-8")
        required = (
            "add_task",
            "complete_task",
            "remove_task",
            "set_active_task",
            "extend_task_deadline",
        )
        for label in required:
            pattern = rf'with\s+_watched_write_lock\s*\(\s*self\._lock\s*,\s*["\']({label})["\']\s*\)'
            assert re.search(pattern, text), (
                f"R326-L3: required write operation `{label}` must use "
                f"_watched_write_lock(self._lock, '{label}') wrapper. "
                f"Without it, deadlock in {label} won't be detected."
            )


class TestLayer4LabelRequirement:
    """Layer 4: 每个 ``_watched_write_lock`` 调用必须传 label string, 不
    允许 None / 空字符串 / 变量。"""

    def test_every_call_has_string_literal_label(self):
        text = _TASK_QUEUE_PY.read_text(encoding="utf-8")
        # 找出所有 _watched_write_lock(self._lock, ???) 调用
        all_calls = re.findall(
            r"with\s+_watched_write_lock\s*\(\s*self\._lock\s*,\s*([^)]+)\)",
            text,
        )
        for arg in all_calls:
            arg_stripped = arg.strip().rstrip(",").strip()
            # label 必须是 string literal "..." 或 '...'
            assert re.match(r"^['\"][^'\"]+['\"]$", arg_stripped), (
                f"R326-L4: _watched_write_lock label must be string "
                f"literal, got: {arg_stripped!r}. Watchdog dump relies on "
                f"label being constant string for grep-ability."
            )


class TestLayer5ReadWriteParity:
    """Layer 5: ``read_lock`` / ``write_lock`` 都必须通过 ``with`` 语句调
    用, 不允许 raw ``acquire()`` / ``release()`` 配对模式 (会 leak)。"""

    def test_no_raw_acquire_release_on_self_lock(self):
        """task_queue.py 不应有 ``self._lock.read_lock().acquire()`` 或
        ``self._lock.write_lock().acquire()`` 之类 raw 模式。"""
        text = _TASK_QUEUE_PY.read_text(encoding="utf-8")
        for bad in (
            r"\.read_lock\(\)\.acquire",
            r"\.write_lock\(\)\.acquire",
            r"\.read_lock\(\)\.release",
            r"\.write_lock\(\)\.release",
        ):
            assert not re.search(bad, text), (
                f"R326-L5: forbidden raw acquire/release pattern matched "
                f"`{bad}`. All RWLock usage must be via `with` statement to "
                f"prevent lock leak on exception."
            )

    def test_read_lock_calls_use_with_statement(self):
        text = _TASK_QUEUE_PY.read_text(encoding="utf-8")
        # 所有 read_lock() 调用都应该出现在 with statement 中
        read_lock_total = len(re.findall(r"self\._lock\.read_lock\(\s*\)", text))
        read_lock_in_with = len(
            re.findall(r"with\s+self\._lock\.read_lock\(\s*\)", text)
        )
        assert read_lock_total == read_lock_in_with, (
            f"R326-L5: all self._lock.read_lock() calls must be in `with` "
            f"statement (found {read_lock_in_with} `with` vs {read_lock_total} "
            f"total). raw call without `with` leaks lock on exception."
        )


class TestR326LineageMarker:
    """R326 是 v3.9 系列第 1 个新 pattern (async race contract)。"""

    def test_this_file_contains_r326_marker(self):
        text = Path(__file__).read_text(encoding="utf-8")
        assert "R326" in text
        assert "async race contract" in text.lower()

    def test_this_file_marks_v3_9_launch(self):
        text = Path(__file__).read_text(encoding="utf-8")
        assert "v3.9" in text, "R326: must mark as v3.9 pattern launch"
        assert "第 1 个新 pattern" in text or "1st" in text.lower(), (
            "R326: must mark as 1st app of v3.9 async race contract"
        )

    def test_this_file_references_prior_methodology(self):
        text = Path(__file__).read_text(encoding="utf-8")
        for prior in ("R315", "R321"):
            assert prior in text, (
                f"R326: must cite prior concurrent-related work: {prior}"
            )

    def test_this_file_documents_5_layers(self):
        text = Path(__file__).read_text(encoding="utf-8")
        for layer_kw in (
            "Layer 1",
            "Layer 2",
            "Layer 3",
            "Layer 4",
            "Layer 5",
            "_watched_write_lock",
            "ReadWriteLock",
        ):
            assert layer_kw in text, (
                f"R326: documentation missing keyword: {layer_kw!r}"
            )
