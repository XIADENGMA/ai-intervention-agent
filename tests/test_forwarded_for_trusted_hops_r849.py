"""R849: behind a reverse proxy the client is the address the proxy wrote, not the first one.

When a connection came from this machine (a reverse proxy on the same host, the profile
``docs/deployment.md`` describes) the Web UI took the *first* entry of ``X-Forwarded-For`` as
the client address, for the access control (``allowed_networks``, ``blocked_ips``) and for
the rate limit.  The first entry is the one a visitor writes: nginx's usual
``proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;`` keeps what the visitor sent
and appends the address it saw on the right.

Real Web UI process (``allowed_networks = ["203.0.113.0/24"]``, ``blocked_ips =
["203.0.113.66"]``, every request from 127.0.0.1 as a proxy on the same machine looks), status
of ``GET /api/tasks`` for each ``X-Forwarded-For``, before and after:

    203.0.113.7                       (the visitor wrote it)        200  200
    203.0.113.7, 198.51.100.9         (visitor, then the real one)  200  403
    203.0.113.7, 203.0.113.66         (visitor, then a blocked one) 200  403
    198.51.100.9                      (an honest proxy)             403  403

A visitor outside the allowed networks was let in by naming an allowed address in front of
their own, and a blocked one by naming an allowed address in front of the blocked one; the
rate limiter gave every made-up first entry a bucket of its own.

Now the client is the entry ``network_security.trusted_proxy_hops`` places from the right:
1 (the default) is the one proxy next to the Web UI, 2 is a CDN in front of nginx, 0 trusts
no ``X-Forwarded-For`` at all.  A header with fewer entries than that gives its first one
(what Express does).  The access control and the rate limiter ask the same method.
"""

from __future__ import annotations

import ast
import tempfile
import tomllib
import unittest
from pathlib import Path
from typing import Any, cast
from unittest.mock import patch

from ai_intervention_agent import web_ui_validators as validators
from ai_intervention_agent.config_manager import ConfigManager
from ai_intervention_agent.shared_types import NetworkSecuritySectionConfig
from ai_intervention_agent.web_ui import WebFeedbackUI
from ai_intervention_agent.web_ui_rate_limiter import WebUiRateLimiter
from ai_intervention_agent.web_ui_security import SecurityMixin

REPO = Path(__file__).resolve().parents[1]
SRC = REPO / "src" / "ai_intervention_agent"

ALLOWED = "203.0.113.0/24"
BLOCKED = "203.0.113.66"
MAX_HOPS = 8


class _Probe(SecurityMixin):
    """A ``SecurityMixin`` with the configuration the access control reads."""

    def __init__(self, **section: object) -> None:
        self.network_security_config = validators.validate_network_security_config(
            section
        )


class _TrackingEnviron(dict[str, Any]):
    def __init__(self, **values: str) -> None:
        super().__init__(values)
        self.forwarded_for_reads = 0

    def get(self, key: str, default: Any = None) -> Any:
        if key == "HTTP_X_FORWARDED_FOR":
            self.forwarded_for_reads += 1
        return super().get(key, default)


class TestWhichEntryIsTheClient(unittest.TestCase):
    """``_parse_forwarded_for``: the entry that ``hops`` proxies vouch for."""

    CASES = [
        # header, hops, client
        ("", 1, ""),
        ("198.51.100.9", 1, "198.51.100.9"),
        ("203.0.113.7, 198.51.100.9", 1, "198.51.100.9"),
        ("  2001:db8::1  , 10.0.0.2  ", 1, "10.0.0.2"),
        ("  2001:db8::1  ", 1, "2001:db8::1"),
        ("a, b, c", 1, "c"),
        ("a, b, c", 2, "b"),
        ("a, b, c", 3, "a"),
        # fewer entries than proxies: the first one is the furthest the chain can say
        ("a, b, c", 4, "a"),
        ("a, b", MAX_HOPS, "a"),
        ("a", 2, "a"),
        # 0 (and anything below 1): the header is not trusted
        ("a, b, c", 0, ""),
        ("a", 0, ""),
        ("a, b, c", -1, ""),
        # an empty entry is an empty answer; it is not skipped for the next one
        ("a,,c", 1, "c"),
        ("a,,c", 2, ""),
        ("a, b,", 1, ""),
        (",", 1, ""),
    ]

    def test_the_entry_hops_places_from_the_right(self) -> None:
        for header, hops, client in self.CASES:
            with self.subTest(header=header, hops=hops):
                self.assertEqual(
                    SecurityMixin._parse_forwarded_for(header, hops), client
                )

    def test_one_hop_is_the_default(self) -> None:
        self.assertEqual(SecurityMixin._parse_forwarded_for("a, b, c"), "c")

    def test_what_the_visitor_wrote_in_front_never_wins_while_the_chain_is_long_enough(
        self,
    ) -> None:
        for hops in range(1, 5):
            real = [f"198.51.100.{n}" for n in range(hops)]
            for visitor in ("203.0.113.7", "203.0.113.7, 10.0.0.1", "x," * 50 + "y"):
                with self.subTest(hops=hops, visitor=visitor[:20]):
                    header = ", ".join([visitor, *real])
                    self.assertEqual(
                        SecurityMixin._parse_forwarded_for(header, hops), real[0]
                    )


class TestClientOfARequest(unittest.TestCase):
    """``_get_request_client_ip``: who the access control judges."""

    def test_the_spoofed_first_entry_does_not_become_the_client(self) -> None:
        environ = {
            "REMOTE_ADDR": "127.0.0.1",
            "HTTP_X_FORWARDED_FOR": "203.0.113.7, 198.51.100.9",
        }
        self.assertEqual(_Probe()._get_request_client_ip(environ), "198.51.100.9")

    def test_two_proxies_in_front_need_two_hops(self) -> None:
        environ = {
            "REMOTE_ADDR": "127.0.0.1",
            "HTTP_X_FORWARDED_FOR": "198.51.100.9, 192.0.2.1",  # client, cdn
        }
        self.assertEqual(
            _Probe(trusted_proxy_hops=1)._get_request_client_ip(environ), "192.0.2.1"
        )
        self.assertEqual(
            _Probe(trusted_proxy_hops=2)._get_request_client_ip(environ),
            "198.51.100.9",
        )

    def test_zero_hops_never_reads_the_header(self) -> None:
        probe = _Probe(trusted_proxy_hops=0)
        environ = _TrackingEnviron(
            REMOTE_ADDR="127.0.0.1", HTTP_X_FORWARDED_FOR="198.51.100.9"
        )
        self.assertEqual(probe._get_request_client_ip(environ), "127.0.0.1")
        self.assertEqual(environ.forwarded_for_reads, 0)

    def test_a_peer_that_is_not_this_machine_is_never_asked(self) -> None:
        for hops in range(4):
            with self.subTest(hops=hops):
                probe = _Probe(trusted_proxy_hops=hops)
                environ = _TrackingEnviron(
                    REMOTE_ADDR="198.51.100.9", HTTP_X_FORWARDED_FOR="203.0.113.7"
                )
                self.assertEqual(probe._get_request_client_ip(environ), "198.51.100.9")
                self.assertEqual(environ.forwarded_for_reads, 0)

    def test_no_header_is_the_peer_itself(self) -> None:
        for hops in range(3):
            with self.subTest(hops=hops):
                probe = _Probe(trusted_proxy_hops=hops)
                self.assertEqual(
                    probe._get_request_client_ip({"REMOTE_ADDR": "127.0.0.1"}),
                    "127.0.0.1",
                )

    def test_a_section_without_the_setting_means_one_hop(self) -> None:
        probe = _Probe()
        probe.network_security_config.pop("trusted_proxy_hops", None)
        environ = {"REMOTE_ADDR": "::1", "HTTP_X_FORWARDED_FOR": "a, 198.51.100.9"}
        self.assertEqual(probe._get_request_client_ip(environ), "198.51.100.9")
        probe.network_security_config = cast("dict[str, Any]", None)
        self.assertEqual(probe._get_request_client_ip(environ), "198.51.100.9")


class TestAccessControlJudgesTheVisitor(unittest.TestCase):
    """The real routes behind the real ``before_request`` hooks (a Flask test client)."""

    ui: WebFeedbackUI

    @classmethod
    def setUpClass(cls) -> None:
        cls.ui = WebFeedbackUI(prompt="r849-access", port=0)
        cls.ui.app.config["TESTING"] = True
        cls.ui.limiter.enabled = False

    def _status(
        self,
        forwarded_for: str | None,
        *,
        hops: int | None = None,
        peer: str = "127.0.0.1",
    ) -> int:
        section: dict[str, Any] = {
            "allowed_networks": [ALLOWED],
            "blocked_ips": [BLOCKED],
        }
        if hops is not None:
            section["trusted_proxy_hops"] = hops
        self.ui.network_security_config = validators.validate_network_security_config(
            section
        )
        environ = {"REMOTE_ADDR": peer}
        if forwarded_for is not None:
            environ["HTTP_X_FORWARDED_FOR"] = forwarded_for
        with self.ui.app.test_client() as client:
            return client.get("/api/health", environ_overrides=environ).status_code

    def test_one_proxy_the_default(self) -> None:
        table = [
            (None, 403),  # the proxy itself is not an allowed network
            ("203.0.113.7", 200),
            ("198.51.100.9", 403),
            (BLOCKED, 403),
            # the visitor wrote the first entry, the proxy appended the real address
            ("203.0.113.7, 198.51.100.9", 403),
            ("203.0.113.7, 203.0.113.66", 403),
            ("198.51.100.9, 203.0.113.7", 200),
            ("203.0.113.66, 203.0.113.7", 200),
        ]
        for forwarded_for, status in table:
            with self.subTest(forwarded_for=forwarded_for):
                self.assertEqual(self._status(forwarded_for), status)

    def test_a_cdn_in_front_of_nginx_needs_two_hops(self) -> None:
        # nginx appended the cdn's address to what the cdn had written: client, cdn
        client_then_cdn = "203.0.113.7, 192.0.2.1"
        self.assertEqual(self._status(client_then_cdn, hops=1), 403)
        self.assertEqual(self._status(client_then_cdn, hops=2), 200)
        self.assertEqual(self._status("198.51.100.9, 192.0.2.1", hops=2), 403)
        self.assertEqual(self._status("203.0.113.66, 192.0.2.1", hops=2), 403)

    def test_zero_hops_trusts_no_header(self) -> None:
        self.assertEqual(self._status("203.0.113.7", hops=0), 403)
        self.assertEqual(self._status("203.0.113.7, 203.0.113.8", hops=0), 403)

    def test_a_peer_that_is_not_this_machine_is_judged_by_its_own_address(self) -> None:
        for hops in range(3):
            with self.subTest(hops=hops):
                self.assertEqual(
                    self._status("203.0.113.7", hops=hops, peer="198.51.100.9"), 403
                )
                self.assertEqual(
                    self._status("198.51.100.9", hops=hops, peer="203.0.113.7"), 200
                )


class TestRateLimitKeyIsTheSameAddress(unittest.TestCase):
    """One visitor is one bucket, whatever they write in front of the proxy's entry."""

    def setUp(self) -> None:
        self.ui = WebFeedbackUI(prompt="r849-limit", port=0)
        self.ui.app.config["TESTING"] = True
        self.limiter = cast("WebUiRateLimiter", self.ui.limiter)

    def _clients_seen(self, headers: list[str], **section: object) -> set[str]:
        self.ui.network_security_config = validators.validate_network_security_config(
            {"access_control_enabled": False, **section}
        )
        self.limiter._buckets.clear()
        with self.ui.app.test_client() as client:
            for forwarded_for in headers:
                response = client.get(
                    "/api/config",
                    headers={"X-Forwarded-For": forwarded_for},
                    environ_base={"REMOTE_ADDR": "127.0.0.1"},
                )
                self.assertEqual(response.status_code, 200)
        return {bucket_key[1] for bucket_key in self.limiter._buckets}

    def test_made_up_first_entries_share_the_bucket_of_the_real_address(self) -> None:
        seen = self._clients_seen(
            [
                "10.1.1.1, 192.0.2.9",
                "10.2.2.2, 192.0.2.9",
                "10.3.3.3, 10.4.4.4, 192.0.2.9",
                "10.5.5.5, 192.0.2.8",
            ]
        )
        self.assertEqual(seen, {"192.0.2.9", "192.0.2.8"})

    def test_the_limiter_follows_the_setting_like_the_access_control_does(self) -> None:
        seen = self._clients_seen(
            ["198.51.100.9, 192.0.2.1", "198.51.100.10, 192.0.2.1"],
            trusted_proxy_hops=2,
        )
        self.assertEqual(seen, {"198.51.100.9", "198.51.100.10"})

    def test_zero_hops_is_one_bucket_for_the_proxy(self) -> None:
        seen = self._clients_seen(
            ["198.51.100.9", "198.51.100.10"], trusted_proxy_hops=0
        )
        self.assertEqual(seen, {"127.0.0.1"})

    def test_the_limiter_asks_the_method_the_access_control_asks(self) -> None:
        # one place decides who the client is: both go through _current_client_ip
        self.assertRegex(
            (SRC / "web_ui.py").read_text(encoding="utf-8"),
            r"client_ip=self\._current_client_ip",
        )
        hook = _function(SRC / "web_ui_security.py", "check_ip_and_generate_nonce")
        self.assertIn("_current_client_ip", _attribute_names(hook))
        key = _function(SRC / "web_ui_rate_limiter.py", "_client_key")
        names = _attribute_names(key) | _plain_names(key)
        self.assertNotIn("_parse_forwarded_for", names)
        self.assertNotIn("_should_trust_forwarded_for", names)

    def test_a_limiter_made_without_a_resolver_trusts_no_header(self) -> None:
        bare = WebUiRateLimiter(app=self.ui.app, default_limits=[])
        with self.ui.app.test_request_context(
            "/",
            headers={"X-Forwarded-For": "198.51.100.9"},
            environ_base={"REMOTE_ADDR": "127.0.0.1"},
        ):
            self.assertEqual(bare._client_key(), "127.0.0.1")

    def test_a_resolver_that_fails_falls_back_to_the_peer(self) -> None:
        def broken() -> str:
            raise RuntimeError("no resolver today")

        limiter = WebUiRateLimiter(app=self.ui.app, default_limits=[], client_ip=broken)
        with self.ui.app.test_request_context(
            "/", environ_base={"REMOTE_ADDR": "198.51.100.9"}
        ):
            self.assertEqual(limiter._client_key(), "198.51.100.9")

    def test_an_empty_answer_falls_back_to_the_peer_or_to_unknown(self) -> None:
        limiter = WebUiRateLimiter(
            app=self.ui.app, default_limits=[], client_ip=lambda: ""
        )
        for peer, key in (("198.51.100.9", "198.51.100.9"), ("", "unknown")):
            with (
                self.subTest(peer=peer),
                self.ui.app.test_request_context(
                    "/", environ_base={"REMOTE_ADDR": peer}
                ),
            ):
                self.assertEqual(limiter._client_key(), key)


class TestTheSetting(unittest.TestCase):
    """``network_security.trusted_proxy_hops``: one rule, every reader."""

    VALID = list(range(MAX_HOPS + 1))
    INVALID: list[object] = [
        True,
        False,
        "2",
        "",
        2.0,
        -1,
        MAX_HOPS + 1,
        10**30,
        [1],
        {},
    ]

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = Path(self._tmp.name) / "config.toml"

    def _manager(self, text: str = "") -> ConfigManager:
        self.path.write_text(text, encoding="utf-8")
        return ConfigManager(config_file=str(self.path))

    def test_the_default_is_one_hop_and_the_limits_are_zero_to_eight(self) -> None:
        self.assertEqual(validators.DEFAULT_TRUSTED_PROXY_HOPS, 1)
        self.assertEqual(validators.MAX_TRUSTED_PROXY_HOPS, MAX_HOPS)
        self.assertEqual(NetworkSecuritySectionConfig().trusted_proxy_hops, 1)
        self.assertEqual(
            validators.validate_network_security_config({})["trusted_proxy_hops"], 1
        )

    def test_whole_numbers_from_zero_to_the_maximum_are_kept_silently(self) -> None:
        for value in self.VALID:
            with self.subTest(value=value), patch.object(validators, "logger") as log:
                self.assertEqual(validators.validate_trusted_proxy_hops(value), value)
                log.warning.assert_not_called()

    def test_not_written_is_the_default_without_a_word(self) -> None:
        with patch.object(validators, "logger") as log:
            self.assertEqual(validators.validate_trusted_proxy_hops(None), 1)
            log.warning.assert_not_called()

    def test_anything_else_is_the_default_with_one_warning(self) -> None:
        for value in self.INVALID:
            with (
                self.subTest(value=repr(value)[:20]),
                patch.object(validators, "logger") as log,
            ):
                self.assertEqual(validators.validate_trusted_proxy_hops(value), 1)
                self.assertEqual(log.warning.call_count, 1)
                self.assertIn("trusted_proxy_hops", log.warning.call_args.args[0])

    def test_every_reader_of_the_section_gives_the_same_answer(self) -> None:
        manager = self._manager()
        for value in [*self.VALID, *self.INVALID, None]:
            with self.subTest(value=repr(value)[:20]):
                expected = validators.validate_trusted_proxy_hops(value)
                raw = {"trusted_proxy_hops": value}
                self.assertEqual(
                    validators.validate_network_security_config(raw)[
                        "trusted_proxy_hops"
                    ],
                    expected,
                )
                self.assertEqual(
                    manager._validate_network_security_config(raw)[
                        "trusted_proxy_hops"
                    ],
                    expected,
                )
                model = NetworkSecuritySectionConfig(
                    trusted_proxy_hops=cast("Any", value)
                )
                self.assertEqual(model.trusted_proxy_hops, expected)

    def test_the_three_readers_use_the_one_validator(self) -> None:
        for path, scope in (
            (SRC / "web_ui_validators.py", "validate_network_security_config"),
            (
                SRC / "config_modules" / "network_security.py",
                "_validate_network_security_config",
            ),
            (SRC / "shared_types.py", "NetworkSecuritySectionConfig"),
        ):
            with self.subTest(path=path.name):
                node = _definition(path, scope)
                self.assertIn("validate_trusted_proxy_hops", _plain_names(node))

    def test_a_file_with_the_setting_gives_it_to_the_running_web_ui(self) -> None:
        manager = self._manager(
            f'[network_security]\nallowed_networks = ["{ALLOWED}"]\n'
            "trusted_proxy_hops = 2\n"
        )
        self.assertEqual(manager.get_network_security_config()["trusted_proxy_hops"], 2)
        self.assertEqual(
            manager.get_section("network_security")["trusted_proxy_hops"], 2
        )
        ui = WebFeedbackUI(prompt="r849-file", port=0)
        with patch(
            "ai_intervention_agent.web_ui_security.get_config", return_value=manager
        ):
            ui.network_security_config = ui._load_network_security_config()
        self.assertEqual(ui.network_security_config["trusted_proxy_hops"], 2)
        environ = {
            "REMOTE_ADDR": "127.0.0.1",
            "HTTP_X_FORWARDED_FOR": "203.0.113.7, 192.0.2.1",
        }
        self.assertEqual(ui._get_request_client_ip(environ), "203.0.113.7")

    def test_a_bad_value_in_the_file_is_one_hop_and_everything_else_survives(
        self,
    ) -> None:
        manager = self._manager(
            f'[network_security]\nallowed_networks = ["{ALLOWED}"]\n'
            'trusted_proxy_hops = "two"\n'
        )
        section = manager.get_network_security_config()
        self.assertEqual(section["trusted_proxy_hops"], 1)
        self.assertEqual(section["allowed_networks"], [ALLOWED])
        self.assertEqual(
            manager.get_section("network_security")["trusted_proxy_hops"], 1
        )

    def test_an_update_is_saved_and_read_back(self) -> None:
        manager = self._manager('[network_security]\nbind_interface = "127.0.0.1"\n')
        manager.update_network_security_config({"trusted_proxy_hops": 3})
        self.assertEqual(manager.get_network_security_config()["trusted_proxy_hops"], 3)
        saved = tomllib.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(saved["network_security"]["trusted_proxy_hops"], 3)
        self.assertEqual(saved["network_security"]["bind_interface"], "127.0.0.1")
        again = ConfigManager(config_file=str(self.path))
        self.assertEqual(again.get_network_security_config()["trusted_proxy_hops"], 3)
        manager.update_network_security_config({"trusted_proxy_hops": 99})
        self.assertEqual(manager.get_network_security_config()["trusted_proxy_hops"], 1)

    def test_the_template_and_the_guides_name_it(self) -> None:
        template = tomllib.loads(
            (REPO / "config.toml.default").read_text(encoding="utf-8")
        )
        self.assertEqual(template["network_security"]["trusted_proxy_hops"], 1)
        for name in (
            "configuration.md",
            "configuration.zh-CN.md",
            "deployment.md",
            "deployment.zh-CN.md",
        ):
            with self.subTest(guide=name):
                text = (REPO / "docs" / name).read_text(encoding="utf-8")
                self.assertIn("trusted_proxy_hops", text)
        for name in ("deployment.md", "deployment.zh-CN.md"):
            with self.subTest(guide=name):
                text = (REPO / "docs" / name).read_text(encoding="utf-8")
                self.assertIn("proxy_set_header X-Forwarded-For", text)
        # a number above the real count of proxies lets the visitor pick the address,
        # so the guides that tell how to set it say so
        for name, warning in (
            (
                "deployment.md",
                "larger number makes an entry the visitor wrote the client",
            ),
            ("deployment.zh-CN.md", "填得比实际多时，访问者自己写的一项会被当成客户端"),
        ):
            with self.subTest(guide=name, warns="a number above the real count"):
                text = (REPO / "docs" / name).read_text(encoding="utf-8")
                self.assertIn(warning, " ".join(text.split()))


def _definition(path: Path, name: str) -> ast.AST:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)) and node.name == name:
            return node
    raise AssertionError(f"{name} not found in {path.name}")


def _function(path: Path, name: str) -> ast.FunctionDef:
    node = _definition(path, name)
    assert isinstance(node, ast.FunctionDef)
    return node


def _plain_names(node: ast.AST) -> set[str]:
    return {child.id for child in ast.walk(node) if isinstance(child, ast.Name)}


def _attribute_names(node: ast.AST) -> set[str]:
    return {child.attr for child in ast.walk(node) if isinstance(child, ast.Attribute)}


if __name__ == "__main__":
    unittest.main()
