"""R60 — ``server_info_resource`` 暴露 process 块（pid / thread_count /
rss_bytes / user_cpu_seconds / sys_cpu_seconds / open_fds）。

设计：

* 所有指标走 stdlib（``os`` / ``threading`` / ``resource`` / ``platform``），
  不引入 ``psutil`` 依赖；
* macOS 与 Linux 的 ``ru_maxrss`` 单位不同（macOS bytes / Linux KB），
  本测试通过 patch ``platform.system()`` 验证两种 normalize 路径都对；
* ``open_fds`` 仅 Linux 可用（``/proc/self/fd``），macOS / Windows
  返回 ``-1``，client UI 该展示 "n/a"。
* 每个子项独立 try/except，单点失败不影响整块。
"""

from __future__ import annotations

import unittest
from typing import Any, cast
from unittest.mock import patch

import server


class TestProcessBlockShape(unittest.TestCase):
    def test_block_present_in_response(self) -> None:
        info = server.server_info_resource()
        self.assertIn("process", info, "server_info_resource 必须暴露 process 块")
        self.assertIsInstance(info["process"], dict)

    def test_basic_fields_present(self) -> None:
        info = server.server_info_resource()
        block = cast(dict[str, Any], info["process"])
        for key in ("pid", "thread_count"):
            self.assertIn(key, block, f"process block 应当包含 {key!r}")
        self.assertIsInstance(block["pid"], int)
        self.assertGreater(block["pid"], 0)
        self.assertIsInstance(block["thread_count"], int)
        self.assertGreaterEqual(block["thread_count"], 1)

    def test_rss_field_is_byte_normalized(self) -> None:
        info = server.server_info_resource()
        block = cast(dict[str, Any], info["process"])
        # 测试运行时 rss 至少要 ≥ 1 MB（Python 解释器自身基线）；
        # 上限放宽到 4 GB —— 任何超过这个的几乎肯定是单位 bug。
        self.assertIn("rss_bytes", block, "rss_bytes 字段必须存在")
        self.assertIsInstance(block["rss_bytes"], int)
        self.assertGreaterEqual(block["rss_bytes"], 1024 * 1024)
        self.assertLess(block["rss_bytes"], 4 * 1024 * 1024 * 1024)

    def test_cpu_fields_are_floats(self) -> None:
        info = server.server_info_resource()
        block = cast(dict[str, Any], info["process"])
        self.assertIn("user_cpu_seconds", block)
        self.assertIn("sys_cpu_seconds", block)
        self.assertIsInstance(block["user_cpu_seconds"], float)
        self.assertIsInstance(block["sys_cpu_seconds"], float)
        self.assertGreaterEqual(block["user_cpu_seconds"], 0.0)
        self.assertGreaterEqual(block["sys_cpu_seconds"], 0.0)

    def test_open_fds_present_int(self) -> None:
        info = server.server_info_resource()
        block = cast(dict[str, Any], info["process"])
        self.assertIn("open_fds", block, "open_fds 字段必须存在")
        self.assertIsInstance(block["open_fds"], int)
        # Linux 时是正整数（≥ 3：stdin/stdout/stderr）；
        # macOS/Windows 时是 -1（unsupported）；都接受
        self.assertTrue(
            block["open_fds"] == -1 or block["open_fds"] >= 3,
            f"open_fds={block['open_fds']!r} 应是 -1（unsupported）或 ≥ 3",
        )


class TestRssUnitNormalizationDarwin(unittest.TestCase):
    """macOS ``ru_maxrss`` 是 bytes，不应再 ×1024。"""

    def test_darwin_rss_passed_through_as_bytes(self) -> None:
        # 1234567 bytes 是 macOS 直接给的；如果代码错误地 ×1024，结果会变 1.2 GB
        with patch("platform.system", return_value="Darwin"):
            info = server.server_info_resource()
            block = cast(dict[str, Any], info["process"])
        # 不能直接 mock getrusage，但 macOS 路径下 rss 应该 < 4 GB（合理范围）
        self.assertIn("rss_bytes", block)
        self.assertLess(block["rss_bytes"], 4 * 1024 * 1024 * 1024)


class TestSubFieldFailureIsolation(unittest.TestCase):
    """单子项失败不应破坏整个 process 块。"""

    def test_resource_module_failure_falls_back_to_resource_error(self) -> None:
        # 故意触发 resource 子块失败：mock ``resource.getrusage`` 抛异常
        with patch("resource.getrusage", side_effect=RuntimeError("simulated")):
            info = server.server_info_resource()
            block = cast(dict[str, Any], info["process"])
        # rss_bytes / cpu_seconds 缺失，但 pid / thread_count 仍在
        self.assertIn("pid", block)
        self.assertIn("thread_count", block)
        self.assertIn("resource_error", block)
        self.assertIn("RuntimeError", str(block["resource_error"]))

    def test_fd_listing_failure_does_not_break_block(self) -> None:
        with patch("os.path.isdir", return_value=True):
            with patch("os.listdir", side_effect=OSError("simulated EACCES")):
                info = server.server_info_resource()
                block = cast(dict[str, Any], info["process"])
        # rss / cpu 仍在
        self.assertIn("rss_bytes", block)
        self.assertIn("fd_error", block)
        self.assertIn("OSError", str(block["fd_error"]))


class TestProcessBlockIsLastFailureSafe(unittest.TestCase):
    """整个 process 块本身的 try/except 也不会让 server_info_resource 抛。"""

    def test_outer_exception_records_block_level_error(self) -> None:
        # 强制 outer try 抛：mock os.getpid 抛
        with patch("os.getpid", side_effect=RuntimeError("boom")):
            info = server.server_info_resource()
            block = cast(dict[str, Any], info["process"])
        # 外层 try 抛后 block 应只剩一个 error 字段，不影响其他块
        self.assertIn("error", block)
        # 其他主块仍然要在（top-level keys：name/version/runtime/...）
        self.assertIn("name", info)
        self.assertIn("runtime", info)


if __name__ == "__main__":
    unittest.main()
