"""``feat-footer-link-plugin`` 回归契约：

VSCode 插件设置页底部"v1.7.X · GitHub"两段视觉合并为单一链接
``[AI Intervention Agent X.Y.Z](GitHub url)``，与 web UI 风格对齐。

背景
----
用户偏好："插件的设置页面的底部 ``v1.7.9 [GitHub]...`` 应该是
``[AI Intervention Agent x.x.x](...)``，这里的 x.x.x 是对应的版本号。
而且样式要符合风格。"

实现要点
--------
- ``packages/vscode/webview.ts``：``.settings-footer`` 内部从 ``span.settings-footer-version``
  + ``a.settings-footer-link`` 两兄弟，重构成单一
  ``a.settings-footer-link`` 同时承担版本号显示 + GitHub 跳转。
- **cycle-22 restyle**：进一步把 ``<a>`` 内部拆为 ``<svg class="github-icon">``
  +  ``<span class="settings-footer-link-text">``，以匹配 web UI 的胶囊按钮
  视觉（圆角 + 半透明背景 + GitHub octocat 图标）。因 i18n.js 的
  ``translateDOM`` 会把 ``[data-i18n]`` 元素的 textContent 整体覆盖，故
  ``data-i18n="settings.footer.versionLink"`` + ``data-i18n-version``
  必须落在 ``<span>`` 上（落在 ``<a>`` 会清掉 svg），``data-i18n-title``
  继续落在 ``<a>`` 上（title 属性是 attribute setter，不影响子元素）。
- ``packages/vscode/webview.css``：删 ``.settings-footer-version::after``
  中点伪元素；``.settings-footer-link`` 升级为胶囊按钮风格（圆角 8px +
  半透明灰底 + ``--vscode-foreground`` 文字色），通过中性灰 ``rgba(127,
  127, 127, .X)`` 适配 dark / light / hc 三种主题。
- ``packages/vscode/locales/{en,zh-CN}.json``：``settings.footer.version`` +
  ``settings.footer.github`` 两个 key 退役，换成 ``settings.footer.versionLink``
  （含 ``{{version}}`` 插值）+ ``settings.footer.versionLinkTitle``（title 属性）。
- ``packages/vscode/i18n-keys.d.ts``：union 类型与 ``I18N_KEYS`` 数组同步更新。
- ``packages/vscode/test/extension.test.js``：更新 mustache 插值 unit test 校验新
  template ``"AI Intervention Agent {{version}}"``。

本测试覆盖
----------
1. webview.ts：``.settings-footer-version`` span 必须缺席；单一
   ``a.settings-footer-link`` 必须包含 ``data-i18n-title="settings.footer.versionLinkTitle"``
   + 子元素 ``span.settings-footer-link-text`` 承载 ``data-i18n="settings.footer.versionLink"``
   + ``data-i18n-version="${extensionVersion}"``；anchor 内必须有
   ``svg.github-icon``（fill="currentColor" 让图标跟随主题色）。
2. webview.css：``.settings-footer-version`` 选择器必须移除；
   ``.settings-footer-link`` 必须仍定义且引入 ``focus-visible`` 强调框；
   cycle-22 起必须用 ``border-radius`` / ``inline-flex`` 胶囊布局。
3. locales：三个 locale 必须有新 ``versionLink`` / ``versionLinkTitle``
   两个 key，且旧 ``version`` / ``github`` 两个 key 必须移除。
4. i18n-keys.d.ts：union 与 array 必须同步。
5. zh-CN 文案确实是中文（不退化为英文 fallback）。
6. web UI 与 plugin 端 footer 链接结构一致性：两个端都用 single anchor
   嵌入 ``AI Intervention Agent {{version}}``，且 anchor 内必须有
   GitHub octocat svg 作为视觉锚点。
"""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PLUGIN_DIR = REPO_ROOT / "packages" / "vscode"
WEBVIEW_TS = PLUGIN_DIR / "webview.ts"
WEBVIEW_CSS = PLUGIN_DIR / "webview.css"
PLUGIN_EN = PLUGIN_DIR / "locales" / "en.json"
PLUGIN_ZH = PLUGIN_DIR / "locales" / "zh-CN.json"
PLUGIN_PSEUDO = PLUGIN_DIR / "locales" / "_pseudo" / "pseudo.json"
I18N_KEYS_DTS = PLUGIN_DIR / "i18n-keys.d.ts"
WEB_UI_HTML = REPO_ROOT / "src" / "ai_intervention_agent" / "templates" / "web_ui.html"
WEB_UI_EN = (
    REPO_ROOT / "src" / "ai_intervention_agent" / "static" / "locales" / "en.json"
)


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


class TestWebviewTsFooterMerged(unittest.TestCase):
    """``webview.ts`` 模板中 footer 区结构必须只剩单一 anchor。"""

    def setUp(self) -> None:
        self.src = _read(WEBVIEW_TS)

    def test_no_legacy_version_span(self) -> None:
        self.assertNotIn(
            'class="settings-footer-version"',
            self.src,
            ".settings-footer-version span 应已合并到 .settings-footer-link",
        )

    def test_footer_link_anchor_has_required_attrs(self) -> None:
        """cycle-22 起 anchor 自身只承担跳转 + title 翻译；
        ``data-i18n`` / ``data-i18n-version`` 因 svg 子元素存在被迁到
        内部 ``<span class="settings-footer-link-text">``。"""
        m = re.search(
            r'<a\b[^>]*class="settings-footer-link"[^>]*>',
            self.src,
        )
        self.assertIsNotNone(m, '未在 webview.ts 找到 <a class="settings-footer-link">')
        assert m is not None
        anchor = m.group(0)
        self.assertIn('data-i18n-title="settings.footer.versionLinkTitle"', anchor)
        self.assertIn('href="${githubUrl}"', anchor)
        self.assertIn('target="_blank"', anchor)
        self.assertIn('rel="noopener noreferrer"', anchor)
        self.assertNotIn(
            'data-i18n="settings.footer.versionLink"',
            anchor,
            "cycle-22 起 data-i18n 必须落在内部 <span> 上而非 <a>，"
            "否则 i18n.translateDOM() 的 textContent 覆写会清掉 svg 子元素",
        )

    def test_footer_link_text_span_carries_i18n(self) -> None:
        """``<span class="settings-footer-link-text">`` 必须承载 i18n key +
        version 插值参数（cycle-22 重构产物）。"""
        m = re.search(
            r'<span\b[^>]*class="settings-footer-link-text"[^>]*>',
            self.src,
        )
        self.assertIsNotNone(
            m, '未在 webview.ts 找到 <span class="settings-footer-link-text">'
        )
        assert m is not None
        span = m.group(0)
        self.assertIn('data-i18n="settings.footer.versionLink"', span)
        self.assertIn('data-i18n-version="${extensionVersion}"', span)

    def test_footer_link_anchor_contains_github_svg(self) -> None:
        """anchor 内必须包含一个 ``svg.github-icon``，与 web ``.version-link``
        的视觉布局对齐（cycle-22 restyle）。"""
        # 多行匹配 anchor 块（含子元素）。锚定 closing </a> 之前必须出现 svg
        # 与 github-icon class。
        m = re.search(
            r'<a\b[^>]*class="settings-footer-link"[^>]*>(.*?)</a>',
            self.src,
            re.DOTALL,
        )
        self.assertIsNotNone(
            m,
            '未能匹配 <a class="settings-footer-link"> ... </a> 完整块',
        )
        assert m is not None
        body = m.group(1)
        self.assertIn(
            'class="github-icon"',
            body,
            "anchor 内必须含 svg.github-icon（与 web UI .version-link 视觉对齐）",
        )
        self.assertRegex(
            body,
            r'<svg\b[^>]*\bfill="currentColor"',
            'svg 必须用 fill="currentColor" 继承链接文字色，便于 dark/light/hc 主题自适应',
        )

    def test_footer_uses_new_tl_keys_not_legacy(self) -> None:
        # tl("settings.footer.versionLink", ...) 必须出现
        self.assertIn(
            'tl("settings.footer.versionLink"',
            self.src,
            'webview.ts 必须用 tl("settings.footer.versionLink", { version }) 取文案',
        )
        # 旧 key 必须退役
        for legacy in ('"settings.footer.version"', '"settings.footer.github"'):
            self.assertNotIn(
                legacy,
                self.src,
                f"webview.ts 不应再引用 {legacy} 旧 key",
            )


class TestWebviewCssFooterMigration(unittest.TestCase):
    """CSS 中 ``.settings-footer-version::after`` 中点伪元素移除；
    ``.settings-footer-link`` 仍存在且强化。"""

    def setUp(self) -> None:
        self.css = _read(WEBVIEW_CSS)

    def test_no_legacy_version_selector(self) -> None:
        self.assertNotIn(
            ".settings-footer-version",
            self.css,
            "webview.css 不应再有 .settings-footer-version 选择器",
        )

    def test_footer_link_still_defined(self) -> None:
        self.assertRegex(
            self.css,
            r"\.settings-footer-link\s*\{",
            "webview.css 必须仍定义 .settings-footer-link",
        )

    def test_footer_link_has_focus_visible(self) -> None:
        self.assertIn(
            ".settings-footer-link:focus-visible",
            self.css,
            "webview.css 必须为 .settings-footer-link 提供 :focus-visible 强调框（无障碍）",
        )

    def test_footer_link_uses_pill_button_layout(self) -> None:
        """cycle-22 restyle：``.settings-footer-link`` 必须呈胶囊按钮样式
        （``border-radius`` 圆角 + ``inline-flex`` 让 svg + 文字横向排齐）。"""
        # 抓 .settings-footer-link { ... } 第一个块
        m = re.search(
            r"\.settings-footer-link\s*\{([^}]*)\}",
            self.css,
            re.DOTALL,
        )
        self.assertIsNotNone(m, "未找到 .settings-footer-link 选择器块")
        assert m is not None
        block = m.group(1)
        self.assertIn(
            "inline-flex",
            block,
            ".settings-footer-link 必须用 ``display: inline-flex`` 让 svg + 文字"
            "在同一行对齐（与 web .version-link 视觉对齐）",
        )
        self.assertRegex(
            block,
            r"border-radius:\s*[0-9]",
            ".settings-footer-link 必须有 border-radius（胶囊按钮特征）",
        )

    def test_footer_link_themes_neutrally(self) -> None:
        """主题适配策略：用 ``rgba(127, 127, 127, .X)`` 中性灰底，无需 @media
        分支即可在 dark / light / hc 三种主题下都不突兀。"""
        m = re.search(
            r"\.settings-footer-link\s*\{([^}]*)\}",
            self.css,
            re.DOTALL,
        )
        assert m is not None
        block = m.group(1)
        # 既能用 var(--vscode-foreground) 文字色，也能用 rgba 灰底
        self.assertIn(
            "var(--vscode-foreground)",
            block,
            "应用 var(--vscode-foreground) 作为文字色（自动跟随 VSCode 主题）",
        )
        self.assertRegex(
            block,
            r"rgba\(\s*127\s*,\s*127\s*,\s*127\s*,",
            "应用中性灰 rgba(127, 127, 127, .X) 作为背景/边框 fallback "
            "（dark / light / hc 主题下均不突兀）",
        )


class TestLocalesUpdated(unittest.TestCase):
    """三个 plugin locale + i18n-keys.d.ts 必须同步迁移到新 key。"""

    def _load_footer(self, p: Path) -> dict[str, object]:
        with p.open(encoding="utf-8") as f:
            data = json.load(f)
        return data["settings"]["footer"]

    def _assert_keys_present(self, footer: dict[str, object], locale: str) -> None:
        for k in ("versionLink", "versionLinkTitle"):
            self.assertIn(k, footer, f"{locale} settings.footer.{k} 必须存在")
            v = footer[k]
            self.assertIsInstance(v, str, f"{locale} settings.footer.{k} 必须是字符串")
            assert isinstance(v, str)
            self.assertTrue(v.strip(), f"{locale} settings.footer.{k} 必须非空")

    def _assert_legacy_removed(self, footer: dict[str, object], locale: str) -> None:
        for k in ("version", "github"):
            self.assertNotIn(
                k,
                footer,
                f"{locale} settings.footer.{k} 应已退役（被 versionLink 取代）",
            )

    def test_en_locale_migration(self) -> None:
        f = self._load_footer(PLUGIN_EN)
        self._assert_keys_present(f, "plugin en.json")
        self._assert_legacy_removed(f, "plugin en.json")
        self.assertIn(
            "{{version}}",
            str(f["versionLink"]),
            "versionLink 必须含 {{version}} mustache 占位符以便插值",
        )

    def test_zh_locale_migration(self) -> None:
        f = self._load_footer(PLUGIN_ZH)
        self._assert_keys_present(f, "plugin zh-CN.json")
        self._assert_legacy_removed(f, "plugin zh-CN.json")

    def test_pseudo_locale_migration(self) -> None:
        f = self._load_footer(PLUGIN_PSEUDO)
        self._assert_keys_present(f, "plugin pseudo.json")
        self._assert_legacy_removed(f, "plugin pseudo.json")

    def test_zh_link_title_actually_chinese(self) -> None:
        """zh versionLinkTitle 应包含中文字符。"""
        f = self._load_footer(PLUGIN_ZH)
        title = f["versionLinkTitle"]
        self.assertIsInstance(title, str)
        assert isinstance(title, str)
        has_chinese = any("\u4e00" <= ch <= "\u9fff" for ch in title)
        self.assertTrue(
            has_chinese,
            f"zh versionLinkTitle 应含中文字符（实际值：{title!r}）",
        )


class TestI18nKeysDtsSynced(unittest.TestCase):
    """``i18n-keys.d.ts`` 的 union literal 与 ``I18N_KEYS`` 数组必须同步。"""

    def setUp(self) -> None:
        self.src = _read(I18N_KEYS_DTS)

    def test_union_has_new_keys(self) -> None:
        for k in (
            '"settings.footer.versionLink"',
            '"settings.footer.versionLinkTitle"',
        ):
            self.assertIn(k, self.src, f"i18n-keys.d.ts union 必须含 {k}")

    def test_union_no_legacy_keys(self) -> None:
        for k in (
            '"settings.footer.version"',
            '"settings.footer.github"',
        ):
            self.assertNotIn(
                k,
                self.src,
                f"i18n-keys.d.ts 不应再列举旧 key {k}",
            )


class TestWebVsPluginFooterParity(unittest.TestCase):
    """web UI 与 plugin 两端 footer 链接的结构 / 文案模板应一致。"""

    def test_both_ends_use_AI_Intervention_Agent_label(self) -> None:
        plugin_label = json.loads(_read(PLUGIN_EN))["settings"]["footer"]["versionLink"]
        # 注意 web UI 是在 HTML 模板里硬编码 ``AI Intervention Agent {{ version }}``
        web_html = _read(WEB_UI_HTML)
        self.assertEqual(
            plugin_label,
            "AI Intervention Agent {{version}}",
            "plugin en footer 必须用 'AI Intervention Agent {{version}}' 模板",
        )
        self.assertIn(
            "AI Intervention Agent {{ version }}",
            web_html,
            "web UI 模板必须含 'AI Intervention Agent {{ version }}' 文本（feat-footer-link-web）",
        )

    def test_both_ends_link_to_github(self) -> None:
        # web UI 用 ``{{ github_url }}``，plugin 用 ``${githubUrl}``，
        # 两个都指向同一 EXT_GITHUB_URL 常量。
        self.assertIn("EXT_GITHUB_URL", _read(WEBVIEW_TS))
        # web UI 模板的 anchor 持有 href="{{ github_url }}"
        web_html = _read(WEB_UI_HTML)
        self.assertIn('href="{{ github_url }}"', web_html)

    def test_web_ui_legacy_github_title_locale_removed(self) -> None:
        """web UI 端 ``page.githubTitle`` 已被 ``page.versionLinkTitle`` 取代
        （feat-footer-link-web），与 plugin 端 ``settings.footer.versionLinkTitle``
        命名对齐。"""
        en = json.loads(_read(WEB_UI_EN))
        self.assertIn("versionLinkTitle", en["page"])
        self.assertNotIn("githubTitle", en["page"])


if __name__ == "__main__":
    unittest.main()
