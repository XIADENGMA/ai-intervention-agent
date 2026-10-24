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

import logging
import os
import re
import shutil
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path

# R76 src/ layout 改造之后，让 ``import ai_intervention_agent.<module>`` 在
# 不依赖 ``pip install -e .`` 的本地 / CI 测试环境也可以解析：把
# ``<repo>/src`` 注入 ``sys.path[0]``。pytest 自身会把 ``tests/`` 注入但
# 不会自动注入 ``src/``，所以这一行是必须的；若已注入则不重复添加。
_REPO_ROOT_CONFTEST = Path(__file__).resolve().parent.parent
_SRC_ROOT_CONFTEST = _REPO_ROOT_CONFTEST / "src"
if _SRC_ROOT_CONFTEST.is_dir() and str(_SRC_ROOT_CONFTEST) not in sys.path:
    sys.path.insert(0, str(_SRC_ROOT_CONFTEST))

# pytest 仅在测试运行时可用；conftest.py 只会被 pytest 加载
import pytest

# 会话级临时目录（pytest 退出时自动清理）
_TEST_TMP_PREFIX = "ai-intervention-agent-pytest-"
_TEST_TMP_DIR = tempfile.TemporaryDirectory(prefix=_TEST_TMP_PREFIX)
_TEST_CONFIG_PATH = Path(_TEST_TMP_DIR.name) / "config.toml"
# 全局 TaskQueue 单例的快照文件。生产路径是 <包目录>/data/tasks.json，而
# ``get_task_queue()`` 构造时会从它恢复任务、之后每次变更都写回——测试若直接
# 用它，会把 ``r520-new`` 之类的夹具任务留在开发者的真实快照里，并且让同一
# 台机器上下一次的测试 / 服务启动读到"幽灵任务"。每个 xdist worker 各有自己
# 的临时目录，所以也不会互相覆盖。
_TEST_TASKS_PATH = Path(_TEST_TMP_DIR.name) / "data" / "tasks.json"

_CONFIG_ENV = "AI_INTERVENTION_AGENT_CONFIG_FILE"
# ``tempfile`` 给 ``prefix`` 补 8 个 [a-z0-9_] 随机字符
_SESSION_DIR_NAME = re.compile(re.escape(_TEST_TMP_PREFIX) + r"[a-z0-9_]{8}")


def _is_path_in_a_pytest_session_dir(raw: str) -> bool:
    """``raw`` 落在某个 pytest 会话（本进程或别的进程）建出来的临时目录里。"""
    return any(_SESSION_DIR_NAME.fullmatch(part) for part in Path(raw).parts)


# 仅当外部未显式指定时才注入，方便本地/CI 自定义。
# 但 pytest-xdist 的主进程也会导入本文件、并把自己的临时路径写进环境变量，worker 继承
# 之后若把它当成"外部显式指定"，所有 worker 就共用主进程目录里的同一份 config.toml：
# ``_is_managed_tmp_config`` 对 worker 自己的临时目录不成立，每个用例前的"重置为默认"
# 随之变成空操作，一个 worker 里写配置的用例（轮换 token、改通知设置……）会漏进另一个
# worker 里正在读配置的用例。别的 pytest 会话留下的路径不是显式指定，每个进程用自己的。
_inherited_config = os.environ.get(_CONFIG_ENV)
if not _inherited_config or _is_path_in_a_pytest_session_dir(_inherited_config):
    os.environ[_CONFIG_ENV] = str(_TEST_CONFIG_PATH)


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _default_config_template() -> Path:
    """返回仓库随附的默认 TOML 配置模板路径。

    R76 起仅保留 TOML 模板（``config.toml.default``）。v1.4 之前的 JSONC
    自动迁移路径在 ``config_manager`` 中仍然支持，但已不再分发独立的
    ``config.jsonc.default`` 样例（用户若要切回 JSONC 自行从 TOML 改写
    即可，``_load_jsonc`` 路径不需要它做 parity）。
    """
    return _project_root() / "config.toml.default"


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

        import ai_intervention_agent.enhanced_logging as enhanced_logging  # noqa: F401

        _loguru_logger.remove()
    except Exception:
        # 静默 fallback：测试运行不应被日志静音失败拖垮
        pass
    yield


def reset_log_duplicate_windows() -> None:
    """清空所有包内模块级 ``EnhancedLogger`` 的重复日志窗口。"""
    for name, loaded in list(sys.modules.items()):
        if not name.startswith("ai_intervention_agent"):
            continue
        namespace = getattr(loaded, "__dict__", None)
        if not isinstance(namespace, dict):
            continue
        for attribute in ("logger", "enhanced_logger"):
            candidate = namespace.get(attribute)
            # 按类名而不是 isinstance 判断：有用例会 reload enhanced_logging，
            # 之前创建的 logger 属于旧的 EnhancedLogger 类。
            if type(candidate).__name__ != "EnhancedLogger":
                continue
            with candidate.deduplicator.lock:
                candidate.deduplicator.cache.clear()


@pytest.fixture(autouse=True)
def _reset_log_duplicate_window():
    """每个用例都从空的重复日志窗口开始。

    ``EnhancedLogger`` 在 5 秒内丢弃相同的消息，窗口随 logger 实例存在于整个
    进程。先跑的用例发过某条警告，后跑的 ``assertLogs`` 就什么也收不到——
    用例是否通过取决于执行顺序。
    """
    reset_log_duplicate_windows()
    yield


@pytest.fixture(autouse=True)
def _reset_feedback_failure_streak():
    """每个用例都从“还没有连续失败过”开始（R857）。

    ``interactive_feedback`` 在进程里数连续失败：第三次起不再回“请立即重调”，而是
    说明原因。这个计数跟着模块活整个 pytest 进程，前面的用例失败过两次，后面用例
    的第一次失败就会拿到另一种回复——用例是否通过取决于执行顺序。
    只在模块已经被导入时才动它：没导入过就没有计数，也不该为此付一次导入。
    """

    def reset() -> None:
        module = sys.modules.get("ai_intervention_agent.server_feedback")
        clear = getattr(module, "reset_failure_streak_for_testing", None)
        if clear is not None:
            clear()

    reset()
    yield
    reset()


def snapshot_global_log_levels() -> Callable[[], None]:
    """记录 root logger、root 上所有 handler 和 werkzeug 当前的级别，返回还原它们的函数。"""
    root = logging.getLogger()
    werkzeug = logging.getLogger("werkzeug")
    root_level = root.level
    werkzeug_level = werkzeug.level
    handler_levels = [(handler, handler.level) for handler in root.handlers]

    def restore() -> None:
        root.setLevel(root_level)
        werkzeug.setLevel(werkzeug_level)
        for handler, level in handler_levels:
            handler.setLevel(level)

    return restore


@pytest.fixture(autouse=True)
def _restore_global_log_levels():
    """每个用例结束后把全局日志级别还原成开始时的样子。

    ``apply_runtime_log_level``（POST ``/api/system/log-level``）同时改 root
    logger、root 上所有 handler 和 werkzeug 的级别。做完不还原，后面的用例就带着
    INFO 级别跑，连 pytest 自己长期挂在 root 上的 live-log handler 也被放宽了。
    pytest 9.1 起这些 handler 还会直接挂到不向上传播的 logger 上，INFO 记录一经过
    它，pytest 就暂停再恢复输出捕获，把用例里 ``redirect_stdout`` 设的目标换掉。
    """
    restore = snapshot_global_log_levels()
    yield
    restore()


def _redirected_default_persist_path() -> Path:
    return _TEST_TASKS_PATH


@pytest.fixture(scope="session", autouse=True)
def _isolate_task_queue_persist_path():
    """把全局 TaskQueue 单例的持久化文件重定向到本会话的临时目录（R770）。

    与上面的配置文件隔离同一个思路：``get_task_queue()`` 的默认路径在包目录里
    （``_default_persist_path()``），测试不应该读写它。只替换路径解析函数，
    单例本身、``TaskQueue`` 的持久化 / 恢复逻辑都保持原样，因此仍在真实地
    被测试覆盖。

    必须是 session 级：unittest 风格的用例在 ``setUpClass`` 里就会首次创建单例
    （例如 ``WebFeedbackUI`` 的构造），那一步发生在任何 function 级 fixture
    之前，function 级的替换来不及生效。
    """
    try:
        import ai_intervention_agent.task_queue_singleton as task_queue_singleton
    except Exception:
        yield
        return

    patcher = pytest.MonkeyPatch()
    patcher.setattr(
        task_queue_singleton,
        "_default_persist_path",
        _redirected_default_persist_path,
        raising=True,
    )
    try:
        yield
    finally:
        patcher.undo()


@pytest.fixture(autouse=True)
def _reassert_task_queue_persist_redirect():
    """每个用例结束后把重定向放回去。

    ``importlib.reload(task_queue_singleton)`` 会重新执行模块体，把
    ``_default_persist_path`` 还原成指向包目录的原版；同一个进程里之后的用例
    再创建单例，就又会读写开发者的真实快照。
    """
    yield
    try:
        import ai_intervention_agent.task_queue_singleton as task_queue_singleton
    except Exception:
        return
    task_queue_singleton._default_persist_path = (  # ty: ignore[invalid-assignment]
        _redirected_default_persist_path
    )
    # R836：``web_feedback_ui`` 会把单例绑到它的端口；一个用例绑过的端口不该决定下一个
    # 用例里快照文件的名字。
    task_queue_singleton._bound_port = None


@pytest.fixture(autouse=True)
def _isolate_config_and_notification_singletons():
    """每个用例前后都做隔离，保证测试离线且互不污染。"""
    config_path = _active_config_path()

    # 1) 配置文件：每个用例开始时回到默认值，避免跨测试污染
    _reset_config_file_to_default(config_path)

    # 2) ConfigManager：如已导入，则强制重新加载并清缓存
    try:
        from ai_intervention_agent.config_manager import config_manager

        config_manager.reload()
    except Exception:
        # 允许某些用例在未导入 config_manager 时运行
        pass

    # 3) NotificationManager：取消残留 Timer、确保线程池可用，并让 Bark provider 与配置一致
    try:
        from ai_intervention_agent.notification_manager import (
            NotificationManager,
            NotificationType,
            notification_manager,
        )

        # 有的用例用 ``__new__`` 自建实例（``_make_manager``），``__new__`` 会把
        # 它登记成单例；不拉回来，后面的 ``NotificationManager()`` 会拿到别人
        # 留下的、可能已经 shutdown 的实例。
        NotificationManager._instance = notification_manager

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

        # R323 (cycle-34 #B2, v3.8 test-isolation pattern 3rd app): 调用
        # ``reset_for_testing()`` 重置 singleton 的 in-memory state (stats /
        # histograms / queue / callbacks / delayed timers / inflight 等),
        # 让跨测试 singleton 隔离全自动化, 不再需要测试 setUp 手动维护。
        # 详见 ``NotificationManager.reset_for_testing()`` docstring (与 R319
        # ``_create_test_instance()`` 互补关系)。
        try:
            notification_manager.reset_for_testing()
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
        from ai_intervention_agent.notification_manager import (
            NotificationType,
            notification_manager,
        )

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
