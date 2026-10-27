r"""R884: the English fallback of a desktop notification survives the page's script order.

``notification-manager.js`` has a translation helper with a third argument, the sentence to
show when the i18n module has no entry for the key, because a desktop notification outside
the browser must never read ``page.noContent.newTasks``.  R822 locked that, and its tests
passed.

On the real page it did not hold.  ``templates/web_ui.html`` loads ``notification-manager.js``
and, a few lines later, ``app.js``, both as classic scripts into one global scope, and both
declared a top-level ``function t``.  The later one wins: ``app.js`` has ``t(key, params)``,
which returns whatever the i18n module returns, so ``window.t.length`` on the page was 2 and
the ``fallback`` was thrown away.  A key that has no translation (a locale that lags behind,
a pseudo-locale, an i18n file that is stale in the browser cache) reached the notification as
its raw key.  Checked in a real Chromium against the running page.

Why two locks missed it:

* R822 evaluated ``notification-manager.js`` *alone*, so ``t`` was always its own;
* R756 forbids a top-level name in two page scripts but let this one pair through, as "the
  same two-line helper", and only checked *where* the two lived, not whether they agreed.

The fix is structural: the notification file's helper is ``tOrFallback`` and no page script
may share a name with another (R756, whose allow-list is gone).  This test is the behavioural
side, for the thing the user sees: the real ``t`` is cut out of ``app.js`` and run in the same
global scope after the notification script, as the page does, and the sentence the notification
carries is read from the result.
"""

from __future__ import annotations

import functools
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

from tests.test_new_task_notification_language_r822 import (
    AWAY,
    COUNT_TWO,
    ONE_NAMED,
    TRANSLATING,
    _harness,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
STATIC_JS = REPO_ROOT / "src" / "ai_intervention_agent" / "static" / "js"
APP_JS = STATIC_JS / "app.js"
NOTIFICATION_MANAGER_JS = STATIC_JS / "notification-manager.js"

pytestmark = pytest.mark.skipif(
    shutil.which("node") is None, reason="node runtime unavailable"
)

# An i18n module that has no entry for the key answers with the key itself.
NO_ENTRY = "{ t(key) { return key; } }"
EMPTY_ANSWER = "{ t() { return ''; } }"


def _function_source(source: str, marker: str) -> str:
    start = source.find(marker)
    assert start != -1, (
        f"{marker!r} is not in app.js any more; point this test at the new home"
    )
    open_brace = source.find("{", start)
    depth = 1
    index = open_brace + 1
    while depth:
        char = source[index]
        depth += (char == "{") - (char == "}")
        index += 1
    return source[start:index]


def _page_scripts_after_notification_manager() -> str:
    """What the page runs after ``notification-manager.js``: the ``t`` of ``app.js``."""
    app_t = _function_source(
        APP_JS.read_text(encoding="utf-8"), "function t(key, params)"
    )
    return f"vm.runInContext({json.dumps(app_t)}, sandbox);"


@functools.cache
def _run(case_js: str, i18n: str | None) -> dict[str, Any]:
    script = _harness(
        case_js,
        document=AWAY,
        secure=True,
        i18n=i18n,
        later_scripts=_page_scripts_after_notification_manager(),
    )
    proc = subprocess.run(
        ["node", "-e", script],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.returncode == 0, (
        f"node exited {proc.returncode}\nstdout={proc.stdout!r}\nstderr={proc.stderr!r}"
    )
    return json.loads(proc.stdout)


def _bodies(case_js: str, i18n: str | None) -> list[str]:
    return [shown["body"] for shown in _run(case_js, i18n)["shown"]]


class TestTheFallbackSurvivesTheRealScriptOrder:
    def test_a_missing_translation_shows_the_english_sentence_for_several(self) -> None:
        assert _bodies(COUNT_TWO, NO_ENTRY) == ["Received 2 new task(s)"]

    def test_a_missing_translation_shows_the_english_sentence_for_one(self) -> None:
        assert _bodies(ONE_NAMED, NO_ENTRY) == ["New task added: task-a"]

    def test_an_empty_answer_is_a_missing_translation_too(self) -> None:
        assert _bodies(COUNT_TWO, EMPTY_ANSWER) == ["Received 2 new task(s)"]
        assert _bodies(ONE_NAMED, EMPTY_ANSWER) == ["New task added: task-a"]

    def test_a_translation_still_wins(self) -> None:
        assert _bodies(COUNT_TWO, TRANSLATING) == [
            '<<page.noContent.newTasks|{"count":2}>>'
        ]
        assert _bodies(ONE_NAMED, TRANSLATING) == ['<<notify.newTask|{"id":"task-a"}>>']

    def test_the_raw_key_is_never_the_body(self) -> None:
        for case in (COUNT_TWO, ONE_NAMED):
            for body in _bodies(case, NO_ENTRY):
                assert "page.noContent" not in body
                assert "notify.newTask" not in body


class TestTheTestSeesTheRealPage:
    """Guards against the test passing because it no longer looks at what the page has."""

    def test_the_page_t_of_app_js_is_in_the_scope_next_to_the_notification_helper(
        self,
    ) -> None:
        out = _run(
            "report({ t: typeof sandbox.t, tLength: sandbox.t && sandbox.t.length, "
            "helper: typeof sandbox.tOrFallback, helperLength: sandbox.tOrFallback.length });",
            NO_ENTRY,
        )
        # the page's helper takes two arguments and cannot carry a fallback ...
        assert (out["t"], out["tLength"]) == ("function", 2)
        # ... which is why the notification file keeps one of its own, under its own name
        assert (out["helper"], out["helperLength"]) == ("function", 3)

    def test_the_page_t_does_not_replace_the_notification_helper(self) -> None:
        out = _run(
            "report({ same: sandbox.t === sandbox.tOrFallback });",
            NO_ENTRY,
        )
        assert out["same"] is False

    def test_the_notification_script_declares_no_global_t(self) -> None:
        # A second ``t`` in this file is what put two of them into one global scope.
        source = NOTIFICATION_MANAGER_JS.read_text(encoding="utf-8")
        assert "\nfunction t(" not in source
        assert "\nfunction tOrFallback(key, params, fallback)" in source
