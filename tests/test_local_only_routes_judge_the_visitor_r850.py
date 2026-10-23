"""R850: the routes only this machine may call judge the visitor, not the proxy in front of them.

``POST /api/system/rotate-api-token``, ``GET /api/system/api-token-info``,
``POST /api/system/log-level``, ``POST /api/system/open-config-file`` and its ``/info`` ask
"is the caller this machine?" of ``request.remote_addr``.  Behind a reverse proxy on the same
machine (the setup ``docs/deployment.md`` describes) every connection comes from 127.0.0.1, so
every visitor the access control let in counted as this machine: ``rotate-api-token`` made the
API token useless and answered the new one to whoever asked.

Now these routes ask the address the access control judged (``SecurityMixin._current_client_ip``,
kept in ``g.client_ip`` by the ``before_request`` hook): the visitor is this machine only when
the proxy wrote a loopback address as the client (you, browsing from the server) or when there is
no proxy at all.  Nothing is let in that was not let in before: the address is only ever read
from a connection that came from this machine, so the new answer is the old one or "not this
machine".
"""

from __future__ import annotations

import ast
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

from werkzeug.exceptions import Forbidden

from ai_intervention_agent import web_ui_validators as validators
from ai_intervention_agent.web_ui import WebFeedbackUI
from ai_intervention_agent.web_ui_routes import system as system_module

REPO = Path(__file__).resolve().parents[1]
SRC = REPO / "src" / "ai_intervention_agent"

ALLOWED = ["127.0.0.0/8", "::1/128", "203.0.113.0/24"]
TOKEN = "r850-token-" + "x" * 24

# peer, X-Forwarded-For, trusted_proxy_hops, the visitor, is the visitor this machine
VISITORS: list[tuple[str, str | None, int | None, str, bool]] = [
    # a program on this machine, no proxy
    ("127.0.0.1", None, None, "127.0.0.1", True),
    ("::1", None, None, "::1", True),
    # you, browsing from the server itself through the proxy
    ("127.0.0.1", "127.0.0.1", None, "127.0.0.1", True),
    ("127.0.0.1", "203.0.113.7, 127.0.0.1", None, "127.0.0.1", True),
    # somebody else through the proxy
    ("127.0.0.1", "203.0.113.7", None, "203.0.113.7", False),
    # wrote 127.0.0.1 in front of the address the proxy saw
    ("127.0.0.1", "127.0.0.1, 203.0.113.7", None, "203.0.113.7", False),
    # a CDN in front of nginx (two hops)
    ("127.0.0.1", "203.0.113.7, 192.0.2.1", 2, "203.0.113.7", False),
    ("127.0.0.1", "127.0.0.1, 192.0.2.1", 2, "127.0.0.1", True),
    # 0: the header is not read, everybody is the proxy, and the proxy is this machine
    ("127.0.0.1", "203.0.113.7", 0, "127.0.0.1", True),
    # a connection from elsewhere is itself; the header it writes is not read
    ("203.0.113.7", "127.0.0.1", None, "203.0.113.7", False),
    ("203.0.113.7", None, None, "203.0.113.7", False),
]

# method, path, body, status when the call is let in (nothing is changed), takes an API token
GATES: list[tuple[str, str, dict[str, Any] | None, int, bool]] = [
    ("GET", "/api/system/api-token-info", None, 200, False),
    ("POST", "/api/system/rotate-api-token", None, 200, False),
    ("POST", "/api/system/log-level", {}, 400, True),
    ("POST", "/api/system/open-config-file", {"path": 1}, 400, True),
    ("GET", "/api/system/open-config-file/info", None, 200, True),
]


class _Routes(unittest.TestCase):
    """The real routes behind the real ``before_request`` hooks (a Flask test client)."""

    ui: WebFeedbackUI

    @classmethod
    def setUpClass(cls) -> None:
        cls.ui = WebFeedbackUI(prompt="r850-local-only", port=0)
        cls.ui.app.config["TESTING"] = True
        cls.ui.limiter.enabled = False

    def _configure(self, hops: int | None) -> None:
        section: dict[str, Any] = {"allowed_networks": ALLOWED}
        if hops is not None:
            section["trusted_proxy_hops"] = hops
        self.ui.network_security_config = validators.validate_network_security_config(
            section
        )

    @staticmethod
    def _environ(peer: str, forwarded_for: str | None) -> dict[str, str]:
        environ = {"REMOTE_ADDR": peer}
        if forwarded_for is not None:
            environ["HTTP_X_FORWARDED_FOR"] = forwarded_for
        return environ

    def _visit(
        self,
        visitor: tuple[str, str | None, int | None],
        gate: tuple[str, str, dict[str, Any] | None],
        *,
        token: bool = False,
    ) -> tuple[Any, int]:
        """The response, and how many times the API token was rewritten."""
        peer, forwarded_for, hops = visitor
        method, path, body = gate
        self._configure(hops)
        config_class = type(system_module.get_config())
        headers = {"Authorization": f"Bearer {TOKEN}"} if token else {}
        with (
            patch.object(
                config_class, "update_network_security_config", return_value=None
            ) as update,
            patch.object(
                config_class,
                "get_network_security_config",
                return_value={"api_token": "", "api_token_rotated_at": ""},
            ),
            patch.object(
                system_module, "_get_configured_api_token", return_value=TOKEN
            ),
            self.ui.app.test_client() as client,
        ):
            response = client.open(
                path,
                method=method,
                json=body,
                headers=headers,
                environ_overrides=self._environ(peer, forwarded_for),
            )
        return response, update.call_count


class TestTheFiveRoutes(_Routes):
    def test_only_a_visitor_that_is_this_machine_gets_in(self) -> None:
        for peer, forwarded_for, hops, client, local in VISITORS:
            for method, path, body, let_in, _takes_token in GATES:
                with self.subTest(
                    peer=peer,
                    forwarded_for=forwarded_for,
                    hops=hops,
                    client=client,
                    path=path,
                ):
                    response, rewrites = self._visit(
                        (peer, forwarded_for, hops), (method, path, body)
                    )
                    self.assertEqual(response.status_code, let_in if local else 403)
                    if path.endswith("rotate-api-token"):
                        self.assertEqual(rewrites, 1 if local else 0)

    def test_a_remote_visitor_is_told_nothing_and_nothing_is_rotated(self) -> None:
        response, rewrites = self._visit(
            ("127.0.0.1", "203.0.113.7", None),
            ("POST", "/api/system/rotate-api-token", None),
        )
        self.assertEqual(response.status_code, 403)
        body = response.get_json()
        self.assertFalse(body["success"])
        for key in ("api_token", "token_length", "rotated_at"):
            self.assertNotIn(key, body)
        self.assertEqual(rewrites, 0)

    def test_a_token_is_still_a_way_in_for_the_routes_that_take_one(self) -> None:
        for method, path, body, let_in, takes_token in GATES:
            with self.subTest(path=path):
                response, rewrites = self._visit(
                    ("127.0.0.1", "203.0.113.7", None),
                    (method, path, body),
                    token=True,
                )
                self.assertEqual(response.status_code, let_in if takes_token else 403)
                self.assertEqual(rewrites, 0)


class TestOneAddressForEveryone(_Routes):
    def test_the_routes_and_the_access_control_see_the_same_visitor(self) -> None:
        for peer, forwarded_for, hops, client, _local in VISITORS:
            with self.subTest(peer=peer, forwarded_for=forwarded_for, hops=hops):
                self._configure(hops)
                with self.ui.app.test_request_context(
                    "/api/health", environ_overrides=self._environ(peer, forwarded_for)
                ):
                    self.assertIsNone(self.ui.app.preprocess_request())
                    self.assertEqual(system_module._get_client_ip(), client)
                    self.assertEqual(self.ui._current_client_ip(), client)

    def test_a_refused_visitor_is_known_to_whoever_logs_it(self) -> None:
        self._configure(None)
        with self.ui.app.test_request_context(
            "/api/health", environ_overrides=self._environ("198.51.100.9", None)
        ):
            with self.assertRaises(Forbidden):
                self.ui.app.preprocess_request()
            self.assertEqual(system_module._get_client_ip(), "198.51.100.9")

    def test_no_answer_is_not_this_machine(self) -> None:
        # a request the hook never saw: nobody can be called this machine
        with self.ui.app.test_request_context(
            "/api/system/api-token-info", environ_overrides={"REMOTE_ADDR": "127.0.0.1"}
        ):
            self.assertEqual(system_module._get_client_ip(), "")
            self.assertFalse(system_module._is_loopback_request())
            with patch.object(
                system_module, "_get_configured_api_token", return_value=TOKEN
            ):
                self.assertFalse(system_module._is_authorized())
        with self.ui.app.test_request_context(
            "/api/system/log-level",
            environ_overrides={"REMOTE_ADDR": "127.0.0.1"},
            headers={"Authorization": f"Bearer {TOKEN}"},
        ):
            with patch.object(
                system_module, "_get_configured_api_token", return_value=TOKEN
            ):
                self.assertFalse(system_module._is_loopback_request())
                self.assertTrue(system_module._is_authorized())


class TestOnlyTheHookSaysWho(unittest.TestCase):
    def test_no_module_reads_the_connections_address_but_the_limiters_fallback(
        self,
    ) -> None:
        found = {}
        for path in sorted(SRC.rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            reads = [
                node
                for node in ast.walk(tree)
                if isinstance(node, ast.Attribute) and node.attr == "remote_addr"
            ]
            if reads:
                found[path.name] = len(reads)
        self.assertEqual(found, {"web_ui_rate_limiter.py": 1})

    def test_the_hook_keeps_the_address_before_it_judges_it(self) -> None:
        tree = ast.parse((SRC / "web_ui_security.py").read_text(encoding="utf-8"))
        hook = next(
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef)
            and node.name == "check_ip_and_generate_nonce"
        )
        steps = []
        for statement in hook.body:
            text = ast.unparse(statement)
            if text == "client_ip = self._current_client_ip()":
                steps.append("resolve")
            elif text == "g.client_ip = client_ip":
                steps.append("keep")
            elif text.startswith("if not self._is_ip_allowed(client_ip)"):
                steps.append("judge")
        self.assertEqual(steps, ["resolve", "keep", "judge"])

    def test_the_helper_only_reads_what_the_hook_kept(self) -> None:
        path = SRC / "web_ui_routes" / "system.py"
        function = _function(path, "_get_client_ip")
        names = _names_in_body(function)
        strings = {
            node.value
            for statement in function.body[1:]
            for node in ast.walk(statement)
            if isinstance(node, ast.Constant) and isinstance(node.value, str)
        }
        self.assertEqual(names, {"g"})
        self.assertIn("client_ip", strings)

    def test_this_machine_is_decided_from_that_one_helper(self) -> None:
        path = SRC / "web_ui_routes" / "system.py"
        self.assertEqual(
            _names_in_body(_function(path, "_is_loopback_request")),
            {"_get_client_ip", "_resolve_loopback_ips"},
        )
        self.assertEqual(
            _names_in_body(_function(path, "_is_authorized")),
            {"_is_loopback_request", "_is_api_token_authorized"},
        )


class TestTheGuidesSayIt(unittest.TestCase):
    def test_the_deployment_guides_name_the_routes_and_what_to_do(self) -> None:
        for name in ("deployment.md", "deployment.zh-CN.md"):
            with self.subTest(guide=name):
                text = (REPO / "docs" / name).read_text(encoding="utf-8")
                for route in (
                    "/api/system/rotate-api-token",
                    "/api/system/api-token-info",
                    "/api/system/log-level",
                    "/api/system/open-config-file",
                ):
                    self.assertIn(route, text)
                self.assertIn("curl http://127.0.0.1:8080/api/system/", text)


def _names_in_body(function: ast.FunctionDef) -> set[str]:
    """The names the statements use (the annotations and the docstring do not count)."""
    return {
        node.id
        for statement in function.body[1:]
        for node in ast.walk(statement)
        if isinstance(node, ast.Name)
    }


def _function(path: Path, name: str) -> ast.FunctionDef:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"{name} not found in {path.name}")


if __name__ == "__main__":
    unittest.main()
