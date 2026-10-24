"""R867: the WSGI factory builds the Web UI with the settings the MCP server gives the Web UI it starts.

The MCP server starts the Web UI as a child process and puts what it reads from ``config.toml``
on that process's command line: ``--host`` (``network_security.bind_interface``), ``--port``
(``web_ui.port``), ``--external-base-url`` (``web_ui.external_base_url``), ``--mdns-hostname``
(``mdns.hostname``) and ``--trusted-hosts`` (``network_security.trusted_hosts``).  The ``Host``
names the Web UI accepts (Flask's ``TRUSTED_HOSTS``) are made from those five at construction.
``ai_intervention_agent.web_ui_wsgi:create_app``, the entrypoint ``docs/deployment.md`` gives for
Waitress and Gunicorn behind a reverse proxy, built ``WebFeedbackUI(prompt="", ...)`` with the
constructor's defaults, so none of the five reached it: the setting the guides tell the reader to
use behind a proxy that passes ``Host`` on (``trusted_hosts``, or ``external_base_url``) did nothing.
Measured with nginx 1.31 passing ``Host: agent.example.com`` on (``proxy_set_header Host
$http_host;``) in front of the real servers (containers)::

    setting                                      desktop   Waitress   Gunicorn
    trusted_hosts = ["agent.example.com"]          404        400        400
    external_base_url = "http://agent.example.com" 404        400        400
    mdns.hostname = "agent.local"                  404        400        400

(404: the ``Host`` is accepted and the probe path does not exist; 400: the Host was refused.)
The one place that did read the live setting was the write guard (``_allowed_write_origins``), which
is why the Origin half of the fix in the guides worked while the ``Host`` half did not.

The factory now asks ``service_manager.get_web_ui_config()``, the function that builds that command
line (environment overrides included), and passes the five values on; an unreadable configuration
starts the app on the defaults with a warning instead of keeping a supervised server from starting.
It also builds the app under a lock: concurrent first requests of a threaded server each built
their own app, and every thread but the last served from one that was then dropped.

What the tests pin:

* a table of settings (nothing, each of the five, all of them, an environment override) against the
  ``Host`` names the factory's app accepts, and that the app accepts the same ones, and holds the same
  ``TRUSTED_HOSTS``, as the one the desktop profile builds from the same configuration;
* an unreadable configuration: the app starts on the defaults and one warning says so;
* the settings are read once, when the app is built; the lazy ``application`` builds the same app;
* concurrent first calls share one app, and the constructor runs once;
* importing the module loads neither the Web UI nor the service manager;
* the five values are exactly the ones ``start_web_service`` puts on the command line;
* both deployment guides name the five settings in the WSGI section.
"""

from __future__ import annotations

import ast
import re
import subprocess
import sys
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from werkzeug.test import EnvironBuilder

from ai_intervention_agent import service_manager, web_ui_wsgi
from ai_intervention_agent.config_manager import get_config
from ai_intervention_agent.web_ui import WebFeedbackUI

REPO = Path(__file__).resolve().parents[1]
SRC = REPO / "src" / "ai_intervention_agent"
GUIDES = {
    "en": REPO / "docs" / "deployment.md",
    "zh": REPO / "docs" / "deployment.zh-CN.md",
}
WSGI_SECTION = {"en": "WSGI / Reverse Proxy Profile", "zh": "WSGI / 反向代理 Profile"}
SETTINGS = (
    "network_security.bind_interface",
    "web_ui.port",
    "web_ui.external_base_url",
    "mdns.hostname",
    "network_security.trusted_hosts",
)
NAME = "agent.example.com"
PROBES = (
    "localhost",
    "127.0.0.1",
    "ai.local",
    "agent.local",
    NAME,
    "other.example",
    "192.0.2.8",
)
DEFAULT_ACCEPTED = {"localhost", "127.0.0.1", "ai.local"}
ENV = (
    "AI_INTERVENTION_AGENT_WEB_UI_HOST",
    "AI_INTERVENTION_AGENT_WEB_UI_PORT",
    "AI_INTERVENTION_AGENT_WEB_UI_LANGUAGE",
)


@pytest.fixture(autouse=True)
def fresh_factory(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """No app built yet, no environment override, and no cached copy of the settings."""
    for name in ENV:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(web_ui_wsgi, "_app", None)
    service_manager.invalidate_web_ui_config_cache()
    yield
    service_manager.invalidate_web_ui_config_cache()


def configure(
    *,
    trusted: tuple[str, ...] = (),
    external: str = "",
    mdns: str = "ai.local",
    bind: str = "0.0.0.0",
) -> None:
    """Write the settings the way the settings page would (the managed test config file)."""
    config = get_config()
    config.update_section(
        "network_security", {"trusted_hosts": list(trusted), "bind_interface": bind}
    )
    config.update_section("web_ui", {"external_base_url": external})
    config.update_section("mdns", {"hostname": mdns})
    service_manager.invalidate_web_ui_config_cache()


def accepted(app: Any) -> set[str]:
    """The probe names the app answers (``200``) rather than refuses (``400``)."""
    answers: dict[str, int] = {}
    with app.test_client() as client:
        for host in PROBES:
            answers[host] = client.get(
                "/api/health", base_url=f"http://{host}"
            ).status_code
    assert set(answers.values()) <= {200, 400}, answers
    return {host for host, status in answers.items() if status == 200}


def desktop_app() -> Any:
    """The app the desktop profile builds: the constructor with the values it is given."""
    config, _timeout = service_manager.get_web_ui_config()
    return WebFeedbackUI(
        prompt="",
        auto_resubmit_timeout=0,
        host=config.host,
        port=config.port,
        external_base_url=config.external_base_url,
        mdns_hostname=config.mdns_hostname,
        trusted_hosts=config.trusted_hosts,
    ).app


# what, the settings, the probe names the app has to accept
ROWS: list[tuple[str, dict[str, Any], set[str]]] = [
    ("nothing is set", {}, DEFAULT_ACCEPTED),
    (
        "trusted_hosts lists the proxy's name",
        {"trusted": (NAME,)},
        DEFAULT_ACCEPTED | {NAME},
    ),
    (
        "external_base_url is the proxy's address",
        {"external": f"https://{NAME}"},
        DEFAULT_ACCEPTED | {NAME},
    ),
    (
        "mdns.hostname is another name",
        {"mdns": "agent.local"},
        {"localhost", "127.0.0.1", "agent.local"},
    ),
    (
        "bind_interface is a concrete address",
        {"bind": "192.0.2.8"},
        DEFAULT_ACCEPTED | {"192.0.2.8"},
    ),
    (
        "all of them",
        {
            "trusted": (NAME,),
            "external": "http://other.example",
            "mdns": "agent.local",
            "bind": "192.0.2.8",
        },
        {"localhost", "127.0.0.1", "agent.local", NAME, "other.example", "192.0.2.8"},
    ),
]


class TestTheFactoryReadsTheSettings:
    @pytest.mark.parametrize(
        ("settings", "expected"),
        [row[1:] for row in ROWS],
        ids=[row[0] for row in ROWS],
    )
    def test_the_hosts_the_app_accepts(
        self, settings: dict[str, Any], expected: set[str]
    ) -> None:
        configure(**settings)
        assert accepted(web_ui_wsgi.create_app()) == expected

    @pytest.mark.parametrize(
        "settings", [row[1] for row in ROWS], ids=[row[0] for row in ROWS]
    )
    def test_both_profiles_accept_the_same_hosts(
        self, settings: dict[str, Any]
    ) -> None:
        configure(**settings)
        factory = web_ui_wsgi.create_app()
        desktop = desktop_app()
        assert factory.config["TRUSTED_HOSTS"] == desktop.config["TRUSTED_HOSTS"]
        assert accepted(factory) == accepted(desktop)

    def test_an_environment_override_of_the_address_counts(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        configure()
        monkeypatch.setenv("AI_INTERVENTION_AGENT_WEB_UI_HOST", "192.0.2.8")
        service_manager.invalidate_web_ui_config_cache()
        assert accepted(web_ui_wsgi.create_app()) == DEFAULT_ACCEPTED | {"192.0.2.8"}

    def test_the_settings_are_read_once_when_the_app_is_built(self) -> None:
        configure(trusted=(NAME,))
        with patch.object(
            service_manager,
            "get_web_ui_config",
            wraps=service_manager.get_web_ui_config,
        ) as read:
            first = web_ui_wsgi.create_app()
            configure(trusted=("another.example",))
            assert web_ui_wsgi.create_app() is first
        assert read.call_count == 1
        assert NAME in first.config["TRUSTED_HOSTS"]
        assert "another.example" not in first.config["TRUSTED_HOSTS"]

    def test_the_lazy_application_builds_the_same_app(self) -> None:
        configure(trusted=(NAME,))
        seen: list[str] = []

        def start_response(status: str, headers: list[tuple[str, str]]) -> None:
            seen.append(status)

        environ = EnvironBuilder(
            path="/api/health",
            base_url=f"http://{NAME}",
            environ_overrides={"REMOTE_ADDR": "127.0.0.1"},
        ).get_environ()
        body = b"".join(web_ui_wsgi.application(environ, start_response))
        assert seen == ["200 OK"], body[:200]
        assert web_ui_wsgi._app is not None
        assert web_ui_wsgi.create_app() is web_ui_wsgi._app


class TestAnUnreadableConfiguration:
    def test_the_app_starts_on_the_defaults_and_says_so(self) -> None:
        configure(trusted=(NAME,))
        with (
            patch.object(
                service_manager,
                "get_web_ui_config",
                side_effect=ValueError("Web UI 配置错误: broken"),
            ),
            patch("ai_intervention_agent.enhanced_logging.EnhancedLogger") as logger,
        ):
            app = web_ui_wsgi.create_app()
        assert accepted(app) == DEFAULT_ACCEPTED
        assert logger.return_value.warning.call_count == 1
        assert "broken" in logger.return_value.warning.call_args.args[0]

    def test_an_unexpected_failure_is_not_hidden(self) -> None:
        with (
            patch.object(
                service_manager, "get_web_ui_config", side_effect=RuntimeError("bug")
            ),
            pytest.raises(RuntimeError, match="bug"),
        ):
            web_ui_wsgi.create_app()
        assert web_ui_wsgi._app is None


class TestOneAppPerProcess:
    def test_threads_that_start_together_share_one_app(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        built: list[int] = []
        real_init = WebFeedbackUI.__init__

        def slow_init(self: WebFeedbackUI, *args: Any, **kwargs: Any) -> None:
            built.append(threading.get_ident())
            time.sleep(0.2)  # the window two threads need to both see "no app yet"
            real_init(self, *args, **kwargs)

        monkeypatch.setattr(WebFeedbackUI, "__init__", slow_init)
        barrier = threading.Barrier(6)
        apps: list[Any] = []

        def first_request() -> None:
            barrier.wait()
            apps.append(web_ui_wsgi.create_app())

        threads = [threading.Thread(target=first_request) for _ in range(6)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(30)
        assert not any(thread.is_alive() for thread in threads)
        assert len(built) == 1
        assert len(apps) == 6
        assert len({id(app) for app in apps}) == 1

    def test_importing_the_module_loads_neither_the_web_ui_nor_the_service_manager(
        self,
    ) -> None:
        script = (
            "import sys\n"
            "import ai_intervention_agent.web_ui_wsgi\n"
            "names = ('ai_intervention_agent.web_ui', 'ai_intervention_agent.service_manager')\n"
            "print([name for name in names if name in sys.modules])\n"
        )
        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=REPO,
            text=True,
            capture_output=True,
            check=True,
        )
        assert result.stdout.strip() == "[]"


# ------------------------------------------------------------------- the command line


def _attributes_of_config(node: ast.AST) -> set[str]:
    """The ``config.<name>`` attributes under ``node``."""
    return {
        child.attr
        for child in ast.walk(node)
        if isinstance(child, ast.Attribute)
        and isinstance(child.value, ast.Name)
        and child.value.id == "config"
    }


def command_line_values() -> set[str]:
    """The ``config`` attributes ``start_web_service`` puts on the Web UI's command line."""
    tree = ast.parse((SRC / "service_manager.py").read_text(encoding="utf-8"))
    found: list[set[str]] = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Assign)
            and isinstance(node.value, ast.List)
            and any(
                isinstance(element, ast.Constant) and element.value == "--trusted-hosts"
                for element in node.value.elts
            )
        ):
            found.append(_attributes_of_config(node.value))
    assert len(found) == 1, found
    return found[0]


def factory_values() -> dict[str, str]:
    """``{argument: config attribute}`` of the dictionary ``_web_ui_arguments`` returns."""
    tree = ast.parse((SRC / "web_ui_wsgi.py").read_text(encoding="utf-8"))
    function = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "_web_ui_arguments"
    )
    returns = [
        node.value
        for node in ast.walk(function)
        if isinstance(node, ast.Return)
        and isinstance(node.value, ast.Dict)
        and node.value.keys  # ``return {}`` is the unreadable-configuration answer
    ]
    assert len(returns) == 1
    values: dict[str, str] = {}
    for key, value in zip(returns[0].keys, returns[0].values, strict=True):
        assert isinstance(key, ast.Constant) and isinstance(key.value, str)
        (attribute,) = _attributes_of_config(value)
        values[key.value] = attribute
    return values


class TestTheSameFiveValues:
    def test_the_factory_passes_what_the_command_line_carries(self) -> None:
        values = factory_values()
        assert values == {name: name for name in values}
        assert (
            set(values)
            == command_line_values()
            == {
                "host",
                "port",
                "external_base_url",
                "mdns_hostname",
                "trusted_hosts",
            }
        )

    def test_the_constructor_takes_all_of_them(self) -> None:
        parameters = WebFeedbackUI.__init__.__code__.co_varnames[
            : WebFeedbackUI.__init__.__code__.co_argcount
        ]
        assert set(factory_values()) <= set(parameters)


# ------------------------------------------------------------------- the guides


class TestTheGuidesSayIt:
    @pytest.mark.parametrize("guide", GUIDES)
    def test_the_wsgi_section_names_the_settings_and_when_they_are_read(
        self, guide: str
    ) -> None:
        text = GUIDES[guide].read_text(encoding="utf-8")
        heading = re.search(
            rf"^## {re.escape(WSGI_SECTION[guide])}$", text, re.MULTILINE
        )
        assert heading, guide
        rest = text[heading.end() :]
        following = re.search(r"^## ", rest, re.MULTILINE)
        section = rest[: following.start()] if following else rest
        for setting in SETTINGS:
            assert f"`{setting}`" in section, (guide, setting)
