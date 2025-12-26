#!/usr/bin/env python3
"""
静态资源压缩脚本

功能说明：
    压缩 JavaScript 和 CSS 文件，减少文件大小，提升加载速度。

使用方法：
    python scripts/minify_assets.py [--check] [--force]

参数说明：
    --check: 只检查是否需要压缩，不执行压缩
    --force: 强制重新压缩所有文件

依赖：
    - rjsmin: JavaScript 压缩 (pip install rjsmin)
    - rcssmin: CSS 压缩 (pip install rcssmin)

注意事项：
    - 压缩后的文件保存为 .min.js / .min.css
    - 原始文件不会被修改
    - 仅压缩 static/js 和 static/css 目录下的文件
"""

import argparse
import sys
from pathlib import Path

# 项目根目录
PROJECT_ROOT = Path(__file__).parent.parent

# 静态资源目录
STATIC_JS_DIR = PROJECT_ROOT / "static" / "js"
STATIC_CSS_DIR = PROJECT_ROOT / "static" / "css"

# 需要跳过的文件模式
SKIP_PATTERNS = [
    ".min.js",  # 已经是压缩文件
    ".min.css",  # 已经是压缩文件
    "prism-",  # Prism 组件（已经压缩）
    "tex-mml-",  # MathJax（已经压缩）
    "marked.js",  # 外部库
]


def should_skip(filename: str) -> bool:
    """检查是否应该跳过该文件"""
    for pattern in SKIP_PATTERNS:
        if pattern in filename:
            return True
    return False


def get_minified_name(filepath: Path) -> Path:
    """获取压缩后的文件名"""
    if filepath.suffix == ".js":
        return filepath.with_suffix(".min.js")
    elif filepath.suffix == ".css":
        return filepath.with_suffix(".min.css")
    return filepath


def needs_minification(src: Path, dst: Path) -> bool:
    """检查是否需要压缩"""
    if not dst.exists():
        return True
    return src.stat().st_mtime > dst.stat().st_mtime


def minify_js(content: str) -> str:
    """压缩 JavaScript 代码"""
    try:
        import rjsmin

        return rjsmin.jsmin(content)
    except ImportError:
        print("警告: rjsmin 未安装，跳过 JS 压缩")
        print("安装命令: pip install rjsmin")
        return content


def minify_css(content: str) -> str:
    """压缩 CSS 代码"""
    try:
        import rcssmin

        return rcssmin.cssmin(content)
    except ImportError:
        print("警告: rcssmin 未安装，跳过 CSS 压缩")
        print("安装命令: pip install rcssmin")
        return content


def process_directory(
    directory: Path,
    file_type: str,
    minify_func,
    check_only: bool = False,
    force: bool = False,
):
    """处理目录中的文件

    Returns:
        int: 在 check_only 模式下，返回“需要压缩”的文件数量；否则返回 0。
    """
    if not directory.exists():
        print(f"目录不存在: {directory}")
        return 0

    suffix = f".{file_type}"
    files_processed = 0
    files_skipped = 0
    total_saved = 0
    needs_count = 0

    for filepath in directory.glob(f"*{suffix}"):
        # 跳过已压缩的文件
        if should_skip(filepath.name):
            files_skipped += 1
            continue

        minified_path = get_minified_name(filepath)

        # 检查是否需要压缩
        if not force and not needs_minification(filepath, minified_path):
            files_skipped += 1
            continue

        if check_only:
            print(f"需要压缩: {filepath.name}")
            files_processed += 1
            needs_count += 1
            continue

        # 读取原始文件
        try:
            content = filepath.read_text(encoding="utf-8")
            original_size = len(content.encode("utf-8"))

            # 压缩
            minified = minify_func(content)
            minified_size = len(minified.encode("utf-8"))

            # 保存压缩后的文件
            minified_path.write_text(minified, encoding="utf-8")

            # 计算节省的空间
            saved = original_size - minified_size
            saved_percent = (saved / original_size * 100) if original_size > 0 else 0
            total_saved += saved

            print(f"✅ {filepath.name} -> {minified_path.name}")
            print(f"   原始大小: {original_size:,} bytes")
            print(f"   压缩后:  {minified_size:,} bytes")
            print(f"   节省:    {saved:,} bytes ({saved_percent:.1f}%)")
            print()

            files_processed += 1

        except Exception as e:
            print(f"❌ 处理失败 {filepath.name}: {e}")

    print(f"处理完成: {files_processed} 个文件, 跳过 {files_skipped} 个")
    if total_saved > 0:
        print(f"总共节省: {total_saved:,} bytes ({total_saved / 1024:.1f} KB)")
    return needs_count


def main():
    parser = argparse.ArgumentParser(description="静态资源压缩脚本")
    parser.add_argument("--check", action="store_true", help="只检查，不执行压缩")
    parser.add_argument("--force", action="store_true", help="强制重新压缩所有文件")
    args = parser.parse_args()

    print("=" * 50)
    print("静态资源压缩工具")
    print("=" * 50)

    if args.check:
        print("模式: 检查模式（不执行压缩）")
    elif args.force:
        print("模式: 强制压缩所有文件")
    else:
        print("模式: 增量压缩（只压缩修改过的文件）")

    print()

    # 处理 JavaScript 文件
    print("📦 处理 JavaScript 文件...")
    print("-" * 40)
    needs_js = process_directory(STATIC_JS_DIR, "js", minify_js, args.check, args.force)
    print()

    # 处理 CSS 文件
    print("🎨 处理 CSS 文件...")
    print("-" * 40)
    needs_css = process_directory(
        STATIC_CSS_DIR, "css", minify_css, args.check, args.force
    )
    print()

    print("=" * 50)
    if args.check:
        total = needs_js + needs_css
        if total > 0:
            print(
                f"❌ 检查失败：发现 {total} 个静态资源需要重新生成 .min 文件。"
                "请运行：python scripts/minify_assets.py"
            )
            sys.exit(1)
        print("✅ 检查通过：所有 .min 文件都是最新的。")
    else:
        print("完成！")


if __name__ == "__main__":
    main()
