"""Runtime checks for notification title-flash timer lifecycle."""

from __future__ import annotations

import json
import shutil
import subprocess
import textwrap
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
NOTIFICATION_MANAGER_JS = (
    REPO_ROOT
    / "src"
    / "ai_intervention_agent"
    / "static"
    / "js"
    / "notification-manager.js"
)


def _node_available() -> bool:
    return shutil.which("node") is not None


def _run_node(script: str) -> str:
    proc = subprocess.run(
        ["node", "-e", script],
        capture_output=True,
        check=False,
        text=True,
        timeout=15,
    )
    if proc.returncode != 0:
        raise AssertionError(
            f"node exited {proc.returncode}\nstdout={proc.stdout!r}\nstderr={proc.stderr!r}"
        )
    return proc.stdout


def _notification_harness(case_js: str) -> str:
    return textwrap.dedent(
        f"""
        const fs = require('fs');
        const vm = require('vm');
        const code = fs.readFileSync({str(NOTIFICATION_MANAGER_JS)!r}, 'utf8')
          + '\\nglobalThis.__notificationManager = notificationManager;';

        const intervals = [];
        const clearedIntervals = [];
        const titleHistory = [];
        let title = 'AI Intervention Agent';

        function setIntervalStub(fn, delay) {{
          const id = `interval-${{intervals.length + 1}}`;
          intervals.push({{ id, fn, delay, cleared: false }});
          return id;
        }}

        function clearIntervalStub(id) {{
          clearedIntervals.push(id);
          const interval = intervals.find((entry) => entry.id === id);
          if (interval) interval.cleared = true;
        }}

        function tick(id, count) {{
          const interval = intervals.find((entry) => entry.id === id);
          for (let i = 0; i < count; i += 1) {{
            if (!interval || interval.cleared) return;
            interval.fn();
          }}
        }}

        const sandbox = {{
          Audio: function Audio() {{}},
          Blob: function Blob(parts) {{
            this.size = String(parts && parts[0] ? parts[0] : '').length;
          }},
          Date,
          Error,
          JSON,
          Map,
          Math,
          Number,
          Object,
          Promise,
          RegExp,
          String,
          console: {{
            debug() {{}},
            error() {{}},
            info() {{}},
            log() {{}},
            warn() {{}},
          }},
          document: {{
            get title() {{
              return title;
            }},
            set title(value) {{
              title = String(value);
              titleHistory.push(title);
            }},
          }},
          localStorage: {{
            getItem() {{
              return null;
            }},
            setItem() {{}},
            removeItem() {{}},
          }},
          navigator: {{
            userAgent: 'node',
          }},
          setInterval: setIntervalStub,
          clearInterval: clearIntervalStub,
          setTimeout(fn) {{
            fn();
            return 1;
          }},
          clearTimeout() {{}},
          AIIA_I18N: {{
            t(key, params) {{
              if (key === 'notify.titleFlash') {{
                return `[Notification] ${{params.message}}`;
              }}
              return key;
            }},
          }},
          __clearedIntervals: clearedIntervals,
          __intervals: intervals,
          __tick: tick,
          __titleHistory: titleHistory,
        }};
        sandbox.window = sandbox;

        vm.createContext(sandbox);
        vm.runInContext(code, sandbox);

        (async () => {{
        {textwrap.indent(case_js, "  ")}
        }})().catch((err) => {{
          console.error(err && err.stack ? err.stack : err);
          process.exit(1);
        }});
        """
    )


@unittest.skipUnless(_node_available(), "node runtime unavailable")
def test_overlapping_flash_title_cancels_stale_interval_and_restores_real_title() -> (
    None
):
    script = _notification_harness(
        """
        const manager = sandbox.__notificationManager;

        manager.flashTitle('first');
        sandbox.__tick('interval-1', 1);
        const afterFirstTick = sandbox.document.title;

        manager.flashTitle('second');
        const afterSecondCall = {
          title: sandbox.document.title,
          cleared: [...sandbox.__clearedIntervals],
        };

        sandbox.__tick('interval-1', 10);
        sandbox.__tick('interval-2', 6);

        process.stdout.write(
          JSON.stringify({
            afterFirstTick,
            afterSecondCall,
            finalTitle: sandbox.document.title,
            clearedIntervals: sandbox.__clearedIntervals,
            intervals: sandbox.__intervals.map(({ id, delay, cleared }) => ({
              id,
              delay,
              cleared,
            })),
          })
        );
        """
    )

    assert json.loads(_run_node(script)) == {
        "afterFirstTick": "[Notification] first",
        "afterSecondCall": {
            "title": "AI Intervention Agent",
            "cleared": ["interval-1"],
        },
        "finalTitle": "AI Intervention Agent",
        "clearedIntervals": ["interval-1", "interval-2"],
        "intervals": [
            {"id": "interval-1", "delay": 1000, "cleared": True},
            {"id": "interval-2", "delay": 1000, "cleared": True},
        ],
    }
