"""R736 — picking several images at once attaches every one of them.

Why this exists
---------------
The file input's ``change`` handler calls ``handleFileUpload(target.files)``
and then resets the input (``target.value = ""``) so the same file can be
picked again.  ``target.files`` is a *live* ``FileList``: the browser empties
it when the input is reset.  ``handleFileUpload`` works through the list in
batches of three with a pause between batches, so every batch after the first
read ``files[j]`` from the already emptied list: with more than three images
picked, the first three were attached and the rest failed with "invalid file
object" ("3/5 files successful").  The summary of a single picked file lost
its name for the same reason ("Processed " with nothing after it).  The older
tests fed plain arrays or plain objects, which never change, so none of them
could see it.

A second, smaller defect lived in the same summary: when the only picked file
was rejected, ``addImageToList`` showed the specific reason ("file too
small", "unsupported format", ...) and ``handleFileUpload`` replaced it in
the same tick with "Failed to process <nothing>: <nothing>".

The fix
-------
``handleFileUpload`` copies the list into an array before its first ``await``;
``addImageToList`` remembers why it failed and the one-file summary repeats
that reason (and stays silent when the upload was cancelled, which is not a
failure).

Pattern: C (runtime) — the real ``image-upload.js`` in a Node ``vm`` with a
``FileList`` stand-in that empties itself like the real one.
"""

from __future__ import annotations

import json
import shutil

import pytest

from tests.test_image_upload_filelist_batch_one_pass_r561 import (
    _image_upload_harness,
    _run_node,
)

pytestmark = pytest.mark.skipif(
    shutil.which("node") is None, reason="node runtime unavailable"
)

_EXPORT_MARKER = (
    "+ '\\nglobalThis.__setUpdateImagePreviewVisibility = "
    "function (fn) { updateImagePreviewVisibility = fn; };'"
)

_EXTRA_EXPORTS = """
          + '\\nglobalThis.__setCompressImage = function (fn) { compressImage = fn; };'
          + '\\nglobalThis.__clearSelected = function () { selectedImages = []; };'"""

_PRELUDE = """
        function makeLiveFileList(names, type) {
          const list = { length: names.length };
          names.forEach((name, index) => {
            list[index] = { name, type: type || 'image/png', size: 2048, lastModified: index + 1 };
          });
          // What ``input.value = ""`` does to the live FileList of the input.
          list.clear = function () {
            for (let i = 0; i < this.length; i += 1) delete this[i];
            this.length = 0;
          };
          return list;
        }

        // Runs the pending 50 ms pauses between batches until the upload ends.
        async function drive(promise) {
          for (let round = 0; round < 50; round += 1) {
            for (let i = 0; i < 20; i += 1) await Promise.resolve();
            const pending = sandbox.__timers.filter((timer) => timer.delay === 50 && !timer.fired);
            if (pending.length === 0) break;
            for (const timer of pending) {
              timer.fired = true;
              timer.fn();
            }
          }
          await promise;
        }
"""


def _harness(case_js: str) -> str:
    script = _image_upload_harness(_PRELUDE + case_js)
    assert _EXPORT_MARKER in script, (
        "tests/test_image_upload_filelist_batch_one_pass_r561.py changed its "
        "export lines; update _EXPORT_MARKER in this file"
    )
    return script.replace(_EXPORT_MARKER, _EXPORT_MARKER + _EXTRA_EXPORTS)


def _run(case_js: str) -> dict:
    return json.loads(_run_node(_harness(case_js)))


def _status_summary(call: dict) -> dict:
    """The sandbox ``t()`` returns ``{"key":..., "params":...}`` as JSON text."""
    return json.loads(call["message"])


def test_every_picked_file_is_processed_when_the_live_list_is_emptied() -> None:
    names = [f"img_{index}.png" for index in range(1, 8)]
    outcome = _run(
        f"""
        const live = makeLiveFileList({json.dumps(names)});
        const started = [];
        sandbox.__setAddImageToList(async (file) => {{
          started.push(file.name);
          return true;
        }});
        sandbox.__setUpdateImagePreviewVisibility(() => {{}});

        const promise = sandbox.__handleFileUpload(live);
        live.clear();
        await drive(promise);

        process.stdout.write(JSON.stringify({{
          started,
          lastStatus: sandbox.__statusCalls[sandbox.__statusCalls.length - 1],
          listLeft: live.length,
        }}));
        """
    )
    # Probe validity: the stand-in really was emptied.
    assert outcome["listLeft"] == 0
    assert outcome["started"] == names
    assert _status_summary(outcome["lastStatus"]) == {
        "key": "status.batchComplete",
        "params": {"successful": 7, "total": 7},
    }
    assert outcome["lastStatus"]["kind"] == "success"


def test_single_file_success_names_the_file_although_the_list_was_emptied() -> None:
    outcome = _run(
        """
        const live = makeLiveFileList(['only.png']);
        sandbox.__setAddImageToList(async () => true);
        sandbox.__setUpdateImagePreviewVisibility(() => {});

        const promise = sandbox.__handleFileUpload(live);
        live.clear();
        await drive(promise);

        process.stdout.write(JSON.stringify({ statusCalls: sandbox.__statusCalls }));
        """
    )
    assert [
        (_status_summary(call), call["kind"]) for call in outcome["statusCalls"]
    ] == [
        (
            {"key": "status.fileProcessSuccess", "params": {"filename": "only.png"}},
            "success",
        )
    ]


def test_single_file_failure_repeats_the_reason_that_was_shown() -> None:
    outcome = _run(
        """
        const live = makeLiveFileList(['notes.txt'], 'text/plain');
        const promise = sandbox.__handleFileUpload(live);
        live.clear();
        await drive(promise);

        process.stdout.write(JSON.stringify({ statusCalls: sandbox.__statusCalls }));
        """
    )
    calls = outcome["statusCalls"]
    assert [call["kind"] for call in calls] == ["error", "error"]
    shown_reason = calls[0]["message"]
    assert _status_summary({"message": shown_reason})["key"] == (
        "validation.unsupportedFormat"
    )
    # The summary adds the file name and keeps the reason instead of
    # replacing it with a bare "failed".
    assert _status_summary(calls[1]) == {
        "key": "status.fileProcessFailed",
        "params": {"filename": "notes.txt", "reason": shown_reason},
    }


def test_cancelled_single_upload_stays_silent_and_never_reuses_an_old_reason() -> None:
    outcome = _run(
        """
        // 1. A rejected file leaves a reason behind.
        const bad = makeLiveFileList(['notes.txt'], 'text/plain');
        await drive(sandbox.__handleFileUpload(bad));
        const afterRejected = sandbox.__statusCalls.length;

        // 2. The user clears the images while the next one is being processed:
        //    that is a cancellation, not a failure, and says nothing.
        sandbox.__setCompressImage(async () => {
          sandbox.__clearSelected();
          return { size: 1 };
        });
        const cancelled = makeLiveFileList(['cancel.png']);
        await drive(sandbox.__handleFileUpload(cancelled));

        process.stdout.write(JSON.stringify({
          afterRejected,
          afterCancelled: sandbox.__statusCalls.length,
        }));
        """
    )
    assert outcome["afterRejected"] == 2
    assert outcome["afterCancelled"] == 2


def test_empty_selection_is_a_quiet_noop() -> None:
    outcome = _run(
        """
        let visibilityUpdates = 0;
        sandbox.__setUpdateImagePreviewVisibility(() => { visibilityUpdates += 1; });
        await sandbox.__handleFileUpload(null);
        await sandbox.__handleFileUpload({ length: 0 });
        process.stdout.write(JSON.stringify({
          statusCalls: sandbox.__statusCalls,
          visibilityUpdates,
        }));
        """
    )
    assert outcome == {"statusCalls": [], "visibilityUpdates": 2}
