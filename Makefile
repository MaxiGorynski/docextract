# ==============================================================================
# FILE: Makefile
# LOCATION: /docextract/Makefile (project root)
# ==============================================================================
#
# PURPOSE:
#   Convenience commands for DocExtract development and operations.
#   Provides shortcuts for common Docker Compose and Django commands.
#
# USAGE:
#   make help          Show available commands
#   make dev           Start development environment
#   make prod          Start production environment
#   make logs          View logs
#   make shell         Django shell
#   make test          Run tests
#
# ==============================================================================

.PHONY: help dev prod stop logs shell migrate test lint clean build deploy backup restore health

# Default compose file (override with COMPOSE_FILE=docker-compose.prod.yml)
COMPOSE_FILE ?= docker-compose.yml
DC = docker compose -f $(COMPOSE_FILE)

# Colours
BLUE := \033[0;34m
GREEN := \033[0;32m
YELLOW := \033[0;33m
NC := \033[0m

# =============================================================================
# Help
# =============================================================================

help:
	@echo ""
	@echo "$(GREEN)DocExtract - Available Commands$(NC)"
	@echo "=================================="
	@echo ""
	@echo "$(BLUE)Development:$(NC)"
	@echo "  make dev          Start development environment"
	@echo "  make stop         Stop all containers"
	@echo "  make logs         View container logs (follow)"
	@echo "  make logs-web     View web container logs"
	@echo "  make shell        Open Django shell"
	@echo "  make dbshell      Open PostgreSQL shell"
	@echo "  make bash         Open bash in web container"
	@echo ""
	@echo "$(BLUE)Database:$(NC)"
	@echo "  make migrate      Run database migrations"
	@echo "  make makemigrations  Create new migrations"
	@echo "  make superuser    Create superuser"
	@echo ""
	@echo "$(BLUE)Testing:$(NC)"
	@echo "  make test         Run all tests"
	@echo "  make lint         Run linting (ruff)"
	@echo "  make check        Run Django system checks"
	@echo ""
	@echo "$(BLUE)Production:$(NC)"
	@echo "  make prod         Start production environment"
	@echo "  make deploy       Run deployment script"
	@echo "  make deploy-init  Run initial deployment"
	@echo "  make backup       Create backup"
	@echo "  make restore      Show restore options"
	@echo "  make health       Run health check"
	@echo "  make ssl          Show SSL setup instructions"
	@echo ""
	@echo "$(BLUE)Maintenance:$(NC)"
	@echo "  make build        Rebuild containers"
	@echo "  make clean        Remove containers and volumes"
	@echo "  make prune        Docker system prune"
	@echo "  make collectstatic  Collect static files"
	@echo ""

# =============================================================================
# Development
# =============================================================================

dev:
	@echo "$(GREEN)Starting development environment...$(NC)"
	docker compose -f docker-compose.yml up

dev-d:
	@echo "$(GREEN)Starting development environment (detached)...$(NC)"
	docker compose -f docker-compose.yml up -d

stop:
	@echo "$(YELLOW)Stopping containers...$(NC)"
	$(DC) down

logs:
	$(DC) logs -f

logs-web:
	$(DC) logs -f web

logs-celery:
	$(DC) logs -f celery_worker 2>/dev/null || $(DC) logs -f celery

shell:
	$(DC) exec web python manage.py shell

dbshell:
	$(DC) exec db psql -U docextract docextract

bash:
	$(DC) exec web bash

# =============================================================================
# Database
# =============================================================================

migrate:
	@echo "$(GREEN)Running migrations...$(NC)"
	$(DC) exec web python manage.py migrate

makemigrations:
	@echo "$(GREEN)Creating migrations...$(NC)"
	$(DC) exec web python manage.py makemigrations

superuser:
	$(DC) exec web python manage.py createsuperuser

# =============================================================================
# Testing
# =============================================================================

test:
	@echo "$(GREEN)Running tests...$(NC)"
	$(DC) exec web python manage.py test

lint:
	@echo "$(GREEN)Running linter...$(NC)"
	$(DC) exec web ruff check . || echo "$(YELLOW)Ruff not installed$(NC)"

check:
	@echo "$(GREEN)Running Django checks...$(NC)"
	$(DC) exec web python manage.py check

# =============================================================================
# Production
# =============================================================================

prod:
	@echo "$(GREEN)Starting production environment...$(NC)"
	docker compose -f docker-compose.prod.yml up -d

prod-logs:
	docker compose -f docker-compose.prod.yml logs -f

deploy:
	@echo "$(GREEN)Running deployment...$(NC)"
	./scripts/deploy.sh

deploy-init:
	@echo "$(GREEN)Running initial deployment...$(NC)"
	./scripts/deploy.sh --init

backup:
	@echo "$(GREEN)Creating backup...$(NC)"
	./scripts/backup.sh

restore:
	@echo "$(YELLOW)Available backups:$(NC)"
	./scripts/restore.sh --list
	@echo ""
	@echo "$(YELLOW)To restore, run:$(NC)"
	@echo "  ./scripts/restore.sh --db backups/<db_file>.sql.gz"
	@echo "  ./scripts/restore.sh --media backups/<media_file>.tar.gz"

health:
	./scripts/health-check.sh

ssl:
	@echo "$(YELLOW)SSL Setup Instructions:$(NC)"
	@echo ""
	@echo "1. Run SSL setup:"
	@echo "   ./scripts/ssl-setup.sh --domain yourdomain.com --email admin@yourdomain.com"
	@echo ""
	@echo "2. Add to .env:"
	@echo "   SECURE_SSL_REDIRECT=true"
	@echo "   SESSION_COOKIE_SECURE=true"
	@echo "   CSRF_COOKIE_SECURE=true"
	@echo ""
	@echo "3. Restart:"
	@echo "   docker compose -f docker-compose.prod.yml restart"

# =============================================================================
# Maintenance
# =============================================================================

build:
	@echo "$(GREEN)Building containers...$(NC)"
	$(DC) build

build-no-cache:
	@echo "$(GREEN)Building containers (no cache)...$(NC)"
	$(DC) build --no-cache

clean:
	@echo "$(YELLOW)Removing containers and volumes...$(NC)"
	$(DC) down -v
	@echo "$(GREEN)Done$(NC)"

prune:
	@echo "$(YELLOW)Pruning Docker system...$(NC)"
	docker system prune -f
	@echo "$(GREEN)Done$(NC)"

collectstatic:
	$(DC) exec web python manage.py collectstatic --noinput

# =============================================================================
# Frontend (if applicable)
# =============================================================================

frontend-install:
	cd frontend && npm install

frontend-dev:
	cd frontend && npm run dev

frontend-build:
	cd frontend && npm run build

# =============================================================================
# Shortcuts
# =============================================================================

up: dev
down: stop
ps:
	$(DC) ps
restart:
	$(DC) restart