"""R554 regression coverage for allocation-light image failure cleanup."""

from __future__ import annotations

import importlib.util
import json
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
IMAGE_UPLOAD_JS = (
    REPO_ROOT / "src" / "ai_intervention_agent" / "static" / "js" / "image-upload.js"
)
ASYNC_HARNESS = REPO_ROOT / "tests" / "test_image_upload_async_cancel_runtime_r452.py"


def _source() -> str:
    return IMAGE_UPLOAD_JS.read_text(encoding="utf-8")


def _extract_function(source: str, marker: str) -> str:
    start = source.find(marker)
    assert start != -1, f"Cannot find function marker: {marker}"
    open_brace = source.find("{", start + len(marker))
    assert open_brace != -1, f"Cannot find opening brace for: {marker}"
    depth = 1
    i = open_brace + 1
    while i < len(source):
        char = source[i]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return source[start : i + 1]
        i += 1
    raise AssertionError(f"Unbalanced function body for: {marker}")


def _load_async_harness() -> tuple[Callable[[str], str], Callable[[str], str]]:
    spec = importlib.util.spec_from_file_location(
        "image_upload_async_harness", ASYNC_HARNESS
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module_any = cast(Any, module)
    return module_any._image_upload_harness, module_any._run_node


def test_failed_image_cleanup_reuses_strict_lazy_removal() -> None:
    source = _source()
    add_body = _extract_function(source, "async function addImageToList(")
    helper = _extract_function(source, "function prepareImageRemoval(")

    assert "selectedImages.find((img) => img.id === imageId)" not in add_body
    assert "selectedImages.filter((img) => img.id !== imageId)" not in add_body
    assert "prepareImageRemoval(imageId, true)" in add_body
    assert (
        "const matches = strictId ? image.id === imageId : image.id == imageId"
        in helper
    )


@pytest.mark.skipif(shutil.which("node") is None, reason="node runtime unavailable")
def test_failed_active_image_cleanup_removes_preview_and_reports_error() -> None:
    image_upload_harness, run_node = _load_async_harness()
    script = image_upload_harness(
        """
        let rejectCompress;
        sandbox.__setCompressImage(() => new Promise((_resolve, reject) => {
          rejectCompress = reject;
        }));

        const pending = sandbox.__addImageToList(makeFile('broken-active.png'));
        sandbox.__flushRafs();

        const imageId = sandbox.__getSelectedImages()[0].id;
        const previewId = `preview-${imageId}`;
        const previewBeforeReject = !!sandbox.__elements.get(previewId);

        rejectCompress(new Error('decode failed'));
        const result = await pending;
        sandbox.__flushRafs();

        process.stdout.write(JSON.stringify({
          result,
          previewBeforeReject,
          previewAfterReject: !!sandbox.__elements.get(previewId),
          selectedCount: sandbox.__getSelectedImages().length,
          errorMessages: sandbox.__errorMessages,
          statusCalls: sandbox.__statusCalls,
        }));
        """
    )

    result = json.loads(run_node(script))

    assert result["result"] is False
    assert result["previewBeforeReject"] is True
    assert result["previewAfterReject"] is False
    assert result["selectedCount"] == 0
    assert result["statusCalls"] == [
        {
            "message": 'status.imageError:{"reason":"decode failed"}',
            "type": "error",
        }
    ]
    assert result["errorMessages"]
    assert result["errorMessages"][0].startswith("Image processing failed:")


@pytest.mark.skipif(shutil.which("node") is None, reason="node runtime unavailable")
def test_failed_image_cleanup_preserves_strict_id_matching() -> None:
    image_upload_harness, run_node = _load_async_harness()
    script = image_upload_harness(
        """
        let rejectCompress;
        sandbox.__setCompressImage(() => new Promise((_resolve, reject) => {
          rejectCompress = reject;
        }));

        const pending = sandbox.__addImageToList(makeFile('strict-id.png'));
        sandbox.__flushRafs();

        const images = sandbox.__getSelectedImages();
        const numericId = images[0].id;
        images.push({
          id: String(numericId),
          name: 'string-lookalike.png',
          size: 1,
          lastModified: 1,
        });

        rejectCompress(new Error('decode failed'));
        await pending;
        sandbox.__flushRafs();

        const remaining = sandbox.__getSelectedImages();
        process.stdout.write(JSON.stringify({
          selectedCount: remaining.length,
          remainingId: remaining[0].id,
          remainingIdType: typeof remaining[0].id,
          numericId,
        }));
        """
    )

    result = json.loads(run_node(script))

    assert result["selectedCount"] == 1
    assert result["remainingId"] == str(result["numericId"])
    assert result["remainingIdType"] == "string"
