"""Modern security-header policy guards.

Locks the contracts established in Round-16.3:

1. ``X-XSS-Protection`` is **explicitly disabled** (``"0"``), not the
   historical ``"1; mode=block"``. The header is deprecated; modern
   browsers ignore it, and legacy browsers that still honour it have
   been shown to use the auditor as an XSS oracle. Mozilla Observatory
   and OWASP Secure Headers Project both recommend ``"0"`` to make the
   intent explicit ("CSP owns XSS defence here").

2. ``Cross-Origin-Opener-Policy: same-origin`` is set, severing
   ``window.opener`` between cross-origin tabs (Spectre + tabnabbing
   defence — [MDN](https://developer.mozilla.org/en-US/docs/Web/HTTP/Cross-Origin-Opener-Policy)).
   We don't legitimately need a cross-origin opener (VSCode webview
   has its own isolation via ``vscode-webview://``), so this is
   zero-cost hardening.

These are reverse-locks — if a future PR ever:

- restores ``X-XSS-Protection: 1; mode=block`` (regressing back to
  pre-2024 best practice that already turned out to be footgun-y),
- or removes the COOP header entirely,

this test fails with a direct pointer to the round-16.3 commit
rationale.

Both checks are AST/string-level on the source file (no Flask app
spin-up needed) so they run in <50ms.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SECURITY_MODULE = REPO_ROOT / "web_ui_security.py"


class TestModernSecurityHeaders(unittest.TestCase):
    """``web_ui_security.SecurityMixin.setup_security_headers`` 的现代头契约。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.src = SECURITY_MODULE.read_text(encoding="utf-8")

    def test_xss_protection_explicitly_disabled(self) -> None:
        """``X-XSS-Protection`` 必须显式设为 ``"0"``。

        历史 ``"1; mode=block"`` 在现代浏览器是 no-op、在遗留浏览器
        反而打开 auditor-XSS 攻击面；``"0"`` 是 OWASP / Mozilla
        Observatory 当前推荐。
        """
        # 必须出现 "X-XSS-Protection" 头设置（防止有人误删整行）
        self.assertIn(
            'response.headers["X-XSS-Protection"]',
            self.src,
            "web_ui_security.py 应保留 X-XSS-Protection 头声明（值为 '0'）",
        )
        # 必须显式赋值为 "0"
        self.assertIn(
            'response.headers["X-XSS-Protection"] = "0"',
            self.src,
            "X-XSS-Protection 必须显式设为 '0'（让 CSP 接管 XSS 防御）；"
            "历史 '1; mode=block' 在现代浏览器是 no-op、在遗留浏览器反而"
            "打开 auditor-XSS 攻击面（OWASP Secure Headers Project 现行建议）",
        )

    def test_xss_protection_does_not_use_legacy_value(self) -> None:
        """Reverse-lock：不能再出现 ``"1; mode=block"`` / ``"1"`` 这些
        遗留值。"""
        self.assertNotIn(
            'response.headers["X-XSS-Protection"] = "1; mode=block"',
            self.src,
            "X-XSS-Protection 已从 '1; mode=block' 改为 '0'。如果你正在"
            "回退本变更，请先阅读 round-16.3 commit message（auditor 自身"
            "可被武器化做 XSS）；如果只是 typo，请改回 '0'。",
        )
        # 也禁单独的 "1"
        match = re.search(
            r'response\.headers\["X-XSS-Protection"\]\s*=\s*"1(?:\s|;|"|$)',
            self.src,
        )
        self.assertIsNone(
            match,
            "X-XSS-Protection 不应取 '1' 系列任何变体（'1' / '1; mode=block' / "
            "'1; report=...'）—— 这些都启用了已废弃的 auditor。",
        )

    def test_coop_same_origin_present(self) -> None:
        """``Cross-Origin-Opener-Policy: same-origin`` 必须存在。

        切断 ``window.opener`` 句柄、防 Spectre 类侧信道 + tabnabbing；
        我们的 Web UI 没有合法 cross-origin opener 用例。
        """
        self.assertIn(
            'response.headers["Cross-Origin-Opener-Policy"] = "same-origin"',
            self.src,
            "web_ui_security.py 必须设置 Cross-Origin-Opener-Policy: "
            "same-origin（Spectre + tabnabbing 防御）。如确认需要 popup "
            "互通，可改为 'same-origin-allow-popups'，但禁用是不可接受的"
            "回退（参见 MDN COOP 指南）。",
        )

    def test_coop_does_not_use_unsafe_none(self) -> None:
        """Reverse-lock：``COOP: unsafe-none`` 等同于不设，应禁止。"""
        self.assertNotIn(
            'response.headers["Cross-Origin-Opener-Policy"] = "unsafe-none"',
            self.src,
            "COOP=unsafe-none 等同于关闭防御（恢复默认浏览器行为，"
            "保留 opener handle）。如确实需要 popup 互通，请用 "
            "'same-origin-allow-popups'。",
        )

    def test_csp_remains_nonce_based(self) -> None:
        """sanity check：本次 R16.3 不应触动 CSP 主体（已被
        ``test_csp_allows_importmap_nonce`` 锁住）。"""
        self.assertIn(
            "script-src 'self' 'nonce-",
            self.src,
            "round-16.3 调整了 X-XSS-Protection 和加 COOP，**不**应触动"
            "CSP nonce 主体。如果这条 fail 了，说明本次 commit 越界。",
        )

    def test_existing_headers_not_regressed(self) -> None:
        """sanity check：``X-Frame-Options: DENY`` 与
        ``X-Content-Type-Options: nosniff`` 仍在。

        Round-16.3 不应顺手删任何旧头。
        """
        self.assertIn(
            'response.headers["X-Frame-Options"] = "DENY"',
            self.src,
            "X-Frame-Options 不能在 round-16.3 中被误删；它是 clickjacking "
            "防御的基础，与 CSP frame-ancestors 互为冗余。",
        )
        self.assertIn(
            'response.headers["X-Content-Type-Options"] = "nosniff"',
            self.src,
            "X-Content-Type-Options 不能在 round-16.3 中被误删；防 MIME "
            "sniffing 攻击。",
        )
        self.assertIn(
            'response.headers["Referrer-Policy"]',
            self.src,
            "Referrer-Policy 不能在 round-16.3 中被误删。",
        )
        self.assertIn(
            'response.headers["Permissions-Policy"]',
            self.src,
            "Permissions-Policy 不能在 round-16.3 中被误删。",
        )


if __name__ == "__main__":
    unittest.main()
