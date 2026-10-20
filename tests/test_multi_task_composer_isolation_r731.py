"""R731: the feedback form belongs to exactly one task at a time.

The text box, the attached images and the option check boxes show the state
of ``activeTaskId``.  Every change of the active task (a click on a tab, a
server-side activation seen by the poll, a finished or closed task) goes
through ``setActiveTaskId``, which parks the leaving task's state, empties the
form and loads what was parked for the entering task.  Before this, a task
without a draft inherited the previous task's text and images, the draft
could even be stored under the wrong task, and a switch decided by the poll
did not save anything at all.

These tests run the real ``multi_task.js`` in Node against a small DOM model;
only the browser surface (elements, fetch) is faked.
"""

from __future__ import annotations

import json
import unittest

from tests.test_multi_task_active_task_reconcile_r452 import (
    _multi_task_harness,
    _node_available,
    _run_node,
)

_FORM = """
        const textarea = document.createElement('textarea');
        const previews = document.createElement('div');
        const optionsContainer = document.createElement('div');
        optionsContainer.dataset.renderedTaskId = '';
        let optionStates = [];
        optionsContainer.querySelectorAll = (selector) =>
          selector === 'input[type="checkbox"]' ? optionStates : [];
        document.getElementById = (id) => {
          if (id === 'feedback-text') return textarea;
          if (id === 'image-previews') return previews;
          if (id === 'options-container') return optionsContainer;
          return null;
        };

        const rendered = [];
        const revoked = [];
        let counterRefreshes = 0;
        renderImagePreview = (item, loading) => rendered.push([item.id, loading]);
        updateImageCounter = () => {};
        updateImagePreviewVisibility = () => {};
        revokeObjectURL = (url) => revoked.push(url);
        window.AIIA_FEEDBACK_CHAR_COUNTER = { refresh() { counterRefreshes += 1; } };

        const open = (id, status = 'pending') => ({
          task_id: id,
          status,
          prompt: 'prompt ' + id,
          auto_resubmit_timeout: 0,
        });
        window.currentTasks = [open('a'), open('b')];
        currentTasks = window.currentTasks;
"""


def _run(case_js: str) -> dict[str, object]:
    script = _multi_task_harness(_FORM + case_js)
    return json.loads(_run_node(script))


@unittest.skipUnless(_node_available(), "node runtime unavailable")
def test_a_task_without_a_draft_starts_with_an_empty_form() -> None:
    result = _run(
        """
        setActiveTaskId('a');
        textarea.value = 'text for a';
        selectedImages = [{ id: 'img-a', previewUrl: 'blob:a' }];

        await api.switchTask('b');

        process.stdout.write(JSON.stringify({
          active: activeTaskId,
          text: textarea.value,
          images: selectedImages.length,
          previewsHtml: previews.innerHTML,
          parkedText: taskTextareaContents.a,
          parkedImages: taskImages.a.map((image) => image.id),
          revoked,
        }));
        """
    )

    assert result == {
        "active": "b",
        "text": "",
        "images": 0,
        "previewsHtml": "",
        "parkedText": "text for a",
        "parkedImages": ["img-a"],
        "revoked": [],
    }


@unittest.skipUnless(_node_available(), "node runtime unavailable")
def test_going_back_restores_the_parked_text_and_images() -> None:
    result = _run(
        """
        setActiveTaskId('a');
        textarea.value = 'text for a';
        const original = { id: 'img-a', previewUrl: 'blob:a' };
        selectedImages = [original];

        await api.switchTask('b');
        textarea.value = 'text for b';
        await api.switchTask('a');
        const backOnA = { text: textarea.value, images: selectedImages.map((i) => i.id) };
        const sameObject = selectedImages[0] === original;
        const previewUrl = selectedImages[0].previewUrl;
        await api.switchTask('b');

        process.stdout.write(JSON.stringify({
          backOnA,
          sameObject,
          previewUrl,
          backOnB: textarea.value,
          rendered,
          revoked,
        }));
        """
    )

    assert result == {
        "backOnA": {"text": "text for a", "images": ["img-a"]},
        "sameObject": False,
        "previewUrl": "blob:a",
        "backOnB": "text for b",
        "rendered": [["img-a", False]],
        "revoked": [],
    }


@unittest.skipUnless(_node_available(), "node runtime unavailable")
def test_a_switch_decided_by_the_poll_parks_and_clears_like_a_click() -> None:
    result = _run(
        """
        setActiveTaskId('a');
        textarea.value = 'text for a';
        selectedImages = [{ id: 'img-a', previewUrl: 'blob:a' }];

        // another client activated "b": the poll moves the active task
        updateTasksList([open('a'), open('b', 'active')]);

        const onB = { active: activeTaskId, text: textarea.value, images: selectedImages.length };
        updateTasksList([open('a', 'active'), open('b')]);

        process.stdout.write(JSON.stringify({
          onB,
          back: { active: activeTaskId, text: textarea.value, images: selectedImages.map((i) => i.id) },
        }));
        """
    )

    assert result == {
        "onB": {"active": "b", "text": "", "images": 0},
        "back": {"active": "a", "text": "text for a", "images": ["img-a"]},
    }


@unittest.skipUnless(_node_available(), "node runtime unavailable")
def test_a_task_finished_elsewhere_leaves_nothing_behind() -> None:
    result = _run(
        """
        setActiveTaskId('a');
        textarea.value = 'text for a';
        selectedImages = [{ id: 'img-a', previewUrl: 'blob:a' }];

        updateTasksList([open('a', 'completed'), open('b')]);

        process.stdout.write(JSON.stringify({
          active: activeTaskId,
          text: textarea.value,
          images: selectedImages.length,
          parkedText: Object.prototype.hasOwnProperty.call(taskTextareaContents, 'a'),
          parkedImages: Object.prototype.hasOwnProperty.call(taskImages, 'a'),
        }));
        """
    )

    assert result == {
        "active": "b",
        "text": "",
        "images": 0,
        "parkedText": False,
        "parkedImages": False,
    }


@unittest.skipUnless(_node_available(), "node runtime unavailable")
def test_a_closed_active_task_is_not_parked_again() -> None:
    result = _run(
        """
        setActiveTaskId('a');
        textarea.value = 'text for a';

        // the active task has left the list and nothing is parked for it
        window.currentTasks = [open('b')];
        currentTasks = window.currentTasks;
        delete taskTextareaContents.a;
        await api.switchTask('b');

        process.stdout.write(JSON.stringify({
          active: activeTaskId,
          text: textarea.value,
          parked: Object.prototype.hasOwnProperty.call(taskTextareaContents, 'a'),
        }));
        """
    )

    assert result == {"active": "b", "text": "", "parked": False}


@unittest.skipUnless(_node_available(), "node runtime unavailable")
def test_the_form_is_emptied_when_no_task_is_left() -> None:
    result = _run(
        """
        setActiveTaskId('a');
        textarea.value = 'text for a';
        selectedImages = [{ id: 'img-a', previewUrl: 'blob:a' }];
        window.currentTasks = [];
        currentTasks = window.currentTasks;

        setActiveTaskId(null);

        process.stdout.write(JSON.stringify({
          active: activeTaskId,
          text: textarea.value,
          images: selectedImages.length,
          parked: Object.prototype.hasOwnProperty.call(taskTextareaContents, 'a'),
        }));
        """
    )

    assert result == {"active": None, "text": "", "images": 0, "parked": False}


@unittest.skipUnless(_node_available(), "node runtime unavailable")
def test_text_typed_before_any_task_owned_the_form_is_kept() -> None:
    result = _run(
        """
        textarea.value = 'typed before the first poll answered';
        selectedImages = [{ id: 'early', previewUrl: 'blob:early' }];

        setActiveTaskId('a');

        process.stdout.write(JSON.stringify({
          text: textarea.value,
          images: selectedImages.map((i) => i.id),
        }));
        """
    )

    assert result == {
        "text": "typed before the first poll answered",
        "images": ["early"],
    }


@unittest.skipUnless(_node_available(), "node runtime unavailable")
def test_a_saved_draft_wins_over_text_present_before_the_first_task() -> None:
    result = _run(
        """
        taskTextareaContents.a = 'saved draft';
        textarea.value = 'leftover the browser restored';

        setActiveTaskId('a');

        process.stdout.write(JSON.stringify({ text: textarea.value }));
        """
    )

    assert result == {"text": "saved draft"}


@unittest.skipUnless(_node_available(), "node runtime unavailable")
def test_only_options_rendered_for_a_task_are_saved_for_it() -> None:
    result = _run(
        """
        optionStates = [{ checked: true }, { checked: false }];
        setActiveTaskId('a');

        // still showing the options of another task when "a" is left
        optionsContainer.dataset.renderedTaskId = 'zzz';
        await api.switchTask('b');
        const foreign = Object.prototype.hasOwnProperty.call(taskOptionsStates, 'a');

        optionsContainer.dataset.renderedTaskId = 'b';
        await api.switchTask('a');
        const own = taskOptionsStates.b;

        process.stdout.write(JSON.stringify({ foreign, own }));
        """
    )

    assert result == {"foreign": False, "own": [True, False]}


@unittest.skipUnless(_node_available(), "node runtime unavailable")
def test_loading_task_details_does_not_touch_what_the_user_is_typing() -> None:
    result = _run(
        """
        fetchWithTimeout = async () => ({
          json: async () => ({
            success: true,
            task: {
              task_id: 'a',
              prompt: 'prompt a',
              predefined_options: [],
              predefined_options_defaults: [],
              auto_resubmit_timeout: 0,
            },
          }),
        });
        updateDescriptionDisplay = () => {};
        updateOptionsDisplay = () => {};
        updateFeedbackPlaceholder = () => {};
        updateHeaderChip = () => {};

        setActiveTaskId('a');
        textarea.value = 'typing right now';
        taskTextareaContents.a = 'older autosave';
        selectedImages = [{ id: 'fresh', previewUrl: 'blob:fresh' }];
        taskImages.a = [{ id: 'stale', previewUrl: 'blob:stale' }];

        await loadTaskDetails('a');

        process.stdout.write(JSON.stringify({
          text: textarea.value,
          images: selectedImages.map((i) => i.id),
          rendered,
        }));
        """
    )

    assert result == {"text": "typing right now", "images": ["fresh"], "rendered": []}


@unittest.skipUnless(_node_available(), "node runtime unavailable")
def test_the_character_counter_is_refreshed_exactly_when_the_form_changes() -> None:
    result = _run(
        """
        setActiveTaskId('a');
        const afterFirst = counterRefreshes;
        setActiveTaskId('a');
        const afterSame = counterRefreshes;
        await api.switchTask('b');
        const afterSwitch = counterRefreshes;

        process.stdout.write(JSON.stringify({ afterFirst, afterSame, afterSwitch }));
        """
    )

    assert result == {"afterFirst": 1, "afterSame": 1, "afterSwitch": 2}


@unittest.skipUnless(_node_available(), "node runtime unavailable")
def test_a_form_that_cannot_be_read_never_blocks_the_task_switch() -> None:
    result = _run(
        """
        setActiveTaskId('a');
        Object.defineProperty(textarea, 'value', {
          configurable: true,
          get() { throw new Error('the text box is gone'); },
          set() {},
        });

        await api.switchTask('b');

        process.stdout.write(JSON.stringify({
          active: activeTaskId,
          windowActive: window.activeTaskId,
        }));
        """
    )

    assert result == {"active": "b", "windowActive": "b"}


@unittest.skipUnless(_node_available(), "node runtime unavailable")
def test_a_form_that_cannot_be_filled_never_blocks_the_task_switch() -> None:
    result = _run(
        """
        taskImages.b = [{ id: 'img-b', previewUrl: 'blob:b' }];
        renderImagePreview = () => { throw new Error('previews are broken'); };
        setActiveTaskId('a');

        await api.switchTask('b');

        process.stdout.write(JSON.stringify({
          active: activeTaskId,
          windowActive: window.activeTaskId,
          counterRefreshes,
        }));
        """
    )

    assert result == {"active": "b", "windowActive": "b", "counterRefreshes": 2}


@unittest.skipUnless(_node_available(), "node runtime unavailable")
def test_choosing_the_task_that_is_already_active_changes_nothing() -> None:
    result = _run(
        """
        setActiveTaskId('a');
        textarea.value = 'text for a';
        selectedImages = [{ id: 'img-a', previewUrl: 'blob:a' }];

        await api.switchTask('a');

        process.stdout.write(JSON.stringify({
          text: textarea.value,
          images: selectedImages.map((i) => i.id),
          rendered,
        }));
        """
    )

    assert result == {"text": "text for a", "images": ["img-a"], "rendered": []}
