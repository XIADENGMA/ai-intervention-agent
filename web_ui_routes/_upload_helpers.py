"""上传文件处理工具 — 从 Flask request 提取已验证的图片列表。

供 task.py 和 feedback.py 中的提交端点共用，消除图片处理逻辑重复。

分层防御（与 ``static/js/image-upload.js`` 的客户端阈值对齐，按拒绝时机由
早到晚排列；任何一层 fail 都不会进入下一层）：

第一层：``app.config["MAX_CONTENT_LENGTH"] = MAX_TOTAL_UPLOAD_BYTES + 1 MB``
    在 ``web_ui.py`` 设置。Flask/Werkzeug 在 multipart 解析阶段直接拒绝
    超大请求（返回 413 Request Entity Too Large），避免恶意 100GB 单
    part 先被流到磁盘临时文件再被下游 cap 发现。OWASP "Limit upload
    size" 推荐做法。

第二层：``MAX_FILE_SIZE_BYTES = 10 MB`` 单文件读取硬上限
    本文件 ``file.read(MAX_FILE_SIZE_BYTES + 1)`` 限制 per-part 读取
    字节数。即使第一层被反向代理 / 网关 strip 掉了 ``Content-Length``
    头（导致 ``MAX_CONTENT_LENGTH`` 无法生效），本层仍能阻止"单 part
    无限大 → 进程内存爆"的 OOM 路径。读取后若 ``len(file_content) >
    MAX_FILE_SIZE_BYTES`` 立即丢弃。

第三层：``MAX_IMAGES_PER_REQUEST = 10``（数量预算）+
       ``MAX_TOTAL_UPLOAD_BYTES = 100 MB``（累计字节预算）
    本文件层面的累计限额。客户端 (``MAX_IMAGE_COUNT`` /
    ``MAX_IMAGE_SIZE``) 同值；这层是"客户端被人为绕过 / 直接 curl
    调 API"时的兜底。任何累计超限的请求都会被丢弃后续文件，已通过
    验证的前几张仍正常返回（避免全有或全无导致客户端体验突然中断；
    前端通过 toast 提示用户重试）。

第四层：``validate_uploaded_file`` magic-number / extension / content-scan
    在 ``file_validator.py``。即使尺寸过关也要确认是真图片且无恶意
    内容（脚本注入、php 标签、可执行扩展名等）。
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
# R17.6 第二道闸：单文件读取硬上限。与 ``file_validator.FileValidator.__init__``
# 默认 ``max_file_size = 10 * 1024 * 1024`` 完全一致，确保读取层 cap 与验证层
# cap 不会出现 drift。任何超过本上限的 part 都在 ``file.read()`` 阶段就被截断
# 拒绝，比依赖下游 ``validate_uploaded_file`` 的"文件大小超过限制" 错误更早一拍
# 生效（节省一次内存拷贝 + 一次正则扫描），同时阻止 ``MAX_CONTENT_LENGTH`` 被
# 上游剥离时的单 part OOM。
MAX_FILE_SIZE_BYTES: int = 10 * 1024 * 1024


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
            # R17.6 第二道闸：read 至多 MAX_FILE_SIZE_BYTES + 1 字节，
            # 用 +1 让超出阈值的 part 能够被检测到（"恰好等于" vs
            # "超过" 的歧义判定）。内存占用始终被严格 cap 在 10 MB +
            # 1 字节，攻击者无法靠"单 part 无限大"耗尽内存。
            file_content = file.read(MAX_FILE_SIZE_BYTES + 1)
            if len(file_content) > MAX_FILE_SIZE_BYTES:
                logger.warning(
                    f"文件超过单文件上限 ({MAX_FILE_SIZE_BYTES // (1024 * 1024)} MB): "
                    f"{file.filename} - 已读 {len(file_content)} bytes，拒绝"
                )
                continue
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
