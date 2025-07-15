#!/usr/bin/env python3
"""
文件验证模块 - 实现安全的文件上传验证
包含文件头部魔数验证、文件类型检查、恶意内容扫描等功能
"""

import logging
import re
from pathlib import Path
from typing import Dict, Optional

logger = logging.getLogger(__name__)

# 支持的图片格式魔数字典
IMAGE_MAGIC_NUMBERS = {
    # PNG格式
    b"\x89\x50\x4e\x47\x0d\x0a\x1a\x0a": {
        "extension": ".png",
        "mime_type": "image/png",
        "description": "PNG图片",
    },
    # JPEG格式 (多种变体)
    b"\xff\xd8\xff\xe0": {
        "extension": ".jpg",
        "mime_type": "image/jpeg",
        "description": "JPEG图片 (JFIF)",
    },
    b"\xff\xd8\xff\xe1": {
        "extension": ".jpg",
        "mime_type": "image/jpeg",
        "description": "JPEG图片 (EXIF)",
    },
    b"\xff\xd8\xff\xe2": {
        "extension": ".jpg",
        "mime_type": "image/jpeg",
        "description": "JPEG图片 (Canon)",
    },
    b"\xff\xd8\xff\xe3": {
        "extension": ".jpg",
        "mime_type": "image/jpeg",
        "description": "JPEG图片 (Samsung)",
    },
    b"\xff\xd8\xff\xdb": {
        "extension": ".jpg",
        "mime_type": "image/jpeg",
        "description": "JPEG图片 (标准)",
    },
    # GIF格式
    b"\x47\x49\x46\x38\x37\x61": {
        "extension": ".gif",
        "mime_type": "image/gif",
        "description": "GIF图片 (87a)",
    },
    b"\x47\x49\x46\x38\x39\x61": {
        "extension": ".gif",
        "mime_type": "image/gif",
        "description": "GIF图片 (89a)",
    },
    # WebP格式
    b"\x52\x49\x46\x46": {
        "extension": ".webp",
        "mime_type": "image/webp",
        "description": "WebP图片",
        "additional_check": lambda data: data[8:12] == b"WEBP",
    },
    # BMP格式
    b"\x42\x4d": {
        "extension": ".bmp",
        "mime_type": "image/bmp",
        "description": "BMP图片",
    },
    # TIFF格式
    b"\x49\x49\x2a\x00": {
        "extension": ".tiff",
        "mime_type": "image/tiff",
        "description": "TIFF图片 (Little Endian)",
    },
    b"\x4d\x4d\x00\x2a": {
        "extension": ".tiff",
        "mime_type": "image/tiff",
        "description": "TIFF图片 (Big Endian)",
    },
    # ICO格式
    b"\x00\x00\x01\x00": {
        "extension": ".ico",
        "mime_type": "image/x-icon",
        "description": "ICO图标",
    },
    # SVG格式 (XML开头)
    b"\x3c\x3f\x78\x6d\x6c": {
        "extension": ".svg",
        "mime_type": "image/svg+xml",
        "description": "SVG矢量图",
        "additional_check": lambda data: b"<svg" in data[:1024].lower(),
    },
}

# 危险文件扩展名列表
DANGEROUS_EXTENSIONS = {
    ".exe",
    ".bat",
    ".cmd",
    ".com",
    ".scr",
    ".pif",
    ".vbs",
    ".js",
    ".jar",
    ".msi",
    ".dll",
    ".sys",
    ".drv",
    ".ocx",
    ".cpl",
    ".inf",
    ".reg",
    ".ps1",
    ".sh",
    ".bash",
    ".zsh",
    ".fish",
    ".py",
    ".pl",
    ".rb",
    ".php",
    ".asp",
    ".jsp",
    ".war",
    ".ear",
    ".deb",
    ".rpm",
    ".dmg",
    ".pkg",
    ".app",
}

# 恶意内容模式 (简化版)
MALICIOUS_PATTERNS = [
    # JavaScript代码模式
    rb"<script[^>]*>",
    rb"javascript:",
    rb"eval\s*\(",
    rb"document\.write",
    rb"window\.location",
    # PHP代码模式
    rb"<\?php",
    rb"<\?=",
    rb"eval\s*\(",
    rb"system\s*\(",
    rb"exec\s*\(",
    # Shell命令模式
    rb"#!/bin/",
    rb"rm\s+-rf",
    rb"wget\s+",
    rb"curl\s+",
    # SQL注入模式
    rb"union\s+select",
    rb"drop\s+table",
    rb"insert\s+into",
    rb"delete\s+from",
]


class FileValidationError(Exception):
    """文件验证异常"""

    pass


class FileValidator:
    """文件验证器"""

    def __init__(self, max_file_size: int = 10 * 1024 * 1024):  # 10MB
        """
        初始化文件验证器

        Args:
            max_file_size: 最大文件大小（字节）
        """
        self.max_file_size = max_file_size
        self.compiled_patterns = [
            re.compile(pattern, re.IGNORECASE) for pattern in MALICIOUS_PATTERNS
        ]

    def validate_file(
        self, file_data: bytes, filename: str, declared_mime_type: str = None
    ) -> Dict:
        """
        验证文件安全性

        Args:
            file_data: 文件二进制数据
            filename: 文件名
            declared_mime_type: 声明的MIME类型

        Returns:
            验证结果字典

        Raises:
            FileValidationError: 验证失败时抛出异常
        """
        result = {
            "valid": False,
            "file_type": None,
            "mime_type": None,
            "extension": None,
            "size": len(file_data),
            "warnings": [],
            "errors": [],
        }

        try:
            # 1. 基础检查
            self._validate_basic_properties(file_data, filename, result)

            # 2. 魔数验证
            detected_type = self._validate_magic_number(file_data, result)

            # 3. 文件名验证
            self._validate_filename(filename, result)

            # 4. MIME类型一致性检查
            if declared_mime_type:
                self._validate_mime_consistency(
                    declared_mime_type, detected_type, result
                )

            # 5. 恶意内容扫描
            self._scan_malicious_content(file_data, result)

            # 6. 最终验证结果
            result["valid"] = len(result["errors"]) == 0

            if result["valid"]:
                logger.info(f"文件验证通过: {filename} ({result['file_type']})")
            else:
                logger.warning(f"文件验证失败: {filename}, 错误: {result['errors']}")

        except Exception as e:
            logger.error(f"文件验证过程中出错: {e}")
            result["errors"].append(f"验证过程异常: {str(e)}")
            result["valid"] = False

        return result

    def _validate_basic_properties(self, file_data: bytes, filename: str, result: Dict):
        """验证基础属性"""
        # 检查文件大小
        if len(file_data) == 0:
            result["errors"].append("文件为空")
            return

        if len(file_data) > self.max_file_size:
            result["errors"].append(
                f"文件大小超过限制: {len(file_data)} > {self.max_file_size}"
            )

        # 检查文件名长度
        if len(filename) > 255:
            result["errors"].append("文件名过长")

        # 检查危险扩展名
        file_ext = Path(filename).suffix.lower()
        if file_ext in DANGEROUS_EXTENSIONS:
            result["errors"].append(f"危险的文件扩展名: {file_ext}")

    def _validate_magic_number(self, file_data: bytes, result: Dict) -> Optional[Dict]:
        """验证文件魔数"""
        detected_type = None

        # 检查所有已知的魔数
        for magic_bytes, type_info in IMAGE_MAGIC_NUMBERS.items():
            if file_data.startswith(magic_bytes):
                # 如果有额外检查，执行额外检查
                if "additional_check" in type_info:
                    if not type_info["additional_check"](file_data):
                        continue

                detected_type = type_info
                result["file_type"] = type_info["description"]
                result["mime_type"] = type_info["mime_type"]
                result["extension"] = type_info["extension"]
                break

        if not detected_type:
            result["errors"].append("无法识别的文件格式或不支持的文件类型")

        return detected_type

    def _validate_filename(self, filename: str, result: Dict):
        """验证文件名安全性"""
        # 检查路径遍历攻击
        if ".." in filename or "/" in filename or "\\" in filename:
            result["errors"].append("文件名包含非法字符")

        # 检查特殊字符
        dangerous_chars = ["<", ">", ":", '"', "|", "?", "*", "\0"]
        if any(char in filename for char in dangerous_chars):
            result["warnings"].append("文件名包含特殊字符")

        # 检查隐藏文件
        if filename.startswith("."):
            result["warnings"].append("隐藏文件")

    def _validate_mime_consistency(
        self, declared_mime: str, detected_type: Optional[Dict], result: Dict
    ):
        """验证MIME类型一致性"""
        if detected_type and declared_mime != detected_type["mime_type"]:
            result["warnings"].append(
                f"MIME类型不一致: 声明={declared_mime}, 检测={detected_type['mime_type']}"
            )

    def _scan_malicious_content(self, file_data: bytes, result: Dict):
        """扫描恶意内容"""
        # 只扫描文件的前64KB，避免性能问题
        scan_data = file_data[: 64 * 1024]

        for pattern in self.compiled_patterns:
            if pattern.search(scan_data):
                result["errors"].append(
                    f"检测到可疑内容模式: {pattern.pattern.decode('utf-8', errors='ignore')}"
                )


def validate_uploaded_file(
    file_data: bytes, filename: str, mime_type: str = None
) -> Dict:
    """
    便捷函数：验证上传的文件

    Args:
        file_data: 文件二进制数据
        filename: 文件名
        mime_type: MIME类型

    Returns:
        验证结果字典
    """
    validator = FileValidator()
    return validator.validate_file(file_data, filename, mime_type)


def is_safe_image_file(file_data: bytes, filename: str) -> bool:
    """
    便捷函数：检查是否为安全的图片文件

    Args:
        file_data: 文件二进制数据
        filename: 文件名

    Returns:
        是否为安全的图片文件
    """
    result = validate_uploaded_file(file_data, filename)
    return result["valid"] and len(result["errors"]) == 0
