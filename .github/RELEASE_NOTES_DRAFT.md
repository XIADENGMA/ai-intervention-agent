# Release notes draft (post-v1.5.21 / candidate v1.5.22)

> Draft assembled by the assistant after the v1.5.21 tag, summarising the 20
> maintenance commits added on top of the release. This is **not** a published
> release; the file is committed under `.github/` only as a paste-ready
> artifact for whoever cuts the next minor.
>
> When ready to publish:
>
> 1. Bump version in `pyproject.toml`, `packages/vscode/package.json`,
>    `package-lock.json`, `CITATION.cff`.
> 2. Move `[Unreleased]` to `[1.5.22] - <date>` in `CHANGELOG.md`.
> 3. Tag `v1.5.22`, push, then paste **the body below** (everything under the
>    "What changed" heading) into GitHub Releases.
> 4. Delete this draft file (or replace with the next draft).

---

## What changed in v1.5.22

This is a **maintenance + community release** with **no behaviour changes**.
The shipped runtime is byte-identical to v1.5.21; everything else either
hardens regression coverage or fills in long-overdue community / packaging
metadata.

### Boundary-test hardening (+32 regression tests)

The v1.5.20 + v1.5.21 features all had silent gaps in their test coverage.
v1.5.22 closes them so future refactors cannot drift them undetected:

- **Server identity** — single-icon read failure isolation (one corrupt PNG
  must not nuke the whole `icons` list); `importlib.metadata` exception
  fallback to `0.0.0+local`.
- **`/api/system/open-config-file`** — empty `_resolve_allowed_paths()`,
  default target missing on disk, explicit editor uninstalled (graceful
  auto-detect fallback).
- **`/api/update-language`** — full contract: three valid languages, empty
  payload default, unknown / empty-string rejection, whitespace stripping,
  write-failure 500 path. (Was previously zero-coverage.)
- **`/manifest.webmanifest`** — PWA install banner regression point.
- **`/api/update-feedback-config`** — non-int countdown, `frontend_countdown=0`
  "disable timer" semantics, single-field updates, no-recognised-fields path,
  non-dict payload coercion, 500 with i18n message wrapping.
- **`predefined_options_defaults` normalization matrix** — bool / int / float /
  str-aliases / unknown types; truncate / pad-with-False length reconciliation.
- **`/api/tasks/<id>/close`** — happy / 404 / 500 (route was untested since
  the multi-task feature shipped).
- **IP validators** — `None` / non-string / empty-string early reject for
  `allowed_networks`; CIDR normalisation (`10.0.0.1/24` → `10.0.0.0/24`) for
  `blocked_ips`; IPv4-mapped IPv6 unwrap (`::ffff:10.0.0.1` → `10.0.0.1`) so
  the same physical host can't bypass blocklist via dual-stack representation.

Net effect: full-suite count rose from 2212 to 2244, overall line coverage
from 89.93% to 90.96%, and six key files now sit at 95%+.

### Packaging & marketplace metadata

- **PyPI Project-URLs**: added `Changelog` and `Release notes` to
  `pyproject.toml`. `pip show` and the PyPI sidebar now point straight to
  `CHANGELOG.md` and the GitHub Releases tab.
- **VSCode extension manifest**: added `license: MIT`, `homepage`, `bugs.url`,
  and 8 `keywords` (`mcp`, `claude`, `cursor`, `windsurf`, …) so marketplace
  search surfaces the extension on common AI workflow queries; License field
  no longer reads `(unknown)`.

### Community files (GitHub Community Standards 100% green)

- **`CITATION.cff` (CFF 1.2.0)** — GitHub's "Cite this repository" sidebar
  button now renders BibTeX / APA / RIS; Zotero & Zenodo plugins pick up
  correct metadata.
- **`SUPPORT.md` (bilingual)** — routes incoming questions by topic
  (defect / feature / discussion / security / packaging / docs) and lays out
  the maintainer-driven best-effort SLOs (1–3 day ack, 2-week silent-bump
  grace).

### Documentation

- **`docs/mcp_tools.{md,zh-CN.md}`** now document all three input shapes of
  `predefined_options` (simple `list[str]`, object `list[{label, default}]`,
  parallel-array `list[str]` + `predefined_options_defaults`). Previously
  only the simple form was documented; LLM clients had to read the source to
  discover the pre-selection capability shipped in v1.5.20.
- **`CONTRIBUTING.md`** clarifies the `✅` vs `🧪` test-commit emoji
  semantics: `🧪` for new / expanded test surface, `✅` for stabilising
  existing tests.

---

## How to install

PyPI:

```bash
pip install -U ai-intervention-agent
# or
uvx ai-intervention-agent@latest
```

VS Code Marketplace: search for `ai-intervention-agent`, or run
`code --install-extension xiadengma.ai-intervention-agent`.

## How to upgrade from v1.5.21

There are **no breaking changes**. Drop in the new wheel / extension and
restart the MCP server. No config migration required.

## Acknowledgements

Thanks to early adopters who reported missing tests and surfaced the
documentation gap on `predefined_options_defaults`.
