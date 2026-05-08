"""R62 — server_info_resource ``runtime`` 块扩展（python_implementation / 启动时戳 / uptime）。

设计目标：

* R44 起初 runtime 块只有 ``python_version`` / ``python_executable`` /
  ``platform`` 三字段。R62 在同一块内追加：
  - ``python_implementation``：解释器实现（CPython / PyPy / Jython / ...），
  - ``started_at_unix``：进程启动 unix 时戳（= module 加载时刻），
  - ``uptime_seconds``：``time.time() - started_at_unix``，每次调用动态算。
* 全部走 stdlib（``sys`` / ``platform`` / ``time``），零依赖；
* 整个块在一个 ``try`` 里：任一字段失败都走 ``error`` 兜底，不影响顶层
  ``info`` 的其他块；
* ``_PROCESS_STARTED_AT_UNIX`` 是 module-level 常量，进程生命周期内不变。

覆盖：

* R62 新增字段都存在；
* 字段值类型与格式正确（``python_implementation`` 非空字符串）；
* ``uptime_seconds`` 是非负 float 且 = ``time.time() - started_at_unix``；
* ``started_at_unix`` 是 module-level 常量，多次调用保持一致；
* R44 老字段仍然在（不破坏 R44 的契约）；
* ``_PROCESS_STARTED_AT_UNIX`` 在 server module 里被定义为 float。
"""

from __future__ import annotations

import time
import unittest
from typing import cast

import ai_intervention_agent.server as server


class TestRuntimeBlockShape(unittest.TestCase):
    def test_runtime_key_present(self) -> None:
        info = cast(dict, server.server_info_resource())
        self.assertIn("runtime", info)
        self.assertIsInstance(info["runtime"], dict)

    def test_runtime_has_r44_legacy_fields(self) -> None:
        """R62 不应破坏 R44 现有契约。"""
        info = cast(dict, server.server_info_resource())
        rt = cast(dict, info["runtime"])
        for key in ("python_version", "python_executable", "platform"):
            self.assertIn(key, rt, f"R44 老字段 {key} 应保留")

    def test_runtime_has_r62_new_fields(self) -> None:
        info = cast(dict, server.server_info_resource())
        rt = cast(dict, info["runtime"])
        for key in ("python_implementation", "started_at_unix", "uptime_seconds"):
            self.assertIn(key, rt, f"R62 新字段缺失：{key}")


class TestRuntimeFieldFormats(unittest.TestCase):
    def test_python_implementation_is_known_string(self) -> None:
        info = cast(dict, server.server_info_resource())
        rt = cast(dict, info["runtime"])
        impl = rt["python_implementation"]
        self.assertIsInstance(impl, str)
        # 不强校验是 CPython（PyPy/Jython 等也合法），只断言非空字符串
        self.assertTrue(len(impl) > 0)
        # 通常是已知集合之一
        known = {"CPython", "PyPy", "Jython", "IronPython", "GraalVM"}
        self.assertIn(impl, known, f"python_implementation 取到了非常规值: {impl!r}")

    def test_started_at_unix_is_float(self) -> None:
        info = cast(dict, server.server_info_resource())
        rt = cast(dict, info["runtime"])
        ts = rt["started_at_unix"]
        self.assertIsInstance(ts, float)
        self.assertGreater(ts, 0.0)

    def test_uptime_seconds_is_float(self) -> None:
        info = cast(dict, server.server_info_resource())
        rt = cast(dict, info["runtime"])
        u = rt["uptime_seconds"]
        self.assertIsInstance(u, float)


class TestUptimeSemantics(unittest.TestCase):
    def test_started_at_unix_is_module_level_constant(self) -> None:
        info1 = cast(dict, server.server_info_resource())
        rt1 = cast(dict, info1["runtime"])
        time.sleep(0.05)
        info2 = cast(dict, server.server_info_resource())
        rt2 = cast(dict, info2["runtime"])
        self.assertEqual(
            rt1["started_at_unix"],
            rt2["started_at_unix"],
            "_PROCESS_STARTED_AT_UNIX 应该在整个进程生命周期内不变",
        )

    def test_uptime_seconds_grows_monotonically(self) -> None:
        info1 = cast(dict, server.server_info_resource())
        rt1 = cast(dict, info1["runtime"])
        u1 = float(rt1["uptime_seconds"])
        time.sleep(0.05)
        info2 = cast(dict, server.server_info_resource())
        rt2 = cast(dict, info2["runtime"])
        u2 = float(rt2["uptime_seconds"])
        self.assertGreater(u2, u1, "uptime 在两次调用间应当严格递增")

    def test_uptime_is_non_negative(self) -> None:
        info = cast(dict, server.server_info_resource())
        rt = cast(dict, info["runtime"])
        self.assertGreaterEqual(float(rt["uptime_seconds"]), 0.0)

    def test_uptime_close_to_now_minus_started(self) -> None:
        info = cast(dict, server.server_info_resource())
        rt = cast(dict, info["runtime"])
        expected = time.time() - float(rt["started_at_unix"])
        diff = abs(float(rt["uptime_seconds"]) - expected)
        # uptime 在 server_info_resource 内部计算，到测试这里取 time.time()
        # 中间最多差 100 ms（系统调度抖动也算上）
        self.assertLess(diff, 0.5, f"uptime 偏离当前差额过大: diff={diff:.3f}s")


class TestRuntimeBlockDoesNotBreakOtherBlocks(unittest.TestCase):
    """新增字段不应影响其他块（process / fastmcp / web_ui）的存在。"""

    def test_other_blocks_still_present(self) -> None:
        info = cast(dict, server.server_info_resource())
        for k in ("name", "process", "runtime", "fastmcp", "web_ui"):
            self.assertIn(k, info, f"顶层缺 {k}")


class TestModuleLevelConstant(unittest.TestCase):
    def test_constant_exists(self) -> None:
        self.assertTrue(hasattr(server, "_PROCESS_STARTED_AT_UNIX"))

    def test_constant_is_float(self) -> None:
        self.assertIsInstance(server._PROCESS_STARTED_AT_UNIX, float)

    def test_constant_is_close_to_now_at_module_level(self) -> None:
        # 测试时刻与 module load 时刻可能差几秒（pytest collection 时长），
        # 但不应该超过 24h（即时戳本身合法）
        delta = time.time() - server._PROCESS_STARTED_AT_UNIX
        self.assertGreater(delta, -1.0)  # 启动不应在未来
        self.assertLess(delta, 86400.0)  # < 1 天


if __name__ == "__main__":
    unittest.main()
