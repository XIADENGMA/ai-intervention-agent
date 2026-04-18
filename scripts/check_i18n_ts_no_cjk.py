#!/usr/bin/env python3
"""CI 门禁：禁止 VSCode 扩展宿主 TypeScript 源文件里出现硬编码 CJK 字面量。

背景
----
`packages/vscode/*.ts` 是 VSCode 扩展宿主（extension host）代码，跑在 Node 侧
而不是 webview 里。其用户可见文本（`showErrorMessage` / `showWarningMessage`
/ `statusBar.text` 等）必须走 ``vscode.l10n.t(...)`` → ``l10n/bundle.l10n.*.json``
这条真源链。诊断日志（`Logger.debug/warn`）也同样要走 l10n，避免 zh-CN 机器
被迫输出英文日志，或 en 用户 IDE 里看到中文警告。

为了防止 P8 之后有新的 CJK 字面量偷偷回流，我们挂一道 TS 层门禁，和
``check_i18n_js_no_cjk.py`` 互补：

- JS gate：扫描 ``static/js/*.js`` 和 ``packages/vscode/*.js``
- TS gate：扫描 ``packages/vscode/*.ts``（extension host + 类型共享）

实现细节
--------
- 扫描范围：``packages/vscode`` 下所有 ``*.ts`` 源文件。
- 跳过目录：``dist/``（tsc 产物）、``node_modules/``、``out/``、``.vscode-test/``、
  ``vendor/``、``mathjax/``、以及 ``packages/vscode/test/*`` 下的测试文件（测试
  用例对 CJK 字符串做断言是合法的，前提是这些断言对应的源文件本身已经 i18n
  化。测试目录用独立 CI 检查保证）。
- 使用轻量词法扫描：先把 ``/* */`` 块注释和 ``//`` 行注释替换成等宽空白（保持
  行号不变），再按 ``'…'`` / ``"…"`` / ```…``` 三种字面量匹配。
- 显式豁免：若某一行带 ``// aiia:i18n-allow-cjk`` 注释，该行 CJK 字符串跳过。

退出码
------
- 0：所有 TS 源文件不包含硬编码 CJK 字符串字面量。
- 1：至少有一个违反项；逐行输出位置与内容。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_VSCODE_ROOT = ROOT / "packages" / "vscode"

CJK_RE = re.compile(
    r"["
    r"\u4e00-\u9fff"  # CJK Unified Ideographs
    r"\u3040-\u309f"  # Hiragana
    r"\u30a0-\u30ff"  # Katakana
    r"\uac00-\ud7af"  # Hangul Syllables
    r"]"
)

STRING_RE = re.compile(
    # Negative lookbehind for backslash prevents a `\`` appearing inside a
    # regex literal or already-escaped context from being mistaken for a
    # fresh template-literal opener. Concretely: `html.match(/`/g)` contains
    # a raw backtick inside a regex literal, which without the lookbehind
    # would pair up with later backticks and cause the scanner to report
    # ghost CJK hits inside surrounding HTML template literals.
    r"(?<!\\)'([^'\\\n]*(?:\\.[^'\\\n]*)*)'"
    r"|(?<!\\)\"([^\"\\\n]*(?:\\.[^\"\\\n]*)*)\""
    r"|(?<!\\)`([^`\\]*(?:\\.[^`\\]*)*)`",
    re.DOTALL,
)

BLOCK_COMMENT_RE = re.compile(r"/\*.*?\*/", re.DOTALL)
LINE_COMMENT_RE = re.compile(r"//[^\n]*")
ALLOW_MARKER = "aiia:i18n-allow-cjk"

_SKIP_PREFIXES: tuple[str, ...] = (
    "packages/vscode/dist/",
    "packages/vscode/node_modules/",
    "packages/vscode/out/",
    "packages/vscode/.vscode-test/",
    "packages/vscode/vendor/",
    "packages/vscode/mathjax/",
    "packages/vscode/test/",
)


def _strip_comments(src: str) -> str:
    def _blank(match: re.Match[str]) -> str:
        span = match.group(0)
        return re.sub(r"[^\n]", " ", span)

    src = BLOCK_COMMENT_RE.sub(_blank, src)
    src = LINE_COMMENT_RE.sub(_blank, src)
    return src


def _iter_ts_source_files() -> list[Path]:
    if not _VSCODE_ROOT.exists():
        return []
    paths: list[Path] = []
    for path in sorted(_VSCODE_ROOT.rglob("*.ts")):
        if path.name.endswith(".d.ts"):
            continue
        rel = path.relative_to(ROOT).as_posix()
        if any(rel.startswith(prefix) for prefix in _SKIP_PREFIXES):
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
    src = path.read_text(encoding="utf-8")
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


def collect_violations() -> list[tuple[Path, int, str]]:
    offenders: list[tuple[Path, int, str]] = []
    for path in _iter_ts_source_files():
        for line, literal in scan_file(path):
            offenders.append((path, line, literal))
    return offenders


def main(argv: list[str] | None = None) -> int:
    violations = collect_violations()
    for path, line, literal in violations:
        rel = path.relative_to(ROOT).as_posix()
        snippet = literal if len(literal) < 80 else literal[:77] + "..."
        print(f"{rel}:{line}: hardcoded CJK string literal: {snippet!r}")
    if violations:
        print(
            f"\nFound {len(violations)} hardcoded CJK string literal(s) in "
            f"packages/vscode/*.ts. Wrap user-visible text in vscode.l10n.t(...) "
            f"and add the English source string to packages/vscode/l10n/"
            f"bundle.l10n.json (and matching locale bundles), or tag the line "
            f"with '// {ALLOW_MARKER}' if the literal is deliberately hardcoded.",
            file=sys.stderr,
        )
        return 1
    print("OK: no hardcoded CJK string literals in packages/vscode/*.ts")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
