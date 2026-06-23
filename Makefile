# =============================================================================
# Tara — developer command surface. Run `make help` for the list.
# All compose commands target infra/compose/docker-compose.yml.
# =============================================================================
SHELL := /bin/bash
COMPOSE := docker compose -f infra/compose/docker-compose.yml --env-file .env
SERVICE ?=

.DEFAULT_GOAL := help

.PHONY: help
help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-22s\033[0m %s\n", $$1, $$2}'

.PHONY: env
env: ## Create .env from .env.example if missing
	@test -f .env || (cp .env.example .env && echo "Created .env from .env.example")

.PHONY: up
up: env ## Start the foundation stack (core profile) in the background
	$(COMPOSE) --profile core up -d --build

.PHONY: up-full
up-full: env ## Start everything (all profiles)
	$(COMPOSE) --profile core --profile observability up -d --build

.PHONY: up-observability
up-observability: env ## Start Prometheus/Grafana/OTel collector
	$(COMPOSE) --profile observability up -d

.PHONY: down
down: ## Stop and remove containers (keeps volumes)
	$(COMPOSE) down

.PHONY: clean
clean: ## Stop and remove containers AND volumes (DESTROYS local data)
	$(COMPOSE) down -v

.PHONY: ps
ps: ## Show running services
	$(COMPOSE) ps

.PHONY: logs
logs: ## Tail logs. Use SERVICE=identity to scope.
	$(COMPOSE) logs -f $(SERVICE)

.PHONY: migrate
migrate: ## Run Django migrations for the identity service
	$(COMPOSE) exec identity python manage.py migrate --noinput

.PHONY: makemigrations
makemigrations: ## Generate migrations for the identity service
	$(COMPOSE) exec identity python manage.py makemigrations

.PHONY: superuser
superuser: ## Create a Django superuser in identity
	$(COMPOSE) exec identity python manage.py createsuperuser

.PHONY: shell
shell: ## Open a shell in a service (SERVICE=identity default)
	$(COMPOSE) exec $(or $(SERVICE),identity) bash

.PHONY: test
test: ## Run tests. Use SERVICE=identity to scope to one service.
	@if [ "$(SERVICE)" = "bff" ]; then \
		cd services/bff && pytest -q; \
	else \
		cd services/identity && pytest -q; \
	fi

.PHONY: lint
lint: ## Lint Python (ruff) across libs and services
	ruff check libs services
	ruff format --check libs services

.PHONY: fmt
fmt: ## Auto-format Python (ruff)
	ruff format libs services
	ruff check --fix libs services

.PHONY: openapi
openapi: ## Dump the Identity OpenAPI schema to stdout
	$(COMPOSE) exec identity python manage.py spectacular --file /tmp/openapi.yaml && \
		$(COMPOSE) exec identity cat /tmp/openapi.yaml

.PHONY: seed
seed: ## Load synthetic development data (no fake "production" data)
	$(COMPOSE) exec identity python manage.py seed_dev_data
