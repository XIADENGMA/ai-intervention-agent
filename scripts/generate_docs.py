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

# R76 src/ layout 改造后，源码顶层模块由 ``./*.py`` 迁移到
# ``src/ai_intervention_agent/*.py``。所有"模块发现 / docstring 解析 /
# 不变量校验"路径都以 ``PKG_ROOT`` 为根。文档输出目录依旧是
# ``docs/api`` / ``docs/api.zh-CN``，向后兼容旧链接。
PKG_ROOT = PROJECT_ROOT / "src" / "ai_intervention_agent"

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
    "service_manager.py",
    "shared_types.py",
    "notification_manager.py",
    "notification_models.py",
    "notification_providers.py",
    "task_queue.py",
    "task_queue_singleton.py",
    "web_ui.py",
    "web_ui_config_sync.py",
    "web_ui_mdns.py",
    "web_ui_mdns_utils.py",
    "web_ui_security.py",
    "web_ui_validators.py",
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
    """``src/ai_intervention_agent/*.py`` 下所有顶层模块文件名（不含子包、不含 ``__init__.py``）。

    分类不变量的 LHS。集合语义；顺序不重要。
    R76 src/ layout 改造之前的 LHS 是 ``PROJECT_ROOT.glob('*.py')``——
    迁移之后所有源码移入 ``PKG_ROOT``，扫描入口同步切换。
    """
    return {
        p.name for p in PKG_ROOT.glob("*.py") if p.is_file() and p.name != "__init__.py"
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
    "shared_types",
    "notification_models",
    "notification_providers",
    "file_validator",
    "enhanced_logging",
    "web_ui_config_sync",
    "web_ui_mdns",
    "web_ui_mdns_utils",
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


def generate_index(
    modules: list[str],
    *,
    lang: str,
    output_dir_display: str,
    existing_path: Path | None = None,
) -> str:
    """生成文档索引。

    Custom prefix preservation (R178 follow-up)
    -------------------------------------------

    R169 把 README 的"How it works / Architecture / Production-grade
    middleware / Server self-info / MCP-spec compliance"5 个 section
    手工插入到 ``docs/api/index.md`` 与 ``docs/api.zh-CN/index.md``
    的 ``## Modules`` / ``## 模块列表`` 标题**之前**。这是 R169 提交
    时的设计决策：README 面向使用者（保持简洁），技术细节下沉到 docs
    并优先展示在 API index 顶部，让点进来的读者第一眼就能看懂工具
    的工作原理与中间件链。

    然而 ``generate_docs.py`` 在 R76 之后会按"signatures-only"模板
    完全重写 index.md，运行 ``--check`` 会把 R169 手工块当成 drift —
    这是个真实存在的 CI footgun，已经在 ``scripts/ci_gate.py:222-235``
    挂着两条 ``generate_docs.py --check`` gate。

    本函数现在支持 ``existing_path``：如果指向的 index.md 已存在且包含
    ``## Modules`` / ``## 模块列表`` 标题，则**保留该标题之前的所有
    内容**（前置手工块），只重写从 modules-heading 开始到文件末尾的
    自动生成部分（modules list + quick navigation + footer）。这样：

    * 首次生成时：和老行为完全一致（不存在文件 → 全文写入）。
    * 后续重生时：手工块永久保留，generator 仅维护其声称负责的"模块
      列表 + 分类导航"部分。
    * ``--check`` 模式下：手工块改动不再触发 drift，仅当 modules 列表
      或 quick-navigation 与代码不同步时才报告 drift（这正是 ci_gate
      最初想守的 invariant）。

    Force-regenerate the manual prefix (CR#12 §F-2 escape hatch)
    ------------------------------------------------------------

    如果某个 R-cycle 因为架构改动 / 模块改名 / 中间件链改动需要**主动
    重写**前置手工块（例如 R200 把 ``Production-grade middleware``
    section 完全废弃），preservation 逻辑会"贴心"地保留旧文案 ——
    这是 silent staleness footgun。escape hatch：

    1. ``git rm docs/api/index.md docs/api.zh-CN/index.md``（或手工
       删除两个文件，下一段 ``generate_docs.py`` 看不到旧文件 →
       走 first-time fresh 路径）；
    2. ``uv run python scripts/generate_docs.py --lang en`` 然后
       ``--lang zh-CN``——产生干净的 signatures-only 模板；
    3. **手工**把新的"How it works / Architecture / 你想要的新
       section"重新插入到 ``## Modules`` / ``## 模块列表`` 标题之
       前；
    4. 提交（一次性，本周期之后又回到 preservation 模式）。

    或者更小步：直接编辑 index.md 顶部、删 / 改 / 加 section，下次
    ``--check`` 仍然 pass（preservation 只看 modules-heading 之
    后的字节），新内容就成了下一周期的 "permanent prefix"。这是
    日常迭代的推荐路径——只在大重写时才走 "rm + regen + manual"
    escape hatch。
    """
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
                "- **i18n**: Lightweight back-end i18n (request-language detection + locale-keyed message lookup)",
                "- **shared_types**: Shared TypedDict definitions",
                "- **notification_models**: Notification data models",
                "- **notification_providers**: Concrete notification backends (Web Push / system sound / Bark / mobile vibration / macOS native)",
                "- **file_validator**: File validation",
                "- **enhanced_logging**: Logging enhancements",
                "- **web_ui_config_sync**: Hot-reload callbacks — propagate `feedback.auto_resubmit_timeout` and network-security config changes into running tasks / Web UI instances",
                "- **web_ui_mdns**: mDNS / DNS-SD lifecycle mixin — service discovery, registration, deregistration",
                "- **web_ui_mdns_utils**: mDNS pure helpers — hostname normalisation, virtual-NIC filtering, IPv4 detection",
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
                "- **i18n**: 后端轻量 i18n（请求语言检测 + 本地化消息查表）",
                "- **shared_types**: 共享 TypedDict 类型定义",
                "- **notification_models**: 通知数据模型",
                "- **notification_providers**: 具体通知后端实现（Web Push / 系统声音 / Bark / 移动振动 / macOS 原生）",
                "- **file_validator**: 文件验证",
                "- **enhanced_logging**: 日志增强",
                "- **web_ui_config_sync**: 配置热更新回调 —— 把 `feedback.auto_resubmit_timeout` 与网络安全配置变更同步到运行中的任务 / Web UI 实例",
                "- **web_ui_mdns**: mDNS / DNS-SD 生命周期 Mixin —— 服务发现、注册、注销",
                "- **web_ui_mdns_utils**: mDNS 纯函数辅助 —— 主机名规范化、虚拟网卡过滤、IPv4 探测",
                "",
                "---",
                "",
                f"_文档自动生成于 `{output_dir_display}`_",
            ]
        )

    fresh = "\n".join(lines) + "\n"

    # Custom prefix preservation (R178 follow-up).
    #
    # 如果目标文件已存在且包含 modules-heading，保留 heading 之前的所有
    # 内容（前置手工块），仅替换 heading 起始的自动生成部分。详细动机
    # 见本函数 docstring。
    if existing_path is not None and existing_path.exists():
        modules_heading = "## Modules" if lang == "en" else "## 模块列表"
        existing_text = existing_path.read_text(encoding="utf-8")
        if modules_heading in existing_text and modules_heading in fresh:
            existing_prefix, _ = existing_text.split(modules_heading, 1)
            _, fresh_suffix = fresh.split(modules_heading, 1)
            return existing_prefix + modules_heading + fresh_suffix

    return fresh


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
        # R76：模块源文件迁到 ``src/ai_intervention_agent/``，PKG_ROOT 已指向那里
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
