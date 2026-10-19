"""R726 · serving the images a task's prompt links to.

``POST /api/tasks`` accepts ``prompt_images`` (base64 bytes read by the MCP
process); ``GET /api/tasks/<task_id>/images/<n>`` serves them. The Web UI never
opens a file by itself, so these tests pin what it does with what it is handed:
only real images are served, with the type the bytes declare and never the one
the client claims, positions survive a bad entry, the bytes stay out of every
listing / export / persisted snapshot, and they disappear with the task.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any

import pytest

from ai_intervention_agent import local_images as li
from ai_intervention_agent.task_queue import Task, TaskQueue
from ai_intervention_agent.web_ui_routes import task as task_routes

PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000d4944415478da63f8cfc0f01f0005000201a1b0d1d40000000049454e44ae426082"
)
JPEG = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
GIF = b"GIF89a\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00\xff\xff\xff!\xf9\x04\x01"


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


@pytest.fixture(scope="module")
def client():
    from ai_intervention_agent.web_ui import WebFeedbackUI

    ui = WebFeedbackUI(prompt="image routes", task_id="image-routes-r726", port=19232)
    ui.app.config["TESTING"] = True
    ui.limiter.enabled = False
    return ui.app.test_client()


@pytest.fixture
def queue(monkeypatch: pytest.MonkeyPatch):
    real = TaskQueue(max_tasks=10)
    monkeypatch.setattr(task_routes, "get_task_queue", lambda: real)
    yield real
    real.stop_cleanup()


def create(client, task_id: str, images: Any = None, **extra: Any):
    body: dict[str, Any] = {"task_id": task_id, "prompt": "see the picture", **extra}
    if images is not None:
        body["prompt_images"] = images
    return client.post(
        "/api/tasks", data=json.dumps(body), content_type="application/json"
    )


def fetch(client, task_id: str, index: int | str):
    return client.get(f"/api/tasks/{task_id}/images/{index}")


def test_a_posted_image_is_served_back_byte_for_byte(client, queue):
    assert create(client, "t-1", [{"data": b64(PNG)}]).status_code == 200

    response = fetch(client, "t-1", 0)

    assert response.status_code == 200
    assert response.data == PNG
    assert response.mimetype == "image/png"


def test_every_supported_type_is_served_with_its_own_content_type(client, queue):
    create(
        client, "t-types", [{"data": b64(PNG)}, {"data": b64(JPEG)}, {"data": b64(GIF)}]
    )

    assert [fetch(client, "t-types", n).mimetype for n in range(3)] == [
        "image/png",
        "image/jpeg",
        "image/gif",
    ]


def test_the_response_is_cacheable_inline_and_not_sniffable(client, queue):
    create(client, "t-headers", [{"data": b64(PNG)}])

    headers = fetch(client, "t-headers", 0).headers

    assert headers["Cache-Control"] == "private, max-age=3600"
    assert headers["Content-Disposition"] == "inline"
    assert headers["X-Content-Type-Options"] == "nosniff"


def test_the_type_comes_from_the_bytes_not_from_the_client(client, queue):
    create(
        client,
        "t-claim",
        [{"mime_type": "text/html", "data": b64(PNG)}],
    )

    assert fetch(client, "t-claim", 0).mimetype == "image/png"


def test_html_or_svg_bytes_are_never_served(client, queue):
    create(
        client,
        "t-script",
        [
            {"mime_type": "image/png", "data": b64(b"<html><script>alert(1)</script>")},
            {"mime_type": "image/svg+xml", "data": b64(b"<svg onload='alert(1)'/>")},
        ],
    )

    assert fetch(client, "t-script", 0).status_code == 404
    assert fetch(client, "t-script", 1).status_code == 404


def test_a_bad_entry_keeps_the_positions_of_the_others(client, queue):
    create(
        client,
        "t-positions",
        [{"data": b64(PNG)}, {"data": "%%%"}, "nope", {"data": b64(JPEG)}],
    )

    assert fetch(client, "t-positions", 0).data == PNG
    assert fetch(client, "t-positions", 1).status_code == 404
    assert fetch(client, "t-positions", 2).status_code == 404
    assert fetch(client, "t-positions", 3).data == JPEG


@pytest.mark.parametrize("index", [1, 5, 99, 10**12])
def test_an_index_past_the_end_is_a_json_404(client, queue, index: int):
    create(client, "t-end", [{"data": b64(PNG)}])

    response = fetch(client, "t-end", index)

    assert response.status_code == 404
    assert response.get_json()["success"] is False


@pytest.mark.parametrize("index", ["-1", "abc", "1.5", "0x1"])
def test_a_malformed_index_is_a_404_not_a_500(client, queue, index: str):
    create(client, "t-malformed", [{"data": b64(PNG)}])

    assert fetch(client, "t-malformed", index).status_code == 404


def test_an_unknown_task_has_no_images(client, queue):
    response = fetch(client, "never-created", 0)

    assert response.status_code == 404
    assert response.get_json()["success"] is False


def test_a_task_without_images_answers_404(client, queue):
    assert create(client, "t-none").status_code == 200

    assert fetch(client, "t-none", 0).status_code == 404


@pytest.mark.parametrize(
    "junk", ["a string", {"data": b64(PNG)}, 7, True, [[]], [None]]
)
def test_a_malformed_field_does_not_stop_the_task_from_being_created(
    client, queue, junk
):
    response = create(client, "t-junk", junk)

    assert response.status_code == 200
    assert queue.get_task("t-junk") is not None
    assert fetch(client, "t-junk", 0).status_code == 404


def test_at_most_the_maximum_number_of_images_is_kept(client, queue):
    images = [{"data": b64(PNG + bytes([n]))} for n in range(li.MAX_IMAGES + 3)]
    create(client, "t-many", images)

    assert fetch(client, "t-many", li.MAX_IMAGES - 1).status_code == 200
    assert fetch(client, "t-many", li.MAX_IMAGES).status_code == 404


def test_an_oversize_image_is_refused_but_the_task_survives(
    client, queue, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(li, "MAX_IMAGE_BYTES", len(PNG))
    create(client, "t-big", [{"data": b64(PNG + b"\x00")}, {"data": b64(PNG)}])

    assert fetch(client, "t-big", 0).status_code == 404
    assert fetch(client, "t-big", 1).status_code == 200


def test_the_task_listing_never_carries_image_data(client, queue):
    create(client, "t-leak", [{"data": b64(PNG)}], predefined_options=["A"])
    needle = b64(PNG)

    for url in ("/api/tasks", "/api/tasks/t-leak", "/api/tasks/export"):
        response = client.get(url)
        assert response.status_code == 200, url
        assert needle not in response.get_data(as_text=True), url
        assert "prompt_images" not in response.get_data(as_text=True), url


def test_images_are_gone_when_the_task_is_removed(client, queue):
    create(client, "t-removed", [{"data": b64(PNG)}])
    assert fetch(client, "t-removed", 0).status_code == 200

    assert queue.remove_task("t-removed")

    assert fetch(client, "t-removed", 0).status_code == 404


def test_the_bytes_are_never_written_to_the_persisted_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    snapshot = tmp_path / "tasks.json"
    persisted = TaskQueue(max_tasks=5, persist_path=str(snapshot))
    try:
        assert persisted.add_task(
            "t-persist",
            "prompt ![x](/api/tasks/t-persist/images/0)",
            prompt_images=[li.PromptImage("image/png", PNG)],
        )
        text = snapshot.read_text(encoding="utf-8")
        assert "t-persist" in text
        assert b64(PNG) not in text
        assert "prompt_images" not in text
    finally:
        persisted.stop_cleanup()

    restored = TaskQueue(max_tasks=5, persist_path=str(snapshot))
    try:
        task = restored.get_task("t-persist")
        assert task is not None
        assert task.prompt_images == ()
    finally:
        restored.stop_cleanup()


def test_the_model_keeps_the_bytes_out_of_dumps_and_reprs():
    task = Task(
        task_id="t-model",
        prompt="p",
        prompt_images=(li.PromptImage("image/png", PNG * 50), None),
    )

    assert "prompt_images" not in task.model_dump()
    assert "prompt_images" not in task.model_dump_json()
    assert "prompt_images" not in repr(task)
    assert len(task.prompt_images) == 2


def test_add_task_defaults_to_no_images(queue):
    assert queue.add_task("t-default", "plain prompt")

    task = queue.get_task("t-default")
    assert task is not None
    assert task.prompt_images == ()
