"""Regression guard for the @aiia/tri-state-panel loader's failure path (T1 · C10c·F1).

Why this test exists:
    The tri-state panel is mounted through a two-script handshake:

        1. ``tri-state-panel-loader.js`` (ES module, runs in the
           importmap graph) calls ``import('@aiia/tri-state-panel')``.
        2. ``tri-state-panel-bootstrap.js`` (classic script) registers a
           ``DOMContentLoaded`` listener which, when fired, checks
           ``window.AIIA_TRI_STATE_PANEL`` — if the loader's import
           already resolved, the global is set and the bootstrap mounts
           the controller directly; otherwise it registers listeners for
           the ``aiia:tri-state-panel-ready`` / ``-failed`` CustomEvents.

    This handshake has an asymmetric hole on the FAILED path.
    READY path is safe: the loader sets ``window.AIIA_TRI_STATE_PANEL``
    BEFORE dispatching the event; even if the event fires before the
    bootstrap registers its listener (HTML spec §8.1.3.2: module
    microtasks can drain before ``DOMContentLoaded``), the bootstrap
    reads the global and recovers. FAILED path had no such flag —
    the error event was dispatched to an empty listener set, and the
    bootstrap would later register a listener that never fired,
    leaving the panel permanently stuck at ``data-state="ready"``
    (which CSS renders as ``display: none``). User-visible symptom:
    the tri-state region is invisible and the rest of the UI works,
    so the failure is extremely hard to diagnose.

Fix (shipped alongside this test):
    ``publishError`` now persists the error on
    ``window.AIIA_TRI_STATE_PANEL_FAILURE`` BEFORE dispatching the
    FAILED event. The bootstrap's ``start()`` checks the flag as a
    symmetric guard to its existing ``window.AIIA_TRI_STATE_PANEL``
    short-circuit — if the loader already failed, bootstrap logs the
    error and returns, avoiding the dead-listener trap.

Static invariants this test pins:

1. Loader sets ``window.AIIA_TRI_STATE_PANEL_FAILURE`` in
   ``publishError``.
2. Setter precedes ``dispatchEvent(FAILED_EVENT)`` (write-before-notify)
   — mirrors the success path's ``publish()`` ordering.
3. Bootstrap's ``start()`` reads ``window.AIIA_TRI_STATE_PANEL_FAILURE``
   before registering the FAILED listener.
4. The symmetric success guards (``window.AIIA_TRI_STATE_PANEL`` in
   both loader and bootstrap) are still in place — we do NOT want a
   "fix regression" that silently removes them.

Both Web UI source and VSCode mirror are checked; byte-parity is
already pinned by ``tests/test_tri_state_panel_parity.py``, but this
test runs before parity would catch a drift so the failure message
points at the *semantic* bug instead of a byte-hash diff.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
LOADER_SOURCES: tuple[Path, ...] = (
    REPO_ROOT / "static" / "js" / "tri-state-panel-loader.js",
    REPO_ROOT / "packages" / "vscode" / "tri-state-panel-loader.js",
)
BOOTSTRAP_SOURCES: tuple[Path, ...] = (
    REPO_ROOT / "static" / "js" / "tri-state-panel-bootstrap.js",
    REPO_ROOT / "packages" / "vscode" / "tri-state-panel-bootstrap.js",
)

FAILURE_FLAG = "AIIA_TRI_STATE_PANEL_FAILURE"
SUCCESS_FLAG = "AIIA_TRI_STATE_PANEL"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


class TestLoaderFailureFlag(unittest.TestCase):
    """Loader must persist the failure BEFORE notifying listeners."""

    def test_failure_flag_is_set_in_publish_error(self) -> None:
        for path in LOADER_SOURCES:
            src = _read(path)
            self.assertRegex(
                src,
                rf"{FAILURE_FLAG}\s*=",
                msg=(
                    f"{path.relative_to(REPO_ROOT)}::publishError does not set "
                    f"``window.{FAILURE_FLAG}``. Without this flag, any late "
                    f"listener (the classic bootstrap registers its listener "
                    f"after a DOMContentLoaded hop, but the import()'s "
                    f"catch-microtask can settle FIRST in the synchronous-"
                    f"reject path) misses the FAILED event and the tri-state "
                    f"panel silently stays at data-state='ready' (hidden). "
                    f"Fix: mirror the success path — set the global BEFORE "
                    f"dispatchEvent(FAILED_EVENT)."
                ),
            )

    def test_setter_precedes_dispatch_event(self) -> None:
        """Write-before-notify: observers that arrive after the event
        dispatch must still be able to read the failure from the flag.
        Order-swap would re-introduce the race this fix was meant to
        close, so pin the ordering in source."""
        for path in LOADER_SOURCES:
            src = _read(path)
            setter_match = re.search(
                rf"globalNamespace\.{FAILURE_FLAG}\s*=",
                src,
            )
            self.assertIsNotNone(
                setter_match,
                msg=(
                    f"{path.relative_to(REPO_ROOT)} has no "
                    f"``globalNamespace.{FAILURE_FLAG} = ...`` statement. "
                    "The canonical fix sets the flag via the reusable "
                    "``globalNamespace`` alias (shared with the success "
                    "path). If you renamed the alias, update this test in "
                    "lockstep."
                ),
            )
            dispatch_match = re.search(
                r"dispatchEvent\(\s*new\s+CustomEvent\(\s*FAILED_EVENT",
                src,
            )
            self.assertIsNotNone(
                dispatch_match,
                msg=(
                    f"{path.relative_to(REPO_ROOT)} has no "
                    "``dispatchEvent(new CustomEvent(FAILED_EVENT, ...))`` — "
                    "the FAILED notification path was removed or renamed, "
                    "which breaks consumers that listen for the event."
                ),
            )
            assert setter_match is not None and dispatch_match is not None
            self.assertLess(
                setter_match.start(),
                dispatch_match.start(),
                msg=(
                    f"{path.relative_to(REPO_ROOT)}: "
                    f"``globalNamespace.{FAILURE_FLAG} = ...`` must appear "
                    "BEFORE ``dispatchEvent(new CustomEvent(FAILED_EVENT))`` "
                    "in the source (write-before-notify order). Swapping "
                    "them re-introduces the race this regression guard was "
                    "added to prevent: a listener that arrives after the "
                    "event dispatch but before the flag assignment would "
                    "see neither the event nor the flag."
                ),
            )


class TestLoaderSuccessFlagUnchanged(unittest.TestCase):
    """The failure-path fix MUST NOT regress the pre-existing success-path
    guarantee (``globalNamespace.AIIA_TRI_STATE_PANEL = pkg`` set in
    ``publish`` before ``dispatchEvent(READY_EVENT)``)."""

    def test_success_flag_still_set_before_ready_dispatch(self) -> None:
        for path in LOADER_SOURCES:
            src = _read(path)
            set_match = re.search(
                rf"globalNamespace\.{SUCCESS_FLAG}\s*=\s*pkg",
                src,
            )
            ready_match = re.search(
                r"dispatchEvent\(\s*new\s+CustomEvent\(\s*READY_EVENT",
                src,
            )
            self.assertIsNotNone(
                set_match,
                msg=(
                    f"{path.relative_to(REPO_ROOT)} lost the pre-existing "
                    f"``globalNamespace.{SUCCESS_FLAG} = pkg`` line — the "
                    "success-path bootstrap guard no longer has a flag to "
                    "check. Restore it in ``publish()``."
                ),
            )
            self.assertIsNotNone(
                ready_match,
                msg=(
                    f"{path.relative_to(REPO_ROOT)} lost the ``dispatchEvent"
                    "(READY_EVENT)`` call — consumers waiting on the event "
                    "will never be notified."
                ),
            )
            assert set_match is not None and ready_match is not None
            self.assertLess(
                set_match.start(),
                ready_match.start(),
                msg=(
                    f"{path.relative_to(REPO_ROOT)}: success-path ordering "
                    "regressed — the flag must still be set BEFORE "
                    "dispatchEvent(READY_EVENT) to preserve the late-"
                    "listener fallback."
                ),
            )


class TestBootstrapReadsFailureFlag(unittest.TestCase):
    """Bootstrap's ``start()`` must read ``window.AIIA_TRI_STATE_PANEL_FAILURE``
    as a symmetric guard to its existing success flag check."""

    def test_bootstrap_checks_failure_flag(self) -> None:
        for path in BOOTSTRAP_SOURCES:
            src = _read(path)
            self.assertRegex(
                src,
                rf"window\.{FAILURE_FLAG}",
                msg=(
                    f"{path.relative_to(REPO_ROOT)}::start() does not read "
                    f"``window.{FAILURE_FLAG}``. Without this check the "
                    "bootstrap can't tell a still-pending loader from an "
                    "already-failed one; it will register a listener that "
                    "never fires and the panel stays hidden. Fix: add a "
                    "symmetric guard next to the existing ``window."
                    f"{SUCCESS_FLAG}`` short-circuit."
                ),
            )

    def test_bootstrap_checks_success_flag_still_present(self) -> None:
        """Guard the pre-existing TOCTOU fallback too, so a future
        refactor that moves both checks into a helper doesn't silently
        drop one of them."""
        for path in BOOTSTRAP_SOURCES:
            src = _read(path)
            self.assertRegex(
                src,
                rf"window\.{SUCCESS_FLAG}\b",
                msg=(
                    f"{path.relative_to(REPO_ROOT)}::start() no longer "
                    f"reads ``window.{SUCCESS_FLAG}``. The success-path "
                    "TOCTOU fallback (bootstrap arriving after the loader's "
                    "READY microtask) regressed; consumers on slow "
                    "handshake timings will miss mount."
                ),
            )


if __name__ == "__main__":
    unittest.main()
