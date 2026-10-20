"""R770: the test session must never read or write the developer's real task snapshot.

``get_task_queue()`` builds the global ``TaskQueue`` with
``<package>/data/tasks.json`` as its snapshot. Every test that touched the
singleton therefore restored whatever an earlier run (or the developer's own
service started from the same checkout) had left there, and wrote its fixture
tasks back. ``test_tasks_export_lazy_since_r520`` left ``r520-new`` /
``r520-old`` behind on every run, and the next service start from the checkout
showed them as pending tasks.

``tests/conftest.py`` now redirects ``_default_persist_path`` to the pytest
session's temporary directory, the same way it already redirects the config
file. These tests pin that redirect and the production default it replaces.
"""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

import ai_intervention_agent
import ai_intervention_agent.task_queue_singleton as task_queue_singleton

PACKAGE_DIR = Path(ai_intervention_agent.__file__).resolve().parent


def _is_inside(path: Path, directory: Path) -> bool:
    resolved = path.resolve()
    return resolved == directory or directory in resolved.parents


def test_session_redirects_the_snapshot_out_of_the_package_directory() -> None:
    path = task_queue_singleton._default_persist_path()
    assert not _is_inside(path, PACKAGE_DIR), path
    assert path.name == "tasks.json"


def test_production_default_is_still_the_package_data_directory() -> None:
    # The redirect replaces the function on the already-imported module, so
    # load a pristine copy of the source to see what a real service uses.
    spec = importlib.util.spec_from_file_location(
        "_aiia_task_queue_singleton_pristine", task_queue_singleton.__file__
    )
    assert spec is not None and spec.loader is not None
    pristine = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(pristine)

    assert pristine._default_persist_path() == PACKAGE_DIR / "data" / "tasks.json"


class TestSingletonCreatedInSetUpClass(unittest.TestCase):
    """unittest-style classes build the singleton in ``setUpClass``, before any
    function-scoped fixture can run; the redirect has to be in place by then."""

    _saved_queue = None
    _queue = None

    @classmethod
    def setUpClass(cls) -> None:
        cls._saved_queue = task_queue_singleton._global_task_queue
        task_queue_singleton._global_task_queue = None
        cls._queue = task_queue_singleton.get_task_queue()

    @classmethod
    def tearDownClass(cls) -> None:
        queue = task_queue_singleton._global_task_queue
        if queue is not None and queue is not cls._saved_queue:
            queue.stop_cleanup()
        task_queue_singleton._global_task_queue = cls._saved_queue

    def test_queue_built_in_set_up_class_uses_the_redirected_snapshot(self) -> None:
        queue = self._queue
        assert queue is not None
        persist_path = queue._persist_path
        self.assertIsNotNone(persist_path)
        assert persist_path is not None
        self.assertFalse(_is_inside(persist_path, PACKAGE_DIR), persist_path)


class TestRedirectSurvivesModuleReload(unittest.TestCase):
    """``importlib.reload`` re-runs the module body and drops the redirect for
    every later test in the same process; ``conftest`` puts it back after each
    test. The two tests below depend on running in this order (pytest keeps
    definition order inside a file, and ``--dist=loadfile`` keeps the file on
    one worker)."""

    def test_1_reload_really_drops_the_redirect(self) -> None:
        keep = {
            name: value
            for name, value in vars(task_queue_singleton).items()
            if name != "_default_persist_path"
        }
        try:
            importlib.reload(task_queue_singleton)
            self.assertEqual(
                task_queue_singleton._default_persist_path(),
                PACKAGE_DIR / "data" / "tasks.json",
                "the hazard this file guards against must be real",
            )
        finally:
            # Put everything back except the path function, so the next test can
            # observe whether conftest repaired it.
            for name, value in keep.items():
                setattr(task_queue_singleton, name, value)

    def test_2_conftest_puts_the_redirect_back_after_the_reload(self) -> None:
        path = task_queue_singleton._default_persist_path()
        self.assertFalse(_is_inside(path, PACKAGE_DIR), path)


if __name__ == "__main__":
    unittest.main()
