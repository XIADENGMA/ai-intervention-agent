"""R307: notification timeout + cache TTL perf-baseline 第三应用 (cycle-31 t31-2)。

cycle-30 cr60 §5 #A1 推荐 — perf-baseline pattern 第三应用。R296 (时间)
→ R304 (容量/系数) → R305 (CI 流水线) → **R307 (业务超时 + 多层缓存
TTL)**。

================================================================
| Const                                | Value | Source                       |
|--------------------------------------|-------|------------------------------|
| 1. _AS_COMPLETED_TIMEOUT_BUFFER_SECS | 5     | notification_manager.py      |
| 2. _RETRY_DELAY_JITTER_RATIO         | 0.5   | notification_manager.py      |
| 3. _network_security_cache_ttl       | 30.0  | config_manager.py            |
| 4. _section_cache_ttl                | 10.0  | config_manager.py            |
| 5. _SSE_STATS_CACHE_TTL_S            | 1.0   | server.py                    |
| 6. _RECENT_LOGS_CACHE_TTL_S          | 1.0   | server.py                    |
================================================================

锁定理由 (每个 const 单独 review):

1. **_AS_COMPLETED_TIMEOUT_BUFFER_SECONDS = 5**: as_completed 超时 = bark_timeout + 5s.
   改小会造成 bark 推送实际收到但 Python 端已超时, 用户看到"通知失败"
   但实际收到推送 (双重打扰)。改大会让 retry 链等待时间累积超出 SLA。

2. **_RETRY_DELAY_JITTER_RATIO = 0.5**: thundering-herd 防御 jitter 系数,
   实际 delay = retry_delay + Uniform(0, retry_delay * 0.5)。0.5 是
   "够分散 (50% 抖动) 但又不让重试时间不可预测" 的平衡点; 0.1 太集中
   仍有雷群, 1.0 太分散用户感受不到 "重试节奏"。

3. **_network_security_cache_ttl = 30.0**: network_security config (IP
   allowlist/blocklist) 缓存 30s。改小会让每个请求都重新解析 config 文件,
   IP check 慢 10x; 改大会让 config 修改后生效延迟超过用户耐心。

4. **_section_cache_ttl = 10.0**: generic config section 缓存 10s。比
   network_security 短 3x 是因为 generic section 可能被频繁 reload (从
   web UI 改设置), 10s 是 "改完看到生效不会失望" 的边界。

5/6. **_SSE_STATS_CACHE_TTL_S / _RECENT_LOGS_CACHE_TTL_S = 1.0**: SSE
   stats / recent logs 缓存 1s。R236 引入用于防 /metrics 高频 scrape
   (Prometheus 默认 15s scrape 间隔, 多个 scraper 同时拉时 cache 1s 内
   返回同一份 snapshot)。改大会让 stats / logs 看到的实时性变差。

================================================================
| Tests | 维度                                                            |
|-------|-------------------------------------------------------------|
| 6     | 6 个 const 直接锁数值 + 来源文件                                  |
| 3     | meta-lint: section < network_security TTL / SSE stats == recent logs |
| 2     | _AS_COMPLETED_TIMEOUT_BUFFER 在 _execute_provider 中实际使用    |
================================================================
| 11 总计                                                                  |
================================================================

**pattern lineage**: R296 (perf 1st, 时间) → R304 (perf 2nd, 容量/系数) →
R305 (perf 4th app, CI 流水线) → **R307 (perf 5th app, notification 业务
超时 + 缓存 TTL)** — perf pattern 应用域跨度从 "运行时基础设施" 扩展
到 "业务超时" + "多层缓存策略"。
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC = PROJECT_ROOT / "src" / "ai_intervention_agent"
NOTIF_MGR = SRC / "notification_manager.py"
CONFIG_MGR = SRC / "config_manager.py"
SERVER = SRC / "server.py"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


# ============================================================
# 6 个 const 直接锁数值
# ============================================================
class TestNotificationTimeoutConsts(unittest.TestCase):
    """notification_manager.py 内 2 个超时/系数常量"""

    def setUp(self) -> None:
        self.src = _read(NOTIF_MGR)

    def test_as_completed_timeout_buffer_5_seconds(self) -> None:
        """``_AS_COMPLETED_TIMEOUT_BUFFER_SECONDS`` 必须 = 5。"""
        m = re.search(
            r"^_AS_COMPLETED_TIMEOUT_BUFFER_SECONDS\s*=\s*5\b",
            self.src,
            re.MULTILINE,
        )
        self.assertIsNotNone(
            m,
            "R307: _AS_COMPLETED_TIMEOUT_BUFFER_SECONDS 必须 = 5 "
            "(bark_timeout 之上 +5s 等推送回执, 不能改小防双重打扰)",
        )

    def test_retry_delay_jitter_ratio_half(self) -> None:
        """``_RETRY_DELAY_JITTER_RATIO`` 必须 = 0.5 (50% jitter)。"""
        m = re.search(
            r"^_RETRY_DELAY_JITTER_RATIO\s*=\s*0\.5\b",
            self.src,
            re.MULTILINE,
        )
        self.assertIsNotNone(
            m,
            "R307: _RETRY_DELAY_JITTER_RATIO 必须 = 0.5 "
            "(thundering-herd 防御, 50% 抖动 sweet spot)",
        )


class TestConfigCacheTTLConsts(unittest.TestCase):
    """config_manager.py 内 2 个缓存 TTL 常量"""

    def setUp(self) -> None:
        self.src = _read(CONFIG_MGR)

    def test_network_security_cache_ttl_30s(self) -> None:
        """``_network_security_cache_ttl`` 必须 = 30.0 秒。"""
        m = re.search(
            r"self\._network_security_cache_ttl:\s*float\s*=\s*30\.0\b",
            self.src,
        )
        self.assertIsNotNone(
            m,
            "R307: _network_security_cache_ttl 必须 = 30.0 (IP allow/block 解析缓存)",
        )

    def test_section_cache_ttl_10s(self) -> None:
        """``_section_cache_ttl`` 必须 = 10.0 秒。"""
        m = re.search(
            r"self\._section_cache_ttl:\s*float\s*=\s*10\.0\b",
            self.src,
        )
        self.assertIsNotNone(
            m,
            "R307: _section_cache_ttl 必须 = 10.0 (generic config section 缓存)",
        )


class TestServerObservabilityCacheTTL(unittest.TestCase):
    """server.py 内 2 个可观测性缓存 TTL"""

    def setUp(self) -> None:
        self.src = _read(SERVER)

    def test_sse_stats_cache_ttl_1s(self) -> None:
        """``_SSE_STATS_CACHE_TTL_S`` 必须 = 1.0 秒。"""
        m = re.search(
            r"^_SSE_STATS_CACHE_TTL_S:\s*float\s*=\s*1\.0\b",
            self.src,
            re.MULTILINE,
        )
        self.assertIsNotNone(
            m,
            "R307: _SSE_STATS_CACHE_TTL_S 必须 = 1.0 (R236 /metrics scrape 防过载缓存)",
        )

    def test_recent_logs_cache_ttl_1s(self) -> None:
        """``_RECENT_LOGS_CACHE_TTL_S`` 必须 = 1.0 秒。"""
        m = re.search(
            r"^_RECENT_LOGS_CACHE_TTL_S:\s*float\s*=\s*1\.0\b",
            self.src,
            re.MULTILINE,
        )
        self.assertIsNotNone(
            m,
            "R307: _RECENT_LOGS_CACHE_TTL_S 必须 = 1.0 "
            "(R236 recent logs scrape 防过载缓存)",
        )


# ============================================================
# meta-lint: 比例关系
# ============================================================
class TestCacheTTLProportions(unittest.TestCase):
    """缓存 TTL 之间的比例关系语义检查"""

    def setUp(self) -> None:
        self.cfg = _read(CONFIG_MGR)
        self.srv = _read(SERVER)

    def test_section_ttl_less_than_network_security_ttl(self) -> None:
        """``_section_cache_ttl`` (10s) 必须 < ``_network_security_cache_ttl`` (30s)。

        generic section 比 IP allowlist 改动频率高, TTL 应更短。
        """
        sec_m = re.search(r"_section_cache_ttl:\s*float\s*=\s*([\d.]+)", self.cfg)
        net_m = re.search(
            r"_network_security_cache_ttl:\s*float\s*=\s*([\d.]+)", self.cfg
        )
        self.assertIsNotNone(sec_m)
        self.assertIsNotNone(net_m)
        assert sec_m is not None and net_m is not None
        sec = float(sec_m.group(1))
        net = float(net_m.group(1))
        self.assertLess(
            sec,
            net,
            f"R307: section TTL ({sec}) 必须 < network_security TTL ({net}) "
            f"(section 改动频率更高 → TTL 更短)",
        )

    def test_sse_stats_equals_recent_logs_ttl(self) -> None:
        """``_SSE_STATS_CACHE_TTL_S`` 必须 = ``_RECENT_LOGS_CACHE_TTL_S``。

        两者都为 /metrics 等高频 scrape 服务, 保持同步避免不一致 snapshot。
        """
        sse_m = re.search(r"_SSE_STATS_CACHE_TTL_S:\s*float\s*=\s*([\d.]+)", self.srv)
        log_m = re.search(r"_RECENT_LOGS_CACHE_TTL_S:\s*float\s*=\s*([\d.]+)", self.srv)
        self.assertIsNotNone(sse_m)
        self.assertIsNotNone(log_m)
        assert sse_m is not None and log_m is not None
        sse = float(sse_m.group(1))
        log = float(log_m.group(1))
        self.assertEqual(
            sse,
            log,
            f"R307: SSE stats TTL ({sse}) 必须 = recent logs TTL ({log}) "
            f"(都为 /metrics scrape 缓存)",
        )

    def test_observability_ttl_less_than_section_ttl(self) -> None:
        """``_SSE_STATS_CACHE_TTL_S`` (1s) 必须 << ``_section_cache_ttl`` (10s)。

        observability TTL 应远小于 config TTL — metrics 实时性优先,
        config 性能优先。
        """
        sse_m = re.search(r"_SSE_STATS_CACHE_TTL_S:\s*float\s*=\s*([\d.]+)", self.srv)
        sec_m = re.search(r"_section_cache_ttl:\s*float\s*=\s*([\d.]+)", self.cfg)
        assert sse_m is not None and sec_m is not None
        sse = float(sse_m.group(1))
        sec = float(sec_m.group(1))
        self.assertLess(
            sse * 5,
            sec,
            f"R307: observability TTL ({sse}) * 5 必须 < section TTL ({sec}) "
            f"— metrics 实时性优先, config 性能优先",
        )


# ============================================================
# 2 个 const 实际使用点检查
# ============================================================
class TestAsCompletedTimeoutBufferActualUsage(unittest.TestCase):
    """``_AS_COMPLETED_TIMEOUT_BUFFER_SECONDS`` 必须实际用在 timeout=... 中"""

    def setUp(self) -> None:
        self.src = _read(NOTIF_MGR)

    def test_buffer_used_in_bark_timeout_calc(self) -> None:
        """``bark_timeout + _AS_COMPLETED_TIMEOUT_BUFFER_SECONDS`` 必须出现。"""
        m = re.search(
            r"bark_timeout\s*\+\s*_AS_COMPLETED_TIMEOUT_BUFFER_SECONDS",
            self.src,
        )
        self.assertIsNotNone(
            m,
            "R307: bark_timeout + _AS_COMPLETED_TIMEOUT_BUFFER_SECONDS 必须出现 "
            "(否则 const 定义后没被使用 = dead code)",
        )

    def test_retry_delay_jitter_ratio_used_in_random_uniform(self) -> None:
        """``random.uniform(0.0, base_delay * _RETRY_DELAY_JITTER_RATIO)`` 必须出现。"""
        m = re.search(
            r"random\.uniform\(0\.0,\s*base_delay\s*\*\s*_RETRY_DELAY_JITTER_RATIO\)",
            self.src,
        )
        self.assertIsNotNone(
            m,
            "R307: random.uniform(0.0, base_delay * _RETRY_DELAY_JITTER_RATIO) "
            "必须出现 (否则 jitter 系数定义后没生效)",
        )


if __name__ == "__main__":
    unittest.main()
