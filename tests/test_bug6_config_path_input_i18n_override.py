"""BUG6 回归契约：Web 设置页"当前配置文件路径"输入框显示为空。

背景
----
用户反馈："Web 设置页 ``当前配置文件路径`` 显示为空但点击按钮可打开"。
按钮能打开 → 后端配置文件路径解析没问题；输入框为空（实际是停在
首屏的 ``Loading…`` / ``加载中…``）→ 前端 i18n 与数据写入之间发生
race condition。

Root cause
----------
``<input id="config-file-path" value="Loading…" data-i18n-value="page.loading">``
的初始 HTML 设计：首屏文案随当前语言翻译。但 ``static/js/i18n.js`` 的
init 链路会触发 **两次** ``translateDOM()``：

  1. await loadLocale(currentLang) 后第一次 → 把 input.value 设为
     当前语言的 ``page.loading`` 翻译值。
  2. ``ensureDefaultLocale()``（fire-and-forget）完成后第二次 →
     再次扫描所有 ``data-i18n-value``，**覆盖 input.value**。

只要 ``fetchFeedbackPromptsFresh`` 在 (1) 与 (2) 之间完成（典型 LAN
场景下 5-50ms 完全可能），用户看到的就是：

  Loading… → /actual/config/path → Loading…（被 i18n 覆盖回去）

修复
----
在向 ``config-file-path`` 写入真实路径的两处（``multi_task.js`` 的
``fetchFeedbackPromptsFresh`` 与 ``settings-manager.js`` 的
``openConfigFileInIde``）写入后立即 ``removeAttribute('data-i18n-value')``，
切断后续 retranslate 覆盖链。

本测试用静态扫描锁住这个不变量。
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
MULTI_TASK_JS = (
    REPO_ROOT / "src" / "ai_intervention_agent" / "static" / "js" / "multi_task.js"
)
SETTINGS_MANAGER_JS = (
    REPO_ROOT
    / "src"
    / "ai_intervention_agent"
    / "static"
    / "js"
    / "settings-manager.js"
)
WEB_UI_HTML = REPO_ROOT / "src" / "ai_intervention_agent" / "templates" / "web_ui.html"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def _strip_js_comments(source: str) -> str:
    """剥除 JS 单行/块注释，避免误命中文档字面量。"""
    out: list[str] = []
    i = 0
    n = len(source)
    in_string: str | None = None
    in_line = False
    in_block = False
    while i < n:
        ch = source[i]
        nxt = source[i + 1] if i + 1 < n else ""
        if in_line:
            if ch == "\n":
                in_line = False
                out.append(ch)
        elif in_block:
            if ch == "*" and nxt == "/":
                in_block = False
                i += 1
        elif in_string is not None:
            out.append(ch)
            if ch == "\\":
                if i + 1 < n:
                    out.append(source[i + 1])
                    i += 1
            elif ch == in_string:
                in_string = None
        else:
            if ch == "/" and nxt == "/":
                in_line = True
                i += 1
            elif ch == "/" and nxt == "*":
                in_block = True
                i += 1
            elif ch in ('"', "'", "`"):
                in_string = ch
                out.append(ch)
            else:
                out.append(ch)
        i += 1
    return "".join(out)


class TestHtmlInitialAttribute(unittest.TestCase):
    """初始 HTML 仍保留 ``data-i18n-value="page.loading"`` —— 首屏占位文案需要它翻译。"""

    def test_initial_attribute_present(self) -> None:
        html = _read(WEB_UI_HTML)
        self.assertRegex(
            html,
            r'id="config-file-path"[^>]*data-i18n-value="page\.loading"',
            "config-file-path input 必须保留 data-i18n-value='page.loading' 作为首屏占位翻译；"
            "BUG6 修复是在 JS 写入真实路径后才移除该属性，不应改 HTML",
        )


class TestMultiTaskRemovesI18nValueAfterWrite(unittest.TestCase):
    """``fetchFeedbackPromptsFresh`` 写入路径后必须立即移除 ``data-i18n-value``。"""

    def setUp(self) -> None:
        self.source = _read(MULTI_TASK_JS)
        self.clean = _strip_js_comments(self.source)

    def _extract_fn_body(self, fn_signature: str) -> str:
        idx = self.clean.find(fn_signature)
        self.assertGreaterEqual(idx, 0, f"找不到函数: {fn_signature}")
        open_brace = self.clean.find("{", idx)
        depth = 1
        i = open_brace + 1
        in_string: str | None = None
        while i < len(self.clean) and depth > 0:
            ch = self.clean[i]
            if in_string is not None:
                if ch == "\\":
                    i += 1
                elif ch == in_string:
                    in_string = None
            else:
                if ch in ('"', "'", "`"):
                    in_string = ch
                elif ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0:
                        return self.clean[open_brace + 1 : i]
            i += 1
        self.fail(f"{fn_signature} 大括号未平衡")
        return ""

    def test_write_then_remove_pattern_present(self) -> None:
        body = self._extract_fn_body("async function fetchFeedbackPromptsFresh()")
        # 必须出现：el.value = data.meta.config_file 后紧跟 removeAttribute
        write_match = re.search(
            r"el\.value\s*=\s*data\.meta\.config_file\s*;?\s*"
            r"el\.removeAttribute\(\s*['\"]data-i18n-value['\"]\s*\)",
            body,
        )
        self.assertIsNotNone(
            write_match,
            "fetchFeedbackPromptsFresh 内必须出现 el.value=data.meta.config_file 紧跟"
            "el.removeAttribute('data-i18n-value')；否则 i18n retranslate 会覆盖真实路径",
        )


class TestSettingsManagerRemovesI18nValueAfterWrite(unittest.TestCase):
    """``openConfigFileInIde`` 回填路径后必须立即移除 ``data-i18n-value``。"""

    def setUp(self) -> None:
        self.source = _read(SETTINGS_MANAGER_JS)
        self.clean = _strip_js_comments(self.source)

    def test_write_then_remove_pattern_present(self) -> None:
        # 找到 pathInput.value = data.path 紧跟 removeAttribute
        match = re.search(
            r"pathInput\.value\s*=\s*data\.path\s*;?\s*"
            r"pathInput\.removeAttribute\(\s*['\"]data-i18n-value['\"]\s*\)",
            self.clean,
        )
        self.assertIsNotNone(
            match,
            "openConfigFileInIde 回填 path 后必须立即调用 "
            "pathInput.removeAttribute('data-i18n-value')，"
            "否则切换语言时 i18n retranslate 会覆盖真实路径",
        )


class TestBug6DocumentationAnchor(unittest.TestCase):
    """注释中必须有 BUG6 锚点便于追溯。"""

    def test_multi_task_documents_bug6(self) -> None:
        self.assertIn(
            "BUG6",
            _read(MULTI_TASK_JS),
            "multi_task.js 应在 fetchFeedbackPromptsFresh 附近注释中标注 'BUG6' 锚点",
        )

    def test_settings_manager_documents_bug6(self) -> None:
        self.assertIn(
            "BUG6",
            _read(SETTINGS_MANAGER_JS),
            "settings-manager.js 应在 openConfigFileInIde 附近注释中标注 'BUG6' 锚点",
        )


if __name__ == "__main__":
    unittest.main()
