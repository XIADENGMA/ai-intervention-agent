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
    "i18n.py",
    "protocol.py",
    "state_machine.py",
    "server.py",
    "server_feedback.py",
    "server_config.py",
    "shared_types.py",
    "notification_manager.py",
    "notification_models.py",
    "notification_providers.py",
    "task_queue.py",
    "web_ui.py",
    "file_validator.py",
    "enhanced_logging.py",
]

# 显式标记"项目根有 *.py 但故意不出现在 docs/api 里"的模块。
# 没有正当理由的话，模块应该挪去 ``MODULES_TO_DOCUMENT``——本集合
# 配合 ``_assert_top_level_modules_classified`` 让未来新增模块时
# 必须做明确决策，而不是悄悄遗漏一个核心模块。
#
# 当前 9 个条目是 v1.5.x 的"历史欠账"——技术上**应该**全部文档化
# （它们都有完整的 module-level docstring + ``__all__``），但批量
# 补 9 份英文 / 中文 docs 是单独的工程工作（每模块都要审 docstring
# 质量、生成签名、刷 docs/README 的 Quick navigation 分组、维护
# 18 份 .md）。先用 IGNORED_MODULES 把现状锁定，未来一个一个
# graduate 到 MODULES_TO_DOCUMENT。
IGNORED_MODULES = frozenset(
    {
        # TODO(round-8/docs-debt): Web 服务编排（进程生命周期 + HTTP 客户端）。
        "service_manager.py",
        # TODO(round-8/docs-debt): web_ui ↔ config 双向同步；与 web_ui.py 一组搬。
        "web_ui_config_sync.py",
        # TODO(round-8/docs-debt): mDNS 发现服务。
        "web_ui_mdns.py",
        # TODO(round-8/docs-debt): mDNS 工具函数（hostname 校验等）。
        "web_ui_mdns_utils.py",
        # TODO(round-8/docs-debt): 网络访问控制 / IP 白名单 / 安全 Header。
        "web_ui_security.py",
        # TODO(round-8/docs-debt): 输入校验（add_task / update_feedback 等 endpoint）。
        "web_ui_validators.py",
    }
)


def _enumerate_top_level_python_modules() -> set[str]:
    """项目根目录下所有 ``*.py`` 文件名（不含子目录、不含 ``__init__.py``）。

    分类不变量的 LHS。集合语义；顺序不重要。
    """
    return {
        p.name
        for p in PROJECT_ROOT.glob("*.py")
        if p.is_file() and p.name != "__init__.py"
    }


def _assert_top_level_modules_classified() -> None:
    """守住「项目根 ``*.py`` ⊆ ``MODULES_TO_DOCUMENT`` ∪ ``IGNORED_MODULES``」不变量。

    场景
    ----
    *  新增模块 ``foo.py`` 但忘了在 ``MODULES_TO_DOCUMENT`` 登记 → 该模块没
       有 docs，下游用户 grep 不到，CI 沉默。本不变量 fail-closed 提示。
    *  ``MODULES_TO_DOCUMENT`` / ``IGNORED_MODULES`` 列了一个已删除的模块
       → "stale entry"。一段时间后会让 reviewer 困惑"为什么这条留着"。

    设计
    ----
    *  与 ``_assert_quick_nav_covers_all_modules`` 同形（都是分类完整性
       不变量），错误消息模板也保持一致：缺谁、误列谁、修复在哪改。
    *  通过 ``generate_index`` 入口触发——任何一次 ``generate_docs.py``
       /``--check`` /``minify_assets.py`` 联动都会走这条路径。
    *  ``IGNORED_MODULES`` 故意做成 ``frozenset``（不可变），避免运行
       时被某个 import 副作用追加，让 CI 错过签收。
    """
    declared = set(MODULES_TO_DOCUMENT)
    ignored = set(IGNORED_MODULES)
    classified = declared | ignored
    actual = _enumerate_top_level_python_modules()

    unclassified = actual - classified
    stale = classified - actual
    overlap = declared & ignored

    if unclassified or stale or overlap:
        details: list[str] = []
        if unclassified:
            details.append(
                f"top-level modules with no classification (add to MODULES_TO_DOCUMENT "
                f"to render docs, or to IGNORED_MODULES with a TODO/justification): "
                f"{sorted(unclassified)}"
            )
        if stale:
            details.append(
                f"listed in MODULES_TO_DOCUMENT or IGNORED_MODULES but no matching "
                f"file at project root (stale entry; remove from "
                f"scripts/generate_docs.py): {sorted(stale)}"
            )
        if overlap:
            details.append(
                f"appears in BOTH MODULES_TO_DOCUMENT and IGNORED_MODULES (the two "
                f"sets must be disjoint; pick one): {sorted(overlap)}"
            )
        raise SystemExit(
            "generate_docs.py invariant violation:\n  - " + "\n  - ".join(details)
        )


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
    else:
        # 中文文档保留完整 docstring；签名速查请看英文 signature-only 版本，
        # 与英文页顶部的 cross-link 保持双语对称（双方都给读者一键跳到对侧）。
        lines.append(
            f"> 英文 signature-only 版本（仅函数 / 类签名速查）："
            f"[`docs/api/{module_info['name']}.md`](../api/{module_info['name']}.md)"
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


# Quick navigation 分组：必须覆盖 MODULES_TO_DOCUMENT 中**全部**模块。
# 修改 MODULES_TO_DOCUMENT 时同步更新此处即可（``_assert_quick_nav_covers_all_modules``
# 会在 generate_index 入口 fail-fast 提示遗漏）。
QUICK_NAV_CORE = (
    "config_manager",
    "exceptions",
    "notification_manager",
    "protocol",
    "state_machine",
    "server",
    "server_feedback",
    "server_config",
    "task_queue",
    "web_ui",
)
QUICK_NAV_UTILITY = (
    "config_utils",
    "i18n",
    "shared_types",
    "notification_models",
    "notification_providers",
    "file_validator",
    "enhanced_logging",
)


def _assert_quick_nav_covers_all_modules(modules: list[str]) -> None:
    """守住「``MODULES_TO_DOCUMENT`` ⊆ Quick nav 分组」不变量。

    历史教训
    ---------
    v1.5.x 早期 ``notification_providers`` 漏在 Quick navigation 之外，
    虽然 ``## Modules`` 列表完整 14 项，``### Core/Utility`` 分组仅
    13 项。今天看是「文案漂移」，未来加 ``audio.py`` / ``ssml.py``
    时如果只动 ``MODULES_TO_DOCUMENT`` 不动这两个分组，会再次复发。

    在 ``generate_index`` 入口断言「分组并集 ⊇ 渲染清单」，
    fail-fast + 一次性给出全部缺漏，而不是让 reviewer 翻 200 行 markdown
    数 bullet。
    """
    declared = {Path(m).stem for m in modules}
    in_nav = set(QUICK_NAV_CORE) | set(QUICK_NAV_UTILITY)
    missing = declared - in_nav
    extra = in_nav - declared
    if missing or extra:
        details = []
        if missing:
            details.append(
                f"missing from Quick navigation (add to QUICK_NAV_CORE / "
                f"QUICK_NAV_UTILITY in scripts/generate_docs.py): {sorted(missing)}"
            )
        if extra:
            details.append(
                f"listed in Quick navigation but not in MODULES_TO_DOCUMENT "
                f"(stale entry; remove): {sorted(extra)}"
            )
        raise SystemExit(
            "generate_docs.py invariant violation:\n  - " + "\n  - ".join(details)
        )


def generate_index(modules: list[str], *, lang: str, output_dir_display: str) -> str:
    """生成文档索引"""
    _assert_quick_nav_covers_all_modules(modules)
    _assert_top_level_modules_classified()
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
            "中文 API 参考（含完整 docstring 叙述）。",
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
                "- **protocol**: Protocol version, capabilities, and server clock — single source of truth for the front/back contract",
                "- **state_machine**: Connection / content / interaction state machines (mirrors front-end constants in `state.js`)",
                "- **server**: MCP server entry point — `interactive_feedback` tool registration, multi-task queue lifecycle, notification integration, and the `main()` event loop",
                "- **server_feedback**: `interactive_feedback` MCP tool implementation extracted from `server.py` — task polling, context management, undecorated tool function (registration stays on `server.mcp`)",
                "- **server_config**: MCP server configuration and utility helpers (dataclasses, constants, input validation, response parsing)",
                "- **task_queue**: Task queue",
                "- **web_ui**: Flask Web UI main class — multi-task panel, file uploads, notifications, mDNS publishing, security middleware, and browser bootstrapping",
                "",
                "### Utility modules",
                "",
                "- **config_utils**: Configuration utility helpers",
                "- **i18n**: Lightweight back-end i18n (request-language detection + locale-keyed message lookup)",
                "- **shared_types**: Shared TypedDict definitions",
                "- **notification_models**: Notification data models",
                "- **notification_providers**: Concrete notification backends (Web Push / system sound / Bark / mobile vibration / macOS native)",
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
                "- **protocol**: 协议版本、Capabilities、服务器时钟 —— 前后端契约的单一事实来源",
                "- **state_machine**: 连接 / 内容 / 交互状态机（与前端 `state.js` 常量一一对应）",
                "- **server**: MCP 服务器入口 —— `interactive_feedback` 工具注册、多任务队列生命周期、通知集成与 `main()` 事件循环",
                "- **server_feedback**: 从 `server.py` 抽出的 `interactive_feedback` 工具实现 —— 任务轮询、上下文管理、未装饰的工具函数本体（注册仍在 `server.mcp`）",
                "- **server_config**: MCP 服务器配置与工具函数（数据类、常量、输入验证、响应解析）",
                "- **task_queue**: 任务队列",
                "- **web_ui**: Flask Web UI 主类 —— 多任务面板、文件上传、通知、mDNS 发布、安全中间件与浏览器引导",
                "",
                "### 工具模块",
                "",
                "- **config_utils**: 配置工具函数",
                "- **i18n**: 后端轻量 i18n（请求语言检测 + 本地化消息查表）",
                "- **shared_types**: 共享 TypedDict 类型定义",
                "- **notification_models**: 通知数据模型",
                "- **notification_providers**: 具体通知后端实现（Web Push / 系统声音 / Bark / 移动振动 / macOS 原生）",
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
