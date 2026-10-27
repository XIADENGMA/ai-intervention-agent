"""R894：没有任务时的页面，等待提示是三个依次亮起的小圆点，文字是“这里暂时很安静”。

现象（真实 Chrome 156 + CDP，干净 profile，修改前后交替各 5 轮、每轮 12 s 取中位数）
================================================================================

没有任务时，网页和 VS Code 面板都画一条来回滑动的长条（``animation: loading 1.5s linear
infinite``，网页 240 px、面板 180 px），标题是“暂无交互反馈请求”。滑动用的是 ``transform``，
可是在真实 Chrome 里每一帧仍是一次样式重算（每秒 60 次），Chrome 全部进程合计占一个核的
12.79 %（渲染进程 5.08 %、GPU 进程 7.50 %、浏览器进程 0.21 %）；把长条关掉是 6.07 %，也就是长条
一个就占了一半以上。维护者还觉得这条“进度条”和标题都不够友好。

现在
====

* 长条换成三个 8 px 的小圆点（``.no-content-progress-dot``）：只动 ``opacity``，一圈 1.8 s、每半圈
  分五步（``steps(5, end)``），三个点相隔 1/3 圈，看上去是一波光依次走过去。同一个页面是 7.97 %
  （渲染进程 3.78 %、GPU 进程 3.94 %、浏览器进程 0.25 %）。样式重算仍是每秒 60 次——分步动画照样
  每帧计时——省下来的是合成器的活。原型阶段在同一台机器上量过：平滑渐变（``ease``，带不带
  ``will-change``）是 11.6–13.2 %，旧长条同一轮是 14.4 %；所以必须是分步。用 JS 定时器切换
  只比 ``steps()`` 再省不到 1.5 个点，不值得多一套定时器和清理逻辑，所以是纯 CSS。
* 标题“这里暂时很安静”，说明“AI 有新问题时，会第一时间出现在这里”（英文、繁体见 ``TITLE`` /
  ``DESCRIPTION``；繁体是手写的，不是转换），VS Code 面板的标题与网页一致。
* 长条的轨道（渐变背景、``overflow: hidden``）、浅色主题的另一套颜色、手机宽度下按位置缩短长条的两条
  规则（``#no-content-container > div:nth-child(4)``）随之去掉：点用品牌色（网页 ``--primary-500``，
  面板 ``--vscode-progressBar-background``），宽度由点自己决定。

契约
====

1. 两个前端的标记里，``no-content-progress`` 里恰好三个 ``no-content-progress-dot``，没有旧的
   ``no-content-progress-bar``，整块 ``aria-hidden``（它是装饰，状态由文字和状态灯说）；
2. ``main.css``、网页实际加载的 ``main.min.css`` 和 ``webview.css`` 里，圆点的动画是只改 ``opacity``
   的分步循环（不是 ``linear`` / ``ease``），三个点从左到右依次最亮、相隔 1/3 圈；旧的 ``loading`` 关键帧和
   ``.no-content-progress-bar`` 不再出现；外层容器是 ``display: flex``，没有固定宽高；
3. 减弱动态效果的豁免（R712）改写在圆点上，时长与基础动画一致；手机宽度下没有再按位置缩短容器的规则；
   面板里 ``.hidden`` 仍压得住容器的 ``display``（连接断开时 ``webview-ui.js`` 靠它隐藏圆点）；
4. 三种语言的文字就是上面这两句，面板标题与网页标题相同，繁体与简体不同（VS Code 的宿主测试也要求
   这一点），模板里没翻译前显示的英文就是 ``en.json`` 的那两句。
"""

from __future__ import annotations

import json
import re
from itertools import pairwise
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
PACKAGE = REPO_ROOT / "src" / "ai_intervention_agent"
STATIC = PACKAGE / "static"
MAIN_CSS = STATIC / "css" / "main.css"
MAIN_MIN_CSS = STATIC / "css" / "main.min.css"
WEB_HTML = PACKAGE / "templates" / "web_ui.html"
WEB_LOCALES = STATIC / "locales"
VSCODE = REPO_ROOT / "packages" / "vscode"
WEBVIEW_CSS = VSCODE / "webview.css"
WEBVIEW_TS = VSCODE / "webview.ts"
VSCODE_LOCALES = VSCODE / "locales"

STYLESHEETS = [MAIN_CSS, MAIN_MIN_CSS, WEBVIEW_CSS]
PAGE_STYLESHEETS = [MAIN_CSS, MAIN_MIN_CSS]
MARKUPS = [WEB_HTML, WEBVIEW_TS]
LANGS = ["en", "zh-CN", "zh-TW"]

KEYFRAMES_NAME = "no-content-dot"
DOT_COLOUR = {
    "main.css": "var(--primary-500)",
    "main.min.css": "var(--primary-500)",
    "webview.css": "var(--vscode-progressBar-background)",
}

TITLE = {
    "en": "All quiet for now",
    "zh-CN": "这里暂时很安静",
    "zh-TW": "這裡暫時很安靜",
}
DESCRIPTION = {
    "en": "When your AI has a question, it shows up here right away",
    "zh-CN": "AI 有新问题时，会第一时间出现在这里",
    "zh-TW": "AI 有新問題時，會第一時間出現在這裡",
}


# --------------------------------------------------------------------------- helpers


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


def _base_dot_animation(path: Path) -> tuple[str, float, str]:
    """(关键帧名, 周期秒数, 时间函数)；基础规则恰有一条。"""
    rules = [
        declarations
        for selector, declarations in _rules(path.read_text(encoding="utf-8"))
        if selector == ".no-content-progress-dot" and "animation" in declarations
    ]
    assert len(rules) == 1, (
        f"{path.name}: 圆点的基础动画规则应恰有一条，实际 {len(rules)}"
    )
    match = re.fullmatch(
        r"([\w-]+) (-?\d*\.?\d+s) (\S+?(?:\([^)]*\))?) infinite",
        rules[0]["animation"],
    )
    assert match, f"{path.name}: 看不懂的 animation：{rules[0]['animation']!r}"
    return match.group(1), _seconds(match.group(2)), match.group(3)


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


# --------------------------------------------------------------------------- markup


class TestMarkup:
    @pytest.mark.parametrize("path", MARKUPS, ids=lambda p: p.name)
    def test_three_dots_replace_the_bar(self, path: Path) -> None:
        text = path.read_text(encoding="utf-8")
        wrapper = re.search(
            r'<div\b[^>]*\bclass="no-content-progress"[^>]*>(?P<body>.*?)</div>',
            text,
            flags=re.S,
        )
        assert wrapper, f"{path.name}: 找不到 .no-content-progress 容器"
        dots = re.findall(
            r'<span\s+class="no-content-progress-dot"\s*></span>',
            wrapper.group("body"),
        )
        assert len(dots) == 3, f"{path.name}: 应有三个圆点，实际 {len(dots)}"
        assert (
            re.sub(r"\s", "", re.sub(r"<span[^>]*></span>", "", wrapper.group("body")))
            == ""
        )
        assert "no-content-progress-bar" not in text

    @pytest.mark.parametrize("path", MARKUPS, ids=lambda p: p.name)
    def test_the_decoration_is_hidden_from_assistive_technology(
        self, path: Path
    ) -> None:
        text = path.read_text(encoding="utf-8")
        opening = re.search(
            r'<div\b[^>]*\bclass="no-content-progress"[^>]*>', text, flags=re.S
        )
        assert opening
        assert 'aria-hidden="true"' in opening.group(0)


# --------------------------------------------------------------------------- stylesheets


class TestDotsAreASteppedOpacityCycle:
    @pytest.mark.parametrize("path", STYLESHEETS, ids=lambda p: p.name)
    def test_the_animation_is_stepped_and_loops(self, path: Path) -> None:
        name, period, timing = _base_dot_animation(path)
        assert name == KEYFRAMES_NAME
        assert timing.startswith("steps("), (
            f"{path.name}: 圆点必须用分步动画（steps），平滑渐变每帧都要重新合成，"
            f"空闲 CPU 和旧长条差不多；实际是 {timing!r}"
        )
        assert period == pytest.approx(1.8)

    @pytest.mark.parametrize("path", STYLESHEETS, ids=lambda p: p.name)
    def test_the_keyframes_only_change_opacity(self, path: Path) -> None:
        frames = _keyframes(path.read_text(encoding="utf-8")).get(KEYFRAMES_NAME)
        assert frames, f"{path.name}: 缺 @keyframes {KEYFRAMES_NAME}"
        for key, declarations in frames.items():
            assert set(declarations) == {"opacity"}, (
                f"{path.name}: 帧 {key} 只能改 opacity（不触发布局，也不碰 transform），"
                f"实际是 {sorted(declarations)}"
            )
        opacities = {float(d["opacity"]) for d in frames.values()}
        assert len(opacities) >= 2, "亮和暗至少要有两档"
        assert max(opacities) == 1.0

    @pytest.mark.parametrize("path", STYLESHEETS, ids=lambda p: p.name)
    def test_the_dots_light_up_left_to_right_a_third_of_a_cycle_apart(
        self, path: Path
    ) -> None:
        _, period, _ = _base_dot_animation(path)
        rules = dict(_rules(path.read_text(encoding="utf-8")))
        delays = [0.0] + [
            _seconds(
                rules[f".no-content-progress-dot:nth-child({n})"]["animation-delay"]
            )
            for n in (2, 3)
        ]
        assert all(delay <= 0 for delay in delays), (
            "负延迟：一开始三个点就在各自的相位上"
        )
        # 关键帧在半圈处最亮；一个点的延迟是 d（负数）时，它在 period / 2 + d 处最亮。
        peaks = [(period / 2 + delay) % period for delay in delays]
        for left, right in pairwise(peaks):
            assert (right - left) % period == pytest.approx(period / 3), (
                f"{path.name}: 三个点应从左到右依次亮起，相隔 1/3 圈；各点最亮的时刻是 {peaks}"
            )

    @pytest.mark.parametrize("path", STYLESHEETS, ids=lambda p: p.name)
    def test_the_dots_use_the_theme_colour(self, path: Path) -> None:
        rules = [
            declarations
            for selector, declarations in _rules(path.read_text(encoding="utf-8"))
            if selector == ".no-content-progress-dot" and "background" in declarations
        ]
        assert len(rules) == 1
        assert rules[0]["background"] == DOT_COLOUR[path.name]


class TestTheOldBarIsGone:
    @pytest.mark.parametrize("path", STYLESHEETS, ids=lambda p: p.name)
    def test_no_sliding_bar_is_left(self, path: Path) -> None:
        css = _strip_comments(path.read_text(encoding="utf-8"))
        assert "no-content-progress-bar" not in css
        assert not re.search(r"@keyframes\s+loading\b", css), (
            f"{path.name}: 旧的 loading 关键帧（transform 滑动）不该回来"
        )
        assert not re.search(r"animation(-name)?\s*:[^;}]*\bloading\b", css)

    @pytest.mark.parametrize("path", STYLESHEETS, ids=lambda p: p.name)
    def test_the_container_is_a_row_with_no_fixed_size(self, path: Path) -> None:
        merged: dict[str, str] = {}
        for selector, declarations in _rules(path.read_text(encoding="utf-8")):
            if selector == ".no-content-progress":
                merged.update(declarations)
        assert merged.get("display") == "flex"
        for name in ("width", "height", "overflow", "box-shadow", "background"):
            assert name not in merged, (
                f"{path.name}: .no-content-progress 不该再带 {name}（那是旧长条的轨道）"
            )

    @pytest.mark.parametrize("path", PAGE_STYLESHEETS, ids=lambda p: p.name)
    def test_no_phone_rule_resizes_the_container_by_position(self, path: Path) -> None:
        offenders = [
            selector
            for selector, _ in _rules(path.read_text(encoding="utf-8"))
            if "#no-content-container" in selector and "nth-child(4)" in selector
        ]
        assert offenders == [], (
            "手机宽度下按位置（第 4 个子元素）缩短旧长条的规则会把三个点压扁："
            f"{offenders}"
        )


class TestReducedMotionAndHiding:
    @pytest.mark.parametrize("path", PAGE_STYLESHEETS, ids=lambda p: p.name)
    def test_the_reduced_motion_exemption_runs_the_same_cycle(self, path: Path) -> None:
        _, period, _ = _base_dot_animation(path)
        exemptions = [
            declarations
            for selector, declarations in _reduced_motion_rules(
                path.read_text(encoding="utf-8")
            )
            if selector == ".no-content-progress-dot"
        ]
        assert len(exemptions) == 1, "R712：减弱动态效果的豁免应写在圆点上"
        assert exemptions[0]["animation-iteration-count"].replace(" ", "") == (
            "infinite!important"
        )
        duration = exemptions[0]["animation-duration"].replace(" ", "")
        assert duration.endswith("!important")
        assert _seconds(duration.removesuffix("!important")) == pytest.approx(period)

    def test_the_panel_hides_the_dots_with_an_important_hidden_rule(self) -> None:
        # 容器现在自己写了 display:flex；webview-ui.js 在连接断开时给它加 .hidden，
        # 没有 !important 就压不住。
        hidden = [
            declarations
            for selector, declarations in _rules(
                WEBVIEW_CSS.read_text(encoding="utf-8")
            )
            if selector == ".hidden"
        ]
        assert any(
            d.get("display", "").replace(" ", "") == "none!important" for d in hidden
        )
        script = (VSCODE / "webview-ui.js").read_text(encoding="utf-8")
        assert "getElementById('noContentProgress')" in script


# --------------------------------------------------------------------------- copy


class TestCopy:
    @pytest.mark.parametrize("lang", LANGS)
    def test_the_page_says_the_chosen_words(self, lang: str) -> None:
        page = _json(WEB_LOCALES / f"{lang}.json")["page"]["noContent"]
        assert page["title"] == TITLE[lang]
        assert page["description"] == DESCRIPTION[lang]

    @pytest.mark.parametrize("lang", LANGS)
    def test_the_panel_title_is_the_pages_title(self, lang: str) -> None:
        panel = _json(VSCODE_LOCALES / f"{lang}.json")["ui"]["noContent"]
        assert panel["title"] == TITLE[lang]

    def test_traditional_chinese_is_not_a_copy_of_simplified(self) -> None:
        # VS Code 宿主测试（language.test.js）对面板标题也有同样的要求。
        web_tw = _json(WEB_LOCALES / "zh-TW.json")["page"]["noContent"]
        web_cn = _json(WEB_LOCALES / "zh-CN.json")["page"]["noContent"]
        assert web_tw["title"] != web_cn["title"]
        assert web_tw["description"] != web_cn["description"]
        panel_tw = _json(VSCODE_LOCALES / "zh-TW.json")["ui"]["noContent"]
        panel_cn = _json(VSCODE_LOCALES / "zh-CN.json")["ui"]["noContent"]
        assert panel_tw["title"] != panel_cn["title"]

    def test_the_text_in_the_template_is_the_english_copy(self) -> None:
        html = WEB_HTML.read_text(encoding="utf-8")
        title = re.search(
            r'<h2\s+class="no-content-title"[^>]*>\s*(.*?)\s*</h2>', html, flags=re.S
        )
        description = re.search(
            r'<p\s+class="no-content-description"[^>]*>\s*(.*?)\s*</p>',
            html,
            flags=re.S,
        )
        assert title and description
        assert title.group(1) == TITLE["en"]
        assert description.group(1) == DESCRIPTION["en"]
