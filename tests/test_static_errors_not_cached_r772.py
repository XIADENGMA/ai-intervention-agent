"""R772 regression coverage: an error is never given the long static Cache-Control.

``add_security_headers`` gave every response under ``/static/js/``, ``/static/css/``,
``/static/locales/``, ``/static/lottie/``, ``/fonts/``, ``/sounds/`` and ``/icons/`` its
cache policy (a day, or a year and ``immutable`` for a ``?v=`` URL) whatever the status.
So a 429 for a font, a 404 for a missing MathJax extension or a 5xx during startup was
stored by the browser under the same long lifetime: one failed request became a file that
stayed missing, and for a ``?v=`` URL it stayed missing for a year. Seen in a real browser:
after a burst of font requests was answered with 429, a reload showed the same 429
without the request ever reaching the server.

Only a response that actually served the file keeps the long policy; any error is
``no-store`` so the next load asks again.
"""

from __future__ import annotations

import itertools
import unittest
from types import SimpleNamespace
from typing import Any
from unittest import mock

from flask import Response

from ai_intervention_agent import web_ui_rate_limiter

POLICIES = {
    "/static/js/x.js": "max-age=86400",
    "/static/js/x.js?v=abc": "max-age=31536000",
    "/static/css/x.css": "max-age=86400",
    "/static/css/x.css?v=abc": "max-age=31536000",
    "/static/locales/x.json": "max-age=86400",
    "/static/locales/x.json?v=abc": "max-age=31536000",
    "/static/js/output/chtml/fonts/woff-v2/x.woff": "max-age=86400",
    "/static/lottie/x.json": "max-age=2592000",
    "/fonts/x.woff": "max-age=2592000",
    "/sounds/x.mp3": "max-age=604800",
    "/icons/x.png": "max-age=604800",
}

# The limiter counts in fixed windows of the wall clock, so a burst is limited only when
# eleven of its fifteen requests fall into one wall-clock second. They do not always: a
# second boundary after the fifth to the tenth request leaves two windows that both stay
# within the limit, and no 429 comes out (about 6 % of the bursts when a request takes
# 10 ms, every one of them when it takes 100 ms or more). The rate-limit test therefore
# pins the limiter's clock, with an instant of its own on every run, so that a repeat in
# the same process does not meet the hits counted by an earlier run.
_INSTANTS = itertools.count()


class TestStaticErrorsAreNotCached(unittest.TestCase):
    _ui: Any = None
    _client: Any = None

    @classmethod
    def setUpClass(cls) -> None:
        from ai_intervention_agent.web_ui import WebFeedbackUI

        cls._ui = WebFeedbackUI(prompt="r772", task_id="r772-base", port=19772)
        cls._ui.app.config["TESTING"] = True
        # A static-looking URL that is under the default limits (it has to exist before
        # the app serves its first request): the 11th request in a second is a 429.
        cls._ui.app.add_url_rule(
            "/static/js/r772-limited.js", "r772_limited", lambda: "ok"
        )
        cls._client = cls._ui.app.test_client()

    def _process(self, path: str, status: int) -> Response:
        with self._ui.app.test_request_context(path):
            return self._ui.app.process_response(Response("body", status=status))

    def test_served_files_keep_their_long_policy(self) -> None:
        for path, expected in POLICIES.items():
            for status in (200, 206, 304):
                header = self._process(path, status).headers.get("Cache-Control", "")
                self.assertIn(expected, header, (path, status))
                self.assertNotIn("no-store", header, (path, status))

    def test_errors_are_never_cacheable(self) -> None:
        for path in POLICIES:
            for status in (400, 403, 404, 429, 500, 503):
                header = self._process(path, status).headers.get("Cache-Control", "")
                self.assertEqual(header, "no-store", (path, status))

    def test_other_paths_are_left_alone(self) -> None:
        for status in (200, 404):
            response = self._process("/api/tasks", status)
            self.assertNotIn("Cache-Control", response.headers, status)

    def test_a_missing_versioned_file_is_not_remembered_for_a_year(self) -> None:
        for url in (
            "/static/js/does-not-exist.js?v=abc",
            "/static/js/input/tex/extensions/does-not-exist.js",
            "/static/css/does-not-exist.css?v=abc",
            "/static/locales/does-not-exist.json?v=abc",
        ):
            response = self._client.get(url)
            try:
                self.assertEqual(response.status_code, 404, url)
                self.assertEqual(response.headers.get("Cache-Control"), "no-store", url)
            finally:
                response.close()

    def test_a_rate_limited_static_url_is_not_cached(self) -> None:
        instant = 1_700_000_000.25 + 120 * next(_INSTANTS)
        with mock.patch.object(
            web_ui_rate_limiter, "time", SimpleNamespace(time=lambda: instant)
        ):
            responses = [
                self._client.get("/static/js/r772-limited.js") for _ in range(15)
            ]
        try:
            statuses = [r.status_code for r in responses]
            self.assertEqual(statuses[0], 200)
            self.assertIn(429, statuses)
            for response in responses:
                if response.status_code == 429:
                    self.assertEqual(response.headers["Cache-Control"], "no-store")
                else:
                    self.assertIn("max-age=86400", response.headers["Cache-Control"])
        finally:
            for response in responses:
                response.close()
