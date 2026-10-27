"""R902: what moves on the no-task page stands still while nobody is looking at it.

TODO "无任务动画在失焦/不可见时暂停".  The no-task page of the Web UI and the no-task state of the VS Code panel run
a Lottie sprout (the hourglass), the three progress dots, a breathing status light and a few more CSS loops, all of
them for as long as the page is open.  The Web page already paused the sprout when its tab was hidden, and nothing
else: losing the focus paused nothing, the CSS loops never stopped, and the panel stopped nothing at all.  Measured
with real focus changes on a 120 Hz display, an idle no-task page cost about 16-17 % of a core in a Chrome window and
about 15 % (35 % counting every process of VS Code) in the panel, all of it spent drawing what nobody looks at.

Now, while the page is hidden *or* its window is not in front, everything on the no-task page stops where it is and
goes on from there.  The class ``aiia-ambient-paused`` on ``<html>`` freezes every CSS animation of the no-task state
(``animation-play-state: paused``, ``::before`` and ``::after`` included); the sprout is ``pause()``d, and when the
page is back it is ``resize()``d (a canvas the system reclaimed must be redrawn) and ``play()``ed from the frame where
it stopped: no new animation, no new fetch, no seek.  The care is in where "in front" comes from:

* The Web page knows it from events only: ``blur`` / ``focus`` of the window, ``visibilitychange``, ``pageshow`` (a
  page restored from the back/forward cache is in front) and, as a safety net, ``pointerdown`` / ``keydown`` in the
  capture phase (a page that is being used is in front, whatever the last event said).  It never asks
  ``document.hasFocus()``: in an embedded view (an iframe, a webview) that stays ``false`` for good and would freeze a
  page that is in use.  The default is "in front", so a page nobody told anything keeps moving.
* The panel cannot see its window: the ``blur`` / ``focus`` of a webview follow the focus *inside* its frame.  The
  extension host posts ``{type: "window-focus", focused}`` instead: on every window state change, after the queue
  held until ``ready`` is flushed (the state as it is now) and whenever the view is shown again.  The panel applies
  it, also follows its own ``visibilitychange`` and ``pointerdown`` / ``keydown``, and ignores its own ``blur`` /
  ``focus``.

Measured in real programs with real focus changes (Finder in front, then the program in front again; medians of
three runs, % of one core).  Chrome 156 with a window, 120 Hz: the old page 16.2 % in front and 17.1 % with another
app in front; now 16.9 % in front and 1.8 % behind (renderer 1.0, GPU 0.02, no style recalculation instead of 120 a
second).  VS Code 1.110.0, the no-task panel: 14.9 % in the webview process (35.6 % with all processes) in front,
0.18 % (0.9 %) with the window behind.  The sprout goes on at the frame where it stopped (37.2 -> 38.8, 160 ms after
the window is back), and none of it prints a console warning or error.

Known limits, on purpose and recorded here so that nobody mistakes them for bugs:

* A Web page that is loaded while its window is already behind, or whose window never owned the focus (the address
  bar had it), is told nothing, so it moves until the first focus, blur or use.  The panel has no such gap: the host
  tells it its state when it reports ``ready``.
* The panel follows the window, not the panel: a visible panel in a window in front moves even while the editor has
  the focus.  What is saved is the window being behind or the panel being hidden.
* The breathing status light of the panel's no-task state is frozen with the rest; the one in the header is not part
  of it.

The checks: the real ``app.js`` (and the ``app.min.js`` the page loads) in Node against the harness of R727: the sprout
and the class for blur, focus, hidden, shown, repeated and out-of-order events, a sprout created or rebuilt (theme
switch) while out of front, the listeners installed once, a class list that throws, the document never asked about its
focus, no warning or error over a round trip; the real block of ``webview-ui.js`` in Node against a small DOM, and how
it is wired (the message, the start, a sprout that finishes loading while the window is behind); the two stylesheets
(everything that moves in the no-task state can be frozen, the rule only ever freezes, no id selector beats it, the
class name is the one the scripts set); and the host (``webview.ts``: the message and its three call sites).
``packages/vscode/test/webview-window-focus.test.js`` runs the real ``WebviewProvider`` in a real VS Code.  This module
(55 tests, 46 of which fail on the old files; the other 9 are controls: a page nobody told anything keeps moving, a
page restored from the cache is in front, the document is never asked, a retired animation stays retired, a round trip
without warning, the freeze rule only freezes and no id selector beats it, in both stylesheets) catches all 86 one-point
mutants of the five sources; the mocha tests catch all 7 mutants of the host.
"""

from __future__ import annotations

import json
import re
import textwrap
from pathlib import Path
from typing import Any

import pytest

from tests.test_app_toast_runtime_r452 import _app_harness, _node_available, _run_node
from tests.test_lottie_canvas_lifecycle_r727 import PRELUDE
from tests.test_options_unpin_r901 import PANEL_RULES, WEB_RULES, _merged, _specificity

REPO_ROOT = Path(__file__).resolve().parent.parent
PACKAGE = REPO_ROOT / "src" / "ai_intervention_agent"
WEB_JS = PACKAGE / "static" / "js" / "app.js"
WEB_MIN_JS = PACKAGE / "static" / "js" / "app.min.js"
WEB_CSS = PACKAGE / "static" / "css" / "main.css"
WEB_MIN_CSS = PACKAGE / "static" / "css" / "main.min.css"
VSCODE = REPO_ROOT / "packages" / "vscode"
PANEL_JS = VSCODE / "webview-ui.js"
PANEL_CSS = VSCODE / "webview.css"
PANEL_TS = VSCODE / "webview.ts"

CLASS_NAME = "aiia-ambient-paused"
PAUSE_ONLY = {"animation-play-state": "paused"}

needs_node = pytest.mark.skipif(
    not _node_available(), reason="node runtime unavailable"
)


# ================================================================================================ the Web page
WEB_PRELUDE = (
    PRELUDE
    + r"""
const PAUSED = 'aiia-ambient-paused';
const stopped = () => sandbox.document.documentElement.classList.contains(PAUSED);
const counts = (a) => ({
  play: a.calls.play, pause: a.calls.pause, resize: a.calls.resize, destroy: a.calls.destroy,
  seeks: a.calls.goToAndStop.length, isPaused: a.isPaused,
});
const blur = () => windowEvent('blur');
const focus = () => windowEvent('focus');
async function start(theme = 'light') {
  const lottieLog = installLottie();
  const fetched = installFetch();
  setTheme(theme);
  const container = makeContainer();
  run('initHourglassAnimation()');
  await flush();
  return { lottieLog, fetched, container, a: lottieLog.animations[0] };
}
"""
)


def _running(counts: dict[str, Any]) -> dict[str, Any]:
    """What was done to start, move or end an animation. ``pause()`` repeats harmlessly, so it is not part of it."""
    return {
        name: counts[name]
        for name in ("play", "resize", "destroy", "seeks", "isPaused")
    }


def _web(case_js: str) -> dict[str, Any]:
    out: dict[str, Any] = json.loads(_run_node(_app_harness(WEB_PRELUDE + case_js)))
    return out


@needs_node
class TestWebPage:
    def test_a_page_nobody_told_anything_keeps_animating(self) -> None:
        out = _web(
            """
            const { a } = await start();
            done({ stopped: stopped(), counts: counts(a), warnings, errors });
            """
        )
        assert out["stopped"] is False
        assert out["counts"] == {
            "play": 1,
            "pause": 0,
            "resize": 1,
            "destroy": 0,
            "seeks": 0,
            "isPaused": False,
        }
        assert out["warnings"] == [] and out["errors"] == []

    def test_losing_the_window_focus_freezes_the_sprout_and_the_css_loops(
        self,
    ) -> None:
        out = _web(
            """
            const { a, lottieLog } = await start();
            const before = counts(a);
            blur();
            done({
              stopped: stopped(), before, after: counts(a),
              loads: lottieLog.animations.length,
            });
            """
        )
        assert out["stopped"] is True
        assert out["after"]["isPaused"] is True
        assert out["after"]["pause"] == out["before"]["pause"] + 1
        assert out["after"]["destroy"] == 0 and out["loads"] == 1, (
            "freezing must keep the animation, not rebuild it"
        )

    def test_getting_the_focus_back_goes_on_from_the_same_frame(self) -> None:
        out = _web(
            """
            const { a, lottieLog, fetched } = await start();
            a.currentFrame = 37;
            blur();
            const frozen = counts(a);
            focus();
            done({
              stopped: stopped(), frozen, resumed: counts(a), frame: a.currentFrame,
              loads: lottieLog.animations.length, urls: fetched.urls.length,
            });
            """
        )
        assert out["stopped"] is False
        assert out["resumed"]["isPaused"] is False
        assert out["resumed"]["play"] == out["frozen"]["play"] + 1
        assert out["resumed"]["resize"] == out["frozen"]["resize"] + 1, (
            "a canvas the system reclaimed while it was out of sight must be redrawn"
        )
        assert out["resumed"]["seeks"] == 0 and out["frame"] == 37, (
            "resuming must not seek, or the sprout would start over"
        )
        assert out["resumed"]["destroy"] == 0 and out["loads"] == 1
        assert out["urls"] == 1, "the animation data is fetched once"

    def test_repeated_events_do_nothing_more(self) -> None:
        out = _web(
            """
            const { a } = await start();
            const before = counts(a);
            blur(); blur(); blur();
            const frozen = counts(a);
            focus(); focus();
            done({ before, frozen, resumed: counts(a) });
            """
        )
        assert out["frozen"]["pause"] == out["before"]["pause"] + 1
        assert out["resumed"]["play"] == out["before"]["play"] + 1
        assert out["resumed"]["resize"] == out["before"]["resize"] + 1

    def test_a_hidden_page_that_is_shown_again_does_not_wait_for_the_focus_event(
        self,
    ) -> None:
        # Chrome: blur -> visibilitychange(hidden); and on the way back visibilitychange(visible) -> focus, with
        # document.hasFocus() still false when the page becomes visible.
        out = _web(
            """
            const { a } = await start();
            const before = counts(a);
            blur();
            setHidden(true);
            const hidden = { stopped: stopped(), counts: counts(a) };
            setHidden(false);
            const shown = { stopped: stopped(), counts: counts(a) };
            focus();
            done({ before, hidden, shown, afterFocus: counts(a), warnings, errors });
            """
        )
        assert out["hidden"]["stopped"] is True
        assert out["hidden"]["counts"]["isPaused"] is True
        assert out["hidden"]["counts"]["play"] == out["before"]["play"]
        assert out["shown"]["stopped"] is False
        assert out["shown"]["counts"]["isPaused"] is False
        assert out["shown"]["counts"]["play"] == out["before"]["play"] + 1
        assert out["afterFocus"] == out["shown"]["counts"], (
            "the focus event that follows must not play a second time"
        )
        assert out["warnings"] == [] and out["errors"] == []

    def test_a_tab_switched_to_while_the_address_bar_has_the_focus_ends_frozen(
        self,
    ) -> None:
        # What a real Chrome 156 delivered when a tab was shown again by activating it: visibilitychange(visible),
        # focus, and about 370 ms later blur (the address bar took the focus back).  Visible, but not focused: still.
        out = _web(
            """
            const { a } = await start();
            blur();
            setHidden(true);
            setHidden(false);
            focus();
            const moving = { stopped: stopped(), counts: counts(a) };
            blur();
            done({ moving, ended: { stopped: stopped(), counts: counts(a) }, warnings, errors });
            """
        )
        assert out["moving"]["stopped"] is False
        assert out["moving"]["counts"]["isPaused"] is False
        assert out["ended"]["stopped"] is True
        assert out["ended"]["counts"]["isPaused"] is True
        assert out["warnings"] == [] and out["errors"] == []

    def test_a_page_that_loads_hidden_is_frozen_from_the_start(self) -> None:
        # A tab opened in the background: the dots must not run for as long as nobody looks at it.
        out = _web(
            """
            installLottie();
            installFetch();
            setTheme('light');
            makeContainer();
            sandbox.document.hidden = true;
            run('initHourglassAnimation()');
            const whileHidden = stopped();
            setHidden(false);
            done({ whileHidden, shown: stopped() });
            """
        )
        assert out == {"whileHidden": True, "shown": False}

    def test_a_page_hidden_while_in_front_is_frozen_and_comes_back(self) -> None:
        out = _web(
            """
            const { a, lottieLog } = await start();
            const before = counts(a);
            setHidden(true);
            const hidden = { stopped: stopped(), counts: counts(a) };
            setHidden(false);
            done({ before, hidden, shown: { stopped: stopped(), counts: counts(a) }, loads: lottieLog.animations.length });
            """
        )
        assert out["hidden"]["stopped"] is True
        assert out["hidden"]["counts"]["isPaused"] is True
        assert out["shown"]["stopped"] is False
        assert out["shown"]["counts"]["isPaused"] is False
        assert out["loads"] == 1

    def test_a_focus_event_in_a_hidden_page_starts_nothing(self) -> None:
        out = _web(
            """
            const { a } = await start();
            blur();
            setHidden(true);
            const hidden = counts(a);
            focus();
            windowEvent('pointerdown');
            windowEvent('keydown');
            const stillHidden = { stopped: stopped(), counts: counts(a) };
            setHidden(false);
            done({ hidden, stillHidden, shown: { stopped: stopped(), counts: counts(a) } });
            """
        )
        assert out["stillHidden"]["stopped"] is True
        assert _running(out["stillHidden"]["counts"]) == _running(out["hidden"]), (
            "nothing is served by a loop in a page nobody can see"
        )
        assert out["shown"]["stopped"] is False
        assert out["shown"]["counts"]["isPaused"] is False

    @pytest.mark.parametrize("kind", ["pointerdown", "keydown"])
    def test_using_the_page_proves_the_window_is_in_front(self, kind: str) -> None:
        # A blur nobody answered with a focus (a window brought to the front by a script, a touch screen) must not
        # leave a page that is being used frozen.
        out = _web(
            f"""
            const {{ a }} = await start();
            const before = counts(a);
            blur();
            const frozen = {{ stopped: stopped(), counts: counts(a) }};
            windowEvent({kind!r});
            const used = {{ stopped: stopped(), counts: counts(a) }};
            windowEvent({kind!r});
            done({{ before, frozen, used, again: counts(a) }});
            """
        )
        assert out["frozen"]["stopped"] is True
        assert out["used"]["stopped"] is False
        assert out["used"]["counts"]["isPaused"] is False
        assert out["used"]["counts"]["play"] == out["before"]["play"] + 1
        assert out["again"] == out["used"]["counts"], "using the page twice plays once"

    def test_the_listeners_see_everything_before_a_page_script_can_stop_it(
        self,
    ) -> None:
        out = _web(
            """
            const registered = [];
            const original = sandbox.addEventListener;
            sandbox.addEventListener = function (type, handler, options) {
              registered.push({ type, options: options === undefined ? null : options });
              return original.call(this, type, handler, options);
            };
            installLottie();
            installFetch();
            setTheme('light');
            makeContainer();
            run('initHourglassAnimation()');
            await flush();
            done({ registered });
            """
        )
        by_type = {entry["type"]: entry["options"] for entry in out["registered"]}
        for kind in ("pointerdown", "keydown"):
            assert by_type[kind] == {"capture": True, "passive": True}, (
                f"{kind}: capturing, so a handler that stops propagation cannot hide it; "
                "passive, so the page never waits for it"
            )
        assert "blur" in by_type and "focus" in by_type

    def test_an_animation_created_while_out_of_focus_comes_up_paused(self) -> None:
        out = _web(
            """
            const lottieLog = installLottie();
            const deferred = installDeferredFetch();
            setTheme('light');
            makeContainer();
            run('initHourglassAnimation()');
            blur();
            deferred.release();
            await flush();
            const a = lottieLog.animations[0];
            const created = { stopped: stopped(), counts: counts(a) };
            a.listeners.DOMLoaded.forEach((handler) => handler());
            done({ created, afterDomLoaded: counts(a) });
            """
        )
        assert out["created"]["stopped"] is True
        assert out["created"]["counts"]["isPaused"] is True
        assert out["created"]["counts"]["play"] == 0
        assert out["afterDomLoaded"]["isPaused"] is True
        assert out["afterDomLoaded"]["play"] == 0, (
            "DOMLoaded runs the same sync: it must not start a sprout that was created out of focus"
        )

    def test_a_theme_switch_while_out_of_focus_rebuilds_a_paused_sprout(self) -> None:
        out = _web(
            """
            const { lottieLog } = await start('dark');
            blur();
            setTheme('light');
            themeChanged();
            const second = lottieLog.animations[1];
            const rebuilt = { stopped: stopped(), counts: counts(second) };
            focus();
            done({ animations: lottieLog.animations.length, rebuilt, resumed: counts(second) });
            """
        )
        assert out["animations"] == 2
        assert out["rebuilt"]["stopped"] is True
        assert out["rebuilt"]["counts"]["isPaused"] is True
        assert out["rebuilt"]["counts"]["play"] == 0, (
            "a rebuilt sprout must not start while the window is out of focus"
        )
        assert out["resumed"]["isPaused"] is False

    def test_showing_pages_and_resizing_never_start_a_frozen_sprout(self) -> None:
        out = _web(
            """
            const instances = installResizeObserver();
            const lottieLog = installLottie();
            installFetch();
            setTheme('light');
            const container = makeContainer(0, 0);
            run('initHourglassAnimation()');
            await flush();
            const a = lottieLog.animations[0];
            blur();
            const frozen = counts(a);
            setSize(container, 120, 120);
            run('showNoContentPage()');
            instances[0].callback([]);
            a.listeners.DOMLoaded.forEach((handler) => handler());
            run('showContentPage()');
            run('showNoContentPage()');
            const afterShow = counts(a);
            focus();
            done({ frozen, afterShow, resumed: counts(a) });
            """
        )
        assert _running(out["afterShow"]) == _running(out["frozen"]), (
            "a sprout that got a box (page switch, ResizeObserver, DOMLoaded) must stay frozen "
            "until the window is back"
        )
        assert out["resumed"]["isPaused"] is False
        assert out["resumed"]["play"] == out["frozen"]["play"] + 1

    def test_a_page_restored_from_the_back_forward_cache_is_in_front(self) -> None:
        out = _web(
            """
            const { lottieLog } = await start();
            blur();
            windowEvent('pagehide', { persisted: true });
            windowEvent('pageshow', { persisted: true });
            await flush();
            const second = lottieLog.animations[1];
            done({
              stopped: stopped(), animations: lottieLog.animations.length,
              playing: !!second && second.isPaused === false,
            });
            """
        )
        assert out == {"stopped": False, "animations": 2, "playing": True}

    def test_a_pageshow_that_is_not_a_restore_changes_nothing(self) -> None:
        out = _web(
            """
            const { a } = await start();
            blur();
            const frozen = counts(a);
            windowEvent('pageshow', { persisted: false });
            done({ stopped: stopped(), frozen, after: counts(a) });
            """
        )
        assert out["stopped"] is True
        assert out["after"] == out["frozen"]

    def test_the_listeners_are_installed_once(self) -> None:
        out = _web(
            """
            installLottie();
            installFetch();
            setTheme('light');
            makeContainer();
            for (let i = 0; i < 4; i++) run('initHourglassAnimation()');
            await flush();
            const w = sandbox.__windowListeners;
            const d = sandbox.__documentListeners;
            const n = (bucket, type) => (bucket[type] || []).length;
            done({
              blur: n(w, 'blur'), focus: n(w, 'focus'), pointerdown: n(w, 'pointerdown'), keydown: n(w, 'keydown'),
              pageshow: n(w, 'pageshow'), visibilitychange: n(d, 'visibilitychange'),
            });
            """
        )
        assert out == {
            "blur": 1,
            "focus": 1,
            "pointerdown": 1,
            "keydown": 1,
            "pageshow": 1,
            "visibilitychange": 1,
        }

    def test_the_document_is_never_asked_whether_it_has_focus(self) -> None:
        # document.hasFocus() is false for good in views that never take focus (an embedded browser, a webview):
        # asking would freeze the sprout there for ever.
        out = _web(
            """
            let asked = 0;
            sandbox.document.hasFocus = () => { asked += 1; return false; };
            const { a } = await start();
            setHidden(true);
            setHidden(false);
            blur();
            focus();
            done({ asked, stopped: stopped(), counts: counts(a) });
            """
        )
        assert out["asked"] == 0
        assert out["stopped"] is False
        assert out["counts"]["isPaused"] is False

    def test_a_class_list_that_throws_does_not_keep_the_sprout_running(self) -> None:
        out = _web(
            """
            const { a } = await start();
            const list = sandbox.document.documentElement.classList;
            list.add = () => { throw new Error('classList.add'); };
            list.remove = () => { throw new Error('classList.remove'); };
            blur();
            const frozen = counts(a);
            focus();
            done({ frozen, resumed: counts(a), warnings, errors });
            """
        )
        assert out["frozen"]["isPaused"] is True
        assert out["resumed"]["isPaused"] is False
        assert out["errors"] == []

    def test_without_the_animation_the_css_loops_still_stand_still(self) -> None:
        # The sprout drawn in place of the animation moves with CSS only.
        out = _web(
            """
            installLottie();
            installFetch('reject');
            setTheme('light');
            makeContainer();
            run('initHourglassAnimation()');
            await flush();
            const noAnimation = run('hourglassAnimation');
            blur();
            const frozen = stopped();
            focus();
            done({ noAnimation, frozen, resumed: !stopped(), errors });
            """
        )
        assert out["noAnimation"] is None
        assert out["frozen"] is True and out["resumed"] is True
        assert out["errors"] == []

    def test_a_retired_animation_stays_retired(self) -> None:
        out = _web(
            """
            const { lottieLog, a } = await start();
            run('retireHourglassAnimation()');
            const retired = counts(a);
            blur(); focus(); windowEvent('pointerdown'); windowEvent('keydown');
            setHidden(true); setHidden(false);
            windowEvent('pageshow', { persisted: true });
            await flush();
            done({ retired, after: counts(a), animations: lottieLog.animations.length });
            """
        )
        assert out["after"] == out["retired"]
        assert out["animations"] == 1

    def test_a_whole_round_trip_leaves_no_warning_or_error(self) -> None:
        out = _web(
            """
            const { a } = await start();
            for (let i = 0; i < 20; i++) {
              blur(); setHidden(true); setHidden(false); focus();
              blur(); windowEvent('pointerdown'); blur(); windowEvent('keydown'); focus();
            }
            done({ warnings, errors, stopped: stopped(), counts: counts(a) });
            """
        )
        assert out["warnings"] == [] and out["errors"] == []
        assert out["stopped"] is False
        assert out["counts"]["isPaused"] is False
        assert out["counts"]["destroy"] == 0


# ================================================================================================ the VS Code panel
def _panel_block() -> str:
    """Everything between the constant and the next unrelated declaration: the panel's whole pause logic."""
    source = PANEL_JS.read_text(encoding="utf-8")
    start = source.index("const AMBIENT_PAUSED_CLASS")
    return source[start : source.index("let lottieLoadPromise", start)]


PANEL_HARNESS = r"""
const documentListeners = {};
const windowListeners = {};
const registered = [];
const classes = new Set();
let classListBroken = false;
const document = {
  hidden: false,
  documentElement: {
    classList: {
      add(name) { if (classListBroken) throw new Error('classList.add'); classes.add(name); },
      remove(name) { if (classListBroken) throw new Error('classList.remove'); classes.delete(name); },
      contains(name) { return classes.has(name); },
    },
  },
  addEventListener(type, handler) { (documentListeners[type] = documentListeners[type] || []).push(handler); },
};
const window = {
  addEventListener(type, handler, options) {
    registered.push({ type, options: options === undefined ? null : options });
    (windowListeners[type] = windowListeners[type] || []).push(handler);
  },
};
const fire = (bucket, type) => (bucket[type] || []).forEach((handler) => handler({ type }));
const stopped = () => classes.has('aiia-ambient-paused');
function makeAnimation(isLoaded = true) {
  return {
    isLoaded,
    calls: { play: 0, pause: 0 },
    play() { this.calls.play += 1; },
    pause() { this.calls.pause += 1; },
  };
}
let noContentHourglassAnimation = null;
"""

PANEL_SCRIPT = r"""
__HARNESS__
__BLOCK__
const out = {};
__CASE__
process.stdout.write(JSON.stringify(out));
"""


def _panel(case_js: str) -> dict[str, Any]:
    script = (
        PANEL_SCRIPT.replace("__HARNESS__", PANEL_HARNESS)
        .replace("__BLOCK__", _panel_block())
        .replace("__CASE__", textwrap.dedent(case_js))
    )
    result: dict[str, Any] = json.loads(_run_node(script))
    return result


@needs_node
class TestPanelPage:
    def test_the_extracted_block_is_the_whole_logic(self) -> None:
        block = _panel_block()
        for name in (
            "ambientAnimationsPaused",
            "syncNoContentHourglassPlayback",
            "syncAmbientAnimations",
            "setAmbientWindowFocused",
            "initAmbientAnimations",
        ):
            assert f"function {name}(" in block, name
        assert "let ambientWindowFocused = true" in block, (
            "a panel that was never told anything keeps animating"
        )

    def test_a_panel_that_loads_hidden_is_frozen_from_the_start(self) -> None:
        out = _panel(
            """
            document.hidden = true;
            initAmbientAnimations();
            out.whileHidden = stopped();
            document.hidden = false; fire(documentListeners, 'visibilitychange');
            out.shown = stopped();
            """
        )
        assert out == {"whileHidden": True, "shown": False}

    def test_a_panel_nobody_told_anything_keeps_animating(self) -> None:
        out = _panel(
            """
            noContentHourglassAnimation = makeAnimation();
            initAmbientAnimations();
            out.stopped = stopped();
            out.calls = noContentHourglassAnimation.calls;
            """
        )
        assert out["stopped"] is False
        assert out["calls"]["pause"] == 0

    def test_the_host_saying_the_window_is_not_in_front_freezes_everything(
        self,
    ) -> None:
        out = _panel(
            """
            const a = noContentHourglassAnimation = makeAnimation();
            initAmbientAnimations();
            const before = { ...a.calls };
            setAmbientWindowFocused(false);
            out.stopped = stopped();
            out.frozen = { ...a.calls };
            setAmbientWindowFocused(true);
            out.resumedStopped = stopped();
            out.resumed = { ...a.calls };
            out.before = before;
            """
        )
        assert out["stopped"] is True
        assert out["frozen"]["pause"] == out["before"]["pause"] + 1
        assert out["resumedStopped"] is False
        assert out["resumed"]["play"] == out["frozen"]["play"] + 1

    def test_repeated_messages_do_nothing_more(self) -> None:
        out = _panel(
            """
            const a = noContentHourglassAnimation = makeAnimation();
            initAmbientAnimations();
            const before = { ...a.calls };
            setAmbientWindowFocused(false); setAmbientWindowFocused(false);
            out.frozen = { ...a.calls };
            setAmbientWindowFocused(true); setAmbientWindowFocused(true);
            out.resumed = { ...a.calls };
            out.before = before;
            """
        )
        assert out["frozen"]["pause"] == out["before"]["pause"] + 1
        assert out["resumed"]["play"] == out["frozen"]["play"] + 1

    def test_a_hidden_panel_is_frozen_whatever_the_window_says(self) -> None:
        out = _panel(
            """
            const a = noContentHourglassAnimation = makeAnimation();
            initAmbientAnimations();
            setAmbientWindowFocused(false);
            document.hidden = true; fire(documentListeners, 'visibilitychange');
            out.hidden = { stopped: stopped(), calls: { ...a.calls } };
            setAmbientWindowFocused(true);
            fire(windowListeners, 'pointerdown');
            fire(windowListeners, 'keydown');
            out.stillHidden = { stopped: stopped(), calls: { ...a.calls } };
            document.hidden = false; fire(documentListeners, 'visibilitychange');
            out.shown = { stopped: stopped(), calls: { ...a.calls } };
            """
        )
        assert out["hidden"]["stopped"] is True
        assert out["stillHidden"]["stopped"] is True
        assert out["stillHidden"]["calls"]["play"] == out["hidden"]["calls"]["play"], (
            "a message or a click must not start a loop in a panel nobody can see"
        )
        assert out["shown"]["stopped"] is False
        assert out["shown"]["calls"]["play"] == out["hidden"]["calls"]["play"] + 1

    @pytest.mark.parametrize("kind", ["pointerdown", "keydown"])
    def test_using_the_panel_proves_the_window_is_in_front(self, kind: str) -> None:
        out = _panel(
            f"""
            const a = noContentHourglassAnimation = makeAnimation();
            initAmbientAnimations();
            const before = {{ ...a.calls }};
            setAmbientWindowFocused(false);
            out.frozen = stopped();
            fire(windowListeners, {kind!r});
            out.used = stopped();
            out.played = a.calls.play - before.play;
            out.registered = registered;
            """
        )
        assert out["frozen"] is True and out["used"] is False
        assert out["played"] == 1
        options = {entry["type"]: entry["options"] for entry in out["registered"]}
        assert options[kind] == {"capture": True, "passive": True}

    def test_a_sprout_created_while_the_window_is_not_in_front_is_paused_when_loaded(
        self,
    ) -> None:
        # What the DOMLoaded handler of the real animation runs: lottie plays first (autoplay), then reports.
        out = _panel(
            """
            initAmbientAnimations();
            setAmbientWindowFocused(false);
            const a = noContentHourglassAnimation = makeAnimation();
            syncNoContentHourglassPlayback();
            out.calls = a.calls;
            """
        )
        assert out["calls"] == {"play": 0, "pause": 1}

    def test_a_sprout_that_is_not_loaded_yet_or_missing_is_left_alone(self) -> None:
        out = _panel(
            """
            initAmbientAnimations();
            const loading = noContentHourglassAnimation = makeAnimation(false);
            setAmbientWindowFocused(false);
            setAmbientWindowFocused(true);
            out.loading = loading.calls;
            noContentHourglassAnimation = null;
            setAmbientWindowFocused(false);
            out.stopped = stopped();
            """
        )
        assert out["loading"] == {"play": 0, "pause": 0}
        assert out["stopped"] is True

    def test_a_class_list_that_throws_does_not_keep_the_sprout_running(self) -> None:
        out = _panel(
            """
            const a = noContentHourglassAnimation = makeAnimation();
            initAmbientAnimations();
            const before = { ...a.calls };
            classListBroken = true;
            setAmbientWindowFocused(false);
            out.frozen = { ...a.calls };
            setAmbientWindowFocused(true);
            out.resumed = { ...a.calls };
            out.before = before;
            """
        )
        assert out["frozen"]["pause"] == out["before"]["pause"] + 1
        assert out["resumed"]["play"] == out["frozen"]["play"] + 1

    def test_the_panel_never_listens_to_its_own_blur_or_focus(self) -> None:
        # A webview's blur and focus follow the element that has the focus (the editor, the panel), not the VS Code
        # window: only the host knows the window.
        out = _panel(
            """
            initAmbientAnimations();
            out.windowTypes = registered.map((entry) => entry.type).sort();
            out.documentTypes = Object.keys(documentListeners).sort();
            """
        )
        assert out["windowTypes"] == ["keydown", "pointerdown"]
        assert out["documentTypes"] == ["visibilitychange"]


class TestPanelWiring:
    def test_the_host_message_is_handled_and_a_missing_flag_means_in_front(
        self,
    ) -> None:
        source = PANEL_JS.read_text(encoding="utf-8")
        assert re.search(
            r"case 'window-focus':\s*setAmbientWindowFocused\(message\.focused !== false\)\s*break",
            source,
        ), "a message without the flag must not freeze the panel"

    def test_the_logic_is_started_once_with_the_other_listeners(self) -> None:
        source = PANEL_JS.read_text(encoding="utf-8")
        assert source.count("initAmbientAnimations()") == 2, (
            "one definition and one call"
        )
        start = source.index("function setupEventListeners(")
        body = source[start : source.index("\n  function ", start + 10)]
        assert "initAmbientAnimations()" in body

    def test_a_sprout_that_finished_loading_is_synced_with_the_state(self) -> None:
        source = PANEL_JS.read_text(encoding="utf-8")
        handler = re.search(
            r"addEventListener\('DOMLoaded', \(\) => \{(.*?)\n        \}\)",
            source,
            re.S,
        )
        assert handler is not None
        assert "syncNoContentHourglassPlayback()" in handler.group(1), (
            "lottie starts playing before it reports DOMLoaded: this is where a frozen state has to be applied"
        )

    def test_the_class_name_is_the_one_the_stylesheet_uses(self) -> None:
        source = PANEL_JS.read_text(encoding="utf-8")
        match = re.search(r"AMBIENT_PAUSED_CLASS = '([\w-]+)'", source)
        assert match is not None and match.group(1) == CLASS_NAME


# ================================================================================================ the stylesheets
SHEETS = [
    pytest.param(WEB_RULES, "#no-content-container", WEB_JS, id="web"),
    pytest.param(PANEL_RULES, "#noContentState", PANEL_JS, id="panel"),
]


class TestStylesheets:
    @pytest.mark.parametrize(("rules", "scope", "script"), SHEETS)
    def test_everything_that_moves_in_the_no_task_state_can_be_frozen(
        self, rules: list[Any], scope: str, script: Path
    ) -> None:
        for suffix in ("", " *", " *::before", " *::after"):
            selector = f".{CLASS_NAME} {scope}{suffix}"
            assert _merged(rules, selector) == PAUSE_ONLY, selector

    @pytest.mark.parametrize(("rules", "scope", "script"), SHEETS)
    def test_the_rule_only_ever_freezes(
        self, rules: list[Any], scope: str, script: Path
    ) -> None:
        for context, selector, declarations in rules:
            state = declarations.get("animation-play-state")
            if state is None:
                continue
            assert selector.startswith(f".{CLASS_NAME} "), selector
            assert state == "paused" and context == "", (context, selector, state)

    @pytest.mark.parametrize(("rules", "scope", "script"), SHEETS)
    def test_no_animation_is_declared_with_an_id_that_would_beat_the_freeze(
        self, rules: list[Any], scope: str, script: Path
    ) -> None:
        freeze = _specificity(f".{CLASS_NAME} {scope} *")
        assert freeze[0] == 1
        for _context, selector, declarations in rules:
            if selector.startswith(f".{CLASS_NAME} "):
                continue
            if not any(name.startswith("animation") for name in declarations):
                continue
            assert _specificity(selector) < freeze, (
                f"{selector!r} animates with a specificity that beats the freeze rule"
            )

    @pytest.mark.parametrize(("rules", "scope", "script"), SHEETS)
    def test_the_class_name_is_the_one_the_script_sets(
        self, rules: list[Any], scope: str, script: Path
    ) -> None:
        source = script.read_text(encoding="utf-8")
        match = re.search(r"AMBIENT_PAUSED_CLASS = [\"']([\w-]+)[\"']", source)
        assert match is not None and match.group(1) == CLASS_NAME
        assert any(
            selector.startswith(f".{match.group(1)} {scope}")
            for _context, selector, _declarations in rules
        )

    def test_the_stylesheet_the_page_loads_has_the_freeze_too(self) -> None:
        # The page loads the minified file, the tests above read the source.
        minified = WEB_MIN_CSS.read_text(encoding="utf-8")
        assert f".{CLASS_NAME} #no-content-container" in minified
        assert "animation-play-state:paused" in minified.replace(" ", "")

    def test_the_script_the_page_loads_has_the_logic_too(self) -> None:
        minified = WEB_MIN_JS.read_text(encoding="utf-8")
        assert re.search(
            rf"AMBIENT_PAUSED_CLASS\s*=\s*[\"']{CLASS_NAME}[\"']", minified
        )
        assert re.search(
            r"AMBIENT_INTERACTION_EVENTS\s*=\s*\[\s*[\"']pointerdown[\"']\s*,\s*[\"']keydown[\"']\s*\]",
            minified,
        )
        for event, state in (("blur", "false"), ("focus", "true")):
            assert re.search(
                rf"addEventListener\(\s*[\"']{event}[\"']\s*,\s*function\s*\(\)\s*\{{\s*"
                rf"_setAmbientWindowFocused\({state}\)",
                minified,
            ), event


# ================================================================================================ the extension host
def _method(source: str, signature: str) -> str:
    start = source.index(signature)
    brace = source.index("{", source.index(")", start))
    depth = 0
    for index in range(brace, len(source)):
        if source[index] == "{":
            depth += 1
        elif source[index] == "}":
            depth -= 1
            if depth == 0:
                return source[brace : index + 1]
    raise AssertionError(f"could not extract {signature}")


class TestHost:
    source = PANEL_TS.read_text(encoding="utf-8")

    def test_the_message_carries_the_state_as_a_boolean(self) -> None:
        body = _method(self.source, "_sendWindowFocus(focused: boolean")
        assert 'type: "window-focus"' in body and "focused: focused" in body
        assert "this._sendMessage(" in body, (
            "through the queue, so a page that has not reported ready yet still hears it"
        )

    def test_without_an_argument_it_reads_the_state_of_the_window_now(self) -> None:
        assert (
            "_sendWindowFocus(focused: boolean = this._windowIsFocused())"
            in self.source
        )
        body = _method(self.source, "_windowIsFocused(): boolean")
        assert "vscode.window.state.focused !== false" in body
        assert re.search(r"catch\s*\{\s*return true;", body), (
            "an unknown state is 'in front': a frozen loop for good is worse than a running one"
        )

    def test_a_window_state_change_is_forwarded_before_the_early_return(self) -> None:
        body = _method(self.source, "async onWindowFocusChanged(")
        assert body.index("this._sendWindowFocus(focused)") < body.index(
            "if (!focused) return;"
        ), "losing the focus is the one that matters"

    def test_a_page_that_reports_ready_is_told_after_its_queue_is_flushed(self) -> None:
        start = self.source.index('case "ready"')
        block = self.source[start : self.source.index("webview.ready", start)]
        assert block.index("this._flushPendingMessages()") < block.index(
            "this._sendWindowFocus()"
        ), "the queued messages are older than the state now"

    def test_a_panel_that_is_shown_again_is_told(self) -> None:
        start = self.source.index("if (webviewView.visible) {")
        block = self.source[start : self.source.index("force-repaint", start)]
        assert "this._sendWindowFocus()" in block

    def test_the_stylesheet_and_script_names_agree_across_surfaces(self) -> None:
        assert "window-focus" in self.source
        assert "'window-focus'" in PANEL_JS.read_text(encoding="utf-8")
