"""mining-cycle-4 §4.5 B.4 borrow #1 — pretty 404 page (session-not-found UX)。

测试矩阵：
- HTML accept → 渲染 not_found.html (200 OK template render)
- JSON accept → return jsonify(error=not_found)
- Status code = 404 in both cases
- Template renders request_path
- Template has Home link
"""

from __future__ import annotations

import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = REPO_ROOT / "src" / "ai_intervention_agent" / "templates" / "not_found.html"
WEB_UI_PY = REPO_ROOT / "src" / "ai_intervention_agent" / "web_ui.py"


class TestTemplateExists(unittest.TestCase):
    def test_template_file_exists(self) -> None:
        self.assertTrue(TEMPLATE.exists())

    def test_template_renders_request_path_var(self) -> None:
        src = TEMPLATE.read_text(encoding="utf-8")
        self.assertIn("{{ request_path }}", src)

    def test_template_has_home_link(self) -> None:
        src = TEMPLATE.read_text(encoding="utf-8")
        self.assertIn('href="/"', src)

    def test_template_uses_inline_styles(self) -> None:
        """no <link rel=stylesheet> — survives even when static asset
        routes are also broken (which is why we render this page)."""
        src = TEMPLATE.read_text(encoding="utf-8")
        self.assertNotIn('rel="stylesheet"', src)
        self.assertIn("<style>", src)

    def test_template_has_prefers_color_scheme(self) -> None:
        """dark mode support inline."""
        src = TEMPLATE.read_text(encoding="utf-8")
        self.assertIn("prefers-color-scheme: dark", src)


class TestErrorHandlerWired(unittest.TestCase):
    def test_404_handler_in_web_ui_py(self) -> None:
        src = WEB_UI_PY.read_text(encoding="utf-8")
        self.assertIn("@self.app.errorhandler(404)", src)
        self.assertIn("def handle_404", src)
        self.assertIn('"not_found.html"', src)

    def test_handler_respects_accept_header(self) -> None:
        src = WEB_UI_PY.read_text(encoding="utf-8")
        self.assertIn("accept_mimetypes.best", src)

    def test_json_fallback_returns_404(self) -> None:
        src = WEB_UI_PY.read_text(encoding="utf-8")
        # Look for the fallback path
        self.assertIn('jsonify({"success": False, "error": "not_found"}), 404', src)


class TestRoute(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        from ai_intervention_agent.web_ui import WebFeedbackUI

        cls._ui = WebFeedbackUI(
            prompt="bench",
            predefined_options=[],
            task_id=None,
            port=18963,
        )
        cls.client = cls._ui.app.test_client()

    def test_html_request_404_returns_html_page(self) -> None:
        rv = self.client.get(
            "/this-path-does-not-exist",
            headers={"Accept": "text/html"},
        )
        self.assertEqual(rv.status_code, 404)
        body = rv.get_data(as_text=True)
        # Either the pretty page or the inline fallback — both must
        # contain a Home link and the path
        self.assertIn("/this-path-does-not-exist", body)
        self.assertIn('href="/"', body)

    def test_json_request_404_returns_json(self) -> None:
        rv = self.client.get(
            "/this-path-does-not-exist",
            headers={"Accept": "application/json"},
        )
        self.assertEqual(rv.status_code, 404)
        data = rv.get_json()
        self.assertEqual(data["success"], False)
        self.assertEqual(data["error"], "not_found")

    def test_pretty_page_includes_subtitle(self) -> None:
        rv = self.client.get(
            "/this-path-does-not-exist-2",
            headers={"Accept": "text/html"},
        )
        self.assertEqual(rv.status_code, 404)
        body = rv.get_data(as_text=True)
        self.assertIn("Task or page not found", body)


if __name__ == "__main__":
    unittest.main()
