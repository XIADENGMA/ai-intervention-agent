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

.PHONY: help install lint test ci coverage docs docs-check vscode-check pre-commit clean

# Default goal: print the help table so a fresh checkout's `make` is informative
# instead of surprising. Pinning this is more robust than relying on Make's
# implicit "first target" behaviour.
.DEFAULT_GOAL := help

help:
	@echo "AI Intervention Agent · Makefile entry points"
	@echo ""
	@echo "  make install        install dev deps via uv (--all-groups)"
	@echo "  make lint           ruff format + check + ty type-check"
	@echo "  make test           pytest only (no i18n / minify gates)"
	@echo "  make ci             full CI Gate (ruff + ty + 8x i18n + minify + pytest + red-team)"
	@echo "  make coverage       full CI Gate + coverage XML / term-missing report"
	@echo "  make docs           regenerate docs/api/ + docs/api.zh-CN/ from Python source"
	@echo "  make docs-check     verify docs/api/ + docs/api.zh-CN/ are in sync (no writes)"
	@echo "  make vscode-check   full CI Gate + VS Code extension test + VSIX build"
	@echo "  make pre-commit     run all pre-commit hooks against all files"
	@echo "  make clean          remove generated build / coverage / lint artefacts"
	@echo ""
	@echo "All targets are thin wrappers; the source of truth lives in"
	@echo "scripts/ci_gate.py and friends. See scripts/README.md for the index."

install:
	uv sync --all-groups

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

clean:
	rm -rf build dist *.egg-info
	rm -rf .coverage .coverage.* coverage.xml htmlcov
	rm -rf .ruff_cache .pytest_cache .mypy_cache .ty_cache
	rm -f packages/vscode/*.vsix
