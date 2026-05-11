"""R125b · Web UI 任务导出按钮 (header-actions) 渲染契约 + i18n 完备性。

背景
----
R125 给后端落地了 ``GET /api/tasks/export?format={json,markdown}``，本身
对 curl / 浏览器直接访问已可用，但缺少前端入口意味着普通用户看不到这
个能力。R125b 在 ``header-actions`` 区放一个 ``<a download>`` 按钮：默
认走 Markdown（人类可读会话日志），让用户单击即下载；想要 JSON 的高级
用户仍可手敲 URL。

为什么不开"导出 JSON"按钮：

- 视觉负担——header-actions 已经有 theme-toggle + settings 两个图标按
  钮，再加一个就视觉拥挤；
- 实际用例——JSON 主要给程序 / AI agent 用，他们不依赖按钮；
- 一致性——把 Markdown 当"用户首选"避免新增 UI 词汇就能让用户理解
  ("导出"="保存这次会话")。

本测试覆盖五个层面：

1.  **按钮 HTML 契约** — ``<a id="export-tasks-btn">`` 存在，
    href 指向 ``?format=markdown`` ，``download`` 属性，role + aria-
    label，class=``export-btn``。
2.  **i18n 完备性** — ``page.exportTasksBtn`` /
    ``page.exportTasksBtnAriaLabel`` 在 ``en.json`` / ``zh-CN.json`` /
    ``_pseudo/pseudo.json`` 都存在；pseudo 形态合规
    （``[!! ...!!]`` wrapper）。
3.  **CSS 样式对齐** — ``.export-btn`` 在 ``.settings-btn`` 同级
    selector 中出现（共享尺寸 / 颜色 / hover），避免视觉漂移。
4.  **link 与 button 视觉去债务** —
    ``.export-btn:visited`` 不会用浏览器默认的紫色 / 蓝色链接颜色。
5.  **不打断既有按钮** — ``.settings-btn`` / ``.theme-toggle-btn``
    定义未被破坏。
"""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = REPO_ROOT / "src" / "ai_intervention_agent" / "templates" / "web_ui.html"
LOCALE_EN = (
    REPO_ROOT / "src" / "ai_intervention_agent" / "static" / "locales" / "en.json"
)
LOCALE_ZH = (
    REPO_ROOT / "src" / "ai_intervention_agent" / "static" / "locales" / "zh-CN.json"
)
LOCALE_PSEUDO = (
    REPO_ROOT
    / "src"
    / "ai_intervention_agent"
    / "static"
    / "locales"
    / "_pseudo"
    / "pseudo.json"
)
CSS = REPO_ROOT / "src" / "ai_intervention_agent" / "static" / "css" / "main.css"


def _read(p: Path) -> str:
    assert p.is_file(), f"缺失文件: {p}"
    return p.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# 1. HTML 按钮契约
# ---------------------------------------------------------------------------


class TestExportButtonHtml(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.html = _read(TEMPLATE)

    def test_anchor_with_correct_id_present(self) -> None:
        self.assertRegex(
            self.html,
            r"<a[^>]*\bid=\"export-tasks-btn\"",
            'header-actions 必须含 <a id="export-tasks-btn"> 元素',
        )

    def test_href_targets_markdown_export(self) -> None:
        # href 必须指向 markdown export 路径（默认人类可读优先）
        self.assertRegex(
            self.html,
            r"href=\"/api/tasks/export\?format=markdown\"",
            "导出按钮的 href 必须指向 /api/tasks/export?format=markdown",
        )

    def test_has_download_attribute(self) -> None:
        # download 属性让浏览器优先下载而非导航
        match = re.search(
            r"<a[^>]*\bid=\"export-tasks-btn\"[^>]*>", self.html, re.DOTALL
        )
        self.assertIsNotNone(match)
        assert match is not None
        self.assertIn(
            "download",
            match.group(0),
            "导出按钮必须含 download 属性（即使后端 Content-Disposition 已强制下载，"
            "前端 download 提示让 a11y 工具能正确朗读 download link 语义）",
        )

    def test_class_is_export_btn(self) -> None:
        match = re.search(
            r"<a[^>]*\bid=\"export-tasks-btn\"[^>]*\bclass=\"([^\"]+)\"",
            self.html,
            re.DOTALL,
        )
        # class 可能在 id 之前；做个鲁棒搜索
        if match is None:
            match = re.search(
                r"<a[^>]*\bclass=\"([^\"]+)\"[^>]*\bid=\"export-tasks-btn\"",
                self.html,
                re.DOTALL,
            )
        self.assertIsNotNone(match, "找不到 export-tasks-btn 的 class 属性")
        assert match is not None
        self.assertIn(
            "export-btn",
            match.group(1).split(),
            f"class 必须含 export-btn（实际：{match.group(1)!r}）",
        )

    def test_i18n_attributes_wired(self) -> None:
        anchor_match = re.search(
            r"<a[^>]*\bid=\"export-tasks-btn\"[^>]*>",
            self.html,
            re.DOTALL,
        )
        self.assertIsNotNone(anchor_match)
        assert anchor_match is not None
        anchor = anchor_match.group(0)
        self.assertIn(
            'data-i18n-title="page.exportTasksBtn"',
            anchor,
            "data-i18n-title 必须挂上 page.exportTasksBtn 否则中英切换不生效",
        )
        self.assertIn(
            'data-i18n-aria-label="page.exportTasksBtnAriaLabel"',
            anchor,
            "data-i18n-aria-label 必须挂上 page.exportTasksBtnAriaLabel 用于辅助技术朗读",
        )

    def test_a11y_role_button(self) -> None:
        anchor_match = re.search(
            r"<a[^>]*\bid=\"export-tasks-btn\"[^>]*>",
            self.html,
            re.DOTALL,
        )
        self.assertIsNotNone(anchor_match)
        assert anchor_match is not None
        self.assertIn(
            'role="button"',
            anchor_match.group(0),
            '<a download> 视觉是按钮，必须给 role="button" 让屏幕阅读器朗读对应语义',
        )


# ---------------------------------------------------------------------------
# 2. i18n 完备性
# ---------------------------------------------------------------------------


class TestI18nKeysPresent(unittest.TestCase):
    """三个 locale 都必须含 exportTasksBtn / exportTasksBtnAriaLabel。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.en = json.loads(_read(LOCALE_EN))
        cls.zh = json.loads(_read(LOCALE_ZH))
        cls.pseudo = json.loads(_read(LOCALE_PSEUDO))

    def test_en_has_keys(self) -> None:
        page = self.en.get("page", {})
        self.assertIn("exportTasksBtn", page)
        self.assertIn("exportTasksBtnAriaLabel", page)
        # 必须是非空字符串
        self.assertTrue(isinstance(page["exportTasksBtn"], str))
        self.assertGreater(len(page["exportTasksBtn"]), 0)

    def test_zh_has_keys(self) -> None:
        page = self.zh.get("page", {})
        self.assertIn("exportTasksBtn", page)
        self.assertIn("exportTasksBtnAriaLabel", page)
        # 中文文案应含中文字符
        self.assertRegex(
            page["exportTasksBtn"],
            r"[\u4e00-\u9fff]",
            "zh-CN 的 exportTasksBtn 必须含中文字符",
        )

    def test_pseudo_has_keys(self) -> None:
        page = self.pseudo.get("page", {})
        self.assertIn("exportTasksBtn", page)
        self.assertIn("exportTasksBtnAriaLabel", page)

    def test_pseudo_uses_correct_wrapper(self) -> None:
        """pseudo locale 必须用 ``[!! ... !!]`` 包裹（与现有 key 一致）。"""
        page = self.pseudo.get("page", {})
        for key in ("exportTasksBtn", "exportTasksBtnAriaLabel"):
            value = page[key]
            self.assertTrue(
                value.startswith("[!!"),
                f"pseudo locale ``page.{key}`` 必须以 ``[!!`` 开头（与现有 key 一致）",
            )
            self.assertTrue(
                value.endswith("!!]"),
                f"pseudo locale ``page.{key}`` 必须以 ``!!]`` 结尾",
            )


# ---------------------------------------------------------------------------
# 3. CSS 样式对齐
# ---------------------------------------------------------------------------


class TestCssStyleAlignment(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.css = _read(CSS)

    def test_export_btn_shares_settings_btn_baseline(self) -> None:
        """``.export-btn`` 必须与 ``.settings-btn`` 出现在同一个 selector group。

        这把"导出按钮的尺寸 / 颜色 / hover" 与设置按钮 lock 在一起，
        避免未来视觉漂移。
        """
        # 主声明块：`.settings-btn,\n.export-btn { ... }`
        match = re.search(
            r"\.settings-btn[\s,]+\.export-btn\s*\{",
            self.css,
        )
        self.assertIsNotNone(
            match,
            "main.css 必须在某处出现 ``.settings-btn, .export-btn {`` 同级 selector，"
            "保证两个按钮共享尺寸 / 颜色 / hover 基线",
        )

    def test_export_btn_visited_resets_text_decoration(self) -> None:
        """``.export-btn:visited`` 必须复位 ``text-decoration``（``<a>`` 默认有下划线）。"""
        # 至少出现一处 ``.export-btn:visited`` 在含 ``text-decoration: none`` 的 block 中
        # 用宽松正则
        self.assertRegex(
            self.css,
            r"\.export-btn[\s,]*[^{}]*:visited[\s\S]{0,400}?text-decoration:\s*none",
            "``.export-btn:visited`` 必须把浏览器默认 underline / visited 颜色复位掉",
        )

    def test_export_btn_in_light_theme_block(self) -> None:
        """浅色主题 selector 必须把 ``.export-btn`` 也包含进来。

        R169 / chore ``73d9980`` 后 main.css 全部 attribute-selector 收敛
        到 double-quote，所以这里同时接受 ``[data-theme='light']`` 与
        ``[data-theme="light"]`` 两种写法 —— 测试关心的是"浅色主题
        selector 包含 .export-btn"这个语义不变量，不是引号风格。
        """
        self.assertRegex(
            self.css,
            r"""\[data-theme=['"]light['"]\][\s\S]{0,80}\.export-btn""",
            "浅色主题的 ``.settings-btn / .theme-toggle-btn`` selector 必须把 "
            "``.export-btn`` 也加进去，否则浅色模式下背景对比度会出戏",
        )


# ---------------------------------------------------------------------------
# 4. 不破坏既有按钮
# ---------------------------------------------------------------------------


class TestExistingButtonsNotBroken(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.html = _read(TEMPLATE)
        cls.css = _read(CSS)

    def test_settings_btn_still_present(self) -> None:
        self.assertIn(
            'id="settings-btn"',
            self.html,
            "settings-btn 必须仍然存在（R125b 是新增按钮，不删除现有按钮）",
        )

    def test_theme_toggle_btn_still_present(self) -> None:
        self.assertIn(
            'id="theme-toggle-btn"',
            self.html,
            "theme-toggle-btn 必须仍然存在",
        )

    def test_settings_btn_block_still_in_css(self) -> None:
        # 确保 settings-btn 仍有自己的样式块
        self.assertIn(
            ".settings-btn",
            self.css,
            ".settings-btn CSS 选择器不应被删除",
        )


if __name__ == "__main__":
    unittest.main()
