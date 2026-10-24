"""R864: no response of the Web UI sets a hop-by-hop header, so a strict WSGI server can serve it.

PEP 3333 forbids a WSGI application to set a hop-by-hop header (``Connection``, ``Keep-Alive``,
``Proxy-Authenticate``, ``Proxy-Authorization``, ``TE``, ``Trailers``, ``Transfer-Encoding``,
``Upgrade``): the server owns them.  Servers differ in how much they care.  Gunicorn drops the
header, Werkzeug's development server (the default ``WebFeedbackUI.run()`` path) sends it and then
sends its own, and Waitress, the server ``docs/deployment.md`` recommends for Windows and for
simple deployments, raises from ``start_response``::

    AssertionError: Connection is a "hop-by-hop" header; it cannot be used by a WSGI
    application (see PEP 3333)

``GET /api/events``, the stream the page and the VS Code extension listen to, built its response
with ``"Connection": "keep-alive"``.  Under Waitress every request for it was therefore a ``500``
(a traceback in the log, no live update ever arrived); on the development server the answer named
``Connection`` twice, ``keep-alive`` and then the server's own ``close``.  Nothing noticed: no test
ran a server that enforces PEP 3333 (``test_web_ui_wsgi_profile_r452`` reads text and docs), a stream
that never ends does not fit a request/response sweep, and ``wsgiref.validate`` does not look at
hop-by-hop headers.

What the tests pin:

* the stream answers with ``Cache-Control: no-cache`` and ``X-Accel-Buffering: no`` and no
  hop-by-hop header;
* ``wsgiref``'s own server handler, which makes the check Waitress makes, serves the stream (a
  ``200``, ``text/event-stream``, the first frame, a task event written to it, and nothing on
  the error stream) and ends it cleanly;
* no response of any route carries a hop-by-hop header: every ``GET`` route (the stream read for
  its first frame so that it can be closed), the paths no route matches, every method each
  ``/api/`` route refuses, and ``OPTIONS`` on every route, with the sweep held to reach each of
  them;
* a static rule over the package so the next route cannot do the same: no ``headers=`` literal,
  assignment to a ``headers`` mapping, ``headers.add`` / ``set`` / ``setdefault`` call or
  ``return body, status, {...}`` tuple names a hop-by-hop header.  A route that has to write one
  anyway (a header of an *outgoing* request, say) is listed in ``OUTGOING`` with its reason; the
  checker's own cases are below.
"""

from __future__ import annotations

import ast
import io
import re
import threading
import time
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from pathlib import Path
from wsgiref.handlers import SimpleHandler
from wsgiref.util import is_hop_by_hop

import pytest
from flask.testing import FlaskClient
from werkzeug.exceptions import HTTPException, MethodNotAllowed
from werkzeug.test import EnvironBuilder

from ai_intervention_agent.web_ui import WebFeedbackUI
from ai_intervention_agent.web_ui_routes import task as task_routes

PACKAGE = Path(__file__).resolve().parent.parent / "src" / "ai_intervention_agent"
LOOPBACK = {"REMOTE_ADDR": "127.0.0.1"}
STREAM = "/api/events"
# Paths no rule matches: ``handle_404`` answers them, in JSON under ``/api/`` and ``/metrics`` and
# with a page elsewhere.
UNMATCHED = ("/api/nothing", "/metrics", "/nothing-here")
# Where a hop-by-hop name is a header of an *outgoing* request, which the rule cannot tell from a
# response header.  ``{"path/inside/the/package.py": "why"}``; empty: nothing writes one.
OUTGOING: dict[str, str] = {}
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
        prompt="r864", task_id="r864-ui", auto_resubmit_timeout=0, port=19865
    )
    instance.app.config["TESTING"] = True
    instance.limiter.enabled = False
    object.__setattr__(instance, "shutdown_server", lambda: None)
    return instance


@pytest.fixture
def client(ui: WebFeedbackUI) -> FlaskClient:
    return ui.app.test_client()


def hop_by_hop(headers: Iterable[tuple[str, str]]) -> list[str]:
    """The names among ``headers`` a WSGI application may not set."""
    return sorted({name for name, _value in headers if is_hop_by_hop(name)})


# ------------------------------------------------------------- a server that enforces PEP 3333


class Stream:
    """``path`` served by ``wsgiref``'s server handler on a thread of its own.

    ``BaseHandler.start_response`` asserts ``not is_hop_by_hop(name)``, the rule Waitress
    enforces; a response it refuses is answered with a ``500`` and a traceback on ``errors``.
    The stream never ends by itself, so ``end()`` hands the sentinel the bus uses to disconnect a
    slow client to every subscriber, which is what makes the generator return.
    """

    def __init__(self, ui: WebFeedbackUI, path: str) -> None:
        environ = EnvironBuilder(path=path).get_environ()
        environ.update(LOOPBACK)
        self._out = io.BytesIO()
        self._errors = io.StringIO()
        handler = SimpleHandler(
            io.BytesIO(), self._out, self._errors, environ, multithread=True
        )
        self._thread = threading.Thread(
            target=handler.run, args=(ui.app,), name="r864-wsgiref", daemon=True
        )
        self._thread.start()

    def wait_for(self, needle: bytes, timeout: float = 5.0) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if needle in self._out.getvalue():
                return True
            if not self._thread.is_alive():
                return needle in self._out.getvalue()
            time.sleep(0.01)
        return False

    def subscribers(self) -> list[task_routes.queue.Queue]:
        return list(task_routes._sse_bus._subscribers)

    def end(self) -> None:
        for subscriber in self.subscribers():
            subscriber.put_nowait(task_routes._SSE_DISCONNECT_SENTINEL)
        self._thread.join(5)
        assert not self._thread.is_alive(), "the handler did not end with the stream"

    @property
    def status_line(self) -> str:
        return self._out.getvalue().split(b"\r\n", 1)[0].decode("iso-8859-1")

    @property
    def headers(self) -> list[tuple[str, str]]:
        head = self._out.getvalue().partition(b"\r\n\r\n")[0].decode("iso-8859-1")
        lines = head.split("\r\n")[1:]
        return [
            (name, value) for name, _sep, value in (x.partition(": ") for x in lines)
        ]

    @property
    def body(self) -> bytes:
        return self._out.getvalue().partition(b"\r\n\r\n")[2]

    @property
    def errors(self) -> str:
        return self._errors.getvalue()


@contextmanager
def served(ui: WebFeedbackUI, path: str) -> Iterator[Stream]:
    stream = Stream(ui, path)
    try:
        yield stream
    finally:
        stream.end()


class TestTheStream:
    def test_the_answer_names_no_hop_by_hop_header(self, client: FlaskClient) -> None:
        with client.get(STREAM, environ_base=LOOPBACK) as resp:
            next(iter(resp.response))
            assert resp.status_code == 200
            assert resp.headers["Content-Type"] == "text/event-stream; charset=utf-8"
            assert resp.headers["Cache-Control"] == "no-cache"
            assert resp.headers["X-Accel-Buffering"] == "no"
            assert hop_by_hop(resp.headers) == []

    def test_a_server_that_enforces_pep_3333_serves_it(self, ui: WebFeedbackUI) -> None:
        with served(ui, STREAM) as stream:
            assert stream.wait_for(b": connected"), (stream.status_line, stream.errors)
            assert stream.status_line.endswith(" 200 OK"), stream.status_line
            assert dict(stream.headers)["Content-Type"] == (
                "text/event-stream; charset=utf-8"
            )
            assert hop_by_hop(stream.headers) == []
            assert stream.body.startswith(b": connected\n\n")
        assert stream.errors == ""

    def test_what_happens_on_the_bus_reaches_the_client_of_that_server(
        self, ui: WebFeedbackUI
    ) -> None:
        event = {
            "id": 1,
            "type": "task_changed",
            "data": {"task_id": "r864"},
            "_serialized": '{"task_id": "r864"}',
        }
        with served(ui, STREAM) as stream:
            assert stream.wait_for(b": connected"), stream.errors
            (subscriber,) = stream.subscribers()
            subscriber.put_nowait(event)
            assert stream.wait_for(b"event: task_changed\n"), stream.errors
            assert b'data: {"task_id": "r864"}\n\n' in stream.body
        assert stream.errors == ""

    def test_the_stream_leaves_no_subscriber_behind(self, ui: WebFeedbackUI) -> None:
        before = task_routes._sse_bus.subscriber_count
        with served(ui, STREAM) as stream:
            assert stream.wait_for(b": connected"), stream.errors
            assert task_routes._sse_bus.subscriber_count == before + 1
        assert task_routes._sse_bus.subscriber_count == before


# ---------------------------------------------------------------------------- every response


def url_for_rule(rule: str) -> str:
    return re.sub(
        r"<[^>]+>", lambda m: "0" if m.group(0).startswith("<int:") else "x", rule
    )


def real_file(directory: str) -> str:
    folder = PACKAGE / directory
    for entry in sorted(folder.iterdir()) if folder.is_dir() else ():
        if entry.is_file() and entry.suffix not in {".br", ".gz"}:
            return entry.name
    return "missing.bin"


def concrete_url(rule: str) -> str:
    """A URL the rule matches: a real file for a file route, ``x`` / ``0`` for other parameters."""
    if rule == "/static/<path:filename>":
        return "/static/css/main.css"
    if "<filename>" in rule:
        prefix = rule.removesuffix("<filename>")
        return prefix + real_file(FILE_ROUTES[prefix])
    return url_for_rule(rule)


def get_urls(ui: WebFeedbackUI) -> dict[str, list[str]]:
    """Every URL to ask with ``GET``, by the rule it exercises, the stream included.

    A file route is asked for a file that exists and for one that does not.
    """
    urls: dict[str, list[str]] = {}
    for rule in ui.app.url_map.iter_rules():
        if "GET" not in (rule.methods or ()):
            continue
        found = [concrete_url(rule.rule)]
        if "<path:filename>" in rule.rule:
            found.append("/static/nothing/at/all.css")
        elif "<filename>" in rule.rule:
            found.append(rule.rule.removesuffix("<filename>") + "missing.bin")
        urls[rule.rule] = found
    return urls


def swept_get_urls(ui: WebFeedbackUI) -> list[str]:
    """Every URL the ``GET`` sweep asks: the ones of ``get_urls`` and the paths no rule matches."""
    return [*(url for group in get_urls(ui).values() for url in group), *UNMATCHED]


def wrong_method_requests(ui: WebFeedbackUI) -> set[tuple[str, str]]:
    """``(method, url)`` for every method an ``/api/`` URL is refused with by the URL map itself.

    Asked of the map, so a method that another rule of the same path serves is not sent (that
    would run a handler).
    """
    adapter = ui.app.url_map.bind("localhost")
    found: set[tuple[str, str]] = set()
    for rule in ui.app.url_map.iter_rules():
        if not rule.rule.startswith("/api/"):
            continue
        url = url_for_rule(rule.rule)
        for method in ("GET", "POST", "PUT", "PATCH", "DELETE"):
            try:
                adapter.match(url, method=method)
            except MethodNotAllowed:
                found.add((method, url))
            except HTTPException:
                continue
    return found


def option_urls(ui: WebFeedbackUI) -> set[str]:
    """One URL per rule: ``OPTIONS`` is answered by Flask for every rule, handler or not."""
    return {concrete_url(rule.rule) for rule in ui.app.url_map.iter_rules()}


def answer_headers(client: FlaskClient, method: str, url: str) -> list[tuple[str, str]]:
    """The headers of the answer; the stream is read for its first frame so it can be closed."""
    with client.open(url, method=method, environ_base=LOOPBACK) as resp:
        if url == STREAM and method == "GET":
            next(iter(resp.response))
        return list(resp.headers)


class TestEveryResponse:
    def test_the_sweep_reaches_every_route_and_is_not_small(
        self, ui: WebFeedbackUI, client: FlaskClient
    ) -> None:
        urls = get_urls(ui)
        get_rules = {
            rule.rule
            for rule in ui.app.url_map.iter_rules()
            if "GET" in (rule.methods or ())
        }
        assert set(urls) == get_rules
        assert STREAM in urls[STREAM]
        assert len([url for group in urls.values() for url in group]) >= 40
        assert set(UNMATCHED) <= set(swept_get_urls(ui))
        for url in UNMATCHED:
            assert client.get(url).status_code == 404, url
        refused = wrong_method_requests(ui)
        assert len(refused) >= 100
        assert ("GET", "/api/submit") in refused
        assert len(option_urls(ui)) >= 50

    def test_no_get_answer_names_a_hop_by_hop_header(
        self, ui: WebFeedbackUI, client: FlaskClient
    ) -> None:
        offenders = {
            url: hop_by_hop(answer_headers(client, "GET", url))
            for url in swept_get_urls(ui)
        }
        assert {url: names for url, names in offenders.items() if names} == {}

    def test_no_refusal_of_a_method_names_one(
        self, ui: WebFeedbackUI, client: FlaskClient
    ) -> None:
        offenders = {
            f"{method} {url}": hop_by_hop(answer_headers(client, method, url))
            for method, url in sorted(wrong_method_requests(ui))
        }
        assert {key: names for key, names in offenders.items() if names} == {}

    def test_no_answer_to_options_names_one(
        self, ui: WebFeedbackUI, client: FlaskClient
    ) -> None:
        offenders = {
            url: hop_by_hop(answer_headers(client, "OPTIONS", url))
            for url in sorted(option_urls(ui))
        }
        assert {url: names for url, names in offenders.items() if names} == {}

    def test_the_stream_is_the_one_answer_the_others_could_not_stand_in_for(
        self, client: FlaskClient
    ) -> None:
        """The stream is part of the sweep above and answers like the stream it is."""
        headers = answer_headers(client, "GET", STREAM)
        assert dict(headers)["Content-Type"] == "text/event-stream; charset=utf-8"


# ------------------------------------------------------------------------------ the source


def text_of(node: ast.AST | None) -> str | None:
    """The string a constant node holds; ``None`` for anything else."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def literal_names(node: ast.AST) -> Iterator[str]:
    """The names a ``{...}`` or ``[(name, value), ...]`` literal gives to headers."""
    if isinstance(node, ast.Dict):
        for key in node.keys:
            if (name := text_of(key)) is not None:
                yield name
    elif isinstance(node, ast.List | ast.Tuple):
        for item in node.elts:
            if (
                isinstance(item, ast.List | ast.Tuple)
                and item.elts
                and (name := text_of(item.elts[0])) is not None
            ):
                yield name


def is_headers(node: ast.AST) -> bool:
    if isinstance(node, ast.Attribute):
        return "headers" in node.attr.lower()
    if isinstance(node, ast.Name):
        return "headers" in node.id.lower()
    return False


def header_names_written(tree: ast.AST) -> Iterator[str]:
    """Every name given to a header being written (a read such as ``headers.get`` is not)."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            for keyword in node.keywords:
                if keyword.arg == "headers":
                    yield from literal_names(keyword.value)
            func = node.func
            if (
                isinstance(func, ast.Attribute)
                and func.attr in {"add", "set", "setdefault", "add_header"}
                and is_headers(func.value)
                and node.args
                and (name := text_of(node.args[0])) is not None
            ):
                yield name
        elif (
            isinstance(node, ast.Return)
            and isinstance(node.value, ast.Tuple)
            and len(node.value.elts) == 3
        ):
            # Flask's ``return body, status, {"Name": "value"}``
            yield from literal_names(node.value.elts[2])
        elif isinstance(node, ast.Assign | ast.AnnAssign | ast.AugAssign):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if isinstance(target, ast.Subscript) and is_headers(target.value):
                    if (name := text_of(target.slice)) is not None:
                        yield name
                elif is_headers(target) and node.value is not None:
                    yield from literal_names(node.value)


def hop_by_hop_literals(source: str) -> list[str]:
    return sorted(
        {
            name
            for name in header_names_written(ast.parse(source))
            if is_hop_by_hop(name)
        }
    )


def package_sources() -> list[Path]:
    return sorted(PACKAGE.rglob("*.py"))


class TestTheSource:
    def test_the_rule_reads_every_module_of_the_package(self) -> None:
        sources = package_sources()
        assert len(sources) >= 40
        assert PACKAGE / "web_ui_routes" / "task.py" in sources

    def test_no_module_writes_a_hop_by_hop_header(self) -> None:
        offenders: dict[str, list[str]] = {}
        for path in package_sources():
            relative = path.relative_to(PACKAGE).as_posix()
            if relative in OUTGOING:
                continue
            names = hop_by_hop_literals(path.read_text(encoding="utf-8"))
            if names:
                offenders[relative] = names
        assert offenders == {}, (
            "a WSGI application must not set these (PEP 3333, and Waitress raises); "
            "a header of an outgoing request goes in OUTGOING with its reason"
        )

    def test_the_exceptions_are_real_files_that_still_need_them(self) -> None:
        for relative in OUTGOING:
            path = PACKAGE / relative
            assert path.is_file(), relative
            assert hop_by_hop_literals(path.read_text(encoding="utf-8")), relative

    @pytest.mark.parametrize(
        ("source", "names"),
        [
            ('Response(b"", headers={"Connection": "keep-alive"})', ["Connection"]),
            (
                'Response(b"", headers=[("Transfer-Encoding", "chunked")])',
                ["Transfer-Encoding"],
            ),
            ('resp.headers["Upgrade"] = "h2c"', ["Upgrade"]),
            (
                'response.headers.add("Proxy-Authenticate", "Basic")',
                ["Proxy-Authenticate"],
            ),
            ('response.headers.set("keep-alive", "timeout=5")', ["keep-alive"]),
            ('headers = {"TE": "trailers", "X-Fine": "1"}', ["TE"]),
            ('self.response_headers = [("Trailers", "x")]', ["Trailers"]),
            (
                'rv.headers.setdefault("Proxy-Authorization", "x")',
                ["Proxy-Authorization"],
            ),
            ('return jsonify({}), 200, {"Connection": "close"}', ["Connection"]),
            ('return body, 200, [("Upgrade", "h2c")]', ["Upgrade"]),
        ],
    )
    def test_the_rule_reports_what_it_should(
        self, source: str, names: list[str]
    ) -> None:
        assert hop_by_hop_literals(source) == sorted(names)

    @pytest.mark.parametrize(
        "source",
        [
            'Response(b"", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})',
            'resp.headers["Content-Type"] = "text/plain"',
            'request.headers.get("Connection")',
            'if "upgrade" in request.headers.get("Connection", ""): pass',
            'TRANSITIONS = {"connection": {"idle": ("open",)}}',
            'headers = {"Vary": "Origin"}',
            'headers_seen = ["Connection"]',
            'return jsonify({}), 200, {"Cache-Control": "no-store"}',
            'return jsonify({"connection": "closed"}), 200',
            'return state, "connection"',
        ],
    )
    def test_the_rule_leaves_alone_what_is_not_a_header_being_written(
        self, source: str
    ) -> None:
        assert hop_by_hop_literals(source) == []
