"""R714（TODO#43）：Cursor / VS Code 内置浏览器（Electron webview）
通知修复回归护栏。

背景：Electron webview / WebContentsView 中，Service Worker 的
``showNotification()`` 常见**静默失败**——Promise resolve 但系统通知
不显示（electron#13041 / #10146）。旧实现把 resolve 当成功，不再尝试
页面级 ``new Notification()``，通知因此丢失（页面级构造在 Electron
中会转主进程原生通知，支持良好）。

修复的两层防线（``notification-manager.js`` ``showSystemNotification``）：
1. UA 探测：``isElectronHost()`` 命中（UA 含 ``Electron/``）→ 跳过 SW
   路径直接页面级；
2. 运行时验证：SW ``showNotification`` resolve 后用
   ``getNotifications({tag})`` 回查——查不到视为静默丢弃，回退页面级。
   查询异常时保守视为成功，不改变正常浏览器（含依赖 SW 通知的
   Android Chrome）的行为。

本护栏为字面 invariant 测试：锁定两层防线的存在与关键行为特征，
防止未来重构把回退链路精简掉。
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
NM_JS = (
    REPO_ROOT
    / "src"
    / "ai_intervention_agent"
    / "static"
    / "js"
    / "notification-manager.js"
)


class TestElectronHostDetection(unittest.TestCase):
    src = NM_JS.read_text(encoding="utf-8")

    def test_detector_defined(self) -> None:
        self.assertIn("isElectronHost()", self.src)
        self.assertIn(r"/\bElectron\//i.test(navigator.userAgent)", self.src)

    def test_detector_fail_safe(self) -> None:
        """UA 读取异常时返回 false（按普通浏览器处理，不激进跳过 SW）。"""
        m = re.search(r"isElectronHost\(\)\s*\{([\s\S]*?)\n  \}", self.src)
        self.assertIsNotNone(m)
        assert m is not None
        self.assertIn("return false", m.group(1))


class TestShowSystemNotificationFallbackChain(unittest.TestCase):
    src = NM_JS.read_text(encoding="utf-8")

    def _body(self) -> str:
        m = re.search(
            r"async showSystemNotification\(title, notificationOptions, options = \{\}\)\s*\{"
            r"([\s\S]*?)\n  \}\n",
            self.src,
        )
        assert m is not None, "未找到 showSystemNotification"
        return m.group(1)

    def test_electron_skips_service_worker_path(self) -> None:
        body = self._body()
        self.assertIn("this.isElectronHost()", body)
        self.assertIn("skipServiceWorkerPath", body)
        # Electron 命中时 registration 必须为 null（跳过 SW 注册/展示）
        self.assertRegex(body, r"skipServiceWorkerPath\s*\?\s*null")

    def test_runtime_verification_via_get_notifications(self) -> None:
        """SW resolve 后必须回查 getNotifications({tag}) 验证真实显示。"""
        body = self._body()
        self.assertIn("getNotifications", body)
        self.assertIn("tag: notificationOptions.tag", body)

    def test_verification_failure_falls_back_to_page_notification(self) -> None:
        """回查为空 → 不 return，落到页面级 new Notification 路径。"""
        body = self._body()
        self.assertIn("silently dropped", body)
        # 页面级构造仍然存在（回退目的地）
        self.assertIn("new Notification(title, notificationOptions)", body)

    def test_verification_exception_treated_as_success(self) -> None:
        """getNotifications 本身异常 → displayed 保守置 true，
        防止 Android Chrome 等 SW-only 平台被误回退（页面级构造在
        Android 上会抛 TypeError）。"""
        body = self._body()
        self.assertRegex(
            body,
            r"catch \(_e\) \{\s*displayed = true",
        )


if __name__ == "__main__":
    unittest.main()
