.DEFAULT_GOAL := help

UV ?= uv
IMAGE ?= endless:dev

.PHONY: help
help: ## List available targets
	@grep -hE '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-13s\033[0m %s\n", $$1, $$2}'

.PHONY: install
install: ## Sync dependencies into .venv
	$(UV) sync

.PHONY: up
up: ## Start local Postgres + Redis
	docker compose up -d

.PHONY: down
down: ## Stop local Postgres + Redis
	docker compose down

.PHONY: dev
dev: up ## Run the API with reload against local Postgres/Redis
	$(UV) run uvicorn app.main:app --reload --host 0.0.0.0 --port 8080

.PHONY: worker
worker: ## Run the Arq worker
	@echo "The worker entrypoint arrives in F0.6 Slice B (app/worker/main.py)."

.PHONY: migrate
migrate: ## Apply Alembic migrations up to head
	$(UV) run alembic upgrade head

.PHONY: revision
revision: ## Autogenerate a migration: make revision m="add catalog_products"
	$(UV) run alembic revision --autogenerate -m "$(m)"

.PHONY: lint
lint: ## ruff check + format --check
	$(UV) run ruff check app tests
	$(UV) run ruff format --check app tests

.PHONY: format
format: ## Apply ruff autofixes + formatting
	$(UV) run ruff check --fix app tests
	$(UV) run ruff format app tests

.PHONY: type
type: ## mypy --strict
	$(UV) run mypy

.PHONY: contracts
contracts: ## Enforce module boundary contracts (import-linter)
	$(UV) run lint-imports

.PHONY: test
test: ## Unit tests (no env vars, no docker needed)
	$(UV) run pytest -m "not integration"

.PHONY: integration
integration: ## Integration tests (real Postgres/Redis via testcontainers)
	$(UV) run pytest -m integration

.PHONY: build
build: ## Build the Docker image
	DOCKER_BUILDKIT=1 docker build -t $(IMAGE) .

.PHONY: check
check: lint type contracts test ## Everything CI runs
