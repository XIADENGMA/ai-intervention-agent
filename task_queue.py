"""
任务队列管理模块

支持多任务并发处理，包括任务添加、状态管理、延迟删除和后台清理
"""

import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime
from threading import Lock
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class Task:
    """任务数据结构

    Attributes:
        task_id: 任务唯一标识符
        prompt: 任务提示信息
        predefined_options: 预定义选项列表
        auto_resubmit_timeout: 自动重新提交超时时间（秒）
        created_at: 任务创建时间
        status: 任务状态（pending/active/completed/expired）
        result: 任务执行结果
        completed_at: 任务完成时间，用于延迟删除
    """

    task_id: str
    prompt: str
    predefined_options: Optional[List[str]] = None
    auto_resubmit_timeout: int = 290
    created_at: datetime = field(default_factory=datetime.now)
    status: str = "pending"
    result: Optional[Dict[str, str]] = None
    completed_at: Optional[datetime] = None


class TaskQueue:
    """任务队列管理器

    提供任务的添加、查询、状态管理和自动清理功能
    """

    def __init__(self, max_tasks: int = 10):
        """初始化任务队列

        Args:
            max_tasks: 最大并发任务数
        """
        self.max_tasks = max_tasks
        self._tasks: Dict[str, Task] = {}
        self._task_order: List[str] = []
        self._lock = Lock()
        self._active_task_id: Optional[str] = None

        self._stop_cleanup = threading.Event()
        self._cleanup_thread = threading.Thread(
            target=self._cleanup_loop, daemon=True, name="TaskQueueCleanup"
        )
        self._cleanup_thread.start()

        logger.info(f"任务队列初始化完成，最大任务数: {max_tasks}，后台清理线程已启动")

    def clear_all_tasks(self):
        """清理所有任务

        用于服务启动时清理残留任务

        Returns:
            int: 清理的任务数量
        """
        with self._lock:
            count = len(self._tasks)
            self._tasks.clear()
            self._task_order.clear()
            self._active_task_id = None
            if count > 0:
                logger.info(f"清理了所有残留任务，共 {count} 个")
            return count

    def add_task(
        self,
        task_id: str,
        prompt: str,
        predefined_options: Optional[List[str]] = None,
        auto_resubmit_timeout: int = 290,
    ) -> bool:
        """添加新任务到队列

        Args:
            task_id: 任务ID
            prompt: 任务提示信息
            predefined_options: 预定义选项列表
            auto_resubmit_timeout: 自动重新提交超时时间（秒）

        Returns:
            bool: 是否成功添加
        """
        with self._lock:
            if len(self._tasks) >= self.max_tasks:
                logger.warning(
                    f"任务队列已满({self.max_tasks})，无法添加新任务: {task_id}"
                )
                return False

            if task_id in self._tasks:
                logger.warning(f"任务ID已存在: {task_id}")
                return False

            task = Task(
                task_id=task_id,
                prompt=prompt,
                predefined_options=predefined_options,
                auto_resubmit_timeout=auto_resubmit_timeout,
            )

            self._tasks[task_id] = task
            self._task_order.append(task_id)

            if self._active_task_id is None:
                self._active_task_id = task_id
                task.status = "active"
            else:
                task.status = "pending"

            logger.info(
                f"添加任务成功: {task_id}, 当前任务数: {len(self._tasks)}/{self.max_tasks}"
            )
            return True

    def get_task(self, task_id: str) -> Optional[Task]:
        """获取指定任务

        Args:
            task_id: 任务ID

        Returns:
            Optional[Task]: 任务对象，不存在则返回 None
        """
        with self._lock:
            return self._tasks.get(task_id)

    def get_all_tasks(self) -> List[Task]:
        """获取所有任务（按添加顺序）

        Returns:
            List[Task]: 任务列表
        """
        with self._lock:
            return [self._tasks[tid] for tid in self._task_order if tid in self._tasks]

    def get_active_task(self) -> Optional[Task]:
        """获取当前活动任务

        Returns:
            Optional[Task]: 活动任务，不存在则返回 None
        """
        with self._lock:
            if self._active_task_id:
                return self._tasks.get(self._active_task_id)
            return None

    def set_active_task(self, task_id: str) -> bool:
        """设置活动任务

        Args:
            task_id: 任务ID

        Returns:
            bool: 是否成功设置
        """
        with self._lock:
            if task_id not in self._tasks:
                logger.warning(f"任务不存在: {task_id}")
                return False

            if self._active_task_id and self._active_task_id in self._tasks:
                old_task = self._tasks[self._active_task_id]
                if old_task.status == "active":
                    old_task.status = "pending"

            self._active_task_id = task_id
            self._tasks[task_id].status = "active"

            logger.info(f"切换到任务: {task_id}")
            return True

    def complete_task(self, task_id: str, result: Dict[str, str]) -> bool:
        """完成任务并标记为延迟删除

        不立即删除已完成的任务，而是标记完成时间并延迟删除，
        避免轮询时遇到 404"任务不存在"问题

        Args:
            task_id: 任务ID
            result: 任务执行结果

        Returns:
            bool: 是否成功完成
        """
        with self._lock:
            if task_id not in self._tasks:
                logger.warning(f"任务不存在: {task_id}")
                return False

            task = self._tasks[task_id]
            task.status = "completed"
            task.result = result
            task.completed_at = datetime.now()

            if self._active_task_id == task_id:
                self._active_task_id = None
                logger.info(f"任务完成并清空激活任务: {task_id}")

                for tid in self._task_order:
                    if tid in self._tasks and self._tasks[tid].status == "pending":
                        self._active_task_id = tid
                        self._tasks[tid].status = "active"
                        logger.info(f"自动激活下一个任务: {tid}")
                        break
            else:
                logger.info(f"任务完成: {task_id}")

            logger.info(f"任务 {task_id} 已标记为完成（将在 10 秒后自动清理）")

            return True

    def remove_task(self, task_id: str) -> bool:
        """移除任务

        Args:
            task_id: 任务ID

        Returns:
            bool: 是否成功移除
        """
        with self._lock:
            if task_id not in self._tasks:
                logger.warning(f"任务不存在: {task_id}")
                return False

            if self._active_task_id == task_id:
                self._active_task_id = None
                for tid in self._task_order:
                    if (
                        tid != task_id
                        and tid in self._tasks
                        and self._tasks[tid].status in ["pending", "active"]
                    ):
                        self._active_task_id = tid
                        self._tasks[tid].status = "active"
                        break

            del self._tasks[task_id]
            self._task_order.remove(task_id)

            logger.info(
                f"移除任务: {task_id}, 剩余任务数: {len(self._tasks)}/{self.max_tasks}"
            )
            return True

    def clear_completed_tasks(self) -> int:
        """清理所有已完成的任务

        Returns:
            int: 清理的任务数量
        """
        with self._lock:
            completed_task_ids = [
                tid for tid, task in self._tasks.items() if task.status == "completed"
            ]

            for tid in completed_task_ids:
                del self._tasks[tid]
                self._task_order.remove(tid)

            count = len(completed_task_ids)
            if count > 0:
                logger.info(f"清理了 {count} 个已完成任务")

            return count

    def cleanup_completed_tasks(self, age_seconds: int = 10) -> int:
        """清理超过指定时间的已完成任务

        Args:
            age_seconds: 任务完成后保留的秒数

        Returns:
            int: 清理的任务数量
        """
        with self._lock:
            now = datetime.now()
            tasks_to_remove = []

            for task_id, task in self._tasks.items():
                if task.status == "completed" and task.completed_at:
                    age = (now - task.completed_at).total_seconds()
                    if age > age_seconds:
                        tasks_to_remove.append(task_id)

            for task_id in tasks_to_remove:
                if task_id in self._tasks:
                    del self._tasks[task_id]
                if task_id in self._task_order:
                    self._task_order.remove(task_id)

            if tasks_to_remove:
                logger.info(
                    f"清理了 {len(tasks_to_remove)} 个已完成任务: {tasks_to_remove}"
                )

            return len(tasks_to_remove)

    def _cleanup_loop(self):
        """后台清理循环

        每5秒清理一次超过10秒的已完成任务
        """
        logger.info("后台清理线程启动")
        while not self._stop_cleanup.wait(timeout=5):
            try:
                cleaned = self.cleanup_completed_tasks(age_seconds=10)
                if cleaned > 0:
                    logger.debug(f"后台清理线程清理了 {cleaned} 个任务")
            except Exception as e:
                logger.error(f"后台清理线程异常: {e}", exc_info=True)
        logger.info("后台清理线程已停止")

    def stop_cleanup(self):
        """停止后台清理线程"""
        logger.info("正在停止后台清理线程...")
        self._stop_cleanup.set()
        if self._cleanup_thread.is_alive():
            self._cleanup_thread.join(timeout=2)
            if self._cleanup_thread.is_alive():
                logger.warning("后台清理线程未能在2秒内停止")
            else:
                logger.info("后台清理线程已成功停止")

    def get_task_count(self) -> Dict[str, int]:
        """获取任务统计信息

        Returns:
            Dict[str, int]: 包含各状态任务数量的字典
        """
        with self._lock:
            total = len(self._tasks)
            pending = sum(1 for t in self._tasks.values() if t.status == "pending")
            active = sum(1 for t in self._tasks.values() if t.status == "active")
            completed = sum(1 for t in self._tasks.values() if t.status == "completed")

            return {
                "total": total,
                "pending": pending,
                "active": active,
                "completed": completed,
                "max": self.max_tasks,
            }
