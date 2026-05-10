"""R146 — Settings UI button: trigger system-level notification self-test.

R141 已经把 ``POST /api/system/notifications/test`` 落成 endpoint；R142 / R143
/ R145 把 per-provider stats / last_error_class / success+failure streak 全部
铺到 ``GET /api/system/health``。**直到 R145 为止，唯一触发途径还是 ``curl``**
——运维 / 监控 OK，但用户改完 Bark / desktop / sound 配置后想"试一下"还得
打开终端，体验断层。R146 闭这个口：在「Test functions」分组里加一个
``Send system self-test`` 按钮，点击 → POST endpoint → 在按钮下方的
``setting-status-line`` 实时打印结果（已触发的 provider 列表 / 限流 / 通知系统
不可用 / 网络错误等）。

约束 / 不变式（覆盖 9 类）：

1.  **JS 模块文件存在 + 体积合理** — 模块文件存在；约 200-360 行（实际
    实现 ≈ 270 行），防误删 / 意外膨胀。
2.  **常量值锁定** — BUTTON_ID = ``system-notification-test-btn`` /
    STATUS_ID = ``system-notification-test-status`` / ENDPOINT = ``/api/
    system/notifications/test`` / CLIENT_COOLDOWN_MS / FETCH_TIMEOUT_MS。
3.  **API 函数签名** — init / triggerSelfTest / _classifyResponse /
    _formatProviderList / _isOnCooldown 全部可见；
    ``window.AIIA_NOTIFICATION_TEST_BUTTON`` 暴露完整 API。
4.  **fetch 路径正确** — POST + Content-Type: application/json +
    JSON.stringify({}) body + same-origin credentials + AbortController
    可选挂钩 + ``finally`` 中 button.disabled = false（即使报错也恢复
    可用）。
5.  **classifyResponse 矩阵** — 429 → rateLimited / 4xx → failed (含
    server message) / 5xx + error="notification_unavailable" →
    unavailable / 5xx + 其它 → failed / 200 + success=true → success /
    200 + success=false + 含 ``disabled``/``enabled=false``/``notification.``
    → disabled / 200 + success=false + 其它 → noProviders。
6.  **HTML 集成** — settings panel 的 Test functions 分组含
    ``<button id="system-notification-test-btn">`` + ``<div id=
    "system-notification-test-status" role="status" aria-live="polite">``；
    ``<script>`` 标签带 ``defer`` + ``nonce={{ csp_nonce }}`` + ``?v=
    {{ notification_test_button_version }}``；``_get_template_context``
    用 ``_compute_file_version`` 计算 ``notification_test_button_version``。
7.  **i18n 双 locale + pseudo** — 10 个 keys（``settings.testSystemBtn``
    / ``settings.testSystemHint`` / ``settings.systemTestSending`` /
    ``settings.systemTestSuccess`` / ``settings.systemTestNoProviders``
    / ``settings.systemTestDisabled`` / ``settings.systemTestRateLimited``
    / ``settings.systemTestUnavailable`` / ``settings.systemTestNetworkError``
    / ``settings.systemTestFailed``）en + zh-CN + _pseudo 全覆盖。
8.  **CSS 状态色样式** — ``.setting-status-line`` + ``.setting-status-pending``
    / ``.setting-status-success`` / ``.setting-status-warning`` /
    ``.setting-status-error`` 在 main.css 存在；颜色用项目 token
    （``--success-500`` / ``--warning-500`` / ``--error-500``）。
9.  **idempotent / cooldown 守卫** — init 二次调用必须 short-circuit
    （``data-r146-bound`` sentinel）；triggerSelfTest 在 cooldown 期内
    返回；button.disabled / _isOnCooldown 双层防 double-click。
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JS_PATH = ROOT / "src/ai_intervention_agent/static/js/notification_test_button.js"
HTML_PATH = ROOT / "src/ai_intervention_agent/templates/web_ui.html"
WEB_UI_PY = ROOT / "src/ai_intervention_agent/web_ui.py"
CSS_PATH = ROOT / "src/ai_intervention_agent/static/css/main.css"
LOCALE_ZH = ROOT / "src/ai_intervention_agent/static/locales/zh-CN.json"
LOCALE_EN = ROOT / "src/ai_intervention_agent/static/locales/en.json"
LOCALE_PSEUDO = ROOT / "src/ai_intervention_agent/static/locales/_pseudo/pseudo.json"

# 与 JS 模块 source-of-truth 完全对齐。任何漂移都让对应测试失败，强制
# 调用方同步更新 i18n / 文档。
EXPECTED_KEYS = (
    "testSystemBtn",
    "testSystemHint",
    "systemTestSending",
    "systemTestSuccess",
    "systemTestNoProviders",
    "systemTestDisabled",
    "systemTestRateLimited",
    "systemTestUnavailable",
    "systemTestNetworkError",
    "systemTestFailed",
)


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
            f"R146 JS 模块文件必须存在: {JS_PATH}",
        )

    def test_js_file_line_count_in_envelope(self) -> None:
        line_count = len(_read_js().splitlines())
        self.assertGreaterEqual(line_count, 200, "R146 JS 模块过短，疑似空壳")
        self.assertLessEqual(line_count, 360, "R146 JS 模块超出预期，疑似膨胀")


# ----------------------------------------------------------------------
# Class 2: 常量值锁定
# ----------------------------------------------------------------------


class TestConstantsLocked(unittest.TestCase):
    def setUp(self) -> None:
        self.js = _read_js()

    def test_button_id_constant(self) -> None:
        self.assertIn(
            'BUTTON_ID = "system-notification-test-btn"',
            self.js,
        )

    def test_status_id_constant(self) -> None:
        self.assertIn(
            'STATUS_ID = "system-notification-test-status"',
            self.js,
        )

    def test_endpoint_constant_matches_r141(self) -> None:
        # 锁定 endpoint 路径与 R141 实现严格一致
        self.assertIn(
            'ENDPOINT = "/api/system/notifications/test"',
            self.js,
        )

    def test_client_cooldown_constant(self) -> None:
        # cooldown 必须 > 0，避免 double-click 立即重发
        self.assertRegex(
            self.js,
            r"CLIENT_COOLDOWN_MS\s*=\s*[1-9]\d{2,}",
        )

    def test_fetch_timeout_constant(self) -> None:
        # 超时必须远大于 Bark 真实 RTT（~2s），且不能无限挂
        self.assertRegex(
            self.js,
            r"FETCH_TIMEOUT_MS\s*=\s*\d+\s*\*\s*1000",
        )


# ----------------------------------------------------------------------
# Class 3: API 函数签名 + window.AIIA_NOTIFICATION_TEST_BUTTON 暴露
# ----------------------------------------------------------------------


class TestApiSurface(unittest.TestCase):
    def setUp(self) -> None:
        self.js = _read_js()

    def test_init_function_present(self) -> None:
        self.assertRegex(self.js, r"function\s+init\s*\(\s*\)")

    def test_trigger_self_test_function_present(self) -> None:
        # 必须是 async（fetch await）
        self.assertRegex(
            self.js,
            r"async\s+function\s+triggerSelfTest\s*\(\s*button\s*,\s*statusNode\s*\)",
        )

    def test_classify_response_function_present(self) -> None:
        self.assertRegex(
            self.js,
            r"function\s+_classifyResponse\s*\(\s*httpStatus\s*,\s*body\s*\)",
        )

    def test_format_provider_list_function_present(self) -> None:
        self.assertRegex(self.js, r"function\s+_formatProviderList\s*\(")

    def test_is_on_cooldown_function_present(self) -> None:
        self.assertRegex(self.js, r"function\s+_isOnCooldown\s*\(\s*button\s*\)")

    def test_window_exposure(self) -> None:
        self.assertIn("window.AIIA_NOTIFICATION_TEST_BUTTON", self.js)
        for name in (
            "BUTTON_ID",
            "STATUS_ID",
            "ENDPOINT",
            "CLIENT_COOLDOWN_MS",
            "FETCH_TIMEOUT_MS",
            "init",
            "triggerSelfTest",
            "_classifyResponse",
            "_formatProviderList",
            "_isOnCooldown",
        ):
            self.assertIn(
                name + ":",
                self.js,
                f"window.AIIA_NOTIFICATION_TEST_BUTTON 必须 export {name}",
            )


# ----------------------------------------------------------------------
# Class 4: fetch 路径正确（method / headers / body / credentials / finally）
# ----------------------------------------------------------------------


class TestFetchPath(unittest.TestCase):
    def setUp(self) -> None:
        self.js = _read_js()

    def test_fetch_method_post(self) -> None:
        self.assertRegex(self.js, r'method:\s*"POST"')

    def test_fetch_content_type_json(self) -> None:
        self.assertRegex(
            self.js,
            r'"Content-Type":\s*"application/json"',
        )

    def test_fetch_body_empty_object(self) -> None:
        # 空 body：服务器默认 provider=all，与 R141 endpoint 行为对齐
        self.assertIn("JSON.stringify({})", self.js)

    def test_fetch_credentials_same_origin(self) -> None:
        self.assertRegex(self.js, r'credentials:\s*"same-origin"')

    def test_fetch_uses_endpoint_constant(self) -> None:
        # 路径必须从常量来，不允许字面值散落
        self.assertRegex(self.js, r"fetch\(\s*ENDPOINT\s*,")

    def test_abort_controller_used(self) -> None:
        # 在支持 AbortController 的环境用，fetch 老超时不会无限挂
        self.assertIn("AbortController", self.js)
        self.assertRegex(self.js, r"controller\.abort\(\s*\)")
        # signal 可以以两种合法形式出现：``signal: controller.signal`` 或
        # ``signal: controller ? controller.signal : undefined``——前者
        # 假设 controller 一定存在，后者保留 fallback。两种我们都接受。
        self.assertRegex(
            self.js, r"signal:\s*controller(?:\s*\?\s*controller)?\.signal"
        )

    def test_button_disabled_during_fetch(self) -> None:
        # 锁住 button.disabled = true 在 await 前
        self.assertRegex(self.js, r"button\.disabled\s*=\s*true")

    def test_button_re_enabled_in_finally(self) -> None:
        # finally 中必须重置 button.disabled = false（无论成功还是异常）
        self.assertRegex(
            self.js,
            r"finally\s*\{[\s\S]*?button\.disabled\s*=\s*false",
        )

    def test_setstatus_called_with_pending_before_fetch(self) -> None:
        # 点击后第一时间显示 "Sending…" 给用户即时反馈
        self.assertRegex(
            self.js,
            r'_setStatus\(statusNode,\s*"pending",\s*_t\("settings\.systemTestSending"\)\)',
        )


# ----------------------------------------------------------------------
# Class 5: classifyResponse 矩阵（lock 完整状态机）
# ----------------------------------------------------------------------


class TestClassifyResponseMatrix(unittest.TestCase):
    def setUp(self) -> None:
        self.js = _read_js()

    def test_429_maps_to_rate_limited(self) -> None:
        self.assertRegex(
            self.js,
            r"httpStatus\s*===\s*429[\s\S]*?settings\.systemTestRateLimited",
        )

    def test_4xx_maps_to_failed_with_server_message(self) -> None:
        # 4xx (非 429) → systemTestFailed，error 来自 body.message / body.error
        self.assertRegex(
            self.js,
            r"httpStatus\s*>=\s*400[\s\S]*?httpStatus\s*<\s*500"
            r"[\s\S]*?settings\.systemTestFailed",
        )

    def test_5xx_unavailable_maps_to_unavailable_key(self) -> None:
        # 5xx + body.error === "notification_unavailable" 走专用 key
        self.assertRegex(
            self.js,
            r'err\s*===\s*"notification_unavailable"'
            r"[\s\S]*?settings\.systemTestUnavailable",
        )

    def test_5xx_other_maps_to_failed(self) -> None:
        # 5xx 其它情况 fallback systemTestFailed（含原始 message / error）
        self.assertRegex(
            self.js,
            r"httpStatus\s*>=\s*500[\s\S]*?settings\.systemTestFailed",
        )

    def test_200_success_true_maps_to_success(self) -> None:
        # body.success === true → systemTestSuccess + providers/event_id
        self.assertRegex(
            self.js,
            r"body\.success\s*===\s*true"
            r"[\s\S]*?settings\.systemTestSuccess",
        )

    def test_200_success_false_disabled_keyword_maps_to_disabled(self) -> None:
        # 含 ``disabled`` / ``enabled=false`` / ``notification.`` 的 server
        # message → systemTestDisabled
        self.assertRegex(
            self.js,
            r"disabled\|enabled=false\|notification\\\.",
        )
        self.assertIn("settings.systemTestDisabled", self.js)

    def test_200_success_false_other_maps_to_no_providers(self) -> None:
        self.assertIn("settings.systemTestNoProviders", self.js)

    def test_provider_list_uses_intl_format_list(self) -> None:
        # _formatProviderList 优先走 i18n.formatList（locale-aware "and"
        # / "、" 分隔符）
        self.assertRegex(
            self.js,
            r"i18n\.formatList\s*\(\s*providers\s*\)",
        )

    def test_message_truncation_applied(self) -> None:
        # 服务器返回的 message 必须截断（avoid runaway error strings 撕
        # 破布局），200 chars 边界
        self.assertIn("slice(0, 200)", self.js)

    def test_event_id_truncation_applied(self) -> None:
        # event_id 截断 64 chars，避免格式化错误时 leak 长字符串
        self.assertIn("slice(0, 64)", self.js)


# ----------------------------------------------------------------------
# Class 6: HTML 模板集成 + script tag + file_version 注入
# ----------------------------------------------------------------------


class TestHtmlIntegration(unittest.TestCase):
    def setUp(self) -> None:
        self.html = _read_html()
        self.web_ui_py = WEB_UI_PY.read_text(encoding="utf-8")

    def test_settings_panel_has_button(self) -> None:
        self.assertRegex(
            self.html,
            r'<button[\s\S]*?id="system-notification-test-btn"',
        )

    def test_settings_panel_has_status_div(self) -> None:
        self.assertRegex(
            self.html,
            (
                r'<div[\s\S]*?id="system-notification-test-status"'
                r'[\s\S]*?role="status"'
                r'[\s\S]*?aria-live="polite"'
            ),
        )

    def test_button_label_uses_i18n(self) -> None:
        self.assertIn('data-i18n="settings.testSystemBtn"', self.html)

    def test_hint_text_uses_i18n(self) -> None:
        self.assertIn('data-i18n="settings.testSystemHint"', self.html)

    def test_script_tag_with_defer_nonce_and_version(self) -> None:
        self.assertRegex(
            self.html,
            (
                r"<script[\s\S]*?defer[\s\S]*?"
                r'src="/static/js/notification_test_button\.js'
                r'\?v=\{\{\s*notification_test_button_version\s*\}\}"[\s\S]*?'
                r'nonce="\{\{\s*csp_nonce\s*\}\}"'
            ),
        )

    def test_template_context_provides_version(self) -> None:
        self.assertRegex(
            self.web_ui_py,
            r'"notification_test_button_version":\s*_compute_file_version\(',
        )

    def test_button_in_test_functions_subgroup(self) -> None:
        # 必须落在 Test functions 子组里（与 test-notification-btn /
        # test-bark-notification-btn 同组），不要被孤立放到别处
        idx_test_section = self.html.find('data-i18n="settings.testSection"')
        idx_button = self.html.find("system-notification-test-btn")
        self.assertGreater(idx_test_section, 0, "settings.testSection 标题必须存在")
        self.assertGreater(idx_button, idx_test_section)


# ----------------------------------------------------------------------
# Class 7: i18n locale 双语种 + pseudo 三套覆盖
# ----------------------------------------------------------------------


class TestI18nLocaleCoverage(unittest.TestCase):
    def test_en_has_all_keys(self) -> None:
        data = _read_locale(LOCALE_EN).get("settings", {})
        for key in EXPECTED_KEYS:
            self.assertIn(key, data, f"en.json 缺 settings.{key}")
            self.assertIsInstance(
                data[key], str, f"en.json settings.{key} 必须是 string"
            )
            self.assertTrue(data[key].strip(), f"en.json settings.{key} 不能为空字符串")

    def test_zh_cn_has_all_keys(self) -> None:
        data = _read_locale(LOCALE_ZH).get("settings", {})
        for key in EXPECTED_KEYS:
            self.assertIn(key, data, f"zh-CN.json 缺 settings.{key}")
            self.assertIsInstance(
                data[key], str, f"zh-CN.json settings.{key} 必须是 string"
            )
            self.assertTrue(
                data[key].strip(),
                f"zh-CN.json settings.{key} 不能为空字符串",
            )

    def test_pseudo_has_all_keys(self) -> None:
        # _pseudo 由 scripts/gen_pseudo_locale.py 自动派生；测试只锁住
        # "key 存在 + 非空 string"，不检查内容（pseudo 字符是变形拼写）。
        data = _read_locale(LOCALE_PSEUDO).get("settings", {})
        for key in EXPECTED_KEYS:
            self.assertIn(key, data, f"_pseudo/pseudo.json 缺 settings.{key}")
            self.assertIsInstance(
                data[key],
                str,
                f"_pseudo/pseudo.json settings.{key} 必须是 string",
            )

    def test_success_message_uses_icu_plural(self) -> None:
        # systemTestSuccess 必须走 ICU plural（"1 provider" vs "N
        # providers"），这是国际化标准做法，避免英文里 "1 providers"
        en = _read_locale(LOCALE_EN)["settings"]["systemTestSuccess"]
        self.assertIn("plural", en, "en.systemTestSuccess 必须用 ICU plural")
        self.assertIn("{count", en)

    def test_message_keys_have_mustache_placeholders(self) -> None:
        # systemTestFailed / Disabled 必须含 ``{{error}}`` / ``{{reason}}``
        # **mustache double-brace** placeholder（项目 i18n runtime 不识别
        # bare ``{name}`` 单括号——会被字面渲染，触发 param-signature
        # linter 报 extra=error/reason）。``_classifyResponse`` 必须传
        # 对应 params 进来。
        en = _read_locale(LOCALE_EN)["settings"]
        self.assertIn("{{error}}", en["systemTestFailed"])
        self.assertIn("{{reason}}", en["systemTestDisabled"])
        # systemTestSuccess 同理：providers / event_id 是双括号 mustache，
        # count 是 ICU plural 的 head（单括号 + ``,plural,``），两种 placeholder
        # 形式必须共存。
        success_en = en["systemTestSuccess"]
        self.assertIn("{{providers}}", success_en)
        self.assertIn("{{event_id}}", success_en)
        self.assertIn("{count, plural", success_en)


# ----------------------------------------------------------------------
# Class 8: CSS 状态色样式（main.css 含 .setting-status-line 全套）
# ----------------------------------------------------------------------


class TestCssStatusLineStyles(unittest.TestCase):
    def setUp(self) -> None:
        self.css = _read_css()

    def test_setting_status_line_class_exists(self) -> None:
        self.assertRegex(self.css, r"\.setting-status-line\s*\{")

    def test_pending_variant_exists(self) -> None:
        self.assertRegex(
            self.css, r"\.setting-status-line\.setting-status-pending\s*\{"
        )

    def test_success_variant_uses_success_token(self) -> None:
        # 颜色必须用项目语义 token，不允许硬编码十六进制
        self.assertRegex(
            self.css,
            r"\.setting-status-line\.setting-status-success\s*\{"
            r"[\s\S]*?--success-500",
        )

    def test_warning_variant_uses_warning_token(self) -> None:
        self.assertRegex(
            self.css,
            r"\.setting-status-line\.setting-status-warning\s*\{"
            r"[\s\S]*?--warning-500",
        )

    def test_error_variant_uses_error_token(self) -> None:
        self.assertRegex(
            self.css,
            r"\.setting-status-line\.setting-status-error\s*\{"
            r"[\s\S]*?--error-500",
        )


# ----------------------------------------------------------------------
# Class 9: idempotent / cooldown / double-click 守卫
# ----------------------------------------------------------------------


class TestIdempotencyAndCooldown(unittest.TestCase):
    def setUp(self) -> None:
        self.js = _read_js()

    def test_init_uses_data_attribute_sentinel(self) -> None:
        # init 二次调用必须 short-circuit；用 data-r146-bound="1" 标记
        self.assertIn("data-r146-bound", self.js)
        self.assertRegex(
            self.js,
            r'getAttribute\("data-r146-bound"\)\s*===\s*"1"'
            r"[\s\S]*?return\s*\{",
        )
        self.assertRegex(
            self.js,
            r'setAttribute\(\s*"data-r146-bound"\s*,\s*"1"\s*\)',
        )

    def test_cooldown_check_before_fetch(self) -> None:
        # _isOnCooldown 必须在 button.disabled = true 之前检查
        self.assertRegex(
            self.js,
            r"_isOnCooldown\(button\)[\s\S]*?return"
            r"[\s\S]*?button\.disabled\s*=\s*true",
        )

    def test_disabled_check_before_cooldown(self) -> None:
        # button.disabled 优先检查，避免 fetch in-flight 时 cooldown 已
        # 过期但 button 还没 enable
        self.assertRegex(
            self.js,
            r"button\.disabled[\s\S]*?return[\s\S]*?_isOnCooldown",
        )

    def test_click_timestamp_stamped(self) -> None:
        # cooldown 用 data-last-click-ts 时间戳；存放在 DOM 上而不是
        # 模块变量，避免节点 re-mount 后丢失
        self.assertIn("data-last-click-ts", self.js)
        self.assertRegex(
            self.js,
            r'setAttribute\(\s*"data-last-click-ts"\s*,\s*String\(Date\.now\(\)\)\s*\)',
        )

    def test_settle_promise_microtask_in_click_handler(self) -> None:
        # click handler 走 Promise.resolve().then 把 await 推到 microtask
        # 队列，避免阻塞渲染
        self.assertRegex(
            self.js,
            r"Promise\.resolve\(\)\.then\(\s*function\s*\(\)\s*\{\s*"
            r"triggerSelfTest\(button,\s*statusNode\)",
        )


if __name__ == "__main__":
    unittest.main()
