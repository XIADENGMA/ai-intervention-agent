"""R312 invariant: Service Worker 缓存一致性三层守护 (v3.7 三层一致性 2nd app)。

背景
----
R306 (cr61) 引入 v3.7 第一个新 pattern "三层一致性 invariant", 锁了 CSP nonce
在 Python HTTP 头 + Jinja 模板 + Python ctx 注入三层的一致性, 修复了 R249
mining-9 时 offline.html 漏 nonce 的 P0 bug。

R312 是 v3.7 三层一致性 pattern 的第二次应用, 对象从 CSP nonce 切换到
**PWA Service Worker 缓存命名 + Flask SW 路由 Cache-Control + Runtime
一致性** 三层。

为什么 SW 缓存一致性容易出 silent bug
-----------------------------------
PWA Service Worker 一旦注册成功就长期驻留在浏览器, 即使 Flask 后端重启 / 升级
也不影响它。SW 自身要靠 "Flask SW route 返回的 ``Cache-Control: no-cache``"
保证浏览器每次都拉新 SW 比对, 否则:

1. SW 自身被浏览器 cache (24h+) → 旧 SW 卡 client 数天
2. SW 内 ``STATIC_CACHE_NAME = 'aiia-static-v1'`` bump 到 ``-v2`` 时, 旧 SW
   不知道新版本号, ``activate`` 阶段没法清理 → 存储泄漏
3. ``OFFLINE_FALLBACK_URL`` 与 Flask ``/offline.html`` 路由不一致 → SW
   install 阶段 fetch 失败, 离线兜底失效 (类似 R306 的 nonce 漏注)

R312 锁住的 3 层
----------------
- **Layer 1 (Python/Flask)**: ``serve_notification_service_worker`` 必须设置
  ``Cache-Control: no-cache, no-store, must-revalidate`` + ``Service-Worker-Allowed: /``
- **Layer 2 (Service Worker JS)**: ``STATIC_CACHE_NAME`` 必须匹配
  ``aiia-static-vN`` 形式, ``OFFLINE_CACHE_NAME`` 匹配 ``aiia-offline-vN``,
  ``activate`` handler 清理两类旧版本 cache 时**保留**当前版本
- **Layer 3 (Runtime via Flask test client)**: 实际请求 ``/notification-service-worker.js``
  返回的头确实是 ``no-cache, no-store, must-revalidate``;
  ``OFFLINE_FALLBACK_URL`` (``/offline.html``) 实际可访问且返回 200

pattern lineage
---------------
v3.7 三层一致性 pattern 应用历史:
- 1st: R306 (cr61) — CSP nonce (Python 头 + Jinja 模板 + Python ctx 注入)
- **2nd: R312 (cr61+2, this)** — PWA SW cache (Flask route 头 + SW JS 常量
  + Runtime 一致性)

methodology: 同 R306, 通过 Flask test client 实际发请求验证 runtime 行为,
不依赖静态源代码扫描 — runtime invariant 防 "源码看起来对但跑时不对" 类
silent bug。
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SW_JS = (
    REPO_ROOT
    / "src"
    / "ai_intervention_agent"
    / "static"
    / "js"
    / "notification-service-worker.js"
)
STATIC_PY = REPO_ROOT / "src" / "ai_intervention_agent" / "web_ui_routes" / "static.py"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


# ============================================================================
# Layer 2: Service Worker JS 常量结构
# ============================================================================


class TestServiceWorkerCacheNaming(unittest.TestCase):
    """Layer 2: SW JS 常量 ``STATIC_CACHE_NAME`` / ``OFFLINE_CACHE_NAME`` 命名规范。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.src = _read(SW_JS)

    def test_static_cache_name_matches_aiia_static_vN(self) -> None:
        """R312-L2: ``STATIC_CACHE_NAME`` 必须匹配 ``aiia-static-v\\d+`` 格式。"""
        m = re.search(
            r"""const\s+STATIC_CACHE_NAME\s*=\s*['"]([^'"]+)['"]""",
            self.src,
        )
        self.assertIsNotNone(m, "R312-L2: SW 必须含 STATIC_CACHE_NAME 常量")
        assert m is not None
        cache_name = m.group(1)
        self.assertRegex(
            cache_name,
            r"^aiia-static-v\d+$",
            f"R312-L2: STATIC_CACHE_NAME 必须匹配 'aiia-static-v\\d+', 实际 '{cache_name}'",
        )

    def test_offline_cache_name_matches_aiia_offline_vN(self) -> None:
        """R312-L2: ``OFFLINE_CACHE_NAME`` 必须匹配 ``aiia-offline-v\\d+``。"""
        m = re.search(
            r"""const\s+OFFLINE_CACHE_NAME\s*=\s*['"]([^'"]+)['"]""",
            self.src,
        )
        self.assertIsNotNone(m, "R312-L2: SW 必须含 OFFLINE_CACHE_NAME 常量")
        assert m is not None
        cache_name = m.group(1)
        self.assertRegex(
            cache_name,
            r"^aiia-offline-v\d+$",
            f"R312-L2: OFFLINE_CACHE_NAME 必须匹配 'aiia-offline-v\\d+', 实际 '{cache_name}'",
        )

    def test_offline_fallback_url_is_offline_html(self) -> None:
        """R312-L2: ``OFFLINE_FALLBACK_URL`` 必须是 ``/offline.html``。"""
        m = re.search(
            r"""const\s+OFFLINE_FALLBACK_URL\s*=\s*['"]([^'"]+)['"]""",
            self.src,
        )
        self.assertIsNotNone(m, "R312-L2: SW 必须含 OFFLINE_FALLBACK_URL 常量")
        assert m is not None
        url = m.group(1)
        self.assertEqual(
            url,
            "/offline.html",
            f"R312-L2: OFFLINE_FALLBACK_URL 必须是 '/offline.html', 实际 '{url}'",
        )


class TestServiceWorkerActivateCleanup(unittest.TestCase):
    """Layer 2: SW ``activate`` handler 必须清理两类旧版本 cache 时保留当前版本。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.src = _read(SW_JS)

    def test_activate_handler_filters_old_static_caches(self) -> None:
        """R312-L2: activate 必须 filter ``startsWith('aiia-static-')`` 旧 cache 并保留 STATIC_CACHE_NAME。"""
        # 必须出现 startsWith('aiia-static-') 模式
        self.assertRegex(
            self.src,
            r"startsWith\(\s*['\"]aiia-static-['\"]\s*\)",
            "R312-L2: activate 应 filter 'aiia-static-' 前缀",
        )
        # 必须出现 name !== STATIC_CACHE_NAME (保留当前版本)
        self.assertRegex(
            self.src,
            r"name\s*!==\s*STATIC_CACHE_NAME",
            "R312-L2: activate 应保留当前 STATIC_CACHE_NAME (即 name !== STATIC_CACHE_NAME)",
        )

    def test_activate_handler_filters_old_offline_caches(self) -> None:
        """R312-L2: activate 必须 filter ``startsWith('aiia-offline-')`` 旧 cache 并保留 OFFLINE_CACHE_NAME。"""
        self.assertRegex(
            self.src,
            r"startsWith\(\s*['\"]aiia-offline-['\"]\s*\)",
            "R312-L2: activate 应 filter 'aiia-offline-' 前缀",
        )
        self.assertRegex(
            self.src,
            r"name\s*!==\s*OFFLINE_CACHE_NAME",
            "R312-L2: activate 应保留当前 OFFLINE_CACHE_NAME",
        )

    def test_activate_handler_calls_caches_delete(self) -> None:
        """R312-L2: activate 必须实际调用 ``caches.delete()`` 清理旧 cache。"""
        self.assertRegex(
            self.src,
            r"caches\.delete\(",
            "R312-L2: activate 应调用 caches.delete() 释放旧 cache",
        )

    def test_install_handler_caches_offline_html(self) -> None:
        """R312-L2: install 必须用 OFFLINE_CACHE_NAME 预缓存 OFFLINE_FALLBACK_URL。"""
        # install 阶段必须 caches.open(OFFLINE_CACHE_NAME)
        install_section = re.search(
            r"addEventListener\(\s*['\"]install['\"][\s\S]*?addEventListener",
            self.src,
        )
        self.assertIsNotNone(install_section, "R312-L2: 应有 install 事件 handler")
        assert install_section is not None
        install_body = install_section.group(0)
        self.assertIn(
            "OFFLINE_CACHE_NAME",
            install_body,
            "R312-L2: install 阶段应使用 OFFLINE_CACHE_NAME",
        )
        self.assertIn(
            "OFFLINE_FALLBACK_URL",
            install_body,
            "R312-L2: install 阶段应预缓存 OFFLINE_FALLBACK_URL",
        )


# ============================================================================
# Layer 1: Flask SW route Cache-Control 配置 (源码级)
# ============================================================================


class TestFlaskServiceWorkerRouteConfig(unittest.TestCase):
    """Layer 1: ``serve_notification_service_worker`` 必须强制 SW 自身永远 fresh。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.src = _read(STATIC_PY)

    def test_serve_notification_service_worker_function_exists(self) -> None:
        """R312-L1: Flask 必须注册 ``serve_notification_service_worker``。"""
        self.assertRegex(
            self.src,
            r"def\s+serve_notification_service_worker\s*\(",
            "R312-L1: static.py 应定义 serve_notification_service_worker route handler",
        )

    def test_sw_route_no_cache_directive(self) -> None:
        """R312-L1: SW 路由必须设置 ``no-cache, no-store, must-revalidate``。"""
        # 提取 serve_notification_service_worker 函数体
        m = re.search(
            r"def\s+serve_notification_service_worker[\s\S]*?(?=def\s+\w|\Z)",
            self.src,
        )
        self.assertIsNotNone(
            m, "R312-L1: 未找到 serve_notification_service_worker 函数体"
        )
        assert m is not None
        body = m.group(0)
        self.assertIn(
            '"no-cache, no-store, must-revalidate"',
            body,
            "R312-L1: SW 路由必须设置 Cache-Control: no-cache, no-store, must-revalidate",
        )

    def test_sw_route_service_worker_allowed_directive(self) -> None:
        """R312-L1: SW 路由必须设置 ``Service-Worker-Allowed: /``。"""
        m = re.search(
            r"def\s+serve_notification_service_worker[\s\S]*?(?=def\s+\w|\Z)",
            self.src,
        )
        self.assertIsNotNone(m)
        assert m is not None
        body = m.group(0)
        self.assertRegex(
            body,
            r"""Service-Worker-Allowed.*['"]\s*/\s*['"]""",
            "R312-L1: SW 路由必须设置 Service-Worker-Allowed: /",
        )

    def test_offline_html_route_exists(self) -> None:
        """R312-L1: Flask 必须注册 ``serve_offline_html`` (与 SW OFFLINE_FALLBACK_URL 对齐)。"""
        self.assertRegex(
            self.src,
            r"def\s+serve_offline_html\s*\(",
            "R312-L1: static.py 应定义 serve_offline_html (SW install 预缓存目标)",
        )
        self.assertRegex(
            self.src,
            r"""@self\.app\.route\(\s*['"]/offline\.html['"]\)""",
            "R312-L1: /offline.html 路由必须注册 (与 SW OFFLINE_FALLBACK_URL 对齐)",
        )


# ============================================================================
# Layer 3: Runtime 一致性 (Flask test client 实发请求验证头)
# ============================================================================


class TestRuntimeServiceWorkerCacheConsistency(unittest.TestCase):
    """Layer 3: Flask test client 实发请求验证 SW + offline.html 头确实正确。"""

    @classmethod
    def setUpClass(cls) -> None:
        # 复用现有测试中的 WebFeedbackUI 启动方式
        from ai_intervention_agent.web_ui import WebFeedbackUI

        cls.ui = WebFeedbackUI("/tmp/r312_test_project")
        cls.client = cls.ui.app.test_client()

    def test_sw_route_returns_no_cache_header(self) -> None:
        """R312-L3 runtime: GET /notification-service-worker.js 必须返回 ``no-cache``。"""
        # 用 with 块, 让 Werkzeug 显式 close BaseResponse, 释放 SW 文件句柄
        # (否则 send_from_directory 留下 ResourceWarning, 在 pytest -W error
        # 模式或新版 pytest unraisable hook 下报 fail)
        with self.client.get("/notification-service-worker.js") as resp:
            if resp.status_code == 200:
                cache_control = resp.headers.get("Cache-Control", "")
                self.assertIn(
                    "no-cache",
                    cache_control,
                    f"R312-L3: SW 响应 Cache-Control 必须含 no-cache, 实际 '{cache_control}'",
                )
                self.assertIn(
                    "no-store",
                    cache_control,
                    f"R312-L3: SW 响应 Cache-Control 必须含 no-store, 实际 '{cache_control}'",
                )
                self.assertEqual(
                    resp.headers.get("Service-Worker-Allowed"),
                    "/",
                    "R312-L3: SW 响应必须含 Service-Worker-Allowed: /",
                )

    def test_offline_html_route_returns_200_and_short_cache(self) -> None:
        """R312-L3 runtime: GET /offline.html 必须 200 + short cache (R249 max-age=600)。"""
        with self.client.get("/offline.html") as resp:
            self.assertEqual(
                resp.status_code,
                200,
                f"R312-L3: /offline.html 必须 200 (SW install 预缓存依赖), 实际 {resp.status_code}",
            )
            cache_control = resp.headers.get("Cache-Control", "")
            self.assertIn(
                "max-age=600",
                cache_control,
                f"R312-L3: /offline.html Cache-Control 应有 max-age=600 (R249), 实际 '{cache_control}'",
            )


# ============================================================================
# Cross-layer 一致性: SW 内的 OFFLINE_FALLBACK_URL 必须等于 Flask 的 /offline.html 路由
# ============================================================================


class TestCrossLayerUrlConsistency(unittest.TestCase):
    """Cross-layer: SW JS 中 OFFLINE_FALLBACK_URL 与 Flask 路由必须字符串等价。"""

    def test_sw_offline_url_matches_flask_route_string(self) -> None:
        """R312-X: SW ``OFFLINE_FALLBACK_URL`` 字符串必须与 Flask ``/offline.html`` route 一致。"""
        sw_src = _read(SW_JS)
        py_src = _read(STATIC_PY)

        sw_match = re.search(
            r"""const\s+OFFLINE_FALLBACK_URL\s*=\s*['"]([^'"]+)['"]""",
            sw_src,
        )
        self.assertIsNotNone(sw_match)
        assert sw_match is not None
        sw_url = sw_match.group(1)

        # Flask 路由字符串
        py_match = re.search(
            r"""@self\.app\.route\(\s*['"](/offline\.html)['"]\)""",
            py_src,
        )
        self.assertIsNotNone(py_match, "R312-X: Flask /offline.html 路由必须存在")
        assert py_match is not None
        py_url = py_match.group(1)

        self.assertEqual(
            sw_url,
            py_url,
            f"R312-X: SW OFFLINE_FALLBACK_URL ('{sw_url}') 必须等于 Flask 路由 ('{py_url}')",
        )


# ============================================================================
# R312 lineage marker
# ============================================================================


class TestR312MarkerPresent(unittest.TestCase):
    """R312 lineage marker 在测试 docstring 中。"""

    def test_test_file_contains_lineage_explanation(self) -> None:
        """本测试文件 docstring 必须含 R312 + v3.7 三层一致性 lineage。"""
        src = _read(Path(__file__))
        self.assertIn("R312", src, "R312 marker 应在测试 docstring")
        self.assertIn(
            "v3.7",
            src,
            "R312 应说明 v3.7 三层一致性 lineage",
        )
        self.assertIn(
            "2nd",
            src,
            "R312 应说明这是 v3.7 三层一致性 pattern 2nd app",
        )
        self.assertIn(
            "R306",
            src,
            "R312 应引用 R306 作为 v3.7 三层一致性 1st app",
        )


if __name__ == "__main__":
    unittest.main()
