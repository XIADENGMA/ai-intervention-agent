import logging
import os
import socket
import subprocess
import sys
import time
from dataclasses import dataclass
from typing import Dict, Optional, Tuple
from urllib.parse import urlparse

import requests
from fastmcp import FastMCP
from pydantic import Field
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


mcp = FastMCP("AI Intervention Agent MCP")

# 配置日志系统
log_handlers = [logging.StreamHandler(sys.stderr)]

# 可选：同时输出到文件（取消注释下面两行来启用文件日志）
# log_file = os.path.join(os.path.dirname(__file__), 'ai_intervention_agent.log')
# log_handlers.append(logging.FileHandler(log_file))

logging.basicConfig(
    level=logging.WARNING,  # 只显示警告和错误，减少日志噪音
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=log_handlers
)
logger = logging.getLogger(__name__)


@dataclass
class WebUIConfig:
    """Web UI 配置类"""
    host: str
    port: int
    timeout: int = 30
    max_retries: int = 3
    retry_delay: float = 1.0

    def __post_init__(self):
        """验证配置参数"""
        if not (1 <= self.port <= 65535):
            raise ValueError(f"端口号必须在 1-65535 范围内，当前值: {self.port}")
        if self.timeout <= 0:
            raise ValueError(f"超时时间必须大于 0，当前值: {self.timeout}")
        if self.max_retries < 0:
            raise ValueError(f"重试次数不能为负数，当前值: {self.max_retries}")


def get_web_ui_config() -> WebUIConfig:
    """获取Web UI配置"""
    try:
        host = os.environ.get("FEEDBACK_WEB_HOST", "0.0.0.0")
        port = int(os.environ.get("FEEDBACK_WEB_PORT", "8080"))
        timeout = int(os.environ.get("FEEDBACK_TIMEOUT", "30"))
        max_retries = int(os.environ.get("FEEDBACK_MAX_RETRIES", "3"))
        retry_delay = float(os.environ.get("FEEDBACK_RETRY_DELAY", "1.0"))

        config = WebUIConfig(
            host=host,
            port=port,
            timeout=timeout,
            max_retries=max_retries,
            retry_delay=retry_delay
        )
        logger.info(f"Web UI 配置加载成功: {host}:{port}")
        return config
    except (ValueError, TypeError) as e:
        logger.error(f"配置参数错误: {e}")
        raise ValueError(f"Web UI 配置错误: {e}")


def validate_input(prompt: str, predefined_options: Optional[list] = None) -> Tuple[str, list]:
    """验证输入参数"""
    # 验证 prompt
    if not isinstance(prompt, str):
        raise ValueError("prompt 必须是字符串类型")

    # 清理和验证 prompt
    cleaned_prompt = prompt.strip()
    if len(cleaned_prompt) > 10000:  # 限制长度
        logger.warning(f"prompt 长度过长 ({len(cleaned_prompt)} 字符)，将被截断")
        cleaned_prompt = cleaned_prompt[:10000] + "..."

    # 验证 predefined_options
    cleaned_options = []
    if predefined_options:
        if not isinstance(predefined_options, list):
            raise ValueError("predefined_options 必须是列表类型")

        for option in predefined_options:
            if not isinstance(option, str):
                logger.warning(f"跳过非字符串选项: {option}")
                continue
            cleaned_option = option.strip()
            if cleaned_option and len(cleaned_option) <= 500:  # 限制选项长度
                cleaned_options.append(cleaned_option)
            elif len(cleaned_option) > 500:
                logger.warning(f"选项过长被截断: {cleaned_option[:50]}...")
                cleaned_options.append(cleaned_option[:500] + "...")

    return cleaned_prompt, cleaned_options


def create_http_session(config: WebUIConfig) -> requests.Session:
    """创建配置了重试机制的 HTTP 会话"""
    session = requests.Session()

    # 配置重试策略
    retry_strategy = Retry(
        total=config.max_retries,
        backoff_factor=config.retry_delay,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["HEAD", "GET", "POST"]
    )

    adapter = HTTPAdapter(max_retries=retry_strategy)
    session.mount("http://", adapter)
    session.mount("https://", adapter)

    # 设置默认超时
    session.timeout = config.timeout

    return session


def is_web_service_running(host: str, port: int, timeout: float = 2.0) -> bool:
    """检查Web服务是否正在运行"""
    try:
        # 验证主机和端口
        if not (1 <= port <= 65535):
            logger.error(f"无效端口号: {port}")
            return False

        # 尝试连接到指定的主机和端口
        target_host = "localhost" if host == "0.0.0.0" else host

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(timeout)
            result = sock.connect_ex((target_host, port))
            is_running = result == 0

            if is_running:
                logger.debug(f"Web 服务运行中: {target_host}:{port}")
            else:
                logger.debug(f"Web 服务未运行: {target_host}:{port}")

            return is_running

    except socket.gaierror as e:
        logger.error(f"主机名解析失败 {host}: {e}")
        return False
    except Exception as e:
        logger.error(f"检查服务状态时出错: {e}")
        return False


def health_check_service(config: WebUIConfig) -> bool:
    """健康检查：验证服务是否正常响应"""
    if not is_web_service_running(config.host, config.port):
        return False

    try:
        session = create_http_session(config)
        target_host = "localhost" if config.host == "0.0.0.0" else config.host
        health_url = f"http://{target_host}:{config.port}/api/config"

        response = session.get(health_url, timeout=5)
        is_healthy = response.status_code == 200

        if is_healthy:
            logger.debug("服务健康检查通过")
        else:
            logger.warning(f"服务健康检查失败，状态码: {response.status_code}")

        return is_healthy

    except requests.exceptions.RequestException as e:
        logger.error(f"健康检查请求失败: {e}")
        return False
    except Exception as e:
        logger.error(f"健康检查时出现未知错误: {e}")
        return False


def start_web_service(config: WebUIConfig, script_dir: str) -> None:
    """启动Web服务 - 启动时为"无有效内容"状态"""
    web_ui_path = os.path.join(script_dir, "web_ui.py")

    # 验证 web_ui.py 文件是否存在
    if not os.path.exists(web_ui_path):
        raise FileNotFoundError(f"Web UI 脚本不存在: {web_ui_path}")

    # 检查服务是否已经在运行
    if health_check_service(config):
        logger.info(f"Web 服务已在运行: http://{config.host}:{config.port}")
        return

    # 启动Web服务，初始为空内容
    args = [
        sys.executable,
        "-u",
        web_ui_path,
        "--prompt",
        "",  # 启动时为空，符合"无有效内容"状态
        "--predefined-options",
        "",
        "--host",
        config.host,
        "--port",
        str(config.port),
    ]

    # 在后台启动服务
    try:
        logger.info(f"启动 Web 服务进程: {' '.join(args)}")
        process = subprocess.Popen(
            args,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            close_fds=True,
        )
        logger.info(f"Web 服务进程已启动，PID: {process.pid}")

    except FileNotFoundError as e:
        logger.error(f"Python 解释器或脚本文件未找到: {e}")
        raise Exception(f"无法启动 Web 服务，文件未找到: {e}")
    except PermissionError as e:
        logger.error(f"权限不足，无法启动服务: {e}")
        raise Exception(f"权限不足，无法启动 Web 服务: {e}")
    except Exception as e:
        logger.error(f"启动服务进程时出错: {e}")
        # 如果启动失败，再次检查服务是否已经在运行
        if health_check_service(config):
            logger.info("服务已经在运行，继续使用现有服务")
            return
        else:
            raise Exception(f"启动 Web 服务失败: {e}")

    # 等待服务启动并进行健康检查
    max_wait = 15  # 最多等待15秒
    check_interval = 0.5  # 每0.5秒检查一次

    for attempt in range(int(max_wait / check_interval)):
        if health_check_service(config):
            logger.info(f"🌐 Web服务已启动: http://{config.host}:{config.port}")
            return

        if attempt % 4 == 0:  # 每2秒记录一次等待状态
            logger.debug(f"等待服务启动... ({attempt * check_interval:.1f}s)")

        time.sleep(check_interval)

    # 最终检查
    if health_check_service(config):
        logger.info(f"🌐 Web 服务启动成功: http://{config.host}:{config.port}")
    else:
        raise Exception(f"Web 服务启动超时 ({max_wait}秒)，请检查端口 {config.port} 是否被占用")


def update_web_content(
    summary: str, predefined_options: Optional[list[str]], config: WebUIConfig
) -> None:
    """更新Web服务的内容"""
    # 验证输入
    cleaned_summary, cleaned_options = validate_input(summary, predefined_options)

    target_host = "localhost" if config.host == "0.0.0.0" else config.host
    url = f"http://{target_host}:{config.port}/api/update"

    data = {
        "prompt": cleaned_summary,
        "predefined_options": cleaned_options
    }

    session = create_http_session(config)

    try:
        logger.debug(f"更新 Web 内容: {url}")
        response = session.post(url, json=data, timeout=config.timeout)

        if response.status_code == 200:
            logger.info(f"📝 内容已更新: {cleaned_summary[:50]}...")

            # 验证更新是否成功
            try:
                result = response.json()
                if result.get("status") != "success":
                    logger.warning(f"更新响应状态异常: {result}")
            except ValueError:
                logger.warning("更新响应不是有效的 JSON 格式")

        elif response.status_code == 400:
            logger.error(f"更新请求参数错误: {response.text}")
            raise Exception(f"更新内容失败，请求参数错误: {response.text}")
        elif response.status_code == 404:
            logger.error("更新 API 端点不存在，可能服务未正确启动")
            raise Exception("更新 API 不可用，请检查服务状态")
        else:
            logger.error(f"更新内容失败，HTTP 状态码: {response.status_code}")
            raise Exception(f"更新内容失败，状态码: {response.status_code}")

    except requests.exceptions.Timeout:
        logger.error(f"更新内容超时 ({config.timeout}秒)")
        raise Exception(f"更新内容超时，请检查网络连接")
    except requests.exceptions.ConnectionError:
        logger.error(f"无法连接到 Web 服务: {url}")
        raise Exception(f"无法连接到 Web 服务，请确认服务正在运行")
    except requests.exceptions.RequestException as e:
        logger.error(f"更新内容时网络请求失败: {e}")
        raise Exception(f"更新内容失败: {e}")
    except Exception as e:
        logger.error(f"更新内容时出现未知错误: {e}")
        raise Exception(f"更新 Web 内容失败: {e}")


def wait_for_feedback(config: WebUIConfig, timeout: int = 300) -> Dict[str, str]:
    """等待用户提交反馈"""
    target_host = "localhost" if config.host == "0.0.0.0" else config.host
    config_url = f"http://{target_host}:{config.port}/api/config"
    feedback_url = f"http://{target_host}:{config.port}/api/feedback"

    session = create_http_session(config)
    start_time = time.time()
    check_interval = 2.0  # 检查间隔
    last_progress_time = start_time
    progress_interval = 30.0  # 进度报告间隔

    logger.info(f"⏳ 等待用户反馈... (超时: {timeout}秒)")

    # 首先获取当前状态
    last_has_content = True  # 默认假设有内容
    try:
        config_response = session.get(config_url, timeout=5)
        if config_response.status_code == 200:
            config_data = config_response.json()
            last_has_content = config_data.get("has_content", False)
            logger.debug(f"初始内容状态: {last_has_content}")
        else:
            logger.warning(f"获取初始状态失败，状态码: {config_response.status_code}")
    except requests.exceptions.RequestException as e:
        logger.warning(f"获取初始状态失败: {e}")

    consecutive_errors = 0
    max_consecutive_errors = 5

    while time.time() - start_time < timeout:
        current_time = time.time()
        elapsed_time = current_time - start_time

        # 定期报告进度
        if current_time - last_progress_time >= progress_interval:
            remaining_time = timeout - elapsed_time
            logger.info(f"⏳ 继续等待用户反馈... (剩余: {remaining_time:.0f}秒)")
            last_progress_time = current_time

        try:
            # 首先检查是否有反馈结果
            feedback_response = session.get(feedback_url, timeout=5)
            if feedback_response.status_code == 200:
                feedback_data = feedback_response.json()
                if (feedback_data.get("status") == "success" and
                    feedback_data.get("feedback")):
                    logger.info("✅ 收到用户反馈")
                    return feedback_data["feedback"]

            # 然后检查内容状态变化
            config_response = session.get(config_url, timeout=5)
            if config_response.status_code == 200:
                config_data = config_response.json()
                current_has_content = config_data.get("has_content", False)

                # 如果从有内容变为无内容，说明用户提交了反馈
                if last_has_content and not current_has_content:
                    logger.debug("检测到内容状态变化，尝试获取反馈")

                    # 再次尝试获取反馈内容
                    feedback_response = session.get(feedback_url, timeout=5)
                    if feedback_response.status_code == 200:
                        feedback_data = feedback_response.json()
                        if (feedback_data.get("status") == "success" and
                            feedback_data.get("feedback")):
                            logger.info("✅ 收到用户反馈")
                            return feedback_data["feedback"]

                    # 如果没有获取到具体反馈内容，返回默认结果
                    logger.info("✅ 收到用户反馈（无具体内容）")
                    return {"interactive_feedback": "用户已提交反馈"}

                last_has_content = current_has_content
                consecutive_errors = 0  # 重置错误计数
            else:
                logger.warning(f"获取配置状态失败，状态码: {config_response.status_code}")
                consecutive_errors += 1

        except requests.exceptions.Timeout:
            logger.warning("检查反馈状态超时")
            consecutive_errors += 1
        except requests.exceptions.ConnectionError:
            logger.warning("连接 Web 服务失败")
            consecutive_errors += 1
        except requests.exceptions.RequestException as e:
            logger.warning(f"检查反馈状态时网络错误: {e}")
            consecutive_errors += 1
        except Exception as e:
            logger.error(f"检查反馈状态时出现未知错误: {e}")
            consecutive_errors += 1

        # 如果连续错误过多，可能服务已经停止
        if consecutive_errors >= max_consecutive_errors:
            logger.error(f"连续 {consecutive_errors} 次检查失败，可能服务已停止")
            raise Exception("Web 服务连接失败，请检查服务状态")

        # 如果有错误，缩短等待时间
        sleep_time = check_interval if consecutive_errors == 0 else 1.0
        time.sleep(sleep_time)

    # 超时处理
    logger.error(f"等待用户反馈超时 ({timeout}秒)")
    raise Exception(f"等待用户反馈超时 ({timeout}秒)，请检查用户是否看到了反馈界面")


def launch_feedback_ui(
    summary: str, predefined_options: Optional[list[str]] = None
) -> Dict[str, str]:
    """启动反馈界面 - 使用Web服务工作流程"""
    try:
        # 验证输入参数
        cleaned_summary, cleaned_options = validate_input(summary, predefined_options)

        # 获取配置
        script_dir = os.path.dirname(os.path.abspath(__file__))
        config = get_web_ui_config()

        logger.info(f"启动反馈界面: {cleaned_summary[:100]}...")

        # 检查服务是否已经运行，如果没有则启动
        if not health_check_service(config):
            logger.info("Web 服务未运行，正在启动...")
            start_web_service(config, script_dir)
        else:
            logger.info("Web 服务已在运行，直接更新内容")

        # 传递消息和选项，在页面上显示（无论是第一次还是后续调用）
        update_web_content(cleaned_summary, cleaned_options, config)

        # 等待用户反馈
        result = wait_for_feedback(config)
        logger.info("用户反馈收集完成")
        return result

    except ValueError as e:
        logger.error(f"输入参数错误: {e}")
        raise Exception(f"参数验证失败: {e}")
    except FileNotFoundError as e:
        logger.error(f"文件未找到: {e}")
        raise Exception(f"必要文件缺失: {e}")
    except Exception as e:
        logger.error(f"启动反馈界面失败: {e}")
        raise Exception(f"反馈界面启动失败: {e}")


@mcp.tool()
def interactive_feedback(
    message: str = Field(description="The specific question for the user"),
    predefined_options: list = Field(
        default=None,
        description="Predefined options for the user to choose from (optional)",
    ),
) -> Dict[str, str]:
    """Request interactive feedback from the user

    Args:
        message: 向用户显示的问题或消息
        predefined_options: 可选的预定义选项列表

    Returns:
        包含用户反馈的字典

    Raises:
        Exception: 当反馈收集失败时
    """
    try:
        # 验证和清理输入
        if not isinstance(message, str):
            raise ValueError("message 参数必须是字符串类型")

        predefined_options_list = None
        if predefined_options is not None:
            if isinstance(predefined_options, list):
                predefined_options_list = predefined_options
            else:
                logger.warning(f"predefined_options 类型错误，期望 list，实际 {type(predefined_options)}")
                predefined_options_list = None

        logger.info(f"收到反馈请求: {message[:50]}...")
        result = launch_feedback_ui(message, predefined_options_list)
        logger.info("反馈请求处理完成")
        return result

    except Exception as e:
        logger.error(f"interactive_feedback 工具执行失败: {e}")
        # 返回错误信息而不是抛出异常，以便 MCP 客户端能够处理
        return {
            "interactive_feedback": f"反馈收集失败: {str(e)}",
            "error": True
        }


def main():
    """Main entry point for the AI Intervention Agent MCP server."""
    try:
        logger.info("启动 AI Intervention Agent MCP 服务器")
        mcp.run(transport="stdio")
    except KeyboardInterrupt:
        logger.info("收到中断信号，正在关闭服务器")
    except Exception as e:
        logger.error(f"服务器启动失败: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
