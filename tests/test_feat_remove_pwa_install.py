"""``feat-remove-pwa-install`` 回归契约：

cycle-22 用户偏好移除「自定义 PWA 安装提示按钮」(原 R247 / mining-7
Track A)。该 feature 由 2 个 button + 1 个 JS 模块 + 1 块 CSS + 1 个
Python 模板变量 + 4 处 locale block 组成，整体下架后通过本测试锁住
"不会未来被未察觉地恢复"。

设计要点
--------
- PWA **能力本身**保留：``manifest.webmanifest`` + Service Worker
  不动，用户依然可以通过 Chrome 地址栏「安装」图标 / iOS Safari Share
  → 添加到主屏幕 等浏览器原生入口安装。
- 仅去除「自定义胶囊按钮 + Dismiss 叉号」这一 UI 显眼层。
- 故本测试**不**校验 manifest / SW 的存在；它们的 invariant 在其他
  test 文件管控（如 ``test_pwa_icon_assets.py`` / SW 相关 R262）。
- 与 ``feat-remove-favicon-badge`` 同期，组成 cycle-22「UI 显眼层
  减法」批次。
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
STATIC_JS = REPO_ROOT / "src" / "ai_intervention_agent" / "static" / "js"
STATIC_CSS = REPO_ROOT / "src" / "ai_intervention_agent" / "static" / "css"
LOCALES_DIR = REPO_ROOT / "src" / "ai_intervention_agent" / "static" / "locales"
TEMPLATES = REPO_ROOT / "src" / "ai_intervention_agent" / "templates"
WEB_UI_PY = REPO_ROOT / "src" / "ai_intervention_agent" / "web_ui.py"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


class TestJsModuleAbsent(unittest.TestCase):
    """``pwa_install.js`` 及其所有衍生产物必须完整缺席。"""

    def test_source_js_absent(self) -> None:
        self.assertFalse(
            (STATIC_JS / "pwa_install.js").exists(),
            "static/js/pwa_install.js 应已删除（feat-remove-pwa-install）",
        )

    def test_minified_js_absent(self) -> None:
        self.assertFalse(
            (STATIC_JS / "pwa_install.min.js").exists(),
            "static/js/pwa_install.min.js 应已删除（feat-remove-pwa-install）",
        )

    def test_no_precompress_artifacts(self) -> None:
        """``.gz`` / ``.br`` precompress 产物也必须清掉，否则 R213
        invariant 会因「source 已删但 .gz/.br 还在」沉默 fail。"""
        for suffix in (
            "pwa_install.js.gz",
            "pwa_install.js.br",
            "pwa_install.min.js.gz",
            "pwa_install.min.js.br",
        ):
            self.assertFalse(
                (STATIC_JS / suffix).exists(),
                f"static/js/{suffix} 应已删除（cleanup with feat-remove-pwa-install）",
            )


class TestHtmlButtonsAbsent(unittest.TestCase):
    """``web_ui.html`` 中两个按钮 + 引用 script 必须完整缺席。"""

    def setUp(self) -> None:
        self.html = _read(TEMPLATES / "web_ui.html")

    def test_no_pwa_install_button(self) -> None:
        # 用 ``id="`` 前缀锁死，避免被注释里的反引号 ``#pwa-install-btn`` 误命中
        self.assertNotIn(
            'id="pwa-install-btn"',
            self.html,
            "web_ui.html 不应再有 <button id='pwa-install-btn'>",
        )

    def test_no_pwa_install_dismiss_button(self) -> None:
        self.assertNotIn(
            'id="pwa-install-dismiss-btn"',
            self.html,
            "web_ui.html 不应再有 <button id='pwa-install-dismiss-btn'>",
        )

    def test_no_pwa_install_script_tag(self) -> None:
        self.assertNotIn(
            'src="/static/js/pwa_install.js',
            self.html,
            "web_ui.html 不应再有 <script src='/static/js/pwa_install.js'>",
        )

    def test_no_pwa_install_class_usage(self) -> None:
        """不应再有 ``class="...pwa-install-btn..."`` 字面引用（注释除外，
        注释里 ``#pwa-install-btn`` / ``.pwa-install-btn`` 是历史锚点）。"""
        # 抓取 class 属性赋值场景：``class="...pwa-install-btn..."``
        # 用 ``class="`` 前缀严格限定
        self.assertNotIn(
            'class="pwa-install',
            self.html,
            'web_ui.html 不应再有 ``class="pwa-install..."`` 实际 element 引用',
        )


class TestCssRulesAbsent(unittest.TestCase):
    """``main.css`` 中 ``.pwa-install-btn`` / ``.pwa-install-dismiss-btn``
    selector 必须全部移除。注释 ok（文档化锚点）。"""

    def setUp(self) -> None:
        self.css = _read(STATIC_CSS / "main.css")

    def test_no_pwa_install_btn_selector(self) -> None:
        # ``.pwa-install-btn {`` 是 selector body，注释里写 ``.pwa-install-btn``
        # 不会跟 `` { ``。
        self.assertNotRegex(
            self.css,
            r"\.pwa-install-btn\b[^\n]*\{",
            "main.css 不应再有 .pwa-install-btn 选择器规则块",
        )

    def test_no_pwa_install_dismiss_btn_selector(self) -> None:
        self.assertNotRegex(
            self.css,
            r"\.pwa-install-dismiss-btn\b[^\n]*\{",
            "main.css 不应再有 .pwa-install-dismiss-btn 选择器规则块",
        )


class TestPythonTemplateVariableAbsent(unittest.TestCase):
    """``web_ui.py`` 中 ``pwa_install_version`` 模板变量必须移除。"""

    def setUp(self) -> None:
        self.py = _read(WEB_UI_PY)

    def test_no_pwa_install_version_variable(self) -> None:
        self.assertNotIn(
            '"pwa_install_version"',
            self.py,
            "web_ui.py 不应再渲染 pwa_install_version 模板变量",
        )

    def test_no_pwa_install_js_file_reference(self) -> None:
        self.assertNotIn(
            "pwa_install.js",
            self.py,
            "web_ui.py 不应再引用 static/js/pwa_install.js 文件路径",
        )


class TestLocalesPwaInstallBlockAbsent(unittest.TestCase):
    """4 个 locale 文件（en / zh-CN / zh-TW / pseudo）必须移除
    ``page.pwaInstall`` 整个 block。"""

    def _check(self, locale_file: Path) -> None:
        data = json.loads(_read(locale_file))
        page = data.get("page", {})
        self.assertNotIn(
            "pwaInstall",
            page,
            f"{locale_file.name} 不应再有 page.pwaInstall block "
            "(feat-remove-pwa-install)",
        )

    def test_en_clean(self) -> None:
        self._check(LOCALES_DIR / "en.json")

    def test_zh_cn_clean(self) -> None:
        self._check(LOCALES_DIR / "zh-CN.json")

    def test_zh_tw_clean(self) -> None:
        self._check(LOCALES_DIR / "zh-TW.json")

    def test_pseudo_clean(self) -> None:
        self._check(LOCALES_DIR / "_pseudo" / "pseudo.json")


if __name__ == "__main__":
    unittest.main()
