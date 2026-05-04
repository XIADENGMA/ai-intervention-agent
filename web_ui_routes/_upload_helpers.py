"""上传文件处理工具 — 从 Flask request 提取已验证的图片列表。

供 task.py 和 feedback.py 中的提交端点共用，消除图片处理逻辑重复。

服务端深度防御限额（与 ``static/js/image-upload.js`` 的客户端阈值
对齐）：

- ``MAX_IMAGES_PER_REQUEST = 10`` —— 单次请求最多接受的 ``image_*``
  字段数量。客户端 (``MAX_IMAGE_COUNT``) 同值；本常量是"客户端被
  人为绕过 / 直接 curl 调 API"时的最后一道闸。

- ``MAX_TOTAL_UPLOAD_BYTES = 100 * 1024 * 1024`` —— 单次请求所有图片
  累计字节上限（10 张 × 10 MB），与 ``file_validator`` 的
  ``max_file_size = 10MB`` 单文件限额相乘后的合理上限。任何累计超
  限的请求都会被丢弃后续文件，已通过验证的前几张仍正常返回（避免
  全有或全无导致客户端体验突然中断；前端通过 toast 提示用户重试）。

为什么不依赖 ``app.config["MAX_CONTENT_LENGTH"]``：那是 Flask 在
multipart 解析前就 reject 整个请求的开关，对 form-only 请求（无
图片，仅文字）会一并影响。这里在文件读取阶段做累计统计更精准。
"""

from __future__ import annotations

import base64
import hashlib
import uuid
from pathlib import Path
from typing import Any

from flask import Request

from enhanced_logging import EnhancedLogger
from file_validator import validate_uploaded_file

logger = EnhancedLogger(__name__)

MAX_IMAGES_PER_REQUEST: int = 10
MAX_TOTAL_UPLOAD_BYTES: int = 100 * 1024 * 1024  # 10 张 × 10 MB


def extract_uploaded_images(
    request: Request, *, include_metadata: bool = False
) -> list[dict[str, Any]]:
    """从 Flask request.files 中提取所有 image_* 文件，返回验证通过的图片列表。

    参数:
        request: Flask 请求对象
        include_metadata: 是否包含额外元数据（safe_filename, file_hash, validation_warnings）

    返回:
        已验证的图片字典列表，每个包含 filename, data(base64), content_type, size

    限额行为：
        - 累计验证通过的图片数到达 ``MAX_IMAGES_PER_REQUEST`` 时，
          后续 ``image_*`` 字段会被跳过并 WARNING 一次（按字段名）。
        - 累计原始字节数到达 ``MAX_TOTAL_UPLOAD_BYTES`` 时同样跳过
          剩余字段（已读入内存的当前文件不会被丢弃，避免拼一半的
          状态机；下一个字段一开始就拒）。
    """
    images: list[dict[str, Any]] = []
    total_bytes = 0
    cap_logged_count = False
    cap_logged_bytes = False
    for key in request.files:
        if not key.startswith("image_"):
            continue

        if len(images) >= MAX_IMAGES_PER_REQUEST:
            if not cap_logged_count:
                logger.warning(
                    f"达到单次请求图片数量上限 ({MAX_IMAGES_PER_REQUEST})，"
                    "已丢弃后续 image_* 字段（深度防御，与客户端 MAX_IMAGE_COUNT 对齐）"
                )
                cap_logged_count = True
            continue
        if total_bytes >= MAX_TOTAL_UPLOAD_BYTES:
            if not cap_logged_bytes:
                logger.warning(
                    f"达到单次请求累计字节上限 "
                    f"({MAX_TOTAL_UPLOAD_BYTES // (1024 * 1024)} MB)，"
                    "已丢弃后续 image_* 字段（深度防御）"
                )
                cap_logged_bytes = True
            continue

        file = request.files[key]
        if not file or not file.filename:
            continue
        try:
            file_content = file.read()
            validation_result = validate_uploaded_file(
                file_content, file.filename, file.content_type
            )
            if not validation_result["valid"]:
                logger.warning(
                    f"文件验证失败: {file.filename} - {'; '.join(validation_result['errors'])}"
                )
                continue

            if validation_result.get("warnings"):
                logger.info(
                    f"文件验证警告: {file.filename} - {'; '.join(validation_result['warnings'])}"
                )

            original_filename = Path(file.filename.replace("\\", "/")).name
            base64_data = base64.b64encode(file_content).decode("utf-8")
            mime = validation_result["mime_type"] or file.content_type or "image/jpeg"

            entry: dict[str, Any] = {
                "filename": original_filename,
                "data": base64_data,
                "content_type": mime,
                "size": len(file_content),
            }

            if include_metadata:
                entry["safe_filename"] = (
                    f"{uuid.uuid4().hex}{validation_result.get('extension', '.bin')}"
                )
                entry["file_hash"] = hashlib.sha256(file_content).hexdigest()[:16]
                entry["validated_type"] = validation_result["file_type"]
                entry["validation_warnings"] = validation_result["warnings"]

            images.append(entry)
            total_bytes += len(file_content)
            logger.debug(
                f"处理图片: {original_filename} ({len(file_content)} bytes) "
                f"- 类型: {validation_result['file_type']}"
            )
        except Exception as e:
            logger.error(f"处理文件 {file.filename} 时出错: {e}", exc_info=True)
    return images
