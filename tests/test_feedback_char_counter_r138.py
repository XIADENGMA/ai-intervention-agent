"""R138 — Feedback textarea 字符计数器（character counter）测试。

R138 把 ``mcp-feedback-enhanced`` v2.4.x 的 character counter 体验吸
收到本项目主反馈输入框 (#feedback-text) ：长 prompt 用户在拼接多段
LLM 输出 / 复制粘贴长技术文档时常常超出心理预期，counter 让"输入
长度"这条不可见维度变显式，避免误超出后端 / Bark 通知的隐性 size
约束。

约束 / 不变式（覆盖 6 类）：

1.  **JS 模块文件存在 + 体积合理** — 模块文件存在；约 100-180 行（实
    际实现 ≈ 145 行），防误删 / 意外膨胀。
2.  **常量值锁定** — TARGET_ID / COUNTER_ID / WARN_THRESHOLD /
    DANGER_THRESHOLD / WARN_CLASS / DANGER_CLASS / I18N_KEY 字面值
    不漂移，确保模板 / CSS / JS 三方对齐。
3.  **API 函数签名** — _formatCount / _resolveLabel /
    _applyThresholdClass / updateCounter / init 全部可见；
    ``window.AIIA_FEEDBACK_CHAR_COUNTER`` 暴露完整 API。
4.  **graceful failure** — Intl.NumberFormat 抛异常 / i18n helper 缺
    失 / I18N runtime 抛异常时全部走 fallback 路径，输出仍可读。
5.  **HTML / context 集成** — ``<span id="feedback-char-counter">``
    在 textarea-container 内、带 ``aria-live="polite"`` + ``hidden``；
    ``<script>`` 标签带 ``defer`` + ``nonce={{ csp_nonce }}`` +
    ``?v={{ feedback_char_counter_version }}``；
    ``_get_template_context`` 用 ``_compute_file_version`` 计算
    ``feedback_char_counter_version``。
6.  **i18n 三 locale 全覆盖** — ``feedback.charCounter`` key 在
    ``zh-CN.json`` / ``en.json`` / ``_pseudo/pseudo.json`` 同时存在；
    含 ``{{count}}`` mustache 占位与 i18n runtime
    ``_interpolateMustache`` 兼容。
"""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JS_PATH = ROOT / "src/ai_intervention_agent/static/js/feedback_char_counter.js"
HTML_PATH = ROOT / "src/ai_intervention_agent/templates/web_ui.html"
CSS_PATH = ROOT / "src/ai_intervention_agent/static/css/main.css"
WEB_UI_PY = ROOT / "src/ai_intervention_agent/web_ui.py"
LOCALE_ZH = ROOT / "src/ai_intervention_agent/static/locales/zh-CN.json"
LOCALE_EN = ROOT / "src/ai_intervention_agent/static/locales/en.json"
LOCALE_PSEUDO = ROOT / "src/ai_intervention_agent/static/locales/_pseudo/pseudo.json"


def _read_js() -> str:
    return JS_PATH.read_text(encoding="utf-8")


def _read_html() -> str:
    return HTML_PATH.read_text(encoding="utf-8")


def _read_css() -> str:
    return CSS_PATH.read_text(encoding="utf-8")


def _read_locale(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


# ----------------------------------------------------------------------
# Class 1: JS 模块文件存在 + 体积合理
# ----------------------------------------------------------------------


class TestJsFileExistsAndSize(unittest.TestCase):
    def test_js_file_exists(self) -> None:
        self.assertTrue(
            JS_PATH.exists(),
            f"R138 JS 模块文件必须存在: {JS_PATH}",
        )

    def test_js_file_line_count_in_envelope(self) -> None:
        line_count = len(_read_js().splitlines())
        # 100-180 行：当前 ≈ 145 行，envelope 防误删 / 意外膨胀
        self.assertGreaterEqual(line_count, 100, "R138 JS 模块过短，疑似空壳")
        self.assertLessEqual(line_count, 180, "R138 JS 模块超出预期，疑似膨胀")


# ----------------------------------------------------------------------
# Class 2: 常量值锁定
# ----------------------------------------------------------------------


class TestConstantsLocked(unittest.TestCase):
    def setUp(self) -> None:
        self.js = _read_js()

    def test_target_id_constant(self) -> None:
        self.assertIn('TARGET_ID = "feedback-text"', self.js)

    def test_counter_id_constant(self) -> None:
        self.assertIn('COUNTER_ID = "feedback-char-counter"', self.js)

    def test_warn_threshold_constant(self) -> None:
        self.assertIn("WARN_THRESHOLD = 8000", self.js)

    def test_danger_threshold_constant(self) -> None:
        self.assertIn("DANGER_THRESHOLD = 10000", self.js)

    def test_warn_class_constant(self) -> None:
        self.assertIn('WARN_CLASS = "warn"', self.js)

    def test_danger_class_constant(self) -> None:
        self.assertIn('DANGER_CLASS = "danger"', self.js)

    def test_i18n_key_constant(self) -> None:
        self.assertIn('I18N_KEY = "feedback.charCounter"', self.js)

    def test_threshold_ordering(self) -> None:
        # WARN < DANGER 是阈值变色逻辑前提；硬数字关系也写成测试防退化
        self.assertLess(
            8000,
            10000,
            "WARN_THRESHOLD 必须 < DANGER_THRESHOLD（变色递进顺序）",
        )


# ----------------------------------------------------------------------
# Class 3: API 函数签名 + window.AIIA_FEEDBACK_CHAR_COUNTER 暴露
# ----------------------------------------------------------------------


class TestApiSurface(unittest.TestCase):
    def setUp(self) -> None:
        self.js = _read_js()

    def test_format_count_function_present(self) -> None:
        self.assertRegex(self.js, r"function\s+_formatCount\s*\(\s*count\s*\)")

    def test_resolve_label_function_present(self) -> None:
        self.assertRegex(self.js, r"function\s+_resolveLabel\s*\(\s*count\s*\)")

    def test_apply_threshold_class_function_present(self) -> None:
        self.assertRegex(
            self.js,
            r"function\s+_applyThresholdClass\s*\(\s*node\s*,\s*count\s*\)",
        )

    def test_update_counter_function_present(self) -> None:
        self.assertRegex(
            self.js,
            r"function\s+updateCounter\s*\(\s*textarea\s*,\s*counter\s*\)",
        )

    def test_init_function_present(self) -> None:
        self.assertRegex(self.js, r"function\s+init\s*\(\s*\)")

    def test_window_exposure(self) -> None:
        self.assertIn("window.AIIA_FEEDBACK_CHAR_COUNTER", self.js)
        # 全部公共 API 都必须 export
        for name in (
            "TARGET_ID",
            "COUNTER_ID",
            "WARN_THRESHOLD",
            "DANGER_THRESHOLD",
            "WARN_CLASS",
            "DANGER_CLASS",
            "I18N_KEY",
            "_formatCount",
            "_resolveLabel",
            "_applyThresholdClass",
            "updateCounter",
            "init",
        ):
            self.assertIn(
                name + ":",
                self.js,
                f"window.AIIA_FEEDBACK_CHAR_COUNTER 必须 export {name}",
            )


# ----------------------------------------------------------------------
# Class 4: graceful failure / fallback 路径
# ----------------------------------------------------------------------


class TestGracefulFallback(unittest.TestCase):
    def setUp(self) -> None:
        self.js = _read_js()

    def test_format_count_has_intl_try_catch(self) -> None:
        # _formatCount 必须 try/catch Intl.NumberFormat
        self.assertRegex(
            self.js,
            r"_formatCount[\s\S]*?try\s*\{\s*[\s\S]*?Intl\.NumberFormat",
        )
        # catch 块必须有 String(count) fallback
        self.assertRegex(
            self.js,
            r"catch[\s\S]*?return\s+String\(count\)",
        )

    def test_t_helper_has_i18n_try_catch(self) -> None:
        # _t helper 必须 try/catch window.AIIA_I18N runtime 调用
        self.assertRegex(
            self.js,
            r"function\s+_t[\s\S]*?try\s*\{\s*[\s\S]*?window\.AIIA_I18N",
        )

    def test_resolve_label_calls_t_with_literal_key(self) -> None:
        # i18n orphan / dead-key 扫描器要求 ``_t("xxx")`` 字面值调用
        # ——而非 ``_t(I18N_KEY, ...)`` indirect。这里锁定字面值调用。
        self.assertRegex(
            self.js,
            r'_t\(\s*"feedback\.charCounter"',
        )

    def test_fallback_table_has_feedback_charcounter(self) -> None:
        # FALLBACK_TEXT 必须含 "feedback.charCounter" → 英文兜底
        # （CJK 护栏 + base locale 对齐）
        self.assertRegex(
            self.js,
            r'FALLBACK_TEXT[\s\S]*?"feedback\.charCounter"\s*:\s*"\{\{count\}\}',
        )

    def test_t_helper_uses_mustache_replacement(self) -> None:
        # fallback 路径用 mustache `\{\{(\w+)\}\}` 替换，与 i18n.js 一致
        self.assertRegex(
            self.js,
            r"\\\{\\\{\(\\w\+\)\\\}\\\}",
        )

    def test_apply_threshold_class_handles_missing_classlist(self) -> None:
        # _applyThresholdClass 必须先检查 node.classList 存在再调用
        self.assertRegex(
            self.js,
            r"_applyThresholdClass[\s\S]*?if\s*\(\s*!node\s*\|\|\s*!node\.classList\s*\)",
        )

    def test_update_counter_zero_count_hides(self) -> None:
        # count == 0 时 hidden = true 且 textContent = ""
        self.assertRegex(
            self.js,
            r"if\s*\(\s*count\s*===\s*0\s*\)[\s\S]*?counter\.hidden\s*=\s*true",
        )


# ----------------------------------------------------------------------
# Class 5: HTML / context 集成
# ----------------------------------------------------------------------


class TestHtmlIntegration(unittest.TestCase):
    def setUp(self) -> None:
        self.html = _read_html()
        self.web_ui_py = WEB_UI_PY.read_text(encoding="utf-8")
        self.css = _read_css()

    def test_counter_span_inside_textarea_container(self) -> None:
        # textarea-container 块内必须含 #feedback-char-counter
        self.assertRegex(
            self.html,
            r'class="textarea-container"[\s\S]*?id="feedback-char-counter"[\s\S]*?</div>',
        )

    def test_counter_span_has_aria_live_polite(self) -> None:
        self.assertRegex(
            self.html,
            r'id="feedback-char-counter"[\s\S]*?aria-live="polite"',
        )

    def test_counter_span_has_hidden_attr(self) -> None:
        # 初始 hidden 避免空 textarea 时显示空白 span
        self.assertRegex(
            self.html,
            r'id="feedback-char-counter"[\s\S]*?hidden',
        )

    def test_script_tag_with_defer_nonce_and_version(self) -> None:
        # <script defer src="..feedback_char_counter.js?v={{...}}"
        # nonce="{{ csp_nonce }}">
        self.assertRegex(
            self.html,
            (
                r"<script[\s\S]*?defer[\s\S]*?"
                r'src="/static/js/feedback_char_counter\.js'
                r'\?v=\{\{\s*feedback_char_counter_version\s*\}\}"[\s\S]*?'
                r'nonce="\{\{\s*csp_nonce\s*\}\}"'
            ),
        )

    def test_template_context_provides_version(self) -> None:
        # web_ui.py 必须给 template 注入 feedback_char_counter_version
        self.assertRegex(
            self.web_ui_py,
            r'"feedback_char_counter_version":\s*_compute_file_version\(',
        )

    def test_css_has_feedback_char_counter_selector(self) -> None:
        # CSS 必须含 .feedback-char-counter 主选择器 + warn / danger 阈值
        self.assertIn(".feedback-char-counter {", self.css)
        self.assertIn(".feedback-char-counter.warn {", self.css)
        self.assertIn(".feedback-char-counter.danger {", self.css)

    def test_css_uses_warning_and_error_tokens(self) -> None:
        # 三阈值类必须用项目色板 token 而非硬编码 hex，与 R66 品牌色护栏一致
        css = self.css
        match_warn = re.search(
            r"\.feedback-char-counter\.warn\s*\{([\s\S]*?)\}",
            css,
        )
        if match_warn is None:
            self.fail("缺 .feedback-char-counter.warn 选择器")
        warn_body = match_warn.group(1)
        self.assertIn("var(--warning-500)", warn_body)
        self.assertIn("var(--warning-bg)", warn_body)

        match_danger = re.search(
            r"\.feedback-char-counter\.danger\s*\{([\s\S]*?)\}",
            css,
        )
        if match_danger is None:
            self.fail("缺 .feedback-char-counter.danger 选择器")
        danger_body = match_danger.group(1)
        self.assertIn("var(--error-500)", danger_body)
        self.assertIn("var(--error-bg)", danger_body)


# ----------------------------------------------------------------------
# Class 6: i18n 三 locale 全覆盖
# ----------------------------------------------------------------------


class TestI18nCoverage(unittest.TestCase):
    def test_zh_cn_has_feedback_char_counter(self) -> None:
        data = _read_locale(LOCALE_ZH)
        self.assertIn("feedback", data, "zh-CN.json 缺 feedback namespace")
        self.assertIn(
            "charCounter",
            data["feedback"],
            "zh-CN.json 缺 feedback.charCounter",
        )
        self.assertIn("{{count}}", data["feedback"]["charCounter"])
        self.assertIn("字符", data["feedback"]["charCounter"])

    def test_en_has_feedback_char_counter(self) -> None:
        data = _read_locale(LOCALE_EN)
        self.assertIn("feedback", data, "en.json 缺 feedback namespace")
        self.assertIn(
            "charCounter",
            data["feedback"],
            "en.json 缺 feedback.charCounter",
        )
        self.assertIn("{{count}}", data["feedback"]["charCounter"])
        self.assertIn("char", data["feedback"]["charCounter"].lower())

    def test_pseudo_has_feedback_char_counter(self) -> None:
        data = _read_locale(LOCALE_PSEUDO)
        self.assertIn("feedback", data, "_pseudo/pseudo.json 缺 feedback")
        self.assertIn(
            "charCounter",
            data["feedback"],
            "_pseudo/pseudo.json 缺 feedback.charCounter",
        )
        # pseudo locale 必须保留原占位
        self.assertIn("{{count}}", data["feedback"]["charCounter"])


if __name__ == "__main__":
    unittest.main()
