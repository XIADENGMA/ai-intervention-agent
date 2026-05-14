# remote_environment

> 英文 signature-only 版本（仅函数 / 类签名速查）：[`docs/api/remote_environment.md`](../api/remote_environment.md)

R225 / Cycle 12: SSH / WSL remote-environment detection.

This module exists to close a UX gap surfaced in the
``Related projects`` section of the README: ``mcp-feedback-enhanced``
advertises "intelligent SSH Remote / WSL detection" while AIIA's
startup prints a bare ``请在浏览器中打开: http://127.0.0.1:8080`` —
which is **unreachable** from the user's local machine when the
process is running on an SSH-attached remote host with the default
``127.0.0.1`` bind. Users hit this silently and waste minutes
chasing "why can't I reach the URL?".

The fix is purely informative: detect SSH / WSL via well-established
environment markers and let the startup banner emit an actionable
hint. Behavior is **not changed** — we never auto-rewrite ``host``
or auto-forward ports; that would be a footgun for the LAN-only and
mDNS-enabled paths. We only *tell* the user what to do.

Design rules:

* **Pure function** — the public ``detect_remote_environment()``
  reads ``os.environ`` and at most one well-known file
  (``/proc/version`` for WSL1 detection); no socket, no subprocess.
* **Best-effort** — every probe is wrapped; missing files /
  permission errors silently degrade to "not detected" so the
  detector itself can never crash the startup path.
* **Conservative false-positive policy** — we only flag SSH when at
  least one of ``SSH_CONNECTION`` / ``SSH_CLIENT`` is set (these
  are propagated by ``sshd`` on connection accept). We never sniff
  ``SHELL`` / ``TERM`` style heuristics — too many false positives
  for local tmux / mosh users.

The startup integration (``web_ui.py``) calls this once and prints
only when the detection result implies the user might be confused
by the default bind. The detector itself is silent.

## 函数

### `_detect_ssh() -> tuple[bool, str | None]`

SSH detection via ``sshd``-propagated env vars.

``SSH_CONNECTION`` is the canonical OpenSSH variable
(``<client_ip> <client_port> <server_ip> <server_port>`` format).
``SSH_CLIENT`` is a slightly older variant; some hardened sshd
configs strip ``SSH_CONNECTION`` but leave ``SSH_CLIENT``, so we
check both for robustness. Empty strings (env var set but blank)
don't count — a non-empty value is required.

``SSH_TTY`` is intentionally **not** used as a signal: long-running
services started under systemd from an SSH session typically have
no TTY, but ``SSH_CONNECTION`` is still inherited by the unit's
``Environment=`` block if propagated. Using ``SSH_TTY`` would miss
those cases.

### `_detect_wsl() -> tuple[bool, str | None]`

WSL detection via env vars (WSL2) plus ``/proc/version`` fallback.

WSL2 distros export ``WSL_DISTRO_NAME`` and ``WSL_INTEROP`` by
default; either is sufficient. WSL1 (rare nowadays but still in
use on locked-down corporate Windows fleets) doesn't set those,
so we fall back to reading ``/proc/version`` and searching for
the substring ``"microsoft"`` (both ``Microsoft`` and
``microsoft-standard`` kernel build strings match case-insensitively).

Probing the file is wrapped — on non-Linux hosts the file
doesn't exist (raises ``FileNotFoundError`` / ``PermissionError``
on some sandbox setups), and on rare corrupted reads we get
``UnicodeDecodeError``. Any of those silently downgrade to
"not WSL", which is the conservative default.

### `detect_remote_environment() -> RemoteEnvironment`

Public entry-point. See module docstring for invariants.

Returns a fully-populated ``RemoteEnvironment`` dict — callers
should treat the result as read-only and never mutate it; future
versions may switch to ``MappingProxyType`` for enforcement.

## 类

### `class RemoteEnvironment`

Detection result schema. Keys are stable contract for tests
and for the startup banner integration in ``web_ui.py``.

``is_ssh`` — process appears to be inside an SSH session.
``is_wsl`` — process appears to be running inside Microsoft
WSL (1 or 2).
``ssh_source`` — ``"SSH_CONNECTION"`` / ``"SSH_CLIENT"`` /
``None`` indicating which env var triggered detection. Useful
for diagnostic logging.
``wsl_source`` — ``"WSL_DISTRO_NAME"`` / ``"WSL_INTEROP"`` /
``"/proc/version"`` / ``None`` indicating which probe matched.
