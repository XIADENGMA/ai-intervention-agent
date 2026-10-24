"""R863: a wrong method on an API route is answered in JSON, as every other error of the API is.

Flask answers a request whose method the route does not serve with Werkzeug's own ``405`` page,
an HTML document.  The Web UI answers every other error of its API in JSON: ``handle_404`` does
for the paths under ``/api/`` and ``/metrics`` (``{"success": false, "error": "not_found"}``), and
so do the ``400``, ``403``, ``413``, ``429`` and ``500`` answers of the routes.  A client that
reads the body of an error answer as JSON got what it asked for from all of them but this one: a
``GET /api/submit`` (the route is ``POST``), or a client of another version that calls a route
with the wrong method, failed on ``Unexpected token '<'`` instead of on the reason.

What the tests pin:

* every route under ``/api/`` answers each method it does not serve with ``405``, the JSON body
  ``{"success": false, "error": "method_not_allowed"}`` and the ``Allow`` header HTTP requires
  (the methods Werkzeug says are valid, sorted), and the sweep is held to reach every such route;
* a path that is not an API path (``POST /``) still gets Werkzeug's page, unless the client asks
  for JSON, which is the rule ``handle_404`` has always applied and now shares with the new
  handler;
* ``404`` answers are what they were (JSON for ``/api/...`` and ``/metrics``, a page otherwise),
  and ``OPTIONS`` and ``HEAD`` are not left out.
"""

from __future__ import annotations

import re

import pytest
from flask.testing import FlaskClient
from werkzeug.exceptions import HTTPException, MethodNotAllowed

from ai_intervention_agent.web_ui import WebFeedbackUI

LOOPBACK = {"REMOTE_ADDR": "127.0.0.1"}
METHODS = ("GET", "POST", "PUT", "PATCH", "DELETE")
BODY = {"success": False, "error": "method_not_allowed"}


@pytest.fixture(scope="module")
def ui() -> WebFeedbackUI:
    instance = WebFeedbackUI(
        prompt="r863", task_id="r863-ui", auto_resubmit_timeout=0, port=19864
    )
    instance.app.config["TESTING"] = True
    instance.limiter.enabled = False
    object.__setattr__(instance, "shutdown_server", lambda: None)
    return instance


@pytest.fixture
def client(ui: WebFeedbackUI) -> FlaskClient:
    return ui.app.test_client()


def url_for_rule(rule: str) -> str:
    return re.sub(
        r"<[^>]+>", lambda m: "0" if m.group(0).startswith("<int:") else "x", rule
    )


def api_urls(ui: WebFeedbackUI) -> set[str]:
    return {
        url_for_rule(rule.rule)
        for rule in ui.app.url_map.iter_rules()
        if rule.rule.startswith("/api/")
    }


def wrong_method_requests(ui: WebFeedbackUI) -> dict[tuple[str, str], list[str]]:
    """``{(method, url): valid methods}`` for every API URL and method Werkzeug refuses.

    Asked of the URL map itself, so a method that another rule of the same path serves (``DELETE
    /api/tasks/export`` is ``DELETE /api/tasks/<task_id>``) is not sent: that would run a handler.
    """
    adapter = ui.app.url_map.bind("localhost")
    found: dict[tuple[str, str], list[str]] = {}
    for url in sorted(api_urls(ui)):
        for method in METHODS:
            try:
                adapter.match(url, method=method)
            except MethodNotAllowed as exc:
                found[(method, url)] = sorted(exc.valid_methods or ())
            except HTTPException:
                continue
    return found


def allowed(header: str) -> list[str]:
    return [token.strip() for token in header.split(",")]


class TestEveryApiRoute:
    def test_the_sweep_reaches_every_api_route_and_is_not_small(
        self, ui: WebFeedbackUI
    ) -> None:
        refused = wrong_method_requests(ui)
        assert {url for _method, url in refused} == api_urls(ui)
        assert len(refused) >= 100
        assert ("GET", "/api/submit") in refused
        assert ("DELETE", "/api/system/health") in refused
        assert ("POST", "/api/system/metrics") in refused

    def test_a_method_the_route_does_not_serve_gets_json_405_and_allow(
        self, ui: WebFeedbackUI, client: FlaskClient
    ) -> None:
        wrong: list[str] = []
        for (method, url), valid in wrong_method_requests(ui).items():
            resp = client.open(url, method=method, environ_base=LOOPBACK)
            problems = []
            if resp.status_code != 405:
                problems.append(f"status {resp.status_code}")
            if resp.mimetype != "application/json":
                problems.append(f"type {resp.headers.get('Content-Type')}")
            elif resp.get_json() != BODY:
                problems.append(f"body {resp.get_data(as_text=True)[:60]!r}")
            if resp.headers.get("Allow") != ", ".join(valid):
                problems.append(f"Allow {resp.headers.get('Allow')!r} not {valid}")
            if problems:
                wrong.append(f"{method} {url}: {'; '.join(problems)}")
        assert wrong == []

    def test_allow_is_sorted_and_names_what_the_path_serves(
        self, client: FlaskClient
    ) -> None:
        resp = client.get("/api/submit", environ_base=LOOPBACK)
        assert resp.headers["Allow"] == "OPTIONS, POST"
        resp = client.delete("/api/system/health", environ_base=LOOPBACK)
        assert resp.headers["Allow"] == "GET, HEAD, OPTIONS"
        resp = client.put("/api/tasks", environ_base=LOOPBACK)
        assert allowed(resp.headers["Allow"]) == sorted(allowed(resp.headers["Allow"]))
        assert {"GET", "POST"} <= set(allowed(resp.headers["Allow"]))
        assert "PUT" not in allowed(resp.headers["Allow"])

    def test_a_405_that_names_no_valid_method_still_answers_in_json(
        self, ui: WebFeedbackUI
    ) -> None:
        """``abort(405)`` in a view has no ``valid_methods``; the handler must not trip on that."""
        with ui.app.test_request_context("/api/whatever"):
            resp = ui.app.make_response(
                ui.app.handle_user_exception(MethodNotAllowed())
            )
        assert resp.status_code == 405
        assert resp.get_json() == BODY
        assert "Allow" not in resp.headers

    def test_head_gets_the_same_answer_without_a_body(
        self, client: FlaskClient
    ) -> None:
        resp = client.head("/api/submit", environ_base=LOOPBACK)
        assert resp.status_code == 405
        assert resp.headers["Content-Type"] == "application/json"
        assert resp.headers["Allow"] == "OPTIONS, POST"
        assert resp.get_data() == b""

    def test_options_and_the_right_method_are_not_touched(
        self, client: FlaskClient
    ) -> None:
        options = client.options("/api/submit", environ_base=LOOPBACK)
        assert options.status_code == 200
        assert set(allowed(options.headers["Allow"])) == {"OPTIONS", "POST"}
        served = client.get("/api/system/health", environ_base=LOOPBACK)
        assert served.status_code == 200
        assert served.get_json() is not None


class TestAPagePath:
    def test_keeps_werkzeugs_page(self, client: FlaskClient) -> None:
        resp = client.post("/", environ_base=LOOPBACK)
        assert resp.status_code == 405
        assert resp.mimetype == "text/html"
        assert "Method Not Allowed" in resp.get_data(as_text=True)
        assert set(allowed(resp.headers["Allow"])) == {"GET", "HEAD", "OPTIONS"}

    def test_gets_json_when_the_client_asks_for_it(self, client: FlaskClient) -> None:
        resp = client.post(
            "/", environ_base=LOOPBACK, headers={"Accept": "application/json"}
        )
        assert resp.status_code == 405
        assert resp.mimetype == "application/json"
        assert resp.get_json() == BODY
        assert resp.headers["Allow"] == "GET, HEAD, OPTIONS"


class TestThe404RuleIsTheSame:
    @pytest.mark.parametrize(
        ("path", "accept", "json_answer"),
        [
            ("/api/nothing", None, True),
            ("/api/tasks/x/nothing", None, True),
            ("/metrics", None, True),
            ("/nothing-here", "application/json", True),
            ("/nothing-here", "text/html", False),
            ("/nothing-here", None, False),
        ],
    )
    def test_404(
        self, client: FlaskClient, path: str, accept: str | None, json_answer: bool
    ) -> None:
        headers = {"Accept": accept} if accept else {}
        resp = client.get(path, environ_base=LOOPBACK, headers=headers)
        assert resp.status_code == 404
        if json_answer:
            assert resp.mimetype == "application/json"
            assert resp.get_json() == {"success": False, "error": "not_found"}
        else:
            assert resp.mimetype == "text/html"
            assert "nothing-here" in resp.get_data(as_text=True)

    @pytest.mark.parametrize(
        ("path", "wrong_method"),
        [("/api/submit", "GET"), ("/", "POST"), ("/static/css/main.css", "POST")],
    )
    def test_a_405_and_a_404_take_the_same_side_for_the_same_request(
        self, client: FlaskClient, path: str, wrong_method: str
    ) -> None:
        wrong = client.open(path, method=wrong_method, environ_base=LOOPBACK)
        missing = client.get(path + "-missing", environ_base=LOOPBACK)
        assert wrong.status_code == 405
        assert missing.status_code == 404
        assert (wrong.mimetype == "application/json") == (
            missing.mimetype == "application/json"
        )
