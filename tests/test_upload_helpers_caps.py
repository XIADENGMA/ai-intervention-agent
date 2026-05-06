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
    MAX_FILE_SIZE_BYTES,
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

    def test_byte_cap_rejects_file_that_would_cross_limit(self) -> None:
        """当前文件会让累计字节超过上限时，应拒绝当前文件而不是越线接受。"""
        original = _upload_helpers.MAX_TOTAL_UPLOAD_BYTES
        try:
            # 第 1 张后尚未达到上限；第 2 张如果被接受会超过总字节上限。
            _upload_helpers.MAX_TOTAL_UPLOAD_BYTES = 2 * len(_TINY_PNG) - 1

            files = {
                "image_a": _make_mock_file("a.png", _TINY_PNG),
                "image_b": _make_mock_file("b.png", _TINY_PNG),
            }
            request = _make_mock_request(files)
            result = extract_uploaded_images(request)

            self.assertEqual(
                len(result),
                1,
                "累计字节上限应约束 total_bytes + 当前文件大小；"
                "不能只在进入循环前检查 total_bytes >= cap",
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


class TestPerFileSizeCap(unittest.TestCase):
    """R17.6 第二道闸：``MAX_FILE_SIZE_BYTES`` 单文件读取硬上限。

    动机：``MAX_CONTENT_LENGTH`` 是请求级闸（第一道闸），但反向代理 / 网关
    可能会 strip 掉 ``Content-Length`` 头，让 Flask 无法预判请求体大小；这
    种情况下，没有第二道闸的话，单 part 上传 100GB 仍能让进程 OOM。本测试
    类锁住第二道闸的关键不变量：``file.read()`` 必须带 size 参数，且超出
    时立即丢弃不进入 validate。
    """

    def test_max_file_size_constant_matches_validator_default(self) -> None:
        """``MAX_FILE_SIZE_BYTES`` 必须与 ``file_validator.FileValidator``
        默认 ``max_file_size`` 一致 —— 否则两层 cap 出现 drift，攻击者能找
        到只过其中一层的口子。"""
        from file_validator import FileValidator

        validator = FileValidator()
        self.assertEqual(
            MAX_FILE_SIZE_BYTES,
            validator.max_file_size,
            "MAX_FILE_SIZE_BYTES 必须与 FileValidator.max_file_size 默认值"
            "完全一致；任何 drift 都意味着两层防御对'多大才算超大'有不同"
            "判断，攻击者可利用这个间隙",
        )

    def test_max_file_size_at_or_below_total(self) -> None:
        """``MAX_FILE_SIZE_BYTES`` 必须 ≤ ``MAX_TOTAL_UPLOAD_BYTES`` —— 否则
        单文件就能超出累计预算，预算检查瞬间失效。"""
        self.assertLessEqual(
            MAX_FILE_SIZE_BYTES,
            MAX_TOTAL_UPLOAD_BYTES,
            "MAX_FILE_SIZE_BYTES > MAX_TOTAL_UPLOAD_BYTES 是配置错误：单文件"
            "本身就超出了「整次请求」的累计预算",
        )

    def test_oversized_part_rejected_before_validate(self) -> None:
        """单 part 超过 ``MAX_FILE_SIZE_BYTES`` 时必须立即拒绝，不调
        ``validate_uploaded_file``。否则验证函数会浪费 CPU 跑魔数检查 +
        正则扫描，且如果未来 validator 出现 bug 把超大 part 误放，整条防御
        链就漏了。"""
        # 模拟一个攻击者发送超大 part：让 .read(N) 返回 N 字节恰好超出
        # MAX_FILE_SIZE_BYTES 一字节（这正是 read(MAX+1) 调用的合约）。
        oversized_content = b"\x00" * (MAX_FILE_SIZE_BYTES + 1)
        oversized_file = MagicMock()
        oversized_file.filename = "evil.png"
        oversized_file.content_type = "image/png"
        oversized_file.read.return_value = oversized_content

        request = _make_mock_request({"image_0": oversized_file})

        # 用 patch 监视 validate_uploaded_file 是否被调到（不应该）
        from unittest.mock import patch

        with patch(
            "web_ui_routes._upload_helpers.validate_uploaded_file"
        ) as mock_validate:
            result = extract_uploaded_images(request)

        self.assertEqual(
            len(result),
            0,
            "超过 MAX_FILE_SIZE_BYTES 的 part 必须被拒绝（不出现在结果列表）",
        )
        mock_validate.assert_not_called()

    def test_at_max_file_size_passes_through(self) -> None:
        """单 part 恰好 ``MAX_FILE_SIZE_BYTES`` 字节（边界情形）必须通过 cap
        检查 —— 否则会出现"声明 10 MB 上限但实际只接受 < 10 MB"的
        off-by-one 误差，让前端文档误导用户。

        注：这里我们只测 cap 检查通过，不测 validate 通过（10 MB 的 \\x00
        显然不是合法 PNG，validate 会拒绝；但 cap 这一层应该放行）。
        """
        from unittest.mock import patch

        at_cap_content = b"\x00" * MAX_FILE_SIZE_BYTES
        at_cap_file = MagicMock()
        at_cap_file.filename = "boundary.png"
        at_cap_file.content_type = "image/png"
        at_cap_file.read.return_value = at_cap_content

        request = _make_mock_request({"image_0": at_cap_file})

        with patch(
            "web_ui_routes._upload_helpers.validate_uploaded_file",
            return_value={
                "valid": False,
                "errors": ["fake reject"],
                "warnings": [],
                "mime_type": None,
                "file_type": None,
                "extension": ".bin",
                "size": 0,
            },
        ) as mock_validate:
            extract_uploaded_images(request)

        # cap 应该放行 → validate 被调到（即使最后被 validate 拒）
        mock_validate.assert_called_once()

    def test_file_read_call_has_size_argument(self) -> None:
        """AST 反向锁：``file.read()`` 必须带 size 参数 —— 裸 ``file.read()``
        会读全量，让第二道闸彻底失效。任何"清理代码删除 size 参数"的重构
        都会立即被本测试拦下。
        """
        import ast
        import inspect

        src = inspect.getsource(extract_uploaded_images)
        tree = ast.parse(src)

        bare_read_calls: list[ast.Call] = []
        sized_read_calls: list[ast.Call] = []

        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "read"
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "file"
            ):
                if not node.args and not node.keywords:
                    bare_read_calls.append(node)
                else:
                    sized_read_calls.append(node)

        self.assertGreater(
            len(sized_read_calls),
            0,
            "extract_uploaded_images 中必须存在至少一个带 size 参数的 "
            "file.read(N) 调用 —— 找不到则说明第二道闸被绕过了",
        )
        self.assertEqual(
            len(bare_read_calls),
            0,
            f"extract_uploaded_images 中发现 {len(bare_read_calls)} 个裸 "
            f"file.read() 调用 —— 必须带 size 参数（建议 MAX_FILE_SIZE_BYTES + 1），"
            "否则攻击者可发送 100GB 单 part 让进程 OOM",
        )


class TestFlaskMaxContentLength(unittest.TestCase):
    """R17.6 第一道闸：Flask ``app.config['MAX_CONTENT_LENGTH']`` 必须设置。

    动机：没有 ``MAX_CONTENT_LENGTH`` 时，Flask/Werkzeug 会把整个请求体流到
    临时存储后再交给应用代码 —— 攻击者能用 100GB 单 part 把磁盘写满 / 进程
    内存爆。设置后超过阈值的请求在 multipart 解析阶段就被 413 拒绝。
    """

    @classmethod
    def setUpClass(cls) -> None:
        """构造一个 WebFeedbackUI 实例供所有测试共用。

        ``WebFeedbackUI.__init__`` 只初始化 Flask app / limiter / 路由 mixin，
        不会启动 server（``shutdown_server`` 会向当前进程发 SIGINT，绝对不能
        在测试里调）。共享一个实例避免每条测试都重新初始化 Compress / Swagger 等
        重型组件。
        """
        from web_ui import WebFeedbackUI

        cls._ui = WebFeedbackUI(prompt="smoke-r17.6", task_id="r17-6-cap", port=0)

    def test_max_content_length_present(self) -> None:
        """``MAX_CONTENT_LENGTH`` 必须在 app.config 中设置（非 None / 非 0）。"""
        value = self._ui.app.config.get("MAX_CONTENT_LENGTH")
        self.assertIsNotNone(value, "app.config['MAX_CONTENT_LENGTH'] 必须设置")
        assert value is not None  # ty narrowing
        self.assertGreater(
            value,
            0,
            "app.config['MAX_CONTENT_LENGTH'] 必须为正数（0/None 等价于无限制）",
        )

    def test_max_content_length_covers_max_total_upload_bytes(self) -> None:
        """``MAX_CONTENT_LENGTH`` 必须 ≥ ``MAX_TOTAL_UPLOAD_BYTES`` —— 否则
        合法的 100 MB 累计上传请求会在 Flask 层被错误地 413 拒绝，前端用户
        永远无法上传完整批次。"""
        value = self._ui.app.config.get("MAX_CONTENT_LENGTH")
        self.assertIsNotNone(value)
        assert value is not None  # ty narrowing
        self.assertGreaterEqual(
            value,
            MAX_TOTAL_UPLOAD_BYTES,
            f"MAX_CONTENT_LENGTH ({value}) < MAX_TOTAL_UPLOAD_BYTES "
            f"({MAX_TOTAL_UPLOAD_BYTES}) 是配置错误：合法上传会被 413",
        )
        # 但也不能太大（防止配置错误把 cap 放到 GB 级，第一道闸失效）
        self.assertLessEqual(
            value,
            MAX_TOTAL_UPLOAD_BYTES + 100 * 1024 * 1024,
            f"MAX_CONTENT_LENGTH ({value}) >> MAX_TOTAL_UPLOAD_BYTES "
            "+ 100 MB 缓冲，超出合理 buffer 范围（multipart overhead + "
            "form text 总和远小于 100 MB）",
        )

    def test_max_content_length_does_not_drift_from_constant(self) -> None:
        """``MAX_CONTENT_LENGTH`` 必须直接引用 ``MAX_TOTAL_UPLOAD_BYTES`` 常量
        而非硬编码数字 —— 防止常量更新时 web_ui.py 没同步更新（这正是历史上
        多个 dual-path drift bug 的根源）。"""
        import inspect

        import web_ui

        src = inspect.getsource(web_ui)
        # 必须出现 MAX_TOTAL_UPLOAD_BYTES 引用（无论是直接 import 还是
        # 模块级访问）
        self.assertIn(
            "MAX_TOTAL_UPLOAD_BYTES",
            src,
            "web_ui.py 必须引用 MAX_TOTAL_UPLOAD_BYTES 常量（而非硬编码数字），"
            "否则常量更新时 web_ui 不会自动跟进，第一道闸与第三道闸 drift",
        )
        # 反向锁：MAX_CONTENT_LENGTH 一定不能被赋值为字面量数字（避免硬编码）
        import ast
        import re

        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                # 找 self.app.config["MAX_CONTENT_LENGTH"] = ... 这类赋值
                for target in node.targets:
                    if (
                        isinstance(target, ast.Subscript)
                        and isinstance(target.value, ast.Attribute)
                        and target.value.attr == "config"
                        and isinstance(target.slice, ast.Constant)
                        and target.slice.value == "MAX_CONTENT_LENGTH"
                    ):
                        # value 必须不是纯字面量（应该是涉及 MAX_TOTAL_UPLOAD_BYTES
                        # 的表达式）
                        value_src = ast.unparse(node.value)
                        self.assertTrue(
                            re.search(r"MAX_TOTAL_UPLOAD_BYTES", value_src),
                            f"MAX_CONTENT_LENGTH 赋值表达式必须引用 "
                            f"MAX_TOTAL_UPLOAD_BYTES；当前是 {value_src!r}",
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
