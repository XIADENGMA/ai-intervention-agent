"""R140 — Feedback 提交模式切换（Ctrl+Enter vs Enter）测试。

R140 给键盘党 + 短文本反馈用户提供一个偏好开关：让 Enter 直接提交
（Slack / Discord / Notion / Telegram 同款 IM 模式），Shift+Enter 换
行；既保留 Ctrl/Cmd+Enter 路径不破坏熟悉用户。设置走纯前端
``localStorage``（与 R137 / R138 / R139 同款架构），不上服务端
``user_settings``，多设备不同步是合理边界。

约束 / 不变式（覆盖 6 类）：

1.  **JS 模块文件存在 + 体积合理** — 模块文件存在；约 130-200 行（实
    际实现 ≈ 165 行），防误删 / 意外膨胀。
2.  **常量值锁定** — STORAGE_KEY = ``aiia.submitMode.v1`` /
    SCHEMA_VERSION = 1 / DEFAULT_MODE = ``ctrl_enter`` / VALID_MODES =
    [``ctrl_enter``, ``enter``] / TARGET_ID = ``feedback-text`` /
    SUBMIT_BTN_ID = ``submit-btn`` 字面值不漂移。
3.  **API 函数签名** — getMode / setMode / _shouldSubmitOnEnter /
    _triggerSubmit / _isStorageAvailable / setupKeydownInterceptor /
    setupSelectListener / init 全部可见；
    ``window.AIIA_FEEDBACK_SUBMIT_MODE`` 暴露完整 API。
4.  **graceful failure** — _isStorageAvailable / getMode / setMode 全
    try/catch；getMode 在 storage 不可用 / corrupt JSON / schema 不匹
    配 / mode 非法时全部 fallback DEFAULT_MODE。
5.  **keydown 拦截边界** — _shouldSubmitOnEnter 排除 Shift / Alt /
    Ctrl / Cmd / IME composition (isComposing + keyCode 229) 组合
    键，仅单 Enter 命中；setupKeydownInterceptor 用 capture phase
    （第三参数 true）确保 preventDefault 在浏览器 newline 默认行为
    前生效；ctrl_enter 模式下 listener 直接 return（不拦截既有
    handler 路径）。
6.  **HTML / context 集成** — settings panel 含 ``<select id=
    "feedback-submit-mode-select">`` + 两个 option（``ctrl_enter`` /
    ``enter``）；``<script>`` 标签带 ``defer`` + ``nonce={{ csp_nonce
    }}`` + ``?v={{ feedback_submit_mode_version }}``；
    ``_get_template_context`` 用 ``_compute_file_version`` 计算
    ``feedback_submit_mode_version``；i18n 三 locale ``settings.
    submitMode`` / ``settings.submitModeCtrlEnter`` / ``settings.
    submitModeEnter`` / ``settings.submitModeHint`` 全覆盖。
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JS_PATH = ROOT / "src/ai_intervention_agent/static/js/feedback_submit_mode.js"
HTML_PATH = ROOT / "src/ai_intervention_agent/templates/web_ui.html"
WEB_UI_PY = ROOT / "src/ai_intervention_agent/web_ui.py"
LOCALE_ZH = ROOT / "src/ai_intervention_agent/static/locales/zh-CN.json"
LOCALE_EN = ROOT / "src/ai_intervention_agent/static/locales/en.json"
LOCALE_PSEUDO = ROOT / "src/ai_intervention_agent/static/locales/_pseudo/pseudo.json"


def _read_js() -> str:
    return JS_PATH.read_text(encoding="utf-8")


def _read_html() -> str:
    return HTML_PATH.read_text(encoding="utf-8")


def _read_locale(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


# ----------------------------------------------------------------------
# Class 1: JS 模块文件存在 + 体积合理
# ----------------------------------------------------------------------


class TestJsFileExistsAndSize(unittest.TestCase):
    def test_js_file_exists(self) -> None:
        self.assertTrue(
            JS_PATH.exists(),
            f"R140 JS 模块文件必须存在: {JS_PATH}",
        )

    def test_js_file_line_count_in_envelope(self) -> None:
        line_count = len(_read_js().splitlines())
        # 130-220 行 envelope；当前 ≈ 170 行
        self.assertGreaterEqual(line_count, 130, "R140 JS 模块过短，疑似空壳")
        self.assertLessEqual(line_count, 220, "R140 JS 模块超出预期，疑似膨胀")


# ----------------------------------------------------------------------
# Class 2: 常量值锁定
# ----------------------------------------------------------------------


class TestConstantsLocked(unittest.TestCase):
    def setUp(self) -> None:
        self.js = _read_js()

    def test_storage_key_constant(self) -> None:
        self.assertIn('STORAGE_KEY = "aiia.submitMode.v1"', self.js)

    def test_schema_version_constant(self) -> None:
        self.assertIn("SCHEMA_VERSION = 1", self.js)

    def test_default_mode_constant(self) -> None:
        self.assertIn('DEFAULT_MODE = "ctrl_enter"', self.js)

    def test_valid_modes_constant(self) -> None:
        # VALID_MODES 必须含 ctrl_enter + enter 两值
        self.assertRegex(
            self.js,
            r'VALID_MODES\s*=\s*\[\s*"ctrl_enter"\s*,\s*"enter"\s*\]',
        )

    def test_target_id_constant(self) -> None:
        self.assertIn('TARGET_ID = "feedback-text"', self.js)

    def test_submit_btn_id_constant(self) -> None:
        self.assertIn('SUBMIT_BTN_ID = "submit-btn"', self.js)


# ----------------------------------------------------------------------
# Class 3: API 函数签名 + window.AIIA_FEEDBACK_SUBMIT_MODE 暴露
# ----------------------------------------------------------------------


class TestApiSurface(unittest.TestCase):
    def setUp(self) -> None:
        self.js = _read_js()

    def test_get_mode_function_present(self) -> None:
        self.assertRegex(self.js, r"function\s+getMode\s*\(\s*\)")

    def test_set_mode_function_present(self) -> None:
        self.assertRegex(self.js, r"function\s+setMode\s*\(\s*mode\s*\)")

    def test_should_submit_on_enter_function_present(self) -> None:
        self.assertRegex(self.js, r"function\s+_shouldSubmitOnEnter\s*\(\s*event\s*\)")

    def test_trigger_submit_function_present(self) -> None:
        self.assertRegex(self.js, r"function\s+_triggerSubmit\s*\(\s*\)")

    def test_setup_keydown_interceptor_function_present(self) -> None:
        self.assertRegex(
            self.js,
            r"function\s+setupKeydownInterceptor\s*\(\s*textarea\s*\)",
        )

    def test_setup_select_listener_function_present(self) -> None:
        self.assertRegex(self.js, r"function\s+setupSelectListener\s*\(\s*\)")

    def test_init_function_present(self) -> None:
        self.assertRegex(self.js, r"function\s+init\s*\(\s*\)")

    def test_window_exposure(self) -> None:
        self.assertIn("window.AIIA_FEEDBACK_SUBMIT_MODE", self.js)
        for name in (
            "STORAGE_KEY",
            "SCHEMA_VERSION",
            "DEFAULT_MODE",
            "VALID_MODES",
            "TARGET_ID",
            "SUBMIT_BTN_ID",
            "getMode",
            "setMode",
            "_shouldSubmitOnEnter",
            "_triggerSubmit",
            "_isStorageAvailable",
            "setupKeydownInterceptor",
            "setupSelectListener",
            "init",
        ):
            self.assertIn(
                name + ":",
                self.js,
                f"window.AIIA_FEEDBACK_SUBMIT_MODE 必须 export {name}",
            )


# ----------------------------------------------------------------------
# Class 4: graceful failure / fallback 路径
# ----------------------------------------------------------------------


class TestGracefulFallback(unittest.TestCase):
    def setUp(self) -> None:
        self.js = _read_js()

    def test_get_mode_has_try_catch_with_fallback(self) -> None:
        # getMode 必须 try/catch 包 localStorage 调用，catch 块 return
        # DEFAULT_MODE
        self.assertRegex(
            self.js,
            r"function\s+getMode[\s\S]*?try[\s\S]*?localStorage\.getItem"
            r"[\s\S]*?catch[\s\S]*?return\s+DEFAULT_MODE",
        )

    def test_get_mode_validates_schema_version(self) -> None:
        # schema_version 不匹配时 return DEFAULT_MODE
        self.assertRegex(
            self.js,
            r"getMode[\s\S]*?parsed\.schema_version\s*!==\s*SCHEMA_VERSION"
            r"[\s\S]*?return\s+DEFAULT_MODE",
        )

    def test_get_mode_validates_mode_in_valid_modes(self) -> None:
        # mode 不在 VALID_MODES 中时 return DEFAULT_MODE
        self.assertRegex(
            self.js,
            r"getMode[\s\S]*?VALID_MODES\.indexOf\(mode\)\s*===\s*-1"
            r"[\s\S]*?return\s+DEFAULT_MODE",
        )

    def test_set_mode_validates_input(self) -> None:
        # setMode 拒绝非法 mode（VALID_MODES.indexOf(mode) === -1 → return false）
        self.assertRegex(
            self.js,
            r"function\s+setMode[\s\S]*?VALID_MODES\.indexOf\(mode\)\s*===\s*-1"
            r"[\s\S]*?return\s+false",
        )

    def test_set_mode_has_try_catch(self) -> None:
        self.assertRegex(
            self.js,
            r"function\s+setMode[\s\S]*?try[\s\S]*?localStorage\.setItem"
            r"[\s\S]*?catch",
        )

    def test_storage_available_probe_pattern(self) -> None:
        self.assertRegex(
            self.js,
            r"_isStorageAvailable[\s\S]*?try[\s\S]*?localStorage\.setItem"
            r"[\s\S]*?localStorage\.removeItem[\s\S]*?catch",
        )


# ----------------------------------------------------------------------
# Class 5: keydown 拦截边界
# ----------------------------------------------------------------------


class TestKeydownInterception(unittest.TestCase):
    def setUp(self) -> None:
        self.js = _read_js()

    def test_should_submit_excludes_non_enter(self) -> None:
        # 非 Enter 键不命中
        self.assertRegex(
            self.js,
            r'_shouldSubmitOnEnter[\s\S]*?event\.key\s*!==\s*"Enter"'
            r"[\s\S]*?return\s+false",
        )

    def test_should_submit_excludes_shift(self) -> None:
        self.assertRegex(
            self.js,
            r"_shouldSubmitOnEnter[\s\S]*?event\.shiftKey[\s\S]*?return\s+false",
        )

    def test_should_submit_excludes_alt(self) -> None:
        self.assertRegex(
            self.js,
            r"_shouldSubmitOnEnter[\s\S]*?event\.altKey[\s\S]*?return\s+false",
        )

    def test_should_submit_excludes_ctrl_or_meta(self) -> None:
        # Ctrl+Enter / Cmd+Enter 让既有 handler 处理
        self.assertRegex(
            self.js,
            r"_shouldSubmitOnEnter[\s\S]*?event\.ctrlKey\s*\|\|\s*event\.metaKey"
            r"[\s\S]*?return\s+false",
        )

    def test_should_submit_excludes_ime_composition(self) -> None:
        # IME composition：isComposing + keyCode 229 双重判断
        self.assertRegex(
            self.js,
            r"_shouldSubmitOnEnter[\s\S]*?event\.isComposing[\s\S]*?return\s+false",
        )
        self.assertRegex(
            self.js,
            r"_shouldSubmitOnEnter[\s\S]*?event\.keyCode\s*===\s*229"
            r"[\s\S]*?return\s+false",
        )

    def test_setup_keydown_interceptor_uses_capture_phase(self) -> None:
        # textarea.addEventListener("keydown", handler, true) — 第三参数 true 走 capture
        self.assertRegex(
            self.js,
            r'textarea\.addEventListener\(\s*"keydown"\s*,\s*handler\s*,\s*true\s*\)',
        )

    def test_handler_returns_early_in_ctrl_enter_mode(self) -> None:
        # ctrl_enter 模式下 listener 直接 return（不拦截既有 handler 路径）
        self.assertRegex(
            self.js,
            r'getMode\(\)\s*!==\s*"enter"[\s\S]*?return',
        )

    def test_handler_calls_prevent_default_and_trigger_submit(self) -> None:
        # 命中条件后必须 preventDefault + 调 _triggerSubmit
        self.assertRegex(
            self.js,
            r"event\.preventDefault\(\)[\s\S]*?_triggerSubmit\(\)",
        )

    def test_trigger_submit_respects_disabled(self) -> None:
        # 提交按钮 disabled 时不触发 click
        self.assertRegex(
            self.js,
            r"_triggerSubmit[\s\S]*?btn\.disabled[\s\S]*?return\s+false",
        )


# ----------------------------------------------------------------------
# Class 6: HTML / context 集成 + i18n
# ----------------------------------------------------------------------


class TestHtmlIntegrationAndI18n(unittest.TestCase):
    def setUp(self) -> None:
        self.html = _read_html()
        self.web_ui_py = WEB_UI_PY.read_text(encoding="utf-8")

    def test_settings_panel_has_select(self) -> None:
        self.assertRegex(
            self.html,
            r'<select[\s\S]*?id="feedback-submit-mode-select"',
        )

    def test_settings_panel_has_both_options(self) -> None:
        self.assertRegex(
            self.html,
            (
                r'<option\s+value="ctrl_enter"[\s\S]*?'
                r'data-i18n="settings\.submitModeCtrlEnter"'
            ),
        )
        self.assertRegex(
            self.html,
            (
                r'<option\s+value="enter"[\s\S]*?'
                r'data-i18n="settings\.submitModeEnter"'
            ),
        )

    def test_settings_panel_has_label_with_i18n(self) -> None:
        self.assertIn('data-i18n="settings.submitMode"', self.html)
        self.assertIn('data-i18n="settings.submitModeHint"', self.html)

    def test_script_tag_with_defer_nonce_and_version(self) -> None:
        self.assertRegex(
            self.html,
            (
                r"<script[\s\S]*?defer[\s\S]*?"
                r'src="/static/js/feedback_submit_mode\.js'
                r'\?v=\{\{\s*feedback_submit_mode_version\s*\}\}"[\s\S]*?'
                r'nonce="\{\{\s*csp_nonce\s*\}\}"'
            ),
        )

    def test_template_context_provides_version(self) -> None:
        self.assertRegex(
            self.web_ui_py,
            r'"feedback_submit_mode_version":\s*_compute_file_version\(',
        )

    def test_zh_cn_has_submit_mode_keys(self) -> None:
        data = _read_locale(LOCALE_ZH).get("settings", {})
        for key in (
            "submitMode",
            "submitModeCtrlEnter",
            "submitModeEnter",
            "submitModeHint",
        ):
            self.assertIn(key, data, f"zh-CN.json 缺 settings.{key}")

    def test_en_has_submit_mode_keys(self) -> None:
        data = _read_locale(LOCALE_EN).get("settings", {})
        for key in (
            "submitMode",
            "submitModeCtrlEnter",
            "submitModeEnter",
            "submitModeHint",
        ):
            self.assertIn(key, data, f"en.json 缺 settings.{key}")

    def test_pseudo_has_submit_mode_keys(self) -> None:
        data = _read_locale(LOCALE_PSEUDO).get("settings", {})
        for key in (
            "submitMode",
            "submitModeCtrlEnter",
            "submitModeEnter",
            "submitModeHint",
        ):
            self.assertIn(key, data, f"_pseudo/pseudo.json 缺 settings.{key}")


if __name__ == "__main__":
    unittest.main()
