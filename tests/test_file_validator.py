#!/usr/bin/env python3
"""
AI Intervention Agent - 文件验证器单元测试

测试覆盖：
1. 魔数验证
2. 恶意内容扫描
3. 文件名安全检查
4. MIME 类型一致性
5. 边界条件
"""

import sys
import unittest
from pathlib import Path

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


class TestMagicNumberValidation(unittest.TestCase):
    """测试魔数验证"""

    def setUp(self):
        """每个测试前的准备"""
        from file_validator import FileValidator

        self.validator = FileValidator()

    def test_png_detection(self):
        """测试 PNG 格式检测"""
        # PNG 魔数
        png_data = b"\x89\x50\x4e\x47\x0d\x0a\x1a\x0a" + b"\x00" * 100

        result = self.validator.validate_file(png_data, "test.png")

        self.assertTrue(result["valid"])
        self.assertEqual(result["mime_type"], "image/png")
        self.assertEqual(result["extension"], ".png")

    def test_jpeg_detection(self):
        """测试 JPEG 格式检测"""
        # JPEG 魔数 (JFIF)
        jpeg_data = b"\xff\xd8\xff\xe0" + b"\x00" * 100

        result = self.validator.validate_file(jpeg_data, "test.jpg")

        self.assertTrue(result["valid"])
        self.assertEqual(result["mime_type"], "image/jpeg")
        self.assertEqual(result["extension"], ".jpg")

    def test_gif_detection(self):
        """测试 GIF 格式检测"""
        # GIF89a 魔数
        gif_data = b"\x47\x49\x46\x38\x39\x61" + b"\x00" * 100

        result = self.validator.validate_file(gif_data, "test.gif")

        self.assertTrue(result["valid"])
        self.assertEqual(result["mime_type"], "image/gif")

    def test_unknown_format(self):
        """测试未知格式"""
        unknown_data = b"\x00\x01\x02\x03" + b"\x00" * 100

        result = self.validator.validate_file(unknown_data, "test.bin")

        self.assertFalse(result["valid"])
        self.assertIn("无法识别的文件格式", result["errors"][0])


class TestMaliciousContentScan(unittest.TestCase):
    """测试恶意内容扫描"""

    def setUp(self):
        """每个测试前的准备"""
        from file_validator import FileValidator

        self.validator = FileValidator()

    def test_javascript_detection(self):
        """测试 JavaScript 代码检测"""
        # PNG 魔数 + JavaScript 代码
        malicious_data = (
            b"\x89\x50\x4e\x47\x0d\x0a\x1a\x0a" + b"<script>alert('xss')</script>"
        )

        result = self.validator.validate_file(malicious_data, "test.png")

        self.assertFalse(result["valid"])
        self.assertTrue(any("可疑内容模式" in e for e in result["errors"]))

    def test_php_detection(self):
        """测试 PHP 代码检测"""
        malicious_data = b"\x89\x50\x4e\x47\x0d\x0a\x1a\x0a" + b"<?php system('ls'); ?>"

        result = self.validator.validate_file(malicious_data, "test.png")

        self.assertFalse(result["valid"])

    def test_clean_file(self):
        """测试干净文件"""
        # 只有 PNG 魔数和正常数据
        clean_data = (
            b"\x89\x50\x4e\x47\x0d\x0a\x1a\x0a" + b"normal image data here" * 100
        )

        result = self.validator.validate_file(clean_data, "test.png")

        self.assertTrue(result["valid"])
        self.assertEqual(len(result["errors"]), 0)


class TestFilenameValidation(unittest.TestCase):
    """测试文件名安全检查"""

    def setUp(self):
        """每个测试前的准备"""
        from file_validator import FileValidator

        self.validator = FileValidator()
        # PNG 魔数
        self.png_data = b"\x89\x50\x4e\x47\x0d\x0a\x1a\x0a" + b"\x00" * 100

    def test_path_traversal(self):
        """测试路径遍历攻击"""
        result = self.validator.validate_file(self.png_data, "../../../etc/passwd")

        self.assertFalse(result["valid"])
        self.assertTrue(any("非法字符" in e for e in result["errors"]))

    def test_backslash_path(self):
        """测试反斜杠路径"""
        result = self.validator.validate_file(self.png_data, "..\\..\\etc\\passwd")

        self.assertFalse(result["valid"])

    def test_dangerous_extension(self):
        """测试危险扩展名"""
        result = self.validator.validate_file(self.png_data, "test.exe")

        self.assertFalse(result["valid"])
        self.assertTrue(any("危险的文件扩展名" in e for e in result["errors"]))

    def test_hidden_file(self):
        """测试隐藏文件"""
        result = self.validator.validate_file(self.png_data, ".hidden.png")

        # 隐藏文件是警告，不是错误
        self.assertTrue(any("隐藏文件" in w for w in result["warnings"]))

    def test_special_characters(self):
        """测试特殊字符"""
        result = self.validator.validate_file(self.png_data, "test<script>.png")

        self.assertTrue(any("特殊字符" in w for w in result["warnings"]))

    def test_empty_filename(self):
        """测试空文件名"""
        result = self.validator.validate_file(self.png_data, "")

        self.assertFalse(result["valid"])

    def test_long_filename(self):
        """测试过长文件名"""
        long_name = "a" * 300 + ".png"
        result = self.validator.validate_file(self.png_data, long_name)

        self.assertFalse(result["valid"])
        self.assertTrue(any("文件名过长" in e for e in result["errors"]))


class TestFileSizeValidation(unittest.TestCase):
    """测试文件大小验证"""

    def test_empty_file(self):
        """测试空文件"""
        from file_validator import FileValidator

        validator = FileValidator()
        result = validator.validate_file(b"", "test.png")

        self.assertFalse(result["valid"])
        self.assertTrue(any("文件为空" in e for e in result["errors"]))

    def test_oversized_file(self):
        """测试超大文件"""
        from file_validator import FileValidator

        # 设置较小的限制
        validator = FileValidator(max_file_size=1000)

        # PNG 魔数 + 超大数据
        large_data = b"\x89\x50\x4e\x47\x0d\x0a\x1a\x0a" + b"\x00" * 2000
        result = validator.validate_file(large_data, "test.png")

        self.assertFalse(result["valid"])
        self.assertTrue(any("文件大小超过限制" in e for e in result["errors"]))


class TestMimeConsistency(unittest.TestCase):
    """测试 MIME 类型一致性"""

    def setUp(self):
        """每个测试前的准备"""
        from file_validator import FileValidator

        self.validator = FileValidator()
        self.png_data = b"\x89\x50\x4e\x47\x0d\x0a\x1a\x0a" + b"\x00" * 100

    def test_consistent_mime(self):
        """测试一致的 MIME 类型"""
        result = self.validator.validate_file(
            self.png_data, "test.png", declared_mime_type="image/png"
        )

        self.assertTrue(result["valid"])
        # 不应有 MIME 不一致警告
        self.assertFalse(any("MIME类型不一致" in w for w in result["warnings"]))

    def test_inconsistent_mime(self):
        """测试不一致的 MIME 类型"""
        result = self.validator.validate_file(
            self.png_data, "test.png", declared_mime_type="image/jpeg"
        )

        # 文件仍然有效，但有警告
        self.assertTrue(result["valid"])
        self.assertTrue(any("MIME类型不一致" in w for w in result["warnings"]))


class TestConvenienceFunctions(unittest.TestCase):
    """测试便捷函数"""

    def test_validate_uploaded_file(self):
        """测试 validate_uploaded_file 函数"""
        from file_validator import validate_uploaded_file

        png_data = b"\x89\x50\x4e\x47\x0d\x0a\x1a\x0a" + b"\x00" * 100
        result = validate_uploaded_file(png_data, "test.png")

        self.assertTrue(result["valid"])

    def test_is_safe_image_file(self):
        """测试 is_safe_image_file 函数"""
        from file_validator import is_safe_image_file

        png_data = b"\x89\x50\x4e\x47\x0d\x0a\x1a\x0a" + b"\x00" * 100
        result = is_safe_image_file(png_data, "test.png")

        self.assertTrue(result)

    def test_is_safe_image_file_unsafe(self):
        """测试 is_safe_image_file 函数 - 不安全文件"""
        from file_validator import is_safe_image_file

        # 包含恶意代码
        malicious_data = (
            b"\x89\x50\x4e\x47\x0d\x0a\x1a\x0a" + b"<script>alert('xss')</script>"
        )
        result = is_safe_image_file(malicious_data, "test.png")

        self.assertFalse(result)


class TestEdgeCases(unittest.TestCase):
    """测试边界条件"""

    def setUp(self):
        """每个测试前的准备"""
        from file_validator import FileValidator

        self.validator = FileValidator()

    def test_none_file_data(self):
        """测试 None 文件数据"""
        result = self.validator.validate_file(None, "test.png")

        self.assertFalse(result["valid"])

    def test_invalid_max_file_size(self):
        """测试无效的最大文件大小"""
        from file_validator import FileValidator

        with self.assertRaises(ValueError):
            FileValidator(max_file_size=0)

    def test_whitespace_only_filename(self):
        """测试只有空格的文件名"""
        png_data = b"\x89\x50\x4e\x47\x0d\x0a\x1a\x0a" + b"\x00" * 100
        result = self.validator.validate_file(png_data, "   ")

        self.assertFalse(result["valid"])


def run_tests():
    """运行所有测试"""
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    suite.addTests(loader.loadTestsFromTestCase(TestMagicNumberValidation))
    suite.addTests(loader.loadTestsFromTestCase(TestMaliciousContentScan))
    suite.addTests(loader.loadTestsFromTestCase(TestFilenameValidation))
    suite.addTests(loader.loadTestsFromTestCase(TestFileSizeValidation))
    suite.addTests(loader.loadTestsFromTestCase(TestMimeConsistency))
    suite.addTests(loader.loadTestsFromTestCase(TestConvenienceFunctions))
    suite.addTests(loader.loadTestsFromTestCase(TestEdgeCases))

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    return result.wasSuccessful()


if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
