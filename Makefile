.DEFAULT_GOAL := help
.PHONY: help check lint format typecheck test test-core live build docs bench bench-data clean

help: ## List the targets
	@awk 'BEGIN {FS = ":.*## "} /^[a-z-]+:.*## / {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)

check: lint typecheck test ## The gate of CI: lint, typecheck, test

lint: ## ruff check and format check
	uv run ruff check
	uv run ruff format --check

format: ## Format the code and fix what ruff can
	uv run ruff format
	uv run ruff check --fix

typecheck: ## mypy --strict
	uv run --all-extras mypy

test: ## pytest with coverage, every extra installed (no key, no network)
	uv run --all-extras pytest --cov --cov-report=term-missing

# What most users install. Its own environment, so .venv keeps the extras:
# the tests of the extras skip, the rest must pass.
test-core: ## pytest on the core alone, without the extras, as CI does
	UV_PROJECT_ENVIRONMENT=.venv-core uv run --locked pytest -p no:cacheprovider
	UV_PROJECT_ENVIRONMENT=.venv-core uv run --locked firms --help > /dev/null

bench: ## Score the known cases offline, as CI does: any change from results.json fails
	uv run --all-extras python -m benchmarks.run --check

# The open country archives (~30 MB, once, into FIRMS_DATA_DIR), EFFIS perimeters
# and WorldCover windows: no key needed.
bench-data: ## Download and crop the data of the known cases again, then score them
	uv run --all-extras python -m benchmarks.fetch
	uv run --all-extras python -m benchmarks.run

# The real service: the archive's columns, the missing-data table and, with
# FIRMS_MAP_KEY (environment or .env), the key and a day of the area API.
live: ## Test against the real FIRMS service, as the weekly CI job does
	uv run pytest -m live -v

build: ## The wheel and the sdist, in dist/
	uv build

# The same site the Pages workflow publishes: the hand-written pages and the
# API reference generated from the docstrings (never committed).
docs: ## The site with the API reference, in _site/
	rm -rf _site
	mkdir -p _site
	cp docs/*.html docs/*.css docs/llms.txt _site/
	cp -r docs/images _site/images
	uv run --all-extras --group docs pdoc firms_client -o _site/api

clean: ## Remove what the targets build (downloaded archives stay in the data directory)
	rm -rf dist _site .venv-core htmlcov .coverage .pytest_cache .mypy_cache .ruff_cache
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
