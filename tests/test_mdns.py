import unittest
from unittest.mock import patch


class TestMdnsHelpers(unittest.TestCase):
    def test_normalize_mdns_hostname_default(self):
        from web_ui import MDNS_DEFAULT_HOSTNAME, normalize_mdns_hostname

        self.assertEqual(normalize_mdns_hostname(None), MDNS_DEFAULT_HOSTNAME)
        self.assertEqual(normalize_mdns_hostname(""), MDNS_DEFAULT_HOSTNAME)
        self.assertEqual(normalize_mdns_hostname("   "), MDNS_DEFAULT_HOSTNAME)

    def test_normalize_mdns_hostname_suffix(self):
        from web_ui import normalize_mdns_hostname

        self.assertEqual(normalize_mdns_hostname("ai"), "ai.local")
        self.assertEqual(normalize_mdns_hostname("ai.local"), "ai.local")
        self.assertEqual(normalize_mdns_hostname("ai.local."), "ai.local")

    def test_detect_best_publish_ipv4_prefers_bind_interface_when_specific(self):
        from web_ui import detect_best_publish_ipv4

        self.assertEqual(detect_best_publish_ipv4("192.168.1.23"), "192.168.1.23")

    def test_detect_best_publish_ipv4_uses_default_route(self):
        from web_ui import detect_best_publish_ipv4

        with patch("web_ui._list_non_loopback_ipv4", return_value=[]), patch(
            "web_ui._get_default_route_ipv4", return_value="192.168.0.10"
        ):
            self.assertEqual(detect_best_publish_ipv4("0.0.0.0"), "192.168.0.10")

    def test_detect_best_publish_ipv4_fallback_to_interface_scan(self):
        from web_ui import detect_best_publish_ipv4

        with patch("web_ui._get_default_route_ipv4", return_value=None), patch(
            "web_ui._list_non_loopback_ipv4", return_value=["10.0.0.5"]
        ):
            self.assertEqual(detect_best_publish_ipv4("0.0.0.0"), "10.0.0.5")


if __name__ == "__main__":
    unittest.main()

