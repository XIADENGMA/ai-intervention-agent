# Web UI for AI Intervention Agent MCP
# Enhanced version supporting both GUI and Web modes for SSH remote usage
import json
import os
import threading
from typing import Dict, List, Optional

import markdown
from flask import Flask, jsonify, render_template_string, request, send_from_directory
from flask_cors import CORS


class WebFeedbackUI:
    def __init__(
        self,
        prompt: str,
        predefined_options: Optional[List[str]] = None,
        host: str = "0.0.0.0",
        port: int = 8080,
    ):
        self.prompt = prompt
        self.predefined_options = predefined_options or []
        self.host = host
        self.port = port
        self.feedback_result = None
        self.current_prompt = prompt if prompt else ""
        self.current_options = predefined_options or []
        self.has_content = bool(prompt)
        self.initial_empty = not bool(prompt)
        self.app = Flask(__name__)
        CORS(self.app)
        self.setup_markdown()
        self.setup_routes()

    def setup_markdown(self):
        """设置Markdown渲染器"""
        self.md = markdown.Markdown(
            extensions=[
                "fenced_code",
                "codehilite",
                "tables",
                "toc",
                "nl2br",
                "attr_list",  # 支持属性列表
                "def_list",   # 支持定义列表
                "abbr",       # 支持缩写
                "footnotes",  # 支持脚注
                "md_in_html", # 支持HTML中的markdown
            ],
            extension_configs={
                "codehilite": {
                    "css_class": "highlight",
                    "use_pygments": True,
                    "noclasses": True,
                    "pygments_style": "monokai",
                    "guess_lang": True,  # 自动猜测语言
                    "linenums": False,   # 不显示行号
                }
            },
        )

    def render_markdown(self, text: str) -> str:
        """渲染Markdown文本为HTML"""
        if not text:
            return ""
        return self.md.convert(text)

    def setup_routes(self):
        @self.app.route("/")
        def index():
            return render_template_string(self.get_html_template())

        @self.app.route("/api/config")
        def get_config():
            return jsonify(
                {
                    "prompt": self.current_prompt,
                    "prompt_html": self.render_markdown(self.current_prompt)
                    if self.has_content
                    else "",
                    "predefined_options": self.current_options,
                    "persistent": True,
                    "has_content": self.has_content,
                    "initial_empty": self.initial_empty,
                }
            )

        @self.app.route("/api/close", methods=["POST"])
        def close_interface():
            """关闭界面的API端点"""
            threading.Timer(0.5, self.shutdown_server).start()
            return jsonify({"status": "success", "message": "服务即将关闭"})

        @self.app.route("/api/submit", methods=["POST"])
        def submit_feedback():
            data = request.json
            feedback_text = data.get("feedback_text", "").strip()
            selected_options = data.get("selected_options", [])

            # Combine selected options and feedback text
            final_feedback_parts = []

            # Add selected options
            if selected_options:
                final_feedback_parts.append("; ".join(selected_options))

            # Add user's text feedback
            if feedback_text:
                final_feedback_parts.append(feedback_text)

            # Join with a newline if both parts exist
            final_feedback = "\n\n".join(final_feedback_parts)

            self.feedback_result = {"interactive_feedback": final_feedback}

            # 清空内容并等待下一次调用
            self.current_prompt = ""
            self.current_options = []
            self.has_content = False
            return jsonify(
                {
                    "status": "success",
                    "message": "反馈已提交",
                    "persistent": True,
                    "clear_content": True,
                }
            )

        @self.app.route("/api/update", methods=["POST"])
        def update_content():
            """更新页面内容"""
            data = request.json
            new_prompt = data.get("prompt", "")
            new_options = data.get("predefined_options", [])

            # 更新内容
            self.current_prompt = new_prompt
            self.current_options = new_options if new_options is not None else []
            self.has_content = bool(new_prompt)
            # 重置反馈结果
            self.feedback_result = None

            return jsonify(
                {
                    "status": "success",
                    "message": "内容已更新",
                    "prompt": self.current_prompt,
                    "prompt_html": self.render_markdown(self.current_prompt)
                    if self.has_content
                    else "",
                    "predefined_options": self.current_options,
                    "has_content": self.has_content,
                }
            )

        @self.app.route("/api/feedback", methods=["GET"])
        def get_feedback():
            """获取用户反馈结果"""
            if self.feedback_result:
                # 返回反馈结果并清空
                result = self.feedback_result
                self.feedback_result = None
                return jsonify({"status": "success", "feedback": result})
            else:
                return jsonify({"status": "waiting", "feedback": None})

        # 静态文件路由
        @self.app.route("/fonts/<filename>")
        def serve_fonts(filename):
            """提供字体文件"""
            current_dir = os.path.dirname(os.path.abspath(__file__))
            fonts_dir = os.path.join(current_dir, "fonts")
            return send_from_directory(fonts_dir, filename)

        @self.app.route("/icons/<filename>")
        def serve_icons(filename):
            """提供图标文件"""
            current_dir = os.path.dirname(os.path.abspath(__file__))
            icons_dir = os.path.join(current_dir, "icons")
            return send_from_directory(icons_dir, filename)

        @self.app.route("/favicon.ico")
        def favicon():
            """提供favicon"""
            current_dir = os.path.dirname(os.path.abspath(__file__))
            icons_dir = os.path.join(current_dir, "icons")
            icon_path = os.path.join(icons_dir, "icon.ico")
            print(f"🔍 Favicon请求 - 图标目录: {icons_dir}")
            print(f"🔍 Favicon请求 - 图标文件: {icon_path}")
            print(f"🔍 Favicon请求 - 文件存在: {os.path.exists(icon_path)}")

            # 设置正确的MIME类型和缓存控制
            response = send_from_directory(icons_dir, "icon.ico")
            response.headers["Content-Type"] = "image/x-icon"
            response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
            return response

    def shutdown_server(self):
        """Gracefully shutdown the Flask server"""
        import signal

        os.kill(os.getpid(), signal.SIGINT)

    def get_html_template(self):
        """从模板文件读取HTML内容"""
        try:
            # 获取当前文件所在目录
            current_dir = os.path.dirname(os.path.abspath(__file__))
            # 构建模板文件路径
            template_path = os.path.join(current_dir, "templates", "web_ui.html")

            # 读取模板文件
            with open(template_path, "r", encoding="utf-8") as f:
                return f.read()
        except FileNotFoundError:
            # 如果模板文件不存在，返回一个基本的错误页面
            return """
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>模板文件未找到</title>
    <style>
        body {
            font-family: Arial, sans-serif;
            text-align: center;
            padding: 50px;
            background: #f5f5f5;
        }
        .error {
            color: #d32f2f;
            font-size: 18px;
            margin: 20px 0;
        }
    </style>
</head>
<body>
    <h1>模板文件未找到</h1>
    <div class="error">无法找到 templates/web_ui.html 文件</div>
    <p>请确保模板文件存在于正确的位置。</p>
</body>
</html>
            """
        except Exception as e:
            # 其他读取错误
            return f"""
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>模板加载错误</title>
    <style>
        body {{
            font-family: Arial, sans-serif;
            text-align: center;
            padding: 50px;
            background: #f5f5f5;
        }}
        .error {{
            color: #d32f2f;
            font-size: 18px;
            margin: 20px 0;
        }}
    </style>
</head>
<body>
    <h1>模板加载错误</h1>
    <div class="error">加载模板文件时发生错误: {str(e)}</div>
    <p>请检查模板文件是否正确。</p>
</body>
</html>
            """

    def update_content(self, new_prompt: str, new_options: Optional[List[str]] = None):
        """更新页面内容"""
        self.current_prompt = new_prompt
        self.current_options = new_options if new_options is not None else []
        self.has_content = bool(new_prompt)
        if new_prompt:
            print(f"📝 内容已更新: {new_prompt[:50]}...")
        else:
            print("📝 内容已清空，显示无有效内容页面")

    def run(self) -> Dict[str, str]:
        """启动Web服务器并等待用户反馈"""
        print(f"\n🌐 Web反馈界面已启动")
        print(f"📍 请在浏览器中打开: http://{self.host}:{self.port}")
        if self.host == "0.0.0.0":
            print(
                f"🔗 SSH端口转发命令: ssh -L {self.port}:localhost:{self.port} user@remote_server"
            )

        print("🔄 页面将保持打开，可实时更新内容")
        print()

        try:
            self.app.run(
                host=self.host, port=self.port, debug=False, use_reloader=False
            )
        except KeyboardInterrupt:
            pass

        return self.feedback_result or {"interactive_feedback": ""}


def web_feedback_ui(
    prompt: str,
    predefined_options: Optional[List[str]] = None,
    output_file: Optional[str] = None,
    host: str = "0.0.0.0",
    port: int = 8080,
) -> Optional[Dict[str, str]]:
    """启动Web版反馈界面"""
    ui = WebFeedbackUI(prompt, predefined_options, host, port)
    result = ui.run()

    if output_file and result:
        # 确保目录存在
        os.makedirs(
            os.path.dirname(output_file) if os.path.dirname(output_file) else ".",
            exist_ok=True,
        )
        # 保存结果到输出文件
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        return None

    return result


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="运行Web版反馈界面")
    parser.add_argument(
        "--prompt", default="我已经实现了您请求的更改。", help="向用户显示的提示信息"
    )
    parser.add_argument(
        "--predefined-options", default="", help="预定义选项列表，用|||分隔"
    )
    parser.add_argument("--output-file", help="将反馈结果保存为JSON文件的路径")
    parser.add_argument("--host", default="0.0.0.0", help="Web服务器监听地址")
    parser.add_argument("--port", type=int, default=8080, help="Web服务器监听端口")
    args = parser.parse_args()

    predefined_options = (
        [opt for opt in args.predefined_options.split("|||") if opt]
        if args.predefined_options
        else None
    )

    result = web_feedback_ui(
        args.prompt,
        predefined_options,
        args.output_file,
        args.host,
        args.port,
    )
    if result:
        print(f"\n收到反馈:\n{result['interactive_feedback']}")
    import sys

    sys.exit(0)
