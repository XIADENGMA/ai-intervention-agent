"""``scripts/minify_assets.py`` helpers 单元测试。

历史背景：``--check`` 模式过去用 mtime (``needs_minification``) 判定漂移，
在 ``git checkout`` / fresh clone 之后 mtime 完全不可控，导致 CI 100% 误报。
v1.5.23 引入 ``content_drifts`` 改为字节比较，本文件锁住其行为不再回退。

覆盖：
- ``needs_minification``：仅作"何时跳过 minify 工作"的增量启发式
- ``content_drifts``：``--check`` 模式的漂移真相，纯内容比较
"""

from __future__ import annotations

import os
import sys
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# 必须在 sys.path 调整后再 import；与 tests/test_i18n_duplicate_values.py 同形。
from scripts.minify_assets import content_drifts, needs_minification, process_directory


def _identity(content: str) -> str:
    """测试用 minify 函数：原样返回，模拟"已经是最优的内容"。"""
    return content


def _uppercase(content: str) -> str:
    """测试用 minify 函数：大写转换，模拟可识别变换。"""
    return content.upper()


def _broken(_content: str) -> str:
    """测试用 minify 函数：抛异常，模拟 rjsmin 找不到/损坏的情况。"""
    raise RuntimeError("simulated minifier failure")


class TestContentDrifts(unittest.TestCase):
    """``content_drifts`` 必须用字节比较，绕开 mtime 不稳定。"""

    def setUp(self) -> None:
        self._tmp_ctx = TemporaryDirectory()
        self.tmp = Path(self._tmp_ctx.name)
        self.addCleanup(self._tmp_ctx.cleanup)

    def _make(self, name: str, body: str) -> Path:
        path = self.tmp / name
        path.write_text(body, encoding="utf-8")
        return path

    def test_dst_missing_drifts(self) -> None:
        """目标文件不存在 → 视为漂移（首次 minify 触发器）。"""
        src = self._make("a.js", "console.log(1)")
        dst = self.tmp / "a.min.js"
        self.assertTrue(content_drifts(src, dst, _identity))

    def test_content_matches_no_drift(self) -> None:
        """``minify(src) == dst.read_text()`` → 无漂移。"""
        src = self._make("a.js", "BODY")
        dst = self._make("a.min.js", "BODY")
        self.assertFalse(content_drifts(src, dst, _identity))

    def test_content_mismatch_drifts(self) -> None:
        """``minify(src) != dst.read_text()`` → 漂移。"""
        src = self._make("a.js", "body")
        dst = self._make("a.min.js", "body")
        self.assertTrue(content_drifts(src, dst, _uppercase))

    def test_minify_failure_treated_as_drift(self) -> None:
        """minifier 抛异常 → 必须视为漂移（CI 暴露问题，不沉默通过）。

        典型场景：``rjsmin`` 未安装 / 升级后接口变了。如果默认通过，
        会让 v1.5.x 历史上吃过的"silent fix" 风险卷土重来。
        """
        src = self._make("a.js", "x")
        dst = self._make("a.min.js", "x")
        self.assertTrue(content_drifts(src, dst, _broken))

    def test_drift_invariant_to_mtime(self) -> None:
        """同内容 src/dst 的 mtime 任意排列都不应触发漂移。

        ``git checkout`` 把工作树 mtime 全部重置为 checkout 时刻，
        实测 fresh runner 上 src/dst mtime 谁先谁后都不可控。
        本断言锁住"内容判定与 mtime 完全脱钩"。
        """
        src = self._make("a.js", "X")
        dst = self._make("a.min.js", "X")
        old_time = time.time() - 3600
        new_time = time.time()
        os.utime(src, (old_time, old_time))
        os.utime(dst, (new_time, new_time))
        self.assertFalse(content_drifts(src, dst, _identity))
        os.utime(src, (new_time, new_time))
        os.utime(dst, (old_time, old_time))
        self.assertFalse(content_drifts(src, dst, _identity))


class TestNeedsMinificationIsHeuristicOnly(unittest.TestCase):
    """``needs_minification`` 必须仅作增量构建的 mtime 启发式，不能用于 fail 判定。

    这条断言反向锁住"未来若有人误把 needs_minification 接进 ``--check`` 路径，
    覆盖率会立即暴露 mtime drift 误报"。
    """

    def setUp(self) -> None:
        self._tmp_ctx = TemporaryDirectory()
        self.tmp = Path(self._tmp_ctx.name)
        self.addCleanup(self._tmp_ctx.cleanup)

    def test_dst_missing_returns_true(self) -> None:
        src = self.tmp / "a.js"
        src.write_text("x", encoding="utf-8")
        dst = self.tmp / "a.min.js"
        self.assertTrue(needs_minification(src, dst))

    def test_src_newer_returns_true(self) -> None:
        """同内容、src mtime 更新 → 报告"需要"——这正是 git checkout 后误报的根源。"""
        src = self.tmp / "a.js"
        dst = self.tmp / "a.min.js"
        src.write_text("X", encoding="utf-8")
        dst.write_text("X", encoding="utf-8")
        old_time = time.time() - 3600
        new_time = time.time()
        os.utime(dst, (old_time, old_time))
        os.utime(src, (new_time, new_time))
        self.assertTrue(needs_minification(src, dst))
        self.assertFalse(content_drifts(src, dst, _identity))


class TestDefaultMinifyRepairsContentDrift(unittest.TestCase):
    """默认生成模式也要修复内容漂移，不能只依赖 mtime 启发式。"""

    def setUp(self) -> None:
        self._tmp_ctx = TemporaryDirectory()
        self.tmp = Path(self._tmp_ctx.name)
        self.addCleanup(self._tmp_ctx.cleanup)

    def test_default_mode_repairs_drift_even_when_dst_mtime_is_newer(self) -> None:
        src = self.tmp / "a.js"
        dst = self.tmp / "a.min.js"
        src.write_text("body", encoding="utf-8")
        dst.write_text("stale", encoding="utf-8")

        old_time = time.time() - 3600
        new_time = time.time()
        os.utime(src, (old_time, old_time))
        os.utime(dst, (new_time, new_time))

        process_directory(self.tmp, "js", _uppercase, check_only=False, force=False)

        self.assertEqual(
            dst.read_text(encoding="utf-8"),
            "BODY",
            "默认生成模式不能只看 mtime；否则 --check 发现的内容漂移无法被普通生成修复",
        )


if __name__ == "__main__":
    unittest.main()
