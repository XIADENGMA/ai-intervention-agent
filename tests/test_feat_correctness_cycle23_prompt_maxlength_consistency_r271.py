"""R271 / cycle-23 Track-D (exploratory audit):
``resubmit_prompt`` / ``prompt_suffix`` 的字符上限必须在 3 处保持一致：

  1. backend ``server_config.PROMPT_MAX_LENGTH``           （Python 源真理）
  2. Web UI HTML ``<textarea maxlength="...">``            （前端硬约束）
  3. VSCode extension webview HTML ``<textarea maxlength>`` （插件硬约束）
  4. OpenAPI/Swagger schema ``maxLength: ...``            （自动 API docs）

Pre-R271 现象：
  - server_config.PROMPT_MAX_LENGTH = 100_000          ✅
  - web_ui.html maxlength="100000" × 2                 ✅
  - packages/vscode/webview.ts maxlength="100000" × 2  ✅
  - notification.py OpenAPI maxLength: 10000 × 2       ❌ **10x 偏差**

后果：
  1. 自动生成的 API docs / Swagger UI / Redoc 显示 "max 10000 chars"，
     用户参考 docs 时以为只能输 10K，实际能输 100K（用户白白受限）。
  2. OpenAPI client generator（``openapi-generator``、``openapi-python-
     client``）会按 10K 校验生成的 client 代码，rejects valid 100K request
     → integration test 在 client 侧失败，但 server 是接受的。
  3. 文档与实现不一致 = trust 漂移；future bug fix / 重构容易跟错文档。

Pattern 类似 BUG7 修复（VSCode webview maxlength 与 web UI 对齐），但 R271
专门盯 OpenAPI schema vs 实际限制的一致性。

Invariant
---------

1. ``server_config.PROMPT_MAX_LENGTH`` = 100_000（基线常量）
2. ``templates/web_ui.html`` 中所有 ``maxlength="..."`` 关于 prompt 的都
   = 100000（写法允许大小写、空格、引号风格不一）
3. ``packages/vscode/webview.ts`` 同上
4. ``web_ui_routes/notification.py`` 的 ``update_feedback_config`` OpenAPI
   schema ``maxLength`` for ``resubmit_prompt`` 和 ``prompt_suffix`` =
   ``server_config.PROMPT_MAX_LENGTH``
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SERVER_CONFIG = REPO_ROOT / "src" / "ai_intervention_agent" / "server_config.py"
WEB_UI_HTML = REPO_ROOT / "src" / "ai_intervention_agent" / "templates" / "web_ui.html"
VSCODE_WEBVIEW = REPO_ROOT / "packages" / "vscode" / "webview.ts"
NOTIFICATION_ROUTE = (
    REPO_ROOT / "src" / "ai_intervention_agent" / "web_ui_routes" / "notification.py"
)

EXPECTED_MAX_LENGTH = 100_000


def _extract_server_config_max_length() -> int:
    text = SERVER_CONFIG.read_text(encoding="utf-8")
    match = re.search(r"^PROMPT_MAX_LENGTH\s*=\s*([0-9_]+)", text, re.MULTILINE)
    assert match is not None, (
        "R271: cannot find ``PROMPT_MAX_LENGTH = N`` in server_config.py"
    )
    return int(match.group(1).replace("_", ""))


def _find_textarea_maxlengths(html_text: str, ids: list[str]) -> list[int]:
    """Return all ``maxlength=`` values found on textareas whose id matches
    one of the given ids. Order preserves source occurrence."""
    pattern = re.compile(
        r'<textarea\b[^>]*?\bid="(?P<id>[^"]+)"[^>]*?\bmaxlength="(?P<val>[0-9]+)"',
        re.IGNORECASE,
    )
    found: list[int] = []
    for match in pattern.finditer(html_text):
        if match.group("id") in ids:
            found.append(int(match.group("val")))
    return found


def _find_openapi_max_lengths(py_text: str, props: list[str]) -> list[int]:
    """Given a Python file containing flasgger-style YAML in docstrings,
    extract ``maxLength: N`` values from the YAML block, one for each
    property listed."""
    found: list[int] = []
    lines = py_text.splitlines()
    for prop in props:
        for i, line in enumerate(lines):
            if re.match(rf"\s*{re.escape(prop)}:\s*$", line):
                window = "\n".join(lines[i : i + 6])
                m = re.search(r"maxLength:\s*([0-9]+)", window)
                if m:
                    found.append(int(m.group(1)))
                    break
    return found


class TestServerConfigBaseline(unittest.TestCase):
    def test_prompt_max_length_is_100000(self) -> None:
        actual = _extract_server_config_max_length()
        self.assertEqual(
            actual,
            EXPECTED_MAX_LENGTH,
            f"R271: PROMPT_MAX_LENGTH 必须 = {EXPECTED_MAX_LENGTH:_}, 实际 {actual:_}. "
            "若刻意调整上限，请同步更新："
            "templates/web_ui.html `<textarea maxlength>`、"
            "packages/vscode/webview.ts `<textarea maxlength>`、"
            "web_ui_routes/notification.py OpenAPI schema maxLength。",
        )


class TestWebUiHtmlMatchesBaseline(unittest.TestCase):
    def test_resubmit_prompt_and_suffix_maxlength_matches_baseline(self) -> None:
        baseline = _extract_server_config_max_length()
        html = WEB_UI_HTML.read_text(encoding="utf-8")
        maxlengths = _find_textarea_maxlengths(
            html,
            ids=[
                "feedback-resubmit-prompt",
                "feedback-prompt-suffix",
                "feedbackResubmitPrompt",
                "feedbackPromptSuffix",
            ],
        )
        self.assertGreaterEqual(
            len(maxlengths),
            2,
            "R271: web_ui.html 必须包含至少 2 个带 maxlength 的 prompt "
            "textarea (resubmit + suffix)，否则前端无法生效字符上限。"
            f"实测发现 {len(maxlengths)} 个。",
        )
        for val in maxlengths:
            self.assertEqual(
                val,
                baseline,
                f"R271: web_ui.html `<textarea maxlength={val}>` 与 backend "
                f"PROMPT_MAX_LENGTH={baseline} 不一致。请改 web_ui.html。",
            )


class TestVscodeWebviewMatchesBaseline(unittest.TestCase):
    def test_resubmit_prompt_and_suffix_maxlength_matches_baseline(self) -> None:
        baseline = _extract_server_config_max_length()
        if not VSCODE_WEBVIEW.exists():
            self.skipTest("packages/vscode/webview.ts not present")
        text = VSCODE_WEBVIEW.read_text(encoding="utf-8")
        maxlengths = _find_textarea_maxlengths(
            text,
            ids=[
                "feedbackResubmitPrompt",
                "feedbackPromptSuffix",
            ],
        )
        self.assertGreaterEqual(
            len(maxlengths),
            2,
            "R271: VSCode webview 必须包含至少 2 个带 maxlength 的 prompt "
            "textarea (resubmit + suffix)，否则插件无法生效字符上限。"
            f"实测发现 {len(maxlengths)} 个。",
        )
        for val in maxlengths:
            self.assertEqual(
                val,
                baseline,
                f"R271: VSCode webview `<textarea maxlength={val}>` 与 "
                f"backend PROMPT_MAX_LENGTH={baseline} 不一致。请改 webview.ts。",
            )


class TestOpenApiSchemaMatchesBaseline(unittest.TestCase):
    def test_update_feedback_config_max_lengths_match_baseline(self) -> None:
        baseline = _extract_server_config_max_length()
        py = NOTIFICATION_ROUTE.read_text(encoding="utf-8")
        max_lengths = _find_openapi_max_lengths(
            py, props=["resubmit_prompt", "prompt_suffix"]
        )
        self.assertEqual(
            len(max_lengths),
            2,
            "R271: notification.py ``update_feedback_config`` 的 OpenAPI "
            "schema 必须为 ``resubmit_prompt`` 与 ``prompt_suffix`` 两个属性"
            "都标 ``maxLength: N``，让 Swagger UI / Redoc / API client "
            f"generator 校验生效。实测找到 {len(max_lengths)} 个。",
        )
        for val in max_lengths:
            self.assertEqual(
                val,
                baseline,
                f"R271: notification.py OpenAPI schema ``maxLength: {val}`` "
                f"与 backend PROMPT_MAX_LENGTH={baseline} 不一致。这是 "
                "auto-generated API docs 用户最容易踩坑的地方，请改 "
                "notification.py 让 docs 反映真实上限。",
            )


class TestCrossPlatformConsistency(unittest.TestCase):
    """Cross-channel sanity: 任何渠道（web html / vscode / openapi）声明的字符
    上限相互之间必须一致，不止与 baseline 一致。"""

    def test_all_max_lengths_are_equal(self) -> None:
        web = _find_textarea_maxlengths(
            WEB_UI_HTML.read_text(encoding="utf-8"),
            ids=[
                "feedback-resubmit-prompt",
                "feedback-prompt-suffix",
                "feedbackResubmitPrompt",
                "feedbackPromptSuffix",
            ],
        )
        vsc: list[int] = []
        if VSCODE_WEBVIEW.exists():
            vsc = _find_textarea_maxlengths(
                VSCODE_WEBVIEW.read_text(encoding="utf-8"),
                ids=["feedbackResubmitPrompt", "feedbackPromptSuffix"],
            )
        openapi = _find_openapi_max_lengths(
            NOTIFICATION_ROUTE.read_text(encoding="utf-8"),
            props=["resubmit_prompt", "prompt_suffix"],
        )
        all_values = set(web + vsc + openapi)
        self.assertEqual(
            len(all_values),
            1,
            "R271: 3 渠道（web HTML / vscode webview / OpenAPI schema）"
            "的 prompt 字符上限必须严格一致。实测发现以下不同值: "
            f"{sorted(all_values)}. 请统一三者，并对齐 server_config."
            "PROMPT_MAX_LENGTH。",
        )


if __name__ == "__main__":
    unittest.main()
