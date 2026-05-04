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
from typing import Any

# 项目根目录
PROJECT_ROOT = Path(__file__).parent.parent

# 需要文档化的模块
MODULES_TO_DOCUMENT = [
    "config_manager.py",
    "config_utils.py",
    "exceptions.py",
    "server_config.py",
    "shared_types.py",
    "notification_manager.py",
    "notification_models.py",
    "notification_providers.py",
    "task_queue.py",
    "file_validator.py",
    "enhanced_logging.py",
]


def extract_docstring(node: ast.AST) -> str | None:
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


def parse_module(filepath: Path) -> dict[str, Any]:
    """解析 Python 模块"""
    with open(filepath, encoding="utf-8") as f:
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


def generate_markdown(
    module_info: dict[str, Any], *, lang: str = "zh-CN", include_docstrings: bool = True
) -> str:
    """生成 Markdown 格式文档"""
    lines = []

    # 模块标题
    lines.append(f"# {module_info['name']}")
    lines.append("")

    if lang == "en":
        # 英文文档聚焦签名；完整说明请看中文版本。
        lines.append(
            f"> For the Chinese version with full docstrings, see: "
            f"[`docs/api.zh-CN/{module_info['name']}.md`](../api.zh-CN/{module_info['name']}.md)"
        )
        lines.append("")

    # 模块文档
    if include_docstrings and module_info["docstring"]:
        lines.append(module_info["docstring"])
        lines.append("")

    # 函数
    if module_info["functions"]:
        lines.append("## Functions" if lang == "en" else "## 函数")
        lines.append("")
        for func in module_info["functions"]:
            prefix = "async " if func["is_async"] else ""
            lines.append(f"### `{prefix}{func['name']}{func['signature']}`")
            lines.append("")
            if include_docstrings and func["docstring"]:
                lines.append(func["docstring"])
                lines.append("")

    # 类
    if module_info["classes"]:
        lines.append("## Classes" if lang == "en" else "## 类")
        lines.append("")
        for cls in module_info["classes"]:
            lines.append(f"### `class {cls['name']}`")
            lines.append("")
            if include_docstrings and cls["docstring"]:
                lines.append(cls["docstring"])
                lines.append("")

            if cls["methods"]:
                lines.append("#### Methods" if lang == "en" else "#### 方法")
                lines.append("")
                for method in cls["methods"]:
                    if method["name"].startswith("_") and method["name"] != "__init__":
                        continue  # 跳过私有方法
                    prefix = "async " if method["is_async"] else ""
                    lines.append(
                        f"##### `{prefix}{method['name']}{method['signature']}`"
                    )
                    lines.append("")
                    if include_docstrings and method["docstring"]:
                        lines.append(method["docstring"])
                        lines.append("")

    # 每个 class/function 区块末尾会留一个 ""（视觉空行），最后一个区块的
    # 那个空行 + final-newline 会叠成 "\n\n"，被 pre-commit
    # `end-of-file-fixer` 还原为 "\n"。先 rstrip 掉所有结尾空白，再补
    # 唯一一个 "\n"，确保 generator 的输出与 fixer 整理后的盘上字节一致，
    # 这也是 `--check` 模式的幂等前提。
    return "\n".join(lines).rstrip("\n") + "\n"


def generate_index(modules: list[str], *, lang: str, output_dir_display: str) -> str:
    """生成文档索引"""
    if lang == "en":
        lines = [
            "# AI Intervention Agent API Docs",
            "",
            "English API reference (signatures-focused).",
            "",
            "- Chinese version: [`docs/api.zh-CN/index.md`](../api.zh-CN/index.md)",
            "",
            "## Modules",
            "",
        ]
    else:
        lines = [
            "# AI Intervention Agent API 文档",
            "",
            "- English version: [`docs/api/index.md`](../api/index.md)",
            "",
            "## 模块列表",
            "",
        ]

    for module in modules:
        module_name = Path(module).stem
        lines.append(f"- [{module_name}]({module_name}.md)")

    if lang == "en":
        lines.extend(
            [
                "",
                "## Quick navigation",
                "",
                "### Core modules",
                "",
                "- **config_manager**: Configuration management",
                "- **exceptions**: Unified exception definitions and error responses",
                "- **notification_manager**: Notification orchestration",
                "- **server_config**: MCP server configuration and utility helpers (dataclasses, constants, input validation, response parsing)",
                "- **task_queue**: Task queue",
                "",
                "### Utility modules",
                "",
                "- **config_utils**: Configuration utility helpers",
                "- **shared_types**: Shared TypedDict definitions",
                "- **notification_models**: Notification data models",
                "- **file_validator**: File validation",
                "- **enhanced_logging**: Logging enhancements",
                "",
                "---",
                "",
                f"_Auto-generated under `{output_dir_display}`_",
            ]
        )
    else:
        lines.extend(
            [
                "",
                "## 快速导航",
                "",
                "### 核心模块",
                "",
                "- **config_manager**: 配置管理",
                "- **exceptions**: 统一异常定义与错误响应",
                "- **notification_manager**: 通知管理",
                "- **server_config**: MCP 服务器配置与工具函数（数据类、常量、输入验证、响应解析）",
                "- **task_queue**: 任务队列",
                "",
                "### 工具模块",
                "",
                "- **config_utils**: 配置工具函数",
                "- **shared_types**: 共享 TypedDict 类型定义",
                "- **notification_models**: 通知数据模型",
                "- **file_validator**: 文件验证",
                "- **enhanced_logging**: 日志增强",
                "",
                "---",
                "",
                f"_文档自动生成于 `{output_dir_display}`_",
            ]
        )

    return "\n".join(lines) + "\n"


def _write_or_check(path: Path, content: str, *, check: bool, drift: list[Path]) -> str:
    """写入或仅校验是否漂移。

    返回单字符状态指示符（用于打印）：
      - ``"="`` 文件已存在且字节级一致（check 与 write 都不改）
      - ``"+"`` 文件不存在或字节级不一致；
        - check 模式：仅记录到 ``drift`` 列表，不写盘
        - write 模式：写入盘并视作成功生成
    """
    expected = content.encode("utf-8")
    actual = path.read_bytes() if path.exists() else b""
    if actual == expected:
        return "="
    if check:
        drift.append(path)
        return "+"
    path.write_bytes(expected)
    return "+"


def main() -> int:
    parser = argparse.ArgumentParser(description="代码文档生成脚本")
    parser.add_argument(
        "--lang",
        choices=["en", "zh-CN"],
        default="zh-CN",
        help="输出语言（默认 zh-CN）",
    )
    parser.add_argument(
        "--format",
        choices=["markdown", "html", "text"],
        default="markdown",
        help="输出格式（默认 markdown）",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="输出目录（默认：en=docs/api/，zh-CN=docs/api.zh-CN/）",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help=(
            "校验模式：不写盘，仅检查 docs/api(.zh-CN) 是否与当前源码同步。"
            "存在漂移时退出码 1，列出漂移文件路径，便于 CI / pre-merge 拦截。"
        ),
    )
    args = parser.parse_args()

    if not args.output:
        args.output = "docs/api/" if args.lang == "en" else "docs/api.zh-CN/"

    output_dir = PROJECT_ROOT / args.output
    if not args.check:
        output_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 50)
    print("代码文档生成工具" + ("（校验模式）" if args.check else ""))
    print("=" * 50)
    print(f"输出目录: {output_dir}")
    print(f"输出格式: {args.format}")
    print()

    generated_modules: list[str] = []
    drift: list[Path] = []

    for module_file in MODULES_TO_DOCUMENT:
        filepath = PROJECT_ROOT / module_file
        if not filepath.exists():
            print(f"⚠️  跳过不存在的文件: {module_file}")
            continue

        print(f"📄 处理: {module_file}")

        try:
            module_info = parse_module(filepath)

            if args.format == "markdown":
                content = generate_markdown(
                    module_info,
                    lang=args.lang,
                    include_docstrings=(args.lang != "en"),
                )
                output_file = output_dir / f"{module_info['name']}.md"
                status = _write_or_check(
                    output_file, content, check=args.check, drift=drift
                )
                marker = "🔄" if status == "+" else "✅"
                action = (
                    ("漂移" if args.check else "生成") if status == "+" else "已同步"
                )
                print(f"   {marker} {action}: {output_file.name}")
                generated_modules.append(module_file)

        except Exception as e:
            print(f"   ❌ 错误: {e}")

    if generated_modules:
        index_content = generate_index(
            generated_modules, lang=args.lang, output_dir_display=args.output
        )
        index_file = output_dir / "index.md"
        status = _write_or_check(
            index_file, index_content, check=args.check, drift=drift
        )
        marker = "🔄" if status == "+" else "📑"
        action = ("漂移" if args.check else "索引") if status == "+" else "索引已同步"
        print(f"\n{marker} {action}: {index_file}")

    print()
    print("=" * 50)
    if args.check:
        if drift:
            print(f"❌ 校验失败：发现 {len(drift)} 个漂移文件")
            for p in drift:
                rel = p.relative_to(PROJECT_ROOT)
                print(f"  - {rel}")
            print()
            print("修复方法：")
            print(f"  uv run python scripts/generate_docs.py --lang {args.lang}")
            return 1
        print(f"✅ 校验通过：所有 {len(generated_modules)} 个文档与源码一致")
        return 0
    print(f"完成！共生成 {len(generated_modules)} 个文档")
    print(f"查看: {output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
