"""``feat-remove-download`` 回归契约：web 右上角下载按钮已移除。

背景
----
用户偏好："web 页面上右上角的下载按钮，这个功能我不喜欢，请完整去除。"

R125b 在 ``header-actions`` 区添加的 ``<a id="export-tasks-btn">`` 按钮被
按用户要求从前端移除。**但**后端 ``/api/tasks/export`` API 保留供 CI /
备份脚本独立调用（R125/R135 实现注释里明确写了这个用例）。

本测试锁住"前端移除，后端保留"的差异化契约，防止：

1. 未来某次 UI 改动重新加回该按钮（regression）；
2. 错把后端 API 当 UI feature 一并移除（API 还有外部用户）。
"""

from __future__ import annotations

import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
WEB_UI_HTML = REPO_ROOT / "src" / "ai_intervention_agent" / "templates" / "web_ui.html"
MAIN_CSS = REPO_ROOT / "src" / "ai_intervention_agent" / "static" / "css" / "main.css"
TASK_PY = REPO_ROOT / "src" / "ai_intervention_agent" / "web_ui_routes" / "task.py"
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


class TestFrontendButtonRemoved(unittest.TestCase):
    """``<a id="export-tasks-btn">`` 不应再出现在 web_ui.html 模板中。"""

    def test_button_id_not_in_html(self) -> None:
        html = _read(WEB_UI_HTML)
        self.assertNotIn(
            'id="export-tasks-btn"',
            html,
            "export-tasks-btn 按钮已按 feat-remove-download 移除，不应再出现在 HTML 中",
        )

    def test_export_btn_class_not_in_html(self) -> None:
        html = _read(WEB_UI_HTML)
        # 锁住"独立 export-btn class"，注意 ``quick-phrases-export-btn`` 是
        # 另一个独立 class（侧边栏 quick phrases 自有的导出按钮，不在
        # 本次移除范围）。用 negative lookbehind 排除任何带连字符前缀的同名后缀。
        self.assertNotRegex(
            html,
            r'class="[^"]*(?<![\w-])export-btn(?![\w-])[^"]*"',
            "HTML 中不应再有独立的 .export-btn class（feat-remove-download 已移除该按钮）",
        )

    def test_export_url_not_referenced_as_link_in_html(self) -> None:
        """禁止 href / src 直接指向 ``/api/tasks/export``。

        注释中提到该 URL（说明历史去向）允许；只禁止真正的 HTML 链接。
        """
        html = _read(WEB_UI_HTML)
        # 锁住 ``href="/api/tasks/export...`` 或 ``href='/api/tasks/export...`` 出现
        self.assertNotRegex(
            html,
            r"""href=["']/api/tasks/export""",
            "HTML 模板不应再 hard-link 到 /api/tasks/export（按钮已移除）；"
            "API 本身保留，但仅供 CI/备份脚本程序化调用",
        )


class TestCssExportBtnRulesRemoved(unittest.TestCase):
    """``.export-btn`` 选择器应从 main.css 中清理。"""

    def test_no_export_btn_selector(self) -> None:
        css = _read(MAIN_CSS)
        # ``.export-btn`` 后跟空格/逗号/{/换行/伪类
        self.assertNotRegex(
            css,
            r"\.export-btn(?:[\s,{:]|$)",
            "main.css 中不应再有 .export-btn 选择器（feat-remove-download 已清理）",
        )


class TestLocalesCleanedUp(unittest.TestCase):
    """三个 locale 文件都不应再有 ``page.exportTasksBtn`` / ``...AriaLabel`` key。"""

    def test_en_locale_no_export_keys(self) -> None:
        content = _read(EN_LOCALE)
        self.assertNotIn(
            '"exportTasksBtn"',
            content,
            "en.json 不应再有 exportTasksBtn key（按钮已移除）",
        )
        self.assertNotIn(
            '"exportTasksBtnAriaLabel"',
            content,
            "en.json 不应再有 exportTasksBtnAriaLabel key",
        )

    def test_zh_locale_no_export_keys(self) -> None:
        content = _read(ZH_LOCALE)
        self.assertNotIn('"exportTasksBtn"', content)
        self.assertNotIn('"exportTasksBtnAriaLabel"', content)

    def test_pseudo_locale_no_export_keys(self) -> None:
        # pseudo locale 是自动生成的。如果生成器还没跑，这里会 fail —— 提醒
        # 维护者 rerun ``scripts/gen_pseudo_locale.py``。
        content = _read(PSEUDO_LOCALE)
        self.assertNotIn(
            '"exportTasksBtn"',
            content,
            "pseudo.json 不应再有 exportTasksBtn key（删 en/zh 后请 rerun "
            "scripts/gen_pseudo_locale.py 同步）",
        )


class TestBackendApiPreserved(unittest.TestCase):
    """后端 ``/api/tasks/export`` API + ``export_tasks`` view function 必须保留。"""

    def test_api_route_still_registered(self) -> None:
        src = _read(TASK_PY)
        self.assertRegex(
            src,
            r'@self\.app\.route\(\s*"/api/tasks/export"',
            "后端 /api/tasks/export route 必须保留 —— CI / 备份脚本仍需用它"
            "（feat-remove-download 只去前端按钮）",
        )

    def test_view_function_still_defined(self) -> None:
        src = _read(TASK_PY)
        self.assertRegex(
            src,
            r"def\s+export_tasks\s*\(",
            "export_tasks view function 必须保留",
        )

    def test_route_format_param_still_supports_markdown(self) -> None:
        """R125 关键不变量：``?format=markdown`` 仍是合法选项。"""
        src = _read(TASK_PY)
        # 锁住 ``"markdown"`` 字面量出现在 fmt 校验段
        self.assertRegex(
            src,
            r"fmt\s+not\s+in\s+\(\s*\"json\"\s*,\s*\"markdown\"\s*\)",
            "/api/tasks/export 必须仍支持 ?format=markdown（向后兼容 CI 脚本）",
        )


if __name__ == "__main__":
    unittest.main()
