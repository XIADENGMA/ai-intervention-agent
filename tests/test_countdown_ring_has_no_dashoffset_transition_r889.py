"""R889：倒计时圈不再给 ``stroke-dashoffset`` 加过渡，一个有任务的页面不再每秒约 20 次样式重算。

现象（真实 Chrome 156 + CDP，干净 profile，修改前后交替各 3 轮取中位数）
=======================================================================

页面上有一个待回复的任务时，Web UI 空闲也占着 CPU：Chrome 全部进程合计约 6.3%（一个核；
渲染进程 2.7%，GPU 进程 3.6%），主线程每秒约 19.9 次样式重算（``Performance.getMetrics`` 的
``RecalcStyleCount``）。来源是倒计时圈的这条规则::

    .countdown-ring svg circle { transition: stroke-dashoffset 0.3s ease, stroke 0.2s; }

脚本每秒把一次 ``stroke-dashoffset`` 写进 SVG 属性（``multi_task.js``、``webview-ui.js``），
0.3 s 的缓动意味着每一秒里有 0.3 s 在逐帧动画，而 ``stroke-dashoffset`` 不走合成器，每一帧都是
主线程上的样式重算。去掉这个过渡后同一页面是 0.85%（渲染进程 0.4%，GPU 进程 0.5%），样式重算
每秒 1.0 次。圈每秒“跳一格”，而不是 0.3 s 滑过去；颜色变化的过渡（``stroke 0.2s``，快到时变色）
原样保留。

契约
====

1. 网页的 ``main.css`` 和 VS Code 的 ``webview.css`` 里，倒计时圈的 ``circle`` 规则的 ``transition``
   只剩 ``stroke``；
2. 两份样式表里没有任何规则给 ``stroke-dashoffset`` 做过渡（含 ``transition-property``），
   以后换个选择器加回来也会被抓住；
3. 网页实际加载的压缩版 ``main.min.css`` 里已经没有 ``stroke-dashoffset``。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
STATIC_CSS = REPO_ROOT / "src" / "ai_intervention_agent" / "static" / "css"
MAIN_CSS = STATIC_CSS / "main.css"
MAIN_MIN_CSS = STATIC_CSS / "main.min.css"
WEBVIEW_CSS = REPO_ROOT / "packages" / "vscode" / "webview.css"

STYLESHEETS = [MAIN_CSS, WEBVIEW_CSS]


def _rules(css: str) -> list[tuple[str, dict[str, str]]]:
    """(选择器, {属性: 值})，去掉注释；``@media`` 里的规则也会被取到。"""
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    found: list[tuple[str, dict[str, str]]] = []
    for match in re.finditer(r"([^{}]+)\{([^{}]*)\}", css):
        selector = " ".join(match.group(1).split())
        declarations: dict[str, str] = {}
        for part in match.group(2).split(";"):
            if ":" in part:
                name, value = part.split(":", 1)
                declarations[name.strip()] = " ".join(value.split())
        found.append((selector, declarations))
    return found


def _ring_rules(path: Path, selector_tail: str) -> list[dict[str, str]]:
    return [
        declarations
        for selector, declarations in _rules(path.read_text(encoding="utf-8"))
        if selector.endswith(selector_tail)
    ]


class TestRingRules:
    @pytest.mark.parametrize(
        ("path", "selector"),
        [
            (MAIN_CSS, ".countdown-ring svg circle"),
            (WEBVIEW_CSS, ".task-tab-countdown svg circle"),
        ],
    )
    def test_the_ring_only_transitions_its_colour(
        self, path: Path, selector: str
    ) -> None:
        rules = [r for r in _ring_rules(path, selector) if "transition" in r]
        assert len(rules) == 1, (
            f"{path.name}: {selector} 应该恰有一条带 transition 的规则"
        )
        assert rules[0]["transition"].replace(" ", "") == "stroke0.2s"

    @pytest.mark.parametrize("path", STYLESHEETS, ids=lambda p: p.name)
    def test_no_rule_transitions_stroke_dashoffset(self, path: Path) -> None:
        offenders = [
            (selector, declarations[name])
            for selector, declarations in _rules(path.read_text(encoding="utf-8"))
            for name in ("transition", "transition-property", "will-change")
            if name in declarations and "stroke-dashoffset" in declarations[name]
        ]
        assert offenders == [], (
            "stroke-dashoffset 每秒由脚本写一次，给它加过渡会让主线程每秒约 20 次样式重算"
            f"（R889）：{offenders}"
        )

    def test_the_minified_page_stylesheet_has_the_same_rule(self) -> None:
        minified = MAIN_MIN_CSS.read_text(encoding="utf-8")
        assert "stroke-dashoffset" not in minified
        # 变色过渡还在（压缩器可能把 ``0.2s`` 写成 ``.2s``）
        transitions = [
            r["transition"].replace(" ", "")
            for r in _ring_rules(MAIN_MIN_CSS, ".countdown-ring svg circle")
            if "transition" in r
        ]
        assert len(transitions) == 1
        assert re.fullmatch(r"stroke0?\.2s", transitions[0])
