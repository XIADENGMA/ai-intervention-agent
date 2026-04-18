"""IG-6 噪音等级约定的「锚点回归」测试（`docs/noise-levels.zh-CN.md`）。

本文件**不**验证运行时行为，而是把规范文档 §五「现状快照」里登记的
DOM 锚点和常量，用 grep 方式在源文件里断言它们仍然存在。

目的：
- 防止未来有人改一处（例如重命名 ``toastHost``、删除 ``TOAST_DEDUPE_WINDOW_MS``）
  而忘了同步更新文档，造成文档失真。
- 任何锚点变化**必须**同时改文档（``docs/noise-levels.zh-CN.md``），
  否则 CI 红。

运行：``uv run pytest tests/test_noise_levels.py -v``
"""

from __future__ import annotations

import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
WEBVIEW_TS = REPO_ROOT / "packages" / "vscode" / "webview.ts"
WEBVIEW_UI_JS = REPO_ROOT / "packages" / "vscode" / "webview-ui.js"
WEB_UI_HTML = REPO_ROOT / "templates" / "web_ui.html"
NOISE_DOC = REPO_ROOT / "docs" / "noise-levels.zh-CN.md"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


class TestNoiseLevelAnchors(unittest.TestCase):
    """§五 现状快照 · 锚点回归（T1 - T6）。"""

    def test_t1_toast_host_has_polite_aria_live(self):
        """T1（§五.1 A1）: ``toastHost`` 容器带 ``aria-live="polite"``。"""
        if not WEBVIEW_TS.exists():
            self.skipTest("webview.ts 不存在")
        content = _read(WEBVIEW_TS)
        self.assertIn(
            'id="toastHost"',
            content,
            "webview.ts 缺少 id=toastHost（aria-live 锚点 A1）",
        )
        self.assertRegex(
            content,
            r'id="toastHost"[^>]*aria-live="polite"',
            "webview.ts 的 #toastHost 上没有 aria-live='polite'",
        )
        self.assertRegex(
            content,
            r'id="toastHost"[^>]*aria-atomic="true"',
            "webview.ts 的 #toastHost 上没有 aria-atomic='true'",
        )

    def test_t2_webview_ui_toast_uses_role_status_polite(self):
        """T2（§五.1 A2）: ``showToast`` 里 toast 元素保留 role=status + aria-live=polite。

        注意：P1 落地后会把手写 aria-live 改为仅 role='status'，那时本断言
        需要同步更新文档 §五.1 A2 和本测试。
        """
        if not WEBVIEW_UI_JS.exists():
            self.skipTest("webview-ui.js 不存在")
        content = _read(WEBVIEW_UI_JS)
        self.assertIn(
            "function showToast(",
            content,
            "webview-ui.js 缺少 showToast 函数（锚点 A2 已失真）",
        )
        self.assertIn(
            "setAttribute('role', 'status')",
            content,
            "showToast 中 toast 元素未设置 role='status'",
        )
        self.assertIn(
            "setAttribute('aria-live', 'polite')",
            content,
            "showToast 中 toast 元素未设置 aria-live='polite'",
        )

    def test_t3_web_ui_status_messages_have_aria_live(self):
        """T3（§五.1 A3/A4）: Web UI 两个 status-message 节点都带 aria-live。"""
        if not WEB_UI_HTML.exists():
            self.skipTest("templates/web_ui.html 不存在")
        content = _read(WEB_UI_HTML)
        self.assertIn(
            'id="no-content-status-message"',
            content,
            "Web UI 缺少 #no-content-status-message（锚点 A3）",
        )
        self.assertIn(
            'id="status-message"',
            content,
            "Web UI 缺少 #status-message（锚点 A4）",
        )
        count = content.count('aria-live="polite"')
        self.assertGreaterEqual(
            count,
            2,
            f"Web UI 的 aria-live='polite' 实例数 {count} < 2（期望 A3 + A4 都存在）",
        )

    def test_t4_toast_dedupe_window_constant_declared(self):
        """T4（§五.2 D1）: ``TOAST_DEDUPE_WINDOW_MS`` 常量仍声明。"""
        if not WEBVIEW_UI_JS.exists():
            self.skipTest("webview-ui.js 不存在")
        content = _read(WEBVIEW_UI_JS)
        self.assertRegex(
            content,
            r"var\s+TOAST_DEDUPE_WINDOW_MS\s*=\s*\d+",
            "webview-ui.js 未声明 TOAST_DEDUPE_WINDOW_MS 常量（锚点 D1）",
        )

    def test_t5_toast_max_visible_constant_declared(self):
        """T5（§五.2 D2）: ``TOAST_MAX_VISIBLE`` 常量仍声明。"""
        if not WEBVIEW_UI_JS.exists():
            self.skipTest("webview-ui.js 不存在")
        content = _read(WEBVIEW_UI_JS)
        self.assertRegex(
            content,
            r"var\s+TOAST_MAX_VISIBLE\s*=\s*\d+",
            "webview-ui.js 未声明 TOAST_MAX_VISIBLE 常量（锚点 D2）",
        )

    def test_t6_doc_level_matrix_keywords_present(self):
        """T6（§一 矩阵自描述）: 规范文档里三级关键词和四通道关键词都在。"""
        if not NOISE_DOC.exists():
            self.skipTest("docs/noise-levels.zh-CN.md 不存在")
        content = _read(NOISE_DOC)
        for keyword in ("critical", "important", "quiet"):
            self.assertIn(keyword, content, f"规范文档缺少级别关键词：{keyword}")
        for channel_keyword in ("aria-live", "toast", "状态栏"):
            self.assertIn(
                channel_keyword,
                content,
                f"规范文档缺少通道关键词：{channel_keyword}",
            )


if __name__ == "__main__":
    unittest.main()
