"""R20.13 · packages/vscode 性能审计源码级 lock。

背景
----
R20.4-R20.11 完成 MCP server 侧 cold-start 优化（425 ms → 156 ms 主进程
+ 1922 ms → 203 ms Web UI 子进程），R20.12 完成浏览器运行时优化
（``mathjax-loader.js`` defer + inline locale + ``createImageBitmap``）。

R20.13 把刀对准 VSCode 插件的扩展宿主（extension host）+ webview 渲染
路径，目标是把「VSCode 启动 → Activity Bar 出现 → webview 首屏 ready」
的端到端延迟再压一层。

R20.13 一共改 6 个点，都在本文件锁住：

A. ``extension.ts::BUILD_ID`` IIFE → ``getBuildId()`` lazy + ``fs.existsSync(.git)``
   守卫。pre-fix 在生产 VSIX（``__BUILD_SHA__`` 未替换 + ``.git`` 不存在）
   仍会跑 ``execSync('git rev-parse --short HEAD')`` 付 ~10 ms 代价；
   post-fix 一次 ``existsSync`` ~5-20 µs 直接跳过。

B. ``webview.ts::WebviewProvider`` 接受 ``extensionVersion: string`` 构造器
   参数；不再每次 ``_getHtmlContent`` 调 ``vscode.extensions.getExtension``
   注册表查表。

C. ``extension.ts::activate`` 改 ``async``；``hostLocales`` 加载从串行
   ``fs.readFileSync`` 切到并行 ``Promise.all + fs.promises.readFile``。

D. ``webview-ui.js::ensureI18nReady`` 启动只 eager-register active 语言 +
   ``en`` fallback，不再 ``Object.keys(__AIIA_I18N_ALL_LOCALES) + 循环 register``。
   ``applyServerLanguage`` 接 ``ensureLocaleRegistered`` lazy hook 做运行时
   切语言时的补注册，保留 i18n fallback 合约。

E. ``webview.ts::_getHtmlContent`` 用 ``_cachedInlineAllLocalesJson`` 缓存
   ``safeJsonForInlineScript(allLocales)`` 序列化结果。键由 locale 名 +
   各 locale entry 字典 key 数组成的 signature 字符串决定。

F. ``webview.ts::_getHtmlContent`` 直接读 ``this._extensionVersion``；不再
   ``vscode.extensions.getExtension('xiadengma.ai-intervention-agent')`` 查表
   （与 B 同源，B 是写入侧、F 是读取侧）。

为什么测试都写在 Python 端：本仓库 ci_gate 唯一驱动器是 pytest，
所有 dev-experience guard / source-text invariant 集中放 ``tests/`` 下，
一次 ``make ci`` 全跑完，不需要为单条 source-text guard 另开 mocha/jest job。
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
VSCODE_DIR = REPO_ROOT / "packages" / "vscode"
EXTENSION_TS = VSCODE_DIR / "extension.ts"
WEBVIEW_TS = VSCODE_DIR / "webview.ts"
WEBVIEW_UI_JS = VSCODE_DIR / "webview-ui.js"


def _read(path: Path) -> str:
    assert path.exists(), f"目标文件缺失：{path}"
    return path.read_text(encoding="utf-8")


def _extract_block_by_brace(text: str, start_idx: int) -> str:
    """从 ``start_idx`` 处的 ``{`` 起做 brace-balance 扫描，返回完整 block 字符串。"""
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


def _extract_function_body_after(text: str, name_pattern: str) -> str:
    """匹配 ``name_pattern``（regex），从其结尾开始扫描下一个 ``{``，返回 body。"""
    m = re.search(name_pattern, text)
    assert m, f"未找到模式：{name_pattern!r}"
    cursor = m.end()
    while cursor < len(text) and text[cursor] != "{":
        cursor += 1
    assert cursor < len(text), f"模式 {name_pattern!r} 之后找不到 '{{'"
    return _extract_block_by_brace(text, cursor)


# ---------------------------------------------------------------------------
# A. ``extension.ts::BUILD_ID`` 改 lazy + ``fs.existsSync(.git)`` 守卫
# ---------------------------------------------------------------------------


def test_a_get_build_id_function_exists() -> None:
    """``extension.ts`` 必须包含 ``function getBuildId()`` 而不是顶层 IIFE。

    pre-fix 是 ``const BUILD_ID = (() => {...})()``，IIFE 在模块加载时
    立刻执行，包含 ``execSync('git rev-parse')`` 不可逃避。post-fix 是
    一个 lazy 函数，被 ``activate`` 调用时才决定是否真的 fork+exec。
    """
    text = _read(EXTENSION_TS)
    assert re.search(r"function\s+getBuildId\s*\(\s*\)", text), (
        "extension.ts 应当定义 ``function getBuildId()`` lazy 计算器；"
        " pre-fix 的 IIFE ``const BUILD_ID = (() => {...})()`` 在模块加载即跑"
        " ``execSync('git rev-parse')`` (~10 ms 生产 VSIX 浪费)。"
    )


def test_a_no_top_level_build_id_iife() -> None:
    """``extension.ts`` 顶层不再有 ``const BUILD_ID = (() => {...})()`` IIFE。

    防止 refactor 不小心把 lazy 函数留下 + IIFE 也保留两份共存，那种状态
    比 pre-fix 还糟（既保留了 IIFE 浪费，又增加 lazy 函数体的代码维护成本）。
    """
    text = _read(EXTENSION_TS)
    assert not re.search(
        r"const\s+BUILD_ID\s*:\s*string\s*=\s*\(\s*\(\s*\)\s*=>\s*\{",
        text,
    ), (
        "extension.ts 顶层不应再有 ``const BUILD_ID = (() => {...})()`` IIFE；"
        " 它在模块加载即跑 execSync，违背 R20.13-A 设计。"
    )


def test_a_get_build_id_uses_fs_existsSync_for_git_dir() -> None:
    """``getBuildId`` 函数体必须先 ``fs.existsSync(.../.git)`` 才 ``execSync``。

    这是核心收益：production VSIX 没有 ``.git``，``existsSync`` 一次
    ~5-20 µs 直接走 ``return 'dev'``，跳过 ~10 ms execSync。
    """
    text = _read(EXTENSION_TS)
    body = _extract_function_body_after(text, r"function\s+getBuildId\s*\(\s*\)")
    assert re.search(r"fs\.existsSync\s*\([^)]*\.git", body), (
        "getBuildId 必须含 ``fs.existsSync(... '.git' ...)`` 守卫；"
        " 缺它则生产 VSIX 仍会付 ~10 ms execSync 代价（违背 R20.13-A 设计）。"
    )


def test_a_get_build_id_existsSync_precedes_execSync() -> None:
    """``existsSync`` 必须在 ``execSync`` 之前 — 这是「能不 fork+exec 就别 fork+exec」的核心。

    若顺序倒了（先 execSync 再 existsSync），R20.13-A 优化原地复活成 pre-fix 行为。
    """
    text = _read(EXTENSION_TS)
    body = _extract_function_body_after(text, r"function\s+getBuildId\s*\(\s*\)")
    exists_match = re.search(r"fs\.existsSync\s*\(", body)
    exec_match = re.search(r"execSync\s*\(", body)
    assert exists_match, "getBuildId 缺 fs.existsSync 调用"
    assert exec_match, "getBuildId 缺 execSync 调用"
    assert exists_match.start() < exec_match.start(), (
        "fs.existsSync 必须在 execSync 之前；顺序倒了等于没修。"
    )


def test_a_get_build_id_caches_result() -> None:
    """``getBuildId`` 多次调用应返回缓存值，不重复跑 existsSync / execSync。

    用一个模块级 ``_cachedBuildId`` 保存结果。第一次调用付代价，之后零成本。
    """
    text = _read(EXTENSION_TS)
    assert re.search(r"_cachedBuildId\s*:\s*string\s*\|\s*null\s*=\s*null", text), (
        "extension.ts 应声明 ``let _cachedBuildId: string | null = null`` 缓存槽位；"
        " 缺它则 getBuildId 多次调用要重复 existsSync。"
    )
    body = _extract_function_body_after(text, r"function\s+getBuildId\s*\(\s*\)")
    assert re.search(r"_cachedBuildId\s*!==\s*null", body), (
        "getBuildId 函数体应包含 ``if (_cachedBuildId !== null) return _cachedBuildId``"
        " 缓存命中分支。"
    )


def test_a_activate_uses_get_build_id_call() -> None:
    """``activate`` 中应调用 ``getBuildId()`` 而不是直接引用顶层 ``BUILD_ID`` 常量。"""
    text = _read(EXTENSION_TS)
    assert re.search(r"buildId:\s*getBuildId\s*\(\s*\)", text), (
        "activate 函数应通过 ``getBuildId()`` 拿值；引用裸 ``BUILD_ID`` 常量等于"
        " 没移除 IIFE。"
    )


# ---------------------------------------------------------------------------
# B+F. ``webview.ts::WebviewProvider`` 接 ``extensionVersion`` 构造器参数
# ---------------------------------------------------------------------------


def test_b_constructor_accepts_extension_version_param() -> None:
    """``WebviewProvider`` 构造器签名必须显式接受 ``extensionVersion`` 参数。"""
    text = _read(WEBVIEW_TS)
    constructor_match = re.search(
        r"constructor\s*\([\s\S]*?\)\s*\{",
        text,
    )
    assert constructor_match, "webview.ts 找不到 WebviewProvider constructor"
    sig = constructor_match.group(0)
    assert re.search(r"extensionVersion\s*:\s*string", sig), (
        "WebviewProvider 构造器应声明 ``extensionVersion: string`` 参数；"
        " 缺它则 host 端无法把版本号一次性灌进来。"
    )


def test_b_extension_version_field_declared() -> None:
    """``WebviewProvider`` 应有 ``private _extensionVersion: string`` 字段。"""
    text = _read(WEBVIEW_TS)
    assert re.search(r"private\s+_extensionVersion\s*:\s*string", text), (
        "WebviewProvider 应声明 ``private _extensionVersion: string`` 实例字段；"
        " 缺它则 _getHtmlContent 没办法用预先填好的版本。"
    )


def test_b_constructor_assigns_extension_version() -> None:
    """构造器必须把入参 ``extensionVersion`` 赋给 ``this._extensionVersion``。"""
    text = _read(WEBVIEW_TS)
    assert re.search(
        r"this\._extensionVersion\s*=\s*[\s\S]*?extensionVersion",
        text,
    ), "构造器必须做 ``this._extensionVersion = ...`` 赋值（值来自参数）"


def test_f_get_html_content_does_not_call_get_extension() -> None:
    """``_getHtmlContent`` 函数体不应再调 ``vscode.extensions.getExtension(...)``。

    pre-fix 每次 HTML 渲染都查一次 host extension registry (~1-3 ms)；
    post-fix 一次 activate 就把版本号传给构造器，渲染零查表。

    匹配模式带 ``\\s*\\(``，避免误伤注释里解释 R20.13 设计动机的
    ``vscode.extensions.getExtension`` 文字（没有跟着括号说明不是调用）。
    """
    text = _read(WEBVIEW_TS)
    body = _extract_function_body_after(
        text, r"_getHtmlContent\s*\(\s*webview:\s*vscode\.Webview\s*\)\s*:\s*string"
    )
    assert not re.search(r"vscode\.extensions\.getExtension\s*\(", body), (
        "_getHtmlContent 函数体不应再调 ``vscode.extensions.getExtension(...)``；"
        " 用 ``this._extensionVersion``（构造器期一次性传入）替代。"
    )


def test_f_get_html_content_uses_cached_extension_version() -> None:
    """``_getHtmlContent`` 应使用 ``this._extensionVersion`` 取版本号。"""
    text = _read(WEBVIEW_TS)
    body = _extract_function_body_after(
        text, r"_getHtmlContent\s*\(\s*webview:\s*vscode\.Webview\s*\)\s*:\s*string"
    )
    assert re.search(r"this\._extensionVersion", body), (
        "_getHtmlContent 应使用 ``this._extensionVersion``；"
        " 走老 vscode.extensions.getExtension 路径浪费时间。"
    )


def test_f_extension_ts_passes_version_to_provider() -> None:
    """``extension.ts`` 调 ``new WebviewProvider`` 时必须把 ``EXT_VERSION`` 传进去。"""
    text = _read(EXTENSION_TS)
    new_match = re.search(r"new\s+WebviewProvider\s*\(", text)
    assert new_match, "extension.ts 找不到 ``new WebviewProvider(`` 调用"
    args_block = _extract_block_by_brace.__doc__  # placeholder to silence linters
    del args_block
    paren_start = new_match.end() - 1
    depth = 0
    end_idx = -1
    for idx in range(paren_start, len(text)):
        ch = text[idx]
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                end_idx = idx
                break
    assert end_idx > 0, "无法平衡 ``new WebviewProvider(...)`` 括号"
    args_text = text[paren_start + 1 : end_idx]
    assert re.search(r"\bEXT_VERSION\b", args_text), (
        "extension.ts ``new WebviewProvider(...)`` 调用必须把 EXT_VERSION 传进去；"
        " 缺它则 webview 不知道版本号，settings 页面 footer 会显示 0.0.0。"
    )


# ---------------------------------------------------------------------------
# C. ``extension.ts::activate`` 改 async，locale 加载并行
# ---------------------------------------------------------------------------


def test_c_activate_is_async() -> None:
    """``activate`` 必须签名为 ``async function activate(...): Promise<void>``。"""
    text = _read(EXTENSION_TS)
    assert re.search(
        r"async\s+function\s+activate\s*\([^)]*\)\s*:\s*Promise<\s*void\s*>", text
    ), (
        "extension.ts ``activate`` 应当签名为 ``async function activate(context):"
        " Promise<void>``；改 async 是 R20.13-C 让 locale 并行 readFile 的前置条件。"
    )


def test_c_locale_loading_uses_promises_read_file_and_parallel() -> None:
    """``activate`` 内 locale 加载用 ``fs.promises.readFile + Promise.all`` 并行。

    pre-fix 串行 ``for (const loc of [...]) fs.readFileSync(...)``；
    post-fix 必须改 ``await Promise.all(['en','zh-CN'].map(async loc => ...))``
    才能把两次 I/O 排到同一 event loop tick，不再线性等。
    """
    text = _read(EXTENSION_TS)
    body_start = re.search(
        r"function\s+activate\s*\([^)]*\)[^{]*\{", text
    ) or re.search(r"async\s+function\s+activate\s*\([^)]*\)[^{]*\{", text)
    assert body_start
    activate_body = _extract_block_by_brace(text, body_start.end() - 1)
    assert re.search(
        r"Promise\.all\s*\(\s*\[\s*['\"]en['\"]\s*,\s*['\"]zh-CN['\"]\s*\]",
        activate_body,
    ), (
        "activate 应当用 ``Promise.all([...locales].map(async ...))`` 并行加载；"
        " pre-fix 串行 fs.readFileSync 慢一倍。"
    )
    assert "fs.promises.readFile" in activate_body, (
        "activate 内 locale 加载应改用 ``fs.promises.readFile``；"
        " 留着 fs.readFileSync 等于没改。"
    )


def test_c_activate_no_top_level_fs_readFileSync_for_locales() -> None:
    """``activate`` 函数体不应再含 ``fs.readFileSync(localesDir`` 调用。"""
    text = _read(EXTENSION_TS)
    body_start = re.search(r"async\s+function\s+activate\s*\([^)]*\)[^{]*\{", text)
    assert body_start, "activate 必须是 async function"
    body = _extract_block_by_brace(text, body_start.end() - 1)
    # 允许其它地方仍用 fs.readFileSync（比如 build SHA 没替换的 dev 路径），但
    # 「locale 加载循环」场景里不应再出现。具体特征：和 ``localesDir`` / ``loc + '.json'``
    # 相邻。
    locale_sync_patterns = [
        r"fs\.readFileSync\s*\([^)]*localesDir",
        r"fs\.readFileSync\s*\([^)]*loc\s*\+\s*['\"]\.json['\"]",
    ]
    for pat in locale_sync_patterns:
        assert not re.search(pat, body), (
            f"activate 不应再用 ``fs.readFileSync`` 同步加载 locale（pattern: {pat}）；"
            " 改 ``fs.promises.readFile + Promise.all`` 才是 R20.13-C 设计。"
        )


# ---------------------------------------------------------------------------
# D. ``webview-ui.js::ensureI18nReady`` 只 eager-register active + 'en'
# ---------------------------------------------------------------------------


def test_d_ensure_i18n_ready_only_eager_registers_active_plus_en() -> None:
    """``ensureI18nReady`` IIFE 不应再 ``Object.keys(allLocales)`` 全量循环 register。

    pre-fix 启动时迭代所有 locale 调 ``i18n.registerLocale`` ~50-100 µs；
    post-fix 只 register active + 'en' 两条。源码上的特征：不再有
    ``for (var ai = 0; ai < keys.length; ai++)`` 这种循环。
    """
    text = _read(WEBVIEW_UI_JS)
    iife_match = re.search(
        r";\(function\s+ensureI18nReady\s*\(\s*\)\s*\{",
        text,
    )
    assert iife_match, "webview-ui.js 找不到 ensureI18nReady IIFE"
    iife_body = _extract_block_by_brace(text, iife_match.end() - 1)
    assert "Object.keys(allLocales)" not in iife_body, (
        "ensureI18nReady IIFE 不应再 ``Object.keys(allLocales)`` 全量循环 register；"
        " R20.13-D 设计是只 eager-register active + 'en'。"
    )


def test_d_ensure_i18n_ready_registers_active_and_en_fallback() -> None:
    """IIFE 必须有「register active 语言」+「register 'en' fallback」两条路径。"""
    text = _read(WEBVIEW_UI_JS)
    iife_match = re.search(
        r";\(function\s+ensureI18nReady\s*\(\s*\)\s*\{",
        text,
    )
    assert iife_match
    iife_body = _extract_block_by_brace(text, iife_match.end() - 1)
    # 看看 IIFE 里是否提到 activeLang + 'en' 双轨
    assert "activeLang" in iife_body, (
        "IIFE 应使用 ``activeLang`` 变量名表达 active 语言（语义清晰）"
    )
    assert re.search(r"activeLang\s*!==\s*['\"]en['\"]", iife_body), (
        "IIFE 应当有 ``activeLang !== 'en'`` 分支判断 'en' fallback 是否需要额外 register"
    )


def test_d_ensure_locale_registered_helper_exists() -> None:
    """``webview-ui.js`` 应当定义 ``function ensureLocaleRegistered``，
    ``applyServerLanguage`` runtime 切换语言时按需补注册。

    没这个 helper，R20.13-D 的「只 register active + en」会让 server 推送
    ``langDetected`` 到一个未 register 的 locale 时 silently fallback 到英文，
    破坏 i18n 合约。
    """
    text = _read(WEBVIEW_UI_JS)
    assert re.search(r"function\s+ensureLocaleRegistered\s*\(", text), (
        "webview-ui.js 应定义 ``function ensureLocaleRegistered(targetLang)`` helper；"
        " 缺它则 R20.13-D 启动期省的 µs 换不来运行时 i18n 正确性。"
    )


def test_d_apply_server_language_calls_ensure_locale_registered() -> None:
    """``applyServerLanguage`` 必须在 ``setLang`` 之前调 ``ensureLocaleRegistered``。"""
    text = _read(WEBVIEW_UI_JS)
    func_match = re.search(
        r"function\s+applyServerLanguage\s*\(\s*lang\s*\)\s*\{", text
    )
    assert func_match, "webview-ui.js 找不到 applyServerLanguage 函数"
    body = _extract_block_by_brace(text, func_match.end() - 1)
    ensure_match = re.search(r"ensureLocaleRegistered\s*\(", body)
    setlang_match = re.search(r"i18n\.setLang\s*\(", body)
    assert ensure_match, (
        "applyServerLanguage 应在切语言前调 ``ensureLocaleRegistered(normalized)``"
        " 补注册（R20.13-D fallback hook）"
    )
    assert setlang_match, "applyServerLanguage 应当含 ``i18n.setLang(...)``"
    assert ensure_match.start() < setlang_match.start(), (
        "ensureLocaleRegistered 必须在 i18n.setLang 之前；顺序倒了等于"
        " setLang 之后才补 register，``t()`` 在切语言瞬间仍 fallback 英文，race 复活"
    )


# ---------------------------------------------------------------------------
# E. ``webview.ts::_getHtmlContent`` 缓存 inline allLocales JSON
# ---------------------------------------------------------------------------


def test_e_inline_all_locales_cache_fields_declared() -> None:
    """``WebviewProvider`` 应有 ``_cachedInlineAllLocalesJson`` + ``_cachedInlineAllLocalesKey`` 字段。"""
    text = _read(WEBVIEW_TS)
    assert re.search(
        r"private\s+_cachedInlineAllLocalesJson\s*:\s*string\s*\|\s*null", text
    ), "缺 ``_cachedInlineAllLocalesJson: string | null`` 字段"
    assert re.search(
        r"private\s+_cachedInlineAllLocalesKey\s*:\s*string\s*\|\s*null", text
    ), (
        "缺 ``_cachedInlineAllLocalesKey: string | null`` 字段（缓存键，"
        " 用于 _cachedLocales 内容变更时让缓存失效）"
    )


def test_e_constructor_initializes_inline_cache_to_null() -> None:
    """构造器必须把 ``_cachedInlineAllLocalesJson`` / ``_cachedInlineAllLocalesKey`` 初始化为 null。"""
    text = _read(WEBVIEW_TS)
    assert re.search(r"this\._cachedInlineAllLocalesJson\s*=\s*null", text), (
        "构造器应初始化 ``this._cachedInlineAllLocalesJson = null``"
    )
    assert re.search(r"this\._cachedInlineAllLocalesKey\s*=\s*null", text), (
        "构造器应初始化 ``this._cachedInlineAllLocalesKey = null``"
    )


def test_e_get_html_content_uses_cached_inline_all_locales() -> None:
    """``_getHtmlContent`` 应当先查 ``_cachedInlineAllLocalesJson`` 缓存命中。"""
    text = _read(WEBVIEW_TS)
    body = _extract_function_body_after(
        text, r"_getHtmlContent\s*\(\s*webview:\s*vscode\.Webview\s*\)\s*:\s*string"
    )
    assert "_cachedInlineAllLocalesJson" in body, (
        "_getHtmlContent 应当查 ``this._cachedInlineAllLocalesJson`` 缓存；"
        " 不查等于没做 R20.13-E"
    )
    assert "_cachedInlineAllLocalesKey" in body, (
        "_getHtmlContent 应当用 ``this._cachedInlineAllLocalesKey`` 比对签名（locale 名 + key 计数）"
    )


def test_e_inline_all_locales_signature_uses_locale_names_and_key_counts() -> None:
    """缓存键必须把 locale 名 + 各 locale 字典 key 数都吃进去。

    防御 refactor：若键退化到只用 locale 名（如 ``'en|zh-CN'``），那
    ``_cachedLocales`` 内容被换掉时（极少但理论可能，比如 hot-reload 注入
    新的 entries）缓存不会失效，HTML 会拿着过期 JSON。
    """
    text = _read(WEBVIEW_TS)
    body = _extract_function_body_after(
        text, r"_getHtmlContent\s*\(\s*webview:\s*vscode\.Webview\s*\)\s*:\s*string"
    )
    # 关键特征：构建签名时 join 既有 locale 名又有 ``Object.keys(...).length``
    assert re.search(r"Object\.keys\s*\(\s*allLocales\[", body) or re.search(
        r"Object\.keys\s*\(\s*allLocales\s*\[", body
    ), "签名构造必须读 ``Object.keys(allLocales[...]).length`` 反映各 locale entry 大小"


# ---------------------------------------------------------------------------
# 累积 invariants：跨改动的语义合约
# ---------------------------------------------------------------------------


def test_cumulative_no_extensions_get_extension_anywhere_in_get_html_content() -> None:
    """B+F 联合：``_getHtmlContent`` 完全不依赖 ``vscode.extensions.getExtension(...)``。"""
    text = _read(WEBVIEW_TS)
    body = _extract_function_body_after(
        text, r"_getHtmlContent\s*\(\s*webview:\s*vscode\.Webview\s*\)\s*:\s*string"
    )
    assert not re.search(r"vscode\.extensions\.getExtension\s*\(", body), (
        "_getHtmlContent 函数体彻底不应再含 ``vscode.extensions.getExtension(...)`` 调用；"
        " 那是 R20.13-B/F 共同约定的核心契约"
    )


def test_cumulative_ext_version_pipeline_intact() -> None:
    """``extension.ts → webview.ts`` 版本号传输链路一致。"""
    ext_text = _read(EXTENSION_TS)
    wv_text = _read(WEBVIEW_TS)
    assert re.search(r"let\s+EXT_VERSION\s*=", ext_text), (
        "extension.ts 应保留 ``let EXT_VERSION`` 变量"
    )
    assert re.search(r"new\s+WebviewProvider\s*\([\s\S]*?EXT_VERSION", ext_text), (
        "new WebviewProvider 调用必须包含 EXT_VERSION 实参"
    )
    constructor_match = re.search(
        r"constructor\s*\([\s\S]*?\)\s*\{",
        wv_text,
    )
    assert constructor_match
    sig = constructor_match.group(0)
    assert re.search(r"extensionVersion\s*:\s*string", sig), (
        "WebviewProvider constructor 的形参列表必须显式声明 ``extensionVersion: string``"
    )


def test_status_bar_poll_changed_path_does_not_apply_twice() -> None:
    """状态变化轮询路径不应重复写 status bar。

    pre-fix：``changed`` 分支里调用一次 ``applyStatusBarPresentation``，
    随后 ``if (statusBarShown)`` 又调用一次；同一次 ``/api/tasks`` 成功响应会
    重复写 text / tooltip / accessibilityInformation。
    """
    text = _read(EXTENSION_TS)
    body = _extract_function_body_after(
        text, r"const\s+updateStatusBar\s*=\s*async\s*\(\s*\)\s*:\s*Promise<[^>]+>"
    )
    assert re.search(
        r"if\s*\(\s*changed\s*\)[\s\S]*?applyStatusBarPresentation", body
    ), "changed 分支仍应立即刷新 status bar"
    assert "if (!changed && statusBarShown)" in body, (
        "非变化路径才需要用 statusBarShown 做保底刷新；"
        " changed=true 时不能重复调用 applyStatusBarPresentation"
    )
    assert "if (statusBarShown) {\n        applyStatusBarPresentation" not in body
