"""R896：标签栏下方的“循环信息卡片”去掉，代码块鼠标移上去不再有动效。

现象
====

* 任务带 loop 字段（``loop_id`` / ``loop_phase`` / ``iteration_label`` / ``loop_objective`` /
  ``success_criteria``）时，Web 页面和 VS Code 面板的标签栏下面会多出一张卡片：loop id、阶段、轮次三个小标签，
  “循环目标”“完成标准”两行，还有一个“历史轮次”折叠面板（点开会请求 ``GET /api/loops``）。真实 Chrome 里这张卡片
  占了约 140 px 的高度，维护者觉得它占位置、没什么用，要求整个清掉。
* 鼠标移到代码块上，容器会突然多出一层大投影（暗色主题还把边框提亮）。基础规则本来写着 ``box-shadow: none``、
  ``transition: none``，旁边还有几条“取消 hover 效果”的空规则，但样式表后面又有两条同选择器的规则把投影加了回来，
  层叠的结果是 hover 有效果。维护者要求去掉这个效果。

现在
====

* 卡片整个去掉：Web 的 ``#task-loop-context`` 和 VS Code 的 ``#taskLoopContext`` 两块标记，两边的样式、渲染脚本和
  “历史轮次”脚本（``updateLoopContext``、``toggleLoopHistory`` 等），两边的文案键（Web 的 ``page.loop*`` 八个，
  VS Code 的 ``ui.loop.*`` 八个，含 pseudo 语言和 ``i18n-keys.d.ts``）都没有了。
* 留下的：后端对 ``loop_*`` 的接收、存储、沿用（R803）、台账和 ``GET /api/loops``；任务标签上的 ``iter-3`` 小徽标
  （``.task-tab-iter``）；``header_label`` 的 ``updateHeaderChip``。因为页面不再显示这些字段，``interactive_feedback``
  的参数描述不再说“显示在提示上方”，``success_criteria`` 还提醒 agent：人必须读到的内容写进 ``message``。
* 代码块容器没有任何 ``:hover`` 规则（也没有互相抵消的空规则）；它的投影在任何状态下都是 ``none``。复制按钮自己的
  hover 变色（浅色主题）不动，VS Code 面板的代码块工具栏也不动。

契约
====

1. Web 的模板、脚本、样式（含压缩版）里找不到卡片的任何标记、函数、类名、文案键和 ``/api/loops`` 请求；
2. VS Code 的 ``webview.ts`` / ``webview-ui.js`` / ``webview.css`` / ``i18n-keys.d.ts`` 里同样找不到，面板脚本也不再读
   ``loop_id`` 等字段；
3. 六个语言文件（Web 三个 + VS Code 三个）和两个 pseudo 文件里没有 loop 文案键；
4. 任务标签上的 ``iteration_label`` 徽标、``updateHeaderChip`` 两边都还在；
5. ``interactive_feedback`` 仍带五个 ``loop_*`` 参数，``GET /api/loops`` 仍在；五个参数描述里没有“页面会显示它”的旧说法，
   ``success_criteria`` 提醒写进 ``message``，``iteration_label`` 说明它是标签上的徽标；
6. ``main.css`` 与 ``main.min.css`` 里没有任何选择器同时含 ``code-block-container`` 和 ``:hover``；以代码块容器为主体的规则
   （任何伪类）的 ``box-shadow`` 只能是 ``none``、``transform`` 只能是 ``none``；复制按钮在浅色主题里仍有自己的 hover 变色。
"""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
PACKAGE = REPO_ROOT / "src" / "ai_intervention_agent"
VSCODE = REPO_ROOT / "packages" / "vscode"

WEB_HTML = PACKAGE / "templates" / "web_ui.html"
WEB_JS = PACKAGE / "static" / "js" / "multi_task.js"
WEB_JS_MIN = PACKAGE / "static" / "js" / "multi_task.min.js"
WEB_CSS = PACKAGE / "static" / "css" / "main.css"
WEB_CSS_MIN = PACKAGE / "static" / "css" / "main.min.css"
WEB_LOCALES = PACKAGE / "static" / "locales"
VS_TS = VSCODE / "webview.ts"
VS_JS = VSCODE / "webview-ui.js"
VS_CSS = VSCODE / "webview.css"
VS_LOCALES = VSCODE / "locales"
VS_KEY_TYPES = VSCODE / "i18n-keys.d.ts"
SERVER_FEEDBACK = PACKAGE / "server_feedback.py"
TASK_ROUTES = PACKAGE / "web_ui_routes" / "task.py"

LANGS = ["en", "zh-CN", "zh-TW", "_pseudo/pseudo"]
LOOP_PARAMS = [
    "loop_id",
    "loop_objective",
    "loop_phase",
    "success_criteria",
    "iteration_label",
]

# 卡片留下的痕迹：标记 / 类名 / 函数 / 文案键 / 请求。
WEB_LEFTOVERS = [
    "task-loop-context",
    "loop-context-",
    "loop-chip",
    "loop-history",
    "loop-objective",
    "loop-criteria",
    "updateLoopContext",
    "LoopHistory",
    "_loopContextTaskId",
    "_loopHistoryGen",
    "page.loop",
    "/api/loops",
]
VSCODE_LEFTOVERS = [
    "task-loop-context",
    "taskLoopContext",
    "loop-context-",
    "loop-chip",
    "loopChip",
    "loop-history",
    "loopHistory",
    "loopObjective",
    "loopCriteria",
    "updateLoopContext",
    "LoopHistory",
    "currentLoopId",
    "currentLoopTaskId",
    "ui.loop.",
    "/api/loops",
]
# 面板脚本不再读这些字段（只有标签上的 iteration_label 徽标还读 iteration_label）。
VSCODE_SCRIPT_ONLY = ["loop_id", "loop_objective", "loop_phase", "success_criteria"]

# 参数描述里“页面会显示它”的旧说法。
STALE_PHRASES = [
    "above the prompt",
    "loop context",
    "grouped in the ui",
    "rendered alongside",
    "shown to the reviewer",
    "helps the reviewer",
    "human reviewer can",
]


# --------------------------------------------------------------------------- helpers


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _strip_comments(css: str) -> str:
    return re.sub(r"/\*.*?\*/", "", css, flags=re.S)


def _declarations(block: str) -> dict[str, str]:
    found: dict[str, str] = {}
    for part in block.split(";"):
        if ":" in part:
            name, value = part.split(":", 1)
            found[name.strip()] = " ".join(value.replace("!important", "").split())
    return found


def _rules(css: str) -> list[tuple[str, dict[str, str]]]:
    """(选择器, {属性: 值})，去掉注释；``@media`` 里的规则也会被取到。"""
    css = _strip_comments(css)
    return [
        (" ".join(m.group(1).split()), _declarations(m.group(2)))
        for m in re.finditer(r"([^{}]+)\{([^{}]*)\}", css)
    ]


def _selectors(css: str) -> list[str]:
    """逗号分开的每一个选择器各算一个。"""
    return [
        part.strip()
        for selector, _ in _rules(css)
        for part in selector.split(",")
        if part.strip()
    ]


def _interactive_feedback_params() -> dict[str, str | None]:
    """``interactive_feedback`` 每个参数的描述（读源码，不导入包）。"""
    tree = ast.parse(_text(SERVER_FEEDBACK))
    function = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.AsyncFunctionDef)
        and node.name == "interactive_feedback"
    )
    args = function.args
    positional = args.posonlyargs + args.args
    defaults: list[ast.expr | None] = [None] * (len(positional) - len(args.defaults))
    defaults += list(args.defaults)
    pairs = list(zip(positional, defaults, strict=True))
    pairs += list(zip(args.kwonlyargs, args.kw_defaults, strict=True))
    found: dict[str, str | None] = {}
    for arg, default in pairs:
        description: str | None = None
        if isinstance(default, ast.Call):
            for keyword in default.keywords:
                if keyword.arg == "description":
                    try:
                        value = ast.literal_eval(keyword.value)
                    except ValueError:  # 不是字面量（常量名、f-string）
                        continue
                    description = value if isinstance(value, str) else None
        found[arg.arg] = description
    return found


# ------------------------------------------------------- 1. Web：卡片整个没有了


@pytest.mark.parametrize(
    "path", [WEB_HTML, WEB_JS, WEB_JS_MIN, WEB_CSS, WEB_CSS_MIN], ids=lambda p: p.name
)
def test_the_web_files_have_no_trace_of_the_loop_card(path: Path) -> None:
    text = _text(path)
    left = [marker for marker in WEB_LEFTOVERS if marker in text]
    assert left == [], f"{path.name} 里还留着循环信息卡片的痕迹：{left}"


@pytest.mark.parametrize("path", [WEB_CSS, WEB_CSS_MIN], ids=lambda p: p.name)
def test_no_web_selector_names_a_loop_class(path: Path) -> None:
    left = sorted({s for s in _selectors(_text(path)) if "loop-" in s or "loop_" in s})
    assert left == [], f"{path.name} 里还有 loop 类的选择器：{left}"


# --------------------------------------------------- 2. VS Code：同样没有了


@pytest.mark.parametrize(
    "path", [VS_TS, VS_JS, VS_CSS, VS_KEY_TYPES], ids=lambda p: p.name
)
def test_the_vscode_files_have_no_trace_of_the_loop_card(path: Path) -> None:
    text = _text(path)
    left = [marker for marker in VSCODE_LEFTOVERS if marker in text]
    assert left == [], f"{path.name} 里还留着循环信息卡片的痕迹：{left}"


def test_the_panel_script_no_longer_reads_the_loop_fields() -> None:
    text = _text(VS_JS)
    left = [name for name in VSCODE_SCRIPT_ONLY if name in text]
    assert left == [], f"webview-ui.js 还在读 {left}"


def test_no_vscode_selector_names_a_loop_class() -> None:
    left = sorted({s for s in _selectors(_text(VS_CSS)) if "loop" in s})
    assert left == [], f"webview.css 里还有 loop 类的选择器：{left}"


# ------------------------------------------------------- 3. 文案键：六个语言文件


@pytest.mark.parametrize("lang", LANGS)
def test_the_web_locales_have_no_loop_words(lang: str) -> None:
    page = json.loads(_text(WEB_LOCALES / f"{lang}.json"))["page"]
    left = sorted(key for key in page if key.lower().startswith("loop"))
    assert left == [], f"Web {lang}.json 的 page 里还有 {left}"


@pytest.mark.parametrize("lang", LANGS)
def test_the_vscode_locales_have_no_loop_words(lang: str) -> None:
    ui = json.loads(_text(VS_LOCALES / f"{lang}.json"))["ui"]
    assert "loop" not in ui, f"VS Code {lang}.json 的 ui 里还有 loop 命名空间"


# ------------------------------------------------------ 4. 留下的：徽标和短标签


def test_the_tab_still_shows_the_iteration_badge() -> None:
    for path in (WEB_JS, VS_JS):
        text = _text(path)
        assert "task-tab-iter" in text, path.name
        assert "task.iteration_label" in text, path.name
    for path in (WEB_CSS, VS_CSS):
        assert ".task-tab-iter" in _selectors(_text(path)), path.name


def test_the_header_chip_helper_is_still_there() -> None:
    assert "function updateHeaderChip(" in _text(WEB_JS)
    assert "updateHeaderChip(task.header_label)" in _text(WEB_JS)
    assert "function updateHeaderChip(" in _text(VS_JS)
    assert "updateHeaderChip(config.header_label)" in _text(VS_JS)


# ------------------------------------------------ 5. 后端还在，说明不再撒谎


def test_the_tool_still_takes_the_five_loop_fields() -> None:
    params = _interactive_feedback_params()
    for name in LOOP_PARAMS:
        assert params.get(name), f"interactive_feedback 缺少 {name} 的描述"


def test_the_loops_endpoint_is_still_served() -> None:
    assert '"/api/loops"' in _text(TASK_ROUTES)


@pytest.mark.parametrize("name", LOOP_PARAMS)
def test_no_loop_description_promises_that_the_page_shows_it(name: str) -> None:
    description = (_interactive_feedback_params()[name] or "").lower()
    left = [phrase for phrase in STALE_PHRASES if phrase in description]
    assert left == [], f"{name} 的描述还在说页面会显示它：{left}"


def test_success_criteria_tells_the_agent_to_write_what_must_be_read_in_message() -> (
    None
):
    description = _interactive_feedback_params()["success_criteria"] or ""
    assert "not displayed" in description
    assert "`message`" in description


def test_iteration_label_says_it_is_a_badge_on_the_tab() -> None:
    description = _interactive_feedback_params()["iteration_label"] or ""
    assert "badge" in description
    assert "tab" in description


# ------------------------------------------------ 6. 代码块：移上去什么都不变


@pytest.mark.parametrize("path", [WEB_CSS, WEB_CSS_MIN], ids=lambda p: p.name)
def test_the_code_block_container_has_no_hover_rule(path: Path) -> None:
    left = sorted(
        {
            s
            for s in _selectors(_text(path))
            if "code-block-container" in s and ":hover" in s
        }
    )
    assert left == [], f"{path.name} 里代码块容器还有 hover 规则：{left}"


def _container_rules(path: Path) -> list[tuple[str, dict[str, str]]]:
    """以代码块容器为主体（最后一段是它，可带伪类）的规则。"""
    subject = re.compile(r"\.code-block-container(?::[a-z-]+(?:\([^)]*\))?)*$")
    found = []
    for selector, declarations in _rules(_text(path)):
        for part in selector.split(","):
            if subject.search(part.strip()):
                found.append((part.strip(), declarations))
    return found


@pytest.mark.parametrize("path", [WEB_CSS, WEB_CSS_MIN], ids=lambda p: p.name)
def test_the_code_block_container_never_gets_a_shadow_or_a_transform(
    path: Path,
) -> None:
    rules = _container_rules(path)
    assert rules, "找不到代码块容器的规则"
    for selector, declarations in rules:
        assert declarations.get("box-shadow", "none") == "none", (
            selector,
            declarations,
        )
        assert declarations.get("transform", "none") == "none", (selector, declarations)


@pytest.mark.parametrize("path", [WEB_CSS, WEB_CSS_MIN], ids=lambda p: p.name)
def test_the_code_block_container_does_not_transition(path: Path) -> None:
    base = [d for s, d in _container_rules(path) if s == ".code-block-container"]
    assert base, "找不到 .code-block-container 的基础规则"
    assert any(d.get("transition") == "none" for d in base)
    assert any(d.get("box-shadow") == "none" for d in base)


def test_the_copy_button_keeps_its_own_hover_in_the_light_theme() -> None:
    rules = dict(_rules(_text(WEB_CSS)))
    rest = rules['[data-theme="light"] .copy-button']
    hover = rules['[data-theme="light"] .copy-button:hover']
    assert hover["background"] != rest["background"]
