#!/usr/bin/env python3
"""
AI Intervention Agent - MCP 客户端测试脚本

测试倒计时自动提交功能（resubmit）的完整工作流程：
1. 创建任务
2. 等待前端倒计时结束
3. 验证自动提交的反馈内容
4. 确认反馈包含配置的 resubmit_prompt

使用方法:
    python test_mcp_client.py --port 8080 --timeout 60

测试依赖：
    - Web UI 服务器运行中
    - 浏览器页面已打开（用于触发前端倒计时）

补充：图片返回格式自检（用于排查 Cursor/uvx 下图片不渲染问题）
------------------------------------------------------------
历史上出现过 uvx 模式下的图片返回报错：
`Error calling tool 'interactive_feedback': Unable to serialize unknown type: <class 'fastmcp.utilities.types.Image'>`

根因通常是：工具返回了“普通 dict / 或 fastmcp 的 Image 类对象”，导致 FastMCP 无法把它识别为 MCP 的 ImageContent。

本脚本提供 `--check-image-return` 快速自检模式，验证：
1) server.parse_structured_response() 返回的是 mcp.types.ImageContent/TextContent（不是 dict）
2) FastMCP 的内部转换逻辑不会把它降级成“文本(JSON字符串)”
"""

import argparse
import sys
import time
from typing import Any, Dict, List, Optional

import requests


class MCPClient:
    """简化的 MCP 客户端"""

    def __init__(self, host: str, port: int, timeout: int = 60):
        self.base_url = f"http://{host}:{port}"
        self.timeout = timeout
        self.active_tasks = []

    def check_server(self) -> bool:
        """检查服务器是否可用"""
        try:
            response = requests.get(f"{self.base_url}/api/health", timeout=5)
            return response.status_code == 200
        except Exception:
            return False

    def get_config(self) -> Dict[str, Any]:
        """获取服务器配置"""
        try:
            response = requests.get(f"{self.base_url}/api/config", timeout=5)
            return response.json() if response.status_code == 200 else {}
        except Exception:
            return {}

    def create_task(
        self, message: str, predefined_options: Optional[List[str]] = None
    ) -> Optional[str]:
        """创建任务，返回任务 ID"""
        import random

        timestamp = int(time.time() * 1000) % 1000000
        random_suffix = random.randint(100, 999)
        task_id = f"test-{timestamp}-{random_suffix}"

        task_data = {
            "task_id": task_id,
            "prompt": message,
            "predefined_options": predefined_options or [],
        }

        try:
            response = requests.post(
                f"{self.base_url}/api/tasks", json=task_data, timeout=10
            )
            if response.status_code == 200:
                self.active_tasks.append(task_id)
                return task_id
        except Exception:
            pass
        return None

    def wait_for_completion(self, task_id: str) -> Dict[str, Any]:
        """等待任务完成，返回反馈结果"""
        start_time = time.time()

        while time.time() - start_time < self.timeout:
            try:
                response = requests.get(
                    f"{self.base_url}/api/tasks/{task_id}", timeout=5
                )

                if response.status_code == 200:
                    task_data = response.json().get("task", {})
                    status = task_data.get("status")

                    if status == "completed":
                        result = task_data.get("result", {}) or {}
                        return {
                            "success": True,
                            "user_input": result.get("user_input", ""),
                            "selected_options": result.get("selected_options", []),
                            "images": result.get("images", []),
                        }

            except Exception:
                pass

            time.sleep(1)

        return {"success": False, "error": "timeout"}

    def cleanup(self, task_id: str) -> None:
        """清理任务"""
        try:
            requests.delete(f"{self.base_url}/api/tasks/{task_id}", timeout=5)
        except Exception:
            pass
        if task_id in self.active_tasks:
            self.active_tasks.remove(task_id)


class TestRunner:
    """测试运行器"""

    def __init__(self, client: MCPClient, verbose: bool = False):
        self.client = client
        self.verbose = verbose
        self.passed = 0
        self.failed = 0

    def log(self, message: str) -> None:
        """输出日志"""
        print(message)

    def run_test(
        self,
        name: str,
        message: str,
        predefined_options: Optional[List[str]] = None,
        expected_prompt: str = "请立即调用 interactive_feedback 工具",
    ) -> bool:
        """
        运行单个测试

        验证：
        1. 任务创建成功
        2. 等待自动提交完成
        3. 反馈内容包含预期的 resubmit_prompt
        """
        self.log(f"\n{'=' * 60}")
        self.log(f"测试: {name}")
        self.log(f"{'=' * 60}")

        # 1. 创建任务
        task_id = self.client.create_task(message, predefined_options)
        if not task_id:
            self.log("FAIL: 创建任务失败")
            self.failed += 1
            return False

        self.log(f"任务已创建: {task_id}")
        self.log(f"等待自动提交 (超时: {self.client.timeout}秒)...")

        # 2. 等待完成
        result = self.client.wait_for_completion(task_id)
        self.client.cleanup(task_id)

        if not result.get("success"):
            self.log(f"FAIL: 等待超时 - {result.get('error', '未知错误')}")
            self.failed += 1
            return False

        # 3. 验证反馈内容
        user_input = result.get("user_input", "")
        self.log(f"收到反馈: {user_input}")

        if expected_prompt in user_input:
            self.log("PASS: 反馈内容正确")
            self.passed += 1
            return True
        else:
            self.log("FAIL: 反馈内容不匹配")
            self.log(f"  预期包含: {expected_prompt}")
            self.log(f"  实际内容: {user_input}")
            self.failed += 1
            return False

    def run_all_tests(self) -> int:
        """运行所有测试"""
        self.log("=" * 60)
        self.log("AI Intervention Agent - 自动提交测试")
        self.log("=" * 60)
        self.log(f"服务器: {self.client.base_url}")
        self.log(f"超时: {self.client.timeout}秒")

        # 检查服务器
        if not self.client.check_server():
            self.log("\nFAIL: 服务器不可用")
            return 1

        # 获取配置
        config = self.client.get_config()
        auto_timeout = config.get("auto_resubmit_timeout", "未知")
        self.log(f"auto_resubmit_timeout: {auto_timeout}秒")

        # 测试 1: 基础反馈
        self.run_test(
            name="基础反馈测试",
            message="# 测试任务 1\n\n等待自动提交...",
        )

        # 测试 2: 带选项
        self.run_test(
            name="预定义选项测试",
            message="# 测试任务 2\n\n选项测试...",
            predefined_options=["选项 A", "选项 B", "选项 C"],
        )

        # 测试 3: 长文本
        self.run_test(
            name="Markdown 渲染测试",
            message="# 测试任务 3\n\n## 代码块\n```python\nprint('hello')\n```\n\n## 表格\n| A | B |\n|---|---|\n| 1 | 2 |",
        )

        # 总结
        self.log(f"\n{'=' * 60}")
        self.log("测试总结")
        self.log(f"{'=' * 60}")
        self.log(f"总计: {self.passed + self.failed}")
        self.log(f"通过: {self.passed}")
        self.log(f"失败: {self.failed}")

        if self.failed == 0:
            self.log("\n所有测试通过!")
            return 0
        else:
            self.log(f"\n{self.failed} 个测试失败")
            return 1


def self_check_image_return_format() -> bool:
    """自检：图片返回是否符合 MCP ContentBlock 约定（type/data/mimeType）"""
    try:
        from fastmcp.tools.tool import _convert_to_content
        from mcp.types import ImageContent, TextContent

        from server import parse_structured_response

        # 构造一个最小图片样例：base64("f") == "Zg=="
        response = {
            "user_input": "带图片的反馈",
            "selected_options": [],
            "images": [
                {
                    "filename": "test.png",
                    "content_type": "image/png",
                    "size": 1,
                    "data": "Zg==",
                }
            ],
        }

        parsed = parse_structured_response(response)
        if not isinstance(parsed, list):
            print("❌ 自检失败：parse_structured_response 未返回 list")
            return False

        if not any(isinstance(x, ImageContent) for x in parsed):
            print("❌ 自检失败：返回结果中没有 ImageContent（可能仍在返回 dict）")
            return False

        if not any(isinstance(x, TextContent) for x in parsed):
            print("❌ 自检失败：返回结果中没有 TextContent")
            return False

        converted = _convert_to_content(parsed)
        if not converted or not isinstance(converted[0], ImageContent):
            print(
                "❌ 自检失败：FastMCP 转换后首个块不是 ImageContent（可能被降级成文本）"
            )
            return False

        img0 = converted[0]
        if img0.mimeType != "image/png":
            print(f"❌ 自检失败：mimeType 不正确：{img0.mimeType!r}")
            return False

        if img0.data != "Zg==":
            print("❌ 自检失败：base64 data 被意外改写")
            return False

        print(
            "✅ 图片返回格式自检通过：ImageContent/TextContent 均可被 FastMCP 正确识别"
        )
        return True
    except Exception as e:
        print(f"❌ 图片返回格式自检异常：{type(e).__name__} - {e}")
        return False


def main():
    """主函数"""
    parser = argparse.ArgumentParser(
        description="测试 AI Intervention Agent 的自动提交功能"
    )
    parser.add_argument(
        "--host", default="127.0.0.1", help="服务器地址 (默认: 127.0.0.1)"
    )
    parser.add_argument(
        "--port", type=int, default=8080, help="服务器端口 (默认: 8080)"
    )
    parser.add_argument("--timeout", type=int, default=60, help="超时时间秒 (默认: 60)")
    parser.add_argument("--verbose", "-v", action="store_true", help="详细输出")
    parser.add_argument(
        "--check-image-return",
        action="store_true",
        help="仅执行图片返回格式自检（不依赖 Web UI 服务运行）",
    )

    args = parser.parse_args()

    if args.check_image_return:
        sys.exit(0 if self_check_image_return_format() else 1)

    client = MCPClient(host=args.host, port=args.port, timeout=args.timeout)
    runner = TestRunner(client, verbose=args.verbose)

    sys.exit(runner.run_all_tests())


if __name__ == "__main__":
    main()
