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
        from ai_intervention_agent.web_ui import WebFeedbackUI

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
        with patch(
            "ai_intervention_agent.web_ui_routes.system._get_client_ip",
            return_value="192.168.1.5",
        ):
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

    @patch("ai_intervention_agent.web_ui_routes.system.subprocess.Popen")
    @patch("ai_intervention_agent.web_ui_routes.system._detect_default_editor")
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

    @patch("ai_intervention_agent.web_ui_routes.system.subprocess.Popen")
    @patch("ai_intervention_agent.web_ui_routes.system._system_open_command")
    @patch("ai_intervention_agent.web_ui_routes.system._detect_default_editor")
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

    @patch(
        "ai_intervention_agent.web_ui_routes.system._system_open_command",
        return_value=None,
    )
    @patch(
        "ai_intervention_agent.web_ui_routes.system._detect_default_editor",
        return_value=(None, []),
    )
    def test_no_editor_no_system_fallback_returns_500(self, *_):
        """所有打开方式都不可用 → 500，且文案不暴露内部细节。"""
        resp = self._client.post(
            "/api/system/open-config-file",
            json={},
            environ_overrides={"REMOTE_ADDR": "127.0.0.1"},
        )
        self.assertEqual(resp.status_code, 500)
        self.assertIn("editor", resp.get_json()["error"].lower())

    @patch("ai_intervention_agent.web_ui_routes.system.subprocess.Popen")
    @patch("ai_intervention_agent.web_ui_routes.system._detect_default_editor")
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

    @patch("ai_intervention_agent.web_ui_routes.system.subprocess.Popen")
    @patch("ai_intervention_agent.web_ui_routes.system.shutil.which")
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

    @patch("ai_intervention_agent.web_ui_routes.system._system_open_command")
    @patch(
        "ai_intervention_agent.web_ui_routes.system._detect_default_editor",
        return_value=(None, []),
    )
    def test_explicit_system_editor_uses_fallback_directly(
        self, _mock_detect, mock_system
    ):
        """editor=system 即使有别的 IDE 也直接走系统 fallback。"""
        mock_system.return_value = ["/usr/bin/open", "/tmp/x"]
        with patch(
            "ai_intervention_agent.web_ui_routes.system.subprocess.Popen"
        ) as mock_popen:
            mock_popen.return_value = MagicMock()
            resp = self._client.post(
                "/api/system/open-config-file",
                json={"editor": "system"},
                environ_overrides={"REMOTE_ADDR": "127.0.0.1"},
            )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json()["editor"], "system")

    @patch("ai_intervention_agent.web_ui_routes.system.subprocess.Popen")
    @patch("ai_intervention_agent.web_ui_routes.system._detect_default_editor")
    def test_popen_oserror_returns_500(self, mock_detect, mock_popen):
        """Popen 抛 OSError（如权限不足） → 500，错误信息不暴露 stderr。

        R72-B（CodeQL py/stack-trace-exposure 修复）锁定：错误响应仅包含
        generic "check server logs" 提示，**不能** 把 OSError 的 detail
        （这里是 "Permission denied"，更恶意的场景下可能包含路径、errno、
        系统库版本等）回传给客户端——这些都属于"对外可见的 stack-trace 类
        信息泄漏"。详情写到服务器 log（已经 ``exc_info=True``）。
        """
        mock_detect.return_value = ("/opt/cursor", [])
        mock_popen.side_effect = OSError("Permission denied")

        resp = self._client.post(
            "/api/system/open-config-file",
            json={},
            environ_overrides={"REMOTE_ADDR": "127.0.0.1"},
        )
        self.assertEqual(resp.status_code, 500)
        body = resp.get_json()
        self.assertIn("launch editor", body["error"].lower())
        self.assertIn(
            "check server logs",
            body["error"].lower(),
            "R72-B 契约：错误信息必须引导运维去查日志",
        )
        self.assertNotIn(
            "Permission denied",
            body["error"],
            "R72-B 契约：OSError 的原始 detail 不能泄漏给客户端",
        )

    @patch("ai_intervention_agent.web_ui_routes.system.subprocess.Popen")
    @patch("ai_intervention_agent.web_ui_routes.system._detect_default_editor")
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

    @patch(
        "ai_intervention_agent.web_ui_routes.system._resolve_allowed_paths",
        return_value=[],
    )
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

    @patch("ai_intervention_agent.web_ui_routes.system._resolve_allowed_paths")
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

    @patch("ai_intervention_agent.web_ui_routes.system.subprocess.Popen")
    @patch("ai_intervention_agent.web_ui_routes.system.shutil.which")
    @patch("ai_intervention_agent.web_ui_routes.system._detect_default_editor")
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
        with patch(
            "ai_intervention_agent.web_ui_routes.system._get_client_ip",
            return_value="10.0.0.1",
        ):
            resp = self._client.get("/api/system/open-config-file/info")
        self.assertEqual(resp.status_code, 403)
        self.assertFalse(resp.get_json()["success"])

    @patch("ai_intervention_agent.web_ui_routes.system._detect_default_editor")
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

    @patch(
        "ai_intervention_agent.web_ui_routes.system._detect_default_editor",
        return_value=(None, []),
    )
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
        from ai_intervention_agent.web_ui_routes.system import _resolve_loopback_ips

        ips = _resolve_loopback_ips()
        self.assertIn("127.0.0.1", ips)
        self.assertIn("::1", ips)

    def test_detect_default_editor_respects_env_override(self):
        from ai_intervention_agent.web_ui_routes import system as sys_mod

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
        from ai_intervention_agent.web_ui_routes import system as sys_mod

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
        from ai_intervention_agent.web_ui_routes.system import _resolve_allowed_paths

        paths = _resolve_allowed_paths()
        path_strs = {str(p) for p in paths}
        # R76 起仅 ``config.toml.default`` 随包发布；JSONC 模板已移除。
        self.assertTrue(
            any(s.endswith("config.toml.default") for s in path_strs),
            f"default 模板未出现在白名单中: {path_strs}",
        )

    def test_system_open_command_returns_argv_or_none(self):
        """_system_open_command 应返回可执行的 argv（list[str]） 或 None。"""
        from ai_intervention_agent.web_ui_routes.system import _system_open_command

        result = _system_open_command(Path("/tmp/dummy.toml"))
        if result is not None:
            self.assertIsInstance(result, list)
            self.assertGreater(len(result), 0)
            self.assertTrue(all(isinstance(s, str) for s in result))


# ════════════════════════════════════════════════════════════════════════════
#  GET /api/system/network-base-url-status — 探测 effective base URL 是否对外可达
# ════════════════════════════════════════════════════════════════════════════
class TestNetworkBaseUrlStatusEndpoint(_SystemRouteBase):
    """R77 补测：原 endpoint 在 web_ui_routes/system.py L445-489 完全无覆盖。

    目标：锁定四种 status 推荐的输出契约（``ok`` / ``configure_external_base_url``
    / ``bind_lan_interface`` + 内部异常 fallback 500）。
    """

    _port = 19130

    def _patch_resolvers(
        self,
        *,
        effective: str = "",
        external_safe: str = "",
        is_loopback: bool = False,
        suggested_lan: str = "",
    ):
        """构造 server_config 三个查询函数的 mock 组合。"""
        server_config = "ai_intervention_agent.web_ui_routes.system.server_config"

        # resolve_external_base_url 是双调用：第 1 次拿 effective，第 2 次（带
        # for_external_use=True）拿 external_safe。用 side_effect 的函数 mock
        # 区分两路：
        def _resolve_external(*_args, **kwargs):
            if kwargs.get("for_external_use"):
                return external_safe
            return effective

        return [
            patch(
                "ai_intervention_agent.server_config.resolve_external_base_url",
                side_effect=_resolve_external,
            ),
            patch(
                "ai_intervention_agent.server_config.is_loopback_url",
                return_value=is_loopback,
            ),
            patch(
                "ai_intervention_agent.server_config.suggest_lan_base_url",
                return_value=suggested_lan or None,
            ),
        ]

    def _get(self):
        return self._client.get("/api/system/network-base-url-status")

    def test_external_safe_url_recommends_ok(self):
        """非 loopback + 有 external_safe → recommendation = ``ok``。"""
        patches = self._patch_resolvers(
            effective="http://10.0.0.5:8080",
            external_safe="http://10.0.0.5:8080",
            is_loopback=False,
        )
        with patches[0], patches[1], patches[2]:
            resp = self._get()
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertTrue(body["success"])
        self.assertEqual(body["recommendation"], "ok")
        self.assertFalse(body["is_loopback"])
        self.assertEqual(body["effective_base_url"], "http://10.0.0.5:8080")

    def test_loopback_with_lan_suggestion_recommends_configure(self):
        """loopback effective + 有 LAN 候选 → recommendation = ``configure_external_base_url``。"""
        patches = self._patch_resolvers(
            effective="http://127.0.0.1:8080",
            external_safe="",
            is_loopback=True,
            suggested_lan="http://192.168.1.10:8080",
        )
        with patches[0], patches[1], patches[2]:
            resp = self._get()
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertEqual(body["recommendation"], "configure_external_base_url")
        self.assertTrue(body["is_loopback"])
        self.assertEqual(body["suggested_lan_base_url"], "http://192.168.1.10:8080")

    def test_loopback_without_lan_suggestion_recommends_bind_lan(self):
        """loopback + 无 LAN 候选 → recommendation = ``bind_lan_interface``。"""
        patches = self._patch_resolvers(
            effective="http://127.0.0.1:8080",
            external_safe="",
            is_loopback=True,
            suggested_lan="",
        )
        with patches[0], patches[1], patches[2]:
            resp = self._get()
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertEqual(body["recommendation"], "bind_lan_interface")
        self.assertTrue(body["is_loopback"])
        self.assertEqual(body["suggested_lan_base_url"], "")

    def test_internal_exception_returns_500(self):
        """resolver 抛异常时 endpoint 返回 500，并不泄漏 stack trace。"""
        with patch(
            "ai_intervention_agent.server_config.resolve_external_base_url",
            side_effect=RuntimeError("boom"),
        ):
            resp = self._get()
        self.assertEqual(resp.status_code, 500)
        body = resp.get_json()
        self.assertFalse(body["success"])
        self.assertNotIn("boom", body.get("error", ""))


# ════════════════════════════════════════════════════════════════════════════
#  GET /api/system/health — K8s probe 友好的综合健康检查
# ════════════════════════════════════════════════════════════════════════════
class TestSystemHealthEndpoint(_SystemRouteBase):
    """R77 补测：原 endpoint 在 web_ui_routes/system.py L602-681 完全无覆盖。

    目标：锁定三档 status enum（``healthy`` / ``degraded`` / ``unhealthy``）
    的判定边界，特别是 backpressure / recent-error 数值的强制 int 守卫。
    """

    _port = 19131

    def _get(self):
        return self._client.get("/api/system/health")

    def test_healthy_when_all_checks_pass(self):
        """SSE bus + TaskQueue + recent_errors 都正常 + 0 错误 → healthy + 200。"""
        with (
            patch(
                "ai_intervention_agent.enhanced_logging.get_recent_error_stats",
                return_value=(0, 0),
            ),
        ):
            resp = self._get()
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertEqual(body["status"], "healthy")
        self.assertIn("checks", body)
        self.assertTrue(body["checks"]["sse_bus"]["ok"])
        self.assertTrue(body["checks"]["task_queue"]["ok"])
        self.assertTrue(body["checks"]["recent_errors"]["ok"])

    def test_degraded_when_recent_errors_seen(self):
        """近 5 分钟有 ERROR 但所有检查 ok → degraded + 200（K8s 不应重启）。"""
        with patch(
            "ai_intervention_agent.enhanced_logging.get_recent_error_stats",
            return_value=(1, 1),
        ):
            resp = self._get()
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertEqual(body["status"], "degraded")
        self.assertEqual(body["checks"]["recent_errors"]["count_last_5min"], 1)

    def test_unhealthy_when_subsystem_check_fails(self):
        """任意子检查抛异常 → unhealthy + 503（K8s readiness probe 不发流量）。"""
        with patch(
            "ai_intervention_agent.web_ui_routes.task._sse_bus.stats_snapshot",
            side_effect=RuntimeError("sse bus crashed"),
        ):
            resp = self._get()
        self.assertEqual(resp.status_code, 503)
        body = resp.get_json()
        self.assertEqual(body["status"], "unhealthy")
        self.assertFalse(body["checks"]["sse_bus"]["ok"])

    def test_payload_carries_no_sensitive_fields(self):
        """规约：payload 必须不含 prompt 内容 / config 值（只有数值/enum/路径）。

        R121-A 扩展了顶层 schema，加入 ``version`` / ``uptime_seconds`` /
        ``config_file_path`` 三个**显式非敏感**的诊断字段。本测试同步演进：
        从"key set 必须严格等于 R53-F 的 3 个字段"改为"key set 必须是
        R53-F + R121-A 的白名单子集"，并对每个新字段单独断言其类型 +
        非敏感语义。这样既保留了"不允许偷偷加新字段"的回归保护，也允许
        R121-A 这种 *显式* 演进。
        """
        with patch(
            "ai_intervention_agent.enhanced_logging.get_recent_error_stats",
            return_value=(0, 0),
        ):
            resp = self._get()
        body = resp.get_json()
        # R53-F 原始字段 + R121-A 新增字段 + R132 新增字段，且**只能是这些**
        allowed_keys = {
            # R53-F 原 schema
            "status",
            "ts_unix",
            "checks",
            # R121-A 新增（每个都有专项类型断言，确保不偷渡敏感字段）
            "version",
            "uptime_seconds",
            "config_file_path",
            # R132 新增：build info（git_commit / git_branch / git_dirty）
            "build",
            # CR#15 续：web_ui env override 名单（host/port/language 白名单）
            "web_ui_env_overrides",
        }
        actual_keys = set(body.keys())
        self.assertTrue(
            actual_keys.issubset(allowed_keys),
            f"payload 多了未授权的顶层字段 {actual_keys - allowed_keys}，"
            "新增任何顶层字段都必须先扩白名单 + 加专项类型断言",
        )
        self.assertIsInstance(body["ts_unix"], int)

        # R121-A 字段类型 + 非敏感性专项断言
        # version 必须是 str 或 None（探测失败可降级），不允许 dict/list 等可
        # 能携带 config 值的复合结构
        if "version" in body:
            self.assertTrue(
                body["version"] is None or isinstance(body["version"], str),
                "version 字段必须是字符串或 None",
            )

        # uptime_seconds 必须是数值或 None，不允许字符串（避免泄漏 ISO 时
        # 间戳里的时区配置等）
        if "uptime_seconds" in body:
            self.assertTrue(
                body["uptime_seconds"] is None
                or isinstance(body["uptime_seconds"], int | float),
                "uptime_seconds 字段必须是数值或 None",
            )

        # config_file_path 必须是字符串路径或 None；同时**不能**是绝对路径
        # 之外的任何东西（防止泄漏 dict 化的 config 内容）
        if "config_file_path" in body:
            cfp = body["config_file_path"]
            self.assertTrue(
                cfp is None or isinstance(cfp, str),
                "config_file_path 字段必须是字符串或 None",
            )

        # R132：build 必须是 dict 或 None；dict 时严格仅含 git_commit /
        # git_branch / git_dirty 三个字符串字段——绝不能允许 dict 透出
        # 任何 config 值 / token / path 之外的复合结构
        if "build" in body:
            build = body["build"]
            self.assertTrue(
                build is None or isinstance(build, dict),
                "build 字段必须是 dict 或 None",
            )
            if isinstance(build, dict):
                self.assertEqual(
                    set(build.keys()),
                    {"git_commit", "git_branch", "git_dirty"},
                    "build 字段必须严格仅含 git_commit / git_branch / git_dirty",
                )
                for k, v in build.items():
                    self.assertIsInstance(
                        v, str, f"build.{k} 必须是字符串（含 'unknown' 兜底）"
                    )

        # CR#15 续：web_ui_env_overrides 必须是 dict 或 None；dict 时严格
        # 仅允许 web_ui 三个白名单 env var key，**绝不**接受任意 key——避
        # 免未来加新 env override 时悄悄扩面到敏感字段。
        if "web_ui_env_overrides" in body:
            overrides = body["web_ui_env_overrides"]
            self.assertTrue(
                overrides is None or isinstance(overrides, dict),
                "web_ui_env_overrides 字段必须是 dict 或 None",
            )
            if isinstance(overrides, dict):
                allowed_env_keys = {
                    "AI_INTERVENTION_AGENT_WEB_UI_HOST",
                    "AI_INTERVENTION_AGENT_WEB_UI_PORT",
                    "AI_INTERVENTION_AGENT_WEB_UI_LANGUAGE",
                }
                self.assertTrue(
                    set(overrides.keys()).issubset(allowed_env_keys),
                    f"web_ui_env_overrides 出现白名单外 key："
                    f"{set(overrides.keys()) - allowed_env_keys}",
                )
                for k, v in overrides.items():
                    self.assertIsInstance(
                        v,
                        str,
                        f"web_ui_env_overrides[{k}] 必须是字符串值",
                    )

        # checks 必须是 dict，每个 sub-check 都是 dict 含 ok 字段
        # 这是 R53-F 已有的 invariant；R121-A 加了 notification 子检查，
        # 也必须满足同样形态
        self.assertIsInstance(body["checks"], dict)
        for check_name, check_value in body["checks"].items():
            self.assertIsInstance(
                check_value,
                dict,
                f"checks[{check_name!r}] 必须是 dict",
            )
            self.assertIn(
                "ok",
                check_value,
                f"checks[{check_name!r}] 必须有 ok 字段",
            )


# ════════════════════════════════════════════════════════════════════════════
#  GET /api/system/recent-logs — ring buffer 最近 N 条 WARN/ERROR 日志摘要
# ════════════════════════════════════════════════════════════════════════════
class TestSystemRecentLogsEndpoint(_SystemRouteBase):
    """R77 补测：原 endpoint 在 web_ui_routes/system.py L740-768 完全无覆盖。

    目标：锁定 limit 边界（默认 50 / 上限 _LOG_RING_MAXLEN / 非法值降级），
    确认正常路径返回 ring buffer 已脱敏快照。
    """

    _port = 19132

    def _get(self, **params):
        return self._client.get("/api/system/recent-logs", query_string=params)

    def test_default_limit_is_50(self):
        """默认 limit=50 应传给 get_recent_logs。"""
        with patch(
            "ai_intervention_agent.enhanced_logging.get_recent_logs",
            return_value=[],
        ) as mock_get:
            resp = self._get()
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertTrue(body["success"])
        self.assertEqual(body["count"], 0)
        mock_get.assert_called_once_with(limit=50)

    def test_explicit_limit_is_passed_through(self):
        """合法范围内的 limit 直接透传到 get_recent_logs。"""
        with patch(
            "ai_intervention_agent.enhanced_logging.get_recent_logs",
            return_value=[],
        ) as mock_get:
            self._get(limit=37)
        mock_get.assert_called_once_with(limit=37)

    def test_invalid_limit_falls_back_to_default(self):
        """非数字 limit → 用默认 50；不返回 400（避免轻易因输入错被拒）。"""
        with patch(
            "ai_intervention_agent.enhanced_logging.get_recent_logs",
            return_value=[],
        ) as mock_get:
            resp = self._get(limit="not-a-number")
        self.assertEqual(resp.status_code, 200)
        mock_get.assert_called_once_with(limit=50)

    def test_limit_above_buffer_capacity_falls_back_to_default(self):
        """limit > _LOG_RING_MAXLEN → 用默认 50（不直接 cap 是为了让客户端意识到上限）。"""
        from ai_intervention_agent.enhanced_logging import _LOG_RING_MAXLEN

        with patch(
            "ai_intervention_agent.enhanced_logging.get_recent_logs",
            return_value=[],
        ) as mock_get:
            self._get(limit=_LOG_RING_MAXLEN + 100)
        mock_get.assert_called_once_with(limit=50)

    def test_zero_limit_falls_back_to_default(self):
        """limit=0 不在 [1, MAX] 范围内 → 用默认 50。"""
        with patch(
            "ai_intervention_agent.enhanced_logging.get_recent_logs",
            return_value=[],
        ) as mock_get:
            self._get(limit=0)
        mock_get.assert_called_once_with(limit=50)

    def test_returns_entries_in_payload(self):
        """非空 ring buffer → entries 列表透传 + count 正确。"""
        fake_entries = [
            {
                "ts_unix": 1700000000,
                "level_no": 30,
                "level_name": "WARNING",
                "logger_name": "x",
                "message": "warn 1",
            },
            {
                "ts_unix": 1700000010,
                "level_no": 40,
                "level_name": "ERROR",
                "logger_name": "y",
                "message": "err 2",
            },
        ]
        with patch(
            "ai_intervention_agent.enhanced_logging.get_recent_logs",
            return_value=fake_entries,
        ):
            resp = self._get(limit=2)
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertEqual(body["count"], 2)
        self.assertEqual(body["entries"], fake_entries)

    def test_internal_exception_returns_500(self):
        """get_recent_logs 抛异常时 endpoint 返回 500，错误信息不泄漏内部细节。"""
        with patch(
            "ai_intervention_agent.enhanced_logging.get_recent_logs",
            side_effect=RuntimeError("ring buffer corruption"),
        ):
            resp = self._get()
        self.assertEqual(resp.status_code, 500)
        body = resp.get_json()
        self.assertFalse(body["success"])
        self.assertNotIn("ring buffer corruption", body.get("error", ""))


if __name__ == "__main__":
    unittest.main()
