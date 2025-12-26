#!/usr/bin/env python3
"""
文件验证模块

功能概述
--------
提供企业级文件上传安全验证，防止恶意文件上传和文件类型伪装攻击。

核心功能
--------
1. **魔数验证**: 基于文件头部字节序列验证真实文件类型
2. **文件类型检查**: 支持 PNG、JPEG、GIF、WebP、BMP、TIFF、ICO、SVG 等图片格式
3. **恶意内容扫描**: 检测 JavaScript、PHP、Shell、SQL 注入等恶意代码模式
4. **文件大小限制**: 可配置的文件大小上限（默认 10MB）
5. **文件名安全**: 检测路径遍历、特殊字符、隐藏文件等安全风险
6. **MIME 类型一致性**: 验证声明的 MIME 类型与实际检测结果是否一致

主要组件
--------
- IMAGE_MAGIC_NUMBERS: 图片格式魔数字典（支持 10+ 种格式）
- DANGEROUS_EXTENSIONS: 危险文件扩展名黑名单（可执行文件、脚本等）
- MALICIOUS_PATTERNS: 恶意内容正则模式列表（JavaScript、PHP、Shell 等）
- FileValidationError: 文件验证异常类
- FileValidator: 核心验证器类
- validate_uploaded_file: 便捷验证函数
- is_safe_image_file: 快速安全检查函数

验证流程
--------
1. 基础属性检查（文件大小、文件名长度、危险扩展名）
2. 魔数验证（识别真实文件类型）
3. 文件名安全检查（路径遍历、特殊字符）
4. MIME 类型一致性验证（可选）
5. 恶意内容扫描（前 64KB）
6. 汇总验证结果

安全特性
--------
- **魔数优先**: 不依赖文件扩展名或 MIME 声明，基于文件实际内容判断
- **深度扫描**: 检测嵌入在图片中的恶意代码
- **性能平衡**: 只扫描文件前 64KB，避免大文件性能问题
- **多层防护**: 文件名、类型、内容、大小多维度验证

使用场景
--------
- Web 应用文件上传
- 用户头像、图片上传
- 文件存储服务
- MCP 服务器文件接收

注意事项
--------
- 恶意内容扫描基于正则匹配，可能存在误判或漏判
- 魔数验证依赖文件头部，对损坏文件可能识别失败
- SVG 文件可能包含 JavaScript，建议额外处理
- 性能优化：只扫描前 64KB，超大文件末尾的恶意代码可能漏检

依赖
----
- logging: 日志记录
- re: 正则表达式（恶意内容扫描）
- pathlib: 文件路径处理
- typing: 类型注解
"""

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


# ============================================================================
# 常量定义：图片格式魔数字典
# ============================================================================
#
# IMAGE_MAGIC_NUMBERS: 图片文件格式魔数（文件头部特征字节）字典
#
# 数据结构
# --------
# {魔数字节序列: {配置信息}}
#   - extension: 文件扩展名
#   - mime_type: MIME 类型
#   - description: 格式描述
#   - additional_check: 可选的额外验证函数（如 WebP、SVG）
#
# 支持的格式
# ----------
# - PNG: 便携式网络图形（单一魔数）
# - JPEG: 联合图像专家组（5 种变体：JFIF、EXIF、Canon、Samsung、标准）
# - GIF: 图形交换格式（87a、89a 两种版本）
# - WebP: Google WebP 格式（需额外检查 "WEBP" 标识）
# - BMP: Windows 位图
# - TIFF: 标签图像文件格式（Little Endian、Big Endian）
# - ICO: Windows 图标
# - SVG: 可缩放矢量图形（XML 格式，需检查 <svg 标签）
#
# 设计原则
# --------
# - 魔数优先：不依赖文件扩展名，基于文件实际内容识别
# - 多变体支持：JPEG 支持多种相机厂商的变体
# - 额外验证：WebP 和 SVG 需要二次验证确保准确性
#
# 注意事项
# --------
# - 魔数匹配使用 bytes.startswith()，只检查文件头部
# - additional_check 是可选的 lambda 函数，接收文件数据
# - SVG 检查前 1024 字节是否包含 <svg 标签
# - WebP 检查偏移 8-12 字节是否为 "WEBP"
#
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

# ============================================================================
# 常量定义：危险文件扩展名黑名单
# ============================================================================
#
# DANGEROUS_EXTENSIONS: 危险文件扩展名集合（禁止上传的文件类型）
#
# 覆盖的文件类型
# --------------
# 1. **Windows 可执行文件**: .exe, .bat, .cmd, .com, .scr, .pif, .msi
# 2. **系统文件**: .dll, .sys, .drv, .ocx, .cpl, .inf, .reg
# 3. **脚本文件**: .vbs, .js, .ps1, .sh, .bash, .zsh, .fish
# 4. **编程语言**: .py, .pl, .rb, .php, .asp, .jsp
# 5. **打包文件**: .jar, .war, .ear, .deb, .rpm, .dmg, .pkg, .app
#
# 设计目的
# --------
# 防止上传可执行文件和脚本，避免服务器端执行恶意代码。
#
# 注意事项
# --------
# - 黑名单策略：只拦截已知危险类型，未知类型可能漏检
# - 扩展名不区分大小写（使用 .lower() 处理）
# - 可根据实际需求扩展此列表
# - 建议配合魔数验证，防止扩展名伪装
#
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

# ============================================================================
# 常量定义：恶意内容正则模式列表
# ============================================================================
#
# MALICIOUS_PATTERNS: 恶意代码特征模式列表（用于内容扫描）
#
# 检测的恶意代码类型
# ------------------
# 1. **JavaScript 代码**: <script>, javascript:, eval(), document.write, window.location
# 2. **PHP 代码**: <?php, <?=, eval(), system(), exec()
# 3. **Shell 命令**: #!/bin/, rm -rf, wget, curl
# 4. **SQL 注入**: union select, drop table, insert into, delete from
#
# 使用方式
# --------
# 这些模式会被编译为正则表达式（re.IGNORECASE），用于扫描文件内容。
#
# 检测机制
# --------
# - 扫描文件前 64KB 内容
# - 不区分大小写匹配
# - 发现任意一个模式即标记为可疑
#
# 局限性
# ------
# - **误报**: 正常的注释或文档可能包含这些关键词
# - **漏报**: 混淆、编码、拆分的恶意代码可能绕过检测
# - **性能**: 正则匹配对大文件可能有性能影响（已限制 64KB）
#
# 扩展建议
# --------
# - 根据实际攻击案例添加新模式
# - 考虑使用专业的恶意代码扫描引擎（如 ClamAV）
# - 对 SVG 文件进行额外的 JavaScript 检测
#
# 注意事项
# --------
# - 这是简化版检测，不能替代专业的安全扫描工具
# - 建议结合其他安全措施（文件隔离、沙箱执行等）
#
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
    """
    文件验证异常

    异常类型
    --------
    当文件验证失败时抛出此异常，表示文件不符合安全要求。

    使用场景
    --------
    - 文件格式无法识别
    - 文件大小超过限制
    - 检测到恶意内容
    - 文件名包含非法字符

    继承
    ----
    继承自 Exception，可被 try-except 捕获。

    注意
    ----
    - 异常消息应包含具体的失败原因
    - 调用方应记录异常信息用于审计
    """

    pass


class FileValidator:
    """
    文件验证器

    功能概述
    --------
    提供全面的文件上传安全验证，包括魔数验证、恶意内容扫描、文件名检查等。

    核心职责
    --------
    1. 基础属性验证（大小、文件名长度、危险扩展名）
    2. 魔数验证（识别真实文件类型）
    3. 文件名安全检查（路径遍历、特殊字符）
    4. MIME 类型一致性检查（可选）
    5. 恶意内容扫描（正则模式匹配）

    配置参数
    --------
    - max_file_size: 最大文件大小（字节），默认 10MB
    - compiled_patterns: 预编译的恶意内容正则模式列表

    验证结果
    --------
    返回字典包含：
    - valid: 是否通过验证
    - file_type: 检测到的文件类型描述
    - mime_type: MIME 类型
    - extension: 推荐扩展名
    - size: 文件大小
    - warnings: 警告列表
    - errors: 错误列表

    设计原则
    --------
    - **安全优先**: 多层验证，宁可误杀不可放过
    - **性能平衡**: 只扫描前 64KB，避免大文件性能问题
    - **可扩展**: 易于添加新的验证规则和文件格式

    使用场景
    --------
    - Web 应用文件上传
    - API 文件接收端点
    - 文件存储服务

    线程安全
    --------
    每个验证操作是独立的，不共享状态，可在多线程环境使用。

    注意事项
    --------
    - 验证失败不会抛出异常，而是返回包含错误信息的字典
    - 警告不影响验证结果，但应引起注意
    - 预编译的正则模式在初始化时生成，提高性能
    """

    # 【优化】类级别常量：危险字符集合（所有实例共享）
    _DANGEROUS_CHARS = frozenset(["<", ">", ":", '"', "|", "?", "*", "\0"])

    def __init__(self, max_file_size: int = 10 * 1024 * 1024):  # 10MB
        """
        初始化文件验证器

        参数
        ----
        max_file_size : int, optional
            最大文件大小（字节），默认 10MB（10 * 1024 * 1024）

        初始化流程
        ----------
        1. 验证max_file_size参数（必须为正数）
        2. 设置最大文件大小限制
        3. 预编译所有恶意内容正则模式（提高后续扫描性能）
        4. 【优化】预先 decode 正则 pattern 字符串（避免重复 decode）

        预编译优化
        ----------
        在初始化时预编译正则表达式，避免每次验证都重新编译，提高性能。
        使用 re.IGNORECASE 标志，实现不区分大小写的匹配。
        同时预先 decode pattern 字符串，避免在错误报告时重复 decode。

        异常
        ----
        ValueError
            如果 max_file_size <= 0
        """
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
        """
        验证文件安全性（核心方法）

        参数
        ----
        file_data : bytes
            文件二进制数据
        filename : str
            文件名（用于扩展名检查和日志）
        declared_mime_type : str, optional
            客户端声明的 MIME 类型（用于一致性检查）

        返回
        ----
        Dict
            验证结果字典，包含以下字段：
            - valid: 是否通过验证（bool）
            - file_type: 检测到的文件类型描述（str）
            - mime_type: MIME 类型（str）
            - extension: 推荐扩展名（str）
            - size: 文件大小（int）
            - warnings: 警告列表（List[str]）
            - errors: 错误列表（List[str]）

        验证流程
        --------
        1. 基础属性检查（文件大小、文件名长度、危险扩展名）
        2. 魔数验证（识别真实文件类型）
        3. 文件名安全检查（路径遍历、特殊字符）
        4. MIME 类型一致性检查（如果提供了 declared_mime_type）
        5. 恶意内容扫描（前 64KB）
        6. 汇总验证结果

        验证结果判定
        ------------
        - valid = True: errors 列表为空
        - valid = False: errors 列表包含至少一个错误
        - warnings 不影响 valid 的值，但应引起注意

        异常处理
        --------
        捕获所有验证过程中的异常，记录到 errors 列表，不会向外抛出异常。

        日志记录
        --------
        - 验证通过: logger.info()
        - 验证失败: logger.warning()
        - 验证异常: logger.error()

        性能
        ----
        - 时间复杂度: O(n)，n 为文件大小（恶意内容扫描）
        - 空间复杂度: O(1)，不复制文件数据
        - 优化: 恶意内容扫描限制为前 64KB

        线程安全
        --------
        每次调用创建独立的 result 字典，无共享状态，线程安全。

        注意事项
        --------
        - 不会抛出 FileValidationError 异常（保留向后兼容）
        - 所有错误都记录在返回字典的 errors 字段
        - 验证失败不会中断流程，会执行所有检查
        - 添加输入参数验证（filename、file_data非空）
        """
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
        """
        验证基础属性

        参数
        ----
        file_data : bytes
            文件二进制数据
        filename : str
            文件名
        result : Dict
            验证结果字典（直接修改，添加 errors）

        检查项
        ------
        1. **文件大小**: 空文件或超过 max_file_size 限制
        2. **文件名长度**: 超过 255 字符（文件系统限制）
        3. **危险扩展名**: 检查是否在 DANGEROUS_EXTENSIONS 黑名单中

        副作用
        ------
        直接修改 result 字典，添加错误信息到 errors 列表。

        性能
        ----
        - 【优化】使用 rsplit('.', 1) 提取扩展名，避免创建 Path 对象

        注意事项
        --------
        - 空文件检查不再提前return，继续执行后续检查
        - 扩展名不区分大小写（使用 .lower()）
        """
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
        """
        验证文件魔数（识别真实文件类型）

        参数
        ----
        file_data : bytes
            文件二进制数据
        result : Dict
            验证结果字典（直接修改，添加 file_type、mime_type、extension、errors）

        返回
        ----
        Optional[Dict]
            检测到的文件类型信息字典，如果无法识别则返回 None

        验证流程
        --------
        1. 【优化】快速路径：优先检查最常见的格式（PNG、JPEG）
        2. 遍历 IMAGE_MAGIC_NUMBERS 字典
        3. 使用 bytes.startswith() 检查文件头部是否匹配魔数
        4. 如果有 additional_check，执行额外验证（如 WebP、SVG）
        5. 匹配成功则更新 result 字典并返回类型信息
        6. 无匹配则添加错误到 result["errors"]

        额外检查
        --------
        - WebP: 检查偏移 8-12 字节是否为 "WEBP"
        - SVG: 检查前 1024 字节是否包含 "<svg" 标签

        副作用
        ------
        直接修改 result 字典，填充 file_type、mime_type、extension 字段。

        性能
        ----
        - 【优化】快速路径：PNG（1次检查）、JPEG（1次检查前3字节）
        - 【优化】JPEG 5个变体合并为1次检查（前3字节 \xff\xd8\xff）
        - 【优化】减少大约 50% 的魔数检查次数（对常见格式）

        注意事项
        --------
        - 魔数匹配优先于文件扩展名
        - 第一个匹配的魔数生效（顺序敏感）
        - 无法识别的文件类型会添加错误，但不会中断验证流程
        """
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
        """
        验证文件名安全性

        参数
        ----
        filename : str
            文件名
        result : Dict
            验证结果字典（直接修改，添加 errors 和 warnings）

        检查项
        ------
        1. **路径遍历攻击**: 检测 "..", "/", "\\" 等路径分隔符
        2. **特殊字符**: 检测 <, >, :, ", |, ?, *, \0 等危险字符
        3. **隐藏文件**: 检测以 "." 开头的文件名
        4. 空文件名检查

        错误 vs 警告
        ------------
        - 错误: 路径遍历攻击、空文件名（严重安全风险）
        - 警告: 特殊字符、隐藏文件（潜在风险）

        副作用
        ------
        直接修改 result 字典，添加错误或警告信息。

        性能
        ----
        - 【优化】使用类级别 frozenset _DANGEROUS_CHARS（O(1) 查找）
        - 【优化】反转循环顺序（遍历 filename，检查集合）

        注意事项
        --------
        - 路径遍历检查是防止访问服务器任意文件的关键
        - 特殊字符可能导致文件系统或命令注入问题
        - 隐藏文件可能被用于隐藏恶意内容
        - 增强路径遍历检查，包括空文件名和只包含点的文件名
        """
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
        """
        验证 MIME 类型一致性

        参数
        ----
        declared_mime : str
            客户端声明的 MIME 类型
        detected_type : Optional[Dict]
            魔数验证检测到的文件类型信息
        result : Dict
            验证结果字典（直接修改，添加 warnings）

        检查逻辑
        --------
        如果 detected_type 不为 None（成功识别文件类型），且声明的 MIME 类型
        与检测到的 MIME 类型不一致，则添加警告。

        副作用
        ------
        直接修改 result 字典，添加警告信息到 warnings 列表。

        注意事项
        --------
        - 不一致性添加警告而非错误，因为某些场景下声明的 MIME 可能更准确
        - 如果无法检测文件类型（detected_type 为 None），则跳过检查
        - MIME 类型不匹配可能表示客户端伪装或配置错误
        - 处理MIME类型参数（如charset），只比较主类型
        """
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
        """
        扫描恶意内容

        参数
        ----
        file_data : bytes
            文件二进制数据
        result : Dict
            验证结果字典（直接修改，添加 errors）

        扫描范围
        --------
        只扫描文件的前 64KB，避免大文件性能问题。

        检测机制
        --------
        使用预编译的正则模式列表（self.compiled_patterns）检测恶意代码特征：
        - JavaScript 代码（<script>, eval, document.write）
        - PHP 代码（<?php, system, exec）
        - Shell 命令（#!/bin/, rm -rf, wget）
        - SQL 注入（union select, drop table）

        副作用
        ------
        直接修改 result 字典，添加错误信息到 errors 列表。

        性能
        ----
        - 时间复杂度: O(m * n)，m 为模式数量，n 为扫描数据长度（最多 64KB）
        - 【优化】使用预编译正则表达式，减少编译开销
        - 【优化】使用预先 decoded 的 pattern 字符串，避免重复 decode
        - 报告所有匹配的模式（更安全），不短路

        注意事项
        --------
        - 只扫描前 64KB，超大文件末尾的恶意代码可能漏检
        - 基于正则匹配，可能存在误报和漏报
        - 混淆、编码、拆分的恶意代码可能绕过检测
        - 建议结合专业的恶意代码扫描工具（如 ClamAV）
        - 报告所有匹配的恶意模式，不短路（避免漏检）
        """
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
    """
    便捷函数：验证上传的文件

    参数
    ----
    file_data : bytes
        文件二进制数据
    filename : str
        文件名
    mime_type : str, optional
        客户端声明的 MIME 类型

    返回
    ----
    Dict
        验证结果字典，包含以下字段：
        - valid: 是否通过验证（bool）
        - file_type: 检测到的文件类型描述（str）
        - mime_type: MIME 类型（str）
        - extension: 推荐扩展名（str）
        - size: 文件大小（int）
        - warnings: 警告列表（List[str]）
        - errors: 错误列表（List[str]）

    功能
    ----
    使用模块级单例 _default_validator 实例（10MB 限制）并执行验证。

    使用场景
    --------
    - 快速验证单个文件
    - 不需要自定义配置时使用
    - API 端点中的简单验证

    性能
    ----
    - 【优化】使用模块级单例实例，避免重复创建和正则编译
    - 【优化】所有调用共享预编译的正则模式，大幅提升性能

    注意事项
    --------
    - 【修改】使用模块级单例 _default_validator（线程安全）
    - 使用默认的 10MB 文件大小限制
    - 如需自定义配置，请直接使用 FileValidator 类
    """
    return _default_validator.validate_file(file_data, filename, mime_type)


def is_safe_image_file(file_data: bytes, filename: str) -> bool:
    """
    便捷函数：检查是否为安全的图片文件

    参数
    ----
    file_data : bytes
        文件二进制数据
    filename : str
        文件名

    返回
    ----
    bool
        True: 文件通过所有验证且无错误
        False: 文件验证失败或存在错误

    功能
    ----
    调用 validate_uploaded_file() 并简化返回结果为布尔值。

    判断逻辑
    --------
    同时满足以下条件返回 True：
    - valid 为 True
    - errors 列表为空

    使用场景
    --------
    - 快速布尔判断（不需要详细错误信息）
    - 条件分支判断
    - 简单的上传前检查

    注意事项
    --------
    - 只返回布尔值，不提供具体错误信息
    - 警告不影响返回结果（只检查 errors）
    - 如需详细信息，请使用 validate_uploaded_file()
    """
    result = validate_uploaded_file(file_data, filename)
    return result["valid"] and len(result["errors"]) == 0
