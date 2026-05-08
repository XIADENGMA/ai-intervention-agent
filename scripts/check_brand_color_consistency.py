#!/usr/bin/env python3
"""R66 / R99：CSS 品牌色硬编码漂移检测器（rgba decimal + hex 双形式）。

背景
----

R64/R65 修复发现：``src/ai_intervention_agent/static/css/main.css``
内 ``rgba(0, 122, 255, X)``（iOS system blue）出现 64 次，与项目品
牌色（dark mode 紫 ``#a855f7``、light mode Anthropic Orange
``#d97757``）不一致，造成 light mode 视觉漂移。R65 已为 7 个高频组件加
light-mode override，但底层 64 处硬编码仍在 — 完全替换风险大（详见
R65 commit message）。

R99 进一步发现：R66 设计时只考虑了 ``rgba(0, 122, 255, X)`` decimal
形式，遗漏了同色的 hex 形式 ``#007aff``（实测 ``main.css`` 含 7 处
真硬编码，用作边框 / 背景 / 文字色 / linear-gradient stop——与 rgba
decimal 形式同样属于品牌色漂移源，light mode 同样显示成 iOS 蓝）。
R99 单独建立 hex baseline 7，与 R66 的 rgba baseline 34 独立运作。

本脚本作为 **护栏（guardrail）**：
* 当前 baseline `34 (rgba decimal) + 7 (hex)` 处硬编码作为「已知技术债」，
  允许保留；
* 任何**新增**的 ``rgba(0, 122, 255, X)`` 或 ``#007aff`` 直接 fail ——
  强迫开发者使用品牌色 / CSS 变量；
* 后续如果有人把硬编码逐步重构成 ``rgba(var(--brand-accent-rgb), X)``
  之类（baseline 减少），只 warn 提示更新对应 baseline 数字，不 fail。

用法
----

::

    # 默认扫 src/ai_intervention_agent/static/css/，baseline 见 DEFAULT_BASELINE
    uv run python scripts/check_brand_color_consistency.py

    # 自定义两条 baseline（重构期使用）
    uv run python scripts/check_brand_color_consistency.py --baseline 50 --hex-baseline 5

    # 自定义扫描目录
    uv run python scripts/check_brand_color_consistency.py --root my/styles

退出码
------

* 0 — 两条 baseline 都 ``count == baseline`` 或 ``count < baseline``（允许减少，警告提示）
* 1 — 任意一条 baseline ``count > baseline``（新增了硬编码，必须修复）
* 2 — 参数错误 / I/O 错误

集成
----

通过 ``.pre-commit-config.yaml`` 的 ``local`` repo hook 接入：每次提交
若动了 ``src/ai_intervention_agent/static/css/*.css`` 就跑一次，
<200 ms 完成。R76 把 ``static/`` 从仓库根挪进包内（PyPA src/ 布局），
此前默认 ``DEFAULT_ROOT = "static/css"`` 在新布局下指向不存在的目录，
hook 实际上已 silently broken；R88 修复并对齐 hook 的 ``files`` glob。
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

DEFAULT_ROOT = "src/ai_intervention_agent/static/css"
# R66 baseline 锁定的是「strip 注释后」的实际 CSS 属性值里的硬编码数。
# R66 commit 时手测 64 处含注释引用，剥离注释后剩 34 处实际样式漂移。
# 后续若有 PR 重构这 34 处中的某些用 ``var(--brand-accent-rgb)`` 替换，
# 脚本会 warn 提示同步把 baseline 数字降下来。
DEFAULT_BASELINE = 34

# R99 baseline：iOS 系统蓝的 hex 形式（``#007aff``）。R66 设计时只考虑了
# ``rgba(0, 122, 255, X)`` decimal 形式作为漂移源，遗漏了同色的 hex 形式。
# 实测 ``main.css`` 含 7 处真 hex 硬编码（剥注释后），全部为真实样式漂移
# 源（边框 / 背景 / 文字色 / linear-gradient stop），与 R65 治理的 rgba
# decimal 漂移**性质完全相同**——light mode 显示成 iOS 蓝。R99 单独给
# hex 一条 baseline 锁住现状不让恶化，后续清理与 rgba decimal 一并完成。
DEFAULT_HEX_BASELINE = 7

# iOS 系统蓝 RGB 字面量。tolerant 于：
#   - 任意空白（rgba( 0 , 122 , 255 ...）
#   - rgba / rgb 都匹配
#   - alpha 通道无所谓（0.05 / 0.1 / 0.5 / 0.8 等）
_IOS_BLUE_RE = re.compile(r"rgba?\s*\(\s*0\s*,\s*122\s*,\s*255\b")

# R99：iOS 系统蓝的 hex 形式（``#007aff``，大小写均可）。``\b`` 防止误匹
# ``#007affab`` 之类的扩展（CSS 不允许，但 robustness）。R66 docstring 里
# 的 hex 形式 RCA 引用（``#a855f7`` / ``#d97757``）不会误命中——它们都
# 不是 iOS 蓝。
_IOS_BLUE_HEX_RE = re.compile(r"#007aff\b", re.IGNORECASE)

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
    """统计 ``text`` 内 iOS 蓝 ``rgba(0, 122, 255, X)`` 出现次数（已假设注释已剔除）。"""
    return len(_IOS_BLUE_RE.findall(text))


def count_ios_blue_hex(text: str) -> int:
    """统计 ``text`` 内 iOS 蓝 ``#007aff`` hex 形式出现次数（R99，已假设注释已剔除）。"""
    return len(_IOS_BLUE_HEX_RE.findall(text))


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


def find_ios_blue_hex_locations(text: str) -> list[tuple[int, str]]:
    """R99：返回 hex 形式 ``#007aff`` 的 ``[(line_number, line_content), ...]``。"""
    locations: list[tuple[int, str]] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        if _IOS_BLUE_HEX_RE.search(line):
            locations.append((lineno, line.strip()))
    return locations


def scan_css_files(
    root: Path,
) -> tuple[
    int,
    dict[Path, list[tuple[int, str]]],
    int,
    dict[Path, list[tuple[int, str]]],
]:
    """递归扫描 ``root`` 下所有 ``*.css``（排除 ``*.min.css``）。

    返回 ``(rgba_total, rgba_per_file, hex_total, hex_per_file)``。R99 把
    rgba decimal 形式（``rgba(0, 122, 255, X)``）和 hex 形式（``#007aff``）
    的扫描结果分别 yield，让 baseline 各自独立——这是因为它们的 baseline
    数字反映了不同时间段的代码现状（rgba baseline 是 R66 commit 时锁的，
    hex baseline 是 R99 commit 时锁的），混用会让"重构降低 baseline"的
    warning 信号失真。
    """
    rgba_total = 0
    rgba_per_file: dict[Path, list[tuple[int, str]]] = {}
    hex_total = 0
    hex_per_file: dict[Path, list[tuple[int, str]]] = {}
    for css_path in sorted(root.rglob("*.css")):
        if css_path.name.endswith(".min.css"):
            continue
        try:
            raw = css_path.read_text(encoding="utf-8")
        except OSError as exc:
            print(f"警告：跳过 {css_path}（{exc}）", file=sys.stderr)
            continue
        stripped = strip_css_comments(raw)

        rgba_count = count_ios_blue(stripped)
        if rgba_count > 0:
            rgba_per_file[css_path] = find_ios_blue_locations(stripped)
            rgba_total += rgba_count

        hex_count = count_ios_blue_hex(stripped)
        if hex_count > 0:
            hex_per_file[css_path] = find_ios_blue_hex_locations(stripped)
            hex_total += hex_count

    return rgba_total, rgba_per_file, hex_total, hex_per_file


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
        help=(
            f"rgba decimal 形式 ``rgba(0, 122, 255, X)`` 的允许硬编码上限"
            f"（默认 {DEFAULT_BASELINE}，即 R66 commit 时的快照）"
        ),
    )
    parser.add_argument(
        "--hex-baseline",
        type=int,
        default=DEFAULT_HEX_BASELINE,
        help=(
            f"R99：hex 形式 ``#007aff`` 的允许硬编码上限"
            f"（默认 {DEFAULT_HEX_BASELINE}，即 R99 commit 时的快照）"
        ),
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="只在失败时输出（适合 pre-commit / CI）",
    )
    return parser


def _report_violation(
    label: str,
    pattern_human: str,
    total: int,
    baseline: int,
    per_file: dict[Path, list[tuple[int, str]]],
) -> None:
    """fail 路径输出工具——把超 baseline 的硬编码列表打到 stderr。"""
    print(
        f"❌ CSS 品牌色检查失败 ({label})：iOS 蓝硬编码数量 {total} > baseline {baseline}\n"
        f"   新增了 {total - baseline} 处 ``{pattern_human}``。\n"
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


def main(argv: list[str] | None = None) -> int:
    parser = _build_arg_parser()
    args = parser.parse_args(argv)

    root = Path(args.root)
    if not root.exists():
        print(f"错误：扫描根目录不存在 → {root}", file=sys.stderr)
        return 2

    rgba_total, rgba_per_file, hex_total, hex_per_file = scan_css_files(root)

    failed = False

    if rgba_total > args.baseline:
        _report_violation(
            "rgba decimal",
            "rgba(0, 122, 255, X)",
            rgba_total,
            args.baseline,
            rgba_per_file,
        )
        failed = True
    if hex_total > args.hex_baseline:
        _report_violation(
            "hex",
            "#007aff",
            hex_total,
            args.hex_baseline,
            hex_per_file,
        )
        failed = True
    if failed:
        return 1

    # 两条 baseline 任一减少都给 warn 提示同步更新。各自独立，不混用。
    # ``--quiet`` 同时抑制 ℹ️ 与 ✅ 输出（通过时静默，与 R66 原始 quiet
    # 语义保持一致——R99 不该让新加的双 baseline 把 quiet mode 撕破）。
    if not args.quiet:
        if rgba_total < args.baseline:
            print(
                f"ℹ️  CSS 品牌色检查通过（rgba decimal 已降低）："
                f"iOS 蓝硬编码 {rgba_total} < baseline {args.baseline}\n"
                f"   你似乎重构掉了 {args.baseline - rgba_total} 处 ``rgba(0, 122, 255, X)``，\n"
                f"   建议把脚本里的 ``DEFAULT_BASELINE`` 同步降到 {rgba_total} 锁定本次进度。"
            )
        if hex_total < args.hex_baseline:
            print(
                f"ℹ️  CSS 品牌色检查通过（hex 已降低）："
                f"iOS 蓝硬编码 {hex_total} < baseline {args.hex_baseline}\n"
                f"   你似乎重构掉了 {args.hex_baseline - hex_total} 处 ``#007aff``，\n"
                f"   建议把脚本里的 ``DEFAULT_HEX_BASELINE`` 同步降到 {hex_total} 锁定本次进度。"
            )
        if rgba_total == args.baseline and hex_total == args.hex_baseline:
            print(
                f"✅ CSS 品牌色检查通过："
                f"rgba decimal {rgba_total} (== baseline {args.baseline}), "
                f"hex {hex_total} (== baseline {args.hex_baseline})"
            )
    return 0


if __name__ == "__main__":
    sys.exit(main())
