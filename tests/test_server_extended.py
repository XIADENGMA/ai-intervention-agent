"""server.py 单元测试 — 工具函数、ServiceManager、HTTP 交互、异步等待。"""

from __future__ import annotations

import asyncio
import signal
import socket
import subprocess
import threading
import unittest
from pathlib import Path
from unittest.mock import MagicMock, PropertyMock, patch

import requests
from mcp.types import TextContent

import server
from exceptions import (
    ServiceConnectionError,
    ServiceTimeoutError,
    ServiceUnavailableError,
    ValidationError,
)
from server_config import WebUIConfig

_SERVER_DIR = Path(server.__file__ or ".").resolve().parent


# ---------------------------------------------------------------------------
# 辅助工具
# ---------------------------------------------------------------------------
def _make_config(
    host: str = "127.0.0.1",
    port: int = 8080,
    timeout: int = 30,
    max_retries: int = 3,
    retry_delay: float = 1.0,
) -> WebUIConfig:
    return WebUIConfig(
        host=host,
        port=port,
        timeout=timeout,
        max_retries=max_retries,
        retry_delay=retry_delay,
    )


# ═══════════════════════════════════════════════════════════════════════════
#  配置缓存回调
# ═══════════════════════════════════════════════════════════════════════════
class TestInvalidateRuntimeCaches(unittest.TestCase):
    def test_clears_config_cache(self):
        with server._config_cache_lock:
            server._config_cache["config"] = "stale"
            server._config_cache["timestamp"] = 999

        server._invalidate_runtime_caches_on_config_change()

        with server._config_cache_lock:
            self.assertIsNone(server._config_cache["config"])
            self.assertEqual(server._config_cache["timestamp"], 0)

    def test_increments_session_generation(self):
        with server._http_session_lock:
            old = server._http_session_generation

        server._invalidate_runtime_caches_on_config_change()

        with server._http_session_lock:
            self.assertEqual(server._http_session_generation, old + 1)


class TestEnsureConfigCallbacksRegistered(unittest.TestCase):
    def test_registers_once(self):
        original = server._config_callbacks_registered
        server._config_callbacks_registered = False
        try:
            mock_cfg = MagicMock()
            with patch("server.get_config", return_value=mock_cfg):
                server._ensure_config_change_callbacks_registered()
                self.assertTrue(server._config_callbacks_registered)
                mock_cfg.register_config_change_callback.assert_called_once()
        finally:
            server._config_callbacks_registered = original

    def test_double_check_lock_skip(self):
        original = server._config_callbacks_registered
        server._config_callbacks_registered = True
        try:
            server._ensure_config_change_callbacks_registered()
        finally:
            server._config_callbacks_registered = original

    def test_exception_does_not_crash(self):
        original = server._config_callbacks_registered
        server._config_callbacks_registered = False
        try:
            with patch("server.get_config", side_effect=RuntimeError("no config")):
                server._ensure_config_change_callbacks_registered()
                self.assertTrue(server._config_callbacks_registered)
        finally:
            server._config_callbacks_registered = original


# ═══════════════════════════════════════════════════════════════════════════
#  get_task_queue / _shutdown_global_task_queue
# ═══════════════════════════════════════════════════════════════════════════
class TestGetTaskQueue(unittest.TestCase):
    def test_lazy_init(self):
        original = server._global_task_queue
        server._global_task_queue = None
        try:
            tq = server.get_task_queue()
            self.assertIsNotNone(tq)
            same = server.get_task_queue()
            self.assertIs(tq, same)
        finally:
            server._global_task_queue = original


class TestShutdownGlobalTaskQueue(unittest.TestCase):
    def test_with_running_queue(self):
        original = server._global_task_queue
        mock_tq = MagicMock()
        server._global_task_queue = mock_tq
        try:
            server._shutdown_global_task_queue()
            mock_tq.stop_cleanup.assert_called_once()
        finally:
            server._global_task_queue = original

    def test_with_none_queue(self):
        original = server._global_task_queue
        server._global_task_queue = None
        try:
            server._shutdown_global_task_queue()
        finally:
            server._global_task_queue = original

    def test_exception_suppressed(self):
        original = server._global_task_queue
        mock_tq = MagicMock()
        mock_tq.stop_cleanup.side_effect = RuntimeError("oops")
        server._global_task_queue = mock_tq
        try:
            server._shutdown_global_task_queue()
        finally:
            server._global_task_queue = original


# ═══════════════════════════════════════════════════════════════════════════
#  ServiceManager
# ═══════════════════════════════════════════════════════════════════════════
class TestServiceManager(unittest.TestCase):
    def setUp(self):
        server.ServiceManager._instance = None
        server.ServiceManager._lock = threading.Lock()

    def tearDown(self):
        server.ServiceManager._instance = None

    def test_singleton(self):
        sm1 = server.ServiceManager()
        sm2 = server.ServiceManager()
        self.assertIs(sm1, sm2)

    def test_register_and_get_process(self):
        sm = server.ServiceManager()
        mock_proc = MagicMock(spec=subprocess.Popen)
        mock_proc.pid = 12345
        cfg = _make_config()

        sm.register_process("test_svc", mock_proc, cfg)
        self.assertIs(sm.get_process("test_svc"), mock_proc)

    def test_get_process_not_found(self):
        sm = server.ServiceManager()
        self.assertIsNone(sm.get_process("nonexistent"))

    def test_unregister_process(self):
        sm = server.ServiceManager()
        mock_proc = MagicMock(spec=subprocess.Popen)
        mock_proc.pid = 100
        sm.register_process("s1", mock_proc, _make_config())
        sm.unregister_process("s1")
        self.assertIsNone(sm.get_process("s1"))

    def test_unregister_nonexistent(self):
        sm = server.ServiceManager()
        sm.unregister_process("nope")

    def test_is_process_running_true(self):
        sm = server.ServiceManager()
        mock_proc = MagicMock(spec=subprocess.Popen)
        mock_proc.pid = 200
        mock_proc.poll.return_value = None
        sm.register_process("running", mock_proc, _make_config())
        self.assertTrue(sm.is_process_running("running"))

    def test_is_process_running_false_exited(self):
        sm = server.ServiceManager()
        mock_proc = MagicMock(spec=subprocess.Popen)
        mock_proc.pid = 201
        mock_proc.poll.return_value = 0
        sm.register_process("exited", mock_proc, _make_config())
        self.assertFalse(sm.is_process_running("exited"))

    def test_is_process_running_not_registered(self):
        sm = server.ServiceManager()
        self.assertFalse(sm.is_process_running("ghost"))

    def test_is_process_running_poll_exception(self):
        sm = server.ServiceManager()
        mock_proc = MagicMock(spec=subprocess.Popen)
        mock_proc.pid = 202
        mock_proc.poll.side_effect = OSError("gone")
        sm.register_process("error", mock_proc, _make_config())
        self.assertFalse(sm.is_process_running("error"))

    @patch("server.is_web_service_running", return_value=False)
    def test_terminate_already_exited(self, _):
        sm = server.ServiceManager()
        mock_proc = MagicMock(spec=subprocess.Popen)
        mock_proc.pid = 300
        mock_proc.poll.return_value = 0
        mock_proc.stdin = None
        mock_proc.stdout = None
        mock_proc.stderr = None
        sm.register_process("done", mock_proc, _make_config())
        self.assertTrue(sm.terminate_process("done"))
        self.assertIsNone(sm.get_process("done"))

    @patch("server.is_web_service_running", return_value=False)
    def test_terminate_graceful(self, _):
        sm = server.ServiceManager()
        mock_proc = MagicMock(spec=subprocess.Popen)
        mock_proc.pid = 301
        mock_proc.poll.side_effect = [None, 0]
        mock_proc.stdin = None
        mock_proc.stdout = None
        mock_proc.stderr = None
        sm.register_process("graceful", mock_proc, _make_config())
        self.assertTrue(sm.terminate_process("graceful", timeout=1.0))
        mock_proc.terminate.assert_called_once()

    @patch("server.is_web_service_running", return_value=False)
    def test_terminate_force_kill(self, _):
        sm = server.ServiceManager()
        mock_proc = MagicMock(spec=subprocess.Popen)
        mock_proc.pid = 302
        mock_proc.poll.side_effect = [None, None, 0]
        mock_proc.terminate.side_effect = None
        mock_proc.wait.side_effect = [subprocess.TimeoutExpired("cmd", 5), None]
        mock_proc.stdin = None
        mock_proc.stdout = None
        mock_proc.stderr = None
        sm.register_process("force", mock_proc, _make_config())
        result = sm.terminate_process("force", timeout=0.1)
        mock_proc.kill.assert_called_once()

    def test_terminate_not_registered(self):
        sm = server.ServiceManager()
        self.assertTrue(sm.terminate_process("nobody"))

    @patch("server.is_web_service_running", return_value=False)
    def test_cleanup_all_with_processes(self, _):
        sm = server.ServiceManager()
        for i in range(2):
            mock_proc = MagicMock(spec=subprocess.Popen)
            mock_proc.pid = 400 + i
            mock_proc.poll.return_value = 0
            mock_proc.stdin = None
            mock_proc.stdout = None
            mock_proc.stderr = None
            sm.register_process(f"svc_{i}", mock_proc, _make_config())

        sm.cleanup_all(shutdown_notification_manager=False)
        self.assertEqual(sm.get_status(), {})

    def test_cleanup_all_empty(self):
        sm = server.ServiceManager()
        sm.cleanup_all(shutdown_notification_manager=False)

    def test_get_status(self):
        sm = server.ServiceManager()
        mock_proc = MagicMock(spec=subprocess.Popen)
        mock_proc.pid = 500
        mock_proc.poll.return_value = None
        cfg = _make_config(port=9999)
        sm.register_process("status_test", mock_proc, cfg)

        status = sm.get_status()
        self.assertIn("status_test", status)
        self.assertEqual(status["status_test"]["pid"], 500)
        self.assertTrue(status["status_test"]["running"])

    def test_signal_handler_main_thread(self):
        sm = server.ServiceManager()
        with patch.object(sm, "cleanup_all"):
            sm._signal_handler(2, None)
            self.assertTrue(sm._should_exit)

    @patch("server.is_web_service_running", return_value=False)
    def test_cleanup_process_resources(self, _):
        sm = server.ServiceManager()
        mock_proc = MagicMock(spec=subprocess.Popen)
        mock_proc.pid = 600
        mock_proc.stdin = MagicMock()
        mock_proc.stdout = MagicMock()
        mock_proc.stderr = MagicMock()

        sm._cleanup_process_resources("test", {"process": mock_proc})
        mock_proc.stdin.close.assert_called_once()
        mock_proc.stdout.close.assert_called_once()
        mock_proc.stderr.close.assert_called_once()

    @patch("server.is_web_service_running", return_value=False)
    def test_graceful_shutdown_timeout(self, _):
        sm = server.ServiceManager()
        mock_proc = MagicMock(spec=subprocess.Popen)
        mock_proc.wait.side_effect = subprocess.TimeoutExpired("cmd", 1)
        self.assertFalse(sm._graceful_shutdown(mock_proc, "test", 0.1))

    @patch("server.is_web_service_running", return_value=False)
    def test_graceful_shutdown_exception(self, _):
        sm = server.ServiceManager()
        mock_proc = MagicMock(spec=subprocess.Popen)
        mock_proc.terminate.side_effect = OSError("no process")
        self.assertFalse(sm._graceful_shutdown(mock_proc, "test", 0.1))

    @patch("server.is_web_service_running", return_value=False)
    def test_force_shutdown_timeout(self, _):
        sm = server.ServiceManager()
        mock_proc = MagicMock(spec=subprocess.Popen)
        mock_proc.wait.side_effect = subprocess.TimeoutExpired("cmd", 2)
        self.assertFalse(sm._force_shutdown(mock_proc, "test"))

    @patch("server.is_web_service_running", return_value=False)
    def test_force_shutdown_exception(self, _):
        sm = server.ServiceManager()
        mock_proc = MagicMock(spec=subprocess.Popen)
        mock_proc.kill.side_effect = OSError("no process")
        self.assertFalse(sm._force_shutdown(mock_proc, "test"))


# ═══════════════════════════════════════════════════════════════════════════
#  get_web_ui_config
# ═══════════════════════════════════════════════════════════════════════════
class TestGetWebUIConfig(unittest.TestCase):
    def setUp(self):
        with server._config_cache_lock:
            self._orig_cache = dict(server._config_cache)
            server._config_cache["config"] = None
            server._config_cache["timestamp"] = 0

    def tearDown(self):
        with server._config_cache_lock:
            server._config_cache.update(self._orig_cache)

    @patch("server.get_config")
    @patch("server._ensure_config_change_callbacks_registered")
    def test_load_config_success(self, _, mock_get_cfg):
        mock_cfg = MagicMock()
        mock_cfg.get_section.side_effect = lambda sec: {
            "web_ui": {"host": "127.0.0.1", "port": 8080},
            "feedback": {},
            "network_security": {},
        }.get(sec, {})
        mock_get_cfg.return_value = mock_cfg

        config, timeout = server.get_web_ui_config()
        self.assertIsInstance(config, WebUIConfig)
        self.assertEqual(config.port, 8080)

    @patch("server.get_config")
    @patch("server._ensure_config_change_callbacks_registered")
    def test_cache_hit(self, _, mock_get_cfg):
        mock_cfg = MagicMock()
        mock_cfg.get_section.side_effect = lambda sec: {
            "web_ui": {"port": 9090},
            "feedback": {},
            "network_security": {},
        }.get(sec, {})
        mock_get_cfg.return_value = mock_cfg

        cfg1, _ = server.get_web_ui_config()
        cfg2, _ = server.get_web_ui_config()
        self.assertEqual(cfg1.port, cfg2.port)
        self.assertEqual(mock_get_cfg.call_count, 1)

    @patch("server.get_config", side_effect=ValueError("bad config"))
    @patch("server._ensure_config_change_callbacks_registered")
    def test_value_error_raises(self, _, __):
        with self.assertRaises(ValueError):
            server.get_web_ui_config()

    @patch("server.get_config", side_effect=RuntimeError("unexpected"))
    @patch("server._ensure_config_change_callbacks_registered")
    def test_generic_error_raises(self, _, __):
        with self.assertRaises(ValueError):
            server.get_web_ui_config()


# ═══════════════════════════════════════════════════════════════════════════
#  create_http_session
# ═══════════════════════════════════════════════════════════════════════════
class TestCreateHttpSession(unittest.TestCase):
    def test_creates_session(self):
        cfg = _make_config()
        session = server.create_http_session(cfg)
        self.assertIsInstance(session, requests.Session)

    def test_cache_reuse(self):
        cfg = _make_config()
        s1 = server.create_http_session(cfg)
        s2 = server.create_http_session(cfg)
        self.assertIs(s1, s2)

    def test_different_config_different_session(self):
        cfg1 = _make_config(max_retries=3)
        cfg2 = _make_config(max_retries=5)
        s1 = server.create_http_session(cfg1)
        s2 = server.create_http_session(cfg2)
        self.assertIsNot(s1, s2)

    def test_generation_change_clears_cache(self):
        cfg = _make_config()
        s1 = server.create_http_session(cfg)
        with server._http_session_lock:
            server._http_session_generation += 1
        s2 = server.create_http_session(cfg)
        self.assertIsNot(s1, s2)


# ═══════════════════════════════════════════════════════════════════════════
#  is_web_service_running
# ═══════════════════════════════════════════════════════════════════════════
class TestIsWebServiceRunning(unittest.TestCase):
    def test_invalid_port(self):
        self.assertFalse(server.is_web_service_running("localhost", 0))
        self.assertFalse(server.is_web_service_running("localhost", 70000))

    @patch("server.socket.getaddrinfo", side_effect=socket.gaierror("resolve fail"))
    def test_dns_failure(self, _):
        self.assertFalse(server.is_web_service_running("bad.host", 8080))

    @patch("server.socket.getaddrinfo")
    @patch("server.socket.socket")
    def test_connection_success(self, mock_sock_cls, mock_getaddr):
        mock_getaddr.return_value = [
            (socket.AF_INET, socket.SOCK_STREAM, 0, "", ("127.0.0.1", 8080))
        ]
        mock_sock = MagicMock()
        mock_sock.connect_ex.return_value = 0
        mock_sock.__enter__ = MagicMock(return_value=mock_sock)
        mock_sock.__exit__ = MagicMock(return_value=False)
        mock_sock_cls.return_value = mock_sock

        self.assertTrue(server.is_web_service_running("127.0.0.1", 8080))

    @patch("server.socket.getaddrinfo")
    @patch("server.socket.socket")
    def test_connection_refused(self, mock_sock_cls, mock_getaddr):
        mock_getaddr.return_value = [
            (socket.AF_INET, socket.SOCK_STREAM, 0, "", ("127.0.0.1", 8080))
        ]
        mock_sock = MagicMock()
        mock_sock.connect_ex.return_value = 1
        mock_sock.__enter__ = MagicMock(return_value=mock_sock)
        mock_sock.__exit__ = MagicMock(return_value=False)
        mock_sock_cls.return_value = mock_sock

        self.assertFalse(server.is_web_service_running("127.0.0.1", 8080))

    @patch("server.socket.getaddrinfo")
    @patch("server.socket.socket")
    def test_socket_oserror_fallback(self, mock_sock_cls, mock_getaddr):
        mock_getaddr.return_value = [
            (socket.AF_INET6, socket.SOCK_STREAM, 0, "", ("::1", 8080, 0, 0)),
            (socket.AF_INET, socket.SOCK_STREAM, 0, "", ("127.0.0.1", 8080)),
        ]
        mock_sock = MagicMock()
        mock_sock.connect_ex.side_effect = [OSError("v6 fail"), 0]
        mock_sock.__enter__ = MagicMock(return_value=mock_sock)
        mock_sock.__exit__ = MagicMock(return_value=False)
        mock_sock_cls.return_value = mock_sock

        self.assertTrue(server.is_web_service_running("localhost", 8080))


# ═══════════════════════════════════════════════════════════════════════════
#  health_check_service
# ═══════════════════════════════════════════════════════════════════════════
class TestHealthCheckService(unittest.TestCase):
    @patch("server.is_web_service_running", return_value=False)
    def test_port_not_listening(self, _):
        cfg = _make_config()
        self.assertFalse(server.health_check_service(cfg))

    @patch("server.create_http_session")
    @patch("server.is_web_service_running", return_value=True)
    def test_health_ok(self, _, mock_session_fn):
        mock_session = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_session.get.return_value = mock_resp
        mock_session_fn.return_value = mock_session

        self.assertTrue(server.health_check_service(_make_config()))

    @patch("server.create_http_session")
    @patch("server.is_web_service_running", return_value=True)
    def test_health_non_200(self, _, mock_session_fn):
        mock_session = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_session.get.return_value = mock_resp
        mock_session_fn.return_value = mock_session

        self.assertFalse(server.health_check_service(_make_config()))

    @patch("server.create_http_session")
    @patch("server.is_web_service_running", return_value=True)
    def test_request_exception(self, _, mock_session_fn):
        mock_session = MagicMock()
        mock_session.get.side_effect = requests.exceptions.ConnectionError("fail")
        mock_session_fn.return_value = mock_session

        self.assertFalse(server.health_check_service(_make_config()))


# ═══════════════════════════════════════════════════════════════════════════
#  update_web_content
# ═══════════════════════════════════════════════════════════════════════════
class TestUpdateWebContent(unittest.TestCase):
    def _setup_session(
        self, status_code=200, json_data=None, text="", side_effect=None
    ):
        mock_session = MagicMock()
        if side_effect:
            mock_session.post.side_effect = side_effect
        else:
            mock_resp = MagicMock()
            mock_resp.status_code = status_code
            mock_resp.json.return_value = json_data or {"status": "success"}
            mock_resp.text = text
            mock_resp.headers = {}
            mock_session.post.return_value = mock_resp
        return mock_session

    @patch("server.create_http_session")
    def test_success(self, mock_create):
        mock_create.return_value = self._setup_session(
            200, {"status": "success", "message": "ok"}
        )
        server.update_web_content("hello", ["A"], "t1", 120, _make_config())

    @patch("server.create_http_session")
    def test_200_invalid_json(self, mock_create):
        mock_session = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.side_effect = ValueError("bad json")
        mock_session.post.return_value = mock_resp
        mock_create.return_value = mock_session

        from exceptions import ServiceConnectionError

        with self.assertRaises(ServiceConnectionError):
            server.update_web_content("hello", None, "t1", 120, _make_config())

    @patch("server.create_http_session")
    def test_200_non_dict(self, mock_create):
        mock_create.return_value = self._setup_session(200, json_data="string")

        from exceptions import ServiceConnectionError

        with self.assertRaises(ServiceConnectionError):
            server.update_web_content("hello", None, "t1", 120, _make_config())

    @patch("server.create_http_session")
    def test_200_status_not_success(self, mock_create):
        mock_create.return_value = self._setup_session(
            200, {"status": "error", "error": "bad_field", "message": "invalid"}
        )

        from exceptions import ServiceConnectionError

        with self.assertRaises(ServiceConnectionError):
            server.update_web_content("hello", None, "t1", 120, _make_config())

    @patch("server.create_http_session")
    def test_400_json_response(self, mock_create):
        mock_session = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 400
        mock_resp.json.return_value = {
            "error": "missing_field",
            "message": "需要 prompt",
        }
        mock_resp.text = '{"error":"missing_field"}'
        mock_resp.headers = {}
        mock_session.post.return_value = mock_resp
        mock_create.return_value = mock_session

        from exceptions import ValidationError

        with self.assertRaises(ValidationError):
            server.update_web_content("hello", None, "t1", 120, _make_config())

    @patch("server.create_http_session")
    def test_400_non_json(self, mock_create):
        mock_session = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 400
        mock_resp.json.side_effect = ValueError("not json")
        mock_resp.text = "Bad Request"
        mock_resp.headers = {}
        mock_session.post.return_value = mock_resp
        mock_create.return_value = mock_session

        from exceptions import ValidationError

        with self.assertRaises(ValidationError):
            server.update_web_content("hello", None, "t1", 120, _make_config())

    @patch("server.create_http_session")
    def test_429_rate_limited(self, mock_create):
        mock_session = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 429
        mock_resp.text = "Too Many Requests"
        mock_resp.headers = {"Retry-After": "5"}
        mock_session.post.return_value = mock_resp
        mock_create.return_value = mock_session

        from exceptions import ServiceConnectionError

        with self.assertRaises(ServiceConnectionError):
            server.update_web_content("hello", None, "t1", 120, _make_config())

    @patch("server.create_http_session")
    def test_404_endpoint_not_found(self, mock_create):
        mock_create.return_value = self._setup_session(404)

        from exceptions import ServiceUnavailableError

        with self.assertRaises(ServiceUnavailableError):
            server.update_web_content("hello", None, "t1", 120, _make_config())

    @patch("server.create_http_session")
    def test_500_server_error(self, mock_create):
        mock_session = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_resp.text = "Internal Server Error"
        mock_resp.headers = {}
        mock_session.post.return_value = mock_resp
        mock_create.return_value = mock_session

        from exceptions import ServiceConnectionError

        with self.assertRaises(ServiceConnectionError):
            server.update_web_content("hello", None, "t1", 120, _make_config())

    @patch("server.create_http_session")
    def test_unexpected_status(self, mock_create):
        mock_session = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 301
        mock_resp.text = "Moved"
        mock_resp.headers = {}
        mock_session.post.return_value = mock_resp
        mock_create.return_value = mock_session

        from exceptions import ServiceConnectionError

        with self.assertRaises(ServiceConnectionError):
            server.update_web_content("hello", None, "t1", 120, _make_config())

    @patch("server.create_http_session")
    def test_timeout_exception(self, mock_create):
        mock_create.return_value = self._setup_session(
            side_effect=requests.exceptions.Timeout("timed out")
        )

        from exceptions import ServiceTimeoutError

        with self.assertRaises(ServiceTimeoutError):
            server.update_web_content("hello", None, "t1", 120, _make_config())

    @patch("server.create_http_session")
    def test_connection_error(self, mock_create):
        mock_create.return_value = self._setup_session(
            side_effect=requests.exceptions.ConnectionError("refused")
        )

        from exceptions import ServiceUnavailableError

        with self.assertRaises(ServiceUnavailableError):
            server.update_web_content("hello", None, "t1", 120, _make_config())

    @patch("server.create_http_session")
    def test_request_exception(self, mock_create):
        mock_create.return_value = self._setup_session(
            side_effect=requests.exceptions.RequestException("generic")
        )

        from exceptions import ServiceConnectionError

        with self.assertRaises(ServiceConnectionError):
            server.update_web_content("hello", None, "t1", 120, _make_config())


# ═══════════════════════════════════════════════════════════════════════════
#  wait_for_task_completion (async)
# ═══════════════════════════════════════════════════════════════════════════
class TestWaitForTaskCompletion(unittest.TestCase):
    @patch("server.get_web_ui_config")
    def test_task_completed(self, mock_get_cfg):
        mock_get_cfg.return_value = (_make_config(), 120)

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "success": True,
            "task": {
                "status": "completed",
                "result": {"user_input": "done", "selected_options": []},
            },
        }

        with patch("server.requests.get", return_value=mock_resp):
            result = asyncio.run(server.wait_for_task_completion("t1", timeout=5))
            self.assertEqual(result["user_input"], "done")

    @patch("server.get_web_ui_config")
    def test_task_404_returns_resubmit(self, mock_get_cfg):
        mock_get_cfg.return_value = (_make_config(), 120)

        mock_resp = MagicMock()
        mock_resp.status_code = 404

        with patch("server.requests.get", return_value=mock_resp):
            result = asyncio.run(server.wait_for_task_completion("t-gone", timeout=5))
            self.assertIn("text", result)

    @patch("server.get_web_ui_config")
    def test_timeout_returns_resubmit(self, mock_get_cfg):
        mock_get_cfg.return_value = (_make_config(), 120)

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "success": True,
            "task": {"status": "pending", "result": None},
        }

        with patch("server.requests.get", return_value=mock_resp):
            with patch("server.BACKEND_MIN", 1):
                result = asyncio.run(
                    server.wait_for_task_completion("t-slow", timeout=2)
                )
                self.assertIn("text", result)

    @patch("server.get_web_ui_config")
    def test_request_exception_continues(self, mock_get_cfg):
        mock_get_cfg.return_value = (_make_config(), 120)
        call_count = {"n": 0}

        def mock_get(*args, **kwargs):
            call_count["n"] += 1
            if call_count["n"] <= 1:
                raise requests.exceptions.ConnectionError("fail")
            resp = MagicMock()
            resp.status_code = 200
            resp.json.return_value = {
                "success": True,
                "task": {
                    "status": "completed",
                    "result": {"user_input": "recovered"},
                },
            }
            return resp

        with patch("server.requests.get", side_effect=mock_get):
            result = asyncio.run(server.wait_for_task_completion("t-flaky", timeout=10))
            self.assertEqual(result.get("user_input"), "recovered")

    @patch("server.get_web_ui_config")
    def test_non_200_continues(self, mock_get_cfg):
        mock_get_cfg.return_value = (_make_config(), 120)
        call_count = {"n": 0}

        def mock_get(*args, **kwargs):
            call_count["n"] += 1
            resp = MagicMock()
            if call_count["n"] <= 1:
                resp.status_code = 500
            else:
                resp.status_code = 200
                resp.json.return_value = {
                    "success": True,
                    "task": {
                        "status": "completed",
                        "result": {"user_input": "ok"},
                    },
                }
            return resp

        with patch("server.requests.get", side_effect=mock_get):
            result = asyncio.run(server.wait_for_task_completion("t-retry", timeout=10))
            self.assertEqual(result.get("user_input"), "ok")

    @patch("server.get_web_ui_config")
    def test_invalid_json_continues(self, mock_get_cfg):
        mock_get_cfg.return_value = (_make_config(), 120)
        call_count = {"n": 0}

        def mock_get(*args, **kwargs):
            call_count["n"] += 1
            resp = MagicMock()
            resp.status_code = 200
            if call_count["n"] <= 1:
                resp.json.side_effect = ValueError("bad json")
            else:
                resp.json.return_value = {
                    "success": True,
                    "task": {"status": "completed", "result": {"user_input": "ok"}},
                }
            return resp

        with patch("server.requests.get", side_effect=mock_get):
            result = asyncio.run(server.wait_for_task_completion("t-json", timeout=10))
            self.assertEqual(result.get("user_input"), "ok")

    @patch("server.get_web_ui_config")
    def test_non_dict_response_continues(self, mock_get_cfg):
        mock_get_cfg.return_value = (_make_config(), 120)
        call_count = {"n": 0}

        def mock_get(*args, **kwargs):
            call_count["n"] += 1
            resp = MagicMock()
            resp.status_code = 200
            if call_count["n"] <= 1:
                resp.json.return_value = "string response"
            else:
                resp.json.return_value = {
                    "success": True,
                    "task": {"status": "completed", "result": {"user_input": "ok"}},
                }
            return resp

        with patch("server.requests.get", side_effect=mock_get):
            result = asyncio.run(server.wait_for_task_completion("t-type", timeout=10))
            self.assertEqual(result.get("user_input"), "ok")


# ═══════════════════════════════════════════════════════════════════════════
#  FeedbackServiceContext
# ═══════════════════════════════════════════════════════════════════════════
class TestFeedbackServiceContext(unittest.TestCase):
    @patch("server.get_web_ui_config")
    def test_enter_success(self, mock_get_cfg):
        mock_get_cfg.return_value = (_make_config(), 120)
        ctx = server.FeedbackServiceContext()
        result = ctx.__enter__()
        self.assertIs(result, ctx)
        self.assertIsNotNone(ctx.config)

    @patch("server.get_web_ui_config", side_effect=ValueError("bad"))
    def test_enter_failure(self, _):
        ctx = server.FeedbackServiceContext()
        with self.assertRaises(ValueError):
            ctx.__enter__()

    @patch("server.get_web_ui_config")
    def test_exit_normal(self, mock_get_cfg):
        mock_get_cfg.return_value = (_make_config(), 120)
        ctx = server.FeedbackServiceContext()
        ctx.__enter__()
        with patch.object(ctx.service_manager, "cleanup_all"):
            ctx.__exit__(None, None, None)

    @patch("server.get_web_ui_config")
    def test_exit_with_exception(self, mock_get_cfg):
        mock_get_cfg.return_value = (_make_config(), 120)
        ctx = server.FeedbackServiceContext()
        ctx.__enter__()
        with patch.object(ctx.service_manager, "cleanup_all"):
            ctx.__exit__(RuntimeError, RuntimeError("boom"), None)

    @patch("server.get_web_ui_config")
    def test_exit_with_keyboard_interrupt(self, mock_get_cfg):
        mock_get_cfg.return_value = (_make_config(), 120)
        ctx = server.FeedbackServiceContext()
        ctx.__enter__()
        with patch.object(ctx.service_manager, "cleanup_all"):
            ctx.__exit__(KeyboardInterrupt, KeyboardInterrupt(), None)

    @patch("server.get_web_ui_config")
    def test_exit_cleanup_error(self, mock_get_cfg):
        mock_get_cfg.return_value = (_make_config(), 120)
        ctx = server.FeedbackServiceContext()
        ctx.__enter__()
        with patch.object(
            ctx.service_manager, "cleanup_all", side_effect=RuntimeError("cleanup fail")
        ):
            ctx.__exit__(None, None, None)


# ═══════════════════════════════════════════════════════════════════════════
#  cleanup_services
# ═══════════════════════════════════════════════════════════════════════════
class TestCleanupServices(unittest.TestCase):
    def test_success(self):
        with patch("server.ServiceManager") as MockSM:
            mock_sm = MagicMock()
            MockSM.return_value = mock_sm
            server.cleanup_services(shutdown_notification_manager=True)
            mock_sm.cleanup_all.assert_called_once_with(
                shutdown_notification_manager=True
            )

    def test_exception_suppressed(self):
        with patch("server.ServiceManager") as MockSM:
            mock_sm = MagicMock()
            mock_sm.cleanup_all.side_effect = RuntimeError("fail")
            MockSM.return_value = mock_sm
            server.cleanup_services()


# ═══════════════════════════════════════════════════════════════════════════
#  main() — 基本重试循环
# ═══════════════════════════════════════════════════════════════════════════
class TestMain(unittest.TestCase):
    @patch("server.mcp")
    @patch("server.cleanup_services")
    def test_normal_exit(self, mock_cleanup, mock_mcp):
        mock_mcp.run.return_value = None
        server.main()
        mock_mcp.run.assert_called_once()

    @patch("server.mcp")
    @patch("server.cleanup_services")
    def test_keyboard_interrupt(self, mock_cleanup, mock_mcp):
        mock_mcp.run.side_effect = KeyboardInterrupt
        server.main()
        mock_cleanup.assert_called_once()

    @patch("server.sys.exit")
    @patch("server.time.sleep")
    @patch("server.mcp")
    @patch("server.cleanup_services")
    def test_retry_then_exit(self, mock_cleanup, mock_mcp, mock_sleep, mock_exit):
        mock_mcp.run.side_effect = RuntimeError("crash")
        server.main()
        self.assertEqual(mock_mcp.run.call_count, 3)
        mock_exit.assert_called_once_with(1)


# ═══════════════════════════════════════════════════════════════════════════
#  ServiceManager — 深层路径
# ═══════════════════════════════════════════════════════════════════════════
class TestServiceManagerDeep(unittest.TestCase):
    def setUp(self):
        server.ServiceManager._instance = None
        server.ServiceManager._lock = threading.Lock()

    def tearDown(self):
        server.ServiceManager._instance = None

    def test_register_cleanup_signal_valueerror(self):
        """非主线程场景：signal 注册抛出 ValueError 但不应崩溃"""
        sm = server.ServiceManager()
        sm._cleanup_registered = False
        with patch("server.signal.signal", side_effect=ValueError("not main thread")):
            sm._register_cleanup()
        self.assertTrue(sm._cleanup_registered)

    def test_signal_handler_non_main_thread(self):
        """非主线程收到信号时不设置 _should_exit"""
        sm = server.ServiceManager()
        sm._should_exit = False
        non_main = threading.Thread(target=lambda: None)
        with (
            patch.object(sm, "cleanup_all"),
            patch("server.threading.current_thread", return_value=non_main),
            patch("server.threading.main_thread", return_value=threading.main_thread()),
        ):
            sm._signal_handler(signal.SIGINT, None)
        self.assertFalse(sm._should_exit)

    def test_signal_handler_cleanup_error(self):
        """cleanup_all 失败不应导致信号处理器崩溃"""
        sm = server.ServiceManager()
        with patch.object(sm, "cleanup_all", side_effect=RuntimeError("cleanup boom")):
            sm._signal_handler(signal.SIGTERM, None)

    @patch("server.is_web_service_running", return_value=False)
    def test_terminate_process_outer_exception(self, _):
        """terminate_process 内部 poll 抛出意外异常"""
        sm = server.ServiceManager()
        mock_proc = MagicMock(spec=subprocess.Popen)
        mock_proc.pid = 700
        mock_proc.poll.side_effect = OSError("gone")
        mock_proc.stdin = None
        mock_proc.stdout = None
        mock_proc.stderr = None
        sm.register_process("error", mock_proc, _make_config())
        result = sm.terminate_process("error")
        self.assertFalse(result)

    @patch("server.is_web_service_running", return_value=False)
    def test_cleanup_process_resources_close_exceptions(self, _):
        """stdin/stdout/stderr 的 close() 各自抛出异常不影响整体"""
        sm = server.ServiceManager()
        mock_proc = MagicMock(spec=subprocess.Popen)
        mock_proc.stdin = MagicMock()
        mock_proc.stdin.close.side_effect = OSError("stdin fail")
        mock_proc.stdout = MagicMock()
        mock_proc.stdout.close.side_effect = OSError("stdout fail")
        mock_proc.stderr = MagicMock()
        mock_proc.stderr.close.side_effect = OSError("stderr fail")
        sm._cleanup_process_resources("test", {"process": mock_proc})

    @patch("server.is_web_service_running", return_value=False)
    def test_cleanup_process_resources_outer_exception(self, _):
        """process_info["process"] 访问失败的情况"""
        sm = server.ServiceManager()
        sm._cleanup_process_resources("test", {})

    @patch("server.time.sleep")
    @patch("server.is_web_service_running", side_effect=[True, True, True, False])
    def test_wait_for_port_release_eventually(self, mock_running, mock_sleep):
        sm = server.ServiceManager()
        sm._wait_for_port_release("127.0.0.1", 8080)
        self.assertTrue(mock_sleep.call_count >= 1)

    @patch("server.time.sleep")
    @patch("server.is_web_service_running", return_value=True)
    def test_wait_for_port_release_timeout(self, mock_running, mock_sleep):
        """端口始终占用超时"""
        sm = server.ServiceManager()
        sm._wait_for_port_release("127.0.0.1", 8080, timeout=0.001)

    @patch("server.is_web_service_running", return_value=False)
    def test_cleanup_all_with_errors_and_remaining(self, _):
        """cleanup_all: terminate 失败 + 残留进程强制移除"""
        sm = server.ServiceManager()
        mock_proc = MagicMock(spec=subprocess.Popen)
        mock_proc.pid = 800
        mock_proc.poll.side_effect = OSError("gone")
        mock_proc.stdin = None
        mock_proc.stdout = None
        mock_proc.stderr = None
        sm.register_process("stuck", mock_proc, _make_config())

        with patch.object(sm, "terminate_process", return_value=False):
            sm.cleanup_all(shutdown_notification_manager=False)

    @patch("server.NOTIFICATION_AVAILABLE", True)
    @patch("server.notification_manager")
    @patch("server.is_web_service_running", return_value=False)
    def test_cleanup_all_shutdown_notification_manager(self, _, mock_nm):
        sm = server.ServiceManager()
        sm.cleanup_all(shutdown_notification_manager=True)
        mock_nm.shutdown.assert_called_once()

    @patch("server.NOTIFICATION_AVAILABLE", True)
    @patch("server.notification_manager")
    @patch("server.is_web_service_running", return_value=False)
    def test_cleanup_all_shutdown_notification_manager_failure(self, _, mock_nm):
        mock_nm.shutdown.side_effect = RuntimeError("shutdown fail")
        sm = server.ServiceManager()
        sm.cleanup_all(shutdown_notification_manager=True)

    @patch("server.is_web_service_running", return_value=False)
    def test_cleanup_all_terminate_exception(self, _):
        """cleanup_all: terminate_process 抛出异常"""
        sm = server.ServiceManager()
        mock_proc = MagicMock(spec=subprocess.Popen)
        mock_proc.pid = 801
        mock_proc.poll.return_value = 0
        mock_proc.stdin = None
        mock_proc.stdout = None
        mock_proc.stderr = None
        sm.register_process("explode", mock_proc, _make_config())

        with patch.object(sm, "terminate_process", side_effect=RuntimeError("boom")):
            sm.cleanup_all(shutdown_notification_manager=False)


# ═══════════════════════════════════════════════════════════════════════════
#  create_http_session — generation 切换时 close 异常
# ═══════════════════════════════════════════════════════════════════════════
class TestCreateHttpSessionDeep(unittest.TestCase):
    def test_generation_change_close_exception(self):
        """generation 变更时旧 session close() 抛出异常不影响新 session 创建"""
        cfg = _make_config()
        s1 = server.create_http_session(cfg)
        s1.close = MagicMock(side_effect=OSError("close fail"))  # type: ignore[method-assign]
        with server._http_session_lock:
            server._http_session_generation += 1
        s2 = server.create_http_session(cfg)
        self.assertIsNot(s1, s2)


# ═══════════════════════════════════════════════════════════════════════════
#  is_web_service_running — 外层异常
# ═══════════════════════════════════════════════════════════════════════════
class TestIsWebServiceRunningDeep(unittest.TestCase):
    @patch("server.socket.getaddrinfo", side_effect=RuntimeError("unexpected"))
    def test_unexpected_exception_returns_false(self, _):
        self.assertFalse(server.is_web_service_running("localhost", 8080))


# ═══════════════════════════════════════════════════════════════════════════
#  health_check_service — 非 RequestException 的异常
# ═══════════════════════════════════════════════════════════════════════════
class TestHealthCheckServiceDeep(unittest.TestCase):
    @patch("server.create_http_session")
    @patch("server.is_web_service_running", return_value=True)
    def test_unexpected_exception(self, _, mock_session_fn):
        mock_session = MagicMock()
        mock_session.get.side_effect = RuntimeError("unexpected")
        mock_session_fn.return_value = mock_session
        self.assertFalse(server.health_check_service(_make_config()))


# ═══════════════════════════════════════════════════════════════════════════
#  update_web_content — 补充分支
# ═══════════════════════════════════════════════════════════════════════════
class TestUpdateWebContentDeep(unittest.TestCase):
    @patch("server.create_http_session")
    def test_400_with_non_dict_json(self, mock_create):
        """400 响应 JSON 不是 dict"""
        mock_session = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 400
        mock_resp.json.return_value = "just_a_string"
        mock_resp.text = "just_a_string"
        mock_resp.headers = {}
        mock_session.post.return_value = mock_resp
        mock_create.return_value = mock_session

        with self.assertRaises(ValidationError):
            server.update_web_content("hello", None, "t1", 120, _make_config())

    @patch("server.create_http_session")
    def test_unexpected_exception(self, mock_create):
        """非网络/已知异常"""
        mock_session = MagicMock()
        mock_session.post.side_effect = TypeError("weird")
        mock_create.return_value = mock_session

        with self.assertRaises(ServiceConnectionError):
            server.update_web_content("hello", None, "t1", 120, _make_config())


# ═══════════════════════════════════════════════════════════════════════════
#  start_web_service
# ═══════════════════════════════════════════════════════════════════════════
class TestStartWebService(unittest.TestCase):
    def setUp(self):
        server.ServiceManager._instance = None
        server.ServiceManager._lock = threading.Lock()

    def tearDown(self):
        server.ServiceManager._instance = None

    @patch("server.health_check_service", return_value=True)
    @patch("server.NOTIFICATION_AVAILABLE", False)
    def test_already_running_via_health_check(self, mock_hc):
        """服务已在运行，直接返回"""
        cfg = _make_config()
        script_dir = _SERVER_DIR
        server.start_web_service(cfg, script_dir)

    @patch("server.health_check_service", return_value=False)
    @patch("server.NOTIFICATION_AVAILABLE", False)
    def test_already_running_via_process_manager(self, mock_hc):
        """ServiceManager 中进程还在运行"""
        sm = server.ServiceManager()
        mock_proc = MagicMock(spec=subprocess.Popen)
        mock_proc.pid = 900
        mock_proc.poll.return_value = None
        cfg = _make_config()
        service_name = f"web_ui_{cfg.host}_{cfg.port}"
        sm.register_process(service_name, mock_proc, cfg)

        script_dir = _SERVER_DIR
        server.start_web_service(cfg, script_dir)

    @patch("server.NOTIFICATION_AVAILABLE", False)
    @patch("server.health_check_service", return_value=False)
    def test_web_ui_path_not_found(self, mock_hc):
        cfg = _make_config()
        with self.assertRaises(FileNotFoundError):
            server.start_web_service(cfg, Path("/nonexistent/dir"))

    @patch("server.time.sleep")
    @patch("server.health_check_service")
    @patch("server.subprocess.Popen")
    @patch("server.NOTIFICATION_AVAILABLE", False)
    def test_success_start(self, mock_popen, mock_hc, mock_sleep):
        mock_proc = MagicMock()
        mock_proc.pid = 1000
        mock_popen.return_value = mock_proc
        mock_hc.side_effect = [False, False, True]

        cfg = _make_config()
        script_dir = _SERVER_DIR
        server.start_web_service(cfg, script_dir)
        mock_popen.assert_called_once()

    @patch("server.health_check_service", return_value=False)
    @patch("server.subprocess.Popen", side_effect=FileNotFoundError("python not found"))
    @patch("server.NOTIFICATION_AVAILABLE", False)
    def test_popen_file_not_found(self, mock_popen, mock_hc):
        cfg = _make_config()
        script_dir = _SERVER_DIR
        with self.assertRaises(ServiceUnavailableError):
            server.start_web_service(cfg, script_dir)

    @patch("server.health_check_service", return_value=False)
    @patch("server.subprocess.Popen", side_effect=PermissionError("access denied"))
    @patch("server.NOTIFICATION_AVAILABLE", False)
    def test_popen_permission_error(self, mock_popen, mock_hc):
        cfg = _make_config()
        script_dir = _SERVER_DIR
        with self.assertRaises(ServiceUnavailableError):
            server.start_web_service(cfg, script_dir)

    @patch("server.health_check_service")
    @patch("server.subprocess.Popen", side_effect=OSError("disk full"))
    @patch("server.NOTIFICATION_AVAILABLE", False)
    def test_popen_generic_error_service_already_running(self, mock_popen, mock_hc):
        """Popen 失败但 health_check 显示服务已在运行"""
        mock_hc.side_effect = [False, True]
        cfg = _make_config()
        script_dir = _SERVER_DIR
        server.start_web_service(cfg, script_dir)

    @patch("server.health_check_service", return_value=False)
    @patch("server.subprocess.Popen", side_effect=OSError("disk full"))
    @patch("server.NOTIFICATION_AVAILABLE", False)
    def test_popen_generic_error_service_not_running(self, mock_popen, mock_hc):
        cfg = _make_config()
        script_dir = _SERVER_DIR
        with self.assertRaises(ServiceUnavailableError):
            server.start_web_service(cfg, script_dir)

    @patch("server.time.sleep")
    @patch("server.health_check_service", return_value=False)
    @patch("server.subprocess.Popen")
    @patch("server.NOTIFICATION_AVAILABLE", False)
    def test_health_check_timeout_raises(self, mock_popen, mock_hc, mock_sleep):
        """健康检查始终失败，触发超时清理"""
        mock_proc = MagicMock()
        mock_proc.pid = 1001
        mock_popen.return_value = mock_proc

        cfg = _make_config()
        script_dir = _SERVER_DIR
        with self.assertRaises(ServiceTimeoutError):
            server.start_web_service(cfg, script_dir)

    @patch("server.time.sleep")
    @patch("server.health_check_service", return_value=False)
    @patch("server.subprocess.Popen")
    @patch("server.NOTIFICATION_AVAILABLE", False)
    def test_health_check_timeout_cleanup_failure(
        self, mock_popen, mock_hc, mock_sleep
    ):
        """健康检查超时后 cleanup 也失败"""
        mock_proc = MagicMock()
        mock_proc.pid = 1002
        mock_popen.return_value = mock_proc

        cfg = _make_config()
        script_dir = _SERVER_DIR
        with self.assertRaises(ServiceTimeoutError):
            server.start_web_service(cfg, script_dir)

    @patch("server.time.sleep")
    @patch("server.health_check_service")
    @patch("server.subprocess.Popen")
    @patch("server.initialize_notification_system")
    @patch("server.notification_manager")
    @patch("server.NOTIFICATION_AVAILABLE", True)
    def test_notification_init_success(
        self, mock_nm, mock_init_ns, mock_popen, mock_hc, mock_sleep
    ):
        mock_proc = MagicMock()
        mock_proc.pid = 1003
        mock_popen.return_value = mock_proc
        mock_hc.side_effect = [False, True]
        mock_nm.get_config.return_value = {}

        cfg = _make_config()
        script_dir = _SERVER_DIR
        server.start_web_service(cfg, script_dir)
        mock_init_ns.assert_called_once()

    @patch("server.time.sleep")
    @patch("server.health_check_service")
    @patch("server.subprocess.Popen")
    @patch(
        "server.initialize_notification_system", side_effect=RuntimeError("init fail")
    )
    @patch("server.notification_manager")
    @patch("server.NOTIFICATION_AVAILABLE", True)
    def test_notification_init_failure(
        self, mock_nm, mock_init_ns, mock_popen, mock_hc, mock_sleep
    ):
        """通知系统初始化失败不影响服务启动"""
        mock_proc = MagicMock()
        mock_proc.pid = 1004
        mock_popen.return_value = mock_proc
        mock_hc.side_effect = [False, True]
        mock_nm.get_config.return_value = {}

        cfg = _make_config()
        script_dir = _SERVER_DIR
        server.start_web_service(cfg, script_dir)


# ═══════════════════════════════════════════════════════════════════════════
#  ensure_web_ui_running (async)
# ═══════════════════════════════════════════════════════════════════════════
class TestEnsureWebUIRunning(unittest.TestCase):
    def test_already_running(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200

        with patch("server.requests.get", return_value=mock_resp):
            asyncio.run(server.ensure_web_ui_running(_make_config()))

    @patch("server.start_web_service")
    def test_health_fail_starts_service(self, mock_start):
        async def _noop_sleep(_: float) -> None:
            pass

        with (
            patch(
                "server.requests.get",
                side_effect=requests.exceptions.ConnectionError("fail"),
            ),
            patch("server.asyncio.sleep", side_effect=_noop_sleep),
        ):
            asyncio.run(server.ensure_web_ui_running(_make_config()))
        mock_start.assert_called_once()


# ═══════════════════════════════════════════════════════════════════════════
#  launch_feedback_ui
# ═══════════════════════════════════════════════════════════════════════════
class TestLaunchFeedbackUI(unittest.TestCase):
    @patch("server.asyncio.run")
    @patch("server.get_web_ui_config")
    @patch("server._generate_task_id", return_value="test-task-1")
    @patch("server.NOTIFICATION_AVAILABLE", False)
    def test_success_flow(self, mock_tid, mock_cfg, mock_arun):
        mock_cfg.return_value = (_make_config(), 120)

        mock_resp = MagicMock()
        mock_resp.status_code = 200

        mock_arun.side_effect = [
            None,
            {"user_input": "done", "selected_options": []},
        ]

        with patch("server.requests.post", return_value=mock_resp):
            result = server.launch_feedback_ui("hello")
        self.assertEqual(result["user_input"], "done")

    @patch("server.asyncio.run")
    @patch("server.get_web_ui_config")
    @patch("server._generate_task_id", return_value="test-task-2")
    @patch("server.NOTIFICATION_AVAILABLE", False)
    def test_api_non_200_dict_json(self, mock_tid, mock_cfg, mock_arun):
        """API 返回非 200 + dict JSON"""
        mock_cfg.return_value = (_make_config(), 120)

        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_resp.json.return_value = {"error": "server down"}
        mock_resp.text = '{"error": "server down"}'

        mock_arun.return_value = None

        with patch("server.requests.post", return_value=mock_resp):
            result = server.launch_feedback_ui("hello")
        self.assertIn("error", result)

    @patch("server.asyncio.run")
    @patch("server.get_web_ui_config")
    @patch("server._generate_task_id", return_value="test-task-3")
    @patch("server.NOTIFICATION_AVAILABLE", False)
    def test_api_non_200_non_dict_json(self, mock_tid, mock_cfg, mock_arun):
        """API 返回非 200 + 非 dict JSON"""
        mock_cfg.return_value = (_make_config(), 120)

        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_resp.json.return_value = "string payload"
        mock_resp.text = '"string payload"'

        mock_arun.return_value = None

        with patch("server.requests.post", return_value=mock_resp):
            result = server.launch_feedback_ui("hello")
        self.assertIn("error", result)

    @patch("server.asyncio.run")
    @patch("server.get_web_ui_config")
    @patch("server._generate_task_id", return_value="test-task-4")
    @patch("server.NOTIFICATION_AVAILABLE", False)
    def test_api_non_200_invalid_json(self, mock_tid, mock_cfg, mock_arun):
        """API 返回非 200 + 无效 JSON"""
        mock_cfg.return_value = (_make_config(), 120)

        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_resp.json.side_effect = ValueError("bad json")
        mock_resp.text = "Internal Error"

        mock_arun.return_value = None

        with patch("server.requests.post", return_value=mock_resp):
            result = server.launch_feedback_ui("hello")
        self.assertIn("error", result)

    @patch("server.asyncio.run")
    @patch("server.get_web_ui_config")
    @patch("server._generate_task_id", return_value="test-task-5")
    @patch("server.NOTIFICATION_AVAILABLE", False)
    def test_api_connection_error(self, mock_tid, mock_cfg, mock_arun):
        mock_cfg.return_value = (_make_config(), 120)
        mock_arun.return_value = None

        with patch(
            "server.requests.post",
            side_effect=requests.exceptions.ConnectionError("refused"),
        ):
            result = server.launch_feedback_ui("hello")
        self.assertIn("error", result)

    @patch("server.asyncio.run")
    @patch("server.get_web_ui_config")
    @patch("server._generate_task_id", return_value="test-task-6")
    @patch("server.notification_manager")
    @patch("server.NOTIFICATION_AVAILABLE", True)
    def test_notification_send_success(self, mock_nm, mock_tid, mock_cfg, mock_arun):
        mock_cfg.return_value = (_make_config(), 120)
        mock_nm.send_notification.return_value = "event-1"
        mock_nm.refresh_config_from_file.return_value = None

        mock_resp = MagicMock()
        mock_resp.status_code = 200

        mock_arun.side_effect = [None, {"user_input": "ok"}]

        with patch("server.requests.post", return_value=mock_resp):
            result = server.launch_feedback_ui("hello")
        self.assertEqual(result["user_input"], "ok")
        mock_nm.send_notification.assert_called_once()

    @patch("server.asyncio.run")
    @patch("server.get_web_ui_config")
    @patch("server._generate_task_id", return_value="test-task-7")
    @patch("server.notification_manager")
    @patch("server.NOTIFICATION_AVAILABLE", True)
    def test_notification_send_failure(self, mock_nm, mock_tid, mock_cfg, mock_arun):
        """通知发送失败不影响任务创建"""
        mock_cfg.return_value = (_make_config(), 120)
        mock_nm.refresh_config_from_file.side_effect = RuntimeError("notify fail")

        mock_resp = MagicMock()
        mock_resp.status_code = 200

        mock_arun.side_effect = [None, {"user_input": "ok"}]

        with patch("server.requests.post", return_value=mock_resp):
            result = server.launch_feedback_ui("hello")
        self.assertEqual(result["user_input"], "ok")

    @patch("server.asyncio.run")
    @patch("server.get_web_ui_config")
    @patch("server._generate_task_id", return_value="test-task-8")
    @patch("server.NOTIFICATION_AVAILABLE", False)
    def test_task_error_result(self, mock_tid, mock_cfg, mock_arun):
        mock_cfg.return_value = (_make_config(), 120)

        mock_resp = MagicMock()
        mock_resp.status_code = 200

        mock_arun.side_effect = [None, {"error": "timeout"}]

        with patch("server.requests.post", return_value=mock_resp):
            result = server.launch_feedback_ui("hello")
        self.assertIn("error", result)

    def test_value_error(self):
        with self.assertRaises(ValidationError):
            server.launch_feedback_ui(123)  # type: ignore[arg-type]

    @patch("server.asyncio.run", side_effect=FileNotFoundError("web_ui.py"))
    @patch("server.get_web_ui_config")
    @patch("server._generate_task_id", return_value="test-task-9")
    def test_file_not_found(self, mock_tid, mock_cfg, mock_arun):
        mock_cfg.return_value = (_make_config(), 120)
        with self.assertRaises(ServiceUnavailableError):
            server.launch_feedback_ui("hello")

    @patch("server.asyncio.run", side_effect=RuntimeError("unexpected"))
    @patch("server.get_web_ui_config")
    @patch("server._generate_task_id", return_value="test-task-10")
    def test_generic_exception(self, mock_tid, mock_cfg, mock_arun):
        mock_cfg.return_value = (_make_config(), 120)
        with self.assertRaises(ServiceUnavailableError):
            server.launch_feedback_ui("hello")

    @patch("server.asyncio.run")
    @patch("server.get_web_ui_config")
    @patch("server._generate_task_id", return_value="test-task-11")
    @patch("server.NOTIFICATION_AVAILABLE", False)
    def test_timeout_ensures_minimum(self, mock_tid, mock_cfg, mock_arun):
        """timeout 小于 300 时会被提升到 300"""
        mock_cfg.return_value = (_make_config(), 120)

        mock_resp = MagicMock()
        mock_resp.status_code = 200

        mock_arun.side_effect = [None, {"user_input": "ok"}]

        with patch("server.requests.post", return_value=mock_resp):
            result = server.launch_feedback_ui("hello", timeout=10)
        self.assertEqual(result["user_input"], "ok")

    @patch("server.asyncio.run")
    @patch("server.get_web_ui_config")
    @patch("server._generate_task_id", return_value="test-task-12")
    @patch("server.NOTIFICATION_AVAILABLE", False)
    def test_api_non_200_invalid_json_no_text(self, mock_tid, mock_cfg, mock_arun):
        """API 返回非 200 + 无效 JSON + response.text 读取失败"""
        mock_cfg.return_value = (_make_config(), 120)

        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_resp.json.side_effect = ValueError("bad json")
        type(mock_resp).text = PropertyMock(side_effect=RuntimeError("text fail"))

        mock_arun.return_value = None

        with patch("server.requests.post", return_value=mock_resp):
            result = server.launch_feedback_ui("hello")
        self.assertIn("error", result)

    @patch("server.asyncio.run")
    @patch("server.get_web_ui_config")
    @patch("server._generate_task_id", return_value="test-task-13")
    @patch("server.notification_manager")
    @patch("server.NOTIFICATION_AVAILABLE", True)
    def test_notification_send_returns_none(
        self, mock_nm, mock_tid, mock_cfg, mock_arun
    ):
        """通知发送返回 None（通知系统已禁用）"""
        mock_cfg.return_value = (_make_config(), 120)
        mock_nm.send_notification.return_value = None
        mock_nm.refresh_config_from_file.return_value = None

        mock_resp = MagicMock()
        mock_resp.status_code = 200

        mock_arun.side_effect = [None, {"user_input": "ok"}]

        with patch("server.requests.post", return_value=mock_resp):
            result = server.launch_feedback_ui("hello")
        self.assertEqual(result["user_input"], "ok")


# ═══════════════════════════════════════════════════════════════════════════
#  interactive_feedback (async MCP tool)
# ═══════════════════════════════════════════════════════════════════════════
_interactive_feedback_fn = server.interactive_feedback.fn


class TestInteractiveFeedback(unittest.TestCase):
    def _run(self, message: str, predefined_options=None):
        """调用底层 async 函数，显式传 predefined_options 避免 FieldInfo 默认值"""
        return asyncio.run(_interactive_feedback_fn(message, predefined_options))

    @patch("server.wait_for_task_completion")
    @patch("server.ensure_web_ui_running")
    @patch("server.get_web_ui_config")
    @patch("server._generate_task_id", return_value="if-task-1")
    @patch("server.NOTIFICATION_AVAILABLE", False)
    def test_success_structured_response(
        self, mock_tid, mock_cfg, mock_ensure, mock_wait
    ):
        mock_cfg.return_value = (_make_config(), 120)
        mock_ensure.return_value = None
        mock_wait.return_value = {
            "user_input": "hello",
            "selected_options": ["A"],
        }

        mock_resp = MagicMock()
        mock_resp.status_code = 200

        with patch("server.requests.post", return_value=mock_resp):
            result = self._run("test prompt")
        self.assertIsInstance(result, list)
        self.assertTrue(any(isinstance(c, TextContent) for c in result))

    @patch("server.wait_for_task_completion")
    @patch("server.ensure_web_ui_running")
    @patch("server.get_web_ui_config")
    @patch("server._generate_task_id", return_value="if-task-2")
    @patch("server.NOTIFICATION_AVAILABLE", False)
    def test_success_text_only_result(self, mock_tid, mock_cfg, mock_ensure, mock_wait):
        """wait_for_task_completion 返回 {"text": "..."} 降级格式"""
        mock_cfg.return_value = (_make_config(), 120)
        mock_ensure.return_value = None
        mock_wait.return_value = {"text": "请重新调用工具"}

        mock_resp = MagicMock()
        mock_resp.status_code = 200

        with patch("server.requests.post", return_value=mock_resp):
            result = self._run("test prompt")
        self.assertIsInstance(result, list)
        self.assertTrue(len(result) > 0)
        self.assertIsInstance(result[0], TextContent)
        self.assertIn("请重新调用工具", result[0].text)

    @patch("server.wait_for_task_completion")
    @patch("server.ensure_web_ui_running")
    @patch("server.get_web_ui_config")
    @patch("server._generate_task_id", return_value="if-task-3")
    @patch("server.NOTIFICATION_AVAILABLE", False)
    def test_success_legacy_format(self, mock_tid, mock_cfg, mock_ensure, mock_wait):
        """旧格式：interactive_feedback 字段"""
        mock_cfg.return_value = (_make_config(), 120)
        mock_ensure.return_value = None
        mock_wait.return_value = {"interactive_feedback": "old response"}

        mock_resp = MagicMock()
        mock_resp.status_code = 200

        with patch("server.requests.post", return_value=mock_resp):
            result = self._run("test prompt")
        self.assertIsInstance(result[0], TextContent)
        self.assertIn("old response", result[0].text)

    @patch("server.wait_for_task_completion")
    @patch("server.ensure_web_ui_running")
    @patch("server.get_web_ui_config")
    @patch("server._generate_task_id", return_value="if-task-4")
    @patch("server.NOTIFICATION_AVAILABLE", False)
    def test_success_fallback_dict(self, mock_tid, mock_cfg, mock_ensure, mock_wait):
        """未知 dict 格式的兜底"""
        mock_cfg.return_value = (_make_config(), 120)
        mock_ensure.return_value = None
        mock_wait.return_value = {"unknown_key": "value"}

        mock_resp = MagicMock()
        mock_resp.status_code = 200

        with patch("server.requests.post", return_value=mock_resp):
            result = self._run("test prompt")
        self.assertIsInstance(result[0], TextContent)

    @patch("server.wait_for_task_completion")
    @patch("server.ensure_web_ui_running")
    @patch("server.get_web_ui_config")
    @patch("server._generate_task_id", return_value="if-task-5")
    @patch("server.NOTIFICATION_AVAILABLE", False)
    def test_success_string_result(self, mock_tid, mock_cfg, mock_ensure, mock_wait):
        """非 dict 字符串结果"""
        mock_cfg.return_value = (_make_config(), 120)
        mock_ensure.return_value = None
        mock_wait.return_value = "simple string"

        mock_resp = MagicMock()
        mock_resp.status_code = 200

        with patch("server.requests.post", return_value=mock_resp):
            result = self._run("test prompt")
        self.assertIsInstance(result[0], TextContent)

    @patch("server.ensure_web_ui_running")
    @patch("server.get_web_ui_config")
    @patch("server._generate_task_id", return_value="if-task-6")
    @patch("server.NOTIFICATION_AVAILABLE", False)
    def test_add_task_non_200(self, mock_tid, mock_cfg, mock_ensure):
        """添加任务 API 返回非 200"""
        mock_cfg.return_value = (_make_config(), 120)
        mock_ensure.return_value = None

        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_resp.json.return_value = {"error": "server down"}
        mock_resp.text = "server error"

        with patch("server.requests.post", return_value=mock_resp):
            result = self._run("test prompt")
        self.assertIsInstance(result, list)

    @patch("server.ensure_web_ui_running")
    @patch("server.get_web_ui_config")
    @patch("server._generate_task_id", return_value="if-task-7")
    @patch("server.NOTIFICATION_AVAILABLE", False)
    def test_add_task_non_200_invalid_json_with_text(
        self, mock_tid, mock_cfg, mock_ensure
    ):
        """添加任务 API 返回非 200 + 无效 JSON + 有 text"""
        mock_cfg.return_value = (_make_config(), 120)
        mock_ensure.return_value = None

        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_resp.json.side_effect = ValueError("bad json")
        mock_resp.text = "Internal Error"

        with patch("server.requests.post", return_value=mock_resp):
            result = self._run("test prompt")
        self.assertIsInstance(result, list)

    @patch("server.ensure_web_ui_running")
    @patch("server.get_web_ui_config")
    @patch("server._generate_task_id", return_value="if-task-8")
    @patch("server.NOTIFICATION_AVAILABLE", False)
    def test_add_task_connection_error(self, mock_tid, mock_cfg, mock_ensure):
        mock_cfg.return_value = (_make_config(), 120)
        mock_ensure.return_value = None

        with patch(
            "server.requests.post",
            side_effect=requests.exceptions.ConnectionError("refused"),
        ):
            result = self._run("test prompt")
        self.assertIsInstance(result, list)

    @patch("server.wait_for_task_completion")
    @patch("server.ensure_web_ui_running")
    @patch("server.get_web_ui_config")
    @patch("server._generate_task_id", return_value="if-task-9")
    @patch("server.notification_manager")
    @patch("server.NOTIFICATION_AVAILABLE", True)
    def test_notification_available_path(
        self, mock_nm, mock_tid, mock_cfg, mock_ensure, mock_wait
    ):
        """NOTIFICATION_AVAILABLE=True 时走通知分支"""
        mock_cfg.return_value = (_make_config(), 120)
        mock_ensure.return_value = None
        mock_nm.send_notification.return_value = "event-1"
        mock_nm.refresh_config_from_file.return_value = None
        mock_wait.return_value = {"user_input": "ok"}

        mock_resp = MagicMock()
        mock_resp.status_code = 200

        with patch("server.requests.post", return_value=mock_resp):
            result = self._run("test prompt")
        self.assertIsInstance(result, list)

    @patch("server.wait_for_task_completion")
    @patch("server.ensure_web_ui_running")
    @patch("server.get_web_ui_config")
    @patch("server._generate_task_id", return_value="if-task-10")
    @patch("server.notification_manager")
    @patch("server.NOTIFICATION_AVAILABLE", True)
    def test_notification_failure(
        self, mock_nm, mock_tid, mock_cfg, mock_ensure, mock_wait
    ):
        """通知失败不影响任务"""
        mock_cfg.return_value = (_make_config(), 120)
        mock_ensure.return_value = None
        mock_nm.refresh_config_from_file.side_effect = RuntimeError("fail")
        mock_wait.return_value = {"user_input": "ok"}

        mock_resp = MagicMock()
        mock_resp.status_code = 200

        with patch("server.requests.post", return_value=mock_resp):
            result = self._run("test prompt")
        self.assertIsInstance(result, list)

    @patch("server.wait_for_task_completion")
    @patch("server.ensure_web_ui_running")
    @patch("server.get_web_ui_config")
    @patch("server._generate_task_id", return_value="if-task-11")
    @patch("server.NOTIFICATION_AVAILABLE", False)
    def test_task_error_returns_resubmit(
        self, mock_tid, mock_cfg, mock_ensure, mock_wait
    ):
        mock_cfg.return_value = (_make_config(), 120)
        mock_ensure.return_value = None
        mock_wait.return_value = {"error": "timeout"}

        mock_resp = MagicMock()
        mock_resp.status_code = 200

        with patch("server.requests.post", return_value=mock_resp):
            result = self._run("test prompt")
        self.assertIsInstance(result, list)

    @patch("server.ensure_web_ui_running", side_effect=RuntimeError("crash"))
    @patch("server.get_web_ui_config")
    @patch("server._generate_task_id", return_value="if-task-12")
    def test_generic_exception_returns_resubmit(self, mock_tid, mock_cfg, mock_ensure):
        mock_cfg.return_value = (_make_config(), 120)
        result = self._run("test prompt")
        self.assertIsInstance(result, list)

    @patch("server.ensure_web_ui_running")
    @patch("server.get_web_ui_config")
    @patch("server._generate_task_id", return_value="if-task-13")
    @patch("server.NOTIFICATION_AVAILABLE", False)
    def test_add_task_non_200_non_dict_json(self, mock_tid, mock_cfg, mock_ensure):
        """添加任务 API 返回非 200 + 非 dict JSON"""
        mock_cfg.return_value = (_make_config(), 120)
        mock_ensure.return_value = None

        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_resp.json.return_value = "string payload"
        mock_resp.text = '"string payload"'

        with patch("server.requests.post", return_value=mock_resp):
            result = self._run("test prompt")
        self.assertIsInstance(result, list)

    @patch("server.wait_for_task_completion")
    @patch("server.ensure_web_ui_running")
    @patch("server.get_web_ui_config")
    @patch("server._generate_task_id", return_value="if-task-14")
    @patch("server.NOTIFICATION_AVAILABLE", False)
    def test_success_with_images(self, mock_tid, mock_cfg, mock_ensure, mock_wait):
        """含图片的结构化响应"""
        mock_cfg.return_value = (_make_config(), 120)
        mock_ensure.return_value = None
        mock_wait.return_value = {
            "user_input": "see image",
            "selected_options": [],
            "images": [],
        }

        mock_resp = MagicMock()
        mock_resp.status_code = 200

        with patch("server.requests.post", return_value=mock_resp):
            result = self._run("test prompt")
        self.assertIsInstance(result, list)

    @patch("server.wait_for_task_completion")
    @patch("server.ensure_web_ui_running")
    @patch("server.get_web_ui_config")
    @patch("server._generate_task_id", return_value="if-task-15")
    @patch("server.notification_manager")
    @patch("server.NOTIFICATION_AVAILABLE", True)
    def test_notification_send_returns_none(
        self, mock_nm, mock_tid, mock_cfg, mock_ensure, mock_wait
    ):
        """通知发送返回 None（通知系统已禁用但可用标志为 True）"""
        mock_cfg.return_value = (_make_config(), 120)
        mock_ensure.return_value = None
        mock_nm.send_notification.return_value = None
        mock_nm.refresh_config_from_file.return_value = None
        mock_wait.return_value = {"user_input": "ok"}

        mock_resp = MagicMock()
        mock_resp.status_code = 200

        with patch("server.requests.post", return_value=mock_resp):
            result = self._run("test prompt")
        self.assertIsInstance(result, list)

    @patch("server.wait_for_task_completion")
    @patch("server.ensure_web_ui_running")
    @patch("server.get_web_ui_config")
    @patch("server._generate_task_id", return_value="if-task-16")
    @patch("server.NOTIFICATION_AVAILABLE", False)
    def test_long_message_truncated_for_notification(
        self, mock_tid, mock_cfg, mock_ensure, mock_wait
    ):
        """消息超过 100 字符时截断"""
        mock_cfg.return_value = (_make_config(), 120)
        mock_ensure.return_value = None
        mock_wait.return_value = {"user_input": "ok"}

        mock_resp = MagicMock()
        mock_resp.status_code = 200

        with patch("server.requests.post", return_value=mock_resp):
            result = self._run("A" * 200)
        self.assertIsInstance(result, list)

    @patch("server.ensure_web_ui_running")
    @patch("server.get_web_ui_config")
    @patch("server._generate_task_id", return_value="if-task-17")
    @patch("server.NOTIFICATION_AVAILABLE", False)
    def test_add_task_non_200_invalid_json_text_fail(
        self, mock_tid, mock_cfg, mock_ensure
    ):
        """添加任务 API 返回非 200 + 无效 JSON + response.text 读取失败"""
        mock_cfg.return_value = (_make_config(), 120)
        mock_ensure.return_value = None

        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_resp.json.side_effect = ValueError("bad json")
        type(mock_resp).text = PropertyMock(side_effect=RuntimeError("text fail"))

        with patch("server.requests.post", return_value=mock_resp):
            result = self._run("test prompt")
        self.assertIsInstance(result, list)

    @patch("server.wait_for_task_completion")
    @patch("server.ensure_web_ui_running")
    @patch("server.get_web_ui_config")
    @patch("server._generate_task_id", return_value="if-task-18")
    @patch("server.NOTIFICATION_AVAILABLE", False)
    def test_fallback_dict_with_text_field(
        self, mock_tid, mock_cfg, mock_ensure, mock_wait
    ):
        """dict 有 text 字段但不只有 text — 走兜底路径"""
        mock_cfg.return_value = (_make_config(), 120)
        mock_ensure.return_value = None
        mock_wait.return_value = {"text": "fallback", "extra": True}

        mock_resp = MagicMock()
        mock_resp.status_code = 200

        with patch("server.requests.post", return_value=mock_resp):
            result = self._run("test prompt")
        self.assertIsInstance(result, list)
        self.assertTrue(len(result) > 0)
        self.assertIsInstance(result[0], TextContent)


# ═══════════════════════════════════════════════════════════════════════════
#  FeedbackServiceContext.launch_feedback_ui_method (line 1617)
# ═══════════════════════════════════════════════════════════════════════════
class TestFeedbackServiceContextMethod(unittest.TestCase):
    @patch("server.launch_feedback_ui", return_value={"user_input": "ok"})
    @patch("server.get_web_ui_config")
    def test_launch_delegates(self, mock_cfg, mock_launch):
        mock_cfg.return_value = (_make_config(), 120)
        ctx = server.FeedbackServiceContext()
        ctx.__enter__()
        result = ctx.launch_feedback_ui("hello", ["A"], "t1", 300)
        self.assertEqual(result["user_input"], "ok")
        mock_launch.assert_called_once_with("hello", ["A"], "t1", 300)


if __name__ == "__main__":
    unittest.main()
