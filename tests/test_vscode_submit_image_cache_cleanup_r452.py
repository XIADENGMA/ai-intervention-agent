"""R452: VS Code webview image cache/upload edge cases."""

from __future__ import annotations

import json
import shutil
import subprocess
import textwrap
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
WEBVIEW_UI_JS = REPO_ROOT / "packages" / "vscode" / "webview-ui.js"


def _node_available() -> bool:
    return shutil.which("node") is not None


def _read_source() -> str:
    return WEBVIEW_UI_JS.read_text(encoding="utf-8")


def _extract_function(source: str, name: str) -> str:
    marker = f"function {name}("
    start = source.index(marker)
    if source[max(0, start - 6) : start] == "async ":
        start -= 6
    brace = source.index("{", start)
    depth = 0
    for index in range(brace, len(source)):
        char = source[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return source[start : index + 1]
    raise AssertionError(f"Could not extract {name}()")


def _run_node(script: str) -> str:
    if not _node_available():
        raise AssertionError("node runtime unavailable")
    completed = subprocess.run(
        ["node", "-e", script],
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout


def test_submit_image_formdata_helper_drops_invalid_cached_data_urls() -> None:
    source = _read_source()
    parts = "\n\n".join(
        _extract_function(source, name)
        for name in (
            "sanitizeFileName",
            "dataURLtoBlob",
            "appendUploadedImagesToFormData",
        )
    )
    script = textwrap.dedent(
        f"""
        const appended = [];
        const SUPPORTED_IMAGE_TYPES = [
          'image/jpeg',
          'image/jpg',
          'image/png',
          'image/gif',
          'image/webp',
          'image/bmp'
        ];
        class Blob {{
          constructor(parts, options) {{
            this.parts = parts;
            this.type = options && options.type ? options.type : '';
            this.size = parts.reduce((total, part) => {{
              if (typeof part === 'string') return total + part.length;
              if (part && typeof part.byteLength === 'number') return total + part.byteLength;
              if (part && typeof part.length === 'number') return total + part.length;
              return total;
            }}, 0);
          }}
        }}
        function atob(value) {{
          const text = String(value);
          if (!/^[A-Za-z0-9+/]*={{0,2}}$/.test(text) || text.length % 4 === 1) {{
            throw new Error('invalid base64');
          }}
          return Buffer.from(text, 'base64').toString('binary');
        }}
        const formData = {{
          append(name, blob, filename) {{
            appended.push({{ name, size: blob.size, type: blob.type, filename }});
          }},
        }};
        let uploadedImages = [
          {{ name: 'good.png', data: 'data:image/png;base64,AAEC' }},
          {{ name: 'bad.png', data: 'data:image/png;base64,@@@' }},
          {{ name: 'empty.png', data: 'data:image/png;base64,' }},
          {{ name: 'vector.svg', data: 'data:image/svg+xml;base64,PHN2Zy8+' }},
          {{ name: 'plain.txt', data: 'not-a-data-url' }},
        ];

        {parts}

        const result = appendUploadedImagesToFormData(formData);
        process.stdout.write(JSON.stringify({{ result, appended, uploadedImages }}));
        """
    )

    assert json.loads(_run_node(script)) == {
        "result": {"appended": 1, "dropped": 4},
        "appended": [
            {"name": "image_0", "size": 3, "type": "image/png", "filename": "good.png"}
        ],
        "uploadedImages": [{"name": "good.png", "data": "data:image/png;base64,AAEC"}],
    }


def test_submit_with_data_uses_validating_image_append_helper() -> None:
    source = _read_source()
    submit_with_data = _extract_function(source, "submitWithData")

    assert "appendUploadedImagesToFormData(formData)" in submit_with_data
    assert "dataURLtoBlob(imageData.data)" not in submit_with_data
    assert "uploadedImages.forEach((imageData, index)" not in submit_with_data


def test_process_images_reserves_pending_slot_before_async_compression() -> None:
    source = _read_source()
    process_images_parts = "\n\n".join(
        _extract_function(source, name)
        for name in (
            "getImageUploadTargetImages",
            "getPendingImageUploadKey",
            "getPendingImageUploadCount",
            "incrementPendingImageUploadCount",
            "decrementPendingImageUploadCount",
            "getTaskIdString",
            "getOpenTaskId",
            "isTaskStillOpenForLocalState",
            "processImages",
        )
    )
    script = textwrap.dedent(
        f"""
        (async () => {{
          const messages = [];
          const resolvers = [];
          const compressCalls = [];
          let uploadedImages = [];
          let pendingImageUploadCounts = {{}};
          let renderCalls = 0;
          let syncCalls = 0;
          let activeTaskId = null;
          let currentConfig = null;
          let allTasks = [];
          let hasInitializedTaskIdTracking = false;
          let taskImages = {{}};
          const MAX_IMAGE_COUNT = 1;
          const vscode = {{
            postMessage(message) {{
              messages.push({{ type: 'postMessage', message }});
            }},
          }};

          function t(key, params) {{
            const value = params && Object.prototype.hasOwnProperty.call(params, 'count')
              ? params.count
              : params && params.reason
                ? params.reason
                : '';
            return `${{key}}:${{value}}`;
          }}
          function logError(message) {{
            messages.push({{ type: 'logError', message }});
          }}
          function sanitizeFileName(value) {{
            return String(value || '').trim();
          }}
          function renderUploadedImages() {{
            renderCalls += 1;
          }}
          function syncImagesToTaskCache() {{
            syncCalls += 1;
          }}
          function compressImageToDataURL(file) {{
            compressCalls.push(file.name);
            return new Promise((resolve) => {{
              resolvers.push(() => resolve({{
                name: file.name,
                data: 'data:image/png;base64,AAEC',
              }}));
            }});
          }}

          {process_images_parts}

          const firstPromise = processImages([{{ name: 'first.png' }}]);
          const secondPromise = processImages([{{ name: 'second.png' }}]);
          const beforeResolve = {{
            pendingImageUploadCounts: {{ ...pendingImageUploadCounts }},
            uploadedCount: uploadedImages.length,
            compressCalls: compressCalls.slice(),
            resolverCount: resolvers.length,
            messages: messages.slice(),
          }};

          while (resolvers.length) {{
            resolvers.shift()();
          }}
          await Promise.all([firstPromise, secondPromise]);

          process.stdout.write(JSON.stringify({{
            beforeResolve,
            final: {{
              pendingImageUploadCounts,
              uploadedImages,
              renderCalls,
              syncCalls,
              compressCalls,
              resolverCount: resolvers.length,
              messages,
            }},
          }}));
        }})().catch((err) => {{
          console.error(err && err.stack ? err.stack : err);
          process.exit(1);
        }});
        """
    )

    assert json.loads(_run_node(script)) == {
        "beforeResolve": {
            "pendingImageUploadCounts": {"current": 1},
            "uploadedCount": 0,
            "compressCalls": ["first.png"],
            "resolverCount": 1,
            "messages": [
                {"type": "logError", "message": "ui.image.tooManyFiles:1"},
                {
                    "type": "postMessage",
                    "message": {
                        "type": "showInfo",
                        "message": "ui.image.tooManyFiles:1",
                    },
                },
            ],
        },
        "final": {
            "pendingImageUploadCounts": {},
            "uploadedImages": [
                {"name": "first.png", "data": "data:image/png;base64,AAEC"}
            ],
            "renderCalls": 1,
            "syncCalls": 0,
            "compressCalls": ["first.png"],
            "resolverCount": 0,
            "messages": [
                {"type": "logError", "message": "ui.image.tooManyFiles:1"},
                {
                    "type": "postMessage",
                    "message": {
                        "type": "showInfo",
                        "message": "ui.image.tooManyFiles:1",
                    },
                },
            ],
        },
    }


def test_process_images_releases_pending_slot_after_compression_failure() -> None:
    source = _read_source()
    process_images_parts = "\n\n".join(
        _extract_function(source, name)
        for name in (
            "getImageUploadTargetImages",
            "getPendingImageUploadKey",
            "getPendingImageUploadCount",
            "incrementPendingImageUploadCount",
            "decrementPendingImageUploadCount",
            "getTaskIdString",
            "getOpenTaskId",
            "isTaskStillOpenForLocalState",
            "processImages",
        )
    )
    script = textwrap.dedent(
        f"""
        (async () => {{
          const messages = [];
          const compressCalls = [];
          let uploadedImages = [];
          let pendingImageUploadCounts = {{}};
          let renderCalls = 0;
          let activeTaskId = null;
          let currentConfig = null;
          let allTasks = [];
          let hasInitializedTaskIdTracking = false;
          let taskImages = {{}};
          const MAX_IMAGE_COUNT = 1;
          const vscode = {{
            postMessage(message) {{
              messages.push({{ type: 'postMessage', message }});
            }},
          }};

          function t(key, params) {{
            const value = params && Object.prototype.hasOwnProperty.call(params, 'count')
              ? params.count
              : params && params.reason
                ? params.reason
                : '';
            return `${{key}}:${{value}}`;
          }}
          function logError(message) {{
            messages.push({{ type: 'logError', message }});
          }}
          function sanitizeFileName(value) {{
            return String(value || '').trim();
          }}
          function renderUploadedImages() {{
            renderCalls += 1;
          }}
          function syncImagesToTaskCache() {{}}
          async function compressImageToDataURL(file) {{
            compressCalls.push(file.name);
            if (file.name === 'bad.png') {{
              throw new Error('decode failed');
            }}
            return {{
              name: file.name,
              data: 'data:image/png;base64,AAEC',
            }};
          }}

          {process_images_parts}

          await processImages([{{ name: 'bad.png' }}]);
          const afterFailure = {{
            pendingImageUploadCounts: {{ ...pendingImageUploadCounts }},
            uploadedCount: uploadedImages.length,
            messages: messages.slice(),
          }};
          await processImages([{{ name: 'good.png' }}]);

          process.stdout.write(JSON.stringify({{
            afterFailure,
            final: {{
              pendingImageUploadCounts,
              uploadedImages,
              renderCalls,
              compressCalls,
              messages,
            }},
          }}));
        }})().catch((err) => {{
          console.error(err && err.stack ? err.stack : err);
          process.exit(1);
        }});
        """
    )

    assert json.loads(_run_node(script)) == {
        "afterFailure": {
            "pendingImageUploadCounts": {},
            "uploadedCount": 0,
            "messages": [
                {
                    "type": "logError",
                    "message": "ui.image.processingFailedReason:decode failed",
                },
                {
                    "type": "postMessage",
                    "message": {
                        "type": "showInfo",
                        "message": "ui.image.processingFailedReason:decode failed",
                    },
                },
            ],
        },
        "final": {
            "pendingImageUploadCounts": {},
            "uploadedImages": [
                {"name": "good.png", "data": "data:image/png;base64,AAEC"}
            ],
            "renderCalls": 1,
            "compressCalls": ["bad.png", "good.png"],
            "messages": [
                {
                    "type": "logError",
                    "message": "ui.image.processingFailedReason:decode failed",
                },
                {
                    "type": "postMessage",
                    "message": {
                        "type": "showInfo",
                        "message": "ui.image.processingFailedReason:decode failed",
                    },
                },
            ],
        },
    }


def test_process_images_keeps_processed_image_with_origin_task_after_switch() -> None:
    source = _read_source()
    process_images_parts = "\n\n".join(
        _extract_function(source, name)
        for name in (
            "getImageUploadTargetImages",
            "cacheImagesForTask",
            "getPendingImageUploadKey",
            "getPendingImageUploadCount",
            "incrementPendingImageUploadCount",
            "decrementPendingImageUploadCount",
            "getTaskIdString",
            "getOpenTaskId",
            "isTaskStillOpenForLocalState",
            "processImages",
        )
    )
    script = textwrap.dedent(
        f"""
        (async () => {{
          const resolvers = [];
          const syncCalls = [];
          let uploadedImages = [];
          let pendingImageUploadCounts = {{}};
          let activeTaskId = 'task-a';
          let currentConfig = {{ task_id: 'task-a' }};
          let allTasks = [
            {{ task_id: 'task-a', status: 'active' }},
            {{ task_id: 'task-b', status: 'pending' }},
          ];
          let hasInitializedTaskIdTracking = true;
          let renderCalls = 0;
          let persistCalls = 0;
          let taskImages = {{
            'task-a': [],
            'task-b': [
              {{
                name: 'b-existing.png',
                data: 'data:image/png;base64,BBBB',
              }},
            ],
          }};
          const MAX_IMAGE_COUNT = 10;
          const vscode = {{ postMessage() {{}} }};

          function t(key, params) {{
            const value = params && Object.prototype.hasOwnProperty.call(params, 'count')
              ? params.count
              : params && params.reason
                ? params.reason
                : '';
            return `${{key}}:${{value}}`;
          }}
          function logError() {{}}
          function sanitizeFileName(value) {{
            return String(value || '').trim();
          }}
          function renderUploadedImages() {{
            renderCalls += 1;
          }}
          function schedulePersistUiState() {{
            persistCalls += 1;
          }}
          function syncImagesToTaskCache(taskId) {{
            syncCalls.push(taskId);
          }}
          function compressImageToDataURL(file) {{
            return new Promise((resolve) => {{
              resolvers.push(() => resolve({{
                name: file.name,
                data: 'data:image/png;base64,AAEC',
              }}));
            }});
          }}

          {process_images_parts}

          const uploadPromise = processImages([{{ name: 'a.png' }}]);

          activeTaskId = 'task-b';
          currentConfig = {{ task_id: 'task-b' }};
          uploadedImages = taskImages['task-b'];

          while (resolvers.length) {{
            resolvers.shift()();
          }}
          await uploadPromise;

          process.stdout.write(JSON.stringify({{
            pendingImageUploadCounts,
            uploadedImages,
            taskImages,
            renderCalls,
            persistCalls,
            syncCalls,
          }}));
        }})().catch((err) => {{
          console.error(err && err.stack ? err.stack : err);
          process.exit(1);
        }});
        """
    )

    assert json.loads(_run_node(script)) == {
        "pendingImageUploadCounts": {},
        "uploadedImages": [
            {"name": "b-existing.png", "data": "data:image/png;base64,BBBB"}
        ],
        "taskImages": {
            "task-a": [{"name": "a.png", "data": "data:image/png;base64,AAEC"}],
            "task-b": [
                {"name": "b-existing.png", "data": "data:image/png;base64,BBBB"}
            ],
        },
        "renderCalls": 0,
        "persistCalls": 1,
        "syncCalls": [],
    }


def test_process_images_counts_pending_slots_per_task_not_globally() -> None:
    source = _read_source()
    process_images_parts = "\n\n".join(
        _extract_function(source, name)
        for name in (
            "getImageUploadTargetImages",
            "cacheImagesForTask",
            "getPendingImageUploadKey",
            "getPendingImageUploadCount",
            "incrementPendingImageUploadCount",
            "decrementPendingImageUploadCount",
            "getTaskIdString",
            "getOpenTaskId",
            "isTaskStillOpenForLocalState",
            "processImages",
        )
    )
    script = textwrap.dedent(
        f"""
        (async () => {{
          const messages = [];
          const resolvers = [];
          const compressCalls = [];
          const syncCalls = [];
          let pendingImageUploadCounts = {{}};
          let activeTaskId = 'task-a';
          let currentConfig = {{ task_id: 'task-a' }};
          let allTasks = [
            {{ task_id: 'task-a', status: 'active' }},
            {{ task_id: 'task-b', status: 'pending' }},
          ];
          let hasInitializedTaskIdTracking = true;
          let renderCalls = 0;
          let persistCalls = 0;
          let taskImages = {{
            'task-a': [],
            'task-b': [],
          }};
          let uploadedImages = taskImages['task-a'];
          const MAX_IMAGE_COUNT = 1;
          const vscode = {{
            postMessage(message) {{
              messages.push({{ type: 'postMessage', message }});
            }},
          }};

          function t(key, params) {{
            const value = params && Object.prototype.hasOwnProperty.call(params, 'count')
              ? params.count
              : params && params.reason
                ? params.reason
                : '';
            return `${{key}}:${{value}}`;
          }}
          function logError(message) {{
            messages.push({{ type: 'logError', message }});
          }}
          function sanitizeFileName(value) {{
            return String(value || '').trim();
          }}
          function renderUploadedImages() {{
            renderCalls += 1;
          }}
          function schedulePersistUiState() {{
            persistCalls += 1;
          }}
          function syncImagesToTaskCache(taskId) {{
            syncCalls.push(taskId);
            taskImages[taskId] = uploadedImages.map((img) => ({{
              name: img.name,
              data: img.data,
            }}));
          }}
          function compressImageToDataURL(file) {{
            compressCalls.push(file.name);
            return new Promise((resolve) => {{
              resolvers.push(() => resolve({{
                name: file.name,
                data: `data:image/png;base64,${{file.name}}`,
              }}));
            }});
          }}

          {process_images_parts}

          const firstPromise = processImages([{{ name: 'a.png' }}]);
          activeTaskId = 'task-b';
          currentConfig = {{ task_id: 'task-b' }};
          uploadedImages = taskImages['task-b'];
          const secondPromise = processImages([{{ name: 'b.png' }}]);
          const beforeResolve = {{
            pendingImageUploadCounts: {{ ...pendingImageUploadCounts }},
            compressCalls: compressCalls.slice(),
            messages: messages.slice(),
          }};

          while (resolvers.length) {{
            resolvers.shift()();
          }}
          await Promise.all([firstPromise, secondPromise]);

          process.stdout.write(JSON.stringify({{
            beforeResolve,
            final: {{
              pendingImageUploadCounts,
              uploadedImages,
              taskImages,
              renderCalls,
              persistCalls,
              syncCalls,
              compressCalls,
              messages,
            }},
          }}));
        }})().catch((err) => {{
          console.error(err && err.stack ? err.stack : err);
          process.exit(1);
        }});
        """
    )

    assert json.loads(_run_node(script)) == {
        "beforeResolve": {
            "pendingImageUploadCounts": {
                "task:task-a": 1,
                "task:task-b": 1,
            },
            "compressCalls": ["a.png", "b.png"],
            "messages": [],
        },
        "final": {
            "pendingImageUploadCounts": {},
            "uploadedImages": [
                {"name": "b.png", "data": "data:image/png;base64,b.png"}
            ],
            "taskImages": {
                "task-a": [{"name": "a.png", "data": "data:image/png;base64,a.png"}],
                "task-b": [{"name": "b.png", "data": "data:image/png;base64,b.png"}],
            },
            "renderCalls": 1,
            "persistCalls": 1,
            "syncCalls": ["task-b"],
            "compressCalls": ["a.png", "b.png"],
            "messages": [],
        },
    }


def test_process_images_drops_result_when_origin_task_disappears_mid_compression() -> (
    None
):
    source = _read_source()
    process_images_parts = "\n\n".join(
        _extract_function(source, name)
        for name in (
            "getImageUploadTargetImages",
            "cacheImagesForTask",
            "getPendingImageUploadKey",
            "getPendingImageUploadCount",
            "incrementPendingImageUploadCount",
            "decrementPendingImageUploadCount",
            "getTaskIdString",
            "getOpenTaskId",
            "isTaskStillOpenForLocalState",
            "processImages",
        )
    )
    script = textwrap.dedent(
        f"""
        (async () => {{
          const resolvers = [];
          const syncCalls = [];
          let pendingImageUploadCounts = {{}};
          let activeTaskId = 'task-a';
          let currentConfig = {{ task_id: 'task-a' }};
          let allTasks = [
            {{ task_id: 'task-a', status: 'active' }},
            {{ task_id: 'task-b', status: 'pending' }},
          ];
          let hasInitializedTaskIdTracking = true;
          let renderCalls = 0;
          let persistCalls = 0;
          let taskImages = {{
            'task-a': [],
            'task-b': [],
          }};
          let uploadedImages = taskImages['task-a'];
          const MAX_IMAGE_COUNT = 10;
          const vscode = {{ postMessage() {{}} }};

          function t(key, params) {{
            const value = params && Object.prototype.hasOwnProperty.call(params, 'count')
              ? params.count
              : params && params.reason
                ? params.reason
                : '';
            return `${{key}}:${{value}}`;
          }}
          function logError() {{}}
          function sanitizeFileName(value) {{
            return String(value || '').trim();
          }}
          function renderUploadedImages() {{
            renderCalls += 1;
          }}
          function schedulePersistUiState() {{
            persistCalls += 1;
          }}
          function syncImagesToTaskCache(taskId) {{
            syncCalls.push(taskId);
          }}
          function compressImageToDataURL(file) {{
            return new Promise((resolve) => {{
              resolvers.push(() => resolve({{
                name: file.name,
                data: 'data:image/png;base64,AAEC',
              }}));
            }});
          }}

          {process_images_parts}

          const uploadPromise = processImages([{{ name: 'late.png' }}]);

          activeTaskId = 'task-b';
          currentConfig = {{ task_id: 'task-b' }};
          allTasks = [{{ task_id: 'task-b', status: 'active' }}];
          uploadedImages = taskImages['task-b'];

          while (resolvers.length) {{
            resolvers.shift()();
          }}
          await uploadPromise;

          process.stdout.write(JSON.stringify({{
            pendingImageUploadCounts,
            uploadedImages,
            taskImages,
            renderCalls,
            persistCalls,
            syncCalls,
          }}));
        }})().catch((err) => {{
          console.error(err && err.stack ? err.stack : err);
          process.exit(1);
        }});
        """
    )

    assert json.loads(_run_node(script)) == {
        "pendingImageUploadCounts": {},
        "uploadedImages": [],
        "taskImages": {"task-a": [], "task-b": []},
        "renderCalls": 0,
        "persistCalls": 0,
        "syncCalls": [],
    }
