"""R26.1/R452 性能不变量：Web UI cold path 不加载 ``flask_limiter``。

背景
====

``web_ui.py`` 在 R26.1 之前顶层 ``from flask_limiter import Limiter`` +
``from flask_limiter.util import get_remote_address``。``flask_limiter`` 模块本身
的 cold-start ~65 ms，但只有受限路由真正处理请求时才需要限流语义——大量「
``from web_ui import 小工具``」的单元测试（
``validate_auto_resubmit_timeout`` / ``MDNS_DEFAULT_HOSTNAME`` /
``_is_probably_virtual_interface`` 等）从来不构造 ``WebFeedbackUI``，却被迫支付
``flask_limiter`` 的加载成本。

R452 进一步把构造期的 Flask-Limiter 替换为本地 ``WebUiRateLimiter`` 兼容层，
保留 ``limit`` / ``exempt`` / ``enabled`` 运行时契约，同时让「只取小工具」和
``WebFeedbackUI`` 构造路径都不加载 ``flask_limiter``。

收益
====

- ``import web_ui`` 路径（小工具单测视角）省 ~21 ms / call（``flask_limiter``
  在 ``flask`` 已加载后增量成本约 21 ms，绝对值 65 ms 的差额是因为大量传递依
  赖如 ``werkzeug`` / ``blinker`` / ``click`` 已经被 ``flask`` 提前加载）。
- ``WebFeedbackUI.__init__`` 构造路径也不再支付 ``flask_limiter`` 成本。

不变量
======

1. **静态源码不变量**（``inspect.getsource``）：
   - 模块顶层不能有 ``from flask_limiter import Limiter`` 或
     ``from flask_limiter.util import get_remote_address``（缩进 0）。
   - ``WebFeedbackUI.__init__`` 函数体必须使用 ``WebUiRateLimiter``，且不能
     重新引入 ``flask_limiter``。

2. **运行时不变量**（fresh subprocess）：
   - ``import web_ui`` 不应让 ``flask_limiter`` 进入 ``sys.modules``。
   - ``from web_ui import validate_auto_resubmit_timeout`` 同上。

3. **行为契约**：实例化 ``WebFeedbackUI`` 后 ``self.limiter`` 必须提供 ``limit`` /
   ``exempt`` / ``enabled`` 兼容面，且受限路由保留 ``X-RateLimit-*`` 响应头。

边界
====

- ``web_ui`` 与 ``web_ui_routes/{task,feedback,static}.py`` 的类型注解也不能
  通过 ``TYPE_CHECKING`` 重新指向 ``flask_limiter.Limiter``；这些 mixin 只依赖
  本地轻量 limiter 的 ``limit`` / ``exempt`` / ``enabled`` 协议面。
- 小工具测试场景和 ``WebFeedbackUI`` 构造场景都不应加载 ``flask_limiter``。
"""

from __future__ import annotations

import inspect
import re
import subprocess
import sys
import unittest

import ai_intervention_agent.web_ui as web_ui


class TestWebUiLazyFlaskLimiterStatic(unittest.TestCase):
    """``web_ui.py`` 顶层不能再 ``from flask_limiter import ...``。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.source = inspect.getsource(web_ui)

    def test_no_top_level_flask_limiter_import(self) -> None:
        """模块顶层不能有 ``from flask_limiter ...``。"""
        for pattern_desc, pattern in (
            (
                "from flask_limiter import Limiter",
                r"^from flask_limiter import Limiter\b",
            ),
            (
                "from flask_limiter.util import get_remote_address",
                r"^from flask_limiter\.util import get_remote_address\b",
            ),
            ("import flask_limiter", r"^import flask_limiter\b"),
        ):
            with self.subTest(pattern=pattern_desc):
                self.assertIsNone(
                    re.search(pattern, self.source, re.MULTILINE),
                    f"R26.1 性能保护：web_ui 顶层禁止 ``{pattern_desc}``——"
                    "应改成本地轻量 WebUiRateLimiter 兼容层",
                )

    def test_init_uses_lightweight_limiter(self) -> None:
        """``WebFeedbackUI.__init__`` 必须使用轻量限流器，避免构造期重导入。"""
        # 用 inspect 拿 __init__ 函数体（class WebFeedbackUI 的 __init__）
        init_src = inspect.getsource(web_ui.WebFeedbackUI.__init__)

        self.assertIn("WebUiRateLimiter(", init_src)
        self.assertNotIn("from flask_limiter import Limiter", init_src)
        self.assertNotIn("from flask_limiter.util import get_remote_address", init_src)

    def test_route_mixins_type_against_local_limiter_protocol(self) -> None:
        """路由 mixin 类型面不能把 ``flask_limiter`` 带回 cold path。"""
        import pathlib

        route_dir = pathlib.Path(web_ui.__file__).parent / "web_ui_routes"
        for filename in ("task.py", "feedback.py", "static.py"):
            with self.subTest(file=filename):
                text = (route_dir / filename).read_text(encoding="utf-8")
                self.assertIn("WebUiLimiterProtocol", text)
                self.assertNotIn("from flask_limiter import Limiter", text)
                self.assertNotIn("limiter: Limiter", text)


class TestWebUiLazyFlaskLimiterRuntime(unittest.TestCase):
    """``import web_ui`` 不触发 ``flask_limiter`` 加载——subprocess 隔离验证。"""

    def _run_in_subprocess(self, code: str) -> str:
        result = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
            cwd=str(__import__("pathlib").Path(web_ui.__file__).parent),
            check=True,
        )
        return result.stdout

    def test_import_web_ui_does_not_load_flask_limiter(self) -> None:
        stdout = self._run_in_subprocess(
            'import sys; import web_ui; print("flask_limiter" in sys.modules)'
        )
        self.assertEqual(
            stdout.strip(),
            "False",
            "R26.1: ``import web_ui`` 不应触发 ``flask_limiter`` 加载（"
            "若失败请检查 web_ui.py 顶层是否有人重新加了 ``from flask_limiter ...``）",
        )

    def test_utility_import_does_not_load_flask_limiter(self) -> None:
        """``from web_ui import 小工具`` 同样不应触发 flask_limiter——这才是 R26.1
        实际收益的所在。"""
        stdout = self._run_in_subprocess(
            "import sys; from web_ui import validate_auto_resubmit_timeout; "
            'print("flask_limiter" in sys.modules)'
        )
        self.assertEqual(
            stdout.strip(),
            "False",
            "R26.1: ``from web_ui import validate_auto_resubmit_timeout`` 不应"
            "触发 flask_limiter 加载",
        )


class TestWebFeedbackUIStillUsesLimiter(unittest.TestCase):
    """构造 ``WebFeedbackUI`` 后 ``self.limiter`` 必须保留运行时契约。"""

    def test_webuiapp_limiter_surface_and_headers(self) -> None:
        """构造 WebFeedbackUI 后限流装饰器与响应头必须仍然可用。

        ``WebFeedbackUI.__init__`` 要求 ``prompt`` 位置参数，这里传一个最简的占位
        prompt 即可（不会触发任何 HTTP 路径，``init`` 只做对象组装）。
        """
        ui = web_ui.WebFeedbackUI(prompt="r26-1-test", port=0)
        self.assertTrue(
            callable(ui.limiter.limit),
            "self.limiter.limit 必须是可调用 decorator factory",
        )
        self.assertTrue(
            callable(ui.limiter.exempt),
            "self.limiter.exempt 必须是可调用 decorator",
        )
        self.assertTrue(hasattr(ui.limiter, "enabled"))

        ui.network_security_config = {"access_control_enabled": False}
        client = ui.app.test_client()
        resp = client.get("/api/config")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("X-RateLimit-Limit", resp.headers)
        self.assertIn("X-RateLimit-Remaining", resp.headers)
        self.assertIn("X-RateLimit-Reset", resp.headers)

    def test_constructing_webuiapp_does_not_load_flask_limiter(self) -> None:
        stdout = subprocess.run(
            [
                sys.executable,
                "-c",
                "import sys; from ai_intervention_agent.web_ui import WebFeedbackUI; "
                "WebFeedbackUI(prompt='r452', port=0); "
                "print('flask_limiter' in sys.modules)",
            ],
            capture_output=True,
            text=True,
            cwd=str(__import__("pathlib").Path(web_ui.__file__).parents[2]),
            check=True,
        ).stdout
        self.assertEqual(stdout.strip(), "False")


class TestWebUiRateLimiterRuntime(unittest.TestCase):
    """轻量 limiter 的本地 profile 行为边界。"""

    def test_loopback_proxy_forwarded_for_uses_distinct_buckets(self) -> None:
        ui = web_ui.WebFeedbackUI(prompt="r452-forwarded", port=0)
        ui.app.config["TESTING"] = True
        ui.network_security_config = {"access_control_enabled": False}
        client = ui.app.test_client()

        headers_a = {"X-Forwarded-For": "10.0.0.10"}
        headers_b = {"X-Forwarded-For": "10.0.0.11"}

        first = client.get(
            "/api/config",
            headers=headers_a,
            environ_base={"REMOTE_ADDR": "127.0.0.1"},
        )
        second = client.get(
            "/api/config",
            headers=headers_b,
            environ_base={"REMOTE_ADDR": "127.0.0.1"},
        )

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(
            first.headers.get("X-RateLimit-Remaining"),
            second.headers.get("X-RateLimit-Remaining"),
            "loopback reverse proxy X-Forwarded-For clients must not share one bucket",
        )

    def test_prunes_expired_buckets(self) -> None:
        from ai_intervention_agent.web_ui_rate_limiter import WebUiRateLimiter

        ui = web_ui.WebFeedbackUI(prompt="r452-prune", port=0)
        limiter = WebUiRateLimiter(app=ui.app, default_limits=[])
        limiter._buckets[("old", "127.0.0.1", "1 per second")] = (1, 1)
        limiter._buckets[("new", "127.0.0.1", "1 per hour")] = (3600, 1)

        limiter._prune_expired_buckets(4000)

        self.assertNotIn(("old", "127.0.0.1", "1 per second"), limiter._buckets)
        self.assertIn(("new", "127.0.0.1", "1 per hour"), limiter._buckets)


if __name__ == "__main__":
    unittest.main()
