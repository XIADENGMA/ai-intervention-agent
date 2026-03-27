"""file_validator.py 扩展单元测试。

覆盖基础测试未触及的边界路径：
- validate_file 中的 Exception 降级（lines 269-272）
- additional_check 抛出异常（lines 365-371）
- 文件名为 "." 或 ".."（line 389）
- declared_mime_type 但检测失败（line 413）
- 超大文件中间采样窗口（lines 446-448）
"""

from __future__ import annotations

import unittest
from unittest.mock import patch

from file_validator import FileValidator


class TestValidateFileException(unittest.TestCase):
    """validate_file 过程中异常降级"""

    def test_internal_exception_returns_error(self):
        """验证过程中意外异常被捕获并记录（lines 269-272）"""
        validator = FileValidator()
        png_data = b"\x89\x50\x4e\x47\x0d\x0a\x1a\x0a" + b"\x00" * 100

        with patch.object(
            validator, "_validate_basic_properties", side_effect=RuntimeError("boom")
        ):
            result = validator.validate_file(png_data, "test.png")

        self.assertFalse(result["valid"])
        self.assertTrue(any("验证过程异常" in e for e in result["errors"]))


class TestAdditionalCheckException(unittest.TestCase):
    """additional_check 回调异常处理"""

    def test_additional_check_raises(self):
        """additional_check 抛出异常时跳过该格式（lines 365-371）"""
        validator = FileValidator()
        riff_data = b"\x52\x49\x46\x46" + b"\x00" * 4 + b"WEBP" + b"\x00" * 100

        with patch.dict(
            "file_validator.IMAGE_MAGIC_NUMBERS",
            {
                b"\x52\x49\x46\x46": {
                    "extension": ".webp",
                    "mime_type": "image/webp",
                    "description": "WebP图片",
                    "additional_check": lambda _data: (_ for _ in ()).throw(
                        ValueError("check failed")
                    ),
                },
            },
            clear=True,
        ):
            result = validator.validate_file(riff_data, "test.webp")

        self.assertFalse(result["valid"])
        self.assertIn("无法识别的文件格式", result["errors"][0])


class TestAdditionalCheckReturnsFalse(unittest.TestCase):
    """additional_check 返回 False（非异常）"""

    def test_additional_check_false_skips_format(self):
        """additional_check 返回 False 时跳过该格式（line 365）"""
        validator = FileValidator()
        riff_data = b"\x52\x49\x46\x46" + b"\x00" * 4 + b"NOTW" + b"\x00" * 100

        result = validator.validate_file(riff_data, "test.webp")
        self.assertFalse(result["valid"])
        self.assertIn("无法识别的文件格式", result["errors"][0])


class TestFilenameDotAndDoubleDot(unittest.TestCase):
    """文件名为 "." 或 ".." 的边界"""

    def setUp(self) -> None:
        self.validator = FileValidator()
        self.png_data = b"\x89\x50\x4e\x47\x0d\x0a\x1a\x0a" + b"\x00" * 100

    def test_filename_dot(self):
        """文件名为 "." 时触发无效文件名错误（line 389）"""
        result = self.validator.validate_file(self.png_data, ".")
        self.assertFalse(result["valid"])
        self.assertTrue(any("文件名无效" in e for e in result["errors"]))

    def test_filename_double_dot(self):
        """文件名为 ".." 时触发无效文件名和路径遍历错误"""
        result = self.validator.validate_file(self.png_data, "..")
        self.assertFalse(result["valid"])
        self.assertTrue(
            any("文件名无效" in e or "非法字符" in e for e in result["errors"])
        )


class TestMimeConsistencyNoDetectedType(unittest.TestCase):
    """declared_mime_type 提供但文件类型未检测到"""

    def test_mime_check_skipped_when_no_detection(self):
        """类型检测失败时 MIME 一致性检查跳过（line 413）"""
        validator = FileValidator()
        unknown_data = b"\x00\x01\x02\x03" + b"\x00" * 100
        result = validator.validate_file(
            unknown_data, "test.bin", declared_mime_type="image/png"
        )
        self.assertFalse(result["valid"])
        self.assertFalse(any("MIME类型不一致" in w for w in result["warnings"]))


class TestLargeFileMiddleSampling(unittest.TestCase):
    """超大文件三窗口采样（头/尾/中间）"""

    def test_malicious_payload_in_middle(self):
        """恶意内容在文件中间应被中间窗口检测到（lines 446-448）

        构造 > 128KB 的文件，payload 放在中间。
        """
        validator = FileValidator()
        png_header = b"\x89\x50\x4e\x47\x0d\x0a\x1a\x0a"
        window = 64 * 1024
        padding = b"A" * window
        payload = b"<script>alert('xss')</script>"

        data = png_header + padding + payload + padding
        self.assertGreater(len(data), window * 2)

        result = validator.validate_file(data, "big.png")
        self.assertFalse(result["valid"])
        self.assertTrue(any("<script" in e for e in result["errors"]))

    def test_clean_large_file_passes(self):
        """干净的大文件应通过验证"""
        validator = FileValidator()
        png_header = b"\x89\x50\x4e\x47\x0d\x0a\x1a\x0a"
        data = png_header + (b"\x00" * (150 * 1024))

        result = validator.validate_file(data, "clean_large.png")
        self.assertTrue(result["valid"])


if __name__ == "__main__":
    unittest.main()
