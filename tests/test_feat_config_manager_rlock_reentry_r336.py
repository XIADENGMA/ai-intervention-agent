"""R336 · ``ConfigManager._lock`` RLock reentry chain contract
(cycle-37 #A1, v3.9 async race contract 6th 应用, R331 模板复用)。

背景
----

cycle-36 R331 首次显式证明 ``_FEEDBACK_TIMEOUT_CALLBACK_LOCK`` 的 reentry
chain。R336 把同样的 "**锁定 why**" 方法学应用到 ``config_manager.py`` 的
``ConfigManager._lock`` (RLock):

**reentry chain 证据**:

1. ``ConfigManager.set()`` (line 1131) 内 ``with self._lock:`` (持锁)
2. → line 1167 调用 ``self._save_config()``
3. → line 997 调用 ``self._schedule_save()``
4. → line 948 ``with self._lock:`` (**同一线程重入获取同一锁**)

同理: ``set_section`` + 其他 mutate API 都走相同 chain。Lock 会
self-deadlock, **RLock 是 hard requirement**。

R336 invariant (5 层)
---------------------

1. **Layer 1 (Anchor)**: ``self._lock = threading.RLock()`` 必须存在 + 必
   须有 ``R336 contract`` 关键字 + 必须显式提到 ``set_value`` /
   ``_save_config`` / ``_schedule_save`` chain
2. **Layer 2 (Reentry chain proof - 出口侧)**: ``set_value`` (或同类 mutate
   方法) 必须在 ``with self._lock:`` 块内调用 ``self._save_config()``
3. **Layer 3 (Reentry chain proof - 入口侧)**: ``_schedule_save`` 必须用
   ``with self._lock:`` (这是 reentry 发生地)
4. **Layer 4 (R330 whitelist consistency)**: ``self._lock = threading.
   RLock()`` 必须仍在 R330 ``ALLOWED_RLOCK_SITES`` 中
5. **Layer 5 (Lock count guard)**: ``config_manager.py`` 内
   ``ConfigManager._lock`` 实例必须 == 1

methodology lineage
-------------------

- v3.9 1st-4th: R326-R330 (cycle-35) — 锁 what
- v3.9 5th: R331 (cycle-36) — 锁 why (web_ui_config_sync chain)
- **v3.9 6th: R336 (本 commit, cycle-37)** — 锁 why (config_manager 内部
  chain), R331 模板复用 + 跨模块验证

R336 标志 v3.9 深化期 pattern (锁定 why) **第 2 次落地**, 证明此模板可被
系统化扩展到任何含 reentry 的 lock site。
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC = REPO_ROOT / "src" / "ai_intervention_agent"
_CONFIG_MANAGER_PY = SRC / "config_manager.py"


class TestLayer1RationaleAnchor:
    """Layer 1: ``self._lock = threading.RLock()`` 必须存在 + 必须有 R336
    contract 关键字 + 必须显式提到 reentry chain 三个函数名。"""

    def test_config_manager_py_exists(self):
        assert _CONFIG_MANAGER_PY.is_file()

    def test_self_lock_declared_as_rlock(self):
        text = _CONFIG_MANAGER_PY.read_text(encoding="utf-8")
        assert "self._lock = threading.RLock()" in text, (
            "R336-L1: self._lock must be `threading.RLock()`"
        )

    def test_self_lock_has_r336_rationale(self):
        text = _CONFIG_MANAGER_PY.read_text(encoding="utf-8")
        idx = text.find("self._lock = threading.RLock()")
        assert idx >= 0
        preamble = text[:idx][-2000:]
        assert "R336 contract" in preamble, (
            "R336-L1: self._lock lacks `R336 contract` rationale comment"
        )
        for func in ("set(", "_save_config", "_schedule_save"):
            assert func in preamble, (
                f"R336-L1: rationale must cite `{func}` (reentry chain function)"
            )


class TestLayer2ReentryChainProofExitSide:
    """Layer 2 (出口侧): ``set_value`` 必须在 ``with self._lock:`` 块内调
    用 ``self._save_config()`` (这是 reentry 触发地)。"""

    def test_set_calls_save_within_lock(self):
        text = _CONFIG_MANAGER_PY.read_text(encoding="utf-8")
        # `def set(` 必须区分 `def settings(` 之类 — 用边界匹配
        m = re.search(
            r"def\s+set\s*\(\s*self[^)]*\)[^:]*:\s*\n(?P<body>.*?)(?=\n    def\s+|\nclass\s+|\Z)",
            text,
            re.DOTALL,
        )
        assert m, "R336-L2: cannot extract ConfigManager.set() body"
        body = m.group("body")
        lock_idx = body.find("with self._lock:")
        assert lock_idx >= 0, "R336-L2: ConfigManager.set() must use `with self._lock:`"
        save_idx = body.find("self._save_config()", lock_idx)
        assert save_idx >= 0, (
            "R336-L2: ConfigManager.set() must call `self._save_config()` "
            "from within `with self._lock:` block (this is the reentry "
            "trigger that requires RLock)"
        )


class TestLayer3ReentryChainProofEntrySide:
    """Layer 3 (入口侧): ``_schedule_save`` 必须用 ``with self._lock:`` (这
    是 reentry 发生地)。"""

    def test_schedule_save_acquires_self_lock(self):
        text = _CONFIG_MANAGER_PY.read_text(encoding="utf-8")
        m = re.search(
            r"def\s+_schedule_save\s*\([^)]*\)[^:]*:\s*\n(?P<body>.*?)(?=\n    def\s+|\nclass\s+|\Z)",
            text,
            re.DOTALL,
        )
        assert m, "R336-L3: cannot extract _schedule_save() body"
        body = m.group("body")
        assert "with self._lock:" in body, (
            "R336-L3: _schedule_save must use `with self._lock:` (this is "
            "the reentry site that makes RLock necessary). Same-thread "
            "set_value→_save_config→_schedule_save chain re-acquires lock "
            "here."
        )


class TestLayer4R330WhitelistConsistency:
    """Layer 4: ``self._lock = threading.RLock()`` 必须仍在 R330 白名单
    中。"""

    def test_self_lock_in_r330_whitelist(self):
        r330_test = REPO_ROOT / "tests" / "test_feat_rlock_usage_contract_r330.py"
        text = r330_test.read_text(encoding="utf-8")
        assert "self._lock = threading.RLock()" in text, (
            "R336-L4: R330 whitelist must contain `self._lock = threading.RLock()`"
        )


class TestLayer5LockCountGuard:
    """Layer 5: ``config_manager.py`` 内 ``self._lock = threading.RLock()``
    实例数 == 1。"""

    def test_config_manager_rlock_count_exactly_1(self):
        text = _CONFIG_MANAGER_PY.read_text(encoding="utf-8")
        text_no_docs = re.sub(r'"""[\s\S]*?"""', "", text)
        instances = re.findall(
            r"self\._lock\s*=\s*threading\.RLock\(\)",
            text_no_docs,
        )
        assert len(instances) == 1, (
            f"R336-L5: config_manager.py `self._lock = threading.RLock()` "
            f"count drifted to {len(instances)}, expected exactly 1. "
            f"If new ConfigManager subclass needs separate lock, justify "
            f"reentry necessity + add R336-style rationale + update R330 "
            f"whitelist + update this invariant."
        )


class TestR336LineageMarker:
    """R336 是 v3.9 6th app, R331 模板 2nd 复用。"""

    def test_this_file_contains_r336_marker(self):
        text = Path(__file__).read_text(encoding="utf-8")
        assert "R336" in text

    def test_this_file_marks_v3_9_6th_app(self):
        text = Path(__file__).read_text(encoding="utf-8")
        assert "v3.9" in text
        assert "6th" in text.lower() or "第 6" in text

    def test_this_file_references_r331_template_origin(self):
        text = Path(__file__).read_text(encoding="utf-8")
        assert "R331" in text, "R336: must cite R331 (template origin)"

    def test_this_file_documents_reentry_chain(self):
        text = Path(__file__).read_text(encoding="utf-8")
        for kw in (
            "reentry chain",
            "set(",
            "_save_config",
            "_schedule_save",
            "锁 why",
        ):
            assert kw in text, f"R336: missing keyword: {kw!r}"
