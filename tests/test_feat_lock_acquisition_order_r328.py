"""R328 · ``notification_manager`` 多锁配对 lock-order invariant
(cycle-35 #B3, v3.9 async race contract 2nd 应用)。

背景
----

cycle-35 #A1 R326 启动了 v3.9 async race contract pattern (锁
task_queue.py 的写锁契约)。R328 是 v3.9 第 2 个应用, 处理另一个 contention
重区: ``notification_manager.py`` 的 **6 个独立 Lock** (``_stats_lock``,
``_queue_lock``, ``_callbacks_lock``, ``_providers_lock``, ``_delayed_
timers_lock``, ``_config_lock``)。

多锁场景的核心风险
-------------------

如果多个线程需要同时持有 2+ 个锁, **必须以一致的顺序 acquire**, 否则会
出现 deadlock cycle:

- Thread A: ``with A: with B:`` (A → B)
- Thread B: ``with B: with A:`` (B → A)
- 互相等对方释放, 永久死锁

``notification_manager`` 用 35+ 处 ``with self._X_lock:``, 任何一处反向嵌
套都会引入潜在 deadlock。R328 invariant 用 **AST 静态分析** 检测:

1. **Layer 1 (Lock anchor)**: 6 个锁全部存在 + 由 ``threading.Lock()`` 创
   建 (非 RLock, 因为不需要 reentry)
2. **Layer 2 (No nested same-lock)**: 不允许 ``with X: with X:`` (会
   self-deadlock, 因为不是 RLock)
3. **Layer 3 (Lock acquisition order consistency)**: 任何两个不同锁 X 和
   Y, 如果存在 nested ``with X: ... with Y:``, 则**不允许**反向 ``with Y:
   ... with X:`` (会形成 deadlock cycle)
4. **Layer 4 (Total lock count guard)**: 锁数量 == 6, 任何新增 lock 必须
   audit (引入新锁前需要 review 其与现有 6 个的 acquisition order)

methodology lineage
-------------------

- v3.9 1st app: R326 (cycle-35 #A1) — task_queue.py 写锁 deadlock-aware
  wrapper contract
- **v3.9 2nd app: R328 (本 commit, cycle-35 #B3)** — notification_manager
  多锁 acquisition order contract

R328 引入 **AST-based 多锁顺序验证**, 是 R326 (单锁 wrapper contract) 的
姐妹技术。R326 关注 "锁是否被正确包装", R328 关注 "多个锁的获取顺序是否
一致"。
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC = REPO_ROOT / "src"
_NOTIFICATION_MANAGER_PY = SRC / "ai_intervention_agent" / "notification_manager.py"


# 6 个 notification_manager 已知锁
EXPECTED_LOCKS = frozenset(
    {
        "_stats_lock",
        "_queue_lock",
        "_callbacks_lock",
        "_providers_lock",
        "_delayed_timers_lock",
        "_config_lock",
    }
)


def _extract_lock_pairs_from_with_stmt(node: ast.AST) -> tuple[str, ...]:
    """从一个 ``with`` 语句节点抽取 ``self._<name>_lock`` 形式的锁名。"""
    locks: list[str] = []
    if isinstance(node, ast.With):
        for item in node.items:
            ctx = item.context_expr
            if (
                isinstance(ctx, ast.Attribute)
                and isinstance(ctx.value, ast.Name)
                and ctx.value.id == "self"
                and ctx.attr.endswith("_lock")
            ):
                locks.append(ctx.attr)
    return tuple(locks)


def _walk_nested_locks(
    tree: ast.AST,
) -> list[tuple[str, ...]]:
    """遍历 AST, 找出所有嵌套的 self.X_lock acquire 序列。

    Returns: list of (outer_lock, inner_lock, ...) 元组, 表示一个 acquire 链。
    """
    chains: list[tuple[str, ...]] = []

    def visit(node: ast.AST, current_chain: tuple[str, ...]) -> None:
        if isinstance(node, ast.With):
            locks = _extract_lock_pairs_from_with_stmt(node)
            new_chain = current_chain + locks
            if len(new_chain) >= 2:
                chains.append(new_chain)
            for child in node.body:
                visit(child, new_chain)
        else:
            for child in ast.iter_child_nodes(node):
                visit(child, current_chain)

    visit(tree, ())
    return chains


class TestLayer1LockAnchor:
    """Layer 1: 6 个锁全部存在 + 类型为 ``threading.Lock()``。"""

    def test_notification_manager_py_exists(self):
        assert _NOTIFICATION_MANAGER_PY.is_file()

    def test_all_six_locks_declared(self, subtests):
        text = _NOTIFICATION_MANAGER_PY.read_text(encoding="utf-8")
        for lock_name in sorted(EXPECTED_LOCKS):
            with subtests.test(lock=lock_name):
                pattern = rf"self\.{re.escape(lock_name)}\s*=\s*threading\.Lock\(\s*\)"
                assert re.search(pattern, text), (
                    f"R328-L1: lock `{lock_name}` must be declared as "
                    f"`self.{lock_name} = threading.Lock()`. RLock not "
                    f"allowed (no reentry needed; if reentry needed, "
                    f"design likely wrong)."
                )

    def test_no_rlock_used(self):
        """R328-L1: 不允许 ``threading.RLock`` (我们的设计原则: 显式 lock
        order > 隐式 reentry)。"""
        text = _NOTIFICATION_MANAGER_PY.read_text(encoding="utf-8")
        # Strip docstring 防止误匹配
        text_no_docs = re.sub(r'"""[\s\S]*?"""', "", text)
        rlock_uses = re.findall(r"threading\.RLock\(\)", text_no_docs)
        assert len(rlock_uses) == 0, (
            f"R328-L1: notification_manager.py uses threading.RLock {len(rlock_uses)} "
            f"times. RLock allows reentry which hides lock-order bugs. "
            f"Use threading.Lock + explicit ordering instead."
        )


class TestLayer2NoNestedSameLock:
    """Layer 2: 不允许 ``with self.X_lock: with self.X_lock:`` (会
    self-deadlock 因为不是 RLock)。"""

    def test_no_self_nested_acquisition(self, subtests):
        text = _NOTIFICATION_MANAGER_PY.read_text(encoding="utf-8")
        tree = ast.parse(text)
        chains = _walk_nested_locks(tree)

        # 检查任何 chain 内, 是否有重复锁名 (self-deadlock 风险)
        for chain in chains:
            with subtests.test(chain=" → ".join(chain)):
                # chain 元素必须互不相同
                seen: set[str] = set()
                for lock in chain:
                    assert lock not in seen, (
                        f"R328-L2: self-deadlock risk! chain `{chain}` "
                        f"acquires `{lock}` twice. threading.Lock is "
                        f"non-reentrant — same thread re-acquiring same "
                        f"lock will deadlock. Refactor to acquire only "
                        f"once, or use RLock (not recommended)."
                    )
                    seen.add(lock)


class TestLayer3LockAcquisitionOrderConsistency:
    """Layer 3: 任何两锁 X / Y, 如果存在 ``with X: ... with Y:`` 嵌套, 则
    **不允许**反向 ``with Y: ... with X:`` (会形成 deadlock cycle)。"""

    def test_no_reverse_lock_acquisition_order(self, subtests):
        text = _NOTIFICATION_MANAGER_PY.read_text(encoding="utf-8")
        tree = ast.parse(text)
        chains = _walk_nested_locks(tree)

        # 收集所有 (outer, inner) 对
        edges: set[tuple[str, str]] = set()
        for chain in chains:
            for i in range(len(chain)):
                for j in range(i + 1, len(chain)):
                    edges.add((chain[i], chain[j]))

        # 检查反向边
        for outer, inner in sorted(edges):
            reverse = (inner, outer)
            with subtests.test(forward=f"{outer} → {inner}"):
                assert reverse not in edges, (
                    f"R328-L3: DEADLOCK CYCLE detected! Found both:\n"
                    f"  forward: `with self.{outer}: ... with self.{inner}:`\n"
                    f"  reverse: `with self.{inner}: ... with self.{outer}:`\n"
                    f"Two threads taking these in opposite order will "
                    f"deadlock. Pick a canonical acquisition order and "
                    f"document in source."
                )


class TestLayer4LockCountGuard:
    """Layer 4: 锁数量 == 6, 任何新增 lock 必须 audit。"""

    def test_lock_count_exactly_matches_expected(self):
        text = _NOTIFICATION_MANAGER_PY.read_text(encoding="utf-8")
        # 找所有 self._X_lock = threading.Lock()
        declared = set(
            re.findall(
                r"self\.(_\w+_lock)\s*=\s*threading\.Lock\(\s*\)",
                text,
            )
        )
        assert declared == EXPECTED_LOCKS, (
            f"R328-L4: lock count drift detected!\n"
            f"  expected: {sorted(EXPECTED_LOCKS)}\n"
            f"  declared: {sorted(declared)}\n"
            f"  added:    {sorted(declared - EXPECTED_LOCKS)}\n"
            f"  removed:  {sorted(EXPECTED_LOCKS - declared)}\n"
            f"**Action** for new lock:\n"
            f"  1. Document its acquisition order vs existing 6 locks\n"
            f"  2. Audit all `with self.<NEW>_lock:` for nested chains\n"
            f"  3. Update EXPECTED_LOCKS in R328 invariant"
        )


class TestR328LineageMarker:
    """R328 是 v3.9 async race contract 2nd app, AST-based 多锁顺序验证。"""

    def test_this_file_contains_r328_marker(self):
        text = Path(__file__).read_text(encoding="utf-8")
        assert "R328" in text

    def test_this_file_marks_v3_9_2nd_app(self):
        text = Path(__file__).read_text(encoding="utf-8")
        assert "v3.9" in text
        assert "2nd" in text.lower() or "第 2" in text

    def test_this_file_references_r326_prior_app(self):
        text = Path(__file__).read_text(encoding="utf-8")
        assert "R326" in text, "R328: must cite R326 (v3.9 1st app)"

    def test_this_file_documents_4_layers(self):
        text = Path(__file__).read_text(encoding="utf-8")
        for kw in (
            "Layer 1",
            "Layer 2",
            "Layer 3",
            "Layer 4",
            "AST",
            "deadlock",
            "acquisition order",
        ):
            assert kw in text, f"R328: missing keyword: {kw!r}"
