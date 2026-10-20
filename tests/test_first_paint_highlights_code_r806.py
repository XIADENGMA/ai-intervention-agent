"""R806: the first paint of the prompt highlights code like every later render.

The Web UI has two writers for the ``#description`` element:

* ``renderMarkdownContent`` (``app.js``) - the first paint, run by
  ``loadConfig`` when the page opens or leaves the "no request" screen;
* ``updateDescriptionDisplay`` (``multi_task.js``) - the multi-task view, run
  when the reviewer switches tabs.

Since R767 the first paint no longer shows the server's raw HTML, and both
writers skip a prompt that the element already shows (R687).  That made the
first writer the permanent one - and ``renderMarkdownContent`` had never called
``Prism.highlightAllUnder``: it was always the multi-task view that did, about
100 ms later, by replacing the first paint.  After R767 nothing replaced it, so
a fenced code block in the agent's message was highlighted only after a tab
switch and stayed plain on every fresh page load and every first task after an
idle screen (real Chrome, same prompt: 22 ``token`` spans after a tab switch,
0 on a fresh load and 0 when the task arrived on an open page; ``<pre>`` also
lacked the ``language-*`` class and the ``tabindex`` Prism sets).

The contract: whichever writer gets to the element first, the element ends up
the same.  The Node tests run both real functions against recording stubs and
require the same post-processing steps in the same order, with the code
highlighted after the HTML is in place and before the code blocks are wrapped.
"""

from __future__ import annotations

from tests.test_prompt_markup_untrusted_r767 import (
    _case,
    _render_markdown_source,
    _update_description_source,
    needs_node,
)

_RECORDERS = """
        const order = [];
        // the element holds the new HTML once the harness has seen either the
        // fragment being appended (first paint) or a non-empty innerHTML (tab switch)
        const populated = () => writes.some((w) => w[0] === 'append-fragment' || (w[0] === 'html' && w[1] !== ''));
        sandbox.marked = { parse: (text) => '<p>' + text + '</p>' };
        sandbox.processCodeBlocks = (el) => order.push(['processCodeBlocks', el === target, populated()]);
        sandbox.processStrikethrough = (el) => order.push(['processStrikethrough', el === target, populated()]);
        sandbox.processLinks = (el) => order.push(['processLinks', el === target, populated()]);
        sandbox.window.loadMathJaxIfNeeded = (el) => order.push(['loadMathJaxIfNeeded', el === target, populated()]);
"""

_PRISM = """
        sandbox.Prism = { highlightAllUnder(el) { order.push(['Prism', el === target, populated()]); } };
"""

_STEPS = [
    ["Prism", True, True],
    ["processCodeBlocks", True, True],
    ["processStrikethrough", True, True],
    ["processLinks", True, True],
    ["loadMathJaxIfNeeded", True, True],
]


def _first_paint(extra: str = "", *, prism: bool = True, prompt: str = "hello") -> dict:
    return _case(
        _render_markdown_source(),
        _RECORDERS
        + (_PRISM if prism else "")
        + extra
        + f"""
        sandbox.renderMarkdownContent(target, {prompt!r}, true);
        runFrames();
        report({{ order }});
        """,
    )


def _tab_switch(extra: str = "", *, prism: bool = True, prompt: str = "hello") -> dict:
    return _case(
        _update_description_source(),
        _RECORDERS
        + (_PRISM if prism else "")
        + extra
        + f"""
        await sandbox.updateDescriptionDisplay({prompt!r});
        report({{ order }});
        """,
    )


@needs_node
def test_the_first_paint_highlights_code_once_the_html_is_in_place() -> None:
    result = _first_paint()

    assert result["order"] == _STEPS


@needs_node
def test_the_tab_switch_runs_the_same_steps_for_comparison() -> None:
    # Anchors the expectation above to what the multi-task view does today.
    result = _tab_switch()

    assert result["order"] == _STEPS


@needs_node
def test_both_writers_leave_the_element_in_the_same_state() -> None:
    first = _first_paint()
    switched = _tab_switch()

    assert first["order"] == switched["order"]
    assert first["dataset"]["renderedPrompt"] == switched["dataset"]["renderedPrompt"]


@needs_node
def test_a_page_without_prism_still_renders_and_post_processes() -> None:
    result = _first_paint(prism=False)

    assert result["order"] == _STEPS[1:]
    assert result["tempHtml"] == ["<p>hello</p>"]
    # Quiet as well: a missing highlighter is a normal state, not a failure to
    # warn about on every render.
    assert result["warnings"] == []


@needs_node
def test_a_tab_switch_without_prism_is_equally_quiet() -> None:
    result = _tab_switch(prism=False)

    assert result["order"] == _STEPS[1:]
    assert result["warnings"] == []


@needs_node
def test_a_highlighter_failure_does_not_skip_the_remaining_steps() -> None:
    result = _first_paint(
        extra="""
        sandbox.Prism = { highlightAllUnder() { throw new Error('boom'); } };
        """
    )

    assert [step[0] for step in result["order"]] == [
        "processCodeBlocks",
        "processStrikethrough",
        "processLinks",
        "loadMathJaxIfNeeded",
    ]
    assert result["warnings"] == ["Prism highlight failed: Error: boom"]
    assert result["tempHtml"] == ["<p>hello</p>"]


@needs_node
def test_a_highlighter_failure_on_a_tab_switch_is_as_gentle_as_on_first_paint() -> None:
    # Same failure, other writer.  Without a guard of its own the tab-switch
    # writer fell into the outer catch, which replaced the rendered Markdown
    # with the raw text and skipped every remaining step.
    result = _case(
        _update_description_source(),
        _RECORDERS
        + """
        const errors = [];
        sandbox.console.error = (...args) => errors.push(args.map(String).join(' '));
        sandbox.Prism = { highlightAllUnder() { throw new Error('boom'); } };
        await sandbox.updateDescriptionDisplay('hello');
        report({ order, errors });
        """,
    )

    assert [step[0] for step in result["order"]] == [
        "processCodeBlocks",
        "processStrikethrough",
        "processLinks",
        "loadMathJaxIfNeeded",
    ]
    assert result["warnings"] == ["Prism highlight failed: Error: boom"]
    assert result["errors"] == []
    assert [write for write in result["writes"] if write[0] == "text"] == []
    assert ["html", "<p>hello</p>"] in result["writes"]


@needs_node
def test_nothing_is_highlighted_when_the_element_already_shows_the_prompt() -> None:
    result = _first_paint(
        extra="""
        target.dataset.renderedPrompt = 'a newer prompt';
        target.childNodes = [{ html: 'live' }];
        """
    )

    assert result["order"] == []
    assert result["writes"] == []


@needs_node
def test_a_repeat_of_the_same_prompt_is_not_highlighted_twice() -> None:
    result = _case(
        _render_markdown_source(),
        _RECORDERS
        + _PRISM
        + """
        sandbox.renderMarkdownContent(target, 'hello', true);
        runFrames();
        sandbox.renderMarkdownContent(target, 'hello', true);
        runFrames();
        report({ order });
        """,
    )

    assert [step[0] for step in result["order"]].count("Prism") == 1
