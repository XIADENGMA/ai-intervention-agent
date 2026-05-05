"""R23.5 · CSP 头模板预拼接的契约 + 性能测试

背景
----
``web_ui_security.SecurityMixin.setup_security_headers`` 的 ``after_request``
钩子之前每次都把 10 段 CSP directive 重新 concat 一次（CPython 用
``BUILD_STRING`` 字节码合成，但仍要重新 alloc + 10 次 memcpy）。R23.5 把
不变部分预拼接到 class attribute（``_CSP_PREFIX`` / ``_CSP_SUFFIX``），
hot path 上每个请求只做 3 段 concat（prefix + nonce + suffix）。

本测试覆盖：

1.  **常量存在性 + 类型**：``_CSP_PREFIX`` / ``_CSP_SUFFIX`` 是模块级
    string 常量。
2.  **拼接函数行为**：``_build_csp_header(nonce)`` 返回的字符串与
    R23.5 之前 f-string 拼接版本逐字节一致。
3.  **directive 完整性**：所有 9 个不变 directive + ``script-src`` 都
    在最终字符串里。
4.  **nonce 不泄漏到常量**：``_CSP_PREFIX`` / ``_CSP_SUFFIX`` 不能
    包含具体 nonce，否则失去『请求级随机性』。
5.  **源码契约**：``add_security_headers`` 不再用 f-string 拼 CSP，
    而是调用 ``_build_csp_header``。
6.  **文档契约**：CSP 区块 docstring 必须解释 R23.5 的优化目的。
7.  **集成回归**：用 Flask test client 真实拉一次响应，确认
    ``Content-Security-Policy`` 头以 ``default-src 'self'`` 开头、含
    ``nonce-`` 字段、且最后一段是 ``object-src 'none'``。
"""

from __future__ import annotations

import inspect
import re
import unittest
from pathlib import Path

from web_ui_security import SecurityMixin

REPO_ROOT = Path(__file__).resolve().parent.parent
WEB_UI_SECURITY_PY = REPO_ROOT / "web_ui_security.py"


# ---------------------------------------------------------------------------
# 1. 常量存在性 + 类型
# ---------------------------------------------------------------------------


class TestConstantsExist(unittest.TestCase):
    """``_CSP_PREFIX`` / ``_CSP_SUFFIX`` 已声明为类常量。"""

    def test_prefix_is_str(self) -> None:
        self.assertIsInstance(SecurityMixin._CSP_PREFIX, str)
        self.assertGreater(len(SecurityMixin._CSP_PREFIX), 0)

    def test_suffix_is_str(self) -> None:
        self.assertIsInstance(SecurityMixin._CSP_SUFFIX, str)
        self.assertGreater(len(SecurityMixin._CSP_SUFFIX), 0)

    def test_prefix_ends_with_nonce_prefix(self) -> None:
        """prefix 必须以 ``'nonce-`` 结尾，让拼接位置落在 nonce 占位上。"""
        self.assertTrue(
            SecurityMixin._CSP_PREFIX.endswith("'nonce-"),
            f"_CSP_PREFIX 必须以 'nonce- 结尾，实际为 {SecurityMixin._CSP_PREFIX!r}",
        )

    def test_suffix_starts_with_nonce_close(self) -> None:
        """suffix 必须以 ``'; `` 起步（闭合 nonce 单引号 + 分号 + 空格）。"""
        self.assertTrue(
            SecurityMixin._CSP_SUFFIX.startswith("'; "),
            f"_CSP_SUFFIX 必须以 '; 起步，实际为 {SecurityMixin._CSP_SUFFIX!r}",
        )


# ---------------------------------------------------------------------------
# 2. 拼接函数行为（byte-for-byte 与 R23.5 前一致）
# ---------------------------------------------------------------------------


class TestBuildCspHeader(unittest.TestCase):
    """``_build_csp_header`` 输出与 R23.5 之前拼接版本逐字节一致。"""

    @staticmethod
    def _legacy_csp(nonce: str) -> str:
        """R23.5 之前的 f-string 拼接逻辑（保留作为基准）。"""
        return (
            "default-src 'self'; "
            f"script-src 'self' 'nonce-{nonce}'; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data: blob:; "
            "font-src 'self' data:; "
            "connect-src 'self'; "
            "worker-src 'self'; "
            "frame-ancestors 'none'; "
            "base-uri 'self'; "
            "object-src 'none'"
        )

    def test_matches_legacy_for_typical_nonce(self) -> None:
        nonce = "abcDEF123_-test"
        self.assertEqual(
            SecurityMixin._build_csp_header(nonce),
            self._legacy_csp(nonce),
            "新拼接结果必须与 R23.5 之前 f-string 版本逐字节一致",
        )

    def test_matches_legacy_for_empty_nonce(self) -> None:
        """nonce 空（极端 fallback）时也必须等价。"""
        self.assertEqual(
            SecurityMixin._build_csp_header(""),
            self._legacy_csp(""),
        )

    def test_matches_legacy_for_long_nonce(self) -> None:
        """偏长 nonce（``secrets.token_urlsafe(64)`` 量级）也必须等价。"""
        nonce = "x" * 88
        self.assertEqual(
            SecurityMixin._build_csp_header(nonce),
            self._legacy_csp(nonce),
        )

    def test_classmethod_can_be_called_via_class(self) -> None:
        """子类 / 类层调用都能拿到正确结果。"""
        header = SecurityMixin._build_csp_header("foo")
        self.assertIn("'nonce-foo'", header)


# ---------------------------------------------------------------------------
# 3. directive 完整性
# ---------------------------------------------------------------------------


class TestDirectiveCompleteness(unittest.TestCase):
    """所有 directive 都必须出现在 final 字符串里。"""

    def setUp(self) -> None:
        self.header = SecurityMixin._build_csp_header("test_nonce")

    def test_default_src(self) -> None:
        self.assertIn("default-src 'self'", self.header)

    def test_script_src_with_nonce(self) -> None:
        self.assertIn("script-src 'self' 'nonce-test_nonce'", self.header)

    def test_style_src(self) -> None:
        self.assertIn("style-src 'self' 'unsafe-inline'", self.header)

    def test_img_src(self) -> None:
        self.assertIn("img-src 'self' data: blob:", self.header)

    def test_font_src(self) -> None:
        self.assertIn("font-src 'self' data:", self.header)

    def test_connect_src(self) -> None:
        self.assertIn("connect-src 'self'", self.header)

    def test_worker_src(self) -> None:
        self.assertIn("worker-src 'self'", self.header)

    def test_frame_ancestors(self) -> None:
        self.assertIn("frame-ancestors 'none'", self.header)

    def test_base_uri(self) -> None:
        self.assertIn("base-uri 'self'", self.header)

    def test_object_src_at_end(self) -> None:
        """``object-src 'none'`` 是最后一个 directive，结尾不应有分号。"""
        self.assertTrue(
            self.header.endswith("object-src 'none'"),
            f"CSP 应以 object-src 'none' 结尾，实际为 ...{self.header[-32:]!r}",
        )


# ---------------------------------------------------------------------------
# 4. nonce 不能泄漏到常量
# ---------------------------------------------------------------------------


class TestNonceIsolation(unittest.TestCase):
    """常量必须与具体请求的 nonce 解耦。"""

    def test_prefix_does_not_contain_concrete_nonce_value(self) -> None:
        # 出现 ``'nonce-`` 字面量是允许的（占位前缀），但不能含实际值
        # 比如 ``nonce-abc123``（任意 base64-like 字符）
        # 这里检查 prefix 末尾就是 ``'nonce-``，没有更多 alphanumeric
        self.assertTrue(SecurityMixin._CSP_PREFIX.endswith("'nonce-"))
        # prefix 中不能再次出现 ``nonce-XXX'`` 模式
        self.assertNotRegex(
            SecurityMixin._CSP_PREFIX,
            r"nonce-[a-zA-Z0-9_-]+'",
            "_CSP_PREFIX 不应内含具体 nonce 值",
        )

    def test_suffix_does_not_contain_nonce(self) -> None:
        self.assertNotIn(
            "nonce-",
            SecurityMixin._CSP_SUFFIX,
            "_CSP_SUFFIX 不应包含 nonce 字段",
        )

    def test_two_calls_with_different_nonces_diverge(self) -> None:
        h1 = SecurityMixin._build_csp_header("nonce_one")
        h2 = SecurityMixin._build_csp_header("nonce_two")
        self.assertNotEqual(h1, h2)
        self.assertIn("nonce-nonce_one", h1)
        self.assertIn("nonce-nonce_two", h2)


# ---------------------------------------------------------------------------
# 5. 源码契约
# ---------------------------------------------------------------------------


class TestSourceContract(unittest.TestCase):
    """源码层面验证：hot path 不再做 10 段 f-string 拼接。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.source = WEB_UI_SECURITY_PY.read_text(encoding="utf-8")

    def test_setup_security_headers_calls_build_csp_header(self) -> None:
        setup_src = inspect.getsource(SecurityMixin.setup_security_headers)
        self.assertIn(
            "_build_csp_header(",
            setup_src,
            "setup_security_headers 必须调用 _build_csp_header",
        )

    def test_setup_security_headers_no_fstring_csp(self) -> None:
        """``setup_security_headers`` 内不能再有原来的 10 段 f-string。"""
        setup_src = inspect.getsource(SecurityMixin.setup_security_headers)
        # 旧 hot path 的标志：``f"script-src 'self' 'nonce-{nonce}'; "``
        self.assertNotRegex(
            setup_src,
            r"f['\"]script-src",
            "hot path 不应再用 f-string 拼 script-src",
        )
        # 也不能再单独出现 style-src/img-src 等字面量（它们应该只在常量里）
        self.assertNotIn(
            "style-src 'self' 'unsafe-inline'",
            setup_src,
            "directive 字面量不应再散落在 setup_security_headers 中",
        )

    def test_module_top_level_has_csp_constants(self) -> None:
        """常量必须以模块/类常量形式存在（搜索源码而非靠属性）。"""
        # _CSP_PREFIX = "..."（class 缩进）
        self.assertRegex(
            self.source,
            r"_CSP_PREFIX\s*:\s*str\s*=",
            "应在类层声明 _CSP_PREFIX: str = ...",
        )
        self.assertRegex(
            self.source,
            r"_CSP_SUFFIX\s*:\s*str\s*=",
            "应在类层声明 _CSP_SUFFIX: str = ...",
        )

    def test_build_csp_header_uses_three_part_concat(self) -> None:
        """``_build_csp_header`` 实现应该是三段 ``+`` 拼接。"""
        method_src = inspect.getsource(SecurityMixin._build_csp_header)
        body = re.sub(r'"""(.*?)"""', "", method_src, count=1, flags=re.DOTALL)
        # 必须含 cls._CSP_PREFIX + nonce + cls._CSP_SUFFIX 形态
        self.assertRegex(
            body,
            r"cls\._CSP_PREFIX\s*\+\s*nonce\s*\+\s*cls\._CSP_SUFFIX",
            "_build_csp_header 应用三段 + 拼接（prefix + nonce + suffix）",
        )


# ---------------------------------------------------------------------------
# 6. 文档契约
# ---------------------------------------------------------------------------


class TestDocstringContract(unittest.TestCase):
    """docstring 必须解释 R23.5 的优化目的。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.source = WEB_UI_SECURITY_PY.read_text(encoding="utf-8")

    def test_module_or_class_doc_mentions_r23_5(self) -> None:
        self.assertIn("R23.5", self.source)

    def test_doc_mentions_predcompute_or_concat(self) -> None:
        self.assertRegex(
            self.source,
            r"预拼接|预先拼接|3 段 concat|三段 concat|hot path",
            "CSP 区块 docstring 应解释 hot path 优化",
        )


# ---------------------------------------------------------------------------
# 7. 集成回归（Flask test client 真实拉一次）
# ---------------------------------------------------------------------------


class TestIntegrationViaFlaskApp(unittest.TestCase):
    """构造一个最小 Flask app 挂上 SecurityMixin，校验真实响应头。"""

    def setUp(self) -> None:
        from flask import Flask, jsonify
        from flask.typing import ResponseReturnValue

        class _MinimalApp(SecurityMixin):
            def __init__(self) -> None:
                self.app = Flask(__name__)
                self.host = "127.0.0.1"
                self.network_security_config = {"access_control_enabled": False}

                @self.app.route("/ping")
                def ping() -> ResponseReturnValue:
                    return jsonify({"ok": True})

                self.setup_security_headers()

        self.holder = _MinimalApp()
        self.client = self.holder.app.test_client()

    def test_response_has_csp_header(self) -> None:
        resp = self.client.get("/ping")
        self.assertEqual(resp.status_code, 200)
        csp = resp.headers.get("Content-Security-Policy", "")
        self.assertNotEqual(csp, "")
        self.assertTrue(csp.startswith("default-src 'self'"))
        self.assertIn("script-src 'self' 'nonce-", csp)
        self.assertTrue(csp.endswith("object-src 'none'"))

    def test_two_requests_have_different_nonces(self) -> None:
        r1 = self.client.get("/ping")
        r2 = self.client.get("/ping")
        nonce_re = re.compile(r"script-src 'self' 'nonce-([^']+)'")
        m1 = nonce_re.search(r1.headers.get("Content-Security-Policy", ""))
        m2 = nonce_re.search(r2.headers.get("Content-Security-Policy", ""))
        assert m1 is not None and m2 is not None  # type: narrowing
        self.assertNotEqual(
            m1.group(1),
            m2.group(1),
            "每个请求必须拿到独立 nonce，不能因为模板预拼接退化成静态",
        )


if __name__ == "__main__":
    unittest.main()
