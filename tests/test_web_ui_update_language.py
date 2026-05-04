"""``/api/update-language`` 端点测试 — 之前完全无覆盖。

锁定的契约：
- 已知语言（``auto`` / ``en`` / ``zh-CN``）→ 200 + 写入 ``web_ui`` section
- 未知语言 → 400 + 不写配置
- payload 解析异常 → 500（兜底）
- 空 payload → 视为 ``auto``（默认值），不报错
"""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch


class _UpdateLanguageBase(unittest.TestCase):
    """共享 fixture：限流关闭 + 测试客户端。"""

    @classmethod
    def setUpClass(cls) -> None:
        from web_ui import WebFeedbackUI

        cls._ui = WebFeedbackUI(
            prompt="update-language test", task_id="ul-test", port=19200
        )
        cls._ui.app.config["TESTING"] = True
        cls._ui.limiter.enabled = False
        cls._client = cls._ui.app.test_client()


class TestUpdateLanguageEndpoint(_UpdateLanguageBase):
    """成功路径：三种合法 language 都应被接受并写入配置。"""

    @patch("web_ui.get_config")
    def test_zh_cn_accepted(self, mock_get_config) -> None:
        mock_mgr = MagicMock()
        mock_get_config.return_value = mock_mgr

        resp = self._client.post("/api/update-language", json={"language": "zh-CN"})

        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data["status"], "success")
        self.assertEqual(data["language"], "zh-CN")
        mock_mgr.update_section.assert_called_once_with("web_ui", {"language": "zh-CN"})

    @patch("web_ui.get_config")
    def test_en_accepted(self, mock_get_config) -> None:
        mock_mgr = MagicMock()
        mock_get_config.return_value = mock_mgr

        resp = self._client.post("/api/update-language", json={"language": "en"})

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json()["language"], "en")

    @patch("web_ui.get_config")
    def test_auto_accepted(self, mock_get_config) -> None:
        mock_mgr = MagicMock()
        mock_get_config.return_value = mock_mgr

        resp = self._client.post("/api/update-language", json={"language": "auto"})

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json()["language"], "auto")

    @patch("web_ui.get_config")
    def test_empty_payload_defaults_to_auto(self, mock_get_config) -> None:
        """空 payload 应回退到默认值 ``auto``，不应 400/500。"""
        mock_mgr = MagicMock()
        mock_get_config.return_value = mock_mgr

        resp = self._client.post("/api/update-language", json={})

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json()["language"], "auto")

    def test_unsupported_language_returns_400(self) -> None:
        """非白名单语言（如 ``fr``、空字符串）→ 400，不应触达 config_manager。"""
        with patch("web_ui.get_config") as mock_get_config:
            resp = self._client.post("/api/update-language", json={"language": "fr"})

        self.assertEqual(resp.status_code, 400)
        data = resp.get_json()
        self.assertEqual(data["status"], "error")
        self.assertIn("fr", data["message"])
        mock_get_config.assert_not_called()

    def test_unsupported_language_empty_string_returns_400(self) -> None:
        """空字符串不在白名单内 → 400。"""
        with patch("web_ui.get_config") as mock_get_config:
            resp = self._client.post("/api/update-language", json={"language": ""})

        self.assertEqual(resp.status_code, 400)
        mock_get_config.assert_not_called()

    @patch("web_ui.get_config")
    def test_config_manager_exception_returns_500(self, mock_get_config) -> None:
        """``update_section`` 抛异常 → 500，不应让 5xx 泄漏 traceback 给前端。"""
        mock_mgr = MagicMock()
        mock_mgr.update_section.side_effect = OSError("simulated config write failure")
        mock_get_config.return_value = mock_mgr

        resp = self._client.post("/api/update-language", json={"language": "zh-CN"})

        self.assertEqual(resp.status_code, 500)
        data = resp.get_json()
        self.assertEqual(data["status"], "error")
        self.assertIn("simulated config write failure", data["message"])

    def test_extra_whitespace_is_stripped(self) -> None:
        """``" zh-CN "`` 应被 ``.strip()`` 后视为合法。"""
        with patch("web_ui.get_config") as mock_get_config:
            mock_mgr = MagicMock()
            mock_get_config.return_value = mock_mgr

            resp = self._client.post(
                "/api/update-language", json={"language": "  zh-CN  "}
            )

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json()["language"], "zh-CN")


if __name__ == "__main__":
    unittest.main()
