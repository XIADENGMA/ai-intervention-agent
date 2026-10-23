"""R843: "is this entry a valid IP / network, and how is it written" is decided once.

The ``[network_security]`` section was validated by two independent implementations:

* ``web_ui_validators`` (``validate_allowed_networks`` and friends), which the access
  control of the Web UI runs over the section it loads, and
* ``ConfigManager._validate_network_security_config``, which every read and save of the
  section runs first: ~200 lines, 36 branches, a copy of the same loops for
  ``allowed_networks`` and ``blocked_ips`` and a third one for ``trusted_hosts``.

In production the data went through both, one after the other, so the second pass was
mostly redundant, but the two copies were already different in small ways (whitespace,
duplicates, how an IPv4-mapped IPv6 address is written, what a non-list means), and
nothing said which of them was meant.  Now the per-entry rules live in
``web_ui_validators.normalize_ip_entries`` / ``validate_trusted_hosts`` /
``parse_bind_interface`` and the manager only chooses *which value* goes in and *what to
fall back to* (and cleans the two ``api_token`` keys, which only it knows).

Equivalence was checked against the previous code with 200 000 random sections (every
kind of garbage: blanks, non-strings, mapped addresses, duplicates, huge netmasks,
control characters, non-lists): the section the access control enforces is identical,
except that two spellings of the same IPv4 address (``::ffff:1.2.3.4`` and ``1.2.3.4``)
now collapse into one entry.  The table below pins a representative slice of those
results, so it keeps being true.
"""

from __future__ import annotations

import ast
import ipaddress
import unittest
from pathlib import Path
from unittest.mock import patch

from ai_intervention_agent import web_ui_validators as validators
from ai_intervention_agent.config_manager import ConfigManager
from ai_intervention_agent.shared_types import NetworkSecuritySectionConfig
from ai_intervention_agent.web_ui_security import _DEFAULT_ALLOWED_NETWORKS

SRC = Path(__file__).resolve().parents[1] / "src" / "ai_intervention_agent"
MANAGER_MODULE = SRC / "config_modules" / "network_security.py"
VALIDATORS_MODULE = SRC / "web_ui_validators.py"

LOOPBACK_ONLY = ["127.0.0.0/8", "::1/128"]
DEFAULT_ALLOWED = [*LOOPBACK_ONLY, "192.168.0.0/16", "10.0.0.0/8", "172.16.0.0/12"]


def _enforced(raw: object) -> dict[str, object]:
    """The section the Web UI's access control ends up with for ``raw``.

    ``WebFeedbackUI._load_network_security_config`` runs the manager's validation first
    (``get_section("network_security")``) and the Web UI validator over the result.
    """
    manager = ConfigManager()
    return validators.validate_network_security_config(
        manager._validate_network_security_config(raw)
    )


def _expected(**overrides: object) -> dict[str, object]:
    section: dict[str, object] = {
        "bind_interface": "0.0.0.0",
        "allowed_networks": list(DEFAULT_ALLOWED),
        "blocked_ips": [],
        "trusted_hosts": [],
        "trusted_proxy_hops": 1,
        "access_control_enabled": True,
    }
    section.update(overrides)
    return section


def _function_node(path: Path, name: str) -> ast.FunctionDef:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"{name} not found in {path.name}")


def _called_names(node: ast.AST) -> list[str]:
    return [
        call.func.id
        for call in ast.walk(node)
        if isinstance(call, ast.Call) and isinstance(call.func, ast.Name)
    ]


class TestEntryNormaliser(unittest.TestCase):
    """``normalize_ip_entries``: the one definition of a usable list entry."""

    def test_whitespace_is_stripped_and_blank_entries_vanish_silently(self) -> None:
        with patch.object(validators, "logger") as log:
            result = validators.normalize_ip_entries(
                ["  10.0.0.1  ", "", "   ", "\t\n", "\u00a0192.168.1.1\u00a0"], "x"
            )
        self.assertEqual(result, ["10.0.0.1", "192.168.1.1"])
        log.warning.assert_not_called()

    def test_networks_are_written_canonically_and_duplicates_collapse(self) -> None:
        # 10.0.0.5/8 is the network 10.0.0.0/8; the three spellings are one entry
        result = validators.normalize_ip_entries(
            ["10.0.0.5/8", " 10.0.0.0/8 ", "10.0.0.0/255.0.0.0", "172.16.1.1"], "x"
        )
        self.assertEqual(result, ["10.0.0.0/8", "172.16.1.1"])

    def test_a_network_with_host_bits_means_the_network(self) -> None:
        # Dropping it instead would leave a blocked range unblocked.
        result = validators.normalize_ip_entries(
            ["192.168.1.77/24", "2001:db8::5/32"], "x"
        )
        self.assertEqual(result, ["192.168.1.0/24", "2001:db8::/32"])

    def test_ipv4_mapped_single_address_is_written_as_ipv4(self) -> None:
        result = validators.normalize_ip_entries(
            ["::ffff:10.0.0.1", "10.0.0.1", "::FFFF:c0a8:101"], "x"
        )
        self.assertEqual(result, ["10.0.0.1", "192.168.1.1"])

    def test_order_of_first_appearance_is_kept(self) -> None:
        result = validators.normalize_ip_entries(
            ["::1", "10.0.0.1", "::1", "8.8.8.8"], "x"
        )
        self.assertEqual(result, ["::1", "10.0.0.1", "8.8.8.8"])

    def test_each_unusable_entry_is_dropped_with_one_warning(self) -> None:
        with patch.object(validators, "logger") as log:
            result = validators.normalize_ip_entries(
                [123, "nope", "10.0.0.0/33", None, "10.0.0.1"], "blocked_ips"
            )
        self.assertEqual(result, ["10.0.0.1"])
        self.assertEqual(log.warning.call_count, 4)
        for call in log.warning.call_args_list:
            self.assertIn("blocked_ips", call.args[0])

    def test_a_netmask_of_any_size_is_just_invalid(self) -> None:
        # int() refuses long digit strings with ValueError, which must stay a dropped entry
        result = validators.normalize_ip_entries(
            ["1.2.3.4/" + "9" * 5000, "1.2.3.4"], "x"
        )
        self.assertEqual(result, ["1.2.3.4"])


class TestFallbackPolicies(unittest.TestCase):
    """What an unusable list turns into is a policy, and each caller states its own."""

    def test_enforcement_validator_keeps_the_documented_default_for_a_non_list(
        self,
    ) -> None:
        self.assertEqual(validators.validate_allowed_networks("oops"), DEFAULT_ALLOWED)

    def test_the_manager_falls_back_to_loopback_only_for_a_non_list(self) -> None:
        # A typo in the file (a string instead of a list) must not open the whole LAN.
        manager = ConfigManager()
        result = manager._validate_network_security_config(
            {"allowed_networks": "192.168.1.0/24"}
        )
        self.assertEqual(result["allowed_networks"], LOOPBACK_ONLY)

    def test_empty_and_all_invalid_lists_mean_loopback_only_in_both(self) -> None:
        manager = ConfigManager()
        for value in ([], ["nope", "300.1.1.1", 7, None]):
            with self.subTest(value=value):
                self.assertEqual(
                    validators.validate_allowed_networks(value), LOOPBACK_ONLY
                )
                self.assertEqual(
                    manager._validate_network_security_config(
                        {"allowed_networks": value}
                    )["allowed_networks"],
                    LOOPBACK_ONLY,
                )

    def test_an_explicit_empty_list_is_not_worth_a_warning(self) -> None:
        # The manager validates on every cache refresh; "allowed_networks = []" must not
        # turn into a warning each time.  Entries that were all unusable are another matter.
        with patch.object(validators, "logger") as log:
            validators.validate_allowed_networks([])
        log.warning.assert_not_called()
        with patch.object(validators, "logger") as log:
            validators.validate_allowed_networks(["nope"])
        self.assertEqual(log.warning.call_count, 2)  # the entry, then the fallback

    def test_a_missing_blocklist_is_silent_and_a_malformed_one_is_reported(
        self,
    ) -> None:
        with patch.object(validators, "logger") as log:
            self.assertEqual(validators.validate_blocked_ips(None), [])
            self.assertEqual(validators.validate_trusted_hosts(None), [])
        log.warning.assert_not_called()
        with patch.object(validators, "logger") as log:
            self.assertEqual(validators.validate_blocked_ips("10.0.0.1"), [])
            self.assertEqual(validators.validate_trusted_hosts("ai.example.com"), [])
        self.assertEqual(log.warning.call_count, 2)

    def test_the_default_lists_agree_wherever_they_are_written(self) -> None:
        manager_default = ConfigManager()._get_default_config()["network_security"]
        self.assertEqual(validators.DEFAULT_ALLOWED_NETWORKS, DEFAULT_ALLOWED)
        self.assertEqual(
            NetworkSecuritySectionConfig().allowed_networks, DEFAULT_ALLOWED
        )
        self.assertEqual(manager_default["allowed_networks"], DEFAULT_ALLOWED)
        self.assertEqual(validators.LOOPBACK_ALLOWED_NETWORKS, LOOPBACK_ONLY)
        self.assertEqual(list(_DEFAULT_ALLOWED_NETWORKS), LOOPBACK_ONLY)


class TestEnforcedSection(unittest.TestCase):
    """What the access control enforces for a given ``[network_security]`` table."""

    CASES: tuple[tuple[str, object, dict[str, object]], ...] = (
        ("empty section", {}, _expected()),
        ("not a table", "oops", _expected()),
        (
            "padding and duplicates",
            {
                "allowed_networks": [
                    " 10.0.0.5/8 ",
                    "10.0.0.0/8",
                    "192.168.1.5",
                    "\t192.168.1.5\n",
                ]
            },
            _expected(allowed_networks=["10.0.0.0/8", "192.168.1.5"]),
        ),
        (
            "IPv4-mapped blocked addresses",
            {
                "blocked_ips": [
                    "::ffff:10.0.0.1",
                    "10.0.0.1",
                    "::FFFF:1.2.3.4",
                    " ::ffff:c0a8:101 ",
                ]
            },
            _expected(blocked_ips=["10.0.0.1", "1.2.3.4", "192.168.1.1"]),
        ),
        (
            "allowed_networks is a string",
            {"allowed_networks": "192.168.1.0/24"},
            _expected(allowed_networks=LOOPBACK_ONLY),
        ),
        (
            "allowed_networks is all invalid",
            {"allowed_networks": ["nope", "300.1.1.1", 7, None]},
            _expected(allowed_networks=LOOPBACK_ONLY),
        ),
        (
            "allowed_networks is empty",
            {"allowed_networks": []},
            _expected(allowed_networks=LOOPBACK_ONLY),
        ),
        ("blocked_ips is a string", {"blocked_ips": "10.0.0.1"}, _expected()),
        (
            "blocked_ips with garbage between",
            {"blocked_ips": ["10.0.0.0/33", "10.0.0.1", "", 5, "fe80::1%eth0", "::1"]},
            _expected(blocked_ips=["10.0.0.1", "fe80::1%eth0", "::1"]),
        ),
        (
            "legacy switch name",
            {"enable_access_control": False},
            _expected(access_control_enabled=False),
        ),
        (
            "switch written as a string",
            {"access_control_enabled": "false"},
            _expected(access_control_enabled=False),
        ),
        (
            "switch written as nonsense stays on",
            {"access_control_enabled": "maybe"},
            _expected(access_control_enabled=True),
        ),
        (
            "bind address with padding",
            {"bind_interface": " 192.168.1.5 "},
            _expected(bind_interface="192.168.1.5"),
        ),
        (
            "bind address in long IPv6 form",
            {"bind_interface": "0:0:0:0:0:0:0:2"},
            _expected(bind_interface="::2"),
        ),
        (
            "bind address is a host name",
            {"bind_interface": "my-host.local"},
            _expected(bind_interface="127.0.0.1"),
        ),
        (
            "bind address is a number",
            {"bind_interface": 12345},
            _expected(bind_interface="127.0.0.1"),
        ),
        (
            "bind address is the IPv6 wildcard",
            {"bind_interface": "::"},
            _expected(bind_interface="::"),
        ),
        (
            "trusted hosts with wildcards, blanks and a duplicate",
            {
                "trusted_hosts": [
                    "ai.example.com",
                    "*.example.com",
                    ".example.com",
                    " h.example ",
                    "ai.example.com",
                    "",
                    None,
                    3,
                ]
            },
            _expected(trusted_hosts=["ai.example.com", "h.example"]),
        ),
        (
            "trusted_hosts is a string",
            {"trusted_hosts": "ai.example.com"},
            _expected(),
        ),
    )

    def test_enforced_section(self) -> None:
        for label, raw, expected in self.CASES:
            with self.subTest(label):
                self.assertEqual(_enforced(raw), expected)

    def test_the_manager_output_is_stable_under_the_enforcement_validator(self) -> None:
        # Validating what the manager produced changes nothing about the lists any more:
        # both sides agree on what a clean entry looks like.
        manager = ConfigManager()
        for label, raw, _expected_section in self.CASES:
            with self.subTest(label):
                once = manager._validate_network_security_config(raw)
                again = validators.validate_network_security_config(once)
                for key in (
                    "bind_interface",
                    "allowed_networks",
                    "blocked_ips",
                    "trusted_hosts",
                ):
                    self.assertEqual(again[key], once[key])


class TestBindInterface(unittest.TestCase):
    def test_parse_bind_interface_never_logs(self) -> None:
        values = [
            "0.0.0.0",
            "127.0.0.1",
            " 192.168.1.5 ",
            "::1",
            "my-host.local",
            "",
            "  ",
            None,
            12345,
            ["127.0.0.1"],
        ]
        with patch.object(validators, "logger") as log:
            parsed = [validators.parse_bind_interface(value) for value in values]
        self.assertEqual(
            parsed,
            [
                "0.0.0.0",
                "127.0.0.1",
                "192.168.1.5",
                "::1",
                None,
                None,
                None,
                None,
                None,
                None,
            ],
        )
        self.assertFalse(log.method_calls)

    def test_the_manager_does_not_add_info_lines_for_a_valid_bind_address(self) -> None:
        # validate_bind_interface announces the address at INFO; the manager validates on
        # every cache refresh and must stay quiet about an address that is fine.
        manager = ConfigManager()
        for value in ("0.0.0.0", "192.168.1.5", "::"):
            with self.subTest(value), patch.object(validators, "logger") as log:
                manager._validate_network_security_config({"bind_interface": value})
            self.assertFalse(log.method_calls)

    def test_a_non_string_that_prints_as_an_address_is_still_accepted(self) -> None:
        # The manager has always converted with str() before judging the value.
        manager = ConfigManager()
        result = manager._validate_network_security_config(
            {"bind_interface": ipaddress.ip_address("10.1.2.3")}
        )
        self.assertEqual(result["bind_interface"], "10.1.2.3")

    def test_the_public_validator_keeps_its_messages(self) -> None:
        with patch.object(validators, "logger") as log:
            self.assertEqual(validators.validate_bind_interface("0.0.0.0"), "0.0.0.0")
            self.assertEqual(validators.validate_bind_interface("10.1.2.3"), "10.1.2.3")
            self.assertEqual(
                validators.validate_bind_interface("127.0.0.1"), "127.0.0.1"
            )
        self.assertEqual(
            log.info.call_count, 2
        )  # wildcard and custom address, not loopback
        with patch.object(validators, "logger") as log:
            self.assertEqual(validators.validate_bind_interface(" nope "), "127.0.0.1")
            self.assertEqual(validators.validate_bind_interface(""), "127.0.0.1")
            self.assertEqual(validators.validate_bind_interface(None), "127.0.0.1")
        self.assertEqual(log.warning.call_count, 3)
        self.assertIn("'nope'", log.warning.call_args_list[0].args[0])


class TestOneHome(unittest.TestCase):
    """No second copy of the per-entry rules grows back in the manager."""

    def test_the_manager_method_only_chooses_inputs_and_fallbacks(self) -> None:
        node = _function_node(MANAGER_MODULE, "_validate_network_security_config")
        loops = [
            type(child).__name__
            for child in ast.walk(node)
            if isinstance(child, (ast.For, ast.AsyncFor, ast.While, ast.Try))
        ]
        self.assertEqual(loops, [], "list handling belongs in web_ui_validators")

    def test_the_manager_module_parses_no_networks_itself(self) -> None:
        tree = ast.parse(MANAGER_MODULE.read_text(encoding="utf-8"))
        self.assertEqual(
            [name for name in _called_names(tree) if name == "ip_network"], []
        )
        imported = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module == "ipaddress"
            for alias in node.names
        }
        self.assertEqual(imported, {"ip_address"})
        # the one remaining use: writing an already-validated bind address canonically
        self.assertEqual(
            [name for name in _called_names(tree) if name == "ip_address"],
            ["ip_address"],
        )

    def test_the_list_validators_delegate_every_entry_to_the_normaliser(self) -> None:
        for name in ("validate_allowed_networks", "validate_blocked_ips"):
            with self.subTest(name):
                called = _called_names(_function_node(VALIDATORS_MODULE, name))
                self.assertIn("normalize_ip_entries", called)
                self.assertNotIn("ip_network", called)
                self.assertNotIn("ip_address", called)

    def test_entries_are_parsed_in_one_place(self) -> None:
        tree = ast.parse(VALIDATORS_MODULE.read_text(encoding="utf-8"))
        holders = sorted(
            node.name
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and "ip_network" in _called_names(node)
        )
        # the entry parser, and the standalone CIDR check that predates it
        self.assertEqual(holders, ["_canonical_ip_entry", "validate_network_cidr"])

    def test_the_fallback_list_is_defined_once(self) -> None:
        offenders = [
            path.name
            for path in (MANAGER_MODULE, SRC / "web_ui_security.py")
            if '"::1/128"' in path.read_text(encoding="utf-8")
        ]
        self.assertEqual(offenders, [])


if __name__ == "__main__":
    unittest.main()
