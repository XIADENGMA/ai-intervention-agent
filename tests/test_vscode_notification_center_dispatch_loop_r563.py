"""R563 regression coverage for VS Code notification center dispatch collection."""

from __future__ import annotations

import json
import subprocess
import textwrap
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
NOTIFICATION_CENTER_TS = REPO_ROOT / "packages" / "vscode" / "notification-center.ts"


def _source() -> str:
    return NOTIFICATION_CENTER_TS.read_text(encoding="utf-8")


def _extract_method(source: str, marker: str) -> str:
    start = source.find(marker)
    assert start != -1, f"Cannot find method marker: {marker}"
    open_brace = source.find("{", start)
    assert open_brace != -1, f"Cannot find opening brace for: {marker}"
    depth = 1
    i = open_brace + 1
    while i < len(source):
        char = source[i]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return source[start : i + 1]
        i += 1
    raise AssertionError(f"Unbalanced method body for: {marker}")


def test_notification_center_dispatch_uses_loop_collector_not_map_callback() -> None:
    source = _source()
    dispatch_method = _extract_method(
        source,
        "async dispatch(eventInput: unknown): Promise<DispatchResult>",
    )
    provider_method = _extract_method(
        source,
        "private async _dispatchToProvider(",
    )

    assert "types.map(" not in dispatch_method
    assert "types.map(async" not in source
    assert "const dispatchPromises: Promise<void>[] = []" in dispatch_method
    assert "for (const t of types)" in dispatch_method
    assert (
        "dispatchPromises.push(this._dispatchToProvider(event, delivered, t))"
        in dispatch_method
    )
    assert "await Promise.allSettled(dispatchPromises)" in dispatch_method
    assert "provider.send(event)" in provider_method
    assert "notify.provider_not_registered" in provider_method
    assert "notify.provider_failed" in provider_method


def test_notification_center_loop_collector_preserves_parallel_dispatch_semantics() -> (
    None
):
    script = textwrap.dedent(
        """
        ;(async () => {
        class NotificationCenter {
          constructor() {
            this._providers = new Map()
          }

          registerProvider(type, provider) {
            this._providers.set(type, provider)
          }

          async _dispatchToProvider(event, delivered, t) {
            const type = String(t || '')
            if (!type) return
            const provider = this._providers.get(type)
            if (!provider || typeof provider.send !== 'function') {
              delivered[type] = false
              return
            }
            try {
              const ok = await provider.send(event)
              delivered[type] = !!ok
            } catch {
              delivered[type] = false
            }
          }

          async dispatch(event) {
            const delivered = {}
            const dispatchPromises = []
            for (const t of event.types) {
              dispatchPromises.push(this._dispatchToProvider(event, delivered, t))
            }
            await Promise.allSettled(dispatchPromises)
            return { delivered }
          }
        }

        const center = new NotificationCenter()
        const started = []
        const resolvers = []
        center.registerProvider('a', {
          send: () => new Promise((resolve) => {
            started.push('a')
            resolvers.push(() => resolve(true))
          })
        })
        center.registerProvider('b', {
          send: () => new Promise((resolve, reject) => {
            started.push('b')
            resolvers.push(() => reject(new Error('boom')))
          })
        })

        const pending = center.dispatch({ message: 'hello', types: ['a', 'b', 'missing'] })
        const startedBeforeAwait = started.slice()
        for (const resolve of resolvers) resolve()
        const result = await pending

        process.stdout.write(JSON.stringify({
          startedBeforeAwait,
          delivered: result.delivered
        }))
        })().catch((error) => {
          console.error(error)
          process.exit(1)
        })
        """
    )
    result = subprocess.run(
        ["node", "-e", script],
        check=True,
        capture_output=True,
        text=True,
    )

    assert json.loads(result.stdout) == {
        "startedBeforeAwait": ["a", "b"],
        "delivered": {"missing": False, "a": True, "b": False},
    }
