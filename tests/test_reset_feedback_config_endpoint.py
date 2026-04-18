"""P7·L2·step-14: coverage for ``POST /api/reset-feedback-config``.

Context
-------
Before P7 the Web UI's "restore defaults" button in the feedback-prompt
settings panel hardcoded the Chinese default strings in JavaScript, which
caused two problems:

1. **Default drift**: changing defaults in ``server_config.py`` required
   editing the frontend too; unsynced edits led to "OK, I clicked reset
   but nothing changed" bug reports.
2. **i18n leak**: the hardcoded Chinese strings made the frontend
   non-localizable; other locales would have seen Chinese after reset.

The endpoint centralizes the defaults on the server
(``server_config.RESUBMIT_PROMPT_DEFAULT`` / ``PROMPT_SUFFIX_DEFAULT`` /
``AUTO_RESUBMIT_TIMEOUT_DEFAULT``) and makes reset a pure server-side op.

What we test
------------
* Happy path: endpoint returns ``status=success`` and the three server
  defaults, **and** calls ``config_mgr.update_section`` with those
  defaults merged over the previous feedback section (never dropping
  unrelated keys).
* Preserves unrelated keys: e.g. a ``feedback.timeout`` field that
  wasn't part of the reset set must remain untouched.
* Error path: if ``get_config`` explodes, the endpoint returns 500 with
  an i18n-keyed error message, *not* a 5xx stack trace.
* Rate limit wiring: the endpoint is decorated with ``@limiter.limit``;
  the test class disables the limiter globally (same pattern as every
  other route test in this repo) so we don't test the limiter itself
  here, just verify the wiring doesn't crash on import.
"""

from __future__ import annotations

import unittest
from typing import Any
from unittest.mock import MagicMock, patch


class _ResetFeedbackBase(unittest.TestCase):
    """Share a single WebFeedbackUI instance + test client across tests.
    Port is unique (``19050``) to avoid colliding with the broader
    ``tests/test_web_ui_routes.py`` test clients."""

    _port: int = 19050
    _ui: Any = None
    _client: Any = None

    @classmethod
    def setUpClass(cls) -> None:
        from web_ui import WebFeedbackUI

        cls._ui = WebFeedbackUI(
            prompt="reset-feedback-test", task_id="rt-reset", port=cls._port
        )
        cls._ui.app.config["TESTING"] = True
        cls._ui.limiter.enabled = False
        cls._client = cls._ui.app.test_client()


class TestResetFeedbackConfig(_ResetFeedbackBase):
    @patch("web_ui_routes.notification.get_config")
    def test_success_returns_server_defaults(self, mock_get_cfg: MagicMock) -> None:
        mock_cfg = MagicMock()
        mock_cfg.get_section.return_value = {
            "frontend_countdown": 123,
            "resubmit_prompt": "old user override",
            "prompt_suffix": "\nold suffix",
            "timeout": 600,  # unrelated field must survive
        }
        mock_get_cfg.return_value = mock_cfg

        from server_config import (
            AUTO_RESUBMIT_TIMEOUT_DEFAULT,
            PROMPT_SUFFIX_DEFAULT,
            RESUBMIT_PROMPT_DEFAULT,
        )

        resp = self._client.post("/api/reset-feedback-config")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data["status"], "success")
        # Server defaults come straight from ``server_config``.
        defaults = data["defaults"]
        self.assertEqual(
            defaults["frontend_countdown"], int(AUTO_RESUBMIT_TIMEOUT_DEFAULT)
        )
        self.assertEqual(defaults["resubmit_prompt"], RESUBMIT_PROMPT_DEFAULT)
        self.assertEqual(defaults["prompt_suffix"], PROMPT_SUFFIX_DEFAULT)

    @patch("web_ui_routes.notification.get_config")
    def test_preserves_unrelated_fields(self, mock_get_cfg: MagicMock) -> None:
        """Reset only touches three keys; every other ``feedback.*`` field
        must survive the round-trip."""
        mock_cfg = MagicMock()
        mock_cfg.get_section.return_value = {
            "frontend_countdown": 7,
            "resubmit_prompt": "x",
            "prompt_suffix": "y",
            "timeout": 600,
            "custom_user_knob": "preserve-me",
        }
        mock_get_cfg.return_value = mock_cfg

        resp = self._client.post("/api/reset-feedback-config")
        self.assertEqual(resp.status_code, 200)

        # Inspect what the endpoint persisted to config_mgr.
        mock_cfg.update_section.assert_called_once()
        section_name, payload = mock_cfg.update_section.call_args.args
        self.assertEqual(section_name, "feedback")
        self.assertEqual(payload["custom_user_knob"], "preserve-me")
        self.assertEqual(payload["timeout"], 600)

        from server_config import (
            AUTO_RESUBMIT_TIMEOUT_DEFAULT,
            PROMPT_SUFFIX_DEFAULT,
            RESUBMIT_PROMPT_DEFAULT,
        )

        self.assertEqual(
            payload["frontend_countdown"], int(AUTO_RESUBMIT_TIMEOUT_DEFAULT)
        )
        self.assertEqual(payload["resubmit_prompt"], RESUBMIT_PROMPT_DEFAULT)
        self.assertEqual(payload["prompt_suffix"], PROMPT_SUFFIX_DEFAULT)

    @patch(
        "web_ui_routes.notification.get_config",
        side_effect=RuntimeError("boom"),
    )
    def test_exception_returns_500(self, _mock: MagicMock) -> None:
        resp = self._client.post("/api/reset-feedback-config")
        self.assertEqual(resp.status_code, 500)
        data = resp.get_json()
        self.assertEqual(data["status"], "error")
        # The failure message should be non-empty and not leak the raw
        # exception message (we do not assert the full English text to
        # avoid coupling to copy changes; just verify it's a string).
        self.assertIsInstance(data["message"], str)
        self.assertTrue(data["message"])


if __name__ == "__main__":
    unittest.main()
