"""
PWA 图标生成器：从 SVG 源生成 PNG / ICO 资产族。

为什么单独建这个脚本
----------------------
PWA / favicon / iOS apple-touch-icon 对图标质量有不同的硬性要求：

1. ``favicon.ico`` 应包含**多尺寸**（16/32/48/256），单尺寸会让浏览器 tab
   位置（16×16 渲染槽）和 Windows 资源管理器（256×256 槽）均有质量损失；
2. ``apple-touch-icon.png`` 在 iOS 主屏幕必须是**整张 canvas 实色的方形**
   （无圆角、无留白、无阴影）——iOS 自己裁圆角，并把 PNG 里每一个透明像素
   涂成黑色。曾经把带圆角和留白的 ``icon.svg`` 直接渲染、再把透明像素
   "实色化"：背景色取自一个透明像素（黑色），结果留白区变成包住图标的黑边。
   现在由专用的全幅源 ``icon-apple-touch.svg`` 渲染，输出不带 alpha 通道的
   RGB PNG；
3. ``icon-maskable-*.png`` 必须**整张 canvas 实色填充**且主体落在中心 80%
   safe zone 内（W3C maskable spec）。OS 蒙板（圆形 / squircle / teardrop）
   会按设备形状裁切，透明角或越界主体都会丢失视觉；
4. ``icon.svg`` 是 "any" purpose 的源——透明角可以保留（OS 不会裁切，会
   渲染原始矩形），但 raster fallback PNG 需要支持降级。

为了同时满足以上 4 类约束，我们维护**三个 SVG 源**：

* ``src/ai_intervention_agent/icons/icon.svg``              — "any" purpose，原始设计；
* ``src/ai_intervention_agent/icons/icon-maskable.svg``     — 实色背景 + 主体缩到 0.6× 居中，专供 maskable；
* ``src/ai_intervention_agent/icons/icon-apple-touch.svg``  — 全幅实色方形，主体与底板的比例同 ``icon.svg``，专供 apple-touch-icon。

并由本脚本一次性产出所有 PNG/ICO，幂等可重复。要求整张实色的两类图标
（maskable、apple-touch）渲染出任何半透明像素时，脚本直接报错、不写文件。

零额外依赖
----------
脚本**只依赖 Python 标准库 + 系统 ``rsvg-convert`` CLI**，故意不引入 Pillow /
cairosvg：

* ``rsvg-convert``（GNOME librsvg 提供）与 Firefox / WebKit / Chromium SVG
  渲染器同源，输出与浏览器渲染视觉一致，比 ImageMagick 内置 SVG 解析器
  质量高几个数量级。
* PNG 编解码（RGBA / RGB）、实色性校验以及 ICO multi-size 容器写入都用
  ``zlib`` + ``struct`` 纯 Python 实现，避免 ``uv sync`` 把 Pillow 装进
  lockfile 又因为只在 scripts/ 用而成为僵尸依赖。

CI 行为
-------
本脚本是 **dev-only 工具**，不在 ``ci_gate.py`` 阶段运行（产出物 commit 进
仓库）。CI 校验交给 ``tests/test_pwa_icon_assets.py`` —— 验证 disk 上的图标
满足规范，但不重新渲染。

使用
----
::

    # 一次性安装系统依赖
    brew install librsvg                     # macOS
    sudo apt-get install librsvg2-bin        # Ubuntu / Debian

    # 重新生成所有 PWA 图标
    uv run python scripts/generate_pwa_icons.py

    # 只检查不写入（不会改 disk，对比 SVG 源与现有 PNG 的尺寸 / 实色性）
    uv run python scripts/generate_pwa_icons.py --check

只检查模式（``--check``）校验：文件存在、尺寸一致、要求实色的图标没有半透明
像素、apple-touch-icon 不带 alpha 通道。它不逐像素对比渲染结果——不同机器上
librsvg 版本不同，边缘抗锯齿会有细微差异。

退出码
------
* 0 = 成功 / 无需重生成
* 1 = 渲染失败 / 验证失败 / 缺少依赖
"""

from __future__ import annotations

import argparse
import shutil
import struct
import subprocess
import sys
import zlib
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ICONS_DIR = REPO_ROOT / "src" / "ai_intervention_agent" / "icons"
SOURCE_SVG_ANY = ICONS_DIR / "icon.svg"
SOURCE_SVG_MASKABLE = ICONS_DIR / "icon-maskable.svg"
SOURCE_SVG_APPLE_TOUCH = ICONS_DIR / "icon-apple-touch.svg"

SOURCES: dict[str, Path] = {
    "any": SOURCE_SVG_ANY,
    "maskable": SOURCE_SVG_MASKABLE,
    "apple-touch": SOURCE_SVG_APPLE_TOUCH,
}


@dataclass(frozen=True)
class PngSpec:
    """单个 PNG 输出规格。

    ``require_opaque``：渲染结果不允许有任何半透明像素，否则脚本报错、不写文件。
    ``drop_alpha``：输出不带 alpha 通道的 RGB PNG（iOS 对带透明度的图标会把透明
    像素涂黑，没有 alpha 通道就没有这个可能）；只能与 ``require_opaque`` 一起用。
    """

    filename: str
    size: int
    source: str
    require_opaque: bool = False
    drop_alpha: bool = False

    def __post_init__(self) -> None:
        if self.source not in SOURCES:
            raise ValueError(f"{self.filename}: 未知源 {self.source!r}")
        if self.drop_alpha and not self.require_opaque:
            raise ValueError(f"{self.filename}: drop_alpha 必须同时 require_opaque")


PNG_OUTPUTS: tuple[PngSpec, ...] = (
    PngSpec("favicon-16.png", 16, "any"),
    PngSpec("favicon-32.png", 32, "any"),
    PngSpec(
        "apple-touch-icon.png", 180, "apple-touch", require_opaque=True, drop_alpha=True
    ),
    PngSpec("icon-72.png", 72, "any"),
    PngSpec("icon-96.png", 96, "any"),
    PngSpec("icon-128.png", 128, "any"),
    PngSpec("icon-144.png", 144, "any"),
    PngSpec("icon-192.png", 192, "any"),
    PngSpec("icon-512.png", 512, "any"),
    PngSpec("icon-maskable-192.png", 192, "maskable", require_opaque=True),
    PngSpec("icon-maskable-512.png", 512, "maskable", require_opaque=True),
)


ICO_SIZES: tuple[int, ...] = (16, 32, 48, 256)


def _check_dependencies() -> bool:
    """提前确认必备依赖可用，给出清晰错误。"""

    if shutil.which("rsvg-convert") is None:
        print(
            "ERROR: rsvg-convert 未安装。请先安装 librsvg：\n"
            "    macOS:  brew install librsvg\n"
            "    Ubuntu: sudo apt-get install librsvg2-bin\n",
            file=sys.stderr,
        )
        return False
    return True


def _render_svg_to_rgba(svg_path: Path, size: int) -> tuple[int, int, bytearray]:
    """用 rsvg-convert 把 SVG 渲染成 RGBA 像素 buffer。"""

    proc = subprocess.run(
        ["rsvg-convert", "-w", str(size), "-h", str(size), str(svg_path)],
        check=False,
        capture_output=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"rsvg-convert 渲染 {svg_path.name} @ {size}x{size} 失败: "
            f"{proc.stderr.decode('utf-8', 'replace').strip()}"
        )
    return _decode_png_to_rgba(proc.stdout)


def _decode_png_to_rgba(data: bytes) -> tuple[int, int, bytearray]:
    """解码 PNG 字节流到 RGBA 像素 buffer（最小化实现）。"""

    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("不是 PNG 流")
    width, height = struct.unpack(">II", data[16:24])
    bit_depth = data[24]
    color_type = data[25]
    interlace = data[28]
    if bit_depth != 8 or interlace != 0 or color_type not in (2, 6):
        raise ValueError(
            f"PNG 格式不支持: ct={color_type} bd={bit_depth} interlace={interlace}"
        )

    bpp = 4 if color_type == 6 else 3
    bpr = bpp * width + 1

    idat = b""
    pos = 8
    while pos < len(data):
        chunk_len = struct.unpack(">I", data[pos : pos + 4])[0]
        chunk_type = data[pos + 4 : pos + 8]
        chunk_data = data[pos + 8 : pos + 8 + chunk_len]
        pos += 12 + chunk_len
        if chunk_type == b"IDAT":
            idat += chunk_data

    raw = zlib.decompress(idat)
    rgba = bytearray()
    prev_row = bytes(width * bpp)
    for y in range(height):
        row_start = y * bpr
        filter_byte = raw[row_start]
        row = bytearray(raw[row_start + 1 : row_start + bpr])
        if filter_byte == 0:
            pass
        elif filter_byte == 1:
            for i in range(bpp, len(row)):
                row[i] = (row[i] + row[i - bpp]) & 0xFF
        elif filter_byte == 2:
            for i in range(len(row)):
                row[i] = (row[i] + prev_row[i]) & 0xFF
        elif filter_byte == 3:
            for i in range(len(row)):
                left = row[i - bpp] if i >= bpp else 0
                up = prev_row[i]
                row[i] = (row[i] + ((left + up) // 2)) & 0xFF
        elif filter_byte == 4:
            for i in range(len(row)):
                left = row[i - bpp] if i >= bpp else 0
                up = prev_row[i]
                up_left = prev_row[i - bpp] if i >= bpp else 0
                p = left + up - up_left
                pa, pb, pc = abs(p - left), abs(p - up), abs(p - up_left)
                if pa <= pb and pa <= pc:
                    pred = left
                elif pb <= pc:
                    pred = up
                else:
                    pred = up_left
                row[i] = (row[i] + pred) & 0xFF
        else:
            raise ValueError(f"未知 PNG filter: {filter_byte}")

        if color_type == 6:
            rgba.extend(row)
        else:
            for px in range(width):
                r = row[px * 3]
                g = row[px * 3 + 1]
                b = row[px * 3 + 2]
                rgba.extend([r, g, b, 0xFF])
        prev_row = bytes(row)

    return width, height, rgba


_PNG_CHANNELS_BY_COLOR_TYPE = {2: 3, 6: 4}


def _encode_png(
    width: int, height: int, pixels: bytes | bytearray, color_type: int
) -> bytes:
    """把像素 buffer 编码成 8-bit 非交错 PNG 字节流（最小化实现）。

    ``color_type`` 为 6（RGBA）或 2（RGB），``pixels`` 的通道数必须与之相符。
    """

    channels = _PNG_CHANNELS_BY_COLOR_TYPE[color_type]
    if len(pixels) != width * height * channels:
        raise ValueError(
            f"像素 buffer 长度 {len(pixels)} 与 {width}×{height}×{channels} 不匹配"
        )

    def _chunk(tag: bytes, payload: bytes) -> bytes:
        header = struct.pack(">I", len(payload)) + tag
        crc = zlib.crc32(tag + payload) & 0xFFFFFFFF
        return header + payload + struct.pack(">I", crc)

    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", width, height, 8, color_type, 0, 0, 0)

    stride = width * channels
    raw = bytearray()
    for y in range(height):
        raw.append(0)
        raw.extend(pixels[y * stride : (y + 1) * stride])
    idat_data = zlib.compress(bytes(raw), 9)

    return (
        sig + _chunk(b"IHDR", ihdr) + _chunk(b"IDAT", idat_data) + _chunk(b"IEND", b"")
    )


def _encode_png_rgba(width: int, height: int, rgba: bytes | bytearray) -> bytes:
    """把 RGBA 像素 buffer 编码成 PNG 字节流（最小化实现）。"""

    return _encode_png(width, height, rgba, 6)


def _encode_png_rgb(width: int, height: int, rgba: bytes | bytearray) -> bytes:
    """丢弃 alpha 通道，把 RGBA 像素 buffer 编码成不带 alpha 的 RGB PNG。

    调用方先用 :func:`_first_translucent_pixel` 确认没有半透明像素；这里不做合成，
    直接取 RGB 三个通道。
    """

    if len(rgba) != width * height * 4:
        raise ValueError(f"rgba 长度 {len(rgba)} 与 {width}×{height}×4 不匹配")
    rgb = bytearray(width * height * 3)
    rgb[0::3] = rgba[0::4]
    rgb[1::3] = rgba[1::4]
    rgb[2::3] = rgba[2::4]
    return _encode_png(width, height, rgb, 2)


def _first_translucent_pixel(
    width: int, rgba: bytes | bytearray
) -> tuple[int, int, int] | None:
    """返回第一个 alpha != 255 的像素 ``(x, y, alpha)``；整张实色则返回 ``None``。"""

    alphas = rgba[3::4]
    if min(alphas, default=255) == 255:
        return None
    index = next(i for i, a in enumerate(alphas) if a != 255)
    return (index % width, index // width, alphas[index])


def _png_color_type(data: bytes) -> int:
    """读取 PNG IHDR 里的 color type（2 = RGB，6 = RGBA）。"""

    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("不是 PNG 流")
    return data[25]


def _build_ico(svg_path: Path, sizes: tuple[int, ...]) -> bytes:
    """把多个尺寸的 RGBA 渲染结果合成 multi-size ICO。"""

    sizes_sorted = sorted(set(sizes))
    n = len(sizes_sorted)
    header = struct.pack("<HHH", 0, 1, n)
    entries = bytearray()
    payloads = bytearray()
    offset = 6 + n * 16

    for s in sizes_sorted:
        w, h, rgba = _render_svg_to_rgba(svg_path, s)
        png_bytes = _encode_png_rgba(w, h, rgba)
        size_in_dir = 0 if s == 256 else s
        entries.extend(
            struct.pack(
                "<BBBBHHII",
                size_in_dir,
                size_in_dir,
                0,
                0,
                1,
                32,
                len(png_bytes),
                offset,
            )
        )
        payloads.extend(png_bytes)
        offset += len(png_bytes)

    return header + bytes(entries) + bytes(payloads)


def _render_all() -> tuple[list[tuple[PngSpec, int, int, bytearray]], bytes] | None:
    """渲染全部 PNG 与 ICO 并校验实色性；任何一步失败都返回 ``None``。

    所有渲染与校验都在写盘之前完成，所以失败时磁盘上不会留下写了一半的图标族。
    """

    rendered: list[tuple[PngSpec, int, int, bytearray]] = []
    for spec in PNG_OUTPUTS:
        src = SOURCES[spec.source]
        try:
            width, height, rgba = _render_svg_to_rgba(src, spec.size)
        except Exception as exc:
            print(f"FAIL render {spec.filename}: {exc}", file=sys.stderr)
            return None

        if spec.require_opaque:
            bad = _first_translucent_pixel(width, rgba)
            if bad is not None:
                x, y, alpha = bad
                print(
                    f"FAIL {spec.filename}: {src.name} 渲染出半透明像素 "
                    f"(x={x}, y={y}, alpha={alpha})。该图标必须整张实色：让背景铺满"
                    "整个 canvas，不要留透明边或圆角（iOS 会把透明像素涂成黑色）。",
                    file=sys.stderr,
                )
                return None
        rendered.append((spec, width, height, rgba))

    try:
        ico_bytes = _build_ico(SOURCE_SVG_ANY, ICO_SIZES)
    except Exception as exc:
        print(f"FAIL build ICO: {exc}", file=sys.stderr)
        return None
    return rendered, ico_bytes


def _check_png_on_disk(spec: PngSpec, dest: Path, width: int, height: int) -> list[str]:
    """校验磁盘上的 PNG：存在、尺寸一致、要求实色的图标确实实色且不带 alpha 通道。"""

    if not dest.is_file():
        return [f"{spec.filename}: 缺失"]
    data = dest.read_bytes()
    try:
        disk_w, disk_h, disk_pixels = _decode_png_to_rgba(data)
    except Exception as exc:
        return [f"{spec.filename}: 解码失败 {exc}"]

    problems: list[str] = []
    if (disk_w, disk_h) != (width, height):
        problems.append(
            f"{spec.filename}: 尺寸不一致 disk={disk_w}x{disk_h} expected={width}x{height}"
        )
    if spec.require_opaque:
        bad = _first_translucent_pixel(disk_w, disk_pixels)
        if bad is not None:
            problems.append(
                f"{spec.filename}: 磁盘上的 PNG 有半透明像素 "
                f"(x={bad[0]}, y={bad[1]}, alpha={bad[2]})，必须整张实色"
            )
    if spec.drop_alpha and _png_color_type(data) != 2:
        problems.append(
            f"{spec.filename}: 磁盘上的 PNG 带 alpha 通道"
            f"（color type {_png_color_type(data)}），应为不带 alpha 的 RGB"
        )
    return problems


def generate_all(check_only: bool = False) -> int:
    """主流程：生成全部 PNG + ICO。返回退出码。"""

    if not _check_dependencies():
        return 1
    for source in SOURCES.values():
        if not source.is_file():
            print(f"ERROR: 缺少源 {source}", file=sys.stderr)
            return 1

    if check_only:
        print("=== check-only 模式：验证现有 PNG/ICO 的存在性、尺寸与实色性 ===")

    outcome = _render_all()
    if outcome is None:
        return 1
    rendered, ico_bytes = outcome

    drift: list[str] = []

    for spec, width, height, rgba in rendered:
        dest = ICONS_DIR / spec.filename
        if check_only:
            drift.extend(_check_png_on_disk(spec, dest, width, height))
            continue
        if spec.drop_alpha:
            png_bytes = _encode_png_rgb(width, height, rgba)
        else:
            png_bytes = _encode_png_rgba(width, height, rgba)
        dest.write_bytes(png_bytes)
        print(f"  wrote  {spec.filename:32s} {spec.size}x{spec.size}")

    ico_dest = ICONS_DIR / "icon.ico"
    if check_only:
        if not ico_dest.is_file():
            drift.append("icon.ico: 缺失")
        else:
            existing = ico_dest.read_bytes()
            if len(existing) < 1024:
                drift.append(
                    f"icon.ico: 大小 {len(existing)}B 异常小（多尺寸 ICO 应 >2KB）"
                )
    else:
        ico_dest.write_bytes(ico_bytes)
        print(
            f"  wrote  icon.ico                         {','.join(str(s) for s in ICO_SIZES)}"
        )

    if check_only and drift:
        print("DRIFT:", file=sys.stderr)
        for d in drift:
            print(f"  - {d}", file=sys.stderr)
        return 1

    if check_only:
        print("OK: 所有 PNG / ICO 存在，尺寸与实色性符合要求")
    else:
        print(f"DONE: 生成 {len(PNG_OUTPUTS)} 个 PNG + 1 个 multi-size ICO")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="从 SVG 源重新生成 PWA 图标族（PNG + ICO）。"
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="只检查不写入；任何 drift 退出码 1（适合 dev workflow）。",
    )
    args = parser.parse_args()
    return generate_all(check_only=args.check)


if __name__ == "__main__":
    raise SystemExit(main())
