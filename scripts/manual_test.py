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
- 直接运行：`python scripts/manual_test.py`

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
- httpx (HTTP请求)
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

sys.path.insert(0, str(Path(__file__).resolve().parent))


test_logger: Any
try:
    from ai_intervention_agent.enhanced_logging import EnhancedLogger

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


class TestConfig:
    """测试配置常量类"""

    DEFAULT_THREAD_TIMEOUT = 600
    SERVICE_STARTUP_WAIT_TIME = 2
    HTTP_REQUEST_TIMEOUT = 5
    PARALLEL_TASK_TIMEOUT = 600
    PARALLEL_THREAD_JOIN_TIMEOUT = 650
    PORT_CHECK_TIMEOUT = 1

    FEEDBACK_TIMEOUT_BUFFER = 10
    FEEDBACK_TIMEOUT_MIN = 30
    FEEDBACK_TIMEOUT_THRESHOLD = 40

    API_CONFIG_PATH = "/api/config"
    API_TASKS_PATH = "/api/tasks"
    API_HEALTH_PATH = "/api/health"

    PORT_MIN = 1
    PORT_MAX = 65535
    PORT_SEARCH_MAX_ATTEMPTS = 10

    PARALLEL_TASKS_COUNT = 3
    PARALLEL_TASK_START_DELAY = 0.5


class SignalHandlerManager:
    """信号处理器管理类"""

    _instance = None
    _cleanup_registered = False

    def __new__(cls):
        """单例模式实现"""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    @classmethod
    def is_registered(cls):
        """检查信号处理器是否已注册"""
        return cls._cleanup_registered

    @classmethod
    def mark_registered(cls):
        """标记信号处理器已注册"""
        cls._cleanup_registered = True


class TestLogger:
    """测试日志工具类"""

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
        """统一的日志输出函数"""

        if emoji is None:
            emoji = TestLogger.DEFAULT_EMOJIS.get(level, "")

        full_message = f"{emoji} {message}" if emoji else message

        print(full_message)

        log_level = level if level in ("warning", "error", "debug") else "info"
        if ENHANCED_LOGGING_AVAILABLE:
            getattr(test_logger, log_level.lower())(message)
        else:
            getattr(test_logger, log_level.lower())(full_message)

    @staticmethod
    def log_exception(
        message: str, exc: Exception | None = None, include_traceback: bool = False
    ):
        """记录异常信息"""
        error_msg = message
        if exc:
            error_msg = f"{message}: {type(exc).__name__} - {exc!s}"

        TestLogger.log(error_msg, "error")

        if include_traceback and exc:
            import traceback

            if ENHANCED_LOGGING_AVAILABLE:
                test_logger.error(traceback.format_exc())
            else:
                test_logger.error(traceback.format_exc())


def log_info(message: str, emoji: str | None = None):
    """记录信息级别日志"""
    TestLogger.log(message, "info", emoji)


def log_success(message: str, emoji: str | None = None):
    """记录成功信息"""
    TestLogger.log(message, "success", emoji or "✅")


def log_warning(message: str, emoji: str | None = None):
    """记录警告信息"""
    TestLogger.log(message, "warning", emoji)


def log_error(message: str, emoji: str | None = None):
    """记录错误信息"""
    TestLogger.log(message, "error", emoji)


def log_debug(message: str, emoji: str | None = None):
    """记录调试信息"""
    TestLogger.log(message, "debug", emoji)


def setup_signal_handlers():
    """设置信号处理器"""
    handler_manager = SignalHandlerManager()

    if handler_manager.is_registered():
        return

    def signal_handler(signum, frame):
        """信号处理器"""
        del frame
        log_warning(f"收到中断信号 {signum}，正在清理资源...", "🛑")
        cleanup_services()
        log_info("程序已安全退出", "👋")
        sys.exit(0)

    def cleanup_on_exit():
        """程序退出时的清理函数"""
        log_info("程序退出，正在清理资源...", "🧹")
        cleanup_services()

    if hasattr(signal, "SIGINT"):
        signal.signal(signal.SIGINT, signal_handler)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, signal_handler)

    atexit.register(cleanup_on_exit)

    handler_manager.mark_registered()
    log_debug("信号处理器和清理机制已注册", "🔧")


def cleanup_services():
    """清理所有服务进程"""
    try:
        from ai_intervention_agent.server import cleanup_services as server_cleanup

        server_cleanup()
        log_debug("服务清理完成")
    except Exception as e:
        TestLogger.log_exception("清理服务时出错", e, include_traceback=False)


def format_feedback_result(result):
    """格式化反馈结果用于显示"""
    if not isinstance(result, dict):
        return str(result)

    formatted_result = result.copy()

    if formatted_result.get("images"):
        formatted_images = []
        for img in formatted_result["images"]:
            if isinstance(img, dict):
                formatted_img = img.copy()

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

        from ai_intervention_agent.server import parse_structured_response
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
    """检查服务是否可用"""
    if timeout is None:
        timeout = TestConfig.HTTP_REQUEST_TIMEOUT
    try:
        import httpx

        response = httpx.get(url, timeout=timeout)
        return response.status_code == 200
    except Exception as e:
        log_debug(f"服务检查失败 ({url}): {type(e).__name__} - {e!s}")
        return False


def test_config_validation():
    """测试配置验证功能"""
    log_info("测试配置验证...", "🔧")

    try:
        from ai_intervention_agent.server import get_web_ui_config, validate_input

        config, auto_resubmit_timeout = get_web_ui_config()
        log_success(
            f"配置加载成功: {config.host}:{config.port}, 自动重新调用超时: {auto_resubmit_timeout}秒"
        )

        prompt, options = validate_input("测试消息", ["选项1", "选项2"])
        log_success(
            f"输入验证成功: prompt='{prompt[:20]}...', options={len(options)}个"
        )

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
    """测试服务健康检查"""
    log_info("测试服务健康检查...", "🏥")

    try:
        from ai_intervention_agent.server import (
            get_web_ui_config,
            health_check_service,
            is_web_service_running,
        )

        config, auto_resubmit_timeout = get_web_ui_config()

        is_running = is_web_service_running(config.host, config.port)
        log_success(f"端口检查完成: {'运行中' if is_running else '未运行'}")

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
    """计算反馈超时时间"""
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
    """生成第一个任务的内容"""
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
    """生成第二个任务的复杂 Markdown 内容"""
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
    """在独立线程中启动任务"""
    from ai_intervention_agent.server import launch_feedback_ui

    result_container = {"result": None}

    def run_task():
        try:
            result_container["result"] = launch_feedback_ui(
                prompt,
                options,
                task_id=task_id,
                timeout=feedback_timeout,
            )
        except Exception as e:
            TestLogger.log_exception("任务执行失败", e, include_traceback=True)

    thread = threading.Thread(target=run_task)
    thread.start()

    return thread, result_container


def _wait_for_service_startup(service_url, port, wait_time=None, max_wait=None):
    """等待 Web 服务启动并验证可用性（使用轮询机制）"""
    if wait_time is None:
        wait_time = TestConfig.SERVICE_STARTUP_WAIT_TIME
    if max_wait is None:
        max_wait = 15

    log_info("等待服务启动...", "⏳")

    time.sleep(wait_time)

    check_interval = 0.5
    elapsed = wait_time
    last_log_time = 0

    while elapsed < max_wait:
        if check_service(service_url):
            log_success("服务启动成功，请在浏览器中提交反馈")
            log_info(f"浏览器地址: http://localhost:{port}", "🌐")
            return True

        if elapsed - last_log_time >= 2:
            log_debug(f"等待服务启动... ({elapsed:.1f}s/{max_wait}s)")
            last_log_time = elapsed

        time.sleep(check_interval)
        elapsed += check_interval

    if check_service(service_url):
        log_success("服务启动成功，请在浏览器中提交反馈")
        log_info(f"浏览器地址: http://localhost:{port}", "🌐")
        return True

    log_error(f"服务启动失败（等待超时 {max_wait} 秒）")
    return False


def test_persistent_workflow(timeout=None):
    """测试智能介入工作流程"""
    if timeout is None:
        timeout = TestConfig.DEFAULT_THREAD_TIMEOUT

    log_info("测试智能介入工作流程...", "🔄")

    feedback_timeout = _calculate_feedback_timeout(timeout)

    try:
        from ai_intervention_agent.server import get_web_ui_config, launch_feedback_ui

        config, auto_resubmit_timeout = get_web_ui_config()
        service_url = f"http://localhost:{config.port}{TestConfig.API_CONFIG_PATH}"

        log_info("启动介入服务...", "🚀")
        prompt1, options1 = _create_first_task_content()

        thread1, result_container1 = _launch_task_in_thread(
            prompt1, options1, feedback_timeout
        )

        if not _wait_for_service_startup(service_url, config.port):
            return False

        if timeout == 0:
            thread1.join()
        else:
            thread1.join(timeout=timeout)

        result1 = result_container1["result"]
        if result1:
            formatted_result1 = format_feedback_result(result1)
            formatted_output = json.dumps(
                formatted_result1, ensure_ascii=False, indent=4
            )
            log_success(f"第一次反馈:\n{formatted_output}")

            mcp_content1 = format_mcp_return_content(result1)
            if mcp_content1 is not None:
                mcp_output1 = json.dumps(mcp_content1, ensure_ascii=False, indent=4)
                log_success(f"第一次反馈（MCP 返回）:\n{mcp_output1}")
        else:
            log_warning("第一次反馈超时")
            return False

        print("🔄 更新页面内容...")
        prompt2, options2 = _create_second_task_content()

        result2 = launch_feedback_ui(
            prompt2,
            options2,
            task_id=None,
            timeout=feedback_timeout,
        )

        if result2:
            formatted_result2 = format_feedback_result(result2)
            formatted_output = json.dumps(
                formatted_result2, ensure_ascii=False, indent=4
            )
            print(f"✅ 第二次反馈:\n{formatted_output}")

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
    """测试 Web UI 功能（通过浏览器交互验证）"""

    try:
        from ai_intervention_agent.server import get_web_ui_config

        config, _ = get_web_ui_config()
        port = config.port
    except Exception:
        port = 8080

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

    try:
        from ai_intervention_agent.server import launch_feedback_ui

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
        return True


def test_multi_task_concurrent():
    """测试多任务并发功能（通过浏览器交互验证）"""

    try:
        from ai_intervention_agent.server import get_web_ui_config

        config, _ = get_web_ui_config()
        port = config.port
    except Exception:
        port = 8080

    log_info("多任务并发功能测试 - 等待浏览器交互验证", "🔄")
    log_info("测试内容：", "ℹ️")
    log_info("1. 多任务API端点验证（/api/tasks, /api/health）", "  ")
    log_info("2. 多任务UI元素验证（标签页容器、任务徽章）", "  ")
    log_info("3. JavaScript模块验证（multi_task.js, initMultiTaskSupport）", "  ")
    log_info("", "")
    log_info(f"请在浏览器中访问 http://localhost:{port} 进行验证", "💡")
    log_info("", "")

    try:
        from ai_intervention_agent.server import launch_feedback_ui

        prompt = f"""## 🔄 第2轮：多任务并发功能验证

请在浏览器中访问 **http://localhost:{port}** 进行验证：

### ✅ 验证清单：

1. **API端点测试**
   - [ ] fetch('/api/tasks') 返回 status 200
   - [ ] fetch('/api/health') 返回 status 200

2. **UI元素检查**
   - [ ] task-tabs-container 元素存在
   - [ ] task-tabs 元素存在且可见

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
        return True


def test_parallel_tasks():
    """测试并行任务功能（通过浏览器交互验证）"""
    log_info("并行任务功能测试 - 创建3个并发任务", "🔄")
    log_info("测试内容：", "ℹ️")
    log_info("1. 同时创建3个并发任务", "  ")
    log_info("2. 验证任务标签页显示和切换功能", "  ")
    log_info("3. 验证每个任务独立倒计时", "  ")
    log_info("", "")

    try:
        import threading

        from ai_intervention_agent.server import launch_feedback_ui

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

                result = launch_feedback_ui(
                    summary=prompt,
                    predefined_options=["✅ 继续下一步"],
                    task_id=f"parallel-task-{task_num}",
                    timeout=TestConfig.PARALLEL_TASK_TIMEOUT,
                )
                task_results[task_num] = result
                log_info(f"任务{task_num}已完成", "✅")
            except Exception as e:
                TestLogger.log_exception(
                    f"任务{task_num}创建失败", e, include_traceback=False
                )
                task_results[task_num] = None

        tasks_count = TestConfig.PARALLEL_TASKS_COUNT
        log_info(f"正在同时创建{tasks_count}个并发任务...", "🚀")
        time.sleep(1)

        for i in range(1, tasks_count + 1):
            thread = threading.Thread(target=create_task, args=(i,), daemon=True)
            thread.start()
            task_threads.append(thread)
            time.sleep(TestConfig.PARALLEL_TASK_START_DELAY)

        log_info(f"{tasks_count}个任务已启动！", "⏳")
        log_info("", "")
        log_info("📊 并行任务验证说明：", "ℹ️")

        try:
            from ai_intervention_agent.server import get_web_ui_config

            config, _ = get_web_ui_config()
            port = config.port
        except Exception:
            port = 8080
        log_info(f"请在浏览器 http://localhost:{port} 验证：", "  ")
        log_info(f"1. 页面顶部显示{tasks_count}个任务标签", "  ")
        log_info("2. 可以点击标签切换任务", "  ")
        log_info("3. 每个任务有独立倒计时", "  ")
        log_info("", "")
        log_info("完成每个任务后，测试将自动通过", "💡")
        log_info("", "")

        log_info("等待所有任务完成...", "⏳")
        for thread in task_threads:
            thread.join(timeout=TestConfig.PARALLEL_THREAD_JOIN_TIMEOUT)

        completed_count = sum(1 for result in task_results.values() if result)
        if completed_count == tasks_count:
            log_info("并行任务功能验证通过！", "✅")
            return True
        else:
            log_info(
                f"并行任务功能验证失败: 仅完成{completed_count}/{TestConfig.PARALLEL_TASKS_COUNT}个任务",
                "❌",
            )
            return True

    except Exception as e:
        TestLogger.log_exception("并行任务测试出错", e, include_traceback=True)
        return True


def parse_arguments():
    """解析命令行参数"""
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
    """根据命令行参数设置测试环境"""
    try:
        if args.verbose:
            try:
                import logging

                from ai_intervention_agent.enhanced_logging import (
                    EnhancedLogger,  # noqa: F401
                )

                logging.getLogger().setLevel(logging.DEBUG)
                print("🔊 已启用详细日志模式（使用增强日志系统）")
            except ImportError:
                import logging

                logging.getLogger().setLevel(logging.DEBUG)
                print("🔊 已启用详细日志模式（使用标准日志系统）")

        config_updated = False

        try:
            from ai_intervention_agent.config_manager import get_config

            config_mgr = get_config()
        except ImportError:
            print("⚠️ 无法导入配置管理器，跳过配置更新")
            return True

        if args.port is not None:
            if check_port_availability(args.port):
                config_mgr.set("web_ui.port", args.port, save=False)
                config_updated = True
                print(f"📌 设置端口: {args.port}")

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
                    pass
            else:
                print(
                    f"❌ 端口 {args.port} 已被占用。"
                    "根据 workflow，本次测试必须使用指定端口，请先释放该端口或调整 --port。"
                )
                return False

        if args.host is not None:
            config_mgr.set("web_ui.host", args.host, save=False)
            config_updated = True
            print(f"📌 设置主机: {args.host}")

        if args.timeout is not None:
            config_mgr.set("feedback.timeout", args.timeout, save=False)
            config_updated = True
            print(f"📌 设置反馈超时: {args.timeout}秒")

        if getattr(args, "resubmit_prompt", None) is not None:
            config_mgr.set("feedback.resubmit_prompt", args.resubmit_prompt, save=False)
            config_updated = True
            print("📌 设置 resubmit_prompt")

        if getattr(args, "prompt_suffix", None) is not None:
            config_mgr.set("feedback.prompt_suffix", args.prompt_suffix, save=False)
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
    """检查端口是否可用"""
    try:
        import socket

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(TestConfig.PORT_CHECK_TIMEOUT)
            result = sock.connect_ex(("localhost", port))
            return result != 0
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
        from ai_intervention_agent.server import get_feedback_prompts, get_web_ui_config

        config, auto_resubmit_timeout = get_web_ui_config()
        resubmit_prompt, prompt_suffix = get_feedback_prompts()

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
    """显示测试配置信息"""
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

        print(f"   prompt_suffix: {preview!r}")
    print("=" * 50)


def main(args=None):
    """主测试函数"""

    setup_signal_handlers()

    print("🧪 AI Intervention Agent 智能介入代理测试")
    print("=" * 50)

    if args and not validate_args(args):
        return False

    config_info = get_test_config(args)
    display_test_config(config_info)

    thread_timeout_value = config_info["thread_timeout"]

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

        if not setup_test_environment(args):
            print("❌ 配置设置失败，程序退出")
            sys.exit(1)

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
