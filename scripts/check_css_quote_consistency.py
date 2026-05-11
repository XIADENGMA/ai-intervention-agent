#!/usr/bin/env python3
"""R174 / CR#10 F-1：CSS 字符串引号一致性漂移检测器。

背景
----

R169 之后的 commit ``73d9980`` 用 prettier 把 ``main.css`` 的字符串引号一次性
收敛到 **double-quote** 一致风格：

* ``@import url("./tri-state-panel.css")`` （url() 内字符串 = 双引号）
* ``font-family: "Segoe UI", ...`` （多词 font-family 名 = 双引号）
* ``[data-theme="light"]`` （属性选择器值 = 双引号）

但仓库**没有 prettier / stylelint 配置** —— 这次重格式化是一次性的、靠人
工运行。Code Review #10 F-1 标记了这个风险：后续 PR 可能再次引入 single-
quote 字符串（在 ``[data-theme='dark']`` / ``url('./icon.svg')`` /
``content: 'hello'`` 等位置），让 CSS 整洁度悄悄退化。

本脚本作为护栏（guardrail）：

* 扫描 ``src/ai_intervention_agent/static/css/*.css``（排除 ``.min.css``）；
* 统计"裸露"的 single-quote 字符串 —— 跳过 ``url(...)`` 内部（合法地嵌套 SVG
  ``xmlns='http://...'`` 时引号需要交错）和 ``/* ... */`` 注释；
* 当前 baseline ``0`` 处违规作为收敛后基线 —— 任何**新增**的"裸露"
  single-quote 字符串直接 fail，强迫开发者用 double-quote 写新代码；
* 后续如果决定迁回 single-quote，把 ``DEFAULT_BASELINE`` 调成具体的允许
  数字即可，不需要重新设计护栏框架。

设计要点（与 ``check_brand_color_consistency.py`` 同模式）
--------------------------------------------------------

* 一条 baseline + 一个文件夹 + 一个正则 —— 与 R66 / R99 / R109 的家族
  对齐，避免发明新约定让 maintainer 学习成本翻倍。
* ``--quiet`` 让 hook 在 baseline 通过时不输出 —— pre-commit 友好。
* 退出码：``0`` 通过 / ``1`` 新增违规 / ``2`` 参数 / I/O 错误。

为什么不引入 prettier
---------------------

完整解决"CSS / Markdown formatter pre-commit hook"需要：

1. ``.prettierrc`` 配置文件（决定 quote / tab / line-width 全套）；
2. ``mirrors-prettier`` pre-commit repo（拖入 Node.js 依赖）；
3. 团队约定哪些文件要被 prettier 接管（CSS / JSON / YAML / MD / TS）；
4. CI 配置 Node.js + npm install。

本仓库已经有 Python (uv) + Node (packages/vscode 用) 双依赖，再加 prettier
会让 CI 矩阵复杂化。R174 这个 baseline-style 守门是"防漂移成本接近 0、覆
盖 80% 价值"的最小可行方案：

* 不能自动 reformat（用户手动跑或一次性脚本）；
* 但**任何漂移**都会在 pre-commit / CI 时被卡住，让维护成本可控。

未来如果决定上完整 prettier，本脚本可以无缝退役（baseline 调 0 + 撤掉 hook
配置即可）。

用法
----

::

    uv run python scripts/check_css_quote_consistency.py
    uv run python scripts/check_css_quote_consistency.py --baseline 5
    uv run python scripts/check_css_quote_consistency.py --root my/styles --quiet
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_TARGETS: tuple[str, ...] = (
    "src/ai_intervention_agent/static/css/main.css",
    "src/ai_intervention_agent/static/css/tri-state-panel.css",
)
"""默认守门文件列表（项目自有 CSS）。

为什么不是整个 ``static/css/`` 目录？
----------------------------------

* ``main.css`` 是 R169 commit ``73d9980`` 用 prettier 收敛过的文件，0 处
  "裸露"single-quote —— 适合上守门。
* ``tri-state-panel.css`` 在 R178 的 follow-up 里被同步收敛到 double-quote
  风格（21 处 attribute-selector 单引号一次性改完），同样 0 处违规，纳入
  守门让 feature-scoped CSS 和 main.css 共享同一基线。
* ``prism.css`` 是上游 prism.js 项目的 vendor 代码（``'Andale Mono'`` 等
  字体名用 single-quote 是其原始风格），**不能改**，故仍排除在外。

未来如果新增项目自有 CSS（例如 ``components/foo.css``），把路径加进
``DEFAULT_TARGETS`` 即可，不需要改 logic。
"""

DEFAULT_BASELINE = 0
"""``main.css`` 在 R169 prettier-reflow 之后达到的稳态基线。"""

# 单引号字符串字面量。``([^']*?)`` 非贪心匹配，避免吃跨行。
SINGLE_QUOTE_LITERAL_RE = re.compile(r"'[^']*?'")
# url(...) 包含的字符串需要排除（SVG ``xmlns='http://...'`` 必须用单引号交错）
URL_BLOCK_RE = re.compile(r"url\([^)]*\)", flags=re.DOTALL)
# /* ... */ 注释块（CSS 唯一注释语法）。``[\s\S]*?`` 非贪心跨行。
COMMENT_BLOCK_RE = re.compile(r"/\*[\s\S]*?\*/")


def _strip_comments_and_url_blocks(src: str) -> str:
    """删除 url(...) + /* ... */ 内容，避免误报合法嵌套引号场景。"""
    src = COMMENT_BLOCK_RE.sub("", src)
    src = URL_BLOCK_RE.sub("", src)
    return src


def count_naked_single_quotes(src: str) -> int:
    """返回 src 里"裸露"的 single-quote 字符串字面量个数。

    "裸露" = 既不在 ``url(...)`` 内（合法的 SVG xmlns 嵌套），也不在
    ``/* ... */`` 注释里。
    """
    stripped = _strip_comments_and_url_blocks(src)
    return len(SINGLE_QUOTE_LITERAL_RE.findall(stripped))


def find_naked_single_quotes_with_lines(src: str) -> list[tuple[int, str]]:
    """返回 (line_number, literal) 列表，给违规 diagnostics 用。"""
    stripped = _strip_comments_and_url_blocks(src)
    out: list[tuple[int, str]] = []
    for m in SINGLE_QUOTE_LITERAL_RE.finditer(stripped):
        # 用 m.start() 算行号 —— stripped 与原 src 的行号偏移会因 sub 缩短
        # 而失真。这里取 stripped 的行号即可，diagnostic 仍能定位大致位置。
        line_no = stripped[: m.start()].count("\n") + 1
        out.append((line_no, m.group(0)))
    return out


def scan_files(
    targets: list[Path],
) -> tuple[int, list[tuple[Path, list[tuple[int, str]]]]]:
    """扫给定的文件列表，返回 (total_violations, per_file_details)。

    不存在的文件 silently skip 并 stderr 记录 —— 让多目标列表里部分缺失
    时仍能完成其他检查（避免一个文件挪位置后整套 hook 全 fail）。
    """
    total = 0
    per_file: list[tuple[Path, list[tuple[int, str]]]] = []
    for path in targets:
        if not path.is_file():
            print(f"WARN: 目标文件不存在: {path}", file=sys.stderr)
            continue
        try:
            src = path.read_text(encoding="utf-8")
        except OSError as exc:
            print(f"WARN: 无法读 {path}: {exc}", file=sys.stderr)
            continue
        details = find_naked_single_quotes_with_lines(src)
        if details:
            per_file.append((path, details))
            total += len(details)
    return total, per_file


def main() -> int:
    parser = argparse.ArgumentParser(
        description="CSS 字符串引号一致性漂移检测（R174 / CR#10 F-1 护栏）",
    )
    parser.add_argument(
        "targets",
        nargs="*",
        help=(
            f"要守门的 CSS 文件（相对仓库根）；留空使用默认 {' '.join(DEFAULT_TARGETS)}"
        ),
    )
    parser.add_argument(
        "--baseline",
        type=int,
        default=DEFAULT_BASELINE,
        help=f'允许的"裸露"single-quote 数量上限（默认 {DEFAULT_BASELINE}）',
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="baseline 通过时不输出（pre-commit 友好）",
    )
    args = parser.parse_args()

    raw_targets: tuple[str, ...] = (
        tuple(args.targets) if args.targets else DEFAULT_TARGETS
    )
    targets = [(REPO_ROOT / t).resolve() for t in raw_targets]
    total, per_file = scan_files(targets)

    if total > args.baseline:
        print(
            f'❌ CSS 引号一致性漂移：发现 {total} 处"裸露"single-quote '
            f"(baseline {args.baseline})",
            file=sys.stderr,
        )
        for css_file, details in per_file:
            rel = css_file.relative_to(REPO_ROOT)
            for line_no, literal in details[:5]:
                # 截断超长 literal（如内嵌 base64 图片）避免日志爆炸
                preview = literal if len(literal) <= 80 else literal[:77] + "..."
                print(f"  {rel}:{line_no}: {preview}", file=sys.stderr)
            if len(details) > 5:
                print(
                    f"  {rel}: ... 共 {len(details)} 处违规（仅展示前 5 行）",
                    file=sys.stderr,
                )
        print(
            "\n如果是有意引入（例如需要 single-quote 字符串），请把 "
            "DEFAULT_BASELINE 改成新的允许值并附 PR 说明；否则把字符串改成 "
            'double-quote ("...")。',
            file=sys.stderr,
        )
        return 1

    if total < args.baseline:
        print(
            f"ℹ️ CSS 引号一致性已收敛：{total} < baseline {args.baseline}。"
            f"请把 DEFAULT_BASELINE 同步降到 {total} 防止回升。",
            file=sys.stderr,
        )
        return 0

    if not args.quiet:
        print(f"✅ CSS 引号一致性检查通过：{total} == baseline {args.baseline}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
