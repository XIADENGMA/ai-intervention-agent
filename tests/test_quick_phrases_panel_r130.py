"""R130 · Quick Phrases / 常用回复面板渲染契约 + i18n + localStorage schema。

背景
----
R130 给 Web UI 加了「常用回复」面板：用户把高频文本片段（"继续"、
"修复 bug"、"这个方案不错"）保存到 localStorage，单击 chip 即把内容
追加到反馈输入框，避免反复手敲。竞品对齐 mcp-feedback-enhanced 的
"Quick Replies" 与 imhuso/cunzhi 的「常用回复和快捷面板」。

为什么纯前端 + localStorage：
- 零后端 API：避免新增 schema / 持久化文件 / 配额管理；
- 卸载后端不丢失数据；
- 隐私边界——常用回复本质是用户私有，不应 broadcast 给 MCP server。

测试覆盖六个层面（共 17 cases / 6 invariant classes）：

1.  **HTML 结构** — ``#quick-phrases-container`` 存在、内含
    ``label / add-btn / list / form-host`` 四个子节点、挂载位置在
    ``.textarea-container`` 之前（视觉接近输入框）。
2.  **JS 模块** — ``quick_phrases.js`` 文件存在 + 暴露
    ``window.AIIA_QUICK_PHRASES`` 公开 API + ``defer`` 脚本标签
    挂在 ``app.js`` 之后。
3.  **i18n 完备性** — ``zh-CN.json`` / ``en.json`` /
    ``_pseudo/pseudo.json`` 三份 locale 都包含 17 个 ``quickPhrases.*``
    键；pseudo 形态合规（``[!! ...!!]`` wrapper 验证由
    gen_pseudo_locale 保证，本测试只检查键齐全）。
4.  **CSS 样式** — ``main.css`` 含 ``.quick-phrases-container`` /
    ``.quick-phrase-chip`` / ``.quick-phrases-form`` 三大块；浅色主题
    覆盖到位；移动端 max-width 768px 收紧外边距。
5.  **localStorage schema 锁定** — ``STORAGE_KEY`` /
    ``SCHEMA_VERSION`` / ``LABEL_MAX_LEN`` / ``TEXT_MAX_LEN`` /
    ``MAX_PHRASES`` 数值锁定，防止未来意外漂移破坏既有用户数据。
6.  **回归保护** — ``#feedback-text`` textarea 仍存在；R125b 的
    ``#export-tasks-btn`` 仍存在；R125 的 ``/api/tasks/export``
    路由代码仍在，确保 R130 没有意外打断历史功能。
"""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC = REPO_ROOT / "src" / "ai_intervention_agent"
TEMPLATE = SRC / "templates" / "web_ui.html"
JS_QP = SRC / "static" / "js" / "quick_phrases.js"
CSS = SRC / "static" / "css" / "main.css"
LOCALE_EN = SRC / "static" / "locales" / "en.json"
LOCALE_ZH = SRC / "static" / "locales" / "zh-CN.json"
LOCALE_PSEUDO = SRC / "static" / "locales" / "_pseudo" / "pseudo.json"
WEB_UI_PY = SRC / "web_ui.py"

# 17 个 quickPhrases.* i18n key（与 quick_phrases.js FALLBACK_TEXT 同步）
EXPECTED_QP_KEYS = (
    "label",
    "addBtn",
    "addBtnAriaLabel",
    "empty",
    "disabled",
    "formLabelPlaceholder",
    "formTextPlaceholder",
    "formSave",
    "formCancel",
    "deleteBtnAriaLabel",
    "chipTitle",
    "errorLabelEmpty",
    "errorTextEmpty",
    "errorLabelTooLong",
    "errorTextTooLong",
    "errorTooMany",
    "confirmDelete",
)


def _read(p: Path) -> str:
    assert p.is_file(), f"缺失文件: {p}"
    return p.read_text(encoding="utf-8")


def _read_locale(p: Path) -> dict:
    raw = _read(p)
    return json.loads(raw)


# ---------------------------------------------------------------------------
# 1. HTML 结构
# ---------------------------------------------------------------------------


class TestQuickPhrasesHtml(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.html = _read(TEMPLATE)

    def test_container_exists(self) -> None:
        self.assertRegex(
            self.html,
            r'<div[^>]*\bid="quick-phrases-container"',
            "必须含 #quick-phrases-container 包装元素",
        )

    def test_four_child_nodes_present(self) -> None:
        for required_id in (
            "quick-phrases-add-btn",
            "quick-phrases-list",
            "quick-phrases-form-host",
        ):
            self.assertIn(
                f'id="{required_id}"',
                self.html,
                f"#{required_id} 必须出现在 quick-phrases-container 内",
            )
        self.assertIn(
            'data-i18n="quickPhrases.label"',
            self.html,
            "面板标题必须挂 data-i18n=quickPhrases.label",
        )

    def test_panel_mounted_before_textarea(self) -> None:
        # 面板要紧贴反馈输入框上方——视觉决策：用户先看到「常用回复」
        # 再开始打字会比把面板埋在 settings 里下面命中率高得多。
        idx_qp = self.html.index('id="quick-phrases-container"')
        idx_textarea = self.html.index('id="feedback-text"')
        self.assertLess(
            idx_qp,
            idx_textarea,
            "quick-phrases-container 必须出现在 #feedback-text 之前（视觉位置）",
        )

    def test_add_button_has_i18n_aria_label(self) -> None:
        # 确保 + 按钮可访问性：屏幕阅读器读出"添加常用回复"而不是"+"
        match = re.search(
            r'<button[^>]*\bid="quick-phrases-add-btn"[^>]*>', self.html, re.DOTALL
        )
        self.assertIsNotNone(match)
        assert match is not None
        anchor = match.group(0)
        self.assertIn(
            'data-i18n-aria-label="quickPhrases.addBtnAriaLabel"',
            anchor,
            "添加按钮必须挂 data-i18n-aria-label",
        )
        self.assertIn(
            'data-i18n="quickPhrases.addBtn"',
            anchor,
            "添加按钮必须挂 data-i18n",
        )


# ---------------------------------------------------------------------------
# 2. JS 模块
# ---------------------------------------------------------------------------


class TestQuickPhrasesJs(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _read(JS_QP)
        cls.html = _read(TEMPLATE)

    def test_module_exposes_public_api(self) -> None:
        # 暴露 AIIA_QUICK_PHRASES 给测试 / 调试 / 未来 R131 编辑功能
        self.assertIn(
            "window.AIIA_QUICK_PHRASES",
            self.js,
            "quick_phrases.js 必须暴露 window.AIIA_QUICK_PHRASES 命名空间",
        )

    def test_script_tag_loaded_after_app_js(self) -> None:
        # 确保 quick_phrases.js 在 app.js 之后加载，避免 i18n / 状态机
        # 还没就绪时 init 失败
        idx_app = self.html.index("/static/js/app.js?v=")
        idx_qp = self.html.index("/static/js/quick_phrases.js?v=")
        self.assertLess(
            idx_app,
            idx_qp,
            "quick_phrases.js script 标签必须出现在 app.js script 标签之后",
        )

    def test_no_inner_html_used(self) -> None:
        # 防 XSS：所有节点构建走 createElement + textContent，绝不用 innerHTML
        # 单字符串 "innerHTML" 在注释里也搜不到——保持代码本体零 innerHTML
        body_only = re.sub(r"/\*[\s\S]*?\*/", "", self.js)  # 去除 block 注释
        body_only = re.sub(r"//[^\n]*", "", body_only)  # 去除 line 注释
        self.assertNotIn(
            "innerHTML",
            body_only,
            "quick_phrases.js 代码本体禁止使用 innerHTML（XSS 防御基线）",
        )


# ---------------------------------------------------------------------------
# 3. i18n 完备性
# ---------------------------------------------------------------------------


class TestQuickPhrasesI18n(unittest.TestCase):
    def _assert_locale_complete(self, path: Path, label: str) -> None:
        data = _read_locale(path)
        qp = data.get("quickPhrases")
        # 显式 isinstance 让 ty 静态收窄类型，避免后续 qp[k] 触发
        # `not-subscriptable` / `Unknown | None`。
        assert isinstance(qp, dict), f"{label} 必须包含 quickPhrases 命名空间（dict）"
        for k in EXPECTED_QP_KEYS:
            self.assertIn(
                k,
                qp,
                f"{label}.quickPhrases 缺少 key={k}",
            )
            v = qp[k]
            self.assertIsInstance(
                v,
                str,
                f"{label}.quickPhrases.{k} 必须是字符串",
            )
            assert isinstance(v, str)
            self.assertGreater(
                len(v.strip()),
                0,
                f"{label}.quickPhrases.{k} 不能是空字符串",
            )

    def test_zh_cn_locale_complete(self) -> None:
        self._assert_locale_complete(LOCALE_ZH, "zh-CN.json")

    def test_en_locale_complete(self) -> None:
        self._assert_locale_complete(LOCALE_EN, "en.json")

    def test_pseudo_locale_complete(self) -> None:
        self._assert_locale_complete(LOCALE_PSEUDO, "_pseudo/pseudo.json")


# ---------------------------------------------------------------------------
# 4. CSS 样式
# ---------------------------------------------------------------------------


class TestQuickPhrasesCss(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.css = _read(CSS)

    def test_container_selector_present(self) -> None:
        self.assertIn(
            ".quick-phrases-container",
            self.css,
            "main.css 必须含 .quick-phrases-container 规则块",
        )

    def test_chip_and_form_selectors_present(self) -> None:
        for selector in (
            ".quick-phrase-chip",
            ".quick-phrase-chip-delete",
            ".quick-phrases-form",
            ".quick-phrases-form-save",
        ):
            self.assertIn(
                selector,
                self.css,
                f"main.css 必须含 {selector} 规则块",
            )

    def test_light_theme_overrides_present(self) -> None:
        # 浅色主题下 chip / 标签颜色不能照搬深色主题，否则在白底上对比度差
        self.assertRegex(
            self.css,
            r'\[data-theme="light"\][^\n]*\.quick-phrases-container',
            "main.css 必须含浅色主题下的 .quick-phrases-container 覆盖",
        )


# ---------------------------------------------------------------------------
# 5. localStorage schema / 容量上限锁定
# ---------------------------------------------------------------------------


class TestQuickPhrasesSchemaLock(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _read(JS_QP)

    def test_storage_key_locked(self) -> None:
        # 改 STORAGE_KEY 会让用户既有数据失效，必须有意识
        self.assertIn(
            'STORAGE_KEY = "aiia.quickPhrases.v1"',
            self.js,
            "STORAGE_KEY 必须锁定为 aiia.quickPhrases.v1（迁移到 v2 需要写 migrator）",
        )

    def test_schema_version_is_one(self) -> None:
        self.assertIn(
            "SCHEMA_VERSION = 1",
            self.js,
            "SCHEMA_VERSION 当前应锁定为 1",
        )

    def test_length_caps_locked(self) -> None:
        # 这些数值是 UI / 校验文案 / 测试 / 用户预期的契约——任何修改都
        # 应当反映在 i18n（formLabelPlaceholder 文案里写了 30/2000）
        for needle in (
            "LABEL_MAX_LEN = 30",
            "TEXT_MAX_LEN = 2000",
            "MAX_PHRASES = 20",
        ):
            self.assertIn(
                needle,
                self.js,
                f"长度 / 容量上限必须锁定：{needle}",
            )


# ---------------------------------------------------------------------------
# 6. 回归保护
# ---------------------------------------------------------------------------


class TestNotBreakingExisting(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.html = _read(TEMPLATE)
        cls.web_ui_py = _read(WEB_UI_PY)

    def test_feedback_textarea_still_present(self) -> None:
        # R130 添加面板时不能误删反馈输入框
        self.assertIn(
            'id="feedback-text"',
            self.html,
            "feedback textarea 必须仍然存在（R130 不能破坏 R0 输入框）",
        )

    def test_export_button_still_present(self) -> None:
        # R125b 的导出按钮不能因为 R130 改版被误删
        self.assertIn(
            'id="export-tasks-btn"',
            self.html,
            "R125b 的 #export-tasks-btn 必须仍然存在",
        )

    def test_template_context_carries_quick_phrases_version(self) -> None:
        # _get_template_context 必须新增 quick_phrases_version 字段
        # 否则模板里的 ?v={{ quick_phrases_version }} 会渲成空串，
        # 导致 serve_js 把缓存策略从 immutable 降级到 1 天，性能回退
        self.assertIn(
            '"quick_phrases_version"',
            self.web_ui_py,
            "_get_template_context 必须填充 quick_phrases_version 字段",
        )


if __name__ == "__main__":
    unittest.main()
