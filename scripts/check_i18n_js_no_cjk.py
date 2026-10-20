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
- 字面量由 ``scripts/js_source_scan.py`` 的词法扫描器识别（与 TypeScript 自带
  扫描器逐字面量比对过）：注释、字符串里的 ``//``、正则字面量里的引号和反引号、
  嵌套模板字符串都不会让后面的配对错位；``\\uXXXX`` / ``\\u{…}`` / ``\\xNN`` 转义
  先还原再判断，所以写成转义的中文同样会被发现。模板字符串按整个字面量报告，
  ``${…}`` 内的字符串另算。
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

sys.path.insert(0, str(Path(__file__).resolve().parent))

from js_source_scan import string_literals

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

ALLOW_MARKER = "aiia:i18n-allow-cjk"


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


def scan_file(path: Path) -> list[tuple[int, str]]:
    """Return a list of (line_number, literal) violations for a given file."""
    try:
        src = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return []
    lines = src.split("\n")
    return [
        (literal.line, literal.text)
        for literal in string_literals(src)
        if CJK_RE.search(literal.text) and ALLOW_MARKER not in lines[literal.line - 1]
    ]


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
