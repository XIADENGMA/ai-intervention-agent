"""R553 regression coverage for allocation-light image removal."""

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


def test_remove_image_uses_lazy_single_pass_removal() -> None:
    source = _source()
    helper = _extract_function(source, "function prepareImageRemoval(")
    remove = _extract_function(source, "function removeImage(")

    assert ".find((img) => img.id == imageId)" not in remove
    assert ".filter((img) => img.id != imageId)" not in remove
    assert "let nextImages = null" in helper
    assert "selectedImages.slice(0, i)" in helper
    assert "nextImages.push(image)" in helper
    assert "if (nextImages === null) return null" in helper
    assert "if (removal) selectedImages = removal.nextImages" in remove


@pytest.mark.skipif(shutil.which("node") is None, reason="node runtime unavailable")
def test_remove_missing_image_keeps_selected_images_array_reference() -> None:
    image_upload_harness, run_node = _load_async_harness()
    script = image_upload_harness(
        """
        sandbox.__setCompressImage(async (file) => file);

        const pending = sandbox.__addImageToList(makeFile('kept.png'));
        sandbox.__flushRafs();
        const result = await pending;
        sandbox.__flushRafs();

        const before = sandbox.__getSelectedImages();
        const imageId = before[0].id;
        sandbox.__removeImage('missing-id');
        const after = sandbox.__getSelectedImages();

        process.stdout.write(JSON.stringify({
          result,
          sameReference: before === after,
          selectedCount: after.length,
          keptId: after[0].id,
          originalId: imageId,
          previewStillExists: !!sandbox.__elements.get(`preview-${imageId}`),
          revokedUrls: sandbox.__revokedUrls,
        }));
        """
    )

    result = json.loads(run_node(script))

    assert result["result"] is True
    assert result["sameReference"] is True
    assert result["selectedCount"] == 1
    assert result["keptId"] == result["originalId"]
    assert result["previewStillExists"] is True
    assert result["revokedUrls"] == []


@pytest.mark.skipif(shutil.which("node") is None, reason="node runtime unavailable")
def test_remove_image_preserves_duplicate_id_removal_contract() -> None:
    image_upload_harness, run_node = _load_async_harness()
    script = image_upload_harness(
        """
        sandbox.__setCompressImage(async (file) => file);

        const firstPending = sandbox.__addImageToList(makeFile('first.png'));
        sandbox.__flushRafs();
        await firstPending;
        sandbox.__flushRafs();

        const secondPending = sandbox.__addImageToList(makeFile('second.png'));
        sandbox.__flushRafs();
        await secondPending;
        sandbox.__flushRafs();

        const images = sandbox.__getSelectedImages();
        const sharedId = images[0].id;
        const firstPreviewUrl = images[0].previewUrl;
        const secondPreviewUrl = images[1].previewUrl;
        images[1].id = sharedId;

        sandbox.__removeImage(String(sharedId));

        process.stdout.write(JSON.stringify({
          selectedCount: sandbox.__getSelectedImages().length,
          firstPreviewUrl,
          secondPreviewUrl,
          revokedUrls: sandbox.__revokedUrls,
        }));
        """
    )

    result = json.loads(run_node(script))

    assert result["selectedCount"] == 0
    assert result["revokedUrls"] == [result["firstPreviewUrl"]]
    assert result["secondPreviewUrl"] != result["firstPreviewUrl"]
