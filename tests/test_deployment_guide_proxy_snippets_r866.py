"""R866: what the deployment guides tell the proxy and the server to do gives the Web UI the visitor's address.

Behind a reverse proxy on the same machine (the setup ``docs/deployment.md`` describes) every
connection reaches the Web UI from 127.0.0.1, so the access control, the rate limiter and the
routes only this machine may call tell visitors apart by the ``X-Forwarded-For`` header the proxy
writes (R849, R850).  Two things the guides said left that header out, and nothing noticed: no
test ran a proxy or a production server, and the guides are text.

* The nginx block for ``/api/events``, the stream, set ``Connection`` and nothing else.  nginx does
  not carry the ``proxy_set_header`` lines of the block around a ``location`` into one that sets its
  own, so the stream reached the Web UI without a client address and its every visitor was judged as
  ``127.0.0.1``.  Measured with nginx 1.31 in front of Waitress 3.0.2, Waitress with its trust flags,
  gunicorn 26.2 with gevent and Flask's own server (containers, the guide's snippets as they were):
  a visitor on ``blocked_ips`` was answered ``403`` on every route but the stream, which answered
  ``200`` and ``: connected``.
* Waitress, run as ``waitress-serve --listen=127.0.0.1:8080 ...`` in the guides, removes
  ``X-Forwarded-For`` (and ``-Host``, ``-Proto``, ``-Port``, ``Forwarded``) from every request
  unless it is given ``--trusted-proxy`` (``clear_untrusted_proxy_headers`` has defaulted to true
  since Waitress 3.0).  Behind nginx every visitor was therefore this machine: a request from another
  machine got ``200`` from ``GET /api/system/api-token-info`` and a visitor on ``blocked_ips`` got
  ``200`` everywhere.  Gunicorn and Flask's server leave the header alone; Waitress with
  ``--trusted-proxy=127.0.0.1 --trusted-proxy-headers=x-forwarded-for --trusted-proxy-count=1``
  puts the visitor's address into ``REMOTE_ADDR`` itself.

The guides now write the header in the stream's block, tell Waitress which proxy to trust and add
two lines to the validation checklist that ask from another machine.  With those snippets all four
servers answered that visitor ``403`` everywhere, the stream included; an allowed visitor got
``: connected`` within a hundredth of a second (the line does not make nginx buffer it); you,
browsing from the server itself through nginx, were still this machine; and a CDN in front of nginx
(two hops) was judged by the address the CDN wrote.

What the tests pin:

* the nginx snippets of both guides (read as nginx reads them, comments aside): the stream and the
  rest are the two locations that reach the Web UI, each writes ``X-Forwarded-For`` once, as the
  address nginx saw (alone or after what the previous proxy sent), never as the header the visitor
  sent; the two guides show the same configuration; the rule's own cases;
* the Waitress command of both guides that names a trusted proxy: the loopback address, the header,
  and as many proxies as ``trusted_proxy_hops`` has by default; the two guides give the same one;
* the validation checklist of both guides asks ``/api/system/api-token-info`` and ``/api/events``
  through the proxy;
* what those lines rest on, with the real routes behind the real hooks: a table of visitors (what
  nginx writes for a blocked one, an allowed one and you; a header that is missing; a CDN at two
  hops and at one; a visitor who writes 127.0.0.1 in front of the chain; no proxy at all) against
  ``api-token-info``, ``/api/health`` and the stream, and every ``GET`` route refusing the visitor
  the proxy named, the stream included and without subscribing to anything.
"""

from __future__ import annotations

import re
import shlex
from pathlib import Path
from typing import Any, NamedTuple

import pytest

from ai_intervention_agent import web_ui_validators as validators
from ai_intervention_agent.web_ui import WebFeedbackUI
from ai_intervention_agent.web_ui_routes import task as task_routes

REPO = Path(__file__).resolve().parents[1]
GUIDES = {
    "en": REPO / "docs" / "deployment.md",
    "zh": REPO / "docs" / "deployment.zh-CN.md",
}
CHECKLIST = {"en": "Validation Checklist", "zh": "验证清单"}
UPSTREAM = "http://127.0.0.1:8080"
STREAM = "/api/events"
HEALTH = "/api/health"
TOKEN_INFO = "/api/system/api-token-info"
# What ``proxy_set_header X-Forwarded-For`` may be: the address nginx saw, alone or appended to what
# the previous proxy sent.  The header the visitor sent (``$http_x_forwarded_for``) is theirs to write.
VISITOR_ADDRESS = {"$remote_addr", "$proxy_add_x_forwarded_for"}

# ------------------------------------------------------------------- reading the guides


class Location(NamedTuple):
    path: str
    directives: tuple[tuple[str, str], ...]


def read(guide: str) -> str:
    return GUIDES[guide].read_text(encoding="utf-8")


def fenced(text: str, language: str) -> list[str]:
    """The bodies of the code blocks written in ``language``."""
    blocks = re.finditer(r"^```(\w*)\n(.*?)^```$", text, re.DOTALL | re.MULTILINE)
    return [block[2] for block in blocks if block[1] == language]


def active_lines(block: str) -> list[str]:
    """The lines of a code block without comments (``#`` starts one in nginx and in a shell)."""
    stripped = (line.split("#", 1)[0].strip() for line in block.splitlines())
    return [line for line in stripped if line]


def locations_in(block: str) -> list[Location]:
    """The ``location`` blocks of an nginx snippet and the directives each one holds."""
    code = "\n".join(active_lines(block))
    found = []
    for match in re.finditer(r"location\s+(\S+)\s*\{([^{}]*)\}", code):
        statements = [
            part.split(None, 1) for part in match[2].split(";") if part.strip()
        ]
        directives = tuple(
            (words[0], words[1].strip() if len(words) > 1 else "")
            for words in statements
        )
        found.append(Location(match[1], directives))
    return found


def nginx_locations(guide: str) -> list[Location]:
    return [
        location
        for block in fenced(read(guide), "nginx")
        for location in locations_in(block)
    ]


def reaches_the_web_ui(location: Location) -> bool:
    return ("proxy_pass", UPSTREAM) in location.directives


def names_the_visitor(location: Location) -> bool:
    """Exactly one ``X-Forwarded-For``, and it is an address nginx saw."""
    values = [
        value.split(None, 1)[1].strip()
        for name, value in location.directives
        if name == "proxy_set_header" and value.lower().startswith("x-forwarded-for ")
    ]
    return len(values) == 1 and values[0] in VISITOR_ADDRESS


def options_of(command: str) -> dict[str, str]:
    """``--name=value`` and ``--name value`` of a shell command line, as ``{name: value}``."""
    words = shlex.split(command)
    options: dict[str, str] = {}
    for position, word in enumerate(words):
        if not word.startswith("--"):
            continue
        name, equals, value = word.partition("=")
        following = words[position + 1] if position + 1 < len(words) else ""
        if not equals and following and not following.startswith("--"):
            value = following
        options[name] = value
    return options


def waitress_commands(guide: str) -> list[dict[str, str]]:
    """The options of every ``waitress-serve`` command in the guide's shell blocks."""
    commands = []
    for block in fenced(read(guide), "bash"):
        code = re.sub(r"\\\n", " ", "\n".join(active_lines(block)))
        commands.extend(
            options_of(line)
            for line in code.splitlines()
            if line.startswith("waitress-serve ")
        )
    return commands


def checklist(guide: str) -> str:
    text = read(guide)
    heading = re.search(rf"^## {CHECKLIST[guide]}$", text, re.MULTILINE)
    assert heading, f"{guide}: no {CHECKLIST[guide]!r} heading"
    rest = text[heading.end() :]
    following = re.search(r"^## ", rest, re.MULTILINE)
    return rest[: following.start()] if following else rest


# ------------------------------------------------------------------- the nginx snippets


class TestTheNginxSnippets:
    @pytest.mark.parametrize("guide", GUIDES)
    def test_the_stream_and_the_rest_are_what_reaches_the_web_ui(
        self, guide: str
    ) -> None:
        paths = [
            location.path
            for location in nginx_locations(guide)
            if reaches_the_web_ui(location)
        ]
        assert sorted(paths) == sorted([STREAM, "/"])

    @pytest.mark.parametrize("guide", GUIDES)
    def test_each_of_them_writes_the_address_nginx_saw(self, guide: str) -> None:
        for location in nginx_locations(guide):
            if reaches_the_web_ui(location):
                assert names_the_visitor(location), (location.path, location.directives)

    def test_the_guides_show_the_same_configuration(self) -> None:
        assert nginx_locations("en") == nginx_locations("zh")

    def test_the_rule_reads_a_snippet_the_way_nginx_does(self) -> None:
        block = """
        location /a {
            proxy_pass http://127.0.0.1:8080;
            # proxy_set_header X-Forwarded-For $http_x_forwarded_for;
            proxy_set_header  x-forwarded-for   $remote_addr;   # one entry
            proxy_set_header Connection "";
        }
        location /b { proxy_pass http://127.0.0.1:8080; }
        location /c { root /srv/www; }
        location /d { proxy_pass http://127.0.0.1:9000; }
        """
        a, b, c, d = locations_in(block)
        assert a == Location(
            "/a",
            (
                ("proxy_pass", "http://127.0.0.1:8080"),
                ("proxy_set_header", "x-forwarded-for   $remote_addr"),
                ("proxy_set_header", 'Connection ""'),
            ),
        )
        assert b == Location("/b", (("proxy_pass", "http://127.0.0.1:8080"),))
        assert reaches_the_web_ui(a)
        assert reaches_the_web_ui(b)
        assert not reaches_the_web_ui(c)
        assert not reaches_the_web_ui(d)
        assert names_the_visitor(a)

    @pytest.mark.parametrize(
        "directives",
        [
            pytest.param(
                'proxy_http_version 1.1; proxy_set_header Connection "";',
                id="the block the guides had: no header at all",
            ),
            pytest.param(
                "proxy_set_header X-Forwarded-For $http_x_forwarded_for;",
                id="the visitor's own header passed on",
            ),
            pytest.param(
                "proxy_set_header X-Forwarded-For $host;", id="not an address"
            ),
            pytest.param(
                "proxy_set_header X-Forwarded-For $remote_addr;"
                " proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;",
                id="written twice",
            ),
            pytest.param(
                "proxy_set_header X-Real-IP $remote_addr;", id="another header"
            ),
        ],
    )
    def test_the_rule_refuses_what_it_exists_to_refuse(self, directives: str) -> None:
        (location,) = locations_in(
            "location /x { proxy_pass http://127.0.0.1:8080; " + directives + " }"
        )
        assert reaches_the_web_ui(location)
        assert not names_the_visitor(location)

    @pytest.mark.parametrize("value", sorted(VISITOR_ADDRESS))
    def test_the_rule_accepts_both_safe_forms(self, value: str) -> None:
        (location,) = locations_in(
            f"location /x {{ proxy_pass http://127.0.0.1:8080; proxy_set_header X-Forwarded-For {value}; }}"
        )
        assert names_the_visitor(location)


# ------------------------------------------------------------------- Waitress


class TestWaitressBehindAProxy:
    @pytest.mark.parametrize("guide", GUIDES)
    def test_one_command_names_the_proxy_to_trust(self, guide: str) -> None:
        trusting = [
            command
            for command in waitress_commands(guide)
            if "--trusted-proxy" in command
        ]
        assert len(trusting) == 1, waitress_commands(guide)
        command = trusting[0]
        assert command["--listen"] == "127.0.0.1:8080"
        assert command["--call"] == "ai_intervention_agent.web_ui_wsgi:create_app"
        assert command["--trusted-proxy"] == "127.0.0.1"
        assert command["--trusted-proxy-headers"] == "x-forwarded-for"
        assert command["--trusted-proxy-count"] == str(
            validators.DEFAULT_TRUSTED_PROXY_HOPS
        )

    def test_the_guides_give_the_same_command(self) -> None:
        def trusting(guide: str) -> list[dict[str, str]]:
            return [c for c in waitress_commands(guide) if "--trusted-proxy" in c]

        assert trusting("en") == trusting("zh") != []

    def test_the_options_are_read_as_a_shell_would(self) -> None:
        line = (
            "waitress-serve --listen=127.0.0.1:8080 --threads=8 --trusted-proxy=127.0.0.1"
            " --clear --call 'pkg.mod:create_app()' --last"
        )
        assert options_of(line) == {
            "--listen": "127.0.0.1:8080",
            "--threads": "8",
            "--trusted-proxy": "127.0.0.1",
            "--clear": "",
            "--call": "pkg.mod:create_app()",
            "--last": "",
        }


# ------------------------------------------------------------------- the checklist


class TestTheValidationChecklist:
    @pytest.mark.parametrize("guide", GUIDES)
    def test_it_asks_from_another_machine_what_only_this_one_may_ask(
        self, guide: str
    ) -> None:
        commands = [
            line
            for block in fenced(checklist(guide), "bash")
            for line in active_lines(block)
        ]
        through_the_proxy = [c for c in commands if re.search(r"http://<[^>]+>", c)]
        assert len(through_the_proxy) == 2, commands
        assert re.fullmatch(
            rf"curl -i http://<[^>]+>{re.escape(TOKEN_INFO)}", through_the_proxy[0]
        ), through_the_proxy
        assert re.fullmatch(
            rf"curl -i -m 3 http://<[^>]+>{re.escape(STREAM)}", through_the_proxy[1]
        ), through_the_proxy

    @pytest.mark.parametrize("guide", GUIDES)
    def test_the_checks_on_the_server_itself_are_still_there(self, guide: str) -> None:
        commands = [
            line
            for block in fenced(checklist(guide), "bash")
            for line in active_lines(block)
        ]
        assert f"curl -i {UPSTREAM}/api/system/health" in commands
        assert f"curl -N {UPSTREAM}{STREAM}" in commands


# ------------------------------------------------------------------- the Web UI behind them

ALLOWED = ["127.0.0.0/8", "::1/128", "203.0.113.0/24", "192.0.2.0/24"]
BLOCKED = "203.0.113.9"
VISITOR = "203.0.113.7"
CDN = "192.0.2.1"

# what, the connection's peer, X-Forwarded-For, trusted_proxy_hops, the answer of api-token-info
# (only this machine), the answer of every other route and of the stream
VISITORS: list[tuple[str, str, str | None, int, int, int]] = [
    ("nginx writes the address of a visitor on blocked_ips", "127.0.0.1", BLOCKED, 1, 403, 403),
    ("nginx writes the address of a visitor who may come in", "127.0.0.1", VISITOR, 1, 403, 200),
    ("you, browsing from the server through nginx", "127.0.0.1", "127.0.0.1", 1, 200, 200),
    ("no header: a location without the line, Waitress without its flags", "127.0.0.1", None, 1, 200, 200),
    ("a CDN in front of nginx, two hops, the visitor is blocked", "127.0.0.1", f"{BLOCKED}, {CDN}", 2, 403, 403),
    ("the same chain with the setting left at 1: the CDN is judged", "127.0.0.1", f"{BLOCKED}, {CDN}", 1, 403, 200),
    ("a visitor writes 127.0.0.1 in front of a two-hop chain", "127.0.0.1", f"127.0.0.1, {BLOCKED}, {CDN}", 2, 403, 403),
    ("no proxy, the visitor is blocked", BLOCKED, None, 1, 403, 403),
    ("no proxy, the visitor may come in", VISITOR, None, 1, 403, 200),
]  # fmt: skip


@pytest.fixture(scope="module")
def ui() -> WebFeedbackUI:
    instance = WebFeedbackUI(prompt="r866", task_id="r866-ui", port=0)
    instance.app.config["TESTING"] = True
    instance.limiter.enabled = False
    return instance


def configure(ui: WebFeedbackUI, hops: int) -> None:
    ui.network_security_config = validators.validate_network_security_config(
        {
            "allowed_networks": ALLOWED,
            "blocked_ips": [BLOCKED],
            "trusted_proxy_hops": hops,
        }
    )


def as_visitor(peer: str, forwarded_for: str | None) -> dict[str, Any]:
    environ: dict[str, Any] = {"REMOTE_ADDR": peer}
    if forwarded_for is not None:
        environ["HTTP_X_FORWARDED_FOR"] = forwarded_for
    return environ


def url_for_rule(rule: str) -> str:
    return re.sub(
        r"<[^>]+>", lambda m: "0" if m.group(0).startswith("<int:") else "x", rule
    )


class TestTheWebUiAnswersAsTheGuidesSay:
    @pytest.mark.parametrize(
        ("peer", "forwarded_for", "hops", "token_info", "others"),
        [row[1:] for row in VISITORS],
        ids=[row[0] for row in VISITORS],
    )
    def test_a_table_of_visitors(
        self,
        ui: WebFeedbackUI,
        peer: str,
        forwarded_for: str | None,
        hops: int,
        token_info: int,
        others: int,
    ) -> None:
        configure(ui, hops)
        environ = as_visitor(peer, forwarded_for)
        before = task_routes._sse_bus.subscriber_count
        with ui.app.test_client() as client:
            assert (
                client.get(TOKEN_INFO, environ_overrides=environ).status_code
                == token_info
            )
            assert client.get(HEALTH, environ_overrides=environ).status_code == others
            with client.get(STREAM, environ_overrides=environ) as stream:
                assert stream.status_code == others
                if others == 200:
                    frame = next(iter(stream.response))
                    assert isinstance(frame, bytes)
                    assert frame.startswith(b": connected")
        assert task_routes._sse_bus.subscriber_count == before

    def test_no_get_route_is_exempt_from_the_access_control(
        self, ui: WebFeedbackUI
    ) -> None:
        configure(ui, 1)
        rules = sorted(
            rule.rule
            for rule in ui.app.url_map.iter_rules()
            if "GET" in (rule.methods or ())
        )
        assert STREAM in rules
        assert len(rules) >= 30
        before = task_routes._sse_bus.subscriber_count
        environ = as_visitor("127.0.0.1", BLOCKED)
        with ui.app.test_client() as client:
            answers = {
                rule: client.get(
                    url_for_rule(rule), environ_overrides=environ
                ).status_code
                for rule in rules
            }
        assert {rule: code for rule, code in answers.items() if code != 403} == {}
        assert task_routes._sse_bus.subscriber_count == before

    def test_the_table_is_held_to_cover_what_the_guides_describe(self) -> None:
        answers = {(row[1], row[2], row[3]): (row[4], row[5]) for row in VISITORS}
        assert len(answers) == len(VISITORS) >= 9
        # a blocked visitor is refused by every route however the proxy chain is written
        assert {a for (peer, _, _), a in answers.items() if peer == BLOCKED} == {
            (403, 403)
        }
        # the lines the guides ask the reader to run give 403 and 403 for the blocked one
        assert answers[("127.0.0.1", BLOCKED, 1)] == (403, 403)
        # the failure the guides warn about: no header means this machine
        assert answers[("127.0.0.1", None, 1)] == (200, 200)
