"""R56 — 静态资源缓存头一致性 + ETag/304 conditional GET 验证。

覆盖目标：

* ``add_security_headers`` after_request hook 是 ``Cache-Control`` 唯一
  权威；route 级 belt-and-suspenders 写法被 hook 覆盖时仍产出正确值；
* ``/static/locales/`` 在 R56 之前没被 hook 覆盖，本轮加进去后行为应该
  与 ``/static/js/`` / ``/static/css/`` 完全一致；
* Flask ``send_from_directory`` 默认行为：响应自带 ``ETag``，conditional
  GET（``If-None-Match`` 命中时）返回 304 Not Modified —— 这是真正"304
  无 body"流量节省的关键，缓存头只是告诉浏览器多久内可以**不发请求**，
  ETag 才是发了请求后告诉服务器**不发响应体**的机制。

设计要点：

* 不依赖具体某个 ``static/css/main.css`` 等文件存在 —— 测试夹具直接
  用 Flask test client 跑，文件不存在时也能验证 hook 仍然设了 Cache-
  Control（hook 是无条件设的）；
* 不要写"路径精确等值"（``max-age=86400``）的脆弱断言，只查"必含
  关键 token"如 ``86400`` / ``31536000`` / ``immutable``，这样未来如果
  改成 ``public, max-age=86400, must-revalidate`` 也不会无意义破坏。
"""

from __future__ import annotations

import unittest
from typing import Any


class _StaticHeaderTestBase(unittest.TestCase):
    _port: int = 19056
    _ui: Any = None
    _client: Any = None

    @classmethod
    def setUpClass(cls) -> None:
        from web_ui import WebFeedbackUI

        cls._ui = WebFeedbackUI(
            prompt="r56-static-cache-test", task_id="r56-base", port=cls._port
        )
        cls._ui.app.config["TESTING"] = True
        cls._ui.limiter.enabled = False
        cls._client = cls._ui.app.test_client()


class TestHookSetsCacheControlForJsCss(_StaticHeaderTestBase):
    """``/static/js/`` / ``/static/css/`` —— hook 覆盖 + route 级 belt-and-
    suspenders 同值，最终响应必有 Cache-Control。"""

    def test_css_no_version_one_day(self) -> None:
        resp = self._client.get("/static/css/main.css")
        cache = resp.headers.get("Cache-Control", "")
        self.assertIn(
            "86400",
            cache,
            "无 ?v= 的 CSS 应被 hook（或 route）设为 1 day = 86400s",
        )
        resp.close()

    def test_css_with_version_one_year_immutable(self) -> None:
        resp = self._client.get("/static/css/main.css?v=abc")
        cache = resp.headers.get("Cache-Control", "")
        self.assertIn("31536000", cache)
        self.assertIn("immutable", cache)
        resp.close()

    def test_js_no_version_one_day(self) -> None:
        resp = self._client.get("/static/js/app.js")
        cache = resp.headers.get("Cache-Control", "")
        self.assertIn("86400", cache)
        resp.close()

    def test_js_with_version_one_year_immutable(self) -> None:
        resp = self._client.get("/static/js/app.js?v=abc")
        cache = resp.headers.get("Cache-Control", "")
        self.assertIn("31536000", cache)
        self.assertIn("immutable", cache)
        resp.close()


class TestHookCoversLocalesR56(_StaticHeaderTestBase):
    """R56 新增：``/static/locales/`` 走与 js/css 相同的策略。

    ``language='auto'`` 模式（R20.12-B inline 优化失效）下浏览器要拉
    locales JSON，频繁切语言时旧的 1 hour 缓存会让用户每小时回源一次。
    R56 把它统一到 1 day，与其他静态资源体感一致。
    """

    def test_locales_no_version_one_day(self) -> None:
        resp = self._client.get("/static/locales/zh-CN.json")
        cache = resp.headers.get("Cache-Control", "")
        self.assertIn(
            "86400",
            cache,
            "R56 后无 ?v= 的 locales JSON 应被设为 1 day = 86400s",
        )
        resp.close()

    def test_locales_with_version_one_year_immutable(self) -> None:
        resp = self._client.get("/static/locales/zh-CN.json?v=abc")
        cache = resp.headers.get("Cache-Control", "")
        self.assertIn("31536000", cache)
        self.assertIn("immutable", cache)
        resp.close()

    def test_locales_non_json_returns_404(self) -> None:
        """白名单仍然只放行 ``.json``。"""
        resp = self._client.get("/static/locales/foo.txt")
        self.assertEqual(resp.status_code, 404)


class TestSpecialPathsKeepRouteLevelHeader(_StaticHeaderTestBase):
    """特殊端点保留 route 级 Cache-Control，hook 不命中。

    ``/manifest.webmanifest`` / ``/favicon.ico`` /
    ``/notification-service-worker.js`` 三者 hook 路径前缀不匹配，所以由
    route 级独占设置语义化值（manifest=1h、favicon=no-cache、SW=no-cache）。
    R56 应保持这一约定。
    """

    def test_manifest_keeps_one_hour(self) -> None:
        resp = self._client.get("/manifest.webmanifest")
        if resp.status_code == 200:
            cache = resp.headers.get("Cache-Control", "")
            self.assertIn("3600", cache)
        resp.close()

    def test_favicon_keeps_no_cache(self) -> None:
        resp = self._client.get("/favicon.ico")
        if resp.status_code == 200:
            cache = resp.headers.get("Cache-Control", "")
            self.assertIn("no-cache", cache)
        resp.close()

    def test_service_worker_keeps_no_cache(self) -> None:
        resp = self._client.get("/notification-service-worker.js")
        if resp.status_code == 200:
            cache = resp.headers.get("Cache-Control", "")
            self.assertIn("no-cache", cache)
        resp.close()


class TestEtagAndConditionalGet(_StaticHeaderTestBase):
    """Flask ``send_from_directory`` 默认行为：自带 ``ETag``，``If-None-Match``
    命中时返回 304 Not Modified（无 body）。

    这是真实流量节省的关键 —— ``Cache-Control: max-age=86400`` 让浏览器
    在 1 天内**不发请求**；``ETag + 304`` 让 1 天后发的请求**不下载
    body**。两者互补，缺一不可。
    """

    def test_static_resource_returns_etag(self) -> None:
        resp = self._client.get("/static/css/main.css")
        if resp.status_code == 200:
            self.assertIsNotNone(
                resp.headers.get("ETag"),
                "static 资源必须自带 ETag 才能触发 conditional GET 304",
            )
        resp.close()

    def test_conditional_get_returns_304_when_etag_matches(self) -> None:
        """先发一次正常请求拿到 ETag，再带 ``If-None-Match`` 重发，
        预期 304 Not Modified。"""
        first = self._client.get("/static/css/main.css")
        if first.status_code != 200:
            first.close()
            self.skipTest("文件不存在，conditional GET 测试不适用")
        etag = first.headers.get("ETag")
        first.close()
        if not etag:
            self.skipTest("响应无 ETag，跳过")

        second = self._client.get(
            "/static/css/main.css", headers={"If-None-Match": etag}
        )
        try:
            self.assertEqual(
                second.status_code,
                304,
                "ETag 命中时应返回 304 Not Modified（无 body）",
            )
            self.assertEqual(
                second.data,
                b"",
                "304 响应必须 body 为空（这正是流量节省点）",
            )
        finally:
            second.close()


class TestHookCoversAllStaticPrefixes(_StaticHeaderTestBase):
    """hook 各分支前缀覆盖性快速回归。"""

    def test_lottie_thirty_days_immutable(self) -> None:
        resp = self._client.get("/static/lottie/anim.json")
        cache = resp.headers.get("Cache-Control", "")
        self.assertIn("2592000", cache)
        self.assertIn("immutable", cache)
        resp.close()

    def test_fonts_thirty_days_immutable(self) -> None:
        resp = self._client.get("/fonts/test.woff2")
        cache = resp.headers.get("Cache-Control", "")
        self.assertIn("2592000", cache)
        self.assertIn("immutable", cache)
        resp.close()

    def test_sounds_one_week(self) -> None:
        resp = self._client.get("/sounds/foo.mp3")
        cache = resp.headers.get("Cache-Control", "")
        self.assertIn("604800", cache)
        resp.close()

    def test_icons_non_ico_one_week(self) -> None:
        resp = self._client.get("/icons/icon.png")
        cache = resp.headers.get("Cache-Control", "")
        self.assertIn("604800", cache)
        resp.close()


if __name__ == "__main__":
    unittest.main()
