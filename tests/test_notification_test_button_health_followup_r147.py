"""R147 — Notification self-test button: health-endpoint follow-up probe.

R146 落地时只闭到 ``POST /api/system/notifications/test`` 这一步——按钮点击 →
endpoint 触发 → 在按钮下方显示「已触发 N 个 provider」。但「已触发」≠ 「已送达」：
真实交付状态要看 ``GET /api/system/health``——具体路径是
``body.checks.notification.per_provider``（R142 ``_safe_per_provider_snapshot``
直接挂在 ``notification`` 子树上，**没有** ``.stats`` 中转层）；R143 / R145
把 last_error_class / streak 全铺到那个 dict 的每个 provider 条目里。
R147 把这条链路在 UI 内闭合：

1. 点 button → POST endpoint 拿到 ``providers_dispatched``。
2. 等 ``PROBE_DELAY_MS = 1500ms`` 让后端 async send 完成（Bark RTT ~1-2s）。
3. GET ``/api/system/health`` 读 ``checks.notification.per_provider`` 取出我们
   刚刚 dispatch 的 provider 子集。
4. 对每个 provider 走 ``_classifyProviderVerdict``：success / failure / stale /
   skipped / unknown 五类，渲染到 ``#system-notification-test-probe`` 这条
   ``aria-live="polite"`` 的副状态行。
5. 任何 transport / parsing 失败 → 静默清空 probe 行，主状态保留（graceful
   degradation，与 R140 / R146 风格一致）。

约束 / 不变式（覆盖 8 类）：

1.  **常量值锁定** — PROBE_ID = ``system-notification-test-probe`` /
    HEALTH_ENDPOINT = ``/api/system/health`` / PROBE_DELAY_MS / PROBE_TIMEOUT_MS
    / PROBE_STALE_THRESHOLD_S 全部存在且数值合理。
2.  **API 函数签名** — ``_classifyProviderVerdict`` / ``_renderProviderVerdict``
    / ``_probeHealthForProviders`` / ``_runProbe`` / ``_setProbe`` 五个函数
    可见；``window.AIIA_NOTIFICATION_TEST_BUTTON`` 暴露这五个 helper。
3.  **HTML probe 节点** — 模板含 ``<div id="system-notification-test-probe"
    role="status" aria-live="polite">``；位置紧跟在主状态 div 之后；样式继承
    ``setting-status-line``。
4.  **classifyProviderVerdict 决策树** — null/non-object → skipped；
    last_error_class === ``not_registered`` → skipped；两个 age 都 null /
    都 > 阈值 → stale；最近一次失败 → failure（带 errorClass + streak）；
    最近一次成功 → success（带 streak）。
5.  **dispatch → probe 联动** — triggerSelfTest 必须在 ``verdict.kind ===
    "success"`` 且 ``providers_dispatched`` 非空时才调 ``_runProbe``；4xx /
    5xx / disabled / no_providers 路径绝不触发 probe。
6.  **graceful failure** — ``_probeHealthForProviders`` 遇 fetch 失败 / 非
    200 / 非 JSON / abort 全部返回 null（不抛）；``_runProbe`` 拿到 null 必须
    清空 probe 行而不是渲染错误。
7.  **i18n locale 双语种 + pseudo** — 6 个 R147 keys（``settings.systemTestProbing``
    / ``settings.systemTestProbeProviderSuccess`` / ``settings.systemTestProbeProviderFailure``
    / ``settings.systemTestProbeProviderStale`` / ``settings.systemTestProbeProviderSkipped``
    / ``settings.systemTestProbeProviderUnknown``）en + zh-CN + _pseudo 全覆盖。
8.  **state hygiene** — 新一次点击必须先清空 probe 行（避免上一次的「bark:
    delivered」遗留）；button.disabled 在 probe 完成后才释放（idempotent
    contract，防 mash）。
"""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JS_PATH = ROOT / "src/ai_intervention_agent/static/js/notification_test_button.js"
HTML_PATH = ROOT / "src/ai_intervention_agent/templates/web_ui.html"
LOCALE_ZH = ROOT / "src/ai_intervention_agent/static/locales/zh-CN.json"
LOCALE_EN = ROOT / "src/ai_intervention_agent/static/locales/en.json"
LOCALE_PSEUDO = ROOT / "src/ai_intervention_agent/static/locales/_pseudo/pseudo.json"

R147_EXPECTED_KEYS = (
    "systemTestProbing",
    "systemTestProbeProviderSuccess",
    "systemTestProbeProviderFailure",
    "systemTestProbeProviderStale",
    "systemTestProbeProviderSkipped",
    "systemTestProbeProviderUnknown",
)


def _read_js() -> str:
    return JS_PATH.read_text(encoding="utf-8")


def _read_html() -> str:
    return HTML_PATH.read_text(encoding="utf-8")


def _read_locale(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


# ----------------------------------------------------------------------
# Class 1: 常量值锁定
# ----------------------------------------------------------------------


class TestR147ConstantsLocked(unittest.TestCase):
    def setUp(self) -> None:
        self.js = _read_js()

    def test_probe_id_constant(self) -> None:
        self.assertIn(
            'PROBE_ID = "system-notification-test-probe"',
            self.js,
        )

    def test_health_endpoint_constant(self) -> None:
        self.assertIn(
            'HEALTH_ENDPOINT = "/api/system/health"',
            self.js,
        )

    def test_probe_delay_constant_reasonable(self) -> None:
        # 1000-3000ms：Bark HTTP RTT ~1-2s 实测，太短会赶不上后端 async
        # send 写 stats，太长会让用户等到失去耐心
        m = re.search(r"PROBE_DELAY_MS\s*=\s*(\d+)", self.js)
        self.assertIsNotNone(m, "缺 PROBE_DELAY_MS 常量")
        assert m is not None  # for type checker
        v = int(m.group(1))
        self.assertGreaterEqual(v, 1000, "PROBE_DELAY_MS 太短")
        self.assertLessEqual(v, 3000, "PROBE_DELAY_MS 太长")

    def test_probe_timeout_constant_reasonable(self) -> None:
        # 1-10s：/health 是本地 endpoint RTT ~10ms，5s 是宽松上限
        self.assertRegex(
            self.js,
            r"PROBE_TIMEOUT_MS\s*=\s*\d+\s*\*\s*1000",
        )

    def test_probe_stale_threshold_reasonable(self) -> None:
        # 阈值需 >= PROBE_DELAY_MS / 1000 + 一些 headroom，否则 dispatch
        # 真到的事件也会被误判 stale
        m = re.search(r"PROBE_STALE_THRESHOLD_S\s*=\s*(\d+)", self.js)
        self.assertIsNotNone(m, "缺 PROBE_STALE_THRESHOLD_S 常量")
        assert m is not None  # for type checker
        v = int(m.group(1))
        self.assertGreaterEqual(v, 5, "PROBE_STALE_THRESHOLD_S 太短，会误报 stale")
        self.assertLessEqual(
            v, 60, "PROBE_STALE_THRESHOLD_S 太长，stale fail-mode 失效"
        )


# ----------------------------------------------------------------------
# Class 2: API 函数签名 + window 暴露
# ----------------------------------------------------------------------


class TestR147ApiSurface(unittest.TestCase):
    def setUp(self) -> None:
        self.js = _read_js()

    def test_classify_provider_verdict_function_present(self) -> None:
        # R148 起签名扩展为 ``(stats, baselineStats)``；保留对 stats 入参
        # 的强约束，第二参可有可无（兼容 R147 only 的调用方式）。
        self.assertRegex(
            self.js,
            r"function\s+_classifyProviderVerdict\s*\(\s*stats(?:\s*,\s*\w+)?\s*\)",
        )

    def test_render_provider_verdict_function_present(self) -> None:
        self.assertRegex(
            self.js,
            r"function\s+_renderProviderVerdict\s*\(\s*provider\s*,\s*verdict\s*\)",
        )

    def test_probe_health_for_providers_function_present(self) -> None:
        # R148 起把 fetch / abort 主体抽进 _fetchHealthSnapshot；
        # _probeHealthForProviders 仍存在为 backwards-compat alias，
        # 签名仍是 (providers)，但是函数声明不再是 async（thin delegate）。
        self.assertRegex(
            self.js,
            r"function\s+_probeHealthForProviders\s*\(\s*providers\s*\)",
        )

    def test_run_probe_function_present(self) -> None:
        # R148 起加可选第三参 baseline；保留前两参强约束。
        self.assertRegex(
            self.js,
            r"async\s+function\s+_runProbe\s*\(\s*providers\s*,\s*probeNode(?:\s*,\s*\w+)?\s*\)",
        )

    def test_set_probe_function_present(self) -> None:
        self.assertRegex(
            self.js,
            r"function\s+_setProbe\s*\(\s*node\s*,\s*kind\s*,\s*text\s*\)",
        )

    def test_window_exports_r147_helpers(self) -> None:
        # 全部 helper 必须 export，方便 test / debug 直接调
        for name in (
            "PROBE_ID",
            "HEALTH_ENDPOINT",
            "PROBE_DELAY_MS",
            "PROBE_TIMEOUT_MS",
            "PROBE_STALE_THRESHOLD_S",
            "_classifyProviderVerdict",
            "_renderProviderVerdict",
            "_probeHealthForProviders",
            "_runProbe",
            "_setProbe",
        ):
            self.assertIn(
                name + ":",
                self.js,
                f"window.AIIA_NOTIFICATION_TEST_BUTTON 必须 export {name}",
            )


# ----------------------------------------------------------------------
# Class 3: HTML probe 节点
# ----------------------------------------------------------------------


class TestR147HtmlIntegration(unittest.TestCase):
    def setUp(self) -> None:
        self.html = _read_html()

    def test_probe_div_present(self) -> None:
        self.assertRegex(
            self.html,
            (
                r'<div[\s\S]*?id="system-notification-test-probe"'
                r'[\s\S]*?role="status"'
                r'[\s\S]*?aria-live="polite"'
            ),
        )

    def test_probe_div_uses_setting_status_line_class(self) -> None:
        # 复用 R146 的 ``.setting-status-line``，避免漂移
        m = re.search(
            r'<div[^>]*id="system-notification-test-probe"[^>]*>',
            self.html,
        )
        self.assertIsNotNone(m, "找不到 probe div")
        assert m is not None  # for type checker
        self.assertIn("setting-status-line", m.group(0))

    def test_probe_div_after_status_div(self) -> None:
        # probe 行必须在主 status 行之后渲染（DOM 顺序），否则 aria-live
        # 公告顺序就反了
        idx_status = self.html.find("system-notification-test-status")
        idx_probe = self.html.find("system-notification-test-probe")
        self.assertGreater(idx_status, 0)
        self.assertGreater(idx_probe, idx_status, "probe div 必须在 status div 之后")


# ----------------------------------------------------------------------
# Class 4: classifyProviderVerdict 决策树
# ----------------------------------------------------------------------


class TestR147ClassifyVerdictMatrix(unittest.TestCase):
    """通过 grep / regex 锁住决策树各个分支的存在；运行时语义由 JS 单测
    （未来引入）补；这里先保证 source 中的关键路径不会被悄悄删掉。"""

    def setUp(self) -> None:
        self.js = _read_js()

    def test_skipped_no_stats_branch(self) -> None:
        # 输入 null / 非 object → kind: "skipped", reason: "no_stats"
        self.assertRegex(
            self.js,
            (
                r'!stats\s*\|\|\s*typeof\s+stats\s*!==\s*"object"'
                r'[\s\S]*?kind:\s*"skipped"'
                r'[\s\S]*?reason:\s*"no_stats"'
            ),
        )

    def test_skipped_not_registered_branch(self) -> None:
        # last_error_class === "not_registered" → skipped
        self.assertRegex(
            self.js,
            (
                r'lastErrorClass\s*===\s*"not_registered"'
                r'[\s\S]*?kind:\s*"skipped"'
                r'[\s\S]*?reason:\s*"not_registered"'
            ),
        )

    def test_stale_branch(self) -> None:
        # freshest === null OR > PROBE_STALE_THRESHOLD_S → stale
        self.assertRegex(
            self.js,
            (
                r"freshest\s*===\s*null"
                r"\s*\|\|\s*freshest\s*>\s*PROBE_STALE_THRESHOLD_S"
                r'[\s\S]*?kind:\s*"stale"'
            ),
        )

    def test_failure_branch(self) -> None:
        # lastWas === "failure" → kind: failure + errorClass
        self.assertRegex(
            self.js,
            (
                r'lastWas\s*===\s*"failure"'
                r'[\s\S]*?kind:\s*"failure"'
                r"[\s\S]*?errorClass:"
            ),
        )

    def test_success_branch(self) -> None:
        # lastWas === "success" → kind: success + streak
        self.assertRegex(
            self.js,
            (
                r'lastWas\s*===\s*"success"'
                r'[\s\S]*?kind:\s*"success"'
                r"[\s\S]*?streak:"
            ),
        )

    def test_uses_min_of_success_and_failure_age(self) -> None:
        # 决策必须看「最近一次事件」（success_age 与 failure_age 取小），
        # 不能只看 success_age，否则失败的 dispatch 会被误判 stale
        self.assertIn("last_success_age_seconds", self.js)
        self.assertIn("last_failure_age_seconds", self.js)
        self.assertRegex(self.js, r"failureAge\s*<=\s*successAge")


# ----------------------------------------------------------------------
# Class 5: dispatch → probe 联动
# ----------------------------------------------------------------------


class TestR147DispatchProbeWiring(unittest.TestCase):
    def setUp(self) -> None:
        self.js = _read_js()

    def test_run_probe_called_only_on_success_with_providers(self) -> None:
        # 触发条件：kind === "success" + providers_dispatched 非空。
        # R148 起 _runProbe 多了第三参 baseline；这里放宽到允许尾部跟一
        # 个标识符。
        self.assertRegex(
            self.js,
            (
                r'verdict\.kind\s*===\s*"success"'
                r"[\s\S]*?providers_dispatched"
                r"[\s\S]*?_runProbe\(\s*body\.providers_dispatched\s*,\s*probeNode(?:\s*,\s*\w+)?\s*\)"
            ),
        )

    def test_run_probe_awaits_so_button_stays_disabled(self) -> None:
        # 必须 ``await _runProbe(...)`` 才能让 button.disabled 在 probe
        # 期间保持，等 probe 完了 finally 再 false。否则用户在 probe 跑
        # 的 1.5s 内连点会同时多次 dispatch（破坏 idempotent contract）
        self.assertRegex(
            self.js,
            r"await\s+_runProbe\(",
        )

    def test_probe_cleared_at_start_of_new_run(self) -> None:
        # 每次新点击必须先 _setProbe(probeNode, "neutral", "") 清空残留
        self.assertRegex(
            self.js,
            r'_setProbe\(probeNode,\s*"neutral",\s*""\)',
        )

    def test_init_passes_probe_node_to_trigger(self) -> None:
        # init 找到 probeNode 后必须传进 click handler 的 triggerSelfTest 调用
        self.assertRegex(
            self.js,
            (
                r"var\s+probeNode\s*=\s*document\.getElementById\(\s*PROBE_ID\s*\)"
                r"[\s\S]*?triggerSelfTest\(button,\s*statusNode,\s*probeNode\)"
            ),
        )


# ----------------------------------------------------------------------
# Class 6: graceful failure（fetch 失败 / 非 200 / 非 JSON / abort 全 → null）
# ----------------------------------------------------------------------


class TestR147GracefulFailure(unittest.TestCase):
    def setUp(self) -> None:
        self.js = _read_js()

    def test_probe_health_returns_null_on_non_ok(self) -> None:
        # !resp.ok → return null
        self.assertRegex(
            self.js,
            r"if\s*\(\s*!resp\.ok\s*\)\s*return\s+null",
        )

    def test_probe_health_returns_null_on_throw(self) -> None:
        # try/catch 必须返回 null（不重新抛）
        self.assertRegex(
            self.js,
            r"catch\s*\(\s*_err\s*\)\s*\{\s*return\s+null;?\s*\}",
        )

    def test_probe_health_uses_correct_response_path(self) -> None:
        # Server contract (R142): per_provider is at
        #   body.checks.notification.per_provider — NOT under .stats.
        # 这里锁住 source 不能漂回 ``stats.per_provider`` 的旧路径，否则
        # 真实环境 probe 永远拿不到数据，会全部走 stale 分支。
        self.assertIn("notif.per_provider", self.js)
        # 反向断言：source 中不能出现 stats.per_provider（无 stats 中转）
        self.assertNotIn("stats.per_provider", self.js)

    def test_probe_health_uses_abort_controller(self) -> None:
        # /health 也用 AbortController，避免 hung server 卡死按钮。
        # R148 起 _fetchHealthSnapshot 把 timeout 作为第二参 timeoutMs，
        # 函数体里把 ``t = timeoutMs || PROBE_TIMEOUT_MS`` 局部缓存后
        # 调 ``setTimeout(..., t)``——锁定 PROBE_TIMEOUT_MS 仍然是默认
        # fallback 即可，不再要求 setTimeout 字面引用它。
        self.assertIn("PROBE_TIMEOUT_MS", self.js)
        self.assertRegex(
            self.js,
            r"setTimeout\(\s*function\s*\(\s*\)\s*\{[\s\S]*?controller\.abort",
        )
        # Default fallback in _fetchHealthSnapshot must reference
        # PROBE_TIMEOUT_MS so callers w/o explicit timeout still get
        # the original 5s budget (R147 contract).
        self.assertRegex(
            self.js,
            r"timeoutMs\s*>\s*0\s*\?\s*timeoutMs\s*:\s*PROBE_TIMEOUT_MS",
        )

    def test_run_probe_silent_on_null_stats(self) -> None:
        # statsByProvider === null → _setProbe(probeNode, "neutral", "")
        # 不能渲染 error（主 status 已经说 dispatch 成功了，不要再吓人）
        self.assertRegex(
            self.js,
            (
                r"statsByProvider\s*===\s*null"
                r'[\s\S]*?_setProbe\(probeNode,\s*"neutral",\s*""\)'
                r"[\s\S]*?return"
            ),
        )


# ----------------------------------------------------------------------
# Class 7: i18n locale 双语种 + pseudo 三套覆盖
# ----------------------------------------------------------------------


class TestR147I18nCoverage(unittest.TestCase):
    def test_en_has_all_r147_keys(self) -> None:
        data = _read_locale(LOCALE_EN).get("settings", {})
        for key in R147_EXPECTED_KEYS:
            self.assertIn(key, data, f"en.json 缺 settings.{key}")
            self.assertIsInstance(data[key], str)
            self.assertTrue(data[key].strip(), f"en.json settings.{key} 不能为空")

    def test_zh_cn_has_all_r147_keys(self) -> None:
        data = _read_locale(LOCALE_ZH).get("settings", {})
        for key in R147_EXPECTED_KEYS:
            self.assertIn(key, data, f"zh-CN.json 缺 settings.{key}")
            self.assertIsInstance(data[key], str)
            self.assertTrue(data[key].strip(), f"zh-CN.json settings.{key} 不能为空")

    def test_pseudo_has_all_r147_keys(self) -> None:
        data = _read_locale(LOCALE_PSEUDO).get("settings", {})
        for key in R147_EXPECTED_KEYS:
            self.assertIn(key, data, f"_pseudo/pseudo.json 缺 settings.{key}")
            self.assertIsInstance(data[key], str)

    def test_provider_success_message_has_required_placeholders(self) -> None:
        # systemTestProbeProviderSuccess 必须含 ``{{provider}}`` /
        # ``{{streak}}`` / ``{{age_seconds}}``——少一个 i18n param-signature
        # linter 就会报 ``extra=...``
        en = _read_locale(LOCALE_EN)["settings"]["systemTestProbeProviderSuccess"]
        self.assertIn("{{provider}}", en)
        self.assertIn("{{streak}}", en)
        self.assertIn("{{age_seconds}}", en)
        zh = _read_locale(LOCALE_ZH)["settings"]["systemTestProbeProviderSuccess"]
        self.assertIn("{{provider}}", zh)
        self.assertIn("{{streak}}", zh)
        self.assertIn("{{age_seconds}}", zh)

    def test_provider_failure_message_has_required_placeholders(self) -> None:
        en = _read_locale(LOCALE_EN)["settings"]["systemTestProbeProviderFailure"]
        self.assertIn("{{provider}}", en)
        self.assertIn("{{streak}}", en)
        self.assertIn("{{error_class}}", en)
        zh = _read_locale(LOCALE_ZH)["settings"]["systemTestProbeProviderFailure"]
        self.assertIn("{{provider}}", zh)
        self.assertIn("{{streak}}", zh)
        self.assertIn("{{error_class}}", zh)

    def test_provider_skipped_message_has_required_placeholders(self) -> None:
        en = _read_locale(LOCALE_EN)["settings"]["systemTestProbeProviderSkipped"]
        self.assertIn("{{provider}}", en)
        self.assertIn("{{reason}}", en)
        zh = _read_locale(LOCALE_ZH)["settings"]["systemTestProbeProviderSkipped"]
        self.assertIn("{{provider}}", zh)
        self.assertIn("{{reason}}", zh)


# ----------------------------------------------------------------------
# Class 8: state hygiene（_setProbe 设 className / 可选 neutral 分支）
# ----------------------------------------------------------------------


class TestR147SetProbeStateHygiene(unittest.TestCase):
    def setUp(self) -> None:
        self.js = _read_js()

    def test_setprobe_resets_classname(self) -> None:
        # 每次都重置 className 为基础类，避免上一次 success / error 状态
        # 残留到这次 pending
        self.assertRegex(
            self.js,
            r'node\.className\s*=\s*"setting-status-line"',
        )

    def test_setprobe_pending_variant(self) -> None:
        self.assertRegex(
            self.js,
            r'kind\s*===\s*"pending"[\s\S]*?setting-status-pending',
        )

    def test_setprobe_success_variant(self) -> None:
        self.assertRegex(
            self.js,
            r'kind\s*===\s*"success"[\s\S]*?setting-status-success',
        )

    def test_setprobe_warning_variant(self) -> None:
        # stale 走 warning 色调（黄色），区分 success（绿）/ failure（红）
        self.assertRegex(
            self.js,
            r'kind\s*===\s*"warning"[\s\S]*?setting-status-warning',
        )

    def test_setprobe_error_variant(self) -> None:
        self.assertRegex(
            self.js,
            r'kind\s*===\s*"error"[\s\S]*?setting-status-error',
        )


if __name__ == "__main__":
    unittest.main()
