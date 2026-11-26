.DEFAULT_GOAL := help
.PHONY: help check lint format typecheck test test-core live build docs bench faithful bench-data notebooks notebooks-offline up demo down logs clean

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
	uv run --all-extras --group demo mypy

test: ## pytest with coverage, every extra installed (no key, no network)
	uv run --all-extras --group demo pytest --cov --cov-report=term-missing

# What most users install. Its own environment, so .venv keeps the extras:
# the tests of the extras skip, the rest must pass.
test-core: ## pytest on the core alone, without the extras, as CI does
	UV_PROJECT_ENVIRONMENT=.venv-core uv run --locked pytest -p no:cacheprovider
	UV_PROJECT_ENVIRONMENT=.venv-core uv run --locked firms --help > /dev/null

bench: ## Score the known cases offline, as CI does: any change from results.json fails
	uv run --all-extras python -m benchmarks.run --check

# The open country archives (~30 MB, once, into $DATA_ROOT/firms-client), EFFIS perimeters
# and WorldCover windows: no key needed.
faithful: ## Score the hand answers against the facts, as CI does (no key, no network)
	uv run --all-extras python -m benchmarks.faithful score --check

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
	cat docs/llms.txt README.md skills/firms-client/SKILL.md > _site/llms-full.txt
	cp -r docs/images _site/images
	uv run --all-extras --group docs pdoc firms_client -o _site/api

# The notebooks are stored with their outputs. 01 and 02 download the yearly
# archives (no key, about 2 MB a year, once); 03 and 04 run on the crops of
# the benchmark, offline, as CI does.
notebooks: ## Run every notebook again, outputs saved in place
	cd notebooks && for nb in *.ipynb; do \
		echo "== $$nb"; \
		uv run --all-extras --group examples jupyter nbconvert --to notebook --execute --inplace "$$nb" || exit 1; \
	done

OFFLINE = 03_how_much_to_trust.ipynb 04_cells_for_a_model.ipynb
notebooks-offline: ## Run the notebooks that need no network (03, 04), as CI does
	cd notebooks && for nb in $(OFFLINE); do \
		echo "== $$nb"; \
		uv run --all-extras --group examples jupyter nbconvert --to notebook --execute --stdout "$$nb" > /dev/null || exit 1; \
	done

# Docker: every setting is in .env (cp .env.example .env). Ports on 127.0.0.1 only.
up: ## The page, the notebooks and the MCP server in Docker (http://127.0.0.1:3005)
	docker compose --profile notebook --profile mcp up -d --build
	@echo "page:      http://127.0.0.1:$${FIRMS_UI_PORT:-3005}"
	@echo "notebooks: http://127.0.0.1:$${FIRMS_NOTEBOOK_PORT:-8890} (token: make logs)"
	@echo "MCP:       http://127.0.0.1:$${FIRMS_MCP_PORT:-8769}/mcp"

demo: ## Only the page (the API and the UI): no key needed
	docker compose up -d --build api ui
	@echo "page: http://127.0.0.1:$${FIRMS_UI_PORT:-3005}"

down: ## Stop the containers (the downloaded archives stay in the volume)
	docker compose --profile notebook --profile mcp --profile tools down

logs: ## Follow the logs of the containers
	docker compose --profile notebook --profile mcp logs -f --tail=50

clean: ## Remove what the targets build (downloaded archives stay in the data directory)
	rm -rf dist _site .venv-core htmlcov .coverage .pytest_cache .mypy_cache .ruff_cache
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
