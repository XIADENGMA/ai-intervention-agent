"""
Feedback 配置模块单元测试

测试覆盖：
    - FeedbackConfig 数据类的边界验证
    - get_feedback_config() 函数的配置获取和验证
    - calculate_backend_timeout() 函数的超时计算逻辑
    - get_feedback_prompts() 函数的向后兼容性
    - web_ui.py 中的 validate_auto_resubmit_timeout() 函数
"""

import unittest
from unittest.mock import MagicMock, patch


class TestFeedbackConfigConstants(unittest.TestCase):
    """测试 Feedback 配置常量"""

    def test_constants_imported(self):
        """测试常量导入"""
        from server import (
            AUTO_RESUBMIT_TIMEOUT_DEFAULT,
            AUTO_RESUBMIT_TIMEOUT_MAX,
            AUTO_RESUBMIT_TIMEOUT_MIN,
            BACKEND_BUFFER,
            BACKEND_MIN,
            FEEDBACK_TIMEOUT_DEFAULT,
            FEEDBACK_TIMEOUT_MAX,
            FEEDBACK_TIMEOUT_MIN,
            PROMPT_MAX_LENGTH,
        )

        # 验证默认值
        self.assertEqual(FEEDBACK_TIMEOUT_DEFAULT, 600)
        self.assertEqual(AUTO_RESUBMIT_TIMEOUT_DEFAULT, 240)

        # 验证边界值
        self.assertEqual(FEEDBACK_TIMEOUT_MIN, 60)
        self.assertEqual(FEEDBACK_TIMEOUT_MAX, 3600)
        self.assertEqual(AUTO_RESUBMIT_TIMEOUT_MIN, 30)
        self.assertEqual(AUTO_RESUBMIT_TIMEOUT_MAX, 250)  # 【优化】从290改为250

        # 验证缓冲和最低值
        self.assertEqual(BACKEND_BUFFER, 40)  # 【优化】从60改为40
        self.assertEqual(BACKEND_MIN, 260)  # 【优化】从300改为260，预留40秒安全余量
        self.assertEqual(PROMPT_MAX_LENGTH, 500)


class TestFeedbackConfigDataclass(unittest.TestCase):
    """测试 FeedbackConfig 数据类"""

    def test_normal_values(self):
        """测试正常值"""
        from server import FeedbackConfig

        config = FeedbackConfig(
            timeout=600,
            auto_resubmit_timeout=240,
            resubmit_prompt="测试提示",
            prompt_suffix="\n测试后缀",
        )

        self.assertEqual(config.timeout, 600)
        self.assertEqual(config.auto_resubmit_timeout, 240)
        self.assertEqual(config.resubmit_prompt, "测试提示")
        self.assertEqual(config.prompt_suffix, "\n测试后缀")

    def test_timeout_below_min(self):
        """测试 timeout 小于最小值"""
        from server import FEEDBACK_TIMEOUT_MIN, FeedbackConfig

        config = FeedbackConfig(
            timeout=10,  # 小于 60
            auto_resubmit_timeout=240,
            resubmit_prompt="测试",
            prompt_suffix="",
        )

        self.assertEqual(config.timeout, FEEDBACK_TIMEOUT_MIN)

    def test_timeout_above_max(self):
        """测试 timeout 大于最大值"""
        from server import FEEDBACK_TIMEOUT_MAX, FeedbackConfig

        config = FeedbackConfig(
            timeout=5000,  # 大于 3600
            auto_resubmit_timeout=240,
            resubmit_prompt="测试",
            prompt_suffix="",
        )

        self.assertEqual(config.timeout, FEEDBACK_TIMEOUT_MAX)

    def test_auto_resubmit_timeout_zero(self):
        """测试 auto_resubmit_timeout 为 0（禁用）"""
        from server import FeedbackConfig

        config = FeedbackConfig(
            timeout=600,
            auto_resubmit_timeout=0,  # 禁用
            resubmit_prompt="测试",
            prompt_suffix="",
        )

        self.assertEqual(config.auto_resubmit_timeout, 0)

    def test_auto_resubmit_timeout_below_min(self):
        """测试 auto_resubmit_timeout 小于最小值"""
        from server import AUTO_RESUBMIT_TIMEOUT_MIN, FeedbackConfig

        config = FeedbackConfig(
            timeout=600,
            auto_resubmit_timeout=10,  # 小于 30
            resubmit_prompt="测试",
            prompt_suffix="",
        )

        self.assertEqual(config.auto_resubmit_timeout, AUTO_RESUBMIT_TIMEOUT_MIN)

    def test_auto_resubmit_timeout_above_max(self):
        """测试 auto_resubmit_timeout 大于最大值"""
        from server import AUTO_RESUBMIT_TIMEOUT_MAX, FeedbackConfig

        config = FeedbackConfig(
            timeout=600,
            auto_resubmit_timeout=500,  # 大于 250（优化后的最大值）
            resubmit_prompt="测试",
            prompt_suffix="",
        )

        self.assertEqual(config.auto_resubmit_timeout, AUTO_RESUBMIT_TIMEOUT_MAX)

    def test_empty_resubmit_prompt(self):
        """测试空 resubmit_prompt"""
        from server import RESUBMIT_PROMPT_DEFAULT, FeedbackConfig

        config = FeedbackConfig(
            timeout=600,
            auto_resubmit_timeout=240,
            resubmit_prompt="",  # 空字符串
            prompt_suffix="",
        )

        self.assertEqual(config.resubmit_prompt, RESUBMIT_PROMPT_DEFAULT)

    def test_whitespace_only_resubmit_prompt(self):
        """测试仅空白字符的 resubmit_prompt"""
        from server import RESUBMIT_PROMPT_DEFAULT, FeedbackConfig

        config = FeedbackConfig(
            timeout=600,
            auto_resubmit_timeout=240,
            resubmit_prompt="   ",  # 仅空白
            prompt_suffix="",
        )

        self.assertEqual(config.resubmit_prompt, RESUBMIT_PROMPT_DEFAULT)

    def test_long_resubmit_prompt_truncation(self):
        """测试过长 resubmit_prompt 截断"""
        from server import PROMPT_MAX_LENGTH, FeedbackConfig

        long_prompt = "A" * 600  # 超过 500
        config = FeedbackConfig(
            timeout=600,
            auto_resubmit_timeout=240,
            resubmit_prompt=long_prompt,
            prompt_suffix="",
        )

        self.assertEqual(len(config.resubmit_prompt), PROMPT_MAX_LENGTH)

    def test_long_prompt_suffix_truncation(self):
        """测试过长 prompt_suffix 截断"""
        from server import PROMPT_MAX_LENGTH, FeedbackConfig

        long_suffix = "B" * 600  # 超过 500
        config = FeedbackConfig(
            timeout=600,
            auto_resubmit_timeout=240,
            resubmit_prompt="测试",
            prompt_suffix=long_suffix,
        )

        self.assertEqual(len(config.prompt_suffix), PROMPT_MAX_LENGTH)


class TestCalculateBackendTimeout(unittest.TestCase):
    """测试 calculate_backend_timeout() 函数"""

    def test_infinite_wait(self):
        """测试无限等待模式"""
        from server import calculate_backend_timeout

        result = calculate_backend_timeout(240, infinite_wait=True)
        self.assertEqual(result, 0)

    def test_disabled_auto_resubmit(self):
        """测试禁用自动提交"""
        from server import BACKEND_MIN, calculate_backend_timeout

        # auto_resubmit_timeout = 0
        result = calculate_backend_timeout(0, max_timeout=600)
        self.assertEqual(result, max(600, BACKEND_MIN))

        # auto_resubmit_timeout 负数
        result = calculate_backend_timeout(-10, max_timeout=400)
        self.assertEqual(result, max(400, BACKEND_MIN))

    def test_normal_calculation(self):
        """测试正常计算"""
        from server import BACKEND_BUFFER, BACKEND_MIN, calculate_backend_timeout

        # 240 + 40 = 280 > BACKEND_MIN(260)，使用 280
        result = calculate_backend_timeout(240, max_timeout=600)
        expected = min(max(240 + BACKEND_BUFFER, BACKEND_MIN), 600)
        self.assertEqual(result, expected)

    def test_below_backend_min(self):
        """测试计算结果低于最低值"""
        from server import BACKEND_MIN, calculate_backend_timeout

        # 100 + 40 = 140 < 260, 应该使用 260（BACKEND_MIN）
        result = calculate_backend_timeout(100, max_timeout=600)
        self.assertGreaterEqual(result, BACKEND_MIN)

    def test_max_timeout_limit(self):
        """测试最大超时限制"""
        from server import calculate_backend_timeout

        # 250 + 40 = 290 < 320, max_timeout = 320, 应该返回 290
        result = calculate_backend_timeout(250, max_timeout=320)
        self.assertEqual(result, 290)


class TestGetFeedbackConfig(unittest.TestCase):
    """测试 get_feedback_config() 函数"""

    @patch("server.get_config")
    def test_normal_config(self, mock_get_config):
        """测试正常配置获取"""
        from server import get_feedback_config

        mock_config_mgr = MagicMock()
        mock_config_mgr.get_section.return_value = {
            "timeout": 600,
            "auto_resubmit_timeout": 240,
            "resubmit_prompt": "测试提示",
            "prompt_suffix": "\n测试后缀",
        }
        mock_get_config.return_value = mock_config_mgr

        config = get_feedback_config()

        self.assertEqual(config.timeout, 600)
        self.assertEqual(config.auto_resubmit_timeout, 240)
        self.assertEqual(config.resubmit_prompt, "测试提示")
        self.assertEqual(config.prompt_suffix, "\n测试后缀")

    @patch("server.get_config")
    def test_config_with_defaults(self, mock_get_config):
        """测试使用默认值"""
        from server import (
            AUTO_RESUBMIT_TIMEOUT_DEFAULT,
            FEEDBACK_TIMEOUT_DEFAULT,
            get_feedback_config,
        )

        mock_config_mgr = MagicMock()
        mock_config_mgr.get_section.return_value = {}  # 空配置
        mock_get_config.return_value = mock_config_mgr

        config = get_feedback_config()

        self.assertEqual(config.timeout, FEEDBACK_TIMEOUT_DEFAULT)
        self.assertEqual(config.auto_resubmit_timeout, AUTO_RESUBMIT_TIMEOUT_DEFAULT)

    @patch("server.get_config")
    def test_config_exception(self, mock_get_config):
        """测试配置异常时使用默认值"""
        from server import (
            AUTO_RESUBMIT_TIMEOUT_DEFAULT,
            FEEDBACK_TIMEOUT_DEFAULT,
            get_feedback_config,
        )

        mock_get_config.side_effect = Exception("配置加载失败")

        config = get_feedback_config()

        self.assertEqual(config.timeout, FEEDBACK_TIMEOUT_DEFAULT)
        self.assertEqual(config.auto_resubmit_timeout, AUTO_RESUBMIT_TIMEOUT_DEFAULT)


class TestGetFeedbackPrompts(unittest.TestCase):
    """测试 get_feedback_prompts() 函数（向后兼容）"""

    @patch("server.get_feedback_config")
    def test_returns_tuple(self, mock_get_feedback_config):
        """测试返回元组"""
        from server import FeedbackConfig, get_feedback_prompts

        mock_get_feedback_config.return_value = FeedbackConfig(
            timeout=600,
            auto_resubmit_timeout=240,
            resubmit_prompt="提示1",
            prompt_suffix="后缀1",
        )

        result = get_feedback_prompts()

        self.assertIsInstance(result, tuple)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0], "提示1")
        self.assertEqual(result[1], "后缀1")


class TestWebUIValidateAutoResubmitTimeout(unittest.TestCase):
    """测试 web_ui.py 中的 validate_auto_resubmit_timeout() 函数"""

    def test_zero_value(self):
        """测试值为 0（禁用）"""
        from web_ui import validate_auto_resubmit_timeout

        result = validate_auto_resubmit_timeout(0)
        self.assertEqual(result, 0)

    def test_negative_value(self):
        """测试负值（转换为禁用）"""
        from web_ui import validate_auto_resubmit_timeout

        result = validate_auto_resubmit_timeout(-10)
        self.assertEqual(result, 0)

    def test_below_min(self):
        """测试小于最小值"""
        from web_ui import AUTO_RESUBMIT_TIMEOUT_MIN, validate_auto_resubmit_timeout

        result = validate_auto_resubmit_timeout(10)
        self.assertEqual(result, AUTO_RESUBMIT_TIMEOUT_MIN)

    def test_above_max(self):
        """测试大于最大值"""
        from web_ui import AUTO_RESUBMIT_TIMEOUT_MAX, validate_auto_resubmit_timeout

        result = validate_auto_resubmit_timeout(500)
        self.assertEqual(result, AUTO_RESUBMIT_TIMEOUT_MAX)

    def test_normal_value(self):
        """测试正常值"""
        from web_ui import validate_auto_resubmit_timeout

        result = validate_auto_resubmit_timeout(120)
        self.assertEqual(result, 120)

    def test_boundary_min(self):
        """测试最小边界值"""
        from web_ui import AUTO_RESUBMIT_TIMEOUT_MIN, validate_auto_resubmit_timeout

        result = validate_auto_resubmit_timeout(AUTO_RESUBMIT_TIMEOUT_MIN)
        self.assertEqual(result, AUTO_RESUBMIT_TIMEOUT_MIN)

    def test_boundary_max(self):
        """测试最大边界值"""
        from web_ui import AUTO_RESUBMIT_TIMEOUT_MAX, validate_auto_resubmit_timeout

        result = validate_auto_resubmit_timeout(AUTO_RESUBMIT_TIMEOUT_MAX)
        self.assertEqual(result, AUTO_RESUBMIT_TIMEOUT_MAX)


class TestIntegration(unittest.TestCase):
    """集成测试"""

    def test_server_and_webui_constants_match(self):
        """测试 server.py 和 web_ui.py 的常量一致性"""
        from server import (
            AUTO_RESUBMIT_TIMEOUT_DEFAULT as SERVER_DEFAULT,
        )
        from server import (
            AUTO_RESUBMIT_TIMEOUT_MAX as SERVER_MAX,
        )
        from server import (
            AUTO_RESUBMIT_TIMEOUT_MIN as SERVER_MIN,
        )
        from web_ui import (
            AUTO_RESUBMIT_TIMEOUT_DEFAULT as WEBUI_DEFAULT,
        )
        from web_ui import (
            AUTO_RESUBMIT_TIMEOUT_MAX as WEBUI_MAX,
        )
        from web_ui import (
            AUTO_RESUBMIT_TIMEOUT_MIN as WEBUI_MIN,
        )

        self.assertEqual(SERVER_MIN, WEBUI_MIN)
        self.assertEqual(SERVER_MAX, WEBUI_MAX)
        self.assertEqual(SERVER_DEFAULT, WEBUI_DEFAULT)

    def test_timeout_calculation_consistency(self):
        """测试超时计算一致性"""
        from server import (
            calculate_backend_timeout,
        )

        # 测试多种场景【优化】更新常量值 BACKEND_BUFFER=40, BACKEND_MIN=260
        test_cases = [
            (240, 600, 280),  # 正常: max(240+40, 260) = 280, min(280, 600) = 280
            (100, 600, 260),  # 低于最低: max(100+40, 260) = 260, min(260, 600) = 260
            (250, 600, 290),  # 接近最大: max(250+40, 260) = 290, min(290, 600) = 290
            (250, 280, 280),  # 超过限制: max(250+40, 260) = 290, min(290, 280) = 280
            (0, 600, 600),  # 禁用: max(600, 260) = 600
        ]

        for auto_resubmit, max_timeout, expected in test_cases:
            result = calculate_backend_timeout(auto_resubmit, max_timeout=max_timeout)
            self.assertEqual(
                result,
                expected,
                f"auto_resubmit={auto_resubmit}, max_timeout={max_timeout}",
            )


if __name__ == "__main__":
    unittest.main()
