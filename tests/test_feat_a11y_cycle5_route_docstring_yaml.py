"""a11y-audit-cycle-5 Track B (R259f) · Flask route docstring YAML 净洁度。

背景
----

cycle-4 Track D (R259d) 在 ``src/ai_intervention_agent/web_ui_routes/
task.py::freeze_task_deadline`` 发现：docstring 末尾有 ``## 设计原因 /
历史教训`` Markdown 块（含 ``-`` bullets），破坏了 flasgger / Swagger 把
docstring 当 YAML 解析的流程，触发：

    yaml.parser.ParserError: while parsing a block mapping
    expected <block end>, but found '-'

修复方法是把 Markdown 注释整段移到 Python 函数定义**前**的 ``#`` 注释。

本测试守住"任何 ``@route`` decorator 标注的 endpoint，docstring 的 YAML
分隔符 ``---`` 之后**不应出现** Markdown 块级语法"语义，防止：

1. 新 contributor 把设计注释写进 docstring YAML 部分
2. PR review 漏检
3. Swagger UI 渲染期才发现 YAML parser 失败（生产 lazy-loaded
   /apispec 路径才触发）

测试矩阵
--------

扫描 ``src/ai_intervention_agent/web_ui_routes/*.py`` 与
``src/ai_intervention_agent/web_ui.py`` 里的所有 ``@self.app.route`` /
``@app.route`` decorator 装饰的函数 docstring。

对每个 docstring：

1. 若包含 ``---`` 分隔符（flasgger YAML 块开始），取 ``---`` 之后内容
2. 检查内容里**不应出现**以下 Markdown 块级语法：
   - 行首 ``\n##`` 标题（YAML 的 ``#`` 是注释，但 ``##`` 会被
     `expected <block end>` 触发）
   - 行首 ``- ``（YAML 看作 root 级 sequence，无 mapping context 时
     触发 ParserError）
   - 行首 ``> `` blockquote
   - 行首 ``* `` Markdown bullet 替代语法

3. **例外**：YAML 自带的 list syntax 不算违规：
   - ``parameters:\n  - name:`` （indented 2+ spaces 是 YAML sequence
     under mapping key，合法）
   - ``tags:\n  - Tasks`` （同上）

策略：只检查**行首**（column 0）开始的 Markdown 块级标记，避免误命中
YAML 合法 indent。
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
WEB_UI_ROUTES_DIR = REPO_ROOT / "src" / "ai_intervention_agent" / "web_ui_routes"
WEB_UI_PY = REPO_ROOT / "src" / "ai_intervention_agent" / "web_ui.py"


def _route_python_files() -> list[Path]:
    """所有可能含 @route decorator 的 Python 源文件。"""
    files: list[Path] = []
    if WEB_UI_PY.is_file():
        files.append(WEB_UI_PY)
    if WEB_UI_ROUTES_DIR.is_dir():
        files.extend(sorted(WEB_UI_ROUTES_DIR.glob("*.py")))
    return files


# 匹配 @self.app.route 或 @app.route decorator + 紧跟的 def + docstring
# 使用 DOTALL 让 .*? 跨行匹配。
# 由于 def signature 可能跨多行（多参数），用 ([\s\S]+?) 兼容。
_ROUTE_DEF_DOC_RE = re.compile(
    r"""
    @(?:self\.)?app\.route\([^)]*\)        # @route decorator
    (?:\s*@[^\n]+)*                         # 可能跟其它 decorators
    \s*def\s+(?P<name>\w+)                  # def func_name
    \([\s\S]+?\)                            # 参数（可能跨行）
    [^:]*:\s*\n                             # ... return-type 提示等 ... :
    \s*\"\"\"(?P<doc>[\s\S]*?)\"\"\"        # docstring
    """,
    re.VERBOSE,
)


def _extract_yaml_section(docstring: str) -> str | None:
    """flasgger 把 docstring 里 ``---`` 之后当 YAML 解析。返回 YAML 段，
    若无 ``---`` 返回 None。"""
    parts = docstring.split("---", 1)
    if len(parts) < 2:
        return None
    return parts[1]


_MD_BULLET_COL0 = re.compile(r"^(- |\* )", re.MULTILINE)
_MD_HEADING_COL0 = re.compile(r"^##+ ", re.MULTILINE)
_MD_BLOCKQUOTE_COL0 = re.compile(r"^> ", re.MULTILINE)


def _scan_docstring_yaml(yaml_section: str) -> dict[str, list[int]]:
    """返回 YAML 段里**违规** Markdown 块级语法的行号映射：
    ``{"bullet": [...], "heading": [...], "blockquote": [...]}``

    所有行号是 yaml_section 内（1-based），调用方需加 docstring + def 偏移。
    """
    out: dict[str, list[int]] = {"bullet": [], "heading": [], "blockquote": []}
    for match in _MD_BULLET_COL0.finditer(yaml_section):
        line_num = yaml_section[: match.start()].count("\n") + 1
        out["bullet"].append(line_num)
    for match in _MD_HEADING_COL0.finditer(yaml_section):
        line_num = yaml_section[: match.start()].count("\n") + 1
        out["heading"].append(line_num)
    for match in _MD_BLOCKQUOTE_COL0.finditer(yaml_section):
        line_num = yaml_section[: match.start()].count("\n") + 1
        out["blockquote"].append(line_num)
    return out


def _scan_file_for_route_violations(path: Path) -> list[str]:
    """扫描单个文件，返回所有违规消息列表。"""
    text = path.read_text(encoding="utf-8")
    violations: list[str] = []
    for match in _ROUTE_DEF_DOC_RE.finditer(text):
        func_name = match.group("name")
        doc = match.group("doc")
        yaml_section = _extract_yaml_section(doc)
        if yaml_section is None:
            continue  # docstring 无 YAML 段，不检
        result = _scan_docstring_yaml(yaml_section)
        if any(result.values()):
            details: list[str] = []
            if result["bullet"]:
                details.append(f"行首 ``- ``/``* `` bullet (lines {result['bullet']})")
            if result["heading"]:
                details.append(f"行首 ``##`` heading (lines {result['heading']})")
            if result["blockquote"]:
                details.append(f"行首 ``> `` blockquote (lines {result['blockquote']})")
            violations.append(
                f"{path.name}::{func_name} docstring 在 ``---`` 之后含 Markdown "
                f"块级语法 → flasgger YAML parser 失败：" + "；".join(details)
            )
    return violations


class TestRouteDocstringYamlClean(unittest.TestCase):
    """R259f · Flask route docstring 的 YAML 段（``---`` 之后）不应含
    Markdown 块级语法。

    若需要写设计注释，移到 def 上方的 Python ``#`` 注释块。
    """

    def test_all_route_files_have_clean_yaml(self) -> None:
        all_violations: list[str] = []
        for f in _route_python_files():
            all_violations.extend(_scan_file_for_route_violations(f))
        self.assertEqual(
            all_violations,
            [],
            "以下 Flask route docstring 的 YAML 段含 Markdown 块级语法（"
            "会破坏 flasgger swagger 渲染，触发 yaml.parser.ParserError）。"
            "请把设计注释整段移到 def 上方的 Python ``#`` 注释块。"
            "详见 a11y-audit-cycle-4 R259d / cycle-5 R259f 文档：\n  • "
            + "\n  • ".join(all_violations),
        )


class TestRegexSelfTest(unittest.TestCase):
    """元测试：确保 _scan_docstring_yaml 能正确捕获各种 Markdown 违规
    形式与 YAML-legitimate 形式的区分。
    """

    def test_detects_col0_bullet(self) -> None:
        yaml_section = "\ntags:\n  - Tasks\n- bad-root-bullet\n"
        result = _scan_docstring_yaml(yaml_section)
        # `\n  - Tasks` 是 indented YAML sequence，合法
        # `\n- bad-root-bullet` 是 col-0 bullet，违规
        self.assertEqual(len(result["bullet"]), 1)

    def test_detects_col0_heading(self) -> None:
        yaml_section = "\nresponses:\n  200:\n    description: ok\n\n## 设计原因\n"
        result = _scan_docstring_yaml(yaml_section)
        self.assertEqual(len(result["heading"]), 1)

    def test_does_not_detect_indented_yaml_sequence(self) -> None:
        # YAML 内合法的 indented sequence 不应被误检为 bullet
        yaml_section = "\nparameters:\n  - name: task_id\n    in: path\n"
        result = _scan_docstring_yaml(yaml_section)
        self.assertEqual(len(result["bullet"]), 0)

    def test_does_not_detect_yaml_comment_hash(self) -> None:
        # YAML 单 ``#`` 是注释，合法
        yaml_section = "\n# this is a YAML comment\nresponses:\n  200:\n"
        result = _scan_docstring_yaml(yaml_section)
        self.assertEqual(len(result["heading"]), 0)

    def test_extracts_yaml_section_correctly(self) -> None:
        doc = "summary\n---\ntags:\n  - X\n"
        self.assertEqual(_extract_yaml_section(doc), "\ntags:\n  - X\n")
        doc_no_sep = "just text"
        self.assertIsNone(_extract_yaml_section(doc_no_sep))


if __name__ == "__main__":
    unittest.main()
