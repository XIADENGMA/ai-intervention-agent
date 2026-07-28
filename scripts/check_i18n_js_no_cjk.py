#!/usr/bin/env python3
"""CI 门禁：禁止前端 JS 源文件里出现硬编码的中文/日文/韩文字符串字面量。

背景
----
Web UI 的前端代码全部通过 i18n key + locale JSON 提供用户可见文本。为了让
locale 成为唯一真源、方便未来扩展更多语言，我们约束 JS 源文件里不出现
中文/日文/韩文字符（CJK Unified Ideographs、Hiragana、Katakana、Hangul）
的**字符串字面量**。注释里的 CJK 字符不受限制（它们是开发者文档）。

默认作用域是 Web UI（``static/js/*``）。VSCode webview（``packages/vscode/*``）
目前不在本门禁范围内——它会在 P8 阶段单独处理。当 VSCode webview 完成 i18n
清理后，只需把 ``--scope all`` 改为默认即可收口。

实现细节
--------
- 扫描 ``static/js/*.js`` 源文件（默认），或通过 ``--scope all`` 扩展到
  ``packages/vscode/*.js``。
- 忽略 ``.min.js`` 产物（由 minifier 从源文件派生）。
- 忽略 VSCode 侧的 ``dist/``、``test/``、``vendor/``、``mathjax/``、
  ``node_modules/`` 等非 webview 源文件。
- 使用轻量词法扫描：先把 ``/* */`` 块注释和 ``//`` 行注释替换成空白（保留行
  号），再匹配单引号、双引号、模板字符串字面量。
- 支持显式豁免：若某一行带有 ``// aiia:i18n-allow-cjk`` 注释，则本行上的
  CJK 字符串字面量会被跳过（用于极少数需要硬编码 CJK 的场景，如 AI prompt
  默认值）。请谨慎使用。

退出码
------
- 0：所有 JS 源文件不包含硬编码 CJK 字符串字面量。
- 1：至少有一个违反项；逐行输出位置与内容。
- 2：配置错误（``--scope`` 对应的某个 scan root 解析后指向不存在的
  目录）。R101 之前这条路径返回 0（silent skip），与 R76 重布局后
  R88/R100 修过的同款 silent-broken 风险一致；改为 fail-loud 让
  reviewer 立刻看到漂移。
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

_WEBUI_ROOT = ROOT / "src" / "ai_intervention_agent" / "static" / "js"
_VSCODE_ROOT = ROOT / "packages" / "vscode"

SCOPES: dict[str, tuple[Path, ...]] = {
    "webui": (_WEBUI_ROOT,),
    "vscode": (_VSCODE_ROOT,),
    "all": (_WEBUI_ROOT, _VSCODE_ROOT),
}

CJK_RE = re.compile(
    r"["
    r"\u4e00-\u9fff"
    r"\u3040-\u309f"
    r"\u30a0-\u30ff"
    r"\uac00-\ud7af"
    r"]"
)

STRING_RE = re.compile(
    r"(?<!\\)'([^'\\\n]*(?:\\.[^'\\\n]*)*)'"
    r"|(?<!\\)\"([^\"\\\n]*(?:\\.[^\"\\\n]*)*)\""
    r"|(?<!\\)`([^`\\]*(?:\\.[^`\\]*)*)`",
    re.DOTALL,
)


BLOCK_COMMENT_RE = re.compile(r"/\*.*?\*/", re.DOTALL)
ALLOW_MARKER = "aiia:i18n-allow-cjk"


def _strip_comments(src: str) -> str:
    """Zero out ``//`` line comments and ``/* ... */`` block comments while
    preserving line offsets exactly (``\n`` count and total byte length
    unchanged) so that ``stripped[:start].count("\n") + 1`` line-number
    mapping in callers stays accurate."""

    def _blank_block(match: re.Match[str]) -> str:
        span = match.group(0)
        return "".join("\n" if ch == "\n" else " " for ch in span)

    out_lines: list[str] = []
    for line in src.split("\n"):
        idx = line.find("//")
        out_lines.append(line if idx == -1 else line[:idx] + " " * (len(line) - idx))
    intermediate = "\n".join(out_lines)
    return BLOCK_COMMENT_RE.sub(_blank_block, intermediate)


_VSCODE_SKIP_PREFIXES: tuple[str, ...] = (
    "packages/vscode/dist/",
    "packages/vscode/test/",
    "packages/vscode/vendor/",
    "packages/vscode/mathjax/",
    "packages/vscode/node_modules/",
    "packages/vscode/out/",
    "packages/vscode/.vscode-test/",
)


def _iter_js_source_files(roots: tuple[Path, ...]) -> list[Path]:
    paths: list[Path] = []
    for root in roots:
        if not root.exists():
            continue
        for path in sorted(root.rglob("*.js")):
            if path.name.endswith(".min.js"):
                continue
            rel = path.relative_to(ROOT).as_posix()
            if any(rel.startswith(prefix) for prefix in _VSCODE_SKIP_PREFIXES):
                continue
            paths.append(path)
    return paths


def _line_has_allow_marker(original_src: str, line_number: int) -> bool:
    lines = original_src.splitlines()
    if 1 <= line_number <= len(lines):
        return ALLOW_MARKER in lines[line_number - 1]
    return False


def scan_file(path: Path) -> list[tuple[int, str]]:
    """Return a list of (line_number, literal) violations for a given file."""
    try:
        src = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return []
    stripped = _strip_comments(src)

    offenders: list[tuple[int, str]] = []
    for match in STRING_RE.finditer(stripped):
        literal = match.group(1) or match.group(2) or match.group(3) or ""
        if not CJK_RE.search(literal):
            continue
        start = match.start()
        line_number = stripped[:start].count("\n") + 1
        if _line_has_allow_marker(src, line_number):
            continue
        offenders.append((line_number, literal))
    return offenders


def collect_violations(scope: str) -> list[tuple[Path, int, str]]:
    roots = SCOPES[scope]
    offenders: list[tuple[Path, int, str]] = []
    for path in _iter_js_source_files(roots):
        for line, literal in scan_file(path):
            offenders.append((path, line, literal))
    return offenders


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--scope",
        choices=sorted(SCOPES.keys()),
        default="webui",
        help="扫描范围：webui=Web UI（默认，P7 已清理完毕）；"
        "vscode=VSCode webview（P8 待清理，暂不挂 CI）；"
        "all=两者合并。",
    )
    args = parser.parse_args(argv)

    expected_roots = SCOPES[args.scope]
    missing = [r for r in expected_roots if not r.exists()]
    if missing:
        rels = [r.relative_to(ROOT).as_posix() for r in missing]
        print(
            f"ERROR: JS scan root(s) not found for scope={args.scope}: "
            f"{', '.join(rels)}\n"
            f"  Resolved absolute paths: {[str(p) for p in missing]}\n"
            f"  This is a configuration drift, not 'OK' — failing loud "
            f"(exit 2) instead of silently skipping (R101; matches R88/R100).",
            file=sys.stderr,
        )
        return 2

    violations = collect_violations(args.scope)
    for path, line, literal in violations:
        rel = path.relative_to(ROOT).as_posix()
        snippet = literal if len(literal) < 80 else literal[:77] + "..."
        print(f"{rel}:{line}: hardcoded CJK string literal: {snippet!r}")
    if violations:
        print(
            f"\nFound {len(violations)} hardcoded CJK string literal(s) in JS sources "
            f"(scope={args.scope}). Move user-visible text to locale JSON and use "
            f"t('...') instead, or tag the line with '// {ALLOW_MARKER}' if the "
            f"literal is deliberately hardcoded.",
            file=sys.stderr,
        )
        return 1
    print(f"OK: no hardcoded CJK string literals in JS sources (scope={args.scope})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
