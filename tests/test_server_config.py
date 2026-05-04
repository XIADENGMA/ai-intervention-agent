"""server_config.py 单元测试。

覆盖配置数据类验证、输入校验、图片处理、MCP 响应构建等分支：
- WebUIConfig / FeedbackConfig 边界检查
- validate_input 长文本截断、非法选项过滤
- _process_image MIME 推断、data URI、边界图片
- parse_structured_response 完整流程
- _make_resubmit_response 两种模式
- _guess_mime_type_from_data 魔数检测
"""

from __future__ import annotations

import base64
import unittest
from unittest.mock import patch

from server_config import (
    BACKEND_MIN,
    FEEDBACK_TIMEOUT_DEFAULT,
    MAX_MESSAGE_LENGTH,
    MAX_OPTION_LENGTH,
    FeedbackConfig,
    WebUIConfig,
    _append_prompt_suffix,
    _format_file_size,
    _generate_task_id,
    _guess_mime_type_from_data,
    _make_resubmit_response,
    _process_image,
    calculate_backend_timeout,
    get_feedback_config,
    get_feedback_prompts,
    get_target_host,
    parse_structured_response,
    resolve_external_base_url,
    validate_input,
)


class TestWebUIConfig(unittest.TestCase):
    """WebUIConfig 数据类"""

    def test_valid_config(self):
        cfg = WebUIConfig(host="localhost", port=8080)
        self.assertEqual(cfg.port, 8080)
        self.assertEqual(cfg.timeout, 30)

    def test_invalid_port(self):
        with self.assertRaises(ValueError):
            WebUIConfig(host="localhost", port=0)
        with self.assertRaises(ValueError):
            WebUIConfig(host="localhost", port=70000)

    def test_privileged_port(self):
        cfg = WebUIConfig(host="localhost", port=80)
        self.assertEqual(cfg.port, 80)

    def test_clamp_timeout(self):
        cfg = WebUIConfig(host="localhost", port=8080, timeout=999)
        self.assertLessEqual(cfg.timeout, 300)

    def test_clamp_retries(self):
        cfg = WebUIConfig(host="localhost", port=8080, max_retries=99)
        self.assertLessEqual(cfg.max_retries, 10)

    def test_external_base_url_default(self):
        cfg = WebUIConfig(host="localhost", port=8080)
        self.assertEqual(cfg.external_base_url, "")


class TestFeedbackConfig(unittest.TestCase):
    """FeedbackConfig 数据类"""

    def test_valid_config(self):
        cfg = FeedbackConfig(
            timeout=600,
            auto_resubmit_timeout=240,
            resubmit_prompt="test",
            prompt_suffix="suffix",
        )
        self.assertEqual(cfg.timeout, 600)

    def test_clamp_timeout(self):
        cfg = FeedbackConfig(
            timeout=9999,
            auto_resubmit_timeout=240,
            resubmit_prompt="test",
            prompt_suffix="",
        )
        self.assertLessEqual(cfg.timeout, 3600)

    def test_zero_auto_resubmit_not_clamped(self):
        cfg = FeedbackConfig(
            timeout=600,
            auto_resubmit_timeout=0,
            resubmit_prompt="test",
            prompt_suffix="",
        )
        self.assertEqual(cfg.auto_resubmit_timeout, 0)

    def test_long_prompt_truncated(self):
        from server_config import PROMPT_MAX_LENGTH

        long_prompt = "x" * (PROMPT_MAX_LENGTH + 500)
        cfg = FeedbackConfig(
            timeout=600,
            auto_resubmit_timeout=240,
            resubmit_prompt=long_prompt,
            prompt_suffix="",
        )
        self.assertLessEqual(len(cfg.resubmit_prompt), PROMPT_MAX_LENGTH + 10)


class TestGetFeedbackConfig(unittest.TestCase):
    """get_feedback_config 函数"""

    def test_default_config(self):
        cfg = get_feedback_config()
        self.assertIsInstance(cfg, FeedbackConfig)
        self.assertGreater(cfg.timeout, 0)

    def test_value_error_fallback(self):
        with patch("server_config.get_config", side_effect=ValueError("bad")):
            cfg = get_feedback_config()
            self.assertEqual(cfg.timeout, FEEDBACK_TIMEOUT_DEFAULT)

    def test_generic_error_fallback(self):
        with patch("server_config.get_config", side_effect=RuntimeError("fail")):
            cfg = get_feedback_config()
            self.assertEqual(cfg.timeout, FEEDBACK_TIMEOUT_DEFAULT)


class TestCalculateBackendTimeout(unittest.TestCase):
    """calculate_backend_timeout 函数"""

    def test_infinite_wait(self):
        self.assertEqual(calculate_backend_timeout(240, 600, infinite_wait=True), 0)

    def test_no_auto_resubmit(self):
        result = calculate_backend_timeout(0, 600)
        self.assertEqual(result, max(600, BACKEND_MIN))

    def test_normal_calculation(self):
        result = calculate_backend_timeout(240, 600)
        self.assertGreaterEqual(result, BACKEND_MIN)
        self.assertLessEqual(result, 600)

    def test_default_max_timeout(self):
        result = calculate_backend_timeout(240, 0)
        self.assertGreaterEqual(result, BACKEND_MIN)


class TestGetFeedbackPrompts(unittest.TestCase):
    """get_feedback_prompts 函数"""

    def test_returns_tuple(self):
        result = get_feedback_prompts()
        self.assertIsInstance(result, tuple)
        self.assertEqual(len(result), 2)


class TestAppendPromptSuffix(unittest.TestCase):
    """_append_prompt_suffix 函数"""

    def test_appends_suffix(self):
        result = _append_prompt_suffix("hello")
        self.assertTrue(len(result) > len("hello"))

    def test_no_double_append(self):
        _, suffix = get_feedback_prompts()
        text_with_suffix = "hello" + suffix
        result = _append_prompt_suffix(text_with_suffix)
        self.assertEqual(result, text_with_suffix)


class TestMakeResubmitResponse(unittest.TestCase):
    """_make_resubmit_response 函数"""

    def test_mcp_mode(self):
        result = _make_resubmit_response(as_mcp=True)
        self.assertIsInstance(result, list)
        self.assertTrue(len(result) > 0)

    def test_dict_mode(self):
        result = _make_resubmit_response(as_mcp=False)
        self.assertIsInstance(result, dict)
        self.assertIn("text", result)


class TestValidateInput(unittest.TestCase):
    """validate_input 函数"""

    def test_normal_input(self):
        prompt, options = validate_input("hello", ["a", "b"])
        self.assertEqual(prompt, "hello")
        self.assertEqual(options, ["a", "b"])

    def test_long_prompt_truncated(self):
        long_text = "x" * (MAX_MESSAGE_LENGTH + 100)
        prompt, _ = validate_input(long_text)
        self.assertLessEqual(len(prompt), MAX_MESSAGE_LENGTH + 10)

    def test_non_string_options_filtered(self):
        _, options = validate_input("test", ["valid", 123, None, "also_valid"])
        self.assertEqual(options, ["valid", "also_valid"])

    def test_long_option_truncated(self):
        long_option = "o" * (MAX_OPTION_LENGTH + 100)
        _, options = validate_input("test", [long_option])
        self.assertEqual(len(options), 1)
        self.assertLessEqual(len(options[0]), MAX_OPTION_LENGTH + 10)

    def test_empty_options(self):
        _, options = validate_input("test", None)
        self.assertEqual(options, [])

    def test_non_string_prompt_raises(self):
        with self.assertRaises(ValueError):
            validate_input(123)  # type: ignore[arg-type]


class TestGenerateTaskId(unittest.TestCase):
    """_generate_task_id 函数"""

    def test_uniqueness(self):
        ids = {_generate_task_id() for _ in range(100)}
        self.assertEqual(len(ids), 100)

    def test_format(self):
        task_id = _generate_task_id()
        self.assertIn("-", task_id)


class TestGetTargetHost(unittest.TestCase):
    """get_target_host 函数"""

    def test_wildcard_to_localhost(self):
        self.assertEqual(get_target_host("0.0.0.0"), "localhost")
        self.assertEqual(get_target_host("::"), "localhost")

    def test_specific_host_preserved(self):
        self.assertEqual(get_target_host("192.168.1.1"), "192.168.1.1")


class TestResolveExternalBaseUrl(unittest.TestCase):
    """resolve_external_base_url 函数"""

    def test_prefers_config_object_external_base_url(self):
        cfg = WebUIConfig(
            host="0.0.0.0",
            port=8080,
            external_base_url="http://ai.local:8080/",
        )
        self.assertEqual(resolve_external_base_url(cfg), "http://ai.local:8080")

    @patch("server_config.get_config")
    def test_falls_back_to_host_port(self, mock_get_config):
        mock_get_config.return_value.get_section.return_value = {}
        cfg = WebUIConfig(host="0.0.0.0", port=8080)
        self.assertEqual(resolve_external_base_url(cfg), "http://localhost:8080")


class TestFormatFileSize(unittest.TestCase):
    """_format_file_size 函数"""

    def test_bytes(self):
        self.assertIn("B", _format_file_size(500))

    def test_kilobytes(self):
        self.assertIn("KB", _format_file_size(2048))

    def test_megabytes(self):
        self.assertIn("MB", _format_file_size(2 * 1024 * 1024))


class TestGuessMimeTypeFromData(unittest.TestCase):
    """_guess_mime_type_from_data 函数"""

    def _encode(self, data: bytes) -> str:
        return base64.b64encode(data).decode()

    def test_png(self):
        data = self._encode(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)
        self.assertEqual(_guess_mime_type_from_data(data), "image/png")

    def test_jpeg(self):
        data = self._encode(b"\xff\xd8\xff" + b"\x00" * 100)
        self.assertEqual(_guess_mime_type_from_data(data), "image/jpeg")

    def test_gif87a(self):
        data = self._encode(b"GIF87a" + b"\x00" * 100)
        self.assertEqual(_guess_mime_type_from_data(data), "image/gif")

    def test_gif89a(self):
        data = self._encode(b"GIF89a" + b"\x00" * 100)
        self.assertEqual(_guess_mime_type_from_data(data), "image/gif")

    def test_webp(self):
        data = self._encode(b"RIFF" + b"\x00" * 4 + b"WEBP" + b"\x00" * 100)
        self.assertEqual(_guess_mime_type_from_data(data), "image/webp")

    def test_svg_no_longer_detected(self):
        """SVG 检测已移除（安全策略：与 file_validator.py 对齐）"""
        data = self._encode(b"<svg xmlns='...'>" + b"\x00" * 100)
        self.assertIsNone(_guess_mime_type_from_data(data))

    def test_unknown(self):
        data = self._encode(b"unknown binary data here " * 10)
        self.assertIsNone(_guess_mime_type_from_data(data))

    def test_invalid_base64(self):
        self.assertIsNone(_guess_mime_type_from_data("!!!not-base64!!!"))

    def test_bmp(self):
        data = self._encode(b"BM" + b"\x00" * 100)
        self.assertEqual(_guess_mime_type_from_data(data), "image/bmp")


class TestProcessImage(unittest.TestCase):
    """_process_image 函数"""

    def _make_png_b64(self) -> str:
        raw = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
        return base64.b64encode(raw).decode()

    def test_valid_image(self):
        img_data = {"data": self._make_png_b64(), "content_type": "image/png"}
        img_content, text_desc = _process_image(img_data, 0)
        self.assertIsNotNone(img_content)
        assert text_desc is not None
        self.assertIn("图片 1", text_desc)

    def test_invalid_data_empty(self):
        img_content, text_desc = _process_image({"data": ""}, 0)
        self.assertIsNone(img_content)
        assert text_desc is not None
        self.assertIn("失败", text_desc)

    def test_invalid_data_non_string(self):
        img_content, text_desc = _process_image({"data": 12345}, 0)
        self.assertIsNone(img_content)

    def test_data_uri_format(self):
        raw = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
        b64 = base64.b64encode(raw).decode()
        img_data = {"data": f"data:image/png;base64,{b64}"}
        img_content, _ = _process_image(img_data, 0)
        self.assertIsNotNone(img_content)
        assert img_content is not None
        self.assertEqual(img_content.mimeType, "image/png")

    def test_mime_with_semicolon(self):
        img_data = {
            "data": self._make_png_b64(),
            "content_type": "image/png; charset=utf-8",
        }
        img_content, _ = _process_image(img_data, 0)
        self.assertIsNotNone(img_content)
        assert img_content is not None
        self.assertEqual(img_content.mimeType, "image/png")

    def test_jpg_to_jpeg(self):
        img_data = {"data": self._make_png_b64(), "content_type": "image/jpg"}
        img_content, _ = _process_image(img_data, 0)
        self.assertIsNotNone(img_content)
        assert img_content is not None
        self.assertEqual(img_content.mimeType, "image/jpeg")

    def test_non_image_mime_fallback(self):
        img_data = {
            "data": self._make_png_b64(),
            "content_type": "application/octet-stream",
        }
        img_content, _ = _process_image(img_data, 0)
        self.assertIsNotNone(img_content)
        assert img_content is not None
        self.assertTrue(img_content.mimeType.startswith("image/"))


class TestParseStructuredResponse(unittest.TestCase):
    """parse_structured_response 函数"""

    @staticmethod
    def _last_text(result: list) -> str:
        from mcp.types import TextContent

        last = result[-1]
        assert isinstance(last, TextContent)
        return last.text

    def test_empty_response(self):
        result = parse_structured_response(None)
        self.assertTrue(len(result) >= 1)
        self.assertIn("未提供", self._last_text(result))

    def test_text_only(self):
        result = parse_structured_response({"user_input": "hello"})
        self.assertIn("hello", self._last_text(result))

    def test_options_only(self):
        result = parse_structured_response({"selected_options": ["opt1", "opt2"]})
        self.assertIn("opt1", self._last_text(result))

    def test_legacy_interactive_feedback(self):
        result = parse_structured_response(
            {"interactive_feedback": "legacy text", "user_input": ""}
        )
        self.assertIn("legacy text", self._last_text(result))

    def test_with_valid_image(self):
        raw = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
        b64 = base64.b64encode(raw).decode()
        result = parse_structured_response(
            {
                "user_input": "see image",
                "images": [{"data": b64, "content_type": "image/png"}],
            }
        )
        self.assertTrue(len(result) >= 2)

    def test_with_invalid_image(self):
        result = parse_structured_response(
            {"user_input": "broken", "images": [{"data": ""}, "not_a_dict"]}
        )
        self.assertTrue(len(result) >= 1)

    def test_non_dict_response(self):
        result = parse_structured_response("not a dict")  # type: ignore[arg-type]
        self.assertTrue(len(result) >= 1)

    def test_selected_options_non_list(self):
        result = parse_structured_response({"selected_options": "not_list"})
        self.assertTrue(len(result) >= 1)


# ──────────────────────────────────────────────────────────
# 覆盖率补充
# ──────────────────────────────────────────────────────────


class TestAppendPromptSuffixEmpty(unittest.TestCase):
    """line 212: prompt_suffix 为空时直接返回"""

    def test_empty_suffix_returns_text_unchanged(self):
        from server_config import _append_prompt_suffix

        with patch("server_config.get_feedback_prompts", return_value=("resubmit", "")):
            result = _append_prompt_suffix("hello")
            self.assertEqual(result, "hello")


class TestParseStructuredResponseImageException(unittest.TestCase):
    """lines 421-423: 图片处理抛异常"""

    def test_image_process_exception(self):
        with patch(
            "server_config._process_image", side_effect=ValueError("decode fail")
        ):
            result = parse_structured_response(
                {"images": [{"data": "abc", "content_type": "image/png"}]}
            )
            text_items = [r for r in result if hasattr(r, "text")]
            self.assertTrue(
                any("处理失败" in str(getattr(t, "text", "")) for t in text_items)
            )


class TestParseStructuredResponseUnknownType(unittest.TestCase):
    """line 444: result 中包含未知类型"""

    def test_unknown_type_in_result(self):
        import logging

        with patch(
            "server_config._process_image",
            return_value=(42, None),
        ):
            with self.assertLogs("server_config", level=logging.DEBUG) as logs:
                parse_structured_response(
                    {"images": [{"data": "abc", "content_type": "image/png"}]}
                )
            unknown_logs = [line for line in logs.output if "未知类型" in line]
            self.assertTrue(len(unknown_logs) >= 1)


if __name__ == "__main__":
    unittest.main()
