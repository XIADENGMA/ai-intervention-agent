"""``web_ui_routes/_upload_helpers.py`` 服务端深度防御限额锁试。

历史背景：
- 客户端 (``static/js/image-upload.js``) 限制 MAX_IMAGE_COUNT = 10，
  MAX_IMAGE_SIZE = 10 MB；但服务端 ``extract_uploaded_images`` 长期没
  对应限额，attacker 直接 curl POST 100 张图就能让进程内存压力变大。
- v1.5.x round-14 加了 ``MAX_IMAGES_PER_REQUEST = 10`` /
  ``MAX_TOTAL_UPLOAD_BYTES = 100 MB`` 两道闸。本测试锁住这两个常量
  实际生效，且与客户端阈值保持对齐，未来变更时不会被静默放宽。

测试策略：
- 不依赖真实 Flask 请求对象；用 mock ``request.files`` 注入
  ``MockFile`` 列表（``namedtuple`` 即可），观察返回的 images 长度。
- 真实文件验证流程会跑 ``file_validator``——为了让测试聚焦在限额
  本身，我们用合法的最小 PNG header 构造 raw bytes，确保
  ``validate_uploaded_file`` 报 valid。
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from web_ui_routes import _upload_helpers
from web_ui_routes._upload_helpers import (
    MAX_IMAGES_PER_REQUEST,
    MAX_TOTAL_UPLOAD_BYTES,
    extract_uploaded_images,
)


def _build_tiny_png() -> bytes:
    """运行时用 ``zlib`` + ``struct`` 拼最小合法 PNG（1×1 灰度像素），
    避免依赖 ``Pillow``（``ai-intervention-agent`` 服务端不打包 PIL）。

    格式：8 字节签名 + IHDR + IDAT(zlib 压缩的 1 字节像素) + IEND，
    每块带正确的 CRC32。
    """
    import struct
    import zlib

    sig = b"\x89PNG\r\n\x1a\n"

    def chunk(tag: bytes, data: bytes) -> bytes:
        crc = zlib.crc32(tag + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", crc)

    # 1×1, 8-bit, grayscale（color_type=0），no interlace
    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 0, 0, 0, 0)
    # IDAT：1 字节 filter (0=None) + 1 字节像素数据
    idat = zlib.compress(b"\x00\x00", 9)
    iend = b""

    return sig + chunk(b"IHDR", ihdr) + chunk(b"IDAT", idat) + chunk(b"IEND", iend)


_TINY_PNG = _build_tiny_png()


def _make_mock_file(filename: str, content: bytes, content_type: str = "image/png"):
    """构造行为类似 Flask FileStorage 的 mock。"""
    file = MagicMock()
    file.filename = filename
    file.content_type = content_type
    file.read.return_value = content
    return file


def _make_mock_request(files: dict):
    """构造行为类似 Flask request 的 mock，``request.files`` 为 dict-like。"""
    request = MagicMock()
    request.files = files
    return request


class TestUploadHelperConstants(unittest.TestCase):
    """常量本身的合理性 + 与客户端 ``image-upload.js`` 对齐。"""

    def test_max_images_matches_client(self) -> None:
        """``MAX_IMAGES_PER_REQUEST`` 与客户端 ``MAX_IMAGE_COUNT`` 对齐。"""
        client_js = (REPO_ROOT / "static" / "js" / "image-upload.js").read_text(
            encoding="utf-8"
        )
        # 找 ``const MAX_IMAGE_COUNT = N``
        import re

        m = re.search(r"const\s+MAX_IMAGE_COUNT\s*=\s*(\d+)", client_js)
        self.assertIsNotNone(m, "image-upload.js 必须定义 MAX_IMAGE_COUNT")
        assert m is not None  # ty narrowing
        client_max = int(m.group(1))
        self.assertEqual(
            MAX_IMAGES_PER_REQUEST,
            client_max,
            "服务端 MAX_IMAGES_PER_REQUEST 必须与客户端 MAX_IMAGE_COUNT 一致；"
            "否则用户在 UI 看似允许的张数会在 API 层被静默拒绝",
        )

    def test_total_bytes_consistent_with_per_file_cap(self) -> None:
        """``MAX_TOTAL_UPLOAD_BYTES`` 应该 ≥ ``MAX_IMAGES × 单文件 10 MB``，避免限额冲突。"""
        per_file_cap = 10 * 1024 * 1024
        expected_min = MAX_IMAGES_PER_REQUEST * per_file_cap
        self.assertGreaterEqual(
            MAX_TOTAL_UPLOAD_BYTES,
            expected_min,
            f"MAX_TOTAL_UPLOAD_BYTES ({MAX_TOTAL_UPLOAD_BYTES}) "
            f"必须 ≥ MAX_IMAGES × 10 MB ({expected_min})；"
            "否则用户上传到一半就被拒",
        )
        # 同时不能太大（防止配置错误把限额放到 GB 级）
        self.assertLessEqual(
            MAX_TOTAL_UPLOAD_BYTES,
            500 * 1024 * 1024,
            "MAX_TOTAL_UPLOAD_BYTES 超过 500 MB 看起来不合理（深度防御失效）",
        )


class TestUploadHelperCountCap(unittest.TestCase):
    """张数上限锁试。"""

    def test_at_cap_all_pass(self) -> None:
        """正好 ``MAX_IMAGES_PER_REQUEST`` 张 → 全部接受。"""
        files = {
            f"image_{i}": _make_mock_file(f"a{i}.png", _TINY_PNG)
            for i in range(MAX_IMAGES_PER_REQUEST)
        }
        request = _make_mock_request(files)
        result = extract_uploaded_images(request)
        self.assertEqual(len(result), MAX_IMAGES_PER_REQUEST)

    def test_over_cap_truncates(self) -> None:
        """超过 ``MAX_IMAGES_PER_REQUEST`` 张 → 后续被丢弃。"""
        n = MAX_IMAGES_PER_REQUEST + 5
        files = {
            f"image_{i}": _make_mock_file(f"a{i}.png", _TINY_PNG) for i in range(n)
        }
        request = _make_mock_request(files)
        result = extract_uploaded_images(request)
        self.assertEqual(
            len(result),
            MAX_IMAGES_PER_REQUEST,
            "超过张数上限的图片必须被丢弃；当前修复回退会导致全部 N 张通过",
        )


class TestUploadHelperByteCap(unittest.TestCase):
    """累计字节上限锁试。

    用 monkey-patch 把 ``MAX_TOTAL_UPLOAD_BYTES`` 临时调成小值
    （比如 2 × len(_TINY_PNG)），让前 2 张通过，第 3 张被字节限额拦下。
    """

    def test_byte_cap_truncates(self) -> None:
        original = _upload_helpers.MAX_TOTAL_UPLOAD_BYTES
        try:
            # 临时把字节上限调成"恰好 2 张"
            _upload_helpers.MAX_TOTAL_UPLOAD_BYTES = 2 * len(_TINY_PNG)

            files = {
                "image_a": _make_mock_file("a.png", _TINY_PNG),
                "image_b": _make_mock_file("b.png", _TINY_PNG),
                "image_c": _make_mock_file("c.png", _TINY_PNG),
                "image_d": _make_mock_file("d.png", _TINY_PNG),
            }
            request = _make_mock_request(files)
            result = extract_uploaded_images(request)

            # 第 1、2 张通过，第 3 张时 total_bytes >= cap → 进入跳过分支
            self.assertEqual(
                len(result),
                2,
                "字节累计达到 MAX_TOTAL_UPLOAD_BYTES 后必须丢弃后续；"
                "当前修复回退会导致 4 张全部通过",
            )
        finally:
            _upload_helpers.MAX_TOTAL_UPLOAD_BYTES = original


class TestUploadHelperBoundaryNotes(unittest.TestCase):
    """读取代码确认两个限额都通过 ``continue`` 而非 ``break`` 跳过——
    避免误把 ``image_*`` 中间夹杂 ``image_xyz`` 这种字段时跳出循环。
    """

    def test_caps_use_continue_not_break(self) -> None:
        src = (REPO_ROOT / "web_ui_routes" / "_upload_helpers.py").read_text(
            encoding="utf-8"
        )
        # 拉出 extract_uploaded_images 函数体
        import ast

        tree = ast.parse(src)
        target_func: ast.FunctionDef | None = None
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.FunctionDef)
                and node.name == "extract_uploaded_images"
            ):
                target_func = node
                break
        self.assertIsNotNone(target_func)
        assert target_func is not None

        body_src = ast.unparse(target_func)
        # 限额相关的两处必须用 ``continue``；不能让攻击者通过插入一个无效
        # ``image_*`` 字段触发 ``break`` 来绕过后续验证（理论上 dict 顺序
        # 是插入顺序，但保险起见）。
        self.assertIn("continue", body_src)
        # 不应在限额检查后立刻 break（会让"第 11 张被拦下"也终止本应继续的循环；
        # 当前实现是 continue + 持续报警，更稳妥）
        # 简单方法：函数体里 ``break`` 出现次数应 == 0
        self.assertEqual(
            body_src.count("break"),
            0,
            "extract_uploaded_images 不应在限额检查后用 break 跳出"
            "（用 continue 保留对剩余字段的扫描记录，防御日志更完整）",
        )


def _file_validator_sanity_check() -> None:
    """import-time sanity：确保 _TINY_PNG 真的能通过 file_validator。

    如果未来 ``file_validator`` 加严了 PNG 校验导致 _TINY_PNG 不再 valid，
    本测试模块会在 import 阶段 fail 而不是在测试阶段 fail，便于排错。
    """
    from file_validator import validate_uploaded_file

    result = validate_uploaded_file(_TINY_PNG, "smoke.png", "image/png")
    if not result["valid"]:
        raise RuntimeError(
            "测试 fixture _TINY_PNG 不再被 file_validator 接受为合法 PNG："
            f"{result.get('errors')}"
        )


_file_validator_sanity_check()


if __name__ == "__main__":
    unittest.main()
