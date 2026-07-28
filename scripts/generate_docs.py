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

PROJECT_ROOT = Path(__file__).parent.parent


PKG_ROOT = PROJECT_ROOT / "src" / "ai_intervention_agent"


MODULES_TO_DOCUMENT = [
    "config_manager.py",
    "config_utils.py",
    "exceptions.py",
    "feedback_types.py",
    "i18n.py",
    "mcp_tool_call_metrics.py",
    "protocol.py",
    "remote_environment.py",
    "runtime_constants.py",
    "rw_lock.py",
    "state_machine.py",
    "server.py",
    "server_feedback.py",
    "server_config.py",
    "service_manager.py",
    "shared_types.py",
    "sse_event_schemas.py",
    "notification_manager.py",
    "notification_models.py",
    "notification_providers.py",
    "task_constants.py",
    "task_queue.py",
    "task_queue_singleton.py",
    "web_ui.py",
    "web_ui_config_sync.py",
    "web_ui_mdns.py",
    "web_ui_mdns_utils.py",
    "web_ui_rate_limiter.py",
    "web_ui_security.py",
    "web_ui_validators.py",
    "web_ui_wsgi.py",
    "file_validator.py",
    "enhanced_logging.py",
]


IGNORED_MODULES: frozenset[str] = frozenset()
"""项目根 ``*.py`` 中"故意不渲染 docs"的清单。

v1.5.x round-8 完成 7 个 docs-debt 模块的 graduation 之后，集合
归零——所有项目根 ``*.py`` 都进入 ``MODULES_TO_DOCUMENT``。保留为
``frozenset[str]``（不是 ``frozenset()`` 的字面量）让类型注解仍
被 IDE / ty 静态识别，并且未来一旦需要新增 ignored 条目时不需要
改类型签名，只需 ``frozenset({"foo.py"})`` 一行。

加新 ignored 条目时同步加 ``# TODO(...)`` 注释；与
``test_docs_module_classification_parity::test_ignored_modules_have_todo_marker``
约定一致——空集合时该测试会自动 noop（loop 没有 iteration），
单一条目 / 多条目都会强制 TODO 注释存在。"""


def _enumerate_top_level_python_modules() -> set[str]:
    """``src/ai_intervention_agent/*.py`` 下所有顶层模块文件名（不含子包、不含 ``__init__.py``）。"""
    return {
        p.name for p in PKG_ROOT.glob("*.py") if p.is_file() and p.name != "__init__.py"
    }


def _assert_top_level_modules_classified() -> None:
    """守住「项目根 ``*.py`` ⊆ ``MODULES_TO_DOCUMENT`` ∪ ``IGNORED_MODULES``」不变量。"""
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

        default_idx = i - defaults_offset
        if default_idx >= 0:
            default = node.args.defaults[default_idx]
            arg_str += f" = {ast.unparse(default)}"

        args.append(arg_str)

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

    lines.append(f"# {module_info['name']}")
    lines.append("")

    if lang == "en":
        lines.append(
            f"> For the Chinese version with full docstrings, see: "
            f"[`docs/api.zh-CN/{module_info['name']}.md`](../api.zh-CN/{module_info['name']}.md)"
        )
        lines.append("")
    else:
        lines.append(
            f"> 英文 signature-only 版本（仅函数 / 类签名速查）："
            f"[`docs/api/{module_info['name']}.md`](../api/{module_info['name']}.md)"
        )
        lines.append("")

    if include_docstrings and module_info["docstring"]:
        lines.append(module_info["docstring"])
        lines.append("")

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
                        continue
                    prefix = "async " if method["is_async"] else ""
                    lines.append(
                        f"##### `{prefix}{method['name']}{method['signature']}`"
                    )
                    lines.append("")
                    if include_docstrings and method["docstring"]:
                        lines.append(method["docstring"])
                        lines.append("")

    return "\n".join(lines).rstrip("\n") + "\n"


QUICK_NAV_CORE = (
    "config_manager",
    "exceptions",
    "notification_manager",
    "protocol",
    "state_machine",
    "server",
    "server_feedback",
    "server_config",
    "service_manager",
    "task_queue",
    "task_queue_singleton",
    "web_ui",
    "web_ui_security",
    "web_ui_validators",
)
QUICK_NAV_UTILITY = (
    "config_utils",
    "i18n",
    "mcp_tool_call_metrics",
    "remote_environment",
    "runtime_constants",
    "rw_lock",
    "shared_types",
    "sse_event_schemas",
    "feedback_types",
    "notification_models",
    "notification_providers",
    "task_constants",
    "file_validator",
    "enhanced_logging",
    "web_ui_config_sync",
    "web_ui_mdns",
    "web_ui_mdns_utils",
    "web_ui_rate_limiter",
    "web_ui_wsgi",
)


def _assert_quick_nav_covers_all_modules(modules: list[str]) -> None:
    """守住「``MODULES_TO_DOCUMENT`` ⊆ Quick nav 分组」不变量。"""
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


def generate_index(
    modules: list[str],
    *,
    lang: str,
    output_dir_display: str,
    existing_path: Path | None = None,
) -> str:
    """生成文档索引。"""
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
                "- **service_manager**: Web service orchestration — process lifecycle, HTTP client, Web UI bring-up + health checks",
                "- **task_queue**: Task queue",
                "- **task_queue_singleton**: Lightweight `TaskQueue` singleton accessor decoupled from `server.py` — keeps the Web UI subprocess from pulling in `fastmcp` / `mcp` purely to access the queue (R20.8 startup-latency optimisation)",
                "- **web_ui**: Flask Web UI main class — multi-task panel, file uploads, notifications, mDNS publishing, security middleware, and browser bootstrapping",
                "- **web_ui_security**: Security policy mixin — IP allow/deny lists, CSP headers, network-security config loading (mixed into `WebFeedbackUI` via MRO)",
                "- **web_ui_validators**: Pure validation/normalisation helpers for network-security configs and timeouts (extracted from `web_ui.py`; safe to call from tests / CLI / hot-reload paths)",
                "",
                "### Utility modules",
                "",
                "- **config_utils**: Configuration utility helpers",
                "- **feedback_types**: Lightweight feedback result typing used by Web UI routes without importing Pydantic-heavy configuration modules",
                "- **i18n**: Lightweight back-end i18n (request-language detection + locale-keyed message lookup)",
                "- **mcp_tool_call_metrics**: MCP tool call counter middleware (R187 / T2) — feeds `aiia_mcp_tool_calls_total{tool,status}` Prometheus metric in `/api/system/metrics`",
                "- **runtime_constants**: Cheap-to-import runtime timeout constants shared by Web UI, task queue, and server config",
                "- **rw_lock**: Lightweight read/write lock primitive shared by queue and compatibility tests",
                "- **shared_types**: Shared TypedDict definitions",
                '- **sse_event_schemas**: SSE event schema registry (R198 / Cycle 7) — central definition of every known SSE `event_type` + payload field set; tests assert every `_sse_bus.emit("<literal>", ...)` call site has a matching schema',
                "- **notification_models**: Notification data models",
                "- **notification_providers**: Concrete notification backends (Web Push / system sound / Bark / mobile vibration / macOS native)",
                "- **task_constants**: Cheap-to-import task constants used by task queue and Web UI cold-start paths",
                "- **file_validator**: File validation",
                "- **enhanced_logging**: Logging enhancements",
                "- **remote_environment**: SSH / WSL remote-environment detection (R225) — pure-function probes used by the Web UI startup banner to surface actionable port-forwarding hints when bound to loopback on a remote host",
                "- **web_ui_config_sync**: Hot-reload callbacks — propagate `feedback.auto_resubmit_timeout` and network-security config changes into running tasks / Web UI instances",
                "- **web_ui_mdns**: mDNS / DNS-SD lifecycle mixin — service discovery, registration, deregistration",
                "- **web_ui_mdns_utils**: mDNS pure helpers — hostname normalisation, virtual-NIC filtering, IPv4 detection",
                "- **web_ui_rate_limiter**: Lightweight in-memory Web UI rate limiter — preserves the Flask-Limiter decorator surface without importing `flask_limiter` on the cold path",
                "- **web_ui_wsgi**: Optional WSGI application factory for production-style runners while preserving the local Flask dev-server default",
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
                "- **service_manager**: Web 服务编排层 —— 进程生命周期管理、HTTP 客户端、Web UI 启动与健康检查",
                "- **task_queue**: 任务队列",
                "- **task_queue_singleton**: 轻量级 `TaskQueue` 单例访问器（与 `server.py` 解耦）—— 让 Web UI 子进程不再为了拿一个 task queue 而触发 `fastmcp` / `mcp` 整条依赖链加载（R20.8 启动延迟优化）",
                "- **web_ui**: Flask Web UI 主类 —— 多任务面板、文件上传、通知、mDNS 发布、安全中间件与浏览器引导",
                "- **web_ui_security**: 安全策略 Mixin —— IP 访问控制、CSP 安全头注入、网络安全配置加载（通过 MRO 注入 `WebFeedbackUI`）",
                "- **web_ui_validators**: 网络安全配置 / 超时校验的纯函数（从 `web_ui.py` 抽出；测试 / CLI / 配置热更新均可安全复用）",
                "",
                "### 工具模块",
                "",
                "- **config_utils**: 配置工具函数",
                "- **feedback_types**: Web UI 路由使用的轻量反馈结果类型，避免为了类型导入 Pydantic 较重的配置模块",
                "- **i18n**: 后端轻量 i18n（请求语言检测 + 本地化消息查表）",
                "- **mcp_tool_call_metrics**: MCP 工具调用计数器中间件（R187 / T2）—— 为 `/api/system/metrics` 的 `aiia_mcp_tool_calls_total{tool,status}` Prometheus 指标提供数据源",
                "- **runtime_constants**: 低成本导入的运行时超时常量，供 Web UI、任务队列与 server config 共享",
                "- **rw_lock**: 轻量读写锁原语，供队列与兼容性测试复用",
                "- **shared_types**: 共享 TypedDict 类型定义",
                '- **sse_event_schemas**: SSE 事件 schema 注册表（R198 / Cycle 7）—— 集中定义每种已知 SSE `event_type` 及其 payload 字段集；测试确保 `_sse_bus.emit("<literal>", ...)` 的每个调用点都有匹配的 schema 项',
                "- **notification_models**: 通知数据模型",
                "- **notification_providers**: 具体通知后端实现（Web Push / 系统声音 / Bark / 移动振动 / macOS 原生）",
                "- **task_constants**: 低成本导入的任务常量，供任务队列与 Web UI 冷启动路径使用",
                "- **file_validator**: 文件验证",
                "- **enhanced_logging**: 日志增强",
                "- **remote_environment**: SSH / WSL 远程环境探测（R225）—— 纯函数探针；Web UI 启动横幅据此在 host 为回环且检测到远程会话时，给出可操作的端口转发提示",
                "- **web_ui_config_sync**: 配置热更新回调 —— 把 `feedback.auto_resubmit_timeout` 与网络安全配置变更同步到运行中的任务 / Web UI 实例",
                "- **web_ui_mdns**: mDNS / DNS-SD 生命周期 Mixin —— 服务发现、注册、注销",
                "- **web_ui_mdns_utils**: mDNS 纯函数辅助 —— 主机名规范化、虚拟网卡过滤、IPv4 探测",
                "- **web_ui_rate_limiter**: Web UI 轻量内存限流器 —— 保留 Flask-Limiter 装饰器兼容面，同时不在 cold path 导入 `flask_limiter`",
                "- **web_ui_wsgi**: 可选 WSGI app factory，用于生产风格 runner，同时保留本地 Flask dev-server 默认路径",
                "",
                "---",
                "",
                f"_文档自动生成于 `{output_dir_display}`_",
            ]
        )

    fresh = "\n".join(lines) + "\n"

    if existing_path is not None and existing_path.exists():
        modules_heading = "## Modules" if lang == "en" else "## 模块列表"
        existing_text = existing_path.read_text(encoding="utf-8")
        if modules_heading in existing_text and modules_heading in fresh:
            existing_prefix, _ = existing_text.split(modules_heading, 1)
            _, fresh_suffix = fresh.split(modules_heading, 1)
            return existing_prefix + modules_heading + fresh_suffix

    return fresh


def _write_or_check(path: Path, content: str, *, check: bool, drift: list[Path]) -> str:
    """写入或仅校验是否漂移。"""
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
        filepath = PKG_ROOT / module_file
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
        index_file = output_dir / "index.md"
        index_content = generate_index(
            generated_modules,
            lang=args.lang,
            output_dir_display=args.output,
            existing_path=index_file,
        )
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
