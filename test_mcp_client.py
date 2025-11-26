#!/usr/bin/env python3
"""
AI Intervention Agent - MCP 客户端测试脚本

通过 MCP 协议测试 interactive_feedback 工具的功能。
不直接调用 Python 函数，而是作为 MCP 客户端连接到服务器。

使用方法:
    python test_mcp_client.py [--port PORT] [--timeout TIMEOUT] [--verbose]

示例:
    # 基础测试
    python test_mcp_client.py

    # 指定端口和详细输出
    python test_mcp_client.py --port 8081 --verbose

    # 使用更长的超时时间
    python test_mcp_client.py --timeout 600
"""

import argparse
import asyncio
import json
import os
import sys
import time
from typing import Any, Dict, List, Optional


def supports_color() -> bool:
    """
    检测终端是否支持颜色输出

    Returns:
        是否支持颜色
    """
    # 检查环境变量
    if os.environ.get("NO_COLOR"):
        return False

    if os.environ.get("FORCE_COLOR"):
        return True

    # Windows 检查
    if os.name == 'nt':
        # Windows 10+ 支持 ANSI 颜色
        try:
            import platform
            version = platform.version()
            # Windows 10 build 10586+ 支持 ANSI
            if 'Windows-10' in version or 'Windows-11' in version:
                return True
        except:
            pass
        # 检查 TERM 环境变量
        return bool(os.environ.get('TERM')) or sys.platform == 'cygwin'

    # Unix/Linux 检查
    return hasattr(sys.stdout, 'isatty') and sys.stdout.isatty()


# 颜色输出
class Colors:
    """终端颜色代码（根据平台自动启用/禁用）"""
    _supports_color = supports_color()

    HEADER = '\033[95m' if _supports_color else ''
    BLUE = '\033[94m' if _supports_color else ''
    CYAN = '\033[96m' if _supports_color else ''
    GREEN = '\033[92m' if _supports_color else ''
    YELLOW = '\033[93m' if _supports_color else ''
    RED = '\033[91m' if _supports_color else ''
    ENDC = '\033[0m' if _supports_color else ''
    BOLD = '\033[1m' if _supports_color else ''
    UNDERLINE = '\033[4m' if _supports_color else ''


def print_colored(message: str, color: str = Colors.ENDC) -> None:
    """打印彩色文本"""
    print(f"{color}{message}{Colors.ENDC}")


def print_header(message: str) -> None:
    """打印标题"""
    print_colored(f"\n{'='*60}", Colors.CYAN)
    print_colored(f"  {message}", Colors.BOLD + Colors.CYAN)
    print_colored(f"{'='*60}", Colors.CYAN)


def print_success(message: str) -> None:
    """打印成功消息"""
    print_colored(f"✅ {message}", Colors.GREEN)


def print_error(message: str) -> None:
    """打印错误消息"""
    print_colored(f"❌ {message}", Colors.RED)


def print_warning(message: str) -> None:
    """打印警告消息"""
    print_colored(f"⚠️  {message}", Colors.YELLOW)


def print_info(message: str) -> None:
    """打印信息"""
    print_colored(f"ℹ️  {message}", Colors.CYAN)


class MCPClient:
    """简化的 MCP 客户端，通过 HTTP API 与服务器通信"""

    def __init__(self, host: str = "0.0.0.0", port: int = 8081, timeout: int = 300, verbose: bool = False):
        """
        初始化 MCP 客户端

        Args:
            host: 服务器主机地址
            port: 服务器端口
            timeout: 任务超时时间（秒）
            verbose: 是否输出详细日志
        """
        self.host = host
        self.port = port
        self.timeout = timeout
        self.verbose = verbose
        self.base_url = f"http://{host}:{port}"
        self.active_tasks = []  # 跟踪活动任务

        # 导入 requests
        try:
            import requests
            self.requests = requests
        except ImportError:
            print_error("requests 库未安装，请运行: pip install requests")
            sys.exit(1)

    def log(self, message: str, level: str = "info") -> None:
        """输出日志"""
        if self.verbose:
            if level == "debug":
                print_info(f"[DEBUG] {message}")
            elif level == "info":
                print_info(message)
            elif level == "success":
                print_success(message)
            elif level == "warning":
                print_warning(message)
            elif level == "error":
                print_error(message)

    def cleanup_task(self, task_id: str) -> None:
        """
        清理任务（从服务器删除）

        Args:
            task_id: 任务 ID
        """
        try:
            self.log(f"清理任务: {task_id}", "debug")
            response = self.requests.delete(
                f"{self.base_url}/api/tasks/{task_id}",
                timeout=5
            )
            if response.status_code == 200:
                self.log(f"✅ 任务已清理: {task_id}", "debug")
            else:
                self.log(f"⚠️  任务清理失败: HTTP {response.status_code}", "debug")
        except:
            # 静默失败，清理失败不影响主流程
            pass

    def cleanup_all_tasks(self) -> None:
        """清理所有活动任务"""
        if self.active_tasks:
            self.log(f"清理 {len(self.active_tasks)} 个活动任务...", "info")
            for task_id in self.active_tasks[:]:  # 复制列表以避免修改迭代中的列表
                self.cleanup_task(task_id)
                self.active_tasks.remove(task_id)

    def check_server_availability(self) -> bool:
        """
        检查服务器是否可用

        Returns:
            服务器是否可用
        """
        self.log("检查服务器可用性...", "info")

        try:
            # 尝试访问配置 API
            response = self.requests.get(
                f"{self.base_url}/api/config",
                timeout=5
            )

            if response.status_code == 200:
                self.log("✅ 服务器可用", "success")
                return True
            else:
                self.log(f"❌ 服务器响应异常: HTTP {response.status_code}", "error")
                return False

        except self.requests.exceptions.ConnectionError:
            print_error("❌ 无法连接到服务器")
            print_info("请检查:")
            print_info(f"  1. 服务器是否已启动？")
            print_info(f"  2. 地址是否正确？{self.base_url}")
            print_info(f"  3. 端口 {self.port} 是否被占用？")
            print()
            print_info("启动服务器命令:")
            print_info(f"  python server.py")
            print_info(f"  或")
            print_info(f"  python test.py --port {self.port}")
            return False

        except self.requests.exceptions.Timeout:
            print_error(f"❌ 连接超时（5秒）")
            print_info("服务器可能启动中，请稍后重试")
            return False

        except Exception as e:
            print_error(f"❌ 服务器检查失败: {e}")
            return False

    def validate_input(self, message: str, predefined_options: Optional[List[str]]) -> None:
        """
        验证输入参数

        Args:
            message: 消息内容
            predefined_options: 预定义选项

        Raises:
            ValueError: 输入验证失败
            TypeError: 类型错误
        """
        # 验证消息
        if not message:
            raise ValueError("消息不能为空")

        if not isinstance(message, str):
            raise TypeError(f"消息必须是字符串，而不是 {type(message).__name__}")

        if not message.strip():
            raise ValueError("消息不能只包含空白字符")

        # 消息长度警告（不阻止）
        if len(message) > 100000:  # 100KB
            self.log(f"⚠️  消息较长 ({len(message)} 字符)，可能影响性能", "warning")

        # 验证预定义选项
        if predefined_options is not None:
            if not isinstance(predefined_options, list):
                raise TypeError(f"predefined_options 必须是列表，而不是 {type(predefined_options).__name__}")

            if len(predefined_options) > 50:
                raise ValueError(f"预定义选项过多（{len(predefined_options)} 个，最多50个）")

            for i, opt in enumerate(predefined_options):
                if not isinstance(opt, str):
                    raise TypeError(f"选项 #{i+1} 必须是字符串，而不是 {type(opt).__name__}")

                if not opt.strip():
                    raise ValueError(f"选项 #{i+1} 不能为空")

                if len(opt) > 500:
                    raise ValueError(f"选项 #{i+1} 过长（{len(opt)} 字符，最多500字符）: {opt[:50]}...")

    def call_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """
        调用 MCP 工具

        Args:
            tool_name: 工具名称（目前只支持 "interactive_feedback"）
            arguments: 工具参数

        Returns:
            工具调用结果
        """
        if tool_name != "interactive_feedback":
            raise ValueError(f"不支持的工具: {tool_name}")

        self.log(f"调用工具: {tool_name}", "info")
        self.log(f"参数: {json.dumps(arguments, ensure_ascii=False, indent=2)}", "debug")

        # 构造请求
        message = arguments.get("message", "")
        predefined_options = arguments.get("predefined_options")

        # 验证输入
        try:
            self.validate_input(message, predefined_options)
            self.log("✅ 输入验证通过", "debug")
        except (ValueError, TypeError) as e:
            self.log(f"❌ 输入验证失败: {e}", "error")
            return {"error": f"输入验证失败: {e}"}

        # 生成任务ID
        import random
        timestamp = int(time.time() * 1000) % 1000000
        random_suffix = random.randint(100, 999)
        task_id = f"test-mcp-{timestamp}-{random_suffix}"

        # 创建任务
        task_data = {
            "task_id": task_id,
            "prompt": message,
            "predefined_options": predefined_options or []
        }

        try:
            # 发送任务到服务器
            self.log("发送任务到服务器...", "info")
            response = self.requests.post(
                f"{self.base_url}/api/tasks",
                json=task_data,
                timeout=10
            )

            if response.status_code != 200:
                try:
                    error_msg = response.json().get("error", "未知错误")
                except:
                    error_msg = f"HTTP {response.status_code}: {response.text[:100]}"
                self.log(f"创建任务失败: {error_msg}", "error")
                return {"error": error_msg}

            task_id = response.json().get("task_id")
            self.log(f"任务已创建: {task_id}", "success")

            # 添加到活动任务列表
            self.active_tasks.append(task_id)

            try:
                # 等待用户反馈
                self.log(f"等待用户反馈 (超时: {self.timeout}秒)...", "info")
                start_time = time.time()

                retry_count = 0
                while time.time() - start_time < self.timeout:
                    try:
                        # 检查任务状态（添加请求超时）
                        status_response = self.requests.get(
                            f"{self.base_url}/api/tasks/{task_id}",
                            timeout=5
                        )

                        if status_response.status_code == 200:
                            task_data = status_response.json().get("task", {})
                            status = task_data.get("status")

                            if status == "completed":
                                self.log("用户已提交反馈", "success")
                                feedback = task_data.get("feedback", {})

                                # 格式化反馈结果
                                result = {
                                    "type": "text",
                                    "text": ""
                                }

                                # 添加选中的选项
                                selected_options = feedback.get("selected_options", [])
                                if selected_options:
                                    result["text"] += f"选择的选项: {', '.join(selected_options)}\n\n"

                                # 添加用户输入
                                user_input = feedback.get("user_input", "")
                                if user_input:
                                    result["text"] += f"用户输入: {user_input}"

                                # 处理图片
                                images = feedback.get("images", [])
                                if images:
                                    result["images"] = images

                                return result

                        # 重置重试计数器（请求成功）
                        retry_count = 0

                    except self.requests.exceptions.Timeout:
                        self.log(f"⚠️  状态查询超时，将重试...", "warning")
                        retry_count += 1
                        if retry_count >= 3:
                            self.log("连续3次超时，放弃重试", "error")
                            return {"error": "状态查询超时"}

                    except self.requests.exceptions.RequestException as e:
                        self.log(f"⚠️  状态查询失败: {e}", "warning")
                        retry_count += 1
                        if retry_count >= 3:
                            return {"error": f"状态查询失败: {e}"}

                    # 指数退避：等待时间随重试次数增加
                    wait_time = min(retry_count * 0.5, 5) if retry_count > 0 else 1
                    time.sleep(wait_time)

                # 超时
                self.log("等待超时", "error")
                return {"error": "任务超时"}

            finally:
                # 确保清理任务
                if task_id in self.active_tasks:
                    self.cleanup_task(task_id)
                    self.active_tasks.remove(task_id)

        except KeyboardInterrupt:
            self.log("用户中断", "warning")
            raise  # 重新抛出，允许退出

        except self.requests.exceptions.ConnectionError as e:
            self.log("无法连接到服务器", "error")
            print_info("可能原因:")
            print_info("  1. 服务器已停止运行")
            print_info("  2. 网络连接中断")
            print_info("  3. 防火墙阻止连接")
            return {"error": "连接失败"}

        except self.requests.exceptions.Timeout as e:
            self.log(f"请求超时", "error")
            print_info(f"超时设置: {self.timeout}秒")
            print_info("建议: 增加 --timeout 参数")
            return {"error": "请求超时"}

        except self.requests.exceptions.HTTPError as e:
            status_code = e.response.status_code if hasattr(e, 'response') else '未知'
            self.log(f"HTTP 错误: {status_code}", "error")
            return {"error": f"HTTP {status_code}"}

        except self.requests.exceptions.RequestException as e:
            self.log(f"请求错误: {e}", "error")
            return {"error": f"请求错误: {str(e)}"}

        except Exception as e:
            self.log(f"未知错误: {type(e).__name__}: {e}", "error")
            if self.verbose:
                import traceback
                self.log(traceback.format_exc(), "debug")
            return {"error": str(e)}


class MCPTestSuite:
    """MCP 测试套件"""

    def __init__(self, client: MCPClient):
        """
        初始化测试套件

        Args:
            client: MCP 客户端实例
        """
        self.client = client
        self.tests_passed = 0
        self.tests_failed = 0
        self.tests_total = 0

    async def run_test(self, test_name: str, test_func: callable) -> bool:
        """
        运行单个测试

        Args:
            test_name: 测试名称
            test_func: 测试函数

        Returns:
            测试是否通过
        """
        self.tests_total += 1
        print_header(f"测试 {self.tests_total}: {test_name}")

        try:
            result = await test_func()
            if result:
                self.tests_passed += 1
                print_success(f"✅ {test_name} 通过")
                return True
            else:
                self.tests_failed += 1
                print_error(f"❌ {test_name} 失败")
                return False
        except Exception as e:
            self.tests_failed += 1
            print_error(f"❌ {test_name} 异常: {e}")
            return False

    async def test_basic_feedback(self) -> bool:
        """测试基础反馈功能"""
        print_info("测试描述: 发送一个简单消息并等待用户反馈")

        result = self.client.call_tool(
            "interactive_feedback",
            {
                "message": "# 🧪 MCP 客户端测试\n\n这是一个通过 MCP 协议调用的测试消息。\n\n请在 Web UI 中提交任何反馈以完成测试。"
            }
        )

        if "error" in result:
            print_error(f"测试失败: {result['error']}")
            return False

        print_success(f"收到反馈: {result.get('text', 'No text')}")
        return True

    async def test_predefined_options(self) -> bool:
        """测试预定义选项功能"""
        print_info("测试描述: 发送带有预定义选项的消息")

        result = self.client.call_tool(
            "interactive_feedback",
            {
                "message": "# 🎯 选项测试\n\n请选择以下一个或多个选项：",
                "predefined_options": [
                    "✅ 选项 A",
                    "✅ 选项 B",
                    "✅ 选项 C"
                ]
            }
        )

        if "error" in result:
            print_error(f"测试失败: {result['error']}")
            return False

        print_success(f"收到反馈: {result.get('text', 'No text')}")
        return True

    async def test_markdown_rendering(self) -> bool:
        """测试 Markdown 渲染"""
        print_info("测试描述: 发送复杂的 Markdown 内容")

        markdown_content = """# 🎨 Markdown 渲染测试

## 文本格式

**粗体文本** 和 *斜体文本* 以及 ~~删除线~~

## 代码块

```python
def hello_world():
    print("Hello from MCP!")
    return 42
```

## 列表

1. 第一项
2. 第二项
   - 子项 A
   - 子项 B
3. 第三项

## 数学公式

行内公式：$E = mc^2$

块级公式：

$$
\\sum_{i=1}^{n} i = \\frac{n(n+1)}{2}
$$

## 表格

| 功能 | 状态 |
|------|------|
| 代码块渲染 | ✅ |
| 数学公式 | ✅ |
| 表格 | ✅ |

---

**请确认 Markdown 渲染正常后提交反馈。**
"""

        result = self.client.call_tool(
            "interactive_feedback",
            {
                "message": markdown_content
            }
        )

        if "error" in result:
            print_error(f"测试失败: {result['error']}")
            return False

        print_success(f"收到反馈: {result.get('text', 'No text')}")
        return True

    async def run_all_tests(self) -> None:
        """运行所有测试"""
        print_header("AI Intervention Agent - MCP 客户端测试套件")
        print_info(f"服务器地址: {self.client.base_url}")
        print_info(f"超时时间: {self.client.timeout}秒")
        print_info(f"详细模式: {'开启' if self.client.verbose else '关闭'}")
        print()

        # 检查服务器可用性
        if not self.client.check_server_availability():
            print_error("❌ 服务器不可用，无法继续测试")
            sys.exit(1)

        print()

        # 运行所有测试
        await self.run_test("基础反馈测试", self.test_basic_feedback)
        await self.run_test("预定义选项测试", self.test_predefined_options)
        await self.run_test("Markdown 渲染测试", self.test_markdown_rendering)

        # 打印测试总结
        print_header("测试总结")
        print_info(f"总计测试: {self.tests_total}")
        print_success(f"通过: {self.tests_passed}")
        if self.tests_failed > 0:
            print_error(f"失败: {self.tests_failed}")
        else:
            print_success("所有测试通过! 🎉")

        # 返回退出码
        sys.exit(0 if self.tests_failed == 0 else 1)


def main():
    """主函数"""
    parser = argparse.ArgumentParser(
        description="AI Intervention Agent - MCP 客户端测试脚本",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 基础测试
  python test_mcp_client.py

  # 指定端口和详细输出
  python test_mcp_client.py --port 8081 --verbose

  # 使用更长的超时时间
  python test_mcp_client.py --timeout 600

注意:
  - 此脚本需要服务器已经在运行
  - 使用 'python server.py' 或 'python test.py' 启动服务器
  - 每个测试都需要在 Web UI 中手动提交反馈
        """
    )

    parser.add_argument(
        "--host",
        default="0.0.0.0",
        help="服务器主机地址 (默认: 0.0.0.0)"
    )

    parser.add_argument(
        "--port",
        type=int,
        default=8081,
        help="服务器端口 (默认: 8081)"
    )

    parser.add_argument(
        "--timeout",
        type=int,
        default=300,
        help="任务超时时间（秒）(默认: 300)"
    )

    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="输出详细日志"
    )

    args = parser.parse_args()

    # 创建 MCP 客户端
    client = MCPClient(
        host=args.host,
        port=args.port,
        timeout=args.timeout,
        verbose=args.verbose
    )

    # 创建测试套件
    test_suite = MCPTestSuite(client)

    # 运行测试
    asyncio.run(test_suite.run_all_tests())


if __name__ == "__main__":
    main()
