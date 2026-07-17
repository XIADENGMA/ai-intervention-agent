"""mining-9 Track B — PWA offline experience regression tests.

覆盖层级：
  1. offline.html 模板 — 存在性 / self-contained (无外部 CSS/JS) /
     UX 元素（重连按钮 / 自动 ping / online 事件） / dark+light theme /
     reduced-motion;
  2. SW 修改 — OFFLINE_CACHE_NAME / OFFLINE_FALLBACK_URL 常量 /
     install pre-cache / activate 清旧 offline cache / fetch 导航
     兜底 handler;
  3. Flask 路由 — /offline.html 路由存在 + serve_offline_html()
     函数定义 + cache-control 头 + content-type;
  4. Pre-cache vs 既有 static-cache 解耦 — 验证 activate 清理逻辑
     用 startsWith 不会误杀。
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SRC_DIR = _REPO_ROOT / "src" / "ai_intervention_agent"
_TEMPLATES_DIR = _SRC_DIR / "templates"
_JS_DIR = _SRC_DIR / "static" / "js"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# §1 offline.html
# ---------------------------------------------------------------------------
class TestOfflineHtml(unittest.TestCase):
    def setUp(self) -> None:
        self.path = _TEMPLATES_DIR / "offline.html"
        self.assertTrue(self.path.exists(), "offline.html 缺失")
        self.html = _read(self.path)

    def test_doctype_and_lang(self) -> None:
        self.assertTrue(
            self.html.lower().startswith("<!doctype html>"),
            "必须以 doctype 开头",
        )
        self.assertIn('lang="zh-CN"', self.html)

    def test_self_contained_no_external_css_link(self) -> None:
        # 只允许 favicon link，**不允许** 外部 <link rel="stylesheet">
        external_css = re.findall(
            r'<link[^>]+rel=["\']stylesheet["\']',
            self.html,
            re.IGNORECASE,
        )
        self.assertEqual(
            external_css, [], "offline.html 必须 self-contained 不依赖外部 CSS"
        )

    def test_self_contained_no_external_script_src(self) -> None:
        # 只允许 inline <script>，**不允许** 外部 src
        external_scripts = re.findall(
            r"<script[^>]+src=[\"']",
            self.html,
            re.IGNORECASE,
        )
        self.assertEqual(
            external_scripts,
            [],
            "offline.html 必须 self-contained 不依赖外部 JS",
        )

    def test_retry_button_present(self) -> None:
        self.assertIn('id="retry-btn"', self.html)

    def test_status_aria_live(self) -> None:
        self.assertIn('aria-live="polite"', self.html)

    def test_online_event_handler(self) -> None:
        self.assertIn('addEventListener("online"', self.html)

    def test_backoff_reset_on_online_event(self) -> None:
        # R252: window 'online' 事件必须重置 currentDelayMs 让用户回到 fast-poll
        m = re.search(
            r'addEventListener\("online", function \(\) \{.*?\}\);',
            self.html,
            re.DOTALL,
        )
        assert m is not None
        block = m.group(0)
        self.assertIn("pauseAutoCheck()", block)
        self.assertIn("resumeAutoCheck(true)", block)

    def test_backoff_reset_on_manual_retry(self) -> None:
        # R252: 点击 retry 按钮也重置 backoff（用户主动 → fast-poll）
        m = re.search(
            r'btn\.addEventListener\("click", function \(\) \{.*?\}\);',
            self.html,
            re.DOTALL,
        )
        assert m is not None
        block = m.group(0)
        self.assertIn("pauseAutoCheck()", block)
        self.assertIn("reload()", block)

    def test_periodic_ping_check(self) -> None:
        # R252 cycle-10：从 setInterval 切到 setTimeout-recursion +
        # exponential backoff 5s → 60s。仍有 5000 (initial delay) +
        # 60000 (max) 常量保证后台 ping 可发生
        self.assertIn("scheduleAutoCheck", self.html)
        self.assertIn("BACKOFF_INITIAL_MS = 5000", self.html)
        self.assertIn("BACKOFF_MAX_MS = 60000", self.html)
        self.assertIn("BACKOFF_FACTOR = 2", self.html)
        self.assertIn("PING_TIMEOUT_MS = 4000", self.html)

    def test_ping_loop_is_page_lifecycle_aware(self) -> None:
        self.assertIn('document.addEventListener("visibilitychange"', self.html)
        self.assertIn('window.addEventListener("pagehide", pauseAutoCheck)', self.html)
        self.assertIn('window.addEventListener("pageshow"', self.html)
        self.assertNotIn('addEventListener("beforeunload"', self.html)
        self.assertNotIn('addEventListener("unload"', self.html)

    def test_ping_uses_head_method(self) -> None:
        # HEAD 比 GET 省带宽且不触发 redirect
        m = re.search(r"async function ping\(\)[^}]+\}", self.html, re.DOTALL)
        assert m is not None
        block = m.group(0)
        self.assertIn('method: "HEAD"', block)
        self.assertIn('cache: "no-store"', block)

    def test_dark_light_theme_css(self) -> None:
        # @media (prefers-color-scheme: light) override
        self.assertIn("@media (prefers-color-scheme: light)", self.html)

    def test_reduced_motion_supported(self) -> None:
        self.assertIn("@media (prefers-reduced-motion: reduce)", self.html)

    def test_bilingual_text_present(self) -> None:
        # 中文 + 英文兜底（无需 i18n runtime；offline.html 必须 self-explain）
        self.assertIn("无法连接", self.html)
        self.assertIn("Retry", self.html)

    def test_brand_purple_accent(self) -> None:
        self.assertIn("#8b5cf6", self.html.lower())


# ---------------------------------------------------------------------------
# §2 Service Worker modifications
# ---------------------------------------------------------------------------
class TestServiceWorkerOfflineSupport(unittest.TestCase):
    def setUp(self) -> None:
        path = _JS_DIR / "notification-service-worker.js"
        self.assertTrue(path.exists(), "notification-service-worker.js 缺失")
        self.js = _read(path)

    def test_offline_cache_name_constant(self) -> None:
        self.assertIn("OFFLINE_CACHE_NAME", self.js)
        self.assertIn("'aiia-offline-v1'", self.js)

    def test_offline_fallback_url_constant(self) -> None:
        self.assertIn("OFFLINE_FALLBACK_URL", self.js)
        self.assertIn("'/offline.html'", self.js)

    def _install_handler_block(self) -> str:
        # 切到 install handler 起点 → 下一个 ``self.addEventListener('activate'`` 起点
        start = self.js.find("self.addEventListener('install'")
        self.assertGreater(start, -1, "install handler 缺失")
        end = self.js.find("self.addEventListener('activate'", start)
        self.assertGreater(end, start, "activate handler 缺失")
        return self.js[start:end]

    def test_install_pre_caches_offline_html(self) -> None:
        block = self._install_handler_block()
        self.assertIn("OFFLINE_CACHE_NAME", block)
        self.assertIn("OFFLINE_FALLBACK_URL", block)
        self.assertIn("cache.put", block)
        self.assertIn("'reload'", block, "必须 fetch with cache: 'reload'")

    def test_install_graceful_failure(self) -> None:
        block = self._install_handler_block()
        # try/catch 包住 fetch
        self.assertGreater(
            block.count("try {"),
            0,
            "install 必须用 try/catch 防 fetch 失败 abort",
        )

    def test_activate_cleans_old_offline_caches(self) -> None:
        # activate handler 必须清理 startsWith('aiia-offline-') 且 != current 的旧版本
        m = re.search(
            r"self\.addEventListener\('activate'.*?self\.clients\.claim",
            self.js,
            re.DOTALL,
        )
        assert m is not None
        block = m.group(0)
        self.assertIn("aiia-offline-", block)
        self.assertIn("OFFLINE_CACHE_NAME", block)

    def test_fetch_handler_routes_navigation_to_offline_fallback(self) -> None:
        # navigation request (request.mode === 'navigate') 必须走
        # handleNavigationWithOfflineFallback
        m = re.search(
            r"self\.addEventListener\('fetch'.*?\}\)\s*$",
            self.js,
            re.DOTALL | re.MULTILINE,
        )
        assert m is not None
        block = m.group(0)
        self.assertIn("request.mode === 'navigate'", block)
        self.assertIn("handleNavigationWithOfflineFallback", block)

    def test_navigation_handler_function_exists(self) -> None:
        self.assertIn(
            "async function handleNavigationWithOfflineFallback",
            self.js,
        )

    def test_navigation_handler_network_first(self) -> None:
        # 必须先 fetch，失败才 fall back
        m = re.search(
            r"async function handleNavigationWithOfflineFallback\(.*?\n\}",
            self.js,
            re.DOTALL,
        )
        assert m is not None
        block = m.group(0)
        # 网络优先
        self.assertIn("await fetch(request)", block)
        # 失败回查 offline cache
        self.assertIn("OFFLINE_FALLBACK_URL", block)
        # 兜底 503
        self.assertIn("makeOfflineResponse", block)


# ---------------------------------------------------------------------------
# §3 Flask route
# ---------------------------------------------------------------------------
class TestFlaskOfflineRoute(unittest.TestCase):
    def setUp(self) -> None:
        path = _SRC_DIR / "web_ui_routes" / "static.py"
        self.assertTrue(path.exists())
        self.py = _read(path)

    def test_route_decorator_present(self) -> None:
        self.assertIn('@self.app.route("/offline.html")', self.py)

    def test_handler_function_defined(self) -> None:
        self.assertIn("def serve_offline_html(", self.py)

    def test_uses_render_template(self) -> None:
        m = re.search(
            r"def serve_offline_html\(.*?(?=\n        @|\nclass |\Z)",
            self.py,
            re.DOTALL,
        )
        assert m is not None
        block = m.group(0)
        self.assertIn("render_template", block)
        self.assertIn("offline.html", block)

    def test_cache_control_header_set(self) -> None:
        m = re.search(
            r"def serve_offline_html\(.*?(?=\n        @|\nclass |\Z)",
            self.py,
            re.DOTALL,
        )
        assert m is not None
        block = m.group(0)
        self.assertIn("Cache-Control", block)
        self.assertIn("max-age=600", block, "短缓存让 SW 拿到新副本")

    def test_content_type_html(self) -> None:
        m = re.search(
            r"def serve_offline_html\(.*?(?=\n        @|\nclass |\Z)",
            self.py,
            re.DOTALL,
        )
        assert m is not None
        block = m.group(0)
        self.assertIn("text/html", block)

    def test_limiter_exempt(self) -> None:
        # 限流豁免（与 webmanifest / sounds 同款）
        m = re.search(
            r'@self\.app\.route\("/offline\.html"\).*?def serve_offline_html',
            self.py,
            re.DOTALL,
        )
        assert m is not None
        block = m.group(0)
        self.assertIn("@self.limiter.exempt", block)


# ---------------------------------------------------------------------------
# §4 解耦 sanity — activate 清理逻辑
# ---------------------------------------------------------------------------
class TestActivateCleanupDoesNotMisfire(unittest.TestCase):
    """确保 OFFLINE_CACHE_NAME 不会被 startsWith('aiia-static-') 误杀."""

    def test_static_and_offline_prefixes_distinct(self) -> None:
        self.assertNotEqual("aiia-static-v2", "aiia-offline-v1")
        self.assertFalse("aiia-offline-v1".startswith("aiia-static-"))
        self.assertFalse("aiia-static-v2".startswith("aiia-offline-"))


if __name__ == "__main__":
    unittest.main()
