"""CSP-compatibility guard for Import Maps (T1 · C10b).

Rationale (BEST_PRACTICES_PLAN.tmp.md §T1 v3 §4):
    Import Maps are subject to CSP `script-src` (WICG/import-maps#105).
    Our Web UI ships `script-src 'self' 'nonce-<...>'`, which is ALREADY
    compatible with Import Maps as long as two conditions hold:

    1. The CSP policy MUST declare a nonce-based `script-src`.
       (If it ever changes to hash-only or an allowlist, Import Maps
       would need `script-src-elem 'unsafe-inline'` or equivalent, which
       would be a regression.)

    2. Every `<script type="importmap">` tag MUST carry that nonce.
       (Otherwise the browser refuses to apply it and bare specifiers
       would fail to resolve at runtime — silent fallback, no error.)

    3. The CSP MUST NOT set `require-trusted-types-for 'script'` (we
       never did, but the guard is kept forward-looking).

If any of these drift, the `@aiia/*` shared-module contract breaks.
This test catches the drift at CI time.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
WEB_UI_HTML = REPO_ROOT / "templates" / "web_ui.html"
SECURITY_MODULE = REPO_ROOT / "web_ui_security.py"
VSCODE_WEBVIEW_TS = REPO_ROOT / "packages" / "vscode" / "webview.ts"


def _strip_html_comments(html: str) -> str:
    return re.sub(r"<!--.*?-->", "", html, flags=re.DOTALL)


class TestCspAllowsImportMapNonce(unittest.TestCase):
    """Regression pins for Web UI CSP + Import Map nonce."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.html = _strip_html_comments(WEB_UI_HTML.read_text(encoding="utf-8"))
        cls.security_src = SECURITY_MODULE.read_text(encoding="utf-8")

    def test_csp_script_src_uses_nonce(self) -> None:
        self.assertIn(
            "'nonce-",
            self.security_src,
            msg=(
                "Web UI CSP must use nonce-based script-src. Hash-only or "
                "allowlist-only policies would break Import Maps (the "
                "<script type='importmap'> must match the same nonce or hash "
                "rule as inline scripts)."
            ),
        )
        self.assertIn(
            "script-src 'self' 'nonce-",
            self.security_src,
            msg=(
                "Expected CSP fragment \"script-src 'self' 'nonce-<...>'\" in "
                "web_ui_security.py. If this is changed, every importmap and "
                "module script in templates/web_ui.html must follow the new "
                "contract or bare-specifier resolution will silently fail."
            ),
        )

    def test_csp_does_not_require_trusted_types(self) -> None:
        self.assertNotIn(
            "require-trusted-types-for",
            self.security_src,
            msg=(
                "If `require-trusted-types-for 'script'` is enabled, Import "
                "Maps and module scripts must be wrapped through a trusted "
                "types policy. We are not ready for that rollout; this test "
                "fails loudly when the CSP is hardened without first "
                "retrofitting the importmap path."
            ),
        )

    def test_importmap_script_carries_nonce(self) -> None:
        match = re.search(
            r'<script\s+type="importmap"\s+nonce="\{\{\s*csp_nonce\s*\}\}"',
            self.html,
        )
        self.assertIsNotNone(
            match,
            msg=(
                '`<script type="importmap" nonce="{{ csp_nonce }}">` missing '
                "in templates/web_ui.html. Without the nonce attribute the "
                "browser drops the importmap under our CSP (nonce-only "
                "script-src), breaking every bare-specifier import silently."
            ),
        )

    def test_module_loader_script_carries_nonce(self) -> None:
        pattern = re.compile(
            r'<script\b[^>]*\btype="module"[^>]*\bnonce="\{\{\s*csp_nonce\s*\}\}"'
            r'[^>]*\bsrc="/static/js/tri-state-panel-loader\.js"',
            flags=re.DOTALL,
        )
        alt_pattern = re.compile(
            r'<script\b[^>]*\bsrc="/static/js/tri-state-panel-loader\.js"'
            r'[^>]*\bnonce="\{\{\s*csp_nonce\s*\}\}"[^>]*\btype="module"',
            flags=re.DOTALL,
        )
        if not pattern.search(self.html) and not alt_pattern.search(self.html):
            self.fail(
                "Loader module script (type='module' src='/static/js/tri-state-panel-loader.js') "
                "missing its nonce attribute. CSP nonce-only script-src would "
                "reject it and bare-specifier resolution never runs."
            )


class TestCspAllowsImportMapNonceVscode(unittest.TestCase):
    """Same regression pins, but for the VSCode webview half (T1 · C10c).

    The webview HTML is generated dynamically inside
    ``packages/vscode/webview.ts::_getHtmlContent``; this test class
    asserts the same nonce contract on that template literal so the
    Web UI and VSCode webview never drift.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.ts = VSCODE_WEBVIEW_TS.read_text(encoding="utf-8")

    def test_csp_script_src_uses_nonce(self) -> None:
        self.assertIn(
            "script-src 'nonce-${nonce}'",
            self.ts,
            msg=(
                "VSCode webview CSP must use nonce-based script-src "
                "(``script-src 'nonce-${nonce}'``). Hash-only or allowlist-only "
                "policies would break Import Maps (the <script type='importmap'> "
                "must match the same nonce or hash rule as inline scripts)."
            ),
        )

    def test_csp_does_not_require_trusted_types(self) -> None:
        self.assertNotIn(
            "require-trusted-types-for",
            self.ts,
            msg=(
                "If `require-trusted-types-for 'script'` is enabled, Import "
                "Maps and module scripts must be wrapped through a trusted "
                "types policy. We are not ready for that rollout; this test "
                "fails loudly when the CSP is hardened without first "
                "retrofitting the importmap path."
            ),
        )

    def test_importmap_script_carries_nonce(self) -> None:
        match = re.search(
            r'<script\s+type="importmap"\s+nonce="\$\{nonce\}"',
            self.ts,
        )
        self.assertIsNotNone(
            match,
            msg=(
                '<script type="importmap" nonce="${nonce}"> missing in '
                "webview.ts::_getHtmlContent. Without the nonce attribute "
                "the browser drops the importmap under the CSP "
                "(nonce-only script-src), breaking every bare-specifier "
                "import silently."
            ),
        )

    def test_module_loader_script_carries_nonce(self) -> None:
        pattern = re.compile(
            r'<script\b[^>]*\btype="module"[^>]*\bnonce="\$\{nonce\}"'
            r'[^>]*\bsrc="\$\{triStatePanelLoaderUri\}"',
            flags=re.DOTALL,
        )
        alt_pattern = re.compile(
            r'<script\b[^>]*\bsrc="\$\{triStatePanelLoaderUri\}"'
            r'[^>]*\bnonce="\$\{nonce\}"[^>]*\btype="module"',
            flags=re.DOTALL,
        )
        if not pattern.search(self.ts) and not alt_pattern.search(self.ts):
            self.fail(
                "Loader module script (type='module' src='${triStatePanelLoaderUri}') "
                "missing its nonce attribute in webview.ts. CSP nonce-only "
                "script-src would reject it and bare-specifier resolution "
                "never runs."
            )


class TestNonceCsprngContract(unittest.TestCase):
    """Reverse-locks for both halves of the CSP nonce generator.

    Why this matters: a nonce-based CSP is **only** as strong as the
    randomness it's seeded with. CSP3 §6 explicitly requires CSPRNG
    output ≥ 64 bits — `Math.random` (V8 xorshift128+, 53-bit state,
    [public algorithm](https://github.com/v8/v8/blob/main/src/numbers/math-random.cc))
    falls below the threshold and is observably-predictable from a
    handful of outputs. If a future "simplification" PR swaps the
    generator back to `Math.random` / Python `random.SystemRandom`
    is replaced by `random.choice`, attackers can predict the nonce
    and bypass the entire CSP nonce-allowlist for inline `<script>`
    blocks (regressing to effectively `script-src 'unsafe-inline'`).
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.ts = VSCODE_WEBVIEW_TS.read_text(encoding="utf-8")
        cls.security_src = SECURITY_MODULE.read_text(encoding="utf-8")

    def test_vscode_getNonce_uses_node_crypto(self) -> None:
        """``packages/vscode/webview.ts::getNonce`` 必须走 Node.js 内置
        ``crypto.randomBytes``（→ OS CSPRNG）。"""
        self.assertIn(
            "crypto.randomBytes",
            self.ts,
            msg=(
                "webview.ts::getNonce must use crypto.randomBytes (Node.js "
                "CSPRNG → OS getentropy/getrandom/BCryptGenRandom). "
                "Math.random is a V8 xorshift128+ PRNG with 53-bit state "
                "and observably predictable output — using it for CSP "
                "nonces effectively regresses to 'unsafe-inline'."
            ),
        )
        self.assertIn(
            "import * as crypto from 'crypto'",
            self.ts,
            msg=(
                "Expected `import * as crypto from 'crypto'` at the top of "
                "webview.ts so getNonce can reach Node's CSPRNG. If a "
                "future refactor reaches for browser-side crypto.subtle, "
                "remember the extension host runs in Node, not the "
                "webview's V8 isolate."
            ),
        )

    def test_vscode_getNonce_does_not_use_math_random(self) -> None:
        """Reverse-lock：``getNonce`` 函数体绝不能再出现 ``Math.random``。

        历史实现把 ``Math.random()`` 在 62-char alphabet 上 sample 32
        字符，看似熵 ≈ 190 bits，但 V8 PRNG state 仅 53 bits，攻击者
        观察少量 nonce 即可预测后续值。
        """
        # 抓出 getNonce 函数体的范围（从 ``function getNonce`` 到下一个
        # 顶层 ``function`` 或文件末尾），仅检查这段内是否出现 Math.random。
        match = re.search(
            r"function\s+getNonce\b[^{]*\{(?P<body>.*?)\n\}",
            self.ts,
            flags=re.DOTALL,
        )
        self.assertIsNotNone(
            match, msg="无法定位 webview.ts::getNonce 函数体（语法漂移？）"
        )
        assert match is not None  # ty narrowing
        body = match.group("body")
        self.assertNotIn(
            "Math.random",
            body,
            msg=(
                "webview.ts::getNonce 函数体含 Math.random —— 这是 V8 "
                "xorshift128+ PRNG，53 bits state，CSP3 §6 明确禁止用于 "
                "nonce 生成。请回到 crypto.randomBytes(16).toString('base64')。"
            ),
        )
        self.assertNotIn(
            "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789",
            body,
            msg=(
                "webview.ts::getNonce 函数体含手工 alphabet 字符串采样 —— "
                "这通常意味着 Math.random 风格的滚轮采样回归。CSPRNG 路径"
                "不需要 alphabet（base64 编码即可）。"
            ),
        )

    def test_python_csp_nonce_uses_secrets_module(self) -> None:
        """Web UI 端 ``web_ui_security.py`` 必须用 ``secrets`` 模块（CSPRNG）
        而非 ``random.choice`` 之类的 PRNG。"""
        self.assertIn(
            "secrets.token_urlsafe",
            self.security_src,
            msg=(
                "web_ui_security.py 必须用 secrets.token_urlsafe(16) 生成 "
                "CSP nonce —— 16 字节 = 128 bits 熵（OS CSPRNG），符合 "
                "CSP3 §6 要求。如改成 random.choice / hashlib.md5(time)，"
                "整个 nonce-only CSP 退化为 'unsafe-inline'。"
            ),
        )
        # 反向：``import random`` 用于 nonce 路径会触发本测试 fail。
        # 注意 web_ui_security.py 整体可以 import random（用于其它非密码学
        # 用途），所以这里只锁 secrets.token_urlsafe 必须存在，不强行禁用
        # ``import random`` —— 但如果直接出现 ``random.choice`` /
        # ``random.randint`` 在 nonce 上下文，应另起一道测试拦截。

    def test_python_csp_nonce_byte_length_at_least_16(self) -> None:
        """Reverse-lock：``secrets.token_urlsafe(N)`` 的 N 必须 ≥ 16
        （= 128 bits 熵 = CSP3 §6 阈值的 2×）。

        历史 N=16 是合理选择（24 字符 base64 输出，浏览器友好）；
        如有人误改成 8（=64 bits，刚好踩在 CSP3 阈值上，无安全裕度）
        或更小，本测试 fail。
        """
        matches = re.findall(
            r"secrets\.token_urlsafe\(\s*(\d+)\s*\)", self.security_src
        )
        self.assertTrue(
            len(matches) > 0,
            "web_ui_security.py 找不到任何 secrets.token_urlsafe(...) 调用",
        )
        for byte_count_str in matches:
            byte_count = int(byte_count_str)
            self.assertGreaterEqual(
                byte_count,
                16,
                f"secrets.token_urlsafe({byte_count}) 熵不足 128 bits "
                "（每字节 8 bits，需要 ≥ 16 字节）。CSP3 §6 阈值 64 bits，"
                "16 字节给一倍裕度。",
            )


if __name__ == "__main__":
    unittest.main()
