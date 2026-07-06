# =============================================================================
# Paismart RAG - Makefile
# =============================================================================
# Common development commands for the Paismart RAG project.
#
# Usage:
#   make up          # Start all infrastructure services
#   make down        # Stop all services
#   make logs        # Follow service logs
#   make ps          # List service status
#   make test        # Run tests
#   make migrate     # Run database migrations
#   make shell-mysql # Open MySQL shell
#   make shell-redis # Open Redis CLI
#   make shell-es    # Open Elasticsearch shell
#   make clean       # Remove all volumes and reset
# =============================================================================

SHELL := /bin/bash
.ONESHELL:
.SHELLFLAGS := -eu -o pipefail -c
.DEFAULT_GOAL := help

# ---------------------------------------------------------------------------
# Project configuration
# ---------------------------------------------------------------------------
PROJECT_NAME   := paismart
COMPOSE_FILE    = docker-compose.yml
COMPOSE_DEV     = docker-compose.dev.yml
COMPOSE_FILES   = -f $(COMPOSE_FILE) -f $(COMPOSE_DEV)
ENV_FILE        = .env

# ---------------------------------------------------------------------------
# Help (default target)
# ---------------------------------------------------------------------------
.PHONY: help
help:
	@echo "Paismart RAG - Development Makefile"
	@echo "==================================="
	@echo ""
	@echo "Infrastructure:"
	@echo "  make up              Start all services (detached)"
	@echo "  make down            Stop all services"
	@echo "  make restart         Restart all services"
	@echo "  make ps              List service status"
	@echo "  make logs            Follow service logs"
	@echo "  make logs-%          Follow logs for a specific service (e.g., make logs-mysql)"
	@echo "  make build           Build custom Docker images"
	@echo ""
	@echo "Database:"
	@echo "  make migrate         Run Alembic migrations"
	@echo "  make shell-mysql     Open MySQL CLI"
	@echo "  make shell-redis     Open Redis CLI"
	@echo "  make shell-es        Open Elasticsearch console"
	@echo ""
	@echo "Development:"
	@echo "  make test            Run all tests"
	@echo ""
	@echo "Initialization:"
	@echo "  make init            Initialize database + Milvus collection"
	@echo "  make init-db         Initialize database (Alembic migrations)"
	@echo "  make init-milvus     Initialize Milvus collection"
	@echo "# (ES index + admin are auto-created on app startup)"
	@echo ""
	@echo "Housekeeping:"
	@echo "  make clean           Remove all volumes (WARNING: destroys data)"
	@echo "  make clean-images    Remove built Docker images"

# ---------------------------------------------------------------------------
# Prerequisites check
# ---------------------------------------------------------------------------
.PHONY: _check-env
_check-env:
	@if [ ! -f "$(ENV_FILE)" ]; then
		echo "[ERROR] .env file not found. Copy .env.example to .env first:" >&2
		echo "        cp .env.example .env" >&2
		exit 1
	fi

.PHONY: _check-compose
_check-compose:
	@if ! command -v docker &>/dev/null; then
		echo "[ERROR] docker is not installed." >&2
		exit 1
	fi

# ---------------------------------------------------------------------------
# Infrastructure lifecycle
# ---------------------------------------------------------------------------
.PHONY: up
up: _check-env _check-compose
	docker compose $(COMPOSE_FILES) up -d
	@echo ""
	@echo "Services started. Run 'make ps' to check status."
	@echo "View logs with 'make logs'."

.PHONY: down
down: _check-compose
	docker compose $(COMPOSE_FILES) down

.PHONY: restart
restart: down up

.PHONY: ps
ps: _check-compose
	docker compose $(COMPOSE_FILES) ps

.PHONY: logs
logs: _check-compose
	docker compose $(COMPOSE_FILES) logs -f

logs-%: _check-compose
	@docker compose $(COMPOSE_FILES) logs -f "$*"

.PHONY: build
build: _check-env _check-compose
	docker compose $(COMPOSE_FILES) build

# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------
.PHONY: migrate
migrate: _check-env
	@echo "[INFO] Running Alembic migrations ..."
	cd backend && alembic upgrade head
	@echo "[OK]   Migrations completed."

.PHONY: shell-mysql
shell-mysql: _check-env _check-compose
	@echo "[INFO] Connecting to MySQL ..."
	docker compose $(COMPOSE_FILES) exec mysql mysql \
		-u"$${MYSQL_USER:-paismart}" \
		-p"$${MYSQL_PASSWORD:?}" \
		"$${MYSQL_DATABASE:-paismart}"

.PHONY: shell-redis
shell-redis: _check-env _check-compose
	@echo "[INFO] Connecting to Redis ..."
	docker compose $(COMPOSE_FILES) exec redis redis-cli \
		-a "$${REDIS_PASSWORD:?}"

.PHONY: shell-es
shell-es: _check-compose
	@echo "[INFO] Opening Elasticsearch console ..."
	@printf 'Try:  GET /_cluster/health\n      GET /document_chunks/_mapping\n'
	docker compose $(COMPOSE_FILES) exec elasticsearch bash

# ---------------------------------------------------------------------------
# Development
# ---------------------------------------------------------------------------
.PHONY: test
test:
	@echo "[INFO] Running tests ..."
	python -m pytest tests/ -v --tb=short $(ARGS)
	@echo "[OK]   Tests completed."

# Removed: build-backend / build-frontend (no Dockerfiles exist)
# Use docker compose build for custom infra images.

# ---------------------------------------------------------------------------
# Initialization scripts
# ---------------------------------------------------------------------------
.PHONY: init-db
init-db: _check-env
	@echo "[INFO] Initializing database ..."
	./scripts/init-db.sh
	@echo "[OK]   Database initialized."

# Removed: init-es (code auto-creates index on startup via init_search_index())

.PHONY: init-milvus
init-milvus: _check-env
	@echo "[INFO] Initializing Milvus collection ..."
	./scripts/init-milvus.sh
	@echo "[OK]   Milvus initialized."

# Removed: init-admin (bootstrap_service.run_bootstrap() runs on app startup)

.PHONY: init
init: init-db init-milvus
	@echo "[OK]   All initialization completed."

# ---------------------------------------------------------------------------
# Housekeeping
# ---------------------------------------------------------------------------
.PHONY: clean
clean: _check-compose down
	@echo "[WARN] Removing all volumes ..."
	docker compose $(COMPOSE_FILES) down -v
	@echo "[OK]   Volumes removed."

.PHONY: clean-images
clean-images:
	@echo "[INFO] Removing built images ..."
	docker rmi paismart-backend:latest 2>/dev/null || true
	docker rmi paismart-elasticsearch:8.10.4 2>/dev/null || true
	@echo "[OK]   Images removed."
