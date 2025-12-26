#!/usr/bin/env python3
"""
代码文档生成脚本

功能说明：
    自动从 Python 源代码生成 API 文档。

使用方法：
    python scripts/generate_docs.py [--format html|markdown|text] [--output docs/]

参数说明：
    --format: 输出格式（默认 markdown）
    --output: 输出目录（默认 docs/api/）

依赖：
    - pydoc: Python 内置
    - ast: Python 内置

注意事项：
    - 生成的文档基于 docstring
    - 支持类型提示解析
"""

import argparse
import ast
from pathlib import Path
from typing import Any, Dict, List, Optional

# 项目根目录
PROJECT_ROOT = Path(__file__).parent.parent

# 需要文档化的模块
MODULES_TO_DOCUMENT = [
    "config_manager.py",
    "config_utils.py",
    "notification_manager.py",
    "notification_providers.py",
    "task_queue.py",
    "file_validator.py",
    "enhanced_logging.py",
]


def extract_docstring(node: ast.AST) -> Optional[str]:
    """提取 AST 节点的 docstring"""
    if isinstance(
        node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Module)
    ):
        docstring = ast.get_docstring(node)
        return docstring
    return None


def get_function_signature(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    """获取函数签名"""
    args = []
    defaults_offset = len(node.args.args) - len(node.args.defaults)

    for i, arg in enumerate(node.args.args):
        arg_str = arg.arg
        if arg.annotation:
            arg_str += f": {ast.unparse(arg.annotation)}"

        # 添加默认值
        default_idx = i - defaults_offset
        if default_idx >= 0:
            default = node.args.defaults[default_idx]
            arg_str += f" = {ast.unparse(default)}"

        args.append(arg_str)

    # 返回类型
    return_type = ""
    if node.returns:
        return_type = f" -> {ast.unparse(node.returns)}"

    return f"({', '.join(args)}){return_type}"


def parse_module(filepath: Path) -> Dict[str, Any]:
    """解析 Python 模块"""
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()

    tree = ast.parse(content)

    classes: list[dict[str, Any]] = []
    functions: list[dict[str, Any]] = []
    result: dict[str, Any] = {
        "name": filepath.stem,
        "docstring": extract_docstring(tree),
        "classes": classes,
        "functions": functions,
    }

    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.ClassDef):
            methods: list[dict[str, Any]] = []
            class_info = {
                "name": node.name,
                "docstring": extract_docstring(node),
                "methods": methods,
            }
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    method_info = {
                        "name": item.name,
                        "signature": get_function_signature(item),
                        "docstring": extract_docstring(item),
                        "is_async": isinstance(item, ast.AsyncFunctionDef),
                    }
                    methods.append(method_info)
            classes.append(class_info)

        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            func_info = {
                "name": node.name,
                "signature": get_function_signature(node),
                "docstring": extract_docstring(node),
                "is_async": isinstance(node, ast.AsyncFunctionDef),
            }
            functions.append(func_info)

    return result


def generate_markdown(module_info: Dict[str, Any]) -> str:
    """生成 Markdown 格式文档"""
    lines = []

    # 模块标题
    lines.append(f"# {module_info['name']}")
    lines.append("")

    # 模块文档
    if module_info["docstring"]:
        lines.append(module_info["docstring"])
        lines.append("")

    # 函数
    if module_info["functions"]:
        lines.append("## 函数")
        lines.append("")
        for func in module_info["functions"]:
            prefix = "async " if func["is_async"] else ""
            lines.append(f"### `{prefix}{func['name']}{func['signature']}`")
            lines.append("")
            if func["docstring"]:
                lines.append(func["docstring"])
                lines.append("")

    # 类
    if module_info["classes"]:
        lines.append("## 类")
        lines.append("")
        for cls in module_info["classes"]:
            lines.append(f"### `class {cls['name']}`")
            lines.append("")
            if cls["docstring"]:
                lines.append(cls["docstring"])
                lines.append("")

            if cls["methods"]:
                lines.append("#### 方法")
                lines.append("")
                for method in cls["methods"]:
                    if method["name"].startswith("_") and method["name"] != "__init__":
                        continue  # 跳过私有方法
                    prefix = "async " if method["is_async"] else ""
                    lines.append(
                        f"##### `{prefix}{method['name']}{method['signature']}`"
                    )
                    lines.append("")
                    if method["docstring"]:
                        # 缩进 docstring
                        lines.append(method["docstring"])
                        lines.append("")

    return "\n".join(lines)


def generate_index(modules: List[str], output_dir: Path) -> str:
    """生成文档索引"""
    lines = [
        "# AI Intervention Agent API 文档",
        "",
        "## 模块列表",
        "",
    ]

    for module in modules:
        module_name = Path(module).stem
        lines.append(f"- [{module_name}]({module_name}.md)")

    lines.extend(
        [
            "",
            "## 快速导航",
            "",
            "### 核心模块",
            "- **config_manager**: 配置管理",
            "- **notification_manager**: 通知管理",
            "- **task_queue**: 任务队列",
            "",
            "### 工具模块",
            "- **config_utils**: 配置工具函数",
            "- **file_validator**: 文件验证",
            "- **enhanced_logging**: 日志增强",
            "",
            "---",
            f"*文档自动生成于 {output_dir}*",
        ]
    )

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="代码文档生成脚本")
    parser.add_argument(
        "--format",
        choices=["markdown", "html", "text"],
        default="markdown",
        help="输出格式（默认 markdown）",
    )
    parser.add_argument(
        "--output", default="docs/api/", help="输出目录（默认 docs/api/）"
    )
    args = parser.parse_args()

    output_dir = PROJECT_ROOT / args.output
    output_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 50)
    print("代码文档生成工具")
    print("=" * 50)
    print(f"输出目录: {output_dir}")
    print(f"输出格式: {args.format}")
    print()

    generated_modules = []

    for module_file in MODULES_TO_DOCUMENT:
        filepath = PROJECT_ROOT / module_file
        if not filepath.exists():
            print(f"⚠️  跳过不存在的文件: {module_file}")
            continue

        print(f"📄 处理: {module_file}")

        try:
            module_info = parse_module(filepath)

            if args.format == "markdown":
                content = generate_markdown(module_info)
                output_file = output_dir / f"{module_info['name']}.md"
                output_file.write_text(content, encoding="utf-8")
                print(f"   ✅ 生成: {output_file.name}")
                generated_modules.append(module_file)

        except Exception as e:
            print(f"   ❌ 错误: {e}")

    # 生成索引
    if generated_modules:
        index_content = generate_index(generated_modules, output_dir)
        index_file = output_dir / "index.md"
        index_file.write_text(index_content, encoding="utf-8")
        print(f"\n📑 索引: {index_file}")

    print()
    print("=" * 50)
    print(f"完成！共生成 {len(generated_modules)} 个文档")
    print(f"查看: {output_dir}")


if __name__ == "__main__":
    main()
