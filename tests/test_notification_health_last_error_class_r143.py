"""R143 · ``per_provider.last_error_class`` 错误类归一化契约测试。

背景
----

R142 给 ``/api/system/health`` 暴露 ``per_provider.last_error_present``
boolean——能告诉调用方「最近一次失败有 / 没有 error 信息」，但回答
不了「是 4xx 还是 5xx」「是网络问题还是 Bark 服务器问题」。监控做
stack-bar 这种维度时，1 bit 信号太粗。

R143 在保留 R142 PII 边界的前提下，加 ``last_error_class``：把
NotificationManager 写入的 ``last_error`` 字符串规整成 6 个稳定类
之一：

- ``client_error``：4xx HTTP / 设备密钥错 / 鉴权失败
- ``server_error``：5xx HTTP / Bark 自身故障
- ``network_error``：connection refused / DNS 失败 / 网络中断
- ``timeout``：请求超时
- ``not_registered``：provider 没在 NotificationManager 注册
- ``unknown``：无法归类的字符串（兜底）

设计契约（共 ~25 cases）：

1. **常量与值集合** — ``_HEALTH_ERROR_CLASS_VALUES`` 是 6 个；都
   出现在 source 中。

2. **None / "" 输入** — ``_classify_last_error(None)`` /
   ``_classify_last_error("")`` 都返回 ``None``，与
   ``last_error_present=False`` 同语义。

3. **HTTP status code 优先级**：
   - ``"{'status_code': 401, 'detail': '...'}"`` → ``client_error``
   - ``"{'status_code': 500, 'detail': '...'}"`` → ``server_error``
   - ``"{'status_code': 503}"`` → ``server_error``
   - ``"HTTP 401 Unauthorized"`` → ``client_error``（裸 status）
   - ``"500 Internal Server Error"`` → ``server_error``

4. **provider not registered** — ``"provider_not_registered"``
   字符串无歧义直接归 ``not_registered``（NotificationManager line
   1046 的固定输出）。

5. **timeout / network 关键字**（无 status code 时）：
   - ``"Connection timeout"`` → ``timeout``（timeout 优先）
   - ``"Connection refused"`` → ``network_error``
   - ``"Name resolution failed"`` → ``network_error``
   - ``"DNS lookup error"`` → ``network_error``
   - ``"Network unreachable"`` → ``network_error``
   - ``"httpx.TimeoutException"`` → ``timeout``

6. **优先级层次** — 同时含有 timeout 关键字 + 5xx → ``server_error``
   优先（因为 server_error 是 HTTP layer 的明确信号，timeout 只是
   transport layer 的弱信号）。

7. **PII 安全边界**：
   - 输入含 ``device_key=SECRET_KEY_123`` 仍只输出归一类，绝不返
     回原文本片段；
   - 输入含 Bark URL ``https://api.day.app/push`` 同样；
   - 输入含 Bark token ``BARK_TOKEN_xxx`` 同样。

8. **integration with `_safe_per_provider_snapshot`**：
   - last_error_present=True 时 last_error_class 必出现且非 None；
   - last_error_present=False 时 last_error_class=None；
   - 9 个 key 不多不少。

9. **`/api/system/health` 端点真打**：HTTP 响应里 per_provider 的
   每个 provider（如已注册）有 ``last_error_class``；
   ``last_error_class`` 取值始终在 ``_HEALTH_ERROR_CLASS_VALUES``
   ∪ ``{None}`` 内。

10. **Swagger doc 提及 R143** — system.py 源码中 ``R143`` /
    ``last_error_class`` / ``client_error`` / ``server_error`` 等
    标识都出现。
"""

from __future__ import annotations

import sys
import time
import unittest
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC = REPO_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ai_intervention_agent.web_ui_routes.system import (
    _HEALTH_ERROR_CLASS_VALUES,
    _HEALTH_PER_PROVIDER_KEYS,
    _classify_last_error,
    _safe_per_provider_snapshot,
)


class TestErrorClassConstants(unittest.TestCase):
    """常量集合契约。"""

    def test_six_classes_in_constant(self):
        self.assertEqual(len(_HEALTH_ERROR_CLASS_VALUES), 6)
        self.assertEqual(
            set(_HEALTH_ERROR_CLASS_VALUES),
            {
                "client_error",
                "server_error",
                "network_error",
                "timeout",
                "not_registered",
                "unknown",
            },
        )

    def test_constant_values_are_lowercase_underscore(self):
        # 与 NotificationType 同款命名：lowercase + underscore 分词
        for v in _HEALTH_ERROR_CLASS_VALUES:
            self.assertEqual(v, v.lower())
            self.assertNotIn(" ", v)
            self.assertNotIn("-", v)


class TestClassifyEmptyInput(unittest.TestCase):
    """None / "" → None；与 last_error_present 同语义。"""

    def test_none_yields_none(self):
        self.assertIsNone(_classify_last_error(None))

    def test_empty_string_yields_none(self):
        self.assertIsNone(_classify_last_error(""))


class TestClassifyHTTPStatusCode(unittest.TestCase):
    """HTTP status code 直接归类。"""

    def test_dict_repr_401_yields_client_error(self):
        s = "{'status_code': 401, 'detail': 'Bark API returned 401'}"
        self.assertEqual(_classify_last_error(s), "client_error")

    def test_dict_repr_403_yields_client_error(self):
        s = "{'status_code': 403, 'detail': 'Forbidden'}"
        self.assertEqual(_classify_last_error(s), "client_error")

    def test_dict_repr_404_yields_client_error(self):
        s = "{'status_code': 404, 'detail': 'Not Found'}"
        self.assertEqual(_classify_last_error(s), "client_error")

    def test_dict_repr_500_yields_server_error(self):
        s = "{'status_code': 500, 'detail': 'Internal'}"
        self.assertEqual(_classify_last_error(s), "server_error")

    def test_dict_repr_503_yields_server_error(self):
        s = "{'status_code': 503, 'detail': 'Bad Gateway'}"
        self.assertEqual(_classify_last_error(s), "server_error")

    def test_bare_http_400_in_message(self):
        # 没 dict 包装的裸状态码也能识别
        s = "HTTP 401 Unauthorized: Bark device key invalid"
        self.assertEqual(_classify_last_error(s), "client_error")

    def test_bare_http_500_in_message(self):
        s = "500 Internal Server Error from upstream"
        self.assertEqual(_classify_last_error(s), "server_error")


class TestClassifyNotRegistered(unittest.TestCase):
    """``provider_not_registered`` 是 NotificationManager 的固定哨兵字符串。"""

    def test_provider_not_registered_recognized(self):
        self.assertEqual(
            _classify_last_error("provider_not_registered"), "not_registered"
        )

    def test_uppercase_provider_not_registered_recognized(self):
        # 实际写入是 lowercase，但容错：未来若变大写也能识别
        self.assertEqual(
            _classify_last_error("Provider_Not_Registered"), "not_registered"
        )


class TestClassifyTimeoutAndNetwork(unittest.TestCase):
    """无 status code 时按关键字归类。"""

    def test_connection_timeout_yields_timeout(self):
        self.assertEqual(_classify_last_error("Connection timeout"), "timeout")

    def test_request_timed_out_yields_timeout(self):
        self.assertEqual(
            _classify_last_error("Request timed out after 30 seconds"), "timeout"
        )

    def test_httpx_timeout_exception(self):
        self.assertEqual(
            _classify_last_error("httpx.TimeoutException: read timeout"), "timeout"
        )

    def test_connection_refused_yields_network(self):
        self.assertEqual(
            _classify_last_error("Connection refused on port 443"), "network_error"
        )

    def test_dns_failure_yields_network(self):
        self.assertEqual(
            _classify_last_error("DNS lookup failed for api.day.app"), "network_error"
        )

    def test_name_resolution_yields_network(self):
        self.assertEqual(
            _classify_last_error("Name resolution error: ENOTFOUND"), "network_error"
        )

    def test_network_unreachable_yields_network(self):
        self.assertEqual(_classify_last_error("Network unreachable"), "network_error")

    def test_connection_error_class_yields_network(self):
        self.assertEqual(
            _classify_last_error("ConnectionError(); ConnectError"), "network_error"
        )


class TestClassifyPriority(unittest.TestCase):
    """优先级：HTTP status > timeout/network 关键字。"""

    def test_5xx_with_timeout_keyword_yields_server_error(self):
        # 即使消息里有 timeout 字样，5xx 是 HTTP layer 的明确信号，应该优先
        s = "{'status_code': 504, 'detail': 'Gateway timeout'}"
        self.assertEqual(_classify_last_error(s), "server_error")

    def test_4xx_with_network_keyword_yields_client_error(self):
        s = "{'status_code': 401, 'detail': 'Connection refused: invalid auth'}"
        self.assertEqual(_classify_last_error(s), "client_error")


class TestClassifyUnknown(unittest.TestCase):
    """无法归类 → unknown。"""

    def test_random_string_yields_unknown(self):
        self.assertEqual(_classify_last_error("Some unstructured error msg"), "unknown")

    def test_plain_word_yields_unknown(self):
        self.assertEqual(_classify_last_error("oops"), "unknown")


class TestPIIBoundary(unittest.TestCase):
    """PII 边界——last_error_class 永远是 6 个泛化字符串之一，永远不漏原文本。"""

    def test_classify_with_device_key_secret(self):
        evil = (
            "{'status_code': 401, 'detail': 'Bark API failed: "
            "device_key=SECRET_KEY_DO_NOT_LEAK'}"
        )
        result = _classify_last_error(evil)
        self.assertEqual(result, "client_error")
        # 输出严格在 6 个值里
        self.assertIn(result, _HEALTH_ERROR_CLASS_VALUES)
        # 输出永不含 PII 子串
        assert result is not None
        self.assertNotIn("SECRET_KEY", result)
        self.assertNotIn("device_key", result)

    def test_classify_with_bark_url_path(self):
        evil = (
            "{'status_code': 500, 'detail': 'POST https://api.day.app/SOMETOKEN/push'}"
        )
        result = _classify_last_error(evil)
        self.assertEqual(result, "server_error")
        assert result is not None
        self.assertNotIn("api.day.app", result)
        self.assertNotIn("SOMETOKEN", result)

    def test_classify_with_bark_token(self):
        evil = "BARK_TOKEN_LEAKED HTTP 403 Forbidden"
        result = _classify_last_error(evil)
        self.assertEqual(result, "client_error")
        assert result is not None
        self.assertNotIn("BARK_TOKEN", result)


class TestSnapshotIntegration(unittest.TestCase):
    """``_safe_per_provider_snapshot`` 输出的 dict 含 ``last_error_class``。"""

    def test_present_true_yields_class_string(self):
        snap = _safe_per_provider_snapshot(
            {
                "bark": {
                    "attempts": 1,
                    "success": 0,
                    "failure": 1,
                    "success_rate": 0.0,
                    "avg_latency_ms": None,
                    "last_success_at": None,
                    "last_failure_at": time.time(),
                    "last_error": "{'status_code': 401, 'detail': '...'}",
                }
            },
            time.time(),
        )
        bark = snap["bark"]
        self.assertIsNotNone(bark)
        assert isinstance(bark, dict)
        self.assertTrue(bark["last_error_present"])
        self.assertEqual(bark["last_error_class"], "client_error")

    def test_present_false_yields_class_none(self):
        snap = _safe_per_provider_snapshot(
            {
                "bark": {
                    "attempts": 1,
                    "success": 1,
                    "failure": 0,
                    "success_rate": 1.0,
                    "avg_latency_ms": 100,
                    "last_success_at": time.time(),
                    "last_failure_at": None,
                    "last_error": None,
                }
            },
            time.time(),
        )
        bark = snap["bark"]
        assert isinstance(bark, dict)
        self.assertFalse(bark["last_error_present"])
        self.assertIsNone(bark["last_error_class"])

    def test_eleven_keys_exact(self):
        snap = _safe_per_provider_snapshot(
            {
                "bark": {
                    "attempts": 1,
                    "success": 0,
                    "failure": 1,
                    "success_rate": 0.0,
                    "last_failure_at": time.time(),
                    "last_error": "Connection refused",
                }
            },
            time.time(),
        )
        bark = snap["bark"]
        assert isinstance(bark, dict)
        # R145：在 R143 9 个 key 上再加 success_streak / failure_streak
        # 两个互斥连续计数 → 共 11 个 key。
        self.assertEqual(
            set(bark.keys()),
            {
                "attempts",
                "success",
                "failure",
                "success_rate",
                "avg_latency_ms",
                "last_success_age_seconds",
                "last_failure_age_seconds",
                "last_error_present",
                "last_error_class",
                "success_streak",
                "failure_streak",
            },
        )

    def test_class_value_in_constant_set(self):
        # 任何 last_error 输入，得到的 class 都必须在 _HEALTH_ERROR_CLASS_VALUES
        # 内（或 None）。给一组发散的 last_error 喂下去做 randomized 检查。
        cases = [
            "Connection refused",
            "{'status_code': 500}",
            "Random error",
            "provider_not_registered",
            "Read timed out",
            "DNS resolution failed",
            "{'status_code': 401, 'detail': 'X'}",
        ]
        for last_error in cases:
            snap = _safe_per_provider_snapshot(
                {
                    "bark": {
                        "attempts": 1,
                        "failure": 1,
                        "last_error": last_error,
                    }
                },
                time.time(),
            )
            bark = snap["bark"]
            assert isinstance(bark, dict)
            cls = bark["last_error_class"]
            self.assertIn(cls, [*_HEALTH_ERROR_CLASS_VALUES, None])


class TestHealthEndpointIntegration(unittest.TestCase):
    """HTTP /api/system/health 真打——last_error_class 出现在 per_provider 子结构。"""

    _port: int = 19113
    _ui: Any = None
    _client: Any = None

    @classmethod
    def setUpClass(cls) -> None:
        from ai_intervention_agent.web_ui import WebFeedbackUI

        cls._ui = WebFeedbackUI(prompt="r143 health", task_id="rt-r143", port=cls._port)
        cls._ui.app.config["TESTING"] = True
        cls._ui.limiter.enabled = False
        cls._client = cls._ui.app.test_client()

    def test_per_provider_payload_contains_last_error_class_key(self):
        resp = self._client.get("/api/system/health")
        self.assertIn(resp.status_code, (200, 503))
        body = resp.get_json()
        notif_check = body.get("checks", {}).get("notification", {})
        if not notif_check.get("ok"):
            self.skipTest("notification check unavailable, skip per_provider check")
        per_prov = notif_check.get("per_provider", {})
        for ptype in _HEALTH_PER_PROVIDER_KEYS:
            self.assertIn(ptype, per_prov)
            entry = per_prov[ptype]
            if entry is None:
                continue
            self.assertIn("last_error_class", entry)
            cls = entry["last_error_class"]
            # 必须是 6 个值之一或 None
            self.assertIn(cls, [*_HEALTH_ERROR_CLASS_VALUES, None])


class TestSwaggerDocAndSourceInvariants(unittest.TestCase):
    """source / Swagger doc 锁住 R143 + last_error_class + 6 类标识。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.source = (
            REPO_ROOT / "src" / "ai_intervention_agent" / "web_ui_routes" / "system.py"
        ).read_text(encoding="utf-8")

    def test_r143_string_in_source(self):
        self.assertIn("R143", self.source)

    def test_last_error_class_in_source(self):
        self.assertIn("last_error_class", self.source)

    def test_all_six_class_values_in_source(self):
        for v in (
            "client_error",
            "server_error",
            "network_error",
            "timeout",
            "not_registered",
            "unknown",
        ):
            self.assertIn(v, self.source)

    def test_swagger_documents_priority_order(self):
        # Swagger doc 至少提一个优先级线索（"5xx > 4xx" 或类似）
        self.assertTrue(
            "5xx > 4xx" in self.source or "优先" in self.source,
            "Swagger doc must explain priority order between class values",
        )


if __name__ == "__main__":
    unittest.main()
