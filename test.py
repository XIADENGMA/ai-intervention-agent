#!/usr/bin/env python3
"""
AI Intervention Agent 智能介入代理测试工具

提供全面的功能测试套件，验证AI介入代理的各项功能是否正常工作。

## 功能概览

### 1. 配置管理测试
- 配置文件加载和验证
- 输入数据验证
- 异常配置处理

### 2. 服务健康检查
- 端口可用性检测
- Web服务运行状态
- API端点健康检查

### 3. 智能介入工作流程测试
- 服务启动和初始化
- 用户交互反馈收集
- 内容动态更新
- Markdown渲染验证

### 4. 多任务并发测试
- 多任务API端点验证
- 任务标签页UI验证
- 任务切换功能验证
- 并行任务创建和管理

## 主要特性

### 信号处理和资源清理
- 捕获 SIGINT 和 SIGTERM 信号
- 优雅关闭服务和清理资源
- atexit 注册的退出清理

### 智能端口管理
- 动态从配置获取端口
- 端口占用检测
- 自动查找可用端口

### 灵活的超时配置
- 可配置的线程等待超时
- 可配置的反馈超时
- 智能超时计算策略

### 详细的日志和反馈
- Emoji 增强的日志输出
- 测试进度实时显示
- 测试结果统计和摘要

## 使用方法

### 基本用法
- 直接运行：`python test.py`

### 高级用法
- 指定端口：`--port 8080`
- 指定主机：`--host 127.0.0.1`
- 指定线程等待超时（秒）：`--thread-timeout 600`
- 指定反馈超时（秒）：`--timeout 60`
- 启用详细日志：`--verbose`
- 组合使用：支持同时使用多个参数

## 命令行参数

- `--port, -p`: 指定测试使用的端口号
- `--host`: 指定测试使用的主机地址
- `--timeout`: 指定反馈超时时间（秒）
- `--thread-timeout`: 指定线程等待超时时间（秒）
- `--verbose, -v`: 显示详细日志信息
- `--help, -h`: 显示帮助信息

## 测试流程

1. **环境初始化**
   - 解析命令行参数
   - 验证参数合理性
   - 设置测试环境
   - 注册信号处理器

2. **配置验证**
   - 加载配置文件
   - 验证配置项
   - 测试输入验证

3. **服务健康检查**
   - 检查端口状态
   - 验证服务运行
   - 健康检查API

4. **智能介入工作流程**
   - 启动介入服务
   - 等待用户交互
   - 验证内容更新
   - 检查渲染效果

5. **并行任务测试**
   - 创建多个并发任务
   - 验证任务标签页
   - 测试任务切换
   - 检查独立倒计时

6. **结果统计**
   - 汇总测试结果
   - 显示通过率
   - 提供使用提示

## 测试结果

测试完成后会显示：
- 每个测试的通过/失败状态
- 总体通过率
- 详细的错误信息（如有）
- 使用提示和建议

## 注意事项

- 测试需要Web浏览器交互
- 某些测试有较长的超时时间
- 可以使用Ctrl+C安全中断测试
- 测试过程中会自动清理资源
- 配置参数仅在内存中修改，不会写入文件

## 依赖项

- Python 3.11+
- requests (HTTP请求)
- server.py (AI介入代理服务)
- enhanced_logging (可选，增强日志)
- config_manager (配置管理)

## 作者和维护

此测试工具是 AI Intervention Agent 项目的一部分。
详细信息请参考项目README。
"""

import argparse
import atexit
import json
import signal
import sys
import threading
import time
from pathlib import Path
from typing import Any

# 添加当前目录到Python路径
sys.path.insert(0, str(Path(__file__).resolve().parent))

# 初始化增强日志系统
test_logger: Any
try:
    from enhanced_logging import EnhancedLogger

    test_logger = EnhancedLogger("test")
    ENHANCED_LOGGING_AVAILABLE = True
except ImportError:
    import logging

    test_logger = logging.getLogger("test")
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    ENHANCED_LOGGING_AVAILABLE = False


# 测试配置常量
class TestConfig:
    """测试配置常量类

    集中管理测试相关的所有硬编码常量，便于维护和调整。

    ## 设计原则

    - 所有常量集中定义，避免魔法数字
    - 使用类属性而非实例属性（无需实例化）
    - 清晰的命名和分类
    - 详细的注释说明用途

    ## 常量分类

    ### 1. 超时配置（秒）
    控制各种等待和超时的时间限制

    ### 2. 反馈超时计算参数
    用于动态计算反馈超时时间

    ### 3. 网络配置
    API端点路径定义

    ### 4. 端口配置
    端口号范围和查找策略

    ### 5. 并行任务配置
    并发任务的创建和管理参数

    ## 使用方式

    - 直接访问类属性（无需实例化）
    - 示例：访问 `TestConfig.DEFAULT_THREAD_TIMEOUT` 获取默认超时
    - 示例：访问 `TestConfig.API_CONFIG_PATH` 获取API路径

    ## 修改建议

    - 修改常量值时应同步更新注释
    - 超时值应考虑实际网络延迟
    - 端口范围应符合操作系统限制
    - 并行任务数不宜过多（避免资源耗尽）

    属性:
        DEFAULT_THREAD_TIMEOUT (int): 默认线程等待超时（600秒=10分钟）
        SERVICE_STARTUP_WAIT_TIME (int): 服务启动等待时间（5秒）
        HTTP_REQUEST_TIMEOUT (int): HTTP请求超时（5秒）
        PARALLEL_TASK_TIMEOUT (int): 并行任务超时（600秒）
        PARALLEL_THREAD_JOIN_TIMEOUT (int): 并行任务线程等待超时（650秒）
        PORT_CHECK_TIMEOUT (int): 端口检查超时（1秒）
        FEEDBACK_TIMEOUT_BUFFER (int): 反馈超时缓冲时间（10秒）
        FEEDBACK_TIMEOUT_MIN (int): 反馈超时最小值（30秒）
        FEEDBACK_TIMEOUT_THRESHOLD (int): 应用缓冲的阈值（40秒）
        API_CONFIG_PATH (str): 配置API端点路径
        API_TASKS_PATH (str): 任务API端点路径
        API_HEALTH_PATH (str): 健康检查API端点路径
        PORT_MIN (int): 最小端口号（1）
        PORT_MAX (int): 最大端口号（65535）
        PORT_SEARCH_MAX_ATTEMPTS (int): 查找可用端口的最大尝试次数（10）
        PARALLEL_TASKS_COUNT (int): 并行任务数量（3）
        PARALLEL_TASK_START_DELAY (float): 并行任务启动间隔秒数（0.5）
    """

    # 超时配置（秒）
    DEFAULT_THREAD_TIMEOUT = 600  # 默认线程等待超时时间
    SERVICE_STARTUP_WAIT_TIME = 2  # 服务启动初始等待时间（轮询前）
    HTTP_REQUEST_TIMEOUT = 5  # HTTP 请求超时时间
    PARALLEL_TASK_TIMEOUT = 600  # 并行任务超时时间
    PARALLEL_THREAD_JOIN_TIMEOUT = 650  # 并行任务线程等待超时时间
    PORT_CHECK_TIMEOUT = 1  # 端口可用性检查超时时间

    # 反馈超时计算参数
    FEEDBACK_TIMEOUT_BUFFER = 10  # 反馈超时缓冲时间（从线程超时减去）
    FEEDBACK_TIMEOUT_MIN = 30  # 反馈超时最小值
    FEEDBACK_TIMEOUT_THRESHOLD = 40  # 应用缓冲的阈值

    # 网络配置
    API_CONFIG_PATH = "/api/config"  # 配置 API 端点
    API_TASKS_PATH = "/api/tasks"  # 任务 API 端点
    API_HEALTH_PATH = "/api/health"  # 健康检查 API 端点

    # 端口配置
    PORT_MIN = 1  # 最小端口号
    PORT_MAX = 65535  # 最大端口号
    PORT_SEARCH_MAX_ATTEMPTS = 10  # 查找可用端口的最大尝试次数

    # 并行任务配置
    PARALLEL_TASKS_COUNT = 3  # 并行任务数量
    PARALLEL_TASK_START_DELAY = 0.5  # 并行任务启动间隔（秒）


class SignalHandlerManager:
    """信号处理器管理类

    使用单例模式全局管理信号处理器的注册状态，防止重复注册。

    ## 设计目标

    1. **单例模式**：全局唯一实例，统一管理注册状态
    2. **重复防护**：确保信号处理器只注册一次
    3. **简洁设计**：最小化状态管理复杂度

    ## 使用场景

    - 程序启动时注册信号处理器（SIGINT、SIGTERM等）
    - 避免多次注册导致的重复处理
    - 测试环境中检查注册状态

    ## 使用场景

    - 获取单例实例并检查是否已注册
    - 注册信号处理器前检查重复
    - 标记注册状态防止重复注册

    ## 注意事项

    - 不提供线程安全保证（假设在单线程初始化阶段使用）
    - 适用于简单的注册状态管理
    - 不负责实际的信号处理逻辑

    属性:
        _instance (SignalHandlerManager 或 None): 单例实例（类属性）
        _cleanup_registered (bool): 信号处理器是否已注册（类属性）
    """

    _instance = None
    _cleanup_registered = False

    def __new__(cls):
        """单例模式实现

        确保全局只有一个 SignalHandlerManager 实例。

        返回:
            SignalHandlerManager: 全局唯一的实例

        ## 实现说明

        - 简单检查：如果实例不存在则创建，否则返回现有实例
        - 非线程安全：假设在单线程环境下初始化
        - 适用于简单场景

        ## 使用说明

        - 多次调用返回相同实例
        - 实例比较时使用 `is` 操作符判断相等
        """
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    @classmethod
    def is_registered(cls):
        """检查信号处理器是否已注册

        返回:
            bool: True 表示已注册，False 表示未注册

        ## 使用场景

        - 注册信号处理器前检查避免重复注册
        - 判断是否需要执行注册逻辑

        ## 注意事项

        - 类方法，无需实例化即可调用
        - 返回全局注册状态（非实例状态）
        """
        return cls._cleanup_registered

    @classmethod
    def mark_registered(cls):
        """标记信号处理器已注册

        设置全局注册标志为 True，表示信号处理器已注册。

        ## 使用场景

        - 成功注册信号处理器后调用此方法
        - 标记注册状态，防止重复注册

        ## 注意事项

        - 类方法，无需实例化即可调用
        - 操作是不可逆的（没有 unregister 方法）
        - 应该在确认注册成功后调用
        """
        cls._cleanup_registered = True


class TestLogger:
    """测试日志工具类

    统一管理测试过程中的日志输出，提供友好的emoji和多级别日志记录。

    ## 设计目标

    1. **视觉友好**：使用 emoji 增强可读性
    2. **双重输出**：同时输出到控制台和日志文件
    3. **灵活配置**：支持自定义 emoji 和日志级别
    4. **降级兼容**：在增强日志不可用时自动降级

    ## 支持的日志级别

    - `info`: 一般信息（ℹ️）
    - `success`: 成功消息（✅）
    - `warning`: 警告信息（⚠️）
    - `error`: 错误信息（❌）
    - `debug`: 调试信息（🔍）
    - `config`: 配置信息（🔧）
    - `network`: 网络信息（🌐）
    - `timing`: 时间信息（⏱️）
    - `start`: 启动信息（🚀）
    - `stop`: 停止信息（🛑）
    - `cleanup`: 清理信息（🧹）
    - `bye`: 结束信息（👋）

    ## 使用场景

    - 基础日志：记录测试开始、结束等信息
    - 自定义 emoji：使用自定义 emoji 增强可读性
    - 异常记录：记录异常信息和堆栈跟踪

    ## 输出行为

    - **控制台**：输出 emoji + 消息（用户友好）
    - **日志文件**：
        - 增强日志可用：仅消息（避免重复 emoji）
        - 标准日志：emoji + 消息（保持一致性）

    属性:
        DEFAULT_EMOJIS (dict): 默认的 emoji 映射表
    """

    DEFAULT_EMOJIS = {
        "info": "ℹ️",
        "success": "✅",
        "warning": "⚠️",
        "error": "❌",
        "debug": "🔍",
        "config": "🔧",
        "network": "🌐",
        "timing": "⏱️",
        "start": "🚀",
        "stop": "🛑",
        "cleanup": "🧹",
        "bye": "👋",
    }

    @staticmethod
    def log(message: str, level: str = "info", emoji: str | None = None):
        """统一的日志输出函数

        参数:
            message (str): 日志消息内容
            level (str, optional): 日志级别，默认为 "info"。
                支持: info/success/warning/error/debug/config/network/timing/start/stop/cleanup/bye
            emoji (str, optional): 自定义 emoji，为 None 时使用默认 emoji

        ## 处理流程

        1. **Emoji 选择**：优先使用自定义 emoji，否则从 DEFAULT_EMOJIS 查找
        2. **消息构建**：emoji + 空格 + 消息
        3. **控制台输出**：print 完整消息（含 emoji）
        4. **日志记录**：根据增强日志可用性决定输出格式

        ## 输出行为

        - 控制台：始终输出 `emoji + message`
        - 日志文件：
            - 增强日志：仅 `message`（避免重复）
            - 标准日志：`emoji + message`（保持一致）

        ## 使用说明

        - 默认级别和 emoji：使用默认 info 级别和 ℹ️ emoji
        - 指定级别：传入 level 参数指定日志级别
        - 自定义 emoji：传入自定义 emoji 覆盖默认值
        - 无 emoji：传入空字符串取消 emoji 前缀

        ## 注意事项

        - level 不区分大小写，但建议使用小写
        - 未知 level 自动降级为 "info"
        - emoji 为空字符串时不添加前缀
        """
        # 获取emoji（优先使用自定义，然后默认，最后为空）
        if emoji is None:
            emoji = TestLogger.DEFAULT_EMOJIS.get(level, "")

        # 构建完整消息
        full_message = f"{emoji} {message}" if emoji else message

        # 输出到控制台（保持原有的用户体验）
        print(full_message)

        # 同时记录到日志系统
        log_level = level if level in ("warning", "error", "debug") else "info"
        if ENHANCED_LOGGING_AVAILABLE:
            getattr(test_logger, log_level.lower())(message)
        else:
            # 降级到标准日志
            getattr(test_logger, log_level.lower())(full_message)

    @staticmethod
    def log_exception(
        message: str, exc: Exception | None = None, include_traceback: bool = False
    ):
        """记录异常信息

        专门用于记录异常和错误，支持自动提取异常类型和堆栈跟踪。

        参数:
            message (str): 错误描述消息
            exc (Exception, optional): 异常对象，为 None 时仅记录 message
            include_traceback (bool, optional): 是否包含完整的堆栈跟踪，默认 False

        ## 处理流程

        1. **消息构建**：
           - 有异常对象：`message: ExceptionType - exception_str`
           - 无异常对象：`message`
        2. **控制台输出**：使用 error 级别（❌ emoji）
        3. **堆栈跟踪**：如果 `include_traceback=True`，额外记录完整堆栈

        ## 使用场景

        - 仅记录错误消息：不传入异常对象
        - 记录异常对象（不含堆栈）：传入异常对象但不启用 include_traceback
        - 记录异常 + 完整堆栈：传入异常对象并启用 include_traceback

        ## 输出说明

        - 控制台：输出错误消息（含异常类型和消息）
        - 日志文件：当启用 include_traceback 时输出完整堆栈跟踪

        ## 注意事项

        - 堆栈跟踪仅记录到日志文件，不输出到控制台
        - 建议在调试时启用 `include_traceback`
        - 生产环境可关闭堆栈跟踪以减少日志量
        """
        error_msg = message
        if exc:
            error_msg = f"{message}: {type(exc).__name__} - {str(exc)}"

        TestLogger.log(error_msg, "error")

        # 如果需要完整堆栈跟踪，记录到日志系统
        if include_traceback and exc:
            import traceback

            if ENHANCED_LOGGING_AVAILABLE:
                test_logger.error(traceback.format_exc())
            else:
                test_logger.error(traceback.format_exc())


# 便捷函数（保持向后兼容）
def log_info(message: str, emoji: str | None = None):
    """记录信息级别日志

    参数:
        message (str): 日志消息
        emoji (str, optional): 自定义 emoji，默认 ℹ️

    ## 使用说明

    - 记录一般信息消息
    - 可选自定义 emoji
    """
    TestLogger.log(message, "info", emoji)


def log_success(message: str, emoji: str | None = None):
    """记录成功信息

    参数:
        message (str): 成功消息
        emoji (str, optional): 自定义 emoji，默认 ✅

    ## 使用说明

    - 记录成功完成的操作
    - 默认使用 ✅ emoji
    """
    TestLogger.log(message, "success", emoji or "✅")


def log_warning(message: str, emoji: str | None = None):
    """记录警告信息

    参数:
        message (str): 警告消息
        emoji (str, optional): 自定义 emoji，默认 ⚠️

    ## 使用说明

    - 记录警告级别的消息
    - 用于非致命问题提示
    """
    TestLogger.log(message, "warning", emoji)


def log_error(message: str, emoji: str | None = None):
    """记录错误信息

    参数:
        message (str): 错误消息
        emoji (str, optional): 自定义 emoji，默认 ❌

    ## 使用说明

    - 记录错误级别的消息
    - 用于操作失败或异常情况
    """
    TestLogger.log(message, "error", emoji)


def log_debug(message: str, emoji: str | None = None):
    """记录调试信息

    参数:
        message (str): 调试消息
        emoji (str, optional): 自定义 emoji，默认 🔍

    ## 使用说明

    - 记录调试级别的详细信息
    - 用于开发和排查问题
    """
    TestLogger.log(message, "debug", emoji)


def setup_signal_handlers():
    """设置信号处理器

    注册 SIGINT/SIGTERM 信号处理器和 atexit 清理机制，确保程序安全退出。

    ## 注册内容

    1. **信号处理器**：捕获 SIGINT（Ctrl+C）和 SIGTERM
    2. **退出回调**：使用 atexit 注册正常退出时的清理函数
    3. **重复防护**：通过 SignalHandlerManager 防止重复注册

    ## 处理流程

    - 收到信号：打印警告 → 清理服务 → 打印退出消息 → sys.exit(0)
    - 正常退出：打印清理消息 → 清理服务

    ## 使用说明

    - 在测试开始前调用一次
    - 后续可以放心使用 Ctrl+C 中断

    ## 清理机制

    - **信号触发**：用户按 Ctrl+C 或系统发送 SIGTERM
    - **正常退出**：程序执行完毕或调用 sys.exit()
    - **清理服务**：关闭 Web UI、停止线程、释放资源

    ## 跨平台兼容性

    - 使用 `hasattr(signal, "SIGINT")` 检查信号是否可用
    - Windows 不支持 SIGTERM，会自动跳过

    ## 注意事项

    - 信号处理器应该快速执行（避免耗时操作）
    - 清理逻辑应该是幂等的（多次调用安全）
    - 避免在信号处理器中抛出异常
    """
    handler_manager = SignalHandlerManager()

    if handler_manager.is_registered():
        return

    def signal_handler(signum, frame):
        """信号处理器

        参数:
            signum (int): 信号编号（SIGINT=2, SIGTERM=15）
            frame: 堆栈帧对象（未使用）
        """
        del frame  # 未使用的参数
        log_warning(f"收到中断信号 {signum}，正在清理资源...", "🛑")
        cleanup_services()
        log_info("程序已安全退出", "👋")
        sys.exit(0)

    def cleanup_on_exit():
        """程序退出时的清理函数

        通过 atexit 注册，在程序正常退出时自动调用。
        """
        log_info("程序退出，正在清理资源...", "🧹")
        cleanup_services()

    # 注册信号处理器
    if hasattr(signal, "SIGINT"):
        signal.signal(signal.SIGINT, signal_handler)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, signal_handler)

    # 注册退出清理函数
    atexit.register(cleanup_on_exit)

    handler_manager.mark_registered()
    log_debug("信号处理器和清理机制已注册", "🔧")


def cleanup_services():
    """清理所有服务进程

    关闭 Web UI、停止线程、释放资源。

    ## 清理内容

    1. 调用 `server.cleanup_services()` 关闭 Web UI 服务
    2. 停止所有活跃线程
    3. 释放网络端口和文件句柄

    ## 异常处理

    - 清理失败时记录错误日志但不抛出异常
    - 确保清理过程不会导致程序崩溃

    ## 使用说明

    - 手动清理：直接调用此函数
    - 自动清理：通过信号处理器或 atexit 自动调用

    ## 注意事项

    - 幂等操作：多次调用安全
    - 快速执行：避免耗时操作
    - 异常隔离：不影响其他清理步骤
    """
    try:
        from server import cleanup_services as server_cleanup

        server_cleanup()
        log_debug("服务清理完成")
    except Exception as e:
        TestLogger.log_exception("清理服务时出错", e, include_traceback=False)


def format_feedback_result(result):
    """格式化反馈结果用于显示

    保留 API 返回的所有字段，仅对 images 字段的 data 内容进行截断。

    参数:
        result: 反馈结果对象（通常是字典）

    返回:
        dict 或 str: 格式化后的结果

    ## 处理逻辑

    1. **非字典类型**：直接转为字符串返回
    2. **字典类型**：
       - 保留 **所有字段**（与 API 返回一致）
       - 仅截断 `images[].data` 字段（限制为 50 个字符 + "..."）
       - 其他字段原样输出

    ## 使用说明

    - 传入反馈结果字典
    - 自动截断 images 数据字段（避免日志过长）
    - 返回格式化后的完整结果

    ## 注意事项

    - 仅截断 images.data 显示，不修改原始数据
    - 其他字段原样输出，不过滤
    - 适用于日志记录和调试输出
    """
    if not isinstance(result, dict):
        return str(result)

    # ✅ 修复：保留所有字段，而不是选择性输出
    formatted_result = result.copy()

    # 仅处理图片数据，限制 data 字段长度
    if "images" in formatted_result and formatted_result["images"]:
        formatted_images = []
        for img in formatted_result["images"]:
            if isinstance(img, dict):
                formatted_img = img.copy()
                # 限制 data 字段显示长度为 50 个字符
                if "data" in formatted_img and len(formatted_img["data"]) > 50:
                    formatted_img["data"] = formatted_img["data"][:50] + "..."
                formatted_images.append(formatted_img)
            else:
                formatted_images.append(img)
        formatted_result["images"] = formatted_images

    return formatted_result


def format_mcp_return_content(feedback_result):
    """将 Web UI 的反馈结果转换为“最终 MCP 返回”的 ContentBlock 列表（可 JSON 序列化展示）"""
    try:
        from mcp.types import ImageContent, TextContent

        from server import parse_structured_response
    except Exception:
        return None

    try:
        content_blocks = parse_structured_response(feedback_result)
    except Exception:
        return None

    formatted = []
    for block in content_blocks:
        if isinstance(block, TextContent):
            formatted.append({"type": "text", "text": block.text})
        elif isinstance(block, ImageContent):
            data = block.data
            if isinstance(data, str) and len(data) > 80:
                data = data[:80] + "..."
            formatted.append(
                {"type": "image", "mimeType": block.mimeType, "data": data}
            )
        else:
            formatted.append({"type": "unknown", "repr": repr(block)})

    return formatted


def check_service(url, timeout=None):
    """检查服务是否可用

    发送 HTTP GET 请求检查服务健康状态。

    参数:
        url (str): 服务 URL（如 http://localhost:8080/api/health）
        timeout (int, optional): 请求超时时间（秒），默认使用 TestConfig.HTTP_REQUEST_TIMEOUT

    返回:
        bool: True 表示服务可用（HTTP 200），False 表示不可用或异常

    ## 检查逻辑

    1. 发送 GET 请求到指定 URL
    2. 检查响应状态码是否为 200
    3. 捕获所有异常并返回 False

    ## 使用说明

    - 等待服务启动：循环调用直到返回 True
    - 健康检查：调用并检查返回值

    ## 异常处理

    - 连接失败：返回 False
    - 超时：返回 False
    - 非 200 状态码：返回 False
    - 调试模式会记录异常详情

    ## 注意事项

    - 仅检查 HTTP 200 状态码
    - 不解析响应内容
    - 适用于简单的健康检查
    """
    if timeout is None:
        timeout = TestConfig.HTTP_REQUEST_TIMEOUT
    try:
        import requests

        response = requests.get(url, timeout=timeout)
        return response.status_code == 200
    except Exception as e:
        log_debug(f"服务检查失败 ({url}): {type(e).__name__} - {str(e)}")
        return False


def test_config_validation():
    """测试配置验证功能

    验证配置加载和输入验证逻辑的正确性。

    返回:
        bool: 测试是否通过

    ## 测试内容

    1. **配置加载**：验证 `get_web_ui_config()` 返回有效配置
    2. **输入验证**：验证 `validate_input()` 正确处理正常和异常输入
    3. **异常处理**：验证空输入的处理逻辑

    ## 使用说明

    - 调用函数执行配置验证测试
    - 返回 True 表示测试通过
    """
    log_info("测试配置验证...", "🔧")

    try:
        from server import get_web_ui_config, validate_input

        # 测试正常配置
        config, auto_resubmit_timeout = get_web_ui_config()
        log_success(
            f"配置加载成功: {config.host}:{config.port}, 自动重新调用超时: {auto_resubmit_timeout}秒"
        )

        # 测试输入验证
        prompt, options = validate_input("测试消息", ["选项1", "选项2"])
        log_success(
            f"输入验证成功: prompt='{prompt[:20]}...', options={len(options)}个"
        )

        # 测试异常输入
        try:
            validate_input("", None)
            log_success("空输入处理正常")
        except Exception as e:
            log_warning(f"空输入处理异常: {e}")

        return True

    except Exception as e:
        TestLogger.log_exception("配置验证测试失败", e, include_traceback=True)
        return False


def test_service_health():
    """测试服务健康检查

    验证服务的端口检查和健康检查功能。

    返回:
        bool: 测试是否通过

    ## 测试内容

    1. **端口检查**：验证 `is_web_service_running()` 正确检测端口状态
    2. **健康检查**：验证 `health_check_service()` 正确检测服务健康状态

    ## 使用说明

    - 调用函数执行服务健康检查测试
    - 返回 True 表示测试通过

    ## 注意事项

    - 如果服务未运行，跳过健康检查
    - 端口检查和健康检查是两个独立的测试
    """
    log_info("测试服务健康检查...", "🏥")

    try:
        from server import (
            get_web_ui_config,
            health_check_service,
            is_web_service_running,
        )

        config, auto_resubmit_timeout = get_web_ui_config()

        # 测试端口检查
        is_running = is_web_service_running(config.host, config.port)
        log_success(f"端口检查完成: {'运行中' if is_running else '未运行'}")

        # 测试健康检查
        if is_running:
            is_healthy = health_check_service(config)
            log_success(f"健康检查完成: {'健康' if is_healthy else '不健康'}")
        else:
            log_info("服务未运行，跳过健康检查")

        return True

    except Exception as e:
        TestLogger.log_exception("服务健康检查测试失败", e, include_traceback=True)
        return False


def _calculate_feedback_timeout(timeout):
    """计算反馈超时时间

    根据线程等待超时时间计算合理的反馈超时值。

    参数:
        timeout (int): 线程等待超时时间（秒），0 表示无限等待

    返回:
        int: 反馈超时时间（秒）

    ## 计算规则

    1. **无限等待**（timeout=0）：返回 0
    2. **大于阈值**（timeout > FEEDBACK_TIMEOUT_THRESHOLD）：
       返回 `max(timeout - FEEDBACK_TIMEOUT_BUFFER, FEEDBACK_TIMEOUT_MIN)`
    3. **小于等于阈值**：直接返回 timeout

    ## 配置参数

    - `FEEDBACK_TIMEOUT_BUFFER`: 缓冲时间（默认 10 秒）
    - `FEEDBACK_TIMEOUT_MIN`: 最小超时（默认 30 秒）
    - `FEEDBACK_TIMEOUT_THRESHOLD`: 应用缓冲的阈值（默认 40 秒）

    ## 计算说明

    - timeout=0：返回 0（无限等待）
    - timeout≤阈值：直接返回 timeout
    - timeout>阈值：返回 max(timeout-缓冲, 最小超时)

    ## 设计目的

    - 为后端预留缓冲时间处理结果
    - 避免前端超时而后端仍在处理
    - 确保最小超时时间的合理性
    """
    if timeout == 0:
        log_info("线程等待超时时间: 无限等待", "⏱️")
        return 0
    else:
        log_info(f"线程等待超时时间: {timeout}秒", "⏱️")
        buffer = TestConfig.FEEDBACK_TIMEOUT_BUFFER
        min_timeout = TestConfig.FEEDBACK_TIMEOUT_MIN
        threshold = TestConfig.FEEDBACK_TIMEOUT_THRESHOLD
        return max(timeout - buffer, min_timeout) if timeout > threshold else timeout


def _create_first_task_content():
    """生成第一个任务的内容

    返回欢迎消息和初始选项。

    返回:
        tuple[str, list[str]]: (prompt, options) 元组

    ## 内容说明

    - **prompt**: 包含 AI Intervention Agent 的介绍和功能说明
    - **options**: 用户可选的操作选项

    ## 使用说明

    - 调用函数获取欢迎消息和选项
    - 用于第一次交互
    """
    prompt = """
        # 你好，我是AI Intervention Agent
**一个让用户能够实时控制 AI 执行过程的 MCP 工具。**

支持`Cursor`、`VS Code`、`Claude Code`、`Augment`、`Windsurf`、`Trae`等 AI 工具。"""
    options = [
        "🔄 继续了解",
        "✅ 立刻开始",
    ]
    return prompt, options


def _create_second_task_content():
    """生成第二个任务的复杂 Markdown 内容

    返回包含高级 Markdown 特性的测试内容。

    返回:
        tuple[str, list[str]]: (prompt, options) 元组

    ## 内容特性

    测试内容包含以下 Markdown 元素：
    - 表格渲染
    - 任务列表
    - 文本格式（粗体、斜体、删除线）
    - 代码块（带语法高亮）
    - 引用块
    - 数学公式（如果支持）
    - 链接

    ## 使用说明

    - 调用函数获取复杂 Markdown 测试内容
    - 用于第二次交互和渲染测试

    ## 注意事项

    - 用于验证 Markdown 渲染的完整性
    - 适合作为 UI 测试的参考内容
    """
    prompt = """# 🎉 内容已更新！- 第二次调用

## 更新内容验证

恭喜！第一次测试已完成。现在进行 **内容动态更新** 测试。

### 新增功能测试

#### 1. 表格渲染测试
| 功能 | 状态 | 备注 |
|------|------|------|
| 服务启动 | ✅ 完成 | 第一次测试通过 |
| Markdown渲染 | 🧪 测试中 | 当前正在验证 |
| 内容更新 | 🔄 进行中 | 动态更新功能 |

#### 2. 任务列表测试
**已完成任务：**
* ✅ 服务启动验证
* ✅ 基础渲染测试
* ✅ 用户交互测试

**进行中任务：**
* 🔄 高级渲染测试
* 🔄 内容更新验证

**待完成任务：**
* ⏳ 性能测试
* ⏳ 错误处理测试

#### 3. 文本格式测试
支持的 Markdown 元素：
- **粗体文本**
- *斜体文本*
- `行内代码`
- ~~删除线~~
- [链接示例](https://example.com)

#### 4. 引用和高级代码块
> 💡 **提示**: 这是一个引用块，用于显示重要信息。
>
> 支持多行引用内容，可以包含 **格式化文本** 和 `代码`。

```javascript
/**
 * AI Intervention Agent - 内容更新模块
 * 用于动态更新页面内容和收集用户反馈
 */
class ContentUpdater {
    constructor(config) {
        this.config = config;
        this.updateCount = 0;
    }

    /**
     * 更新页面内容
     * @param {string} newContent - 新的内容
     * @param {Array} options - 用户选项
     * @returns {Promise<Object>} 更新结果
     */
    async updateContent(newContent, options) {
        try {
            this.updateCount++;
            console.log(`第 ${this.updateCount} 次内容更新`);

            // 模拟异步更新
            await new Promise(resolve => setTimeout(resolve, 100));

            return {
                success: true,
                content: newContent,
                options: options,
                timestamp: new Date().toISOString(),
                updateId: this.updateCount
            };
        } catch (error) {
            console.error("内容更新失败:", error);
            return { success: false, error: error.message };
        }
    }
}

// 使用示例
const updater = new ContentUpdater({ debug: true });
updater.updateContent("测试内容", ["选项1", "选项2"])
    .then(result => console.log("更新结果:", result));
```

#### 5. 数学公式测试（如果支持）
内联公式：$E = mc^2$

块级公式：
$$
\\sum_{i=1}^{n} x_i = x_1 + x_2 + \\cdots + x_n
$$

---

### 🎯 最终测试
请选择一个选项来完成测试流程："""
    options = ["🎉 内容更新成功", "✅ 测试完成"]
    return prompt, options


def _launch_task_in_thread(prompt, options, feedback_timeout, task_id=None):
    """在独立线程中启动任务

    ⚠️ 注意：task_id 参数已废弃，系统会自动生成唯一ID

    参数:
        prompt: 任务提示内容
        options: 用户选项列表
        feedback_timeout: 反馈超时时间（秒）
        task_id: （已废弃）任务ID，此参数将被忽略

    返回:
        tuple: (thread, result_container) 元组
            - thread: 线程对象
            - result_container: 字典，包含 'result' 键用于存储结果
    """
    from server import launch_feedback_ui

    result_container = {"result": None}

    def run_task():
        try:
            # task_id 参数已废弃，系统会自动生成唯一ID
            result_container["result"] = launch_feedback_ui(
                prompt,
                options,
                task_id=task_id,  # 此参数将被忽略
                timeout=feedback_timeout,
            )
        except Exception as e:
            TestLogger.log_exception("任务执行失败", e, include_traceback=True)

    thread = threading.Thread(target=run_task)
    thread.start()

    return thread, result_container


def _wait_for_service_startup(service_url, port, wait_time=None, max_wait=None):
    """等待 Web 服务启动并验证可用性（使用轮询机制）

    参数:
        service_url: 服务健康检查URL
        port: 服务端口号
        wait_time: 初始等待时间（秒），默认使用 TestConfig.SERVICE_STARTUP_WAIT_TIME
        max_wait: 最大等待时间（秒），默认 15 秒

    返回:
        bool: 服务是否成功启动

    改进说明:
        使用轮询机制而非单次检查，与 server.py 中的 start_web_service 逻辑一致。
        每 0.5 秒检查一次服务状态，最多等待 max_wait 秒。
    """
    if wait_time is None:
        wait_time = TestConfig.SERVICE_STARTUP_WAIT_TIME
    if max_wait is None:
        max_wait = 15  # 最大等待 15 秒，与 server.py 保持一致

    log_info("等待服务启动...", "⏳")

    # 初始等待，给服务一些启动时间
    time.sleep(wait_time)

    # 使用轮询机制检查服务状态
    check_interval = 0.5  # 每 0.5 秒检查一次
    elapsed = wait_time
    last_log_time = 0

    while elapsed < max_wait:
        if check_service(service_url):
            log_success("服务启动成功，请在浏览器中提交反馈")
            log_info(f"浏览器地址: http://localhost:{port}", "🌐")
            return True

        # 每 2 秒记录一次等待状态
        if elapsed - last_log_time >= 2:
            log_debug(f"等待服务启动... ({elapsed:.1f}s/{max_wait}s)")
            last_log_time = elapsed

        time.sleep(check_interval)
        elapsed += check_interval

    # 最终检查
    if check_service(service_url):
        log_success("服务启动成功，请在浏览器中提交反馈")
        log_info(f"浏览器地址: http://localhost:{port}", "🌐")
        return True

    log_error(f"服务启动失败（等待超时 {max_wait} 秒）")
    return False


def test_persistent_workflow(timeout=None):
    """测试智能介入工作流程

    参数:
        timeout: 线程等待超时时间（秒），0表示无限等待，None使用默认值

    返回:
        bool: 测试是否通过
    """
    if timeout is None:
        timeout = TestConfig.DEFAULT_THREAD_TIMEOUT

    log_info("测试智能介入工作流程...", "🔄")

    # 计算反馈超时时间
    feedback_timeout = _calculate_feedback_timeout(timeout)

    try:
        from server import get_web_ui_config, launch_feedback_ui

        config, auto_resubmit_timeout = get_web_ui_config()
        service_url = f"http://localhost:{config.port}{TestConfig.API_CONFIG_PATH}"

        # 第一次调用 - 启动服务
        log_info("启动介入服务...", "🚀")
        prompt1, options1 = _create_first_task_content()

        thread1, result_container1 = _launch_task_in_thread(
            prompt1, options1, feedback_timeout
        )

        # 等待服务启动并检查
        if not _wait_for_service_startup(service_url, config.port):
            return False

        # 等待第一个任务完成
        if timeout == 0:
            thread1.join()  # 无限等待
        else:
            thread1.join(timeout=timeout)

        result1 = result_container1["result"]
        if result1:
            formatted_result1 = format_feedback_result(result1)
            formatted_output = json.dumps(
                formatted_result1, ensure_ascii=False, indent=4
            )
            log_success(f"第一次反馈:\n{formatted_output}")

            # 打印“最终 MCP 返回结果”（interactive_feedback 的返回内容）
            mcp_content1 = format_mcp_return_content(result1)
            if mcp_content1 is not None:
                mcp_output1 = json.dumps(mcp_content1, ensure_ascii=False, indent=4)
                log_success(f"第一次反馈（MCP 返回）:\n{mcp_output1}")
        else:
            log_warning("第一次反馈超时")
            return False

        # 第二次调用 - 更新内容
        print("🔄 更新页面内容...")
        prompt2, options2 = _create_second_task_content()

        result2 = launch_feedback_ui(
            prompt2,
            options2,
            task_id=None,  # 让系统自动生成 task_id
            timeout=feedback_timeout,
        )

        if result2:
            formatted_result2 = format_feedback_result(result2)
            formatted_output = json.dumps(
                formatted_result2, ensure_ascii=False, indent=4
            )
            print(f"✅ 第二次反馈:\n{formatted_output}")

            # 打印“最终 MCP 返回结果”（interactive_feedback 的返回内容）
            mcp_content2 = format_mcp_return_content(result2)
            if mcp_content2 is not None:
                mcp_output2 = json.dumps(mcp_content2, ensure_ascii=False, indent=4)
                print(f"✅ 第二次反馈（MCP 返回）:\n{mcp_output2}")
            print("🎉 智能介入测试完成！")
            return True
        else:
            print("⚠️ 第二次反馈失败")
            return False

    except KeyboardInterrupt:
        print("\n🛑 测试被用户中断")
        print("🧹 正在清理资源...")
        cleanup_services()
        return False
    except Exception as e:
        TestLogger.log_exception("智能介入测试失败", e, include_traceback=True)
        print("🧹 正在清理资源...")
        cleanup_services()
        return False


def test_web_ui_features():
    """测试 Web UI 功能（通过浏览器交互验证）

    验证 Web UI 的关键功能：task_id 显示和倒计时。

    返回:
        bool: 测试是否通过

    ## 测试内容

    1. **task_id 显示**：验证页面显示任务 ID
    2. **倒计时功能**：验证倒计时持续递减

    ## 验证方式

    - 启动 Web UI 并展示验证清单
    - 用户在浏览器中手动验证功能
    - 通过交互式选项收集验证结果

    ## 使用说明

    - 调用函数执行 Web UI 功能测试
    - 返回 True 表示测试通过

    ## 注意事项

    - 需要手动访问浏览器验证
    - 端口号从配置文件动态获取
    - 测试失败不会阻塞后续测试
    """
    # 从配置获取端口号
    try:
        from server import get_web_ui_config

        config, _ = get_web_ui_config()
        port = config.port
    except Exception:
        port = 8080  # 默认端口（与 workflow 保持一致）

    log_info("Web UI 功能测试 - 等待浏览器交互验证", "🌐")
    log_info("测试内容：", "ℹ️")
    log_info("1. task_id显示功能 - 验证task_id在页面上真实显示", "  ")
    log_info("2. 自动重调倒计时功能 - 验证倒计时持续递减", "  ")
    log_info("", "")
    log_info(f"请在浏览器中访问 http://localhost:{port} 进行以下验证：", "💡")
    log_info("  - 检查页面上是否显示 task_id（如 '📋 任务: xxx'）", "")
    log_info("  - 检查倒计时是否显示并持续递减", "")
    log_info("  - 等待几秒后确认倒计时数值确实在减少", "")
    log_info("", "")

    # 使用交互MCP等待用户验证
    try:
        from server import launch_feedback_ui

        prompt = f"""## 🌐 第1轮：Web UI 功能验证

请在浏览器中访问 **http://localhost:{port}** 进行验证：

### ✅ 验证清单：

1. **task_id显示**
   - [ ] 页面上显示 "📋 任务: xxx"
   - [ ] task_id文本清晰可见

2. **倒计时功能**
   - [ ] 页面上显示 "⏰ XX 秒后自动重调"
   - [ ] 倒计时数字在递减（等待5秒验证）

### 验证完成后请选择结果："""

        result = launch_feedback_ui(
            summary=prompt,
            predefined_options=[
                "✅ Web UI功能全部正常",
                "❌ 有功能异常",
                "🔄 需要重新测试",
            ],
            task_id=None,
            timeout=TestConfig.DEFAULT_THREAD_TIMEOUT,
        )

        if result and result.get("selected_options"):
            choice = result["selected_options"][0]
            if "全部正常" in choice:
                log_info("Web UI功能验证通过！", "✅")
                return True
            else:
                log_info(f"Web UI功能验证结果: {choice}", "⚠️")
                return False
        return True
    except Exception as e:
        TestLogger.log_exception("Web UI验证出错", e, include_traceback=True)
        return True  # 不阻塞后续测试


def test_multi_task_concurrent():
    """测试多任务并发功能（通过浏览器交互验证）

    验证多任务 UI 和 API 的正确性。

    返回:
        bool: 测试是否通过

    ## 测试内容

    1. **多任务 API 端点**：验证 `/api/tasks`, `/api/health` 可用
    2. **多任务 UI 元素**：验证标签页容器、任务徽章显示

    ## 验证方式

    - 启动 Web UI 并展示验证清单
    - 用户在浏览器中手动验证 UI 元素
    - 通过交互式选项收集验证结果

    ## 使用说明

    - 调用函数执行多任务并发测试
    - 返回 True 表示测试通过

    ## 注意事项

    - 需要手动访问浏览器验证
    - 端口号从配置文件动态获取
    - 测试失败不会阻塞后续测试
    """
    # 从配置获取端口号
    try:
        from server import get_web_ui_config

        config, _ = get_web_ui_config()
        port = config.port
    except Exception:
        port = 8080  # 默认端口（与 workflow 保持一致）

    log_info("多任务并发功能测试 - 等待浏览器交互验证", "🔄")
    log_info("测试内容：", "ℹ️")
    log_info("1. 多任务API端点验证（/api/tasks, /api/health）", "  ")
    log_info("2. 多任务UI元素验证（标签页容器、任务徽章）", "  ")
    log_info("3. JavaScript模块验证（multi_task.js, initMultiTaskSupport）", "  ")
    log_info("", "")
    log_info(f"请在浏览器中访问 http://localhost:{port} 进行验证", "💡")
    log_info("", "")

    # 使用交互MCP等待用户验证
    try:
        from server import launch_feedback_ui

        prompt = f"""## 🔄 第2轮：多任务并发功能验证

请在浏览器中访问 **http://localhost:{port}** 进行验证：

### ✅ 验证清单：

1. **API端点测试**
   - [ ] fetch('/api/tasks') 返回 status 200
   - [ ] fetch('/api/health') 返回 status 200

2. **UI元素检查**
   - [ ] task-tabs-container 元素存在
   - [ ] task-tabs 元素存在且可见
   - [ ] task-count-badge 元素存在

3. **JavaScript模块**
   - [ ] multi_task.js 脚本已加载
   - [ ] initMultiTaskSupport() 函数存在

### 验证完成后请选择结果："""

        result = launch_feedback_ui(
            summary=prompt,
            predefined_options=[
                "✅ 多任务功能全部正常",
                "❌ 有功能异常",
                "🔄 需要重新测试",
            ],
            task_id=None,
            timeout=TestConfig.DEFAULT_THREAD_TIMEOUT,
        )

        if result and result.get("selected_options"):
            choice = result["selected_options"][0]
            if "全部正常" in choice:
                log_info("多任务并发功能验证通过！", "✅")
                return True
            else:
                log_info(f"多任务并发功能验证结果: {choice}", "⚠️")
                return False
        return True
    except Exception as e:
        TestLogger.log_exception("多任务验证出错", e, include_traceback=True)
        return True  # 不阻塞后续测试


def test_parallel_tasks():
    """测试并行任务功能（通过浏览器交互验证）

    创建多个并发任务，验证任务管理和 UI 切换功能。

    返回:
        bool: 测试是否通过

    ## 测试内容

    1. **并发任务创建**：同时创建 3 个并发任务
    2. **任务标签页**：验证标签页显示和切换功能
    3. **独立倒计时**：验证每个任务有独立的倒计时

    ## 测试流程

    1. 启动 3 个并行线程，每个创建一个任务
    2. 用户在浏览器中验证任务切换功能
    3. 收集各任务的反馈结果
    4. 验证所有任务完成且结果正确

    ## 使用说明

    - 调用函数执行并行任务测试
    - 返回 True 表示测试通过

    ## 注意事项

    - 使用线程池并发创建任务
    - 需要等待所有任务创建完成
    - 用户需手动切换标签页验证
    - 测试失败不会阻塞后续测试
    """
    log_info("并行任务功能测试 - 创建3个并发任务", "🔄")
    log_info("测试内容：", "ℹ️")
    log_info("1. 同时创建3个并发任务", "  ")
    log_info("2. 验证任务标签页显示和切换功能", "  ")
    log_info("3. 验证每个任务独立倒计时", "  ")
    log_info("", "")

    try:
        import threading

        from server import launch_feedback_ui

        # 用于存储3个任务的结果
        task_results = {}
        task_threads = []

        def create_task(task_num):
            """创建单个任务的函数"""
            try:
                tasks_count = TestConfig.PARALLEL_TASKS_COUNT
                prompt = f"""## 📋 任务 {task_num}/{tasks_count}

这是**并行任务测试**中的第{task_num}个任务。

### 🎯 测试说明：
- 当前正在创建{tasks_count}个并发任务
- 请在浏览器查看是否显示了多个任务标签
- 可以通过点击标签切换任务

### ⏰ 重要：
- **任务{task_num}** 将保持活动状态
- 请等待所有任务创建完成后再验证
- 每个任务都有独立的倒计时

---

**请在此任务中输入 "task{task_num}" 然后点击"继续下一步"**"""

                # ⚠️ 注意：task_id 参数已废弃，系统会自动生成唯一ID
                # 这里保留是为了向后兼容测试代码，但实际会被忽略
                result = launch_feedback_ui(
                    summary=prompt,
                    predefined_options=["✅ 继续下一步"],
                    task_id=f"parallel-task-{task_num}",  # 此参数将被忽略
                    timeout=TestConfig.PARALLEL_TASK_TIMEOUT,
                )
                task_results[task_num] = result
                log_info(f"任务{task_num}已完成", "✅")
            except Exception as e:
                TestLogger.log_exception(
                    f"任务{task_num}创建失败", e, include_traceback=False
                )
                task_results[task_num] = None

        # 同时启动多个并发任务
        tasks_count = TestConfig.PARALLEL_TASKS_COUNT
        log_info(f"正在同时创建{tasks_count}个并发任务...", "🚀")
        time.sleep(1)  # 确保Web UI已启动

        for i in range(1, tasks_count + 1):
            thread = threading.Thread(target=create_task, args=(i,), daemon=True)
            thread.start()
            task_threads.append(thread)
            time.sleep(TestConfig.PARALLEL_TASK_START_DELAY)  # 稍微错开启动时间

        log_info(f"{tasks_count}个任务已启动！", "⏳")
        log_info("", "")
        log_info("📊 并行任务验证说明：", "ℹ️")
        # 从配置获取端口号
        try:
            from server import get_web_ui_config

            config, _ = get_web_ui_config()
            port = config.port
        except Exception:
            port = 8080  # 默认端口（与 workflow 保持一致）
        log_info(f"请在浏览器 http://localhost:{port} 验证：", "  ")
        log_info(f"1. 页面顶部显示{tasks_count}个任务标签", "  ")
        log_info("2. 可以点击标签切换任务", "  ")
        log_info("3. 每个任务有独立倒计时", "  ")
        log_info("", "")
        log_info("完成每个任务后，测试将自动通过", "💡")
        log_info("", "")

        # 等待所有任务线程完成
        log_info("等待所有任务完成...", "⏳")
        for thread in task_threads:
            thread.join(timeout=TestConfig.PARALLEL_THREAD_JOIN_TIMEOUT)

        # 检查结果
        completed_count = sum(1 for result in task_results.values() if result)
        if completed_count == tasks_count:
            log_info("并行任务功能验证通过！", "✅")
            return True
        else:
            log_info(
                f"并行任务功能验证失败: 仅完成{completed_count}/{TestConfig.PARALLEL_TASKS_COUNT}个任务",
                "❌",
            )
            return True  # 不阻塞后续测试

    except Exception as e:
        TestLogger.log_exception("并行任务测试出错", e, include_traceback=True)
        return True  # 不阻塞后续测试


def parse_arguments():
    """解析命令行参数

    解析测试工具的命令行参数，支持自定义端口、主机、超时等配置。

    返回:
        argparse.Namespace: 解析后的参数对象

    ## 支持的参数

    - `--port, -p`: 指定端口号（默认从配置文件读取）
    - `--host`: 指定主机地址（默认从配置文件读取或 0.0.0.0）
    - `--timeout`: 指定超时时间（秒，默认从配置文件读取或 300）
    - `--thread-timeout`: 指定线程等待超时时间（秒，默认 600）
    - `--verbose, -v`: 显示详细日志信息

    ## 使用说明

    - 使用默认配置：`python test.py`
    - 指定端口：`--port 9000`
    - 指定主机和超时：`--host 127.0.0.1 --timeout 600`
    - 启用详细日志：`--verbose`

    ## 注意事项

    - 命令行参数优先级高于配置文件
    - 指定 --port 时端口冲突会直接报错退出（避免端口漂移）
    - timeout 和 thread-timeout 是不同的概念
    """
    parser = argparse.ArgumentParser(
        description="AI Intervention Agent 智能介入代理测试工具"
    )

    parser.add_argument(
        "--port",
        "-p",
        type=int,
        default=None,
        help="指定测试使用的端口号 (默认使用配置文件中的设置)",
    )

    parser.add_argument(
        "--host",
        type=str,
        default=None,
        help="指定测试使用的主机地址 (默认使用配置文件中的设置或0.0.0.0)",
    )

    parser.add_argument(
        "--timeout",
        type=int,
        default=None,
        help="指定超时时间（秒）(默认使用配置文件中的设置或300)",
    )

    parser.add_argument(
        "--resubmit-prompt",
        type=str,
        default=None,
        help="设置 feedback.resubmit_prompt（用于超时/错误提示语；默认使用配置文件）",
    )

    parser.add_argument(
        "--prompt-suffix",
        type=str,
        default=None,
        help="设置 feedback.prompt_suffix（追加在反馈末尾的提示语；默认使用配置文件）",
    )

    parser.add_argument(
        "--thread-timeout",
        type=int,
        default=TestConfig.DEFAULT_THREAD_TIMEOUT,
        help=f"指定线程等待超时时间（秒）(默认{TestConfig.DEFAULT_THREAD_TIMEOUT}秒)",
    )

    parser.add_argument("--verbose", "-v", action="store_true", help="显示详细日志信息")

    return parser.parse_args()


def setup_test_environment(args):
    """根据命令行参数设置测试环境

    根据命令行参数配置日志级别、端口、主机、超时等。

    参数:
        args (argparse.Namespace): 命令行参数对象

    返回:
        bool: 配置设置是否成功

    ## 配置内容

    1. **日志级别**：根据 `--verbose` 启用详细日志
    2. **端口配置**：如果指定了 --port，则必须使用该端口；端口冲突会直接报错（避免“端口漂移”）
    3. **主机配置**：更新主机地址
    4. **超时配置**：更新超时时间

    ## 处理流程

    1. 设置日志级别（如果启用 verbose）
    2. 检查并更新端口（如果指定）
    3. 更新主机地址（如果指定）
    4. 更新超时时间（如果指定）
    5. 保存配置更新

    ## 使用说明

    - 解析命令行参数后调用此函数
    - 设置测试环境
    - 返回 True 表示设置成功

    ## 注意事项

    - 指定 --port 时不会自动切换端口（避免偏离测试 workflow）
    - 配置更新仅在内存中生效（不修改配置文件）
    - 失败时不会中断程序，仅记录警告
    """
    try:
        # 设置日志级别
        if args.verbose:
            try:
                import logging

                from enhanced_logging import EnhancedLogger  # noqa: F401

                # 设置全局日志级别为DEBUG
                logging.getLogger().setLevel(logging.DEBUG)
                print("🔊 已启用详细日志模式（使用增强日志系统）")
            except ImportError:
                import logging

                logging.getLogger().setLevel(logging.DEBUG)
                print("🔊 已启用详细日志模式（使用标准日志系统）")

        # 更新配置文件（如果指定了参数）
        config_updated = False

        try:
            from config_manager import get_config

            config_mgr = get_config()
        except ImportError:
            print("⚠️ 无法导入配置管理器，跳过配置更新")
            return True

        if args.port is not None:
            # 检查端口是否被占用
            if check_port_availability(args.port):
                config_mgr.set("web_ui.port", args.port, save=False)  # 不保存到文件
                config_updated = True
                print(f"📌 设置端口: {args.port}")

                # 【关键修复】锁定测试端口：避免运行过程中 ConfigManager 因热加载/外部变更
                # 重新读回 config.jsonc 的端口（例如 8081）导致第二轮/后续轮次跑偏。
                # 设计：注册配置变更回调，在检测到端口被改回非 args.port 时，立即改回 args.port。
                _enforce_state = {"active": False}

                def _enforce_test_port() -> None:
                    if _enforce_state["active"]:
                        return
                    _enforce_state["active"] = True
                    try:
                        current_port = config_mgr.get("web_ui.port")
                        if current_port != args.port:
                            config_mgr.set("web_ui.port", args.port, save=False)
                    finally:
                        _enforce_state["active"] = False

                try:
                    config_mgr.register_config_change_callback(_enforce_test_port)
                except Exception:
                    # 回调注册失败不影响主流程（最多导致端口可能被外部配置覆盖）
                    pass
            else:
                # 按 workflow：用户显式指定端口时必须严格使用该端口，不能自动切换
                print(
                    f"❌ 端口 {args.port} 已被占用。"
                    "根据 workflow，本次测试必须使用指定端口，请先释放该端口或调整 --port。"
                )
                return False

        if args.host is not None:
            config_mgr.set("web_ui.host", args.host, save=False)  # 不保存到文件
            config_updated = True
            print(f"📌 设置主机: {args.host}")

        if args.timeout is not None:
            config_mgr.set("feedback.timeout", args.timeout, save=False)  # 不保存到文件
            config_updated = True
            print(f"📌 设置反馈超时: {args.timeout}秒")

        if getattr(args, "resubmit_prompt", None) is not None:
            config_mgr.set(
                "feedback.resubmit_prompt", args.resubmit_prompt, save=False
            )  # 不保存到文件
            config_updated = True
            print("📌 设置 resubmit_prompt")

        if getattr(args, "prompt_suffix", None) is not None:
            config_mgr.set(
                "feedback.prompt_suffix", args.prompt_suffix, save=False
            )  # 不保存到文件
            config_updated = True
            print("📌 设置 prompt_suffix")

        if args.thread_timeout is not None:
            print(f"📌 设置线程等待超时: {args.thread_timeout}秒")

        if config_updated:
            print("✅ 配置已更新（仅在内存中，不修改配置文件）")

        return True

    except Exception as e:
        TestLogger.log_exception("配置设置失败", e, include_traceback=True)
        return False


def check_port_availability(port):
    """检查端口是否可用

    参数:
        port: 端口号

    返回:
        bool: 端口是否可用（未被占用）
    """
    try:
        import socket

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(TestConfig.PORT_CHECK_TIMEOUT)
            result = sock.connect_ex(("localhost", port))
            return result != 0  # 端口未被占用返回True
    except Exception as e:
        log_debug(f"端口可用性检查失败 (端口 {port}): {type(e).__name__}")
        return False


def find_available_port(start_port, max_attempts=None):
    """从指定端口开始查找可用端口"""
    if max_attempts is None:
        max_attempts = TestConfig.PORT_SEARCH_MAX_ATTEMPTS

    for port in range(start_port, start_port + max_attempts):
        if (
            TestConfig.PORT_MIN <= port <= TestConfig.PORT_MAX
            and check_port_availability(port)
        ):
            return port
    return None


def validate_args(args):
    """验证命令行参数的合理性"""
    if args.thread_timeout is not None and args.thread_timeout < 0:
        print("❌ 错误: 线程等待超时时间不能为负数")
        return False

    if args.timeout is not None and args.timeout <= 0:
        print("❌ 错误: 反馈超时时间必须大于0")
        return False

    if args.port is not None and (
        args.port < TestConfig.PORT_MIN or args.port > TestConfig.PORT_MAX
    ):
        print(f"❌ 错误: 端口号必须在{TestConfig.PORT_MIN}-{TestConfig.PORT_MAX}范围内")
        return False

    return True


def get_test_config(args):
    """获取测试配置信息"""
    try:
        from server import get_feedback_prompts, get_web_ui_config

        config, auto_resubmit_timeout = get_web_ui_config()
        resubmit_prompt, prompt_suffix = get_feedback_prompts()

        # 获取线程等待超时时间
        thread_timeout_value = (
            args.thread_timeout
            if args and args.thread_timeout is not None
            else TestConfig.DEFAULT_THREAD_TIMEOUT
        )

        return {
            "server_config": config,
            "auto_resubmit_timeout": auto_resubmit_timeout,
            "resubmit_prompt": resubmit_prompt,
            "prompt_suffix": prompt_suffix,
            "thread_timeout": thread_timeout_value,
            "success": True,
        }
    except Exception as e:
        # 如果无法获取服务器配置，使用默认值
        thread_timeout_value = (
            args.thread_timeout
            if args and args.thread_timeout is not None
            else TestConfig.DEFAULT_THREAD_TIMEOUT
        )

        return {
            "server_config": None,
            "thread_timeout": thread_timeout_value,
            "success": False,
            "error": str(e),
        }


def display_test_config(config_info):
    """显示测试配置信息

    在控制台打印当前的测试配置详情。

    参数:
        config_info (dict): 配置信息字典，包含以下键：
            - server_config: 服务器配置对象（或 None）
            - thread_timeout: 线程等待超时时间（秒）
            - success: 配置获取是否成功
            - error: 错误信息（如果有）

    ## 显示内容

    - 主机地址
    - 端口号
    - 反馈超时时间
    - 最大重试次数
    - 线程等待超时时间

    ## 使用说明

    - 传入配置信息字典
    - 自动格式化并打印到控制台
    """
    print("📋 当前测试配置:")

    if config_info["success"] and config_info["server_config"]:
        server_config = config_info["server_config"]
        print(f"   主机: {server_config.host}")
        print(f"   端口: {server_config.port}")
        print(f"   反馈超时: {server_config.timeout}秒")
        print(f"   重试: {server_config.max_retries}次")
    else:
        print("   ⚠️ 无法获取服务器配置，使用默认值")
        if config_info.get("error"):
            print(f"   错误信息: {config_info['error']}")

    thread_timeout = config_info["thread_timeout"]
    if thread_timeout == 0:
        print("   线程等待超时: 无限等待")
    else:
        print(f"   线程等待超时: {thread_timeout}秒")

    # 提示语配置（用于验证 interactive_feedback 的提示语是否生效）
    resubmit_prompt = config_info.get("resubmit_prompt")
    prompt_suffix = config_info.get("prompt_suffix")
    if isinstance(resubmit_prompt, str) and resubmit_prompt:
        preview = (
            resubmit_prompt
            if len(resubmit_prompt) <= 80
            else resubmit_prompt[:80] + "..."
        )
        print(f"   resubmit_prompt: {preview}")
    if isinstance(prompt_suffix, str) and prompt_suffix:
        preview = (
            prompt_suffix if len(prompt_suffix) <= 80 else prompt_suffix[:80] + "..."
        )
        # 为了可读性，把换行转义展示
        print(f"   prompt_suffix: {preview!r}")
    print("=" * 50)


def main(args=None):
    """主测试函数

    AI Intervention Agent 测试工具的入口函数。

    参数:
        args (argparse.Namespace, optional): 命令行参数对象

    返回:
        bool: 所有测试是否都通过

    ## 测试流程

    1. **信号处理器注册**：设置 Ctrl+C 和退出清理
    2. **参数验证**：验证命令行参数的有效性
    3. **配置获取**：获取并显示测试配置
    4. **配置验证测试**：测试配置加载和验证功能
    5. **服务健康检查测试**：测试服务健康检查功能
    6. **Web UI 功能测试**：测试 task_id 显示和倒计时
    7. **多任务并发测试**：测试多任务 UI 和 API
    8. **并行任务测试**：测试并行任务创建和切换
    9. **清理资源**：关闭服务和清理临时文件

    ## 使用说明

    - 命令行运行：`python test.py`
    - 程序内调用：导入并调用 main 函数

    ## 注意事项

    - 需要手动在浏览器中验证 UI 功能
    - 测试失败不会中断程序，会继续执行后续测试
    - 测试结束后自动清理资源
    - 支持 Ctrl+C 中断并安全退出
    """
    # 设置信号处理器和清理机制
    setup_signal_handlers()

    print("🧪 AI Intervention Agent 智能介入代理测试")
    print("=" * 50)

    # 验证参数
    if args and not validate_args(args):
        return False

    # 获取和显示配置
    config_info = get_test_config(args)
    display_test_config(config_info)

    thread_timeout_value = config_info["thread_timeout"]

    # 运行所有测试
    tests = [
        ("配置验证", test_config_validation),
        ("服务健康检查", test_service_health),
        ("智能介入工作流程", lambda: test_persistent_workflow(thread_timeout_value)),
        ("并行任务功能", test_parallel_tasks),
    ]

    results = []

    for test_name, test_func in tests:
        print(f"\n🧪 运行测试: {test_name}")
        print("-" * 30)

        try:
            success = test_func()
            results.append((test_name, success))

            if success:
                print(f"✅ {test_name} 测试通过")
            else:
                print(f"❌ {test_name} 测试失败")

        except KeyboardInterrupt:
            print(f"\n👋 {test_name} 测试被中断")
            print("🧹 正在清理资源...")
            cleanup_services()
            break
        except Exception as e:
            TestLogger.log_exception(f"{test_name} 测试出错", e, include_traceback=True)
            results.append((test_name, False))

    # 显示测试结果摘要
    print("\n" + "=" * 50)
    print("📊 测试结果摘要:")

    passed = 0
    total = len(results)

    for test_name, success in results:
        status = "✅ 通过" if success else "❌ 失败"
        print(f"   {test_name}: {status}")
        if success:
            passed += 1

    print(f"\n📈 总体结果: {passed}/{total} 测试通过")

    if passed == total:
        print("🎉 所有测试都通过了！")
    else:
        print("⚠️ 部分测试失败，请检查日志")

    # 显示使用示例
    print("\n💡 使用提示:")
    print("   指定端口: --port 8080")
    print("   指定主机: --host 127.0.0.1")
    print("   指定线程等待超时: --thread-timeout 600")
    print("   指定反馈超时: --timeout 60")
    print("   详细日志: --verbose")
    print("   查看帮助: --help")

    return passed == total


if __name__ == "__main__":
    try:
        args = parse_arguments()

        # 设置测试环境
        if not setup_test_environment(args):
            print("❌ 配置设置失败，程序退出")
            sys.exit(1)

        # 运行主测试
        success = main(args)
        sys.exit(0 if success else 1)

    except KeyboardInterrupt:
        print("\n👋 程序被用户中断")
        cleanup_services()
        sys.exit(0)
    except Exception as e:
        print(f"❌ 程序运行出错: {e}")
        cleanup_services()
        sys.exit(1)
