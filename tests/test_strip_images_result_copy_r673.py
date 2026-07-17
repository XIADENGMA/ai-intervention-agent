from __future__ import annotations

import inspect

from ai_intervention_agent.web_ui_routes.task import _strip_images_from_result


def test_strip_images_result_snapshot_uses_dict_copy() -> None:
    source = inspect.getsource(_strip_images_from_result)

    assert "sanitized = result.copy()" in source
    assert "sanitized: dict[str, Any] = dict(result)" not in source
    assert "sanitized = dict(result)" not in source


def test_include_images_true_returns_original_result_object() -> None:
    original = {"images": [{"data": "AAAA", "filename": "x.png"}]}

    assert _strip_images_from_result(original, include_images=True) is original


def test_include_images_false_strips_without_mutating_result() -> None:
    original = {
        "user_input": "ok",
        "images": [
            {
                "data": "AAAA",
                "filename": "x.png",
                "size": 4,
                "content_type": "image/png",
            }
        ],
    }

    stripped = _strip_images_from_result(original, include_images=False)

    assert stripped is not original
    assert stripped == {
        "user_input": "ok",
        "images": [
            {
                "filename": "x.png",
                "size": 4,
                "content_type": "image/png",
            }
        ],
        "images_stripped": True,
    }
    assert original["images"][0]["data"] == "AAAA"
    assert "images_stripped" not in original


def test_include_images_false_without_list_images_returns_original() -> None:
    no_images = {"user_input": "ok"}
    malformed_images = {"images": "not-a-list"}

    assert _strip_images_from_result(no_images, include_images=False) is no_images
    assert (
        _strip_images_from_result(malformed_images, include_images=False)
        is malformed_images
    )
