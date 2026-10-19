"""R726 · the ``[feedback] local_image_dirs`` setting.

One list decides which folders prompt images may be read from: ``["auto"]`` is
the default (workspace folders reported by the MCP client plus the temp
directory), ``[]`` switches the feature off, anything else names folders. These
tests pin the model, the shipped default file and the user documentation to the
same behaviour, and keep the setting aligned with its sibling ``skill_dirs``.
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

import pytest

from ai_intervention_agent import dir_settings as ds
from ai_intervention_agent import local_images as li
from ai_intervention_agent import skill_catalog as sc
from ai_intervention_agent.shared_types import FeedbackSectionConfig

REPO = Path(__file__).resolve().parent.parent


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ({}, ["auto"]),
        ({"local_image_dirs": []}, []),
        ({"local_image_dirs": "~/shots"}, ["~/shots"]),
        ({"local_image_dirs": [3]}, ["auto"]),
        ({"local_image_dirs": None}, ["auto"]),
        ({"local_image_dirs": ["auto", "~/shots"]}, ["auto", "~/shots"]),
        ({"local_image_dirs": [" ~/a ", "", "~/b"]}, ["~/a", "~/b"]),
    ],
)
def test_the_config_model_normalises_the_setting(
    raw: dict[str, Any], expected: list[str]
):
    assert FeedbackSectionConfig.model_validate(raw).local_image_dirs == expected


def test_the_default_list_is_not_shared_between_instances():
    first, second = FeedbackSectionConfig(), FeedbackSectionConfig()
    first.local_image_dirs.append("mutated")

    assert second.local_image_dirs == ["auto"]
    assert FeedbackSectionConfig().local_image_dirs == ["auto"]
    assert li.DEFAULT_IMAGE_DIRS == ("auto",)


def test_the_list_is_capped_like_every_directory_setting():
    result = li.normalize_image_dirs([f"d{n}" for n in range(100)])

    assert len(result) == ds.MAX_CONFIGURED_DIRS
    assert result[0] == "d0"


@pytest.mark.parametrize(
    "value",
    [None, [], "x", ["auto"], ["a", "", " b "], [1, None], 5, {"a": 1}, ("a", "b")],
)
def test_images_and_skills_read_their_folder_lists_the_same_way(value: Any):
    assert li.normalize_image_dirs(value) == sc.normalize_skill_dirs(value)


def test_the_shipped_default_file_declares_the_setting_with_the_default():
    data = tomllib.loads((REPO / "config.toml.default").read_text(encoding="utf-8"))

    assert data["feedback"]["local_image_dirs"] == ["auto"]
    assert (
        FeedbackSectionConfig.model_validate(data["feedback"]).local_image_dirs
        == data["feedback"]["local_image_dirs"]
    )


@pytest.mark.parametrize(
    ("name", "limits"),
    [
        (
            "configuration.md",
            f"At most {li.MAX_IMAGES} images per prompt, "
            f"{li.MAX_IMAGE_BYTES >> 20} MB each and {li.MAX_TOTAL_BYTES >> 20} MB together",
        ),
        (
            "configuration.zh-CN.md",
            f"每条提示词最多 {li.MAX_IMAGES} 张，"
            f"单张不超过 {li.MAX_IMAGE_BYTES >> 20} MB，"
            f"合计不超过 {li.MAX_TOTAL_BYTES >> 20} MB",
        ),
    ],
)
def test_the_configuration_guide_states_the_limits_the_code_enforces(
    name: str, limits: str
):
    text = (REPO / "docs" / name).read_text(encoding="utf-8")

    assert "local_image_dirs" in text
    assert limits in text
