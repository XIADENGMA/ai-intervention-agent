"""R276 / cycle-24 mining-14 (R271 spillover): image upload limits
跨 frontend/backend 一致性 invariant。

R271 教训
---------

R271 揭示了 4-way drift (server_config / web_ui.html / webview.ts /
notification.py OpenAPI schema)。修复后引入了 distributed source-of-truth
audit (cr53 §5 #2 mining-14)。

R276 是 mining-14 的第一个真发现：image upload 大小/数量限制分别在
**前后端各 hardcode 一次**，没有 invariant lock。

Pre-R276 状态
-------------

| Constant | Frontend (image-upload.js) | Backend (_upload_helpers.py) |
|----------|---------------------------|------------------------------|
| 单文件大小 | ``MAX_IMAGE_SIZE = 10 * 1024 * 1024`` | ``MAX_FILE_SIZE_BYTES = 10 * 1024 * 1024`` |
| 单请求数量 | ``MAX_IMAGE_COUNT = 10`` | ``MAX_IMAGES_PER_REQUEST = 10`` |
| 累计字节预算 | (无前端 cap，依赖个数 × 单大小) | ``MAX_TOTAL_UPLOAD_BYTES = 100 * 1024 * 1024`` |

只有 ``_upload_helpers.py`` 注释里写"客户端 (MAX_IMAGE_COUNT /
MAX_IMAGE_SIZE) 同值"作为软约定。如果有人改一边，另一边静默 drift:

- backend 改 20MB 但 frontend 不改 → frontend 直接拒绝 10MB+ 文件（用户
  看到"过大"误判），明明 backend 已经允许
- frontend 改 20MB 但 backend 不改 → frontend pass，backend 413 Payload
  Too Large（用户填了很久的反馈一键消失）

任一方向都是糟糕的 UX。

R276 修复
---------

不改源码，只加 invariant test 锁定 4 对常量的字节值与计数等价：
- ``MAX_IMAGE_SIZE`` ≡ ``MAX_FILE_SIZE_BYTES``
- ``MAX_IMAGE_COUNT`` ≡ ``MAX_IMAGES_PER_REQUEST``
- (sanity) ``MAX_TOTAL_UPLOAD_BYTES`` ≥ ``MAX_FILE_SIZE_BYTES *
  MAX_IMAGES_PER_REQUEST`` (累计预算 ≥ 理论最大)

Invariant 详细
--------------

1. ``MAX_IMAGE_SIZE`` 与 ``MAX_FILE_SIZE_BYTES`` 字节值相等
2. ``MAX_IMAGE_COUNT`` 与 ``MAX_IMAGES_PER_REQUEST`` 整数值相等
3. ``MAX_TOTAL_UPLOAD_BYTES`` ≥ ``MAX_FILE_SIZE_BYTES * MAX_IMAGES_PER_REQUEST``
   （sanity：累计预算必须 ≥ "10 张 × 10 MB"，否则单文件 max + 数量 max
   组合后 backend 还是会拒绝）

Why locked
----------

R271 已经证明 4-way drift 会发生。这里只有 2 处但 risk 更高 (用户填了
反馈一键消失)。Lock 在 invariant 层，是最便宜的防御。
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
IMAGE_UPLOAD_JS = (
    REPO_ROOT / "src" / "ai_intervention_agent" / "static" / "js" / "image-upload.js"
)
UPLOAD_HELPERS_PY = (
    REPO_ROOT / "src" / "ai_intervention_agent" / "web_ui_routes" / "_upload_helpers.py"
)


def _parse_js_const(src: str, name: str) -> int:
    """从 image-upload.js 解析 ``const NAME = 10 * 1024 * 1024;`` 或
    ``const NAME = 10;`` 这种声明，返回求值结果。"""
    pattern = re.compile(
        r"^const\s+" + re.escape(name) + r"\s*=\s*([^;]+);",
        re.MULTILINE,
    )
    match = pattern.search(src)
    assert match is not None, f"R276: 找不到 ``const {name}`` 声明"
    expr = match.group(1).strip()
    # 安全 eval — 只允许数字 + 算术运算符
    safe_chars = set("0123456789 *+-/().")
    if not all(ch in safe_chars for ch in expr):
        raise AssertionError(f"R276: ``{name}`` 表达式包含非数学字符: {expr!r}")
    return int(eval(expr))


def _parse_py_int_const(src: str, name: str) -> int:
    """从 _upload_helpers.py 解析 ``NAME: int = 10 * 1024 * 1024`` 或
    ``NAME: int = 10``，返回求值结果。"""
    pattern = re.compile(
        r"^" + re.escape(name) + r"\s*:\s*int\s*=\s*([^#\n]+)",
        re.MULTILINE,
    )
    match = pattern.search(src)
    assert match is not None, f"R276: 找不到 ``{name}: int`` 声明"
    expr = match.group(1).strip()
    safe_chars = set("0123456789 *+-/().")
    if not all(ch in safe_chars for ch in expr):
        raise AssertionError(f"R276: ``{name}`` 表达式包含非数学字符: {expr!r}")
    return int(eval(expr))


class TestImageSizeConsistency(unittest.TestCase):
    js_src = IMAGE_UPLOAD_JS.read_text(encoding="utf-8")
    py_src = UPLOAD_HELPERS_PY.read_text(encoding="utf-8")

    def test_max_image_size_bytes_equal(self) -> None:
        frontend_size = _parse_js_const(self.js_src, "MAX_IMAGE_SIZE")
        backend_size = _parse_py_int_const(self.py_src, "MAX_FILE_SIZE_BYTES")
        self.assertEqual(
            frontend_size,
            backend_size,
            "R276: ``MAX_IMAGE_SIZE`` (frontend image-upload.js) 与 "
            "``MAX_FILE_SIZE_BYTES`` (backend _upload_helpers.py) 字节"
            "值必须严格相等，否则会出现 frontend 拒收/backend 413 silent "
            "drift。\n"
            f"  frontend MAX_IMAGE_SIZE = {frontend_size}\n"
            f"  backend  MAX_FILE_SIZE_BYTES = {backend_size}",
        )

    def test_max_image_count_equal(self) -> None:
        frontend_count = _parse_js_const(self.js_src, "MAX_IMAGE_COUNT")
        backend_count = _parse_py_int_const(self.py_src, "MAX_IMAGES_PER_REQUEST")
        self.assertEqual(
            frontend_count,
            backend_count,
            "R276: ``MAX_IMAGE_COUNT`` (frontend) 与 "
            "``MAX_IMAGES_PER_REQUEST`` (backend) 整数值必须严格相等。\n"
            f"  frontend MAX_IMAGE_COUNT = {frontend_count}\n"
            f"  backend  MAX_IMAGES_PER_REQUEST = {backend_count}",
        )

    def test_total_upload_budget_sanity(self) -> None:
        """累计字节预算必须 ≥ ``单文件最大 × 数量最大``，否则单 request
        装满即触 413，那 ``MAX_IMAGES_PER_REQUEST`` 就成了纸面数字。"""
        max_file = _parse_py_int_const(self.py_src, "MAX_FILE_SIZE_BYTES")
        max_count = _parse_py_int_const(self.py_src, "MAX_IMAGES_PER_REQUEST")
        total_budget = _parse_py_int_const(self.py_src, "MAX_TOTAL_UPLOAD_BYTES")
        self.assertGreaterEqual(
            total_budget,
            max_file * max_count,
            "R276: ``MAX_TOTAL_UPLOAD_BYTES`` 必须 ≥ ``MAX_FILE_SIZE_BYTES "
            "× MAX_IMAGES_PER_REQUEST``，否则单 request 装满 10 张 10MB "
            "图片就触 413，``MAX_IMAGES_PER_REQUEST=10`` 形同虚设。\n"
            f"  MAX_FILE_SIZE_BYTES = {max_file}\n"
            f"  MAX_IMAGES_PER_REQUEST = {max_count}\n"
            f"  expected_min = {max_file * max_count}\n"
            f"  actual MAX_TOTAL_UPLOAD_BYTES = {total_budget}",
        )


class TestConstantsAnchorComment(unittest.TestCase):
    """R276 文档锚点 — `_upload_helpers.py` 必须保留 "客户端 ... 同值"
    注释，方便未来维护者立刻找到 frontend pair。"""

    py_src = UPLOAD_HELPERS_PY.read_text(encoding="utf-8")

    def test_frontend_pair_comment_present(self) -> None:
        """注释里必须提到 ``MAX_IMAGE_COUNT`` 与 ``MAX_IMAGE_SIZE``。"""
        self.assertIn(
            "MAX_IMAGE_COUNT",
            self.py_src,
            "R276: _upload_helpers.py 必须有 'MAX_IMAGE_COUNT' 注释"
            "锚，方便维护者找到 frontend pair",
        )
        self.assertIn(
            "MAX_IMAGE_SIZE",
            self.py_src,
            "R276: _upload_helpers.py 必须有 'MAX_IMAGE_SIZE' 注释"
            "锚，方便维护者找到 frontend pair",
        )


if __name__ == "__main__":
    unittest.main()
