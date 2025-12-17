#!/bin/bash
# ==============================================================================
# FILE: restore.sh
# LOCATION: /docextract/scripts/restore.sh
# ==============================================================================
#
# PURPOSE:
#   Restore DocExtract from backup files. Handles database restoration
#   and media file recovery.
#
# USAGE:
#   Restore database from specific backup:
#       ./scripts/restore.sh --db backups/db_20251217_030000.sql.gz
#
#   Restore media files:
#       ./scripts/restore.sh --media backups/media_20251217_030000.tar.gz
#
#   Restore both:
#       ./scripts/restore.sh --db backups/db_backup.sql.gz --media backups/media_backup.tar.gz
#
#   List available backups:
#       ./scripts/restore.sh --list
#
# OPTIONS:
#   --db FILE        Restore database from .sql.gz file
#   --media FILE     Restore media files from .tar.gz file
#   --list           List available backups
#   --force          Skip confirmation prompts
#   --help           Show this help message
#
# WARNING:
#   Database restore will OVERWRITE existing data. Always verify you have
#   a current backup before restoring from an older one.
#
# PREREQUISITES:
#   - Docker Compose running with database container
#   - Backup files accessible
#   - Sufficient disk space for restoration
#
# ==============================================================================

set -e  # Exit on any error

# =============================================================================
# Configuration
# =============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
COMPOSE_FILE="docker-compose.prod.yml"
BACKUP_DIR="$PROJECT_DIR/backups"
DB_BACKUP=""
MEDIA_BACKUP=""
FORCE=false
LIST_MODE=false

# Colours for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Colour

# =============================================================================
# Functions
# =============================================================================

log() {
    echo -e "${GREEN}[$(date '+%Y-%m-%d %H:%M:%S')]${NC} $1"
}

warn() {
    echo -e "${YELLOW}[$(date '+%Y-%m-%d %H:%M:%S')] WARNING:${NC} $1"
}

error() {
    echo -e "${RED}[$(date '+%Y-%m-%d %H:%M:%S')] ERROR:${NC} $1"
    exit 1
}

show_help() {
    head -40 "$0" | grep -E "^#" | sed 's/^# //' | sed 's/^#//'
    exit 0
}

confirm() {
    if [ "$FORCE" = true ]; then
        return 0
    fi

    local message="$1"
    echo -e "${YELLOW}$message${NC}"
    read -p "Are you sure you want to continue? (yes/no): " response

    if [ "$response" != "yes" ]; then
        log "Operation cancelled"
        exit 0
    fi
}

list_backups() {
    log "Available backups in $BACKUP_DIR:"
    log ""

    if [ ! -d "$BACKUP_DIR" ]; then
        warn "Backup directory does not exist: $BACKUP_DIR"
        exit 0
    fi

    echo "Database backups:"
    echo "================="
    ls -lh "$BACKUP_DIR"/db_*.sql.gz 2>/dev/null || echo "  No database backups found"
    echo ""

    echo "Media backups:"
    echo "=============="
    ls -lh "$BACKUP_DIR"/media_*.tar.gz 2>/dev/null || echo "  No media backups found"
    echo ""

    echo "Environment backups:"
    echo "===================="
    ls -lh "$BACKUP_DIR"/env_* 2>/dev/null || echo "  No environment backups found"
    echo ""

    # Show total size
    if [ -d "$BACKUP_DIR" ]; then
        echo "Total backup storage: $(du -sh "$BACKUP_DIR" 2>/dev/null | cut -f1)"
    fi
}

check_prerequisites() {
    # Check Docker Compose
    if ! docker compose version &> /dev/null; then
        error "Docker Compose is not installed"
    fi

    # Check compose file exists
    if [ ! -f "$PROJECT_DIR/$COMPOSE_FILE" ]; then
        # Fall back to development compose file
        COMPOSE_FILE="docker-compose.yml"
        if [ ! -f "$PROJECT_DIR/$COMPOSE_FILE" ]; then
            error "No docker-compose file found"
        fi
    fi
}

restore_database() {
    local backup_file="$1"

    log "Restoring database from: $backup_file"

    # Verify file exists
    if [ ! -f "$backup_file" ]; then
        error "Backup file not found: $backup_file"
    fi

    # Verify file is not empty
    if [ ! -s "$backup_file" ]; then
        error "Backup file is empty: $backup_file"
    fi

    # Get file size
    local size=$(du -h "$backup_file" | cut -f1)
    log "Backup file size: $size"

    # Confirm restoration
    confirm "This will OVERWRITE all existing database data!"

    cd "$PROJECT_DIR"

    # Get database credentials from .env
    if [ -f "$PROJECT_DIR/.env" ]; then
        source "$PROJECT_DIR/.env"
    fi

    DB_NAME="${POSTGRES_DB:-docextract}"
    DB_USER="${POSTGRES_USER:-docextract}"

    # Check database container is running
    if ! docker compose -f "$COMPOSE_FILE" ps db 2>/dev/null | grep -q "running"; then
        log "Starting database container..."
        docker compose -f "$COMPOSE_FILE" up -d db
        sleep 10
    fi

    log "Dropping existing database..."
    docker compose -f "$COMPOSE_FILE" exec -T db \
        psql -U "$DB_USER" -d postgres -c "DROP DATABASE IF EXISTS $DB_NAME;" 2>/dev/null || true

    log "Creating fresh database..."
    docker compose -f "$COMPOSE_FILE" exec -T db \
        psql -U "$DB_USER" -d postgres -c "CREATE DATABASE $DB_NAME OWNER $DB_USER;"

    log "Restoring from backup..."
    gunzip -c "$backup_file" | docker compose -f "$COMPOSE_FILE" exec -T db \
        psql -U "$DB_USER" -d "$DB_NAME"

    log "Database restored successfully!"

    # Run migrations to ensure schema is up to date
    log "Running migrations to ensure schema consistency..."
    docker compose -f "$COMPOSE_FILE" exec -T web python manage.py migrate --noinput 2>/dev/null || \
        warn "Could not run migrations. Run manually: docker compose exec web python manage.py migrate"
}

restore_media() {
    local backup_file="$1"

    log "Restoring media files from: $backup_file"

    # Verify file exists
    if [ ! -f "$backup_file" ]; then
        error "Backup file not found: $backup_file"
    fi

    # Verify file is not empty
    if [ ! -s "$backup_file" ]; then
        error "Backup file is empty: $backup_file"
    fi

    # Get file size
    local size=$(du -h "$backup_file" | cut -f1)
    log "Backup file size: $size"

    # Confirm restoration
    confirm "This will OVERWRITE existing media files!"

    local media_dir="$PROJECT_DIR/media"

    # Create backup of current media if it exists
    if [ -d "$media_dir" ] && [ "$(ls -A $media_dir 2>/dev/null)" ]; then
        local current_backup="$BACKUP_DIR/media_pre_restore_$(date +%Y%m%d_%H%M%S).tar.gz"
        log "Backing up current media to: $current_backup"
        tar -czf "$current_backup" -C "$PROJECT_DIR" media/
    fi

    # Clear existing media
    log "Clearing existing media directory..."
    rm -rf "$media_dir"/*

    # Extract backup
    log "Extracting media files..."
    tar -xzf "$backup_file" -C "$PROJECT_DIR"

    # Fix permissions
    log "Fixing permissions..."
    chown -R 1000:1000 "$media_dir" 2>/dev/null || true

    log "Media files restored successfully!"
}

# =============================================================================
# Parse Arguments
# =============================================================================

while [[ $# -gt 0 ]]; do
    case $1 in
        --db)
            DB_BACKUP="$2"
            shift 2
            ;;
        --media)
            MEDIA_BACKUP="$2"
            shift 2
            ;;
        --list)
            LIST_MODE=true
            shift
            ;;
        --force)
            FORCE=true
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

log "=============================================="
log "DocExtract Restore Script"
log "=============================================="

if [ "$LIST_MODE" = true ]; then
    list_backups
    exit 0
fi

if [ -z "$DB_BACKUP" ] && [ -z "$MEDIA_BACKUP" ]; then
    error "No backup specified. Use --db FILE and/or --media FILE, or --list to see available backups."
fi

check_prerequisites

# Create backup directory if it doesn't exist
mkdir -p "$BACKUP_DIR"

if [ -n "$DB_BACKUP" ]; then
    restore_database "$DB_BACKUP"
fi

if [ -n "$MEDIA_BACKUP" ]; then
    restore_media "$MEDIA_BACKUP"
fi

log ""
log "=============================================="
log "Restore completed!"
log "=============================================="
log ""
log "Recommended next steps:"
log "1. Verify data integrity by checking the application"
log "2. Run: docker compose -f $COMPOSE_FILE exec web python manage.py check"
log "3. If needed, restart services: docker compose -f $COMPOSE_FILE restart"