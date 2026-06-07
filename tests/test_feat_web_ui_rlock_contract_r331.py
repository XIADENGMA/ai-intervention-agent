"""R331 · ``web_ui`` 2 处 RLock reentry contract invariant
(cycle-36 #A1, v3.9 async race contract 5th 应用)。

背景
----

cycle-35 通过 R330 把 ``web_ui.py`` 的 2 处 RLock 加入白名单, 但仅做"白名
单存在 + 附近有任意 # 注释"层级的 audit。R331 进一步**证明 reentry 必要
性的具体来源**:

1. ``_FEEDBACK_TIMEOUT_CALLBACK_LOCK`` (web_ui.py:284) — RLock 必需, 因为
   存在**显式 reentry chain**:
   - ``web_ui_config_sync.py:128`` `with _FEEDBACK_TIMEOUT_CALLBACK_LOCK:`
   - 内部 line 137 调用 ``_sync_existing_tasks_timeout_from_config()``
   - 后者 line 47 又 ``with _FEEDBACK_TIMEOUT_CALLBACK_LOCK:`` (同一线程
     重入)
   - Lock 会 self-deadlock, **RLock 是 hard requirement**

2. ``WebFeedbackUI._state_lock`` (web_ui.py:458) — RLock 是**防御性选
   择**, 当前 codebase 内无实际 reentry chain, 但保留 RLock 防御未来扩展
   (callback 在持锁状态下回调访问同一状态)

R331 invariant (4 层)
---------------------

1. **Layer 1 (Anchor)**: 2 处 RLock 必须存在 + 必须有 ``R331 contract``
   关键字的 rationale 注释 (强化 R330 的弱 audit)
2. **Layer 2 (Reentry chain proof)**: ``_FEEDBACK_TIMEOUT_CALLBACK_LOCK``
   必须有 reentry chain 证据 — web_ui_config_sync.py 内必须能找到嵌套调
   用图 (callback registration → callback 执行 → 重入同一锁)
3. **Layer 3 (R330 whitelist consistency)**: 2 处 RLock 必须仍在 R330
   ``ALLOWED_RLOCK_SITES`` 中 (跨 invariant 一致性)
4. **Layer 4 (Count guard)**: ``web_ui.py`` 内 RLock 总数 == 2, 任何新增
   必须 audit

methodology lineage milestone
-----------------------------

- v3.9 1st app: R326 (cycle-35) — task_queue wrapper contract
- v3.9 2nd app: R328 (cycle-35) — notification_manager AST 顺序
- v3.9 3rd app: R329 (cycle-35) — service_manager 模块锁顺序
- v3.9 4th app: R330 (cycle-35) — 跨 codebase RLock 白名单
- **v3.9 5th app: R331 (本 commit, cycle-36)** — web_ui 2 RLock reentry
  contract (深化 R330 弱 audit, **首次显式证明 reentry chain 必要性**)

R331 是 v3.9 pattern 进入 **深化期** 的标志: 不仅锁住"什么", 而是锁住
"**为什么需要**" (rationale 可执行验证)。
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC = REPO_ROOT / "src" / "ai_intervention_agent"
_WEB_UI_PY = SRC / "web_ui.py"
_WEB_UI_CONFIG_SYNC_PY = SRC / "web_ui_config_sync.py"


class TestLayer1RationaleAnchor:
    """Layer 1: 2 处 RLock 必须存在 + 必须有 ``R331 contract`` 关键字的
    rationale 注释。"""

    def test_web_ui_py_exists(self):
        assert _WEB_UI_PY.is_file()

    def test_feedback_timeout_lock_has_r331_rationale(self):
        text = _WEB_UI_PY.read_text(encoding="utf-8")
        # 找 _FEEDBACK_TIMEOUT_CALLBACK_LOCK = threading.RLock() 位置
        idx = text.find("_FEEDBACK_TIMEOUT_CALLBACK_LOCK = threading.RLock()")
        assert idx >= 0, "R331-L1: _FEEDBACK_TIMEOUT_CALLBACK_LOCK not found"
        # 检查前 10 行内有 `R331 contract` 关键字
        preamble = text[:idx][-1500:]
        assert "R331 contract" in preamble, (
            "R331-L1: _FEEDBACK_TIMEOUT_CALLBACK_LOCK lacks `R331 contract` "
            "rationale comment (must explain reentry chain explicitly)"
        )
        assert "self-deadlock" in preamble or "reentry" in preamble, (
            "R331-L1: rationale must mention `self-deadlock` or `reentry`"
        )

    def test_state_lock_has_r331_rationale(self):
        text = _WEB_UI_PY.read_text(encoding="utf-8")
        idx = text.find("self._state_lock = threading.RLock()")
        assert idx >= 0, "R331-L1: self._state_lock not found"
        preamble = text[:idx][-1500:]
        assert "R331 contract" in preamble, (
            "R331-L1: self._state_lock lacks `R331 contract` rationale "
            "comment (must mark whether reentry is real or defensive)"
        )
        assert "防御" in preamble or "defensive" in preamble.lower(), (
            "R331-L1: rationale must mark _state_lock as 防御性/defensive"
        )


class TestLayer2ReentryChainProof:
    """Layer 2: ``_FEEDBACK_TIMEOUT_CALLBACK_LOCK`` 必须有 reentry chain
    证据 (callback registration → callback execution → 重入同一锁)。"""

    def test_register_callback_holds_lock_when_calling_callback(self):
        """``_ensure_feedback_timeout_hot_reload_callback_registered`` 在持
        锁状态下调用 ``_sync_existing_tasks_timeout_from_config()``。"""
        text = _WEB_UI_CONFIG_SYNC_PY.read_text(encoding="utf-8")
        # 找 _ensure_feedback_timeout_hot_reload_callback_registered 函数体
        m = re.search(
            r"def\s+_ensure_feedback_timeout_hot_reload_callback_registered"
            r"\s*\(\s*\)[^:]*:\s*\n(?P<body>.*?)(?=\ndef\s+|\nclass\s+|\Z)",
            text,
            re.DOTALL,
        )
        assert m, "R331-L2: cannot find _ensure_*_callback_registered function"
        body = m.group("body")
        # 必须在 with _FEEDBACK_TIMEOUT_CALLBACK_LOCK: 块内调用 _sync_*
        # 找 `with ..._FEEDBACK_TIMEOUT_CALLBACK_LOCK:` 后是否有 _sync_*
        with_idx = body.find("_FEEDBACK_TIMEOUT_CALLBACK_LOCK")
        assert with_idx >= 0, "R331-L2: with block not found in register"
        sync_call_idx = body.find("_sync_existing_tasks_timeout_from_config(", with_idx)
        assert sync_call_idx >= 0, (
            "R331-L2: register function must call _sync_existing_tasks_*() "
            "from within `with _FEEDBACK_TIMEOUT_CALLBACK_LOCK:` block "
            "(this is the reentry trigger that requires RLock)"
        )

    def test_callback_function_acquires_same_lock(self):
        """``_sync_existing_tasks_timeout_from_config`` 必须也用
        ``with _FEEDBACK_TIMEOUT_CALLBACK_LOCK:`` (这是 reentry 发生地)。"""
        text = _WEB_UI_CONFIG_SYNC_PY.read_text(encoding="utf-8")
        m = re.search(
            r"def\s+_sync_existing_tasks_timeout_from_config"
            r"\s*\(\s*\)[^:]*:\s*\n(?P<body>.*?)(?=\ndef\s+|\nclass\s+|\Z)",
            text,
            re.DOTALL,
        )
        assert m, "R331-L2: cannot find _sync_existing_tasks_* function"
        body = m.group("body")
        assert "_FEEDBACK_TIMEOUT_CALLBACK_LOCK" in body and "with" in body, (
            "R331-L2: _sync_existing_tasks_timeout_from_config must use "
            "`with _FEEDBACK_TIMEOUT_CALLBACK_LOCK:` (this is the reentry "
            "site that makes RLock necessary)"
        )

    def test_reentry_chain_is_documented_in_source_comment(self):
        """``_FEEDBACK_TIMEOUT_CALLBACK_LOCK`` 的 rationale 必须显式提到
        ``web_ui_config_sync.py`` 行号或函数名 (使 reentry chain 可追溯)。"""
        text = _WEB_UI_PY.read_text(encoding="utf-8")
        idx = text.find("_FEEDBACK_TIMEOUT_CALLBACK_LOCK = threading.RLock()")
        assert idx >= 0
        preamble = text[:idx][-1500:]
        assert "web_ui_config_sync" in preamble, (
            "R331-L2: rationale must cite `web_ui_config_sync.py` (reentry "
            "chain source file) so future readers can trace the chain"
        )


class TestLayer3R330WhitelistConsistency:
    """Layer 3: 2 处 RLock 必须仍在 R330 ``ALLOWED_RLOCK_SITES`` 白名单
    中 (跨 invariant 一致性)。"""

    def test_both_locks_in_r330_whitelist(self):
        r330_test = REPO_ROOT / "tests" / "test_feat_rlock_usage_contract_r330.py"
        text = r330_test.read_text(encoding="utf-8")
        assert "_FEEDBACK_TIMEOUT_CALLBACK_LOCK = threading.RLock()" in text, (
            "R331-L3: R330 whitelist must contain _FEEDBACK_TIMEOUT_CALLBACK_LOCK"
        )
        assert "self._state_lock = threading.RLock()" in text, (
            "R331-L3: R330 whitelist must contain self._state_lock"
        )


class TestLayer4CountGuard:
    """Layer 4: ``web_ui.py`` 内 RLock 总数 == 2, 新增必须 audit。"""

    def test_web_ui_py_rlock_count_exactly_2(self):
        text = _WEB_UI_PY.read_text(encoding="utf-8")
        text_no_docs = re.sub(r'"""[\s\S]*?"""', "", text)
        rlocks = re.findall(r"threading\.RLock\(\)", text_no_docs)
        assert len(rlocks) == 2, (
            f"R331-L4: web_ui.py RLock count drifted to {len(rlocks)}, "
            f"expected exactly 2. **Action**: if new RLock added, justify "
            f"reentry necessity + add R331-style rationale + update R330 "
            f"whitelist + update this invariant."
        )


class TestR331LineageMarker:
    """R331 是 v3.9 5th app, 进入深化期 (锁 "为什么需要")。"""

    def test_this_file_contains_r331_marker(self):
        text = Path(__file__).read_text(encoding="utf-8")
        assert "R331" in text

    def test_this_file_marks_v3_9_5th_app(self):
        text = Path(__file__).read_text(encoding="utf-8")
        assert "v3.9" in text
        assert "5th" in text.lower() or "第 5" in text

    def test_this_file_references_all_prior_v3_9_apps(self):
        text = Path(__file__).read_text(encoding="utf-8")
        for prior in ("R326", "R328", "R329", "R330"):
            assert prior in text, f"R331: must cite prior v3.9 app: {prior}"

    def test_this_file_documents_deepening_phase(self):
        text = Path(__file__).read_text(encoding="utf-8")
        for kw in (
            "深化",
            "reentry chain",
            "rationale",
            "首次显式证明",
        ):
            assert kw in text, f"R331: missing keyword: {kw!r}"
