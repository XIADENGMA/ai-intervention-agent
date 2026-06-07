"""R306: CSP nonce 一致性 invariant (cycle-31 t31-1, v3.7 新 pattern)。

cycle-30 cr60 §5 #B1 v3.7 新 pattern 提议 — CSP nonce 一致性 invariant。
R306 既修一个 P0 bug, 又引入 v3.7 第一个新 pattern。

================================================================
| P0 Bug 修复                                                     |
================================================================
- ``offline.html`` 通过 Flask ``render_template("offline.html")`` 渲染时
  ``after_request`` 钩子附加 CSP ``script-src 'self' 'nonce-XXX'`` 头,
  但模板内 ``<script>`` 没有 ``nonce=`` 属性 (R249 mining-9 引入时遗漏),
  浏览器 CSP 阻止该 inline script 执行 → "Retry / 重试" 按钮事件监听器
  永不绑定 → 用户离线后点击重试无反应。
- 同时, 即便手动加 ``nonce="{{ csp_nonce }}"``, ``static.py:308``
  ``render_template("offline.html")`` 没有传 ``csp_nonce`` 上下文,
  Jinja2 渲染为 ``<script nonce="">`` 空字符串, 仍然不匹配 CSP nonce。
- R306 修复: ① offline.html 加 ``nonce="{{ csp_nonce }}"`` ② SecurityMixin
  注册 ``@app.context_processor`` 让所有模板自动获得 ``csp_nonce``。

================================================================
| v3.7 新 pattern: CSP nonce 一致性 invariant                     |
================================================================
锁定 5 层 invariant:

1. **CSP 头结构**: ``_CSP_PREFIX`` 必须以 ``'nonce-`` 结尾 (即 script-src
   使用 nonce-only 策略, 不允许回退到 ``'unsafe-inline'``)
2. **Nonce 强度**: ``secrets.token_urlsafe(N)`` 必须 ``N >= 16`` (>= 128
   bit entropy, 符合 OWASP CSP nonce minimum 推荐)
3. **Single source of truth**: ``_build_csp_header`` 必须是唯一的 CSP 头
   构造点 (防止多处拼接漂移)
4. **Context processor 注入**: ``@app.context_processor`` 必须存在 + 注入
   ``csp_nonce``, 让任何 ``render_template()`` 都自动拿到
5. **运行时一致性**: 通过 Flask test client 验证响应头中的 nonce 与响应
   body 中所有 ``<script>`` 的 ``nonce=`` 属性**完全相等** (web_ui.html +
   offline.html 全覆盖)

================================================================
| Tests | 维度                                                    |
|-------|------------------------------------------------------|
| 5     | _CSP_PREFIX / _CSP_SUFFIX / _build_csp_header 结构      |
| 3     | secrets.token_urlsafe 强度 + g.csp_nonce 赋值          |
| 1     | context_processor 注入                                  |
| 3     | runtime: web_ui.html / offline.html / not_found.html   |
================================================================
| 12 总计                                                          |
================================================================

**v3.7 pattern lineage**: v3.6 4 个 pattern (perf / cross-language /
lifecycle / visual-architecture) 都聚焦 **代码 / 文档** 维度,
**R306 引入 v3.7 第一个 "运行时 + 模板 + Python 三层一致性" pattern**:
HTTP response header (Python after_request) ↔ HTML template (Jinja
``{{ csp_nonce }}``) ↔ 模板渲染 ctx 注入 (Python context_processor)
三层必须严格一致, 任何一层漂移都让 CSP 防御失效但浏览器只在 console
报错 (单测不一定捕获)。
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC = PROJECT_ROOT / "src" / "ai_intervention_agent"
SEC_PY = SRC / "web_ui_security.py"
TEMPLATES = SRC / "templates"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


# ============================================================
# Layer 1: _CSP_PREFIX / _CSP_SUFFIX / _build_csp_header 结构
# ============================================================
class TestCspHeaderStructure(unittest.TestCase):
    """SecurityMixin CSP 头模板结构必须保持 nonce-only 策略"""

    def setUp(self) -> None:
        self.src = _read(SEC_PY)

    def test_csp_prefix_uses_nonce(self) -> None:
        """``_CSP_PREFIX`` 必须以 ``'nonce-`` 结尾, 锁 script-src nonce 策略。"""
        m = re.search(
            r"_CSP_PREFIX:\s*str\s*=\s*\"[^\"]*?script-src 'self' 'nonce-\"",
            self.src,
        )
        self.assertIsNotNone(
            m,
            "R306: _CSP_PREFIX 必须含 `script-src 'self' 'nonce-` "
            "(锁 nonce-only 策略, 不允许 unsafe-inline 回退)",
        )

    def test_csp_prefix_does_not_allow_unsafe_inline_script(self) -> None:
        """``_CSP_PREFIX`` 不能在 script-src 出现 ``'unsafe-inline'``。"""
        # 在 _CSP_PREFIX / _CSP_SUFFIX 字符串内查找
        m = re.search(
            r"_CSP_PREFIX:\s*str\s*=\s*\"([^\"]+)\"",
            self.src,
        )
        self.assertIsNotNone(m)
        assert m is not None
        prefix = m.group(1)
        self.assertIn("script-src", prefix)
        # 找 script-src 后到下一个 ; 之间的部分
        sm = re.search(r"script-src\s+([^;]+)", prefix)
        self.assertIsNotNone(sm, "script-src 必须存在于 _CSP_PREFIX")
        assert sm is not None
        script_directive = sm.group(1)
        self.assertNotIn(
            "'unsafe-inline'",
            script_directive,
            "R306: script-src 不允许 'unsafe-inline' (会绕过 nonce, 让 CSP 失效)",
        )

    def test_csp_suffix_has_style_src(self) -> None:
        """``_CSP_SUFFIX`` 必须包含 ``style-src`` directive (zero unsafe-eval)。"""
        m = re.search(
            r"_CSP_SUFFIX:\s*str\s*=\s*\(([^)]+)\)",
            self.src,
            re.DOTALL,
        )
        self.assertIsNotNone(m)
        assert m is not None
        suffix = m.group(1)
        self.assertIn("style-src", suffix, "R306: _CSP_SUFFIX 必须含 style-src")

    def test_build_csp_header_single_source_of_truth(self) -> None:
        """``_build_csp_header`` 必须是唯一的 nonce 嵌入点 (3 段 concat)。"""
        m = re.search(
            r"def _build_csp_header\([\s\S]{0,800}?"
            r"return\s+cls\._CSP_PREFIX\s*\+\s*nonce\s*\+\s*cls\._CSP_SUFFIX",
            self.src,
        )
        self.assertIsNotNone(
            m,
            "R306: _build_csp_header 必须 `return cls._CSP_PREFIX + nonce + "
            "cls._CSP_SUFFIX` (single source of truth, 3 段 concat)",
        )

        outside = re.sub(r"_CSP_PREFIX:\s*str\s*=\s*\"[^\"]+\"", "", self.src)
        outside = re.sub(r"def _build_csp_header[\s\S]+?return[^\n]+", "", outside)
        self.assertNotIn(
            "'nonce-' +",
            outside,
            "R306: 不允许在 _build_csp_header 外另起一处 'nonce-' 字符串拼接",
        )

    def test_csp_header_set_in_after_request(self) -> None:
        """``Content-Security-Policy`` 必须在 ``after_request`` 钩子中设置。"""
        m = re.search(
            r"@self\.app\.after_request[\s\S]{0,500}?"
            r"response\.headers\[\"Content-Security-Policy\"\]\s*=\s*"
            r"self\._build_csp_header\(nonce\)",
            self.src,
        )
        self.assertIsNotNone(
            m,
            "R306: after_request 钩子必须设置 CSP 头, 用 self._build_csp_header(nonce)",
        )


# ============================================================
# Layer 2: nonce 强度 + g.csp_nonce 赋值
# ============================================================
class TestNonceStrengthAndAssignment(unittest.TestCase):
    """nonce 必须用 secrets.token_urlsafe(>=16) + 在 before_request 中赋值"""

    def setUp(self) -> None:
        self.src = _read(SEC_PY)

    def test_nonce_uses_secrets_token_urlsafe(self) -> None:
        """nonce 必须用 ``secrets.token_urlsafe(N)`` (CSPRNG, 不是 random)。"""
        m = re.search(
            r"g\.csp_nonce\s*=\s*secrets\.token_urlsafe\(\d+\)",
            self.src,
        )
        self.assertIsNotNone(
            m,
            "R306: g.csp_nonce 必须用 secrets.token_urlsafe(N) "
            "(CSPRNG, 不能用 random.choice / time.time() 等弱熵)",
        )

    def test_nonce_length_at_least_16_bytes(self) -> None:
        """``secrets.token_urlsafe(N)`` N 必须 >= 16 (128 bit entropy)。"""
        for m in re.finditer(r"secrets\.token_urlsafe\((\d+)\)", self.src):
            n = int(m.group(1))
            self.assertGreaterEqual(
                n,
                16,
                f"R306: secrets.token_urlsafe({n}) 必须 N >= 16 "
                f"(OWASP CSP nonce >= 128 bit entropy 推荐)",
            )

    def test_nonce_assigned_in_before_request(self) -> None:
        """``g.csp_nonce`` 必须在 ``before_request`` 中赋值。"""
        m = re.search(
            r"@self\.app\.before_request[\s\S]{0,500}?g\.csp_nonce\s*=\s*"
            r"secrets\.token_urlsafe\(",
            self.src,
        )
        self.assertIsNotNone(
            m,
            "R306: g.csp_nonce 必须在 before_request 钩子中赋值 "
            "(每请求一次, 不能在 module 级常量)",
        )


# ============================================================
# Layer 3: context_processor 注入 (R306 修复点)
# ============================================================
class TestCspNonceContextProcessor(unittest.TestCase):
    """R306 修复: context_processor 必须自动注入 csp_nonce 到所有模板"""

    def setUp(self) -> None:
        self.src = _read(SEC_PY)

    def test_context_processor_registered_with_csp_nonce(self) -> None:
        """``@app.context_processor`` 必须存在并注入 ``csp_nonce`` 键。"""
        m = re.search(
            r"@self\.app\.context_processor[\s\S]{0,400}?"
            r'return\s*\{\s*"csp_nonce":\s*getattr\(g,\s*"csp_nonce"',
            self.src,
        )
        self.assertIsNotNone(
            m,
            "R306: SecurityMixin 必须注册 @app.context_processor 注入 csp_nonce, "
            "让所有 render_template() 自动获得 nonce (修 offline.html 类 bug)",
        )


# ============================================================
# Layer 4: 运行时一致性 (通过 Flask test client)
# ============================================================
class TestRuntimeCspNonceConsistency(unittest.TestCase):
    """端到端: 响应 CSP header nonce = 响应 body 内所有 <script> nonce"""

    @classmethod
    def setUpClass(cls) -> None:
        from ai_intervention_agent.web_ui import WebFeedbackUI

        cls.ui = WebFeedbackUI(prompt="test", host="127.0.0.1", port=9998)
        cls.client = cls.ui.app.test_client()

    @staticmethod
    def _strip_html_comments(html: str) -> str:
        """剥离 HTML ``<!-- ... -->`` 注释 (避免注释内的 ``<script>`` 字面值误匹配)。"""
        return re.sub(r"<!--[\s\S]*?-->", "", html)

    def _check_page(self, path: str, allow_zero_scripts: bool = False) -> None:
        """通用工具: 请求 path, 验证所有 ``<script>`` nonce = CSP header nonce。"""
        resp = self.client.get(path)
        self.assertIn(resp.status_code, (200, 404))
        csp = resp.headers.get("Content-Security-Policy", "")
        self.assertIn(
            "nonce-",
            csp,
            f"R306: {path} 响应 CSP 头必须含 nonce- (找到: {csp[:200]!r})",
        )
        m = re.search(r"nonce-([A-Za-z0-9_\-]+)", csp)
        self.assertIsNotNone(m)
        assert m is not None
        header_nonce = m.group(1)
        self.assertGreater(
            len(header_nonce),
            16,
            f"R306: {path} CSP header nonce 长度太短 ({len(header_nonce)})",
        )

        body = self._strip_html_comments(resp.get_data(as_text=True))
        scripts = re.findall(r"<script[^>]*>", body)
        if not allow_zero_scripts:
            self.assertGreater(
                len(scripts),
                0,
                f"R306: {path} 响应 body 必须含至少 1 个 <script> 标签",
            )

        for s in scripts:
            nm = re.search(r'nonce="([^"]+)"', s)
            self.assertIsNotNone(
                nm,
                f"R306: {path} 响应 body 中 <script> 必须含 nonce= 属性, "
                f"找到无 nonce 的 script: {s[:120]!r}",
            )
            assert nm is not None
            self.assertEqual(
                nm.group(1),
                header_nonce,
                f"R306: {path} <script nonce=...> 必须与 CSP header nonce "
                f"完全一致 (script={nm.group(1)!r} vs csp={header_nonce!r})",
            )

    def test_web_ui_html_nonce_consistency(self) -> None:
        """``GET /`` (web_ui.html) 所有 ``<script>`` nonce = CSP header nonce。"""
        self._check_page("/")

    def test_offline_html_nonce_consistency(self) -> None:
        """``GET /offline.html`` 所有 ``<script>`` nonce = CSP header nonce
        (R306 P0 bug 修复点)。"""
        self._check_page("/offline.html")

    def test_offline_html_retry_script_has_nonce(self) -> None:
        """``offline.html`` 模板源码必须含 ``<script nonce="{{ csp_nonce }}">``。

        防止未来有人重写 offline.html 忘了 nonce → 重现 R306 修复的 P0 bug。
        """
        src = self._strip_html_comments(_read(TEMPLATES / "offline.html"))
        scripts = re.findall(r"<script[^>]*>", src)
        for s in scripts:
            self.assertIn(
                'nonce="{{ csp_nonce }}"',
                s,
                f"R306: offline.html <script> 必须含 nonce='{{{{ csp_nonce }}}}' "
                f"(R249 mining-9 时漏加 → CSP 阻止 Retry 按钮)。找到: {s!r}",
            )


if __name__ == "__main__":
    unittest.main()
