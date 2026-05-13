"""R200 / Cycle 8 · F-199-1 from CR#20 §4.1: api_token_rotated_at cascade-clear。

背景
----
R199 把 ``api_token_rotated_at`` 持久化进 config，但 CR#20 §4.1 指出
一个「stale ghost」漏洞：

如果 admin 手动 edit ``config.toml`` 把 ``api_token = ""``（撤销 token），
但**忘记**或**没意识到要同时清空** ``api_token_rotated_at`` —— 那么
``GET /api/system/api-token-info`` 会返回:

- ``has_token = false``（API 看不到 token）
- ``rotated_at = "2026-04-02T..."``（指向上次 rotation）
- ``age_seconds = 5_270_400``（≈ 60 天）

这是**误导性状态**：dashboard 会按 NIST SP 800-63B 90 天规则报「token
60 天未轮换」，但实际 token 已被撤销 ——「闹鬼的轮换提醒」。

R200 修复策略
=============
在 ``_validate_network_security_config`` 走完所有字段 normalize 之后，
加一道 sanity check:

- 如果 ``api_token`` 经过 normalize **为空**（包括 < 16 字符被丢弃 /
  raw 就是空串 / 含空白被清洗后变空）；
- 但 ``api_token_rotated_at`` 经过 normalize **不为空**（合法 ISO-8601）
  → log warning + cascade-clear 时间戳为空串。

不变量：normalize 完后必须满足「``api_token`` 在 ⇔ ``api_token_rotated_at``
在」双向蕴含（empty/empty 也满足）。

这道 sanitize 是**幂等**的——cascade-clear 后再调一次 normalize 仍是
一致状态。

测试覆盖（13 cases / 4 invariant classes）：

1. **直接 normalize 路径**（5 cases）: ``_validate_network_security_config``
   独立调用就要满足不变量；
2. **incremental update 路径**（3 cases）: ``update_network_security_config``
   接受 incremental 改动后 cascade 也要正确触发；
3. **R199 端点交互**（3 cases）: ``GET /api/system/api-token-info`` 在
   cascade-clear 触发后看到一致状态；
4. **不变量 + 幂等**（2 cases）: empty/empty 不触发 warning; 双调 normalize
   稳定。
"""

from __future__ import annotations

import logging
import sys
import unittest
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import patch

# ai_intervention_agent 用自定义 ``EnhancedLogger``（loguru 后端 + propagate=False），
# ``unittest.assertLogs`` 拿不到。下面定义一个上下文管理器 patch 模块级
# ``logger.warning`` 收集消息——比 assertLogs 更直接, 也更适合 cascade-clear
# 这种「期望特定 marker 出现在 warning」的测试场景。


@contextmanager
def capture_ns_warnings() -> Any:
    """捕获 ``config_modules.network_security`` 模块内 ``logger.warning(...)``
    调用的 message。yield 一个 list, ctx 退出时 list 含全部 warning text。"""
    from ai_intervention_agent.config_modules import network_security as ns_module

    captured: list[str] = []
    original_warning = ns_module.logger.warning

    def _record(msg: str, *args: Any, **kwargs: Any) -> None:
        captured.append(msg)
        original_warning(msg, *args, **kwargs)

    with patch.object(ns_module.logger, "warning", side_effect=_record):
        yield captured


REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _valid_ts(days_ago: int = 30) -> str:
    """生成 N 天前的 ISO-8601 UTC 时间戳（默认 30 天前）。"""
    return (
        (datetime.now(UTC) - timedelta(days=days_ago))
        .isoformat()
        .replace("+00:00", "Z")
    )


# ---------------------------------------------------------------------------
# 1. Direct normalize path
# ---------------------------------------------------------------------------


class TestDirectNormalize(unittest.TestCase):
    """``_validate_network_security_config(raw)`` 应该自带 cascade-clear。"""

    def _get_manager(self) -> Any:
        from ai_intervention_agent import config_manager as cm

        return cm.get_config()

    def test_ghost_state_token_empty_rotated_at_set(self) -> None:
        """核心 bug: api_token="" but rotated_at != "" → 应该被 cascade-clear。"""
        mgr = self._get_manager()
        ts = _valid_ts(days_ago=60)
        with capture_ns_warnings() as warnings:
            result = mgr._validate_network_security_config(
                {
                    "api_token": "",
                    "api_token_rotated_at": ts,
                }
            )
        self.assertEqual(result["api_token"], "")
        self.assertEqual(
            result["api_token_rotated_at"],
            "",
            "R200 cascade-clear: rotated_at must be empty when token is empty",
        )
        # 警告消息明确说明 cascade-clear
        warnings_text = " ".join(warnings).lower()
        self.assertIn("cascade-clear", warnings_text)

    def test_short_token_normalized_to_empty_also_cascades(self) -> None:
        """边界: raw token 长度 < 16 → _validate 视作未设置 → rotated_at 也清。"""
        mgr = self._get_manager()
        result = mgr._validate_network_security_config(
            {
                "api_token": "too-short",  # < 16 chars → normalized to ""
                "api_token_rotated_at": _valid_ts(),
            }
        )
        self.assertEqual(result["api_token"], "")
        self.assertEqual(result["api_token_rotated_at"], "")

    def test_whitespace_only_token_cascades(self) -> None:
        """边界: 全空白 token → strip 后变空 → rotated_at 也清。"""
        mgr = self._get_manager()
        result = mgr._validate_network_security_config(
            {
                "api_token": "   \t\n  ",
                "api_token_rotated_at": _valid_ts(),
            }
        )
        self.assertEqual(result["api_token"], "")
        self.assertEqual(result["api_token_rotated_at"], "")

    def test_valid_token_keeps_rotated_at(self) -> None:
        """正常配对: token + rotated_at 都合法 → 保持不变。"""
        mgr = self._get_manager()
        ts = _valid_ts(days_ago=10)
        result = mgr._validate_network_security_config(
            {
                "api_token": "x" * 32,
                "api_token_rotated_at": ts,
            }
        )
        self.assertEqual(result["api_token"], "x" * 32)
        self.assertEqual(result["api_token_rotated_at"], ts)

    def test_empty_token_empty_rotated_at_no_warning(self) -> None:
        """全空状态: 不触发 cascade-clear warning（避免日志 noise）。"""
        mgr = self._get_manager()
        with capture_ns_warnings() as warnings:
            result = mgr._validate_network_security_config(
                {"api_token": "", "api_token_rotated_at": ""}
            )
        self.assertEqual(result["api_token"], "")
        self.assertEqual(result["api_token_rotated_at"], "")
        # 关键: 全空状态**不应**触发 cascade-clear warning（避免日志 noise）。
        # 其他 warning (如 allowed_networks dedupe) 可能出现, 我们只 assert
        # cascade-clear 这一句没出现。
        cascade_warnings = [w for w in warnings if "cascade-clear" in w.lower()]
        self.assertEqual(
            cascade_warnings,
            [],
            "empty token + empty rotated_at should NOT trigger cascade-clear warning",
        )


# ---------------------------------------------------------------------------
# 2. Incremental update path
# ---------------------------------------------------------------------------


class TestIncrementalUpdate(unittest.TestCase):
    """``update_network_security_config(updates)`` 应该 cascade。"""

    @classmethod
    def setUpClass(cls) -> None:
        # 启动状态: 给 config 一个 valid token + rotated_at
        from ai_intervention_agent import config_manager as cm

        cls.cfg = cm.get_config()

    def setUp(self) -> None:
        # 每个 test 开始: 设置一对 valid token + rotated_at
        self.original_ns = self.cfg.get_network_security_config()
        self.cfg.update_network_security_config(
            {"api_token": "y" * 32, "api_token_rotated_at": _valid_ts()}
        )

    def tearDown(self) -> None:
        # 还原: 把 token + rotated_at 都清空（不会留 ghost）
        self.cfg.update_network_security_config(
            {"api_token": "", "api_token_rotated_at": ""}
        )

    def test_explicit_clear_token_cascades_rotated_at(self) -> None:
        """admin 调 update({"api_token": ""}) 不传 rotated_at → 仍然被清。"""
        self.cfg.update_network_security_config({"api_token": ""})
        ns = self.cfg.get_network_security_config()
        self.assertEqual(ns["api_token"], "")
        self.assertEqual(
            ns["api_token_rotated_at"],
            "",
            "R200: incremental update path must also trigger cascade-clear",
        )

    def test_explicit_clear_both_no_ghost(self) -> None:
        """admin 调 update 同时把 token 和 rotated_at 清空 → 也是一致状态。"""
        self.cfg.update_network_security_config(
            {"api_token": "", "api_token_rotated_at": ""}
        )
        ns = self.cfg.get_network_security_config()
        self.assertEqual(ns["api_token"], "")
        self.assertEqual(ns["api_token_rotated_at"], "")

    def test_set_short_token_cascades(self) -> None:
        """admin 通过 update 设置短 token (< 16) → token 被视作未配置 → rotated_at 也清。"""
        self.cfg.update_network_security_config({"api_token": "short"})
        ns = self.cfg.get_network_security_config()
        self.assertEqual(ns["api_token"], "")
        self.assertEqual(ns["api_token_rotated_at"], "")


# ---------------------------------------------------------------------------
# 3. R199 端点交互
# ---------------------------------------------------------------------------


class TestApiTokenInfoEndpointConsistency(unittest.TestCase):
    """``GET /api/system/api-token-info`` 在 cascade-clear 后应该返回一致状态。"""

    _port: int = 19200
    _ui: Any = None
    _client: Any = None

    @classmethod
    def setUpClass(cls) -> None:
        from ai_intervention_agent.web_ui import WebFeedbackUI

        cls._ui = WebFeedbackUI(
            prompt="r200 cascade test", task_id="tk-r200", port=cls._port
        )
        cls._ui.app.config["TESTING"] = True
        cls._ui.limiter.enabled = False
        cls._client = cls._ui.app.test_client()

    def tearDown(self) -> None:
        from ai_intervention_agent.web_ui_routes import system as system_module

        system_module.get_config().update_network_security_config(
            {"api_token": "", "api_token_rotated_at": ""}
        )

    def test_endpoint_returns_consistent_state_after_cascade(self) -> None:
        """关键 e2e: admin clear token → endpoint 立刻看到 has_token=false +
        rotated_at="" + age_seconds=None。"""
        from ai_intervention_agent.web_ui_routes import system as system_module

        cfg = system_module.get_config()
        # 1. 设置 valid token + rotated_at
        cfg.update_network_security_config(
            {"api_token": "z" * 32, "api_token_rotated_at": _valid_ts(days_ago=45)}
        )
        # 2. admin 调 update({"api_token": ""}) 撤销 token
        cfg.update_network_security_config({"api_token": ""})
        # 3. 查询 endpoint
        with patch.object(system_module, "_get_client_ip", return_value="127.0.0.1"):
            resp = self._client.get("/api/system/api-token-info")
        body = resp.get_json()
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(body["has_token"])
        # 关键: rotated_at 也清了, 不是 stale ghost
        self.assertEqual(
            body["rotated_at"],
            "",
            "R200: after token revocation, rotated_at must be empty in info "
            "endpoint response (no stale ghost)",
        )
        # age_seconds 必须是 null
        self.assertIsNone(body["age_seconds"])

    def test_rotation_endpoint_then_revoke_cascade(self) -> None:
        """R195 rotate → R200 admin manual clear → 一致状态。"""
        from ai_intervention_agent.web_ui_routes import system as system_module

        with patch.object(system_module, "_get_client_ip", return_value="127.0.0.1"):
            # rotate
            r1 = self._client.post("/api/system/rotate-api-token")
            self.assertEqual(r1.status_code, 200)
            info1 = self._client.get("/api/system/api-token-info").get_json()
            self.assertTrue(info1["has_token"])
            self.assertNotEqual(info1["rotated_at"], "")

            # admin manual clear
            system_module.get_config().update_network_security_config({"api_token": ""})
            info2 = self._client.get("/api/system/api-token-info").get_json()

        self.assertFalse(info2["has_token"])
        self.assertEqual(info2["rotated_at"], "")
        self.assertIsNone(info2["age_seconds"])

    def test_rotation_endpoint_writes_consistent_pair(self) -> None:
        """R195 rotate → token + rotated_at 都非空; 不是 cascade-clear 路径，
        但这个 invariant 测试同样确认 cascade-clear **没有误伤** R195 写入。"""
        from ai_intervention_agent.web_ui_routes import system as system_module

        with patch.object(system_module, "_get_client_ip", return_value="127.0.0.1"):
            r1 = self._client.post("/api/system/rotate-api-token")
            info = self._client.get("/api/system/api-token-info").get_json()
        rotate_body = r1.get_json()
        self.assertEqual(info["rotated_at"], rotate_body["rotated_at"])
        self.assertTrue(info["has_token"])
        self.assertIsNotNone(info["age_seconds"])


# ---------------------------------------------------------------------------
# 4. 不变量 + 幂等
# ---------------------------------------------------------------------------


class TestInvariantAndIdempotency(unittest.TestCase):
    """cascade-clear 应该是**幂等**的——一次调用 sanitize 后, 再调一次也是
    一致状态。"""

    def _get_manager(self) -> Any:
        from ai_intervention_agent import config_manager as cm

        return cm.get_config()

    def test_normalize_is_idempotent(self) -> None:
        """二次 normalize 不应再触发 cascade-clear warning。"""
        mgr = self._get_manager()
        with capture_ns_warnings() as warnings1:
            result1 = mgr._validate_network_security_config(
                {"api_token": "", "api_token_rotated_at": _valid_ts()}
            )
        # 第二次: result1 喂回 _validate → 已经是一致状态, 不应再触发 cascade warning
        with capture_ns_warnings() as warnings2:
            result2 = mgr._validate_network_security_config(result1)
        self.assertEqual(result1["api_token"], result2["api_token"])
        self.assertEqual(
            result1["api_token_rotated_at"],
            result2["api_token_rotated_at"],
        )
        self.assertEqual(result1["api_token_rotated_at"], "")
        # 第一次有 cascade-clear warning, 第二次不应再有
        first_cascade = [w for w in warnings1 if "cascade-clear" in w.lower()]
        second_cascade = [w for w in warnings2 if "cascade-clear" in w.lower()]
        self.assertEqual(len(first_cascade), 1, "first normalize should warn once")
        self.assertEqual(
            second_cascade,
            [],
            "second normalize on already-clean state should NOT re-warn",
        )

    def test_cascade_clear_log_includes_specific_marker(self) -> None:
        """cascade-clear warning 必须包含关键字 'cascade-clear' / 'stale ghost'
        让 grep audit log 可以快速定位。"""
        mgr = self._get_manager()
        with capture_ns_warnings() as warnings:
            mgr._validate_network_security_config(
                {"api_token": "", "api_token_rotated_at": _valid_ts()}
            )
        joined = " ".join(warnings).lower()
        self.assertTrue(
            "cascade-clear" in joined or "stale ghost" in joined,
            f"R200: warning must include 'cascade-clear' or 'stale ghost' "
            f"marker for audit grep; got: {joined!r}",
        )


if __name__ == "__main__":  # pragma: no cover
    logging.basicConfig(level=logging.DEBUG)
    unittest.main()
