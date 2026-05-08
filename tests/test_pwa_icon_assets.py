"""PWA 图标资产必须与 manifest / HTML 引用保持一致。

历史问题（已修复 / 这里固化为回归测试）：

* **r32 之前**：``icons/manifest.webmanifest`` 与 ``templates/web_ui.html`` 声明了
  多组 PNG PWA 图标，但仓库里只有 ``icon.svg``。浏览器安装 PWA 时这些 PNG 404，
  回退为截图或错误图标。
* **r32 引入的 regression**：把 ``icons/icon.ico`` 从原本的双尺寸（16+32）覆盖成
  单一 32×32，浏览器 tab favicon（16×16 槽）需要被强制下采样后变模糊；本次（紧随
  r32 的 PWA 自检批次）补上多尺寸 ICO + 多源 SVG（"any" 与 "maskable" 各自独立）
  + maskable 安全区检查，让所有同类 regression 在 CI 阶段失败。
* **maskable / any 字节相同**：r32 的 ``icon-maskable-512.png`` 与 ``icon-512.png``
  MD5 一致，违反 W3C maskable 规范（实色全填 + 主体落在中心 80% safe zone 内）。
* **apple-touch-icon 透明角**：iOS 14+ 的 Add to Home Screen 不支持 alpha，会用
  黑/白填充透明角。我们把 apple-touch-icon 的角落强制实色化（``solid_background_color``
  来自 SVG 渲染结果的浅紫灰渐变端，与 manifest ``background_color`` 视觉一致）。

CI 行为：本测试仅校验 disk 上的图标满足规范，**不重新渲染**。开发者修改 SVG 之后
需要手动跑 ``uv run python scripts/generate_pwa_icons.py`` 重新生成 PNG / ICO 并
commit。
"""

from __future__ import annotations

import hashlib
import json
import re
import struct
from collections.abc import Iterable
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ICONS_DIR = REPO_ROOT / "src" / "ai_intervention_agent" / "icons"
MANIFEST_PATH = ICONS_DIR / "manifest.webmanifest"
TEMPLATE_PATH = (
    REPO_ROOT / "src" / "ai_intervention_agent" / "templates" / "web_ui.html"
)
STATIC_JS_DIR = REPO_ROOT / "src" / "ai_intervention_agent" / "static" / "js"
VSCODE_PACKAGE_PATH = REPO_ROOT / "packages" / "vscode" / "package.json"
NOTIFICATION_MANAGER_PATH = STATIC_JS_DIR / "notification-manager.js"

WEB_ASSET_RE = re.compile(
    r"""["'](?P<path>/(?:static|icons|sounds|fonts)/[^"'?#]+|/manifest\.webmanifest|/notification-service-worker\.js)"""
)

# CSS 中 ``url(/static/...)`` / ``url(/icons/...)`` 没有引号的形式
# （也允许 ``url("...")`` / ``url('...')``），单独识别。
WEB_ASSET_CSS_URL_RE = re.compile(
    r"""url\(\s*["']?(?P<path>/(?:static|icons|sounds|fonts)/[^"'?#)\s]+)["']?\s*\)"""
)


def _png_dimensions(path: Path) -> tuple[int, int]:
    """读取 PNG IHDR 宽高，不引入 Pillow 依赖。"""
    data = path.read_bytes()
    assert data.startswith(b"\x89PNG\r\n\x1a\n"), f"{path.name} 不是 PNG 文件"
    return struct.unpack(">II", data[16:24])


def _icons_path_from_src(src: str) -> Path:
    assert src.startswith("/icons/"), f"PWA icon src 必须是 /icons/ 路径：{src!r}"
    rel = src.removeprefix("/icons/")
    assert "/" not in rel and ".." not in rel, (
        f"PWA icon src 不应包含子路径或穿越：{src!r}"
    )
    return ICONS_DIR / rel


def _web_route_to_path(route: str) -> Path:
    """把浏览器路由 ``/static/...`` ``/icons/...`` 映射回 src layout 内的实际路径。

    R76 src/ layout 后所有静态资产都迁入 ``src/ai_intervention_agent/`` 包内，
    所以路由前面统一拼包前缀。"""
    pkg_root = REPO_ROOT / "src" / "ai_intervention_agent"
    clean = route.rstrip("/")
    if clean == "/manifest.webmanifest":
        return MANIFEST_PATH
    if clean == "/notification-service-worker.js":
        return STATIC_JS_DIR / "notification-service-worker.js"
    return pkg_root / clean.lstrip("/")


def _production_web_sources() -> Iterable[Path]:
    """覆盖所有线上会被浏览器加载的 web 源文件。

    扩展点（相比 r32 的最初版本）：把 ``static/css/*.css`` 也纳入扫描——
    ``url(/static/...)`` / ``url(/icons/...)`` 等 CSS 资源引用一旦失效，浏览器
    背景图就会消失。同时**保留** r32 的 ``*.min.js`` 排除，因为：

    * 项目自产 ``*.min.js``（``app.min.js`` / ``i18n.min.js`` 等）由
      ``scripts/minify_assets.py`` 自动从同名源文件压缩生成，资源引用与源文件
      字节级保留；扫源文件已经覆盖；
    * upstream ``*.min.js``（``prism.min.js`` / ``lottie.min.js`` 等）的内部
      字符串是 upstream 团队的契约，不是本项目的资源完整性范畴；如果它们
      内部有 path 引用，应在 upstream 修复，本项目扫描捕到只会是噪声。

    ``static/js/prism-components/*.js`` 同样故意排除——upstream Prism 在
    runtime 根据 highlight 时检测到的语言**动态计算**子语言路径
    （``Prism.plugins.autoloader`` 拼字符串），不会作为字面量出现在源代码里。
    """

    yield TEMPLATE_PATH
    for path in sorted(STATIC_JS_DIR.glob("*.js")):
        if path.name.endswith(".min.js"):
            continue
        yield path
    static_css_dir = REPO_ROOT / "src" / "ai_intervention_agent" / "static" / "css"
    if static_css_dir.is_dir():
        for path in sorted(static_css_dir.glob("*.css")):
            if path.name.endswith(".min.css"):
                continue
            yield path


def test_manifest_icon_files_exist_and_match_declared_png_sizes() -> None:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    icons = manifest.get("icons")
    assert isinstance(icons, list) and icons, "manifest.webmanifest 必须声明 icons"

    purposes = set()
    for icon in icons:
        assert isinstance(icon, dict), "manifest icons 条目必须是对象"
        src = str(icon.get("src", ""))
        icon_path = _icons_path_from_src(src)
        assert icon_path.is_file(), f"manifest 引用的 PWA 图标文件不存在：{src}"

        purpose = str(icon.get("purpose", "any"))
        purposes.update(part.strip() for part in purpose.split())

        if icon.get("type") == "image/png":
            sizes = str(icon.get("sizes", ""))
            match = re.fullmatch(r"(\d+)x(\d+)", sizes)
            assert match, f"PNG icon 必须声明固定尺寸：{src} sizes={sizes!r}"
            expected = (int(match.group(1)), int(match.group(2)))
            assert _png_dimensions(icon_path) == expected, (
                f"{src} 实际尺寸与 manifest sizes 不一致"
            )

    assert "maskable" in purposes, "PWA manifest 必须包含 maskable 图标"


def test_manifest_covers_pwa_installation_icon_sizes() -> None:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    icons = [icon for icon in manifest.get("icons", []) if isinstance(icon, dict)]

    # 每个尺寸可能同时被 any / maskable 两条 entry 占用，按 (size, purpose)
    # 索引避免后加入的 entry 把前一条覆盖掉。
    by_size_purpose: dict[tuple[str, str], dict] = {}
    for icon in icons:
        sizes = str(icon.get("sizes"))
        for purpose in str(icon.get("purpose", "any")).split():
            by_size_purpose[(sizes, purpose)] = icon

    for size in ("72x72", "96x96", "128x128", "144x144", "192x192", "512x512"):
        icon = by_size_purpose.get((size, "any"))
        assert icon is not None, f"PWA manifest 应覆盖常见安装图标尺寸（any）：{size}"
        assert icon.get("type") == "image/png", f"{size} any PWA icon 应使用 PNG"

    # Lighthouse PWA audit 推荐 192 与 512 两档都提供 maskable，
    # 缺 192 maskable 会让 Android Chrome 把 512 下采样到 192 启动器槽位 → 毛刺。
    for size in ("192x192", "512x512"):
        maskable = by_size_purpose.get((size, "maskable"))
        assert maskable is not None, (
            f"PWA manifest 必须提供 {size} maskable 图标（Lighthouse PWA audit 推荐）"
        )
        assert maskable.get("type") == "image/png", (
            f"{size} maskable icon 应使用 PNG（W3C maskable spec 要求实色画布）"
        )


def test_web_ui_icon_links_reference_existing_assets() -> None:
    template = TEMPLATE_PATH.read_text(encoding="utf-8")
    hrefs = re.findall(r'href="(/icons/[^"]+)"', template)
    assert hrefs, "web_ui.html 应声明 favicon / apple-touch-icon / mask-icon"

    for href in hrefs:
        assert _icons_path_from_src(href).is_file(), (
            f"HTML 引用的图标文件不存在：{href}"
        )


def test_favicon_ico_asset_exists_for_browser_default_request() -> None:
    icon_path = ICONS_DIR / "icon.ico"
    assert icon_path.is_file(), "/favicon.ico 路由依赖 icons/icon.ico，文件必须存在"
    header = icon_path.read_bytes()[:6]
    assert header[:4] == b"\x00\x00\x01\x00", "icons/icon.ico 必须是 ICO 文件"
    assert int.from_bytes(header[4:6], "little") >= 1, "ICO 文件至少需要包含一个图标"


def test_production_web_asset_routes_reference_existing_files() -> None:
    missing: list[str] = []
    for source in _production_web_sources():
        text = source.read_text(encoding="utf-8")
        for match in WEB_ASSET_RE.finditer(text):
            route = match.group("path")
            path = _web_route_to_path(route)
            if not path.exists():
                missing.append(f"{source.relative_to(REPO_ROOT)} -> {route}")
        # CSS 文件还要扫 ``url(...)`` 形式的引用（无引号或单/双引号都算）
        if source.suffix == ".css":
            for match in WEB_ASSET_CSS_URL_RE.finditer(text):
                route = match.group("path")
                path = _web_route_to_path(route)
                if not path.exists():
                    missing.append(f"{source.relative_to(REPO_ROOT)} -> url({route})")

    assert not missing, "生产 Web 源码引用了不存在的静态资产：\n  " + "\n  ".join(
        missing
    )


def test_vscode_package_declared_icon_assets_exist() -> None:
    pkg = json.loads(VSCODE_PACKAGE_PATH.read_text(encoding="utf-8"))
    vscode_dir = VSCODE_PACKAGE_PATH.parent

    icon = pkg.get("icon")
    assert isinstance(icon, str) and icon, "VSCode package.json 必须声明 icon"
    assert (vscode_dir / icon).is_file(), f"VSCode 扩展 icon 文件不存在：{icon}"

    containers = pkg.get("contributes", {}).get("viewsContainers", {})
    for entries in containers.values():
        for entry in entries:
            declared_icon = entry.get("icon")
            if declared_icon:
                assert (vscode_dir / declared_icon).is_file(), (
                    f"VSCode activity bar icon 文件不存在：{declared_icon}"
                )


def test_vscode_package_literal_file_entries_exist() -> None:
    """VSCode package.json.files 的源码/资源字面量应在仓库中存在。"""
    pkg = json.loads(VSCODE_PACKAGE_PATH.read_text(encoding="utf-8"))
    vscode_dir = VSCODE_PACKAGE_PATH.parent
    missing: list[str] = []

    for entry in pkg.get("files", []):
        assert isinstance(entry, str), "package.json files 条目必须是字符串"
        if any(ch in entry for ch in "*?["):
            # dist/**/*.js 等构建产物 glob 由 npm run compile/package 验证。
            continue
        if not (vscode_dir / entry).exists():
            missing.append(entry)

    assert not missing, (
        "VSCode package.json.files 声明了不存在的源码/资源：\n  " + "\n  ".join(missing)
    )


def test_default_notification_sound_asset_exists_and_is_wav() -> None:
    sound_path = REPO_ROOT / "src" / "ai_intervention_agent" / "sounds" / "deng.wav"
    assert sound_path.is_file(), "默认通知声音 /sounds/deng.wav 必须随仓库发布"
    data = sound_path.read_bytes()
    assert data[:4] == b"RIFF" and data[8:12] == b"WAVE", (
        "sounds/deng.wav 必须是浏览器可解码的 WAV 文件"
    )

    source = NOTIFICATION_MANAGER_PATH.read_text(encoding="utf-8")
    assert "DEFAULT_NOTIFICATION_SOUND_URL = '/sounds/deng.wav'" in source
    assert "deng.mp3" not in source, "默认通知声音不应再引用缺失的 deng.mp3"


# ──────────────────────────────────────────────────────────────────────────
# 紧随 r32 的"自检 + 循环验证"批次新增的回归测试
# 每条都对应根因复盘 / 类比扫描时发现的盲区，注释里写清楚锁的是哪一个
# ──────────────────────────────────────────────────────────────────────────


def _ico_image_sizes(path: Path) -> list[tuple[int, int]]:
    """解析 ICO 文件目录区，返回所有内嵌图像 (width, height) 列表。

    ICO 格式：6 字节 header + N×16 字节 directory entries。Width/height 字节
    为 0 表示 256（ICO format 用 1 字节存尺寸所以 256 必须特别表示）。
    """

    data = path.read_bytes()
    if len(data) < 6:
        return []
    reserved, image_type, num_images = struct.unpack("<HHH", data[:6])
    sizes: list[tuple[int, int]] = []
    for i in range(num_images):
        entry = data[6 + i * 16 : 6 + (i + 1) * 16]
        if len(entry) < 16:
            break
        width = entry[0] or 256
        height = entry[1] or 256
        sizes.append((width, height))
    return sizes


def test_favicon_ico_contains_required_multi_sizes() -> None:
    """``icons/icon.ico`` 必须是多尺寸 ICO，至少包含 16×16 与 32×32。

    根因复盘：r32 把 ICO 从原 v1.5.35 的双尺寸（16+32，5430 字节）覆盖成单一
    32×32（4414 字节），浏览器 tab 标签页（16×16 渲染槽）需要从 32×32 强制
    下采样，肉眼可见模糊——这就是用户感知的 "PWA 图标不正确"。这个 test 的
    存在是阻止任何"先有 ICO 就行"的 regression 再次混进 main。
    """

    icon_path = ICONS_DIR / "icon.ico"
    sizes = _ico_image_sizes(icon_path)
    assert sizes, f"icon.ico 解析失败或不含图像目录：{icon_path}"

    width_set = {w for (w, _) in sizes}
    required = {16, 32}
    missing = required - width_set
    assert not missing, (
        f"icon.ico 必须至少包含 16×16 与 32×32 双尺寸（浏览器 tab 槽 16，桌面 32），"
        f"当前 ICO 实际尺寸 = {sorted(width_set)}，缺失 = {sorted(missing)}"
    )

    assert len(sizes) >= 2, (
        f"icon.ico 必须是 multi-size ICO（至少 2 个尺寸），当前只有 {len(sizes)} 个"
    )


def test_maskable_icon_distinct_from_any_icon() -> None:
    """``icon-maskable-{192,512}.png`` 与对应 any 版本必须**字节不同**。

    W3C maskable 规范要求 maskable 图标实色填充整张 canvas + 主体落在中心
    80% safe zone 内；"any" 图标允许保留透明角和延伸到边缘。两者**视觉设计**
    不同，r32 把 maskable PNG 与 any PNG 复制成同一份字节就会同时违反两边
    的视觉契约（maskable 角透明、any 主体被压缩）。

    192 与 512 两档都验：r40 引入 192 maskable 时同样可能因为脚本 bug /
    渲染 fallback 让两者字节相同，这条 test 把 r32 的 512 锁同步扩展到 192。
    """

    pairs = (
        (ICONS_DIR / "icon-192.png", ICONS_DIR / "icon-maskable-192.png", "192x192"),
        (ICONS_DIR / "icon-512.png", ICONS_DIR / "icon-maskable-512.png", "512x512"),
    )
    for any_path, maskable_path, size_label in pairs:
        assert any_path.is_file(), f"missing: {any_path}"
        assert maskable_path.is_file(), f"missing: {maskable_path}"

        any_hash = hashlib.sha256(any_path.read_bytes()).hexdigest()
        maskable_hash = hashlib.sha256(maskable_path.read_bytes()).hexdigest()
        assert any_hash != maskable_hash, (
            f"{maskable_path.name} 与 {any_path.name} ({size_label}) 字节完全"
            "相同——maskable 与 any purpose 的视觉设计必须独立。请运行 "
            "`uv run python scripts/generate_pwa_icons.py` 从 "
            "icons/icon-maskable.svg 重新生成 maskable PNG。"
        )


def _png_alpha_at(path: Path, points: list[tuple[int, int]]) -> list[int]:
    """读取 PNG 指定坐标点的 alpha 值（不依赖 Pillow 等额外库）。

    最小化 PNG 解码：只读 IDAT 块、PNG filter 反算、抽 alpha 字节。仅支持
    RGBA 8-bit 非交错（``color_type=6 bit_depth=8 interlace=0``），其他格式
    raise 异常。
    """

    import zlib

    data = path.read_bytes()
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError(f"{path.name} 不是 PNG")
    width, height = struct.unpack(">II", data[16:24])
    bit_depth = data[24]
    color_type = data[25]
    interlace = data[28]
    if color_type != 6 or bit_depth != 8 or interlace != 0:
        raise ValueError(
            f"{path.name} 必须是 RGBA8 非交错 PNG（实际 ct={color_type} "
            f"bd={bit_depth} interlace={interlace}）"
        )

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
    bytes_per_row = 4 * width + 1  # +1 for filter byte
    pixels = bytearray()
    prev_row = bytes(width * 4)
    for y in range(height):
        row_start = y * bytes_per_row
        filter_byte = raw[row_start]
        row = bytearray(raw[row_start + 1 : row_start + bytes_per_row])
        if filter_byte == 0:
            pass
        elif filter_byte == 1:  # Sub
            for i in range(4, len(row)):
                row[i] = (row[i] + row[i - 4]) & 0xFF
        elif filter_byte == 2:  # Up
            for i in range(len(row)):
                row[i] = (row[i] + prev_row[i]) & 0xFF
        elif filter_byte == 3:  # Average
            for i in range(len(row)):
                left = row[i - 4] if i >= 4 else 0
                up = prev_row[i]
                row[i] = (row[i] + ((left + up) // 2)) & 0xFF
        elif filter_byte == 4:  # Paeth
            for i in range(len(row)):
                left = row[i - 4] if i >= 4 else 0
                up = prev_row[i]
                up_left = prev_row[i - 4] if i >= 4 else 0
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
            raise ValueError(f"未知 PNG filter type: {filter_byte}")
        pixels.extend(row)
        prev_row = bytes(row)

    out: list[int] = []
    for x, y in points:
        idx = (y * width + x) * 4
        out.append(pixels[idx + 3])
    return out


def test_maskable_icon_has_opaque_canvas() -> None:
    """``icon-maskable-{192,512}.png`` 整张 canvas 必须实色（无透明角）。

    W3C maskable 规范：OS 蒙板（圆形 / squircle / teardrop / 任意形状）会按设备
    形状裁切；透明角在裁切后会留下视觉空洞，与系统其他图标不一致。本测试只
    采样 4 个角和中心 5 个点（不读全图，对 CI 时间友好），任何角落 alpha=0
    都判失败。

    192 与 512 都验：r40 把 192 maskable 加进 manifest 后，rsvg-convert 在
    192px 渲染时若 stride padding 异常也可能在四角引入半透明像素。
    """

    expected_sizes = {
        "icon-maskable-192.png": 192,
        "icon-maskable-512.png": 512,
    }

    for filename, expected in expected_sizes.items():
        path = ICONS_DIR / filename
        width, height = _png_dimensions(path)
        assert width == height == expected, (
            f"{filename} 尺寸应为 {expected}×{expected}，实际 {width}×{height}"
        )

        corners = [
            (0, 0),
            (width - 1, 0),
            (0, height - 1),
            (width - 1, height - 1),
            (5, 5),
            (width - 6, 5),
            (5, height - 6),
            (width - 6, height - 6),
        ]
        alphas = _png_alpha_at(path, corners)
        transparent_corners = [
            pt for pt, a in zip(corners, alphas, strict=True) if a < 250
        ]
        assert not transparent_corners, (
            f"{filename} 不应有透明角落（W3C maskable spec：OS 蒙板裁切后会留空洞）。"
            f"以下采样点 alpha < 250: {transparent_corners}"
        )


def test_apple_touch_icon_has_opaque_corners() -> None:
    """``apple-touch-icon.png`` 角落必须不透明。

    iOS 14+ 的 ``Add to Home Screen`` 把 apple-touch-icon 直接合成到主屏幕，
    不支持 alpha 透明度——透明角会被填充黑（深色模式）或白（浅色模式），
    与系统其他图标视觉割裂。
    """

    path = ICONS_DIR / "apple-touch-icon.png"
    width, height = _png_dimensions(path)
    assert width == height == 180, (
        f"apple-touch-icon.png 尺寸应为 180×180（iOS Safari 添加到主屏幕硬性要求），"
        f"实际 {width}×{height}"
    )

    corners = [(0, 0), (width - 1, 0), (0, height - 1), (width - 1, height - 1)]
    alphas = _png_alpha_at(path, corners)
    transparent_corners = [pt for pt, a in zip(corners, alphas, strict=True) if a < 250]
    assert not transparent_corners, (
        "apple-touch-icon.png 角落必须不透明（iOS 不支持 alpha，会用黑/白填充）。"
        f"以下角落 alpha < 250: {transparent_corners}"
    )


def test_maskable_source_svg_exists_and_distinct_from_any_svg() -> None:
    """maskable 必须有独立的 SVG 源，不能与 any purpose 共用。

    锁定 ``src/ai_intervention_agent/icons/icon-maskable.svg`` 文件存在 + 与
    ``src/ai_intervention_agent/icons/icon.svg`` 字节不同。这是脚本
    ``scripts/generate_pwa_icons.py`` 的输入契约——如果 maskable.svg 丢失，
    ``--check`` 模式会立即报错；如果有人误将 ``icon.svg`` 复制成 ``icon-maskable.svg``
    就会让两者输出 byte-identical PNG，再次回到 r32 之前的 bug。
    """

    any_svg = ICONS_DIR / "icon.svg"
    maskable_svg = ICONS_DIR / "icon-maskable.svg"
    assert any_svg.is_file(), f"missing: {any_svg}"
    assert maskable_svg.is_file(), (
        f"missing: {maskable_svg}（PWA maskable 必须独立 SVG 源；"
        "见 scripts/generate_pwa_icons.py 文档头）"
    )

    any_hash = hashlib.sha256(any_svg.read_bytes()).hexdigest()
    maskable_hash = hashlib.sha256(maskable_svg.read_bytes()).hexdigest()
    assert any_hash != maskable_hash, (
        "icon-maskable.svg 与 icon.svg 字节完全相同——必须为 maskable 重新设计"
        "（实色背景 + 主体缩到中心 80% safe zone 内）。"
    )


def test_icon_svg_byte_parity_between_web_and_vscode() -> None:
    """``src/ai_intervention_agent/icons/icon.svg`` 与 ``packages/vscode/icon.svg`` 必须 byte-identical。

    背景：``packages/vscode/`` 是 VSCode 扩展打包根，``vsce package`` 不会跨
    extension root 引用 ``../../src/ai_intervention_agent/icons/icon.svg``，所以扩展端必须有自己的副本。
    两份字节相同的文件没有任何 byte-parity 锁就会随时间漂移——一边更新，
    另一边遗忘。这就是 PWA r32 之前同样的失败模式（声明 vs 实存不对齐）的
    "升级版"：声明都对，但**字节内容**对不上。

    类比 ``tests/test_tri_state_panel_parity.py`` 已经为 tri-state-panel JS/CSS
    建立的 byte-parity 锁，本 test 把同样的保护扩展到 icon.svg。

    如果未来还有其它"两份镜像"对（例如 lottie/sprout.json、prism.min.js），
    建议复用同一类 byte-parity 模式而不是各自一个测试。
    """

    web_svg = ICONS_DIR / "icon.svg"
    vscode_svg = REPO_ROOT / "packages" / "vscode" / "icon.svg"
    assert web_svg.is_file(), f"missing: {web_svg}"
    assert vscode_svg.is_file(), f"missing: {vscode_svg}"

    web_hash = hashlib.sha256(web_svg.read_bytes()).hexdigest()
    vscode_hash = hashlib.sha256(vscode_svg.read_bytes()).hexdigest()
    assert web_hash == vscode_hash, (
        f"icon.svg byte parity 失败：\n"
        f"  src/ai_intervention_agent/icons/icon.svg  sha256 = {web_hash[:32]}…\n"
        f"  packages/vscode/icon.svg                  sha256 = {vscode_hash[:32]}…\n"
        f"  修法：把 src/ai_intervention_agent/icons/icon.svg 复制到 packages/vscode/icon.svg "
        f"（cp src/ai_intervention_agent/icons/icon.svg packages/vscode/icon.svg）。两边任何一边修改"
        f"必须同步，与 tests/test_tri_state_panel_parity.py 同源策略。"
    )


def test_lottie_sprout_byte_parity_between_web_and_vscode() -> None:
    """``static/lottie/sprout.json`` 与 ``packages/vscode/lottie/sprout.json`` byte-identical。

    与 icon.svg 的理由相同——这两份文件视觉上是同一个 Lottie 动画，但字节
    层面没有锁就会随时间漂移；把它们一并锁住，避免再次出现"PWA 图标不正确"
    那种"声明对应正确、字节内容错位"的问题。
    """

    web_lottie = (
        REPO_ROOT
        / "src"
        / "ai_intervention_agent"
        / "static"
        / "lottie"
        / "sprout.json"
    )
    vscode_lottie = REPO_ROOT / "packages" / "vscode" / "lottie" / "sprout.json"
    assert web_lottie.is_file(), f"missing: {web_lottie}"
    assert vscode_lottie.is_file(), f"missing: {vscode_lottie}"

    web_hash = hashlib.sha256(web_lottie.read_bytes()).hexdigest()
    vscode_hash = hashlib.sha256(vscode_lottie.read_bytes()).hexdigest()
    assert web_hash == vscode_hash, (
        f"sprout.json byte parity 失败：\n"
        f"  static/lottie/sprout.json                  sha256 = {web_hash[:32]}…\n"
        f"  packages/vscode/lottie/sprout.json         sha256 = {vscode_hash[:32]}…\n"
        f"  修法：cp static/lottie/sprout.json packages/vscode/lottie/sprout.json"
    )


# ──────────────────────────────────────────────────────────────────────────
# r40 PWA 修复批次：apple-touch-icon 归位 / 192 maskable 引入 / 显式
# prefer_related_applications。每条 test 的注释都说明它锁的是哪一面 regression。
# ──────────────────────────────────────────────────────────────────────────


def test_pwa_manifest_does_not_declare_apple_touch_icon() -> None:
    """``manifest.webmanifest`` 不应声明 ``apple-touch-icon.png``（180×180）。

    根因：iOS Safari 在 ``Add to Home Screen`` 时**不读** ``manifest.webmanifest``，
    它读 HTML ``<link rel="apple-touch-icon" sizes="180x180" href="...">``。把
    180×180 列在 manifest icons 里，结果是 Android Chrome PWA installer 把它
    视为一个 ``any`` purpose 的 180px 候选，**可能在选择 192 启动器槽位时把
    180 拉伸/挤压填充**，导致用户感知"PWA 安装后图标不正确"。

    apple-touch-icon.png 仍需要存在 disk + ``templates/web_ui.html`` 的
    ``<link rel="apple-touch-icon">`` 仍要保留——本 test 只锁定 manifest
    icons 里**不要**有 180×180 / apple-touch 字面量。
    """

    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    icons = manifest.get("icons", [])

    offending: list[dict] = []
    for icon in icons:
        if not isinstance(icon, dict):
            continue
        src = str(icon.get("src", ""))
        sizes = str(icon.get("sizes", ""))
        if "apple-touch" in src or sizes == "180x180":
            offending.append(icon)

    assert not offending, (
        "manifest.webmanifest 不应声明 apple-touch-icon / 180×180（iOS 不读"
        " manifest，Android Chrome 会把它误选为 192 启动器槽位）。多余条目："
        f"{offending}"
    )


def test_pwa_manifest_explicitly_disables_related_applications() -> None:
    """``manifest.webmanifest`` 必须显式声明 ``prefer_related_applications: false``。

    背景：``prefer_related_applications`` 默认值在 W3C spec 上是 ``false``，但
    Chrome / Edge 安装 banner 在缺省字段时会偶发显示"安装相关应用"提示
    （当 ``related_applications`` 也没声明时这是空操作，但 banner 文案仍可
    能让用户困惑）。显式 ``false`` 让 PWA installability check 100% 走"安装
    本 PWA"路径，无任何提示模糊性。
    """

    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    assert manifest.get("prefer_related_applications") is False, (
        "manifest.webmanifest 必须显式声明 prefer_related_applications=false，"
        "避免 Chrome 安装 banner 在某些版本上回退到模糊提示。"
    )


def test_pwa_manifest_icon_purposes_explicitly_declared() -> None:
    """每个 manifest icon 必须显式声明 ``purpose`` 字段。

    根因：W3C spec 规定 ``purpose`` 缺省为 ``any``，但**显式优于隐式**。在
    r32 之前的 manifest 里 favicon-16/32 没有 purpose 字段，依赖默认值；
    日后任何 PWA installer 实现微调（例如 Chrome 把缺省值改作 "monochrome"
    或对 ``maskable`` 提升优先级），都可能让缺省 entry 的展示行为发生静默
    漂移。锁定 explicit 让 manifest 行为对 spec 演进免疫。
    """

    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    icons = manifest.get("icons", [])

    missing: list[str] = []
    for icon in icons:
        if not isinstance(icon, dict):
            continue
        if "purpose" not in icon:
            missing.append(str(icon.get("src", icon)))

    assert not missing, (
        "manifest.webmanifest 中以下 icon entry 缺 explicit purpose 字段："
        f"{missing}。每个 icon 都应显式写 purpose: any / maskable / monochrome。"
    )
