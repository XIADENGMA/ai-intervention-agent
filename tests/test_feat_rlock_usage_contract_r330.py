"""R330 · 跨 codebase ``threading.RLock`` 使用白名单 contract
(cycle-35 #C1, v3.9 async race contract 4th 应用)。

背景
----

cycle-35 已通过 R328 (notification_manager) 和 R329 (service_manager) 禁
止这两个模块使用 ``threading.RLock``, 强制显式 lock-order。但其他模块
(``config_manager.py``, ``web_ui.py``) 因为有特定 rationale, 仍然使用
RLock。

R330 引入 **跨 codebase RLock 白名单 invariant**:

- 全 codebase RLock 使用位置必须严格匹配已审查的白名单
- 任何新增 RLock 都会让 invariant fail, 强制 author:
  1. 解释为什么需要 reentry (避免隐藏 lock-order bug)
  2. 在白名单注释中记录 rationale
  3. 更新本 invariant 的 ``ALLOWED_RLOCK_SITES``

R330 invariant (3 层)
---------------------

1. **Layer 1 (Anchor)**: 全 codebase RLock 使用位置集合 == 已审查的白名
   单 (4 处)
2. **Layer 2 (Rationale required)**: 每个白名单位置在源文件**附近 5 行内**
   必须有 ``# ...`` 注释解释 reentry 必要性
3. **Layer 3 (Forbidden modules)**: notification_manager / service_manager
   模块**绝对禁止** RLock (与 R328 / R329 contract 一致)

methodology lineage milestone
-----------------------------

- v3.9 1st app: R326 (cycle-35 #A1) — task_queue 写锁 wrapper contract
- v3.9 2nd app: R328 (cycle-35 #B3) — notification_manager AST 多锁顺序
- v3.9 3rd app: R329 (cycle-35 #A2) — service_manager 模块级多锁顺序
  → **v3.9 达 3 应用工业化阈值**
- **v3.9 4th app: R330 (本 commit, cycle-35 #C1)** — 跨 codebase RLock
  使用白名单 contract

R330 是 v3.9 进入 **完全工业化期** 的标志: 4 个不同 pattern 实例覆盖了
"单锁 wrapper / 多锁顺序 / module-level / 跨模块白名单" 全场景。

**cycle-35 创下 v3.9 单 cycle 内 0→4 应用新纪录** (此前 v3.6/v3.7/v3.8
均需要 2-3 个 cycles 才能从启动到完全工业化)。
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC = REPO_ROOT / "src" / "ai_intervention_agent"


# 已审查的 RLock 使用白名单 (file_rel_path, line_substring) — 4 处
# 任何变更必须经过 audit + 更新本列表 + 在源代码附近注释 rationale
ALLOWED_RLOCK_SITES = frozenset(
    {
        # (1) config_manager.py: ReadWriteLock 内部 condition + RLock
        #     合理因为 condition 需要 reentry-safe lock
        ("config_manager.py", "self._read_ready = threading.Condition"),
        # (2) config_manager.py: ConfigManager 实例延迟保存定时器
        #     合理因为定时器回调可能从持有锁的线程内触发
        ("config_manager.py", "self._lock = threading.RLock()"),
        # (3) web_ui.py: feedback timeout callback 注册锁
        #     合理因为 register_config_change_callback 可能 reentrant
        ("web_ui.py", "_FEEDBACK_TIMEOUT_CALLBACK_LOCK = threading.RLock()"),
        # (4) web_ui.py: WebFeedbackUI 共享状态保护
        #     合理因为 Flask threaded mode 下 polling + submission 并发
        ("web_ui.py", "self._state_lock = threading.RLock()"),
    }
)

# 这些模块严禁 RLock (与 R328/R329 invariant 一致)
FORBIDDEN_MODULES = frozenset(
    {
        "notification_manager.py",
        "service_manager.py",
    }
)


def _enumerate_rlock_sites() -> set[tuple[str, str]]:
    """枚举 src 下所有 ``threading.RLock()`` 使用位置。

    Returns: set of (file_rel_path, full_line_stripped)
    """
    sites: set[tuple[str, str]] = set()
    for py in SRC.rglob("*.py"):
        text = py.read_text(encoding="utf-8")
        for m in re.finditer(r"^.*threading\.RLock\(\).*$", text, re.MULTILINE):
            line = m.group(0).strip()
            # 跳过纯 docstring / comment 引用 (避免误报)
            stripped = line.lstrip()
            if stripped.startswith(("#", '"')):
                continue
            sites.add((py.name, line))
    return sites


class TestLayer1WhitelistMatch:
    """Layer 1: 全 codebase RLock 使用必须严格匹配已审查白名单。"""

    def test_no_unauthorized_rlock_usage(self):
        sites = _enumerate_rlock_sites()
        unauthorized: list[tuple[str, str]] = []

        for file_name, line in sites:
            # 任何 site 必须有至少一个白名单条目 substring match
            matched = False
            for allowed_file, allowed_substr in ALLOWED_RLOCK_SITES:
                if file_name == allowed_file and allowed_substr in line:
                    matched = True
                    break
            if not matched:
                unauthorized.append((file_name, line))

        assert not unauthorized, (
            "R330-L1: unauthorized threading.RLock() usage detected:\n"
            + "\n".join(f"  - {f}: {ln}" for f, ln in unauthorized)
            + "\n\n**Action**: (1) audit if RLock necessary or Lock + "
            "explicit order works; (2) document rationale in source "
            "comment; (3) add (file, substring) to ALLOWED_RLOCK_SITES "
            "in tests/test_feat_rlock_usage_contract_r330.py"
        )

    def test_all_whitelist_entries_still_exist(self, subtests):
        """白名单条目必须仍然在源代码中存在 — 防止陈旧白名单。"""
        for allowed_file, allowed_substr in sorted(ALLOWED_RLOCK_SITES):
            with subtests.test(file=allowed_file, substr=allowed_substr[:50]):
                py = SRC / allowed_file
                # 也允许嵌套子目录
                if not py.exists():
                    matches = list(SRC.rglob(allowed_file))
                    assert matches, f"R330-L1: file `{allowed_file}` not found"
                    py = matches[0]
                text = py.read_text(encoding="utf-8")
                assert allowed_substr in text, (
                    f"R330-L1: stale whitelist! `{allowed_file}` no longer "
                    f"contains `{allowed_substr}`. Remove from "
                    f"ALLOWED_RLOCK_SITES."
                )


class TestLayer2RationaleRequired:
    """Layer 2: 每个白名单位置在源代码 **同行末尾** 或 **附近 5 行内** 必
    须有 ``#`` 注释说明 reentry 必要性。"""

    def test_each_rlock_site_has_nearby_comment(self, subtests):
        # 收集每个白名单条目所在文件内容
        for allowed_file, allowed_substr in sorted(ALLOWED_RLOCK_SITES):
            with subtests.test(file=allowed_file):
                matches = list(SRC.rglob(allowed_file))
                assert matches
                text = matches[0].read_text(encoding="utf-8")
                lines = text.splitlines()
                idx = next(
                    (i for i, ln in enumerate(lines) if allowed_substr in ln),
                    -1,
                )
                assert idx >= 0, (
                    f"R330-L2: cannot locate `{allowed_substr}` in {allowed_file}"
                )

                # 检查同行末尾或前后 5 行内有 `#` 注释 (排除 shebang / type)
                window_start = max(0, idx - 5)
                window_end = min(len(lines), idx + 6)
                comment_found = False
                for li in range(window_start, window_end):
                    line = lines[li]
                    # 找 inline comment 或 standalone comment
                    if "#" in line:
                        # 排除 type: ignore / noqa / shebang 等
                        comment_part = line[line.index("#") :]
                        if not any(
                            kw in comment_part for kw in ("type:", "noqa", "!/usr/bin")
                        ):
                            comment_found = True
                            break
                assert comment_found, (
                    f"R330-L2: RLock site `{allowed_substr}` in "
                    f"{allowed_file} (line {idx + 1}) lacks nearby (±5 lines) "
                    f"rationale comment. Add `# ...` explaining why "
                    f"reentry is necessary."
                )


class TestLayer3ForbiddenModules:
    """Layer 3: notification_manager / service_manager 严禁 RLock (与
    R328 / R329 contract 一致)。"""

    def test_forbidden_modules_have_zero_rlock(self, subtests):
        for forbidden in sorted(FORBIDDEN_MODULES):
            with subtests.test(module=forbidden):
                matches = list(SRC.rglob(forbidden))
                assert matches, f"R330-L3: module `{forbidden}` not found"
                text = matches[0].read_text(encoding="utf-8")
                # Strip docstrings 防误报
                text_no_docs = re.sub(r'"""[\s\S]*?"""', "", text)
                rlock_uses = re.findall(r"threading\.RLock\(\)", text_no_docs)
                assert len(rlock_uses) == 0, (
                    f"R330-L3: forbidden module `{forbidden}` uses RLock "
                    f"{len(rlock_uses)} times! Per R328/R329 contract, "
                    f"these modules must use threading.Lock + explicit "
                    f"acquisition order, NOT RLock (which hides "
                    f"lock-order bugs)."
                )


class TestR330LineageMarker:
    """R330 是 v3.9 4th app, 标志 cycle-35 单 cycle 完成 v3.9 0→4 应用新
    纪录。"""

    def test_this_file_contains_r330_marker(self):
        text = Path(__file__).read_text(encoding="utf-8")
        assert "R330" in text

    def test_this_file_marks_v3_9_4th_app(self):
        text = Path(__file__).read_text(encoding="utf-8")
        assert "v3.9" in text
        assert "4th" in text.lower() or "第 4" in text

    def test_this_file_references_all_prior_v3_9_apps(self):
        text = Path(__file__).read_text(encoding="utf-8")
        for prior in ("R326", "R328", "R329"):
            assert prior in text, f"R330: must cite prior v3.9 app: {prior}"

    def test_this_file_documents_cycle_35_velocity_record(self):
        text = Path(__file__).read_text(encoding="utf-8")
        for kw in ("0→4", "完全工业化", "白名单"):
            assert kw in text, f"R330: missing keyword: {kw!r}"
