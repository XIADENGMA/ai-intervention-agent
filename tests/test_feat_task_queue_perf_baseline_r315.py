"""R315 invariant: task_queue.py lifecycle 关键常量 perf-baseline (v3.6
perf-baseline pattern 6th app)。

背景
----
v3.6 perf-baseline pattern 应用历史:
- 1st: R296 (cr59) — 5 hot-path 时间常量 (SSE/cleanup/throttle/JS health)
- 2nd: R304 (cr60) — SSE bus 6 buffer/cap 常量 + JS backoff 系数
- 3rd: R305 (cr60) — CI ``pytest-xdist`` 流水线 (域跨界)
- 4th: R307 (cr61) — Notification timeout + multi-layer cache TTL
- 5th: R314 (cr61+4) — fetch retry backoff sequence (与决策三层同 commit)
- **6th: R315 (cycle-32 #A2, this)** — task_queue 锁监控 + prompt size guard

R315 锁定的 4 个模块级常量
--------------------------
``src/ai_intervention_agent/task_queue.py`` 顶部有 4 个直接影响 task
lifecycle 性能 / 安全的常量:

1. ``_PROMPT_WARN_BYTES = 6 * 1024 * 1024`` (6 MB) — prompt 太大时
   warn 阈值, 触发 logger.warning + 截断
2. ``_PROMPT_REJECT_BYTES = 10 * 1024 * 1024`` (10 MB) — prompt 强制
   拒绝阈值, 防 OOM / OOMKilled
3. ``_LOCK_WATCHDOG_TIMEOUT_S = 30.0`` — 单次 write lock acquire+hold
   上限, 超过会 dump 全线程栈到日志
4. ``_LOCK_WATCHDOG_SCAN_INTERVAL_S = 5.0`` — watchdog 扫描周期, 决定
   最快多久能发现死锁

这 4 个常量都满足 perf-baseline pattern 的判别条件:
- 值有非平凡设计依据 (docstring 详细解释为什么是这个数字)
- 改动会**silently** 影响性能 / 安全 / SLA
- 没有显式 CI / runtime 报警, 静默退化

R315 invariant
--------------
- Layer 1 字面量精确锁:
  * 4 个常量名称 + 类型 + 字面量值精确锁定
  * meta-lint: ``_PROMPT_REJECT_BYTES > _PROMPT_WARN_BYTES`` (reject 必须 > warn)
  * meta-lint: ``_LOCK_WATCHDOG_TIMEOUT_S / _LOCK_WATCHDOG_SCAN_INTERVAL_S
    >= 5`` (扫描频次足够多, 至少能扫到 5 次 timeout)
  * meta-lint: ``_PROMPT_WARN_BYTES / _PROMPT_REJECT_BYTES`` 都是 ``* 1024 * 1024``
    形式 (人类可读 MB), 防止改成 hard literal 失去单位语义
- Layer 2 docstring 文档化:
  * 4 个常量都必须有非空 docstring 解释为什么是这个数
- R315 lineage marker (与 R296/R304/R305/R307/R314 串联)

pattern lineage 总结
-------------------
perf-baseline pattern 域跨度:
- R296: SSE / cleanup / throttle (运行时基础设施时间)
- R304: SSE bus 容量 + JS backoff 系数 (容量 + 系数)
- R305: CI pytest-xdist 配置 (toolchain / 流水线)
- R307: notification timeout + cache TTL (业务超时 + 缓存策略)
- R314: fetch retry backoff (网络抖动重试序列)
- **R315: task_queue lock watchdog + prompt size guard** (task lifecycle
  锁 + safety guard)

至 R315, perf-baseline pattern 完全覆盖了从 "基础设施" → "业务运行时" →
"工具链 CI" → "task lifecycle 安全" 的全 domain stack。
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_PY = REPO_ROOT / "src" / "ai_intervention_agent" / "task_queue.py"


# Expected baseline (locked by R315)
EXPECTED_PROMPT_WARN_BYTES = 6 * 1024 * 1024  # 6 MB
EXPECTED_PROMPT_REJECT_BYTES = 10 * 1024 * 1024  # 10 MB
EXPECTED_LOCK_WATCHDOG_TIMEOUT_S = 30.0
EXPECTED_LOCK_WATCHDOG_SCAN_INTERVAL_S = 5.0


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


# ============================================================================
# Layer 1: 4 个常量字面量精确锁
# ============================================================================


class TestPromptSizeGuardConstants(unittest.TestCase):
    """Layer 1: prompt size guard 2 常量 (_PROMPT_WARN_BYTES + _PROMPT_REJECT_BYTES)。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.src = _read(SRC_PY)

    def test_prompt_warn_bytes_constant_exists(self) -> None:
        """R315-L1: ``_PROMPT_WARN_BYTES`` 必须存在, type ``int``, value = 6 MB。"""
        m = re.search(
            r"^_PROMPT_WARN_BYTES\s*:\s*int\s*=\s*(\d+)\s*\*\s*1024\s*\*\s*1024\b",
            self.src,
            re.MULTILINE,
        )
        self.assertIsNotNone(
            m,
            "R315-L1: 必须有 ``_PROMPT_WARN_BYTES: int = N * 1024 * 1024`` 形式声明",
        )
        assert m is not None
        mb_value = int(m.group(1))
        self.assertEqual(
            mb_value * 1024 * 1024,
            EXPECTED_PROMPT_WARN_BYTES,
            f"R315-L1: _PROMPT_WARN_BYTES 必须 = 6 MB, 实际 {mb_value} MB",
        )

    def test_prompt_reject_bytes_constant_exists(self) -> None:
        """R315-L1: ``_PROMPT_REJECT_BYTES`` 必须存在, type ``int``, value = 10 MB。"""
        m = re.search(
            r"^_PROMPT_REJECT_BYTES\s*:\s*int\s*=\s*(\d+)\s*\*\s*1024\s*\*\s*1024\b",
            self.src,
            re.MULTILINE,
        )
        self.assertIsNotNone(
            m,
            "R315-L1: 必须有 ``_PROMPT_REJECT_BYTES: int = N * 1024 * 1024`` 形式声明",
        )
        assert m is not None
        mb_value = int(m.group(1))
        self.assertEqual(
            mb_value * 1024 * 1024,
            EXPECTED_PROMPT_REJECT_BYTES,
            f"R315-L1: _PROMPT_REJECT_BYTES 必须 = 10 MB, 实际 {mb_value} MB",
        )

    def test_reject_must_be_greater_than_warn(self) -> None:
        """R315-L1 meta-lint: reject 阈值必须 > warn 阈值 (semantic invariant)。"""
        warn_m = re.search(
            r"_PROMPT_WARN_BYTES\s*:\s*int\s*=\s*(\d+)\s*\*\s*1024\s*\*\s*1024",
            self.src,
        )
        reject_m = re.search(
            r"_PROMPT_REJECT_BYTES\s*:\s*int\s*=\s*(\d+)\s*\*\s*1024\s*\*\s*1024",
            self.src,
        )
        assert warn_m is not None and reject_m is not None
        warn_mb = int(warn_m.group(1))
        reject_mb = int(reject_m.group(1))
        self.assertGreater(
            reject_mb,
            warn_mb,
            f"R315-L1 meta-lint: REJECT ({reject_mb} MB) 必须 > WARN ({warn_mb} MB), "
            f"否则 reject 在 warn 之前触发, warn 永远不会发出 → 静默截断",
        )

    def test_prompt_size_uses_kb_mb_form_not_hard_literal(self) -> None:
        """R315-L1 meta-lint: 必须用 ``N * 1024 * 1024`` 而非 hard literal (人类可读 MB)。"""
        # 测试两个常量都不能是单纯数字字面量 (e.g. = 6291456)
        for name in ("_PROMPT_WARN_BYTES", "_PROMPT_REJECT_BYTES"):
            with self.subTest(constant=name):
                # 反断言: 不能匹配纯数字 (没有 * 1024 * 1024)
                hard_literal_match = re.search(
                    rf"^{re.escape(name)}\s*:\s*int\s*=\s*(\d+)\s*(?:#|$)",
                    self.src,
                    re.MULTILINE,
                )
                self.assertIsNone(
                    hard_literal_match,
                    f"R315-L1 meta-lint: {name} 不能是 hard literal (要用 N*1024*1024 保留 MB 单位语义)",
                )


class TestLockWatchdogConstants(unittest.TestCase):
    """Layer 1: lock watchdog 2 常量 (_LOCK_WATCHDOG_TIMEOUT_S + _LOCK_WATCHDOG_SCAN_INTERVAL_S)。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.src = _read(SRC_PY)

    def test_lock_watchdog_timeout_constant_exists(self) -> None:
        """R315-L1: ``_LOCK_WATCHDOG_TIMEOUT_S: float = 30.0``。"""
        m = re.search(
            r"^_LOCK_WATCHDOG_TIMEOUT_S\s*:\s*float\s*=\s*([\d.]+)",
            self.src,
            re.MULTILINE,
        )
        self.assertIsNotNone(
            m, "R315-L1: 必须有 ``_LOCK_WATCHDOG_TIMEOUT_S: float = ...``"
        )
        assert m is not None
        value = float(m.group(1))
        self.assertEqual(
            value,
            EXPECTED_LOCK_WATCHDOG_TIMEOUT_S,
            f"R315-L1: _LOCK_WATCHDOG_TIMEOUT_S 必须 = 30.0, 实际 {value}",
        )

    def test_lock_watchdog_scan_interval_constant_exists(self) -> None:
        """R315-L1: ``_LOCK_WATCHDOG_SCAN_INTERVAL_S: float = 5.0``。"""
        m = re.search(
            r"^_LOCK_WATCHDOG_SCAN_INTERVAL_S\s*:\s*float\s*=\s*([\d.]+)",
            self.src,
            re.MULTILINE,
        )
        self.assertIsNotNone(
            m, "R315-L1: 必须有 ``_LOCK_WATCHDOG_SCAN_INTERVAL_S: float = ...``"
        )
        assert m is not None
        value = float(m.group(1))
        self.assertEqual(
            value,
            EXPECTED_LOCK_WATCHDOG_SCAN_INTERVAL_S,
            f"R315-L1: _LOCK_WATCHDOG_SCAN_INTERVAL_S 必须 = 5.0, 实际 {value}",
        )

    def test_scan_interval_supports_at_least_5_checks_per_timeout(self) -> None:
        """R315-L1 meta-lint: TIMEOUT / SCAN_INTERVAL >= 5 (扫描频次足够多, 死锁可见)。"""
        timeout_m = re.search(
            r"_LOCK_WATCHDOG_TIMEOUT_S\s*:\s*float\s*=\s*([\d.]+)", self.src
        )
        interval_m = re.search(
            r"_LOCK_WATCHDOG_SCAN_INTERVAL_S\s*:\s*float\s*=\s*([\d.]+)", self.src
        )
        assert timeout_m is not None and interval_m is not None
        ratio = float(timeout_m.group(1)) / float(interval_m.group(1))
        self.assertGreaterEqual(
            ratio,
            5.0,
            f"R315-L1 meta-lint: TIMEOUT/INTERVAL = {ratio} < 5, "
            f"扫描频次不够 (理想 >= 5, 实际 {ratio:.1f}); 死锁最坏延迟检测 = TIMEOUT+INTERVAL",
        )

    def test_constants_actually_consumed_by_watchdog_code(self) -> None:
        """R315-L1: 两个 watchdog 常量都必须被实际使用 (防 dead constant)。"""
        # _LOCK_WATCHDOG_TIMEOUT_S 必须出现至少 2 次 (定义 + 使用)
        timeout_count = len(re.findall(r"_LOCK_WATCHDOG_TIMEOUT_S\b", self.src))
        self.assertGreater(
            timeout_count,
            1,
            f"R315-L1: _LOCK_WATCHDOG_TIMEOUT_S 必须被实际使用, 出现 {timeout_count} 次",
        )
        interval_count = len(re.findall(r"_LOCK_WATCHDOG_SCAN_INTERVAL_S\b", self.src))
        self.assertGreater(
            interval_count,
            1,
            f"R315-L1: _LOCK_WATCHDOG_SCAN_INTERVAL_S 必须被实际使用, 出现 {interval_count} 次",
        )


# ============================================================================
# Layer 2: 文档化要求 (4 个常量都必须有 docstring)
# ============================================================================


class TestPerfBaselineConstantsHaveDocumentation(unittest.TestCase):
    """Layer 2: 每个 perf-baseline 常量必须有非空 docstring 解释设计依据。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.src = _read(SRC_PY)

    def _extract_const_following_docstring(self, const_name: str) -> str:
        """提取紧跟在常量声明后的 docstring (Python 模块级常量惯用形式)。"""
        # 匹配: const_name : type = value\n"""docstring"""
        # 或者: const_name : type = value\n"""docstring..."""
        pattern = re.compile(
            rf"^{re.escape(const_name)}\s*:\s*\w+\s*=\s*[^\n]+\n\s*\"\"\"([\s\S]*?)\"\"\"",
            re.MULTILINE,
        )
        m = pattern.search(self.src)
        return m.group(1).strip() if m else ""

    def test_prompt_warn_bytes_has_docstring(self) -> None:
        """R315-L2: ``_PROMPT_WARN_BYTES`` 必须有 docstring 解释 6 MB 选择依据。"""
        doc = self._extract_const_following_docstring("_PROMPT_WARN_BYTES")
        self.assertTrue(
            doc,
            "R315-L2: _PROMPT_WARN_BYTES 必须紧跟 docstring 解释设计依据",
        )
        self.assertGreater(
            len(doc),
            30,
            f"R315-L2: _PROMPT_WARN_BYTES docstring 太短 ({len(doc)} 字符), 缺乏设计依据",
        )

    def test_prompt_reject_bytes_has_docstring(self) -> None:
        """R315-L2: ``_PROMPT_REJECT_BYTES`` 必须有 docstring。"""
        doc = self._extract_const_following_docstring("_PROMPT_REJECT_BYTES")
        self.assertTrue(
            doc,
            "R315-L2: _PROMPT_REJECT_BYTES 必须紧跟 docstring 解释设计依据",
        )

    def test_lock_watchdog_timeout_has_docstring(self) -> None:
        """R315-L2: ``_LOCK_WATCHDOG_TIMEOUT_S`` 必须有 docstring 解释 30s 选择依据。"""
        doc = self._extract_const_following_docstring("_LOCK_WATCHDOG_TIMEOUT_S")
        self.assertTrue(
            doc,
            "R315-L2: _LOCK_WATCHDOG_TIMEOUT_S 必须紧跟 docstring",
        )

    def test_lock_watchdog_scan_interval_has_docstring(self) -> None:
        """R315-L2: ``_LOCK_WATCHDOG_SCAN_INTERVAL_S`` 必须有 docstring。"""
        doc = self._extract_const_following_docstring("_LOCK_WATCHDOG_SCAN_INTERVAL_S")
        self.assertTrue(
            doc,
            "R315-L2: _LOCK_WATCHDOG_SCAN_INTERVAL_S 必须紧跟 docstring",
        )


# ============================================================================
# R315 lineage marker
# ============================================================================


class TestR315MarkerPresent(unittest.TestCase):
    """R315 lineage marker。"""

    def test_test_file_contains_lineage_explanation(self) -> None:
        """本测试文件 docstring 必须含 R315 + perf-baseline + 6th + 前序 R 编号链。"""
        src = _read(Path(__file__))
        self.assertIn("R315", src, "R315 marker 应在测试 docstring")
        self.assertIn("perf-baseline", src, "R315 应说明 perf-baseline lineage")
        self.assertIn("6th", src, "R315 应说明这是 perf-baseline pattern 6th app")
        # 必须引用前 5 次 R 编号 (R296, R304, R305, R307, R314)
        for r_num in ("R296", "R304", "R305", "R307", "R314"):
            with self.subTest(prior_r=r_num):
                self.assertIn(
                    r_num,
                    src,
                    f"R315 应引用 {r_num} (perf-baseline 前序 application)",
                )


if __name__ == "__main__":
    unittest.main()
