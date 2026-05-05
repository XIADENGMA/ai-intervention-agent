"""G1 回归：确保 <html dir> 在 Web UI 与 VSCode webview 两侧都被显式注入，
且 setLang() 同步更新 document.documentElement.dir（LTR/RTL 白名单）。

证据来源：
- W3C string-meta 要求 dir 与 lang 同级显式声明。
- intlpull.com 2026 i18n 最佳实践：pseudo-locale 之外最先被忽视的就是 dir 缺失。

本测试纯静态（grep + regex + Jinja context 构造），不启动服务/浏览器，
因此既能跑在 ci_gate 也能跑在单测环境。"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = ROOT / "templates" / "web_ui.html"
WEB_I18N_JS = ROOT / "static" / "js" / "i18n.js"
VSCODE_I18N_JS = ROOT / "packages" / "vscode" / "i18n.js"
VSCODE_WEBVIEW_TS = ROOT / "packages" / "vscode" / "webview.ts"


class TestTemplateDir:
    def test_web_ui_template_has_explicit_dir_attribute(self):
        """templates/web_ui.html 的 <html> 根元素必须同时声明 lang 和 dir。"""
        html = TEMPLATE.read_text(encoding="utf-8")
        match = re.search(r"<html\s+([^>]+)>", html)
        assert match, "templates/web_ui.html 找不到 <html ...> 开标签"
        attrs = match.group(1)
        assert "lang=" in attrs, "<html> 缺少 lang 属性"
        assert "dir=" in attrs, "<html> 缺少 dir 属性（无障碍 + RTL 准备）"

    def test_web_ui_py_injects_html_dir_in_template_context(self):
        """web_ui.py::_get_template_context 必须把 html_dir 注入 Jinja 上下文。"""
        src = (ROOT / "web_ui.py").read_text(encoding="utf-8")
        assert '"html_dir"' in src, "_get_template_context 未向模板注入 html_dir"
        # 白名单必须覆盖主流 RTL 语言前缀（至少 ar/he/fa/ur）
        for prefix in ("ar", "he", "fa", "ur"):
            assert f'"{prefix}"' in src, f"RTL 白名单缺少 {prefix!r} 前缀"


class TestWebI18nJsLangDir:
    """static/js/i18n.js::setLang 必须同时更新 lang + dir。"""

    def test_setLang_updates_dir(self):
        src = WEB_I18N_JS.read_text(encoding="utf-8")
        m = re.search(r"function\s+setLang\s*\([^)]*\)\s*\{([\s\S]*?)\n\s*\}\n", src)
        assert m, "找不到 setLang 函数"
        body = m.group(1)
        assert "documentElement" in body and ".lang" in body, "setLang 未更新 lang"
        assert ".dir" in body, "setLang 未更新 dir"

    def test_langToDir_whitelist_matches_rtl_prefixes(self):
        src = WEB_I18N_JS.read_text(encoding="utf-8")
        assert "langToDir" in src, "static/js/i18n.js 未导出 langToDir 帮助函数"
        for prefix in (
            "ar",
            "he",
            "fa",
            "ur",
            "ps",
            "yi",
            "ug",
            "ckb",
            "ku",
            "dv",
            "sd",
            "iw",
        ):
            assert f"{prefix}" in src, f"langToDir 白名单缺少 {prefix!r}"


class TestVSCodeI18nJsLangDir:
    """packages/vscode/i18n.js::setLang 必须同时更新 lang + dir，
    不能因为是 webview 就跳过（之前版本这里连 lang 都没更新）。"""

    def test_setLang_updates_both(self):
        src = VSCODE_I18N_JS.read_text(encoding="utf-8")
        m = re.search(r"function\s+setLang\s*\([^)]*\)\s*\{([\s\S]*?)\n\s*\}\n", src)
        assert m, "找不到 setLang 函数"
        body = m.group(1)
        assert ".lang" in body and ".dir" in body, "setLang 必须同时更新 lang 和 dir"
        # webview 环境 document 必然存在，但测试环境下守护 try/catch 要在，
        # 避免 Node 侧单测 require 这份 js 时炸在 document 访问上。
        assert "typeof document" in body, (
            "setLang 缺少 DOM 可用性守护（typeof document）"
        )


class TestWebviewTsInjection:
    """packages/vscode/webview.ts HTML 模板注入必须带 dir。"""

    def test_webview_template_injects_html_dir(self):
        src = VSCODE_WEBVIEW_TS.read_text(encoding="utf-8")
        assert "htmlDir" in src, "webview.ts 未计算 htmlDir"
        assert re.search(r'dir="\$\{htmlDir\}"', src), (
            "webview.ts 模板未写出 dir=${htmlDir}"
        )
        for prefix in ("ar", "he", "fa", "ur"):
            # Quote-agnostic：Prettier 把数组字面量 ['ar', ...] 改写成
            # ["ar", ...] 后旧的 single-quote-only 检查会 false-fail；
            # 真正要锁的是「白名单包含这个前缀」，引号风格无关。
            assert re.search(rf"['\"]{re.escape(prefix)}['\"]", src), (
                f"webview.ts RTL 白名单缺少 {prefix!r}"
            )


class TestHtmlDirContextValues:
    """真实调用 _get_template_context（不经 Flask），验证 html_dir 值域。"""

    @pytest.fixture(autouse=True)
    def _setup(self, monkeypatch):
        # 避免触碰全局 config；构造一个最小化 stub
        import web_ui

        class _StubConfig:
            def __init__(self, lang: str) -> None:
                self._lang = lang

            def get_section(self, name: str) -> dict:
                return {"language": self._lang}

        self._web_ui = web_ui
        self._StubConfig = _StubConfig

    def _make_manager(self):
        # WebFeedbackUI 依赖外部资源，这里直接构造一个裸对象，
        # 只测 _get_template_context 上相关属性。
        ui = object.__new__(self._web_ui.WebFeedbackUI)
        return ui

    def _call(self, manager, lang: str) -> dict:
        """用 monkeypatch 切换 get_config().get_section('web_ui')['language']。"""
        # 直接复用模块内的 get_config
        import web_ui

        original = web_ui.get_config
        stub = self._StubConfig(lang)
        web_ui.get_config = lambda: stub  # ty: ignore[invalid-assignment]
        try:
            return manager._get_template_context()
        finally:
            web_ui.get_config = original

    def test_en_is_ltr(self):
        ui = self._make_manager()
        # _get_file_version 之类的会访问磁盘；这里仅断言关心的键，不关心其他。
        # 为了稳健捕捉 io 异常，我们直接读返回 dict 后验证 html_dir。
        ctx = self._call(ui, "en")
        assert ctx.get("html_lang") == "en"
        assert ctx.get("html_dir") == "ltr"

    def test_zh_is_ltr(self):
        ui = self._make_manager()
        ctx = self._call(ui, "zh-CN")
        assert ctx.get("html_lang") == "zh-CN"
        assert ctx.get("html_dir") == "ltr"

    def test_auto_falls_back_to_en_ltr(self):
        ui = self._make_manager()
        ctx = self._call(ui, "auto")
        assert ctx.get("html_lang") == "en"
        assert ctx.get("html_dir") == "ltr"
