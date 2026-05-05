"""R21.1：``templates/web_ui.html`` ``<head>`` 关键资源 preload 不变量。

设计目标
========
R20.x 把 Web UI 子进程冷启动从 ~1980 ms 压到 ~360 ms，剩下 ~360 ms 里
**浏览器侧 critical-path 加载**（HTML → 解析 → defer script 串行下载）成了
新的瓶颈。R21.1 用 ``<link rel="preload" as="script">`` 在 ``<head>`` 早期
告诉浏览器去并行下载 body 末尾才声明的 defer 脚本（``app.js`` /
``multi_task.js`` / ``i18n.js`` / ``state.js``）。预期 FCP 提早 30-100 ms。

为什么需要 invariants
======================
preload 的 cache 命中**必须**满足"URL 完全相等"约束：

- preload 的 ``href`` 与下游 ``<script src=>`` 任何一个字节不同
  （包括 ``?v=`` 版本号 query），浏览器都会判定为不同资源，**重新下载**，
  此时不仅 preload 的开销是浪费，devtools 还会刷红色 ``unused preload``
  警告，PR review 期间很容易被 squash 掉认为是 dead code。

所以这条测试的核心目的是**字节级 URL 一致性 forward lock** + ``preload``
出现位置必须在 ``<head>`` 内、必须在 ``<body>`` 之前的**结构 invariant**。

测试矩阵
========
1. **存在性**：``<head>`` 必须包含 ``app.js`` / ``multi_task.js`` /
   ``i18n.js`` / ``state.js`` 这 4 条 preload。
2. **URL 一致性**：每条 preload 的 ``href``（含 Jinja2 占位符）必须
   与 body 末尾相同名字 ``<script>`` 的 ``src`` 完全相等。
3. **位置 invariant**：preload 必须出现在 ``<head>`` 块内、且在 body 中
   对应 ``<script>`` 出现位置之前——否则浏览器会先解析 script、自己发请求，
   preload 反而变成 redundant double-fetch。
4. **as="script" 强制**：preload 必须有 ``as="script"`` 属性；preload 的
   spec 要求显式 destination，缺失会被浏览器降级为 ``Cache-Control``-only
   预取，丢失 preload 的优先级提升语义。
5. **不要 preload 不需要 preload 的资源**：CSS 已经 ``<link
   rel="stylesheet">`` 同步加载，再 preload 一遍是重复工作；
   ``mathjax-loader.js`` 在 head 早期就声明了 defer，浏览器扫到就发
   请求，preload 没增量；这条测试用 source-text 检查防止后续 PR 误加。

测试不验证什么
===============
- 不验证浏览器实际行为（preload 是否生效、FCP 是否真的提早）：
  浏览器侧度量没有稳定 stub，留给手动 lighthouse / WebPageTest。
- 不验证 ``?v={{ ... }}`` 占位符的具体哈希值：版本号是渲染期由
  ``_get_template_context()`` 算出来的，单测只关心**模板里写的**变量名。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
TEMPLATE_PATH = REPO_ROOT / "templates" / "web_ui.html"


# ---------------------------------------------------------------------------
# 工具：分别提取 <head> 与 <body> 区段，避免误把 body 里的 preload 当 head 项
# ---------------------------------------------------------------------------


def _read_template() -> str:
    assert TEMPLATE_PATH.is_file(), f"模板缺失：{TEMPLATE_PATH}"
    return TEMPLATE_PATH.read_text(encoding="utf-8")


def _extract_head(text: str) -> str:
    """抽出 ``<head>...</head>`` 内容。模板 head 形态稳定（有显式闭合标签）。"""
    m = re.search(r"<head\b[^>]*>([\s\S]*?)</head>", text, re.IGNORECASE)
    assert m is not None, "模板找不到 <head>...</head>"
    return m.group(1)


def _extract_body(text: str) -> str:
    """抽出 ``<body>...</body>`` 内容。"""
    m = re.search(r"<body\b[^>]*>([\s\S]*?)</body>", text, re.IGNORECASE)
    assert m is not None, "模板找不到 <body>...</body>"
    return m.group(1)


def _find_preload_hrefs(head_html: str) -> list[str]:
    """返回 head 内所有 ``<link rel="preload" ... href="..." as="script">`` 的 href 列表。

    用 ``[^>]*?`` 而不是 ``.+?`` 是因为 ``<link>`` 是 void element，没有闭合，
    属性可能跨行（HTML 多行格式化），但绝不会跨过 ``>``。
    """
    hrefs: list[str] = []
    pattern = re.compile(
        r'<link\b[^>]*?\brel\s*=\s*"preload"[^>]*?>',
        re.IGNORECASE,
    )
    for m in pattern.finditer(head_html):
        tag = m.group(0)
        # 必须是 as="script" 才认；as="style" 是给 CSS 的
        if not re.search(r'\bas\s*=\s*"script"', tag, re.IGNORECASE):
            continue
        href_m = re.search(r'\bhref\s*=\s*"([^"]+)"', tag)
        if href_m:
            hrefs.append(href_m.group(1))
    return hrefs


def _find_script_srcs(html: str) -> list[str]:
    """返回 ``<script src="...">`` 的 src 列表（保持出现顺序）。"""
    srcs: list[str] = []
    for m in re.finditer(
        r'<script\b[^>]*?\bsrc\s*=\s*"([^"]+)"[^>]*>', html, re.IGNORECASE
    ):
        srcs.append(m.group(1))
    return srcs


# ---------------------------------------------------------------------------
# 1. 存在性：4 条核心 preload 必须出现在 <head>
# ---------------------------------------------------------------------------

# (preload href, 下游 body script 中相同名字的 src)
EXPECTED_PRELOADS = [
    "/static/js/app.js?v={{ app_version }}",
    "/static/js/multi_task.js?v={{ multi_task_version }}",
    "/static/js/i18n.js",
    "/static/js/state.js",
]


class TestPreloadPresence:
    """存在性 forward lock：任何一条被删都立刻 fail。"""

    @pytest.mark.parametrize("expected", EXPECTED_PRELOADS)
    def test_preload_exists(self, expected: str) -> None:
        head = _extract_head(_read_template())
        hrefs = _find_preload_hrefs(head)
        assert expected in hrefs, (
            f"R21.1 期望 ``<link rel='preload' href='{expected}' as='script'>`` "
            f"出现在 ``<head>``，实际 head 里 as='script' 的 preload 列表："
            f"\n{hrefs}\n"
            "FCP 优化的核心是让浏览器在 head 解析阶段就并行下载下游 defer 脚本。"
        )

    def test_preload_count(self) -> None:
        """精确 4 条；多 1 条少 1 条都要让作者解释，避免悄悄漂移成 8 条
        把带宽全占满（preload 太多反而拖慢真正关键资源的优先级）。"""
        head = _extract_head(_read_template())
        hrefs = _find_preload_hrefs(head)
        assert len(hrefs) == len(EXPECTED_PRELOADS), (
            f"R21.1 期望 head 内有 {len(EXPECTED_PRELOADS)} 条 ``as=script`` preload，"
            f"实际 {len(hrefs)} 条：\n{hrefs}\n"
            "增加 preload 之前请评估带宽优先级影响——参考 web.dev/preload-critical-assets。"
        )


# ---------------------------------------------------------------------------
# 2. URL 一致性：preload href 必须与 body 中同名 script src 字节级相等
# ---------------------------------------------------------------------------


class TestPreloadUrlConsistency:
    """URL **完全相等** invariant：preload href 与 body script src 必须字节相等。

    任何一个字节差异（包括 ``?v=`` 占位符不一致）都会让浏览器把 preload 与
    实际 script 当成不同资源，preload 失效。
    """

    def test_app_js_preload_matches_body_src(self) -> None:
        text = _read_template()
        body = _extract_body(text)
        body_srcs = _find_script_srcs(body)
        target = "/static/js/app.js?v={{ app_version }}"
        assert target in body_srcs, (
            f'找不到 body 内 ``<script src="{target}">``；'
            f"实际 body script src 列表前 12 项：\n{body_srcs[:12]}\n"
            "preload 与实际 script 的 ``?v=`` 占位符必须保持同名（``app_version``）。"
        )

    def test_multi_task_js_preload_matches_body_src(self) -> None:
        text = _read_template()
        body = _extract_body(text)
        body_srcs = _find_script_srcs(body)
        target = "/static/js/multi_task.js?v={{ multi_task_version }}"
        assert target in body_srcs, (
            f'找不到 body 内 ``<script src="{target}">``；'
            f"实际 body script src 列表前 12 项：\n{body_srcs[:12]}"
        )

    def test_i18n_js_preload_matches_body_src(self) -> None:
        body = _extract_body(_read_template())
        body_srcs = _find_script_srcs(body)
        assert "/static/js/i18n.js" in body_srcs, (
            '找不到 body 内 ``<script src="/static/js/i18n.js">``。'
        )

    def test_state_js_preload_matches_body_src(self) -> None:
        body = _extract_body(_read_template())
        body_srcs = _find_script_srcs(body)
        assert "/static/js/state.js" in body_srcs, (
            '找不到 body 内 ``<script src="/static/js/state.js">``。'
        )


# ---------------------------------------------------------------------------
# 3. 位置 invariant：preload 必须在 head 内（不能在 body 里）
# ---------------------------------------------------------------------------


class TestPreloadPosition:
    def test_preload_links_only_in_head(self) -> None:
        """body 内不该出现 ``rel="preload" as="script"`` ——
        body 里的 preload 几乎肯定是误改，浏览器看到时实际 script 已经被解析、
        发请求了，重复下载。"""
        body = _extract_body(_read_template())
        body_preload_count = len(
            re.findall(
                r'<link\b[^>]*?\brel\s*=\s*"preload"[^>]*?\bas\s*=\s*"script"',
                body,
                re.IGNORECASE,
            )
        )
        assert body_preload_count == 0, (
            f"R21.1 期望所有 ``rel='preload' as='script'`` 都在 ``<head>`` 内，"
            f"但 body 里发现 {body_preload_count} 条；"
            "body 里的 preload 在 HTML 解析顺序上**晚于**实际 script 标签，"
            "此时浏览器已经发了原 script 请求，preload 反而变成 double-fetch。"
        )

    @pytest.mark.parametrize("expected", EXPECTED_PRELOADS)
    def test_preload_appears_before_script(self, expected: str) -> None:
        """preload 标签必须出现在文档的 script 标签**之前**，否则 preload
        失去抢先并行下载的语义。

        实现：以原文档（不分 head/body）的字节偏移做比较。
        """
        text = _read_template()
        # preload link 在 head 里的字节偏移
        link_pat = re.compile(
            r'<link\b[^>]*?\brel\s*=\s*"preload"[^>]*?\bhref\s*=\s*"'
            + re.escape(expected)
            + r'"[^>]*?>',
            re.IGNORECASE,
        )
        link_match = link_pat.search(text)
        assert link_match is not None, (
            f"找不到 ``<link rel='preload' href='{expected}'>``——"
            "可能被换行重排了，更新 _find_preload_hrefs 的解析或 EXPECTED_PRELOADS 列表。"
        )

        # 同名 src 的 <script> 标签字节偏移
        script_pat = re.compile(
            r'<script\b[^>]*?\bsrc\s*=\s*"' + re.escape(expected) + r'"[^>]*>',
            re.IGNORECASE,
        )
        script_match = script_pat.search(text)
        assert script_match is not None, (
            f"找不到 ``<script src='{expected}'>``——R21.1 假设 body 仍有同名 script，"
            "如果 script 被移除了，preload 也应该一起移除。"
        )

        assert link_match.start() < script_match.start(), (
            f"R21.1 invariant 违反：preload(``{expected}``) 在文档字节偏移 "
            f"{link_match.start()}，但同名 script 在 {script_match.start()}，"
            "preload 必须出现在 script **之前**才有抢先下载语义。"
        )


# ---------------------------------------------------------------------------
# 4. as="script" 强制：preload 必须显式声明 destination
# ---------------------------------------------------------------------------


class TestPreloadAttributes:
    @pytest.mark.parametrize("expected", EXPECTED_PRELOADS)
    def test_preload_has_as_script_attribute(self, expected: str) -> None:
        text = _read_template()
        link_pat = re.compile(
            r'<link\b[^>]*?\brel\s*=\s*"preload"[^>]*?\bhref\s*=\s*"'
            + re.escape(expected)
            + r'"[^>]*?>',
            re.IGNORECASE,
        )
        m = link_pat.search(text)
        assert m is not None, f"找不到 preload(``{expected}``)。"
        tag = m.group(0)
        assert re.search(r'\bas\s*=\s*"script"', tag, re.IGNORECASE), (
            f"R21.1 invariant 违反：preload(``{expected}``) 必须显式声明 "
            '``as="script"``，否则浏览器无法预知资源类型，会降级为 '
            "Cache-Control-only 预取，丢失优先级语义。\n"
            f"当前 tag：{tag}"
        )


# ---------------------------------------------------------------------------
# 5. 反过来锁：不要错误地 preload "不该 preload" 的资源
# ---------------------------------------------------------------------------


class TestPreloadDoesNotIncludeAntiPattern:
    """防止后续 PR 误加 main.css / mathjax-loader.js 等"加了反而退化"的 preload。

    main.css 已经在 head 里 ``<link rel='stylesheet'>`` 同步加载，
    再 preload 一次会被 Chrome devtools 报 ``preloaded twice`` 警告。

    mathjax-loader.js 在 head 早期就 ``<script defer>``，浏览器扫到立即
    发请求，preload 没增量。
    """

    def test_main_css_not_preloaded(self) -> None:
        head = _extract_head(_read_template())
        # 找 head 内所有 preload，看有没有 main.css 这条
        for tag_match in re.finditer(
            r'<link\b[^>]*?\brel\s*=\s*"preload"[^>]*?>',
            head,
            re.IGNORECASE,
        ):
            tag = tag_match.group(0)
            href_m = re.search(r'\bhref\s*=\s*"([^"]+)"', tag)
            if href_m and "main.css" in href_m.group(1):
                msg = (
                    f"R21.1 anti-pattern：``{href_m.group(1)}`` 被 preload。"
                    " main.css 已经是 head 内 ``<link rel='stylesheet'>`` 同步加载，"
                    "再 preload 一次会触发 Chrome ``Resource was preloaded but used twice`` 警告。"
                )
                pytest.fail(msg)  # ty: ignore[invalid-argument-type]

    def test_mathjax_loader_not_preloaded(self) -> None:
        head = _extract_head(_read_template())
        for tag_match in re.finditer(
            r'<link\b[^>]*?\brel\s*=\s*"preload"[^>]*?>',
            head,
            re.IGNORECASE,
        ):
            tag = tag_match.group(0)
            href_m = re.search(r'\bhref\s*=\s*"([^"]+)"', tag)
            if href_m and "mathjax-loader" in href_m.group(1):
                msg = (
                    "R21.1 anti-pattern：``mathjax-loader.js`` 被 preload。"
                    " 它在 head 早期就 ``<script defer>``，浏览器扫到 head 时已经"
                    "在并行下载，再加 preload 没有增量收益。"
                )
                pytest.fail(msg)  # ty: ignore[invalid-argument-type]


# ---------------------------------------------------------------------------
# 6. CSP / 安全 invariant：preload link 不需要 nonce（声明性，非执行性）
# ---------------------------------------------------------------------------


class TestPreloadNoNonceRequired:
    """preload ``<link>`` 不应该携带 ``nonce=`` 属性——它不会执行 JS，CSP 不约束它。

    历史上有人误以为所有 ``<link>`` 都得加 nonce 来"对齐"，结果 nonce 失败时
    preload 还是会被浏览器接受（因为 CSP 不管 link rel=preload），但代码注释
    会让 reviewer 错以为我们依赖 nonce 验证 preload，引发误读。
    """

    @pytest.mark.parametrize("expected", EXPECTED_PRELOADS)
    def test_preload_does_not_carry_nonce(self, expected: str) -> None:
        text = _read_template()
        link_pat = re.compile(
            r'<link\b[^>]*?\brel\s*=\s*"preload"[^>]*?\bhref\s*=\s*"'
            + re.escape(expected)
            + r'"[^>]*?>',
            re.IGNORECASE,
        )
        m = link_pat.search(text)
        assert m is not None
        tag = m.group(0)
        assert "nonce=" not in tag.lower(), (
            f"R21.1 不变量：preload link(``{expected}``) 不需要 ``nonce=``。"
            "preload 是声明性资源提示，不执行任何脚本，CSP 不约束它；"
            "加 nonce 会误导 reviewer 以为我们依赖 nonce 验证 preload。\n"
            f"当前 tag：{tag}"
        )
