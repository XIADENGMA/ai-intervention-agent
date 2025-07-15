#!/usr/bin/env python3
"""
AI Intervention Agent 智能介入代理测试工具
"""

import argparse
import atexit
import os
import signal
import sys
import threading
import time

# 添加当前目录到Python路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 初始化增强日志系统
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


# 全局变量用于跟踪清理状态
_cleanup_registered = False


def log_and_print(message: str, level: str = "info", emoji: str = ""):
    """统一的日志和控制台输出函数"""
    # 构建完整消息
    full_message = f"{emoji} {message}" if emoji else message

    # 输出到控制台（保持原有的用户体验）
    print(full_message)

    # 同时记录到日志系统
    if ENHANCED_LOGGING_AVAILABLE:
        getattr(test_logger, level.lower())(message)
    else:
        # 降级到标准日志
        getattr(test_logger, level.lower())(full_message)


def log_info(message: str, emoji: str = "ℹ️"):
    """记录信息级别日志"""
    log_and_print(message, "info", emoji)


def log_success(message: str, emoji: str = "✅"):
    """记录成功信息"""
    log_and_print(message, "info", emoji)


def log_warning(message: str, emoji: str = "⚠️"):
    """记录警告信息"""
    log_and_print(message, "warning", emoji)


def log_error(message: str, emoji: str = "❌"):
    """记录错误信息"""
    log_and_print(message, "error", emoji)


def log_debug(message: str, emoji: str = "🔍"):
    """记录调试信息"""
    log_and_print(message, "debug", emoji)


def setup_signal_handlers():
    """设置信号处理器"""
    global _cleanup_registered

    if _cleanup_registered:
        return

    def signal_handler(signum, frame):
        """信号处理器"""
        del frame  # 未使用的参数
        log_warning(f"收到中断信号 {signum}，正在清理资源...", "🛑")
        cleanup_services()
        log_info("程序已安全退出", "👋")
        sys.exit(0)

    def cleanup_on_exit():
        """程序退出时的清理函数"""
        log_info("程序退出，正在清理资源...", "🧹")
        cleanup_services()

    # 注册信号处理器
    if hasattr(signal, "SIGINT"):
        signal.signal(signal.SIGINT, signal_handler)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, signal_handler)

    # 注册退出清理函数
    atexit.register(cleanup_on_exit)

    _cleanup_registered = True
    log_debug("信号处理器和清理机制已注册", "🔧")


def cleanup_services():
    """清理所有服务进程"""
    try:
        from server import cleanup_services as server_cleanup

        server_cleanup()
        log_debug("服务清理完成")
    except Exception as e:
        log_warning(f"清理服务时出错: {e}")


def format_feedback_result(result):
    """格式化反馈结果用于显示，限制images的data字段长度"""
    if not isinstance(result, dict):
        return str(result)

    formatted_result = {}

    # 处理用户输入
    if "user_input" in result:
        formatted_result["user_input"] = result["user_input"]

    # 处理选择的选项
    if "selected_options" in result:
        formatted_result["selected_options"] = result["selected_options"]

    # 处理图片数据，限制data字段长度
    if "images" in result and result["images"]:
        formatted_images = []
        for img in result["images"]:
            if isinstance(img, dict):
                formatted_img = img.copy()
                # 限制data字段显示长度为50个字符
                if "data" in formatted_img and len(formatted_img["data"]) > 50:
                    formatted_img["data"] = formatted_img["data"][:50] + "..."
                formatted_images.append(formatted_img)
            else:
                formatted_images.append(img)
        formatted_result["images"] = formatted_images

    return formatted_result


def check_service(url, timeout=5):
    """检查服务是否可用"""
    try:
        import requests

        response = requests.get(url, timeout=timeout)
        return response.status_code == 200
    except Exception:
        return False


def test_config_validation():
    """测试配置验证功能"""
    log_info("测试配置验证...", "🔧")

    try:
        from server import get_web_ui_config, validate_input

        # 测试正常配置
        config = get_web_ui_config()
        log_success(f"配置加载成功: {config.host}:{config.port}")

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
        log_error(f"配置验证测试失败: {e}")
        return False


def test_service_health():
    """测试服务健康检查"""
    log_info("测试服务健康检查...", "🏥")

    try:
        from server import (
            get_web_ui_config,
            health_check_service,
            is_web_service_running,
        )

        config = get_web_ui_config()

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
        log_error(f"服务健康检查测试失败: {e}")
        return False


def test_persistent_workflow(timeout=300):
    """测试智能介入工作流程"""
    log_info("测试智能介入工作流程...", "🔄")
    if timeout == 0:
        log_info("线程等待超时时间: 无限等待", "⏱️")
        # 如果线程等待时间为0（无限等待），则反馈等待时间也设为0（无限等待）
        feedback_timeout = 0
    else:
        log_info(f"线程等待超时时间: {timeout}秒", "⏱️")
        # 反馈等待时间应该略小于线程等待时间，以便线程能够正常结束
        feedback_timeout = max(timeout - 10, 30) if timeout > 40 else timeout

    try:
        from server import get_web_ui_config, launch_feedback_ui

        config = get_web_ui_config()
        service_url = f"http://localhost:{config.port}/api/config"

        # 第一次调用 - 启动服务
        log_info("启动介入服务...", "🚀")
        prompt1 = """
        # 你好，我是AI Intervention Agent
**一个让用户能够实时控制 AI 执行过程的 MCP 工具。**

支持`Cursor`、`Vscode`、`Claude Code`、`Augment`、`Windsurf`、`Trae`等 AI 工具。"""
        options1 = [
            "🔄 继续了解",
            "✅ 立刻开始",
        ]  # "✅ 服务正常", "🔄 准备第二次测试", "📊 查看详细信息"

        result1 = None

        def run_first():
            nonlocal result1
            try:
                result1 = launch_feedback_ui(prompt1, options1, feedback_timeout)
            except Exception as e:
                log_error(f"第一次调用失败: {e}")

        thread1 = threading.Thread(target=run_first)
        thread1.start()

        # 等待服务启动并检查
        log_info("等待服务启动...", "⏳")
        time.sleep(5)
        if not check_service(service_url):
            log_error("服务启动失败")
            return False

        log_success("服务启动成功，请在浏览器中提交反馈")
        log_info(f"浏览器地址: http://localhost:{config.port}", "🌐")

        # 如果 timeout 为 0，表示无限等待
        if timeout == 0:
            thread1.join()  # 无限等待
        else:
            thread1.join(timeout=timeout)

        if result1:
            formatted_result1 = format_feedback_result(result1)
            log_success(f"第一次反馈: {formatted_result1}")
        else:
            log_warning("第一次反馈超时")
            return False

        # 第二次调用 - 更新内容
        print("🔄 更新页面内容...")
        prompt2 = """# 🎉 内容已更新！- 第二次调用

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
        options2 = ["🎉 内容更新成功", "✅ 测试完成"]

        result2 = launch_feedback_ui(prompt2, options2, feedback_timeout)

        if result2:
            formatted_result2 = format_feedback_result(result2)
            print(f"✅ 第二次反馈: {formatted_result2}")
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
        print(f"❌ 智能介入测试失败: {e}")
        print("🧹 正在清理资源...")
        cleanup_services()
        return False


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
        help="指定测试使用的端口号 (默认使用配置文件中的设置或8082)",
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
        "--thread-timeout",
        type=int,
        default=300,
        help="指定线程等待超时时间（秒）(默认300秒)",
    )

    parser.add_argument("--verbose", "-v", action="store_true", help="显示详细日志信息")

    return parser.parse_args()


def setup_test_environment(args):
    """根据命令行参数设置测试环境

    Args:
        args: 命令行参数对象

    Returns:
        bool: 配置设置是否成功
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
            else:
                print(f"⚠️ 端口 {args.port} 已被占用，将尝试自动查找可用端口...")
                available_port = find_available_port(args.port)
                if available_port:
                    config_mgr.set(
                        "web_ui.port", available_port, save=False
                    )  # 不保存到文件
                    config_updated = True
                    print(f"✅ 找到可用端口: {available_port}")
                else:
                    print("❌ 无法找到可用端口，将使用默认配置")

        if args.host is not None:
            config_mgr.set("web_ui.host", args.host, save=False)  # 不保存到文件
            config_updated = True
            print(f"📌 设置主机: {args.host}")

        if args.timeout is not None:
            config_mgr.set("feedback.timeout", args.timeout, save=False)  # 不保存到文件
            config_updated = True
            print(f"📌 设置反馈超时: {args.timeout}秒")

        if args.thread_timeout is not None:
            print(f"📌 设置线程等待超时: {args.thread_timeout}秒")

        if config_updated:
            print("✅ 配置已更新（仅在内存中，不修改配置文件）")

        return True

    except Exception as e:
        print(f"❌ 配置设置失败: {e}")
        return False


def check_port_availability(port):
    """检查端口是否可用"""
    try:
        import socket

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(1)
            result = sock.connect_ex(("localhost", port))
            return result != 0  # 端口未被占用返回True
    except Exception:
        return False


def find_available_port(start_port, max_attempts=10):
    """从指定端口开始查找可用端口"""
    for port in range(start_port, start_port + max_attempts):
        if 1 <= port <= 65535 and check_port_availability(port):
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

    if args.port is not None and (args.port < 1 or args.port > 65535):
        print("❌ 错误: 端口号必须在1-65535范围内")
        return False

    return True


def get_test_config(args):
    """获取测试配置信息"""
    try:
        from server import get_web_ui_config

        config = get_web_ui_config()

        # 获取线程等待超时时间
        thread_timeout_value = (
            args.thread_timeout if args and args.thread_timeout is not None else 300
        )

        return {
            "server_config": config,
            "thread_timeout": thread_timeout_value,
            "success": True,
        }
    except Exception as e:
        # 如果无法获取服务器配置，使用默认值
        thread_timeout_value = (
            args.thread_timeout if args and args.thread_timeout is not None else 300
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
    print("=" * 50)


def main(args=None):
    """主测试函数

    Args:
        args: 命令行参数对象，包含用户指定的配置选项

    Returns:
        bool: 所有测试是否都通过
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
            print(f"❌ {test_name} 测试出错: {e}")
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
    print("   指定端口: --port 8081")
    print("   指定主机: -host 127.0.0.1")
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
