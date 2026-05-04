"""pytest 全局测试配置

目标：
- 让测试完全可重复、可离线运行
- 避免读取/污染用户真实配置（~/.config/ai-intervention-agent/）

实现：
- 通过环境变量 AI_INTERVENTION_AGENT_CONFIG_FILE 指定临时配置文件路径
- 该环境变量会被 config_manager.find_config_file() 优先读取

注意：
- 这里使用 TemporaryDirectory，并把对象保存在模块全局，确保整个 pytest 会话期间目录不被提前清理
"""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

# pytest 仅在测试运行时可用；conftest.py 只会被 pytest 加载
import pytest

# 会话级临时目录（pytest 退出时自动清理）
_TEST_TMP_DIR = tempfile.TemporaryDirectory(prefix="ai-intervention-agent-pytest-")
_TEST_CONFIG_PATH = Path(_TEST_TMP_DIR.name) / "config.toml"

# 仅当外部未显式指定时才注入，方便本地/CI 自定义
_CONFIG_ENV = "AI_INTERVENTION_AGENT_CONFIG_FILE"
os.environ.setdefault(_CONFIG_ENV, str(_TEST_CONFIG_PATH))


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _default_config_template() -> Path:
    root = _project_root()
    toml_tpl = root / "config.toml.default"
    if toml_tpl.exists():
        return toml_tpl
    return root / "config.jsonc.default"


def _active_config_path() -> Path:
    # 允许外部覆盖，但避免对外部路径做破坏性写入
    raw = os.environ.get(_CONFIG_ENV, str(_TEST_CONFIG_PATH))
    return Path(raw).expanduser().resolve()


def _is_managed_tmp_config(path: Path) -> bool:
    try:
        tmp_root = Path(_TEST_TMP_DIR.name).resolve()
        return tmp_root == path.parent or tmp_root in path.parents
    except Exception:
        return False


def _reset_config_file_to_default(path: Path) -> None:
    """将测试配置文件重置为默认模板（仅对本 conftest 管理的临时路径生效）"""
    if not _is_managed_tmp_config(path):
        return

    path.parent.mkdir(parents=True, exist_ok=True)
    template = _default_config_template()
    if template.exists():
        shutil.copy2(template, path)
    else:
        # 极端兜底：模板丢失时仍保证文件存在
        path.write_text("{}", encoding="utf-8")


# 确保 pytest 会话开始前就有一份“默认配置”，避免首次加载走到用户目录
_reset_config_file_to_default(_active_config_path())


@pytest.fixture(scope="session", autouse=True)
def _silence_loguru_sinks_during_tests():
    """会话级：移除 enhanced_logging 模块加载时注入的 loguru stderr sink。

    背景
    ----
    `enhanced_logging.py` 通过 `InterceptHandler` 把 stdlib logging 路由到
    loguru，并把 loguru sink 接到 `sys.__stderr__`（绕过 pytest capsys）。
    LogDeduplicator 还有 5 秒时间窗口去重——这两件事叠加导致 CI Gate 偶尔
    会“漏出”一条 retry/重试类 WARNING 到终端：
      1. 同一条消息在 5s 内只会输出一次（首次测试触发后被印一次）；
      2. 后续相同消息被去重静默，造成下一轮 ci_gate 看不到 WARNING；
      3. 但跨用例时序变化时（首测顺序不同）会再次漏出，输出不可预测。

    `assertLogs` 抓的是 stdlib LogRecord（在 InterceptHandler.emit 之前），
    因此移除 loguru sink 不影响“断言能抓到 WARNING”，只是让 loguru 不再
    直接写 stderr。pytest 输出立刻变得稳定干净。

    退出时不再 restore——pytest 进程立刻终止，restore 反而会引入额外的
    edge case（fixture 顺序、其他 finalizer 也想往 stderr 写）。
    """
    try:
        # 触发 enhanced_logging 加载（确保 sink 已注册），然后再 remove。
        from loguru import logger as _loguru_logger

        import enhanced_logging  # noqa: F401

        _loguru_logger.remove()
    except Exception:
        # 静默 fallback：测试运行不应被日志静音失败拖垮
        pass
    yield


@pytest.fixture(autouse=True)
def _isolate_config_and_notification_singletons():
    """每个用例前后都做隔离，保证测试离线且互不污染。"""
    config_path = _active_config_path()

    # 1) 配置文件：每个用例开始时回到默认值，避免跨测试污染
    _reset_config_file_to_default(config_path)

    # 2) ConfigManager：如已导入，则强制重新加载并清缓存
    try:
        from config_manager import config_manager

        config_manager.reload()
    except Exception:
        # 允许某些用例在未导入 config_manager 时运行
        pass

    # 3) NotificationManager：取消残留 Timer、确保线程池可用，并让 Bark provider 与配置一致
    try:
        from notification_manager import NotificationType, notification_manager

        # 清理上一个用例可能遗留的 timer/线程池（避免用例结束后继续重试打印日志）
        try:
            notification_manager.shutdown(wait=False)
        except Exception:
            pass
        try:
            notification_manager.restart()
        except Exception:
            pass

        # 强制从配置文件刷新（force=True 绕过 mtime 缓存），并同步 Bark provider 状态
        try:
            notification_manager.refresh_config_from_file(force=True)
        except Exception:
            pass

        # 关键：有些测试会直接改 config 字段绕过 update_config_without_save，
        # 这里强制对齐 provider（避免 Bark provider “幽灵存在”）
        try:
            notification_manager._update_bark_provider()
        except Exception:
            try:
                with notification_manager._providers_lock:
                    notification_manager._providers.pop(NotificationType.BARK, None)
            except Exception:
                pass
    except Exception:
        pass

    yield

    # 用例结束后再做一次“硬清理”，确保不会有后台重试/网络访问溜出 pytest 生命周期
    try:
        from notification_manager import NotificationType, notification_manager

        try:
            notification_manager.shutdown(wait=False)
        except Exception:
            pass
        try:
            notification_manager.restart()
        except Exception:
            pass

        # 额外确保 Bark provider 被移除（更保守，避免误触发真实网络）
        try:
            notification_manager.config.bark_enabled = False
            notification_manager.config.bark_url = ""
            notification_manager.config.bark_device_key = ""
            notification_manager._update_bark_provider()
        except Exception:
            try:
                with notification_manager._providers_lock:
                    notification_manager._providers.pop(NotificationType.BARK, None)
            except Exception:
                pass
    except Exception:
        pass


@pytest.fixture(autouse=True)
def _disable_real_network_requests(monkeypatch: pytest.MonkeyPatch):
    """全局禁用真实网络请求：任何未 mock 的 httpx 调用都应失败。"""
    import httpx

    def _blocked_send(self, request, *args, **kwargs):  # type: ignore[no-untyped-def]
        raise RuntimeError(f"测试环境禁止真实网络请求: {request.method} {request.url}")

    monkeypatch.setattr(httpx.Client, "send", _blocked_send, raising=True)
    monkeypatch.setattr(httpx.AsyncClient, "send", _blocked_send, raising=True)
    yield
