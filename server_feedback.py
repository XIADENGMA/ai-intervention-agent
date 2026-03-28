"""反馈交互层 - interactive_feedback 工具实现、任务轮询与上下文管理。

该模块从 `server.py` 抽取反馈相关逻辑，避免在 MCP 入口文件里堆积业务代码。
注意：`interactive_feedback` 的 MCP 工具注册由 `server.py` 持有的 `mcp` 实例完成，
本模块内的 `interactive_feedback` 为“未装饰”的实现函数。
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any, Dict, Optional, cast

import httpx
from mcp.types import TextContent
from pydantic import Field

import server_config
import service_manager
from enhanced_logging import EnhancedLogger
from exceptions import (
    ServiceConnectionError,
    ServiceTimeoutError,
    ServiceUnavailableError,
    ValidationError,
)

logger = EnhancedLogger(__name__)


try:
    from notification_manager import NotificationTrigger, notification_manager
    from notification_models import NotificationType

    NOTIFICATION_AVAILABLE = True
    logger.info("通知系统已导入")
except ImportError as e:
    logger.warning(f"通知系统不可用: {e}", exc_info=True)
    NOTIFICATION_AVAILABLE = False


async def wait_for_task_completion(task_id: str, timeout: int = 260) -> Dict[str, Any]:
    """通过轮询 HTTP API 等待任务完成（异步版本）"""
    if timeout > 0:
        timeout = max(timeout, server_config.BACKEND_MIN)

    config, _ = service_manager.get_web_ui_config()
    target_host = server_config.get_target_host(config.host)
    api_url = f"http://{target_host}:{config.port}/api/tasks/{task_id}"

    start_time_monotonic = time.monotonic()
    deadline_monotonic = start_time_monotonic + timeout if timeout > 0 else float("inf")

    if timeout == 0:
        logger.info(f"等待任务完成: {task_id}, 超时时间: 无限等待")
    else:
        logger.info(f"等待任务完成: {task_id}, 超时时间: {timeout}秒（使用单调时间）")

    _POLL_INTERVAL_S = 0.5

    while timeout == 0 or time.monotonic() < deadline_monotonic:
        try:
            config_tuple = service_manager.get_web_ui_config()
            client = service_manager.get_async_client(config_tuple[0])
            response = await client.get(api_url, timeout=2)

            if response.status_code == 404:
                logger.warning(f"任务不存在: {task_id}，引导重新调用")
                return cast(
                    Dict[str, Any], server_config._make_resubmit_response(as_mcp=False)
                )

            if response.status_code != 200:
                logger.warning(f"获取任务状态失败: HTTP {response.status_code}")
                await asyncio.sleep(_POLL_INTERVAL_S)
                continue

            try:
                task_data = response.json()
            except ValueError as e:
                logger.warning(f"任务状态响应不是有效 JSON: {e}", exc_info=True)
                await asyncio.sleep(_POLL_INTERVAL_S)
                continue

            if not isinstance(task_data, dict):
                logger.warning(
                    f"任务状态响应类型异常: {type(task_data)}，已忽略并继续轮询"
                )
                await asyncio.sleep(_POLL_INTERVAL_S)
                continue

            if task_data.get("success") and task_data.get("task"):
                task = task_data["task"]
                if isinstance(task, dict):
                    if task.get("status") == "completed" and task.get("result"):
                        logger.info(f"任务完成: {task_id}")
                        return cast(Dict[str, Any], task["result"])

        except httpx.HTTPError as e:
            logger.warning(f"轮询任务状态失败: {e}", exc_info=True)

        await asyncio.sleep(_POLL_INTERVAL_S)

    elapsed = time.monotonic() - start_time_monotonic
    logger.error(
        f"任务超时: {task_id}, 等待时间已超过 {elapsed:.1f} 秒（使用单调时间判断）"
    )
    return cast(Dict[str, Any], server_config._make_resubmit_response(as_mcp=False))


def launch_feedback_ui(
    summary: str,
    predefined_options: Optional[list[str]] = None,
    task_id: Optional[str] = None,
    timeout: int = 300,
) -> Dict[str, Any]:
    """废弃：旧版 Python API，推荐使用 interactive_feedback() MCP 工具"""
    # 确保超时时间不小于300秒（0表示无限等待，保持不变）
    if timeout > 0:
        timeout = max(timeout, 300)
    try:
        # 自动生成唯一 task_id（task_id 参数将被忽略，始终使用自动生成）
        task_id = server_config._generate_task_id()

        # 验证输入参数
        cleaned_summary, cleaned_options = server_config.validate_input(
            summary, predefined_options
        )

        # 获取配置
        config, auto_resubmit_timeout = service_manager.get_web_ui_config()

        logger.info(
            f"启动反馈界面: {cleaned_summary[:100]}... (自动生成task_id: {task_id})"
        )

        # 确保 Web UI 正在运行（在同步函数中运行异步函数）
        asyncio.run(service_manager.ensure_web_ui_running(config))

        # 通过 HTTP API 向 web_ui 添加任务
        target_host = server_config.get_target_host(config.host)
        api_url = f"http://{target_host}:{config.port}/api/tasks"

        try:
            client = service_manager.get_sync_client(config)
            response = client.post(
                api_url,
                json={
                    "task_id": task_id,
                    "prompt": cleaned_summary,
                    "predefined_options": cleaned_options,
                    "auto_resubmit_timeout": auto_resubmit_timeout,
                },
                timeout=5,
            )

            if response.status_code != 200:
                error_detail = "未知错误"
                try:
                    payload = response.json()
                    if isinstance(payload, dict):
                        error_detail = str(payload.get("error", error_detail))
                    else:
                        error_detail = str(payload)
                except ValueError:
                    try:
                        if response.text:
                            error_detail = response.text[:200]
                    except Exception:
                        pass
                logger.error(
                    f"添加任务失败: HTTP {response.status_code}, 详情: {error_detail}"
                )
                return {
                    "error": f"添加任务失败: {error_detail}",
                }

            logger.info(f"任务已通过API添加到队列: {task_id}")

            # 【新增】发送通知（立即触发，不阻塞主流程）
            if NOTIFICATION_AVAILABLE:
                try:
                    # 【关键修复】从配置文件刷新配置，解决跨进程配置不同步问题
                    # Web UI 以子进程方式运行，配置更新只发生在 Web UI 进程中
                    # MCP 服务器进程需要在发送通知前同步最新配置
                    notification_manager.refresh_config_from_file()

                    # 截断消息，避免过长（Bark 有长度限制）
                    notification_message = cleaned_summary[:100]
                    if len(cleaned_summary) > 100:
                        notification_message += "..."

                    # MCP 侧仅发送系统级通知，Bark 由前端统一处理（避免跨进程双重推送）
                    mcp_types = [
                        t
                        for t in [NotificationType.SYSTEM, NotificationType.SOUND]
                        if t != NotificationType.BARK
                    ]
                    event_id = notification_manager.send_notification(
                        title="新的交互反馈请求",
                        message=notification_message,
                        trigger=NotificationTrigger.IMMEDIATE,
                        types=mcp_types,
                        metadata={"task_id": task_id, "source": "launch_feedback_ui"},
                    )

                    if event_id:
                        logger.debug(
                            f"已为任务 {task_id} 发送通知，事件 ID: {event_id}"
                        )
                    else:
                        logger.debug(f"任务 {task_id} 通知已跳过（通知系统已禁用）")

                except Exception as e:
                    # 通知失败不影响任务创建，仅记录警告
                    logger.warning(
                        f"发送任务通知失败: {e}，任务 {task_id} 已正常创建",
                        exc_info=True,
                    )
            else:
                logger.debug("通知系统不可用，跳过通知发送")

        except httpx.HTTPError as e:
            logger.error(f"添加任务请求失败: {e}", exc_info=True)
            return {
                "error": f"无法连接到 Web UI：{e}。请确认 Web UI 服务已启动，并检查地址/端口配置（如 web_ui.host/web_ui.port 或 VS Code 的 serverUrl）。"
            }

        # 【优化】使用统一的超时计算函数
        # timeout=0 表示无限等待模式
        backend_timeout = server_config.calculate_backend_timeout(
            auto_resubmit_timeout,
            max_timeout=max(timeout, 0),  # 传入的 timeout 参数作为参考
            infinite_wait=(timeout == 0),
        )
        logger.info(
            f"后端等待时间: {backend_timeout}秒 (前端倒计时: {auto_resubmit_timeout}秒, 传入timeout: {timeout}秒)"
        )
        # 在同步函数中运行异步函数（废弃的 API，保持向后兼容）
        result = asyncio.run(wait_for_task_completion(task_id, timeout=backend_timeout))

        if "error" in result:
            logger.error(f"任务执行失败: {result['error']}")
            return {"error": result["error"]}

        logger.info("用户反馈收集完成")
        return result

    except ValueError as e:
        logger.error(f"输入参数错误: {e}", exc_info=True)
        raise ValidationError(f"参数验证失败: {e}", code="invalid_params") from e
    except FileNotFoundError as e:
        logger.error(f"文件未找到: {e}", exc_info=True)
        raise ServiceUnavailableError(
            f"必要文件缺失: {e}", code="file_not_found"
        ) from e
    except (
        ServiceConnectionError,
        ServiceTimeoutError,
        ServiceUnavailableError,
        ValidationError,
    ):
        raise
    except Exception as e:
        logger.error(f"启动反馈界面失败: {e}", exc_info=True)
        raise ServiceUnavailableError(
            f"反馈界面启动失败: {e}", code="start_failed"
        ) from e


async def interactive_feedback(
    message: str = Field(description="向用户展示的具体问题/提示（支持 Markdown）"),
    predefined_options: Optional[list] = Field(
        default=None,
        description="可选的预定义选项列表，供用户单选/多选",
    ),
) -> list:
    """
    MCP 工具实现：请求用户通过 Web UI 提供交互反馈

    注意：该函数本身不负责 MCP 工具注册；注册由 `server.py` 中的 `mcp` 完成。
    """
    try:
        # 输入清理：截断过长内容，过滤非法选项（对齐工具契约/避免后端 400）
        cleaned_message, cleaned_options = server_config.validate_input(
            message, predefined_options
        )
        predefined_options_list = cleaned_options

        # 自动生成唯一 task_id（避免极端并发下碰撞）
        task_id = server_config._generate_task_id()

        logger.info(
            f"收到反馈请求: {cleaned_message[:50]}... (自动生成task_id: {task_id})"
        )

        # 获取配置
        config, auto_resubmit_timeout = service_manager.get_web_ui_config()

        # 确保 Web UI 正在运行
        await service_manager.ensure_web_ui_running(config)

        # 通过 HTTP API 添加任务
        target_host = server_config.get_target_host(config.host)
        api_url = f"http://{target_host}:{config.port}/api/tasks"

        try:
            client = service_manager.get_async_client(config)
            response = await client.post(
                api_url,
                json={
                    "task_id": task_id,
                    "prompt": cleaned_message,
                    "predefined_options": predefined_options_list,
                    "auto_resubmit_timeout": auto_resubmit_timeout,
                },
                timeout=5,
            )

            if response.status_code != 200:
                # 记录详细错误信息到日志
                error_detail = "未知错误"
                try:
                    payload = response.json()
                    if isinstance(payload, dict):
                        error_detail = str(payload.get("error", error_detail))
                    else:
                        error_detail = str(payload)
                except ValueError as e:
                    logger.warning(
                        f"添加任务失败响应不是有效 JSON: {e}",
                        exc_info=True,
                    )
                    try:
                        if response.text:
                            error_detail = response.text[:200]
                    except Exception:
                        # response.text 读取失败不应影响主流程
                        pass
                logger.error(
                    f"添加任务失败: HTTP {response.status_code}, 详情: {error_detail}"
                )
                # 返回配置的提示语，引导 AI 重新调用工具
                return server_config._make_resubmit_response()

            logger.info(f"任务已通过API添加到队列: {task_id}")

            # 【新增】发送通知（立即触发，不阻塞主流程）
            if NOTIFICATION_AVAILABLE:
                try:
                    # 【关键修复】从配置文件刷新配置，解决跨进程配置不同步问题
                    # Web UI 以子进程方式运行，配置更新只发生在 Web UI 进程中
                    # MCP 服务器进程需要在发送通知前同步最新配置
                    notification_manager.refresh_config_from_file()

                    # 截断消息，避免过长（Bark 有长度限制）
                    notification_message = cleaned_message[:100]
                    if len(cleaned_message) > 100:
                        notification_message += "..."

                    # MCP 侧仅发送系统级通知，Bark 由前端统一处理（避免跨进程双重推送）
                    mcp_types = [
                        t
                        for t in [NotificationType.SYSTEM, NotificationType.SOUND]
                        if t != NotificationType.BARK
                    ]
                    event_id = notification_manager.send_notification(
                        title="新的反馈请求",
                        message=notification_message,
                        trigger=NotificationTrigger.IMMEDIATE,
                        types=mcp_types,
                        metadata={"task_id": task_id, "source": "interactive_feedback"},
                    )

                    if event_id:
                        logger.debug(
                            f"已为任务 {task_id} 发送通知，事件 ID: {event_id}"
                        )
                    else:
                        logger.debug(f"任务 {task_id} 通知已跳过（通知系统已禁用）")

                except Exception as e:
                    # 通知失败不影响任务创建，仅记录警告
                    logger.warning(
                        f"发送任务通知失败: {e}，任务 {task_id} 已正常创建",
                        exc_info=True,
                    )
            else:
                logger.debug("通知系统不可用，跳过通知发送")

        except httpx.HTTPError as e:
            logger.error(f"添加任务请求失败，无法连接到 Web UI: {e}", exc_info=True)
            # 返回配置的提示语，引导 AI 重新调用工具
            return server_config._make_resubmit_response()

        # 【优化】使用统一的超时计算函数，利用 feedback.timeout 作为上限
        backend_timeout = server_config.calculate_backend_timeout(auto_resubmit_timeout)
        logger.info(
            f"后端等待时间: {backend_timeout}秒 (前端倒计时: {auto_resubmit_timeout}秒)"
        )
        result = await wait_for_task_completion(task_id, timeout=backend_timeout)

        if "error" in result:
            # 记录任务执行失败的详细错误
            logger.error(f"任务执行失败: {result['error']}, 任务 ID: {task_id}")
            # 返回配置的提示语，引导 AI 重新调用工具
            return server_config._make_resubmit_response()

        logger.info("反馈请求处理完成")

        # 解析返回：兼容新旧格式 + 兜底处理 {"text": "..."} 降级返回
        if isinstance(result, dict):
            # wait_for_task_completion 的降级返回（超时/404）：{"text": "..."}
            if set(result.keys()) == {"text"} and isinstance(result.get("text"), str):
                return [TextContent(type="text", text=str(result["text"]))]

            # 新格式（结构化 JSON，可能含 images）
            if (
                "images" in result
                or "user_input" in result
                or "selected_options" in result
            ):
                return server_config.parse_structured_response(result)

            # 旧格式：只有文本反馈
            legacy = result.get("interactive_feedback")
            if isinstance(legacy, str) and legacy.strip():
                return [
                    TextContent(
                        type="text",
                        text=server_config._append_prompt_suffix(legacy),
                    )
                ]

            # 最后兜底：尽量取 text 字段，否则转字符串
            fallback = (
                result.get("text")
                if isinstance(result.get("text"), str)
                else str(result)
            )
            return [
                TextContent(
                    type="text",
                    text=server_config._append_prompt_suffix(str(fallback)),
                )
            ]

        # 简单字符串结果
        return [
            TextContent(
                type="text",
                text=server_config._append_prompt_suffix(str(result)),
            )
        ]

    except Exception as e:
        logger.error(f"interactive_feedback 工具执行失败: {e}", exc_info=True)
        # 返回配置的提示语，引导 AI 重新调用工具
        return server_config._make_resubmit_response()


class FeedbackServiceContext:
    """反馈服务上下文管理器 - 自动管理服务启动和清理"""

    def __init__(self):
        """初始化，延迟加载配置"""
        self.service_manager = service_manager.ServiceManager()
        self.config = None
        self.script_dir = None

    def __enter__(self):
        """加载配置并返回 self"""
        try:
            self.config, self.auto_resubmit_timeout = (
                service_manager.get_web_ui_config()
            )
            self.script_dir = Path(__file__).resolve().parent
            logger.info(
                f"反馈服务上下文已初始化，自动重调超时: {self.auto_resubmit_timeout}秒"
            )
            return self
        except Exception as e:
            logger.error(f"初始化反馈服务上下文失败: {e}", exc_info=True)
            raise

    def __exit__(self, exc_type, exc_val, exc_tb):
        """清理所有服务进程（退出上下文时）"""
        del exc_tb
        try:
            # 上下文退出不等同于进程退出：仅清理子进程/端口等资源，保留通知线程池可用性
            self.service_manager.cleanup_all(shutdown_notification_manager=False)
            if exc_type is KeyboardInterrupt:
                logger.info("收到中断信号，服务已清理")
            elif exc_type is not None:
                logger.error(f"异常退出，服务已清理: {exc_type.__name__}: {exc_val}")
            else:
                logger.info("正常退出，服务已清理")
        except Exception as e:
            logger.error(f"清理服务时出错: {e}", exc_info=True)

    def launch_feedback_ui(
        self,
        summary: str,
        predefined_options: Optional[list[str]] = None,
        task_id: Optional[str] = None,
        timeout: int = 300,
    ) -> Dict[str, Any]:
        """在上下文中启动反馈界面（委托给全局 launch_feedback_ui）"""
        return launch_feedback_ui(summary, predefined_options, task_id, timeout)
