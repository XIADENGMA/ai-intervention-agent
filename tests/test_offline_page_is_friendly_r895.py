"""R895：断线页（离线页）的图标和文字更友好——不再是被斜线划掉的 wifi 加“无法连接到…”，也不再有解释段落。

现象
====

服务停了、或设备断网时，浏览器显示的是 Service Worker 缓存起来的 ``offline.html``。旧页面是一个被整条斜线
划掉的 wifi 图标，标题“无法连接到 AI Intervention Agent”，下面两句解释（“服务可能已停止，或设备当前处于离线
状态。连接恢复后将自动重新加载。”），读起来像是报错，而多数时候只是服务暂时没回来。维护者希望图标和文字都更
友好；看过预览后又觉得那段解释没必要，要求去掉。

现在
====

* 图标：去掉斜线，换成淡橙圆底里的信号波（一个圆点加三道弧，``.icon-badge`` 里的 ``svg.icon``）。四个部分由内
  向外依次亮起，相隔 0.3 s、一圈 1.8 s，只改 ``opacity``、每半圈分五步（``steps(5, end)``），与 R894 的三个点同
  一种动法；“减少动态效果”时常亮不动。真实 Chrome 156（DPR 2、真实 GPU，每个版本 3 轮、每轮 12 s 取中位数，
  占一个核的百分比，Chrome 全部进程合计）：旧图标页 1.06 %，新图标静止 0.50 %，新图标亮起 2.91 %（渲染进程
  1.19 %、GPU 进程 1.59 %、浏览器进程 0.13 %），样式重算每秒 0 次（opacity 动画在合成器上跑）。
* 文字：标题和按钮三种语言各一句——“稍等，服务还没回来 / 再试试”（English：Hang on, the service isn't back
  yet / Try again；繁体是手写的）。解释段落（``.hint``）和 ``MESSAGES`` 里的 ``hint`` 都去掉了；服务恢复时的
  状态提示（``#status``）不变。标题 ``text-wrap: balance``，窄屏换行均匀。
* 标题不再带产品名，所以卡片底部加一行小字“AI Intervention Agent”（``.brand``），浏览器标签页标题
  （``docTitle`` / ``<title>``）仍带产品名。
* Service Worker 只在安装时把离线页放进缓存（缓存名里的版本号就是“这一份”的标识），脚本一字不变的话已经
  装过的浏览器不会重新安装，会一直显示旧页；所以 ``OFFLINE_CACHE_NAME`` 从 ``aiia-offline-v1`` 升到
  ``aiia-offline-v2``：浏览器发现脚本变了就重新安装、抓新页，激活时再把 ``v1`` 删掉。

契约
====

1. 图标里没有 ``<line>``（旧的斜线和旧的“用线画的点”都没了）；它在一个 ``aria-hidden`` 的圆形淡橙底里，底色是
   品牌色的半透明，圆点和三道弧各带 ``wave`` 类，三道弧的编号（``wave-1`` 到 ``wave-3``）从内到外对应半径从小
   到大；
2. ``.wave`` 的动画是只改 ``opacity`` 的分步循环（不是 ``linear`` / ``ease``），圆点、``wave-1``、``wave-2``、
   ``wave-3`` 依次最亮、相隔 1/6 圈；减少动态效果时 ``.wave`` 的动画是 ``none``；
3. 三种语言的标题和按钮就是上面那几句，页面静态写的英文与内联英文一致（脚本没跑起来时看到的也是这两句），没有
   ``hint`` 键、没有 ``.hint`` 段落，旧文案不再出现，三种语言的键一致，繁体与简体不同，``docTitle`` 带产品名；
4. ``.brand`` 是卡片里的最后一个元素，文字是产品名，在深色和浅色两套主题里与卡片底色的对比度都不低于
   4.5:1（WCAG AA）；
5. Service Worker 的离线缓存名版本号不低于 2，压缩过的 ``.min.js`` 与源文件一致。
"""

from __future__ import annotations

import re
from itertools import pairwise
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
PACKAGE = REPO_ROOT / "src" / "ai_intervention_agent"
PAGE = PACKAGE / "templates" / "offline.html"
SERVICE_WORKER = PACKAGE / "static" / "js" / "notification-service-worker.js"
SERVICE_WORKER_MIN = PACKAGE / "static" / "js" / "notification-service-worker.min.js"

LANGS = ["en", "zh-CN", "zh-TW"]
PRODUCT = "AI Intervention Agent"
TITLE = {
    "en": "Hang on, the service isn't back yet",
    "zh-CN": "稍等，服务还没回来",
    "zh-TW": "稍等，服務還沒回來",
}
RETRY = {
    "en": "Try again",
    "zh-CN": "再试试",
    "zh-TW": "再試試",
}
MESSAGE_KEYS = {"docTitle", "title", "retry", "retrying", "online", "back"}
OLD_PHRASES = [
    "无法连接到",
    "無法連接到",
    "Can't reach AI Intervention Agent",
    "设备当前处于离线状态",
    "裝置目前處於離線狀態",
    "may be stopped, or your device is offline",
    "服务可能已停止",
    "服務可能已停止",
]
KEYFRAMES_NAME = "offline-wave"
MIN_CONTRAST = 4.5


# --------------------------------------------------------------------------- helpers


def _page() -> str:
    return PAGE.read_text(encoding="utf-8")


def _css() -> str:
    match = re.search(r"<style>(.*?)</style>", _page(), flags=re.S)
    assert match, "离线页里找不到 <style>"
    return match.group(1)


def _strip_comments(css: str) -> str:
    return re.sub(r"/\*.*?\*/", "", css, flags=re.S)


def _declarations(block: str) -> dict[str, str]:
    found: dict[str, str] = {}
    for part in block.split(";"):
        if ":" in part:
            name, value = part.split(":", 1)
            found[name.strip()] = " ".join(value.split())
    return found


def _rules(css: str) -> list[tuple[str, dict[str, str]]]:
    """(选择器, {属性: 值})，去掉注释；``@media`` 里的规则也会被取到。"""
    css = _strip_comments(css)
    return [
        (" ".join(m.group(1).split()), _declarations(m.group(2)))
        for m in re.finditer(r"([^{}]+)\{([^{}]*)\}", css)
    ]


def _balanced(css: str, start: int) -> str:
    """``start`` 是一个 ``{`` 之后的位置；返回配对的 ``}`` 之前的内容。"""
    depth = 1
    for idx in range(start, len(css)):
        depth += (css[idx] == "{") - (css[idx] == "}")
        if depth == 0:
            return css[start:idx]
    raise AssertionError("unbalanced braces")


def _without_at_rules(css: str) -> str:
    """去掉 ``@media`` 和 ``@keyframes`` 整块，只剩顶层规则。"""
    css = _strip_comments(css)
    out: list[str] = []
    pos = 0
    for m in re.finditer(r"@(?:media|keyframes)\b[^{]*\{", css):
        if m.start() < pos:
            continue
        out.append(css[pos : m.start()])
        pos = m.end() + len(_balanced(css, m.end())) + 1
    out.append(css[pos:])
    return "".join(out)


def _top_level_rules(css: str) -> dict[str, dict[str, str]]:
    merged: dict[str, dict[str, str]] = {}
    for selector, declarations in _rules(_without_at_rules(css)):
        merged.setdefault(selector, {}).update(declarations)
    return merged


def _keyframes(css: str) -> dict[str, dict[str, dict[str, str]]]:
    css = _strip_comments(css)
    found: dict[str, dict[str, dict[str, str]]] = {}
    for m in re.finditer(r"@keyframes\s+([\w-]+)\s*\{", css):
        frames: dict[str, dict[str, str]] = {}
        for frame in re.finditer(r"([^{}]+)\{([^{}]*)\}", _balanced(css, m.end())):
            key = "".join(frame.group(1).split())
            frames[key] = _declarations(frame.group(2))
        found[m.group(1)] = frames
    return found


def _reduced_motion_rules(css: str) -> list[tuple[str, dict[str, str]]]:
    css = _strip_comments(css)
    found: list[tuple[str, dict[str, str]]] = []
    pattern = r"@media\s*\(\s*prefers-reduced-motion\s*:\s*reduce\s*\)\s*\{"
    for m in re.finditer(pattern, css):
        found.extend(_rules(_balanced(css, m.end())))
    return found


def _seconds(value: str) -> float:
    match = re.fullmatch(r"(-?\d*\.?\d+)s", value.strip())
    assert match, f"not a time in seconds: {value!r}"
    return float(match.group(1))


def _main_inner() -> str:
    match = re.search(
        r'<main\b[^>]*\bclass="card"[^>]*>(.*?)</main>', _page(), flags=re.S
    )
    assert match, "离线页里找不到 <main class=card>"
    return match.group(1)


def _icon_svg() -> str:
    match = re.search(r'<svg\b[^>]*\bclass="icon"[^>]*>.*?</svg>', _page(), flags=re.S)
    assert match, "离线页里找不到 svg.icon"
    return match.group(0)


def _messages() -> dict[str, dict[str, str]]:
    """内联的 ``MESSAGES`` 对象，``{语言: {键: 文字}}``。"""
    page = _page()
    start = page.index("var MESSAGES = {") + len("var MESSAGES = {")
    body = _balanced(page, start)
    found: dict[str, dict[str, str]] = {}
    for lang in LANGS:
        match = re.search(
            rf'(?:"{re.escape(lang)}"|\b{re.escape(lang)})\s*:\s*\{{', body
        )
        assert match, f"MESSAGES 里没有 {lang}"
        block = _balanced(body, match.end())
        found[lang] = dict(re.findall(r'(\w+):\s*"((?:[^"\\]|\\.)*)"', block))
    return found


def _service_worker_cache_name(path: Path) -> str:
    match = re.search(
        r"OFFLINE_CACHE_NAME\s*=\s*'([^']+)'", path.read_text(encoding="utf-8")
    )
    assert match, f"{path.name}: 找不到 OFFLINE_CACHE_NAME"
    return match.group(1)


# --- colour maths (WCAG 2.x) ---


def _hex(value: str) -> tuple[int, int, int]:
    match = re.fullmatch(r"#([0-9a-fA-F]{6})", value.strip())
    assert match, f"not a #rrggbb colour: {value!r}"
    raw = match.group(1)
    return int(raw[0:2], 16), int(raw[2:4], 16), int(raw[4:6], 16)


def _luminance(rgb: tuple[float, float, float]) -> float:
    def channel(c: float) -> float:
        c /= 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = (channel(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _contrast(a: tuple[float, float, float], b: tuple[float, float, float]) -> float:
    la, lb = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def _theme_tokens() -> dict[str, dict[str, str]]:
    """三套主题的 token：深色（``:root``）、手动浅色、跟随系统的浅色。"""
    rules = _rules(_css())
    wanted = {
        "dark": ":root",
        "light": '[data-theme="light"]',
        "system light": ":root:not([data-theme])",
    }
    tokens: dict[str, dict[str, str]] = {}
    for name, selector in wanted.items():
        merged: dict[str, str] = {}
        for sel, declarations in rules:
            if sel == selector:
                merged.update(declarations)
        assert "--bg-secondary" in merged and "--text-secondary" in merged, name
        tokens[name] = merged
    return tokens


# --------------------------------------------------------------------------- icon


class TestIcon:
    def test_the_icon_is_not_crossed_out_any_more(self) -> None:
        svg = _icon_svg()
        assert "<line" not in svg, (
            "图标里不该再有 <line>：旧图标靠一条斜线把整个 wifi 划掉，看上去像报错"
        )
        assert len(re.findall(r"<path\b", svg)) == 3
        assert len(re.findall(r"<circle\b", svg)) == 1

    def test_the_icon_sits_in_a_decorative_round_badge(self) -> None:
        match = re.search(
            r'<div\b[^>]*\bclass="icon-badge"[^>]*>(?P<body>.*?)</div>',
            _page(),
            flags=re.S,
        )
        assert match, "找不到 .icon-badge"
        opening = re.search(r'<div\b[^>]*\bclass="icon-badge"[^>]*>', _page())
        assert opening and 'aria-hidden="true"' in opening.group(0), (
            "图标是装饰，要 aria-hidden"
        )
        assert re.search(r'<svg\b[^>]*\bclass="icon"', match.group("body"))

        rules = _top_level_rules(_css())
        badge = rules[".icon-badge"]
        assert badge["border-radius"] == "50%"
        assert badge["width"] == badge["height"]
        assert badge["background"].startswith("rgba(217, 119, 87,"), (
            "底色应是品牌橙（#d97757）的半透明"
        )
        assert badge["color"] == "var(--primary-500)"
        assert 'stroke="currentColor"' in _icon_svg()

    def test_the_four_parts_are_marked_and_the_arcs_grow_outwards(self) -> None:
        svg = _icon_svg()
        dot = re.findall(r'<circle\b[^>]*\bclass="wave"[^>]*/?>', svg, flags=re.S)
        assert len(dot) == 1, "圆点应恰好带 wave 类（没有编号）"
        arcs = re.findall(
            r'<path\b[^>]*\bclass="wave wave-(\d)"[^>]*\bd="([^"]+)"', svg, flags=re.S
        )
        assert sorted(number for number, _ in arcs) == ["1", "2", "3"]
        radii = {}
        for number, d in arcs:
            radius = re.search(r"a\s*(\d+(?:\.\d+)?)\s+\1\b", d)
            assert radius, f"看不懂的弧：{d!r}"
            radii[number] = float(radius.group(1))
        assert radii["1"] < radii["2"] < radii["3"], (
            f"wave-1 到 wave-3 应从内到外（半径由小到大），实际 {radii}"
        )


# --------------------------------------------------------------------------- animation


def _base_wave_animation() -> tuple[str, float, str]:
    """(关键帧名, 周期秒数, 时间函数)；基础规则恰有一条。"""
    rule = _top_level_rules(_css()).get(".wave")
    assert rule and "animation" in rule, "找不到 .wave 的 animation"
    match = re.fullmatch(
        r"([\w-]+) (-?\d*\.?\d+s) (\S+?(?:\([^)]*\))?) infinite", rule["animation"]
    )
    assert match, f"看不懂的 animation：{rule['animation']!r}"
    return match.group(1), _seconds(match.group(2)), match.group(3)


class TestTheWavesLightUpInTurn:
    def test_the_animation_is_stepped_and_loops(self) -> None:
        name, period, timing = _base_wave_animation()
        assert name == KEYFRAMES_NAME
        assert timing.startswith("steps("), (
            f"必须用分步动画（steps），平滑渐变每帧都要重新合成；实际是 {timing!r}"
        )
        assert period == pytest.approx(1.8)

    def test_the_keyframes_only_change_opacity(self) -> None:
        frames = _keyframes(_css()).get(KEYFRAMES_NAME)
        assert frames, f"缺 @keyframes {KEYFRAMES_NAME}"
        for key, declarations in frames.items():
            assert set(declarations) == {"opacity"}, (
                f"帧 {key} 只能改 opacity（不触发布局，也不碰 transform），"
                f"实际是 {sorted(declarations)}"
            )
        opacities = {float(d["opacity"]) for d in frames.values()}
        assert len(opacities) >= 2, "亮和暗至少要有两档"
        assert max(opacities) == 1.0

    def test_the_dot_and_then_each_arc_light_up_a_sixth_of_a_cycle_apart(self) -> None:
        _, period, _ = _base_wave_animation()
        rules = _top_level_rules(_css())
        delays = [0.0] + [
            _seconds(rules[f".wave-{n}"]["animation-delay"]) for n in (1, 2, 3)
        ]
        assert all(delay <= 0 for delay in delays), (
            "负延迟：一开始四个部分就在各自的相位上"
        )
        # 关键帧在半圈处最亮；延迟是 d（负数）时，它在 period / 2 + d 处最亮。
        peaks = [(period / 2 + delay) % period for delay in delays]
        for left, right in pairwise(peaks):
            assert (right - left) % period == pytest.approx(period / 6), (
                f"圆点、wave-1、wave-2、wave-3 应依次最亮、相隔 1/6 圈；各自最亮的时刻是 {peaks}"
            )

    def test_reduced_motion_keeps_the_icon_still(self) -> None:
        stills = [
            declarations
            for selector, declarations in _reduced_motion_rules(_css())
            if selector == ".wave"
        ]
        assert len(stills) == 1, "减少动态效果时 .wave 要有一条规则"
        assert stills[0]["animation"] == "none"


# --------------------------------------------------------------------------- copy


class TestCopy:
    @pytest.mark.parametrize("lang", LANGS)
    def test_the_page_says_the_chosen_words(self, lang: str) -> None:
        messages = _messages()[lang]
        assert messages["title"] == TITLE[lang]
        assert messages["retry"] == RETRY[lang]

    def test_the_static_english_is_the_inline_english(self) -> None:
        # 脚本没跑起来时，页面里写死的英文就是用户看到的。
        page = _page()
        title = re.search(
            r'<h1\s+id="offline-title"[^>]*>\s*(.*?)\s*</h1>', page, flags=re.S
        )
        button = re.search(
            r'<button\s+id="retry-btn"[^>]*>\s*(.*?)\s*</button>', page, flags=re.S
        )
        assert title and button
        assert title.group(1) == TITLE["en"]
        assert button.group(1) == RETRY["en"]

    def test_there_is_no_explanatory_paragraph(self) -> None:
        page = _page()
        assert 'class="hint"' not in page
        assert "offline-hint" not in page
        assert not re.search(r"\.hint\b", _css())
        assert "T.hint" not in page
        for lang, messages in _messages().items():
            assert "hint" not in messages, f"{lang}: MESSAGES 里不该再有 hint"

    @pytest.mark.parametrize("phrase", OLD_PHRASES)
    def test_the_old_cold_wording_is_gone(self, phrase: str) -> None:
        assert phrase not in _page()

    def test_every_language_has_the_same_keys(self) -> None:
        for lang, messages in _messages().items():
            assert set(messages) == MESSAGE_KEYS, f"{lang}: {sorted(messages)}"

    def test_traditional_chinese_is_not_a_copy_of_simplified(self) -> None:
        messages = _messages()
        for key in ("title", "retry"):
            assert messages["zh-TW"][key] != messages["zh-CN"][key]

    def test_the_tab_title_still_names_the_product(self) -> None:
        for lang, messages in _messages().items():
            assert PRODUCT in messages["docTitle"], lang
        head = re.search(r"<title>(.*?)</title>", _page(), flags=re.S)
        assert head and PRODUCT in head.group(1)

    def test_the_heading_wraps_in_balanced_lines(self) -> None:
        assert _top_level_rules(_css())["h1"].get("text-wrap") == "balance"


# --------------------------------------------------------------------------- brand line


class TestBrandLine:
    def test_the_product_name_closes_the_card(self) -> None:
        inner = _main_inner().rstrip()
        assert inner.endswith(f'<p class="brand">{PRODUCT}</p>'), (
            "卡片里的最后一个元素应是产品名小字（标题不再带产品名）"
        )

    @pytest.mark.parametrize("theme", ["dark", "light", "system light"])
    def test_the_brand_line_is_readable(self, theme: str) -> None:
        rules = _top_level_rules(_css())
        brand = rules[".brand"]
        tokens = _theme_tokens()[theme]

        def token(name: str) -> tuple[int, int, int]:
            return _hex(tokens[name])

        colour = brand["color"]
        match = re.fullmatch(r"var\((--[\w-]+)\)", colour)
        assert match, f".brand 的颜色应取主题变量，实际 {colour!r}"
        text = token(match.group(1))
        card = rules[".card"]["background"]
        match = re.fullmatch(r"var\((--[\w-]+)\)", card)
        assert match, f".card 的底色应取主题变量，实际 {card!r}"
        background = token(match.group(1))

        # opacity 会把文字和底色混在一起，对比度跟着降低。
        opacity = float(brand.get("opacity", "1"))
        blended = (
            opacity * text[0] + (1 - opacity) * background[0],
            opacity * text[1] + (1 - opacity) * background[1],
            opacity * text[2] + (1 - opacity) * background[2],
        )
        ratio = _contrast(blended, background)
        assert ratio >= MIN_CONTRAST, (
            f"{theme}: 产品名小字与卡片底色的对比度 {ratio:.2f}:1，低于 {MIN_CONTRAST}:1"
        )


# --------------------------------------------------------------------------- service worker


class TestServiceWorkerCache:
    @pytest.mark.parametrize(
        "path", [SERVICE_WORKER, SERVICE_WORKER_MIN], ids=lambda p: p.name
    )
    def test_the_offline_copy_is_cached_under_a_new_name(self, path: Path) -> None:
        name = _service_worker_cache_name(path)
        match = re.fullmatch(r"aiia-offline-v(\d+)", name)
        assert match, name
        assert int(match.group(1)) >= 2, (
            "v1 里存着旧的离线页（被划掉的 wifi）；脚本不变的话已装过的浏览器不会重新安装、"
            "也就不会抓新页，缓存名必须比 v1 新"
        )

    def test_the_minified_worker_names_the_same_cache(self) -> None:
        assert _service_worker_cache_name(
            SERVICE_WORKER_MIN
        ) == _service_worker_cache_name(SERVICE_WORKER)
