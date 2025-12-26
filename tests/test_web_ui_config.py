"""
Web UI 配置模块单元测试

测试覆盖：
    - WebUIConfig 数据类的边界验证
    - 端口号验证（范围、特权端口）
    - 超时时间验证
    - 重试次数验证
    - 重试延迟验证
"""

import unittest
from unittest.mock import MagicMock, patch


class TestWebUIConfigConstants(unittest.TestCase):
    """测试 WebUIConfig 常量"""

    def test_constants_defined(self):
        """测试常量定义"""
        from server import WebUIConfig

        # 端口常量
        self.assertEqual(WebUIConfig.PORT_MIN, 1)
        self.assertEqual(WebUIConfig.PORT_MAX, 65535)
        self.assertEqual(WebUIConfig.PORT_PRIVILEGED, 1024)

        # 超时常量
        self.assertEqual(WebUIConfig.TIMEOUT_MIN, 1)
        self.assertEqual(WebUIConfig.TIMEOUT_MAX, 300)

        # 重试常量
        self.assertEqual(WebUIConfig.MAX_RETRIES_MIN, 0)
        self.assertEqual(WebUIConfig.MAX_RETRIES_MAX, 10)
        self.assertEqual(WebUIConfig.RETRY_DELAY_MIN, 0.1)
        self.assertEqual(WebUIConfig.RETRY_DELAY_MAX, 60.0)


class TestWebUIConfigPort(unittest.TestCase):
    """测试端口号验证"""

    def test_valid_port(self):
        """测试有效端口号"""
        from server import WebUIConfig

        # 正常端口
        config = WebUIConfig(host="127.0.0.1", port=8080)
        self.assertEqual(config.port, 8080)

        # 边界值
        config = WebUIConfig(host="127.0.0.1", port=1)
        self.assertEqual(config.port, 1)

        config = WebUIConfig(host="127.0.0.1", port=65535)
        self.assertEqual(config.port, 65535)

    def test_invalid_port_zero(self):
        """测试无效端口号 0"""
        from server import WebUIConfig

        with self.assertRaises(ValueError) as context:
            WebUIConfig(host="127.0.0.1", port=0)

        self.assertIn("端口号必须在", str(context.exception))

    def test_invalid_port_negative(self):
        """测试负数端口号"""
        from server import WebUIConfig

        with self.assertRaises(ValueError):
            WebUIConfig(host="127.0.0.1", port=-1)

    def test_invalid_port_too_large(self):
        """测试超大端口号"""
        from server import WebUIConfig

        with self.assertRaises(ValueError):
            WebUIConfig(host="127.0.0.1", port=65536)

    def test_privileged_port_warning(self):
        """测试特权端口警告"""
        from server import WebUIConfig

        # 特权端口应该生成警告但不抛异常
        config = WebUIConfig(host="127.0.0.1", port=80)
        self.assertEqual(config.port, 80)

        config = WebUIConfig(host="127.0.0.1", port=443)
        self.assertEqual(config.port, 443)


class TestWebUIConfigTimeout(unittest.TestCase):
    """测试超时时间验证"""

    def test_valid_timeout(self):
        """测试有效超时时间"""
        from server import WebUIConfig

        config = WebUIConfig(host="127.0.0.1", port=8080, timeout=30)
        self.assertEqual(config.timeout, 30)

        # 边界值
        config = WebUIConfig(host="127.0.0.1", port=8080, timeout=1)
        self.assertEqual(config.timeout, 1)

        config = WebUIConfig(host="127.0.0.1", port=8080, timeout=300)
        self.assertEqual(config.timeout, 300)

    def test_timeout_below_min(self):
        """测试超时时间小于最小值"""
        from server import WebUIConfig

        config = WebUIConfig(host="127.0.0.1", port=8080, timeout=0)
        self.assertEqual(config.timeout, WebUIConfig.TIMEOUT_MIN)

        config = WebUIConfig(host="127.0.0.1", port=8080, timeout=-10)
        self.assertEqual(config.timeout, WebUIConfig.TIMEOUT_MIN)

    def test_timeout_above_max(self):
        """测试超时时间大于最大值"""
        from server import WebUIConfig

        config = WebUIConfig(host="127.0.0.1", port=8080, timeout=500)
        self.assertEqual(config.timeout, WebUIConfig.TIMEOUT_MAX)

        config = WebUIConfig(host="127.0.0.1", port=8080, timeout=3600)
        self.assertEqual(config.timeout, WebUIConfig.TIMEOUT_MAX)


class TestWebUIConfigMaxRetries(unittest.TestCase):
    """测试重试次数验证"""

    def test_valid_max_retries(self):
        """测试有效重试次数"""
        from server import WebUIConfig

        config = WebUIConfig(host="127.0.0.1", port=8080, max_retries=3)
        self.assertEqual(config.max_retries, 3)

        # 边界值
        config = WebUIConfig(host="127.0.0.1", port=8080, max_retries=0)
        self.assertEqual(config.max_retries, 0)

        config = WebUIConfig(host="127.0.0.1", port=8080, max_retries=10)
        self.assertEqual(config.max_retries, 10)

    def test_max_retries_below_min(self):
        """测试重试次数小于最小值"""
        from server import WebUIConfig

        config = WebUIConfig(host="127.0.0.1", port=8080, max_retries=-1)
        self.assertEqual(config.max_retries, WebUIConfig.MAX_RETRIES_MIN)

        config = WebUIConfig(host="127.0.0.1", port=8080, max_retries=-10)
        self.assertEqual(config.max_retries, WebUIConfig.MAX_RETRIES_MIN)

    def test_max_retries_above_max(self):
        """测试重试次数大于最大值"""
        from server import WebUIConfig

        config = WebUIConfig(host="127.0.0.1", port=8080, max_retries=20)
        self.assertEqual(config.max_retries, WebUIConfig.MAX_RETRIES_MAX)

        config = WebUIConfig(host="127.0.0.1", port=8080, max_retries=100)
        self.assertEqual(config.max_retries, WebUIConfig.MAX_RETRIES_MAX)


class TestWebUIConfigRetryDelay(unittest.TestCase):
    """测试重试延迟验证"""

    def test_valid_retry_delay(self):
        """测试有效重试延迟"""
        from server import WebUIConfig

        config = WebUIConfig(host="127.0.0.1", port=8080, retry_delay=1.0)
        self.assertEqual(config.retry_delay, 1.0)

        # 边界值
        config = WebUIConfig(host="127.0.0.1", port=8080, retry_delay=0.1)
        self.assertEqual(config.retry_delay, 0.1)

        config = WebUIConfig(host="127.0.0.1", port=8080, retry_delay=60.0)
        self.assertEqual(config.retry_delay, 60.0)

    def test_retry_delay_below_min(self):
        """测试重试延迟小于最小值"""
        from server import WebUIConfig

        config = WebUIConfig(host="127.0.0.1", port=8080, retry_delay=0.0)
        self.assertEqual(config.retry_delay, WebUIConfig.RETRY_DELAY_MIN)

        config = WebUIConfig(host="127.0.0.1", port=8080, retry_delay=-1.0)
        self.assertEqual(config.retry_delay, WebUIConfig.RETRY_DELAY_MIN)

    def test_retry_delay_above_max(self):
        """测试重试延迟大于最大值"""
        from server import WebUIConfig

        config = WebUIConfig(host="127.0.0.1", port=8080, retry_delay=100.0)
        self.assertEqual(config.retry_delay, WebUIConfig.RETRY_DELAY_MAX)

        config = WebUIConfig(host="127.0.0.1", port=8080, retry_delay=1000.0)
        self.assertEqual(config.retry_delay, WebUIConfig.RETRY_DELAY_MAX)


class TestWebUIConfigCombined(unittest.TestCase):
    """测试组合场景"""

    def test_all_defaults(self):
        """测试所有默认值"""
        from server import WebUIConfig

        config = WebUIConfig(host="127.0.0.1", port=8080)

        self.assertEqual(config.host, "127.0.0.1")
        self.assertEqual(config.port, 8080)
        self.assertEqual(config.timeout, 30)
        self.assertEqual(config.max_retries, 3)
        self.assertEqual(config.retry_delay, 1.0)

    def test_all_custom_valid(self):
        """测试所有自定义有效值"""
        from server import WebUIConfig

        config = WebUIConfig(
            host="0.0.0.0",
            port=9000,
            timeout=60,
            max_retries=5,
            retry_delay=2.0,
        )

        self.assertEqual(config.host, "0.0.0.0")
        self.assertEqual(config.port, 9000)
        self.assertEqual(config.timeout, 60)
        self.assertEqual(config.max_retries, 5)
        self.assertEqual(config.retry_delay, 2.0)

    def test_multiple_boundary_adjustments(self):
        """测试多个边界调整"""
        from server import WebUIConfig

        config = WebUIConfig(
            host="127.0.0.1",
            port=8080,
            timeout=0,  # 调整到 1
            max_retries=-5,  # 调整到 0
            retry_delay=0.0,  # 调整到 0.1
        )

        self.assertEqual(config.timeout, WebUIConfig.TIMEOUT_MIN)
        self.assertEqual(config.max_retries, WebUIConfig.MAX_RETRIES_MIN)
        self.assertEqual(config.retry_delay, WebUIConfig.RETRY_DELAY_MIN)


class TestGetWebUIConfig(unittest.TestCase):
    """测试 get_web_ui_config() 函数"""

    @patch("server.get_config")
    def test_load_config_success(self, mock_get_config):
        """测试成功加载配置"""
        # 清除缓存
        import server
        from server import WebUIConfig, get_web_ui_config

        server._config_cache["config"] = None
        server._config_cache["timestamp"] = 0

        mock_config_mgr = MagicMock()
        mock_config_mgr.get_section.side_effect = lambda section: {
            "web_ui": {
                "port": 8080,
                "timeout": 30,
                "max_retries": 3,
                "retry_delay": 1.0,
            },
            "feedback": {"auto_resubmit_timeout": 240},
            "network_security": {"bind_interface": "127.0.0.1"},
        }[section]
        mock_get_config.return_value = mock_config_mgr

        config, auto_resubmit = get_web_ui_config()

        self.assertIsInstance(config, WebUIConfig)
        self.assertEqual(config.port, 8080)
        self.assertEqual(auto_resubmit, 240)

    @patch("server.get_config")
    def test_load_config_with_defaults(self, mock_get_config):
        """测试使用默认值加载配置"""
        # 清除缓存
        import server
        from server import get_web_ui_config

        server._config_cache["config"] = None
        server._config_cache["timestamp"] = 0

        mock_config_mgr = MagicMock()
        mock_config_mgr.get_section.return_value = {}  # 空配置
        mock_get_config.return_value = mock_config_mgr

        config, auto_resubmit = get_web_ui_config()

        # 应该使用默认值
        self.assertEqual(config.port, 8080)
        self.assertEqual(config.timeout, 30)
        self.assertEqual(auto_resubmit, 240)


if __name__ == "__main__":
    unittest.main()
