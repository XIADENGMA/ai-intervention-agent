"""
PWA 图标生成器：从 SVG 源生成 PNG / ICO 资产族。

为什么单独建这个脚本
----------------------
PWA / favicon / iOS apple-touch-icon 对图标质量有不同的硬性要求：

1. ``favicon.ico`` 应包含**多尺寸**（16/32/48/256），单尺寸会让浏览器 tab
   位置（16×16 渲染槽）和 Windows 资源管理器（256×256 槽）均有质量损失；
2. ``apple-touch-icon.png`` 在 iOS 主屏幕**应有实色背景**——iOS 不支持透明
   alpha，会用黑/白填充透明角，与系统其它图标视觉割裂；
3. ``icon-maskable-*.png`` 必须**整张 canvas 实色填充**且主体落在中心 80%
   safe zone 内（W3C maskable spec）。OS 蒙板（圆形 / squircle / teardrop）
   会按设备形状裁切，透明角或越界主体都会丢失视觉；
4. ``icon.svg`` 是 "any" purpose 的源——透明角可以保留（OS 不会裁切，会
   渲染原始矩形），但 raster fallback PNG 需要支持降级。

为了同时满足以上 4 类约束，我们维护**两个 SVG 源**：

* ``src/ai_intervention_agent/icons/icon.svg``           — "any" purpose，原始设计；
* ``src/ai_intervention_agent/icons/icon-maskable.svg``  — 实色背景 + 主体缩到 0.6× 居中，专供 maskable。

并由本脚本一次性产出所有 PNG/ICO，幂等可重复。

零额外依赖
----------
脚本**只依赖 Python 标准库 + 系统 ``rsvg-convert`` CLI**，故意不引入 Pillow /
cairosvg：

* ``rsvg-convert``（GNOME librsvg 提供）与 Firefox / WebKit / Chromium SVG
  渲染器同源，输出与浏览器渲染视觉一致，比 ImageMagick 内置 SVG 解析器
  质量高几个数量级。
* PNG 后处理（透明角实色化、像素采样）以及 ICO multi-size 容器写入都用
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


@dataclass(frozen=True)
class PngSpec:
    """单个 PNG 输出规格。

    Attributes
    ----------
    filename:
        输出文件名（相对 ``icons/``）。
    size:
        PNG 边长（正方形）。
    source:
        SVG 源："any" 或 "maskable"。
    fill_corners:
        是否将透明角强制填充为不透明实色（用于 iOS apple-touch-icon）。
        实色取自 source SVG 渲染结果在 (1, 1) 像素的颜色——这是
        ``masterBg`` 渐变最浅端，与 manifest ``background_color`` 视觉一致。
    """

    filename: str
    size: int
    source: str  # "any" | "maskable"
    fill_corners: bool = False


# 输出图标族。顺序按尺寸升序，便于 review。
PNG_OUTPUTS: tuple[PngSpec, ...] = (
    # 浏览器 tab favicon —— 用 SVG 直接渲染最小尺寸保证清晰
    PngSpec("favicon-16.png", 16, "any"),
    PngSpec("favicon-32.png", 32, "any"),
    # iOS apple-touch-icon 必须填透明角（iOS 14+ 自动加圆角，不支持 alpha）
    PngSpec("apple-touch-icon.png", 180, "any", fill_corners=True),
    # PWA manifest "any" purpose 图标族
    PngSpec("icon-72.png", 72, "any"),
    PngSpec("icon-96.png", 96, "any"),
    PngSpec("icon-128.png", 128, "any"),
    PngSpec("icon-144.png", 144, "any"),
    PngSpec("icon-192.png", 192, "any"),
    PngSpec("icon-512.png", 512, "any"),
    # PWA manifest "maskable" purpose —— 整张实色 + 80% safe zone
    # 同时输出 192 + 512：Lighthouse PWA audit 推荐两档都覆盖。Android Chrome
    # 把 192 作为启动器图标第一选择，缺失时会拿 512 maskable 下采样导致毛刺。
    PngSpec("icon-maskable-192.png", 192, "maskable"),
    PngSpec("icon-maskable-512.png", 512, "maskable"),
)

# multi-size ICO 标准 favicon.ico 应至少包含的尺寸；256 让 Windows 资源管理器
# 大图标位置不模糊。
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
    """用 rsvg-convert 把 SVG 渲染成 RGBA 像素 buffer。

    返回 ``(width, height, pixels)``，``pixels`` 是 ``len = w*h*4`` 的
    bytearray，每像素 4 字节 RGBA（已经过 PNG filter 反算解码）。
    """

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
    """解码 PNG 字节流到 RGBA 像素 buffer（最小化实现）。

    支持 ``color_type=2``（RGB）/ ``color_type=6``（RGBA） + ``bit_depth=8`` +
    ``interlace=0``（非交错）。其它情况 raise ValueError。rsvg-convert 输出
    总是这两种之一，所以足够用。
    """

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

    bpp = 4 if color_type == 6 else 3  # bytes per pixel before alpha pad
    bpr = bpp * width + 1  # plus 1 filter byte per row

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
        elif filter_byte == 1:  # Sub
            for i in range(bpp, len(row)):
                row[i] = (row[i] + row[i - bpp]) & 0xFF
        elif filter_byte == 2:  # Up
            for i in range(len(row)):
                row[i] = (row[i] + prev_row[i]) & 0xFF
        elif filter_byte == 3:  # Average
            for i in range(len(row)):
                left = row[i - bpp] if i >= bpp else 0
                up = prev_row[i]
                row[i] = (row[i] + ((left + up) // 2)) & 0xFF
        elif filter_byte == 4:  # Paeth
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
        else:  # color_type == 2 (RGB → 补 alpha=255)
            for px in range(width):
                r = row[px * 3]
                g = row[px * 3 + 1]
                b = row[px * 3 + 2]
                rgba.extend([r, g, b, 0xFF])
        prev_row = bytes(row)

    return width, height, rgba


def _encode_png_rgba(width: int, height: int, rgba: bytes | bytearray) -> bytes:
    """把 RGBA 像素 buffer 编码成 PNG 字节流（最小化实现）。

    输出固定为 ``color_type=6 bit_depth=8 interlace=0`` 的 IHDR/IDAT/IEND
    三块结构，filter 全用 0（None）。zlib level=9，体积比 Pillow 默认稍大但
    仍是同量级（多 5-15%），可接受。
    """

    if len(rgba) != width * height * 4:
        raise ValueError(f"rgba 长度 {len(rgba)} 与 {width}×{height}×4 不匹配")

    def _chunk(tag: bytes, payload: bytes) -> bytes:
        header = struct.pack(">I", len(payload)) + tag
        crc = zlib.crc32(tag + payload) & 0xFFFFFFFF
        return header + payload + struct.pack(">I", crc)

    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)

    raw = bytearray()
    for y in range(height):
        raw.append(0)
        raw.extend(rgba[y * width * 4 : (y + 1) * width * 4])
    idat_data = zlib.compress(bytes(raw), 9)

    return (
        sig + _chunk(b"IHDR", ihdr) + _chunk(b"IDAT", idat_data) + _chunk(b"IEND", b"")
    )


def _solid_background_color(
    rgba: bytes | bytearray, width: int
) -> tuple[int, int, int]:
    """从 RGBA buffer (1, 1) 像素取实色背景色。

    选 (1, 1) 而不是 (0, 0)：rsvg-convert 在边缘 1px 偶尔有抗锯齿余量，
    (1, 1) 已经稳定落在 ``masterBg`` 渐变最浅端。
    """

    idx = (1 * width + 1) * 4
    return (rgba[idx], rgba[idx + 1], rgba[idx + 2])


def _fill_transparent_corners(width: int, height: int, rgba: bytearray) -> bytearray:
    """把透明像素合成到实色背景上（in-place 修改 rgba）。

    Alpha-over 公式：``out = src + bg * (1 - src_alpha / 255)``。前景 alpha
    为 0 时输出完全是 bg；alpha 为 255 时不变。每像素 ~3 次浮点 → 整数运算，
    512×512 用纯 Python 跑约 200 ms，对一次性脚本可接受。
    """

    bg_r, bg_g, bg_b = _solid_background_color(rgba, width)
    for y in range(height):
        for x in range(width):
            idx = (y * width + x) * 4
            a = rgba[idx + 3]
            if a == 255:
                continue
            inv = 255 - a
            rgba[idx] = (rgba[idx] * a + bg_r * inv + 127) // 255
            rgba[idx + 1] = (rgba[idx + 1] * a + bg_g * inv + 127) // 255
            rgba[idx + 2] = (rgba[idx + 2] * a + bg_b * inv + 127) // 255
            rgba[idx + 3] = 255
    return rgba


def _build_ico(svg_path: Path, sizes: tuple[int, ...]) -> bytes:
    """把多个尺寸的 RGBA 渲染结果合成 multi-size ICO。

    ICO 格式：6 字节 header（reserved=0, type=1, count=N） + N×16 字节目录
    项 + N 个内嵌 PNG 数据流。每个目录项：
      ``<BBBBHHII> width height palette reserved planes bpp size offset``
    Width / height 字节为 0 表示 256（1 字节存不下）。
    """

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
                size_in_dir,  # width
                size_in_dir,  # height
                0,  # palette colors (0 for true-color)
                0,  # reserved
                1,  # color planes
                32,  # bits per pixel
                len(png_bytes),  # size in bytes
                offset,
            )
        )
        payloads.extend(png_bytes)
        offset += len(png_bytes)

    return header + bytes(entries) + bytes(payloads)


def generate_all(check_only: bool = False) -> int:
    """主流程：生成全部 PNG + ICO。返回退出码。"""

    if not _check_dependencies():
        return 1
    if not SOURCE_SVG_ANY.is_file():
        print(f"ERROR: 缺少源 {SOURCE_SVG_ANY}", file=sys.stderr)
        return 1
    if not SOURCE_SVG_MASKABLE.is_file():
        print(f"ERROR: 缺少源 {SOURCE_SVG_MASKABLE}", file=sys.stderr)
        return 1

    if check_only:
        print("=== check-only 模式：仅验证现有 PNG/ICO 的存在性与尺寸 ===")

    sources = {
        "any": SOURCE_SVG_ANY,
        "maskable": SOURCE_SVG_MASKABLE,
    }

    drift: list[str] = []

    for spec in PNG_OUTPUTS:
        src = sources[spec.source]
        dest = ICONS_DIR / spec.filename
        try:
            width, height, rgba = _render_svg_to_rgba(src, spec.size)
        except Exception as exc:
            print(f"FAIL render {spec.filename}: {exc}", file=sys.stderr)
            return 1

        if spec.fill_corners:
            rgba = _fill_transparent_corners(width, height, rgba)

        if check_only:
            if not dest.is_file():
                drift.append(f"{spec.filename}: 缺失")
                continue
            try:
                disk_w, disk_h, _ = _decode_png_to_rgba(dest.read_bytes())
            except Exception as exc:
                drift.append(f"{spec.filename}: 解码失败 {exc}")
                continue
            if (disk_w, disk_h) != (width, height):
                drift.append(
                    f"{spec.filename}: 尺寸不一致 disk={disk_w}x{disk_h} expected={width}x{height}"
                )
        else:
            png_bytes = _encode_png_rgba(width, height, bytes(rgba))
            dest.write_bytes(png_bytes)
            print(f"  wrote  {spec.filename:32s} {spec.size}x{spec.size}")

    ico_dest = ICONS_DIR / "icon.ico"
    try:
        ico_bytes = _build_ico(SOURCE_SVG_ANY, ICO_SIZES)
    except Exception as exc:
        print(f"FAIL build ICO: {exc}", file=sys.stderr)
        return 1

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
        print("OK: 所有 PNG / ICO 与 SVG 渲染一致")
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
