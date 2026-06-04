"""``feat-remove-test`` 回归契约：

UI 入口移除 + 后端 API 保留（差异化锁定）。

背景
----
用户偏好："web 页面上设置页面的测试功能下的``发送系统自检通知``和``活动面板``，
这两个功能我不喜欢，请完整去除。"

历史上线分散在 R146/R147/R150（自检按钮）+ R152/R153/R155/R156（活动面板）。
feat-remove-test 把**前端 UI 与对应 JS / CSS / locale / route-bound js 版本号
全部下线**，但**后端 4 个 API endpoint 必须保留**，因为：

- ``POST /api/system/notifications/test``：CI 烟测脚本与外部健康检查仍调用；
- ``GET /api/system/health``：监控面板（Prometheus exporter / k8s liveness 等）
  以及 R59/R60 server-info 路由内部用；
- ``GET /api/system/sse-stats``：性能基线脚本 + dev 调试；
- ``GET /api/system/recent-logs``：CI 调试 + 用户支持工单时手动 curl。

本测试覆盖
----------
1. 前端 UI（HTML / CSS / locale / JS module / template version）必须**全部缺席**。
2. 后端 API 4 路必须**全部保留**，且关键 JSON 字段（``status`` / ``checks`` /
   ``entries`` / ``emit_total`` / ``stats``）不被误删。
3. 历史 R146-R156 的回归测试已被 prune，本文件作为该差异化契约的唯一锚点。
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
WEB_UI_HTML = REPO_ROOT / "src" / "ai_intervention_agent" / "templates" / "web_ui.html"
MAIN_CSS = REPO_ROOT / "src" / "ai_intervention_agent" / "static" / "css" / "main.css"
WEB_UI_PY = REPO_ROOT / "src" / "ai_intervention_agent" / "web_ui.py"
SYSTEM_PY = REPO_ROOT / "src" / "ai_intervention_agent" / "web_ui_routes" / "system.py"
NOTIFICATION_PY = (
    REPO_ROOT / "src" / "ai_intervention_agent" / "web_ui_routes" / "notification.py"
)
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
STATIC_JS_DIR = REPO_ROOT / "src" / "ai_intervention_agent" / "static" / "js"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def _strip_html_comments(src: str) -> str:
    """剥离 ``<!-- ... -->`` 注释（含跨行），便于检查"活代码"中是否引用某 ID/资源。

    我们在移除按钮时会留下解释性注释（提及历史 ID / JS 文件名），但这些
    并不会被浏览器渲染或加载，不应被回归契约误判为"未移除"。
    """
    return re.sub(r"<!--.*?-->", "", src, flags=re.DOTALL)


class TestFrontendDomRemoved(unittest.TestCase):
    """两个 setting-item 必须从模板中物理消失。"""

    def setUp(self) -> None:
        # 用"剥离注释后的活代码"做检查 —— 我们在移除处留下了解释性注释，
        # 注释里会提到历史 ID / 文件名，但浏览器不会渲染或加载它们。
        self.html = _strip_html_comments(_read(WEB_UI_HTML))

    def test_system_notification_test_button_id_absent(self) -> None:
        self.assertNotIn(
            'id="system-notification-test-btn"',
            self.html,
            "system self-test button 已按 feat-remove-test 移除，不应再出现在模板中",
        )

    def test_system_notification_test_status_id_absent(self) -> None:
        self.assertNotIn('id="system-notification-test-status"', self.html)
        self.assertNotIn('id="system-notification-test-probe"', self.html)
        self.assertNotIn('id="system-notification-test-history-toggle"', self.html)
        self.assertNotIn('id="system-notification-test-history-list"', self.html)

    def test_activity_dashboard_ids_absent(self) -> None:
        self.assertNotIn('id="activity-dashboard"', self.html)
        self.assertNotIn('id="activity-dashboard-toggle"', self.html)
        self.assertNotIn('id="activity-dashboard-body"', self.html)

    def test_no_script_tag_for_removed_modules(self) -> None:
        self.assertNotIn("notification_test_button.js", self.html)
        self.assertNotIn("activity_dashboard.js", self.html)


class TestJsModulesDeleted(unittest.TestCase):
    """两个 JS 物理文件（与所有 .min / .br / .gz 派生件）必须缺席。"""

    def test_source_modules_deleted(self) -> None:
        self.assertFalse(
            (STATIC_JS_DIR / "notification_test_button.js").exists(),
            "notification_test_button.js 应已删除",
        )
        self.assertFalse(
            (STATIC_JS_DIR / "activity_dashboard.js").exists(),
            "activity_dashboard.js 应已删除",
        )

    def test_no_build_artifacts_remain(self) -> None:
        """``.min.js`` / ``.br`` / ``.gz`` 派生件不应残留。"""
        stragglers = sorted(STATIC_JS_DIR.glob("notification_test_button*")) + sorted(
            STATIC_JS_DIR.glob("activity_dashboard*")
        )
        self.assertEqual(
            stragglers,
            [],
            f"以下构建产物应被清理：{[p.name for p in stragglers]}",
        )


class TestTemplateContextNotRegisteringRemovedVersions(unittest.TestCase):
    """``_get_template_context`` 不应再注入两个已删模块的 cache-busting 版本号。"""

    def setUp(self) -> None:
        self.py = _read(WEB_UI_PY)

    def test_notification_test_button_version_not_registered(self) -> None:
        self.assertNotRegex(
            self.py,
            r'"notification_test_button_version"\s*:',
            "template context 不应再注入 notification_test_button_version",
        )

    def test_activity_dashboard_version_not_registered(self) -> None:
        self.assertNotRegex(
            self.py,
            r'"activity_dashboard_version"\s*:',
            "template context 不应再注入 activity_dashboard_version",
        )

    def test_no_compute_file_version_for_removed_js(self) -> None:
        """避免遗留 ``_compute_file_version(str(... / "notification_test_button.js"))``
        这种本身就会 IO 报错的死代码。"""
        self.assertNotIn("notification_test_button.js", self.py)
        self.assertNotIn("activity_dashboard.js", self.py)


class TestLocalesCleanedUp(unittest.TestCase):
    """系列 ``systemTest*`` / ``activityDashboard*`` keys 必须从所有 locale 删干净。"""

    PATTERNS = (
        '"testSystemBtn"',
        '"testSystemHint"',
        '"systemTestSending"',
        '"systemTestSuccess"',
        '"systemTestNoProviders"',
        '"systemTestDisabled"',
        '"systemTestRateLimited"',
        '"systemTestUnavailable"',
        '"systemTestNetworkError"',
        '"systemTestFailed"',
        '"systemTestProbing"',
        '"systemTestProbeProviderSuccess"',
        '"systemTestProbeProviderSuccessNoAge"',
        '"systemTestProbeProviderFailure"',
        '"systemTestProbeProviderStale"',
        '"systemTestProbeProviderSkipped"',
        '"systemTestProbeProviderUnknown"',
        '"systemTestHistoryToggle"',
        '"systemTestHistoryEmpty"',
        '"systemTestHistoryAgeJustNow"',
        '"systemTestHistoryAgeSeconds"',
        '"systemTestHistoryAgeMinutes"',
        '"systemTestHistoryAgeHours"',
        '"systemTestHistoryAgeDays"',
        '"systemTestHistoryVerdictSuccess"',
        '"systemTestHistoryVerdictWarning"',
        '"systemTestHistoryVerdictError"',
        '"systemTestHistoryVerdictUnknown"',
        '"activityDashboardToggle"',
        '"activityDashboardHint"',
        '"activityDashboardRowTasks"',
        '"activityDashboardRowSse"',
        '"activityDashboardRowLatency"',
        '"activityDashboardRowNotif"',
        '"activityDashboardRowHealth"',
        '"activityDashboardRowLogs"',
        '"activityDashboardTasksValue"',
        '"activityDashboardSseValue"',
        '"activityDashboardLatencyEmpty"',
        '"activityDashboardLatencyValue"',
        '"activityDashboardNotifEmpty"',
        '"activityDashboardNotifLine"',
        '"activityDashboardHealthValue"',
        '"activityDashboardLogsValue"',
        '"activityDashboardLogsExpand"',
        '"activityDashboardLogsCollapse"',
        '"activityDashboardLogsEmpty"',
        '"activityDashboardLogsShowMore"',
        '"activityDashboardLogsShowDefault"',
    )

    def _assert_clean(self, path: Path) -> None:
        content = _read(path)
        leftovers = [pat for pat in self.PATTERNS if pat in content]
        self.assertEqual(
            leftovers,
            [],
            f"{path.name} 中残留以下已下线 key：{leftovers}",
        )

    def test_en_locale_clean(self) -> None:
        self._assert_clean(EN_LOCALE)

    def test_zh_locale_clean(self) -> None:
        self._assert_clean(ZH_LOCALE)

    def test_pseudo_locale_clean(self) -> None:
        self._assert_clean(PSEUDO_LOCALE)


class TestCssAuxClassesRemoved(unittest.TestCase):
    """``.self-test-history*`` 与 ``.activity-dashboard-*`` 选择器应已清理。"""

    def setUp(self) -> None:
        self.css = _read(MAIN_CSS)

    def test_no_self_test_history_selectors(self) -> None:
        self.assertNotRegex(
            self.css,
            r"\.self-test-history(?:[\s,{:.]|-\w)",
            "main.css 不应再有 .self-test-history* 选择器",
        )

    def test_no_activity_dashboard_selectors(self) -> None:
        self.assertNotRegex(
            self.css,
            r"\.activity-dashboard(?:[\s,{:]|-\w)",
            "main.css 不应再有 .activity-dashboard-* 选择器",
        )


class TestBackendApisPreserved(unittest.TestCase):
    """后端 4 个 API endpoint 必须仍注册 + view function 必须仍定义。"""

    def setUp(self) -> None:
        self.src = _read(SYSTEM_PY)
        self.notif_src = _read(NOTIFICATION_PY)

    def test_notifications_test_route_registered(self) -> None:
        # 注：自检 endpoint 注册在 notification.py（POST，rate-limited 6/min），
        # 见 R59/R60 mixin 划分历史。
        self.assertRegex(
            self.notif_src,
            r'@self\.app\.route\(\s*"/api/system/notifications/test"',
            "/api/system/notifications/test 必须保留 —— CI / 烟测脚本仍依赖",
        )

    def test_health_route_registered(self) -> None:
        self.assertRegex(
            self.src,
            r'@self\.app\.route\(\s*"/api/system/health"',
            "/api/system/health 必须保留 —— Prometheus / k8s probe 仍依赖",
        )

    def test_sse_stats_route_registered(self) -> None:
        self.assertRegex(
            self.src,
            r'@self\.app\.route\(\s*"/api/system/sse-stats"',
            "/api/system/sse-stats 必须保留",
        )

    def test_recent_logs_route_registered(self) -> None:
        self.assertRegex(
            self.src,
            r'@self\.app\.route\(\s*"/api/system/recent-logs"',
            "/api/system/recent-logs 必须保留",
        )


class TestBackendPayloadFieldsPreserved(unittest.TestCase):
    """关键 JSON 字段（外部脚本以及 R154 历史契约里 pin 的字段）不应被误删。

    覆盖：``status``（health）、``entries``（recent-logs）、``emit_total``
    （sse-stats）、``stats``（tasks-snapshot 内嵌字段名）。
    """

    def setUp(self) -> None:
        self.src = _read(SYSTEM_PY)

    def test_health_status_field_present(self) -> None:
        # ``"status"`` 字面量出现在 system.py 中（jsonify 或 stats_snapshot）
        self.assertRegex(
            self.src,
            r'"status"\s*:',
            "/api/system/health 必须仍含 ``status`` 字段",
        )

    def test_recent_logs_entries_field_present(self) -> None:
        self.assertIn(
            '"entries"',
            self.src,
            "/api/system/recent-logs 必须仍输出 ``entries`` 数组",
        )

    def test_sse_stats_emit_total_field_present(self) -> None:
        self.assertIn(
            '"emit_total"',
            self.src,
            "/api/system/sse-stats 必须仍含 ``emit_total`` 字段",
        )


class TestStaleHookFilesPruned(unittest.TestCase):
    """老 invariant 测试文件已 prune（保护 housekeeping 不被反向恢复）。"""

    STALE_FILES = (
        "tests/test_notification_test_button_r146.py",
        "tests/test_notification_test_button_health_followup_r147.py",
        "tests/test_notification_test_button_baseline_delta_r148.py",
        "tests/test_notification_test_button_history_r150.py",
        "tests/test_activity_dashboard_r152.py",
        "tests/test_activity_dashboard_logs_expand_r153.py",
        "tests/test_activity_dashboard_expanded_state_r155.py",
        "tests/test_activity_dashboard_logs_show_more_r156.py",
        "tests/test_housekeeping_r151.py",
        "tests/test_system_endpoint_payload_contract_r154.py",
    )

    def test_all_stale_tests_removed(self) -> None:
        present = [f for f in self.STALE_FILES if (REPO_ROOT / f).exists()]
        self.assertEqual(
            present,
            [],
            f"以下过时测试文件本应在 feat-remove-test 中 prune，仍残留：{present}",
        )


if __name__ == "__main__":
    unittest.main()
