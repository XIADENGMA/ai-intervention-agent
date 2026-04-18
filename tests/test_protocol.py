"""protocol.py 单元测试。

目标：
- 锁定 PROTOCOL_VERSION 为语义化版本
- 锁定 capabilities 返回字段集合（结构变更即失败，强制同步更新客户端契约）
- 锁定 clock 的单位与单调性（毫秒整数）
"""

from __future__ import annotations

import time
import unittest

from protocol import PROTOCOL_VERSION, get_capabilities, get_server_clock


class TestProtocolVersion(unittest.TestCase):
    def test_is_semver_three_parts(self):
        parts = PROTOCOL_VERSION.split(".")
        self.assertEqual(
            len(parts), 3, f"PROTOCOL_VERSION={PROTOCOL_VERSION!r} 必须是三段 semver"
        )
        for p in parts:
            self.assertTrue(p.isdigit(), f"semver 段 {p!r} 应为纯数字")

    def test_is_string(self):
        self.assertIsInstance(PROTOCOL_VERSION, str)


class TestGetCapabilities(unittest.TestCase):
    def test_basic_shape(self):
        caps = get_capabilities("1.2.3")
        self.assertEqual(caps["protocol_version"], PROTOCOL_VERSION)
        self.assertEqual(caps["server_version"], "1.2.3")
        self.assertEqual(caps["build_id"], "")
        self.assertIsInstance(caps["features"], dict)

    def test_empty_server_version_falls_back(self):
        caps = get_capabilities("")
        self.assertEqual(caps["server_version"], "unknown")

    def test_build_id_passthrough(self):
        caps = get_capabilities("1.0.0", build_id="abc1234")
        self.assertEqual(caps["build_id"], "abc1234")

    def test_extra_features_merge(self):
        caps = get_capabilities("1.0.0", extra_features={"experiment_x": True})
        self.assertTrue(caps["features"]["experiment_x"])
        self.assertIn("sse", caps["features"], "基线 feature 不应被覆盖")

    def test_extra_features_can_override(self):
        caps = get_capabilities("1.0.0", extra_features={"sse": False})
        self.assertFalse(caps["features"]["sse"])

    def test_baseline_feature_keys_are_stable(self):
        """核心 feature key 名不应变化：这是前后端契约锁。"""
        caps = get_capabilities("1.0.0")
        expected = {"sse", "polling", "multi_task", "capabilities_endpoint", "clock"}
        self.assertTrue(
            expected.issubset(caps["features"].keys()),
            f"features 缺少基线键: expected⊂{expected}, got={set(caps['features'].keys())}",
        )

    def test_all_fields_json_serializable(self):
        import json

        caps = get_capabilities("1.0.0", build_id="x")
        json.dumps(caps)


class TestGetServerClock(unittest.TestCase):
    def test_returns_two_int_fields(self):
        clock = get_server_clock()
        self.assertIn("time_ms", clock)
        self.assertIn("monotonic_ms", clock)
        self.assertIsInstance(clock["time_ms"], int)
        self.assertIsInstance(clock["monotonic_ms"], int)

    def test_wall_clock_near_python_time(self):
        before = int(time.time() * 1000)
        clock = get_server_clock()
        after = int(time.time() * 1000)
        self.assertGreaterEqual(clock["time_ms"], before - 5)
        self.assertLessEqual(clock["time_ms"], after + 5)

    def test_monotonic_is_non_negative_and_monotonic(self):
        c1 = get_server_clock()
        time.sleep(0.002)
        c2 = get_server_clock()
        self.assertGreaterEqual(c1["monotonic_ms"], 0)
        self.assertGreaterEqual(c2["monotonic_ms"], c1["monotonic_ms"])


if __name__ == "__main__":
    unittest.main()
