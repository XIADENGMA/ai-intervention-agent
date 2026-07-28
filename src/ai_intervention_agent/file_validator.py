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


IMAGE_MAGIC_NUMBERS: dict[bytes, ImageTypeInfo] = {
    b"\x89\x50\x4e\x47\x0d\x0a\x1a\x0a": {
        "extension": ".png",
        "mime_type": "image/png",
        "description": "PNG图片",
    },
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
    b"\x52\x49\x46\x46": {
        "extension": ".webp",
        "mime_type": "image/webp",
        "description": "WebP图片",
        "additional_check": lambda data: data[8:12] == b"WEBP",
    },
    b"\x42\x4d": {
        "extension": ".bmp",
        "mime_type": "image/bmp",
        "description": "BMP图片",
    },
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
    b"\x00\x00\x01\x00": {
        "extension": ".ico",
        "mime_type": "image/x-icon",
        "description": "ICO图标",
    },
}


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
    ".svg",
    ".htm",
    ".html",
    ".xhtml",
}


MALICIOUS_PATTERNS = [
    rb"<script[^>]*>",
    rb"javascript:",
    rb"eval\s*\(",
    rb"document\.write",
    rb"window\.location",
    rb"<\?php",
    rb"<\?=",
    rb"system\s*\(",
    rb"exec\s*\(",
    rb"#!/bin/",
    rb"rm\s+-rf",
    rb"wget\s+",
    rb"curl\s+",
    rb"union\s+select",
    rb"drop\s+table",
    rb"insert\s+into",
    rb"delete\s+from",
]


class FileValidator:
    """文件验证器 - 魔数验证、恶意内容扫描、文件名安全检查。"""

    _DANGEROUS_CHARS = frozenset(["<", ">", ":", '"', "|", "?", "*"])

    def __init__(self, max_file_size: int = 10 * 1024 * 1024):
        """初始化并预编译恶意内容正则"""

        if max_file_size <= 0:
            raise ValueError(f"max_file_size 必须为正数，当前值: {max_file_size}")

        self.max_file_size = max_file_size

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
            self._validate_basic_properties(file_data, filename, result)

            detected_type = self._validate_magic_number(file_data, result)

            self._validate_filename(filename, result)

            if declared_mime_type:
                self._validate_mime_consistency(
                    declared_mime_type, detected_type, result
                )

            self._scan_malicious_content(file_data, result)

            result["valid"] = len(result["errors"]) == 0

            if result["valid"]:
                logger.debug(f"文件验证通过: {filename} ({result['file_type']})")
            else:
                logger.warning(f"文件验证失败: {filename}, 错误: {result['errors']}")

        except Exception as e:
            logger.error(f"文件验证过程中出错: {e}", exc_info=True)
            result["errors"].append(f"验证过程异常: {e!s}")
            result["valid"] = False

        return result

    def _validate_basic_properties(
        self, file_data: bytes, filename: str, result: FileValidationResult
    ) -> None:
        """检查文件大小、文件名长度、危险扩展名"""

        if len(file_data) == 0:
            result["errors"].append("文件为空")

        if len(file_data) > self.max_file_size:
            result["errors"].append(
                f"文件大小超过限制: {len(file_data)} > {self.max_file_size}"
            )

        if len(filename) > 255:
            result["errors"].append("文件名过长")

        parts = filename.rsplit(".", 1)
        file_ext = ("." + parts[1]).lower() if len(parts) > 1 else ""

        if file_ext and file_ext in DANGEROUS_EXTENSIONS:
            result["errors"].append(f"危险的文件扩展名: {file_ext}")

    def _validate_magic_number(
        self, file_data: bytes, result: FileValidationResult
    ) -> ImageTypeInfo | None:
        """通过魔数识别真实文件类型（PNG/JPEG 快速路径优化）"""
        detected_type: ImageTypeInfo | None = None

        if file_data.startswith(b"\x89\x50\x4e\x47\x0d\x0a\x1a\x0a"):
            detected_type = cast(
                ImageTypeInfo,
                {
                    "extension": ".png",
                    "mime_type": "image/png",
                    "description": "PNG图片",
                },
            )

        elif file_data.startswith(b"\xff\xd8\xff"):
            detected_type = cast(
                ImageTypeInfo,
                {
                    "extension": ".jpg",
                    "mime_type": "image/jpeg",
                    "description": "JPEG图片",
                },
            )

        if detected_type:
            result["file_type"] = detected_type["description"]
            result["mime_type"] = detected_type["mime_type"]
            result["extension"] = detected_type["extension"]
            return detected_type

        _SKIP_MAGIC_BYTES = {
            b"\x89\x50\x4e\x47\x0d\x0a\x1a\x0a",
            b"\xff\xd8\xff\xe0",
            b"\xff\xd8\xff\xe1",
            b"\xff\xd8\xff\xe2",
            b"\xff\xd8\xff\xe3",
            b"\xff\xd8\xff\xdb",
        }

        for magic_bytes, type_info in IMAGE_MAGIC_NUMBERS.items():
            if magic_bytes in _SKIP_MAGIC_BYTES:
                continue

            if file_data.startswith(magic_bytes):
                if "additional_check" in type_info:
                    try:
                        if not type_info["additional_check"](file_data):
                            continue
                    except Exception as e:
                        logger.warning(
                            f"额外检查失败: {type_info.get('description', 'Unknown')} - {e}",
                            exc_info=True,
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

        stripped_name = filename.strip()
        if not stripped_name or stripped_name == "." or stripped_name == "..":
            result["errors"].append("文件名无效（空或只包含点）")

        if "\x00" in filename:
            result["errors"].append("文件名包含 NUL 字节（path-truncation 攻击向量）")

        if ".." in filename or "/" in filename or "\\" in filename:
            result["errors"].append("文件名包含非法字符")

        if any(char in self._DANGEROUS_CHARS for char in filename):
            result["warnings"].append("文件名包含特殊字符")

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

        declared_main_type = declared_mime.split(";")[0].strip().lower()
        detected_main_type = detected_type["mime_type"].lower()

        if declared_main_type != detected_main_type:
            result["warnings"].append(
                f"MIME类型不一致: 声明={declared_mime}, 检测={detected_type['mime_type']}"
            )

    def _scan_malicious_content(
        self, file_data: bytes, result: FileValidationResult
    ) -> None:
        """扫描恶意代码特征（头/尾/中间采样窗口）。"""
        window_size = 64 * 1024
        size = len(file_data)

        scan_windows: list[bytes] = []
        if size <= window_size:
            scan_windows.append(file_data)
        else:
            scan_windows.append(file_data[:window_size])
            scan_windows.append(file_data[-window_size:])
            if size > window_size * 2:
                mid = size // 2
                start = max(0, mid - window_size // 2)
                scan_windows.append(file_data[start : start + window_size])

        for compiled, pattern_str in self.compiled_patterns:
            for chunk in scan_windows:
                if compiled.search(chunk):
                    result["errors"].append(f"检测到可疑内容模式: {pattern_str}")
                    break


_default_validator = FileValidator()


def validate_uploaded_file(
    file_data: bytes | None, filename: str, mime_type: str | None = None
) -> FileValidationResult:
    """便捷函数：使用默认单例验证文件"""
    return _default_validator.validate_file(file_data, filename, mime_type)


def is_safe_image_file(file_data: bytes, filename: str) -> bool:
    """便捷函数：返回文件是否通过验证"""
    return validate_uploaded_file(file_data, filename)["valid"]
