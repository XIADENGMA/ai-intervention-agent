#!/usr/bin/env python3
"""R66：CSS 品牌色硬编码漂移检测器。

背景
----

R64/R65 修复发现：``static/css/main.css`` 内 ``rgba(0, 122, 255, X)``
（iOS system blue）出现 64 次，与项目品牌色（dark mode 紫 ``#a855f7``、
light mode Anthropic Orange ``#d97757``）不一致，造成 light mode 视觉
漂移。R65 已为 7 个高频组件加 light-mode override，但底层 64 处硬编码
仍在 — 完全替换风险大（详见 R65 commit message）。

本脚本作为 **护栏（guardrail）**：
* 当前 baseline 64 处硬编码作为「已知技术债」，允许保留；
* 任何**新增**的 ``rgba(0, 122, 255, X)`` 直接 fail —— 强迫开发者
  使用品牌色 / CSS 变量；
* 后续如果有人把硬编码逐步重构成 ``rgba(var(--brand-accent-rgb), X)``
  之类（baseline 减少），只 warn 提示更新 baseline 数字，不 fail。

用法
----

::

    # 默认扫 static/css/，baseline 64
    uv run python scripts/check_brand_color_consistency.py

    # 自定义 baseline（重构期使用）
    uv run python scripts/check_brand_color_consistency.py --baseline 50

    # 自定义扫描目录
    uv run python scripts/check_brand_color_consistency.py --root my/styles

退出码
------

* 0 — count == baseline 或 count < baseline（允许减少，警告提示）
* 1 — count > baseline（新增了硬编码，必须修复）
* 2 — 参数错误 / I/O 错误

集成
----

通过 ``.pre-commit-config.yaml`` 的 ``local`` repo hook 接入：每次提交
若动了 ``static/css/*.css`` 就跑一次，<200 ms 完成。
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

DEFAULT_ROOT = "static/css"
# R66 baseline 锁定的是「strip 注释后」的实际 CSS 属性值里的硬编码数。
# R66 commit 时手测 64 处含注释引用，剥离注释后剩 34 处实际样式漂移。
# 后续若有 PR 重构这 34 处中的某些用 ``var(--brand-accent-rgb)`` 替换，
# 脚本会 warn 提示同步把 baseline 数字降下来。
DEFAULT_BASELINE = 34

# iOS 系统蓝 RGB 字面量。tolerant 于：
#   - 任意空白（rgba( 0 , 122 , 255 ...）
#   - rgba / rgb 都匹配
#   - alpha 通道无所谓（0.05 / 0.1 / 0.5 / 0.8 等）
_IOS_BLUE_RE = re.compile(r"rgba?\s*\(\s*0\s*,\s*122\s*,\s*255\b")

# CSS 块注释 ``/* ... */`` —— 跨行非贪婪。
_CSS_COMMENT_RE = re.compile(r"/\*.*?\*/", re.DOTALL)


def strip_css_comments(source: str) -> str:
    """删除 CSS 块注释。

    R65 commit 在注释里引用了 ``rgba(0, 122, 255, X)`` 作为 RCA 说明，
    这种文档引用不应计入实际样式硬编码计数；本函数把所有 ``/* ... */``
    去掉再做计数。

    单行行尾 ``//`` 注释 CSS 标准里不存在，故不处理。
    """
    return _CSS_COMMENT_RE.sub("", source)


def count_ios_blue(text: str) -> int:
    """统计 ``text`` 内 iOS 蓝硬编码出现次数（已假设注释已剔除）。"""
    return len(_IOS_BLUE_RE.findall(text))


def find_ios_blue_locations(text: str) -> list[tuple[int, str]]:
    """返回 ``[(line_number, line_content), ...]``。

    line_number 1-based，line_content 是命中所在的整行（去掉首尾空白）。
    用于在 fail 时给开发者完整上下文。
    """
    locations: list[tuple[int, str]] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        if _IOS_BLUE_RE.search(line):
            locations.append((lineno, line.strip()))
    return locations


def scan_css_files(root: Path) -> tuple[int, dict[Path, list[tuple[int, str]]]]:
    """递归扫描 ``root`` 下所有 ``*.css``（排除 ``*.min.css``）。

    返回 ``(total_count, {path: [(lineno, line)]})``。
    """
    total = 0
    per_file: dict[Path, list[tuple[int, str]]] = {}
    for css_path in sorted(root.rglob("*.css")):
        if css_path.name.endswith(".min.css"):
            continue
        try:
            raw = css_path.read_text(encoding="utf-8")
        except OSError as exc:
            print(f"警告：跳过 {css_path}（{exc}）", file=sys.stderr)
            continue
        stripped = strip_css_comments(raw)
        count = count_ios_blue(stripped)
        if count == 0:
            continue
        per_file[css_path] = find_ios_blue_locations(stripped)
        total += count
    return total, per_file


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="检测 CSS 文件中 iOS 系统蓝硬编码相对 baseline 的漂移。"
    )
    parser.add_argument(
        "--root",
        default=DEFAULT_ROOT,
        help=f"扫描目录（默认 {DEFAULT_ROOT}）",
    )
    parser.add_argument(
        "--baseline",
        type=int,
        default=DEFAULT_BASELINE,
        help=f"允许的硬编码上限（默认 {DEFAULT_BASELINE}，即 R66 commit 时的快照）",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="只在失败时输出（适合 pre-commit / CI）",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_arg_parser()
    args = parser.parse_args(argv)

    root = Path(args.root)
    if not root.exists():
        print(f"错误：扫描根目录不存在 → {root}", file=sys.stderr)
        return 2

    total, per_file = scan_css_files(root)

    if total > args.baseline:
        print(
            f"❌ CSS 品牌色检查失败：iOS 蓝硬编码数量 {total} > baseline {args.baseline}\n"
            f"   新增了 {total - args.baseline} 处 ``rgba(0, 122, 255, X)``。\n"
            f"   请使用品牌色（dark mode 紫 #a855f7 / light mode Orange #d97757），\n"
            f"   或为新组件同时添加 ``[data-theme='light']`` override（参考 R65）。\n",
            file=sys.stderr,
        )
        for path, locs in per_file.items():
            try:
                rel = path.relative_to(Path.cwd())
            except ValueError:
                rel = path
            print(f"   {rel}（{len(locs)} 处）：", file=sys.stderr)
            for lineno, line in locs[:5]:
                snippet = line if len(line) <= 100 else line[:97] + "..."
                print(f"     L{lineno}: {snippet}", file=sys.stderr)
            if len(locs) > 5:
                print(f"     ... 共 {len(locs)} 处，已截断显示", file=sys.stderr)
        return 1

    if total < args.baseline:
        print(
            f"ℹ️  CSS 品牌色检查通过（且降低）：iOS 蓝硬编码 {total} < baseline "
            f"{args.baseline}\n"
            f"   你似乎重构掉了 {args.baseline - total} 处硬编码，建议把脚本里的\n"
            f"   ``DEFAULT_BASELINE`` 同步降到 {total} 锁定本次进度。"
        )
        return 0

    if not args.quiet:
        print(
            f"✅ CSS 品牌色检查通过：iOS 蓝硬编码 {total}（== baseline {args.baseline}）"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
