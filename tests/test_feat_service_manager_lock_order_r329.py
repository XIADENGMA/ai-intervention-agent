"""R329 · ``service_manager`` 模块级锁 lock-order invariant
(cycle-35 #A2, v3.9 async race contract 3rd 应用)。

背景
----

继 R326 (task_queue 写锁 wrapper, v3.9 #1) 和 R328 (notification_manager 6
锁 acquisition order, v3.9 #2), R329 是 v3.9 第 3 个应用, 处理
``service_manager.py`` 的 **3 个 module-level Lock**:

- ``_http_client_lock`` — 保护 ``_async_client`` / ``_sync_client``
  singleton + connection pool
- ``_config_cache_lock`` — 保护 ``_cached_config`` 单例 + LRU 缓存
- ``_config_callbacks_lock`` — 保护 callback 注册标志

与 R328 (instance-level ``self.X_lock``) 不同, R329 处理 **module-level
``X_lock``** (无 ``self.`` 前缀), 验证策略相同但 AST 提取规则不同。

R329 invariant (4 层)
---------------------

1. **Layer 1 (Anchor)**: 3 个 module-level lock 全部用 ``threading.Lock()``
   (非 RLock) 声明
2. **Layer 2 (No nested same-lock)**: 不允许 ``with X: with X:`` (会
   self-deadlock 因为非 RLock)
3. **Layer 3 (Lock acquisition order consistency)**: 任何 2 锁 X / Y, 不
   允许同时存在 ``with X: with Y:`` 和反向 ``with Y: with X:``
   (deadlock cycle guard)
4. **Layer 4 (Lock count guard)**: 锁数量 == 3, 新增 lock 强制 audit

methodology lineage
-------------------

- v3.9 1st app: R326 (cycle-35 #A1) — task_queue 写锁 wrapper contract
- v3.9 2nd app: R328 (cycle-35 #B3) — notification_manager 6 instance lock
  AST-based acquisition order
- **v3.9 3rd app: R329 (本 commit, cycle-35 #A2)** — service_manager 3
  module-level lock AST-based acquisition order

R329 完成意味着 **v3.9 async race contract pattern 达 3 应用工业化阈值**,
与 v3.7 (decision-three-layer) / v3.8 (idempotent / test-isolation) 看齐。
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC = REPO_ROOT / "src"
_SERVICE_MANAGER_PY = SRC / "ai_intervention_agent" / "service_manager.py"

EXPECTED_LOCKS = frozenset(
    {
        "_http_client_lock",
        "_config_cache_lock",
        "_config_callbacks_lock",
    }
)


def _extract_module_locks_from_with_stmt(node: ast.AST) -> tuple[str, ...]:
    """从一个 ``with`` 语句节点抽取 module-level ``X_lock`` 锁名 (无
    ``self.`` / ``cls.`` 前缀)。"""
    locks: list[str] = []
    if isinstance(node, ast.With):
        for item in node.items:
            ctx = item.context_expr
            if isinstance(ctx, ast.Name) and ctx.id.endswith("_lock"):
                locks.append(ctx.id)
    return tuple(locks)


def _walk_nested_module_locks(tree: ast.AST) -> list[tuple[str, ...]]:
    chains: list[tuple[str, ...]] = []

    def visit(node: ast.AST, current_chain: tuple[str, ...]) -> None:
        if isinstance(node, ast.With):
            locks = _extract_module_locks_from_with_stmt(node)
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
    def test_service_manager_exists(self):
        assert _SERVICE_MANAGER_PY.is_file()

    def test_all_three_locks_declared(self, subtests):
        text = _SERVICE_MANAGER_PY.read_text(encoding="utf-8")
        for name in sorted(EXPECTED_LOCKS):
            with subtests.test(lock=name):
                pattern = rf"^{re.escape(name)}\s*=\s*threading\.Lock\(\s*\)"
                assert re.search(pattern, text, re.MULTILINE), (
                    f"R329-L1: module-level lock `{name}` must be "
                    f"declared as `{name} = threading.Lock()`"
                )

    def test_no_rlock_at_module_level(self):
        text = _SERVICE_MANAGER_PY.read_text(encoding="utf-8")
        text_no_docs = re.sub(r'"""[\s\S]*?"""', "", text)
        # match module-level RLock 声明
        rlock_decls = re.findall(
            r"^_\w+\s*=\s*threading\.RLock\(\)",
            text_no_docs,
            re.MULTILINE,
        )
        assert len(rlock_decls) == 0, (
            f"R329-L1: service_manager.py uses module-level RLock "
            f"{len(rlock_decls)} times. Design principle: explicit lock "
            f"order > implicit reentry."
        )


class TestLayer2NoNestedSameLock:
    def test_no_self_nested_acquisition(self, subtests):
        text = _SERVICE_MANAGER_PY.read_text(encoding="utf-8")
        tree = ast.parse(text)
        chains = _walk_nested_module_locks(tree)

        for chain in chains:
            with subtests.test(chain=" → ".join(chain)):
                seen: set[str] = set()
                for lock in chain:
                    assert lock not in seen, (
                        f"R329-L2: self-deadlock risk! chain `{chain}` "
                        f"acquires `{lock}` twice (threading.Lock "
                        f"non-reentrant)."
                    )
                    seen.add(lock)


class TestLayer3LockAcquisitionOrderConsistency:
    def test_no_reverse_lock_acquisition_order(self, subtests):
        text = _SERVICE_MANAGER_PY.read_text(encoding="utf-8")
        tree = ast.parse(text)
        chains = _walk_nested_module_locks(tree)

        edges: set[tuple[str, str]] = set()
        for chain in chains:
            for i in range(len(chain)):
                for j in range(i + 1, len(chain)):
                    edges.add((chain[i], chain[j]))

        for outer, inner in sorted(edges):
            reverse = (inner, outer)
            with subtests.test(forward=f"{outer} → {inner}"):
                assert reverse not in edges, (
                    f"R329-L3: DEADLOCK CYCLE detected!\n"
                    f"  forward: `with {outer}: ... with {inner}:`\n"
                    f"  reverse: `with {inner}: ... with {outer}:`"
                )


class TestLayer4LockCountGuard:
    def test_lock_count_exactly_matches_expected(self):
        text = _SERVICE_MANAGER_PY.read_text(encoding="utf-8")
        declared = set(
            re.findall(
                r"^(_\w+_lock)\s*=\s*threading\.Lock\(\s*\)",
                text,
                re.MULTILINE,
            )
        )
        assert declared == EXPECTED_LOCKS, (
            f"R329-L4: module lock count drift!\n"
            f"  expected: {sorted(EXPECTED_LOCKS)}\n"
            f"  declared: {sorted(declared)}\n"
            f"  added:    {sorted(declared - EXPECTED_LOCKS)}\n"
            f"  removed:  {sorted(EXPECTED_LOCKS - declared)}\n"
            f"**Action** for new lock:\n"
            f"  1. Document its acquisition order vs existing locks\n"
            f"  2. Audit nested `with` chains\n"
            f"  3. Update EXPECTED_LOCKS in R329"
        )


class TestR329LineageMarker:
    """R329 是 v3.9 async race contract 3rd app, 标志 v3.9 达 3 应用工业化
    阈值。"""

    def test_this_file_contains_r329_marker(self):
        text = Path(__file__).read_text(encoding="utf-8")
        assert "R329" in text

    def test_this_file_marks_v3_9_3rd_app(self):
        text = Path(__file__).read_text(encoding="utf-8")
        assert "v3.9" in text
        assert "3rd" in text.lower() or "第 3" in text

    def test_this_file_references_prior_v3_9_apps(self):
        text = Path(__file__).read_text(encoding="utf-8")
        for prior in ("R326", "R328"):
            assert prior in text, f"R329: must cite prior v3.9 app: {prior}"

    def test_this_file_documents_4_layers_and_module_level_distinction(self):
        text = Path(__file__).read_text(encoding="utf-8")
        for kw in (
            "Layer 1",
            "Layer 2",
            "Layer 3",
            "Layer 4",
            "module-level",
            "工业化阈值",
        ):
            assert kw in text, f"R329: missing keyword: {kw!r}"
