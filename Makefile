# AI Intervention Agent · Makefile entry points
#
# Thin wrappers around `scripts/ci_gate.py` and friends so contributors get
# `make test` / `make ci` / `make docs` muscle memory instead of remembering
# four flavours of `uv run …`. Every target delegates to an existing
# script — no duplicated logic, no drift surface.
#
# Convention (per `.editorconfig::[Makefile] indent_style = tab`):
#   - Recipes use TAB indentation; do not convert to spaces or `make` will
#     bail out with "missing separator" errors.
#   - `.PHONY` lists every target so they always re-run regardless of the
#     presence of same-named files.
#
# Discoverability:
#   `make` (no args) → renders the help table; same as `make help`.

.PHONY: help install install-hooks lint test ci coverage docs docs-check vscode-check pre-commit release-check release-check-cve clean

# Default goal: print the help table so a fresh checkout's `make` is informative
# instead of surprising. Pinning this is more robust than relying on Make's
# implicit "first target" behaviour.
.DEFAULT_GOAL := help

help:
	@echo "AI Intervention Agent · Makefile entry points"
	@echo ""
	@echo "  make install           install dev deps via uv (--all-groups)"
	@echo "  make install-hooks     install pre-commit + pre-push git hooks (R209 / F-release-2)"
	@echo "  make lint              ruff format + check + ty type-check"
	@echo "  make test              pytest only (no i18n / minify gates)"
	@echo "  make ci                full CI Gate (ruff + ty + 8x i18n + minify + pytest + red-team)"
	@echo "  make coverage          full CI Gate + coverage XML / term-missing report"
	@echo "  make docs              regenerate docs/api/ + docs/api.zh-CN/ from Python source"
	@echo "  make docs-check        verify docs/api/ + docs/api.zh-CN/ are in sync (no writes)"
	@echo "  make vscode-check      full CI Gate + VS Code extension test + VSIX build"
	@echo "  make pre-commit        run all pre-commit hooks against all files"
	@echo "  make release-check     verify <=3 unpushed v*.*.* tags before 'git push --follow-tags'"
	@echo "  make release-check-cve same as release-check, plus R185 Dependabot CVE gate"
	@echo "                         (requires 'gh' CLI logged in; blocks on critical/high open alerts)"
	@echo "  make clean             remove generated build / coverage / lint artefacts"
	@echo ""
	@echo "All targets are thin wrappers; the source of truth lives in"
	@echo "scripts/ci_gate.py and friends. See scripts/README.md for the index."

install:
	uv sync --all-groups

# R209 / Cycle 10 · F-release-2: install both pre-commit and pre-push
# git hooks so the R206 13-step pre-flight checklist's automation-able
# steps (step 6: check_tag_push_safety.py) are enforced rather than
# memory-dependent. Idempotent — safe to re-run after `make install`.
install-hooks:
	uv run pre-commit install --hook-type pre-commit --hook-type pre-push

lint:
	uv run ruff format .
	uv run ruff check .
	uv run ty check .

test:
	uv run pytest -q

ci:
	uv run python scripts/ci_gate.py

coverage:
	uv run python scripts/ci_gate.py --with-coverage

docs:
	uv run python scripts/generate_docs.py --lang en
	uv run python scripts/generate_docs.py --lang zh-CN

docs-check:
	uv run python scripts/generate_docs.py --lang en --check
	uv run python scripts/generate_docs.py --lang zh-CN --check

vscode-check:
	uv run python scripts/ci_gate.py --with-vscode

pre-commit:
	uv run pre-commit run --all-files

release-check:
	uv run python scripts/check_tag_push_safety.py

# R185: opt-in CVE gate variant — same tag-count check, plus Dependabot
# alerts at critical/high severity become release blockers. Requires
# `gh` CLI logged in. Use this from CI / before tagging a release; the
# default `release-check` target stays byte-identical so existing
# pipelines aren't disrupted.
release-check-cve:
	uv run python scripts/check_tag_push_safety.py --check-cve

clean:
	rm -rf build dist *.egg-info
	rm -rf .coverage .coverage.* coverage.xml htmlcov
	rm -rf .ruff_cache .pytest_cache .mypy_cache .ty_cache
	rm -f packages/vscode/*.vsix
