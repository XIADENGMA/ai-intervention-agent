"""R723: the apple-touch icon is a full-bleed opaque tile, never a black-framed one.

Symptom: the icon saved to the iOS home screen ("Add to Home Screen") had a black
border.

Root cause: ``apple-touch-icon.png`` was rendered from ``icon.svg``, a rounded plate
inset by 10 of 120 units on a transparent canvas, and ``generate_pwa_icons.py`` then
"filled" every transparent pixel with the colour sampled at pixel (1, 1). That pixel is
transparent, so the colour was black: a third of the 180x180 PNG (the whole margin ring
and the corners) was solid black, and iOS showed it as a frame around the icon. The old
test only asserted that the four corner pixels were opaque, which a black fill satisfies.

What is locked here:

* the shipped PNG has no alpha channel and no dark pixel, in particular none in its frame;
* its source ``icon-apple-touch.svg`` is a full-bleed, opaque, static square;
* the generator refuses to write an apple-touch or maskable icon whose source renders
  translucent pixels, writes nothing in that case, and ``--check`` notices an apple-touch
  icon on disk that has an alpha channel or translucent pixels;
* the page links the icon with a URL that changes when the file does, because ``/icons/*``
  is cached for a week and by the service worker and the project version is not bumped
  for every regeneration;
* every pre-commit hook ``files`` filter matches at least one file (``check-pwa-icons-fresh``
  used ``^icons/``, a directory that does not exist, so it never ran).
"""

from __future__ import annotations

import html
import importlib.util
import os
import re
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType

import pytest
import yaml

from tests.test_pwa_icon_assets import _decode_png_pixels, _png_alpha_at

REPO_ROOT = Path(__file__).resolve().parent.parent
PACKAGE_DIR = REPO_ROOT / "src" / "ai_intervention_agent"
ICONS_DIR = PACKAGE_DIR / "icons"
APPLE_TOUCH_PNG = ICONS_DIR / "apple-touch-icon.png"
APPLE_TOUCH_SVG = ICONS_DIR / "icon-apple-touch.svg"
TEMPLATE_PATH = PACKAGE_DIR / "templates" / "web_ui.html"
GENERATOR_PATH = REPO_ROOT / "scripts" / "generate_pwa_icons.py"
PRECOMMIT_PATH = REPO_ROOT / ".pre-commit-config.yaml"

SVG_NS = "http://www.w3.org/2000/svg"
PNG_COLOR_TYPE_RGB = 2
PNG_COLOR_TYPE_RGBA = 6
FRAME_WIDTH = 12
LIGHT = (232, 236, 245)


def _frame_pixels(
    width: int, height: int, bpp: int, pixels: bytearray
) -> Iterator[tuple[int, int, tuple[int, ...]]]:
    for y in range(height):
        for x in range(width):
            if (
                x < FRAME_WIDTH
                or y < FRAME_WIDTH
                or x >= width - FRAME_WIDTH
                or y >= height - FRAME_WIDTH
            ):
                start = (y * width + x) * bpp
                yield x, y, tuple(pixels[start : start + 3])


class TestShippedApplePng:
    def test_has_the_size_ios_asks_for_and_no_alpha_channel(self) -> None:
        data = APPLE_TOUCH_PNG.read_bytes()
        width = int.from_bytes(data[16:20], "big")
        height = int.from_bytes(data[20:24], "big")
        assert (width, height) == (180, 180)
        assert data[24] == 8
        assert data[25] == PNG_COLOR_TYPE_RGB, (
            "apple-touch-icon.png must be RGB without an alpha channel: iOS paints "
            "transparent pixels black"
        )

    def test_frame_is_light_not_black(self) -> None:
        width, height, bpp, pixels = _decode_png_pixels(APPLE_TOUCH_PNG)
        dark = [
            (x, y, rgb)
            for x, y, rgb in _frame_pixels(width, height, bpp, pixels)
            if min(rgb) < 200
        ]
        assert not dark, (
            f"{len(dark)} pixel(s) in the {FRAME_WIDTH}px frame of apple-touch-icon.png are "
            f"dark, e.g. {dark[:3]}: iOS would show them as a black border"
        )

    def test_has_no_near_black_pixel_anywhere(self) -> None:
        width, height, bpp, pixels = _decode_png_pixels(APPLE_TOUCH_PNG)
        black = sum(
            1
            for start in range(0, width * height * bpp, bpp)
            if max(pixels[start : start + 3]) < 48
        )
        assert black == 0, f"{black} near-black pixel(s) in apple-touch-icon.png"

    def test_frame_uses_the_tile_background_colour(self) -> None:
        width, height, bpp, pixels = _decode_png_pixels(APPLE_TOUCH_PNG)
        for x, y in ((0, 0), (width - 1, 0), (0, height - 1), (width - 1, height - 1)):
            start = (y * width + x) * bpp
            rgb = tuple(pixels[start : start + 3])
            assert all(abs(a - b) <= 12 for a, b in zip(rgb, LIGHT, strict=True)), (
                f"corner ({x}, {y}) is {rgb}, expected about {LIGHT}"
            )


class TestSourceSvg:
    @staticmethod
    def _root() -> ET.Element:
        return ET.parse(APPLE_TOUCH_SVG).getroot()

    def test_exists_and_is_not_a_copy_of_icon_svg(self) -> None:
        assert APPLE_TOUCH_SVG.is_file()
        assert APPLE_TOUCH_SVG.read_bytes() != (ICONS_DIR / "icon.svg").read_bytes()

    def test_background_is_a_full_bleed_opaque_square(self) -> None:
        root = self._root()
        assert root.get("viewBox") == "0 0 120 120"
        drawables = [el for el in root if el.tag != f"{{{SVG_NS}}}defs"]
        background = drawables[0]
        assert background.tag == f"{{{SVG_NS}}}rect"
        assert (background.get("x"), background.get("y")) == ("0", "0")
        assert (background.get("width"), background.get("height")) == ("120", "120")
        assert background.get("rx") is None
        assert background.get("ry") is None
        assert background.get("opacity") is None
        assert background.get("fill-opacity") is None
        assert background.get("filter") is None

        match = re.fullmatch(r"url\(#([\w-]+)\)", background.get("fill") or "")
        assert match, "the background must be filled with a gradient"
        gradient = root.find(f".//{{{SVG_NS}}}linearGradient[@id='{match.group(1)}']")
        assert gradient is not None
        stops = gradient.findall(f"{{{SVG_NS}}}stop")
        assert len(stops) >= 2
        for stop in stops:
            opacity = re.search(r"stop-opacity\s*:\s*([\d.]+)", stop.get("style", ""))
            assert opacity is None or float(opacity.group(1)) == 1.0, (
                "background gradient stops must be fully opaque"
            )

    def test_is_static(self) -> None:
        animated = [
            el.tag
            for el in self._root().iter()
            if isinstance(el.tag, str)
            and (
                el.tag.rsplit("}", 1)[-1].startswith("animate")
                or el.tag.endswith("}set")
            )
        ]
        assert animated == []

    @pytest.mark.skipif(shutil.which("rsvg-convert") is None, reason="needs librsvg")
    def test_renders_fully_opaque_with_a_light_frame(
        self, generator: ModuleType
    ) -> None:
        width, height, rgba = generator._render_svg_to_rgba(APPLE_TOUCH_SVG, 180)
        assert generator._first_translucent_pixel(width, rgba) is None
        dark = [
            rgb
            for _x, _y, rgb in _frame_pixels(width, height, 4, rgba)
            if min(rgb) < 200
        ]
        assert dark == []


@pytest.fixture
def generator() -> Iterator[ModuleType]:
    name = "generate_pwa_icons_under_test"
    spec = importlib.util.spec_from_file_location(name, GENERATOR_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
        yield module
    finally:
        sys.modules.pop(name, None)


def _install_fake_renderer(
    generator: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    translucent_for: str | None = None,
) -> None:
    def fake_render(svg_path: Path, size: int) -> tuple[int, int, bytearray]:
        rgba = bytearray(bytes((*LIGHT, 255)) * (size * size))
        if svg_path.name == translucent_for:
            rgba[3] = 0
        return size, size, rgba

    monkeypatch.setattr(generator, "_render_svg_to_rgba", fake_render)
    monkeypatch.setattr(generator, "_check_dependencies", lambda: True)


class TestGeneratorSpecs:
    def test_apple_touch_icon_is_opaque_rgb_from_its_own_source(
        self, generator: ModuleType
    ) -> None:
        specs = {spec.filename: spec for spec in generator.PNG_OUTPUTS}
        apple = specs["apple-touch-icon.png"]
        assert apple.source == "apple-touch"
        assert apple.size == 180
        assert apple.require_opaque and apple.drop_alpha
        assert generator.SOURCES["apple-touch"] == APPLE_TOUCH_SVG

    def test_maskable_icons_must_render_opaque_and_any_icons_may_not(
        self, generator: ModuleType
    ) -> None:
        for spec in generator.PNG_OUTPUTS:
            if spec.source == "maskable":
                assert spec.require_opaque and not spec.drop_alpha, spec.filename
            elif spec.source == "any":
                assert not spec.require_opaque and not spec.drop_alpha, spec.filename

    def test_dropping_alpha_requires_opaque_and_the_source_must_exist(
        self, generator: ModuleType
    ) -> None:
        with pytest.raises(ValueError, match="require_opaque"):
            generator.PngSpec("x.png", 10, "any", drop_alpha=True)
        with pytest.raises(ValueError, match="nope"):
            generator.PngSpec("x.png", 10, "nope")

    def test_every_source_exists(self, generator: ModuleType) -> None:
        assert all(path.is_file() for path in generator.SOURCES.values())


class TestGeneratorPixelHelpers:
    def test_first_translucent_pixel(self, generator: ModuleType) -> None:
        width, height = 4, 3
        rgba = bytearray(bytes((10, 20, 30, 255)) * (width * height))
        assert generator._first_translucent_pixel(width, rgba) is None
        rgba[(1 * width + 2) * 4 + 3] = 254
        assert generator._first_translucent_pixel(width, rgba) == (2, 1, 254)
        rgba[3] = 0
        assert generator._first_translucent_pixel(width, rgba) == (0, 0, 0)

    def test_rgb_encoder_drops_alpha_and_round_trips(
        self, generator: ModuleType, tmp_path: Path
    ) -> None:
        width, height = 3, 2
        rgba = bytearray()
        for index in range(width * height):
            rgba.extend((index, 100 + index, 200 + index, 255))
        data = generator._encode_png_rgb(width, height, rgba)
        assert data[25] == PNG_COLOR_TYPE_RGB

        decoded_width, decoded_height, decoded = generator._decode_png_to_rgba(data)
        assert (decoded_width, decoded_height) == (width, height)
        assert bytes(decoded) == bytes(rgba)

        path = tmp_path / "rgb.png"
        path.write_bytes(data)
        assert _decode_png_pixels(path)[2] == 3
        assert _png_alpha_at(path, [(0, 0), (2, 1)]) == [255, 255]

    def test_rgba_encoder_still_writes_color_type_6(
        self, generator: ModuleType
    ) -> None:
        rgba = bytes((1, 2, 3, 4)) * 4
        data = generator._encode_png_rgba(2, 2, rgba)
        assert data[25] == PNG_COLOR_TYPE_RGBA
        assert bytes(generator._decode_png_to_rgba(data)[2]) == rgba

    def test_encoders_reject_a_buffer_of_the_wrong_length(
        self, generator: ModuleType
    ) -> None:
        with pytest.raises(ValueError):
            generator._encode_png_rgba(2, 2, bytes(15))
        with pytest.raises(ValueError):
            generator._encode_png_rgb(2, 2, bytes(15))


class TestGeneratorEndToEnd:
    def test_refuses_a_translucent_apple_touch_source_and_writes_nothing(
        self,
        generator: ModuleType,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        monkeypatch.setattr(generator, "ICONS_DIR", tmp_path)
        _install_fake_renderer(
            generator, monkeypatch, translucent_for="icon-apple-touch.svg"
        )

        assert generator.generate_all() == 1

        assert list(tmp_path.iterdir()) == []
        err = capsys.readouterr().err
        assert "apple-touch-icon.png" in err
        assert "x=0, y=0, alpha=0" in err

    def test_refuses_a_translucent_maskable_source(
        self,
        generator: ModuleType,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        monkeypatch.setattr(generator, "ICONS_DIR", tmp_path)
        _install_fake_renderer(
            generator, monkeypatch, translucent_for="icon-maskable.svg"
        )

        assert generator.generate_all() == 1

        assert list(tmp_path.iterdir()) == []
        assert "icon-maskable-192.png" in capsys.readouterr().err

    def test_any_icons_keep_their_transparency(
        self, generator: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setattr(generator, "ICONS_DIR", tmp_path)
        _install_fake_renderer(generator, monkeypatch, translucent_for="icon.svg")

        assert generator.generate_all() == 0

        assert _png_alpha_at(tmp_path / "icon-192.png", [(0, 0), (1, 0)]) == [0, 255]

    def test_writes_rgb_for_the_apple_touch_icon_and_rgba_for_the_rest(
        self, generator: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setattr(generator, "ICONS_DIR", tmp_path)
        _install_fake_renderer(generator, monkeypatch)

        assert generator.generate_all() == 0

        apple = tmp_path / "apple-touch-icon.png"
        assert apple.read_bytes()[25] == PNG_COLOR_TYPE_RGB
        width, height, bpp, pixels = _decode_png_pixels(apple)
        assert (width, height, bpp) == (180, 180, 3)
        assert bytes(pixels) == bytes(LIGHT) * (180 * 180)
        for name in ("icon-192.png", "icon-maskable-192.png", "favicon-16.png"):
            assert (tmp_path / name).read_bytes()[25] == PNG_COLOR_TYPE_RGBA, name

        assert generator.generate_all(check_only=True) == 0

    def test_check_mode_flags_an_apple_touch_icon_with_an_alpha_channel(
        self,
        generator: ModuleType,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        monkeypatch.setattr(generator, "ICONS_DIR", tmp_path)
        _install_fake_renderer(generator, monkeypatch)
        assert generator.generate_all() == 0
        capsys.readouterr()

        rgba = bytes((*LIGHT, 255)) * (180 * 180)
        (tmp_path / "apple-touch-icon.png").write_bytes(
            generator._encode_png_rgba(180, 180, rgba)
        )

        assert generator.generate_all(check_only=True) == 1
        assert "alpha 通道" in capsys.readouterr().err

    def test_check_mode_flags_a_translucent_pixel_on_disk(
        self,
        generator: ModuleType,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        monkeypatch.setattr(generator, "ICONS_DIR", tmp_path)
        _install_fake_renderer(generator, monkeypatch)
        assert generator.generate_all() == 0
        capsys.readouterr()

        rgba = bytearray(bytes((*LIGHT, 255)) * (180 * 180))
        rgba[(7 * 180 + 5) * 4 + 3] = 254
        (tmp_path / "apple-touch-icon.png").write_bytes(
            generator._encode_png_rgba(180, 180, rgba)
        )

        assert generator.generate_all(check_only=True) == 1
        assert "x=5, y=7, alpha=254" in capsys.readouterr().err

    def test_check_mode_flags_a_translucent_maskable_icon_on_disk(
        self,
        generator: ModuleType,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        monkeypatch.setattr(generator, "ICONS_DIR", tmp_path)
        _install_fake_renderer(generator, monkeypatch)
        assert generator.generate_all() == 0
        capsys.readouterr()

        rgba = bytearray(bytes((*LIGHT, 255)) * (192 * 192))
        rgba[3] = 0
        (tmp_path / "icon-maskable-192.png").write_bytes(
            generator._encode_png_rgba(192, 192, rgba)
        )

        assert generator.generate_all(check_only=True) == 1
        assert "icon-maskable-192.png" in capsys.readouterr().err


class TestTemplateLink:
    def test_template_declares_version_and_file_revision(self) -> None:
        template = TEMPLATE_PATH.read_text(encoding="utf-8")
        assert re.search(
            r'<link\s+rel="apple-touch-icon"\s+sizes="180x180"\s+'
            r'href="/icons/apple-touch-icon\.png\?v=\{\{ version \}\}&amp;r=\{\{ apple_touch_icon_version \}\}"',
            template,
        )

    def test_rendered_page_links_the_icon_with_the_file_revision(self) -> None:
        from ai_intervention_agent.web_ui import WebFeedbackUI, _compute_file_version

        ui = WebFeedbackUI(prompt="r723 apple touch link", port=19005)
        ui.app.config["TESTING"] = True
        client = ui.app.test_client()
        response = client.get("/")
        page = response.get_data(as_text=True)
        response.close()

        match = re.search(r'<link\s+rel="apple-touch-icon"[^>]*\bhref="([^"]+)"', page)
        assert match, "the rendered page must link an apple-touch-icon"
        href = html.unescape(match.group(1))
        version = ui._get_template_context()["version"]
        revision = _compute_file_version(str(APPLE_TOUCH_PNG))
        assert href == f"/icons/apple-touch-icon.png?v={version}&r={revision}"
        assert revision and revision != "1"

        served = client.get(href)
        assert served.status_code == 200
        assert served.mimetype == "image/png"
        assert served.data == APPLE_TOUCH_PNG.read_bytes()
        served.close()

    def test_revision_follows_the_icon_file(self, tmp_path: Path) -> None:
        from ai_intervention_agent.web_ui import WebFeedbackUI, _compute_file_version

        static_dir = tmp_path / "static"
        static_dir.mkdir()
        icons_dir = tmp_path / "icons"
        icons_dir.mkdir()
        icon = icons_dir / "apple-touch-icon.png"
        icon.write_bytes(b"icon")
        os.utime(icon, (1_700_000_123, 1_700_000_123))

        ui = WebFeedbackUI(prompt="r723 revision", port=19006)
        ui._static_dir = static_dir
        _compute_file_version.cache_clear()
        try:
            first = ui._get_template_context()["apple_touch_icon_version"]
            os.utime(icon, (1_700_000_623, 1_700_000_623))
            _compute_file_version.cache_clear()
            second = ui._get_template_context()["apple_touch_icon_version"]
        finally:
            _compute_file_version.cache_clear()

        assert (first, second) == ("00000123", "00000623")


def _tracked_and_untracked_files() -> list[str] | None:
    try:
        completed = subprocess.run(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return completed.stdout.splitlines()


def _hooks_with_file_filters() -> list[tuple[str, str]]:
    config = yaml.safe_load(PRECOMMIT_PATH.read_text(encoding="utf-8"))
    return [
        (hook["id"], hook["files"])
        for repo in config["repos"]
        for hook in repo.get("hooks", [])
        if hook.get("files")
    ]


class TestPreCommitFilters:
    def test_pwa_icons_hook_runs_for_the_icon_sources_and_the_generator(self) -> None:
        pattern = dict(_hooks_with_file_filters())["check-pwa-icons-fresh"]
        for path in (
            "src/ai_intervention_agent/icons/apple-touch-icon.png",
            "src/ai_intervention_agent/icons/icon-apple-touch.svg",
            "src/ai_intervention_agent/icons/icon-maskable.svg",
            "src/ai_intervention_agent/icons/icon.ico",
            "scripts/generate_pwa_icons.py",
        ):
            assert re.search(pattern, path), (
                f"{path} must trigger check-pwa-icons-fresh"
            )
        for path in (
            "src/ai_intervention_agent/static/js/app.js",
            "scripts/generate_docs.py",
            "docs/icons.md",
        ):
            assert not re.search(pattern, path), (
                f"{path} must not trigger check-pwa-icons-fresh"
            )

    def test_every_hook_file_filter_matches_at_least_one_file(self) -> None:
        files = _tracked_and_untracked_files()
        if files is None:
            pytest.skip("not a git checkout")
        dead = [
            f"{hook_id}: {pattern!r}"
            for hook_id, pattern in _hooks_with_file_filters()
            if not any(re.search(pattern, path) for path in files)
        ]
        assert dead == [], (
            "pre-commit hooks whose files filter matches nothing never run: "
            + "; ".join(dead)
        )
