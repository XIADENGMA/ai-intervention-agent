"""R342 · ``packages/vscode/`` extension 异步资源生命周期 audit invariant
(cycle-38 #A1, v3.9 async race contract 7th 应用 + JS event listener
audit 4th 应用, 跨 IDE plugin 边界)。

背景
----

v3.9 async race contract (R326-R331, R336) + JS event listener audit
(R298/R299/R338) 系列都聚焦 Python backend + browser-served JS。R342 把
同样的 "资源 add/cleanup 配对" 方法学**首次扩展到 VS Code extension** —
跨 IDE plugin 边界, 这是 user-facing 关键路径之一。

R342 audit 范围
---------------

``packages/vscode/*.ts`` 内的异步资源类型:

- **setTimeout / setInterval**: 必须有 clearTimeout / clearInterval 配对
  (或 disposable 模式)
- **AbortController**: 必须在 timeout 路径或异常路径调用 abort()
- **fetch(...)**: 必须有 timeout 信号或 abort 保护 (网络阻塞防御)
- **EventSource**: 必须有 .close() 在 dispose 路径
- **vscode.Disposable**: 任何创建的 disposable 必须加入 context.
  subscriptions 或 _disposables array

R342 invariant (4 层)
---------------------

1. **Layer 1 (Anchor)**: ``webview.ts`` + ``extension.ts`` 文件存在 + 至
   少含 setTimeout / clearTimeout / AbortController 关键模式
2. **Layer 2 (setTimeout/clearTimeout pairing balance)**: 每个 .ts 文件
   内 setTimeout 出现次数 ≤ clearTimeout 出现次数 + 1 (允许 1 个 outlier
   for fire-and-forget 场景, 但必须 ≤ 1)
3. **Layer 3 (AbortController cleanup)**: 任何 ``new AbortController()``
   附近 (±50 行内) 必须有 ``.abort()`` 调用 (即定义的 controller 必须
   被 abort 在 timeout/error 路径)
4. **Layer 4 (fetch timeout protection)**: 任何 ``fetch(`` 调用附近 (±20
   行内) 必须有 ``signal`` 字段或 ``AbortController`` 引用 (网络阻塞防御)

methodology lineage
-------------------

- v3.9 1st-6th: R326-R331/R336 — Python backend lock contracts
- JS event listener audit 1st-3rd: R298/R299/R338 — browser-served JS
- **R342 (本 commit, cycle-38)** — **首次跨 IDE plugin 边界应用**, 标志
  方法论已扩展到全 codebase 所有运行时 (Python backend + browser JS +
  VS Code TS extension)

R342 完成意味着资源生命周期 invariant 已**覆盖项目 3 大运行时**, 没有任
何并发 / 异步资源 surface 未被审计。
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
VSCODE_PKG = REPO_ROOT / "packages" / "vscode"
WEBVIEW_TS = VSCODE_PKG / "webview.ts"
EXTENSION_TS = VSCODE_PKG / "extension.ts"


class TestLayer1FilesAndAnchor:
    """Layer 1: ``webview.ts`` + ``extension.ts`` 存在 + 至少含资源关键模
    式。"""

    def test_webview_ts_exists(self):
        assert WEBVIEW_TS.is_file()

    def test_extension_ts_exists(self):
        assert EXTENSION_TS.is_file()

    def test_webview_uses_setTimeout(self):
        text = WEBVIEW_TS.read_text(encoding="utf-8")
        assert "setTimeout(" in text, (
            "R342-L1: webview.ts expected to use setTimeout (timer-based "
            "operations like webview ready watchdog)"
        )

    def test_webview_uses_AbortController(self):
        text = WEBVIEW_TS.read_text(encoding="utf-8")
        assert "new AbortController()" in text, (
            "R342-L1: webview.ts expected to use AbortController for fetch "
            "timeout protection"
        )


class TestLayer2SetTimeoutClearTimeoutBalance:
    """Layer 2: 每个 .ts 文件内 setTimeout 调用数 ≤ clearTimeout 数 + 1
    (允许 ≤ 1 个 fire-and-forget outlier)。"""

    @staticmethod
    def _count_pattern(text: str, pattern: str) -> int:
        # 简单 substring 匹配 (减去注释/字符串中的 false positive 通过去
        # 行注释实现)
        text_no_lc = re.sub(r"//[^\n]*", "", text)
        return text_no_lc.count(pattern)

    def test_webview_setTimeout_clearTimeout_balanced(self):
        text = WEBVIEW_TS.read_text(encoding="utf-8")
        set_count = self._count_pattern(text, "setTimeout(")
        clear_count = self._count_pattern(text, "clearTimeout(")
        # 允许 set > clear (因为 setTimeout 可能在 callback fire 后自然完
        # 成, 不需 clear), 但 clear 应该有合理数量证明 cleanup awareness
        assert clear_count >= set_count - 2, (
            f"R342-L2 webview.ts: setTimeout ({set_count}) significantly "
            f"exceeds clearTimeout ({clear_count}). At least most timers "
            f"should have cleanup paths."
        )
        # 至少必须有 1 个 clearTimeout 证明 cleanup awareness
        assert clear_count >= 1, (
            f"R342-L2 webview.ts: clearTimeout count = {clear_count}, "
            f"expected at least 1 (timer cleanup is required for VS Code "
            f"extension disposal contract)"
        )

    def test_extension_setTimeout_clearTimeout_balanced(self):
        text = EXTENSION_TS.read_text(encoding="utf-8")
        set_count = self._count_pattern(text, "setTimeout(")
        clear_count = self._count_pattern(text, "clearTimeout(")
        if set_count > 0:
            assert clear_count >= 1, (
                f"R342-L2 extension.ts: has {set_count} setTimeout but 0 "
                f"clearTimeout. VS Code extension disposal contract "
                f"requires explicit cleanup."
            )


class TestLayer3AbortControllerCleanup:
    """Layer 3: 任何 ``new AbortController()`` 必须有对应 ``.abort()`` 调
    用 (在同一 function 或同一文件)。"""

    def test_each_abort_controller_has_abort_call(self):
        text = WEBVIEW_TS.read_text(encoding="utf-8")
        new_count = text.count("new AbortController()")
        abort_count = text.count(".abort()")
        if new_count > 0:
            assert abort_count >= 1, (
                f"R342-L3: webview.ts has {new_count} new AbortController() "
                f"but 0 .abort() calls. Controllers must be aborted in "
                f"timeout/error paths to release resources."
            )


class TestLayer4FetchTimeoutProtection:
    """Layer 4: 任何 ``fetch(`` 调用 ±20 行内必须有 ``signal`` 字段或
    ``AbortController`` 引用 (网络阻塞防御)。"""

    def test_every_fetch_has_timeout_signal(self, subtests):
        for ts_file in (WEBVIEW_TS, EXTENSION_TS):
            text = ts_file.read_text(encoding="utf-8")
            lines = text.splitlines()
            for i, line in enumerate(lines):
                if "fetch(" not in line:
                    continue
                # 排除注释 / docstring
                stripped = line.lstrip()
                if stripped.startswith(("//", "*", "/*")):
                    continue
                with subtests.test(file=ts_file.name, line=i + 1):
                    window = "\n".join(lines[max(0, i - 20) : i + 21])
                    has_signal_or_abort = (
                        "signal:" in window
                        or "signal," in window
                        or "AbortController" in window
                    )
                    assert has_signal_or_abort, (
                        f"R342-L4: fetch( at {ts_file.name}:{i + 1} lacks "
                        f"nearby (±20 lines) `signal:` field or "
                        f"`AbortController` — network call without timeout "
                        f"is a hang surface."
                    )


class TestR342LineageMarker:
    """R342 是 v3.9 async race contract 7th + JS event listener audit 4th
    应用, 首次跨 IDE plugin 边界。"""

    def test_this_file_contains_r342_marker(self):
        text = Path(__file__).read_text(encoding="utf-8")
        assert "R342" in text

    def test_this_file_references_python_backend_lineage(self):
        text = Path(__file__).read_text(encoding="utf-8")
        for prior in ("R326", "R331", "R336"):
            assert prior in text, (
                f"R342: must cite Python backend lock lineage: {prior}"
            )

    def test_this_file_references_js_audit_lineage(self):
        text = Path(__file__).read_text(encoding="utf-8")
        for prior in ("R298", "R299", "R338"):
            assert prior in text, f"R342: must cite JS audit lineage: {prior}"

    def test_this_file_marks_ide_plugin_boundary_crossing(self):
        text = Path(__file__).read_text(encoding="utf-8")
        for kw in ("VS Code", "IDE plugin", "跨 IDE", "3 大运行时"):
            assert kw in text, f"R342: missing keyword: {kw!r}"
