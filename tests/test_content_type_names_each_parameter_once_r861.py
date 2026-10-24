"""R861: a response's ``Content-Type`` names each of its parameters once.

``Response(body, mimetype="text/plain; version=0.0.4; charset=utf-8")`` does not give that header.
Werkzeug appends ``; charset=utf-8`` to every ``text/*`` mimetype by itself
(``werkzeug.utils.get_content_type``) and does not read what the string already says, so two
routes answered with a header that repeated its charset:

* ``GET /api/system/metrics``: ``text/plain; version=0.0.4; charset=utf-8; charset=utf-8``;
* ``GET /api/tasks/export?format=markdown``: ``text/markdown; charset=utf-8; charset=utf-8``.

Nothing visibly broke.  Browsers read the first ``charset``, and Go's ``mime.ParseMediaType``
(Prometheus uses it on the scrape's ``Content-Type``) calls a repeated parameter name "incorrect,
but we allow them if they are equal".  But the value is not what the Prometheus client libraries
send, a parser that does not make that exception rejects it, and the route's own OpenAPI text and
the test next to it (``tests/test_system_metrics_prometheus_r186.py``) both name the value
without the repeat.  The fix is the one Werkzeug documents: a ``mimetype`` is the bare type
(``text/markdown``, the charset is added), a header that carries parameters is a ``content_type``
(used as it stands).

What the tests pin:

* the two routes answer with ``text/plain; version=0.0.4; charset=utf-8`` and
  ``text/markdown; charset=utf-8``, and what they answer with is unchanged otherwise;
* every ``GET`` route of the Web UI, asked with and without ``Accept-Encoding: gzip``, for a file
  that exists and for one that does not, answers with a ``Content-Type`` in which no parameter
  is named twice, and the sweep is held to reach every ``GET`` route, a real file and a miss on
  every file route, and both answers of the export route (a sweep that stops short fails the
  test instead of passing it);
* a static rule over the package so the next route cannot do the same: no ``mimetype=`` or
  ``content_type=`` literal produces such a header.  The rule asks Werkzeug what header a
  ``mimetype`` literal becomes, so ``application/javascript; charset=utf-8`` (which Werkzeug leaves
  alone) is not reported and ``text/markdown; charset=utf-8`` (which it does not) is; the checker's
  own cases below show both.
"""

from __future__ import annotations

import ast
from collections.abc import Iterator
from pathlib import Path

import pytest
from flask.testing import FlaskClient
from werkzeug.utils import get_content_type

from ai_intervention_agent.task_queue_singleton import get_task_queue
from ai_intervention_agent.web_ui import WebFeedbackUI

PACKAGE = Path(__file__).resolve().parent.parent / "src" / "ai_intervention_agent"
LOOPBACK = {"REMOTE_ADDR": "127.0.0.1"}
TASK_ID = "r861-task"
# ``br`` and ``zstd`` on a file response go through Flask-Compress's streaming path, which
# leaves the file for the garbage collector to close (a ``ResourceWarning``, an error under
# ``filterwarnings = error``).  The header read here is the route's own and does not depend on
# the encoding, so the sweep asks without one and with ``gzip``.
ENCODINGS = ("", "gzip")
FILE_ROUTES = {
    "/static/css/": "static/css",
    "/static/js/": "static/js",
    "/static/locales/": "static/locales",
    "/static/lottie/": "static/lottie",
    "/icons/": "icons",
    "/sounds/": "sounds",
    "/fonts/": "fonts",
}


@pytest.fixture(scope="module")
def ui() -> WebFeedbackUI:
    instance = WebFeedbackUI(
        prompt="r861", task_id="r861-ui", auto_resubmit_timeout=0, port=19863
    )
    instance.app.config["TESTING"] = True
    instance.limiter.enabled = False
    object.__setattr__(instance, "shutdown_server", lambda: None)
    return instance


@pytest.fixture
def client(ui: WebFeedbackUI) -> Iterator[FlaskClient]:
    queue = get_task_queue()
    queue.clear_all_tasks()
    assert queue.add_task(task_id=TASK_ID, prompt="r861", auto_resubmit_timeout=0)
    try:
        yield ui.app.test_client()
    finally:
        queue.clear_all_tasks()


def parameter_names(content_type: str) -> list[str]:
    return [
        part.split("=", 1)[0].strip().lower()
        for part in content_type.split(";")[1:]
        if part.strip()
    ]


def repeated_parameters(content_type: str) -> list[str]:
    names = parameter_names(content_type)
    return sorted({name for name in names if names.count(name) > 1})


# --------------------------------------------------------------------------- the two routes


class TestTheTwoRoutes:
    def test_metrics_answers_with_the_header_prometheus_clients_send(
        self, client: FlaskClient
    ) -> None:
        resp = client.get("/api/system/metrics", environ_base=LOOPBACK)
        assert resp.status_code == 200
        assert (
            resp.headers["Content-Type"] == "text/plain; version=0.0.4; charset=utf-8"
        )
        assert resp.mimetype == "text/plain"
        assert resp.mimetype_params == {"version": "0.0.4", "charset": "utf-8"}

    def test_metrics_body_is_still_the_exposition_text(
        self, client: FlaskClient
    ) -> None:
        resp = client.get("/api/system/metrics", environ_base=LOOPBACK)
        body = resp.get_data(as_text=True)
        assert body.startswith("# HELP ")
        assert "aiia_uptime_seconds" in body
        assert body.endswith("\n")

    @pytest.mark.parametrize("name", ["markdown", "MARKDOWN", "Markdown"])
    def test_markdown_export_names_the_charset_once(
        self, client: FlaskClient, name: str
    ) -> None:
        resp = client.get(f"/api/tasks/export?format={name}", environ_base=LOOPBACK)
        assert resp.status_code == 200
        assert resp.headers["Content-Type"] == "text/markdown; charset=utf-8"
        assert resp.mimetype == "text/markdown"
        assert resp.mimetype_params == {"charset": "utf-8"}

    def test_markdown_export_is_otherwise_unchanged(self, client: FlaskClient) -> None:
        resp = client.get("/api/tasks/export?format=markdown", environ_base=LOOPBACK)
        disposition = resp.headers["Content-Disposition"]
        assert disposition.startswith('attachment; filename="')
        assert disposition.endswith('.md"')
        body = resp.get_data(as_text=True)
        assert f"`{TASK_ID}`" in body
        assert body.endswith("\n")

    def test_json_export_still_answers_json(self, client: FlaskClient) -> None:
        resp = client.get("/api/tasks/export", environ_base=LOOPBACK)
        assert resp.status_code == 200
        assert resp.headers["Content-Type"] == "application/json"
        assert resp.headers["Content-Disposition"].endswith('.json"')


# --------------------------------------------------------------------------- every route


def _real_files(directory: str) -> list[str]:
    """One file per extension of ``directory`` (the first by name), no precompressed copies."""
    folder = PACKAGE / directory
    if not folder.is_dir():
        return []
    chosen: dict[str, str] = {}
    for entry in sorted(folder.iterdir()):
        if entry.is_file() and entry.suffix not in {".br", ".gz"}:
            chosen.setdefault(entry.suffix, entry.name)
    return sorted(chosen.values())


def sweep_urls(ui: WebFeedbackUI) -> dict[str, list[str]]:
    """Every URL to ask, grouped by the rule it exercises (``GET`` rules only)."""
    urls: dict[str, list[str]] = {}
    for rule in ui.app.url_map.iter_rules():
        if "GET" not in (rule.methods or ()) or rule.rule == "/api/events":
            continue
        found: list[str] = []
        if rule.rule == "/static/<path:filename>":
            found = ["/static/css/main.css", "/static/nothing/at/all.css"]
        elif "<filename>" in rule.rule:
            prefix = rule.rule.removesuffix("<filename>")
            directory = FILE_ROUTES[prefix]
            found = [prefix + name for name in _real_files(directory)]
            found.append(prefix + "missing.bin")
        else:
            found = [
                rule.rule.replace("<task_id>", TASK_ID).replace("<int:index>", "0")
            ]
        urls[rule.rule] = found
    urls["/api/tasks/export"] = [
        "/api/tasks/export",
        "/api/tasks/export?format=markdown",
        "/api/tasks/export?format=nonsense",
    ]
    return urls


class TestEveryRoute:
    def test_the_sweep_asks_every_get_route_and_is_not_empty(
        self, ui: WebFeedbackUI
    ) -> None:
        urls = sweep_urls(ui)
        get_rules = {
            rule.rule
            for rule in ui.app.url_map.iter_rules()
            if "GET" in (rule.methods or ()) and rule.rule != "/api/events"
        }
        assert set(urls) == get_rules
        assert all(urls[rule] for rule in get_rules)
        asked = [url for group in urls.values() for url in group]
        assert len(asked) >= 40
        assert "/api/system/metrics" in asked
        assert "/api/tasks/export?format=markdown" in asked

    def test_no_route_names_a_parameter_of_its_content_type_twice(
        self, ui: WebFeedbackUI, client: FlaskClient
    ) -> None:
        offenders: list[str] = []
        statuses: dict[str, set[int]] = {}
        seen: set[str] = set()
        for rule, group in sweep_urls(ui).items():
            for url in group:
                for encoding in ENCODINGS:
                    headers = {"Accept-Encoding": encoding} if encoding else {}
                    with client.get(
                        url, environ_base=LOOPBACK, headers=headers
                    ) as resp:
                        content_type = resp.headers.get("Content-Type", "")
                        status = resp.status_code
                    statuses.setdefault(rule, set()).add(status)
                    seen.add(content_type)
                    if repeated_parameters(content_type):
                        offenders.append(
                            f"{url} [{encoding or '-'}] {status} {content_type}"
                        )
        assert offenders == []
        # a sweep that read no header would find no offender: it did see what the routes send
        assert {
            "application/json",
            "text/markdown; charset=utf-8",
            "text/plain; version=0.0.4; charset=utf-8",
        } <= seen
        for prefix, directory in FILE_ROUTES.items():
            answered = statuses[f"{prefix}<filename>"]
            assert 404 in answered, prefix
            assert (200 in answered) == bool(_real_files(directory)), prefix
        assert statuses["/api/tasks/export"] == {200, 400}

    def test_repeated_parameters_names_what_it_finds(self, client: FlaskClient) -> None:
        resp = client.get("/api/system/health", environ_base=LOOPBACK)
        assert resp.headers["Content-Type"] == "application/json"
        assert repeated_parameters(resp.headers["Content-Type"]) == []
        assert repeated_parameters("text/plain; charset=utf-8; charset=utf-8") == [
            "charset"
        ]
        assert repeated_parameters("text/plain; Charset=utf-8; charset=UTF-8") == [
            "charset"
        ]
        assert repeated_parameters("text/plain; version=0.0.4; charset=utf-8") == []
        assert repeated_parameters("application/json") == []


# --------------------------------------------------------------------------- the source


def _literal(node: ast.expr) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        return "".join(
            part.value
            if isinstance(part, ast.Constant) and isinstance(part.value, str)
            else "x"
            for part in node.values
        )
    return None


def repeating_literals(source: str) -> list[tuple[int, str]]:
    """The ``(line, header)`` of every call whose ``mimetype=`` / ``content_type=`` literal
    becomes a ``Content-Type`` that names a parameter twice."""
    found: list[tuple[int, str]] = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call):
            continue
        for keyword in node.keywords:
            literal = _literal(keyword.value)
            if literal is None:
                continue
            if keyword.arg == "mimetype":
                header = get_content_type(literal, "utf-8")
            elif keyword.arg == "content_type":
                header = literal
            else:
                continue
            if repeated_parameters(header):
                found.append((node.lineno, header))
    return found


def _package_sources() -> list[Path]:
    return sorted(PACKAGE.rglob("*.py"))


class TestTheSource:
    def test_the_package_has_sources_to_read(self) -> None:
        sources = _package_sources()
        assert len(sources) >= 40
        assert PACKAGE / "web_ui_routes" / "system.py" in sources
        assert PACKAGE / "web_ui_routes" / "task.py" in sources

    def test_no_literal_makes_a_header_repeat_a_parameter(self) -> None:
        found = {
            f"{path.relative_to(PACKAGE)}:{line}": header
            for path in _package_sources()
            for line, header in repeating_literals(path.read_text(encoding="utf-8"))
        }
        assert found == {}

    @pytest.mark.parametrize(
        ("snippet", "header"),
        [
            (
                'Response(x, mimetype="text/plain; version=0.0.4; charset=utf-8")',
                "text/plain; version=0.0.4; charset=utf-8; charset=utf-8",
            ),
            (
                'Response(x, mimetype="text/markdown; charset=utf-8")',
                "text/markdown; charset=utf-8; charset=utf-8",
            ),
            (
                'send_from_directory(d, f, mimetype="text/css; charset=utf-8")',
                "text/css; charset=utf-8; charset=utf-8",
            ),
            (
                'Response(x, mimetype=f"text/{kind}; charset=utf-8")',
                "text/x; charset=utf-8; charset=utf-8",
            ),
            (
                'Response(x, content_type="text/plain; charset=utf-8; charset=utf-8")',
                "text/plain; charset=utf-8; charset=utf-8",
            ),
            (
                'Response(x, mimetype="text/plain; Charset=UTF-8")',
                "text/plain; Charset=UTF-8; charset=utf-8",
            ),
        ],
    )
    def test_checker_reports_a_literal_that_repeats_a_parameter(
        self, snippet: str, header: str
    ) -> None:
        assert repeating_literals(snippet) == [(1, header)]

    @pytest.mark.parametrize(
        "snippet",
        [
            'Response(x, mimetype="text/markdown")',
            'Response(x, mimetype="application/json")',
            'Response(x, mimetype="application/javascript; charset=utf-8")',
            'Response(x, mimetype="application/atom+xml; charset=utf-8")',
            'Response(x, content_type="text/plain; version=0.0.4; charset=utf-8")',
            'Response(x, mimetype="text/event-stream")',
            "Response(x, mimetype=kind)",
            'Response(x, headers={"Content-Type": "text/plain"})',
        ],
    )
    def test_checker_leaves_a_literal_that_is_fine(self, snippet: str) -> None:
        assert repeating_literals(snippet) == []
