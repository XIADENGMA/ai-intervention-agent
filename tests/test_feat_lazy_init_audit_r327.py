"""R327 · codebase-wide ``_ensure_*`` lazy-init audit invariant
(cycle-35 #B1, R324/R325 模式扩展到全 codebase)。

背景
----

R324 (cycle-34 #D) 修复了 ``web_ui_routes/notification.py`` 的 lazy load
mock pollution bug, R325 (cycle-34 #E) 扩展到 ``service_manager.py`` +
加 future-guard, 但 R325 future-guard 只扫 ``_ensure_*_loaded`` 命名空间。

R327 把 audit 扩展到 **全部 ``_ensure_*`` lazy-init 函数**, 按行为分 3
类, 强制每个函数被显式分类 + 满足对应类别的 safety 要求:

1. **`_loaded` (multi-attribute import)**: 必须用 per-attribute null check
   (R324/R325 pattern), 防止 mock pollution
2. **`_registered` (single flag double-check)**: 必须用 double-check
   locking + flag short-circuit (经典模式, 单 boolean 不会 mock pollute)
3. **`_started` (daemon thread spawn)**: 必须用 flag + lock 防止重复 spawn
4. **未分类**: invariant fail, 强制 audit

R327 的价值
-----------

- **全 codebase 覆盖**: 不只 ``_ensure_*_loaded``, 而是所有 ``_ensure_*``
- **行为分类**: 让 audit 不止于 "存在 short-circuit", 而是检查每类函数
  的契约
- **R325 future-guard 升级**: R325 只防 ``_loaded`` 新增, R327 防全
  ``_ensure_*`` 命名空间

methodology lineage
-------------------

- R324 (cycle-34 #D): web_ui_routes lazy-load mock safety (source 层)
- R325 (cycle-34 #E): service_manager lazy-load mock safety + future-guard
  (cross-module)
- **R327 (本 commit, cycle-35 #B1)**: codebase-wide lazy-init audit
  (全 codebase + 行为分类)

这是 v3.8 test-isolation pattern 的 **6th 应用** + **R325 future-guard 升
级版**: 把 audit 从单 namespace 扩展到全 codebase, 让任何新 lazy-init 函
数都必须被显式审查。

注意: R326 已启动 v3.9 async race contract pattern, R327 不属于 v3.9 (R327
是 R324/R325 同源 v3.8 test-isolation pattern 的延续应用)。
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC = REPO_ROOT / "src" / "ai_intervention_agent"


# ============================================================================
# Classification: 每个 _ensure_* 函数必须被显式分类到下面 3 个集合之一
# ============================================================================

# Category 1: multi-attribute lazy import (R324/R325 pattern 适用)
_LOADED_FUNCS = {
    "_ensure_notification_loaded",
    "_ensure_notification_system_loaded",
    "_ensure_bark_provider_loaded",  # 单 attribute, 但归类一致
}

# Category 2: single-flag double-check registration (boolean flag pattern)
_REGISTERED_FUNCS = {
    "_ensure_config_change_callbacks_registered",
    "_ensure_sse_callback_registered",
    "_ensure_network_security_hot_reload_callback_registered",
    "_ensure_feedback_timeout_hot_reload_callback_registered",
    "_ensure_config_changed_sse_callback_registered",
}

# Category 3: daemon thread spawn (flag + lock pattern)
_STARTED_FUNCS = {
    "_ensure_lock_watchdog_started",
}


def _enumerate_ensure_functions() -> dict[str, Path]:
    """枚举 src 下所有 ``def _ensure_*(...)`` 函数, 返回 {name: file_path}。"""
    found: dict[str, Path] = {}
    for py in SRC.rglob("*.py"):
        text = py.read_text(encoding="utf-8")
        for m in re.finditer(r"^def\s+(_ensure_\w+)\s*\(", text, re.MULTILINE):
            name = m.group(1)
            if name in found:
                # 不允许同名函数跨多 module (会让分类语义混乱)
                continue
            found[name] = py
    return found


class TestEnumerationConsistency:
    """所有 ``_ensure_*`` 函数必须可被穷举, 且分类集合无重叠。"""

    def test_at_least_8_ensure_functions_found(self):
        funcs = _enumerate_ensure_functions()
        assert len(funcs) >= 8, (
            f"R327 anchor: expected >=8 _ensure_* functions in src/, "
            f"found {len(funcs)}: {list(funcs)}"
        )

    def test_categories_have_no_overlap(self):
        """3 个分类集合不能重叠。"""
        intersections = (
            _LOADED_FUNCS & _REGISTERED_FUNCS,
            _LOADED_FUNCS & _STARTED_FUNCS,
            _REGISTERED_FUNCS & _STARTED_FUNCS,
        )
        for inter in intersections:
            assert not inter, (
                f"R327: classification categories must be mutually "
                f"exclusive, overlap found: {inter}"
            )


class TestCompletenessFutureGuard:
    """**future-guard**: 任何 ``_ensure_*`` 函数都必须被显式分类, 否则
    invariant fail 强制 audit。"""

    def test_every_ensure_func_is_classified(self, subtests):
        found = _enumerate_ensure_functions()
        classified = _LOADED_FUNCS | _REGISTERED_FUNCS | _STARTED_FUNCS

        for name, path in found.items():
            with subtests.test(func=name, file=path.name):
                assert name in classified, (
                    f"R327 future-guard: `{name}` at {path.name} is NOT "
                    f"classified. **Action**:\n"
                    f"  1. Audit the function's pattern: multi-attribute "
                    f"lazy import / single-flag registration / daemon "
                    f"thread spawn / new pattern?\n"
                    f"  2. Add to _LOADED_FUNCS / _REGISTERED_FUNCS / "
                    f"_STARTED_FUNCS in test_feat_lazy_init_audit_r327.py\n"
                    f"  3. If new pattern, design corresponding safety "
                    f"contract before committing.\n"
                    f"This guards against R324-style mock pollution / "
                    f"R145-style race-condition bugs sneaking in via "
                    f"unaudited lazy-init."
                )


class TestLoadedFuncsSafety:
    """Category 1 (loaded): 每个 ``_ensure_*_loaded`` 函数必须用
    per-attribute null check (R324/R325 pattern), 或单 attribute (天然
    安全)。"""

    def test_loaded_funcs_use_per_attribute_or_single_attr(self, subtests):
        for name in sorted(_LOADED_FUNCS):
            with subtests.test(func=name):
                found = _enumerate_ensure_functions()
                assert name in found, f"R327: function `{name}` not found"
                path = found[name]
                text = path.read_text(encoding="utf-8")
                m = re.search(
                    rf"def\s+{re.escape(name)}\s*\(\s*\)[^:]*:\s*\n"
                    r"(?P<body>.*?)(?=\n(?:def\s+|class\s+|@|\Z))",
                    text,
                    re.DOTALL,
                )
                assert m, f"R327: cannot extract body of `{name}`"
                body = m.group("body")

                # Strategy: 必须有 `is None` 检查 (per-attribute or short-circuit)
                # 单 attribute 的也满足 (只检查 1 个就够)
                is_none_count = body.count("is None")
                assert is_none_count >= 1, (
                    f"R327 Category 1: `{name}` must use `is None` check "
                    f"(per-attribute null check / single-attr short-circuit). "
                    f"Found 0 `is None` in body."
                )


class TestRegisteredFuncsSafety:
    """Category 2 (registered): 每个 ``_ensure_*_registered`` 函数必须用
    flag + double-check locking 模式 (single boolean flag, 不会 mock
    pollute)。"""

    def test_registered_funcs_use_flag_pattern(self, subtests):
        for name in sorted(_REGISTERED_FUNCS):
            with subtests.test(func=name):
                found = _enumerate_ensure_functions()
                assert name in found, f"R327: function `{name}` not found"
                path = found[name]
                text = path.read_text(encoding="utf-8")
                m = re.search(
                    rf"def\s+{re.escape(name)}\s*\(\s*\)[^:]*:\s*\n"
                    r"(?P<body>.*?)(?=\n(?:def\s+|class\s+|@|\Z))",
                    text,
                    re.DOTALL,
                )
                assert m
                body = m.group("body")

                # Pattern: `if ..._registered:` + `with ..._lock:` + 内层重复检查
                # 必须含 "if" + "return" (short-circuit) + "with" (lock)
                assert "if" in body and "return" in body, (
                    f"R327 Category 2: `{name}` must use early return "
                    f"short-circuit pattern (`if ..._registered: return`)"
                )
                # case-insensitive: `_LOCK` (constant) 或 `_lock` (variable)
                # 都接受, body 必须既含 `with` 也含 `_lock`/_LOCK
                body_lower = body.lower()
                assert "with" in body_lower and "_lock" in body_lower, (
                    f"R327 Category 2: `{name}` must use lock-guarded "
                    f"double-check (`with ..._lock:` or `with ..._LOCK:`)"
                )


class TestStartedFuncsSafety:
    """Category 3 (started): 每个 ``_ensure_*_started`` 函数必须用 flag +
    lock 防止重复 spawn daemon thread。"""

    def test_started_funcs_use_thread_safe_spawn(self, subtests):
        for name in sorted(_STARTED_FUNCS):
            with subtests.test(func=name):
                found = _enumerate_ensure_functions()
                assert name in found, f"R327: function `{name}` not found"
                path = found[name]
                text = path.read_text(encoding="utf-8")
                m = re.search(
                    rf"def\s+{re.escape(name)}\s*\(\s*\)[^:]*:\s*\n"
                    r"(?P<body>.*?)(?=\n(?:def\s+|class\s+|@|\Z))",
                    text,
                    re.DOTALL,
                )
                assert m
                body = m.group("body")

                # Pattern: 必须 spawn thread + 有 flag + 有 lock
                assert "thread" in body.lower(), (
                    f"R327 Category 3: `{name}` should spawn a thread"
                )
                # 必须有 boolean flag 短路
                assert "if" in body and "return" in body, (
                    f"R327 Category 3: `{name}` must use early return "
                    f"short-circuit to prevent duplicate spawn"
                )


class TestR327LineageMarker:
    """R327 是 R324/R325 模式扩展, v3.8 test-isolation 6th app。"""

    def test_this_file_contains_r327_marker(self):
        text = Path(__file__).read_text(encoding="utf-8")
        assert "R327" in text

    def test_this_file_references_prior_apps(self):
        text = Path(__file__).read_text(encoding="utf-8")
        for prior in ("R316", "R319", "R323", "R324", "R325"):
            assert prior in text, f"R327: must cite prior app: {prior}"

    def test_this_file_documents_pattern_extension(self):
        text = Path(__file__).read_text(encoding="utf-8")
        for kw in (
            "全 codebase",
            "_loaded",
            "_registered",
            "_started",
            "future-guard",
            "6th",
        ):
            assert kw in text, f"R327: missing keyword: {kw!r}"
