"""R656: ``_get_csp_nonce`` reuses the module-level Flask context helper."""

from __future__ import annotations

import inspect
import unittest
from unittest.mock import patch

import ai_intervention_agent.web_ui_security as web_ui_security
from ai_intervention_agent.web_ui import WebFeedbackUI
from ai_intervention_agent.web_ui_security import SecurityMixin


class TestCspNonceHasRequestContextBindingR656(unittest.TestCase):
    def setUp(self) -> None:
        self.ui = WebFeedbackUI(
            prompt="test",
            predefined_options=[],
            task_id="test-csp-nonce-binding-r656",
        )

    def test_module_imports_has_request_context_once(self) -> None:
        source = inspect.getsource(web_ui_security)
        get_nonce_source = inspect.getsource(SecurityMixin._get_csp_nonce)

        self.assertIn(
            "from flask import Response, abort, g, has_request_context, request",
            source,
        )
        self.assertNotIn(
            "from flask import has_request_context",
            get_nonce_source,
        )

    def test_existing_request_nonce_does_not_call_token_urlsafe(self) -> None:
        from flask import g

        with self.ui.app.test_request_context("/"):
            g.csp_nonce = "existing-r656-nonce"
            with patch(
                "ai_intervention_agent.web_ui_security.secrets.token_urlsafe",
                side_effect=AssertionError("existing nonce should not generate"),
            ):
                nonce = self.ui._get_csp_nonce()

        self.assertEqual(nonce, "existing-r656-nonce")

    def test_module_context_helper_runtime_error_falls_back_to_generated_nonce(
        self,
    ) -> None:
        with (
            patch(
                "ai_intervention_agent.web_ui_security.has_request_context",
                side_effect=RuntimeError("context torn down"),
            ),
            patch(
                "ai_intervention_agent.web_ui_security.secrets.token_urlsafe",
                return_value="generated-r656-nonce",
            ) as token_spy,
        ):
            nonce = self.ui._get_csp_nonce()

        self.assertEqual(nonce, "generated-r656-nonce")
        token_spy.assert_called_once_with(16)


if __name__ == "__main__":
    unittest.main()
