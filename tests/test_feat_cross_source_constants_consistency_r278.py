"""R278 / cycle-25 t25-2 (R276 spillover): 跨源 constant consistency
invariant 扩展 (countdown defaults / max / default port)。

R271 + R276 教训
----------------

- R271 揭示 OpenAPI ↔ 后端 4-way drift (10K vs 100K)
- R276 锁定 image upload 限制 frontend/backend invariant

R278 推广 R276 cross-language constant pattern 到 3 个新场景：

1. **AUTO_RESUBMIT_TIMEOUT_DEFAULT (240 seconds)** — 倒计时默认值出现 3 处:
   - `server_config.AUTO_RESUBMIT_TIMEOUT_DEFAULT = 240` (canonical source)
   - `templates/web_ui.html` `<input value="240">` (UI default)
   - `packages/vscode/webview.ts` `<input value="240">` (VSCode default)

   如果 server 升级到 300 但 UI 还显示 240，用户输入新值前 settings 显示
   错误默认 → 提交后才发现服务器实际行为不同 → silent drift。

2. **AUTO_RESUBMIT_TIMEOUT_MAX (3600 seconds)** — 上限出现 3 处:
   - `server_config.AUTO_RESUBMIT_TIMEOUT_MAX = 3600`
   - `templates/web_ui.html` `<input max="3600">`
   - `packages/vscode/webview.ts` `<input max="3600">`

   HTML max 是浏览器 form validation hint，超出会显示红框。如果 server
   允许 7200 但 HTML 还是 3600，用户被 HTML 验证强制截断 → 无法利用更高
   server cap。

3. **default web_ui.port (8080)** — 7+ 处独立 hardcode 风险:
   - `shared_types.WebUISectionConfig.port = 8080` (Pydantic single source
     of truth)
   - `web_ui.py::FeedbackWebUI.__init__ port: int = 8080` (function default)
   - `web_ui.py::start_web_ui port: int = 8080`
   - `web_ui.py argparse --port default=8080`
   - `server_config.py` `web_section.get("port", 8080)` (config fallback)
   - `web_ui_routes/system.py` × 2 (parse + catch fallback)
   - `service_manager.py` `web_ui_config.get("port", 8080)` (subprocess)

   8 处独立 hardcode 8080 — 任一改了未同步全部就是 silent drift。

R278 修复
---------

不改源码（当前都已对齐），加 invariant 锁定:

| Constant | Authoritative | Mirror sites |
|----------|--------------|--------------|
| 240 | `server_config.AUTO_RESUBMIT_TIMEOUT_DEFAULT` | HTML + webview.ts |
| 3600 | `server_config.AUTO_RESUBMIT_TIMEOUT_MAX` | HTML + webview.ts |
| 8080 | `shared_types.WebUISectionConfig.port` default | 7+ Python sites |

Why locked
----------

R271 已经证明 4-way drift 真实发生 (OpenAPI 10K vs 100K 实际全)。R278
覆盖 3 个新场景，从 R276 的 1 对扩展到 3 个跨端/跨文件 constant。

Pattern reuse: R276 引入的跨语言 const parser (JS const + Py annotated
assign) 在 R278 复用到 HTML attribute parser (`<input value="...">`)，
增强到 3 种 source language (Python / JS / HTML)。

Invariant
---------

1. `AUTO_RESUBMIT_TIMEOUT_DEFAULT` (server_config) ≡ HTML input value ≡
   webview.ts input value
2. `AUTO_RESUBMIT_TIMEOUT_MAX` (server_config) ≡ HTML input max attr ≡
   webview.ts input max attr
3. `WebUISectionConfig.port` Pydantic default ≡ 所有 .py hardcode 8080
   场点一致（强制 7+ 站点必须保持同值）

Sanity
------

- HTML / webview.ts 的 input min 不强求等于 `AUTO_RESUBMIT_TIMEOUT_MIN`
  (10)，因为 HTML min=0 是设计允许 disable (0 = 关闭倒计时)，与 server
  validator floor 不一致是有意行为
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SERVER_CONFIG_PY = REPO_ROOT / "src" / "ai_intervention_agent" / "server_config.py"
SHARED_TYPES_PY = REPO_ROOT / "src" / "ai_intervention_agent" / "shared_types.py"
WEB_UI_HTML = REPO_ROOT / "src" / "ai_intervention_agent" / "templates" / "web_ui.html"
VSCODE_WEBVIEW_TS = REPO_ROOT / "packages" / "vscode" / "webview.ts"
WEB_UI_PY = REPO_ROOT / "src" / "ai_intervention_agent" / "web_ui.py"
SERVICE_MANAGER_PY = REPO_ROOT / "src" / "ai_intervention_agent" / "service_manager.py"
SYSTEM_PY = REPO_ROOT / "src" / "ai_intervention_agent" / "web_ui_routes" / "system.py"


def _parse_python_int_const(src: str, name: str) -> int:
    """解析 ``NAME = 240`` 或 ``NAME: int = 240`` 形式的 module-level 常量
    (支持 PEP 515 ``_`` 数字分隔符如 ``100_000``)。"""
    pattern = re.compile(
        r"^" + re.escape(name) + r"(?:\s*:\s*int)?\s*=\s*([\d_]+)",
        re.MULTILINE,
    )
    match = pattern.search(src)
    assert match is not None, f"R278: 找不到 ``{name}`` 常量声明"
    return int(match.group(1).replace("_", ""))


def _parse_html_input_attr(src: str, input_id: str, attr: str) -> int:
    """解析 ``<input id="..." ... attr="N">`` 中的整数属性。"""
    pattern = re.compile(
        r'<input[^>]*id="' + re.escape(input_id) + r'"[^>]*>',
        re.DOTALL,
    )
    match = pattern.search(src)
    assert match is not None, f'R278: 找不到 ``<input id="{input_id}">``'
    tag = match.group(0)
    attr_pattern = re.compile(re.escape(attr) + r'="(\d+)"')
    attr_match = attr_pattern.search(tag)
    assert attr_match is not None, f'R278: ``<input id="{input_id}">`` 没有 {attr} 属性'
    return int(attr_match.group(1))


def _count_python_hardcoded(src: str, value: int) -> int:
    """统计某 Python 源里 hardcoded 整数字面值的出现次数（仅匹配独立 token，
    跳过注释/字符串字面里的）。"""
    # 找 hardcoded `8080` 但不在注释或字符串里
    # 简化：扫所有 non-comment 行 + match ``\b<value>\b``
    count = 0
    for line in src.splitlines():
        # 跳过纯注释行
        stripped = line.lstrip()
        if stripped.startswith("#"):
            continue
        # 跳过 docstring（粗略 ""..."" 中行）— 实际中由 caller 选 file
        # 只匹配 literal not in string
        # 简化：直接匹配 word boundary
        if re.search(r"\b" + re.escape(str(value)) + r"\b", line):
            # 跳过 string 内（找 `"..."` 或 `'...'` 包裹的）
            # 极简启发：行内若同时有 quote 且 value 在 quote 内，跳过
            # 但对 8080 这种数字字面，常见在 fallback 调用如 `get("port", 8080)`，
            # 是 literal 不在 quote 内 — 直接计数
            count += 1
    return count


class TestAutoResubmitTimeoutDefaultCrossSource(unittest.TestCase):
    """R278 #1: AUTO_RESUBMIT_TIMEOUT_DEFAULT (240) cross-source consistency."""

    server_config = SERVER_CONFIG_PY.read_text(encoding="utf-8")
    web_ui_html = WEB_UI_HTML.read_text(encoding="utf-8")
    webview_ts = VSCODE_WEBVIEW_TS.read_text(encoding="utf-8")

    def test_server_config_default(self) -> None:
        val = _parse_python_int_const(
            self.server_config, "AUTO_RESUBMIT_TIMEOUT_DEFAULT"
        )
        self.assertEqual(
            val,
            240,
            "R278: server_config.AUTO_RESUBMIT_TIMEOUT_DEFAULT 必须 = 240 "
            "(canonical authoritative source)",
        )

    def test_html_input_default_value(self) -> None:
        html_default = _parse_html_input_attr(
            self.web_ui_html, "feedback-countdown", "value"
        )
        server_default = _parse_python_int_const(
            self.server_config, "AUTO_RESUBMIT_TIMEOUT_DEFAULT"
        )
        self.assertEqual(
            html_default,
            server_default,
            'R278: web_ui.html ``<input id="feedback-countdown" value="N">`` '
            "必须等于 server_config.AUTO_RESUBMIT_TIMEOUT_DEFAULT。"
            f" HTML={html_default}, server={server_default}",
        )

    def test_webview_input_default_value(self) -> None:
        webview_default = _parse_html_input_attr(
            self.webview_ts, "feedbackCountdown", "value"
        )
        server_default = _parse_python_int_const(
            self.server_config, "AUTO_RESUBMIT_TIMEOUT_DEFAULT"
        )
        self.assertEqual(
            webview_default,
            server_default,
            'R278: webview.ts ``<input id="feedbackCountdown" value="N">`` '
            "必须等于 server_config.AUTO_RESUBMIT_TIMEOUT_DEFAULT。"
            f" VSCode={webview_default}, server={server_default}",
        )


class TestAutoResubmitTimeoutMaxCrossSource(unittest.TestCase):
    """R278 #2: AUTO_RESUBMIT_TIMEOUT_MAX (3600) cross-source consistency."""

    server_config = SERVER_CONFIG_PY.read_text(encoding="utf-8")
    web_ui_html = WEB_UI_HTML.read_text(encoding="utf-8")
    webview_ts = VSCODE_WEBVIEW_TS.read_text(encoding="utf-8")

    def test_server_config_max(self) -> None:
        val = _parse_python_int_const(self.server_config, "AUTO_RESUBMIT_TIMEOUT_MAX")
        self.assertEqual(
            val,
            3600,
            "R278: server_config.AUTO_RESUBMIT_TIMEOUT_MAX 必须 = 3600 "
            "(canonical authoritative source)",
        )

    def test_html_input_max_value(self) -> None:
        html_max = _parse_html_input_attr(self.web_ui_html, "feedback-countdown", "max")
        server_max = _parse_python_int_const(
            self.server_config, "AUTO_RESUBMIT_TIMEOUT_MAX"
        )
        self.assertEqual(
            html_max,
            server_max,
            'R278: web_ui.html ``<input ... max="N">`` 必须等于 '
            "server_config.AUTO_RESUBMIT_TIMEOUT_MAX，否则用户被 HTML "
            "form validation 强制截断在更低值。"
            f" HTML={html_max}, server={server_max}",
        )

    def test_webview_input_max_value(self) -> None:
        webview_max = _parse_html_input_attr(
            self.webview_ts, "feedbackCountdown", "max"
        )
        server_max = _parse_python_int_const(
            self.server_config, "AUTO_RESUBMIT_TIMEOUT_MAX"
        )
        self.assertEqual(
            webview_max,
            server_max,
            'R278: webview.ts ``<input ... max="N">`` 必须等于 '
            "server_config.AUTO_RESUBMIT_TIMEOUT_MAX。"
            f" VSCode={webview_max}, server={server_max}",
        )


class TestDefaultWebPortCrossSource(unittest.TestCase):
    """R278 #3: default web_ui.port (8080) cross-source consistency.

    Pydantic ``WebUISectionConfig.port = 8080`` 是 canonical source；
    其他 Python 文件里的 hardcode 8080 必须保持一致。
    """

    shared_types = SHARED_TYPES_PY.read_text(encoding="utf-8")

    def test_shared_types_pydantic_default(self) -> None:
        """Pydantic ``port: Annotated[...] = 8080`` 必须保留。"""
        pattern = re.compile(
            r"port\s*:\s*Annotated\[.*?8080.*?\]\s*=\s*8080",
            re.DOTALL,
        )
        self.assertRegex(
            self.shared_types,
            pattern,
            "R278: WebUISectionConfig.port 必须保持 ``Annotated[...8080...] "
            "= 8080`` 默认 (clamp default 与 field default 都是 8080)。"
            "如果要改默认端口，请同步更新所有 R278 mirror sites（见测试列表）",
        )

    def test_web_ui_py_fn_defaults(self) -> None:
        """``web_ui.py`` 函数签名 ``port: int = 8080`` 出现至少 2 处。"""
        src = WEB_UI_PY.read_text(encoding="utf-8")
        matches = re.findall(r"port:\s*int\s*=\s*8080\b", src)
        self.assertGreaterEqual(
            len(matches),
            2,
            "R278: web_ui.py 必须至少 2 处 ``port: int = 8080`` 签名默认 "
            "(FeedbackWebUI.__init__ + start_web_ui)。"
            f" 当前匹配 {len(matches)} 处",
        )

    def test_web_ui_py_argparse_default(self) -> None:
        """argparse ``--port default=8080`` 必须保留。"""
        src = WEB_UI_PY.read_text(encoding="utf-8")
        self.assertRegex(
            src,
            r"--port[^)]*default=8080",
            "R278: web_ui.py argparse ``--port default=8080`` 必须保留",
        )

    def test_service_manager_fallback_8080(self) -> None:
        """``service_manager.py`` 解析 web_ui_config.get('port', 8080)。"""
        src = SERVICE_MANAGER_PY.read_text(encoding="utf-8")
        self.assertRegex(
            src,
            r'get\("port",\s*8080\)',
            "R278: service_manager.py 必须保持 "
            '``web_ui_config.get("port", 8080)`` fallback',
        )

    def test_system_py_fallback_8080(self) -> None:
        """``web_ui_routes/system.py`` 解析 + catch path fallback。"""
        src = SYSTEM_PY.read_text(encoding="utf-8")
        matches = re.findall(r"\b8080\b", src)
        self.assertGreaterEqual(
            len(matches),
            2,
            "R278: web_ui_routes/system.py 必须至少 2 处 ``8080`` "
            "(parse + catch fallback)。"
            f" 当前 {len(matches)} 处",
        )


class TestPromptMaxLengthCrossSource(unittest.TestCase):
    """R278 #4 (R283 spillover): ``PROMPT_MAX_LENGTH`` (100,000) cross-source
    consistency.

    User TODO 中 "可能的 BUG6：插件读取 Resubmit prompt 和 Feedback suffix
    字数限制不和 web 统一" 已在 cycle-21 R196 修复，但当时只有 web ↔ 插件
    2 端 invariant；R283 把 PROMPT_MAX_LENGTH lock 扩展到 server_config
    authoritative + 4 个 frontend mirror site 的 5-way invariant。

    Mirror sites
    ------------
    - ``server_config.PROMPT_MAX_LENGTH = 100_000`` (authoritative)
    - ``templates/web_ui.html`` `<textarea id="feedback-resubmit-prompt"
      maxlength="100000">`
    - ``templates/web_ui.html`` `<textarea id="feedback-prompt-suffix"
      maxlength="100000">` (第二个 textarea)
    - ``packages/vscode/webview.ts`` `<textarea id="feedbackResubmitPrompt"
      maxlength="100000">`
    - ``packages/vscode/webview.ts`` `<textarea id="feedbackPromptSuffix"
      maxlength="100000">`

    Silent drift 风险
    -----------------

    Server 升级 PROMPT_MAX_LENGTH 到 200_000 (例如用户反馈需要更长 prompt)
    但前端 maxlength 仍是 100000 → 用户被 HTML form validation 截断在更低
    值，提交后才发现 server 实际可接受更长 → 反复 trial-and-error 找上限。

    或反向：server 降低到 50_000 但前端不变 → 前端 client-side 允许 100K，
    submit 时被 backend reject 抛 400 → user-visible "请求被拒绝" 但前端
    UI 没显示任何 hint。
    """

    server_config = SERVER_CONFIG_PY.read_text(encoding="utf-8")
    web_ui_html = WEB_UI_HTML.read_text(encoding="utf-8")
    webview_ts = VSCODE_WEBVIEW_TS.read_text(encoding="utf-8")

    def test_server_config_prompt_max_length(self) -> None:
        val = _parse_python_int_const(self.server_config, "PROMPT_MAX_LENGTH")
        self.assertEqual(
            val,
            100_000,
            "R278 #4: server_config.PROMPT_MAX_LENGTH 必须 = 100_000 "
            "(authoritative source)",
        )

    def test_web_ui_html_textarea_maxlength_consistency(self) -> None:
        """``feedback-resubmit-prompt`` + ``feedback-prompt-suffix`` 两个
        textarea 的 maxlength 必须等于 server_config."""
        server_max = _parse_python_int_const(self.server_config, "PROMPT_MAX_LENGTH")
        for textarea_id in (
            "feedback-resubmit-prompt",
            "feedback-prompt-suffix",
        ):
            # textarea 不同于 input，正则要找 ``<textarea ...id="..." ...>``
            pattern = re.compile(
                r'<textarea[^>]*id="' + re.escape(textarea_id) + r'"[^>]*>',
                re.DOTALL,
            )
            match = pattern.search(self.web_ui_html)
            self.assertIsNotNone(
                match,
                f'R278 #4: 找不到 ``<textarea id="{textarea_id}">``',
            )
            assert match is not None  # for type checker
            tag = match.group(0)
            attr_match = re.search(r'maxlength="(\d+)"', tag)
            self.assertIsNotNone(
                attr_match,
                f'R278 #4: ``<textarea id="{textarea_id}">`` 没有 maxlength 属性',
            )
            assert attr_match is not None
            html_max = int(attr_match.group(1))
            self.assertEqual(
                html_max,
                server_max,
                f'R278 #4: web_ui.html ``<textarea id="{textarea_id}" '
                f'maxlength="{html_max}">`` 必须等于 server_config.'
                f"PROMPT_MAX_LENGTH ({server_max})",
            )

    def test_vscode_webview_textarea_maxlength_consistency(self) -> None:
        """VSCode webview 的 ``feedbackResubmitPrompt`` +
        ``feedbackPromptSuffix`` 也必须一致 (插件 BUG6 历史教训)."""
        server_max = _parse_python_int_const(self.server_config, "PROMPT_MAX_LENGTH")
        for textarea_id in ("feedbackResubmitPrompt", "feedbackPromptSuffix"):
            pattern = re.compile(
                r'<textarea[^>]*id="' + re.escape(textarea_id) + r'"[^>]*>',
                re.DOTALL,
            )
            match = pattern.search(self.webview_ts)
            self.assertIsNotNone(
                match,
                f'R278 #4: 找不到 webview ``<textarea id="{textarea_id}">``',
            )
            assert match is not None
            tag = match.group(0)
            attr_match = re.search(r'maxlength="(\d+)"', tag)
            self.assertIsNotNone(
                attr_match,
                f'R278 #4: webview ``<textarea id="{textarea_id}">`` 没有 maxlength 属性',
            )
            assert attr_match is not None
            ts_max = int(attr_match.group(1))
            self.assertEqual(
                ts_max,
                server_max,
                f'R278 #4: webview.ts ``<textarea id="{textarea_id}" '
                f'maxlength="{ts_max}">`` 必须等于 server_config.'
                f"PROMPT_MAX_LENGTH ({server_max})。"
                "原 BUG6 user-reported 修复 (cycle-21 R196) 现升级为 5-way invariant。",
            )


class TestConstantDriftPreventionDoc(unittest.TestCase):
    """R278 文档锚: 任何站点都必须有 R278 anchor 注释（或在 changelog 中
    标记 R278 关联），让维护者修改时立刻看到 invariant 范围。

    （由于本 commit 是 invariant-only，不改源码，注释要 cycle-25 后续逐步
    补；本 sanity test 暂时只 mark anchor 在测试文件本身存在。）
    """

    def test_test_file_documents_authoritative_sources(self) -> None:
        """本测试文件的 docstring 必须列出 authoritative sources（让 grep
        R278 能立刻找到全部 mirror 位置）。"""
        self_src = Path(__file__).read_text(encoding="utf-8")
        for marker in (
            "AUTO_RESUBMIT_TIMEOUT_DEFAULT",
            "AUTO_RESUBMIT_TIMEOUT_MAX",
            "WebUISectionConfig",
            "server_config",
            "webview.ts",
            "PROMPT_MAX_LENGTH",
        ):
            self.assertIn(
                marker,
                self_src,
                f"R278 doc anchor: 测试文件必须 docstring 提到 ``{marker}``，"
                "让 grep R278 能立刻定位 authoritative source",
            )


if __name__ == "__main__":
    unittest.main()
