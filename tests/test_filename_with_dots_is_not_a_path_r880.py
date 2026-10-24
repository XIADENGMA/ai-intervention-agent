"""R880: a file name with two dots in it is a file name, not a path.

Both upload checks refused every name that had ``..`` anywhere in it, as if the two dots were a
way out of the folder: ``FileValidator._validate_filename`` (``".." in filename``) and the page's
``ValidationUtils.validateFilename`` (``filename.includes("..")``).  A name leaves its folder only
through a separator (``/`` or ``\\``), and both checks already refuse those on the next line, so
the dots added nothing but false alarms: ``a..b.png``, ``report..final.png``, ``v1..2.png``,
``photo..png`` and ``x..`` were all refused with ``文件名包含非法字符``, which names a character
that is not there.  The server never writes the name to disk (the saved copy is a UUID and the
agent is only told the name), so there was nothing for the substring to guard.

What the user saw depended on where the picture came from.  The page checks the file when it is
added and refuses it with "File name contains path traversal characters", a message that is wrong
for the name.  The VS Code webview has no such check (its ``sanitizeFileName`` leaves dots alone),
sends the file as it is, and the server dropped it: ``extract_uploaded_images`` logs a warning and
goes on, so ``POST /api/tasks/<id>/submit`` answered success while the picture never reached the
agent.  The page can reach the server with such a name too, whenever its compression does not
make the file smaller and it sends the original.

The substring did one more thing by accident: it refused names made only of dots longer than two
(``...``), which are as little a file as ``.`` and ``..``.  Dropping it alone would have let them
in, so the rule is now what the error text always said, a name that is empty or only dots.

What the tests pin, in the validator, in the page script (the source and the minified copy the
page is served, run by node), in the upload helper and end to end through the submit route:

* a name with dots inside it, at its start or at its end, and no separator is accepted;
* a name that is only dots (with or without spaces round it) is refused, and says so;
* a name with ``/`` or ``\\`` in it is refused, whatever surrounds it, and says "illegal
  character" in the validator and "path traversal characters" in the page;
* the validator and the page agree on every name in the lists;
* the VS Code webview still sends the dots as they are (the premise of the server-side half).
"""

from __future__ import annotations

import functools
import io
import json
import shutil
import subprocess
import textwrap
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from flask.testing import FlaskClient

from ai_intervention_agent.file_validator import FileValidator
from ai_intervention_agent.task_queue_singleton import get_task_queue
from ai_intervention_agent.web_ui import WebFeedbackUI
from ai_intervention_agent.web_ui_routes._upload_helpers import extract_uploaded_images

REPO_ROOT = Path(__file__).resolve().parent.parent
JS_DIR = REPO_ROOT / "src" / "ai_intervention_agent" / "static" / "js"
PAGE_SCRIPTS = [JS_DIR / "validation-utils.js", JS_DIR / "validation-utils.min.js"]
WEBVIEW_UI = REPO_ROOT / "packages" / "vscode" / "webview-ui.js"

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 200
LOOPBACK = {"REMOTE_ADDR": "127.0.0.1"}

ILLEGAL_CHARACTER = "文件名包含非法字符"
ONLY_DOTS = "文件名无效（空或只包含点）"
PAGE_TRAVERSAL = "validation.filenamePathTraversal"

# dots that are only a part of the name: nothing here can lead out of a folder
DOTS_INSIDE = [
    "a..b.png",
    "report..final.png",
    "v1..2.png",
    "photo..png",
    "a...b.png",
    "wait....png",
    "..png",
    "x..",
]
# the current folder, the parent, longer runs of dots, and the same with spaces round them
ONLY_DOTS_NAMES = [".", "..", "...", "....", " .. ", ".. "]
# the way out of a folder, with the dots, without them, and in both slash styles
SEPARATORS = [
    "../a.png",
    "a/../b.png",
    "..\\a.png",
    "a\\..\\b.png",
    "a/b.png",
    "a\\b.png",
    "/a.png",
    "\\a.png",
]
EVERY_NAME = DOTS_INSIDE + ONLY_DOTS_NAMES + SEPARATORS

needs_node = pytest.mark.skipif(
    shutil.which("node") is None, reason="node runtime unavailable"
)


def verdict(name: str) -> tuple[bool, list[str], list[str]]:
    result = FileValidator().validate_file(PNG, name)
    return result["valid"], result["errors"], result["warnings"]


# --------------------------------------------------------------------------- node


NODE_SCRIPT = textwrap.dedent(
    """
    const fs = require('fs');
    const vm = require('vm');
    const code = fs.readFileSync(__SOURCE__, 'utf8')
      + '\\nglobalThis.__ValidationUtils = ValidationUtils;';
    const sandbox = {};
    vm.createContext(sandbox);
    vm.runInContext(code, sandbox);
    const utils = sandbox.__ValidationUtils;
    const answer = { filename: {}, image: {} };
    for (const name of __NAMES__) {
      answer.filename[name] = utils.validateFilename(name);
      answer.image[name] = utils.validateImageFile({ name, type: 'image/png', size: 5000 });
    }
    process.stdout.write(JSON.stringify(answer));
    """
)


@functools.cache
def page_answers(source: Path) -> dict[str, dict[str, Any]]:
    """What ``ValidationUtils`` says about every name, run by node on ``source``.

    Without ``window.AIIA_I18N`` the script's translator hands back the key, so an error is the
    key of its message.
    """
    script = NODE_SCRIPT.replace("__SOURCE__", json.dumps(str(source))).replace(
        "__NAMES__", json.dumps(EVERY_NAME)
    )
    proc = subprocess.run(
        ["node", "-e", script],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.returncode == 0, f"node: {proc.stderr!r}"
    return json.loads(proc.stdout)


def page_errors(source: Path, name: str) -> list[str]:
    return page_answers(source)["filename"][name]


# --------------------------------------------------------------------------- the validator


class TestTheValidator:
    @pytest.mark.parametrize("name", DOTS_INSIDE)
    def test_dots_inside_a_name_are_not_a_reason_to_refuse_it(self, name: str) -> None:
        valid, errors, _ = verdict(name)
        assert errors == []
        assert valid is True

    @pytest.mark.parametrize("name", ONLY_DOTS_NAMES)
    def test_a_name_of_nothing_but_dots_is_refused_and_says_so(self, name: str) -> None:
        valid, errors, _ = verdict(name)
        assert valid is False
        assert ONLY_DOTS in errors

    @pytest.mark.parametrize("name", ["...", "...."])
    def test_a_long_run_of_dots_is_not_called_an_illegal_character(
        self, name: str
    ) -> None:
        _, errors, _ = verdict(name)
        assert ILLEGAL_CHARACTER not in errors

    @pytest.mark.parametrize("name", SEPARATORS)
    def test_a_separator_is_refused_as_an_illegal_character(self, name: str) -> None:
        valid, errors, _ = verdict(name)
        assert valid is False
        assert ILLEGAL_CHARACTER in errors

    def test_a_forward_slash_alone_is_enough(self) -> None:
        assert verdict("a/b.png")[1] == [ILLEGAL_CHARACTER]

    def test_a_backslash_alone_is_enough(self) -> None:
        assert verdict("a\\b.png")[1] == [ILLEGAL_CHARACTER]

    def test_a_name_that_starts_with_dots_is_still_called_hidden(self) -> None:
        assert "隐藏文件" in verdict("..png")[2]
        assert "隐藏文件" not in verdict("a..b.png")[2]

    def test_a_nul_byte_is_still_refused(self) -> None:
        valid, errors, _ = verdict("a..b\x00.png")
        assert valid is False
        assert any("NUL" in error for error in errors)

    def test_an_accepted_name_carries_no_warning(self) -> None:
        assert verdict("a..b.png")[2] == []


# --------------------------------------------------------------------------- the page


@needs_node
@pytest.mark.parametrize("source", PAGE_SCRIPTS, ids=lambda p: p.name)
class TestThePageScript:
    @pytest.mark.parametrize("name", DOTS_INSIDE)
    def test_dots_inside_a_name_are_not_a_reason_to_refuse_it(
        self, source: Path, name: str
    ) -> None:
        assert page_errors(source, name) == []

    @pytest.mark.parametrize("name", DOTS_INSIDE)
    def test_an_image_with_such_a_name_is_accepted(
        self, source: Path, name: str
    ) -> None:
        answer = page_answers(source)["image"][name]
        assert answer == {"valid": True, "errors": []}

    @pytest.mark.parametrize("name", ONLY_DOTS_NAMES)
    def test_a_name_of_nothing_but_dots_is_refused(
        self, source: Path, name: str
    ) -> None:
        assert PAGE_TRAVERSAL in page_errors(source, name)

    @pytest.mark.parametrize("name", SEPARATORS)
    def test_a_separator_is_refused_as_path_traversal(
        self, source: Path, name: str
    ) -> None:
        assert PAGE_TRAVERSAL in page_errors(source, name)

    @pytest.mark.parametrize("name", ONLY_DOTS_NAMES + SEPARATORS)
    def test_an_image_with_such_a_name_is_refused(
        self, source: Path, name: str
    ) -> None:
        answer = page_answers(source)["image"][name]
        assert answer["valid"] is False

    @pytest.mark.parametrize("name", EVERY_NAME)
    def test_the_page_and_the_validator_agree(self, source: Path, name: str) -> None:
        assert (page_errors(source, name) == []) == verdict(name)[0]


# --------------------------------------------------------------------------- the webview


def extract_function(source: str, marker: str) -> str:
    start = source.find(marker)
    assert start != -1, f"no {marker!r} in the webview script"
    depth = 0
    for index in range(source.index("{", start), len(source)):
        depth += {"{": 1, "}": -1}.get(source[index], 0)
        if depth == 0:
            return source[start : index + 1]
    raise AssertionError(f"{marker!r} is not closed")


@needs_node
class TestTheWebview:
    def test_it_sends_the_dots_of_a_name_as_they_are(self) -> None:
        function = extract_function(
            WEBVIEW_UI.read_text(encoding="utf-8"), "function sanitizeFileName("
        )
        script = function + (
            "\nprocess.stdout.write(JSON.stringify("
            "['a..b.png', 'report..final.png', 'x..'].map(sanitizeFileName)));"
        )
        proc = subprocess.run(
            ["node", "-e", script],
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert proc.returncode == 0, f"node: {proc.stderr!r}"
        assert json.loads(proc.stdout) == ["a..b.png", "report..final.png", "x.."]


# --------------------------------------------------------------------------- the route


@pytest.fixture
def ui() -> WebFeedbackUI:
    instance = WebFeedbackUI(prompt="", auto_resubmit_timeout=0, port=19880)
    instance.app.config["TESTING"] = True
    instance.limiter.enabled = False
    object.__setattr__(instance, "shutdown_server", lambda: None)
    return instance


@pytest.fixture
def client(ui: WebFeedbackUI) -> Iterator[FlaskClient]:
    queue = get_task_queue()
    queue.clear_all_tasks()
    try:
        yield ui.app.test_client()
    finally:
        queue.clear_all_tasks()


class TestTheSubmitRoute:
    def submit(self, client: FlaskClient, task_id: str, name: str) -> list[str]:
        """The names of the images the agent gets when the user attaches one called ``name``."""
        assert get_task_queue().add_task(
            task_id=task_id, prompt="p", auto_resubmit_timeout=240
        )
        response = client.post(
            f"/api/tasks/{task_id}/submit",
            data={
                "feedback_text": "see the picture",
                "image_0": (io.BytesIO(PNG), name),
            },
            environ_base=LOOPBACK,
            content_type="multipart/form-data",
        )
        assert response.status_code == 200
        task = client.get(f"/api/tasks/{task_id}", environ_base=LOOPBACK).get_json()[
            "task"
        ]
        return [image["filename"] for image in task["result"].get("images", [])]

    def test_an_image_with_dots_in_its_name_reaches_the_agent(
        self, client: FlaskClient
    ) -> None:
        assert self.submit(client, "r880-dots", "a..b.png") == ["a..b.png"]

    def test_an_image_with_dots_at_the_end_of_its_name_reaches_the_agent(
        self, client: FlaskClient
    ) -> None:
        assert self.submit(client, "r880-end", "report..png") == ["report..png"]

    def test_an_image_whose_name_walks_out_of_the_folder_does_not(
        self, client: FlaskClient
    ) -> None:
        assert self.submit(client, "r880-walk", "../a.png") == []

    def test_an_image_named_with_only_dots_does_not(self, client: FlaskClient) -> None:
        assert self.submit(client, "r880-only", "...") == []


# --------------------------------------------------------------------------- the helper


class TestTheUploadHelper:
    """The helper the route calls, handed the name as it is.

    Werkzeug's multipart parser reads a backslash in a quoted file name as an escape and drops
    it (``..\\a.png`` reaches the route as ``..a.png``), so the backslash paths are tried here,
    where the name arrives untouched.
    """

    def kept(self, name: str) -> list[str]:
        upload = MagicMock()
        upload.filename = name
        upload.content_type = "image/png"
        upload.read.return_value = PNG
        request = MagicMock()
        request.files = {"image_0": upload}
        return [image["filename"] for image in extract_uploaded_images(request)]

    def test_a_name_with_dots_in_it_is_kept_as_it_is(self) -> None:
        assert self.kept("a..b.png") == ["a..b.png"]

    @pytest.mark.parametrize("name", [*SEPARATORS, "...", ".. "])
    def test_a_path_or_a_name_of_dots_is_dropped(self, name: str) -> None:
        assert self.kept(name) == []
