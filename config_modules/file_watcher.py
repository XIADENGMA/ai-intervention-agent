"""配置文件监听 Mixin。

提供 ConfigManager 的后台文件监听、配置变更回调注册/触发、
以及 shutdown 生命周期管理能力。
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import TYPE_CHECKING, Optional

from enhanced_logging import EnhancedLogger

if TYPE_CHECKING:
    from pathlib import Path

logger = EnhancedLogger(__name__)


class FileWatcherMixin:
    """文件监听、回调管理、shutdown 方法集合。"""

    if TYPE_CHECKING:
        config_file: Path
        _lock: threading.RLock
        _last_file_mtime: float
        _file_watcher_running: bool
        _file_watcher_interval: float
        _file_watcher_stop_event: threading.Event
        _file_watcher_thread: Optional[threading.Thread]
        _save_timer: Optional[threading.Timer]
        _config_change_callbacks: list[Callable[[], None]]

        def reload(self) -> None: ...

    def _update_file_mtime(self):
        """更新文件修改时间缓存"""
        try:
            if self.config_file.exists():
                mtime = self.config_file.stat().st_mtime
                with self._lock:
                    self._last_file_mtime = mtime
        except Exception as e:
            logger.warning(f"获取文件修改时间失败: {e}", exc_info=True)

    def start_file_watcher(self, interval: float = 2.0) -> None:
        """启动配置文件监听（后台守护线程，检测文件变化自动重载）"""
        with self._lock:
            if self._file_watcher_running:
                logger.debug("文件监听器已在运行")
                return

            self._file_watcher_interval = interval
            self._file_watcher_running = True
            self._file_watcher_stop_event.clear()

        try:
            if self.config_file.exists():
                current_mtime = self.config_file.stat().st_mtime
                if self._last_file_mtime and current_mtime > self._last_file_mtime:
                    logger.info("启动监听器时发现配置文件已变化，先执行一次重新加载")
                    with self._lock:
                        self._last_file_mtime = current_mtime
                    self.reload()
                    self._trigger_config_change_callbacks()
                elif self._last_file_mtime == 0:
                    with self._lock:
                        self._last_file_mtime = current_mtime
        except Exception as e:
            logger.warning(f"启动监听器时同步配置文件状态失败: {e}", exc_info=True)

        thread = threading.Thread(
            target=self._file_watcher_loop,
            name="ConfigFileWatcher",
            daemon=True,
        )
        with self._lock:
            self._file_watcher_thread = thread
        thread.start()
        logger.info(f"配置文件监听器已启动，检查间隔: {interval} 秒")

    def stop_file_watcher(self) -> None:
        """停止配置文件监听"""
        thread: Optional[threading.Thread]
        with self._lock:
            if not self._file_watcher_running:
                logger.debug("文件监听器未运行")
                return

            self._file_watcher_running = False
            self._file_watcher_stop_event.set()
            thread = self._file_watcher_thread
            self._file_watcher_thread = None

        if thread:
            thread.join(timeout=1.0)
        logger.info("配置文件监听器已停止")

    def shutdown(self) -> None:
        """关闭配置管理器：停止文件监听、取消延迟保存定时器（幂等）"""
        try:
            self.stop_file_watcher()
        except Exception as e:
            logger.debug(f"关闭文件监听器失败（忽略）: {e}")

        try:
            with self._lock:
                if self._save_timer is not None:
                    self._save_timer.cancel()
                    self._save_timer = None
        except Exception as e:
            logger.debug(f"取消延迟保存定时器失败（忽略）: {e}")

    def _file_watcher_loop(self):
        """文件监听循环（后台线程主循环）"""
        logger.debug("文件监听循环已启动")
        while self._file_watcher_running:
            try:
                if self.config_file.exists():
                    current_mtime = self.config_file.stat().st_mtime
                    if current_mtime > self._last_file_mtime:
                        logger.info("检测到配置文件变化，自动重新加载")
                        with self._lock:
                            self._last_file_mtime = current_mtime
                        self.reload()
                        self._trigger_config_change_callbacks()
            except Exception as e:
                logger.warning(f"文件监听检查失败: {e}", exc_info=True)

            if self._file_watcher_stop_event.wait(self._file_watcher_interval):
                break

    def register_config_change_callback(self, callback: Callable[[], None]) -> None:
        """注册配置变更回调函数"""
        with self._lock:
            if callback not in self._config_change_callbacks:
                self._config_change_callbacks.append(callback)
                cb_name = getattr(callback, "__name__", None) or repr(callback)
                logger.debug(f"已注册配置变更回调: {cb_name}")

    def unregister_config_change_callback(self, callback: Callable[[], None]) -> None:
        """取消注册配置变更回调函数"""
        with self._lock:
            if callback in self._config_change_callbacks:
                self._config_change_callbacks.remove(callback)
                cb_name = getattr(callback, "__name__", None) or repr(callback)
                logger.debug(f"已取消配置变更回调: {cb_name}")

    def _trigger_config_change_callbacks(self):
        """触发所有配置变更回调"""
        with self._lock:
            callbacks = list(self._config_change_callbacks)

        for callback in callbacks:
            try:
                callback()
            except Exception as e:
                cb_name = getattr(callback, "__name__", None) or repr(callback)
                logger.error(f"配置变更回调执行失败 ({cb_name}): {e}", exc_info=True)

    @property
    def is_file_watcher_running(self) -> bool:
        """检查文件监听器是否在运行"""
        return self._file_watcher_running
