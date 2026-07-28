#!/usr/bin/env python3
"""R66 / R99 / R109：CSS 品牌色硬编码漂移检测器（rgba decimal + hex 家族）。

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

R109 收尾："iOS 蓝家族"还有两个变体在 R99 漏检：

* ``#0a84ff`` —— iOS 13+ / macOS dark mode 系统蓝（dark mode systemBlue
  的 hex 直写），实测 ``main.css::1020`` ``.btn-primary-enabled``
  背景色直接硬编码这个值——同性质漂移；
* ``#0056cc`` —— iOS 蓝的 darker variant（hover/active 用 30% 暗色），
  实测 ``main.css::3982`` ``.btn-primary:hover`` 背景色——同性质漂移。

R109 把 hex 端的正则扩成 union（``#007aff|#0a84ff|#0056cc``），
``DEFAULT_HEX_BASELINE`` 从 7 增到 9（= 7 + 1 + 1），与 R65 把不同
alpha 通道（``0.05/0.1/0.5/0.8``）合并到同一条 rgba baseline 的设计
**同构**——同一品牌漂移家族用一条 baseline 锁住，保持简单。后续清理
重构（把 ``#0a84ff`` 替换成 ``var(--brand-accent-dark)`` 等）会让
hex 计数下降，脚本会 ``ℹ️`` 提示同步降 baseline。

本脚本作为 **护栏（guardrail）**：
* 当前 baseline ``34 (rgba decimal) + 9 (hex 家族 = #007aff + #0a84ff +
  #0056cc)`` 处硬编码作为「已知技术债」，允许保留；
* 任何**新增**的 ``rgba(0, 122, 255, X)`` 或 ``#007aff`` /
  ``#0a84ff`` / ``#0056cc`` 直接 fail —— 强迫开发者使用品牌色 / CSS
  变量；
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


DEFAULT_BASELINE = 0


DEFAULT_HEX_BASELINE = 0


_IOS_BLUE_RE = re.compile(r"rgba?\s*\(\s*0\s*,\s*122\s*,\s*255\b")


_IOS_BLUE_HEX_RE = re.compile(r"#(?:007aff|0a84ff|0056cc|0045a0)\b", re.IGNORECASE)


_CSS_COMMENT_RE = re.compile(r"/\*.*?\*/", re.DOTALL)


def strip_css_comments(source: str) -> str:
    """删除 CSS 块注释。"""
    return _CSS_COMMENT_RE.sub("", source)


def count_ios_blue(text: str) -> int:
    """统计 ``text`` 内 iOS 蓝 ``rgba(0, 122, 255, X)`` 出现次数（已假设注释已剔除）。"""
    return len(_IOS_BLUE_RE.findall(text))


def count_ios_blue_hex(text: str) -> int:
    """统计 ``text`` 内 iOS 蓝家族 hex 形式出现次数（已假设注释已剔除）。"""
    return len(_IOS_BLUE_HEX_RE.findall(text))


def find_ios_blue_locations(text: str) -> list[tuple[int, str]]:
    """返回 ``[(line_number, line_content), ...]``。"""
    locations: list[tuple[int, str]] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        if _IOS_BLUE_RE.search(line):
            locations.append((lineno, line.strip()))
    return locations


def find_ios_blue_hex_locations(text: str) -> list[tuple[int, str]]:
    """R99 / R109：返回 iOS 蓝家族 hex 形式 ``[(line_number, line_content), ...]``。"""
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
    """递归扫描 ``root`` 下所有 ``*.css``（排除 ``*.min.css``）。"""
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
            f"R99 / R109：hex 家族（``#007aff`` / ``#0a84ff`` / ``#0056cc``）"
            f"的允许硬编码上限（默认 {DEFAULT_HEX_BASELINE}，即 R109 commit "
            f"时的快照 = 7 + 1 + 1）"
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
            "hex 家族",
            "#007aff / #0a84ff / #0056cc",
            hex_total,
            args.hex_baseline,
            hex_per_file,
        )
        failed = True
    if failed:
        return 1

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
                f"ℹ️  CSS 品牌色检查通过（hex 家族已降低）："
                f"iOS 蓝硬编码 {hex_total} < baseline {args.hex_baseline}\n"
                f"   你似乎重构掉了 {args.hex_baseline - hex_total} 处 hex 家族 "
                f"(``#007aff`` / ``#0a84ff`` / ``#0056cc``)，\n"
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
