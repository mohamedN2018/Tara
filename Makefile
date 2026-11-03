# =============================================================================
# Tara — developer command surface. Run `make help` for the list.
# All compose commands target infra/compose/docker-compose.yml.
# =============================================================================
SHELL := /bin/bash
COMPOSE := docker compose -f infra/compose/docker-compose.yml --env-file .env
SERVICE ?=
DB_SERVICES := identity profile graph media post feed chat marketplace notification search moderation admin ads
ALL_SERVICES := $(DB_SERVICES) realtime bff

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
migrate: ## Apply migrations on every service (web containers also do this at boot)
	@for s in $(DB_SERVICES); do echo "== $$s"; $(COMPOSE) exec -T $$s python manage.py migrate --noinput || exit 1; done

.PHONY: makemigrations
makemigrations: ## Generate migrations (SERVICE=post, default all); review and commit the files
	@for s in $(or $(SERVICE),$(DB_SERVICES)); do 		$(COMPOSE) run --rm --no-deps -v "$(PWD)/services/$$s:/app" -e RUN_MIGRATIONS=false $$s python manage.py makemigrations || exit 1; 	done

.PHONY: check-migrations
check-migrations: ## Fail if any model change has no committed migration
	@for s in $(DB_SERVICES); do echo "== $$s"; 		$(COMPOSE) run --rm --no-deps -e RUN_MIGRATIONS=false $$s python manage.py makemigrations --check --dry-run || exit 1; 	done

.PHONY: superuser
superuser: ## Create a Django superuser in identity
	$(COMPOSE) exec identity python manage.py createsuperuser

.PHONY: shell
shell: ## Open a shell in a service (SERVICE=identity default)
	$(COMPOSE) exec $(or $(SERVICE),identity) bash

.PHONY: test
test: ## Run tests in throwaway containers. SERVICE=post scopes to one service.
	@for s in $(or $(SERVICE),$(ALL_SERVICES)); do echo "== $$s"; scripts/test-service.sh $$s || exit 1; done

.PHONY: lock
lock: ## Regenerate constraints.txt files from the built images
	scripts/lock-deps.sh

.PHONY: smoke
smoke: ## End-to-end API check against the running stack
	python scripts/smoke_test.py

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

# ---- Phase 9: production readiness -----------------------------------------
.PHONY: check-deploy
check-deploy: ## Run Django's --deploy checks (incl. tara production-safety gate)
	$(COMPOSE) exec -e IDENTITY_DEBUG=false identity python manage.py check --deploy --fail-level WARNING

.PHONY: k8s-build
k8s-build: ## Render the identity Kustomize overlay (validate manifests)
	kubectl kustomize infra/k8s/overlays/identity

.PHONY: prom-check
prom-check: ## Validate Prometheus rules/config with dockerized promtool
	docker run --rm -v "$(PWD)/infra/observability:/work:ro" --entrypoint promtool \
		prom/prometheus:latest check rules /work/alerts.yml
