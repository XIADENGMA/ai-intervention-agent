"""CR#30 follow-up regression contracts (loop-task cycle #1):

锁住 4 个仍存活的后端路由都带有"UI 已下线"的解释性注释，以及
``docs/troubleshooting.{md,zh-CN.md}`` § 13 已迁移到"backend-only"
版本（不再误导读者期待 UI 复现路径）。

为什么把这些做成 invariant
--------------------------
``feat-remove-test`` / ``feat-remove-download`` 这类"UI 下线但 backend
保留"的 commit，最大的长期债务是：未来贡献者看到"这个 endpoint 似乎没人
用"就把它一起删了，破坏 CI / 监控 / 备份等 off-process 消费者。

CR#30 § 3.3 建议在每个保留 route 上方加 ``NOTE(feat-remove-*)`` 注释
说明谁还在用 + 删除前要 grep 哪些字符串。本测试锁住"注释必须存在
且必须引用对应的回归测试文件"，让未来 prune 路径必须先走过这层警示。

锁定的不变量
------------
1. 4 个保留 route 上方必须有 ``NOTE(feat-remove-...)`` 注释；
2. ``docs/troubleshooting.md`` § 13 必须已经标注"feat-remove-test 后"
   的状态，不再误导提及 in-app UI 行 / 设置面板；
3. 中英双版本 § 13 都必须迁移完成（双语对齐）；
4. ``docs/code-reviews/cr9.md`` 必须有"UI scope removed in
   feat-remove-test"的 backref banner，避免老 CR 误导新贡献者
   去读已下线代码。
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TASK_PY = REPO_ROOT / "src" / "ai_intervention_agent" / "web_ui_routes" / "task.py"
NOTIFICATION_PY = (
    REPO_ROOT / "src" / "ai_intervention_agent" / "web_ui_routes" / "notification.py"
)
SYSTEM_PY = REPO_ROOT / "src" / "ai_intervention_agent" / "web_ui_routes" / "system.py"
TROUBLE_EN = REPO_ROOT / "docs" / "troubleshooting.md"
TROUBLE_ZH = REPO_ROOT / "docs" / "troubleshooting.zh-CN.md"
CR9_MD = REPO_ROOT / "docs" / "code-reviews" / "cr9.md"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


class TestBackendRouteNotesPresent(unittest.TestCase):
    """每个仍存活的"UI 已下线但 backend 保留"的 route 上方都要有 NOTE 注释。"""

    def _assert_note_before_route(
        self, src: str, route: str, feat_tag: str, file_label: str
    ) -> None:
        # 找到 ``@self.app.route("<route>"``，往上回溯 ~20 行，看里面是否
        # 出现 ``NOTE(<feat_tag>)`` 字样。
        pattern = re.escape(f'@self.app.route("{route}"')
        m = re.search(pattern, src)
        self.assertIsNotNone(
            m,
            f"{file_label} 未找到 route 注册：{route}（不应被 prune）",
        )
        assert m is not None
        start = max(0, m.start() - 1200)
        preamble = src[start : m.start()]
        self.assertIn(
            f"NOTE({feat_tag}):",
            preamble,
            f"{file_label} route {route} 上方必须有 ``NOTE({feat_tag}):`` "
            "注释解释为何 UI 移除后仍保留（防止后续误 prune）",
        )

    def test_export_route_has_note(self) -> None:
        self._assert_note_before_route(
            _read(TASK_PY),
            "/api/tasks/export",
            "feat-remove-download",
            "task.py",
        )

    def test_notifications_test_route_has_note(self) -> None:
        self._assert_note_before_route(
            _read(NOTIFICATION_PY),
            "/api/system/notifications/test",
            "feat-remove-test",
            "notification.py",
        )

    def test_sse_stats_route_has_note(self) -> None:
        self._assert_note_before_route(
            _read(SYSTEM_PY),
            "/api/system/sse-stats",
            "feat-remove-test",
            "system.py",
        )

    def test_health_route_has_note(self) -> None:
        self._assert_note_before_route(
            _read(SYSTEM_PY),
            "/api/system/health",
            "feat-remove-test",
            "system.py",
        )

    def test_recent_logs_route_has_note(self) -> None:
        self._assert_note_before_route(
            _read(SYSTEM_PY),
            "/api/system/recent-logs",
            "feat-remove-test",
            "system.py",
        )


class TestTroubleshootingDocsMigrated(unittest.TestCase):
    """``docs/troubleshooting.*`` § 13 必须已经迁移到"backend-only"框架。"""

    def test_en_doc_has_status_note(self) -> None:
        content = _read(TROUBLE_EN)
        self.assertIn(
            "feat-remove-test",
            content,
            "docs/troubleshooting.md § 13 必须标注 feat-remove-test 后的状态",
        )
        # 不应再让读者去跑已删除的 R154 测试文件
        self.assertNotIn(
            "tests/test_system_endpoint_payload_contract_r154.py",
            content,
            "§ 13 不应再引导读者跑已删除的 R154 测试文件",
        )

    def test_zh_doc_has_status_note(self) -> None:
        content = _read(TROUBLE_ZH)
        self.assertIn(
            "feat-remove-test",
            content,
            "docs/troubleshooting.zh-CN.md § 13 必须标注 feat-remove-test 后的状态",
        )
        self.assertNotIn(
            "tests/test_system_endpoint_payload_contract_r154.py",
            content,
            "§ 13 不应再引导读者跑已删除的 R154 测试文件",
        )

    def test_en_doc_no_longer_promises_ui_repro(self) -> None:
        """§ 13 不应再用"Activity Dashboard's Recent logs row stays '—'"
        这种 UI 复现路径作为主症状（UI 已不存在）。"""
        content = _read(TROUBLE_EN)
        # 整段连续 UI 文案不应再作为"症状"列表项出现
        self.assertNotRegex(
            content,
            r"-\s+The\s+Activity\s+Dashboard's\s+`Recent\s+logs`\s+row\s+stays",
            "§ 13 不应再以 Activity Dashboard UI 行作为复现症状",
        )

    def test_zh_doc_no_longer_promises_ui_repro(self) -> None:
        content = _read(TROUBLE_ZH)
        self.assertNotRegex(
            content,
            r"-\s+Activity\s+Dashboard\s+的「近期日志」行一直显示",
            "§ 13 不应再以 Activity Dashboard UI 行作为复现症状",
        )


class TestCr9HasBackrefBanner(unittest.TestCase):
    """``docs/code-reviews/cr9.md`` 必须有"UI scope removed"backref。"""

    def test_cr9_banner_present(self) -> None:
        content = _read(CR9_MD)
        self.assertIn(
            "feat-remove-test",
            content,
            "cr9.md 必须有 feat-remove-test 的 backref banner",
        )
        self.assertIn(
            "Historical context",
            content,
            "cr9.md banner 应明确标注为 historical context（避免误读为现状）",
        )

    def test_cr9_banner_references_post_removal_test_file(self) -> None:
        content = _read(CR9_MD)
        self.assertIn(
            "tests/test_feat_remove_test_uis_removed.py",
            content,
            "cr9.md banner 应指向 feat-remove-test 的回归契约文件",
        )


if __name__ == "__main__":
    unittest.main()
