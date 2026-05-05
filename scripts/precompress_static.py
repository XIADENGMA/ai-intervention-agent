"""R20.14-D · 预压缩静态资源 (gzip)。

设计目标
========

Flask 的默认静态资源响应 **不带任何内容压缩**。``static/js/tex-mml-chtml.js``
1.1 MB、``static/js/lottie.min.js`` 300 KB、``static/locales/zh-CN.json``
~11 KB 等首屏可见资源都按原始大小通过 loopback 发给浏览器。本机 loopback
速度快，节流不在带宽上 —— 但远程 / 容器环境 / mDNS LAN 设备访问这些资源
时，gzip 能直接砍 70-85% 的传输量。

为什么是「构建期预压缩」而不是「运行期 on-the-fly」
====================================================

- on-the-fly 压缩（如 ``flask-compress``）每次请求都吃 CPU；R20.10/R20.11
  花了大量精力把冷启动从 425ms 压到 156ms / spawn-to-listen 1922→203ms，
  在 hot path 上塞 zlib.compress 是反方向；
- 构建期一次性产出 ``<file>.gz``，运行时 Flask 只是 send_from_directory
  一份预压缩文件外加 ``Content-Encoding: gzip`` 头。零 CPU、零内存增量；
- 不引入新依赖（Python stdlib ``gzip`` 即可）；Brotli 比 gzip 多 15-20%
  但要 ``pip install brotli``，先 R20.14-D 只做 gzip。

工作流
------

    uv run python scripts/precompress_static.py             # 默认运行
    uv run python scripts/precompress_static.py --check     # 只检查不写
    uv run python scripts/precompress_static.py --clean     # 删除所有 .gz
    uv run python scripts/precompress_static.py --verbose

策略
----

- 遍历 ``static/css``、``static/js``、``static/locales`` 三个目录；
- 跳过 ``< MIN_SIZE_BYTES`` (默认 4 KB) 的小文件（gzip overhead 收益不划算）；
- 跳过已经是压缩格式的文件（``.gz`` / ``.br`` / ``.zip`` / ``.png`` /
  ``.jpg`` / ``.webp`` / ``.woff`` / ``.woff2``） —— 重复 gzip 通常会增大；
- 比较源文件 ``mtime`` 和已有 ``.gz`` 的 mtime，源更新时才重新压缩；
- 写入时用 ``tempfile + os.replace`` 保证原子性，避免半成品文件被 Flask
  picked up 后导致响应错误。

集成
----

应当在 CI / package_vscode_vsix 流水线 / pre-commit 之外的某处批量跑（每
次开发/部署前）。当前阶段不强制集成 —— 留给 R20.14-E 文档里说明。
"""

from __future__ import annotations

import argparse
import gzip
import os
import sys
import tempfile
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

DEFAULT_TARGET_DIRS = (
    REPO_ROOT / "static" / "css",
    REPO_ROOT / "static" / "js",
    REPO_ROOT / "static" / "locales",
)

# R20.14-D：阈值改 500 字节，对齐 flask-compress 的 ``COMPRESS_MIN_SIZE``
# 默认值。原本设 4 KB 的初衷是「太小时 gzip 头 18 字节 overhead 不划算」，
# 但 web_ui.py 里 ``_get_minified_file`` 会把 ``foo.js`` 重定向到 ``foo.min.js``，
# 而 minified 文件经常落在 1-3 KB 区间。如果这层不预压缩，serve_js 拿到
# minified path 时找不到 .gz 副本，就只能 fallback 到 flask-compress 的
# 运行时压缩 —— 失去 R20.14-D 的所有 CPU 节省收益。500 字节是 flask-compress
# 自身的 sweet spot，保持一致避免「flask-compress 想压但我们没预压」的盲区。
MIN_SIZE_BYTES = 500

GZIP_LEVEL = 9  # 离线一次性运行，对压缩速度不敏感，纯求最小体积

# 不应被 gzip 的扩展名 —— 这些已经是压缩格式，再压一次只会变大且浪费 CPU。
SKIP_EXTENSIONS = frozenset(
    {
        ".gz",
        ".br",
        ".zip",
        ".png",
        ".jpg",
        ".jpeg",
        ".webp",
        ".woff",
        ".woff2",
        ".ttf",  # ttf 实际有些可压缩，但 woff2 已经是 OTF/TTF + Brotli，重复压收益小
        ".ico",
    }
)


@dataclass
class Result:
    """单个文件的处理结果。"""

    source: Path
    action: str  # 'compressed' / 'skipped_small' / 'skipped_ext' / 'skipped_fresh' / 'cleaned'
    original_size: int = 0
    compressed_size: int = 0

    @property
    def saved_pct(self) -> float:
        if self.original_size == 0:
            return 0.0
        return (1.0 - self.compressed_size / self.original_size) * 100.0


def _walk_targets(directories: list[Path]) -> Iterator[Path]:
    """走目标目录，按字典序 yield 所有常规文件路径。"""
    for d in directories:
        if not d.exists():
            continue
        for path in sorted(d.rglob("*")):
            if path.is_file():
                yield path


def _should_compress(path: Path) -> tuple[bool, str]:
    """判断单个文件是否值得压缩。

    返回 (should_compress, reason)；reason 用于 ``--verbose`` 输出。
    """
    if path.suffix.lower() in SKIP_EXTENSIONS:
        return False, "skipped_ext"
    try:
        if path.stat().st_size < MIN_SIZE_BYTES:
            return False, "skipped_small"
    except OSError:
        return False, "skipped_stat_error"
    return True, "compressed"


def _is_fresh(source: Path, gz_path: Path) -> bool:
    """判断 ``gz_path`` 是否相对 ``source`` 新鲜（mtime 更晚），新鲜则跳过。"""
    if not gz_path.exists():
        return False
    try:
        return gz_path.stat().st_mtime >= source.stat().st_mtime
    except OSError:
        return False


def compress_file(source: Path, *, level: int = GZIP_LEVEL) -> Result:
    """压缩单个文件，返回 ``Result``。

    - 写入用 ``tempfile.NamedTemporaryFile`` + ``os.replace`` 原子化，避免
      Flask 中途读到半成品 ``.gz`` 文件返回错误响应。
    - level=9 是最大压缩比；预压缩是离线一次性操作，对压缩速度不敏感。
    """
    should, reason = _should_compress(source)
    if not should:
        return Result(source=source, action=reason)

    gz_path = source.with_suffix(source.suffix + ".gz")
    if _is_fresh(source, gz_path):
        return Result(
            source=source,
            action="skipped_fresh",
            original_size=source.stat().st_size,
            compressed_size=gz_path.stat().st_size,
        )

    raw = source.read_bytes()
    compressed = gzip.compress(raw, compresslevel=level, mtime=0)
    # ``mtime=0`` 让输出稳定可复现（reproducible build），同源文件多次跑得到
    # byte-identical 输出，方便 CI 校验「是否需要重新压缩」。

    # 反检：如果 gzip 后比原文件还大（极小文件 + entropy 已高），跳过写入，
    # 让 Flask 回退到 uncompressed。这种情况下保留 ``.gz`` 反而误导。
    if len(compressed) >= len(raw):
        return Result(
            source=source,
            action="skipped_no_gain",
            original_size=len(raw),
            compressed_size=len(compressed),
        )

    # 原子写入：先写临时文件再 rename，确保 Flask 不会读到中间状态。
    tmp_fd, tmp_path = tempfile.mkstemp(
        prefix=".tmp.precompress.", suffix=".gz", dir=str(source.parent)
    )
    try:
        with os.fdopen(tmp_fd, "wb") as fh:
            fh.write(compressed)
        os.replace(tmp_path, gz_path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise

    return Result(
        source=source,
        action="compressed",
        original_size=len(raw),
        compressed_size=len(compressed),
    )


def clean_dir(directory: Path) -> list[Result]:
    """删除目录里的所有 ``.gz`` 副本（``--clean`` 模式）。"""
    results: list[Result] = []
    if not directory.exists():
        return results
    for path in sorted(directory.rglob("*.gz")):
        if path.is_file():
            try:
                path.unlink()
                results.append(Result(source=path, action="cleaned"))
            except OSError:
                # 单文件 unlink 失败不应阻塞整体流程
                pass
    return results


def run(
    *,
    directories: list[Path] | None = None,
    check: bool = False,
    clean: bool = False,
    verbose: bool = False,
) -> dict[str, list[Result]]:
    """主入口。返回 ``{"results": [...]}``。"""
    targets = list(directories) if directories else list(DEFAULT_TARGET_DIRS)
    if clean:
        all_results: list[Result] = []
        for d in targets:
            all_results.extend(clean_dir(d))
        return {"results": all_results}

    all_results = []
    for source in _walk_targets(targets):
        if check:
            should, reason = _should_compress(source)
            if not should:
                all_results.append(Result(source=source, action=reason))
                continue
            gz_path = source.with_suffix(source.suffix + ".gz")
            if _is_fresh(source, gz_path):
                all_results.append(
                    Result(
                        source=source,
                        action="skipped_fresh",
                        original_size=source.stat().st_size,
                        compressed_size=gz_path.stat().st_size,
                    )
                )
            else:
                # 在 check 模式下，这个文件需要被压缩，但我们不写入
                all_results.append(
                    Result(
                        source=source,
                        action="needs_compress",
                        original_size=source.stat().st_size,
                    )
                )
        else:
            all_results.append(compress_file(source))
        if verbose:
            r = all_results[-1]
            if r.action == "compressed":
                print(
                    f"[gz] {r.source.relative_to(REPO_ROOT)}: "
                    f"{r.original_size:>8d} → {r.compressed_size:>8d} "
                    f"(-{r.saved_pct:5.1f}%)"
                )
            elif r.action != "skipped_ext":
                print(f"[gz] {r.source.relative_to(REPO_ROOT)}: {r.action}")
    return {"results": all_results}


def _format_summary(results: list[Result]) -> str:
    """汇总：压缩了多少文件，省了多少字节。"""
    by_action: dict[str, int] = {}
    total_original = 0
    total_compressed = 0
    for r in results:
        by_action[r.action] = by_action.get(r.action, 0) + 1
        if r.action == "compressed":
            total_original += r.original_size
            total_compressed += r.compressed_size
    lines = []
    for action in sorted(by_action.keys()):
        lines.append(f"  {action:>16}: {by_action[action]}")
    if total_original > 0:
        lines.append(
            f"  {'savings':>16}: "
            f"{total_original:>8d} → {total_compressed:>8d} "
            f"(-{(1.0 - total_compressed / total_original) * 100:.1f}%, "
            f"{(total_original - total_compressed) // 1024} KB freed)"
        )
    return "\n".join(lines)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="R20.14-D · pre-compress static assets (gzip)"
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="检查哪些文件需要被（重新）压缩，但不写入；exit 1 if 任意文件 stale",
    )
    parser.add_argument(
        "--clean",
        action="store_true",
        help="删除所有 .gz 副本（清理用，开发场景下常用）",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="按文件打印进度",
    )
    parser.add_argument(
        "--dir",
        action="append",
        type=Path,
        help="覆盖默认目标目录；可重复指定。默认 static/css static/js static/locales",
    )
    return parser


def _main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    out = run(
        directories=args.dir if args.dir else None,
        check=args.check,
        clean=args.clean,
        verbose=args.verbose,
    )
    summary = _format_summary(out["results"])
    print(summary)

    # check 模式下，任何 needs_compress 都让 exit 非 0，方便 CI 拦截
    if args.check:
        stale = [r for r in out["results"] if r.action == "needs_compress"]
        if stale:
            print(
                f"\n{len(stale)} file(s) stale; run "
                "`uv run python scripts/precompress_static.py` to regenerate.",
                file=sys.stderr,
            )
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
