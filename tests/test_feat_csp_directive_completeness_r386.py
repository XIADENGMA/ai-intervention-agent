"""R386 · CSP directive 完整性 invariant — Security header strict mode
2nd app (cycle-43 扩展 #2, **Security header 维度进入巩固期**)。

R376 (1st app) 锁定 web_ui_security 内 7 个 top-level 安全 header 的
**存在 + 关键值**。但 ``Content-Security-Policy`` 是单一 header **内部
包含 10 个 directive**, R376 只锁外壳 (header 出现 + nonce 模式), 没锁
**内部每个 directive 的完整性和值**。

风险:
- 开发者重构 ``_CSP_SUFFIX`` 时把 ``frame-ancestors 'none'`` 不小心去
  掉 → clickjacking 防御失效 (而 R376 仍 pass, 因为 CSP header 还在);
- 把 ``object-src 'none'`` 改宽松 → Flash/<object> XSS 攻击面打开;
- 把 ``script-src 'self' 'nonce-...'`` 改成 ``script-src 'self' 'unsafe-inline'``
  → CSP 防护被完全旁路 (R306 nonce 三层一致性虽然 pass, 但 attacker
  可以注入 inline script);
- ``base-uri 'self'`` 漏配 → ``<base href>`` 攻击 (CRLF / URL hijack);
- ``connect-src 'self'`` 漏配 → 任意 origin 可被 XHR exfil 走。

R386 invariant 强制锁定 **CSP 完整的 10 directive + 关键值字面量**, 任
何 directive 被删除 / 弱化 → 立即 CI fail。

R386 invariant (3 层)
---------------------

1. **Layer 1 (Anchor)**: ``web_ui_security.py`` 内 ``_CSP_PREFIX`` 与
   ``_CSP_SUFFIX`` 常量字符串可加载, ``_build_csp_header(nonce)`` 拼出
   的完整 CSP 字符串至少含 10 个 directive ('; ' 分隔);
2. **Layer 2 (Source-level lock)**: 完整 CSP 字符串包含 10 个必需
   directive, 每个 directive 的 keyword + 关键 source-expression 值
   (e.g., ``frame-ancestors 'none'`` 不能放宽到 ``'self'``);
3. **Layer 3 (Runtime lock)**: Flask test_client 实际响应 CSP header
   包含同样 10 个 directive (反向验证: source 改了不漏到 runtime, runtime
   改 monkey-patch 不漏到 source 校验);

methodology lineage
-------------------

R386 是 **Security header strict mode 维度 2nd 应用**, 与:
- R306 (CSP nonce 三层一致性, response header ↔ template ↔ JS reader)
- R376 (Security header 1st, 7 top-level header 锁定)

形成 "Security header 三层完整覆盖": 1. nonce 同步 (R306), 2. 必需
header 存在 + 值 (R376), 3. **CSP 内部 directive 完整性** (R386)。

进入巩固期标志: 维度从 1 应用 (单点) → 2 应用 (互补) → 3 应用 (工业
化), 当前在 2 应用 → 3 应用过渡阶段。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SECURITY_PY = REPO_ROOT / "src" / "ai_intervention_agent" / "web_ui_security.py"

# CSP 10 个必需 directive + 关键值要求
# - "value" 为字面 substring (必须出现在 directive 后)
# - "must_not" 为禁用 source-expression (出现即视为弱化)
REQUIRED_CSP_DIRECTIVES: dict[str, dict[str, list[str]]] = {
    "default-src": {"value": ["'self'"], "must_not": ["'unsafe-inline'", "*"]},
    "script-src": {
        "value": ["'self'", "'nonce-"],
        "must_not": ["'unsafe-inline'", "'unsafe-eval'"],
    },
    "style-src": {
        # ``'unsafe-inline'`` 当前显式接受 (前端 ``<style>`` 大量内嵌),
        # R386 接受现状, R306 锁了 nonce 路径作为补强
        "value": ["'self'"],
        "must_not": ["*"],
    },
    "img-src": {"value": ["'self'", "data:", "blob:"], "must_not": []},
    "font-src": {"value": ["'self'", "data:"], "must_not": ["*"]},
    "connect-src": {"value": ["'self'"], "must_not": ["*"]},
    "worker-src": {"value": ["'self'"], "must_not": ["*"]},
    "frame-ancestors": {
        # clickjacking 防御核心: must be 'none' 不能放宽到 'self'
        "value": ["'none'"],
        "must_not": ["'self'", "*"],
    },
    "base-uri": {
        # base 标签注入防御: must be 'self' 或 'none'
        "value": ["'self'"],
        "must_not": ["*"],
    },
    "object-src": {
        # Flash/<object> XSS 防御核心: must be 'none'
        "value": ["'none'"],
        "must_not": ["'self'", "*"],
    },
}


def _build_full_csp() -> str:
    """读 _CSP_PREFIX + _CSP_SUFFIX, 拼出完整 CSP 字符串 (含示意 nonce)。"""
    text = SECURITY_PY.read_text(encoding="utf-8")
    prefix_match = re.search(r"_CSP_PREFIX\s*:\s*str\s*=\s*\"([^\"]+)\"", text)
    if not prefix_match:
        raise AssertionError(
            "R386-L1: cannot extract _CSP_PREFIX literal from web_ui_security.py"
        )
    suffix_match = re.search(
        r"_CSP_SUFFIX\s*:\s*str\s*=\s*\(([^)]+)\)",
        text,
        re.DOTALL,
    )
    if not suffix_match:
        raise AssertionError(
            "R386-L1: cannot extract _CSP_SUFFIX literal from web_ui_security.py"
        )
    suffix_raw = suffix_match.group(1)
    suffix_parts = re.findall(r"\"([^\"]+)\"", suffix_raw)
    suffix = "".join(suffix_parts)
    return prefix_match.group(1) + "SAMPLENONCE" + suffix


def _split_directives(csp: str) -> dict[str, str]:
    """把 CSP 字符串切成 {directive_name: directive_value} 字典。"""
    out: dict[str, str] = {}
    for part in csp.split(";"):
        part = part.strip()
        if not part:
            continue
        tokens = part.split(None, 1)
        if not tokens:
            continue
        name = tokens[0]
        value = tokens[1] if len(tokens) > 1 else ""
        out[name] = value
    return out


class TestLayer1Anchor:
    """Layer 1: _CSP_PREFIX / _CSP_SUFFIX 常量可加载, 完整 CSP 至少 10 directive。"""

    def test_csp_constants_loadable(self):
        full = _build_full_csp()
        assert "default-src" in full, "R386-L1: CSP must contain default-src"
        assert "script-src" in full, "R386-L1: CSP must contain script-src"
        assert "SAMPLENONCE" in full, (
            "R386-L1: nonce placeholder must be in CSP (prefix/suffix concat)"
        )

    def test_at_least_10_directives(self):
        directives = _split_directives(_build_full_csp())
        assert len(directives) >= 10, (
            f"R386-L1: only {len(directives)} CSP directives, "
            f"expected >= 10. Refactor must update "
            f"REQUIRED_CSP_DIRECTIVES."
        )


class TestLayer2SourceLevelLock:
    """Layer 2: 完整 CSP 字符串含每个必需 directive + 关键值, 无弱化。"""

    @pytest.fixture(scope="class")
    def directives(self) -> dict[str, str]:
        return _split_directives(_build_full_csp())

    def test_every_required_directive_present(self, directives, subtests):
        for name in REQUIRED_CSP_DIRECTIVES:
            with subtests.test(directive=name):
                assert name in directives, (
                    f"R386-L2: required CSP directive '{name}' missing. "
                    f"Restore in _CSP_PREFIX / _CSP_SUFFIX."
                )

    def test_directive_required_values(self, directives, subtests):
        violations: list[str] = []
        for name, spec in REQUIRED_CSP_DIRECTIVES.items():
            if name not in directives:
                continue
            value = directives[name]
            for needed in spec["value"]:
                with subtests.test(directive=name, value=needed):
                    if needed not in value:
                        violations.append(
                            f"  {name}: missing required value '{needed}'"
                            f" (got: '{value}')"
                        )
        if violations:
            raise AssertionError(
                f"R386-L2: {len(violations)} required CSP value(s) "
                f"missing:\n" + "\n".join(violations)
            )

    def test_directive_forbidden_values_absent(self, directives, subtests):
        violations: list[str] = []
        for name, spec in REQUIRED_CSP_DIRECTIVES.items():
            if name not in directives:
                continue
            value = directives[name]
            for forbidden in spec["must_not"]:
                with subtests.test(directive=name, forbidden=forbidden):
                    if forbidden in value:
                        violations.append(
                            f"  {name}: weakened by forbidden value "
                            f"'{forbidden}' (got: '{value}')"
                        )
        if violations:
            raise AssertionError(
                f"R386-L2: {len(violations)} CSP directive(s) weakened "
                f"by forbidden values:\n" + "\n".join(violations)
            )


class TestLayer3RuntimeLock:
    """Layer 3: Flask test_client 响应 CSP header 含同样 10 directive。"""

    @pytest.fixture(scope="class")
    def runtime_csp(self) -> str:
        """启动 minimal Flask app, 拿到 ``/`` 响应的 CSP header。"""
        from flask import Flask

        from ai_intervention_agent.web_ui_security import SecurityMixin

        class _DummySecurityApp(SecurityMixin):
            def __init__(self):
                self.app = Flask(__name__)
                self.host = "127.0.0.1"
                self.network_security_config = {"access_control_enabled": False}
                self.setup_security_headers()

                @self.app.route("/_r386_probe")
                def _probe():
                    return "ok"

        dummy = _DummySecurityApp()
        client = dummy.app.test_client()
        resp = client.get("/_r386_probe")
        csp = resp.headers.get("Content-Security-Policy", "")
        if not csp:
            raise AssertionError("R386-L3: runtime CSP header empty / not set")
        return csp

    def test_runtime_csp_has_all_directives(self, runtime_csp, subtests):
        directives = _split_directives(runtime_csp)
        for name in REQUIRED_CSP_DIRECTIVES:
            with subtests.test(directive=name):
                assert name in directives, (
                    f"R386-L3: runtime CSP missing directive '{name}' "
                    f"despite source check passing. Possible monkey-"
                    f"patch / runtime override?"
                )

    def test_runtime_csp_directive_values_match(self, runtime_csp, subtests):
        directives = _split_directives(runtime_csp)
        violations: list[str] = []
        for name, spec in REQUIRED_CSP_DIRECTIVES.items():
            if name not in directives:
                continue
            value = directives[name]
            for needed in spec["value"]:
                with subtests.test(directive=name, value=needed):
                    if needed not in value:
                        violations.append(
                            f"  {name}: missing '{needed}' at runtime (got: '{value}')"
                        )
        if violations:
            raise AssertionError(
                f"R386-L3: {len(violations)} runtime CSP value(s) "
                f"missing:\n" + "\n".join(violations)
            )


class TestR386LineageMarker:
    """Methodology lineage 引用必须保留。"""

    def test_this_file_contains_r386_marker(self):
        text = Path(__file__).read_text(encoding="utf-8")
        assert "R386" in text

    def test_this_file_references_lineage(self):
        text = Path(__file__).read_text(encoding="utf-8")
        for prior in ("R306", "R376"):
            assert prior in text, f"R386: must cite related lineage: {prior}"

    def test_this_file_marks_2nd_app(self):
        text = Path(__file__).read_text(encoding="utf-8")
        for kw in ("Security header strict mode 2nd app", "巩固期"):
            assert kw in text, f"R386: missing keyword: {kw!r}"
