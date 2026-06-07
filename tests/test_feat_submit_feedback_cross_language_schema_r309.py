"""R309: POST /api/submit cross-language schema 第三应用 (cycle-31 t31-4)。

cycle-30 cr60 §5 #A2 推荐 — cross-language schema pattern 第三应用。
R297 (SSE event payload) → R302 (REST GET /api/tasks) → **R309 (REST
POST /api/submit feedback)** — pattern 应用域从 "GET 响应" 扩展到
"POST 请求体 + 响应"。

================================================================
| 维度              | Python 端 (web_ui_routes/feedback.py)     | JS 端 (app.js) |
|-------------------|--------------------------------------------|----------------|
| 字段 (request)    | task_id / feedback_text / selected_options / files (image_N) | FormData 同名 |
| 兼容字段          | user_input (alt of feedback_text)           | —              |
| 成功响应          | status / message / persistent / clear_content | result.message |
| 失败响应 (404)    | success: false / error                       | result.message tries error |
| 端点              | /api/submit                                  | "/api/submit" 字符串 |
================================================================

================================================================
| Tests | 维度                                                            |
|-------|-------------------------------------------------------------|
| 4     | Python 必须 form/json 接收 4 字段 (task_id / feedback_text / selected_options / images) |
| 4     | Python 成功响应必须含 4 字段 (status / message / persistent / clear_content) |
| 2     | JS FormData 必须 append 关键字段 (feedback_text / selected_options) |
| 2     | JS 必须读取 response.ok / result.message                     |
| 1     | 端点字符串 cross-source consistency (/api/submit)             |
================================================================
| 13 总计                                                                  |
================================================================

**pattern lineage**: cross-language schema pattern 第三应用 —
R297 (SSE event) → R302 (REST GET) → R309 (REST POST + request body),
覆盖 HTTP API 的全 method 三大类。pattern 完全工业化。
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC = PROJECT_ROOT / "src" / "ai_intervention_agent"
PY_FEEDBACK = SRC / "web_ui_routes" / "feedback.py"
JS_APP = SRC / "static" / "js" / "app.js"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def _extract_submit_feedback_body(py: str) -> str:
    """从 ``feedback.py`` 中切出 ``submit_feedback`` 函数体。"""
    m = re.search(
        r"def submit_feedback\([\s\S]+?(?=\n        @self\.app\.route|\nclass )",
        py,
    )
    return m.group(0) if m else ""


# ============================================================
# Python 端接收 4 字段
# ============================================================
class TestPythonReceivesRequestFields(unittest.TestCase):
    """submit_feedback 必须解析 task_id / feedback_text / selected_options / images"""

    def setUp(self) -> None:
        self.body = _extract_submit_feedback_body(_read(PY_FEEDBACK))
        self.assertGreater(len(self.body), 500, "未提取到 submit_feedback 函数体")

    def test_reads_task_id(self) -> None:
        """``submit_feedback`` 必须读 ``task_id`` (form 或 JSON)。"""
        m = re.search(
            r"(?:request\.form\.get\(\"task_id\"|data\.get\(\"task_id\")",
            self.body,
        )
        self.assertIsNotNone(m, "R309: submit_feedback 必须读 task_id (form / JSON)")

    def test_reads_feedback_text(self) -> None:
        """``submit_feedback`` 必须读 ``feedback_text``。"""
        m = re.search(
            r"(?:request\.form\.get\(\"feedback_text\"|data\.get\(\"feedback_text\")",
            self.body,
        )
        self.assertIsNotNone(m, "R309: submit_feedback 必须读 feedback_text")

    def test_reads_selected_options(self) -> None:
        """``submit_feedback`` 必须读 ``selected_options``。"""
        m = re.search(
            r"(?:request\.form\.get\(\"selected_options\"|data\.get\(\"selected_options\")",
            self.body,
        )
        self.assertIsNotNone(m, "R309: submit_feedback 必须读 selected_options")

    def test_reads_uploaded_images(self) -> None:
        """``submit_feedback`` 必须处理上传 images。"""
        # 通过 extract_uploaded_images helper 或 request.files
        m = re.search(
            r"(?:extract_uploaded_images|request\.files)",
            self.body,
        )
        self.assertIsNotNone(
            m,
            "R309: submit_feedback 必须通过 extract_uploaded_images 或 request.files 处理图片",
        )


# ============================================================
# Python 端成功响应 4 字段
# ============================================================
class TestPythonSuccessResponseFields(unittest.TestCase):
    """成功响应必须含 status / message / persistent / clear_content"""

    def setUp(self) -> None:
        self.body = _extract_submit_feedback_body(_read(PY_FEEDBACK))

    def test_response_has_status(self) -> None:
        m = re.search(r'"status":\s*"success"', self.body)
        self.assertIsNotNone(
            m,
            'R309: 成功响应必须含 "status": "success" (JS 检查 response.ok 后能从此分类)',
        )

    def test_response_has_message(self) -> None:
        m = re.search(r'"message":\s*msg\("feedback\.submitted"\)', self.body)
        self.assertIsNotNone(
            m,
            'R309: 成功响应必须含 "message": msg("feedback.submitted") '
            "(JS showStatus 显示)",
        )

    def test_response_has_persistent(self) -> None:
        m = re.search(r'"persistent":\s*True', self.body)
        self.assertIsNotNone(
            m,
            'R309: 成功响应必须含 "persistent": True (告知 JS 显示是否持久化)',
        )

    def test_response_has_clear_content(self) -> None:
        m = re.search(r'"clear_content":\s*True', self.body)
        self.assertIsNotNone(
            m,
            'R309: 成功响应必须含 "clear_content": True (告知 JS 清表单)',
        )


# ============================================================
# JS 端 FormData 字段
# ============================================================
class TestJsFormDataAppendsFields(unittest.TestCase):
    """JS app.js 必须 formData.append feedback_text + selected_options"""

    def setUp(self) -> None:
        self.src = _read(JS_APP)

    def test_appends_feedback_text(self) -> None:
        m = re.search(
            r'formData\.append\(\s*"feedback_text"\s*,\s*feedbackText\s*\)',
            self.src,
        )
        self.assertIsNotNone(
            m,
            'R309: JS 必须 formData.append("feedback_text", feedbackText) '
            "(与 Python feedback.py form 接收对齐)",
        )

    def test_appends_selected_options_as_json(self) -> None:
        m = re.search(
            r'formData\.append\(\s*"selected_options"\s*,\s*JSON\.stringify\(\s*selectedOptions\s*\)\s*\)',
            self.src,
        )
        self.assertIsNotNone(
            m,
            'R309: JS 必须 formData.append("selected_options", '
            "JSON.stringify(selectedOptions)) (Python json.loads 解析)",
        )


# ============================================================
# JS 端响应处理
# ============================================================
class TestJsResponseHandling(unittest.TestCase):
    """JS 必须正确处理 response.ok + result.message"""

    def setUp(self) -> None:
        self.src = _read(JS_APP)

    def test_checks_response_ok(self) -> None:
        """JS 必须用 ``response.ok`` 分支成功/失败。"""
        m = re.search(r"if\s*\(\s*response\.ok\s*\)", self.src)
        self.assertIsNotNone(
            m,
            "R309: JS 必须用 if (response.ok) 分支 success/error",
        )

    def test_reads_result_message(self) -> None:
        """JS 必须读 ``result.message`` (与 Python message 对齐)。"""
        m = re.search(r"result\.message", self.src)
        self.assertIsNotNone(
            m,
            "R309: JS 必须读 result.message (Python 返回 message 字段)",
        )


# ============================================================
# 端点字符串 cross-source
# ============================================================
class TestEndpointStringConsistency(unittest.TestCase):
    """端点 ``/api/submit`` 字符串必须在 Python + JS 严格一致"""

    def test_endpoint_in_python_and_js(self) -> None:
        """``/api/submit`` 字面值必须同时出现在 Python route + JS fetch。"""
        py = _read(PY_FEEDBACK)
        js = _read(JS_APP)
        self.assertIn(
            '"/api/submit"',
            py,
            "R309: Python 必须注册 /api/submit route",
        )
        self.assertIn(
            '"/api/submit"',
            js,
            "R309: JS 必须 fetch /api/submit",
        )


if __name__ == "__main__":
    unittest.main()
