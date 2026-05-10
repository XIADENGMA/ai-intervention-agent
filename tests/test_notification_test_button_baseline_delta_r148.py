"""R148 — Notification self-test button: baseline-delta probe (root-cause fix for R147 false-success window).

R147 closed half the loop: after a successful R141 dispatch the button
probes ``/api/system/health`` and reports a per-provider verdict.  But
the verdict was age-only — *"if the freshest of last_success_age and
last_failure_age is < 10s, classify as success/failure based on which
is fresher"*.  That logic has a sneaky failure mode:

    1. User clicks the button — dispatch completes successfully at T=0.
       ``last_success_age`` becomes 0.
    2. Eight seconds later (T=8s) the user clicks again.  Before this
       second dispatch reaches the (possibly slow) Bark provider,
       the probe runs at T=8s+1.5s=9.5s.
    3. ``last_success_age = 9.5s`` is still < 10s threshold → probe
       reports "delivered (9.5s ago, streak=N)".
    4. But the streak / last_success_at it's reading came from the
       FIRST click; the SECOND dispatch hasn't actually completed
       yet.  User thinks "great, my second click worked" but it
       hasn't — they may have been Bark-rate-limited or hitting a
       transient 5xx that gets retried on the next dispatch.

R148 root-causes this by switching to **delta-based** classification:

    1. Take a *baseline* snapshot of per_provider stats **before**
       posting the dispatch (separate /health GET, 1s tight timeout).
    2. Post the dispatch.
    3. Wait PROBE_DELAY_MS, take *current* snapshot.
    4. For each provider in providers_dispatched:
        - if current.success_streak > baseline.success_streak → success
          (this dispatch advanced the streak — reliable)
        - if current.failure_streak > baseline.failure_streak → failure
        - neither delta → "stale" (dispatch hasn't completed yet —
          retry, don't lie about delivery)

The baseline-delta path works because each event resets the *opposite*
streak (success → failure_streak=0; failure → success_streak=0), so a
single dispatch always increments exactly one streak counter by exactly
one.  Comparing ``current > baseline`` is therefore a reliable
"did exactly one event happen between baseline and current?" signal.

If the baseline fetch fails (network down / /health 5xx / timeout), we
**fall back** to the R147 age-only path so R147's contract isn't broken.
That fallback is silently activated; the user still gets a verdict, just
one with the original false-success window.

Constraints / invariants (covered classes):

1.  **常量值锁定** — BASELINE_TIMEOUT_MS = 1s (>= 500ms, <= 2s);
    ALL_KNOWN_PROVIDERS == 4-tuple matching server's
    ``_HEALTH_PER_PROVIDER_KEYS``.
2.  **API 函数签名** — ``_fetchHealthSnapshot`` 接受 (providers,
    timeoutMs); ``_classifyProviderVerdict`` 接受可选第二参 ``baselineStats``;
    ``_runProbe`` 接受可选第三参 ``baseline``; ``triggerSelfTest`` dispatch
    前调 ``_fetchHealthSnapshot(ALL_KNOWN_PROVIDERS, BASELINE_TIMEOUT_MS)``。
3.  **delta 分支** — ``baseline + current`` 同时存在时:
    success_streak 增 → success / failure_streak 增 → failure /
    都不变 → stale。``verdict.source === "delta"`` 标识。
4.  **R147 fallback 不破** — ``baselineStats === null`` → 走原 R147 age-only
    决策树；``verdict.source === "age"`` 标识。
5.  **baseline 抓取超时分流** — BASELINE_TIMEOUT_MS 与 PROBE_TIMEOUT_MS 分别
    可配；baseline 失败 → null → R147 fallback；不影响 dispatch 路径。
6.  **i18n 增量** — systemTestProbeProviderSuccessNoAge key 在
    en + zh-CN + _pseudo 三套全覆盖；含 ``{{provider}}`` / ``{{streak}}`` 占位符。
7.  **module export 增量** — ``_fetchHealthSnapshot`` /
    ``BASELINE_TIMEOUT_MS`` / ``ALL_KNOWN_PROVIDERS`` 暴露在
    ``window.AIIA_NOTIFICATION_TEST_BUTTON``。
8.  **R147 backwards-compat** — ``_probeHealthForProviders`` 仍然存在并 delegate
    到 ``_fetchHealthSnapshot`` (避免外部 caller / R147 测试断裂)。
"""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JS_PATH = ROOT / "src/ai_intervention_agent/static/js/notification_test_button.js"
LOCALE_ZH = ROOT / "src/ai_intervention_agent/static/locales/zh-CN.json"
LOCALE_EN = ROOT / "src/ai_intervention_agent/static/locales/en.json"
LOCALE_PSEUDO = ROOT / "src/ai_intervention_agent/static/locales/_pseudo/pseudo.json"


def _read_js() -> str:
    return JS_PATH.read_text(encoding="utf-8")


def _read_locale(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


# ----------------------------------------------------------------------
# Class 1: 常量值锁定
# ----------------------------------------------------------------------


class TestR148ConstantsLocked(unittest.TestCase):
    def setUp(self) -> None:
        self.js = _read_js()

    def test_baseline_timeout_constant_reasonable(self) -> None:
        # 1 * 1000ms：实测本地 /health RTT ~10ms；1s tight timeout 让基线
        # 抓取永远不会拖累 user-visible dispatch 超过 1s。<500ms 太紧（紧
        # 张网下抓不到），>2s 太松（违背"基线不能 stall dispatch"原则）。
        m = re.search(r"BASELINE_TIMEOUT_MS\s*=\s*(\d+)\s*\*\s*1000", self.js)
        self.assertIsNotNone(m, "缺 BASELINE_TIMEOUT_MS 常量（须 = N * 1000）")
        assert m is not None
        v = int(m.group(1))
        self.assertGreaterEqual(v, 1, "BASELINE_TIMEOUT_MS 太短（< 1s）")
        self.assertLessEqual(v, 2, "BASELINE_TIMEOUT_MS 太长（> 2s）")

    def test_all_known_providers_constant_matches_server(self) -> None:
        # 必须与 server-side ``_HEALTH_PER_PROVIDER_KEYS`` 严格一致：
        # 顺序无所谓，但 set 必须 = {bark, web, sound, system}
        m = re.search(
            r"ALL_KNOWN_PROVIDERS\s*=\s*\[([^\]]+)\]",
            self.js,
        )
        self.assertIsNotNone(m, "缺 ALL_KNOWN_PROVIDERS 常量")
        assert m is not None
        items = re.findall(r'"(\w+)"', m.group(1))
        self.assertEqual(
            set(items),
            {"bark", "web", "sound", "system"},
            "ALL_KNOWN_PROVIDERS 必须 = {bark, web, sound, system}（与 server "
            "_HEALTH_PER_PROVIDER_KEYS 一致）",
        )


# ----------------------------------------------------------------------
# Class 2: API 函数签名
# ----------------------------------------------------------------------


class TestR148ApiSignatures(unittest.TestCase):
    def setUp(self) -> None:
        self.js = _read_js()

    def test_fetch_health_snapshot_function_present(self) -> None:
        self.assertRegex(
            self.js,
            r"async\s+function\s+_fetchHealthSnapshot\s*\(\s*providers\s*,"
            r"\s*timeoutMs\s*\)",
        )

    def test_classify_verdict_takes_optional_baseline(self) -> None:
        # 必须接受第二参 baselineStats（可选；null → fallback）
        self.assertRegex(
            self.js,
            r"function\s+_classifyProviderVerdict\s*\(\s*stats\s*,\s*baselineStats\s*\)",
        )

    def test_run_probe_takes_optional_baseline(self) -> None:
        # _runProbe(providers, probeNode, baseline)
        self.assertRegex(
            self.js,
            r"async\s+function\s+_runProbe\s*\(\s*providers\s*,\s*probeNode\s*,"
            r"\s*baseline\s*\)",
        )

    def test_probe_health_for_providers_delegates(self) -> None:
        # backwards-compat alias 必须保留并 delegate
        self.assertRegex(
            self.js,
            r"function\s+_probeHealthForProviders\s*\(\s*providers\s*\)"
            r"\s*\{\s*return\s+_fetchHealthSnapshot\(\s*providers\s*,"
            r"\s*PROBE_TIMEOUT_MS\s*\)",
        )


# ----------------------------------------------------------------------
# Class 3: delta 分支
# ----------------------------------------------------------------------


class TestR148DeltaBranches(unittest.TestCase):
    def setUp(self) -> None:
        self.js = _read_js()

    def test_baseline_present_branch_isolated(self) -> None:
        # 必须有 ``if (baselineStats && typeof baselineStats === "object")`` 分支
        self.assertRegex(
            self.js,
            r'if\s*\(\s*baselineStats\s*&&\s*typeof\s+baselineStats\s*===\s*"object"\s*\)',
        )

    def test_success_delta_branch(self) -> None:
        # current.success_streak - baseline.success_streak > 0 → success
        # source 必须打 "delta" 标识（让测试 / debug 知道走了哪条路径）
        self.assertRegex(
            self.js,
            (
                r"deltaSucc\s*=\s*successStreak\s*-\s*bSucc"
                r"[\s\S]*?deltaSucc\s*>\s*0"
                r'[\s\S]*?kind:\s*"success"'
                r'[\s\S]*?source:\s*"delta"'
            ),
        )

    def test_failure_delta_branch(self) -> None:
        self.assertRegex(
            self.js,
            (
                r"deltaFail\s*=\s*failureStreak\s*-\s*bFail"
                r"[\s\S]*?deltaFail\s*>\s*0"
                r'[\s\S]*?kind:\s*"failure"'
                r'[\s\S]*?source:\s*"delta"'
            ),
        )

    def test_stale_branch_when_no_delta(self) -> None:
        # 都没增 → kind: "stale", source: "delta"
        self.assertRegex(
            self.js,
            r'kind:\s*"stale"[\s\S]*?source:\s*"delta"',
        )

    def test_baseline_streak_normalisation(self) -> None:
        # 防御性 parseInt + isFinite fallback 0
        self.assertIn("isFinite(bSucc)", self.js)
        self.assertIn("isFinite(bFail)", self.js)


# ----------------------------------------------------------------------
# Class 4: R147 fallback path 不破
# ----------------------------------------------------------------------


class TestR148R147FallbackPreserved(unittest.TestCase):
    def setUp(self) -> None:
        self.js = _read_js()

    def test_age_only_fallback_present(self) -> None:
        # 只要 baselineStats 缺席（null / undefined），就走 R147 age-only
        # 决策树（freshest min, lastWas decision）
        self.assertRegex(
            self.js,
            r"freshest\s*===\s*null\s*\|\|\s*freshest\s*>\s*PROBE_STALE_THRESHOLD_S",
        )

    def test_age_only_marks_source(self) -> None:
        # source: "age" 标识（与 delta 分支的 "delta" 互斥）
        self.assertRegex(
            self.js,
            r'kind:\s*"stale"[\s\S]*?source:\s*"age"',
        )
        self.assertRegex(
            self.js,
            r'kind:\s*"success"[\s\S]*?source:\s*"age"',
        )
        self.assertRegex(
            self.js,
            r'kind:\s*"failure"[\s\S]*?source:\s*"age"',
        )

    def test_skipped_branch_works_for_both_paths(self) -> None:
        # last_error_class === "not_registered" → skipped
        # （不论 baseline 有无）
        self.assertRegex(
            self.js,
            (
                r'lastErrorClass\s*===\s*"not_registered"'
                r'[\s\S]*?kind:\s*"skipped"'
            ),
        )


# ----------------------------------------------------------------------
# Class 5: baseline 抓取超时分流 + dispatch 路径接入
# ----------------------------------------------------------------------


class TestR148BaselineWiring(unittest.TestCase):
    def setUp(self) -> None:
        self.js = _read_js()

    def test_baseline_fetched_before_dispatch(self) -> None:
        # triggerSelfTest 在 fetch(ENDPOINT, ...) **之前** 必须已经
        # 调用了 _fetchHealthSnapshot(ALL_KNOWN_PROVIDERS, BASELINE_TIMEOUT_MS)
        idx_baseline = self.js.find(
            "_fetchHealthSnapshot(\n        ALL_KNOWN_PROVIDERS"
        )
        if idx_baseline < 0:
            # 容错：单行 / 不同换行下也能匹配
            m = re.search(
                r"_fetchHealthSnapshot\(\s*ALL_KNOWN_PROVIDERS\s*,\s*BASELINE_TIMEOUT_MS\s*\)",
                self.js,
            )
            self.assertIsNotNone(
                m,
                "triggerSelfTest 必须调 _fetchHealthSnapshot(ALL_KNOWN_PROVIDERS, "
                "BASELINE_TIMEOUT_MS) 取 baseline",
            )
            assert m is not None
            idx_baseline = m.start()
        idx_dispatch = self.js.find("fetch(ENDPOINT")
        self.assertGreater(idx_dispatch, idx_baseline, "baseline 必须先于 dispatch")

    def test_baseline_passed_to_run_probe(self) -> None:
        # _runProbe 收到 baseline 作为第三参
        self.assertRegex(
            self.js,
            r"_runProbe\(\s*body\.providers_dispatched\s*,\s*probeNode\s*,\s*baseline\s*\)",
        )

    def test_baseline_skip_when_no_probe_node(self) -> None:
        # 如果 probeNode === null（用户的 DOM 里 R147 div 还没渲染），
        # 不必要花 baseline RTT；直接走原 R146 路径
        self.assertRegex(
            self.js,
            r"if\s*\(\s*probeNode\s*\)\s*\{\s*baseline\s*=\s*await\s+_fetchHealthSnapshot",
        )


# ----------------------------------------------------------------------
# Class 6: i18n 增量 — systemTestProbeProviderSuccessNoAge
# ----------------------------------------------------------------------


class TestR148I18nNoAgeKey(unittest.TestCase):
    KEY = "systemTestProbeProviderSuccessNoAge"

    def test_en_has_key_with_placeholders(self) -> None:
        en = _read_locale(LOCALE_EN)["settings"]
        self.assertIn(self.KEY, en, f"en.json 缺 settings.{self.KEY}")
        v = en[self.KEY]
        self.assertIsInstance(v, str)
        self.assertIn("{{provider}}", v)
        self.assertIn("{{streak}}", v)
        # **必须 NOT** 含 {{age_seconds}}（这是 NoAge 变体）
        self.assertNotIn("{{age_seconds}}", v)

    def test_zh_cn_has_key_with_placeholders(self) -> None:
        zh = _read_locale(LOCALE_ZH)["settings"]
        self.assertIn(self.KEY, zh)
        v = zh[self.KEY]
        self.assertIn("{{provider}}", v)
        self.assertIn("{{streak}}", v)
        self.assertNotIn("{{age_seconds}}", v)

    def test_pseudo_has_key(self) -> None:
        ps = _read_locale(LOCALE_PSEUDO).get("settings", {})
        self.assertIn(self.KEY, ps)


# ----------------------------------------------------------------------
# Class 7: module export 增量
# ----------------------------------------------------------------------


class TestR148ModuleExport(unittest.TestCase):
    def setUp(self) -> None:
        self.js = _read_js()

    def test_window_exports_baseline_helpers(self) -> None:
        for name in (
            "BASELINE_TIMEOUT_MS",
            "ALL_KNOWN_PROVIDERS",
            "_fetchHealthSnapshot",
        ):
            self.assertIn(
                name + ":",
                self.js,
                f"window.AIIA_NOTIFICATION_TEST_BUTTON 必须 export {name}",
            )

    def test_window_keeps_r147_helpers(self) -> None:
        # R147 的 _probeHealthForProviders 必须保留为 alias
        for name in (
            "_probeHealthForProviders",
            "_classifyProviderVerdict",
            "_runProbe",
        ):
            self.assertIn(name + ":", self.js)


# ----------------------------------------------------------------------
# Class 8: R147 backwards-compat — _probeHealthForProviders 不能消失
# ----------------------------------------------------------------------


class TestR148R147BackwardsCompat(unittest.TestCase):
    def setUp(self) -> None:
        self.js = _read_js()

    def test_probe_health_for_providers_is_thin_delegate(self) -> None:
        # 不能再有第二份独立实现；必须只是 _fetchHealthSnapshot 的 alias
        # （函数体只剩 return _fetchHealthSnapshot(providers, PROBE_TIMEOUT_MS)）
        m = re.search(
            r"function\s+_probeHealthForProviders\s*\(\s*providers\s*\)\s*\{([^}]+)\}",
            self.js,
        )
        self.assertIsNotNone(m, "_probeHealthForProviders 函数必须存在")
        assert m is not None
        body = m.group(1).strip()
        self.assertIn("_fetchHealthSnapshot", body)
        self.assertIn("PROBE_TIMEOUT_MS", body)
        # 不允许保留 fetch / try-catch / etc.（那是 _fetchHealthSnapshot 的事）
        self.assertNotIn("fetch(", body)
        self.assertNotIn("AbortController", body)


if __name__ == "__main__":
    unittest.main()
