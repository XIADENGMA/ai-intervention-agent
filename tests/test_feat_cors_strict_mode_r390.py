"""R390 · CORS strict mode invariant — Security header strict mode
3rd app (cycle-44 #A2, **Security header 维度达 3 应用工业化阈值**)。

R376 (1st, top-level header 锁定) + R386 (2nd, CSP 内核 directive 锁
定) 之后, R390 锁 **CORS** 配置 strict mode, 完成 3 应用工业化阈值。

CORS (Cross-Origin Resource Sharing) 配置错误是 web 安全的常见 P0 漏
洞:

- ``origins="*"`` + ``supports_credentials=True`` → 任意网站可以带凭
  证读用户数据 (典型 origin reflection 攻击);
- ``Access-Control-Allow-Origin: *`` + 敏感 endpoint → 任意网站可以
  exfil 数据;
- ``Allow-Methods: *`` + ``Allow-Headers: *`` → 攻击面无限扩大;
- ``Access-Control-Max-Age`` 过大 → preflight 缓存让安全策略变更滞后
  生效;

R390 锁定 ``flask_cors.CORS()`` 调用的安全参数:

- ``supports_credentials=False`` 不能改成 ``True`` (除非配 explicit
  origin allowlist, 当前 codebase 没有此需求)
- ``origins`` 必须是 **closed list / Pattern**, 不能是 ``"*"`` / ``True``
  / ``None`` (即不能 wildcard)
- 必须包含 ``http://localhost`` / ``http://127.0.0.1`` / ``vscode-webview://``
  3 类合法 origin

R390 invariant (3 层)
---------------------

1. **Layer 1 (Anchor)**: ``web_ui.py`` 必须 import ``flask_cors.CORS``
   + 必须 call ``CORS()`` 至少一次;
2. **Layer 2 (Source-level lock)**: ``CORS()`` 调用必须含
   ``supports_credentials=False`` 字面量, ``origins`` 参数必须是 list
   字面量 (不能是 ``"*"`` / ``True`` / 简单 string);
3. **Layer 3 (Runtime lock)**: ``Access-Control-Allow-Origin`` 响应头
   必须 echo 合法 origin (不能是 ``*``), ``Access-Control-Allow-Credentials``
   绝不能等于 ``true``;

methodology lineage
-------------------

R390 是 **Security header strict mode 维度 3rd 应用**, 与:
- R306 (CSP nonce 三层一致性)
- R376 (top-level header 锁定, 1st)
- R386 (CSP 内核 directive, 2nd)

并列, 完成 Security header **3 应用工业化阈值**。Security header
strict mode 维度从 cycle-42 启动到 cycle-44 工业化, 与
v3.7/v3.8/v3.9 等 pattern 维度并列。

CORS 与其他 security header 协同:
- CSP (R306/R376/R386) — 浏览器侧防 XSS;
- CORS (R390) — 浏览器侧防跨域数据 exfil;
- X-Frame-Options (R376) — 防 clickjacking;
- COOP (R376) — 防 Spectre + tabnabbing;

形成完整的 **same-origin / cross-origin / framing** 三大边界防御。
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
WEB_UI_PY = REPO_ROOT / "src" / "ai_intervention_agent" / "web_ui.py"

# 必须 import 的 CORS 库
REQUIRED_IMPORTS: set[str] = {"flask_cors.CORS", "CORS"}

# CORS() 调用必须含的安全字面量参数
REQUIRED_CORS_KWARGS: dict[str, str] = {
    "supports_credentials": "False",
}

# CORS origins 必须包含的合法 origin 字符串 substring
REQUIRED_ORIGIN_SUBSTRINGS: tuple[str, ...] = (
    "localhost",
    "127.0.0.1",
    "vscode-webview://",
)

# 禁止出现在 CORS origins 的弱化 value (即 wildcard / 真值)
FORBIDDEN_ORIGIN_VALUES: tuple[str, ...] = ("*",)


def _read_web_ui_source() -> str:
    return WEB_UI_PY.read_text(encoding="utf-8")


def _find_cors_call(text: str) -> ast.Call:
    """找 web_ui.py 内 ``CORS(self.app, ...)`` 调用 (第一次出现)。"""
    tree = ast.parse(text)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name) and func.id == "CORS":
                return node
    raise AssertionError("R390-L1: cannot find CORS(...) call in web_ui.py")


def _get_keyword_value_repr(call: ast.Call, name: str) -> str | None:
    """从 CORS 调用拿 keyword 参数的字面 repr。"""
    for kw in call.keywords:
        if kw.arg == name:
            return ast.unparse(kw.value)
    return None


def _get_origins_value(call: ast.Call) -> ast.expr | None:
    """从 CORS 调用提取 origins 参数 (kw or 位置)。"""
    for kw in call.keywords:
        if kw.arg == "origins":
            return kw.value
    return None


class TestLayer1Anchor:
    """Layer 1: web_ui.py import + 调用 CORS。"""

    def test_cors_imported(self):
        text = _read_web_ui_source()
        assert "from flask_cors import CORS" in text or (
            "flask_cors" in text and "CORS" in text
        ), "R390-L1: web_ui.py must import CORS from flask_cors"

    def test_cors_call_exists(self):
        text = _read_web_ui_source()
        call = _find_cors_call(text)
        assert call is not None, (
            "R390-L1: CORS(self.app, ...) call must exist in web_ui.py"
        )


class TestLayer2SourceLevelLock:
    """Layer 2: CORS 调用必须含安全参数 + origins 必须是 closed list。"""

    @pytest.fixture(scope="class")
    def cors_call(self) -> ast.Call:
        return _find_cors_call(_read_web_ui_source())

    def test_supports_credentials_false(self, cors_call):
        val = _get_keyword_value_repr(cors_call, "supports_credentials")
        assert val == "False", (
            f"R390-L2: CORS supports_credentials must be False, "
            f"got: {val!r}. Setting True without explicit origin "
            f"allowlist opens credentialed cross-origin attacks."
        )

    def test_origins_is_list_not_wildcard(self, cors_call):
        origins = _get_origins_value(cors_call)
        assert origins is not None, (
            "R390-L2: CORS must explicitly specify origins= "
            "(default is wildcard '*' which is unsafe)"
        )
        # origins 必须是直接 list/var-ref, 不能是 string literal "*"
        assert not (
            isinstance(origins, ast.Constant)
            and isinstance(origins.value, str)
            and origins.value == "*"
        ), "R390-L2: CORS origins='*' forbidden — opens to any site"
        assert not (isinstance(origins, ast.Constant) and origins.value is True), (
            "R390-L2: CORS origins=True forbidden (alias for '*')"
        )

    def test_origins_value_contains_required_substrings(self):
        """origins list 必须含 localhost / 127.0.0.1 / vscode-webview://。"""
        text = _read_web_ui_source()
        # 找 _cors_origins 字面定义行 + 接下来一直读到匹配的 ``]``
        anchor = text.find("_cors_origins")
        assert anchor >= 0, "R390-L2: cannot find _cors_origins anchor in web_ui.py"
        # 从 anchor 开始定位 ``= [``, 然后取到最近的 ``]``
        bracket_open = text.find("= [", anchor)
        assert bracket_open >= 0, (
            "R390-L2: cannot find ``= [`` after _cors_origins anchor"
        )
        bracket_close = text.find("]", bracket_open)
        assert bracket_close >= 0, (
            "R390-L2: cannot find closing ``]`` for _cors_origins list"
        )
        origins_text = text[bracket_open + 3 : bracket_close]
        for needed in REQUIRED_ORIGIN_SUBSTRINGS:
            assert needed in origins_text, (
                f"R390-L2: _cors_origins missing required substring "
                f"{needed!r} (got: {origins_text[:300]}...)"
            )


class TestLayer3RuntimeLock:
    """Layer 3: 实际 HTTP 响应 CORS header 不能是 wildcard / credentials true。"""

    @pytest.fixture(scope="class")
    def runtime_cors_headers(self) -> dict[str, str]:
        """启动 minimal Flask app + CORS, 拿到 ``/`` OPTIONS preflight 响应 header。"""
        import re as _re

        from flask import Flask
        from flask_cors import CORS as _CORS

        app = Flask(__name__)
        _cors_origins: list = [
            "http://localhost:8095",
            "http://127.0.0.1:8095",
            _re.compile(r"^vscode-webview://"),
        ]
        _CORS(app, origins=_cors_origins, supports_credentials=False)

        @app.route("/_r390_probe", methods=["GET", "OPTIONS"])
        def _probe():
            return "ok"

        client = app.test_client()
        resp = client.get(
            "/_r390_probe",
            headers={"Origin": "http://localhost:8095"},
        )
        return dict(resp.headers)

    def test_acao_not_wildcard(self, runtime_cors_headers):
        acao = runtime_cors_headers.get("Access-Control-Allow-Origin", "")
        # 当 Origin 头来自合法 origin, ACAO 必须 echo 该 origin (不能是 "*")
        # 也允许 ACAO 不存在 (Flask CORS 在 origin 不匹配时不设头)
        assert acao != "*", (
            f"R390-L3: Access-Control-Allow-Origin must NOT be wildcard "
            f"'*' when origins is a closed list. Got: {acao!r}"
        )

    def test_aca_credentials_not_true(self, runtime_cors_headers):
        acac = runtime_cors_headers.get("Access-Control-Allow-Credentials", "")
        assert acac.lower() != "true", (
            f"R390-L3: Access-Control-Allow-Credentials must NOT be "
            f"'true' (matches source supports_credentials=False). "
            f"Got: {acac!r}"
        )

    def test_acao_echoes_legal_origin(self, runtime_cors_headers):
        acao = runtime_cors_headers.get("Access-Control-Allow-Origin", "")
        if acao:
            assert acao == "http://localhost:8095", (
                f"R390-L3: when ACAO is set, must echo request Origin "
                f"exactly. Got: {acao!r}, expected: "
                f"'http://localhost:8095'"
            )


class TestR390LineageMarker:
    """Methodology lineage 引用必须保留。"""

    def test_this_file_contains_r390_marker(self):
        text = Path(__file__).read_text(encoding="utf-8")
        assert "R390" in text

    def test_this_file_references_lineage(self):
        text = Path(__file__).read_text(encoding="utf-8")
        for prior in ("R306", "R376", "R386"):
            assert prior in text, f"R390: must cite related lineage: {prior}"

    def test_this_file_marks_3rd_app(self):
        text = Path(__file__).read_text(encoding="utf-8")
        for kw in ("Security header strict mode 3rd app", "工业化阈值"):
            assert kw in text, f"R390: missing keyword: {kw!r}"
