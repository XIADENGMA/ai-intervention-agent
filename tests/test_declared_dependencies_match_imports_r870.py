"""R870: the packages ``pyproject.toml`` asks every user to install are the packages the code uses.

``flask-limiter`` was a runtime dependency that nothing imported.  R452 replaced Flask-Limiter with
the in-house ``WebUiRateLimiter`` and removed the last ``import flask_limiter`` from the package, but
``pyproject.toml`` kept ``flask-limiter>=4.0.0``: every ``uvx`` start and every ``pip install``
fetched and installed it, together with ``limits``, ``ordered-set``, ``deprecated`` and ``wrapt``,
for code that is not there.  It kept costing too: the ``limits`` pin of the lock file had to be
raised for security and resolver reasons (``virtualenv`` needs ``packaging>=26.3``, which ``limits``
capped), and every audit report listed it.  Nothing noticed, because nothing compared what the
package declares with what it imports; the cold-start test only asserts that ``flask_limiter`` is
not *loaded*, which is true when the code never mentions it.

What the tests pin, comparing ``[project].dependencies`` with an ``ast`` scan of
``src/ai_intervention_agent`` (every absolute import, in a function body too):

* every third-party module the package must have comes from a declared dependency.  The exceptions
  are written down in ``COMES_WITH``: ``werkzeug``, ``jinja2`` and ``markupsafe`` are what Flask is
  built on, and ``fastmcp`` is a distribution that holds no module (``fastmcp-slim`` does).  Each
  entry has to be true: the declared package requires the other one, and the code imports it.  An
  import in a ``try`` that catches ``ImportError`` (``rich`` is silenced when it is there) or under
  ``if TYPE_CHECKING:`` is optional and needs no declaration;
* every declared dependency is used: a module it provides is imported (an optional import counts),
  or a package that comes with it is, or it is on the short list of packages that run without an
  import and say why (``pygments`` is loaded by Markdown's ``codehilite``, ``brotli`` by
  Flask-Compress).  An entry of that list that is not declared, is imported after all, or whose
  reason no longer appears in the source fails the test, so the list cannot rot into the thing it
  guards against;
* the scanner and the metadata helpers: dotted names, ``from`` imports, relative imports,
  function-level imports, the ``try`` / ``except`` forms (``ImportError``, ``ModuleNotFoundError``,
  a tuple, ``Exception``, a bare ``except``, ``except*``) that make an import optional and the ones
  that do not (another exception, the ``except`` body, ``else``, ``finally``), ``TYPE_CHECKING``
  blocks and their ``else``, ``importlib.import_module("x")`` and ``__import__("x")`` with a
  literal, the PEP 503 names, the extras and platform markers that are not part of what a package
  brings along.
"""

from __future__ import annotations

import ast
import importlib.metadata
import os
import re
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path

import pytest
from packaging.requirements import Requirement

REPO = Path(__file__).resolve().parents[1]
PYPROJECT = REPO / "pyproject.toml"
PACKAGE = REPO / "src" / "ai_intervention_agent"
OWN_MODULE = "ai_intervention_agent"

#: Imported distributions that are not declared themselves, each with the declared one it comes with.
COMES_WITH: dict[str, str] = {
    "werkzeug": "flask",
    "jinja2": "flask",
    "markupsafe": "flask",
    "fastmcp-slim": "fastmcp",
}

#: Declared dependencies that run without any ``import`` in the package, each with the reason and
#: a phrase that has to stay in the source for the reason to be true.
RUNS_WITHOUT_AN_IMPORT: dict[str, tuple[str, str]] = {
    "pygments": (
        "Markdown's codehilite extension imports it when the codehilite config turns use_pygments on",
        '"use_pygments": True',
    ),
    "brotli": (
        "Flask-Compress compresses with it when the client accepts br",
        "Compress(self.app)",
    ),
}


# --------------------------------------------------------------------------- the scanner


@dataclass(frozen=True)
class Import:
    """One absolute import: the top-level module, where, and whether the package needs it."""

    module: str
    file: str
    required: bool


_MISSING_MODULE_ERRORS = {
    "ImportError",
    "ModuleNotFoundError",
    "Exception",
    "BaseException",
}


def _handler_expects_a_missing_module(handler: ast.ExceptHandler) -> bool:
    if handler.type is None:
        return True
    caught = (
        handler.type.elts if isinstance(handler.type, ast.Tuple) else [handler.type]
    )
    return any(
        isinstance(c, ast.Name) and c.id in _MISSING_MODULE_ERRORS for c in caught
    )


def _is_type_checking(test: ast.expr) -> bool:
    if isinstance(test, ast.Name):
        return test.id == "TYPE_CHECKING"
    return isinstance(test, ast.Attribute) and test.attr == "TYPE_CHECKING"


class _Collector(ast.NodeVisitor):
    def __init__(self, file: str) -> None:
        self.file = file
        self.found: list[Import] = []
        self._optional = 0
        self._typing_only = 0

    def _add(self, dotted: str) -> None:
        if self._typing_only:
            return
        self.found.append(
            Import(dotted.split(".")[0], self.file, required=not self._optional)
        )

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            self._add(alias.name)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.level == 0 and node.module:
            self._add(node.module)

    def visit_If(self, node: ast.If) -> None:
        if not _is_type_checking(node.test):
            self.generic_visit(node)
            return
        self._typing_only += 1
        for statement in node.body:
            self.visit(statement)
        self._typing_only -= 1
        for statement in node.orelse:
            self.visit(statement)

    def visit_Try(self, node: ast.Try | ast.TryStar) -> None:
        guarded = any(_handler_expects_a_missing_module(h) for h in node.handlers)
        self._optional += guarded
        for statement in node.body:
            self.visit(statement)
        self._optional -= guarded
        for part in (*node.handlers, *node.orelse, *node.finalbody):
            self.visit(part)

    visit_TryStar = visit_Try

    def visit_Call(self, node: ast.Call) -> None:
        function = node.func
        name = function.attr if isinstance(function, ast.Attribute) else None
        if isinstance(function, ast.Name):
            name = function.id
        if name in {"import_module", "__import__"} and node.args:
            first = node.args[0]
            if isinstance(first, ast.Constant) and isinstance(first.value, str):
                self._add(first.value)
        self.generic_visit(node)


def scan(source: str, file: str = "<memory>") -> list[Import]:
    collector = _Collector(file)
    collector.visit(ast.parse(source, filename=file))
    return collector.found


def third_party(imports: list[Import]) -> list[Import]:
    return [
        i
        for i in imports
        if i.module not in sys.stdlib_module_names and i.module != OWN_MODULE
    ]


def package_files() -> list[Path]:
    """Every Python file of the shipped package, the sub-packages included."""
    return sorted(PACKAGE.rglob("*.py"))


def package_imports() -> list[Import]:
    found: list[Import] = []
    for file in package_files():
        found += scan(file.read_text(encoding="utf-8"), str(file.relative_to(REPO)))
    return third_party(found)


# --------------------------------------------------------------------------- the metadata


def normalise(name: str) -> str:
    """PEP 503: what ``Flask_Cors`` and ``flask-cors`` have in common."""
    return re.sub(r"[-_.]+", "-", name).lower()


def declared(lines: list[str] | None = None) -> dict[str, Requirement]:
    """The requirements of ``[project].dependencies`` that apply to this interpreter."""
    if lines is None:
        data = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
        lines = data["project"]["dependencies"]
    found: dict[str, Requirement] = {}
    for line in lines:
        requirement = Requirement(line)
        if requirement.marker is not None and not requirement.marker.evaluate():
            continue
        found[normalise(requirement.name)] = requirement
    return found


def installed() -> set[str]:
    return {normalise(d.metadata["Name"]) for d in importlib.metadata.distributions()}


def modules_provided_by() -> dict[str, set[str]]:
    """Top-level module -> the distributions that install it."""
    return {
        module: {normalise(d) for d in dists}
        for module, dists in importlib.metadata.packages_distributions().items()
    }


def requirements_of(dist: str) -> set[str]:
    """The packages ``dist`` always installs with it (extras and other platforms left out)."""
    try:
        metadata = importlib.metadata.distribution(dist)
    except importlib.metadata.PackageNotFoundError:
        return set()
    found: set[str] = set()
    for line in metadata.requires or ():
        requirement = Requirement(line)
        if requirement.marker is None or requirement.marker.evaluate({"extra": ""}):
            found.add(normalise(requirement.name))
    return found


def covered_by(declared_dists: set[str]) -> set[str]:
    """Distributions the package may import: the declared ones and what comes with them."""
    return declared_dists | {
        child for child, parent in COMES_WITH.items() if parent in declared_dists
    }


def source_text() -> str:
    return "\n".join(f.read_text(encoding="utf-8") for f in package_files())


def distributions_in_use() -> set[str]:
    owners = modules_provided_by()
    return {d for i in package_imports() for d in owners.get(i.module, set())}


# --------------------------------------------------------------------------- the package


class TestDeclaredDependenciesAgainstImports:
    def test_every_declared_dependency_is_installed(self) -> None:
        """The comparison below reads the installed metadata, so it needs all of them."""
        missing = sorted(set(declared()) - installed())
        assert not missing, (
            f"declared in [project].dependencies but not installed: {missing}; "
            "run `uv sync` (or remove the entry if the package no longer needs it)"
        )

    def test_the_scan_reads_every_python_file_of_the_package(self) -> None:
        walked = sorted(
            Path(root) / name
            for root, _dirs, names in os.walk(PACKAGE)
            for name in names
            if name.endswith(".py")
        )
        assert package_files() == walked
        assert {"web_ui_routes", "config_modules"} <= {f.parent.name for f in walked}

    def test_the_package_has_something_to_scan(self) -> None:
        imports = package_imports()
        assert len(imports) > 30
        assert {"flask", "mcp", "pydantic"} <= {i.module for i in imports}

    def test_every_required_import_comes_from_a_declared_dependency(self) -> None:
        owners = modules_provided_by()
        allowed = covered_by(set(declared()))
        problems: list[str] = []
        for imp in package_imports():
            if not imp.required:
                continue
            providers = owners.get(imp.module, set())
            if not providers:
                problems.append(
                    f"{imp.file}: `{imp.module}` is provided by no installed package"
                )
            elif not providers & allowed:
                problems.append(
                    f"{imp.file}: `{imp.module}` ({', '.join(sorted(providers))}) is not "
                    "in [project].dependencies"
                )
        assert not problems, "\n".join(sorted(set(problems)))

    def test_every_declared_dependency_is_used(self) -> None:
        in_use = distributions_in_use()
        unused: list[str] = []
        for dist in sorted(declared()):
            comes_with_it = {c for c, parent in COMES_WITH.items() if parent == dist}
            if (
                dist in RUNS_WITHOUT_AN_IMPORT
                or dist in in_use
                or comes_with_it & in_use
            ):
                continue
            unused.append(dist)
        assert not unused, (
            f"declared in [project].dependencies, but no module of it is imported: {unused}.  "
            "Remove the entry (and refresh uv.lock), or add it to RUNS_WITHOUT_AN_IMPORT with "
            "the reason it is needed"
        )

    @pytest.mark.parametrize("child", sorted(COMES_WITH))
    def test_a_package_that_comes_with_another_is_still_needed_and_still_comes_with_it(
        self, child: str
    ) -> None:
        parent = COMES_WITH[child]
        assert parent in declared(), (
            f"{child} comes with {parent}, which is not declared"
        )
        assert child in requirements_of(parent), f"{parent} no longer requires {child}"
        assert child in distributions_in_use(), (
            f"the package no longer imports {child}; take it off COMES_WITH"
        )

    @pytest.mark.parametrize("dist", sorted(RUNS_WITHOUT_AN_IMPORT))
    def test_a_package_that_runs_without_an_import_is_declared_and_still_needed(
        self, dist: str
    ) -> None:
        reason, phrase = RUNS_WITHOUT_AN_IMPORT[dist]
        assert dist in declared(), (
            f"{dist} is on the list ({reason}) but is not declared"
        )
        assert dist not in distributions_in_use(), (
            f"{dist} is imported after all; take it off RUNS_WITHOUT_AN_IMPORT"
        )
        assert phrase in source_text(), (
            f"`{phrase}` no longer appears in the package, so this is no longer true: {reason}"
        )


# --------------------------------------------------------------------------- the scanner itself


def modules(source: str, *, required: bool | None = None) -> list[str]:
    return [
        i.module for i in scan(source) if required is None or i.required is required
    ]


class TestTheScanner:
    def test_import_forms(self) -> None:
        source = (
            "import a\nimport b.c.d\nimport e.f as g\nfrom h import i\nfrom j.k import l\n"
            "from . import m\nfrom .n import o\nfrom .. import p\n"
        )
        assert modules(source) == ["a", "b", "e", "h", "j"]

    def test_standard_library_and_the_package_itself_are_not_third_party(self) -> None:
        source = (
            "from __future__ import annotations\nimport os, json\nimport ai_intervention_agent.x\n"
            "import flask\n"
        )
        assert [i.module for i in third_party(scan(source))] == ["flask"]

    def test_an_import_in_a_function_or_a_class_counts(self) -> None:
        source = (
            "def f():\n    import a\n    def g():\n        from b import c\n"
            "class K:\n    import d\n"
        )
        assert modules(source, required=True) == ["a", "b", "d"]

    @pytest.mark.parametrize(
        "handler",
        [
            "except ImportError:",
            "except ModuleNotFoundError:",
            "except (ImportError, OSError):",
            "except (OSError, ModuleNotFoundError) as exc:",
            "except Exception:",
            "except BaseException:",
            "except:",
        ],
    )
    def test_a_try_that_expects_the_module_to_be_missing_makes_the_import_optional(
        self, handler: str
    ) -> None:
        source = f"try:\n    import a\n{handler}\n    a = None\n"
        assert modules(source, required=False) == ["a"]
        assert modules(source, required=True) == []

    @pytest.mark.parametrize(
        "handlers",
        [
            "except ImportError:\n    pass\nexcept ValueError:\n    pass\n",
            "except ValueError:\n    pass\nexcept ImportError:\n    pass\n",
            "except KeyError:\n    pass\nexcept ImportError:\n    pass\nexcept OSError:\n    pass\n",
        ],
    )
    def test_any_handler_may_be_the_one_that_expects_it(self, handlers: str) -> None:
        source = f"try:\n    import a\n{handlers}"
        assert modules(source, required=False) == ["a"]

    def test_except_star_guards_too(self) -> None:
        source = "try:\n    import a\nexcept* ImportError:\n    pass\n"
        assert modules(source, required=False) == ["a"]

    @pytest.mark.parametrize(
        "handler", ["except ValueError:", "except (OSError, KeyError):"]
    )
    def test_a_try_for_another_error_does_not(self, handler: str) -> None:
        source = f"try:\n    import a\n{handler}\n    pass\n"
        assert modules(source, required=True) == ["a"]

    def test_only_the_body_of_the_try_is_optional(self) -> None:
        source = (
            "try:\n    import a\nexcept ImportError:\n    import b\n"
            "else:\n    import c\nfinally:\n    import d\n"
        )
        assert modules(source, required=False) == ["a"]
        assert modules(source, required=True) == ["b", "c", "d"]

    def test_the_guard_ends_with_the_try(self) -> None:
        source = "try:\n    import a\nexcept ImportError:\n    pass\nimport b\n"
        assert modules(source, required=True) == ["b"]

    def test_a_nested_try_does_not_unguard_the_outer_one(self) -> None:
        source = (
            "try:\n    try:\n        import a\n    except ValueError:\n        pass\n"
            "except ImportError:\n    pass\n"
        )
        assert modules(source, required=False) == ["a"]

    @pytest.mark.parametrize(
        "test", ["TYPE_CHECKING", "typing.TYPE_CHECKING", "t.TYPE_CHECKING"]
    )
    def test_type_checking_blocks_need_nothing_installed(self, test: str) -> None:
        source = f"if {test}:\n    import a\nelse:\n    import b\nimport c\n"
        assert modules(source) == ["b", "c"]

    def test_other_conditions_count(self) -> None:
        source = "if sys.platform == 'win32':\n    import a\nelse:\n    import b\n"
        assert modules(source, required=True) == ["a", "b"]

    @pytest.mark.parametrize(
        "call",
        ['importlib.import_module("a.b")', 'import_module("a.b")', '__import__("a.b")'],
    )
    def test_import_calls_with_a_literal_name_count(self, call: str) -> None:
        assert modules(f"x = {call}\n") == ["a"]

    def test_import_calls_with_a_computed_name_are_left_alone(self) -> None:
        source = "x = importlib.import_module(name)\ny = __import__(f'a{n}')\n"
        assert modules(source) == []

    def test_a_call_to_something_else_is_not_an_import(self) -> None:
        assert modules('x = load_module("a")\ny = obj.import_modules("b")\n') == []


class TestTheMetadataHelpers:
    @pytest.mark.parametrize(
        ("name", "expected"),
        [
            ("Flask_Cors", "flask-cors"),
            ("flask.cors", "flask-cors"),
            ("zope__interface", "zope-interface"),
            ("PyYAML", "pyyaml"),
        ],
    )
    def test_normalise_follows_pep_503(self, name: str, expected: str) -> None:
        assert normalise(name) == expected

    def test_declared_keeps_the_requirements_that_apply_here(self) -> None:
        lines = [
            "Flask_Cors>=5",
            "only-on-the-moon; sys_platform == 'moon'",
            "ancient; python_version < '3.0'",
            "modern; python_version >= '3.11'",
        ]
        assert sorted(declared(lines)) == ["flask-cors", "modern"]

    def test_a_package_with_its_own_requirements(self) -> None:
        assert {"werkzeug", "jinja2", "markupsafe"} <= requirements_of("flask")

    def test_a_package_that_is_not_installed_requires_nothing(self) -> None:
        assert requirements_of("no-such-distribution-r870") == set()

    def test_extras_are_not_part_of_what_comes_along(self) -> None:
        """Flask lists ``asgiref`` and ``python-dotenv`` under extras only."""
        requirements = requirements_of("flask")
        assert "asgiref" not in requirements
        assert "python-dotenv" not in requirements

    def test_what_is_covered_is_the_declared_and_what_comes_with_them(self) -> None:
        assert covered_by({"flask"}) == {"flask", "werkzeug", "jinja2", "markupsafe"}
        assert covered_by({"fastmcp", "httpx"}) == {"fastmcp", "httpx", "fastmcp-slim"}
        assert covered_by({"httpx"}) == {"httpx"}
