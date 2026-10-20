# Dependency Security Audit Gate

## Command

Use one entrypoint for local, PR, and release dependency security checks:

```bash
uv run python scripts/dependency_audit.py --gate local
uv run python scripts/dependency_audit.py --gate pr
uv run python scripts/dependency_audit.py --gate release
```

`make dependency-audit` runs the local form.

## Gate Levels

| Context | Command | Gate decision |
| --- | --- | --- |
| Local development | `uv run python scripts/dependency_audit.py --gate local` | Hard-fails Python vulnerabilities and unaccepted npm findings. Documented npm dev-tool exceptions are warnings. |
| Pull requests | `uv run python scripts/dependency_audit.py --gate pr` plus GitHub Dependency Review | Hard-fails unaccepted findings. Dependency Review also blocks new moderate-or-higher vulnerable dependencies introduced by the PR diff. |
| Release | `uv run python scripts/dependency_audit.py --gate release` | Hard-fails Python vulnerabilities and unaccepted npm findings before publishing artifacts. Accepted npm dev-tool exceptions must remain documented and absent from the VS Code package dry-run. |

## Accepted npm Exceptions

No npm finding is accepted at the moment: `npm audit --audit-level=moderate`
is clean. The 2026-06-21 test-runner exception
([`npm-audit-2026-06-21.md`](npm-audit-2026-06-21.md): `@vscode/test-cli`,
`mocha`, `diff`, `serialize-javascript`) was closed on 2026-10-20 and removed
from the script, so a regression on any of those packages now fails the gate.

The script keeps one narrow valve, triaged in
[`npm-audit-2026-07-26.md`](npm-audit-2026-07-26.md). A finding on the
`brace-expansion` dev-toolchain chain (`brace-expansion`, `minimatch`, `glob`,
`mocha`, `eslint`, `@eslint/config-array`, `@eslint/eslintrc`) is accepted
only when every advisory it carries is one of the triaged GHSA ids, or when it
is a transitive marker pointing at that chain. It also needs
`npm pack --workspace ai-intervention-agent --dry-run --json` to list no
`node_modules/`, `mocha`, or `brace-expansion` path. Any other npm audit
finding is a hard failure.

## Python Audit

The wrapper exports locked third-party Python requirements with all dependency
groups and extras enabled:

```bash
uv export --format requirements-txt --all-groups --all-extras --no-emit-project --no-hashes
```

It audits the exported requirements with:

```bash
uvx pip-audit -r <exported-requirements> --format json --no-deps --disable-pip
```

Any `pip-audit` vulnerability is unresolved by default and fails every gate
level. The local editable project itself is intentionally omitted because it is
not a third-party dependency and would otherwise add resolver noise rather than
vulnerability coverage.
