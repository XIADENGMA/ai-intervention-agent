"""上传文件处理工具 — 从 Flask request 提取已验证的图片列表。

供 task.py 和 feedback.py 中的提交端点共用，消除图片处理逻辑重复。
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


def extract_uploaded_images(
    request: Request, *, include_metadata: bool = False
) -> list[dict[str, Any]]:
    """从 Flask request.files 中提取所有 image_* 文件，返回验证通过的图片列表。

    参数:
        request: Flask 请求对象
        include_metadata: 是否包含额外元数据（safe_filename, file_hash, validation_warnings）

    返回:
        已验证的图片字典列表，每个包含 filename, data(base64), content_type, size
    """
    images: list[dict[str, Any]] = []
    for key in request.files:
        if not key.startswith("image_"):
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
            logger.debug(
                f"处理图片: {original_filename} ({len(file_content)} bytes) "
                f"- 类型: {validation_result['file_type']}"
            )
        except Exception as e:
            logger.error(f"处理文件 {file.filename} 时出错: {e}", exc_info=True)
    return images
