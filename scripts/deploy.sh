#!/bin/bash
# ==============================================================================
# FILE: deploy.sh
# LOCATION: /docextract/scripts/deploy.sh
# ==============================================================================
#
# PURPOSE:
#   Automated deployment script for DocExtract production environment.
#   Handles code updates, migrations, static files, and service restarts
#   with zero-downtime deployment strategy.
#
# USAGE:
#   Initial deployment:
#       ./scripts/deploy.sh --init
#
#   Update deployment:
#       ./scripts/deploy.sh
#
#   With specific branch:
#       ./scripts/deploy.sh --branch feature-branch
#
# OPTIONS:
#   --init      Run initial setup (create directories, first migration)
#   --branch    Specify git branch to deploy (default: main)
#   --no-pull   Skip git pull (useful for local testing)
#   --help      Show this help message
#
# PREREQUISITES:
#   - Docker and Docker Compose installed
#   - Git repository cloned
#   - .env file configured with production values
#   - SSH access to server (for remote deployment)
#
# DEPLOYMENT STRATEGY:
#   1. Pull latest code from git
#   2. Build new Docker images
#   3. Run database migrations
#   4. Collect static files
#   5. Restart application services (web, celery)
#   6. Verify deployment with health check
#
# ROLLBACK:
#   If deployment fails, run:
#       ./scripts/deploy.sh --rollback
#
# LOGGING:
#   Deployment logs are written to ./logs/deploy_YYYYMMDD_HHMMSS.log
#
# ==============================================================================

set -e  # Exit on any error

# =============================================================================
# Configuration
# =============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
COMPOSE_FILE="docker-compose.prod.yml"
LOG_DIR="$PROJECT_DIR/logs"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
LOG_FILE="$LOG_DIR/deploy_$TIMESTAMP.log"
BRANCH="main"
DO_PULL=true
INIT_MODE=false
ROLLBACK_MODE=false

# Colours for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Colour

# =============================================================================
# Functions
# =============================================================================

log() {
    echo -e "${GREEN}[$(date '+%Y-%m-%d %H:%M:%S')]${NC} $1" | tee -a "$LOG_FILE"
}

warn() {
    echo -e "${YELLOW}[$(date '+%Y-%m-%d %H:%M:%S')] WARNING:${NC} $1" | tee -a "$LOG_FILE"
}

error() {
    echo -e "${RED}[$(date '+%Y-%m-%d %H:%M:%S')] ERROR:${NC} $1" | tee -a "$LOG_FILE"
    exit 1
}

show_help() {
    head -50 "$0" | grep -E "^#" | sed 's/^# //' | sed 's/^#//'
    exit 0
}

check_prerequisites() {
    log "Checking prerequisites..."

    # Check Docker
    if ! command -v docker &> /dev/null; then
        error "Docker is not installed"
    fi

    # Check Docker Compose
    if ! docker compose version &> /dev/null; then
        error "Docker Compose is not installed"
    fi

    # Check .env file
    if [ ! -f "$PROJECT_DIR/.env" ]; then
        error ".env file not found. Copy from .env.production.example and configure."
    fi

    # Check compose file
    if [ ! -f "$PROJECT_DIR/$COMPOSE_FILE" ]; then
        error "$COMPOSE_FILE not found"
    fi

    log "Prerequisites check passed"
}

create_directories() {
    log "Creating required directories..."

    mkdir -p "$LOG_DIR"
    mkdir -p "$PROJECT_DIR/certbot/conf"
    mkdir -p "$PROJECT_DIR/certbot/www"
    mkdir -p "$PROJECT_DIR/nginx/conf.d"

    log "Directories created"
}

pull_code() {
    if [ "$DO_PULL" = true ]; then
        log "Pulling latest code from branch: $BRANCH..."
        cd "$PROJECT_DIR"
        git fetch origin
        git checkout "$BRANCH"
        git pull origin "$BRANCH"
        log "Code updated to: $(git rev-parse --short HEAD)"
    else
        log "Skipping git pull (--no-pull flag set)"
    fi
}

build_images() {
    log "Building Docker images..."
    cd "$PROJECT_DIR"
    docker compose -f "$COMPOSE_FILE" build --no-cache
    log "Images built successfully"
}

run_migrations() {
    log "Running database migrations..."
    cd "$PROJECT_DIR"
    docker compose -f "$COMPOSE_FILE" run --rm web python manage.py migrate --noinput
    log "Migrations completed"
}

collect_static() {
    log "Collecting static files..."
    cd "$PROJECT_DIR"
    docker compose -f "$COMPOSE_FILE" run --rm web python manage.py collectstatic --noinput
    log "Static files collected"
}

restart_services() {
    log "Restarting application services..."
    cd "$PROJECT_DIR"

    # Restart web, celery_worker, and celery_beat without affecting db/redis
    docker compose -f "$COMPOSE_FILE" up -d --no-deps web celery_worker celery_beat

    log "Services restarted"
}

start_all_services() {
    log "Starting all services..."
    cd "$PROJECT_DIR"
    docker compose -f "$COMPOSE_FILE" up -d
    log "All services started"
}

verify_deployment() {
    log "Verifying deployment..."

    # Wait for services to be ready
    sleep 15

    # Check health endpoint
    cd "$PROJECT_DIR"

    # Try to reach health endpoint through nginx
    HEALTH_CHECK=$(docker compose -f "$COMPOSE_FILE" exec -T web python -c "
import urllib.request
try:
    response = urllib.request.urlopen('http://localhost:8000/health/', timeout=10)
    print(response.read().decode())
except Exception as e:
    print(f'FAILED: {e}')
    exit(1)
")

    if echo "$HEALTH_CHECK" | grep -q "healthy"; then
        log "Health check passed: $HEALTH_CHECK"
    else
        error "Health check failed: $HEALTH_CHECK"
    fi

    # Show running containers
    log "Running containers:"
    docker compose -f "$COMPOSE_FILE" ps | tee -a "$LOG_FILE"
}

rollback() {
    log "Rolling back to previous version..."
    cd "$PROJECT_DIR"

    PREVIOUS_COMMIT=$(git rev-parse HEAD~1)
    log "Rolling back to commit: $PREVIOUS_COMMIT"

    git checkout "$PREVIOUS_COMMIT"

    docker compose -f "$COMPOSE_FILE" build
    docker compose -f "$COMPOSE_FILE" up -d --no-deps web celery_worker celery_beat

    log "Rollback completed. Verify manually and consider running migrations if needed."
}

init_deployment() {
    log "Running initial deployment setup..."

    create_directories

    if [ "$DO_PULL" = true ]; then
        pull_code
    fi

    build_images

    log "Starting database and redis first..."
    cd "$PROJECT_DIR"
    docker compose -f "$COMPOSE_FILE" up -d db redis

    # Wait for database to be ready
    log "Waiting for database to be ready..."
    sleep 10

    run_migrations
    collect_static

    log "Starting all services..."
    start_all_services

    verify_deployment

    log "=============================================="
    log "Initial deployment completed successfully!"
    log "=============================================="
    log ""
    log "Next steps:"
    log "1. Create superuser: docker compose -f $COMPOSE_FILE exec web python manage.py createsuperuser"
    log "2. Set up SSL: See docs/DEPLOYMENT.md for Certbot instructions"
    log "3. Update nginx config with your domain"
    log ""
}

update_deployment() {
    log "Running update deployment..."

    pull_code
    build_images
    run_migrations
    collect_static
    restart_services
    verify_deployment

    log "=============================================="
    log "Update deployment completed successfully!"
    log "=============================================="
}

# =============================================================================
# Parse Arguments
# =============================================================================

while [[ $# -gt 0 ]]; do
    case $1 in
        --init)
            INIT_MODE=true
            shift
            ;;
        --branch)
            BRANCH="$2"
            shift 2
            ;;
        --no-pull)
            DO_PULL=false
            shift
            ;;
        --rollback)
            ROLLBACK_MODE=true
            shift
            ;;
        --help|-h)
            show_help
            ;;
        *)
            error "Unknown option: $1. Use --help for usage."
            ;;
    esac
done

# =============================================================================
# Main Execution
# =============================================================================

# Create log directory
mkdir -p "$LOG_DIR"

log "=============================================="
log "DocExtract Deployment Script"
log "=============================================="
log "Project directory: $PROJECT_DIR"
log "Compose file: $COMPOSE_FILE"
log "Branch: $BRANCH"
log "Log file: $LOG_FILE"
log ""

check_prerequisites

if [ "$ROLLBACK_MODE" = true ]; then
    rollback
elif [ "$INIT_MODE" = true ]; then
    init_deployment
else
    update_deployment
fi

log ""
log "Deployment log saved to: $LOG_FILE"