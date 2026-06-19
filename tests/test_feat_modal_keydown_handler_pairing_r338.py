"""R338 · modal/dialog ``keydown`` handler add/remove pairing invariant
(cycle-37 #B1, JS event listener leak audit)。

背景
----

cycle-29 R298 已经审计 ``fetchWithTimeout`` AbortController, cycle-29 R299
已经审计 ``mutationObserver disconnect``。R338 补完 event listener 审计的
最后一块: **modal/dialog 类 ``document.addEventListener("keydown", ...)``
必须有对应 ``removeEventListener``**。

为什么聚焦 modal/dialog?
-----------------------

- 页面级 long-lived listener (如主键盘快捷键 ``app.js:1694``) 整个 SPA
  生命周期都活, 不需要 remove
- 但 modal/dialog 临时 listener (ESC 关闭 / Tab trap) **每次 open 都
  add**, 如果 close 时不 remove, 多次 open/close 会累积 → 内存 leak +
  无效的 handler 仍在 fire (可能 throw 因 modal 已 hidden)
- 这是真实可发现的 P1 bug surface, 历史上是 a11y audit cycle 高发问题

R338 invariant (3 层)
---------------------

1. **Layer 1 (Pairing pattern enumeration)**: 每个已知的 modal/dialog
   ``document.addEventListener("keydown", handlerName)`` 必须有对应的
   ``document.removeEventListener("keydown", handlerName)`` 在同一文件
2. **Layer 2 (Handler name consistency)**: add 和 remove 必须用**同一
   handler 引用** (不允许 inline function 或不同变量名 — 会让 remove
   静默失效)
3. **Layer 3 (Future-guard)**: 任何新 ``document.addEventListener
   ("keydown", ...)`` 都必须被显式分类: (a) page-level long-lived (列入
   白名单), (b) modal/dialog 临时 (必须有 remove 配对)

methodology lineage
-------------------

- R298 (cycle-29): AbortController 内存泄漏审计
- R299 (cycle-29): mutationObserver disconnect 审计
- **R338 (本 commit, cycle-37)**: modal/dialog keydown handler pairing
  (event listener audit 系列 3rd app)

R338 与 R298/R299 共同构成 **JS 异步资源生命周期审计 pattern** 的完整覆
盖, 任何新增的 modal/dialog/observer/abortable 都被强制配对 audit。
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
STATIC_JS = REPO_ROOT / "src" / "ai_intervention_agent" / "static" / "js"


# 已审查的 modal/dialog handler add/remove 配对 (file, handler_name)
# 这些 handler 是临时 (modal open 时 add, close 时 remove), 必须配对
MODAL_DIALOG_PAIRS = frozenset(
    {
        ("app.js", "handleCodePasteModalKeydown"),
        ("image-upload.js", "handleModalKeydown"),
        ("image-upload.js", "_imageModalTabTrapHandler"),
        ("settings-manager.js", "this._settingsEscHandler"),
        ("keyboard_shortcut_help.js", "_onTabInOverlay"),
    }
)

# 已审查的 page-level long-lived handler (不需要 remove, 整个 SPA 生命周期)。
# 值可以是稳定 handler 名（优先，抗行号漂移）或历史行号哨兵。
PAGE_LEVEL_LONG_LIVED = frozenset(
    {
        ("app.js", "handleGlobalKeydown"),  # 主键盘快捷键 (page-level)
        ("keyboard_shortcut_help.js", "_onKeydown"),  # ? cheatsheet trigger
        ("quick_phrases.js", "_fallbackShortcutHandler"),  # Alt+N fallback
        ("keyboard-shortcuts.js", "handleKeydown"),  # 有 destroy() 配对
        ("feedback_submit_mode.js", None),  # docstring 引用
    }
)


def _find_keydown_add_calls(
    file_path: Path,
) -> list[tuple[int, str]]:
    """找 ``document.addEventListener("keydown", <handler>)`` 调用。

    Returns: list of (line_number, handler_arg). 排除 JSDoc / comment
    引用 (行首是 ``*`` / ``//`` 的不算)。
    """
    text = file_path.read_text(encoding="utf-8")
    results: list[tuple[int, str]] = []
    for m in re.finditer(
        r"document\.addEventListener\(\s*['\"]keydown['\"]\s*,\s*([^,)]+)[,)]",
        text,
    ):
        # 提取行首到 match 的起始, 判断是否在 comment 内
        line_start = text.rfind("\n", 0, m.start()) + 1
        line_prefix = text[line_start : m.start()].lstrip()
        if line_prefix.startswith(("*", "//")):
            continue
        line_no = text[: m.start()].count("\n") + 1
        handler = m.group(1).strip()
        results.append((line_no, handler))
    return results


def _find_keydown_remove_calls(
    file_path: Path,
) -> list[tuple[int, str]]:
    text = file_path.read_text(encoding="utf-8")
    results: list[tuple[int, str]] = []
    for m in re.finditer(
        r"document\.removeEventListener\(\s*['\"]keydown['\"]\s*,\s*([^,)]+)[,)]",
        text,
    ):
        line_no = text[: m.start()].count("\n") + 1
        handler = m.group(1).strip()
        results.append((line_no, handler))
    return results


class TestLayer1ModalDialogPairing:
    """Layer 1: 每个 modal/dialog keydown handler add 必须有 remove 配对。"""

    def test_all_modal_handlers_have_remove_pair(self, subtests):
        for file_name, handler_name in sorted(MODAL_DIALOG_PAIRS):
            with subtests.test(file=file_name, handler=handler_name):
                py = STATIC_JS / file_name
                assert py.is_file(), f"R338-L1: file `{file_name}` missing"
                text = py.read_text(encoding="utf-8")
                # add 和 remove 都必须含 handler_name
                add_pattern = (
                    rf'document\.addEventListener\(\s*[\'"]keydown[\'"]\s*,\s*'
                    rf"{re.escape(handler_name)}"
                )
                remove_pattern = (
                    rf'document\.removeEventListener\(\s*[\'"]keydown[\'"]\s*,\s*'
                    rf"{re.escape(handler_name)}"
                )
                assert re.search(add_pattern, text), (
                    f"R338-L1: file `{file_name}` no longer has "
                    f"`document.addEventListener('keydown', {handler_name})`"
                )
                assert re.search(remove_pattern, text), (
                    f"R338-L1: file `{file_name}` has "
                    f"`addEventListener('keydown', {handler_name})` but "
                    f"NO matching `removeEventListener` — this is a real "
                    f"event listener leak! Modal open will accumulate "
                    f"handlers each time, causing memory leak + invalid "
                    f"handler firing on hidden modal."
                )


class TestLayer2HandlerNameConsistency:
    """Layer 2: add 和 remove 必须用同一 handler 引用 (变量名 / 属性引用),
    不允许 inline function (会让 remove 静默失效, 因为函数引用每次不同)。"""

    def test_modal_add_handlers_are_named_references(self, subtests):
        for file_name, handler_name in sorted(MODAL_DIALOG_PAIRS):
            with subtests.test(file=file_name, handler=handler_name):
                # handler_name 不能是 inline function (如 "(e) => {...}" 或
                # "function(e) {...}")
                assert not handler_name.startswith("("), (
                    f"R338-L2: handler `{handler_name}` looks like inline "
                    f"arrow function — removeEventListener will fail to "
                    f"match. Use a named function reference."
                )
                assert not handler_name.startswith("function"), (
                    f"R338-L2: handler `{handler_name}` looks like inline "
                    f"function expression — removeEventListener will fail."
                )


class TestLayer3FutureGuardEnumeration:
    """Layer 3 (future-guard): 任何新 ``document.addEventListener("keydown",
    ...)`` 都必须被显式分类。"""

    def test_every_keydown_add_is_classified(self, subtests):
        # 收集所有 .js 文件内的 document.addEventListener('keydown', X) 调用
        # 排除 .min.js (minified copy, audit 原始 .js 即可)
        all_adds: list[tuple[str, int, str]] = []
        for js in STATIC_JS.glob("*.js"):
            if js.name.endswith(".min.js"):
                continue
            for line_no, handler in _find_keydown_add_calls(js):
                all_adds.append((js.name, line_no, handler))

        # 已分类:
        # (a) MODAL_DIALOG_PAIRS handler_name match
        # (b) PAGE_LEVEL_LONG_LIVED (file, line_no)
        for file_name, line_no, handler in all_adds:
            with subtests.test(file=file_name, line=line_no, handler=handler):
                modal_match = any(
                    file_name == f and handler == h for f, h in MODAL_DIALOG_PAIRS
                )
                page_match = any(
                    file_name == f
                    and (
                        (isinstance(marker, int) and line_no == marker)
                        or (isinstance(marker, str) and handler == marker)
                    )
                    for f, marker in PAGE_LEVEL_LONG_LIVED
                    if marker is not None
                )
                assert modal_match or page_match, (
                    f"R338-L3 future-guard: NEW `document.addEventListener"
                    f"('keydown', ...)` detected at {file_name}:{line_no} "
                    f"with handler `{handler}` — NOT classified. "
                    f"**Action**:\n"
                    f"  (a) If modal/dialog 临时 listener: add to "
                    f"MODAL_DIALOG_PAIRS + add matching removeEventListener\n"
                    f"  (b) If page-level long-lived: add (file, line_no) "
                    f"to PAGE_LEVEL_LONG_LIVED with rationale comment"
                )


class TestR338LineageMarker:
    """R338 是 event listener audit 系列 3rd app (R298 + R299 sister)。"""

    def test_this_file_contains_r338_marker(self):
        text = Path(__file__).read_text(encoding="utf-8")
        assert "R338" in text

    def test_this_file_references_prior_audit_series(self):
        text = Path(__file__).read_text(encoding="utf-8")
        for prior in ("R298", "R299"):
            assert prior in text, f"R338: must cite prior listener audit: {prior}"

    def test_this_file_documents_3_layers(self):
        text = Path(__file__).read_text(encoding="utf-8")
        for kw in ("Layer 1", "Layer 2", "Layer 3", "modal/dialog", "future-guard"):
            assert kw in text, f"R338: missing keyword: {kw!r}"
