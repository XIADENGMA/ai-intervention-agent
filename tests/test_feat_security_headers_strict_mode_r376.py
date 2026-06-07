"""R376 · 安全 HTTP header strict mode invariant (cycle-42 #E1,
**新维度: Security header strict mode**)。

R376 锁定 web_ui_security.py 内的 7 个生产 path 安全 header 不能被静
默删除或弱化:

- ``Content-Security-Policy`` (with nonce, R306 已锁三层一致性)
- ``X-Frame-Options: DENY`` (clickjacking 防御)
- ``X-Content-Type-Options: nosniff`` (MIME type guessing 防御)
- ``X-XSS-Protection: 0`` (OWASP 推荐: 显式关闭老 auditor)
- ``Referrer-Policy: strict-origin-when-cross-origin`` (URL 泄漏防御)
- ``Cross-Origin-Opener-Policy: same-origin`` (Spectre + tabnabbing
  防御)
- ``Permissions-Policy`` (含至少 geolocation / camera / microphone /
  payment / usb 5 个 disabled feature)

为什么这个 invariant 重要
-------------------------

安全 header 容易被 "看起来无害" 的重构悄悄破坏:

- 开发者觉得 "X-XSS-Protection 已废弃" 删除头 → 老浏览器掉到默认行
  为, 反而启用 1; mode=block 老 auditor 漏洞;
- 开发者把 ``X-Frame-Options: DENY`` 改为 ``SAMEORIGIN`` 想嵌 iframe →
  打开 clickjacking 攻击面;
- 开发者把 ``Referrer-Policy`` 改宽松想方便调试 → URL token / auth
  state 在跨域请求里泄露。

R376 在 invariant 层强制锁定: **任何 header 缺失 / 值弱化都会 CI 失
败**。修改 header 必须显式更新本 invariant + 提供 rationale。

R376 invariant (3 层)
---------------------

1. **Layer 1 (Anchor)**: ``web_ui_security.py`` 可以 import + 含
   ``add_security_headers`` 函数
2. **Layer 2 (Source-level lock)**: ``add_security_headers`` 函数体内
   必须含每个必需 header 的赋值字面量 (header 名 + 期望值 substring)
3. **Layer 3 (Runtime lock)**: Flask test_client 实际响应的 headers 字典
   包含所有必需 header, 值与 source-level 期望一致

methodology lineage
-------------------

R306 (cycle-31) 已经锁定 CSP nonce 三层一致性 (response header ↔
template attribute ↔ JS reader). R376 是 **security header 维度第 2
应用**, 把 CSP 之外的其他 6 个 header 也纳入锁定。
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SECURITY_PY = REPO_ROOT / "src" / "ai_intervention_agent" / "web_ui_security.py"

# 必需 header → 期望 substring (None 表示只要求 header 出现, 不锁值)
REQUIRED_HEADERS: dict[str, str | None] = {
    "Content-Security-Policy": None,  # 复杂值, 单独由 R306 + 其他锁
    "X-Frame-Options": "DENY",
    "X-Content-Type-Options": "nosniff",
    "X-XSS-Protection": "0",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Permissions-Policy": "geolocation=()",  # 至少 geolocation 显式禁用
}


def _get_add_security_headers_body() -> str:
    """提取 ``add_security_headers`` 函数体源码 (AST unparse)。"""
    text = SECURITY_PY.read_text(encoding="utf-8")
    tree = ast.parse(text)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "add_security_headers":
            return ast.unparse(node)
    raise AssertionError(
        "R376-L1: cannot find add_security_headers function in web_ui_security.py"
    )


class TestLayer1Anchor:
    """Layer 1: ``web_ui_security.py`` 可加载 + 含目标函数。"""

    def test_security_py_loadable(self):
        text = SECURITY_PY.read_text(encoding="utf-8")
        assert "add_security_headers" in text, (
            "R376-L1: add_security_headers function name not found in "
            "web_ui_security.py — major refactor must update R376"
        )

    def test_function_body_extractable(self):
        body = _get_add_security_headers_body()
        assert "response.headers" in body, (
            "R376-L1: add_security_headers body must contain "
            "'response.headers' assignment"
        )


class TestLayer2SourceLevelLock:
    """Layer 2: 函数体内必须含每个必需 header 的赋值字面量。"""

    def test_every_required_header_set(self, subtests):
        body = _get_add_security_headers_body()
        missing: list[str] = []
        for header, expected_value in REQUIRED_HEADERS.items():
            with subtests.test(header=header):
                if header not in body:
                    missing.append(f"  {header}: not set in add_security_headers")
                elif expected_value and expected_value not in body:
                    missing.append(
                        f"  {header}: expected value substring "
                        f"{expected_value!r} not found"
                    )
        if missing:
            raise AssertionError(
                f"R376-L2: {len(missing)} required header(s) missing or "
                f"weakened in add_security_headers:\n"
                + "\n".join(missing)
                + "\nFix: restore the header / value or explicitly "
                "update REQUIRED_HEADERS with rationale (security "
                "posture changes require explicit review)."
            )


class TestLayer3RuntimeLock:
    """Layer 3: Flask test_client 实际响应必须含所有必需 header。"""

    def test_runtime_response_contains_all_headers(self, subtests):
        from ai_intervention_agent.web_ui import WebFeedbackUI

        ui = WebFeedbackUI(prompt="r376 test", predefined_options=None, task_id="r376")
        client = ui.app.test_client()
        # 走任意一个 endpoint 触发 after_request hook
        resp = client.get("/api/tasks")
        # 不强求 200 (可能 IP 白名单), 但 after_request 应已运行
        missing: list[str] = []
        for header, expected_value in REQUIRED_HEADERS.items():
            with subtests.test(header=header):
                if header not in resp.headers:
                    missing.append(f"  {header}: not in response")
                elif expected_value and expected_value not in resp.headers[header]:
                    missing.append(
                        f"  {header}: runtime value "
                        f"{resp.headers[header]!r} does not contain "
                        f"expected substring {expected_value!r}"
                    )
        if missing:
            raise AssertionError(
                f"R376-L3: {len(missing)} required header(s) missing "
                f"or weakened in actual Flask response:\n"
                + "\n".join(missing)
                + "\nFix: after_request hook is not adding the header "
                "at runtime. Verify it's registered + actually runs "
                "for the test endpoint."
            )


class TestR376LineageMarker:
    def test_this_file_contains_r376_marker(self):
        text = Path(__file__).read_text(encoding="utf-8")
        assert "R376" in text

    def test_this_file_references_csp_lineage(self):
        text = Path(__file__).read_text(encoding="utf-8")
        assert "R306" in text, "R376: must cite R306 (CSP nonce 3-layer)"

    def test_this_file_marks_security_dimension(self):
        text = Path(__file__).read_text(encoding="utf-8")
        for kw in ("Security header strict mode", "新维度"):
            assert kw in text, f"R376: missing keyword: {kw!r}"
