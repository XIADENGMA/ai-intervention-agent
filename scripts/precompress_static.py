"""R20.14-D + R21.4 · 预压缩静态资源 (gzip + Brotli)。

设计目标
========

Flask 的默认静态资源响应 **不带任何内容压缩**。``static/js/tex-mml-chtml.js``
1.1 MB、``static/js/lottie.min.js`` 300 KB、``static/locales/zh-CN.json``
~11 KB 等首屏可见资源都按原始大小通过 loopback 发给浏览器。本机 loopback
速度快，节流不在带宽上 —— 但远程 / 容器环境 / mDNS LAN 设备访问这些资源
时，gzip 能直接砍 70-85% 的传输量，Brotli 在 gzip 基础上再额外省
15-23%。

R21.4 在 R20.14-D（仅 gzip）的基础上扩展为 **gzip + Brotli 双重预压缩**：
- 客户端 ``Accept-Encoding`` 含 ``br`` 时，运行时优先服务 ``.br`` 副本
  （所有 2017+ 主流浏览器原生支持）；
- 否则退化到 ``.gz`` 副本（覆盖几乎所有 client）；
- 都没有时直接服务原文件（极少数 ``Accept-Encoding: identity`` 客户端）。

为什么是「构建期预压缩」而不是「运行期 on-the-fly」
====================================================

- on-the-fly 压缩（如 ``flask-compress``）每次请求都吃 CPU；R20.10/R20.11
  花了大量精力把冷启动从 425ms 压到 156ms / spawn-to-listen 1922→203ms，
  在 hot path 上塞 zlib.compress / brotli.compress 是反方向；
- 构建期一次性产出 ``<file>.gz`` / ``<file>.br``，运行时 Flask 只是
  ``send_from_directory`` 一份预压缩文件外加 ``Content-Encoding`` 头。
  零 CPU、零内存增量；
- ``brotli`` 库在我们的 venv 里通过 ``flask-compress`` 间接装入（uv.lock
  中的 transitive dep），import 失败时降级到 gzip-only 不报错。

工作流
------

    uv run python scripts/precompress_static.py             # 默认运行（gzip + br）
    uv run python scripts/precompress_static.py --check     # 只检查不写
    uv run python scripts/precompress_static.py --clean     # 删除所有 .gz 和 .br
    uv run python scripts/precompress_static.py --verbose
    uv run python scripts/precompress_static.py --no-brotli # 强制只 gzip

策略
----

- 遍历 ``static/css``、``static/js``、``static/locales``、``static/lottie`` 四个目录；
- 跳过 ``< MIN_SIZE_BYTES`` (默认 500 字节) 的小文件（gzip overhead 不划算）；
- 跳过已经是压缩格式的文件（``.gz`` / ``.br`` / ``.zip`` / ``.png`` /
  ``.jpg`` / ``.webp`` / ``.woff`` / ``.woff2``） —— 重复压缩通常会增大；
- 比较源文件 ``mtime``，并反解已有 ``.gz`` / ``.br`` 校验内容仍匹配当前源文件；
- 写入时用 ``tempfile + os.replace`` 保证原子性，避免半成品文件被 Flask
  picked up 后导致响应错误；
- 反检：如果压缩后体积 ≥ 原文件，跳过写入避免误导。

Brotli quality 选择
-------------------

- ``brotli.compress(data, quality=11)``：最高压缩比（11 是 max），单文件
  10-50 ms（1.1 MB MathJax 大概 60-80 ms）。这是一次性离线开销，不影响
  运行时；
- 不和 gzip ``compresslevel=9`` 做对应——不同算法，``compresslevel=9`` 也是
  各自的 max；保持「最高压缩比一次性，运行时零开销」语义统一。

集成
----

应当在 CI / package_vscode_vsix 流水线 / pre-commit 之外的某处批量跑（每
次开发/部署前）。当前阶段不强制集成 —— 留给 R20.14-E 文档说明，R21.4
继承同样的策略。
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

try:
    import brotli as _brotli_mod

    BROTLI_AVAILABLE = True
except ImportError:
    _brotli_mod = None  # ty: ignore[invalid-assignment]
    BROTLI_AVAILABLE = False

REPO_ROOT = Path(__file__).resolve().parent.parent

DEFAULT_TARGET_DIRS = (
    REPO_ROOT / "src" / "ai_intervention_agent" / "static" / "css",
    REPO_ROOT / "src" / "ai_intervention_agent" / "static" / "js",
    REPO_ROOT / "src" / "ai_intervention_agent" / "static" / "locales",
    REPO_ROOT / "src" / "ai_intervention_agent" / "static" / "lottie",
)


MIN_SIZE_BYTES = 500

GZIP_LEVEL = 9
BROTLI_QUALITY = 11


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
        ".ttf",
        ".ico",
    }
)


@dataclass
class Result:
    """单个文件的处理结果。"""

    source: Path
    action: str
    encoding: str = "gzip"
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
    """判断单个文件是否值得压缩。"""
    if path.suffix.lower() in SKIP_EXTENSIONS:
        return False, "skipped_ext"
    try:
        if path.stat().st_size < MIN_SIZE_BYTES:
            return False, "skipped_small"
    except OSError:
        return False, "skipped_stat_error"
    return True, "compressed"


def _compressed_matches_source(source: Path, compressed_path: Path) -> bool:
    """确认压缩副本可解回当前源文件，避免 mtime 新但内容旧的静默漂移。"""
    try:
        raw = source.read_bytes()
        compressed = compressed_path.read_bytes()
        if compressed_path.suffix == ".gz":
            return gzip.decompress(compressed) == raw
        if compressed_path.suffix == ".br":
            if _brotli_mod is None:
                return False
            return _brotli_mod.decompress(compressed) == raw
    except Exception:
        return False
    return False


def _is_fresh(source: Path, compressed_path: Path) -> bool:
    """判断 ``compressed_path``（``.gz`` 或 ``.br``）是否相对 ``source`` 新鲜。"""
    if not compressed_path.exists():
        return False
    try:
        return (
            compressed_path.stat().st_mtime >= source.stat().st_mtime
            and _compressed_matches_source(source, compressed_path)
        )
    except OSError:
        return False


def _atomic_write(target: Path, content: bytes, *, suffix: str) -> None:
    """用 ``tempfile + os.replace`` 原子写入压缩文件。"""
    tmp_fd, tmp_path = tempfile.mkstemp(
        prefix=".tmp.precompress.", suffix=suffix, dir=str(target.parent)
    )
    try:
        with os.fdopen(tmp_fd, "wb") as fh:
            fh.write(content)
        os.replace(tmp_path, target)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def compress_file(source: Path, *, level: int = GZIP_LEVEL) -> Result:
    """压缩单个文件为 gzip，返回 ``Result``。"""
    should, reason = _should_compress(source)
    if not should:
        return Result(source=source, action=reason, encoding="gzip")

    gz_path = source.with_suffix(source.suffix + ".gz")
    if _is_fresh(source, gz_path):
        return Result(
            source=source,
            action="skipped_fresh",
            encoding="gzip",
            original_size=source.stat().st_size,
            compressed_size=gz_path.stat().st_size,
        )

    raw = source.read_bytes()
    compressed = gzip.compress(raw, compresslevel=level, mtime=0)

    if len(compressed) >= len(raw):
        return Result(
            source=source,
            action="skipped_no_gain",
            encoding="gzip",
            original_size=len(raw),
            compressed_size=len(compressed),
        )

    _atomic_write(gz_path, compressed, suffix=".gz")

    return Result(
        source=source,
        action="compressed",
        encoding="gzip",
        original_size=len(raw),
        compressed_size=len(compressed),
    )


def compress_file_br(source: Path, *, quality: int = BROTLI_QUALITY) -> Result:
    """压缩单个文件为 Brotli，返回 ``Result``。"""
    if not BROTLI_AVAILABLE:
        return Result(source=source, action="skipped_no_brotli", encoding="br")

    should, reason = _should_compress(source)
    if not should:
        return Result(source=source, action=reason, encoding="br")

    br_path = source.with_suffix(source.suffix + ".br")
    if _is_fresh(source, br_path):
        return Result(
            source=source,
            action="skipped_fresh",
            encoding="br",
            original_size=source.stat().st_size,
            compressed_size=br_path.stat().st_size,
        )

    raw = source.read_bytes()

    assert _brotli_mod is not None
    compressed = _brotli_mod.compress(raw, quality=quality)

    if len(compressed) >= len(raw):
        return Result(
            source=source,
            action="skipped_no_gain",
            encoding="br",
            original_size=len(raw),
            compressed_size=len(compressed),
        )

    _atomic_write(br_path, compressed, suffix=".br")

    return Result(
        source=source,
        action="compressed",
        encoding="br",
        original_size=len(raw),
        compressed_size=len(compressed),
    )


def clean_dir(directory: Path) -> list[Result]:
    """删除目录里的所有 ``.gz`` / ``.br`` 副本（``--clean`` 模式）。"""
    results: list[Result] = []
    if not directory.exists():
        return results
    for pattern, encoding in (("*.gz", "gzip"), ("*.br", "br")):
        for path in sorted(directory.rglob(pattern)):
            if path.is_file():
                try:
                    path.unlink()
                    results.append(
                        Result(source=path, action="cleaned", encoding=encoding)
                    )
                except OSError:
                    pass
    return results


def run(
    *,
    directories: list[Path] | None = None,
    check: bool = False,
    clean: bool = False,
    verbose: bool = False,
    enable_brotli: bool = True,
) -> dict[str, list[Result]]:
    """主入口。返回 ``{"results": [...]}``。"""
    targets = list(directories) if directories else list(DEFAULT_TARGET_DIRS)
    if clean:
        all_results: list[Result] = []
        for d in targets:
            all_results.extend(clean_dir(d))
        return {"results": all_results}

    do_brotli = enable_brotli and BROTLI_AVAILABLE
    all_results = []
    for source in _walk_targets(targets):
        if check:
            should, reason = _should_compress(source)
            if not should:
                all_results.append(
                    Result(source=source, action=reason, encoding="gzip")
                )
                continue
            for ext, encoding in [("gz", "gzip")] + (
                [("br", "br")] if do_brotli else []
            ):
                comp_path = source.with_suffix(source.suffix + "." + ext)
                if _is_fresh(source, comp_path):
                    all_results.append(
                        Result(
                            source=source,
                            action="skipped_fresh",
                            encoding=encoding,
                            original_size=source.stat().st_size,
                            compressed_size=comp_path.stat().st_size,
                        )
                    )
                else:
                    all_results.append(
                        Result(
                            source=source,
                            action="needs_compress",
                            encoding=encoding,
                            original_size=source.stat().st_size,
                        )
                    )
        else:
            r_gz = compress_file(source)
            all_results.append(r_gz)
            if do_brotli:
                r_br = compress_file_br(source)
                all_results.append(r_br)
        if verbose:
            for r in all_results[-2:] if not check else all_results[-1:]:
                if r.action == "compressed":
                    print(
                        f"[{r.encoding:>4}] {r.source.relative_to(REPO_ROOT)}: "
                        f"{r.original_size:>8d} → {r.compressed_size:>8d} "
                        f"(-{r.saved_pct:5.1f}%)"
                    )
                elif r.action != "skipped_ext":
                    print(
                        f"[{r.encoding:>4}] {r.source.relative_to(REPO_ROOT)}: "
                        f"{r.action}"
                    )
    return {"results": all_results}


def _format_summary(results: list[Result]) -> str:
    """汇总：每种 encoding 分别统计文件数 / 节省字节。"""
    lines = []
    by_encoding_action: dict[tuple[str, str], int] = {}
    by_encoding_savings: dict[str, tuple[int, int]] = {"gzip": (0, 0), "br": (0, 0)}
    for r in results:
        key = (r.encoding, r.action)
        by_encoding_action[key] = by_encoding_action.get(key, 0) + 1
        if r.action == "compressed":
            o, c = by_encoding_savings.get(r.encoding, (0, 0))
            by_encoding_savings[r.encoding] = (
                o + r.original_size,
                c + r.compressed_size,
            )

    for encoding in ("gzip", "br"):
        per_action = {a: n for (e, a), n in by_encoding_action.items() if e == encoding}
        if not per_action:
            continue
        lines.append(f"  [{encoding}]")
        for action in sorted(per_action.keys()):
            lines.append(f"    {action:>16}: {per_action[action]}")
        total_o, total_c = by_encoding_savings.get(encoding, (0, 0))
        if total_o > 0:
            lines.append(
                f"    {'savings':>16}: "
                f"{total_o:>8d} → {total_c:>8d} "
                f"(-{(1.0 - total_c / total_o) * 100:.1f}%, "
                f"{(total_o - total_c) // 1024} KB freed)"
            )
    return "\n".join(lines)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="R20.14-D + R21.4 · pre-compress static assets (gzip + Brotli)"
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="检查哪些文件需要被（重新）压缩，但不写入；exit 1 if 任意文件 stale",
    )
    parser.add_argument(
        "--clean",
        action="store_true",
        help="删除所有 .gz / .br 副本（清理用，开发场景下常用）",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="按文件打印进度",
    )
    parser.add_argument(
        "--no-brotli",
        action="store_true",
        help="禁用 Brotli 压缩（R21.4），仅生成 .gz（R20.14-D 行为）",
    )
    parser.add_argument(
        "--dir",
        action="append",
        type=Path,
        help=(
            "覆盖默认目标目录；可重复指定。默认 static/css static/js "
            "static/locales static/lottie"
        ),
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
        enable_brotli=not args.no_brotli,
    )
    summary = _format_summary(out["results"])
    print(summary)

    if not BROTLI_AVAILABLE and not args.no_brotli and not args.clean:
        print(
            "\nNOTE: brotli library not importable; only gzip variants written. "
            "Run `uv add brotli` to enable Brotli precompression.",
            file=sys.stderr,
        )

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
