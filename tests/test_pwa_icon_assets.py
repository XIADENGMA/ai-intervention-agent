"""PWA 图标资产必须与 manifest / HTML 引用保持一致。

历史问题：``icons/manifest.webmanifest`` 和 ``templates/web_ui.html`` 已经声明了
多组 PNG PWA 图标，但仓库里只有 ``icon.svg``。浏览器安装 PWA 时这些 PNG 404，
会回退为截图或错误图标。
"""

from __future__ import annotations

import json
import re
import struct
from collections.abc import Iterable
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ICONS_DIR = REPO_ROOT / "icons"
MANIFEST_PATH = ICONS_DIR / "manifest.webmanifest"
TEMPLATE_PATH = REPO_ROOT / "templates" / "web_ui.html"
STATIC_JS_DIR = REPO_ROOT / "static" / "js"
VSCODE_PACKAGE_PATH = REPO_ROOT / "packages" / "vscode" / "package.json"
NOTIFICATION_MANAGER_PATH = STATIC_JS_DIR / "notification-manager.js"

WEB_ASSET_RE = re.compile(
    r"""["'](?P<path>/(?:static|icons|sounds|fonts)/[^"'?#]+|/manifest\.webmanifest|/notification-service-worker\.js)"""
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
    clean = route.rstrip("/")
    if clean == "/manifest.webmanifest":
        return MANIFEST_PATH
    if clean == "/notification-service-worker.js":
        return STATIC_JS_DIR / "notification-service-worker.js"
    return REPO_ROOT / clean.lstrip("/")


def _production_web_sources() -> Iterable[Path]:
    yield TEMPLATE_PATH
    for path in sorted(STATIC_JS_DIR.glob("*.js")):
        if path.name.endswith(".min.js"):
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
    by_size = {
        str(icon.get("sizes")): icon
        for icon in manifest.get("icons", [])
        if isinstance(icon, dict)
    }

    for size in ("72x72", "96x96", "128x128", "144x144", "192x192", "512x512"):
        icon = by_size.get(size)
        assert icon is not None, f"PWA manifest 应覆盖常见安装图标尺寸：{size}"
        assert icon.get("type") == "image/png", f"{size} PWA icon 应使用 PNG"

    maskable_512 = [
        icon
        for icon in manifest.get("icons", [])
        if isinstance(icon, dict)
        and icon.get("sizes") == "512x512"
        and "maskable" in str(icon.get("purpose", "")).split()
    ]
    assert maskable_512, "PWA manifest 必须提供 512x512 maskable 图标"


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
    sound_path = REPO_ROOT / "sounds" / "deng.wav"
    assert sound_path.is_file(), "默认通知声音 /sounds/deng.wav 必须随仓库发布"
    data = sound_path.read_bytes()
    assert data[:4] == b"RIFF" and data[8:12] == b"WAVE", (
        "sounds/deng.wav 必须是浏览器可解码的 WAV 文件"
    )

    source = NOTIFICATION_MANAGER_PATH.read_text(encoding="utf-8")
    assert "DEFAULT_NOTIFICATION_SOUND_URL = '/sounds/deng.wav'" in source
    assert "deng.mp3" not in source, "默认通知声音不应再引用缺失的 deng.mp3"
