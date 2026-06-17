"""R352 · module-level cache reset audit invariant (cycle-39 #C2,
v3.8 test-isolation **6th 应用 (跨域)**)。

test-isolation 系列累计应用
---------------------------

- R316 (cycle-33 #A1): NotificationHealthStreak flake fix (1st)
- R319 (cycle-33 #A2): ``_create_test_instance()`` helper (2nd)
- R323 (cycle-34 #B2): NotificationManager.reset_for_testing() (3rd)
- R324 (cycle-34 #D):  web_ui_config_sync lazy-load (4th 跨域)
- R325 (cycle-34 #E):  service_manager lazy-load (5th 跨域)
- **R352 (本 commit, cycle-39)**: module-level cache reset helpers
  for ``_BUILD_INFO_CACHE`` + ``_FEEDBACK_COUNTERS`` (6th 跨域)

R352 修复的真实问题
-------------------

1. ``server.py:_BUILD_INFO_CACHE`` (dict) — 一旦填充就在进程生命周期内
   不刷, 测试 mock subprocess 后无法 reset cache, mock 的返回值不会被
   读取
2. ``server_feedback.py:_FEEDBACK_COUNTERS`` (dict[str, int]) — 累计型
   counter, 跨测试不归零会污染断言

修复方式
--------

- 给两处分别新增 ``reset_*_for_testing()`` helper
- 本 invariant 锁定 helper 存在 + 行为正确 + future-guard (新增其他
  module-level cache 时强制审查)

R352 invariant (5 层)
---------------------

1. **Layer 1 (Existence)**: 两个 reset helper 都存在且可调用
2. **Layer 2 (Behavior)**: 调用 reset 后, cache 内容真的被清空 / 归零
3. **Layer 3 (Idempotency)**: 重复调用 reset 安全, 不抛异常
4. **Layer 4 (Future-guard)**: 任何 ``src/ai_intervention_agent/*.py``
   内新增 module-level mutable cache (符合特定 pattern) 都必须有
   reset helper, 否则触发 audit 失败
5. **Layer 5 (Lineage)**: R352 必须 cite 前 5 个 test-isolation 应用
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = REPO_ROOT / "src" / "ai_intervention_agent"

# 已知有 reset helper 的 module-level cache (whitelist)
KNOWN_CACHES_WITH_RESET: dict[str, tuple[str, str]] = {
    "_BUILD_INFO_CACHE": (
        "server.py",
        "reset_build_info_cache_for_testing",
    ),
    "_FEEDBACK_COUNTERS": (
        "server_feedback.py",
        "reset_feedback_counters_for_testing",
    ),
    "_sse_stats_cache": (
        "server.py",
        "reset_sse_stats_cache_for_testing",
    ),
    "_recent_logs_cache": (
        "server.py",
        "reset_recent_logs_cache_for_testing",
    ),
    "_config_cache": (
        "service_manager.py",
        "reset_config_cache_for_testing",
    ),
    "_latency_state": (
        "mcp_tool_call_metrics.py",
        "reset_mcp_tool_call_stats",  # 已存在 (R190)
    ),
}

# 不需要 reset 的 module-level state (frozen / immutable / lookup-only /
# 自动清理)
EXEMPT_MODULE_STATE: set[str] = {
    "_MESSAGES",  # i18n.py, frozen lookup dict, never mutated at runtime
    "_MD_EXTENSIONS",  # web_ui.py, list of markdown extension config
    "_MD_EXTENSION_CONFIGS",  # web_ui.py, frozen config dict
    "_LIMIT_SECONDS",  # web_ui_rate_limiter.py, MappingProxyType frozen lookup map
    "_SERVER_ICONS",  # server.py, computed at import then frozen
    "_pending_acquisitions",  # task_queue.py, transient request-tracking,
    # 函数返回前 try/finally 会 pop
}


class TestLayer1ResetHelpersExist:
    """Layer 1: 两个 reset helper 都存在且可调用。"""

    def test_reset_build_info_cache_helper_exists(self):
        from ai_intervention_agent.server import (
            reset_build_info_cache_for_testing,
        )

        assert callable(reset_build_info_cache_for_testing)

    def test_reset_feedback_counters_helper_exists(self):
        from ai_intervention_agent.server_feedback import (
            reset_feedback_counters_for_testing,
        )

        assert callable(reset_feedback_counters_for_testing)


class TestLayer2ResetBehavior:
    """Layer 2: reset 后 cache 内容真的被清空。"""

    def test_reset_build_info_cache_clears(self):
        from ai_intervention_agent import server

        # 先填充 cache
        server._BUILD_INFO_CACHE["test_key"] = "test_value"
        assert server._BUILD_INFO_CACHE.get("test_key") == "test_value"

        # reset 后清空
        server.reset_build_info_cache_for_testing()
        assert server._BUILD_INFO_CACHE == {}, (
            f"R352-L2: _BUILD_INFO_CACHE not fully cleared after reset: "
            f"{server._BUILD_INFO_CACHE}"
        )

    def test_reset_feedback_counters_zeros(self):
        from ai_intervention_agent import server_feedback

        server_feedback._FEEDBACK_COUNTERS["created_total"] = 99
        server_feedback._FEEDBACK_COUNTERS["completed_total"] = 50

        server_feedback.reset_feedback_counters_for_testing()
        assert server_feedback._FEEDBACK_COUNTERS["created_total"] == 0
        assert server_feedback._FEEDBACK_COUNTERS["completed_total"] == 0


class TestLayer3ResetIdempotency:
    """Layer 3: 重复调用 reset 安全 (不抛异常, 不改变 already-reset 状态)。"""

    def test_reset_build_info_cache_idempotent(self):
        from ai_intervention_agent import server

        server.reset_build_info_cache_for_testing()
        server.reset_build_info_cache_for_testing()
        server.reset_build_info_cache_for_testing()
        assert server._BUILD_INFO_CACHE == {}

    def test_reset_feedback_counters_idempotent(self):
        from ai_intervention_agent import server_feedback

        server_feedback.reset_feedback_counters_for_testing()
        server_feedback.reset_feedback_counters_for_testing()
        server_feedback.reset_feedback_counters_for_testing()
        assert all(v == 0 for v in server_feedback._FEEDBACK_COUNTERS.values())


class TestLayer4FutureGuardModuleLevelCacheAudit:
    """Layer 4: 静态分析 ``src/ai_intervention_agent/*.py`` 内 module-level
    可变 dict / list cache, 强制每个都有对应 reset helper 或在豁免名单
    内。"""

    @staticmethod
    def _find_module_level_caches(
        source: str,
    ) -> list[tuple[str, str]]:
        """返回 ``[(var_name, init_repr), ...]`` for top-level mutable
        cache assignments matching pattern ``_NAME_CACHE`` or
        ``_NAME_COUNTERS``."""
        tree = ast.parse(source)
        results: list[tuple[str, str]] = []
        for node in tree.body:
            if isinstance(node, (ast.Assign, ast.AnnAssign)):
                targets = (
                    node.targets if isinstance(node, ast.Assign) else [node.target]
                )
                for tgt in targets:
                    if not isinstance(tgt, ast.Name):
                        continue
                    name = tgt.id
                    if not name.startswith("_"):
                        continue
                    # __all__ 是 Python export convention, 不是 cache
                    if name == "__all__":
                        continue
                    # 关注 pattern: dict / list / set 初始化
                    value = node.value
                    if value is None:
                        continue
                    if isinstance(value, (ast.Dict, ast.List, ast.Set)):
                        results.append((name, ast.dump(value)[:40]))
        return results

    def test_every_module_level_cache_has_reset_or_exempt(self, subtests):
        offenders: list[str] = []
        for py_file in sorted(SRC_DIR.glob("*.py")):
            if py_file.name == "__init__.py":
                continue
            text = py_file.read_text(encoding="utf-8")
            caches = self._find_module_level_caches(text)
            for name, _repr in caches:
                with subtests.test(file=py_file.name, var=name):
                    if name in KNOWN_CACHES_WITH_RESET:
                        # 已知有 reset, 验证 reset 函数也在该文件
                        expected_file, expected_fn = KNOWN_CACHES_WITH_RESET[name]
                        if py_file.name == expected_file:
                            assert expected_fn in text, (
                                f"R352-L4: {name} declared in "
                                f"{py_file.name} but reset helper "
                                f"{expected_fn!r} not found in file"
                            )
                        continue
                    if name in EXEMPT_MODULE_STATE:
                        continue
                    offenders.append(f"{py_file.name}:{name}")
        if offenders:
            raise AssertionError(
                "R352-L4: module-level mutable cache without reset "
                "helper or exemption:\n  "
                + "\n  ".join(offenders)
                + "\nFix: either add a reset_*_for_testing() helper and "
                "register it in KNOWN_CACHES_WITH_RESET, or add the "
                "variable name to EXEMPT_MODULE_STATE with a comment "
                "explaining why it's frozen / immutable."
            )


class TestR352LineageMarker:
    def test_this_file_contains_r352_marker(self):
        text = Path(__file__).read_text(encoding="utf-8")
        assert "R352" in text

    def test_this_file_references_test_isolation_lineage(self):
        text = Path(__file__).read_text(encoding="utf-8")
        for prior in ("R316", "R319", "R323", "R324", "R325"):
            assert prior in text, f"R352: must cite test-isolation lineage: {prior}"

    def test_this_file_marks_sixth_application(self):
        text = Path(__file__).read_text(encoding="utf-8")
        for kw in ("6th 应用", "test-isolation"):
            assert kw in text, f"R352: missing keyword: {kw!r}"
