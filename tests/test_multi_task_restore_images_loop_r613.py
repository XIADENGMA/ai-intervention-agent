"""R613 regression coverage for loadTaskDetails image-restore loops."""

from __future__ import annotations

import json
import unittest

from tests.test_multi_task_poll_controller_lifecycle_r452 import (
    MULTI_TASK_JS,
    _node_available,
    _poll_harness,
    _run_node,
)
from tests.test_multi_task_tab_active_sync_loop_r610 import _extract_function_body


def _source() -> str:
    return MULTI_TASK_JS.read_text(encoding="utf-8")


def test_load_task_details_restored_images_use_sparse_safe_indexed_loop() -> None:
    body = _extract_function_body(_source(), "loadTaskDetails")

    assert "selectedImages.forEach((imageItem)" not in body
    assert "const restoredImageCount = selectedImages.length;" in body
    assert "let imageIndex = 0;" in body
    assert "imageIndex < restoredImageCount;" in body
    assert "imageIndex += 1" in body
    assert "if (!(imageIndex in selectedImages)) continue;" in body
    assert "const imageItem = selectedImages[imageIndex];" in body
    assert "renderImagePreview(imageItem, false);" in body


@unittest.skipUnless(_node_available(), "node runtime unavailable")
def test_load_task_details_restores_images_without_array_foreach() -> None:
    script = _poll_harness(
        """
        const rendered = [];
        let counterUpdates = 0;
        let visibilityUpdates = 0;
        const previewContainer = { innerHTML: 'stale' };

        document.getElementById = function getElementById(id) {
          if (id === 'image-previews') return previewContainer;
          return null;
        };
        fetchWithTimeout = async function stubFetchWithTimeout() {
          return {
            json: async () => ({
              success: true,
              task: {
                task_id: 'task-a',
                prompt: 'Prompt',
                predefined_options: [],
                predefined_options_defaults: [],
                auto_resubmit_timeout: 30,
                remaining_time: 20,
              },
            }),
          };
        };
        updateDescriptionDisplay = function stubUpdateDescriptionDisplay() {};
        updateOptionsDisplay = function stubUpdateOptionsDisplay() {};
        updateFeedbackPlaceholder = function stubUpdateFeedbackPlaceholder() {};
        updateYesnoButtonGroup = function stubUpdateYesnoButtonGroup() {};
        updateHeaderChip = function stubUpdateHeaderChip() {};
        startTaskCountdown = function stubStartTaskCountdown() {};
        renderImagePreview = function stubRenderImagePreview(imageItem, allowRemove) {
          rendered.push([imageItem.id, allowRemove]);
        };
        updateImageCounter = function stubUpdateImageCounter() {
          counterUpdates += 1;
        };
        updateImagePreviewVisibility = function stubUpdateImagePreviewVisibility() {
          visibilityUpdates += 1;
        };

        const storedImages = [];
        storedImages[0] = { id: 'first', url: 'blob:first' };
        storedImages[2] = { id: 'third', url: 'blob:third' };
        taskImages['task-a'] = storedImages;
        setActiveTaskId('task-a');

        const originalForEach = Array.prototype.forEach;
        Array.prototype.forEach = function disabledForEach() {
          throw new Error('Array.prototype.forEach must not be used');
        };
        try {
          await loadTaskDetails('task-a');
        } finally {
          Array.prototype.forEach = originalForEach;
        }

        process.stdout.write(JSON.stringify({
          rendered,
          counterUpdates,
          visibilityUpdates,
          previewInnerHTML: previewContainer.innerHTML,
          selectedImageIds: selectedImages.map((image) => image && image.id),
          selectedImageLength: selectedImages.length,
          selectedImageOwnIndex1: Object.prototype.hasOwnProperty.call(
            selectedImages,
            '1',
          ),
          clonedFirst: selectedImages[0] !== storedImages[0],
          clonedThird: selectedImages[2] !== storedImages[2],
        }));
        """
    )

    result = json.loads(_run_node(script))

    assert result == {
        "rendered": [["first", False], ["third", False]],
        "counterUpdates": 1,
        "visibilityUpdates": 1,
        "previewInnerHTML": "",
        "selectedImageIds": ["first", None, "third"],
        "selectedImageLength": 3,
        "selectedImageOwnIndex1": False,
        "clonedFirst": True,
        "clonedThird": True,
    }
