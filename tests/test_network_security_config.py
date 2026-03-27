"""
Network Security 配置模块单元测试

测试覆盖：
    - validate_bind_interface() 函数
    - validate_network_cidr() 函数
    - validate_allowed_networks() 函数
    - validate_blocked_ips() 函数
    - validate_network_security_config() 函数
    - _load_network_security_config() 方法
"""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from config_manager import ConfigManager


class TestValidateBindInterface(unittest.TestCase):
    """测试 validate_bind_interface() 函数"""

    def test_valid_special_values(self):
        """测试有效的特殊值"""
        from web_ui import validate_bind_interface

        # 所有特殊值应该直接通过
        special_values = ["0.0.0.0", "127.0.0.1", "localhost", "::1", "::"]
        for value in special_values:
            result = validate_bind_interface(value)
            self.assertEqual(result, value, f"特殊值 {value} 应该直接通过")

    def test_valid_ip_addresses(self):
        """测试有效的 IP 地址"""
        from web_ui import validate_bind_interface

        valid_ips = ["192.168.1.1", "10.0.0.1", "172.16.0.1", "::ffff:192.168.1.1"]
        for ip in valid_ips:
            result = validate_bind_interface(ip)
            self.assertEqual(result, ip, f"有效 IP {ip} 应该通过")

    def test_invalid_ip_addresses(self):
        """测试无效的 IP 地址"""
        from web_ui import validate_bind_interface

        invalid_ips = ["invalid", "256.1.1.1", "192.168.1", "abc.def.ghi.jkl"]
        for ip in invalid_ips:
            result = validate_bind_interface(ip)
            self.assertEqual(result, "127.0.0.1", f"无效 IP {ip} 应该使用默认值")

    def test_empty_value(self):
        """测试空值"""
        from web_ui import validate_bind_interface

        self.assertEqual(validate_bind_interface(""), "127.0.0.1")
        self.assertEqual(validate_bind_interface(None), "127.0.0.1")

    def test_whitespace_handling(self):
        """测试空白字符处理"""
        from web_ui import validate_bind_interface

        # 带空白的有效值应该被处理
        self.assertEqual(validate_bind_interface("  127.0.0.1  "), "127.0.0.1")


class TestValidateNetworkCidr(unittest.TestCase):
    """测试 validate_network_cidr() 函数"""

    def test_valid_cidr_ipv4(self):
        """测试有效的 IPv4 CIDR"""
        from web_ui import validate_network_cidr

        valid_cidrs = [
            "192.168.0.0/16",
            "10.0.0.0/8",
            "172.16.0.0/12",
            "127.0.0.0/8",
            "192.168.1.0/24",
        ]
        for cidr in valid_cidrs:
            self.assertTrue(
                validate_network_cidr(cidr), f"有效 CIDR {cidr} 应该返回 True"
            )

    def test_valid_cidr_ipv6(self):
        """测试有效的 IPv6 CIDR"""
        from web_ui import validate_network_cidr

        valid_cidrs = ["::1/128", "fe80::/10", "2001:db8::/32"]
        for cidr in valid_cidrs:
            self.assertTrue(
                validate_network_cidr(cidr), f"有效 IPv6 CIDR {cidr} 应该返回 True"
            )

    def test_valid_single_ip(self):
        """测试有效的单个 IP"""
        from web_ui import validate_network_cidr

        valid_ips = ["192.168.1.1", "::1", "10.0.0.1"]
        for ip in valid_ips:
            self.assertTrue(validate_network_cidr(ip), f"有效单 IP {ip} 应该返回 True")

    def test_invalid_cidr(self):
        """测试无效的 CIDR"""
        from web_ui import validate_network_cidr

        invalid_cidrs = [
            "192.168.0.0/33",  # 掩码过大
            "invalid/24",  # 无效 IP
            "256.1.1.1/24",  # 无效 IP
        ]
        for cidr in invalid_cidrs:
            self.assertFalse(
                validate_network_cidr(cidr), f"无效 CIDR {cidr} 应该返回 False"
            )

    def test_empty_value(self):
        """测试空值"""
        from web_ui import validate_network_cidr

        self.assertFalse(validate_network_cidr(""))
        self.assertFalse(validate_network_cidr(None))


class TestValidateAllowedNetworks(unittest.TestCase):
    """测试 validate_allowed_networks() 函数"""

    def test_valid_networks(self):
        """测试有效的网络列表"""
        from web_ui import validate_allowed_networks

        networks = ["192.168.0.0/16", "10.0.0.0/8", "127.0.0.0/8"]
        result = validate_allowed_networks(networks)

        self.assertEqual(len(result), 3)
        for network in networks:
            self.assertIn(network, result)

    def test_filter_invalid_networks(self):
        """测试过滤无效网络"""
        from web_ui import validate_allowed_networks

        networks = ["192.168.0.0/16", "invalid", "10.0.0.0/8", "256.1.1.1/24"]
        result = validate_allowed_networks(networks)

        self.assertEqual(len(result), 2)
        self.assertIn("192.168.0.0/16", result)
        self.assertIn("10.0.0.0/8", result)
        self.assertNotIn("invalid", result)

    def test_empty_list_protection(self):
        """测试空列表保护"""
        from web_ui import validate_allowed_networks

        result = validate_allowed_networks([])

        # 应该自动添加本地回环
        self.assertTrue(len(result) > 0)
        self.assertIn("127.0.0.0/8", result)

    def test_all_invalid_protection(self):
        """测试全部无效时的保护"""
        from web_ui import validate_allowed_networks

        result = validate_allowed_networks(["invalid1", "invalid2"])

        # 应该自动添加本地回环
        self.assertTrue(len(result) > 0)
        self.assertIn("127.0.0.0/8", result)

    def test_non_list_input(self):
        """测试非列表输入"""
        from web_ui import DEFAULT_ALLOWED_NETWORKS, validate_allowed_networks

        result = validate_allowed_networks("not a list")

        self.assertEqual(result, DEFAULT_ALLOWED_NETWORKS)

    def test_default_networks(self):
        """测试默认网络"""
        from web_ui import DEFAULT_ALLOWED_NETWORKS, validate_allowed_networks

        result = validate_allowed_networks(None)

        self.assertEqual(result, DEFAULT_ALLOWED_NETWORKS)


class TestValidateBlockedIps(unittest.TestCase):
    """测试 validate_blocked_ips() 函数"""

    def test_valid_ips(self):
        """测试有效的 IP 列表"""
        from web_ui import validate_blocked_ips

        ips = ["192.168.1.1", "10.0.0.1", "::1"]
        result = validate_blocked_ips(ips)

        self.assertEqual(len(result), 3)
        for ip in ips:
            self.assertIn(ip, result)

    def test_filter_invalid_ips(self):
        """测试过滤无效 IP"""
        from web_ui import validate_blocked_ips

        ips = ["192.168.1.1", "invalid", "10.0.0.1", "256.1.1.1"]
        result = validate_blocked_ips(ips)

        self.assertEqual(len(result), 2)
        self.assertIn("192.168.1.1", result)
        self.assertIn("10.0.0.1", result)
        self.assertNotIn("invalid", result)

    def test_empty_list(self):
        """测试空列表"""
        from web_ui import validate_blocked_ips

        result = validate_blocked_ips([])

        self.assertEqual(result, [])

    def test_non_list_input(self):
        """测试非列表输入"""
        from web_ui import validate_blocked_ips

        result = validate_blocked_ips("not a list")

        self.assertEqual(result, [])


class TestValidateNetworkSecurityConfig(unittest.TestCase):
    """测试 validate_network_security_config() 函数"""

    def test_complete_config(self):
        """测试完整配置"""
        from web_ui import validate_network_security_config

        config = {
            "bind_interface": "192.168.1.1",
            "allowed_networks": ["192.168.0.0/16", "10.0.0.0/8"],
            "blocked_ips": ["192.168.1.100"],
            "access_control_enabled": True,
        }
        result = validate_network_security_config(config)

        self.assertEqual(result["bind_interface"], "192.168.1.1")
        self.assertEqual(len(result["allowed_networks"]), 2)
        self.assertEqual(len(result["blocked_ips"]), 1)
        self.assertTrue(result["access_control_enabled"])

    def test_empty_config(self):
        """测试空配置"""
        from web_ui import validate_network_security_config

        result = validate_network_security_config({})

        # 应该使用默认值
        self.assertIn(result["bind_interface"], ["0.0.0.0", "127.0.0.1"])
        self.assertTrue(len(result["allowed_networks"]) > 0)
        self.assertEqual(result["blocked_ips"], [])
        self.assertTrue(result["access_control_enabled"])

    def test_partial_config(self):
        """测试部分配置"""
        from web_ui import validate_network_security_config

        config = {"bind_interface": "127.0.0.1"}
        result = validate_network_security_config(config)

        self.assertEqual(result["bind_interface"], "127.0.0.1")
        # 其他字段使用默认值
        self.assertTrue(len(result["allowed_networks"]) > 0)

    def test_access_control_enabled_conversion(self):
        """测试 access_control_enabled 布尔转换"""
        from web_ui import validate_network_security_config

        # 真值
        config = {"access_control_enabled": "true"}
        result = validate_network_security_config(config)
        self.assertTrue(result["access_control_enabled"])

        # 假值
        config = {"access_control_enabled": False}
        result = validate_network_security_config(config)
        self.assertFalse(result["access_control_enabled"])

        config = {"access_control_enabled": 0}
        result = validate_network_security_config(config)
        self.assertFalse(result["access_control_enabled"])

    def test_non_dict_input(self):
        """测试非字典输入"""
        from web_ui import validate_network_security_config

        result = validate_network_security_config("not a dict")

        # 应该返回默认配置
        self.assertIsInstance(result, dict)
        self.assertIn("bind_interface", result)
        self.assertIn("allowed_networks", result)


class TestLoadNetworkSecurityConfig(unittest.TestCase):
    """测试 _load_network_security_config() 方法"""

    def test_load_with_validation(self):
        """测试加载时验证"""
        from web_ui import WebFeedbackUI

        ui = WebFeedbackUI(
            prompt="test",
            predefined_options=[],
            task_id="test-1",
            auto_resubmit_timeout=60,
        )

        config = ui.network_security_config

        # 验证配置字段存在
        self.assertIn("bind_interface", config)
        self.assertIn("allowed_networks", config)
        self.assertIn("blocked_ips", config)
        self.assertIn("access_control_enabled", config)

        # 验证配置有效性
        self.assertIsInstance(config["allowed_networks"], list)
        self.assertIsInstance(config["blocked_ips"], list)
        self.assertIsInstance(config["access_control_enabled"], bool)


class TestIsIpAllowed(unittest.TestCase):
    """测试 _is_ip_allowed() 方法"""

    def test_access_control_disabled(self):
        """测试禁用访问控制"""
        from web_ui import WebFeedbackUI

        ui = WebFeedbackUI(
            prompt="test",
            predefined_options=[],
            task_id="test-1",
        )

        # 禁用访问控制
        ui.network_security_config["access_control_enabled"] = False

        # 任何 IP 都应该被允许
        self.assertTrue(ui._is_ip_allowed("1.2.3.4"))
        self.assertTrue(ui._is_ip_allowed("192.168.1.1"))

    def test_blocked_ip(self):
        """测试黑名单 IP"""
        from web_ui import WebFeedbackUI

        ui = WebFeedbackUI(
            prompt="test",
            predefined_options=[],
            task_id="test-1",
        )

        # 添加到黑名单
        ui.network_security_config["blocked_ips"] = ["192.168.1.100"]
        ui.network_security_config["access_control_enabled"] = True

        # 黑名单 IP 应该被拒绝
        self.assertFalse(ui._is_ip_allowed("192.168.1.100"))

    def test_allowed_network(self):
        """测试允许的网络"""
        from web_ui import WebFeedbackUI

        ui = WebFeedbackUI(
            prompt="test",
            predefined_options=[],
            task_id="test-1",
        )

        ui.network_security_config["allowed_networks"] = ["127.0.0.0/8"]
        ui.network_security_config["access_control_enabled"] = True

        # 在允许网络中的 IP 应该被允许
        self.assertTrue(ui._is_ip_allowed("127.0.0.1"))

    def test_localhost(self):
        """测试本地回环地址"""
        from web_ui import WebFeedbackUI

        ui = WebFeedbackUI(
            prompt="test",
            predefined_options=[],
            task_id="test-1",
        )

        # 默认配置应该允许本地回环
        self.assertTrue(ui._is_ip_allowed("127.0.0.1"))


class TestRequestClientIpResolution(unittest.TestCase):
    """测试请求来源 IP 解析与 before_request 访问控制"""

    def setUp(self):
        from web_ui import WebFeedbackUI

        self.ui = WebFeedbackUI(
            prompt="test",
            predefined_options=[],
            task_id="test-1",
        )
        self.ui.app.config["TESTING"] = True
        self.client = self.ui.app.test_client()

    def test_spoofed_forwarded_for_from_remote_client_is_ignored(self):
        """远端客户端不能用 X-Forwarded-For 冒充白名单来源"""
        self.ui.network_security_config["allowed_networks"] = ["127.0.0.0/8"]
        self.ui.network_security_config["blocked_ips"] = []
        self.ui.network_security_config["access_control_enabled"] = True

        response = self.client.get(
            "/api/health",
            environ_overrides={
                "REMOTE_ADDR": "8.8.8.8",
                "HTTP_X_FORWARDED_FOR": "127.0.0.1",
            },
        )

        self.assertEqual(response.status_code, 403)

    def test_loopback_proxy_forwarded_for_is_respected(self):
        """仅本机反向代理转发的 X-Forwarded-For 才会被信任"""
        self.ui.network_security_config["allowed_networks"] = ["192.168.0.0/16"]
        self.ui.network_security_config["blocked_ips"] = []
        self.ui.network_security_config["access_control_enabled"] = True

        response = self.client.get(
            "/api/health",
            environ_overrides={
                "REMOTE_ADDR": "127.0.0.1",
                "HTTP_X_FORWARDED_FOR": "192.168.1.20, 127.0.0.1",
            },
        )

        self.assertEqual(response.status_code, 200)


class TestIntegration(unittest.TestCase):
    """集成测试"""

    def test_constants_defined(self):
        """测试常量定义"""
        from web_ui import (
            DEFAULT_ALLOWED_NETWORKS,
            VALID_BIND_INTERFACES,
        )

        self.assertIn("0.0.0.0", VALID_BIND_INTERFACES)
        self.assertIn("127.0.0.1", VALID_BIND_INTERFACES)

        self.assertIn("127.0.0.0/8", DEFAULT_ALLOWED_NETWORKS)
        self.assertIn("::1/128", DEFAULT_ALLOWED_NETWORKS)

    def test_validation_chain(self):
        """测试验证链"""
        from web_ui import (
            validate_network_security_config,
        )

        # 测试完整的验证链
        raw_config = {
            "bind_interface": "invalid_ip",
            "allowed_networks": ["192.168.0.0/16", "invalid"],
            "blocked_ips": ["10.0.0.1", "invalid"],
            "access_control_enabled": True,
        }

        result = validate_network_security_config(raw_config)

        # 验证所有字段都经过了验证
        self.assertEqual(result["bind_interface"], "127.0.0.1")  # 无效 IP 使用默认值
        self.assertEqual(len(result["allowed_networks"]), 1)  # 过滤了无效网络
        self.assertEqual(len(result["blocked_ips"]), 1)  # 过滤了无效 IP


# ============================================================================
# config_modules/network_security.py Mixin 方法测试
# ============================================================================


class TestValidateNetworkSecurityConfigMixin(unittest.TestCase):
    """测试 NetworkSecurityMixin._validate_network_security_config()"""

    def _get_manager(self):
        from config_manager import ConfigManager

        return ConfigManager()

    def test_bind_interface_special_values(self):
        """所有特殊 bind_interface 值应直接通过"""
        mgr = self._get_manager()
        for addr in ("0.0.0.0", "127.0.0.1", "localhost", "::1", "::"):
            result = mgr._validate_network_security_config({"bind_interface": addr})
            self.assertEqual(result["bind_interface"], addr)

    def test_bind_interface_valid_ip(self):
        """合法 IP 地址应通过验证"""
        mgr = self._get_manager()
        result = mgr._validate_network_security_config(
            {"bind_interface": "192.168.1.100"}
        )
        self.assertEqual(result["bind_interface"], "192.168.1.100")

    def test_bind_interface_invalid_fallback(self):
        """无效 bind_interface 应回退到 127.0.0.1"""
        mgr = self._get_manager()
        result = mgr._validate_network_security_config({"bind_interface": "not-an-ip"})
        self.assertEqual(result["bind_interface"], "127.0.0.1")

    def test_bind_interface_non_string(self):
        """非字符串 bind_interface（如整数）应尝试转换"""
        mgr = self._get_manager()
        result = mgr._validate_network_security_config({"bind_interface": 12345})
        self.assertEqual(result["bind_interface"], "127.0.0.1")

    def test_bind_interface_empty_dict(self):
        """空 dict 应使用默认 bind_interface"""
        mgr = self._get_manager()
        result = mgr._validate_network_security_config({})
        self.assertIn(result["bind_interface"], ("0.0.0.0", "127.0.0.1"))

    def test_bind_interface_non_dict_raw(self):
        """非 dict 的 raw 参数应被处理为空 dict，使用默认配置的 bind_interface"""
        mgr = self._get_manager()
        result = mgr._validate_network_security_config("not a dict")
        self.assertIn(result["bind_interface"], ("0.0.0.0", "127.0.0.1"))

    def test_allowed_networks_cidr(self):
        """CIDR 格式的 allowed_networks 应正确解析"""
        mgr = self._get_manager()
        result = mgr._validate_network_security_config(
            {"allowed_networks": ["192.168.0.0/16", "10.0.0.0/8"]}
        )
        self.assertIn("192.168.0.0/16", result["allowed_networks"])
        self.assertIn("10.0.0.0/8", result["allowed_networks"])

    def test_allowed_networks_single_ip(self):
        """单个 IP 地址的 allowed_networks 应正确解析"""
        mgr = self._get_manager()
        result = mgr._validate_network_security_config(
            {"allowed_networks": ["192.168.1.1"]}
        )
        self.assertIn("192.168.1.1", result["allowed_networks"])

    def test_allowed_networks_invalid_entries_filtered(self):
        """无效条目应被过滤，有效条目保留"""
        mgr = self._get_manager()
        result = mgr._validate_network_security_config(
            {"allowed_networks": ["192.168.1.0/24", "not-valid", "10.0.0.1"]}
        )
        self.assertIn("192.168.1.0/24", result["allowed_networks"])
        self.assertIn("10.0.0.1", result["allowed_networks"])
        self.assertNotIn("not-valid", result["allowed_networks"])

    def test_allowed_networks_deduplication(self):
        """重复条目应被去重"""
        mgr = self._get_manager()
        result = mgr._validate_network_security_config(
            {"allowed_networks": ["192.168.1.0/24", "192.168.1.0/24", "10.0.0.1"]}
        )
        cidr_count = result["allowed_networks"].count("192.168.1.0/24")
        self.assertEqual(cidr_count, 1)

    def test_allowed_networks_empty_fallback(self):
        """空列表应回退到默认值"""
        mgr = self._get_manager()
        result = mgr._validate_network_security_config({"allowed_networks": []})
        self.assertIn("127.0.0.0/8", result["allowed_networks"])
        self.assertIn("::1/128", result["allowed_networks"])

    def test_allowed_networks_non_list_fallback(self):
        """非列表类型应使用默认值"""
        mgr = self._get_manager()
        result = mgr._validate_network_security_config(
            {"allowed_networks": "not-a-list"}
        )
        self.assertIn("127.0.0.0/8", result["allowed_networks"])

    def test_allowed_networks_non_string_items_skipped(self):
        """非字符串条目应被跳过"""
        mgr = self._get_manager()
        result = mgr._validate_network_security_config(
            {"allowed_networks": [123, None, "10.0.0.0/8"]}
        )
        self.assertIn("10.0.0.0/8", result["allowed_networks"])

    def test_allowed_networks_empty_strings_skipped(self):
        """空字符串应被跳过"""
        mgr = self._get_manager()
        result = mgr._validate_network_security_config(
            {"allowed_networks": ["", "  ", "10.0.0.0/8"]}
        )
        self.assertIn("10.0.0.0/8", result["allowed_networks"])

    def test_blocked_ips_valid(self):
        """有效 blocked_ips 应正确解析"""
        mgr = self._get_manager()
        result = mgr._validate_network_security_config(
            {"blocked_ips": ["192.168.1.100", "10.0.0.5"]}
        )
        self.assertIn("192.168.1.100", result["blocked_ips"])
        self.assertIn("10.0.0.5", result["blocked_ips"])

    def test_blocked_ips_invalid_filtered(self):
        """无效 blocked_ips 应被过滤"""
        mgr = self._get_manager()
        result = mgr._validate_network_security_config(
            {"blocked_ips": ["192.168.1.100", "not-valid-ip", "10.0.0.5"]}
        )
        self.assertIn("192.168.1.100", result["blocked_ips"])
        self.assertNotIn("not-valid-ip", result["blocked_ips"])

    def test_blocked_ips_non_list_fallback(self):
        """非列表 blocked_ips 应使用默认值（空列表）"""
        mgr = self._get_manager()
        result = mgr._validate_network_security_config({"blocked_ips": "not-a-list"})
        self.assertEqual(result["blocked_ips"], [])

    def test_blocked_ips_deduplication(self):
        """重复 blocked_ips 应去重"""
        mgr = self._get_manager()
        result = mgr._validate_network_security_config(
            {"blocked_ips": ["10.0.0.1", "10.0.0.1", "10.0.0.2"]}
        )
        count = result["blocked_ips"].count("10.0.0.1")
        self.assertEqual(count, 1)

    def test_access_control_enabled_default_true(self):
        """未提供 access_control_enabled 时应默认为 True"""
        mgr = self._get_manager()
        result = mgr._validate_network_security_config({})
        self.assertTrue(result["access_control_enabled"])

    def test_access_control_enabled_legacy_key(self):
        """旧字段名 enable_access_control 应被兼容"""
        mgr = self._get_manager()
        result = mgr._validate_network_security_config({"enable_access_control": False})
        self.assertFalse(result["access_control_enabled"])

    def test_ipv6_allowed_networks(self):
        """IPv6 地址和 CIDR 应正确处理"""
        mgr = self._get_manager()
        result = mgr._validate_network_security_config(
            {"allowed_networks": ["::1", "fe80::/10", "2001:db8::/32"]}
        )
        self.assertTrue(len(result["allowed_networks"]) >= 3)

    def test_ipv6_blocked_ips(self):
        """IPv6 blocked_ips 应正确处理"""
        mgr = self._get_manager()
        result = mgr._validate_network_security_config(
            {"blocked_ips": ["::1", "fe80::1"]}
        )
        self.assertTrue(len(result["blocked_ips"]) >= 2)

    def test_full_config_all_fields(self):
        """完整配置（所有字段）应全部正确验证"""
        mgr = self._get_manager()
        result = mgr._validate_network_security_config(
            {
                "bind_interface": "0.0.0.0",
                "allowed_networks": ["192.168.0.0/16", "10.0.0.0/8"],
                "blocked_ips": ["192.168.1.100"],
                "access_control_enabled": True,
            }
        )
        self.assertEqual(result["bind_interface"], "0.0.0.0")
        self.assertEqual(len(result["allowed_networks"]), 2)
        self.assertEqual(len(result["blocked_ips"]), 1)
        self.assertTrue(result["access_control_enabled"])

    def test_output_structure(self):
        """输出字典应包含且仅包含 4 个预期字段"""
        mgr = self._get_manager()
        result = mgr._validate_network_security_config({})
        self.assertEqual(
            set(result.keys()),
            {
                "bind_interface",
                "allowed_networks",
                "blocked_ips",
                "access_control_enabled",
            },
        )


class TestUpdateNetworkSecurityMixin(unittest.TestCase):
    """测试 set/update_network_security_config Mixin 方法"""

    def _get_manager(self):
        from config_manager import ConfigManager

        return ConfigManager()

    def test_set_network_security_persists_to_file(self):
        """save=True 时应写入文件并可重新读取"""
        mgr = self._get_manager()
        config = {
            "bind_interface": "0.0.0.0",
            "allowed_networks": ["192.168.0.0/16"],
            "blocked_ips": [],
            "access_control_enabled": True,
        }
        mgr.set_network_security_config(config, save=True, trigger_callbacks=False)
        result = mgr.get_network_security_config()
        self.assertEqual(result["bind_interface"], "0.0.0.0")
        self.assertIn("192.168.0.0/16", result["allowed_networks"])

    def test_update_network_security_incremental(self):
        """增量更新只修改指定字段"""
        mgr = self._get_manager()
        mgr.set_network_security_config(
            {
                "bind_interface": "127.0.0.1",
                "allowed_networks": ["192.168.0.0/16"],
                "blocked_ips": ["10.0.0.1"],
                "access_control_enabled": True,
            },
            save=True,
            trigger_callbacks=False,
        )
        mgr.update_network_security_config(
            {"blocked_ips": ["10.0.0.2"]},
            save=True,
            trigger_callbacks=False,
        )
        result = mgr.get_network_security_config()
        self.assertIn("10.0.0.2", result["blocked_ips"])

    def test_update_network_security_unknown_fields_ignored(self):
        """未知字段应被忽略"""
        mgr = self._get_manager()
        mgr.update_network_security_config(
            {"unknown_field": "value", "blocked_ips": ["10.0.0.1"]},
            save=True,
            trigger_callbacks=False,
        )
        result = mgr.get_network_security_config()
        self.assertNotIn("unknown_field", result)

    def test_update_network_security_invalid_type(self):
        """非 dict 更新应抛出 ValueError"""
        mgr = self._get_manager()
        with self.assertRaises(ValueError):
            mgr.update_network_security_config("not a dict", save=False)

    def test_update_legacy_enable_access_control_key(self):
        """旧字段名 enable_access_control 应映射到 access_control_enabled"""
        mgr = self._get_manager()
        mgr.set_network_security_config(
            {
                "bind_interface": "127.0.0.1",
                "allowed_networks": ["127.0.0.0/8"],
                "blocked_ips": [],
                "access_control_enabled": True,
            },
            save=True,
            trigger_callbacks=False,
        )
        mgr.update_network_security_config(
            {"enable_access_control": False},
            save=True,
            trigger_callbacks=False,
        )
        result = mgr.get_network_security_config()
        self.assertFalse(result["access_control_enabled"])


# ---------------------------------------------------------------------------
# 边界路径补充（原 test_network_security_extended.py）
# ---------------------------------------------------------------------------


class TestValidateBlockedIpsEdge(unittest.TestCase):
    """_validate_network_security_config 中 blocked_ips 边界分支"""

    def _mgr(self) -> ConfigManager:
        return ConfigManager()

    def test_blocked_ips_non_string_ignored(self):
        mgr = self._mgr()
        result = mgr._validate_network_security_config(
            {"blocked_ips": [123, "127.0.0.1"]}
        )
        self.assertIn("127.0.0.1", result["blocked_ips"])
        self.assertNotIn(123, result["blocked_ips"])

    def test_blocked_ips_empty_string_ignored(self):
        mgr = self._mgr()
        result = mgr._validate_network_security_config(
            {"blocked_ips": ["", " ", "127.0.0.1"]}
        )
        self.assertIn("127.0.0.1", result["blocked_ips"])
        self.assertEqual(len(result["blocked_ips"]), 1)

    def test_blocked_ips_invalid_address(self):
        mgr = self._mgr()
        result = mgr._validate_network_security_config(
            {"blocked_ips": ["not_an_ip", "192.168.1.1"]}
        )
        self.assertIn("192.168.1.1", result["blocked_ips"])
        self.assertNotIn("not_an_ip", result["blocked_ips"])

    def test_blocked_ips_not_list(self):
        mgr = self._mgr()
        result = mgr._validate_network_security_config({"blocked_ips": "not_a_list"})
        self.assertEqual(result["blocked_ips"], [])


class TestValidateAllowedNetworksEdge(unittest.TestCase):
    """_validate_network_security_config 中 allowed_networks 边界"""

    def _mgr(self) -> ConfigManager:
        return ConfigManager()

    def test_non_string_item_ignored(self):
        mgr = self._mgr()
        result = mgr._validate_network_security_config(
            {"allowed_networks": [42, "10.0.0.0/8"]}
        )
        self.assertIn("10.0.0.0/8", result["allowed_networks"])

    def test_empty_string_ignored(self):
        mgr = self._mgr()
        result = mgr._validate_network_security_config(
            {"allowed_networks": ["", "10.0.0.0/8"]}
        )
        self.assertIn("10.0.0.0/8", result["allowed_networks"])

    def test_invalid_cidr_ignored(self):
        mgr = self._mgr()
        result = mgr._validate_network_security_config(
            {"allowed_networks": ["not/cidr", "10.0.0.0/8"]}
        )
        self.assertIn("10.0.0.0/8", result["allowed_networks"])

    def test_not_list_uses_default(self):
        mgr = self._mgr()
        result = mgr._validate_network_security_config({"allowed_networks": "bad"})
        self.assertIn("127.0.0.0/8", result["allowed_networks"])

    def test_empty_list_gets_fallback(self):
        mgr = self._mgr()
        result = mgr._validate_network_security_config({"allowed_networks": []})
        self.assertIn("127.0.0.0/8", result["allowed_networks"])
        self.assertIn("::1/128", result["allowed_networks"])

    def test_ip_without_cidr(self):
        mgr = self._mgr()
        result = mgr._validate_network_security_config(
            {"allowed_networks": ["192.168.1.100"]}
        )
        self.assertIn("192.168.1.100", result["allowed_networks"])

    def test_dedup(self):
        mgr = self._mgr()
        result = mgr._validate_network_security_config(
            {"allowed_networks": ["10.0.0.0/8", "10.0.0.0/8"]}
        )
        self.assertEqual(result["allowed_networks"].count("10.0.0.0/8"), 1)


class TestValidateBindInterfaceEdge(unittest.TestCase):
    """_validate_network_security_config 中 bind_interface 边界"""

    def _mgr(self) -> ConfigManager:
        return ConfigManager()

    def test_non_string_bind(self):
        mgr = self._mgr()
        result = mgr._validate_network_security_config({"bind_interface": 12345})
        self.assertEqual(result["bind_interface"], "127.0.0.1")

    def test_invalid_bind(self):
        mgr = self._mgr()
        result = mgr._validate_network_security_config(
            {"bind_interface": "bad_address"}
        )
        self.assertEqual(result["bind_interface"], "127.0.0.1")

    def test_valid_ip_bind(self):
        mgr = self._mgr()
        result = mgr._validate_network_security_config(
            {"bind_interface": "192.168.1.1"}
        )
        self.assertEqual(result["bind_interface"], "192.168.1.1")


# ──────────────────────────────────────────────────────────
# _save_network_security_config_immediate 各路径
# ──────────────────────────────────────────────────────────


class TestSaveNetworkSecurityImmediate(unittest.TestCase):
    """测试各种文件格式/内容状态下的保存逻辑"""

    def test_json_format_save(self):
        """非 JSONC 后缀 → JSON 保存路径"""
        with tempfile.TemporaryDirectory() as td:
            cfg_path = Path(td) / "config.json"
            cfg_path.write_text('{"notification": {}}')
            mgr = ConfigManager(str(cfg_path))
            ns = {
                "bind_interface": "0.0.0.0",
                "allowed_networks": ["10.0.0.0/8"],
                "blocked_ips": [],
                "access_control_enabled": True,
            }
            mgr._save_network_security_config_immediate(ns)
            content = json.loads(cfg_path.read_text())
            self.assertIn("network_security", content)

    def test_json_format_empty_content(self):
        with tempfile.TemporaryDirectory() as td:
            cfg_path = Path(td) / "config.json"
            cfg_path.write_text("")
            mgr = ConfigManager(str(cfg_path))
            ns = {
                "bind_interface": "0.0.0.0",
                "allowed_networks": [],
                "blocked_ips": [],
                "access_control_enabled": True,
            }
            mgr._save_network_security_config_immediate(ns)
            content = json.loads(cfg_path.read_text())
            self.assertIn("network_security", content)

    def test_json_format_invalid_json(self):
        with tempfile.TemporaryDirectory() as td:
            cfg_path = Path(td) / "config.json"
            cfg_path.write_text("{bad json")
            mgr = ConfigManager(str(cfg_path))
            ns = {
                "bind_interface": "0.0.0.0",
                "allowed_networks": [],
                "blocked_ips": [],
                "access_control_enabled": True,
            }
            mgr._save_network_security_config_immediate(ns)
            content = json.loads(cfg_path.read_text())
            self.assertIn("network_security", content)

    def test_json_no_content_fallback(self):
        """JSON 文件但无 base_content 和 original_content → JSON dump"""
        with tempfile.TemporaryDirectory() as td:
            cfg_path = Path(td) / "config.json"
            cfg_path.write_text("")
            mgr = ConfigManager(str(cfg_path))
            mgr._original_content = None
            ns = {
                "bind_interface": "0.0.0.0",
                "allowed_networks": [],
                "blocked_ips": [],
                "access_control_enabled": True,
            }
            mgr._save_network_security_config_immediate(ns)
            content = json.loads(cfg_path.read_text())
            self.assertIn("network_security", content)

    def test_json_no_ns_range(self):
        """JSON 有内容但找不到 network_security 段 → parse + dump"""
        with tempfile.TemporaryDirectory() as td:
            cfg_path = Path(td) / "config.json"
            cfg_path.write_text('{\n  "notification": {}\n}')
            mgr = ConfigManager(str(cfg_path))
            ns = {
                "bind_interface": "0.0.0.0",
                "allowed_networks": ["10.0.0.0/8"],
                "blocked_ips": [],
                "access_control_enabled": True,
            }
            mgr._save_network_security_config_immediate(ns)
            content = cfg_path.read_text()
            self.assertIn("network_security", content)

    def test_config_file_not_exist_creates_default(self):
        with tempfile.TemporaryDirectory() as td:
            cfg_path = Path(td) / "subdir" / "config.toml"
            mgr = ConfigManager.__new__(ConfigManager)
            mgr.config_file = cfg_path
            mgr._config = {}
            mgr._original_content = None
            mgr._lock = __import__("threading").RLock()
            mgr._network_security_cache = None
            mgr._network_security_cache_time = 0
            mgr._network_security_cache_ttl = 30.0
            mgr._section_cache = {}
            mgr._section_cache_time = {}
            mgr._section_cache_ttl = 10.0
            mgr._cache_stats = {"hits": 0, "misses": 0, "invalidations": 0}
            mgr._last_file_mtime = 0
            mgr._file_watcher_running = False

            cfg_path.parent.mkdir(parents=True, exist_ok=True)
            ns = {
                "bind_interface": "0.0.0.0",
                "allowed_networks": [],
                "blocked_ips": [],
                "access_control_enabled": True,
            }

            with patch.object(mgr, "_create_default_config_file"):
                with patch.object(mgr, "_update_file_mtime"):
                    mgr._save_network_security_config_immediate(ns)

    def test_write_exception_raised(self):
        with tempfile.TemporaryDirectory() as td:
            cfg_path = Path(td) / "config.json"
            cfg_path.write_text('{"a":1}')
            mgr = ConfigManager(str(cfg_path))
            ns = {
                "bind_interface": "0.0.0.0",
                "allowed_networks": [],
                "blocked_ips": [],
                "access_control_enabled": True,
            }

            import os

            os.chmod(str(cfg_path), 0o444)
            try:
                with self.assertRaises(RuntimeError):
                    mgr._save_network_security_config_immediate(ns)
            finally:
                os.chmod(str(cfg_path), 0o644)


# ──────────────────────────────────────────────────────────
# get_network_security_config 各分支
# ──────────────────────────────────────────────────────────


class TestGetNetworkSecurityConfig(unittest.TestCase):
    def test_file_not_exist_returns_default(self):
        with tempfile.TemporaryDirectory() as td:
            cfg_path = Path(td) / "nonexistent.toml"
            mgr = ConfigManager(str(cfg_path))
            mgr.invalidate_all_caches()
            result = mgr.get_network_security_config()
            self.assertIn("bind_interface", result)

    def test_json_file_format(self):
        with tempfile.TemporaryDirectory() as td:
            cfg_path = Path(td) / "config.json"
            cfg_data = {
                "notification": {},
                "network_security": {
                    "bind_interface": "192.168.1.1",
                    "allowed_networks": ["10.0.0.0/8"],
                    "blocked_ips": [],
                    "access_control_enabled": True,
                },
            }
            cfg_path.write_text(json.dumps(cfg_data))
            mgr = ConfigManager(str(cfg_path))
            mgr.invalidate_all_caches()
            result = mgr.get_network_security_config()
            self.assertEqual(result["bind_interface"], "192.168.1.1")

    def test_no_ns_in_file_uses_default(self):
        with tempfile.TemporaryDirectory() as td:
            cfg_path = Path(td) / "config.json"
            cfg_path.write_text('{\n  "notification": {}\n}')
            mgr = ConfigManager(str(cfg_path))
            mgr.invalidate_all_caches()
            result = mgr.get_network_security_config()
            self.assertIn("bind_interface", result)

    def test_read_exception_returns_cached(self):
        mgr = ConfigManager()
        mgr._network_security_cache = {
            "bind_interface": "1.2.3.4",
            "allowed_networks": [],
            "blocked_ips": [],
            "access_control_enabled": True,
        }
        mgr._network_security_cache_time = 0

        with patch("builtins.open", side_effect=IOError("disk error")):
            result = mgr.get_network_security_config()
            self.assertEqual(result["bind_interface"], "1.2.3.4")

    def test_read_exception_no_cache_returns_default(self):
        mgr = ConfigManager()
        mgr._network_security_cache = None
        mgr._network_security_cache_time = 0

        with patch("builtins.open", side_effect=IOError("disk error")):
            result = mgr.get_network_security_config()
            self.assertIn("bind_interface", result)


# ──────────────────────────────────────────────────────────
# 回调异常路径
# ──────────────────────────────────────────────────────────


class TestCallbackExceptions(unittest.TestCase):
    def test_set_callback_exception(self):
        mgr = ConfigManager()
        with patch.object(
            mgr, "_trigger_config_change_callbacks", side_effect=RuntimeError("fail")
        ):
            mgr.set_network_security_config({"bind_interface": "127.0.0.1"}, save=True)

    def test_update_callback_exception(self):
        mgr = ConfigManager()
        with patch.object(
            mgr, "_trigger_config_change_callbacks", side_effect=RuntimeError("fail")
        ):
            mgr.update_network_security_config(
                {"bind_interface": "127.0.0.1"}, save=True
            )

    def test_update_unknown_field_warned(self):
        mgr = ConfigManager()
        mgr.update_network_security_config({"unknown_field": "val"}, save=True)


# ──────────────────────────────────────────────────────────
# blocked_ips AddressValueError 分支（防御性代码）
# ──────────────────────────────────────────────────────────


class TestBlockedIpsAddressValueError(unittest.TestCase):
    """line 98-99: ip_address 实际抛 ValueError，但代码有 AddressValueError 守卫"""

    def test_address_value_error_caught(self):
        from ipaddress import AddressValueError

        mgr = ConfigManager()
        with patch(
            "config_modules.network_security.ip_address",
            side_effect=AddressValueError("mock"),
        ):
            result = mgr._validate_network_security_config({"blocked_ips": ["1.2.3.4"]})
        self.assertEqual(result["blocked_ips"], [])


# ──────────────────────────────────────────────────────────
# _save_network_security_config_immediate 异常路径
# ──────────────────────────────────────────────────────────


class TestSaveImmediateExceptionPaths(unittest.TestCase):
    """覆盖 save 方法中各种异常/边界分支"""

    def _make_mgr(self, cfg_path: Path) -> ConfigManager:
        mgr = ConfigManager(str(cfg_path))
        return mgr

    _NS = {
        "bind_interface": "0.0.0.0",
        "allowed_networks": ["10.0.0.0/8"],
        "blocked_ips": [],
        "access_control_enabled": True,
    }

    def test_config_file_exists_exception_swallowed(self):
        """lines 131-132: config_file.exists() 首次检查抛异常时被吞掉"""
        with tempfile.TemporaryDirectory() as td:
            cfg_path = Path(td) / "config.json"
            cfg_path.write_text('{"a":1}')
            mgr = self._make_mgr(cfg_path)

            original_exists = cfg_path.exists

            call_count = 0

            def exists_side_effect() -> bool:
                nonlocal call_count
                call_count += 1
                if call_count == 1:
                    raise OSError("permission denied")
                return original_exists()

            with patch.object(
                type(mgr.config_file),
                "exists",
                new_callable=lambda: property(lambda self: exists_side_effect),
            ):
                mgr._save_network_security_config_immediate(self._NS)

    def test_read_text_exception_raised(self):
        """lines 138-139: read_text 失败时抛 RuntimeError"""
        with tempfile.TemporaryDirectory() as td:
            cfg_path = Path(td) / "config.json"
            cfg_path.write_text('{"a":1}')
            mgr = self._make_mgr(cfg_path)
            with patch.object(
                type(cfg_path), "read_text", side_effect=PermissionError("denied")
            ):
                with self.assertRaises(RuntimeError) as ctx:
                    mgr._save_network_security_config_immediate(self._NS)
                self.assertIn("读取配置文件失败", str(ctx.exception))

    def test_json_non_dict_content_reset(self):
        """line 145: JSON 解析结果不是 dict（如数组）时重置为空 dict"""
        with tempfile.TemporaryDirectory() as td:
            cfg_path = Path(td) / "config.json"
            cfg_path.write_text("[1, 2, 3]")
            mgr = self._make_mgr(cfg_path)
            mgr._save_network_security_config_immediate(self._NS)
            content = json.loads(cfg_path.read_text())
            self.assertIn("network_security", content)
            self.assertIsInstance(content, dict)

    def test_json_empty_content_with_original(self):
        """JSON 文件内容为空但 _original_content 非空时使用 original"""
        with tempfile.TemporaryDirectory() as td:
            cfg_path = Path(td) / "config.json"
            cfg_path.write_text("")
            mgr = self._make_mgr(cfg_path)
            mgr._original_content = '{\n  "notification": {}\n}'
            mgr._save_network_security_config_immediate(self._NS)
            content = cfg_path.read_text()
            self.assertIn("network_security", content)

    def test_json_no_base_content_write_exception(self):
        """JSON 无 base_content 时写入失败"""
        with tempfile.TemporaryDirectory() as td:
            cfg_path = Path(td) / "config.json"
            cfg_path.write_text("")
            mgr = self._make_mgr(cfg_path)
            mgr._original_content = None
            with patch.object(
                type(cfg_path), "write_text", side_effect=PermissionError("denied")
            ):
                with self.assertRaises(RuntimeError) as ctx:
                    mgr._save_network_security_config_immediate(self._NS)
                self.assertIn("写入配置文件失败", str(ctx.exception))

    def test_json_fallback_write_exception(self):
        """JSON 降级路径写入失败"""
        with tempfile.TemporaryDirectory() as td:
            cfg_path = Path(td) / "config.json"
            cfg_path.write_text('{\n  "notification": {}\n}')
            mgr = self._make_mgr(cfg_path)
            with patch.object(
                type(cfg_path),
                "write_text",
                side_effect=PermissionError("denied"),
            ):
                with self.assertRaises(RuntimeError) as ctx:
                    mgr._save_network_security_config_immediate(self._NS)
                self.assertIn("写入配置文件失败", str(ctx.exception))


# ──────────────────────────────────────────────────────────
# set/update save=False 分支
# ──────────────────────────────────────────────────────────


class TestSaveSkipBranch(unittest.TestCase):
    """branch 215->217 / 246->249: save=False 时跳过写入"""

    def test_set_network_security_save_false(self):
        mgr = ConfigManager()
        with patch.object(mgr, "_save_network_security_config_immediate") as mock_save:
            mgr.set_network_security_config({"bind_interface": "127.0.0.1"}, save=False)
            mock_save.assert_not_called()

    def test_update_network_security_save_false(self):
        mgr = ConfigManager()
        with patch.object(mgr, "_save_network_security_config_immediate") as mock_save:
            mgr.update_network_security_config(
                {"bind_interface": "127.0.0.1"}, save=False
            )
            mock_save.assert_not_called()


# ──────────────────────────────────────────────────────────
# get_network_security_config 文件不存在分支
# ──────────────────────────────────────────────────────────


class TestGetConfigFileNotExistBranch(unittest.TestCase):
    """lines 274-282: 配置文件在 get 时确实不存在"""

    def test_file_deleted_after_init(self):
        """init 后删除文件，get 走 file-not-exist 分支"""
        with tempfile.TemporaryDirectory() as td:
            cfg_path = Path(td) / "config.json"
            cfg_path.write_text('{"network_security":{}}')
            mgr = ConfigManager(str(cfg_path))
            mgr._network_security_cache = None
            mgr._network_security_cache_time = 0
            cfg_path.unlink()
            result = mgr.get_network_security_config()
            self.assertIn("bind_interface", result)
            self.assertIn("allowed_networks", result)
            self.assertIsNotNone(mgr._network_security_cache)


if __name__ == "__main__":
    unittest.main()
