#!/usr/bin/env python3
"""文件验证模块 - 魔数验证、恶意内容扫描、文件名安全检查，防止上传攻击。"""

import logging
import re
from collections.abc import Callable
from typing import TypedDict, cast

logger = logging.getLogger(__name__)


class ImageTypeInfo(TypedDict, total=False):
    """图片类型信息（用于魔数识别）"""

    extension: str
    mime_type: str
    description: str
    additional_check: Callable[[bytes], bool]


class FileValidationResult(TypedDict):
    """文件验证结果结构（用于类型检查与 IDE 提示）"""

    valid: bool
    file_type: str | None
    mime_type: str | None
    extension: str | None
    size: int
    warnings: list[str]
    errors: list[str]


# 图片格式魔数字典：{魔数字节: {extension, mime_type, description, additional_check?}}
IMAGE_MAGIC_NUMBERS: dict[bytes, ImageTypeInfo] = {
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

# 危险文件扩展名黑名单：可执行文件、脚本、打包文件
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

# 恶意内容正则模式：JavaScript/PHP/Shell/SQL 注入特征
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
    """文件验证器 - 魔数验证、恶意内容扫描、文件名安全检查。"""

    # 【优化】类级别常量：危险字符集合（所有实例共享）
    _DANGEROUS_CHARS = frozenset(["<", ">", ":", '"', "|", "?", "*", "\0"])

    def __init__(self, max_file_size: int = 10 * 1024 * 1024):  # 10MB
        """初始化并预编译恶意内容正则"""
        # 验证max_file_size参数
        if max_file_size <= 0:
            raise ValueError(f"max_file_size 必须为正数，当前值: {max_file_size}")

        self.max_file_size = max_file_size
        # 【优化】预编译正则并缓存 decoded pattern 字符串
        self.compiled_patterns = []
        for pattern in MALICIOUS_PATTERNS:
            compiled = re.compile(pattern, re.IGNORECASE)
            pattern_str = pattern.decode("utf-8", errors="ignore")
            self.compiled_patterns.append((compiled, pattern_str))

    def validate_file(
        self,
        file_data: bytes | None,
        filename: str,
        declared_mime_type: str | None = None,
    ) -> FileValidationResult:
        """验证文件安全性，返回 {valid, file_type, mime_type, extension, size, warnings, errors}"""
        # 验证输入参数
        if not filename or not filename.strip():
            return {
                "valid": False,
                "file_type": None,
                "mime_type": None,
                "extension": None,
                "size": 0,
                "warnings": [],
                "errors": ["文件名为空"],
            }

        if file_data is None:
            return {
                "valid": False,
                "file_type": None,
                "mime_type": None,
                "extension": None,
                "size": 0,
                "warnings": [],
                "errors": ["文件数据为空（None）"],
            }

        result: FileValidationResult = {
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

    def _validate_basic_properties(
        self, file_data: bytes, filename: str, result: FileValidationResult
    ) -> None:
        """检查文件大小、文件名长度、危险扩展名"""
        # 检查文件大小
        if len(file_data) == 0:
            result["errors"].append("文件为空")
            # 不再提前return，继续检查文件名安全性

        if len(file_data) > self.max_file_size:
            result["errors"].append(
                f"文件大小超过限制: {len(file_data)} > {self.max_file_size}"
            )

        # 检查文件名长度
        if len(filename) > 255:
            result["errors"].append("文件名过长")

        # 【优化】使用 rsplit 代替 Path，避免创建对象
        # 原逻辑：Path(filename).suffix.lower()
        # 优化后：提取 '.' 后的扩展名，保留 '.' 前缀
        parts = filename.rsplit(".", 1)
        file_ext = ("." + parts[1]).lower() if len(parts) > 1 else ""

        # 检查危险扩展名
        if file_ext and file_ext in DANGEROUS_EXTENSIONS:
            result["errors"].append(f"危险的文件扩展名: {file_ext}")

    def _validate_magic_number(
        self, file_data: bytes, result: FileValidationResult
    ) -> ImageTypeInfo | None:
        """通过魔数识别真实文件类型（PNG/JPEG 快速路径优化）"""
        detected_type: ImageTypeInfo | None = None

        # 【优化】快速路径：优先检查最常见的格式（PNG、JPEG）
        # PNG 魔数检查（约占 40% 图片上传）
        if file_data.startswith(b"\x89\x50\x4e\x47\x0d\x0a\x1a\x0a"):
            detected_type = cast(
                ImageTypeInfo,
                {
                    "extension": ".png",
                    "mime_type": "image/png",
                    "description": "PNG图片",
                },
            )

        # JPEG 魔数检查（约占 50% 图片上传）
        # 所有 JPEG 变体的前 3 字节都是 \xff\xd8\xff
        elif file_data.startswith(b"\xff\xd8\xff"):
            detected_type = cast(
                ImageTypeInfo,
                {
                    "extension": ".jpg",
                    "mime_type": "image/jpeg",
                    "description": "JPEG图片",
                },
            )

        # 快速路径命中，直接返回
        if detected_type:
            result["file_type"] = detected_type["description"]
            result["mime_type"] = detected_type["mime_type"]
            result["extension"] = detected_type["extension"]
            return detected_type

        # 【优化】慢速路径：跳过已在快速路径检查的 PNG 和 JPEG 格式
        # PNG 魔数：\x89\x50\x4e\x47\x0d\x0a\x1a\x0a
        # JPEG 魔数（5个变体）：\xff\xd8\xff\xe0, \xff\xd8\xff\xe1, \xff\xd8\xff\xe2,
        #                        \xff\xd8\xff\xe3, \xff\xd8\xff\xdb
        _SKIP_MAGIC_BYTES = {
            b"\x89\x50\x4e\x47\x0d\x0a\x1a\x0a",  # PNG
            b"\xff\xd8\xff\xe0",  # JPEG JFIF
            b"\xff\xd8\xff\xe1",  # JPEG EXIF
            b"\xff\xd8\xff\xe2",  # JPEG Canon
            b"\xff\xd8\xff\xe3",  # JPEG Samsung
            b"\xff\xd8\xff\xdb",  # JPEG 标准
        }

        # 慢速路径：检查其他所有格式（跳过快速路径已检查的）
        for magic_bytes, type_info in IMAGE_MAGIC_NUMBERS.items():
            # 【优化】跳过快速路径已检查的格式
            if magic_bytes in _SKIP_MAGIC_BYTES:
                continue

            if file_data.startswith(magic_bytes):
                # 额外检查添加错误处理
                if "additional_check" in type_info:
                    try:
                        if not type_info["additional_check"](file_data):
                            continue
                    except Exception as e:
                        logger.warning(
                            f"额外检查失败: {type_info.get('description', 'Unknown')} - {e}"
                        )
                        continue

                detected_type = type_info
                result["file_type"] = type_info["description"]
                result["mime_type"] = type_info["mime_type"]
                result["extension"] = type_info["extension"]
                break

        if not detected_type:
            result["errors"].append("无法识别的文件格式或不支持的文件类型")

        return detected_type

    def _validate_filename(self, filename: str, result: FileValidationResult) -> None:
        """检查路径遍历、特殊字符、隐藏文件"""
        # 检查空文件名或只包含空格/点的文件名
        stripped_name = filename.strip()
        if not stripped_name or stripped_name == "." or stripped_name == "..":
            result["errors"].append("文件名无效（空或只包含点）")

        # 检查路径遍历攻击
        if ".." in filename or "/" in filename or "\\" in filename:
            result["errors"].append("文件名包含非法字符")

        # 【优化】使用类级别 frozenset 和反转循环顺序
        # 原逻辑：any(char in filename for char in dangerous_chars) O(n * m)
        # 优化后：any(char in _DANGEROUS_CHARS for char in filename) O(n)
        if any(char in self._DANGEROUS_CHARS for char in filename):
            result["warnings"].append("文件名包含特殊字符")

        # 检查隐藏文件
        if filename.startswith("."):
            result["warnings"].append("隐藏文件")

    def _validate_mime_consistency(
        self,
        declared_mime: str,
        detected_type: ImageTypeInfo | None,
        result: FileValidationResult,
    ):
        """检查声明的 MIME 类型与检测结果是否一致"""
        if not detected_type:
            return

        # 提取MIME类型的主类型（忽略参数部分）
        # 例如："image/png; charset=utf-8" → "image/png"
        declared_main_type = declared_mime.split(";")[0].strip().lower()
        detected_main_type = detected_type["mime_type"].lower()

        if declared_main_type != detected_main_type:
            result["warnings"].append(
                f"MIME类型不一致: 声明={declared_mime}, 检测={detected_type['mime_type']}"
            )

    def _scan_malicious_content(
        self, file_data: bytes, result: FileValidationResult
    ) -> None:
        """扫描前 64KB 检测恶意代码特征"""
        # 只扫描文件的前64KB，避免性能问题
        scan_data = file_data[: 64 * 1024]

        # 遍历所有模式，报告所有匹配
        for compiled, pattern_str in self.compiled_patterns:
            if compiled.search(scan_data):
                # 【优化】使用预先 decoded 的 pattern_str，避免重复 decode
                result["errors"].append(f"检测到可疑内容模式: {pattern_str}")
                # 不短路，继续检查其他模式


# 【优化】模块级单例：预创建默认 FileValidator 实例，避免重复初始化
# 所有 validate_uploaded_file() 调用共享此实例，避免重复编译正则表达式
_default_validator = FileValidator()


def validate_uploaded_file(
    file_data: bytes | None, filename: str, mime_type: str | None = None
) -> FileValidationResult:
    """便捷函数：使用默认单例验证文件"""
    return _default_validator.validate_file(file_data, filename, mime_type)


def is_safe_image_file(file_data: bytes, filename: str) -> bool:
    """便捷函数：返回文件是否通过验证"""
    result = validate_uploaded_file(file_data, filename)
    return result["valid"] and len(result["errors"]) == 0
