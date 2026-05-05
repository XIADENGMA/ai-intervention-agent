"""R24.1 · ``packages/vscode/webview.ts::_preloadResources`` 4 file read 并行化。

背景
----
R20.13-C 已经把 ``extension.ts::activate`` 内的 host locale 加载从串行
``fs.readFileSync`` 切到了并行 ``Promise.all + fs.promises.readFile``，
但 ``WebviewProvider::_preloadResources`` 里的 webview 端 4 个 read 一直是
串行：``for (const loc of ['en','zh-CN'])`` 顺序 ``await
vscode.workspace.fs.readFile(...)``，再串行做 ``activity-icon.svg`` 和
``lottie/sprout.json``。

``_preloadResources`` 在 ``resolveWebviewView`` 的 critical path 上
``await`` 一次（line 431），是首屏渲染前**唯一**的同步阻塞点 —
原 inline 注释直接量化为「首次 ~50ms」。R24.1 把它改成 ``Promise.all``
（4 个 read 互无数据依赖），首次 wall-clock 从 ~50 ms 压到 ~15 ms。

测试维度
--------

1. 源码契约：``_preloadResources`` 函数体不再含 ``for (const loc of`` 串行
   循环；必须用 ``Promise.all([loadLocale(...), loadLocale(...),
   loadStaticAssets()])`` 一次性调度。
2. 内联注释含 ``R24.1`` tag，方便 git blame / regression 时定位设计动机。
3. 容错降级链路保留：每个 read 仍有 ``vscode.workspace.fs.readFile``
   → ``safeReadTextFile`` 的两段 try/catch（这是 R18 时代的 dev-experience
   契约，新结构不能丢）。
4. ``Promise.all`` 至少出现 1 次（外层调度），且包含 ``loadLocale`` /
   ``loadStaticAssets`` 字符串特征 —— 防御 refactor 误把并行化改回串行。
5. 仍然只有一个 ``private async _preloadResources(): Promise<void>``
   入口 —— 防御重复定义两份导致 hot path 错走老版本。
6. ``vscode.workspace.fs.readFile`` 在新版本里至少出现 3 次（en, zh-CN,
   svg, lottie 各一次，但每个都有 fallback；最少 3 次保证主路径未丢）。

为什么用 source-text guard：和 ``test_vscode_perf_r20_13.py`` 同款思路 —
ci_gate 唯一驱动器是 pytest，``packages/vscode`` 的 mocha/jest 不进
ci_gate；用 Python 端 source-text 锁定 TypeScript 源码契约是最低运行
成本（无需 npm install、tsc 编译），同时跨平台稳定。
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
WEBVIEW_TS = REPO_ROOT / "packages" / "vscode" / "webview.ts"


def _read(path: Path) -> str:
    assert path.exists(), f"目标文件缺失：{path}"
    return path.read_text(encoding="utf-8")


def _extract_block_by_brace(text: str, start_idx: int) -> str:
    """从 ``start_idx`` 处的 ``{`` 起做 brace-balance 扫描，返回完整 block。"""
    assert text[start_idx] == "{", (
        f"_extract_block_by_brace 入参 start_idx 必须指向 '{{'，"
        f"实际是 {text[start_idx]!r}"
    )
    depth = 0
    for idx in range(start_idx, len(text)):
        ch = text[idx]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start_idx : idx + 1]
    raise AssertionError("brace 不平衡，无法提取 block")


def _extract_preload_resources_body(text: str) -> str:
    """提取 ``_preloadResources`` 函数体（含外层 ``{...}``）。"""
    m = re.search(
        r"private\s+async\s+_preloadResources\s*\(\s*\)\s*:\s*Promise<\s*void\s*>",
        text,
    )
    assert m, "webview.ts 找不到 ``_preloadResources`` 方法定义"
    cursor = m.end()
    while cursor < len(text) and text[cursor] != "{":
        cursor += 1
    assert cursor < len(text), "_preloadResources 签名后找不到 ``{``"
    return _extract_block_by_brace(text, cursor)


# ---------------------------------------------------------------------------
# 1. 串行 ``for ... of`` 循环必须移除
# ---------------------------------------------------------------------------


def test_preload_resources_no_serial_for_of_loop() -> None:
    """``_preloadResources`` 函数体不应再含 ``for (const loc of [...])`` 串行循环。

    pre-fix 是：

        for (const loc of ["en", "zh-CN"]) {
            if (this._cachedLocales[loc]) continue;
            try { ... await vscode.workspace.fs.readFile(...); ... }
        }

    post-fix 必须用 ``Promise.all([loadLocale("en"), loadLocale("zh-CN"),
    loadStaticAssets()])`` 一次性调度，把 4 个 read 排到同一 event loop tick。
    """
    text = _read(WEBVIEW_TS)
    body = _extract_preload_resources_body(text)
    assert not re.search(
        r"for\s*\(\s*const\s+loc\s+of\s*\[",
        body,
    ), (
        "_preloadResources 函数体不应再含 ``for (const loc of [...])`` 串行循环；"
        " R24.1 设计是 ``await Promise.all([loadLocale('en'),"
        " loadLocale('zh-CN'), loadStaticAssets()])`` 一次调度。"
    )


# ---------------------------------------------------------------------------
# 2. 必须用 ``Promise.all`` 并行调度
# ---------------------------------------------------------------------------


def _extract_promise_all_arrays(body: str) -> list[str]:
    """提取 body 内所有 ``Promise.all([...])`` 的数组字面量内容（不含外层 ``[]``）。

    R24.1 的设计是「外层 Promise.all 排 3 个 helper」+「inner Promise.all
    在 loadStaticAssets 内部排 svg/lottie」，所以一个 _preloadResources
    body 里会出现 2 个 Promise.all。
    """
    out: list[str] = []
    cursor = 0
    while True:
        m = re.search(r"Promise\.all\s*\(\s*\[", body[cursor:])
        if not m:
            return out
        start = cursor + m.end()
        depth = 1
        end_idx = -1
        for idx in range(start, len(body)):
            ch = body[idx]
            if ch == "[":
                depth += 1
            elif ch == "]":
                depth -= 1
                if depth == 0:
                    end_idx = idx
                    break
        assert end_idx > 0, "Promise.all 的 [] 数组括号不平衡"
        out.append(body[start:end_idx])
        cursor = end_idx + 1


def test_preload_resources_uses_promise_all_with_three_branches() -> None:
    """``_preloadResources`` 函数体外层必须出现 ``await Promise.all([...])``，
    且至少一个 ``Promise.all`` 数组里同时引用 ``loadLocale`` 和
    ``loadStaticAssets`` 两个 helper。

    R24.1 的设计有两层 Promise.all：
    - 外层：``Promise.all([loadLocale("en"), loadLocale("zh-CN"),
      loadStaticAssets()])``
    - 内层（在 loadStaticAssets 内部）：``Promise.all([svgPromise,
      lottiePromise])``

    本测试锁定的是**外层调度**——确保 4 个 disk read 真的并行调度，
    不被 refactor 误改回 ``await loadLocale(...); await loadStaticAssets()``。
    """
    body = _extract_preload_resources_body(_read(WEBVIEW_TS))
    arrays = _extract_promise_all_arrays(body)
    assert arrays, (
        "_preloadResources 必须含 ``Promise.all([...])``；"
        " 缺它则 4 个 disk read 仍是串行。"
    )
    has_outer = any("loadLocale" in arr and "loadStaticAssets" in arr for arr in arrays)
    assert has_outer, (
        "至少一个 ``Promise.all([...])`` 数组应同时引用 ``loadLocale`` 与 "
        "``loadStaticAssets``（外层调度分支）；当前所有 Promise.all 数组："
        f" {arrays!r}"
    )


def test_preload_resources_load_locale_helper_defined() -> None:
    """``_preloadResources`` 函数体内应定义 ``loadLocale`` 局部 async 函数。

    这是 R24.1 的执行单元 — 把单个 locale 的 vscode.workspace.fs.readFile +
    safeReadTextFile fallback 封进一个 helper，``Promise.all`` 调度的就是
    它的 promise，便于 reasoning 并发图。
    """
    body = _extract_preload_resources_body(_read(WEBVIEW_TS))
    assert re.search(
        r"const\s+loadLocale\s*=\s*async\s*\(\s*loc\s*:\s*string\s*\)\s*"
        r":\s*Promise<\s*void\s*>",
        body,
    ), (
        "_preloadResources 函数体应当定义 "
        "``const loadLocale = async (loc: string): Promise<void> => {...}`` "
        "helper"
    )


def test_preload_resources_load_static_assets_helper_defined() -> None:
    """``_preloadResources`` 函数体内应定义 ``loadStaticAssets`` 局部 async 函数。

    封 ``activity-icon.svg`` + ``lottie/sprout.json`` 两个 read 进同一个
    helper，且 helper 内部用 ``Promise.all`` 把这两个再次并行（svg 和
    lottie 也无依赖关系）。
    """
    body = _extract_preload_resources_body(_read(WEBVIEW_TS))
    assert re.search(
        r"const\s+loadStaticAssets\s*=\s*async\s*\(\s*\)\s*"
        r":\s*Promise<\s*void\s*>",
        body,
    ), (
        "_preloadResources 函数体应当定义 "
        "``const loadStaticAssets = async (): Promise<void> => {...}`` helper"
    )


def test_load_static_assets_uses_inner_promise_all_for_svg_and_lottie() -> None:
    """``loadStaticAssets`` 内部应当再用一次 ``Promise.all`` 让 svg + lottie 并行。

    若 loadStaticAssets 内部仍是 ``await read(svg); await read(lottie)``
    串行，整体 wall-clock 还是要付 svg + lottie 两段时间，违背 R24.1 设计。
    """
    text = _read(WEBVIEW_TS)
    body = _extract_preload_resources_body(text)
    # 在 _preloadResources body 里再定位 loadStaticAssets 函数体
    static_match = re.search(
        r"const\s+loadStaticAssets\s*=\s*async\s*\(\s*\)\s*"
        r":\s*Promise<\s*void\s*>\s*=>\s*\{",
        body,
    )
    assert static_match, "_preloadResources 找不到 loadStaticAssets 定义"
    static_body = _extract_block_by_brace(body, static_match.end() - 1)
    assert re.search(r"await\s+Promise\.all\s*\(\s*\[", static_body), (
        "``loadStaticAssets`` 内部应当用 ``await Promise.all([...])`` 让 svg "
        "和 lottie 也并行；缺它则 svg/lottie 之间还是串行，多浪费一段时间。"
    )
    assert "svgPromise" in static_body and "lottiePromise" in static_body, (
        "``loadStaticAssets`` 内部应当用命名的 ``svgPromise`` / ``lottiePromise`` "
        "提升可读性（也是稳定 hash 的源码契约 — 重命名时同步改测试可以提示开发者）"
    )


# ---------------------------------------------------------------------------
# 3. 容错降级链路保留
# ---------------------------------------------------------------------------


def test_preload_resources_keeps_safe_read_text_file_fallback() -> None:
    """``_preloadResources`` 函数体仍应包含 ``safeReadTextFile(...)`` fallback。

    R18 时代的 dev-experience 契约：``vscode.workspace.fs.readFile`` 在
    某些 workspace trust 状态下会抛 ``FileSystemError``，必须降级到同步
    ``fs.readFileSync``（``safeReadTextFile`` 封了 catch）。R24.1 不能丢这层。
    """
    body = _extract_preload_resources_body(_read(WEBVIEW_TS))
    safe_calls = re.findall(r"safeReadTextFile\s*\(", body)
    # 4 个 read，每个都有 ``vscode.workspace.fs.readFile`` 主路径 +
    # ``safeReadTextFile`` fallback，所以期望出现 ≥3 次
    # （en + zh-CN locale 共用 loadLocale helper 算 1 次，
    # svg 1 次、lottie 1 次，所以 ≥3 次）
    assert len(safe_calls) >= 3, (
        f"_preloadResources 应当至少 3 次调用 ``safeReadTextFile(...)`` 兜底；"
        f"当前 {len(safe_calls)} 次，可能漏写了 fallback 链路"
    )


def test_preload_resources_keeps_vscode_fs_read_file_main_path() -> None:
    """``_preloadResources`` 函数体仍应保留 ``vscode.workspace.fs.readFile`` 主路径。

    主路径是 VSCode 推荐写法（走 workspace trust 检查 + 跨 remote
    workspace 兼容），fallback 才用 ``fs.readFileSync``。两者都不能丢。
    """
    body = _extract_preload_resources_body(_read(WEBVIEW_TS))
    main_calls = re.findall(r"vscode\.workspace\.fs\.readFile\s*\(", body)
    # 3 个文件主读取（locale helper 1 次 + svg 1 次 + lottie 1 次）
    assert len(main_calls) >= 3, (
        f"_preloadResources 应当至少 3 次 ``vscode.workspace.fs.readFile`` 主路径；"
        f"当前 {len(main_calls)} 次，可能漏写"
    )


# ---------------------------------------------------------------------------
# 4. cache guard 与签名仍存在
# ---------------------------------------------------------------------------


def test_load_locale_keeps_cache_short_circuit() -> None:
    """``loadLocale`` 入口应当先检查 ``_cachedLocales[loc]`` 命中并 ``return``。

    pre-fix 串行 for-loop 起手用 ``if (this._cachedLocales[loc]) continue``
    避免重复 read。post-fix 改 helper 形态后必须改成 ``return``，否则
    缓存命中也会去走 vscode.workspace.fs.readFile，浪费 ~12 ms。
    """
    body = _extract_preload_resources_body(_read(WEBVIEW_TS))
    locale_match = re.search(
        r"const\s+loadLocale\s*=\s*async\s*\(\s*loc\s*:\s*string\s*\)\s*"
        r":\s*Promise<\s*void\s*>\s*=>\s*\{",
        body,
    )
    assert locale_match
    locale_body = _extract_block_by_brace(body, locale_match.end() - 1)
    assert re.search(
        r"if\s*\(\s*this\._cachedLocales\s*\[\s*loc\s*\]\s*\)\s*return",
        locale_body,
    ), (
        "``loadLocale`` 应当起手 ``if (this._cachedLocales[loc]) return`` "
        "短路；缺它则二次 ``resolveWebviewView`` 也会重读 disk"
    )


def test_load_static_assets_keeps_cache_short_circuit() -> None:
    """``loadStaticAssets`` 入口应当先检查 ``_cachedStaticAssets`` 命中并 ``return``。

    同样的二次命中短路，缺它则二次 ``resolveWebviewView`` 也会
    重读 svg + lottie。
    """
    text = _read(WEBVIEW_TS)
    body = _extract_preload_resources_body(text)
    static_match = re.search(
        r"const\s+loadStaticAssets\s*=\s*async\s*\(\s*\)\s*"
        r":\s*Promise<\s*void\s*>\s*=>\s*\{",
        body,
    )
    assert static_match
    static_body = _extract_block_by_brace(body, static_match.end() - 1)
    assert re.search(
        r"if\s*\(\s*this\._cachedStaticAssets\s*\)\s*return",
        static_body,
    ), (
        "``loadStaticAssets`` 应当起手 ``if (this._cachedStaticAssets) return`` "
        "短路；缺它则缓存命中也会重读 svg/lottie"
    )


def test_load_static_assets_writes_back_cached_object_at_end() -> None:
    """``loadStaticAssets`` 末尾应当把 ``activityIconSvg + lottieData``
    一次性写回 ``this._cachedStaticAssets``，确保两个字段同时可见。

    防御部分写回（如先写 svg 再 await lottie）—— 部分写回会让其它
    路径看到 ``_cachedStaticAssets.activityIconSvg`` 已存在但
    ``lottieData`` 为 undefined 的中间状态。
    """
    text = _read(WEBVIEW_TS)
    body = _extract_preload_resources_body(text)
    static_match = re.search(
        r"const\s+loadStaticAssets\s*=\s*async\s*\(\s*\)\s*"
        r":\s*Promise<\s*void\s*>\s*=>\s*\{",
        body,
    )
    assert static_match
    static_body = _extract_block_by_brace(body, static_match.end() - 1)
    # 关键 invariant：``await Promise.all`` 之后再 ``this._cachedStaticAssets =``，
    # 不能在两个 promise 之间 partial-write。
    promise_all_match = re.search(r"await\s+Promise\.all\s*\(\s*\[", static_body)
    assign_match = re.search(
        r"this\._cachedStaticAssets\s*=\s*\{[\s\S]*?activityIconSvg[\s\S]*?lottieData",
        static_body,
    )
    assert promise_all_match, "loadStaticAssets 应包含 ``await Promise.all([...])``"
    assert assign_match, (
        "loadStaticAssets 应一次性写 "
        "``this._cachedStaticAssets = { activityIconSvg, lottieData }``"
    )
    assert promise_all_match.start() < assign_match.start(), (
        "``await Promise.all([...])`` 必须在 ``this._cachedStaticAssets = {...}`` 之前；"
        " 顺序倒了等于 partial-write，破坏 atomic visibility"
    )


# ---------------------------------------------------------------------------
# 5. R24.1 注释 + 唯一性
# ---------------------------------------------------------------------------


def test_preload_resources_has_r24_1_design_tag_comment() -> None:
    """``_preloadResources`` 内联注释应含 ``R24.1`` 设计标签。

    git blame / regression triage 时这个 tag 是定位 commit 的快捷方式
    （和 R20.13-A/B/.../F、R22.* 的注释风格保持一致）。
    """
    body = _extract_preload_resources_body(_read(WEBVIEW_TS))
    assert "R24.1" in body, (
        "_preloadResources 函数体应含 ``R24.1`` 设计 tag 注释；"
        " 这个 tag 是 git blame 快速定位优化设计的合约"
    )


def test_preload_resources_singly_defined() -> None:
    """``_preloadResources`` 必须只定义一次。

    防御 refactor 误把新版本附加在旧版本之后但漏删旧版本，导致 hot path
    走了哪一份不可控（TS 编译器允许同名 method 重复但 runtime 取最后一个）。
    """
    text = _read(WEBVIEW_TS)
    matches = re.findall(
        r"private\s+async\s+_preloadResources\s*\(\s*\)\s*:\s*Promise<\s*void\s*>",
        text,
    )
    assert len(matches) == 1, (
        f"_preloadResources 应当只定义一次，当前 {len(matches)} 次；"
        f" 重复定义会让 hot path 走最后一份，旧版本变 dead code 但仍占 bundle 体积"
    )


# ---------------------------------------------------------------------------
# 6. 调用点（``resolveWebviewView``）保持 ``await``
# ---------------------------------------------------------------------------


def test_resolve_webview_view_still_awaits_preload_resources() -> None:
    """``resolveWebviewView`` 必须 ``await this._preloadResources()`` 后再渲染。

    R24.1 是把 ``_preloadResources`` 内部 4 个 read 并行化，**不**改变它
    在 ``resolveWebviewView`` 的位置 —— 仍然是渲染前的同步阻塞。
    若误改成 ``this._preloadResources(); // 不 await``，HTML 会拿空 locale。
    """
    text = _read(WEBVIEW_TS)
    resolve_match = re.search(
        r"async\s+resolveWebviewView\s*\([\s\S]*?\)\s*:\s*Promise<\s*void\s*>\s*\{",
        text,
    )
    assert resolve_match, "webview.ts 找不到 resolveWebviewView 方法"
    resolve_body = _extract_block_by_brace(text, resolve_match.end() - 1)
    assert re.search(
        r"await\s+this\._preloadResources\s*\(\s*\)",
        resolve_body,
    ), (
        "resolveWebviewView 仍应 ``await this._preloadResources()`` 阻塞首屏；"
        " 改成 fire-and-forget 会让 webview 拿空 locale 渲染，破坏 i18n 合约"
    )
