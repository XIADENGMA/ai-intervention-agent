"""exceptions.py 单元测试 — 异常层次、属性行为、make_error_response 工具函数。"""

import unittest

from exceptions import (
    AIAgentError,
    ConfigError,
    ConfigFileNotFoundError,
    ConfigValidationError,
    NotificationError,
    ServiceConnectionError,
    ServiceTimeoutError,
    ServiceUnavailableError,
    TaskError,
    TaskNotFoundError,
    TaskTimeoutError,
    ValidationError,
    make_error_response,
)


class TestAIAgentErrorBase(unittest.TestCase):
    """AIAgentError 基类行为。"""

    def test_message_only(self) -> None:
        exc = AIAgentError("出错了")
        self.assertEqual(str(exc), "出错了")
        self.assertIsNone(exc.code)
        self.assertEqual(exc.details, {})

    def test_with_code_and_details(self) -> None:
        exc = AIAgentError(
            "服务不可用",
            code="service_unavailable",
            details={"retry_after": 30},
        )
        self.assertEqual(str(exc), "服务不可用")
        self.assertEqual(exc.code, "service_unavailable")
        self.assertEqual(exc.details, {"retry_after": 30})

    def test_details_defaults_to_empty_dict(self) -> None:
        exc = AIAgentError("msg", details=None)
        self.assertIsInstance(exc.details, dict)
        self.assertEqual(exc.details, {})

    def test_is_exception_subclass(self) -> None:
        self.assertTrue(issubclass(AIAgentError, Exception))

    def test_can_be_raised_and_caught(self) -> None:
        with self.assertRaises(AIAgentError):
            raise AIAgentError("test")


class TestExceptionHierarchy(unittest.TestCase):
    """继承关系验证。"""

    def test_config_chain(self) -> None:
        self.assertTrue(issubclass(ConfigError, AIAgentError))
        self.assertTrue(issubclass(ConfigFileNotFoundError, ConfigError))
        self.assertTrue(issubclass(ConfigValidationError, ConfigError))

    def test_service_chain(self) -> None:
        self.assertTrue(issubclass(ServiceConnectionError, AIAgentError))
        self.assertTrue(issubclass(ServiceUnavailableError, ServiceConnectionError))
        self.assertTrue(issubclass(ServiceTimeoutError, ServiceConnectionError))

    def test_task_chain(self) -> None:
        self.assertTrue(issubclass(TaskError, AIAgentError))
        self.assertTrue(issubclass(TaskNotFoundError, TaskError))
        self.assertTrue(issubclass(TaskTimeoutError, TaskError))

    def test_notification_chain(self) -> None:
        self.assertTrue(issubclass(NotificationError, AIAgentError))

    def test_validation_chain(self) -> None:
        self.assertTrue(issubclass(ValidationError, AIAgentError))

    def test_catch_base_catches_all(self) -> None:
        """用 AIAgentError 可以捕获所有子异常。"""
        for exc_cls in [
            ConfigError,
            ConfigFileNotFoundError,
            ConfigValidationError,
            ServiceConnectionError,
            ServiceUnavailableError,
            ServiceTimeoutError,
            TaskError,
            TaskNotFoundError,
            TaskTimeoutError,
            NotificationError,
            ValidationError,
        ]:
            with self.assertRaises(
                AIAgentError, msg=f"{exc_cls.__name__} 未被基类捕获"
            ):
                raise exc_cls("test")

    def test_catch_mid_level_catches_children(self) -> None:
        """中间层（如 ConfigError）可以捕获其子异常。"""
        with self.assertRaises(ConfigError):
            raise ConfigFileNotFoundError("missing")
        with self.assertRaises(ServiceConnectionError):
            raise ServiceTimeoutError("timeout")
        with self.assertRaises(TaskError):
            raise TaskNotFoundError("not found")


class TestSubclassAttributes(unittest.TestCase):
    """子类同样支持 code / details 关键字参数。"""

    def test_config_error_with_code(self) -> None:
        exc = ConfigValidationError(
            "端口超出范围", code="validation", details={"port": 99999}
        )
        self.assertEqual(exc.code, "validation")
        self.assertEqual(exc.details["port"], 99999)

    def test_service_timeout_with_details(self) -> None:
        exc = ServiceTimeoutError(
            "连接超时", code="timeout", details={"elapsed_ms": 5000}
        )
        self.assertEqual(str(exc), "连接超时")
        self.assertEqual(exc.details["elapsed_ms"], 5000)

    def test_task_not_found_with_code(self) -> None:
        exc = TaskNotFoundError(
            "任务不存在", code="not_found", details={"task_id": "abc-123"}
        )
        self.assertEqual(exc.code, "not_found")
        self.assertEqual(exc.details["task_id"], "abc-123")


class TestMakeErrorResponse(unittest.TestCase):
    """make_error_response 工具函数。"""

    def test_default_status_code(self) -> None:
        body, status = make_error_response("参数错误")
        self.assertEqual(status, 400)
        self.assertEqual(body["success"], False)
        self.assertEqual(body["error"], "参数错误")
        self.assertNotIn("code", body)

    def test_custom_status_code(self) -> None:
        body, status = make_error_response("未找到", 404)
        self.assertEqual(status, 404)

    def test_with_code(self) -> None:
        body, status = make_error_response("任务不存在", 404, code="not_found")
        self.assertEqual(body["code"], "not_found")
        self.assertEqual(body["error"], "任务不存在")
        self.assertEqual(status, 404)

    def test_without_code_no_key(self) -> None:
        body, _ = make_error_response("error")
        self.assertNotIn("code", body)

    def test_return_type(self) -> None:
        result = make_error_response("err")
        self.assertIsInstance(result, tuple)
        self.assertEqual(len(result), 2)
        self.assertIsInstance(result[0], dict)
        self.assertIsInstance(result[1], int)


if __name__ == "__main__":
    unittest.main()
