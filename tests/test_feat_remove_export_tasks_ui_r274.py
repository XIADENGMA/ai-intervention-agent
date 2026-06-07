"""R274 / cycle-24 t24-1: 整体下架 Settings 页 Export task history UI。

用户偏好理由
------------

用户在 TODO 明确要求"web 页面上右上角的下载按钮，这个功能我不喜欢，请完整去除"。

虽然 "右上角" 与实际位置 (Settings 面板的 Export task history row) 不完全
对应，但项目内仅剩 `#export-tasks-link` 一个可见"下载按钮" — `R125b` 引入
的右上角任务列表下载按钮早已在 cycle-22 下架。因此用户描述指向的唯一前端
入口就是这个 Settings row。

R274 范围
---------

**删除**:
- `templates/web_ui.html` `.export-tasks-row` (label + select + anchor)
- `static/js/settings-manager.js` `_wireExportTasksControls` 函数 + 调用
- `static/css/main.css` `.export-tasks-*` 4 条规则
- 4 个 locale 文件的 `settings.exportTasks` object (5 keys × 4 locales = 20 keys)

**保留** (`POST /api/tasks/export` 后端 API 保持可用):
- CI / 备份脚本依然可以通过 curl / HTTP client 调用
- R125 / R135 后端集成测试不受影响
- 仅前端 UI 入口移除

R274 invariant
--------------

1. `web_ui.html` 中**不能**再出现 `.export-tasks-row`/`#export-tasks-format`
   /`#export-tasks-link`/`settings.exportTasks.*` 引用
2. `settings-manager.js` 中**不能**再有 `_wireExportTasksControls` 函数
   或调用
3. `main.css` 中**不能**再有 `.export-tasks-*` 选择器
4. 4 个 locale 文件**不能**再有 `settings.exportTasks` 顶级 key
5. (保留 sanity) `web_ui_routes/tasks.py` 中 `/api/tasks/export` 路由
   依然存在（防止误删后端 API）

Why locked
----------

防止未来重新引入下载入口时打回原状 (forgotten user preference)。如果
真的需要重新引入，必须**显式编辑此测试** + 在 CHANGELOG 中标注用户
重新启用了该 UI，避免静默回归。
"""

from __future__ import annotations

import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
HTML = REPO_ROOT / "src" / "ai_intervention_agent" / "templates" / "web_ui.html"
SETTINGS_JS = (
    REPO_ROOT
    / "src"
    / "ai_intervention_agent"
    / "static"
    / "js"
    / "settings-manager.js"
)
MAIN_CSS = REPO_ROOT / "src" / "ai_intervention_agent" / "static" / "css" / "main.css"
LOCALES_DIR = REPO_ROOT / "src" / "ai_intervention_agent" / "static" / "locales"
TASKS_ROUTE = REPO_ROOT / "src" / "ai_intervention_agent" / "web_ui_routes" / "task.py"


class TestHtmlExportTasksUiRemoved(unittest.TestCase):
    src = HTML.read_text(encoding="utf-8")

    def test_no_export_tasks_row_class(self) -> None:
        self.assertNotIn(
            'class="setting-item export-tasks-row"',
            self.src,
            "R274: ``.export-tasks-row`` div 必须从 web_ui.html 移除",
        )

    def test_no_export_tasks_format_id(self) -> None:
        self.assertNotIn(
            'id="export-tasks-format"',
            self.src,
            "R274: ``#export-tasks-format`` select 必须从 web_ui.html 移除",
        )

    def test_no_export_tasks_link_id(self) -> None:
        self.assertNotIn(
            'id="export-tasks-link"',
            self.src,
            "R274: ``#export-tasks-link`` anchor 必须从 web_ui.html 移除",
        )

    def test_no_export_tasks_btn_class_usage(self) -> None:
        """匹配实际 HTML attribute 写法，不包含 R125b 旧注释里的 ID 文本。"""
        self.assertNotIn(
            'class="btn btn-secondary export-tasks-btn"',
            self.src,
            "R274: ``.export-tasks-btn`` class 用法必须从 web_ui.html 移除",
        )

    def test_no_export_tasks_i18n_keys_referenced(self) -> None:
        for sub in ("label", "formatLabel", "json", "markdown", "download"):
            key = f"settings.exportTasks.{sub}"
            self.assertNotIn(
                key,
                self.src,
                f'R274: ``data-i18n="{key}"`` 必须从 web_ui.html 移除',
            )

    def test_removal_annotation_present(self) -> None:
        """R274 注释 anchor (要求维护者主动找到这里再考虑重启)"""
        self.assertIn(
            "R274",
            self.src,
            "R274: web_ui.html 必须保留 R274 注释，标注 export-tasks UI"
            "下架原因 + invariant 测试入口",
        )


class TestSettingsManagerJsWireFunctionRemoved(unittest.TestCase):
    src = SETTINGS_JS.read_text(encoding="utf-8")

    def test_no_wire_function_definition(self) -> None:
        self.assertNotRegex(
            self.src,
            r"_wireExportTasksControls\s*\(\s*\)\s*\{",
            "R274: ``_wireExportTasksControls()`` 函数定义必须从 settings-"
            "manager.js 移除",
        )

    def test_no_wire_function_invocation(self) -> None:
        self.assertNotIn(
            "this._wireExportTasksControls()",
            self.src,
            "R274: ``this._wireExportTasksControls()`` 调用必须从 settings-"
            "manager.js 移除",
        )

    def test_no_export_tasks_dom_query(self) -> None:
        for dom_id in ("export-tasks-format", "export-tasks-link"):
            self.assertNotIn(
                dom_id,
                self.src,
                f"R274: ``{dom_id}`` DOM 查询必须从 settings-manager.js 移除",
            )

    def test_removal_annotation_present(self) -> None:
        self.assertIn(
            "R274",
            self.src,
            "R274: settings-manager.js 必须保留 R274 注释，标注 _wire"
            "ExportTasksControls 下架原因 + invariant 测试入口",
        )


class TestMainCssExportTasksRulesRemoved(unittest.TestCase):
    src = MAIN_CSS.read_text(encoding="utf-8")

    def test_no_export_tasks_row_selector(self) -> None:
        self.assertNotRegex(
            self.src,
            r"^\.export-tasks-row\s*\{",
            "R274: ``.export-tasks-row { ... }`` CSS 规则必须从 main.css 移除",
        )

    def test_no_export_tasks_label_selector(self) -> None:
        self.assertNotRegex(
            self.src,
            r"^\.export-tasks-label\s*\{",
            "R274: ``.export-tasks-label { ... }`` CSS 规则必须从 main.css 移除",
        )

    def test_no_export_tasks_format_selector(self) -> None:
        self.assertNotRegex(
            self.src,
            r"^\.export-tasks-format\s*\{",
            "R274: ``.export-tasks-format { ... }`` CSS 规则必须从 main.css 移除",
        )

    def test_no_export_tasks_btn_selector(self) -> None:
        self.assertNotRegex(
            self.src,
            r"^\.export-tasks-btn\s*\{",
            "R274: ``.export-tasks-btn { ... }`` CSS 规则必须从 main.css 移除",
        )


class TestLocalesExportTasksKeysRemoved(unittest.TestCase):
    def test_en_locale_no_export_tasks_key(self) -> None:
        text = (LOCALES_DIR / "en.json").read_text(encoding="utf-8")
        self.assertNotIn(
            '"exportTasks"',
            text,
            "R274: en.json settings.exportTasks 顶级 object 必须移除",
        )

    def test_zh_cn_locale_no_export_tasks_key(self) -> None:
        text = (LOCALES_DIR / "zh-CN.json").read_text(encoding="utf-8")
        self.assertNotIn(
            '"exportTasks"',
            text,
            "R274: zh-CN.json settings.exportTasks 顶级 object 必须移除",
        )

    def test_zh_tw_locale_no_export_tasks_key(self) -> None:
        text = (LOCALES_DIR / "zh-TW.json").read_text(encoding="utf-8")
        self.assertNotIn(
            '"exportTasks"',
            text,
            "R274: zh-TW.json settings.exportTasks 顶级 object 必须移除",
        )

    def test_pseudo_locale_no_export_tasks_key(self) -> None:
        text = (LOCALES_DIR / "_pseudo" / "pseudo.json").read_text(encoding="utf-8")
        self.assertNotIn(
            '"exportTasks"',
            text,
            "R274: pseudo.json settings.exportTasks 顶级 object 必须移除",
        )


class TestBackendApiRoutePreserved(unittest.TestCase):
    """R274 范围 sanity check — 仅删前端 UI，保留后端 ``/api/tasks/export``
    路由（CI / 备份脚本依然依赖）。"""

    def test_tasks_route_module_exists(self) -> None:
        self.assertTrue(
            TASKS_ROUTE.exists(),
            "R274: web_ui_routes/task.py 必须存在 (后端 API 保留)",
        )

    def test_export_endpoint_still_registered(self) -> None:
        text = TASKS_ROUTE.read_text(encoding="utf-8")
        self.assertRegex(
            text,
            r"/api/tasks/export|export_tasks",
            "R274: ``/api/tasks/export`` 后端路由必须保留 (R125/R135 用例"
            "依赖；用户偏好只移除前端入口)",
        )


if __name__ == "__main__":
    unittest.main()
