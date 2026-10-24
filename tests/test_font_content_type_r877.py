"""R877: the Content-Type of a Web font does not depend on the host's ``mime.types``.

The Web UI serves the MathJax CHTML fonts (``static/js/output/chtml/fonts/woff-v2/*.woff``) with
Flask's own static endpoint, and ``send_from_directory`` asks the standard library's ``mimetypes``
for the type of a file by its extension.  The table that ``mimetypes`` ships with has no ``.woff`` and
no ``.woff2`` up to Python 3.13 (3.14 added them), so there the answer came from the host:
``/etc/mime.types`` on Debian and Ubuntu, ``/etc/apache2/mime.types`` on macOS.  A slim Linux image
has no such file, and the fonts went out as ``application/octet-stream`` there; a host whose file
still says ``application/x-font-woff`` made it a third value.  Browsers load a web font whatever its
type says, so nothing visible broke, but the header of the same file differed from host to host.

``web_ui_routes/static.py`` registers ``font/woff`` and ``font/woff2`` (RFC 8081) with ``mimetypes``
when it is imported.  These tests run a clean interpreter for each scenario, because the type table
is process-wide state that the pytest process has already filled from its own host:

* a host without any ``mime.types`` file (and, on Python 3.14, without the table's own entries): the
  shipped font is answered as ``font/woff``;
* a host whose file says something else for both extensions: ours wins, so the answer is the same
  everywhere;
* every font extension that is shipped under ``static/`` is one that gets registered.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
STATIC_DIR = REPO_ROOT / "src" / "ai_intervention_agent" / "static"
FONTS_DIR = STATIC_DIR / "js" / "output" / "chtml" / "fonts" / "woff-v2"

# The extensions the ``/fonts/`` route lets through (R112).
FONT_EXTENSIONS = {".woff", ".woff2", ".ttf", ".otf", ".eot", ".ttc"}

CHILD = r"""
import json
import mimetypes
import sys

scenario = json.loads(sys.argv[1])
mimetypes.knownfiles = scenario["knownfiles"]
mimetypes.init()
if scenario["strip_the_tables_own_entries"]:
    for extension in (".woff", ".woff2"):
        mimetypes.types_map.pop(extension, None)


def types() -> dict[str, str | None]:
    return {e: mimetypes.guess_type("a" + e)[0] for e in (".woff", ".woff2")}


before = types()

import ai_intervention_agent.web_ui_routes.static  # noqa: F401  (registers the font types)
from flask import Flask

app = Flask("r877", static_folder=scenario["static_folder"], static_url_path="/static")
response = app.test_client().get("/static/" + scenario["url_path"])
try:
    print(
        "R877-RESULT "
        + json.dumps(
            {
                "before": before,
                "status": response.status_code,
                "content_type": response.headers.get("Content-Type"),
                "after": types(),
            }
        )
    )
finally:
    response.close()
"""


def _a_shipped_font() -> str:
    """URL path (below ``/static/``) of one font the bundle ships."""
    fonts = sorted(FONTS_DIR.glob("*.woff"))
    assert fonts, f"no .woff file under {FONTS_DIR}"
    return fonts[0].relative_to(STATIC_DIR).as_posix()


def _run_in_a_clean_interpreter(scenario: dict) -> dict:
    done = subprocess.run(
        [sys.executable, "-c", CHILD, json.dumps(scenario)],
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    assert done.returncode == 0, f"exit {done.returncode}: {done.stderr}"
    lines = [
        line for line in done.stdout.splitlines() if line.startswith("R877-RESULT ")
    ]
    assert len(lines) == 1, done.stdout
    return json.loads(lines[0].removeprefix("R877-RESULT "))


class TestTheTypeDoesNotDependOnTheHost:
    def test_a_host_without_a_mime_types_file_answers_font_woff(self) -> None:
        result = _run_in_a_clean_interpreter(
            {
                "knownfiles": [],
                # Python 3.14's own table has the two; 3.13 and older do not.  Either way the
                # process starts out knowing nothing about them.
                "strip_the_tables_own_entries": True,
                "static_folder": str(STATIC_DIR),
                "url_path": _a_shipped_font(),
            }
        )

        # The control: before ``static.py`` is imported there is nothing to answer with.
        assert result["before"] == {".woff": None, ".woff2": None}
        assert result["status"] == 200
        assert result["content_type"] == "font/woff"
        assert result["after"] == {".woff": "font/woff", ".woff2": "font/woff2"}

    def test_a_host_file_that_says_something_else_does_not_win(
        self, tmp_path: Path
    ) -> None:
        host_file = tmp_path / "mime.types"
        host_file.write_text(
            "application/x-font-woff\t\t\twoff\napplication/x-font-woff2\t\t\twoff2\n",
            encoding="utf-8",
        )

        result = _run_in_a_clean_interpreter(
            {
                "knownfiles": [str(host_file)],
                "strip_the_tables_own_entries": False,
                "static_folder": str(STATIC_DIR),
                "url_path": _a_shipped_font(),
            }
        )

        # The control: the host's file is what the interpreter had read.
        assert result["before"] == {
            ".woff": "application/x-font-woff",
            ".woff2": "application/x-font-woff2",
        }
        assert result["status"] == 200
        assert result["content_type"] == "font/woff"
        assert result["after"] == {".woff": "font/woff", ".woff2": "font/woff2"}


class TestEveryShippedFontExtensionIsRegistered:
    def test_the_extensions_under_static_are_all_in_the_registration(self) -> None:
        from ai_intervention_agent.web_ui_routes.static import _FONT_MIME_TYPES

        registered = {extension for extension, _ in _FONT_MIME_TYPES}
        shipped = {
            path.suffix.lower()
            for path in STATIC_DIR.rglob("*")
            if path.suffix.lower() in FONT_EXTENSIONS
        }

        assert shipped, "the bundle ships no font any more; this check has gone idle"
        assert sorted(shipped - registered) == [], (
            "a font file of a kind that web_ui_routes/static.py does not register is shipped "
            "(its Content-Type would depend on the host again)"
        )

    @pytest.mark.parametrize(
        ("extension", "mime_type"),
        [(".woff", "font/woff"), (".woff2", "font/woff2")],
    )
    def test_the_registered_types_are_the_ones_of_rfc_8081(
        self, extension: str, mime_type: str
    ) -> None:
        from ai_intervention_agent.web_ui_routes.static import _FONT_MIME_TYPES

        assert dict(_FONT_MIME_TYPES)[extension] == mime_type
