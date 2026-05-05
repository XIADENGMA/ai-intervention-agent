"""R23.3 · ``flasgger.Swagger`` 改成 env-gated opt-in 的契约测试

背景
----
``web_ui.py`` 模块顶部之前写着 ``from flasgger import Swagger`` —— 这一行
在 macOS / Python 3.11 上是 74-78 ms 的同步 import 成本（pulls in
``flasgger.base``、``jsonschema`` 验证器图、``mistune`` 渲染器、
``yaml.SafeLoader`` 等），加上 ``Swagger(app, template=...)`` 实例化又
0.5 ms。这 75 ms 全部阻塞在 web_ui 子进程的 main thread 上，直接出现在
「AI agent 调 ``interactive_feedback`` → 浏览器能打开页面」的用户感知
延迟里。

R23.3 把 Swagger UI 改成 opt-in：
- 默认 ``AI_AGENT_ENABLE_SWAGGER`` 未设置或非 truthy → web_ui 子进程完全
  不 import flasgger，``/apidocs/`` 由轻量级 HTML 提示页面接管。
- ``AI_AGENT_ENABLE_SWAGGER=1`` (或 ``true`` / ``yes`` / ``on``，大小写不
  敏感) → ``__init__`` 同步 import flasgger + 实例化 Swagger，``/apidocs/``
  与启用前完全一致。

本测试覆盖：

1.  **truthy 解析**：``_is_swagger_enabled_via_env`` 对各种取值的判断符
    合 ``{"1", "true", "yes", "on"}`` 大小写不敏感 / strip 的契约。
2.  **默认禁用路径**：未设置环境变量时，``WebFeedbackUI()`` 不会触发
    flasgger import，``/apidocs/`` 注册的是 fallback handler。
3.  **fallback HTML 内容契约**：禁用时 ``GET /apidocs/`` 返回 200，含
    `AI_AGENT_ENABLE_SWAGGER=1` 字面量与 GitHub URL，``Content-Type``
    是 ``text/html; charset=utf-8``。
4.  **启用路径**：env=1 时 ``WebFeedbackUI()`` 真的实例化 Swagger，
    ``/apidocs/`` / ``/apispec_1.json`` / ``/flasgger_static/<path>``
    都被注册到 url_map。
5.  **源码契约**：``web_ui.py`` 模块顶部不再 ``from flasgger import
    Swagger``（regex 检查），``_init_swagger_lazy`` 内含 lazy import。
6.  **文档契约**：模块 docstring / 类 attribute / 注释中含 ``R23.3``
    与启用方式说明。
"""

from __future__ import annotations

import os
import re
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parent.parent
WEB_UI_PY = REPO_ROOT / "web_ui.py"


# ---------------------------------------------------------------------------
# 1. truthy 解析
# ---------------------------------------------------------------------------


class TestEnvTruthyParsing(unittest.TestCase):
    """``_is_swagger_enabled_via_env`` 接受的 truthy 取值集合。"""

    @staticmethod
    def _check(value: str | None) -> bool:
        from web_ui import _is_swagger_enabled_via_env

        env = {**os.environ}
        env.pop("AI_AGENT_ENABLE_SWAGGER", None)
        if value is not None:
            env["AI_AGENT_ENABLE_SWAGGER"] = value
        with patch.dict(os.environ, env, clear=True):
            return _is_swagger_enabled_via_env()

    def test_unset_env_disables(self) -> None:
        self.assertFalse(self._check(None))

    def test_empty_string_disables(self) -> None:
        self.assertFalse(self._check(""))

    def test_zero_disables(self) -> None:
        self.assertFalse(self._check("0"))

    def test_false_disables(self) -> None:
        self.assertFalse(self._check("false"))
        self.assertFalse(self._check("FALSE"))

    def test_one_enables(self) -> None:
        self.assertTrue(self._check("1"))

    def test_true_enables(self) -> None:
        self.assertTrue(self._check("true"))
        self.assertTrue(self._check("TRUE"))
        self.assertTrue(self._check("True"))

    def test_yes_enables(self) -> None:
        self.assertTrue(self._check("yes"))
        self.assertTrue(self._check("YES"))

    def test_on_enables(self) -> None:
        self.assertTrue(self._check("on"))
        self.assertTrue(self._check("ON"))

    def test_strips_whitespace_then_evaluates(self) -> None:
        self.assertTrue(self._check("  1  "))
        self.assertTrue(self._check("\t true \n"))

    def test_unknown_string_disables(self) -> None:
        self.assertFalse(self._check("enabled"))
        self.assertFalse(self._check("yep"))
        self.assertFalse(self._check("y"))


# ---------------------------------------------------------------------------
# 2. 默认禁用路径
# ---------------------------------------------------------------------------


class TestDefaultDisabledPath(unittest.TestCase):
    """未设置环境变量时不应触发 flasgger import。"""

    def setUp(self) -> None:
        # 清掉 sys.modules 里已有的 flasgger / web_ui，确保每次测都是 fresh import
        # 注意：这里只 pop 而不重 import，避免影响测试间的状态
        import sys

        def _pop_flasgger() -> None:
            sys.modules.pop("flasgger", None)

        self.addCleanup(_pop_flasgger)

    def _make_ui(self):
        from web_ui import WebFeedbackUI

        # port 取一个不太可能冲突的高端口；__init__ 不会真的 listen
        return WebFeedbackUI(prompt="r23.3 test", host="127.0.0.1", port=18099)

    def test_disabled_does_not_import_flasgger(self) -> None:
        import sys

        sys.modules.pop("flasgger", None)

        env = {**os.environ}
        env.pop("AI_AGENT_ENABLE_SWAGGER", None)
        with patch.dict(os.environ, env, clear=True):
            self._make_ui()

        self.assertNotIn(
            "flasgger",
            sys.modules,
            "禁用 Swagger 时不应 import flasgger",
        )

    def test_disabled_registers_fallback_apidocs_route(self) -> None:
        env = {**os.environ}
        env.pop("AI_AGENT_ENABLE_SWAGGER", None)
        with patch.dict(os.environ, env, clear=True):
            ui = self._make_ui()

        endpoints = {rule.endpoint for rule in ui.app.url_map.iter_rules()}
        self.assertIn("swagger_disabled_apidocs", endpoints)
        # 不应出现 flasgger 的 endpoint 名（pre-fix 是 ``flasgger.apidocs``）
        flasgger_endpoints = {ep for ep in endpoints if ep.startswith("flasgger")}
        self.assertEqual(
            flasgger_endpoints,
            set(),
            f"禁用时不应注册 flasgger 端点，实际：{flasgger_endpoints}",
        )


# ---------------------------------------------------------------------------
# 3. fallback HTML 内容契约
# ---------------------------------------------------------------------------


class TestFallbackHtmlBody(unittest.TestCase):
    """禁用时 ``GET /apidocs/`` 返回的 HTML 提示页面契约。"""

    def setUp(self) -> None:
        env = {**os.environ}
        env.pop("AI_AGENT_ENABLE_SWAGGER", None)
        self._env_patch = patch.dict(os.environ, env, clear=True)
        self._env_patch.start()
        self.addCleanup(self._env_patch.stop)

        from web_ui import WebFeedbackUI

        self.ui = WebFeedbackUI(prompt="r23.3 test", host="127.0.0.1", port=18097)
        self.client = self.ui.app.test_client()

    def test_fallback_returns_200(self) -> None:
        resp = self.client.get("/apidocs/")
        self.assertEqual(resp.status_code, 200)

    def test_fallback_content_type_is_html_utf8(self) -> None:
        resp = self.client.get("/apidocs/")
        self.assertIn("text/html", resp.headers.get("Content-Type", ""))
        self.assertIn("charset=utf-8", resp.headers.get("Content-Type", "").lower())

    def test_fallback_body_mentions_env_var(self) -> None:
        resp = self.client.get("/apidocs/")
        body = resp.get_data(as_text=True)
        self.assertIn("AI_AGENT_ENABLE_SWAGGER", body)
        self.assertIn("=1", body)

    def test_fallback_body_links_to_github(self) -> None:
        resp = self.client.get("/apidocs/")
        body = resp.get_data(as_text=True)
        self.assertIn("github.com/XIADENGMA/ai-intervention-agent", body)

    def test_fallback_no_slash_path_also_works(self) -> None:
        """``/apidocs`` (no trailing slash) 也应返回 fallback 而不是 308."""
        resp = self.client.get("/apidocs")
        # Flask 默认对 strict_slashes 路由会重定向到带斜杠版，但我们明确注
        # 册了 ``/apidocs`` 端点，两条都应直接 200
        self.assertEqual(resp.status_code, 200)

    def test_fallback_body_under_2kb(self) -> None:
        """fallback 体积控制 < 2 KB，避免引入大块 inline 资源。"""
        resp = self.client.get("/apidocs/")
        body = resp.get_data()
        self.assertLess(
            len(body),
            2048,
            f"fallback HTML 应 < 2 KB，实际 {len(body)} bytes",
        )


# ---------------------------------------------------------------------------
# 4. 启用路径
# ---------------------------------------------------------------------------


class TestEnabledPath(unittest.TestCase):
    """``AI_AGENT_ENABLE_SWAGGER=1`` 时真的实例化 Swagger。"""

    def setUp(self) -> None:
        env = {**os.environ}
        env["AI_AGENT_ENABLE_SWAGGER"] = "1"
        self._env_patch = patch.dict(os.environ, env, clear=True)
        self._env_patch.start()
        self.addCleanup(self._env_patch.stop)

    def _make_ui(self):
        from web_ui import WebFeedbackUI

        return WebFeedbackUI(prompt="r23.3 test", host="127.0.0.1", port=18096)

    def test_enabled_imports_flasgger(self) -> None:
        import sys

        sys.modules.pop("flasgger", None)

        self._make_ui()

        self.assertIn("flasgger", sys.modules, "启用 Swagger 时应 import flasgger")

    def test_enabled_registers_flasgger_routes(self) -> None:
        ui = self._make_ui()
        endpoints = {rule.endpoint for rule in ui.app.url_map.iter_rules()}
        # flasgger 注册的端点必须存在
        self.assertIn("flasgger.apidocs", endpoints)
        self.assertIn("flasgger.apispec_1", endpoints)
        # 我们的 fallback 不应再被注册
        self.assertNotIn("swagger_disabled_apidocs", endpoints)

    def test_enabled_apispec_returns_json(self) -> None:
        ui = self._make_ui()
        client = ui.app.test_client()
        resp = client.get("/apispec_1.json")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("application/json", resp.headers.get("Content-Type", ""))


# ---------------------------------------------------------------------------
# 5. 源码契约
# ---------------------------------------------------------------------------


class TestSourceContract(unittest.TestCase):
    """模块顶部不再 ``from flasgger import Swagger``。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.source = WEB_UI_PY.read_text(encoding="utf-8")

    def test_no_top_level_flasgger_import(self) -> None:
        """模块顶部禁止 ``from flasgger import ...`` 与 ``import flasgger``。"""
        # 排除 docstring / 注释中的提及；只检查真正的 import 语句行
        self.assertIsNone(
            re.search(
                r"^from flasgger import\b|^import flasgger\b",
                self.source,
                re.MULTILINE,
            ),
            "web_ui.py 模块顶部不应再 import flasgger（应改成 lazy）",
        )

    def test_lazy_init_method_contains_flasgger_import(self) -> None:
        """``_init_swagger_lazy`` 方法体内必须含 ``from flasgger import Swagger``。"""
        import inspect

        from web_ui import WebFeedbackUI

        src = inspect.getsource(WebFeedbackUI._init_swagger_lazy)
        # 去掉 docstring 后再搜，避免 docstring 里的 backtick 提及被命中
        body = re.sub(r'"""(.*?)"""', "", src, count=1, flags=re.DOTALL)
        self.assertIsNotNone(
            re.search(r"^\s+from flasgger import Swagger\b", body, re.MULTILINE),
            "_init_swagger_lazy 必须含 lazy import 语句",
        )

    def test_env_helper_exists_and_reads_env(self) -> None:
        from web_ui import _is_swagger_enabled_via_env

        self.assertTrue(callable(_is_swagger_enabled_via_env))


# ---------------------------------------------------------------------------
# 6. 文档契约
# ---------------------------------------------------------------------------


class TestDocstringContract(unittest.TestCase):
    """模块源码必须解释 R23.3 + opt-in 启用方式。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.source = WEB_UI_PY.read_text(encoding="utf-8")

    def test_source_mentions_r23_3(self) -> None:
        self.assertIn("R23.3", self.source)

    def test_source_mentions_env_var_name(self) -> None:
        # 至少在某个注释 / docstring 中出现
        self.assertIn("AI_AGENT_ENABLE_SWAGGER", self.source)

    def test_source_explains_cold_start_savings(self) -> None:
        """注释里要说 ~75 ms 这种量化数字，避免被未来「这优化不重要」drive-by 删掉。"""
        self.assertRegex(
            self.source,
            r"75\s*ms|\b75ms\b",
            "R23.3 注释应量化 ~75 ms 的成本以防止 drive-by 回退",
        )


if __name__ == "__main__":
    unittest.main()
