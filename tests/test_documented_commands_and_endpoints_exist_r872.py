"""R872: the commands, endpoints and switches the docs tell a reader to use exist.

Four things the docs named did not exist, and nothing noticed, because every docs check there was
looked at files, links or config keys, never at what a reader is told to *run* or *call*:

* ``docs/troubleshooting.md`` (and its zh-CN twin) told a maintainer upgrading ``ovsx`` to
  ``npm run build:vscode`` and to expect ``dist/vsix/*.vsix``.  Neither ``package.json`` has that
  script: the VSIX comes from ``npm run vscode:package`` and lands in ``packages/vscode/``.
* ``README.md``, ``README.zh-CN.md`` and both ``docs/observability/README`` files called the
  Prometheus endpoint ``/metrics``.  The Web UI serves it at ``/api/system/metrics`` and answers
  ``/metrics`` with a JSON 404, so a scrape job left on Prometheus's default ``metrics_path``
  collected nothing, and the Grafana dashboard that doc imports stayed empty.  (The route's own
  docstring, which becomes the OpenAPI page, also gave the scrape target as port 8765; the default
  is 8080.)
* ``docs/noise-levels.md`` said the Web UI takes its log level from ``localStorage.AIIA_LOG_LEVEL``.
  No script reads that key; the only switch is ``window.AIIA_DEBUG``, for one helper.
  ``docs/perf-ci-xdist-r308.md`` said ``AIIA_TEST_WORKERS=auto uv run pytest`` works; nothing reads
  ``AIIA_TEST_WORKERS`` (further down, the same file says it is not implemented).
* ``docs/configuration.md`` called an SSH tunnel ``--ssh -L ...`` (the zh-CN twin has ``ssh -L``).

What the tests pin, over the *living* documents (the READMEs, ``docs/``, ``.github/``,
``packages/vscode/`` and ``scripts/``; the generated API pages, changelogs, dated reviews and
audits, and the one-row-per-round invariant tables name what used to exist on purpose and are
left out, each by a pattern that says why):

* every ``npm run <script>`` a doc gives is a script of the root or of a package ``package.json``;
* every endpoint a doc names in backticks is served by the real Web UI's URL map, when its first
  segment is one the app serves (``/api``, ``/static`` ...) or one a reader expects any service
  to answer (``/metrics``, ``/health`` ...).  A placeholder (``<id>``, ``{task_id}``) stands for
  any segment, a route that exists for another method counts, and a path ending in ``/`` is a
  prefix;
* every ``AI_INTERVENTION_AGENT_*`` / ``AIIA_*`` / ``AI_AGENT_*`` name a doc gives occurs in the
  code (``src/``, ``scripts/``, ``packages/vscode/``, ``.github/`` and the config files, never
  ``tests/``, which would vouch for itself), unless the doc says right there that the name is not
  implemented.  That exception is a short list; an entry whose doc no longer says so, or whose
  name the code reads after all, fails;
* every ``localStorage.<key>`` a doc gives occurs in a script or template;
* the scanners and the helpers: what each regex takes and leaves, the URL-map matching on a small
  map of its own (wrong method, placeholder, prefix, redirect, a miss), the corpus and the doc
  discovery, and that the checks look at enough to mean something.
"""

from __future__ import annotations

import contextlib
import functools
import json
import os
import re
from pathlib import Path

import pytest
from werkzeug.exceptions import MethodNotAllowed, NotFound
from werkzeug.routing import Map, RequestRedirect, Rule

from ai_intervention_agent.web_ui import WebFeedbackUI

REPO = Path(__file__).resolve().parents[1]

#: What counts as a living document: where to look ...
DOC_GLOBS = (
    "README.md",
    "README.zh-CN.md",
    "docs/**/*.md",
    ".github/*.md",
    "packages/vscode/*.md",
    "scripts/*.md",
)

#: ... and what to leave out.  Each of these names things that used to exist, or were only
#: proposed, on purpose, so a name in them proves nothing about today.
RECORDS: tuple[tuple[str, str], ...] = (
    (r"packages/vscode/CHANGELOG", "history"),
    (r"docs/api(?:\.zh-CN)?/", "generated from the code"),
    (r"docs/code-reviews/", "dated reviews"),
    (r"docs/feature-mining-", "dated research"),
    (r"docs/perf-audit-", "dated audits"),
    (r"docs/a11y-audit-", "dated audits"),
    (r"docs/security/", "dated audits"),
    (r"docs/triage/", "dated triage"),
    (
        r"docs/contributor-guide-invariant-tests",
        "one row per round, each naming what the round found",
    ),
    (r"docs/lessons-learned-", "post-mortems that name what broke"),
    (r"docs/methodology-evolution", "history of the method"),
    (r"docs/zhconv-eval", "an evaluation record"),
    (r"docs/loop-engineering-design-notes", "a design note"),
)

#: Names a reader expects any HTTP service to answer, whether or not this one does.
CONVENTIONAL = frozenset(
    {
        "metrics",
        "health",
        "healthz",
        "livez",
        "readyz",
        "ready",
        "status",
        "ping",
        "openapi.json",
        "swagger",
        "swagger.json",
    }
)

#: Where the code that reads a switch lives.  ``tests/`` is left out on purpose.
CODE_ROOTS = (
    "src",
    "scripts",
    "packages/vscode",
    ".github",
    "config.toml.default",
    "pyproject.toml",
    "pytest.ini",
)
CODE_SUFFIXES = frozenset(
    {
        ".py",
        ".js",
        ".mjs",
        ".cjs",
        ".ts",
        ".toml",
        ".yml",
        ".yaml",
        ".html",
        ".sh",
        ".ini",
    }
)
SCRIPT_SUFFIXES = frozenset({".js", ".mjs", ".cjs", ".ts", ".html"})
#: Directories, by name, that hold what is built, installed or a test (a test would vouch for
#: itself).  Every hidden directory is left out too: virtualenvs, caches and the copy of VS Code
#: the extension's tests download into ``packages/vscode/.vscode-test``.  (``.github`` is read:
#: it is a root, which the walk starts in, and only the directories below a root are judged.)
SKIPPED_DIRS = frozenset({"node_modules", "dist", "out", "__pycache__", "test"})

#: Names that docs may use although no code reads them, because the doc says right there that
#: they are not implemented.  ``{(doc, name): the sentence the doc must still contain}``.  The
#: sentence has to be in the same section as the mention (one under the next heading, a fenced
#: block's ``#`` comments aside), so the name cannot be called working above it.
NOT_IMPLEMENTED: dict[tuple[str, str], str] = {
    (
        "docs/perf-ci-xdist-r308.md",
        "AIIA_TEST_WORKERS",
    ): "not yet implemented in `ci_gate.py`",
}

# --------------------------------------------------------------------------- the scanners

NPM_RUN = re.compile(r"\bnpm run ([A-Za-z0-9][A-Za-z0-9:_\-]*)")
ROUTE = re.compile(
    r"`(?:(?:GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS) )?"
    r"(/[A-Za-z0-9_\-.]+(?:/[A-Za-z0-9_\-.<>{}:]*)*)`"
)
SWITCH = re.compile(r"\b(?:AI_INTERVENTION_AGENT|AIIA|AI_AGENT)_[A-Z0-9_]+\b")
LOCAL_STORAGE = re.compile(
    r"localStorage(?:\.(?!(?:getItem|setItem|removeItem|clear|key|length)\b)([A-Za-z_]\w*)"
    r"|\.(?:getItem|setItem|removeItem)\(\s*['\"]([\w\-.]+)['\"]"
    r"|\[\s*['\"]([\w\-.]+)['\"]\s*\])"
)

Mention = tuple[int, str]


def line_of(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def npm_scripts_run(text: str) -> list[Mention]:
    return [(line_of(text, m.start()), m.group(1)) for m in NPM_RUN.finditer(text)]


def route_mentions(text: str) -> list[Mention]:
    """Every backticked absolute path, with its line (``..`` is an ellipsis, not a path)."""
    return [
        (line_of(text, m.start()), m.group(1))
        for m in ROUTE.finditer(text)
        if ".." not in m.group(1)
    ]


def first_segment(path: str) -> str:
    return path.split("/")[1]


def checked_route_mentions(text: str, served: frozenset[str]) -> list[Mention]:
    """The paths a doc names that the app is held to: under a prefix it serves, or a
    conventional endpoint name."""
    return [
        (line, path)
        for line, path in route_mentions(text)
        if first_segment(path) in served | CONVENTIONAL
    ]


def fold(text: str) -> str:
    """The text with every run of whitespace, a line break included, made one space."""
    return " ".join(text.split())


def section_at(text: str, line: int) -> str:
    """The section of a markdown text, from its heading to the next one, that ``line`` is in.
    A ``#`` line inside a fenced block is a comment, not a heading."""
    lines = text.split("\n")
    headings: list[int] = []
    fenced = False
    for number, raw in enumerate(lines, start=1):
        if raw.lstrip().startswith(("```", "~~~")):
            fenced = not fenced
        elif not fenced and re.match(r"#{1,6} ", raw):
            headings.append(number)
    start = max((h for h in headings if h <= line), default=1)
    end = min((h for h in headings if h > line), default=len(lines) + 1)
    return "\n".join(lines[start - 1 : end - 1])


def concrete(path: str, fill: str = "x") -> str:
    """A path with its placeholders (``<id>``, ``<int:n>``, ``{task_id}``) filled in."""
    return re.sub(r"<[^>]+>|\{[^}]+\}", fill, path)


def is_served(url_map: Map, path: str) -> bool:
    """Whether ``path`` matches a rule of ``url_map``, for any method.  A path ending in ``/`` is
    also served when a rule starts with it (``/api/system/`` for ``/api/system/health``), and when
    a rule takes a file path under it (``/static/wasm/`` for ``/static/<path:filename>``).  A
    placeholder is filled with a word and with a number, for the ``<int:...>`` converters."""
    if path.endswith("/") and path != "/":
        prefix = concrete(path)
        if any(concrete(rule.rule).startswith(prefix) for rule in url_map.iter_rules()):
            return True
    adapter = url_map.bind("localhost")
    for fill in ("x", "0"):
        try:
            adapter.match(concrete(path, fill), method="GET")
        except MethodNotAllowed:
            return True  # the path exists, for another method
        except RequestRedirect:
            return True  # to the path with or without its trailing slash
        except NotFound:
            continue
        return True
    return False


def served_first_segments(url_map: Map) -> frozenset[str]:
    return frozenset(
        rule.rule.split("/")[1]
        for rule in url_map.iter_rules()
        if rule.rule.startswith("/")
        and rule.rule != "/"
        and not rule.rule.split("/")[1].startswith("<")
    )


def switch_mentions(text: str) -> list[Mention]:
    return [(line_of(text, m.start()), m.group(0)) for m in SWITCH.finditer(text)]


def local_storage_mentions(text: str) -> list[Mention]:
    return [
        (line_of(text, m.start()), next(g for g in m.groups() if g))
        for m in LOCAL_STORAGE.finditer(text)
    ]


def unread_switches(
    docs: dict[str, str], code: str, exceptions: dict[tuple[str, str], str]
) -> list[str]:
    """``doc:line: NAME`` for each switch a doc names that ``code`` does not contain, unless the
    section it sits in says, in the words ``exceptions`` holds for that doc and name, that the
    name is not implemented."""
    unread = []
    for doc, text in docs.items():
        for line, name in switch_mentions(text):
            if name in code:
                continue
            sentence = exceptions.get((doc, name))
            if sentence and sentence in fold(section_at(text, line)):
                continue
            unread.append(f"{doc}:{line}: {name}")
    return unread


# --------------------------------------------------------------------------- the files


def is_record(name: str) -> bool:
    return any(re.match(pattern, name) for pattern, _reason in RECORDS)


def living_docs() -> list[Path]:
    return sorted(
        {
            path
            for pattern in DOC_GLOBS
            for path in REPO.glob(pattern)
            if path.is_file() and not is_record(rel(path))
        }
    )


def rel(path: Path) -> str:
    return path.relative_to(REPO).as_posix()


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def npm_scripts_defined() -> set[str]:
    manifests = [REPO / "package.json", *sorted(REPO.glob("packages/*/package.json"))]
    return {
        name
        for manifest in manifests
        for name in json.loads(read(manifest)).get("scripts", {})
    }


def is_skipped_dir(name: str) -> bool:
    return name in SKIPPED_DIRS or name.startswith(".")


def code_files(suffixes: frozenset[str], repo: Path = REPO) -> list[Path]:
    """The files of ``CODE_ROOTS`` under ``repo`` with one of ``suffixes``, by walking down from
    each root and not into a skipped directory; a root that is itself a file counts as it is."""
    found: list[Path] = []
    for root in CODE_ROOTS:
        base = repo / root
        if base.is_file():
            found.append(base)
            continue
        for current, directories, names in os.walk(base):
            directories[:] = sorted(d for d in directories if not is_skipped_dir(d))
            for name in sorted(names):
                path = Path(current, name)
                if path.suffix in suffixes and path.is_file():
                    found.append(path)
    return found


@functools.cache
def code_text() -> str:
    return "\n".join(read(path) for path in code_files(CODE_SUFFIXES))


@functools.cache
def script_text() -> str:
    return "\n".join(read(path) for path in code_files(SCRIPT_SUFFIXES))


@pytest.fixture(scope="module")
def url_map() -> Map:
    ui = WebFeedbackUI(
        prompt="r872", task_id="r872-ui", auto_resubmit_timeout=0, port=19872
    )
    return ui.app.url_map


# --------------------------------------------------------------------------- the documents


class TestLivingDocs:
    def test_the_set_is_the_docs_a_reader_follows_and_not_the_records(self) -> None:
        docs = {rel(p) for p in living_docs()}
        assert len(docs) >= 40
        for name in (
            "README.md",
            "README.zh-CN.md",
            "docs/configuration.md",
            "docs/configuration.zh-CN.md",
            "docs/troubleshooting.md",
            "docs/observability/README.md",
            "docs/noise-levels.md",
            "docs/perf-ci-xdist-r308.md",
            ".github/CONTRIBUTING.md",
            "packages/vscode/README.md",
            "scripts/README.md",
        ):
            assert name in docs, name
        for name in (
            "CHANGELOG.md",
            "packages/vscode/CHANGELOG.md",
            "docs/api/index.md",
            "docs/api.zh-CN/index.md",
            "docs/code-reviews/cr9.md",
            "docs/feature-mining-cycle-1.md",
            "docs/perf-audit-cycle-3.md",
            "docs/security/AUDIT_2026-05-04.md",
            "docs/contributor-guide-invariant-tests.md",
            "docs/contributor-guide-invariant-tests.zh-CN.md",
            "docs/lessons-learned-silent-decay.md",
        ):
            assert name not in docs, name

    def test_each_record_pattern_still_matches_a_file_that_exists(self) -> None:
        every = {rel(p) for pattern in DOC_GLOBS for p in REPO.glob(pattern)}
        for pattern, reason in RECORDS:
            assert any(re.match(pattern, name) for name in every), (
                f"{pattern} ({reason}) matches nothing: drop it"
            )


class TestNpmScripts:
    def test_every_script_a_doc_runs_exists(self) -> None:
        defined = npm_scripts_defined()
        missing = [
            f"{rel(doc)}:{line}: npm run {name}"
            for doc in living_docs()
            for line, name in npm_scripts_run(read(doc))
            if name not in defined
        ]
        assert missing == []

    def test_the_check_sees_the_scripts_and_the_runs(self) -> None:
        defined = npm_scripts_defined()
        assert {"vscode:check", "vscode:package", "compile", "lint"} <= defined
        runs = {name for doc in living_docs() for _, name in npm_scripts_run(read(doc))}
        assert "vscode:check" in runs or "vscode:package" in runs
        assert len(runs) >= 3


class TestEndpoints:
    def test_every_endpoint_a_doc_names_is_served(self, url_map: Map) -> None:
        served = served_first_segments(url_map)
        missing = [
            f"{rel(doc)}:{line}: {path}"
            for doc in living_docs()
            for line, path in checked_route_mentions(read(doc), served)
            if not is_served(url_map, path)
        ]
        assert missing == []

    def test_the_check_reaches_enough_of_the_docs(self, url_map: Map) -> None:
        served = served_first_segments(url_map)
        checked = {
            path
            for doc in living_docs()
            for _, path in checked_route_mentions(read(doc), served)
        }
        assert len(checked) >= 15
        assert "/api/system/metrics" in checked
        assert "/api/tasks" in checked
        assert {"api", "static"} <= served

    def test_a_real_route_is_served_and_an_invented_one_is_not(
        self, url_map: Map
    ) -> None:
        assert is_served(url_map, "/api/system/metrics")
        assert is_served(url_map, "/api/tasks")
        assert not is_served(url_map, "/api/system/no-such-route")
        assert not is_served(url_map, "/no-such-root/x")


class TestSwitches:
    def test_every_name_a_doc_gives_is_read_by_the_code(self) -> None:
        docs = {rel(doc): read(doc) for doc in living_docs()}
        assert unread_switches(docs, code_text(), NOT_IMPLEMENTED) == []

    def test_every_not_implemented_entry_is_still_true(self) -> None:
        code = code_text()
        for (doc, name), sentence in NOT_IMPLEMENTED.items():
            text = read(REPO / doc)
            assert name in {n for _, n in switch_mentions(text)}, (
                f"{doc} no longer names {name}: drop the entry"
            )
            assert sentence in fold(text), (
                f"{doc} no longer says {name} is not implemented"
            )
            assert name not in code, f"the code reads {name} now: drop the entry"

    def test_every_local_storage_key_a_doc_gives_is_in_a_script(self) -> None:
        scripts = script_text()
        unread = [
            f"{rel(doc)}:{line}: localStorage.{key}"
            for doc in living_docs()
            for line, key in local_storage_mentions(read(doc))
            if key not in scripts
        ]
        assert unread == []

    def test_the_checks_see_names_and_the_code_they_are_held_against(self) -> None:
        names = {n for doc in living_docs() for _, n in switch_mentions(read(doc))}
        assert len(names) >= 12
        assert {
            "AI_INTERVENTION_AGENT_CONFIG_FILE",
            "AIIA_SSE_SCHEMA_VALIDATE",
        } <= names
        assert "AI_INTERVENTION_AGENT_LOG_LEVEL" in code_text()
        assert "AIIA_DEBUG" in script_text()
        assert "AIIA_TEST_WORKERS" not in code_text()
        keys = {
            k for doc in living_docs() for _, k in local_storage_mentions(read(doc))
        }
        assert keys, (
            "no doc names a localStorage key any more; is the scan still looking?"
        )


# --------------------------------------------------------------------------- the scanners


class TestNpmScanner:
    def test_takes_the_script_name_with_its_colon_and_line(self) -> None:
        text = "x\nnpm run build:vscode  # c\nand `npm run lint`, then npm run a_b-c\n"
        assert npm_scripts_run(text) == [(2, "build:vscode"), (3, "lint"), (3, "a_b-c")]

    def test_leaves_what_is_not_a_script_run(self) -> None:
        assert npm_scripts_run("npm runner x; npm ci; npm test; pnpm run lint") == []
        assert npm_scripts_run("npm run -w pkg test") == []
        assert npm_scripts_run("npm run") == []


class TestRouteScanner:
    def test_takes_backticked_absolute_paths_with_or_without_a_method(self) -> None:
        text = (
            "see `/metrics` and `GET /api/tasks/<id>`\n"
            "and `POST /api/tasks/{task_id}/submit` or `/api/system/`.\n"
        )
        assert route_mentions(text) == [
            (1, "/metrics"),
            (1, "/api/tasks/<id>"),
            (2, "/api/tasks/{task_id}/submit"),
            (2, "/api/system/"),
        ]

    def test_leaves_what_is_not_an_absolute_path_in_backticks(self) -> None:
        text = (
            "bare /metrics, a url `http://host/metrics`, relative `api/tasks`, "
            "an ellipsis `/api/.../x`, a file `foo.py`, two words `/a b`, "
            'an empty `/`, prose "`" text /api/tasks'
        )
        assert route_mentions(text) == []

    def test_a_dotted_first_segment_is_a_path(self) -> None:
        assert route_mentions("`/manifest.webmanifest` `/sw.js`") == [
            (1, "/manifest.webmanifest"),
            (1, "/sw.js"),
        ]

    def test_only_paths_the_app_is_held_to_are_checked(self) -> None:
        text = "`/metrics` `/api/x` `/usr/bin/osascript` `/tmp` `/review` `/health`"
        got = checked_route_mentions(text, frozenset({"api", "static"}))
        assert [p for _, p in got] == ["/metrics", "/api/x", "/health"]
        got = checked_route_mentions(text, frozenset())
        assert [p for _, p in got] == ["/metrics", "/health"]

    def test_the_first_segment_is_the_one_after_the_slash(self) -> None:
        assert first_segment("/api/tasks") == "api"
        assert first_segment("/metrics") == "metrics"
        assert first_segment("/manifest.webmanifest") == "manifest.webmanifest"


class TestUrlMapMatching:
    @staticmethod
    def a_map(catch_all: bool = False) -> Map:
        rules = [
            Rule("/", endpoint="index"),
            Rule("/api/a", endpoint="a", methods=["GET"]),
            Rule("/api/b/<int:n>", endpoint="b", methods=["POST"]),
            Rule("/api/b/export", endpoint="b2", methods=["GET"]),
            Rule("/api/dir/", endpoint="dir", methods=["GET"]),
            Rule("/api/system/health", endpoint="h", methods=["GET"]),
            Rule("/static/<path:filename>", endpoint="static"),
        ]
        if (
            catch_all
        ):  # it serves every path, for PUT: only the first-segment test wants it
            rules.append(Rule("/<path:anything>", endpoint="catch", methods=["PUT"]))
        return Map(rules)

    def test_an_exact_route(self) -> None:
        m = self.a_map()
        assert is_served(m, "/api/a")
        assert is_served(m, "/api/system/health")

    def test_a_placeholder_stands_for_a_segment_of_any_kind(self) -> None:
        m = self.a_map()
        assert concrete("/api/b/<int:n>/x/{task_id}/<id>") == "/api/b/x/x/x/x"
        assert concrete("/api/b/<n>", "0") == "/api/b/0"
        assert is_served(m, "/api/b/<n>")  # an int converter takes the number fill
        assert is_served(m, "/api/b/{task_id}")
        assert is_served(m, "/static/js/app.js")

    def test_a_route_that_exists_for_another_method_is_served(self) -> None:
        m = Map([Rule("/api/only-post", endpoint="p", methods=["POST"])])
        assert is_served(m, "/api/only-post")
        m = Map([Rule("/api/only-delete", endpoint="d", methods=["DELETE"])])
        assert is_served(m, "/api/only-delete")
        m = Map([Rule("/api/only-options", endpoint="o", methods=["OPTIONS"])])
        assert is_served(m, "/api/only-options")

    def test_a_miss_is_not_served(self) -> None:
        m = Map([Rule("/api/a", endpoint="a")])
        assert not is_served(m, "/metrics")
        assert not is_served(m, "/api/zzz")
        assert not is_served(m, "/api/a/extra")
        assert not is_served(m, "/api")
        assert not is_served(m, "/")  # no rule serves the root here

    def test_a_trailing_slash_names_a_prefix(self) -> None:
        m = Map(
            [
                Rule("/api/system/health", endpoint="h"),
                Rule("/api/a", endpoint="a"),
                Rule("/static/<path:filename>", endpoint="static"),
            ]
        )
        assert is_served(m, "/api/system/")  # a rule starts with it
        assert is_served(m, "/api/")
        assert is_served(m, "/static/wasm/")  # a file under it would be served
        assert not is_served(m, "/api/other/")
        assert not is_served(m, "/metrics/")

    def test_a_redirect_to_the_path_with_its_slash_is_served(self) -> None:
        m = Map([Rule("/api/dir/", endpoint="dir", methods=["GET"])])
        assert is_served(m, "/api/dir")

    def test_the_first_segments_are_those_of_the_rules(self) -> None:
        assert served_first_segments(self.a_map()) == {"api", "static"}
        assert served_first_segments(self.a_map(catch_all=True)) == {"api", "static"}


SECTIONS = """intro mentions AIIA_X
# One
alpha
```bash
# a comment, not a heading
AIIA_X=1 run
```
still one
## Two
beta
"""


class TestSections:
    def test_a_section_runs_from_its_heading_to_the_next(self) -> None:
        assert section_at(SECTIONS, 1) == "intro mentions AIIA_X"
        assert section_at(SECTIONS, 3).splitlines()[0] == "# One"
        assert section_at(SECTIONS, 3).splitlines()[-1] == "still one"
        assert section_at(SECTIONS, 9) == "## Two\nbeta\n"
        assert section_at(SECTIONS, 10) == "## Two\nbeta\n"

    def test_a_hash_line_in_a_fenced_block_is_not_a_heading(self) -> None:
        assert section_at(SECTIONS, 6) == section_at(SECTIONS, 3)
        assert "# a comment, not a heading" in section_at(SECTIONS, 6)
        tilde = "# H\n~~~\n# c\n~~~\ntext\n"
        assert section_at(tilde, 5) == tilde  # one section, to the end
        assert section_at("a\n### Deep\nb", 3) == "### Deep\nb"
        assert section_at("a\n#nospace\nb", 3) == "a\n#nospace\nb"

    def test_a_fence_indented_by_a_space_still_fences(self) -> None:
        text = "# H\n ```sh\n# c\n run\n ```\ntext\n"
        assert section_at(text, 3) == text  # the comment is no heading

    def test_fold_makes_every_run_of_whitespace_one_space(self) -> None:
        assert fold("not yet\n  implemented\tin x") == "not yet implemented in x"
        assert fold("") == ""


class TestUnreadSwitches:
    DOC = "d.md"
    CODE = "reads AIIA_READ here"
    NOT = {("d.md", "AIIA_NOPE"): "is not implemented"}

    def run(self, text: str, code: str | None = None) -> list[str]:
        return unread_switches(
            {self.DOC: text}, self.CODE if code is None else code, self.NOT
        )

    def test_a_name_the_code_has_is_fine_and_one_it_lacks_is_reported_with_its_line(
        self,
    ) -> None:
        assert self.run("AIIA_READ") == []
        assert self.run("x\nuse AIIA_GONE now") == ["d.md:2: AIIA_GONE"]

    def test_a_name_is_excused_by_the_sentence_in_its_own_section(self) -> None:
        text = "# A\nAIIA_NOPE is not\nimplemented yet.\n"  # the sentence wraps
        assert self.run(text) == []

    def test_a_name_is_not_excused_by_a_sentence_in_another_section(self) -> None:
        text = "# A\nrun AIIA_NOPE=auto now\n# B\nAIIA_NOPE is not implemented\n"
        assert self.run(text) == ["d.md:2: AIIA_NOPE"]

    def test_a_name_is_not_excused_without_its_sentence_or_for_another_doc_or_name(
        self,
    ) -> None:
        assert self.run("# A\nAIIA_NOPE works\n") == ["d.md:2: AIIA_NOPE"]
        other = {("e.md", "AIIA_NOPE"): "is not implemented"}
        text = "# A\nAIIA_NOPE is not implemented\n"
        assert unread_switches({"d.md": text}, "", other) == ["d.md:2: AIIA_NOPE"]
        other = {("d.md", "AIIA_OTHER"): "is not implemented"}
        assert unread_switches({"d.md": text}, "", other) == ["d.md:2: AIIA_NOPE"]

    def test_a_section_with_the_sentence_inside_a_fence_still_counts(self) -> None:
        text = "# A\nnot implemented\n```sh\n# c\nAIIA_NOPE=1 go\n```\n"
        assert self.run(text.replace("not implemented", "is not implemented")) == []


class TestSwitchScanner:
    def test_takes_each_prefix_with_trailing_underscore_forms(self) -> None:
        text = (
            "AIIA_DEBUG and AI_INTERVENTION_AGENT_WEB_UI_ (prefix)\n"
            "`AI_AGENT_ENABLE_SWAGGER=1`, AIIA_X1\n"
        )
        assert switch_mentions(text) == [
            (1, "AIIA_DEBUG"),
            (1, "AI_INTERVENTION_AGENT_WEB_UI_"),
            (2, "AI_AGENT_ENABLE_SWAGGER"),
            (2, "AIIA_X1"),
        ]

    def test_leaves_other_names(self) -> None:
        text = (
            "aiia_debug OTHER_AIIA_X XAIIA_Y AIIA AIIA_ lower_AIIA_Z AI_AGENT AIIA_Xy"
        )
        assert switch_mentions(text) == []


class TestLocalStorageScanner:
    def test_takes_a_property_a_literal_key_and_a_bracket_key(self) -> None:
        text = (
            "localStorage.AIIA_LOG_LEVEL and localStorage.getItem('k1')\n"
            "and localStorage.setItem(\"k2\", 1) localStorage.removeItem( 'k3' )\n"
            "and localStorage['k4'] and localStorage[ \"k-5\" ]\n"
            "and localStorage.keyboard_layout\n"
        )
        assert local_storage_mentions(text) == [
            (1, "AIIA_LOG_LEVEL"),
            (1, "k1"),
            (2, "k2"),
            (2, "k3"),
            (3, "k4"),
            (3, "k-5"),
            (4, "keyboard_layout"),
        ]

    def test_leaves_the_storage_api_itself(self) -> None:
        text = "localStorage.clear() localStorage.key(0) localStorage.length localStorage.getItem(name)"
        assert local_storage_mentions(text) == []


class TestCorpus:
    def test_the_code_corpus_has_the_code_and_not_the_tests(self) -> None:
        files = {rel(p) for p in code_files(CODE_SUFFIXES)}
        assert "src/ai_intervention_agent/web_ui.py" in files
        assert "scripts/ci_gate.py" in files
        assert "config.toml.default" in files
        assert "pyproject.toml" in files
        assert any(f.startswith(".github/workflows/") for f in files)
        assert any(
            f.startswith("packages/vscode/") and f.endswith(".ts") for f in files
        )
        assert not any(f.startswith("tests/") for f in files)
        assert not any("/node_modules/" in f or "/dist/" in f for f in files)
        assert not any(f.startswith("packages/vscode/test/") for f in files)
        for f in files:
            below_the_root = f.split("/")[1:-1]
            assert not any(d.startswith(".") for d in below_the_root), (
                f"{f} is in a hidden directory (the downloaded VS Code, a virtualenv ...)"
            )

    def test_the_corpus_skips_what_is_built_installed_or_a_test(
        self, tmp_path: Path
    ) -> None:
        # the checkout itself may sit under a directory with a skipped name: only the path
        # inside it counts
        repo = tmp_path / "test" / "dist" / "repo"
        keep = [
            "src/pkg/a.py",
            "src/pkg/settings.toml",
            "scripts/b.mjs",
            "scripts/c.sh",
            "scripts/d.cjs",
            "scripts/e.ini",
            "packages/vscode/extension.ts",
            "packages/vscode/.vscode-test.mjs",  # a hidden file is no hidden directory
            "packages/vscode/f.js",
            "packages/vscode/media/view.html",
            ".github/workflows/ci.yml",
            ".github/workflows/x.yaml",
            "config.toml.default",
            "pyproject.toml",
            "pytest.ini",
        ]
        skip = [
            "packages/vscode/node_modules/dep/index.js",
            "packages/vscode/dist/extension.js",
            "packages/vscode/out/extension.js",
            "packages/vscode/test/suite.ts",
            "src/pkg/__pycache__/a.cpython-311.py",
            "scripts/.venv/lib/site.py",
            "src/.cache/y.py",
            "packages/vscode/.vscode-test/vscode/app/x.js",
            ".github/.hidden/z.yml",
            "src/pkg/notes.md",
            "src/pkg/data.json",
            "tests/test_a.py",
            "docs/guide.md",
        ]
        for name in [*keep, *skip]:
            target = repo / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("x", encoding="utf-8")
        odd = repo / "src" / "odd.py"
        odd.mkdir()  # a directory named like a script is no script
        with contextlib.suppress(OSError):  # a link to nothing is no script either
            (repo / "src" / "broken.py").symlink_to(repo / "src" / "no-such-file")
        found = {
            p.relative_to(repo).as_posix() for p in code_files(CODE_SUFFIXES, repo)
        }
        assert found == set(keep)

    def test_the_script_corpus_is_the_front_end(self) -> None:
        files = {rel(p) for p in code_files(SCRIPT_SUFFIXES)}
        assert "src/ai_intervention_agent/static/js/app.js" in files
        assert "src/ai_intervention_agent/templates/web_ui.html" in files
        assert "packages/vscode/webview-ui.js" in files
        assert not any(f.endswith(".py") for f in files)
