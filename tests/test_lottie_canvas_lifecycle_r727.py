"""R727 回归护栏：移动端空态 Lottie 嫩芽不再闪烁 / 不稳定。

症状：手机上等待页（「暂无交互反馈请求」）的嫩芽会闪、切回页面时从头重播，
关闭服务后的卡片上还会冒出第二只嫩芽。iOS 上的闪烁本身无法在桌面引擎里复现，
所以下面每一条都是「已知机制」加「在真实 WebKit 27.2 / Chromium 156
（iPhone 15 模拟，3x DPR）里量到的事实」，不是对闪烁的复现：

1. **SVG 渲染器**。嫩芽（1200x1200、12 fps、72 帧、135 个形状图层、184 个静态纯色
   填充）被展开成 514 个 DOM 节点，播放时每秒约 265 次 DOM 属性变更（8 秒内
   Chromium 2114 次、WebKit 2089 次）；canvas 渲染器只有 1 个节点，播放期间
   0 次 DOM 变更。lottie 社区有 iOS 上 SVG 渲染器白闪的报告，通行解法是 canvas
   渲染器（airbnb/lottie-web#2051、ngx-lottie/ngx-lottie#183）。桌面引擎里两种
   渲染器的帧率都是 60 fps、0 次跳帧，8 倍 CPU 降速下各有 1 个长任务，所以这里
   不声称性能提升。
2. **深色主题的 ``filter: invert(1)``**。滤镜套在持续重绘的容器上，依赖 WebKit
   的滤镜合成路径，而它对动画内容有公开的未修复缺陷（例如 WebKit 219729）。
   深色配色现在直接烘焙进动画数据（``fl`` / ``st`` 的 RGB 取反，alpha 不动），
   页面上没有任何 CSS filter。与旧实现（SVG + 滤镜）逐像素对比（WebKit，3x DPR，
   8 个关键帧 x 明暗两套）：对齐 1 个设备像素后平均差 <= 0.13/255，不对齐
   <= 1.5/255（只有边缘像素）。
3. **每次 visibilitychange 都销毁并重建**（旧代码：来回切 3 次，loadAnimation
   共 4 次、destroy 共 3 次）。切 App / 锁屏 / 下拉通知栏都会触发，每次回来动画
   都从第 0 帧重播并短暂空白。现在隐藏只 ``pause()``，回来 ``resize()`` +
   ``play()``（resize 同时强制重画，系统回收 canvas 位图后也不会留空白）；动画
   数据只取一次。
4. **canvas 的像素尺寸在创建时就定死**。容器是 ``display: none`` 时创建得到
   0x0 画布，之后再显示也不会自己长出来（lottie 不会自动 resize）。所以显示 /
   隐藏空态页（``showNoContentPage`` / ``showContentPage``）与 ResizeObserver
   都会同步一次：有盒子 -> resize + play，没盒子 -> pause（内容页显示时动画
   也不再空转）。
5. **已关闭卡片被复活**（老 bug）。关闭服务后卡片只画一个绿色对勾，但切走再切回
   标签页，``visibilitychange`` 会再建一个动画（旧代码实测 loadAnimation 1 -> 2）。
   现在 ``renderClosedTerminalState`` 走 ``retireHourglassAnimation``，之后任何
   init 都直接返回。
6. 创建前清空容器：降级 SVG 之后再成功创建时不再叠在一起。

降级用的 CSS 嫩芽原来写死 ``#111`` 并依赖那个滤镜反色，滤镜没了之后改成
``currentColor``，``.no-content-icon`` 提供主题文字色。

本文件不依赖真实浏览器：用 Node ``vm`` 沙箱跑真实的 ``app.js``，lottie /
fetch / ResizeObserver 都是可观测的桩。无法在这里覆盖的部分（真机 iOS 上闪烁
是否消失）只能靠真机确认。
"""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path
from typing import Any

import pytest

from tests.test_app_toast_runtime_r452 import _app_harness, _node_available, _run_node

REPO_ROOT = Path(__file__).resolve().parent.parent
STATIC = REPO_ROOT / "src" / "ai_intervention_agent" / "static"
APP_JS = STATIC / "js" / "app.js"
MAIN_CSS = STATIC / "css" / "main.css"
SPROUT_JSON = STATIC / "lottie" / "sprout.json"

pytestmark = pytest.mark.skipif(
    not _node_available(), reason="node runtime unavailable"
)


PRELUDE = r"""
const flush = () => new Promise((resolve) => setImmediate(resolve));

const ANIMATION = {
  v: '5.12.1', fr: 12, ip: 0, op: 72, w: 100, h: 100,
  layers: [{
    ty: 4,
    ks: { p: { a: 0, k: [50, 60, 0] } },
    shapes: [{ ty: 'gr', it: [
      { ty: 'sh', ks: { a: 0, k: { v: [[0, 0], [1, 1]] } } },
      { ty: 'fl', c: { a: 0, k: [0.25, 0.5, 0.75, 1] }, o: { a: 0, k: 100 } },
      { ty: 'st', c: { a: 1, k: [{ t: 0, s: [1, 0, 0, 1], e: [0, 1, 0, 0.5] }] }, o: { a: 0, k: 100 } },
      { ty: 'tr' },
    ] }],
  }],
};
const LIGHT_FILL = [0.25, 0.5, 0.75, 1];
const DARK_FILL = [0.75, 0.5, 0.25, 1];
const fillOf = (data) => data.layers[0].shapes[0].it[1].c.k;
const strokeOf = (data) => data.layers[0].shapes[0].it[2].c.k[0];

const warnings = [];
const errors = [];
sandbox.console.warn = (...args) => warnings.push(args.map(String).join(' '));
sandbox.console.error = (...args) => errors.push(args.map(String).join(' '));
sandbox.document.querySelector = () => null;
sandbox.document.querySelectorAll = () => [];

function makeContainer(width = 120, height = 120) {
  const el = sandbox.document.createElement('div');
  el.id = 'hourglass-lottie';
  el.offsetWidth = width;
  el.offsetHeight = height;
  Object.defineProperty(el, 'textContent', {
    get() { return this._text || ''; },
    set(value) {
      this._text = String(value);
      this.children.forEach((child) => { child.parentNode = null; });
      this.children = [];
    },
  });
  sandbox.document.body.appendChild(el);
  return el;
}

function installLottie() {
  const log = { animations: [] };
  sandbox.lottie = {
    loadAnimation(options) {
      const listeners = {};
      const calls = { play: 0, pause: 0, resize: 0, destroy: 0, goToAndStop: [] };
      const animation = {
        options, calls, listeners,
        isLoaded: true,
        isPaused: options.autoplay === false,
        currentFrame: 0,
        containerWasEmpty: options.container.children.length === 0 && options.container.textContent === '',
        addEventListener(type, handler) { (listeners[type] = listeners[type] || []).push(handler); },
        play() { calls.play += 1; this.isPaused = false; },
        pause() { calls.pause += 1; this.isPaused = true; },
        resize() { calls.resize += 1; },
        destroy() { calls.destroy += 1; this.destroyed = true; },
        goToAndStop(frame, isFrame) { calls.goToAndStop.push([frame, isFrame]); this.currentFrame = frame; this.isPaused = true; },
      };
      log.animations.push(animation);
      return animation;
    },
  };
  return log;
}

function installFetch(behaviour = 'ok', text = JSON.stringify(ANIMATION)) {
  const urls = [];
  const state = { behaviour, text };
  sandbox.fetch = (url) => {
    urls.push(String(url));
    if (state.behaviour === 'reject') return Promise.reject(new Error('offline'));
    if (state.behaviour === 'http500') return Promise.resolve({ ok: false, status: 500, text: async () => 'oops' });
    if (state.behaviour === 'badjson') return Promise.resolve({ ok: true, status: 200, text: async () => '{not json' });
    return Promise.resolve({ ok: true, status: 200, text: async () => state.text });
  };
  return { urls, state };
}

function installDeferredFetch() {
  const urls = [];
  let release = null;
  sandbox.fetch = (url) => {
    urls.push(String(url));
    return new Promise((resolve) => {
      release = () => resolve({ ok: true, status: 200, text: async () => JSON.stringify(ANIMATION) });
    });
  };
  return { urls, release: () => release() };
}

function installResizeObserver() {
  const instances = [];
  sandbox.ResizeObserver = function ResizeObserver(callback) {
    this.callback = callback;
    this.observed = [];
    this.disconnected = false;
    this.observe = (el) => { this.observed.push(el); };
    this.disconnect = () => { this.disconnected = true; };
    instances.push(this);
  };
  return instances;
}

const fire = (bucket, type, event = {}) => (bucket[type] || []).forEach((handler) => handler(event));
const documentEvent = (type, event) => fire(sandbox.__documentListeners, type, event);
const windowEvent = (type, event) => fire(sandbox.__windowListeners, type, event);
const run = (source) => vm.runInContext(source, sandbox);
const setTheme = (theme) => sandbox.document.documentElement.setAttribute('data-theme', theme);
const setHidden = (hidden) => { sandbox.document.hidden = hidden; documentEvent('visibilitychange'); };
const setSize = (container, width, height) => { container.offsetWidth = width; container.offsetHeight = height; };
function themeChanged() {
  windowEvent('theme-changed', { detail: {} });
  const pending = sandbox.__timers.filter((timer) => !timer.cleared && timer.delay === 50);
  if (pending.length) sandbox.__runTimer(pending[pending.length - 1].id, false);
}
const done = (value) => process.stdout.write(JSON.stringify(value));
"""


def _run(case_js: str) -> dict:
    return json.loads(_run_node(_app_harness(PRELUDE + case_js)))


def _function_body(source: str, name: str) -> str:
    match = re.search(rf"function\s+{name}\s*\([^)]*\)\s*\{{", source)
    assert match is not None, f"missing function {name}"
    depth = 0
    for idx in range(match.end() - 1, len(source)):
        char = source[idx]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return source[match.end() : idx]
    raise AssertionError(f"could not parse body for {name}")


class TestAnimationIsACanvasWithBakedColours(unittest.TestCase):
    def test_light_theme_builds_a_canvas_animation_from_the_original_data(self) -> None:
        out = _run(
            """
            const lottieLog = installLottie();
            const { urls } = installFetch();
            setTheme('light');
            const container = makeContainer();
            run('initHourglassAnimation()');
            await flush();
            const a = lottieLog.animations[0];
            done({
              loads: lottieLog.animations.length,
              renderer: a.options.renderer,
              loop: a.options.loop,
              autoplay: a.options.autoplay,
              hasPath: 'path' in a.options,
              preserve: a.options.rendererSettings.preserveAspectRatio,
              original: JSON.stringify(a.options.animationData) === JSON.stringify(ANIMATION),
              ownContainer: a.options.container === container,
              urls,
              filterTouched: container.style.filter !== undefined,
              errors,
            });
            """
        )
        assert out == {
            "loads": 1,
            "renderer": "canvas",
            "loop": True,
            "autoplay": True,
            "hasPath": False,
            "preserve": "xMidYMid meet",
            "original": True,
            "ownContainer": True,
            "urls": ["/static/lottie/sprout.json"],
            "filterTouched": False,
            "errors": [],
        }

    def test_dark_theme_gets_every_fill_and_stroke_colour_inverted(self) -> None:
        out = _run(
            """
            const lottieLog = installLottie();
            installFetch();
            setTheme('dark');
            const container = makeContainer();
            run('initHourglassAnimation()');
            await flush();
            const data = lottieLog.animations[0].options.animationData;
            done({
              fill: fillOf(data),
              strokeStart: strokeOf(data).s,
              strokeEnd: strokeOf(data).e,
              position: data.layers[0].ks.p.k,
              vertices: data.layers[0].shapes[0].it[0].ks.k.v,
              filterTouched: container.style.filter !== undefined,
            });
            """
        )
        assert out == {
            "fill": [0.75, 0.5, 0.25, 1],
            "strokeStart": [0, 1, 1, 1],
            "strokeEnd": [1, 0, 1, 0.5],
            "position": [50, 60, 0],
            "vertices": [[0, 0], [1, 1]],
            "filterTouched": False,
        }

    def test_a_page_without_a_theme_attribute_is_dark(self) -> None:
        out = _run(
            """
            const lottieLog = installLottie();
            installFetch();
            makeContainer();
            run('initHourglassAnimation()');
            await flush();
            done({ fill: fillOf(lottieLog.animations[0].options.animationData) });
            """
        )
        assert out == {"fill": [0.75, 0.5, 0.25, 1]}

    def test_the_inversion_never_leaks_into_the_cached_text(self) -> None:
        out = _run(
            """
            const lottieLog = installLottie();
            const { urls } = installFetch();
            setTheme('dark');
            makeContainer();
            run('initHourglassAnimation()');
            await flush();
            setTheme('light');
            themeChanged();
            done({
              loads: lottieLog.animations.length,
              darkFill: fillOf(lottieLog.animations[0].options.animationData),
              lightFill: fillOf(lottieLog.animations[1].options.animationData),
              urls,
            });
            """
        )
        assert out == {
            "loads": 2,
            "darkFill": [0.75, 0.5, 0.25, 1],
            "lightFill": [0.25, 0.5, 0.75, 1],
            "urls": ["/static/lottie/sprout.json"],
        }

    def test_the_real_asset_is_inverted_channel_by_channel(self) -> None:
        text = SPROUT_JSON.read_text(encoding="utf-8")
        original = json.loads(text)

        def colours(node: Any) -> list[Any]:
            found: list[Any] = []
            if isinstance(node, list):
                for child in node:
                    found.extend(colours(child))
            elif isinstance(node, dict):
                if node.get("ty") in ("fl", "st") and "c" in node:
                    found.append(node["c"]["k"])
                for value in node.values():
                    found.extend(colours(value))
            return found

        expected = [[1 - c[0], 1 - c[1], 1 - c[2], c[3]] for c in colours(original)]
        assert expected, "sprout.json must contain colours to invert"
        out = _run(
            f"""
            sandbox.__text = {json.dumps(text)};
            const dark = run('_hourglassAnimationData(__text, "dark")');
            const light = run('_hourglassAnimationData(__text, "light")');
            function colours(node) {{
              if (Array.isArray(node)) return node.flatMap(colours);
              if (!node || typeof node !== 'object') return [];
              const own = (node.ty === 'fl' || node.ty === 'st') && node.c ? [node.c.k] : [];
              return own.concat(Object.values(node).flatMap(colours));
            }}
            done({{ dark: colours(dark), light: colours(light) }});
            """
        )
        assert out["dark"] == expected
        assert out["light"] == colours(original)


class TestHiddenPagePausesInsteadOfRebuilding(unittest.TestCase):
    def test_hide_pauses_and_show_resumes_the_same_animation(self) -> None:
        out = _run(
            """
            const lottieLog = installLottie();
            const { urls } = installFetch();
            setTheme('light');
            const container = makeContainer();
            run('initHourglassAnimation()');
            await flush();
            const a = lottieLog.animations[0];
            const afterCreate = { play: a.calls.play, pause: a.calls.pause, resize: a.calls.resize, paused: a.isPaused };
            setHidden(true);
            const hidden = { pause: a.calls.pause, destroy: a.calls.destroy, paused: a.isPaused };
            setHidden(false);
            done({
              afterCreate, hidden,
              back: { play: a.calls.play, resize: a.calls.resize, destroy: a.calls.destroy, paused: a.isPaused },
              loads: lottieLog.animations.length,
              urls: urls.length,
            });
            """
        )
        assert out["hidden"] == {
            "pause": out["afterCreate"]["pause"] + 1,
            "destroy": 0,
            "paused": True,
        }
        assert out["back"]["paused"] is False
        assert out["back"]["destroy"] == 0
        assert out["back"]["resize"] == out["afterCreate"]["resize"] + 1
        assert out["back"]["play"] == out["afterCreate"]["play"] + 1
        assert out["loads"] == 1
        assert out["urls"] == 1

    def test_many_rapid_cycles_never_rebuild_or_refetch(self) -> None:
        out = _run(
            """
            const lottieLog = installLottie();
            const { urls } = installFetch();
            setTheme('dark');
            makeContainer();
            run('initHourglassAnimation()');
            await flush();
            for (let i = 0; i < 25; i++) { setHidden(true); setHidden(false); }
            await flush();
            const a = lottieLog.animations[0];
            done({ loads: lottieLog.animations.length, urls: urls.length, destroyed: a.calls.destroy, paused: a.isPaused });
            """
        )
        assert out == {"loads": 1, "urls": 1, "destroyed": 0, "paused": False}

    def test_a_creation_still_in_flight_is_dropped_when_the_page_hides(self) -> None:
        out = _run(
            """
            const lottieLog = installLottie();
            const deferred = installDeferredFetch();
            setTheme('light');
            makeContainer();
            run('initHourglassAnimation()');
            sandbox.document.hidden = true;
            deferred.release();
            await flush();
            const whileHidden = lottieLog.animations.length;
            setHidden(false);
            await flush();
            done({ whileHidden, afterReturn: lottieLog.animations.length, urls: deferred.urls.length });
            """
        )
        assert out == {"whileHidden": 0, "afterReturn": 1, "urls": 1}

    def test_overlapping_inits_create_exactly_one_animation(self) -> None:
        out = _run(
            """
            const lottieLog = installLottie();
            const { urls } = installFetch();
            setTheme('light');
            makeContainer();
            run('initHourglassAnimation()');
            run('initHourglassAnimation()');
            setHidden(false);
            await flush();
            done({ loads: lottieLog.animations.length, urls: urls.length });
            """
        )
        assert out == {"loads": 1, "urls": 1}

    def test_a_page_that_starts_hidden_creates_nothing_until_it_is_shown(self) -> None:
        out = _run(
            """
            const lottieLog = installLottie();
            installFetch();
            setTheme('light');
            makeContainer();
            sandbox.document.hidden = true;
            run('initHourglassAnimation()');
            await flush();
            const whileHidden = lottieLog.animations.length;
            setHidden(false);
            await flush();
            done({ whileHidden, afterShow: lottieLog.animations.length });
            """
        )
        assert out == {"whileHidden": 0, "afterShow": 1}


class TestCanvasFollowsTheContainerBox(unittest.TestCase):
    def test_created_inside_a_hidden_page_it_waits_and_sizes_itself_on_show(
        self,
    ) -> None:
        out = _run(
            """
            const lottieLog = installLottie();
            installFetch();
            setTheme('light');
            const container = makeContainer(0, 0);
            run('initHourglassAnimation()');
            await flush();
            const a = lottieLog.animations[0];
            const created = { paused: a.isPaused, play: a.calls.play, resize: a.calls.resize };
            setSize(container, 120, 120);
            run('showNoContentPage()');
            const shown = { paused: a.isPaused, play: a.calls.play, resize: a.calls.resize };
            setSize(container, 0, 0);
            run('showContentPage()');
            done({ created, shown, hiddenAgain: { paused: a.isPaused, resize: a.calls.resize } });
            """
        )
        assert out["created"] == {"paused": True, "play": 0, "resize": 0}
        assert out["shown"] == {"paused": False, "play": 1, "resize": 1}
        assert out["hiddenAgain"] == {"paused": True, "resize": 1}

    def test_dom_loaded_syncs_playback_with_the_current_box(self) -> None:
        out = _run(
            """
            const lottieLog = installLottie();
            installFetch();
            setTheme('light');
            const container = makeContainer(0, 0);
            run('initHourglassAnimation()');
            await flush();
            const a = lottieLog.animations[0];
            setSize(container, 120, 120);
            a.listeners.DOMLoaded.forEach((handler) => handler());
            done({ paused: a.isPaused, resize: a.calls.resize, play: a.calls.play });
            """
        )
        assert out == {"paused": False, "resize": 1, "play": 1}

    def test_a_zero_sized_box_is_never_resized_into(self) -> None:
        out = _run(
            """
            const lottieLog = installLottie();
            installFetch();
            setTheme('light');
            const container = makeContainer(120, 0);
            run('initHourglassAnimation()');
            await flush();
            run('showNoContentPage()');
            const a = lottieLog.animations[0];
            done({ paused: a.isPaused, resize: a.calls.resize, play: a.calls.play });
            """
        )
        assert out == {"paused": True, "resize": 0, "play": 0}

    def test_resize_observer_drives_resize_play_and_pause(self) -> None:
        out = _run(
            """
            const instances = installResizeObserver();
            const lottieLog = installLottie();
            installFetch();
            setTheme('light');
            const container = makeContainer(0, 0);
            run('initHourglassAnimation()');
            await flush();
            const a = lottieLog.animations[0];
            const observer = instances[0];
            setSize(container, 120, 120);
            observer.callback([]);
            const shown = { paused: a.isPaused, resize: a.calls.resize, play: a.calls.play };
            setSize(container, 0, 0);
            observer.callback([]);
            const hidden = { paused: a.isPaused };
            run('disposeHourglassAnimationLifecycle()');
            done({
              observers: instances.length,
              watchesContainer: observer.observed.length === 1 && observer.observed[0] === container,
              shown, hidden,
              disconnectedOnDispose: observer.disconnected,
            });
            """
        )
        assert out == {
            "observers": 1,
            "watchesContainer": True,
            "shown": {"paused": False, "resize": 1, "play": 1},
            "hidden": {"paused": True},
            "disconnectedOnDispose": True,
        }

    def test_a_rebuild_replaces_the_observer_instead_of_stacking_them(self) -> None:
        out = _run(
            """
            const instances = installResizeObserver();
            const lottieLog = installLottie();
            installFetch();
            setTheme('dark');
            makeContainer();
            run('initHourglassAnimation()');
            await flush();
            setTheme('light');
            themeChanged();
            done({
              animations: lottieLog.animations.length,
              observers: instances.length,
              staleDisconnected: instances[0].disconnected,
              liveDisconnected: instances[1].disconnected,
            });
            """
        )
        assert out == {
            "animations": 2,
            "observers": 2,
            "staleDisconnected": True,
            "liveDisconnected": False,
        }

    def test_a_browser_without_resize_observer_still_works(self) -> None:
        out = _run(
            """
            const lottieLog = installLottie();
            installFetch();
            setTheme('light');
            makeContainer();
            const hadObserver = typeof sandbox.ResizeObserver !== 'undefined';
            run('initHourglassAnimation()');
            await flush();
            done({ hadObserver, loads: lottieLog.animations.length, errors });
            """
        )
        assert out == {"hadObserver": False, "loads": 1, "errors": []}


class TestThemeSwitchRebuildsOnlyWhenThePaletteChanges(unittest.TestCase):
    def test_switch_rebuilds_once_keeps_the_frame_and_plays_on(self) -> None:
        out = _run(
            """
            const lottieLog = installLottie();
            installFetch();
            setTheme('dark');
            makeContainer();
            run('initHourglassAnimation()');
            await flush();
            const first = lottieLog.animations[0];
            first.currentFrame = 42.6;
            setTheme('light');
            windowEvent('theme-changed', { detail: {} });
            windowEvent('theme-changed', { detail: {} });
            const timers = sandbox.__timers.filter((timer) => timer.delay === 50);
            const cleared = timers.filter((timer) => timer.cleared).length;
            sandbox.__runTimer(timers[timers.length - 1].id, false);
            const second = lottieLog.animations[1];
            themeChanged();
            done({
              animations: lottieLog.animations.length,
              timersScheduled: timers.length,
              timersCleared: cleared,
              firstDestroyed: first.calls.destroy,
              secondFill: fillOf(second.options.animationData),
              seek: second.calls.goToAndStop,
              secondPaused: second.isPaused,
              containerWasEmpty: second.containerWasEmpty,
            });
            """
        )
        assert out == {
            "animations": 2,
            "timersScheduled": 2,
            "timersCleared": 1,
            "firstDestroyed": 1,
            "secondFill": [0.25, 0.5, 0.75, 1],
            "seek": [[42.6, True]],
            "secondPaused": False,
            "containerWasEmpty": True,
        }

    def test_a_theme_event_for_the_same_palette_does_nothing(self) -> None:
        out = _run(
            """
            const lottieLog = installLottie();
            installFetch();
            setTheme('light');
            makeContainer();
            run('initHourglassAnimation()');
            await flush();
            themeChanged();
            themeChanged();
            done({ animations: lottieLog.animations.length, destroyed: lottieLog.animations[0].calls.destroy });
            """
        )
        assert out == {"animations": 1, "destroyed": 0}

    def test_a_switch_while_hidden_is_applied_when_the_page_returns(self) -> None:
        out = _run(
            """
            const lottieLog = installLottie();
            installFetch();
            setTheme('dark');
            makeContainer();
            run('initHourglassAnimation()');
            await flush();
            setHidden(true);
            setTheme('light');
            themeChanged();
            const whileHidden = lottieLog.animations.length;
            setHidden(false);
            await flush();
            const second = lottieLog.animations[1];
            done({
              whileHidden,
              afterReturn: lottieLog.animations.length,
              fill: second && fillOf(second.options.animationData),
              playing: second && !second.isPaused,
            });
            """
        )
        assert out == {
            "whileHidden": 1,
            "afterReturn": 2,
            "fill": [0.25, 0.5, 0.75, 1],
            "playing": True,
        }

    def test_a_switch_before_the_first_creation_uses_the_final_theme(self) -> None:
        out = _run(
            """
            const lottieLog = installLottie();
            const deferred = installDeferredFetch();
            setTheme('dark');
            makeContainer();
            run('initHourglassAnimation()');
            setTheme('light');
            themeChanged();
            deferred.release();
            await flush();
            done({
              animations: lottieLog.animations.length,
              fill: fillOf(lottieLog.animations[0].options.animationData),
            });
            """
        )
        assert out == {"animations": 1, "fill": [0.25, 0.5, 0.75, 1]}


class TestRetiredAnimationStaysRetired(unittest.TestCase):
    def test_retire_destroys_and_blocks_every_way_back(self) -> None:
        out = _run(
            """
            const lottieLog = installLottie();
            const { urls } = installFetch();
            setTheme('light');
            makeContainer();
            run('initHourglassAnimation()');
            await flush();
            run('retireHourglassAnimation()');
            const destroyed = lottieLog.animations[0].calls.destroy;
            run('initHourglassAnimation()');
            setHidden(true);
            setHidden(false);
            windowEvent('pageshow', { persisted: true });
            await flush();
            done({
              destroyed,
              animations: lottieLog.animations.length,
              urls: urls.length,
              current: run('hourglassAnimation'),
            });
            """
        )
        assert out == {"destroyed": 1, "animations": 1, "urls": 1, "current": None}

    def test_the_closed_card_keeps_its_check_icon(self) -> None:
        out = _run(
            """
            const lottieLog = installLottie();
            installFetch();
            setTheme('light');
            const container = makeContainer();
            run('initHourglassAnimation()');
            await flush();
            run('renderClosedTerminalState()');
            setHidden(true);
            setHidden(false);
            windowEvent('pageshow', { persisted: true });
            await flush();
            done({
              animations: lottieLog.animations.length,
              destroyed: lottieLog.animations[0].calls.destroy,
              children: container.children.map((child) => child.tagName),
              filterTouched: container.style.filter !== undefined,
            });
            """
        )
        assert out == {
            "animations": 1,
            "destroyed": 1,
            "children": ["SVG"],
            "filterTouched": False,
        }


class TestPageLifecycle(unittest.TestCase):
    def test_pagehide_disposes_and_a_persisted_pageshow_rebuilds_from_the_cache(
        self,
    ) -> None:
        out = _run(
            """
            const lottieLog = installLottie();
            const { urls } = installFetch();
            setTheme('light');
            makeContainer();
            run('initHourglassAnimation()');
            await flush();
            windowEvent('pagehide', { persisted: true });
            const afterHide = { destroyed: lottieLog.animations[0].calls.destroy, current: run('hourglassAnimation') };
            windowEvent('pageshow', { persisted: false });
            await flush();
            const ignored = lottieLog.animations.length;
            windowEvent('pageshow', { persisted: true });
            await flush();
            done({ afterHide, ignored, animations: lottieLog.animations.length, urls: urls.length });
            """
        )
        assert out == {
            "afterHide": {"destroyed": 1, "current": None},
            "ignored": 1,
            "animations": 2,
            "urls": 1,
        }


class TestFallbackPaths(unittest.TestCase):
    def test_failed_data_falls_back_then_recovers_without_stacking(self) -> None:
        out = _run(
            """
            const lottieLog = installLottie();
            const fetcher = installFetch('reject');
            setTheme('light');
            const container = makeContainer();
            run('initHourglassAnimation()');
            await flush();
            const failed = {
              animations: lottieLog.animations.length,
              children: container.children.map((child) => child.tagName),
              warnings: warnings.length,
            };
            fetcher.state.behaviour = 'ok';
            setHidden(true);
            setHidden(false);
            await flush();
            done({
              failed,
              animations: lottieLog.animations.length,
              wasEmpty: lottieLog.animations[0] && lottieLog.animations[0].containerWasEmpty,
              fetches: fetcher.urls.length,
              errors,
            });
            """
        )
        assert out == {
            "failed": {"animations": 0, "children": ["SVG"], "warnings": 1},
            "animations": 1,
            "wasEmpty": True,
            "fetches": 2,
            "errors": [],
        }

    def test_http_errors_and_invalid_json_fall_back_without_creating_a_canvas(
        self,
    ) -> None:
        for behaviour in ("http500", "badjson"):
            with self.subTest(behaviour=behaviour):
                out = _run(
                    f"""
                    const lottieLog = installLottie();
                    installFetch({behaviour!r});
                    setTheme('light');
                    const container = makeContainer();
                    run('initHourglassAnimation()');
                    await flush();
                    done({{
                      animations: lottieLog.animations.length,
                      children: container.children.map((child) => child.tagName),
                      warnings: warnings.length,
                    }});
                    """
                )
                assert out == {"animations": 0, "children": ["SVG"], "warnings": 1}

    def test_a_missing_lottie_runtime_falls_back(self) -> None:
        out = _run(
            """
            installFetch();
            setTheme('light');
            const container = makeContainer();
            run('initHourglassAnimation()');
            const script = sandbox.document.head.children[0];
            script.onerror();
            await flush();
            done({
              scripts: sandbox.document.head.children.length,
              children: container.children.map((child) => child.tagName),
            });
            """
        )
        assert out == {"scripts": 1, "children": ["SVG"]}

    def test_a_lottie_error_event_swaps_in_the_fallback(self) -> None:
        out = _run(
            """
            const lottieLog = installLottie();
            installFetch();
            setTheme('light');
            const container = makeContainer();
            run('initHourglassAnimation()');
            await flush();
            const a = lottieLog.animations[0];
            a.listeners.error.forEach((handler) => handler());
            done({
              destroyed: a.calls.destroy,
              children: container.children.map((child) => child.tagName),
              current: run('hourglassAnimation'),
            });
            """
        )
        assert out == {"destroyed": 1, "children": ["SVG"], "current": None}

    def test_an_exception_while_building_falls_back_and_is_reported(self) -> None:
        out = _run(
            """
            installFetch();
            setTheme('light');
            const container = makeContainer();
            sandbox.lottie = { loadAnimation() { throw new Error('boom'); } };
            run('initHourglassAnimation()');
            await flush();
            done({ children: container.children.map((child) => child.tagName), errors: errors.length });
            """
        )
        assert out == {"children": ["SVG"], "errors": 1}


class TestSourceContracts(unittest.TestCase):
    def setUp(self) -> None:
        self.app = APP_JS.read_text(encoding="utf-8")

    def test_the_icon_is_never_filtered(self) -> None:
        self.assertNotIn("invert(", self.app)
        self.assertNotIn("style.filter", self.app)

    def test_the_animation_is_a_canvas_built_from_data_not_from_a_path(self) -> None:
        body = _function_body(self.app, "_createLottieAnimation")
        self.assertIn('renderer: "canvas"', body)
        self.assertIn("animationData", body)
        self.assertNotIn('renderer: "svg"', body)
        self.assertNotIn("path:", body)

    def test_the_container_is_cleared_before_a_new_animation_is_built(self) -> None:
        body = _function_body(self.app, "_createLottieAnimation")
        self.assertLess(
            body.index('container.textContent = ""'),
            body.index("lottie.loadAnimation"),
        )

    def test_visibility_handler_pauses_instead_of_disposing(self) -> None:
        body = _function_body(self.app, "installHourglassAnimationLifecycleHandlers")
        hidden_branch = body[body.index("if (document.hidden)") :]
        hidden_branch = hidden_branch[: hidden_branch.index("} else {")]
        self.assertIn("_syncHourglassPlayback()", hidden_branch)
        self.assertNotIn("disposeHourglassAnimationLifecycle", hidden_branch)

    def test_page_switches_resync_the_canvas(self) -> None:
        self.assertIn(
            "_syncHourglassPlayback()", _function_body(self.app, "showNoContentPage")
        )
        self.assertIn(
            "_syncHourglassPlayback()", _function_body(self.app, "showContentPage")
        )

    def test_retire_marks_the_lifecycle_and_disposes(self) -> None:
        body = _function_body(self.app, "retireHourglassAnimation")
        self.assertIn("_hourglassLifecycleRetired = true", body)
        self.assertIn("disposeHourglassAnimationLifecycle()", body)
        self.assertIn(
            "_hourglassLifecycleRetired",
            _function_body(self.app, "initHourglassAnimation"),
        )

    def test_the_closed_card_retires_the_animation(self) -> None:
        self.assertIn(
            "retireHourglassAnimation()",
            _function_body(self.app, "renderClosedTerminalState"),
        )

    def test_the_fallback_sprout_follows_the_theme_text_colour(self) -> None:
        body = _function_body(self.app, "renderSproutFallback")
        self.assertIn('stroke="currentColor"', body)
        self.assertNotIn("#111", body)
        css = MAIN_CSS.read_text(encoding="utf-8")
        rule = re.search(r"\.no-content-icon\s*\{([^}]*)\}", css)
        assert rule is not None
        self.assertRegex(rule.group(1), r"(?m)^\s*color:\s*var\(--text-primary")


class TestAssetIsCoveredByTheInversion(unittest.TestCase):
    """Only static solid fills are inverted; a different asset must not slip by."""

    def test_sprout_json_uses_only_static_solid_fills(self) -> None:
        data = json.loads(SPROUT_JSON.read_text(encoding="utf-8"))
        seen: dict[str, int] = {}

        def walk(node: Any) -> None:
            if isinstance(node, list):
                for child in node:
                    walk(child)
            elif isinstance(node, dict):
                kind = node.get("ty")
                if isinstance(kind, str):
                    seen[kind] = seen.get(kind, 0) + 1
                # An expression is a string under "x"; "x" is a list in easing curves.
                assert not isinstance(node.get("x"), str), "expression found"
                if kind == "fl":
                    colour = node["c"]
                    assert colour["a"] == 0, "animated fill colour"
                    assert len(colour["k"]) == 4
                    assert all(isinstance(v, (int, float)) for v in colour["k"])
                    assert min(colour["k"]) >= 0 and max(colour["k"]) <= 1
                for value in node.values():
                    walk(value)

        walk(data)
        assert seen.get("fl", 0) > 0
        for unsupported in ("gf", "gs"):
            assert unsupported not in seen, (
                f"sprout.json now uses '{unsupported}' items; "
                "_invertLottieColors does not recolour gradients for the dark theme"
            )


if __name__ == "__main__":
    unittest.main()
