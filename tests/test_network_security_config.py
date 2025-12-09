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

import unittest


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
            "enable_access_control": True,
        }
        result = validate_network_security_config(config)

        self.assertEqual(result["bind_interface"], "192.168.1.1")
        self.assertEqual(len(result["allowed_networks"]), 2)
        self.assertEqual(len(result["blocked_ips"]), 1)
        self.assertTrue(result["enable_access_control"])

    def test_empty_config(self):
        """测试空配置"""
        from web_ui import validate_network_security_config

        result = validate_network_security_config({})

        # 应该使用默认值
        self.assertIn(result["bind_interface"], ["0.0.0.0", "127.0.0.1"])
        self.assertTrue(len(result["allowed_networks"]) > 0)
        self.assertEqual(result["blocked_ips"], [])
        self.assertTrue(result["enable_access_control"])

    def test_partial_config(self):
        """测试部分配置"""
        from web_ui import validate_network_security_config

        config = {"bind_interface": "127.0.0.1"}
        result = validate_network_security_config(config)

        self.assertEqual(result["bind_interface"], "127.0.0.1")
        # 其他字段使用默认值
        self.assertTrue(len(result["allowed_networks"]) > 0)

    def test_enable_access_control_conversion(self):
        """测试 enable_access_control 布尔转换"""
        from web_ui import validate_network_security_config

        # 真值
        config = {"enable_access_control": "true"}
        result = validate_network_security_config(config)
        self.assertTrue(result["enable_access_control"])

        # 假值
        config = {"enable_access_control": False}
        result = validate_network_security_config(config)
        self.assertFalse(result["enable_access_control"])

        config = {"enable_access_control": 0}
        result = validate_network_security_config(config)
        self.assertFalse(result["enable_access_control"])

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
        self.assertIn("enable_access_control", config)

        # 验证配置有效性
        self.assertIsInstance(config["allowed_networks"], list)
        self.assertIsInstance(config["blocked_ips"], list)
        self.assertIsInstance(config["enable_access_control"], bool)


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
        ui.network_security_config["enable_access_control"] = False

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
        ui.network_security_config["enable_access_control"] = True

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
        ui.network_security_config["enable_access_control"] = True

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
            "enable_access_control": True,
        }

        result = validate_network_security_config(raw_config)

        # 验证所有字段都经过了验证
        self.assertEqual(result["bind_interface"], "127.0.0.1")  # 无效 IP 使用默认值
        self.assertEqual(len(result["allowed_networks"]), 1)  # 过滤了无效网络
        self.assertEqual(len(result["blocked_ips"]), 1)  # 过滤了无效 IP


if __name__ == "__main__":
    unittest.main()
