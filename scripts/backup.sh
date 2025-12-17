#!/bin/bash
# ==============================================================================
# FILE: backup.sh
# LOCATION: /docextract/scripts/backup.sh
# ==============================================================================
#
# PURPOSE:
#   Automated backup script for DocExtract production environment.
#   Creates compressed backups of PostgreSQL database and media files.
#
# USAGE:
#   Manual backup:
#       ./scripts/backup.sh
#
#   With custom retention:
#       ./scripts/backup.sh --retention 14
#
#   Database only:
#       ./scripts/backup.sh --db-only
#
#   Media only:
#       ./scripts/backup.sh --media-only
#
# OPTIONS:
#   --retention N    Keep backups for N days (default: 7)
#   --db-only        Only backup database
#   --media-only     Only backup media files
#   --output DIR     Custom output directory (default: ./backups)
#   --help           Show this help message
#
# AUTOMATED BACKUPS:
#   Add to crontab for daily backups at 3 AM:
#       crontab -e
#       0 3 * * * /home/deploy/docextract/scripts/backup.sh >> /home/deploy/logs/backup.log 2>&1
#
# BACKUP CONTENTS:
#   - db_YYYYMMDD_HHMMSS.sql.gz: PostgreSQL database dump (compressed)
#   - media_YYYYMMDD_HHMMSS.tar.gz: Media files archive
#   - env_YYYYMMDD_HHMMSS: Environment file copy (credentials backup)
#
# STORAGE RECOMMENDATIONS:
#   - Store backups on separate volume or remote storage
#   - Consider rsync to offsite location after backup
#   - Test restore procedure regularly
#
# RESTORE:
#   Use scripts/restore.sh or manually:
#       gunzip -c backup.sql.gz | docker compose exec -T db psql -U docextract docextract
#       tar -xzf media_backup.tar.gz -C /path/to/media
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
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
RETENTION_DAYS=7
BACKUP_DB=true
BACKUP_MEDIA=true

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
    head -50 "$0" | grep -E "^#" | sed 's/^# //' | sed 's/^#//'
    exit 0
}

check_prerequisites() {
    # Check Docker Compose
    if ! docker compose version &> /dev/null; then
        error "Docker Compose is not installed"
    fi

    # Check compose file exists
    if [ ! -f "$PROJECT_DIR/$COMPOSE_FILE" ]; then
        error "$COMPOSE_FILE not found in $PROJECT_DIR"
    fi

    # Check database container is running
    cd "$PROJECT_DIR"
    if ! docker compose -f "$COMPOSE_FILE" ps db | grep -q "running"; then
        error "Database container is not running"
    fi
}

backup_database() {
    log "Backing up database..."

    local backup_file="$BACKUP_DIR/db_$TIMESTAMP.sql.gz"

    cd "$PROJECT_DIR"

    # Get database credentials from .env
    if [ -f "$PROJECT_DIR/.env" ]; then
        source "$PROJECT_DIR/.env"
    fi

    DB_NAME="${POSTGRES_DB:-docextract}"
    DB_USER="${POSTGRES_USER:-docextract}"

    # Dump database and compress
    docker compose -f "$COMPOSE_FILE" exec -T db \
        pg_dump -U "$DB_USER" "$DB_NAME" \
        | gzip > "$backup_file"

    # Verify backup was created and has content
    if [ ! -s "$backup_file" ]; then
        error "Database backup file is empty or was not created"
    fi

    local size=$(du -h "$backup_file" | cut -f1)
    log "Database backup created: $backup_file ($size)"
}

backup_media() {
    log "Backing up media files..."

    local backup_file="$BACKUP_DIR/media_$TIMESTAMP.tar.gz"
    local media_dir="$PROJECT_DIR/media"

    # Check if media directory exists
    if [ ! -d "$media_dir" ]; then
        warn "Media directory does not exist: $media_dir"
        return 0
    fi

    # Check if media directory has content
    if [ -z "$(ls -A $media_dir 2>/dev/null)" ]; then
        warn "Media directory is empty, skipping media backup"
        return 0
    fi

    # Create compressed archive
    tar -czf "$backup_file" -C "$PROJECT_DIR" media/

    local size=$(du -h "$backup_file" | cut -f1)
    log "Media backup created: $backup_file ($size)"
}

backup_env() {
    log "Backing up environment file..."

    local backup_file="$BACKUP_DIR/env_$TIMESTAMP"

    if [ -f "$PROJECT_DIR/.env" ]; then
        cp "$PROJECT_DIR/.env" "$backup_file"
        # Secure the backup
        chmod 600 "$backup_file"
        log "Environment backup created: $backup_file"
    else
        warn ".env file not found, skipping environment backup"
    fi
}

cleanup_old_backups() {
    log "Cleaning up backups older than $RETENTION_DAYS days..."

    local count_before=$(find "$BACKUP_DIR" -type f \( -name "*.gz" -o -name "env_*" \) | wc -l)

    # Remove old database backups
    find "$BACKUP_DIR" -name "db_*.sql.gz" -mtime +$RETENTION_DAYS -delete 2>/dev/null || true

    # Remove old media backups
    find "$BACKUP_DIR" -name "media_*.tar.gz" -mtime +$RETENTION_DAYS -delete 2>/dev/null || true

    # Remove old environment backups
    find "$BACKUP_DIR" -name "env_*" -mtime +$RETENTION_DAYS -delete 2>/dev/null || true

    local count_after=$(find "$BACKUP_DIR" -type f \( -name "*.gz" -o -name "env_*" \) | wc -l)
    local removed=$((count_before - count_after))

    if [ $removed -gt 0 ]; then
        log "Removed $removed old backup file(s)"
    fi
}

show_summary() {
    log ""
    log "=============================================="
    log "Backup Summary"
    log "=============================================="
    log "Backup directory: $BACKUP_DIR"
    log ""
    log "Current backups:"
    ls -lh "$BACKUP_DIR"/*_$TIMESTAMP* 2>/dev/null || log "No backups created this run"
    log ""
    log "Total backup storage used:"
    du -sh "$BACKUP_DIR" 2>/dev/null || log "Unable to calculate"
    log "=============================================="
}

# =============================================================================
# Parse Arguments
# =============================================================================

while [[ $# -gt 0 ]]; do
    case $1 in
        --retention)
            RETENTION_DAYS="$2"
            shift 2
            ;;
        --db-only)
            BACKUP_DB=true
            BACKUP_MEDIA=false
            shift
            ;;
        --media-only)
            BACKUP_DB=false
            BACKUP_MEDIA=true
            shift
            ;;
        --output)
            BACKUP_DIR="$2"
            shift 2
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
log "DocExtract Backup Script"
log "=============================================="
log "Timestamp: $TIMESTAMP"
log "Retention: $RETENTION_DAYS days"
log ""

# Create backup directory
mkdir -p "$BACKUP_DIR"

# Check prerequisites
check_prerequisites

# Perform backups
if [ "$BACKUP_DB" = true ]; then
    backup_database
fi

if [ "$BACKUP_MEDIA" = true ]; then
    backup_media
fi

# Always backup environment file
backup_env

# Cleanup old backups
cleanup_old_backups

# Show summary
show_summary

log ""
log "Backup completed successfully!"