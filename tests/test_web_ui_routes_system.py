"""web_ui_routes/system.py 测试 - /api/system/open-config-file 端点。

覆盖目标：TODO #4「用 IDE 打开配置文件」按钮的安全门禁与运行时行为，
锁定下列契约（防止后续 refactor 时把安全护栏拆掉）：

- 仅 loopback 客户端允许调用；其他来源一律 403
- 仅当前进程读到的配置文件 / 仓库内 default 模板可被打开
- 客户端传入的 path 必须命中白名单，否则 403
- 客户端可显式指定 editor，但必须在 ``_ALLOWED_EDITOR_NAMES`` 里
- 编辑器全部不可用、系统 fallback 也没有时返回 500
- 启动子进程时 shell=False / start_new_session=True，避免 shell 注入与父子进程联动
"""

from __future__ import annotations

import unittest
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch


class _SystemRouteBase(unittest.TestCase):
    """所有 system 路由测试共享的 fixture：限流关闭 + 测试客户端。"""

    _port: int = 19101
    _ui: Any = None
    _client: Any = None

    @classmethod
    def setUpClass(cls) -> None:
        from web_ui import WebFeedbackUI

        cls._ui = WebFeedbackUI(
            prompt="system route test", task_id="sys-rt", port=cls._port
        )
        cls._ui.app.config["TESTING"] = True
        cls._ui.limiter.enabled = False
        cls._client = cls._ui.app.test_client()


# ════════════════════════════════════════════════════════════════════════════
#  POST /api/system/open-config-file - 主请求路径
# ════════════════════════════════════════════════════════════════════════════
class TestOpenConfigFileEndpoint(_SystemRouteBase):
    _port = 19110

    def test_non_loopback_request_returns_403(self):
        """非 127.0.0.1 / ::1 来源的请求必须被拒绝（首层安全护栏）。"""
        with patch("web_ui_routes.system._get_client_ip", return_value="192.168.1.5"):
            resp = self._client.post("/api/system/open-config-file", json={})
        self.assertEqual(resp.status_code, 403)
        data = resp.get_json()
        self.assertFalse(data["success"])
        self.assertIn("loopback", data["error"].lower())

    def test_invalid_path_type_returns_400(self):
        """payload.path 不是字符串时拒绝。"""
        resp = self._client.post(
            "/api/system/open-config-file",
            json={"path": 12345},
            environ_overrides={"REMOTE_ADDR": "127.0.0.1"},
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("string", resp.get_json()["error"].lower())

    def test_unresolvable_path_returns_400(self):
        """传入无法 resolve 的路径（极端字符）→ 400。"""
        # NUL 字符在多数文件系统下都无法 resolve
        resp = self._client.post(
            "/api/system/open-config-file",
            json={"path": "/tmp/with\x00null"},
            environ_overrides={"REMOTE_ADDR": "127.0.0.1"},
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("resolve", resp.get_json()["error"].lower())

    def test_path_outside_allowlist_returns_403(self):
        """请求里塞外部任意路径 → 403（杜绝路径穿越）。"""
        resp = self._client.post(
            "/api/system/open-config-file",
            json={"path": "/etc/passwd"},
            environ_overrides={"REMOTE_ADDR": "127.0.0.1"},
        )
        self.assertEqual(resp.status_code, 403)
        self.assertIn("allow-list", resp.get_json()["error"].lower())

    @patch("web_ui_routes.system.subprocess.Popen")
    @patch("web_ui_routes.system._detect_default_editor")
    def test_default_path_with_detected_editor_returns_200(
        self, mock_detect, mock_popen
    ):
        """loopback + 不传 path → 用当前配置文件 + 自动探测的编辑器。"""
        mock_detect.return_value = ("/usr/local/bin/cursor", ["--reuse-window"])
        mock_popen.return_value = MagicMock()

        resp = self._client.post(
            "/api/system/open-config-file",
            json={},
            environ_overrides={"REMOTE_ADDR": "127.0.0.1"},
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data["success"])
        self.assertEqual(data["editor"], "cursor")
        self.assertTrue(data["path"])

        # 子进程参数：shell=False（避免注入），start_new_session=True（独立生存）
        kwargs = mock_popen.call_args.kwargs
        self.assertIs(kwargs["shell"], False)
        self.assertIs(kwargs["start_new_session"], True)
        # 命令 argv 第一项应是 cursor 绝对路径
        argv = mock_popen.call_args.args[0]
        self.assertEqual(argv[0], "/usr/local/bin/cursor")
        self.assertIn("--reuse-window", argv)

    @patch("web_ui_routes.system.subprocess.Popen")
    @patch("web_ui_routes.system._system_open_command")
    @patch("web_ui_routes.system._detect_default_editor")
    def test_no_editor_falls_back_to_system_opener(
        self, mock_detect, mock_system, mock_popen
    ):
        """编辑器都不可用时回退到系统 open / xdg-open。"""
        mock_detect.return_value = (None, [])
        mock_system.return_value = ["/usr/bin/open", "/path/to/config.toml"]
        mock_popen.return_value = MagicMock()

        resp = self._client.post(
            "/api/system/open-config-file",
            json={},
            environ_overrides={"REMOTE_ADDR": "127.0.0.1"},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json()["editor"], "system")

    @patch("web_ui_routes.system._system_open_command", return_value=None)
    @patch("web_ui_routes.system._detect_default_editor", return_value=(None, []))
    def test_no_editor_no_system_fallback_returns_500(self, *_):
        """所有打开方式都不可用 → 500，且文案不暴露内部细节。"""
        resp = self._client.post(
            "/api/system/open-config-file",
            json={},
            environ_overrides={"REMOTE_ADDR": "127.0.0.1"},
        )
        self.assertEqual(resp.status_code, 500)
        self.assertIn("editor", resp.get_json()["error"].lower())

    @patch("web_ui_routes.system.subprocess.Popen")
    @patch("web_ui_routes.system._detect_default_editor")
    def test_unknown_editor_param_falls_back_to_auto_detect(
        self, mock_detect, mock_popen
    ):
        """前端传入不在白名单的 editor → 忽略并退回自动探测。"""
        mock_detect.return_value = ("/usr/local/bin/code", ["--reuse-window"])
        mock_popen.return_value = MagicMock()

        resp = self._client.post(
            "/api/system/open-config-file",
            json={"editor": "notepad++"},
            environ_overrides={"REMOTE_ADDR": "127.0.0.1"},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json()["editor"], "code")

    @patch("web_ui_routes.system.subprocess.Popen")
    @patch("web_ui_routes.system.shutil.which")
    def test_explicit_editor_in_allowlist_used(self, mock_which, mock_popen):
        """前端显式 editor=cursor + cursor 在 PATH → 用 cursor。"""
        mock_which.side_effect = (
            lambda name: f"/opt/{name}" if name == "cursor" else None
        )
        mock_popen.return_value = MagicMock()

        resp = self._client.post(
            "/api/system/open-config-file",
            json={"editor": "cursor"},
            environ_overrides={"REMOTE_ADDR": "127.0.0.1"},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json()["editor"], "cursor")
        argv = mock_popen.call_args.args[0]
        self.assertEqual(argv[0], "/opt/cursor")

    @patch("web_ui_routes.system._system_open_command")
    @patch("web_ui_routes.system._detect_default_editor", return_value=(None, []))
    def test_explicit_system_editor_uses_fallback_directly(
        self, _mock_detect, mock_system
    ):
        """editor=system 即使有别的 IDE 也直接走系统 fallback。"""
        mock_system.return_value = ["/usr/bin/open", "/tmp/x"]
        with patch("web_ui_routes.system.subprocess.Popen") as mock_popen:
            mock_popen.return_value = MagicMock()
            resp = self._client.post(
                "/api/system/open-config-file",
                json={"editor": "system"},
                environ_overrides={"REMOTE_ADDR": "127.0.0.1"},
            )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json()["editor"], "system")

    @patch("web_ui_routes.system.subprocess.Popen")
    @patch("web_ui_routes.system._detect_default_editor")
    def test_popen_oserror_returns_500(self, mock_detect, mock_popen):
        """Popen 抛 OSError（如权限不足） → 500，错误信息不暴露 stderr。"""
        mock_detect.return_value = ("/opt/cursor", [])
        mock_popen.side_effect = OSError("Permission denied")

        resp = self._client.post(
            "/api/system/open-config-file",
            json={},
            environ_overrides={"REMOTE_ADDR": "127.0.0.1"},
        )
        self.assertEqual(resp.status_code, 500)
        self.assertIn("launch editor", resp.get_json()["error"].lower())

    @patch("web_ui_routes.system.subprocess.Popen")
    @patch("web_ui_routes.system._detect_default_editor")
    def test_popen_filenotfound_returns_500(self, mock_detect, mock_popen):
        """Popen FileNotFoundError（探测和启动之间 binary 消失）→ 500。"""
        mock_detect.return_value = ("/opt/cursor", [])
        mock_popen.side_effect = FileNotFoundError("binary vanished")

        resp = self._client.post(
            "/api/system/open-config-file",
            json={},
            environ_overrides={"REMOTE_ADDR": "127.0.0.1"},
        )
        self.assertEqual(resp.status_code, 500)
        self.assertIn("vanish", resp.get_json()["error"].lower())

    @patch("web_ui_routes.system._resolve_allowed_paths", return_value=[])
    def test_no_allowed_paths_returns_400(self, _mock_resolve):
        """server 端解析不出任何配置路径 → 400 拦截。

        这是「极端环境（如 read-only fs / 配置加载失败）」的兜底护栏，
        防止在没有可写配置的环境里盲启子进程。
        """
        resp = self._client.post(
            "/api/system/open-config-file",
            json={},
            environ_overrides={"REMOTE_ADDR": "127.0.0.1"},
        )
        self.assertEqual(resp.status_code, 400)
        data = resp.get_json()
        self.assertFalse(data["success"])
        self.assertIn("config file path", data["error"].lower())

    @patch("web_ui_routes.system._resolve_allowed_paths")
    def test_default_target_does_not_exist_returns_400(self, mock_resolve):
        """默认 target 在磁盘上不存在 → 400，不应继续启动子进程。

        动机：白名单里只声明了"允许打开的路径"，但若文件实际不存在，启动
        编辑器只会得到一个空 buffer / 报错弹窗，体验差且模糊。
        """
        ghost = Path("/tmp/aiia-nonexistent-config-aaaa-bbbb.toml")
        mock_resolve.return_value = [ghost]
        if ghost.exists():
            ghost.unlink()

        resp = self._client.post(
            "/api/system/open-config-file",
            json={},
            environ_overrides={"REMOTE_ADDR": "127.0.0.1"},
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("does not exist", resp.get_json()["error"].lower())

    @patch("web_ui_routes.system.subprocess.Popen")
    @patch("web_ui_routes.system.shutil.which")
    @patch("web_ui_routes.system._detect_default_editor")
    def test_explicit_editor_not_in_path_falls_back_to_auto_detect(
        self, mock_detect, mock_which, mock_popen
    ):
        """显式 editor 在白名单内但不在 PATH → 走自动探测，不直接 500。

        防止「用户在 dropdown 里选了 cursor，但 cursor 卸载了」时弹错误，
        而是平滑回退到 _detect_default_editor 找下一个可用编辑器。
        """
        mock_which.return_value = None
        mock_detect.return_value = ("/opt/code", ["--reuse-window"])
        mock_popen.return_value = MagicMock(pid=1234)

        resp = self._client.post(
            "/api/system/open-config-file",
            json={"editor": "cursor"},
            environ_overrides={"REMOTE_ADDR": "127.0.0.1"},
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data["success"])
        self.assertEqual(data["editor"], "code")


# ════════════════════════════════════════════════════════════════════════════
#  GET /api/system/open-config-file/info - 探测能力 endpoint
# ════════════════════════════════════════════════════════════════════════════
class TestOpenConfigFileInfoEndpoint(_SystemRouteBase):
    _port = 19111

    def test_non_loopback_returns_403(self):
        with patch("web_ui_routes.system._get_client_ip", return_value="10.0.0.1"):
            resp = self._client.get("/api/system/open-config-file/info")
        self.assertEqual(resp.status_code, 403)
        self.assertFalse(resp.get_json()["success"])

    @patch("web_ui_routes.system._detect_default_editor")
    def test_loopback_with_editor_returns_full_info(self, mock_detect):
        mock_detect.return_value = ("/opt/cursor", ["--reuse-window"])

        resp = self._client.get(
            "/api/system/open-config-file/info",
            environ_overrides={"REMOTE_ADDR": "127.0.0.1"},
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data["success"])
        self.assertEqual(data["editor"], "cursor")
        self.assertTrue(data["editor_available"])
        self.assertIsInstance(data["allowed_paths"], list)
        self.assertGreater(len(data["allowed_paths"]), 0)
        self.assertIsNotNone(data["primary_path"])

    @patch("web_ui_routes.system._detect_default_editor", return_value=(None, []))
    def test_loopback_without_editor_still_succeeds(self, _mock_detect):
        """探测不到 IDE 也不应返回错误，前端会用 system fallback 或禁用按钮。"""
        resp = self._client.get(
            "/api/system/open-config-file/info",
            environ_overrides={"REMOTE_ADDR": "127.0.0.1"},
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data["success"])
        self.assertIsNone(data["editor"])
        self.assertFalse(data["editor_available"])


# ════════════════════════════════════════════════════════════════════════════
#  内部 helper - 安全护栏单元测试（不经过 HTTP layer，更稳）
# ════════════════════════════════════════════════════════════════════════════
class TestSystemHelpers(unittest.TestCase):
    def test_resolve_loopback_ips_covers_v4_and_v6(self):
        from web_ui_routes.system import _resolve_loopback_ips

        ips = _resolve_loopback_ips()
        self.assertIn("127.0.0.1", ips)
        self.assertIn("::1", ips)

    def test_detect_default_editor_respects_env_override(self):
        from web_ui_routes import system as sys_mod

        with patch.dict(
            "os.environ", {"AI_INTERVENTION_AGENT_OPEN_WITH": "cursor"}, clear=False
        ):
            with patch.object(sys_mod.shutil, "which", return_value="/opt/cursor"):
                editor, extra = sys_mod._detect_default_editor()
        self.assertEqual(editor, "/opt/cursor")
        # env 覆盖时不带 --reuse-window 等隐式参数（环境变量是用户自己指定的）
        self.assertEqual(extra, [])

    def test_detect_default_editor_skips_invalid_env(self):
        """AI_INTERVENTION_AGENT_OPEN_WITH 指向不存在的 binary → 走自动探测。"""
        from web_ui_routes import system as sys_mod

        which_calls: list[str] = []

        def fake_which(name: str) -> str | None:
            which_calls.append(name)
            return "/opt/code" if name == "code" else None

        with patch.dict(
            "os.environ",
            {"AI_INTERVENTION_AGENT_OPEN_WITH": "nonexistent-editor"},
            clear=False,
        ):
            with patch.object(sys_mod.shutil, "which", side_effect=fake_which):
                editor, _ = sys_mod._detect_default_editor()
        self.assertEqual(editor, "/opt/code")
        self.assertIn("nonexistent-editor", which_calls)

    def test_resolve_allowed_paths_includes_default_template(self):
        """白名单除当前配置外应至少含仓库内的 default 模板。"""
        from web_ui_routes.system import _resolve_allowed_paths

        paths = _resolve_allowed_paths()
        path_strs = {str(p) for p in paths}
        self.assertTrue(
            any(s.endswith("config.toml.default") for s in path_strs)
            or any(s.endswith("config.jsonc.default") for s in path_strs),
            f"default 模板未出现在白名单中: {path_strs}",
        )

    def test_system_open_command_returns_argv_or_none(self):
        """_system_open_command 应返回可执行的 argv（list[str]） 或 None。"""
        from web_ui_routes.system import _system_open_command

        result = _system_open_command(Path("/tmp/dummy.toml"))
        if result is not None:
            self.assertIsInstance(result, list)
            self.assertGreater(len(result), 0)
            self.assertTrue(all(isinstance(s, str) for s in result))


if __name__ == "__main__":
    unittest.main()
