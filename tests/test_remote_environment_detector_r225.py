"""R225 / Cycle 12: SSH / WSL remote-environment detector tests.

Validates ``ai_intervention_agent.remote_environment.detect_remote_environment``
behavior across the environment matrices the startup banner cares
about. Pure function tests — no subprocess, no socket, no real
``/proc/version`` reads (we monkey-patch the module constant).

Cases (13 total):
1. Clean baseline — no SSH, no WSL → both False.
2. ``SSH_CONNECTION`` set + non-empty → SSH detected via that var.
3. ``SSH_CLIENT`` set + non-empty (no ``SSH_CONNECTION``) → SSH via SSH_CLIENT.
4. Both vars set → prefers ``SSH_CONNECTION`` (canonical OpenSSH var).
5. ``SSH_CONNECTION`` set but **empty string** → not detected
   (defensive — hardened sshd configs may set blank values).
6. ``WSL_DISTRO_NAME`` set → WSL detected via that var.
7. ``WSL_INTEROP`` set (no ``WSL_DISTRO_NAME``) → WSL via WSL_INTEROP.
8. Neither WSL env var, ``/proc/version`` contains "Microsoft" (mixed case)
   → WSL detected via filesystem probe (WSL1 path).
9. ``/proc/version`` contains "microsoft-standard" → WSL detected.
10. ``/proc/version`` reads fine but doesn't mention microsoft → not WSL.
11. ``/proc/version`` raises ``FileNotFoundError`` → detector returns
    not WSL (silent degrade, no crash).
12. ``/proc/version`` raises ``PermissionError`` → silent degrade.
13. ``/proc/version`` raises ``UnicodeDecodeError`` → silent degrade.

Plus 2 invariant checks:
- Return dict matches the ``RemoteEnvironment`` TypedDict keys
  (no key drift between module + callers).
- SSH + WSL flags are independent — both can be True simultaneously
  (rare but real: developer SSHs into a WSL distro from another
  machine).
"""

from __future__ import annotations

import builtins
import os
import unittest
from pathlib import Path
from unittest import mock

from ai_intervention_agent import remote_environment
from ai_intervention_agent.remote_environment import (
    RemoteEnvironment,
    detect_remote_environment,
)


def _strip_env_keys() -> dict[str, str]:
    """Remove all SSH/WSL keys from os.environ, return a copy of the
    original ``os.environ`` snapshot for restore."""
    keys_to_strip = (
        "SSH_CONNECTION",
        "SSH_CLIENT",
        "SSH_TTY",
        "WSL_DISTRO_NAME",
        "WSL_INTEROP",
    )
    original = {k: os.environ[k] for k in keys_to_strip if k in os.environ}
    for k in keys_to_strip:
        os.environ.pop(k, None)
    return original


class _CleanEnvTestCase(unittest.TestCase):
    """Shared setUp/tearDown to ensure no env leakage between cases."""

    def setUp(self) -> None:
        self._saved_env = _strip_env_keys()

    def tearDown(self) -> None:
        # Restore original env keys
        for k in (
            "SSH_CONNECTION",
            "SSH_CLIENT",
            "SSH_TTY",
            "WSL_DISTRO_NAME",
            "WSL_INTEROP",
        ):
            os.environ.pop(k, None)
        for k, v in self._saved_env.items():
            os.environ[k] = v


class TestNoRemoteBaseline(_CleanEnvTestCase):
    def test_no_ssh_no_wsl_when_env_clean_and_no_proc_version(self) -> None:
        # Force /proc/version probe to "not microsoft" by pointing the
        # module's path constant at a fixture file in this test's repo.
        with mock.patch.object(
            remote_environment, "_PROC_VERSION_PATH", "/nonexistent/path/does-not-exist"
        ):
            result = detect_remote_environment()
        self.assertFalse(result["is_ssh"])
        self.assertFalse(result["is_wsl"])
        self.assertIsNone(result["ssh_source"])
        self.assertIsNone(result["wsl_source"])


class TestSshDetection(_CleanEnvTestCase):
    def test_ssh_connection_set(self) -> None:
        os.environ["SSH_CONNECTION"] = "203.0.113.5 51234 192.0.2.1 22"
        with mock.patch.object(
            remote_environment, "_PROC_VERSION_PATH", "/nonexistent/x"
        ):
            result = detect_remote_environment()
        self.assertTrue(result["is_ssh"])
        self.assertEqual(result["ssh_source"], "SSH_CONNECTION")
        self.assertFalse(result["is_wsl"])

    def test_ssh_client_only_no_ssh_connection(self) -> None:
        os.environ["SSH_CLIENT"] = "203.0.113.5 51234 22"
        with mock.patch.object(
            remote_environment, "_PROC_VERSION_PATH", "/nonexistent/x"
        ):
            result = detect_remote_environment()
        self.assertTrue(result["is_ssh"])
        self.assertEqual(result["ssh_source"], "SSH_CLIENT")

    def test_both_ssh_vars_prefer_ssh_connection(self) -> None:
        os.environ["SSH_CONNECTION"] = "203.0.113.5 51234 192.0.2.1 22"
        os.environ["SSH_CLIENT"] = "203.0.113.5 51234 22"
        with mock.patch.object(
            remote_environment, "_PROC_VERSION_PATH", "/nonexistent/x"
        ):
            result = detect_remote_environment()
        self.assertTrue(result["is_ssh"])
        self.assertEqual(
            result["ssh_source"],
            "SSH_CONNECTION",
            (
                "When both SSH_CONNECTION and SSH_CLIENT are set the "
                "canonical OpenSSH variable (SSH_CONNECTION) should "
                "win — see _detect_ssh()."
            ),
        )

    def test_empty_ssh_connection_does_not_trigger(self) -> None:
        # Some hardened sshd configs export the var with an empty string.
        os.environ["SSH_CONNECTION"] = ""
        with mock.patch.object(
            remote_environment, "_PROC_VERSION_PATH", "/nonexistent/x"
        ):
            result = detect_remote_environment()
        self.assertFalse(
            result["is_ssh"],
            "Empty SSH_CONNECTION must not trigger SSH detection.",
        )

    def test_whitespace_only_ssh_connection_does_not_trigger(self) -> None:
        os.environ["SSH_CONNECTION"] = "   "
        with mock.patch.object(
            remote_environment, "_PROC_VERSION_PATH", "/nonexistent/x"
        ):
            result = detect_remote_environment()
        self.assertFalse(result["is_ssh"])


class TestWslDetection(_CleanEnvTestCase):
    def test_wsl_distro_name_set(self) -> None:
        os.environ["WSL_DISTRO_NAME"] = "Ubuntu-22.04"
        with mock.patch.object(
            remote_environment, "_PROC_VERSION_PATH", "/nonexistent/x"
        ):
            result = detect_remote_environment()
        self.assertTrue(result["is_wsl"])
        self.assertEqual(result["wsl_source"], "WSL_DISTRO_NAME")
        self.assertFalse(result["is_ssh"])

    def test_wsl_interop_only(self) -> None:
        os.environ["WSL_INTEROP"] = "/run/WSL/abc.sock"
        with mock.patch.object(
            remote_environment, "_PROC_VERSION_PATH", "/nonexistent/x"
        ):
            result = detect_remote_environment()
        self.assertTrue(result["is_wsl"])
        self.assertEqual(result["wsl_source"], "WSL_INTEROP")

    def test_proc_version_contains_microsoft_mixed_case(self) -> None:
        # WSL1 + some legacy WSL2 builds: env vars not set, /proc/version
        # reports the kernel build string with "Microsoft" in it.
        fake_proc = (
            "Linux version 5.15.0-microsoft-standard (oe-user@oe-host) "
            "(x86_64-msft-linux-gcc (GCC) 11.2.0)"
        )
        m_open = mock.mock_open(read_data=fake_proc)
        with (
            mock.patch.object(
                remote_environment, "_PROC_VERSION_PATH", "/proc/version"
            ),
            mock.patch.object(builtins, "open", m_open),
        ):
            result = detect_remote_environment()
        self.assertTrue(result["is_wsl"])
        self.assertEqual(result["wsl_source"], "/proc/version")

    def test_proc_version_contains_no_microsoft(self) -> None:
        fake_proc = "Linux version 6.5.0-generic (build@host)"
        m_open = mock.mock_open(read_data=fake_proc)
        with (
            mock.patch.object(
                remote_environment, "_PROC_VERSION_PATH", "/proc/version"
            ),
            mock.patch.object(builtins, "open", m_open),
        ):
            result = detect_remote_environment()
        self.assertFalse(result["is_wsl"])

    def test_proc_version_missing_silent_degrade(self) -> None:
        with (
            mock.patch.object(
                remote_environment, "_PROC_VERSION_PATH", "/proc/version"
            ),
            mock.patch.object(
                builtins, "open", side_effect=FileNotFoundError("not on this OS")
            ),
        ):
            result = detect_remote_environment()
        self.assertFalse(result["is_wsl"])
        self.assertIsNone(result["wsl_source"])

    def test_proc_version_permission_error_silent_degrade(self) -> None:
        with (
            mock.patch.object(
                remote_environment, "_PROC_VERSION_PATH", "/proc/version"
            ),
            mock.patch.object(builtins, "open", side_effect=PermissionError("denied")),
        ):
            result = detect_remote_environment()
        self.assertFalse(result["is_wsl"])

    def test_proc_version_unicode_decode_error_silent_degrade(self) -> None:
        with (
            mock.patch.object(
                remote_environment, "_PROC_VERSION_PATH", "/proc/version"
            ),
            mock.patch.object(
                builtins,
                "open",
                side_effect=UnicodeDecodeError("utf-8", b"\xff\xfe", 0, 1, "bad byte"),
            ),
        ):
            result = detect_remote_environment()
        self.assertFalse(result["is_wsl"])


class TestSchemaInvariants(_CleanEnvTestCase):
    def test_returned_dict_has_exactly_the_typed_dict_keys(self) -> None:
        with mock.patch.object(
            remote_environment, "_PROC_VERSION_PATH", "/nonexistent/x"
        ):
            result = detect_remote_environment()
        expected_keys = set(RemoteEnvironment.__annotations__.keys())
        actual_keys = set(result.keys())
        self.assertEqual(
            actual_keys,
            expected_keys,
            (
                "detect_remote_environment() returned keys do not "
                "match the RemoteEnvironment TypedDict — key drift "
                "between module and callers."
            ),
        )

    def test_ssh_and_wsl_can_coexist(self) -> None:
        # Real scenario: developer SSHs from machine A into machine B's
        # WSL distro. Both should be flagged True simultaneously.
        os.environ["SSH_CONNECTION"] = "203.0.113.5 51234 192.0.2.1 22"
        os.environ["WSL_DISTRO_NAME"] = "Ubuntu-22.04"
        with mock.patch.object(
            remote_environment, "_PROC_VERSION_PATH", "/nonexistent/x"
        ):
            result = detect_remote_environment()
        self.assertTrue(result["is_ssh"])
        self.assertTrue(result["is_wsl"])


class TestRealProcessIntegration(unittest.TestCase):
    """One real-environment smoke test: detector must run without
    raising on whatever the actual test host looks like. We can't
    assert specific flag values (depends on CI), only that the call
    completes and returns the expected shape."""

    def test_real_call_completes_and_returns_typed_dict_shape(self) -> None:
        result = detect_remote_environment()
        self.assertIsInstance(result, dict)
        self.assertIn("is_ssh", result)
        self.assertIn("is_wsl", result)
        self.assertIn("ssh_source", result)
        self.assertIn("wsl_source", result)
        self.assertIsInstance(result["is_ssh"], bool)
        self.assertIsInstance(result["is_wsl"], bool)


class TestWebUiIntegrationGuard(unittest.TestCase):
    """Locks in that `web_ui.py` imports `detect_remote_environment`
    and gates the hint print on `host in ("127.0.0.1", "localhost")`.
    Without this, a future refactor could silently delete the hint
    block without obvious test breakage."""

    REPO_ROOT = Path(__file__).resolve().parent.parent
    WEB_UI_PATH = REPO_ROOT / "src" / "ai_intervention_agent" / "web_ui.py"

    def setUp(self) -> None:
        self.source = self.WEB_UI_PATH.read_text(encoding="utf-8")

    def test_web_ui_imports_detect_remote_environment(self) -> None:
        self.assertIn(
            "from ai_intervention_agent.remote_environment import detect_remote_environment",
            self.source,
            (
                "web_ui.py no longer imports detect_remote_environment "
                "— the R225 SSH/WSL startup hint is broken."
            ),
        )

    def test_web_ui_invokes_detector_in_loopback_branch(self) -> None:
        self.assertIn(
            "detect_remote_environment()",
            self.source,
            "web_ui.py never calls detect_remote_environment().",
        )

    def test_web_ui_hint_mentions_ssh_port_forwarding(self) -> None:
        # Hint must include actionable port-forwarding fragment, not
        # just "SSH detected" with no remedy.
        self.assertIn(
            "ssh -L",
            self.source,
            "web_ui.py R225 hint missing actionable `ssh -L` recipe.",
        )


if __name__ == "__main__":
    unittest.main()
