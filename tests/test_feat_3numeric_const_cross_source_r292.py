"""R292 invariant: 3 个 numeric const 第三轮 cross-source audit (R290 spillover lock)。

背景
----
cycle-27 R290 锁了 4 个 retry / timeout const (bark_timeout / retry_count /
http_request_timeout / http_max_retries)，cr57 §5 #A 推荐第三轮 audit。
R292 锁定 3 个新 numeric const：

1. **``retry_delay``** (notification, 2s)，**7 source**:
   - ``shared_types.NotificationSectionConfig.retry_delay`` Pydantic
   - ``notification_manager.NotificationConfig.retry_delay = 2`` class default
   - ``coerce_retry_delay`` validator fallback (``return 2``)
   - ``from_config_file()`` parser: ``cfg.get("retry_delay", 2)``
   - ``_set_runtime_config()``: 同上
   - ``_schedule_retry`` 内 ``getattr(self.config, "retry_delay", 2)`` 运行时兜底
   - ``config.toml.default``: ``retry_delay = 2``

2. **``sound_volume``** (notification, 80 int ↔ 0.8 float)，**7 source**:
   - ``shared_types.NotificationSectionConfig.sound_volume`` Pydantic = 80
   - ``notification_manager.NotificationConfig.sound_volume: float = 0.8`` (内部 0-1 range)
   - ``from_config_file()``: ``cfg.get("sound_volume", 80) / 100.0``
   - ``_set_runtime_config()``: 同上
   - ``save_config()``: ``round(self.config.sound_volume * 100)`` (反向转换回 80)
   - ``web_ui_routes/notification.py::normalize_sound_volume``: ``int(...get("sound_volume", 80))``
   - ``config.toml.default``: ``sound_volume = 80``
   - 特殊性：0-100 int ↔ 0.0-1.0 float 双向转换，需要 lock 两端 default 一致

3. **``http_retry_delay``** (web_ui HTTP, 1.0s)，**5 source**:
   - ``shared_types.WebUISectionConfig.http_retry_delay`` Pydantic = 1.0
   - ``server_config.WebUIConfig.retry_delay = 1.0`` (另一个 model 同语义)
   - ``server_config.clamp_retry_delay`` validator (无 fallback default，纯 clamp)
   - ``service_manager.py``: ``get_compat_config(..., "retry_delay", 1.0)``
   - ``config.toml.default``: ``http_retry_delay = 1.0``

R290 总 source 18 处 → R292 新增 19 处 (7+7+5)。两轮 cumulative: 37 source
sites locked。
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC = REPO_ROOT / "src" / "ai_intervention_agent"
SHARED_TYPES = SRC / "shared_types.py"
NOTIFICATION_MANAGER = SRC / "notification_manager.py"
SERVER_CONFIG = SRC / "server_config.py"
SERVICE_MANAGER = SRC / "service_manager.py"
NOTIFICATION_ROUTES = SRC / "web_ui_routes" / "notification.py"
CONFIG_TOML_DEFAULT = REPO_ROOT / "config.toml.default"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


class TestRetryDelay7Source(unittest.TestCase):
    """``retry_delay`` (notification, 2s) 必须在 7 个 source 保持一致。"""

    EXPECTED = 2

    def test_shared_types_pydantic_default(self) -> None:
        src = _read(SHARED_TYPES)
        self.assertRegex(
            src,
            r"retry_delay\s*:\s*Annotated\[.*?_clamp_int\(\s*\d+\s*,\s*\d+\s*,\s*2\s*\)\)\s*\]\s*=\s*2",
            "shared_types.NotificationSectionConfig.retry_delay Pydantic = 2",
        )

    def test_notification_manager_class_default(self) -> None:
        src = _read(NOTIFICATION_MANAGER)
        self.assertRegex(
            src,
            r"retry_delay\s*:\s*int\s*=\s*2\b",
            "NotificationConfig.retry_delay class default must = 2",
        )

    def test_validator_fallback(self) -> None:
        src = _read(NOTIFICATION_MANAGER)
        match = re.search(
            r"def\s+coerce_retry_delay\([^)]*\)[^:]*:.*?except.*?return\s+(\d+)",
            src,
            re.DOTALL,
        )
        self.assertIsNotNone(match, "找不到 coerce_retry_delay 的 except return")
        assert match is not None
        self.assertEqual(int(match.group(1)), self.EXPECTED)

    def test_parser_fallbacks(self) -> None:
        """``cfg.get("retry_delay", 2)`` 至少 2 处 (from_config_file +
        _set_runtime_config)，全部必须 = 2。"""
        src = _read(NOTIFICATION_MANAGER)
        matches = re.findall(r'cfg\.get\(\s*"retry_delay"\s*,\s*(\d+)\s*\)', src)
        self.assertGreaterEqual(
            len(matches),
            2,
            "notification_manager 必须至少有 2 处 cfg.get('retry_delay', N) "
            "fallback parser (from_config_file + _set_runtime_config)",
        )
        for m in matches:
            self.assertEqual(int(m), self.EXPECTED)

    def test_runtime_getattr_fallback(self) -> None:
        """运行时 ``getattr(self.config, "retry_delay", 2)`` 兜底 (在
        ``_schedule_retry`` jitter 计算路径中)。"""
        src = _read(NOTIFICATION_MANAGER)
        match = re.search(
            r'getattr\(\s*self\.config\s*,\s*"retry_delay"\s*,\s*(\d+)\s*\)',
            src,
        )
        self.assertIsNotNone(
            match, "找不到 getattr(self.config, 'retry_delay', N) 兜底"
        )
        assert match is not None
        self.assertEqual(int(match.group(1)), self.EXPECTED)

    def test_config_toml_default(self) -> None:
        src = _read(CONFIG_TOML_DEFAULT)
        match = re.search(r"^retry_delay\s*=\s*2\b", src, re.MULTILINE)
        self.assertIsNotNone(match, "config.toml.default retry_delay line missing")


class TestSoundVolume7SourceWithIntFloatBridge(unittest.TestCase):
    """``sound_volume`` (notification, 80 int ↔ 0.8 float) 双向 bridge 一致性。

    特殊性：source 在 ``[0, 100] int`` 和 ``[0.0, 1.0] float`` 之间转换，
    必须**同时**锁定：
        80 (int, 公开 API + TOML + 80% 默认 == 80/100)
        0.8 (float, 内部 audio API 用 0-1)
        转换式: from_file = int/100.0 / save = round(float*100)
    任一端漂移都会导致用户感知音量错乱。
    """

    EXPECTED_INT = 80
    EXPECTED_FLOAT = 0.8

    def test_shared_types_pydantic_default_int_80(self) -> None:
        """shared_types 中 Pydantic 默认 = 80 (int)，对应 0-100 公开 API。"""
        src = _read(SHARED_TYPES)
        self.assertRegex(
            src,
            r"sound_volume\s*:\s*Annotated\[.*?_clamp_int\(\s*0\s*,\s*100\s*,\s*80\s*\)\)\s*\]\s*=\s*80",
            "shared_types.NotificationSectionConfig.sound_volume Pydantic = 80",
        )

    def test_notification_manager_class_default_float_08(self) -> None:
        """notification_manager 内部 0-1 范围，class default = 0.8 (= 80/100)。"""
        src = _read(NOTIFICATION_MANAGER)
        self.assertRegex(
            src,
            r"sound_volume\s*:\s*float\s*=\s*0\.8\b",
            "NotificationConfig.sound_volume class default must = 0.8 (= 80/100)",
        )

    def test_from_config_file_divides_by_100(self) -> None:
        """``cfg.get("sound_volume", 80) / 100.0`` 把 80 转换成 0.8。"""
        src = _read(NOTIFICATION_MANAGER)
        matches = re.findall(
            r'cfg\.get\(\s*"sound_volume"\s*,\s*(\d+)\s*\)\s*/\s*100\.0',
            src,
        )
        self.assertGreaterEqual(
            len(matches),
            2,
            "notification_manager 必须至少有 2 处 cfg.get('sound_volume', 80) / 100.0 "
            "转换 (from_config_file + _set_runtime_config)",
        )
        for m in matches:
            self.assertEqual(
                int(m),
                self.EXPECTED_INT,
                f"sound_volume parser fallback = {m}, 应该 = 80 (转 0.8 内部 float)",
            )

    def test_save_config_multiplies_by_100(self) -> None:
        """``round(self.config.sound_volume * 100)`` 把 0.8 转回 80 int 保存。"""
        src = _read(NOTIFICATION_MANAGER)
        self.assertRegex(
            src,
            r"round\(\s*self\.config\.sound_volume\s*\*\s*100\s*\)",
            "save_config 必须用 round(sound_volume * 100) 转回 int (反向 bridge)",
        )

    def test_routes_normalize_sound_volume_fallback_80(self) -> None:
        """``web_ui_routes/notification.py::normalize_sound_volume`` fallback = 80。"""
        src = _read(NOTIFICATION_ROUTES)
        match = re.search(
            r'notification_config\.get\(\s*"sound_volume"\s*,\s*(\d+)\s*\)',
            src,
        )
        self.assertIsNotNone(
            match,
            "web_ui_routes/notification.py 必须有 notification_config.get('sound_volume', N)",
        )
        assert match is not None
        self.assertEqual(int(match.group(1)), self.EXPECTED_INT)

    def test_config_toml_default_int_80(self) -> None:
        src = _read(CONFIG_TOML_DEFAULT)
        match = re.search(r"^sound_volume\s*=\s*80\b", src, re.MULTILINE)
        self.assertIsNotNone(match, "config.toml.default sound_volume line missing")


class TestHttpRetryDelay5Source(unittest.TestCase):
    """``http_retry_delay`` (web_ui HTTP, 1.0s) 5 source 一致性。

    特殊性：``server_config.WebUIConfig`` 和 ``shared_types.WebUISectionConfig``
    是 2 个独立 Pydantic model (cycle-25 R277 双 model 共存设计)；都必须 = 1.0。
    """

    EXPECTED = 1.0

    def test_shared_types_pydantic_default(self) -> None:
        src = _read(SHARED_TYPES)
        self.assertRegex(
            src,
            r"http_retry_delay\s*:\s*Annotated\[.*?_clamp_float\(\s*\d+(?:\.\d+)?\s*,\s*\d+(?:\.\d+)?\s*,\s*1\.0\s*\)\)\s*\]\s*=\s*1\.0",
            "shared_types.WebUISectionConfig.http_retry_delay Pydantic = 1.0",
        )

    def test_server_config_webui_retry_delay_default(self) -> None:
        """``server_config.WebUIConfig.retry_delay: float = 1.0`` (注：字段名是
        ``retry_delay`` 不是 ``http_retry_delay``，但语义同)。"""
        src = _read(SERVER_CONFIG)
        self.assertRegex(
            src,
            r"retry_delay\s*:\s*float\s*=\s*1\.0\b",
            "server_config.WebUIConfig.retry_delay must default = 1.0",
        )

    def test_server_config_retry_delay_max_60(self) -> None:
        """``RETRY_DELAY_MAX`` clamp 上限必须 = 60.0，与 shared_types
        ``_clamp_float(0, 60, 1.0)`` 一致。"""
        src = _read(SERVER_CONFIG)
        self.assertRegex(
            src,
            r"RETRY_DELAY_MAX\s*:\s*ClassVar\[float\]\s*=\s*60\.0\b",
            "server_config.WebUIConfig.RETRY_DELAY_MAX must = 60.0",
        )

    def test_service_manager_compat_fallback(self) -> None:
        """``service_manager.py`` ``get_compat_config(..., "retry_delay", 1.0)`` 兜底。"""
        src = _read(SERVICE_MANAGER)
        self.assertRegex(
            src,
            r'get_compat_config\([^,]+,\s*"http_retry_delay"\s*,\s*"retry_delay"\s*,\s*1\.0\s*\)',
            "service_manager.py must call get_compat_config(..., 'http_retry_delay', 'retry_delay', 1.0)",
        )

    def test_config_toml_default(self) -> None:
        src = _read(CONFIG_TOML_DEFAULT)
        match = re.search(r"^http_retry_delay\s*=\s*1\.0\b", src, re.MULTILINE)
        self.assertIsNotNone(
            match,
            "config.toml.default http_retry_delay line missing (expected '= 1.0')",
        )


class TestR290LineagePreserved(unittest.TestCase):
    """meta-doc: R292 docstring 必须 reference R290 (cycle-27 第二轮) 作为
    第三轮 audit 的前置 anchor。"""

    def test_docstring_mentions_3_consts_and_r290(self) -> None:
        src = _read(Path(__file__))
        for const in ["retry_delay", "sound_volume", "http_retry_delay"]:
            self.assertIn(const, src, f"R292 docstring must list `{const}`")
        self.assertIn(
            "R290", src, "R292 docstring must reference R290 (cycle-27 第二轮)"
        )

    def test_total_source_count_documented(self) -> None:
        """docstring 必须显式列出本轮新增 source 总数 (7+7+5=19)。"""
        src = _read(Path(__file__))
        self.assertRegex(
            src,
            r"7\s*\+\s*7\s*\+\s*5",
            "R292 docstring 必须列出 7+7+5 source 分解 (便于 cumulative 跟踪)",
        )


if __name__ == "__main__":
    unittest.main()
