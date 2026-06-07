"""R290 invariant: 4 个未 lock 的跨源常量统一加 cross-source lock
(R284 第二轮 const audit)。

背景
----
cycle-26 R284 lock 了 ``web_timeout`` (5000ms) 5-source 一致性。cr56 §5
#D 推荐第二轮 audit。本次新增 4 个 const lock (与 R284 同 pattern)：

1. **``bark_timeout``** (10s)，6 source:
   - ``shared_types.NotificationSectionConfig`` Pydantic authoritative
   - ``notification_manager.NotificationConfig.bark_timeout`` class default
   - ``coerce_bark_timeout`` validator fallback (``except: return 10``)
   - ``from_config_file()`` parser: ``cfg.get("bark_timeout", 10)``
   - ``_set_runtime_config()``: 同上
   - ``config.toml.default``: ``bark_timeout = 10``

2. **``retry_count``** (3 retries)，6 source（同 ``bark_timeout`` 结构）:
   - ``shared_types.NotificationSectionConfig``
   - ``notification_manager.NotificationConfig.retry_count``
   - ``coerce_retry_count`` validator fallback
   - 2 个 ``cfg.get("retry_count", 3)`` parser fallback
   - ``config.toml.default``: ``retry_count = 3``

3. **``http_request_timeout``** (30s)，3 source:
   - ``shared_types.WebUISectionConfig``
   - ``service_manager.py`` ``get_compat_config(..., "timeout", 30)``
   - ``config.toml.default``: ``http_request_timeout = 30``

4. **``http_max_retries``** (3 retries)，3 source:
   - ``shared_types.WebUISectionConfig``
   - ``service_manager.py`` ``get_compat_config(..., "max_retries", 3)``
   - ``config.toml.default``: ``http_max_retries = 3``

R284 lock 了 backend timeout fallback drift；R290 把同 pattern 扩展到 4
个 retry / timeout const，覆盖 18 处 hardcode site（6+6+3+3）。

drift risk: 改 Pydantic default 但忘 TOML 模板 → 新装用户拿到旧默认；
忘改 fallback parser → cfg 缺 key 时返回旧值；忘改 validator return →
非法值 fallback 错。
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC = REPO_ROOT / "src" / "ai_intervention_agent"
SHARED_TYPES = SRC / "shared_types.py"
NOTIFICATION_MANAGER = SRC / "notification_manager.py"
SERVICE_MANAGER = SRC / "service_manager.py"
CONFIG_TOML_DEFAULT = REPO_ROOT / "config.toml.default"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


class TestBarkTimeout6Source(unittest.TestCase):
    """``bark_timeout`` (10s) 必须在 6 个 source 保持一致。"""

    EXPECTED = 10

    def test_shared_types_pydantic_default(self) -> None:
        """``shared_types.NotificationSectionConfig.bark_timeout`` Pydantic = 10。

        regex 必须匹配两个 close paren（``_clamp_int(...)`` 的 + 外层
        ``BeforeValidator(...)`` 的）+ ``]`` + ``= 10``。
        """
        src = _read(SHARED_TYPES)
        self.assertRegex(
            src,
            r"bark_timeout\s*:\s*Annotated\[.*?_clamp_int\(\s*\d+\s*,\s*\d+\s*,\s*10\s*\)\)\s*\]\s*=\s*10",
            "shared_types.NotificationSectionConfig.bark_timeout must default = 10",
        )

    def test_notification_manager_class_default(self) -> None:
        """``notification_manager.NotificationConfig.bark_timeout: int = 10``。"""
        src = _read(NOTIFICATION_MANAGER)
        self.assertRegex(
            src,
            r"bark_timeout\s*:\s*int\s*=\s*10\b",
            "notification_manager.NotificationConfig.bark_timeout class default must = 10",
        )

    def test_validator_fallback(self) -> None:
        """``coerce_bark_timeout`` 的 except 分支必须 ``return 10``。"""
        src = _read(NOTIFICATION_MANAGER)
        match = re.search(
            r"def\s+coerce_bark_timeout\([^)]*\)[^:]*:.*?except.*?return\s+(\d+)",
            src,
            re.DOTALL,
        )
        self.assertIsNotNone(match, "找不到 coerce_bark_timeout 的 except return")
        assert match is not None
        self.assertEqual(
            int(match.group(1)),
            self.EXPECTED,
            "coerce_bark_timeout except fallback must return 10",
        )

    def test_from_config_file_parser_fallback(self) -> None:
        """``cfg.get("bark_timeout", 10)`` 必须以 10 兜底（至少 1 处）。"""
        src = _read(NOTIFICATION_MANAGER)
        matches = re.findall(r'cfg\.get\(\s*"bark_timeout"\s*,\s*(\d+)\s*\)', src)
        self.assertGreaterEqual(
            len(matches),
            1,
            'notification_manager 必须至少有 1 处 cfg.get("bark_timeout", N) fallback parser',
        )
        for m in matches:
            self.assertEqual(
                int(m),
                self.EXPECTED,
                f'cfg.get("bark_timeout", {m}) fallback 必须 = 10',
            )

    def test_config_toml_default(self) -> None:
        """``config.toml.default`` ``bark_timeout = 10`` (行首)。

        ``unittest.assertRegex`` 不支持 MULTILINE 旗，所以用显式 ``re.search``。
        """
        src = _read(CONFIG_TOML_DEFAULT)
        match = re.search(r"^bark_timeout\s*=\s*10\b", src, re.MULTILINE)
        self.assertIsNotNone(match, "config.toml.default bark_timeout line missing")


class TestRetryCount6Source(unittest.TestCase):
    """``retry_count`` (3) 必须在 6 个 source 保持一致。"""

    EXPECTED = 3

    def test_shared_types_pydantic_default(self) -> None:
        src = _read(SHARED_TYPES)
        self.assertRegex(
            src,
            r"retry_count\s*:\s*Annotated\[.*?_clamp_int\(\s*\d+\s*,\s*\d+\s*,\s*3\s*\)\)\s*\]\s*=\s*3",
            "shared_types.NotificationSectionConfig.retry_count Pydantic = 3",
        )

    def test_notification_manager_class_default(self) -> None:
        src = _read(NOTIFICATION_MANAGER)
        self.assertRegex(
            src,
            r"retry_count\s*:\s*int\s*=\s*3\b",
            "NotificationConfig.retry_count class default must = 3",
        )

    def test_validator_fallback(self) -> None:
        src = _read(NOTIFICATION_MANAGER)
        match = re.search(
            r"def\s+coerce_retry_count\([^)]*\)[^:]*:.*?except.*?return\s+(\d+)",
            src,
            re.DOTALL,
        )
        self.assertIsNotNone(match)
        assert match is not None
        self.assertEqual(int(match.group(1)), self.EXPECTED)

    def test_parser_fallbacks(self) -> None:
        src = _read(NOTIFICATION_MANAGER)
        matches = re.findall(r'cfg\.get\(\s*"retry_count"\s*,\s*(\d+)\s*\)', src)
        self.assertGreaterEqual(
            len(matches),
            1,
            'notification_manager 必须至少有 1 处 cfg.get("retry_count", N) fallback',
        )
        for m in matches:
            self.assertEqual(
                int(m),
                self.EXPECTED,
                f'cfg.get("retry_count", {m}) fallback 必须 = 3',
            )

    def test_config_toml_default(self) -> None:
        src = _read(CONFIG_TOML_DEFAULT)
        match = re.search(r"^retry_count\s*=\s*3\b", src, re.MULTILINE)
        self.assertIsNotNone(match, "config.toml.default retry_count line missing")


class TestHttpRequestTimeout3Source(unittest.TestCase):
    """``http_request_timeout`` (30s) 必须在 3 个 source 保持一致。"""

    EXPECTED = 30

    def test_shared_types_pydantic_default(self) -> None:
        src = _read(SHARED_TYPES)
        self.assertRegex(
            src,
            r"http_request_timeout\s*:\s*Annotated\[.*?_clamp_int\(\s*\d+\s*,\s*\d+\s*,\s*30\s*\)\)\s*\]\s*=\s*30",
            "shared_types.WebUISectionConfig.http_request_timeout Pydantic = 30",
        )

    def test_service_manager_compat_fallback(self) -> None:
        """``service_manager.py`` 通过 ``get_compat_config(..., "timeout", 30)`` 兜底。"""
        src = _read(SERVICE_MANAGER)
        self.assertRegex(
            src,
            r'get_compat_config\([^,]+,\s*"http_request_timeout"\s*,\s*"timeout"\s*,\s*30\s*\)',
            "service_manager.py must call get_compat_config(..., 'http_request_timeout', 'timeout', 30)",
        )

    def test_config_toml_default(self) -> None:
        src = _read(CONFIG_TOML_DEFAULT)
        match = re.search(r"^http_request_timeout\s*=\s*30\b", src, re.MULTILINE)
        self.assertIsNotNone(
            match,
            "config.toml.default http_request_timeout line missing",
        )


class TestHttpMaxRetries3Source(unittest.TestCase):
    """``http_max_retries`` (3) 必须在 3 个 source 保持一致。"""

    EXPECTED = 3

    def test_shared_types_pydantic_default(self) -> None:
        src = _read(SHARED_TYPES)
        self.assertRegex(
            src,
            r"http_max_retries\s*:\s*Annotated\[.*?_clamp_int\(\s*\d+\s*,\s*\d+\s*,\s*3\s*\)\)\s*\]\s*=\s*3",
            "shared_types.WebUISectionConfig.http_max_retries Pydantic = 3",
        )

    def test_service_manager_compat_fallback(self) -> None:
        src = _read(SERVICE_MANAGER)
        self.assertRegex(
            src,
            r'get_compat_config\([^,]+,\s*"http_max_retries"\s*,\s*"max_retries"\s*,\s*3\s*\)',
            "service_manager.py must call get_compat_config(..., 'http_max_retries', 'max_retries', 3)",
        )

    def test_config_toml_default(self) -> None:
        src = _read(CONFIG_TOML_DEFAULT)
        match = re.search(r"^http_max_retries\s*=\s*3\b", src, re.MULTILINE)
        self.assertIsNotNone(
            match,
            "config.toml.default http_max_retries line missing",
        )


class TestTestFileDocumentsAuthoritativeSources(unittest.TestCase):
    """meta-doc: 本测试文件 docstring 必须列出 4 个 const 的所有 source（便于
    后续 R\\d+ 第三轮扩展时知道在哪里更新）。"""

    def test_docstring_mentions_all_4_consts(self) -> None:
        src = _read(Path(__file__))
        for const in [
            "bark_timeout",
            "retry_count",
            "http_request_timeout",
            "http_max_retries",
        ]:
            self.assertIn(
                const,
                src,
                f"R290 test docstring must list `{const}` as one of the 4 audit-2 consts",
            )

    def test_docstring_mentions_r284_lineage(self) -> None:
        """必须明确标记 R284 第二轮"。"""
        src = _read(Path(__file__))
        self.assertIn(
            "R284",
            src,
            "R290 test docstring must reference R284 (cycle-26) as the 第一轮 anchor",
        )


if __name__ == "__main__":
    unittest.main()
