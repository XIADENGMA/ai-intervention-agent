"""R18.2 · ``packages/vscode/webview.ts::updateServerUrl`` dispose-race
源码级 lock。

背景
----
``updateServerUrl`` 走的是 ``_preloadResources()`` 的 async finally：

    this._preloadResources()
      .catch(() => {})
      .finally(() => {
        if (this._view !== view) return       // ← R18.2 dispose-race guard
        if (view.webview) view.webview.html = this._getHtmlContent(view.webview)
        this._webviewReadyTimer = setTimeout(() => { ...warning log... }, 2500)
      })

``_preloadResources`` 通常含一次 HTTP probe（locale / config / version
预热）。如果用户在它 in-flight 期间 dispose webview（``onDidDispose``
触发，``this._view`` 被置为 ``null``），那么 stale finally 仍然会执行
两件事：

1. ``view.webview.html = ...``：``view`` 是 capture-time 的 stale
   引用，VSCode 多半 noop 但偶发抛 ``Webview is disposed``，把
   finally 转成 unhandled rejection，污染 Output channel。

2. ``this._webviewReadyTimer = setTimeout(..., 2500)``：dispose 的
   ``clearTimeout`` 已经在 capture 之前完成，新创建的 timer 不会被
   dispose 回收。2.5 s 后 timer fires → 写一条
   ``webview.ready_timeout`` warning 日志 —— 但 webview 早已不存在，
   这是 false-positive observability 噪声，会让运维在排查"真" CSP /
   script 注入失败时被误导。

修复是一行 ``if (this._view !== view) return``。这个测试做三件事：

1. **Guard 存在性**（前向 lock）：确认 ``webview.ts`` 的
   ``updateServerUrl`` 函数体里包含
   ``if (this._view !== view) return``。
2. **Guard 出现在 ``setTimeout`` 之前**（顺序 lock）：保证一旦
   stale 退出生效，新 timer 永远不会被创建 —— 这是修复"2.5 s 后
   false-positive 日志"的载荷。
3. **Reverse lock**：如果将来某次 refactor 把 guard 从 finally 里
   挪走 / 删掉，这条测试立刻 fail。

为什么写在 Python 端：本仓库 ci_gate 唯一驱动器是 pytest，把
dev-experience guard 都集中在 ``tests/`` 下能让一次 ``make ci``
全跑完，无需为单条 source-text guard 另外发明 mocha/jest job。
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
WEBVIEW_TS = REPO_ROOT / "packages" / "vscode" / "webview.ts"


def _read_webview_ts() -> str:
    assert WEBVIEW_TS.exists(), f"webview.ts 缺失：{WEBVIEW_TS}"
    return WEBVIEW_TS.read_text(encoding="utf-8")


def _extract_update_server_url_body() -> str:
    """从 ``webview.ts`` 提取 ``updateServerUrl`` 函数体的源码片段。

    用一个简单的"找到声明 → 平衡 brace 计数"扫描器；TS AST 工具
    （ts-morph / babel-parser）会引入 npm dep，这条单测不值得换那
    种重量级方案。
    """
    text = _read_webview_ts()
    # 找到 ``updateServerUrl(serverUrl: string): void {`` 这一行
    m = re.search(r"updateServerUrl\s*\([^)]*\)\s*:\s*void\s*\{", text)
    assert m, "webview.ts 找不到 ``updateServerUrl`` 方法签名"
    start = m.end() - 1  # ``{`` 的位置

    # brace 平衡扫描，找配对的 ``}``
    depth = 0
    for idx in range(start, len(text)):
        ch = text[idx]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start : idx + 1]
    raise AssertionError("``updateServerUrl`` 方法体 brace 不平衡，无法提取函数体")


# ---------------------------------------------------------------------------
# 1. Guard 存在性 lock
# ---------------------------------------------------------------------------

GUARD_PATTERN = re.compile(
    r"if\s*\(\s*this\._view\s*!==\s*view\s*\)\s*return",
)


def test_dispose_race_guard_present_in_update_server_url() -> None:
    """``updateServerUrl`` 的 finally 必须含
    ``if (this._view !== view) return`` dispose-race guard。

    这是 R18.2 修复的载荷：没有这一行，webview dispose 之后异步
    完成的 ``_preloadResources`` finally 会把 stale 引用拖进操作链，
    生成 false-positive ``webview.ready_timeout`` 日志。
    """
    body = _extract_update_server_url_body()
    matches = GUARD_PATTERN.findall(body)
    assert matches, (
        "webview.ts::updateServerUrl 的 finally 缺少 dispose-race guard"
        " ``if (this._view !== view) return``。"
        " 缺失会导致 webview dispose 后 stale ``_preloadResources`` finally"
        " 仍然给已 disposed view 赋 HTML + 创建新的 setTimeout，"
        " 2.5 s 后写一条 false-positive ``webview.ready_timeout`` warning"
        " 日志，污染 Output channel 干扰 CSP/script 故障排查。"
    )


# ---------------------------------------------------------------------------
# 2. Guard 顺序 lock：必须在 setTimeout 创建之前
# ---------------------------------------------------------------------------


def test_dispose_race_guard_precedes_setTimeout_in_finally() -> None:
    """guard 必须出现在 ``setTimeout`` 创建之前。

    这是真正的 load-bearing 不变量：guard 在 setTimeout 之前 → 一旦
    stale 退出生效，新 timer 不会被创建，dispose 已经 cancel 的
    timer 不会"再生"。如果 guard 跑到 setTimeout 之后，false-positive
    日志的 race 会原地复活。
    """
    body = _extract_update_server_url_body()
    guard_match = GUARD_PATTERN.search(body)
    assert guard_match, (
        "guard 缺失（详细见 test_dispose_race_guard_present_in_update_server_url）"
    )
    settimeout_match = re.search(r"\bsetTimeout\s*\(", body)
    assert settimeout_match, (
        "updateServerUrl 应当含 setTimeout 调用（_webviewReadyTimer 创建）"
    )
    assert guard_match.start() < settimeout_match.start(), (
        "dispose-race guard 必须出现在 ``setTimeout`` 之前；"
        " 当前 guard 在 setTimeout 之后等于"
        " 没修，stale finally 仍会创建 false-positive timer。"
    )


# ---------------------------------------------------------------------------
# 3. Reverse lock：guard 必须挂在 ``_preloadResources`` 的 finally 里，
#    不能是其他位置（比如挪到 try 块入口或被注释掉）
# ---------------------------------------------------------------------------


def test_dispose_race_guard_inside_preload_resources_finally() -> None:
    """guard 必须落在 ``_preloadResources(...).catch(...).finally(() => {`` 的
    block 里，而不是飘在 ``updateServerUrl`` 顶层。

    refactor 风险：若有人把 guard "提前"到方法顶部"早 return"，
    dispose 后调用 ``updateServerUrl`` 会被外层 ``if (this._view &&
    this._view.webview)`` 已经挡住（dispose 后 ``_view = null``），
    所以顶部 guard 是 dead code —— 但 finally 里 stale callback 仍
    会在原 view 还存在 / dispose 进行中等微秒级 race 触发；finally
    里的 guard 才是 race-correct 位置。
    """
    body = _extract_update_server_url_body()
    # 找 ``_preloadResources()`` 之后 ``.finally(() => {`` 开始位置；
    # 中间允许多行 ``.catch(() => {})`` chaining
    finally_start = re.search(
        r"_preloadResources\s*\(\s*\)[\s\S]*?\.finally\s*\(\s*\(\s*\)\s*=>\s*\{",
        body,
    )
    assert finally_start, (
        "找不到 ``_preloadResources(...).finally(() => {`` —— 调用结构变了，"
        " 本测试需要同步更新"
    )
    finally_block_start = finally_start.end()

    # brace 平衡扫到 finally 的 ``}``
    depth = 1
    finally_block_end = -1
    for idx in range(finally_block_start, len(body)):
        ch = body[idx]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                finally_block_end = idx
                break
    assert finally_block_end > 0, "finally 块 brace 不平衡"
    finally_body = body[finally_block_start:finally_block_end]
    assert GUARD_PATTERN.search(finally_body), (
        "dispose-race guard 必须落在 ``_preloadResources(...).finally(() => {...})``"
        " 里；落在外层等同于没修复 race。"
    )


# ---------------------------------------------------------------------------
# 4. setTimeout 必须仍然在 finally 里（防御 over-fix：guard 把 setTimeout
#    误删的可能）
# ---------------------------------------------------------------------------


def test_setTimeout_still_present_for_ready_timeout_observability() -> None:
    """guard 引入后，``setTimeout(..., 2500)`` 仍然必须保留 —— 这是
    "webview script 真没起来"时的观测点，不能因为加 guard 顺手把
    它删掉。
    """
    body = _extract_update_server_url_body()
    m = re.search(
        r"setTimeout\s*\(\s*\(\s*\)\s*=>\s*\{[\s\S]*?\}\s*,\s*2500\s*\)", body
    )
    assert m, (
        "updateServerUrl 应当仍包含 ``setTimeout(() => {...}, 2500)``，用于在 webview"
        " script 未上报 ``ready`` 时记录 ``webview.ready_timeout`` warning。R18.2 dispose"
        " race guard 仅应让 stale finally 跳过这一段，而不是把可观测性删掉。"
    )


# ---------------------------------------------------------------------------
# 5. ``view`` 变量必须在 finally 之前 capture（这是 guard 比较的对象）
# ---------------------------------------------------------------------------


def test_view_captured_before_preload_finally() -> None:
    """``const view = this._view`` 必须在 ``_preloadResources()`` 调用之前；
    这样 finally 比较的 ``view`` 是"调用 updateServerUrl 那一刻的 view"，
    跟 finally fire 时刻的 ``this._view`` 比较才能正确识别 dispose。

    如果 ``view`` 在 finally 里现取，那它跟 ``this._view`` 永远相等，
    guard 永远是 falsy。
    """
    body = _extract_update_server_url_body()
    capture_match = re.search(r"const\s+view\s*=\s*this\._view\b", body)
    preload_match = re.search(r"_preloadResources\s*\(\s*\)", body)
    assert capture_match, "updateServerUrl 应当含 ``const view = this._view`` capture"
    assert preload_match, "updateServerUrl 应当调用 ``_preloadResources()``"
    assert capture_match.start() < preload_match.start(), (
        "``const view = this._view`` 必须早于 ``_preloadResources()`` 调用；"
        " capture 跑到 finally 里等于没 capture，guard 退化成 ``this._view !== this._view``"
        " 永远 false，race 复活。"
    )
