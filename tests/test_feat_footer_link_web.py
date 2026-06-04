"""``feat-footer-link-web`` 回归契约：

设置页底部"AI Intervention Agent v X.Y.Z + GitHub"两段视觉合并为单一链接
``[AI Intervention Agent X.Y.Z](GitHub url)``。

背景
----
用户偏好："web 页面上设置页面的底部 ``AI Intervention Agent vunknown
[GitHub](https://github.com/XIADENGMA/ai-intervention-agent)``，这三个应该都在
``[GitHub](https://github.com/XIADENGMA/ai-intervention-agent)`` 这个按钮里面，
也就是 ``[AI Intervention Agent x.x.x](GitHub url)``。"

实现要点
--------
- HTML：``<div class="version-info">`` 下不再有 ``.version-text`` / ``.version-name``
  / ``.version-number`` / ``.github-link`` 这四种旧 class；改为单一
  ``<a class="version-link">`` 内嵌 ``<svg.github-icon>`` + ``<span.version-link-text>``，
  span 文本是 ``AI Intervention Agent {{ version }}``（合并 name + version）。
- CSS：删除 ``.version-text`` / ``.version-name`` / ``.version-number`` / ``.github-link``
  以及对应的 ``[data-theme="light"]`` 浅色覆盖，新增 ``.version-link`` / ``.version-link-text``
  样式（沿用原 ``.github-link`` 视觉规格）。
- i18n：``page.githubTitle`` 退役，换成 ``page.versionLinkTitle``（含项目全名 + 操作动词），
  三个 locale 同步。
- 不动后端 ``version`` / ``github_url`` 两个模板变量 —— 它们已被 BUG3 修好且其他
  invariant（R220 / R244 等）锁着。
"""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
WEB_UI_HTML = REPO_ROOT / "src" / "ai_intervention_agent" / "templates" / "web_ui.html"
MAIN_CSS = REPO_ROOT / "src" / "ai_intervention_agent" / "static" / "css" / "main.css"
EN_LOCALE = (
    REPO_ROOT / "src" / "ai_intervention_agent" / "static" / "locales" / "en.json"
)
ZH_LOCALE = (
    REPO_ROOT / "src" / "ai_intervention_agent" / "static" / "locales" / "zh-CN.json"
)
PSEUDO_LOCALE = (
    REPO_ROOT
    / "src"
    / "ai_intervention_agent"
    / "static"
    / "locales"
    / "_pseudo"
    / "pseudo.json"
)


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def _strip_html_comments(src: str) -> str:
    return re.sub(r"<!--.*?-->", "", src, flags=re.DOTALL)


def _extract_version_link_anchor(html: str) -> str | None:
    """抓 ``<a ... class="version-link" ...>...</a>`` 的整个 element（multiline）。"""
    m = re.search(
        r'<a\b[^>]*class="[^"]*\bversion-link\b[^"]*"[^>]*>[\s\S]*?</a>',
        html,
    )
    return m.group(0) if m else None


class TestVersionInfoMergedLink(unittest.TestCase):
    """``.version-info`` 内部应只剩单一链接。"""

    def test_no_legacy_version_classes(self) -> None:
        html = _strip_html_comments(_read(WEB_UI_HTML))
        for legacy in (
            "version-text",
            "version-name",
            "version-number",
            "github-link",
        ):
            self.assertNotRegex(
                html,
                rf'class="[^"]*\b{re.escape(legacy)}\b[^"]*"',
                f".{legacy} class 应已下线（合并到 .version-link）",
            )

    def setUp(self) -> None:
        self.html = _strip_html_comments(_read(WEB_UI_HTML))
        self.anchor = _extract_version_link_anchor(self.html)
        self.assertIsNotNone(
            self.anchor,
            '未在模板中找到 ``<a class="version-link">`` —— feat-footer-link-web 必有',
        )

    def test_version_link_anchor_href_to_github_url(self) -> None:
        assert self.anchor is not None
        self.assertRegex(
            self.anchor,
            r'href="\{\{\s*github_url\s*\}\}"',
            "version-link anchor 必须 href 到 ``{{ github_url }}``",
        )

    def test_link_target_blank_with_noopener(self) -> None:
        assert self.anchor is not None
        self.assertIn('target="_blank"', self.anchor)
        self.assertIn('rel="noopener noreferrer"', self.anchor)

    def test_link_text_contains_full_product_and_version(self) -> None:
        """链接文字应是 ``AI Intervention Agent {{ version }}`` —— 把项目名与
        版本号都纳入可点击 anchor。"""
        assert self.anchor is not None
        # 注意：HTML 格式化器会把 ``</span\n>`` 这种「关标签 + 换行 + ``>``」
        # 形态生成（避免行尾尾随空格），所以 regex 用 ``</span\s*>`` 兼容。
        m = re.search(
            r'<span\s+class="version-link-text"[^>]*>\s*AI Intervention Agent\s+\{\{\s*version\s*\}\}\s*</span\s*>',
            self.anchor,
        )
        self.assertIsNotNone(
            m,
            "<span.version-link-text> 必须含 ``AI Intervention Agent {{ version }}``",
        )

    def test_github_icon_still_inside_link(self) -> None:
        """GitHub 图标作为视觉装饰仍保留在链接内（aria-hidden 让 SR 跳过）。"""
        assert self.anchor is not None
        self.assertIn(
            "github-icon",
            self.anchor,
            "github-icon SVG 必须嵌在 .version-link anchor 内",
        )


class TestCssMigration(unittest.TestCase):
    """CSS：旧 class 选择器全部清理；新 class 选择器都存在。"""

    def setUp(self) -> None:
        self.css = _read(MAIN_CSS)

    def test_no_legacy_selectors(self) -> None:
        for legacy in (
            r"\.version-text",
            r"\.version-name",
            r"\.version-number",
            r"\.github-link",
        ):
            self.assertNotRegex(
                self.css,
                rf"{legacy}(?:[\s,{{:]|$)",
                f"main.css 中不应再有 {legacy} 选择器（已合并到 .version-link）",
            )

    def test_new_version_link_selector_defined(self) -> None:
        self.assertRegex(
            self.css,
            r"\.version-link\s*\{",
            "main.css 必须定义 .version-link 选择器",
        )

    def test_new_version_link_text_selector_defined(self) -> None:
        self.assertRegex(
            self.css,
            r"\.version-link-text\s*\{",
            "main.css 必须定义 .version-link-text 选择器（文字字号 / weight）",
        )

    def test_light_theme_override_present(self) -> None:
        self.assertRegex(
            self.css,
            r'\[data-theme="light"\]\s*\.version-link\s*\{',
            'main.css 必须定义 [data-theme="light"] .version-link 主题覆盖',
        )


class TestLocalesUpdated(unittest.TestCase):
    """``page.versionLinkTitle`` 三 locale 必须就位，且旧 ``githubTitle`` 已退役。"""

    def _load_page(self, p: Path) -> dict[str, object]:
        with p.open(encoding="utf-8") as f:
            data = json.load(f)
        return data["page"]

    def test_en_has_version_link_title(self) -> None:
        page = self._load_page(EN_LOCALE)
        self.assertIn("versionLinkTitle", page)
        val = page["versionLinkTitle"]
        self.assertIsInstance(val, str)
        assert isinstance(val, str)
        self.assertIn("GitHub", val, "en versionLinkTitle 应提到 GitHub")

    def test_zh_has_version_link_title(self) -> None:
        page = self._load_page(ZH_LOCALE)
        self.assertIn("versionLinkTitle", page)
        val = page["versionLinkTitle"]
        self.assertIsInstance(val, str)
        assert isinstance(val, str)
        self.assertIn("GitHub", val, "zh versionLinkTitle 应提到 GitHub")

    def test_pseudo_has_version_link_title(self) -> None:
        page = self._load_page(PSEUDO_LOCALE)
        self.assertIn(
            "versionLinkTitle",
            page,
            "pseudo.json 必须含 versionLinkTitle（rerun gen_pseudo_locale.py）",
        )

    def test_legacy_github_title_removed(self) -> None:
        for path in (EN_LOCALE, ZH_LOCALE, PSEUDO_LOCALE):
            page = self._load_page(path)
            self.assertNotIn(
                "githubTitle",
                page,
                f"{path.name} 中 page.githubTitle 应退役（被 versionLinkTitle 取代）",
            )


if __name__ == "__main__":
    unittest.main()
