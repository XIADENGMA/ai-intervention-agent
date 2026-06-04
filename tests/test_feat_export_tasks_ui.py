"""mining-cycle-2 §3.1 cycle-3 polish — Settings 页 Export task history
UI 回归测试。

后端 ``/api/tasks/export`` 早已 ship (R125 / R125c / R135)；本测试只
确保 settings 面板新增的 UI 入口正确接入。
"""

from __future__ import annotations

import json
import re
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
EN_JSON = REPO_ROOT / "src" / "ai_intervention_agent" / "static" / "locales" / "en.json"
ZH_CN_JSON = (
    REPO_ROOT / "src" / "ai_intervention_agent" / "static" / "locales" / "zh-CN.json"
)
MAIN_CSS = REPO_ROOT / "src" / "ai_intervention_agent" / "static" / "css" / "main.css"


class TestHtmlMarkup(unittest.TestCase):
    src = HTML.read_text(encoding="utf-8")

    def test_export_row_present(self) -> None:
        self.assertIn(
            "export-tasks-row",
            self.src,
            "settings 页必须包含 ``.export-tasks-row``",
        )

    def test_format_select_present(self) -> None:
        self.assertIn('id="export-tasks-format"', self.src)
        self.assertIn('<option value="json"', self.src)
        self.assertIn('<option\n                      value="markdown"', self.src)

    def test_download_anchor_present(self) -> None:
        self.assertIn('id="export-tasks-link"', self.src)
        # 必须 download attribute 触发浏览器原生下载
        # （不能用 JS-driven fetch + Blob，因为大 JSON 会内存爆）
        self.assertRegex(
            self.src,
            r'id="export-tasks-link"[\s\S]*?download',
            "anchor 必须有 ``download`` 属性",
        )

    def test_anchor_default_href_points_to_backend(self) -> None:
        self.assertIn('href="/api/tasks/export?format=json"', self.src)

    def test_anchor_has_rel_noopener(self) -> None:
        self.assertRegex(
            self.src,
            r'id="export-tasks-link"[\s\S]*?rel="noopener"',
            "anchor 必须 rel=noopener 避免 download 触发 window opener 泄露",
        )

    def test_i18n_attributes_present(self) -> None:
        for key in (
            "settings.exportTasks.label",
            "settings.exportTasks.json",
            "settings.exportTasks.markdown",
            "settings.exportTasks.download",
            "settings.exportTasks.formatLabel",
        ):
            self.assertIn(
                f'"{key}"', self.src, f"必须有 data-i18n / data-i18n-aria-label = {key}"
            )


class TestJsWiring(unittest.TestCase):
    src = SETTINGS_JS.read_text(encoding="utf-8")

    def test_wire_function_defined(self) -> None:
        self.assertRegex(
            self.src,
            r"_wireExportTasksControls\(\)\s*\{",
            "settings-manager 必须有 _wireExportTasksControls()",
        )

    def test_wire_function_called(self) -> None:
        self.assertIn(
            "this._wireExportTasksControls()",
            self.src,
            "constructor / init 必须调 _wireExportTasksControls",
        )

    def test_wire_uses_change_event(self) -> None:
        m = re.search(r"_wireExportTasksControls\(\)\s*\{([\s\S]*?)\n  \}", self.src)
        self.assertIsNotNone(m)
        assert m is not None
        body = m.group(1)
        self.assertIn(
            'addEventListener("change"',
            body,
            "必须监听 select 的 change 事件来同步 href",
        )

    def test_wire_only_allows_known_formats(self) -> None:
        """invariant：URL ?format= 值必须从白名单选取，绝不接受任意 select.value。"""
        m = re.search(r"_wireExportTasksControls\(\)\s*\{([\s\S]*?)\n  \}", self.src)
        assert m is not None
        body = m.group(1)
        # 白名单逻辑：``fmt === "markdown" ? "markdown" : "json"`` 等价表达
        # 接受 ternary / if-else 任一写法，但必须有"非 markdown 就回退 json"
        # 的兜底，否则可能 setAttribute("href", "...?format=<XSS>")。
        self.assertRegex(
            body,
            r'(===\s*"markdown"|=="markdown"|"markdown"\s*\?)',
            "必须有 ``markdown`` 白名单分支",
        )

    def test_wire_uses_encode_uri_component(self) -> None:
        """defense in depth：即使 format 白名单走通，``encodeURIComponent``
        多一层兜底，防止未来引入新 format 时遗漏 escape。
        """
        m = re.search(r"_wireExportTasksControls\(\)\s*\{([\s\S]*?)\n  \}", self.src)
        assert m is not None
        self.assertIn("encodeURIComponent(", m.group(1))


class TestI18nKeys(unittest.TestCase):
    def _section(self, path: Path) -> dict:
        data = json.loads(path.read_text(encoding="utf-8"))
        return ((data.get("settings") or {}).get("exportTasks")) or {}

    def test_en_has_all_keys(self) -> None:
        sec = self._section(EN_JSON)
        for key in ("label", "formatLabel", "json", "markdown", "download"):
            self.assertIn(key, sec, f"en.json::settings.exportTasks.{key} 必须存在")

    def test_zh_cn_has_all_keys(self) -> None:
        sec = self._section(ZH_CN_JSON)
        for key in ("label", "formatLabel", "json", "markdown", "download"):
            self.assertIn(key, sec, f"zh-CN.json::settings.exportTasks.{key} 必须存在")

    def test_zh_cn_distinct_from_en(self) -> None:
        """label / download 必须翻译，不是英文原样。"""
        en = self._section(EN_JSON)
        zh = self._section(ZH_CN_JSON)
        for k in ("label", "download"):
            self.assertNotEqual(
                en.get(k),
                zh.get(k),
                f"zh-CN settings.exportTasks.{k} 不能与 en 相同（说明没翻译）",
            )


class TestCssRow(unittest.TestCase):
    src = MAIN_CSS.read_text(encoding="utf-8")

    def test_export_row_classes_defined(self) -> None:
        for cls in (
            ".export-tasks-row",
            ".export-tasks-label",
            ".export-tasks-format",
            ".export-tasks-btn",
        ):
            self.assertIn(cls, self.src, f"main.css 必须有 {cls}")


if __name__ == "__main__":
    unittest.main()
